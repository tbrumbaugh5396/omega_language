"""The community — finding people, connecting, talking, and live video.
Ported from lingua-portal's social layer and its WebRTC signaling.

Three design decisions carried over intact, because they are the point:

**Messaging requires a mutual contact.** Anyone can *find* people and *ask*
to connect; nobody can message somebody who has not said yes. In a school
with minors this is not a nicety — an adult stranger being able to open a DM
to any student is the abuse case, so the accept step is the gate, and it is
enforced on SEND, server-side, not by hiding a compose box. The one keyhole
is per-person open DMs, off by default: the recipient's own choice.

**Message bodies never reach the audit log.** The log is read by staff.
Private conversations surfacing on an administrator's screen would be a
worse failure than keeping no record — the release valve is the REPORT: a
party to a conversation can hand one message to the office, snapshotted at
that moment so the evidence outlives the sender.

**A contact pair is stored once, `a_id < b_id`.** Two mirrored rows is the
classic shape and the classic bug: they drift, and "are we connected"
depends on which row you asked.

Adaptations in the move: the community is scoped to the SCHOOL — people
enrolled in a course, teaching one, or administering — never the shop's
whole customer file; the source's people-photos and QR identity cards have
no counterpart here yet; privacy knobs live in `community_prefs` rather than
on the user row.

Signaling for live video is the source's HTTP-polling mailbox, verbatim in
spirit: the server never touches media, it relays SDP/ICE between browsers
and answers "who is in the room". In-memory on purpose — signaling is
ephemeral, and a restart should drop stale offers rather than replay them.
Rooms are keyed by tenant: two schools sharing a process must never share a
mailbox.
"""

import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import notify, tenancy

MAX_MESSAGE = 2000
MAX_REASON = 1000
PRIVACY_LEVELS = ("everyone", "initial", "class", "contacts", "nobody")
MESH_MAX = 12

TABLES = """
CREATE TABLE IF NOT EXISTS contacts (
  a_id INTEGER NOT NULL,
  b_id INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','accepted')),
  requested_by INTEGER NOT NULL,
  created_at REAL NOT NULL,
  decided_at REAL,
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)
);

CREATE TABLE IF NOT EXISTS dm_messages (
  id INTEGER PRIMARY KEY,
  from_id INTEGER NOT NULL,
  to_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'text' CHECK (kind IN ('text','call')),
  body TEXT NOT NULL DEFAULT '',
  room TEXT,
  at REAL NOT NULL,
  read_at REAL
);

CREATE TABLE IF NOT EXISTS blocks (
  blocker_id INTEGER NOT NULL,
  blocked_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id != blocked_id)
);

CREATE TABLE IF NOT EXISTS ghosts (
  owner_id INTEGER NOT NULL,
  hidden_from_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (owner_id, hidden_from_id),
  CHECK (owner_id != hidden_from_id)
);

CREATE TABLE IF NOT EXISTS conduct_reports (
  id INTEGER PRIMARY KEY,
  reporter_id INTEGER NOT NULL,
  subject_id INTEGER NOT NULL,
  message_id INTEGER,                     -- no FK: the report must outlive the message
  body_snapshot TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at REAL NOT NULL,
  resolved_by INTEGER,
  resolved_at REAL,
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS community_prefs (
  user_id INTEGER PRIMARY KEY,
  privacy_name TEXT NOT NULL DEFAULT 'everyone',
  privacy_photo INTEGER NOT NULL DEFAULT 1,
  invisible INTEGER NOT NULL DEFAULT 0,
  open_dm INTEGER NOT NULL DEFAULT 0
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── who is in the community, and how they appear ─────────────────────────────

def _pair(a: int, b: int):
    a, b = int(a), int(b)
    if a == b:
        raise HTTPException(400, "that is you")
    return (a, b) if a < b else (b, a)


def prefs_of(con, uid: int) -> dict:
    r = con.execute("SELECT * FROM community_prefs WHERE user_id=?",
                    (int(uid),)).fetchone()
    if r is None:
        return {"user_id": int(uid), "privacy_name": "everyone",
                "privacy_photo": 1, "invisible": 0, "open_dm": 0}
    return dict(r)


def set_prefs(con, uid: int, **kw) -> dict:
    p = prefs_of(con, uid)
    for k in ("privacy_name", "invisible", "open_dm"):
        if k in kw and kw[k] is not None:
            p[k] = kw[k]
    if p["privacy_name"] not in PRIVACY_LEVELS:
        raise HTTPException(400, "unknown privacy level")
    con.execute(
        "INSERT INTO community_prefs(user_id,privacy_name,privacy_photo,"
        " invisible,open_dm) VALUES(?,?,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET"
        "  privacy_name=excluded.privacy_name, invisible=excluded.invisible,"
        "  open_dm=excluded.open_dm",
        (int(uid), p["privacy_name"], p["privacy_photo"],
         1 if p["invisible"] else 0, 1 if p["open_dm"] else 0))
    return p


def is_staff(con, user) -> bool:
    """Full-record viewers: admins, and anyone who teaches a course.
    Attendance sheets and rosters cannot run on initials."""
    if user["is_admin"]:      # user may be a sqlite Row — no .get on those
        return True
    return con.execute("SELECT 1 FROM courses WHERE teacher_id=? AND active=1",
                       (user["id"],)).fetchone() is not None


def in_community(con, uid: int) -> bool:
    """The community is the SCHOOL, not the shop: currently enrolled, or
    teaching, or administering. A customer who only ever bought sparkling
    water is not findable in a student directory."""
    uid = int(uid)
    if con.execute(
            "SELECT 1 FROM enrollments WHERE user_id=? AND"
            " (until IS NULL OR until > ?)", (uid, time.time())).fetchone():
        return True
    if con.execute("SELECT 1 FROM courses WHERE teacher_id=? AND active=1",
                   (uid,)).fetchone():
        return True
    r = con.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["is_admin"])


def _visible_person(con, actor, person_id: int) -> dict:
    """The person, if this actor is allowed to know they exist. Absence and
    prohibition are the same answer, so they cannot be told apart."""
    row = con.execute("SELECT id, name, role, is_admin FROM users"
                      " WHERE id=? AND active=1", (int(person_id),)).fetchone()
    if row is None or not in_community(con, row["id"]):
        raise HTTPException(404, "no such person")
    return dict(row)


def _initialed(name: str) -> str:
    """"Ana Ruiz" -> "Ana R." — the first name whole, the rest one initial."""
    parts = str(name or "").split()
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{parts[0]} {parts[-1][0]}."


def are_contacts(con, a: int, b: int) -> bool:
    x, y = _pair(a, b)
    return con.execute("SELECT 1 FROM contacts WHERE a_id=? AND b_id=?"
                       " AND state='accepted'", (x, y)).fetchone() is not None


def _share_class(con, a: int, b: int) -> bool:
    """Do these two share a course — as students, or teacher-and-student?"""
    now = time.time()
    if con.execute(
            "SELECT 1 FROM enrollments e1 JOIN enrollments e2"
            " ON e1.course_id=e2.course_id"
            " WHERE e1.user_id=? AND e2.user_id=?"
            " AND (e1.until IS NULL OR e1.until > ?)"
            " AND (e2.until IS NULL OR e2.until > ?)", (a, b, now, now)
            ).fetchone():
        return True
    return con.execute(
        "SELECT 1 FROM courses c JOIN enrollments e ON e.course_id=c.id"
        " WHERE (c.teacher_id=? AND e.user_id=?)"
        " OR (c.teacher_id=? AND e.user_id=?)", (a, b, b, a)).fetchone() is not None


def _ghosts(con, owner: int, hidden_from: int) -> bool:
    """Is `owner` a ghost to `hidden_from`? One-directional — the other way
    round is a separate row."""
    return con.execute("SELECT 1 FROM ghosts WHERE owner_id=? AND"
                       " hidden_from_id=?",
                       (int(owner), int(hidden_from))).fetchone() is not None


def _blocked_between(con, a: int, b: int) -> bool:
    """A block in EITHER direction: its effect is mutual — neither side sees
    the other — even though only the blocker can lift it."""
    return con.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?)"
        " OR (blocker_id=? AND blocked_id=?)", (a, b, b, a)).fetchone() is not None


def present(con, viewer, person, *, contact=None, classmate=None):
    """How this person appears to this viewer — their own privacy applied.

    Returns None when the person has chosen not to be visible to this viewer
    at all. One function on purpose: search, the people screen and course
    lists all call it, so "who can see me" has one answer instead of several
    that drift. Staff always get the full record; you always see yourself.
    """
    out = {"id": person["id"], "name": person["name"]}
    if viewer["id"] == person["id"] or is_staff(con, viewer):
        return out
    p = prefs_of(con, person["id"])
    # Ghost mode and blocks come before every privacy level: a ghost is
    # invisible even to accepted contacts, and a blocked pair is invisible
    # to each other whoever placed the block.
    if p["invisible"]:
        return None
    if _blocked_between(con, viewer["id"], person["id"]):
        return None
    if _ghosts(con, person["id"], viewer["id"]):
        return None
    level = p["privacy_name"]
    if level != "everyone":
        if contact is None:
            contact = are_contacts(con, viewer["id"], person["id"])
        if not contact:
            if level == "initial":
                out["name"] = _initialed(person["name"])
            elif level == "class":
                if classmate is None:
                    classmate = _share_class(con, viewer["id"], person["id"])
                if not classmate:
                    return None
            else:                           # contacts-only, or nobody
                return None
    return out


def _decorate_contact(con, actor, p: dict) -> dict:
    if p["id"] == actor["id"]:
        p["contact"] = "self"
        p["requested_by_me"] = False
        return p
    a, b = _pair(actor["id"], p["id"])
    c = con.execute("SELECT state, requested_by FROM contacts WHERE a_id=?"
                    " AND b_id=?", (a, b)).fetchone()
    p["contact"] = c["state"] if c else "none"
    p["requested_by_me"] = bool(c and c["requested_by"] == actor["id"])
    return p


def search(con, actor, q: str, *, limit: int = 20) -> list:
    """Find people by name. Names only — email search would let anyone
    harvest addresses. Only community members appear."""
    q = str(q or "").strip()
    if len(q) < 2:
        return []
    rows = con.execute(
        "SELECT id, name, role FROM users WHERE active=1 AND id != ?"
        " AND name LIKE ? ORDER BY name COLLATE NOCASE LIMIT ?",
        (actor["id"], f"%{q}%", min(int(limit) * 3, 150))).fetchall()
    out = []
    for row in rows:
        if not in_community(con, row["id"]):
            continue
        d = dict(row)
        a, b = _pair(actor["id"], d["id"])
        c = con.execute("SELECT state, requested_by FROM contacts"
                        " WHERE a_id=? AND b_id=?", (a, b)).fetchone()
        p = present(con, actor, d,
                    contact=bool(c and c["state"] == "accepted"))
        if p is None:
            continue                        # their choice; same as not existing
        p["contact"] = c["state"] if c else "none"
        p["requested_by_me"] = bool(c and c["requested_by"] == actor["id"])
        p["open_dm"] = bool(prefs_of(con, d["id"])["open_dm"])
        out.append(p)
        if len(out) >= limit:
            break
    return out


# ── connecting ───────────────────────────────────────────────────────────────

def request(con, actor, person_id: int) -> dict:
    """Ask to connect. If THEY had already asked, this is the acceptance —
    two people who both reached out should not deadlock on who clicks a
    second button."""
    other = _visible_person(con, actor, person_id)
    if _ghosts(con, actor["id"], other["id"]):
        raise HTTPException(409, "you are a ghost to them — unghost them first")
    if present(con, actor, other) is None:
        raise HTTPException(404, "no such person")
    a, b = _pair(actor["id"], other["id"])
    existing = con.execute("SELECT * FROM contacts WHERE a_id=? AND b_id=?",
                           (a, b)).fetchone()
    if existing and existing["state"] == "accepted":
        return {"state": "accepted", "with": other["id"]}
    if existing and existing["requested_by"] != actor["id"]:
        con.execute("UPDATE contacts SET state='accepted', decided_at=?"
                    " WHERE a_id=? AND b_id=?", (time.time(), a, b))
        notify.push(con, "You are now connected",
                    f"you and {actor['name']} accepted each other",
                    kind="learning", user_id=other["id"],
                    dedup=f"contact:{a}:{b}")
        from . import learning
        learning.award_achievements(con, actor["id"])
        learning.award_achievements(con, other["id"])
        return {"state": "accepted", "with": other["id"]}
    if existing:
        return {"state": "pending", "with": other["id"]}
    con.execute("INSERT INTO contacts(a_id,b_id,state,requested_by,created_at)"
                " VALUES(?,?,?,?,?)",
                (a, b, "pending", actor["id"], time.time()))
    notify.push(con, f"{actor['name']} wants to connect",
                "accept or decline on the learning page's People tab",
                kind="learning", user_id=other["id"],
                dedup=f"contactask:{a}:{b}")
    return {"state": "pending", "with": other["id"]}


def respond(con, actor, person_id: int, accept: bool) -> dict:
    """Only the person who was ASKED may decide — the asker deciding for
    them would make the accept step theatre. The asker may withdraw."""
    a, b = _pair(actor["id"], int(person_id))
    c = con.execute("SELECT * FROM contacts WHERE a_id=? AND b_id=?",
                    (a, b)).fetchone()
    if c is None or c["state"] != "pending":
        raise HTTPException(404, "there is no request waiting between you")
    if c["requested_by"] == actor["id"]:
        if accept:
            raise HTTPException(409, "they have not answered yet — you cannot"
                                     " accept for them")
        con.execute("DELETE FROM contacts WHERE a_id=? AND b_id=?", (a, b))
        return {"state": "none"}            # withdrawn
    if accept:
        con.execute("UPDATE contacts SET state='accepted', decided_at=?"
                    " WHERE a_id=? AND b_id=?", (time.time(), a, b))
        notify.push(con, f"{actor['name']} accepted",
                    "you are now connected", kind="learning",
                    user_id=c["requested_by"], dedup=f"contact:{a}:{b}")
        from . import learning
        learning.award_achievements(con, actor["id"])
        learning.award_achievements(con, c["requested_by"])
        return {"state": "accepted"}
    con.execute("DELETE FROM contacts WHERE a_id=? AND b_id=?", (a, b))
    return {"state": "none"}


def remove(con, actor, person_id: int) -> dict:
    a, b = _pair(actor["id"], int(person_id))
    con.execute("DELETE FROM contacts WHERE a_id=? AND b_id=?", (a, b))
    return {"state": "none"}


def contacts(con, actor) -> dict:
    """Everyone connected or asking, with unread counts — the People screen
    in one call. Ghosts, blocks and the invisible are absent throughout."""
    me = actor["id"]
    rows = con.execute(
        "SELECT c.state, c.requested_by, u.id, u.name, u.role,"
        " (SELECT COUNT(*) FROM dm_messages m WHERE m.from_id=u.id"
        "   AND m.to_id=? AND m.read_at IS NULL) AS unread,"
        " (SELECT MAX(m.at) FROM dm_messages m"
        "   WHERE (m.from_id=u.id AND m.to_id=?)"
        "      OR (m.from_id=? AND m.to_id=u.id)) AS last_at"
        " FROM contacts c JOIN users u ON u.id ="
        "   CASE WHEN c.a_id=? THEN c.b_id ELSE c.a_id END"
        " WHERE (c.a_id=? OR c.b_id=?) AND u.active=1"
        " AND NOT EXISTS (SELECT 1 FROM community_prefs p WHERE p.user_id=u.id"
        "                 AND p.invisible=1)"
        " AND NOT EXISTS (SELECT 1 FROM blocks b"
        "   WHERE (b.blocker_id=? AND b.blocked_id=u.id)"
        "      OR (b.blocker_id=u.id AND b.blocked_id=?))"
        " AND NOT EXISTS (SELECT 1 FROM ghosts g WHERE g.owner_id=u.id"
        "                 AND g.hidden_from_id=?)"
        " ORDER BY last_at IS NULL, last_at DESC, u.name COLLATE NOCASE",
        (me, me, me, me, me, me, me, me, me)).fetchall()
    out = {"accepted": [], "incoming": [], "outgoing": [],
           "blocked": [dict(r) for r in con.execute(
               "SELECT u.id, u.name FROM blocks b JOIN users u"
               " ON u.id=b.blocked_id WHERE b.blocker_id=?"
               " ORDER BY u.name COLLATE NOCASE", (me,)).fetchall()]}
    for r in rows:
        d = dict(r)
        mine = d.pop("requested_by") == me
        state = d.pop("state")
        d["ghosted"] = _ghosts(con, me, d["id"])
        if state == "accepted":   # a contact is a friend: full name by definition
            out["accepted"].append(d)
        elif mine:
            out["outgoing"].append(d)
        else:
            out["incoming"].append(d)
    return out


# ── safety controls ──────────────────────────────────────────────────────────

def block(con, actor, person_id: int) -> dict:
    """Shut the door. Any contact edge or pending request goes at the same
    moment — a block that left a live edge behind would let messages keep
    flowing through it. Not audited: who blocks whom is nobody's business."""
    other_id = int(person_id)
    if other_id == actor["id"]:
        raise HTTPException(400, "that is you")
    if con.execute("SELECT 1 FROM users WHERE id=? AND active=1",
                   (other_id,)).fetchone() is None:
        raise HTTPException(404, "no such person")
    a, b = _pair(actor["id"], other_id)
    con.execute("DELETE FROM contacts WHERE a_id=? AND b_id=?", (a, b))
    con.execute("INSERT OR IGNORE INTO blocks(blocker_id,blocked_id,"
                " created_at) VALUES(?,?,?)",
                (actor["id"], other_id, time.time()))
    return {"blocked": other_id}


def unblock(con, actor, person_id: int) -> dict:
    """Only the blocker lifts their own block; the other side's, if any,
    stays."""
    con.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?",
                (actor["id"], int(person_id)))
    return {"blocked": None}


def ghost(con, actor, person_id: int) -> dict:
    """Become a ghost to ONE person: they lose sight of you and messaging
    pauses both ways — but the contact edge survives, and unghosting resumes
    the friendship exactly where it was. You still see THEM."""
    other_id = int(person_id)
    if other_id == actor["id"]:
        raise HTTPException(400, "that is you")
    if con.execute("SELECT 1 FROM users WHERE id=? AND active=1",
                   (other_id,)).fetchone() is None:
        raise HTTPException(404, "no such person")
    con.execute("INSERT OR IGNORE INTO ghosts(owner_id,hidden_from_id,"
                " created_at) VALUES(?,?,?)",
                (actor["id"], other_id, time.time()))
    return {"ghosted": other_id}


def unghost(con, actor, person_id: int) -> dict:
    con.execute("DELETE FROM ghosts WHERE owner_id=? AND hidden_from_id=?",
                (actor["id"], int(person_id)))
    return {"ghosted": None}


# ── messages ─────────────────────────────────────────────────────────────────

def _require_contact(con, actor, person_id: int) -> None:
    a, b = _pair(actor["id"], int(person_id))
    if con.execute("SELECT 1 FROM contacts WHERE a_id=? AND b_id=?"
                   " AND state='accepted'", (a, b)).fetchone() is None:
        raise HTTPException(403, "you can only message people who have"
                                 " accepted you")


def send(con, actor, to_id: int, body: str, *, kind: str = "text",
         room: str = "") -> dict:
    other = _visible_person(con, actor, to_id)
    # Ghost mode pauses messaging BOTH ways: a ghost who could still message
    # people would be invisible-but-present, the unsettling thing the mode
    # exists to prevent being done TO you. Being selectively ghosted reads
    # the same as full ghost mode, deliberately.
    if prefs_of(con, actor["id"])["invisible"] \
            or prefs_of(con, other["id"])["invisible"]:
        raise HTTPException(409, "messaging is paused while ghost mode is on")
    if _ghosts(con, actor["id"], other["id"]):
        raise HTTPException(409, "you are a ghost to them — unghost them to talk")
    if _ghosts(con, other["id"], actor["id"]):
        raise HTTPException(409, "messaging is paused while ghost mode is on")
    if _blocked_between(con, actor["id"], other["id"]):
        raise HTTPException(403, "you can only message people who have"
                                 " accepted you")
    if not prefs_of(con, other["id"])["open_dm"]:
        _require_contact(con, actor, other["id"])
    elif present(con, actor, other) is None:
        raise HTTPException(404, "no such person")
    body = str(body or "").strip()
    if kind not in ("text", "call"):
        raise HTTPException(400, "unknown message kind")
    if kind == "text" and not body:
        raise HTTPException(400, "there is nothing to send")
    if len(body) > MAX_MESSAGE:
        raise HTTPException(400, f"messages are capped at {MAX_MESSAGE}"
                                 " characters")
    cur = con.execute(
        "INSERT INTO dm_messages(from_id,to_id,kind,body,room,at)"
        " VALUES(?,?,?,?,?,?)",
        (actor["id"], other["id"], kind, body,
         str(room or "")[:64] or None, time.time()))
    # No audit row, deliberately: even TRAFFIC (who talks to whom, when) is
    # nearly as sensitive as content. See the module docstring.
    return {"id": cur.lastrowid}


def thread(con, actor, other_id: int, *, since: float = 0,
           limit: int = 200) -> list:
    """The conversation, oldest first. Reading marks their messages read —
    the act of looking IS the receipt."""
    other = _visible_person(con, actor, other_id)
    has_history = con.execute(
        "SELECT 1 FROM dm_messages WHERE (from_id=? AND to_id=?)"
        " OR (from_id=? AND to_id=?) LIMIT 1",
        (actor["id"], other["id"], other["id"], actor["id"])).fetchone() is not None
    if not (has_history or prefs_of(con, other["id"])["open_dm"]):
        _require_contact(con, actor, other["id"])
    rows = con.execute(
        "SELECT id, from_id, to_id, kind, body, room, at, read_at"
        " FROM dm_messages WHERE ((from_id=? AND to_id=?)"
        " OR (from_id=? AND to_id=?)) AND at > ? ORDER BY at, id LIMIT ?",
        (actor["id"], other["id"], other["id"], actor["id"],
         float(since), min(int(limit), 500))).fetchall()
    con.execute("UPDATE dm_messages SET read_at=? WHERE from_id=? AND to_id=?"
                " AND read_at IS NULL", (time.time(), other["id"], actor["id"]))
    return [dict(r) for r in rows]


# ── reports: the release valve ───────────────────────────────────────────────

def report(con, actor, person_id: int, reason: str, *,
           message_id: int | None = None) -> dict:
    """Report a person — or one specific message — to the office. Staff can
    never read a thread, but either party can HAND a message over: its body
    is snapshotted now so the evidence survives the sender being erased, and
    only messages from your own conversations can be snapshotted."""
    reason = str(reason or "").strip()
    if not reason:
        raise HTTPException(400, "say what is wrong — the office reads every"
                                 " report")
    if len(reason) > MAX_REASON:
        raise HTTPException(400, f"reports are capped at {MAX_REASON}"
                                 " characters")
    subject_id = int(person_id)
    if con.execute("SELECT 1 FROM users WHERE id=?",
                   (subject_id,)).fetchone() is None:
        raise HTTPException(404, "no such person")
    snapshot = None
    if message_id is not None:
        msg = con.execute(
            "SELECT * FROM dm_messages WHERE id=?"
            " AND ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?))",
            (int(message_id), subject_id, actor["id"], actor["id"],
             subject_id)).fetchone()
        if msg is None:
            raise HTTPException(404, "that message is not in a conversation"
                                     " of yours")
        snapshot = f"[{msg['kind']}] {msg['body']}"
    cur = con.execute(
        "INSERT INTO conduct_reports(reporter_id,subject_id,message_id,"
        " body_snapshot,reason,created_at) VALUES(?,?,?,?,?,?)",
        (actor["id"], subject_id,
         int(message_id) if message_id is not None else None,
         snapshot, reason, time.time()))
    notify.push(con, "A conduct report was filed",
                "review it on the Learning tab", kind="learning",
                dedup=f"report:{cur.lastrowid}")
    return {"id": cur.lastrowid}


# ── live video signaling ─────────────────────────────────────────────────────
# room -> {peer_id: [msg, ...]}, keyed by tenant so two schools sharing a
# process never share a mailbox. In-memory on purpose.

_ROOMS: dict = {}
_LOCK = threading.Lock()


def _room_key(room: str) -> tuple:
    return (tenancy.CURRENT.get(), str(room)[:64])


def _rtc_join(room: str, peer: str | None) -> dict:
    peer = peer or secrets.token_hex(6)
    key = _room_key(room)
    with _LOCK:
        r = _ROOMS.setdefault(key, {})
        if peer not in r and len(r) >= MESH_MAX:
            raise HTTPException(403, f"the call is full — the mesh carries"
                                     f" {MESH_MAX} people at most")
        r.setdefault(peer, [])
        peers = [p for p in r if p != peer]
    return {"peer": peer, "peers": peers}


def _rtc_signal(room: str, to: str, from_peer: str, payload) -> None:
    key = _room_key(room)
    with _LOCK:
        r = _ROOMS.setdefault(key, {})
        if to not in r:
            raise HTTPException(404, f"peer {to} is not in the room")
        r[to].append({"from": from_peer, "payload": payload})


def _rtc_poll(room: str, peer: str) -> dict:
    key = _room_key(room)
    with _LOCK:
        r = _ROOMS.setdefault(key, {})
        msgs = r.get(peer, [])
        r[peer] = []
        peers = [p for p in r if p != peer]
    return {"messages": msgs, "peers": peers}


def _rtc_leave(room: str, peer: str) -> None:
    key = _room_key(room)
    with _LOCK:
        _ROOMS.get(key, {}).pop(peer, None)
        if not _ROOMS.get(key):
            _ROOMS.pop(key, None)


def rtc_config(cfg) -> dict:
    """ICE servers for the mesh. A deployment without TURN quietly fails for
    anyone behind symmetric NAT — the call simply never connects — so this
    is where a school configures one (config keys turn_url/turn_user/
    turn_pass)."""
    ice = [{"urls": ["stun:stun.l.google.com:19302",
                     "stun:stun1.l.google.com:19302"]}]
    turn = (cfg.get("turn_url") or "").strip()
    if turn:
        entry = {"urls": [u.strip() for u in turn.split(",") if u.strip()]}
        if cfg.get("turn_user"):
            entry["username"] = cfg["turn_user"]
            entry["credential"] = cfg.get("turn_pass", "")
        ice.append(entry)
    return {"mode": "mesh", "mesh_max": MESH_MAX, "ice_servers": ice,
            "has_turn": bool(turn)}


# ── ops routes: the report queue ─────────────────────────────────────────────

router = APIRouter()

from .main import admin_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/learning/conduct")
def ops_reports(user=Depends(admin_user), con=Depends(get_con),
                status: str = "open"):
    rows = con.execute(
        "SELECT r.*, rep.name AS reporter_name, sub.name AS subject_name"
        " FROM conduct_reports r JOIN users rep ON rep.id=r.reporter_id"
        " JOIN users sub ON sub.id=r.subject_id"
        " WHERE r.status=? ORDER BY r.created_at DESC LIMIT 200",
        (str(status),)).fetchall()
    return [dict(r) for r in rows]


class ResolveBody(BaseModel):
    note: str = ""


@router.post("/api/learning/conduct/{rid}/resolve")
def ops_resolve_report(rid: int, body: ResolveBody, user=Depends(admin_user),
                       con=Depends(get_con)):
    cur = con.execute(
        "UPDATE conduct_reports SET status='resolved', resolved_by=?,"
        " resolved_at=?, note=? WHERE id=? AND status='open'",
        (user["id"], time.time(), str(body.note or "")[:1000], int(rid)))
    if cur.rowcount == 0:
        raise HTTPException(404, "no open report with that id")
    con.commit()
    return {"resolved": True}
