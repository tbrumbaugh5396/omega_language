"""Discord: notifications out, and automation rules that decide what goes.

Small teams already live in Discord. The useful integration isn't a bot that
answers questions — it's the business talking to the room it's already in:
an order lands, stock drops below par, a contract gets signed, and the
channel knows before anyone opens a dashboard.

Two halves:

  Channels — an incoming webhook per Discord channel, so #orders gets orders
  and #alerts gets the things that need someone. Webhooks need no bot token,
  no OAuth and no gateway connection, which means nothing to keep running and
  no long-lived credential with server-wide scope.

  Rules — event → channel, with a condition. This is the automation layer the
  deck describes, scoped to one destination: pick an event, optionally filter
  it, choose where it lands.

The webhook URL is a secret: anyone holding it can post to the channel. It is
stored, never returned to the browser after saving, and validated against
Discord's own host so a typo can't turn this into a generic request forwarder
pointed at an internal address.
"""
import json
import re
import threading
import time
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
    threading.Thread(target=run, daemon=True).start()


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
    return {
        # webhook deliberately absent — it's a credential, and a UI that can
        # display it is a UI that can leak it over someone's shoulder
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
