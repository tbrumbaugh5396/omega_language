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
        "blurb": "Post what happens in the business into a channel.",
        "auth": "webhook",
        "fields": [{"k": "webhook_url", "label": "Incoming webhook URL",
                    "secret": True,
                    "hint": "Slack → Apps → Incoming Webhooks → Add to "
                            "Workspace, then copy the URL for the channel."}],
        "events": ["order.created", "enquiry.created", "ticket.created",
                   "inventory.low", "document.signed"],
        "does": "Sends a line to the channel when an order lands, stock runs "
                "low, a partner enquires, a ticket opens or a document is "
                "signed.",
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
        "does": "Creates a card for each new enquiry, support ticket or "
                "low-stock warning, so the work sits where the team looks.",
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
        "does": "Creates a person and a deal for every wholesale, "
                "distribution or partnership enquiry, so nothing sits in an "
                "inbox.",
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
        return (True, "channel verified") if ok else (False, str(d))

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


def oauth_exchange(con, name: str, cfg: dict, code: str,
                   redirect: str) -> dict:
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
    account = str(d.get("realmId") or d.get("account_id")
                  or d.get("team", {}).get("name", "") if isinstance(
                      d.get("team"), dict) else "") or p["label"]
    save(con, name,
         {"access_token": d["access_token"],
          "refresh_token": d.get("refresh_token", "")},
         account, {}, expires)
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
        return _req(f"https://api.trello.com/1/cards?{q}", "POST")

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
        return _json_req(f"{base}/deals?api_token={tok}", "POST", payload=deal)

    if name == "dropbox":
        # Only documents are filed; there is nothing useful to put in a
        # folder for an order that is a row in a database.
        if event != "document.signed":
            return True, "nothing to file"
        body = json.dumps(d, indent=1).encode()
        path = f"/business-control/signed/{d.get('id', 'doc')}.json"
        return _req(
            "https://content.dropboxapi.com/2/files/upload", "POST",
            {"Authorization": f"Bearer {c.get('access_token','')}",
             "Dropbox-API-Arg": json.dumps(
                 {"path": path, "mode": "overwrite", "mute": True}),
             "Content-Type": "application/octet-stream"}, body)

    return True, "connected, nothing to send for this event"
