"""Support: tickets, contact details, and the bridge to live help.

The storefront already had live chat riding the ERP's conversation rails.
What it lacked was everything around it — a way to leave a message when
nobody is on, a phone number, and a route into the voice/video calling the
ERP already implements. This module adds the parts that don't exist and
points at the parts that do rather than duplicating them:

  chat   -> erp.backend.chat (existing support conversations)
  calls  -> the same WebRTC signaling the ops app uses, over /ws
  ticket -> here, with an email acknowledgement and a reply thread
  phone  -> here, as merchant-configured contact details

A ticket also opens a support conversation, so a customer who writes in and
then starts chatting is one thread to the team rather than two.
"""
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from erp.backend import auth, db, mailer
from .api import admin_user, get_con, rate_limit

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS store_tickets (
  id INTEGER PRIMARY KEY,
  ref TEXT UNIQUE NOT NULL,                -- ZJ-4F2A, what we tell the customer
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  topic TEXT DEFAULT 'other',              -- order|product|delivery|wholesale|other
  order_ref TEXT DEFAULT '',
  subject TEXT DEFAULT '',
  body TEXT DEFAULT '',
  status TEXT DEFAULT 'open',              -- open|waiting|closed
  user_id INTEGER DEFAULT 0,               -- linked account, when signed in
  conv_id INTEGER DEFAULT 0,               -- the support conversation
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS store_tickets_time
  ON store_tickets(created_at DESC);

CREATE TABLE IF NOT EXISTS store_ticket_replies (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL,
  author TEXT DEFAULT '',
  staff INTEGER DEFAULT 0,
  body TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""

TOPICS = {
    "order": "An order I've placed",
    "delivery": "Delivery or tracking",
    "product": "A question about the drinks",
    "wholesale": "Wholesale or stocking",
    "other": "Something else",
}

DEFAULT_CONTACT = {
    "phone": "",
    "phone_hours": "Mon–Fri, 9am–5pm ET",
    "email": "",
    "reply_target": "within one working day",
    "calls_enabled": True,
}


def init_tables(con):
    con.executescript(TABLES)


def contact(con) -> dict:
    row = con.execute(
        "SELECT v FROM store_meta WHERE k='support_contact'").fetchone()
    saved = {}
    if row:
        try:
            saved = json.loads(row["v"])
        except ValueError:
            saved = {}
    return {**DEFAULT_CONTACT, **saved}


def new_ref(con) -> str:
    import secrets
    for _ in range(20):
        ref = "ZJ-" + secrets.token_hex(2).upper()
        if not con.execute("SELECT 1 FROM store_tickets WHERE ref=?",
                           (ref,)).fetchone():
            return ref
    return "ZJ-" + str(int(time.time()))[-6:]


# ---------- public ----------

@router.get("/api/store/support/config")
def support_config(con=Depends(get_con)):
    """What the support hub can offer right now. `staff_online` decides
    whether we invite someone to call or steer them to a ticket — offering a
    call that nobody picks up is worse than not offering one."""
    from erp.backend import chat
    c = contact(con)
    online = []
    try:
        ids = chat.online_ids()
        if ids:
            marks = ",".join("?" * len(ids))
            online = [r["id"] for r in con.execute(
                f"SELECT id FROM users WHERE id IN ({marks}) AND active=1"
                " AND (is_admin=1 OR role IN ('employee','owner'))",
                tuple(ids)).fetchall()]
    except Exception:
        online = []
    return {"phone": c["phone"], "phone_hours": c["phone_hours"],
            "email": c["email"], "reply_target": c["reply_target"],
            "calls_enabled": bool(c["calls_enabled"]) and bool(online),
            "staff_online": len(online), "topics": TOPICS}


class TicketBody(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    topic: str = "other"
    order_ref: str = ""
    subject: str = ""
    body: str


@router.post("/api/store/support/ticket")
def create_ticket(body: TicketBody, request: Request, con=Depends(get_con),
                  _rl=Depends(rate_limit)):
    name = body.name.strip()
    text = body.body.strip()
    if not name or not text:
        raise HTTPException(400, "we need a name and a message")
    if body.topic not in TOPICS:
        raise HTTPException(400, "unknown topic")
    email = body.email.strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "that email doesn't look right")

    # Link to the signed-in account when there is one, so the ticket and any
    # live chat are the same person to the team.
    user = None
    tok = request.headers.get("authorization", "")
    if tok:
        user = auth.user_for_token(con, tok.removeprefix("Bearer ").strip())

    conv_id = 0
    if user is not None:
        from erp.backend import chat
        conv_id = chat.ensure_support(con, user)

    ref = new_ref(con)
    now = time.time()
    cur = con.execute(
        "INSERT INTO store_tickets(ref,name,email,phone,topic,order_ref,"
        " subject,body,user_id,conv_id,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ref, name, email, body.phone.strip(), body.topic,
         body.order_ref.strip(), body.subject.strip()[:140], text,
         user["id"] if user else 0, conv_id, now, now))
    tid = cur.lastrowid

    # Drop it into the support conversation too, so whoever is on chat sees
    # it without opening a second tool.
    if conv_id:
        try:
            from erp.backend import chat
            chat.add_message(
                con, conv_id, user,
                f"[ticket {ref}] "
                f"{body.subject.strip() or TOPICS[body.topic]}\n{text}")
        except Exception:
            pass
    con.commit()

    if email:
        c = contact(con)
        try:
            from erp.backend.main import CFG
            mailer.send(
                CFG, email, f"We've got your message ({ref})",
                f"Hi {name},\n\nThanks for writing in — your reference is "
                f"{ref} and a human will reply {c['reply_target']}.\n\n"
                f"What you sent us:\n{text}\n\n— Zenjoy support")
        except Exception:
            pass          # a mail outage must not lose the ticket
    from .api import fire_webhooks
    fire_webhooks("ticket.created", {
        "id": tid, "ref": ref, "topic": body.topic,
        "name": name, "email": body.email.strip()})
    return {"ok": True, "ref": ref, "id": tid}


@router.get("/api/store/support/ticket/{ref}")
def read_ticket(ref: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    """Look a ticket up by its reference. Deliberately thin: the reference is
    a weak secret, so this returns status and replies but never the email or
    phone number the customer gave us."""
    t = con.execute("SELECT * FROM store_tickets WHERE ref=?",
                    (ref.strip().upper(),)).fetchone()
    if t is None:
        raise HTTPException(404, "no ticket with that reference")
    replies = con.execute(
        "SELECT author, staff, body, created_at FROM store_ticket_replies"
        " WHERE ticket_id=? ORDER BY id", (t["id"],)).fetchall()
    return {"ref": t["ref"], "status": t["status"], "topic": t["topic"],
            "subject": t["subject"], "body": t["body"],
            "created_at": t["created_at"],
            "replies": [dict(r) for r in replies]}


# ---------- admin ----------

@router.get("/api/store/admin/tickets")
def admin_tickets(status: str = "", u=Depends(admin_user),
                  con=Depends(get_con)):
    sql = "SELECT * FROM store_tickets"
    args: tuple = ()
    if status in ("open", "waiting", "closed"):
        sql += " WHERE status=?"
        args = (status,)
    sql += " ORDER BY (status='closed'), updated_at DESC LIMIT 200"
    rows = con.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["topic_label"] = TOPICS.get(r["topic"], r["topic"])
        d["replies"] = con.execute(
            "SELECT COUNT(*) n FROM store_ticket_replies WHERE ticket_id=?",
            (r["id"],)).fetchone()["n"]
        out.append(d)
    return out


class ReplyBody(BaseModel):
    body: str = ""
    status: str = ""


@router.post("/api/store/admin/tickets/{tid}")
def admin_reply(tid: int, body: ReplyBody, u=Depends(admin_user),
                con=Depends(get_con)):
    t = con.execute("SELECT * FROM store_tickets WHERE id=?",
                    (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such ticket")
    now = time.time()
    if body.body.strip():
        con.execute(
            "INSERT INTO store_ticket_replies(ticket_id,author,staff,body,"
            " created_at) VALUES(?,?,1,?,?)",
            (tid, u["name"], body.body.strip(), now))
        if t["email"]:
            try:
                from erp.backend.main import CFG
                mailer.send(
                    CFG, t["email"], f"Re: your message ({t['ref']})",
                    f"{body.body.strip()}\n\n— {u['name']}, Zenjoy support")
            except Exception:
                pass
    status = body.status if body.status in ("open", "waiting", "closed") \
        else ("waiting" if body.body.strip() else t["status"])
    con.execute("UPDATE store_tickets SET status=?, updated_at=? WHERE id=?",
                (status, now, tid))
    con.commit()
    return {"ok": True, "status": status}


class ContactBody(BaseModel):
    phone: str = ""
    phone_hours: str = ""
    email: str = ""
    reply_target: str = ""
    calls_enabled: bool = True


@router.get("/api/store/admin/support-contact")
def read_contact(u=Depends(admin_user), con=Depends(get_con)):
    return contact(con)


@router.post("/api/store/admin/support-contact")
def save_contact(body: ContactBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    cfg = {
        "phone": re.sub(r"[<>]", "", body.phone)[:40],
        "phone_hours": re.sub(r"[<>]", "", body.phone_hours)[:80]
        or DEFAULT_CONTACT["phone_hours"],
        "email": re.sub(r"[<>\s]", "", body.email)[:80],
        "reply_target": re.sub(r"[<>]", "", body.reply_target)[:80]
        or DEFAULT_CONTACT["reply_target"],
        "calls_enabled": bool(body.calls_enabled),
    }
    con.execute(
        "INSERT INTO store_meta(k,v) VALUES('support_contact',?)"
        " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(cfg),))
    con.commit()
    return {"ok": True}
