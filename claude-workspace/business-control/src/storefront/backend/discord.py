"""Discord: notifications out, and automation rules that decide what goes.

Small teams already live in Discord. The useful integration isn't a bot that
answers questions — it's the business talking to the room it's already in:
an order lands, stock drops below par, a contract gets signed, and the
channel knows before anyone opens a dashboard.

Three parts:

  Channels — an incoming webhook per Discord channel, so #orders gets orders
  and #alerts gets the things that need someone. Webhooks need no bot token,
  no OAuth and no gateway connection, which means nothing to keep running and
  no long-lived credential with server-wide scope.

  Rules — event → channel, with a condition. This is the automation layer the
  deck describes, scoped to one destination: pick an event, optionally filter
  it, choose where it lands.

  Chat — reading channels and replying in them, which webhooks can't do at
  all: they are a one-way pipe. That needs a bot token, so it's optional and
  separate. Connect one and Discord becomes another place the back office
  works from rather than somewhere alerts disappear into.

Both the webhook URL and the bot token are secrets: anyone holding one can
post as the business. They are stored, never returned to the browser after
saving, and the webhook is validated against Discord's own host so a typo
can't turn this into a generic request forwarder pointed at an internal
address. Reads and replies go through Discord's REST API — still no gateway
connection to keep alive.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import admin_user, get_con

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS discord_channels (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,                     -- "#orders"
  webhook TEXT NOT NULL,                   -- secret; never returned
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_rules (
  id INTEGER PRIMARY KEY,
  channel_id INTEGER NOT NULL,
  event TEXT NOT NULL,                     -- see EVENTS
  condition_field TEXT DEFAULT '',         -- e.g. total_cents
  condition_op TEXT DEFAULT '',            -- gt|lt|eq|contains
  condition_value TEXT DEFAULT '',
  template TEXT DEFAULT '',                -- optional override
  active INTEGER DEFAULT 1,
  fired INTEGER DEFAULT 0,
  last_fired REAL DEFAULT 0,
  created_at REAL NOT NULL
);

/* One row. A bot token is what turns this from a megaphone into a
   conversation: webhooks only push out, so reading a channel — or replying
   in it as the business — needs an identity Discord will authenticate. */
CREATE TABLE IF NOT EXISTS discord_bot (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  token TEXT NOT NULL,                     -- secret; never returned
  guild_id TEXT NOT NULL,
  bot_name TEXT DEFAULT '',
  guild_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_log (
  id INTEGER PRIMARY KEY,
  rule_id INTEGER DEFAULT 0,
  event TEXT DEFAULT '',
  ok INTEGER DEFAULT 0,
  detail TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS discord_log_time ON discord_log(created_at DESC);
"""

# What the business can announce. Each carries a default sentence so a rule
# works the moment it's created, without writing a template.
EVENTS = {
    "order.created": ("New order",
                      "New order #{id} — {total} from {customer}"),
    "order.large": ("Large order",
                    "Large order #{id} — {total} from {customer}"),
    "inventory.low": ("Stock below par",
                      "{product} is low at {store}: {qty} left (par {par})"),
    "ticket.created": ("Support ticket",
                       "Support ticket {ref} — {topic}"),
    "enquiry.created": ("Partner enquiry",
                        "New {kind} enquiry from {company}"),
    "document.signed": ("Document signed",
                        "{title} was signed by {signer}"),
    "review.created": ("Product review",
                       "New {rating}-star review on {product}"),
    "route.completed": ("Route finished",
                        "{route} completed — {stops} stops"),
    "campaign.live": ("Campaign live", "Campaign '{name}' is live"),
    "achievement": ("Milestone", "{title}"),
}
OPS = ("gt", "lt", "eq", "contains")
DISCORD_HOSTS = ("discord.com", "discordapp.com", "ptb.discord.com",
                 "canary.discord.com")


def init_tables(con):
    con.executescript(TABLES)


def valid_webhook(url: str) -> str:
    """Only real Discord webhook URLs.

    Without this the field is a server-side request forwarder: paste an
    internal address and the app will happily POST to it on every order.
    """
    url = (url or "").strip()
    m = re.match(r"^https://([a-z.]+)/api/webhooks/\d+/[\w-]+$", url)
    if not m or m.group(1) not in DISCORD_HOSTS:
        raise HTTPException(
            400, "that isn't a Discord webhook URL — it should look like "
                 "https://discord.com/api/webhooks/<id>/<token>")
    return url


def _post(url: str, payload: dict) -> tuple:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "business-control/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return True, str(r.status)
    except Exception as e:                      # noqa: BLE001
        return False, str(e)[:200]


# ---------- the bot: reading and replying ----------

API = "https://discord.com/api/v10"


def _bot(con):
    row = con.execute("SELECT * FROM discord_bot WHERE id=1").fetchone()
    if row is None:
        raise HTTPException(
            400, "no Discord bot connected — add a bot token to read and "
                 "reply to channels from here")
    return row


def _call(token: str, path: str, method: str = "GET", payload=None):
    """One place for every authenticated Discord call.

    Discord's errors are the useful part: a 401 means the token is wrong, a
    403 means the bot is in the server but lacks a permission on that
    channel, and a 429 means slow down. Collapsing those into "request
    failed" would leave someone guessing which of three different fixes
    they need, so each is translated on the way out.
    """
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Bot {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "business-control/1.0 (+local)"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read().decode() or "null"
            return json.loads(body)
    except urllib.error.HTTPError as e:                 # noqa: PERF203
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("message", "")
        except Exception:
            pass
        if e.code == 401:
            raise HTTPException(400, "Discord rejected the bot token")
        if e.code == 403:
            raise HTTPException(
                403, "the bot is connected but not allowed to do that — check "
                     "its channel permissions in Discord (View Channel, Read "
                     "Message History, Send Messages)")
        if e.code == 404:
            raise HTTPException(404, "Discord doesn't know that channel — is "
                                     "the bot in this server?")
        if e.code == 429:
            raise HTTPException(429, "Discord is rate-limiting us; try again "
                                     "in a moment")
        raise HTTPException(400, f"Discord said: {detail or e.code}")
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(502, f"couldn't reach Discord: {str(e)[:120]}")


class BotBody(BaseModel):
    token: str
    guild_id: str


@router.post("/api/store/admin/discord/bot")
def connect_bot(body: BotBody, u=Depends(admin_user), con=Depends(get_con)):
    token = body.token.strip()
    guild = re.sub(r"\D", "", body.guild_id)
    if not token:
        raise HTTPException(400, "paste the bot token")
    if not guild:
        raise HTTPException(
            400, "paste the server ID — in Discord, right-click the server "
                 "and Copy Server ID (Developer Mode must be on)")
    me = _call(token, "/users/@me")
    guilds = _call(token, "/users/@me/guilds")
    match = next((g for g in guilds if str(g["id"]) == guild), None)
    if match is None:
        raise HTTPException(
            400, "the bot isn't in that server yet — invite it first, then "
                 "connect it here")
    con.execute("DELETE FROM discord_bot")
    con.execute(
        "INSERT INTO discord_bot(id,token,guild_id,bot_name,guild_name,"
        " created_at) VALUES(1,?,?,?,?,?)",
        (token, guild, me.get("username", "bot"), match.get("name", ""),
         time.time()))
    con.commit()
    return {"bot_name": me.get("username", "bot"),
            "guild_name": match.get("name", "")}


@router.delete("/api/store/admin/discord/bot")
def disconnect_bot(u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM discord_bot")
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/discord/chat/channels")
def guild_channels(u=Depends(admin_user), con=Depends(get_con)):
    b = _bot(con)
    chans = _call(b["token"], f"/guilds/{b['guild_id']}/channels")
    # 0 = text, 5 = announcement. Voice and category rows aren't places you
    # can hold a conversation from a back office.
    out = [{"id": str(c["id"]), "name": c.get("name", ""),
            "topic": (c.get("topic") or "")[:200],
            "position": c.get("position", 0)}
           for c in chans if c.get("type") in (0, 5)]
    out.sort(key=lambda c: c["position"])
    return {"channels": out, "guild_name": b["guild_name"],
            "bot_name": b["bot_name"]}


@router.get("/api/store/admin/discord/chat/{channel_id}/messages")
def read_messages(channel_id: str, limit: int = 40, u=Depends(admin_user),
                  con=Depends(get_con)):
    b = _bot(con)
    cid = re.sub(r"\D", "", channel_id)
    msgs = _call(b["token"],
                 f"/channels/{cid}/messages?limit={min(max(limit, 1), 100)}")
    out = []
    for m in reversed(msgs):                    # Discord returns newest first
        a = m.get("author") or {}
        out.append({
            "id": str(m.get("id", "")),
            "author": a.get("global_name") or a.get("username", "someone"),
            "bot": bool(a.get("bot")),
            "content": m.get("content", ""),
            "at": m.get("timestamp", ""),
            "attachments": [x.get("filename", "file")
                            for x in m.get("attachments", [])],
        })
    return {"messages": out}


class SayBody(BaseModel):
    content: str


@router.post("/api/store/admin/discord/chat/{channel_id}/messages")
def send_message(channel_id: str, body: SayBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    b = _bot(con)
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "nothing to send")
    cid = re.sub(r"\D", "", channel_id)
    # Attributed to the person, not to a faceless bot: a message from "the
    # business" that nobody can trace back is worse than no message.
    m = _call(b["token"], f"/channels/{cid}/messages", "POST",
              {"content": f"**{u['name']}:** {text[:1900]}"})
    con.execute(
        "INSERT INTO discord_log(rule_id,event,ok,detail,created_at)"
        " VALUES(0,'chat.sent',1,?,?)", (f"#{cid}", time.time()))
    con.commit()
    return {"id": str(m.get("id", ""))}


def _fmt(template: str, data: dict) -> str:
    """Fill a template, leaving unknown placeholders visible rather than
    raising — a missing field should read oddly, not stop the message."""
    out = template
    for k, v in (data or {}).items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out[:1800]


def _matches(rule, data: dict) -> bool:
    field = rule["condition_field"]
    if not field or not rule["condition_op"]:
        return True
    val = (data or {}).get(field)
    want = rule["condition_value"]
    op = rule["condition_op"]
    try:
        if op == "contains":
            return str(want).lower() in str(val).lower()
        if op == "eq":
            return str(val) == str(want)
        return float(val) > float(want) if op == "gt" else float(val) < float(want)
    except (TypeError, ValueError):
        return False


def emit(event: str, data: dict) -> None:
    """Fire any rules watching this event. Off-thread and swallowing errors:
    Discord being down must never fail an order."""
    def run():
        from erp.backend import db
        con = db.connect()
        try:
            rules = con.execute(
                "SELECT r.*, c.webhook, c.label FROM discord_rules r"
                " JOIN discord_channels c ON c.id=r.channel_id"
                " WHERE r.event=? AND r.active=1 AND c.active=1",
                (event,)).fetchall()
            for r in rules:
                if not _matches(r, data):
                    continue
                template = r["template"] or EVENTS.get(event, ("", event))[1]
                ok, detail = _post(r["webhook"], {
                    "content": _fmt(template, data),
                    "username": "Business Control"})
                con.execute(
                    "UPDATE discord_rules SET fired=fired+1, last_fired=?"
                    " WHERE id=?", (time.time(), r["id"]))
                con.execute(
                    "INSERT INTO discord_log(rule_id,event,ok,detail,"
                    " created_at) VALUES(?,?,?,?,?)",
                    (r["id"], event, 1 if ok else 0, detail, time.time()))
            con.commit()
        except Exception:
            pass
        finally:
            con.close()
    from erp.backend import tenancy
    threading.Thread(target=tenancy.with_tenant(
        tenancy.CURRENT.get(), run), daemon=True).start()


# ---------- admin ----------

@router.get("/api/store/admin/discord")
def read_config(u=Depends(admin_user), con=Depends(get_con)):
    chans = con.execute(
        "SELECT id, label, active, created_at FROM discord_channels"
        " ORDER BY id").fetchall()
    rules = con.execute(
        "SELECT r.*, c.label channel_label FROM discord_rules r"
        " JOIN discord_channels c ON c.id=r.channel_id ORDER BY r.id"
        ).fetchall()
    log = con.execute(
        "SELECT * FROM discord_log ORDER BY id DESC LIMIT 40").fetchall()
    bot = con.execute("SELECT bot_name, guild_name, guild_id FROM discord_bot"
                      " WHERE id=1").fetchone()
    return {
        # webhook and bot token deliberately absent — they're credentials,
        # and a UI that can display one is a UI that can leak it over
        # someone's shoulder
        "bot": dict(bot) if bot else None,
        "channels": [dict(c) for c in chans],
        "rules": [dict(r) for r in rules],
        "log": [dict(l) for l in log],
        "events": {k: v[0] for k, v in EVENTS.items()},
        "defaults": {k: v[1] for k, v in EVENTS.items()},
        "ops": list(OPS),
    }


class ChannelBody(BaseModel):
    label: str
    webhook: str


@router.post("/api/store/admin/discord/channels")
def add_channel(body: ChannelBody, u=Depends(admin_user),
                con=Depends(get_con)):
    url = valid_webhook(body.webhook)
    label = body.label.strip()[:60] or "#general"
    cur = con.execute(
        "INSERT INTO discord_channels(label,webhook,active,created_at)"
        " VALUES(?,?,1,?)", (label, url, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.delete("/api/store/admin/discord/channels/{cid}")
def del_channel(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM discord_rules WHERE channel_id=?", (cid,))
    con.execute("DELETE FROM discord_channels WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}


@router.post("/api/store/admin/discord/channels/{cid}/test")
def test_channel(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    c = con.execute("SELECT * FROM discord_channels WHERE id=?",
                    (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "no such channel")
    ok, detail = _post(c["webhook"], {
        "content": f"Test message from Business Control — sent by {u['name']}.",
        "username": "Business Control"})
    con.execute(
        "INSERT INTO discord_log(rule_id,event,ok,detail,created_at)"
        " VALUES(0,'test',?,?,?)", (1 if ok else 0, detail, time.time()))
    con.commit()
    if not ok:
        raise HTTPException(400, f"Discord rejected it: {detail}")
    return {"ok": True}


class RuleBody(BaseModel):
    channel_id: int
    event: str
    condition_field: str = ""
    condition_op: str = ""
    condition_value: str = ""
    template: str = ""
    active: bool = True


@router.post("/api/store/admin/discord/rules")
def add_rule(body: RuleBody, u=Depends(admin_user), con=Depends(get_con)):
    if body.event not in EVENTS:
        raise HTTPException(400, "unknown event")
    if body.condition_op and body.condition_op not in OPS:
        raise HTTPException(400, f"condition must be one of {OPS}")
    if not con.execute("SELECT 1 FROM discord_channels WHERE id=?",
                       (body.channel_id,)).fetchone():
        raise HTTPException(404, "no such channel")
    cur = con.execute(
        "INSERT INTO discord_rules(channel_id,event,condition_field,"
        " condition_op,condition_value,template,active,created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (body.channel_id, body.event, body.condition_field.strip()[:40],
         body.condition_op, body.condition_value.strip()[:80],
         body.template.strip()[:400], 1 if body.active else 0, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.patch("/api/store/admin/discord/rules/{rid}")
def toggle_rule(rid: int, body: dict, u=Depends(admin_user),
                con=Depends(get_con)):
    con.execute("UPDATE discord_rules SET active=? WHERE id=?",
                (1 if body.get("active") else 0, rid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/discord/rules/{rid}")
def del_rule(rid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM discord_rules WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}
