"""Outside services, behind one shape.

Seven of these were asked for and there will be an eighth. Written as seven
modules they become seven ways to store a credential, seven opinions about
what "connected" means, and seven screens to keep in step. So a provider here
is a table entry: what it needs to connect, how to check the connection is
real, and what it does when something happens in the business. The screen is
generated from that, which is why adding one is a dozen lines rather than a
feature.

The parts that are the same for everyone are done once, in here:

  Credentials go in and never come out. The API returns whether a provider is
  connected and which account it landed on — never the token. A screen that
  can display a credential leaks it to whoever is standing behind you.

  Connecting tests the credential immediately. Storing an unverified token
  means the first thing to discover it's wrong is an order that silently
  fails to reach your accountant a week later.

  Events fan out off-thread and failures are logged, not raised. Trello being
  down must never fail an order — the order is the business, the card is a
  convenience.

Two honest limits, stated here rather than discovered later:

  The OAuth providers (Dropbox, QuickBooks, Canva) need an app you register
  yourself, because the client secret belongs to your company, not to this
  software. Paste the client id and secret, then click connect and approve.

  LaceUp has no public API to write against. What it does have is order
  files, so that one is an inbound route — a signed endpoint it can POST to
  and a CSV import — rather than an outbound client pretending to be more.
"""
import base64
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException
from pydantic import BaseModel

from . import db

TABLES = """
CREATE TABLE IF NOT EXISTS integrations (
  provider TEXT PRIMARY KEY,
  credentials TEXT NOT NULL DEFAULT '{}',   -- secret; never returned
  account TEXT DEFAULT '',                  -- which workspace/company it hit
  settings TEXT DEFAULT '{}',               -- per-provider, non-secret
  active INTEGER DEFAULT 1,
  connected_at REAL NOT NULL,
  expires_at REAL DEFAULT 0                 -- OAuth access token expiry
);

CREATE TABLE IF NOT EXISTS integration_log (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  event TEXT DEFAULT '',
  ok INTEGER DEFAULT 0,
  detail TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS integration_log_time
  ON integration_log(created_at DESC);

/* An inbound key, for services that push to us rather than the other way
   round. Separate from the outbound credential because it is the opposite
   direction of trust: this one we issue, and we can rotate it without
   asking anybody. */
/* What we made over there, and for what over here.

   Without this row an integration is write-only by construction: a card
   exists in Trello and a deal in Pipedrive, and nothing in this database
   knows which enquiry either belongs to, so whatever happens to them later
   can never come back. It is the whole difference between pushing and
   syncing. */
CREATE TABLE IF NOT EXISTS integration_links (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL,                       -- enquiry | ticket
  local_id INTEGER NOT NULL,
  remote_id TEXT NOT NULL,
  remote_url TEXT DEFAULT '',
  remote_state TEXT DEFAULT '',             -- as last seen over there
  applied TEXT DEFAULT '',                  -- what we did about it
  created_at REAL NOT NULL,
  synced_at REAL DEFAULT 0,
  UNIQUE(provider, kind, local_id)
);

CREATE TABLE IF NOT EXISTS integration_inbound (
  provider TEXT PRIMARY KEY,
  key TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen REAL DEFAULT 0,
  received INTEGER DEFAULT 0
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ---------- the registry ----------
#
# `fields` are what the person has to supply. `secret` fields are stored and
# never returned. `events` are the business events this provider reacts to.

PROVIDERS = {
    "slack": {
        "label": "Slack",
        "blurb": "Post what happens in the business into a channel — and "
                 "read and reply without leaving.",
        "auth": "webhook",
        # A webhook is a one-way pipe: it can post and can never read. So the
        # bot token is a second, optional step, exactly as it is for Discord
        # — connect only the webhook and the alerts still work.
        "chat": True,
        "fields": [
            {"k": "webhook_url", "label": "Incoming webhook URL",
             "secret": True,
             "hint": "Slack → Apps → Incoming Webhooks → Add to Workspace, "
                     "then copy the URL for the channel."},
            {"k": "bot_token", "label": "Bot token (optional)",
             "secret": True, "optional": True,
             "hint": "Starts xoxb-. Needed only to read channels and reply "
                     "from here; add the scopes channels:read, "
                     "channels:history and chat:write to your app."},
        ],
        "events": ["order.created", "enquiry.created", "ticket.created",
                   "inventory.low", "document.signed"],
        "does": "Sends a line to the channel when an order lands, stock runs "
                "low, a partner enquires, a ticket opens or a document is "
                "signed. With a bot token it also reads the channels and "
                "lets you reply from here.",
    },
    "trello": {
        "label": "Trello",
        "blurb": "Turn things that need doing into cards.",
        "auth": "key_token",
        "fields": [
            {"k": "api_key", "label": "API key", "secret": True,
             "hint": "From trello.com/power-ups/admin — your key."},
            {"k": "token", "label": "Token", "secret": True,
             "hint": "The token you get after authorising that key."},
            {"k": "list_id", "label": "List ID", "secret": False,
             "hint": "The list new cards land in. Open a board, add .json to "
                     "the URL, and find the id of the list you want."},
        ],
        "events": ["enquiry.created", "ticket.created", "inventory.low"],
        "syncs": True,
        "does": "Creates a card for each new enquiry, support ticket or "
                "low-stock warning, so the work sits where the team looks — "
                "and reads back where each card has got to, so a thing done "
                "on the board stops sitting in the list here.",
    },
    "pipedrive": {
        "label": "Pipedrive",
        "blurb": "Push partner enquiries into the sales pipeline.",
        "auth": "api_token",
        "fields": [
            {"k": "api_token", "label": "API token", "secret": True,
             "hint": "Pipedrive → personal preferences → API."},
            {"k": "domain", "label": "Company domain", "secret": False,
             "hint": "The bit before .pipedrive.com in your URL."},
        ],
        "events": ["enquiry.created"],
        "syncs": True,
        "does": "Creates a person and a deal for every wholesale, "
                "distribution or partnership enquiry, so nothing sits in an "
                "inbox — and reads the deal back, so one won or lost in the "
                "pipeline closes here too.",
    },
    "dropbox": {
        "label": "Dropbox",
        "blurb": "Keep signed documents and exports somewhere shared.",
        "auth": "oauth2",
        "oauth": {
            "authorize": "https://www.dropbox.com/oauth2/authorize",
            "token": "https://api.dropboxapi.com/oauth2/token",
            "scope": "files.content.write files.content.read account_info.read",
            "extra_auth": {"token_access_type": "offline"},
        },
        "fields": [],
        "events": ["document.signed"],
        "does": "Files a copy of each signed document, and gives the "
                "database export somewhere to land that isn't one laptop.",
    },
    "quickbooks": {
        "label": "QuickBooks",
        "blurb": "Send sales through to the books.",
        "auth": "oauth2",
        "oauth": {
            "authorize": "https://appcenter.intuit.com/connect/oauth2",
            "token": "https://oauth.platform.intuit.com/oauth2/v1/tokens/"
                     "bearer",
            "scope": "com.intuit.quickbooks.accounting",
        },
        "fields": [],
        "events": ["order.paid"],
        "does": "Records a paid order as a sales receipt against the "
                "customer, so the month doesn't end with a re-typing session.",
    },
    "canva": {
        "label": "Canva",
        "blurb": "Pull finished artwork straight into the store.",
        "auth": "oauth2",
        "oauth": {
            "authorize": "https://www.canva.com/api/oauth/authorize",
            "token": "https://api.canva.com/rest/v1/oauth/token",
            "scope": "design:meta:read asset:read",
        },
        "fields": [],
        "events": [],
        "does": "Lists your designs so a finished label or campaign image "
                "can be brought in as product media without a download-and-"
                "upload round trip.",
    },
    "laceup": {
        "label": "LaceUp",
        "blurb": "Take orders written on the van.",
        "auth": "inbound",
        "fields": [],
        "events": [],
        "does": "Receives orders LaceUp sends, and imports an order CSV. "
                "Inbound rather than outbound because LaceUp publishes no "
                "API to call — this is the direction that actually exists.",
    },
}

# Events any provider may care about. Kept here so the screen can explain
# what a connection will actually do.
EVENT_LABELS = {
    "order.created": "an order is placed",
    "order.paid": "an order is paid",
    "enquiry.created": "a partner enquiry arrives",
    "ticket.created": "a support ticket opens",
    "inventory.low": "stock drops below par",
    "document.signed": "a document is signed",
}


def provider(name: str) -> dict:
    p = PROVIDERS.get(name)
    if p is None:
        raise HTTPException(404, f"no integration called {name!r}")
    return p


# ---------- HTTP ----------

def _req(url: str, method: str = "GET", headers: dict | None = None,
         body: bytes | None = None, timeout: int = 15):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "null"
            try:
                return True, json.loads(raw)
            except ValueError:
                return True, raw
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        return False, f"{e.code}: {detail or e.reason}"
    except Exception as e:                              # noqa: BLE001
        return False, str(e)[:200]


def _json_req(url, method="GET", headers=None, payload=None, timeout=15):
    h = {"Content-Type": "application/json", **(headers or {})}
    body = json.dumps(payload).encode() if payload is not None else None
    return _req(url, method, h, body, timeout)


# ---------- storage ----------

def creds(con, name: str) -> dict:
    row = con.execute("SELECT * FROM integrations WHERE provider=?",
                      (name,)).fetchone()
    if row is None or not row["active"]:
        return {}
    try:
        return json.loads(row["credentials"] or "{}")
    except Exception:
        return {}


def settings(con, name: str) -> dict:
    row = con.execute("SELECT settings FROM integrations WHERE provider=?",
                      (name,)).fetchone()
    try:
        return json.loads(row["settings"]) if row else {}
    except Exception:
        return {}


def save(con, name: str, credentials: dict, account: str = "",
         setting: dict | None = None, expires_at: float = 0) -> None:
    con.execute(
        "INSERT INTO integrations(provider,credentials,account,settings,"
        " active,connected_at,expires_at) VALUES(?,?,?,?,1,?,?)"
        " ON CONFLICT(provider) DO UPDATE SET credentials=excluded.credentials,"
        " account=excluded.account, settings=excluded.settings, active=1,"
        " connected_at=excluded.connected_at, expires_at=excluded.expires_at",
        (name, json.dumps(credentials), account[:120],
         json.dumps(setting or {}), time.time(), expires_at))
    con.commit()


KIND_FOR_EVENT = {"enquiry.created": "enquiry", "ticket.created": "ticket"}


def link(con, provider_name: str, kind: str, local_id, remote_id: str,
         url: str = "") -> None:
    if not local_id or not remote_id:
        return
    con.execute(
        "INSERT INTO integration_links(provider,kind,local_id,remote_id,"
        " remote_url,created_at) VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(provider,kind,local_id) DO UPDATE SET"
        " remote_id=excluded.remote_id, remote_url=excluded.remote_url",
        (provider_name, kind, int(local_id), str(remote_id), url, time.time()))
    con.commit()


def log(con, name: str, event: str, ok: bool, detail: str = "") -> None:
    try:
        con.execute(
            "INSERT INTO integration_log(provider,event,ok,detail,created_at)"
            " VALUES(?,?,?,?,?)", (name, event, 1 if ok else 0,
                                   str(detail)[:400], time.time()))
        con.commit()
    except Exception:
        pass


def status(con) -> dict:
    """What the screen shows. Deliberately without a single credential in it:
    connected or not, which account, and how it has been behaving."""
    rows = {r["provider"]: r for r in con.execute(
        "SELECT provider, account, active, connected_at, expires_at"
        " FROM integrations").fetchall()}
    inbound = {r["provider"]: r for r in con.execute(
        "SELECT * FROM integration_inbound").fetchall()}
    out = []
    for name, p in PROVIDERS.items():
        r = rows.get(name)
        i = inbound.get(name)
        out.append({
            "name": name, "label": p["label"], "blurb": p["blurb"],
            "auth": p["auth"], "does": p["does"],
            "fields": [{k: v for k, v in f.items()} for f in p["fields"]],
            "events": [EVENT_LABELS.get(e, e) for e in p["events"]],
            "syncs": bool(p.get("syncs")),
            "connected": bool(r and r["active"]),
            "account": r["account"] if r else "",
            "connected_at": r["connected_at"] if r else 0,
            "inbound_ready": bool(i),
            "received": i["received"] if i else 0,
        })
    recent = [dict(r) for r in con.execute(
        "SELECT * FROM integration_log ORDER BY id DESC LIMIT 40").fetchall()]
    return {"providers": out, "log": recent,
            "events": EVENT_LABELS}


# ---------- connecting ----------

def connect(con, name: str, fields: dict) -> dict:
    """Store a credential, but only after proving it works."""
    p = provider(name)
    if p["auth"] == "oauth2":
        raise HTTPException(
            400, f"{p['label']} connects by approving access, not by pasting "
                 "a token — use the connect link")
    if p["auth"] == "inbound":
        raise HTTPException(
            400, f"{p['label']} sends data to us; generate its key instead")

    supplied = {}
    for f in p["fields"]:
        v = str(fields.get(f["k"], "")).strip()
        if not v:
            if f.get("optional"):
                continue
            raise HTTPException(400, f"{f['label']} is needed")
        supplied[f["k"]] = v

    ok, detail = check(name, supplied)
    if not ok:
        raise HTTPException(400, f"{p['label']} rejected that: {detail}")
    account = detail if isinstance(detail, str) else ""
    secret_keys = {f["k"] for f in p["fields"] if f.get("secret")}
    save(con, name, {k: v for k, v in supplied.items() if k in secret_keys},
         account,
         {k: v for k, v in supplied.items() if k not in secret_keys})
    log(con, name, "connect", True, account)
    return {"ok": True, "account": account}


def check(name: str, c: dict) -> tuple:
    """Ask the service whether these credentials are real. Returns
    (ok, account-or-error)."""
    if name == "slack":
        url = c.get("webhook_url", "")
        if not url.startswith("https://hooks.slack.com/"):
            return False, ("that isn't a Slack webhook URL — it starts "
                           "https://hooks.slack.com/")
        ok, d = _json_req(url, "POST", payload={
            "text": "Business Control is connected to this channel."})
        if not ok:
            return False, str(d)
        tok = c.get("bot_token", "")
        if not tok:
            return True, "channel verified"
        if not tok.startswith("xoxb-"):
            return False, ("a bot token starts xoxb- — xoxp- is a user "
                           "token and won't have the app's scopes")
        ok2, d2 = _slack(tok, "auth.test")
        if not ok2:
            return False, f"the bot token was refused: {d2}"
        return True, f"{d2.get('team', 'workspace')} · reading and replying"

    if name == "trello":
        q = urllib.parse.urlencode({"key": c.get("api_key", ""),
                                    "token": c.get("token", "")})
        ok, d = _req(f"https://api.trello.com/1/members/me?{q}")
        if not ok:
            return False, str(d)
        # A list that doesn't exist fails at the first card, not here, so
        # check it now while someone is watching.
        lid = c.get("list_id", "")
        ok2, d2 = _req(f"https://api.trello.com/1/lists/{lid}?{q}")
        if not ok2:
            return False, f"the list id doesn't resolve ({d2})"
        board = d2.get("name", "list") if isinstance(d2, dict) else "list"
        who = d.get("username", "") if isinstance(d, dict) else ""
        return True, f"{who} → {board}"

    if name == "pipedrive":
        dom = c.get("domain", "").replace(".pipedrive.com", "").strip("/")
        ok, d = _req(f"https://{dom}.pipedrive.com/api/v1/users/me"
                     f"?api_token={urllib.parse.quote(c.get('api_token',''))}")
        if not ok:
            return False, str(d)
        data = d.get("data", {}) if isinstance(d, dict) else {}
        return True, data.get("company_name") or data.get("name") or dom

    return False, "no check for that provider"


def verify(con, name: str, cfg: dict) -> tuple:
    """Ask a connected provider whether it still works.

    Worth its own action because OAuth connections rot quietly — a refresh
    token is revoked in someone else's admin panel and nothing here notices
    until an order fails to post weeks later.
    """
    p = provider(name)
    c = creds(con, name)
    if not c:
        return False, "not connected"
    if p["auth"] in ("webhook", "key_token", "api_token"):
        merged = {**c, **settings(con, name)}
        return check(name, merged)
    tok = access_token(con, name, cfg)
    if not tok:
        return False, "no usable token — reconnect"
    if name == "dropbox":
        ok, d = _req("https://api.dropboxapi.com/2/users/get_current_account",
                     "POST", {"Authorization": f"Bearer {tok}",
                              "Content-Type": "application/json"}, b"null")
        if ok and isinstance(d, dict):
            return True, (d.get("name", {}) or {}).get("display_name", "ok")
        return False, str(d)
    if name == "canva":
        ok, d = _req("https://api.canva.com/rest/v1/users/me",
                     headers={"Authorization": f"Bearer {tok}"})
        return (True, "ok") if ok else (False, str(d))
    if name == "quickbooks":
        realm = settings(con, name).get("realm_id", "")
        if not realm:
            return False, "no company id — reconnect"
        ok, d = _req(
            f"https://quickbooks.api.intuit.com/v3/company/{realm}"
            "/companyinfo/" + realm + "?minorversion=70",
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/json"})
        if ok and isinstance(d, dict):
            info = (d.get("CompanyInfo") or {})
            return True, info.get("CompanyName", realm)
        return False, str(d)
    return False, "no check for that provider"


def disconnect(con, name: str) -> dict:
    provider(name)
    con.execute("DELETE FROM integrations WHERE provider=?", (name,))
    con.commit()
    log(con, name, "disconnect", True)
    return {"ok": True}


# ---------- OAuth ----------

def oauth_url(con, name: str, cfg: dict, redirect: str, state: str) -> str:
    p = provider(name)
    if p["auth"] != "oauth2":
        raise HTTPException(400, f"{p['label']} doesn't use OAuth")
    app = (cfg.get("integration_apps") or {}).get(name) or {}
    if not app.get("client_id"):
        raise HTTPException(
            400, f"register an app with {p['label']} first and save its "
                 "client id and secret — the secret belongs to your company, "
                 "not to this software, so it can't be shipped with it")
    q = {"client_id": app["client_id"], "response_type": "code",
         "redirect_uri": redirect, "state": state,
         "scope": p["oauth"]["scope"], **p["oauth"].get("extra_auth", {})}
    return p["oauth"]["authorize"] + "?" + urllib.parse.urlencode(q)


def oauth_exchange(con, name: str, cfg: dict, code: str, redirect: str,
                   extra: dict | None = None) -> dict:
    p = provider(name)
    app = (cfg.get("integration_apps") or {}).get(name) or {}
    basic = base64.b64encode(
        f"{app.get('client_id','')}:{app.get('client_secret','')}".encode()
    ).decode()
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect}).encode()
    ok, d = _req(p["oauth"]["token"], "POST",
                 {"Authorization": f"Basic {basic}",
                  "Content-Type": "application/x-www-form-urlencoded",
                  "Accept": "application/json"}, body)
    if not ok or not isinstance(d, dict) or not d.get("access_token"):
        raise HTTPException(400, f"{p['label']} wouldn't issue a token: {d}")
    expires = time.time() + int(d.get("expires_in") or 3600) - 60
    # QuickBooks identifies the company on the callback rather than in the
    # token response, and every later call needs it — so it is kept, not
    # just displayed. Without it a connected QuickBooks can't post anywhere.
    setting = {}
    realm = (extra or {}).get("realmId") or d.get("realmId")
    if realm:
        setting["realm_id"] = str(realm)
    account = str(realm or d.get("account_id") or p["label"])
    save(con, name,
         {"access_token": d["access_token"],
          "refresh_token": d.get("refresh_token", "")},
         account, setting, expires)
    log(con, name, "oauth", True, account)
    return {"ok": True, "account": account}


def access_token(con, name: str, cfg: dict) -> str:
    """A usable token, refreshed if the stored one has expired.

    Refreshing here rather than at each call site means an integration that
    is used once a month works as reliably as one used hourly — the failure
    mode of forgetting is a token that silently expired weeks ago.
    """
    row = con.execute("SELECT * FROM integrations WHERE provider=? AND"
                      " active=1", (name,)).fetchone()
    if row is None:
        raise HTTPException(400, f"{name} isn't connected")
    c = json.loads(row["credentials"] or "{}")
    if row["expires_at"] and row["expires_at"] > time.time():
        return c.get("access_token", "")
    if not c.get("refresh_token"):
        return c.get("access_token", "")
    p = provider(name)
    app = (cfg.get("integration_apps") or {}).get(name) or {}
    basic = base64.b64encode(
        f"{app.get('client_id','')}:{app.get('client_secret','')}".encode()
    ).decode()
    ok, d = _req(p["oauth"]["token"], "POST",
                 {"Authorization": f"Basic {basic}",
                  "Content-Type": "application/x-www-form-urlencoded",
                  "Accept": "application/json"},
                 urllib.parse.urlencode({
                     "grant_type": "refresh_token",
                     "refresh_token": c["refresh_token"]}).encode())
    if ok and isinstance(d, dict) and d.get("access_token"):
        c["access_token"] = d["access_token"]
        if d.get("refresh_token"):
            c["refresh_token"] = d["refresh_token"]
        con.execute(
            "UPDATE integrations SET credentials=?, expires_at=?"
            " WHERE provider=?",
            (json.dumps(c), time.time() + int(d.get("expires_in") or 3600) - 60,
             name))
        con.commit()
        return c["access_token"]
    log(con, name, "refresh", False, str(d))
    return c.get("access_token", "")


# ---------- inbound ----------

def inbound_key(con, name: str, rotate: bool = False) -> str:
    p = provider(name)
    if p["auth"] != "inbound":
        raise HTTPException(400, f"{p['label']} doesn't receive data")
    row = con.execute("SELECT key FROM integration_inbound WHERE provider=?",
                      (name,)).fetchone()
    if row and not rotate:
        return row["key"]
    key = secrets.token_urlsafe(28)
    con.execute(
        "INSERT INTO integration_inbound(provider,key,created_at)"
        " VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET key=excluded.key,"
        " created_at=excluded.created_at", (name, key, time.time()))
    con.commit()
    return key


def check_inbound(con, name: str, key: str):
    row = con.execute("SELECT * FROM integration_inbound WHERE provider=?",
                      (name,)).fetchone()
    if row is None or not key or key != row["key"]:
        raise HTTPException(401, "that key isn't recognised")
    con.execute(
        "UPDATE integration_inbound SET last_seen=?, received=received+1"
        " WHERE provider=?", (time.time(), name))
    con.commit()
    return row


# ---------- reacting to the business ----------

def emit(event: str, payload: dict) -> None:
    """Tell whoever is listening. Off-thread and swallowing errors: an
    integration being down must never fail the thing it was reporting."""
    def run():
        con = db.connect()
        try:
            for name, p in PROVIDERS.items():
                if event not in p["events"]:
                    continue
                c = creds(con, name)
                if not c:
                    continue
                try:
                    ok, detail = _deliver(con, name, event, payload, c)
                except Exception as e:                  # noqa: BLE001
                    ok, detail = False, str(e)[:200]
                log(con, name, event, ok, detail)
        except Exception:
            pass
        finally:
            con.close()
    threading.Thread(target=run, daemon=True).start()


def _line(event: str, d: dict) -> str:
    """One sentence describing what happened, for the providers that want
    prose rather than fields."""
    if event == "order.created":
        return (f"New order #{d.get('id','')} — {d.get('total','')}"
                f" from {d.get('customer', 'a customer')}")
    if event == "inventory.low":
        return (f"{d.get('product','Something')} is low at "
                f"{d.get('store','a store')}: {d.get('qty','?')} left")
    if event == "enquiry.created":
        return (f"New {d.get('kind','partner')} enquiry from "
                f"{d.get('company','someone')}")
    if event == "ticket.created":
        return f"Support ticket {d.get('ref','')} — {d.get('topic','')}"
    if event == "document.signed":
        return f"{d.get('title','A document')} was signed by " \
               f"{d.get('signer','someone')}"
    return f"{event}: {json.dumps(d)[:200]}"


def _document_bytes(con, doc_id) -> tuple:
    """The uploaded file for a document, if it has one."""
    if not doc_id:
        return None, ""
    try:
        row = con.execute("SELECT ext FROM documents WHERE id=?",
                          (doc_id,)).fetchone()
        if row is None or not row["ext"]:
            return None, ""
        from storefront.backend import config as sconfig
        f = sconfig.DATA_DIR / "uploads" / "documents" / \
            f"{doc_id}.{row['ext']}"
        return (f.read_bytes(), row["ext"]) if f.exists() else (None, "")
    except Exception:
        return None, ""


def _deliver(con, name: str, event: str, d: dict, c: dict) -> tuple:
    text = _line(event, d)

    if name == "slack":
        return _json_req(c["webhook_url"], "POST", payload={"text": text})

    if name == "trello":
        s = settings(con, name)
        q = urllib.parse.urlencode({
            "key": c.get("api_key", ""), "token": c.get("token", ""),
            "idList": s.get("list_id", ""), "name": text[:200],
            "desc": json.dumps(d, indent=1)[:2000]})
        ok, card = _req(f"https://api.trello.com/1/cards?{q}", "POST")
        if ok and isinstance(card, dict):
            link(con, name, KIND_FOR_EVENT.get(event, event), d.get("id"),
                 card.get("id", ""), card.get("shortUrl", ""))
        return ok, card

    if name == "pipedrive":
        s = settings(con, name)
        dom = s.get("domain", "").replace(".pipedrive.com", "").strip("/")
        tok = urllib.parse.quote(c.get("api_token", ""))
        base = f"https://{dom}.pipedrive.com/api/v1"
        person = {"name": d.get("company") or d.get("customer") or "Enquiry",
                  "email": [d.get("email", "")] if d.get("email") else []}
        ok, pd = _json_req(f"{base}/persons?api_token={tok}", "POST",
                           payload=person)
        pid = (pd.get("data", {}) or {}).get("id") if ok and isinstance(
            pd, dict) else None
        deal = {"title": text[:200]}
        if pid:
            deal["person_id"] = pid
        ok, dd = _json_req(f"{base}/deals?api_token={tok}", "POST",
                           payload=deal)
        if ok and isinstance(dd, dict):
            did = (dd.get("data", {}) or {}).get("id")
            link(con, name, KIND_FOR_EVENT.get(event, event), d.get("id"),
                 did, f"https://{dom}.pipedrive.com/deal/{did}" if did else "")
        return ok, dd

    if name == "quickbooks":
        # A sales receipt rather than an invoice: the money has already been
        # taken, and recording an invoice for a paid order leaves the
        # accountant reconciling something that was never owed.
        s = settings(con, name)
        realm = s.get("realm_id") or ""
        if not realm:
            return False, ("no company id — reconnect QuickBooks so it can "
                           "record which company to post to")
        base = ("https://quickbooks.api.intuit.com/v3/company/"
                f"{realm}/salesreceipt?minorversion=70")
        lines = [{
            "Amount": round((it.get("qty", 1)
                             * it.get("unit_price_cents", 0)) / 100, 2),
            "DetailType": "SalesItemLineDetail",
            "Description": f"{it.get('name','')} ({it.get('sku','')}) "
                           f"x{it.get('qty',1)}",
            "SalesItemLineDetail": {"Qty": it.get("qty", 1)},
        } for it in (d.get("items") or [])]
        if not lines:
            lines = [{"Amount": round((d.get("total_cents") or 0) / 100, 2),
                      "DetailType": "SalesItemLineDetail",
                      "Description": f"Order #{d.get('id','')}",
                      "SalesItemLineDetail": {"Qty": 1}}]
        payload = {"Line": lines,
                   "PrivateNote": f"Business Control order #{d.get('id','')}",
                   "CustomerMemo": {"value": d.get("customer", "")}}
        if d.get("email"):
            payload["BillEmail"] = {"Address": d["email"]}
        return _json_req(base, "POST", {
            "Authorization": f"Bearer {c.get('access_token','')}",
            "Accept": "application/json"}, payload)

    if name == "dropbox":
        # Only documents are filed; an order is a row in a database and there
        # is nothing useful to put in a folder for it.
        if event != "document.signed":
            return True, "nothing to file"
        # The document itself where there is a file, and the signature record
        # beside it either way — a folder holding a summary of a contract,
        # and not the contract, is the wrong half.
        blob, ext = _document_bytes(con, d.get("id"))
        stem = f"/business-control/signed/{d.get('id', 'doc')}"
        ok, detail = _req(
            "https://content.dropboxapi.com/2/files/upload", "POST",
            {"Authorization": f"Bearer {c.get('access_token','')}",
             "Dropbox-API-Arg": json.dumps(
                 {"path": f"{stem}-signatures.json", "mode": "overwrite",
                  "mute": True}),
             "Content-Type": "application/octet-stream"},
            json.dumps(d, indent=1).encode())
        if blob:
            ok2, detail2 = _req(
                "https://content.dropboxapi.com/2/files/upload", "POST",
                {"Authorization": f"Bearer {c.get('access_token','')}",
                 "Dropbox-API-Arg": json.dumps(
                     {"path": f"{stem}.{ext}", "mode": "overwrite",
                      "mute": True}),
                 "Content-Type": "application/octet-stream"}, blob)
            return ok and ok2, f"{detail2 if not ok2 else 'filed with the file'}"
        return ok, "filed (no attachment on the document)"

    return True, "connected, nothing to send for this event"


# ---------- Slack, in both directions ----------
#
# The webhook posts and can never read; that is what a webhook is. Reading a
# channel or answering in it needs a bot token, so it stays optional and
# separate — the same shape as Discord, and for the same reason: most people
# want the alerts and nothing else, and should not have to create an app to
# get them.

SLACK_API = "https://slack.com/api"


def _slack(token: str, method: str, payload: dict | None = None) -> tuple:
    """One place for every Slack call.

    Slack answers 200 with {"ok": false, "error": "..."} rather than an HTTP
    error, so a naive caller treats every failure as a success. Unwrapping it
    here means no call site can make that mistake.
    """
    if payload is None:
        ok, d = _req(f"{SLACK_API}/{method}",
                     headers={"Authorization": f"Bearer {token}"})
    else:
        ok, d = _json_req(f"{SLACK_API}/{method}", "POST",
                          {"Authorization": f"Bearer {token}"}, payload)
    if not ok:
        return False, str(d)
    if not isinstance(d, dict):
        return False, str(d)[:200]
    if not d.get("ok"):
        return False, d.get("error", "slack said no")
    return True, d


def slack_token(con) -> str:
    tok = creds(con, "slack").get("bot_token", "")
    if not tok:
        raise HTTPException(
            400, "Slack is posting alerts but can't read: add a bot token to "
                 "the Slack integration to read channels and reply")
    return tok


def slack_channels(con) -> dict:
    tok = slack_token(con)
    ok, d = _slack(tok, "conversations.list?types=public_channel,"
                        "private_channel&limit=200&exclude_archived=true")
    if not ok:
        return {"error": d, "channels": []}
    chans = [{"id": c["id"], "name": c["name"],
              "member": bool(c.get("is_member")),
              "topic": (c.get("topic", {}) or {}).get("value", "")[:160]}
             for c in d.get("channels", [])]
    # A channel the bot hasn't been invited to can be listed but not read,
    # so say which those are rather than letting them fail on selection.
    chans.sort(key=lambda c: (not c["member"], c["name"]))
    return {"channels": chans}


def slack_messages(con, channel: str, limit: int = 40) -> dict:
    tok = slack_token(con)
    ok, d = _slack(tok, f"conversations.history?channel="
                        f"{urllib.parse.quote(channel)}&limit={min(limit,100)}")
    if not ok:
        if d == "not_in_channel":
            return {"error": "the bot isn't in that channel — invite it with "
                             "/invite in Slack, then try again",
                    "messages": []}
        return {"error": d, "messages": []}
    names = {}
    out = []
    for m in reversed(d.get("messages", [])):
        uid = m.get("user") or m.get("bot_id") or ""
        if uid and uid not in names:
            okp, prof = _slack(tok, f"users.info?user={uid}")
            names[uid] = (prof.get("user", {}).get("real_name")
                          or prof.get("user", {}).get("name")
                          or "someone") if okp else uid
        out.append({"id": m.get("ts", ""),
                    "author": names.get(uid, "someone"),
                    "bot": bool(m.get("bot_id")),
                    "content": m.get("text", ""),
                    "at": float(m.get("ts", 0) or 0)})
    return {"messages": out}


def slack_send(con, channel: str, text: str, who: str) -> dict:
    tok = slack_token(con)
    # Attributed to the person, as in the Discord reader: a message from
    # "the business" that nobody can trace back is worse than none.
    ok, d = _slack(tok, "chat.postMessage",
                   {"channel": channel, "text": f"*{who}:* {text[:2900]}"})
    if not ok:
        raise HTTPException(400, f"Slack refused that: {d}")
    return {"ok": True, "ts": d.get("ts", "")}


# ---------- reading state back ----------
#
# A one-way integration becomes a stale copy: cards get done and deals get
# won over there, and nothing here ever hears. Six weeks in, the enquiry list
# is full of things somebody dealt with a month ago.
#
# The rule for reconciling the two is deliberately narrow. The remote may
# *advance* a record — say it has been picked up, or that it is finished —
# and may never reopen one that was closed here. Anything else needs a
# genuine answer to "which side is right", and a sync that guesses wrong
# resurrects work people have already done.

LOCAL_TABLE = {"enquiry": ("store_enquiries", ("new", "contacted", "closed")),
               "ticket": ("support_tickets", ("open", "waiting", "closed"))}


def _advance(con, kind: str, local_id: int, to: str) -> str:
    """Move a local record forward, never back. Returns what happened."""
    table, order = LOCAL_TABLE.get(kind, (None, ()))
    if not table or to not in order:
        return ""
    row = con.execute(f"SELECT status FROM {table} WHERE id=?",
                      (local_id,)).fetchone()
    if row is None:
        return "gone"
    now = row["status"]
    if now not in order or order.index(to) <= order.index(now):
        return ""                      # already there, or further along
    con.execute(f"UPDATE {table} SET status=? WHERE id=?", (to, local_id))
    con.commit()
    return f"{now} → {to}"


def sync(con, name: str) -> dict:
    """Pull the state of everything we created over there."""
    p = provider(name)
    c = creds(con, name)
    if not c:
        raise HTTPException(400, f"{p['label']} isn't connected")
    rows = con.execute(
        "SELECT * FROM integration_links WHERE provider=?", (name,)).fetchall()
    checked, changed, gone = 0, [], 0
    for r in rows:
        state, to = None, ""
        if name == "trello":
            state, to = _trello_state(c, r["remote_id"])
        elif name == "pipedrive":
            state, to = _pipedrive_state(con, c, r["remote_id"])
        if state is None:
            gone += 1
            continue
        checked += 1
        did = _advance(con, r["kind"], r["local_id"], to) if to else ""
        con.execute(
            "UPDATE integration_links SET remote_state=?, applied=?,"
            " synced_at=? WHERE id=?",
            (state, did or r["applied"], time.time(), r["id"]))
        if did:
            changed.append({"kind": r["kind"], "id": r["local_id"],
                            "state": state, "applied": did})
    con.commit()
    log(con, name, "sync", True,
        f"{checked} checked, {len(changed)} applied"
        + (f", {gone} unreachable" if gone else ""))
    return {"checked": checked, "changed": changed, "unreachable": gone}


def _trello_state(c: dict, card_id: str) -> tuple:
    """(what the card looks like, what it means for us)."""
    q = urllib.parse.urlencode({"key": c.get("api_key", ""),
                                "token": c.get("token", "")})
    ok, card = _req(f"https://api.trello.com/1/cards/{card_id}"
                    f"?fields=name,closed,dueComplete,idList&{q}")
    if not ok or not isinstance(card, dict):
        return None, ""
    # Archived or ticked off is finished. Otherwise the list it sits in is
    # the state — that is how people actually use a board, and reading the
    # list name means a team's own "Done" column works without configuring
    # anything here.
    if card.get("closed") or card.get("dueComplete"):
        return "done", "closed"
    ok2, lst = _req(f"https://api.trello.com/1/lists/{card.get('idList','')}"
                    f"?fields=name&{q}")
    lname = (lst.get("name", "") if ok2 and isinstance(lst, dict) else "")
    low = lname.lower()
    if any(w in low for w in ("done", "complete", "closed", "shipped", "won")):
        return lname, "closed"
    if any(w in low for w in ("doing", "progress", "contacted", "working")):
        return lname, "contacted"
    return lname or "open", ""


def _pipedrive_state(con, c: dict, deal_id: str) -> tuple:
    s = settings(con, "pipedrive")
    dom = s.get("domain", "").replace(".pipedrive.com", "").strip("/")
    tok = urllib.parse.quote(c.get("api_token", ""))
    ok, d = _req(f"https://{dom}.pipedrive.com/api/v1/deals/{deal_id}"
                 f"?api_token={tok}")
    if not ok or not isinstance(d, dict) or not d.get("data"):
        return None, ""
    deal = d["data"]
    st = deal.get("status", "open")
    if st in ("won", "lost"):
        # Both are conclusions. The pipeline knows which; our enquiry list
        # only needs to know it is no longer waiting on anyone here.
        return st, "closed"
    if deal.get("stage_order_nr", 1) and int(
            deal.get("stage_order_nr") or 1) > 1:
        return f"stage {deal.get('stage_order_nr')}", "contacted"
    return st, ""


def links_for(con, kind: str, local_id: int) -> list:
    """Where this record also lives, for showing on its own screen."""
    return [dict(r) for r in con.execute(
        "SELECT provider, remote_url, remote_state, synced_at"
        " FROM integration_links WHERE kind=? AND local_id=?",
        (kind, local_id)).fetchall()]
