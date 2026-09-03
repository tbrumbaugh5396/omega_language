"""The board: work that is somebody's, in a state, with a date.

A business already had four places work hid — a note on a client, a
blocker on a portal, an event in a calendar, a thing somebody said in
chat — and no place where all of it was one list you could move. This is
that list. A ticket has a title, a column, an owner, a priority and a
due date, and nothing else is required, because the fastest way to lose
a board is to make filing on it cost more than remembering.

Columns are fixed and few on purpose. Every team that gets to invent its
own ends up with eleven, three of which mean "waiting", and no two
people agreeing which. Backlog is not started, Doing is started, Review
is somebody else's turn, Done is done, and Blocked is the honest one:
started, not moving, and the reason is written down.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db
from .main import current_user, get_con

router = APIRouter()

COLUMNS = ("backlog", "doing", "review", "blocked", "done")
PRIORITIES = ("low", "normal", "high", "urgent")

TABLES = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  col TEXT NOT NULL DEFAULT 'backlog',     -- see COLUMNS
  priority TEXT NOT NULL DEFAULT 'normal', -- see PRIORITIES
  assignee_id INTEGER DEFAULT 0,           -- 0 = nobody yet
  reporter_id INTEGER DEFAULT 0,
  due REAL DEFAULT 0,                      -- 0 = no date
  engagement_id INTEGER DEFAULT 0,         -- the client it belongs to
  labels TEXT DEFAULT '',                  -- comma separated, free
  position REAL DEFAULT 0,                 -- order within a column
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  closed_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS tickets_col ON tickets(col, position);
CREATE INDEX IF NOT EXISTS tickets_due ON tickets(due);

CREATE TABLE IF NOT EXISTS ticket_log (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL,
  at REAL NOT NULL,
  actor TEXT DEFAULT '',
  what TEXT NOT NULL
);
"""


def init_tables(con):
    con.executescript(TABLES)


def _row(con, tid: int):
    r = con.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such ticket")
    return r


def _log(con, tid: int, actor: str, what: str) -> None:
    con.execute("INSERT INTO ticket_log(ticket_id,at,actor,what)"
                " VALUES(?,?,?,?)", (tid, db.now(), actor[:80], what[:200]))


def _shape(con, r) -> dict:
    d = dict(r)
    d["labels"] = [x.strip() for x in (r["labels"] or "").split(",")
                   if x.strip()]
    d["overdue"] = bool(r["due"] and r["due"] < time.time()
                        and r["col"] != "done")
    return d


@router.get("/api/tickets")
def list_tickets(mine: int = 0, user=Depends(current_user),
                 con=Depends(get_con)):
    """The whole board. Small enough to send at once — a board you have to
    paginate is a board nobody is working."""
    rows = con.execute(
        "SELECT t.*, u.name AS assignee_name, e.name AS client_name"
        " FROM tickets t"
        " LEFT JOIN users u ON u.id=t.assignee_id"
        " LEFT JOIN engagements e ON e.id=t.engagement_id"
        " ORDER BY t.col, t.position, t.id DESC LIMIT 800").fetchall()
    out = [_shape(con, r) for r in rows]
    if mine:
        out = [t for t in out if t["assignee_id"] == user["id"]]
    people = [dict(p) for p in con.execute(
        "SELECT id, name FROM users WHERE active=1 AND"
        " (is_admin=1 OR role IN ('employee','owner','teacher','volunteer',"
        "  'director')) ORDER BY name").fetchall()]
    return {"tickets": out, "columns": list(COLUMNS),
            "priorities": list(PRIORITIES), "people": people,
            "me": user["id"]}


class TicketBody(BaseModel):
    title: str = ""
    body: str = ""
    col: str = ""
    priority: str = ""
    assignee_id: int | None = None
    due: float | None = None
    engagement_id: int | None = None
    labels: str | None = None


@router.post("/api/tickets")
def create_ticket(body: TicketBody, user=Depends(current_user),
                  con=Depends(get_con)):
    title = body.title.strip()[:200]
    if not title:
        raise HTTPException(400, "a ticket needs a title")
    col = body.col or "backlog"
    if col not in COLUMNS:
        raise HTTPException(400, f"column must be one of {COLUMNS}")
    pri = body.priority or "normal"
    if pri not in PRIORITIES:
        raise HTTPException(400, f"priority must be one of {PRIORITIES}")
    now = db.now()
    top = con.execute("SELECT COALESCE(MIN(position),0)-1 AS p FROM tickets"
                      " WHERE col=?", (col,)).fetchone()["p"]
    cur = con.execute(
        "INSERT INTO tickets(title,body,col,priority,assignee_id,reporter_id,"
        " due,engagement_id,labels,position,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (title, body.body.strip()[:4000], col, pri,
         max(0, body.assignee_id or 0), user["id"], max(0.0, body.due or 0),
         max(0, body.engagement_id or 0), (body.labels or "").strip()[:200],
         top, now, now))
    _log(con, cur.lastrowid, user["name"], "opened")
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/tickets/{tid}")
def update_ticket(tid: int, body: TicketBody, user=Depends(current_user),
                  con=Depends(get_con)):
    """Change one thing or several. What moved is written on the ticket's
    own record: a board where cards move and nobody can say who moved them
    is a board that starts arguments."""
    r = _row(con, tid)
    fields: dict = {}
    said = []
    if body.title.strip() and body.title.strip() != r["title"]:
        fields["title"] = body.title.strip()[:200]
        said.append("retitled")
    if body.body is not None and body.body.strip() != (r["body"] or ""):
        fields["body"] = body.body.strip()[:4000]
        said.append("edited the detail")
    if body.col and body.col != r["col"]:
        if body.col not in COLUMNS:
            raise HTTPException(400, f"column must be one of {COLUMNS}")
        fields["col"] = body.col
        fields["closed_at"] = db.now() if body.col == "done" else 0
        said.append(f"moved to {body.col}")
        top = con.execute("SELECT COALESCE(MIN(position),0)-1 AS p"
                          " FROM tickets WHERE col=?",
                          (body.col,)).fetchone()["p"]
        fields["position"] = top
    if body.priority and body.priority != r["priority"]:
        if body.priority not in PRIORITIES:
            raise HTTPException(400, f"priority must be one of {PRIORITIES}")
        fields["priority"] = body.priority
        said.append(f"priority {body.priority}")
    if body.assignee_id is not None and body.assignee_id != r["assignee_id"]:
        fields["assignee_id"] = max(0, body.assignee_id)
        who = con.execute("SELECT name FROM users WHERE id=?",
                          (fields["assignee_id"],)).fetchone()
        said.append(f"assigned to {who['name']}" if who else "unassigned")
    if body.due is not None and float(body.due) != float(r["due"] or 0):
        fields["due"] = max(0.0, body.due)
        said.append("due date set" if body.due else "due date cleared")
    if body.engagement_id is not None \
            and body.engagement_id != r["engagement_id"]:
        fields["engagement_id"] = max(0, body.engagement_id)
        said.append("client changed")
    if body.labels is not None and body.labels.strip() != (r["labels"] or ""):
        fields["labels"] = body.labels.strip()[:200]
        said.append("labels changed")
    if not fields:
        return {"ok": True, "unchanged": True}
    fields["updated_at"] = db.now()
    sets = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE tickets SET {sets} WHERE id=?",
                (*fields.values(), tid))
    _log(con, tid, user["name"], ", ".join(said) or "edited")
    con.commit()
    return {"ok": True}


@router.get("/api/tickets/{tid}")
def one_ticket(tid: int, user=Depends(current_user), con=Depends(get_con)):
    r = _row(con, tid)
    out = _shape(con, r)
    out["log"] = [dict(x) for x in con.execute(
        "SELECT at, actor, what FROM ticket_log WHERE ticket_id=?"
        " ORDER BY id DESC LIMIT 40", (tid,))]
    return out


@router.delete("/api/tickets/{tid}")
def delete_ticket(tid: int, user=Depends(current_user), con=Depends(get_con)):
    _row(con, tid)
    if not (user["is_admin"] or user["role"] in ("owner", "employee")):
        raise HTTPException(403, "the board is office-side")
    con.execute("DELETE FROM ticket_log WHERE ticket_id=?", (tid,))
    con.execute("DELETE FROM tickets WHERE id=?", (tid,))
    con.commit()
    return {"ok": True}


# ---------- the calendar: one month, everything dated in it ----------

@router.get("/api/calendar")
def calendar(from_ts: float = 0, to_ts: float = 0,
             user=Depends(current_user), con=Depends(get_con)):
    """Everything this business has a date for, in one list.

    A month had four calendars in it — events on one page, ticket due
    dates on another, a client's milestones on a third, classes on a
    fourth — and the only place they were ever laid over each other was
    somebody's head. They are dated rows in one database; there is no
    reason they cannot be one answer.
    """
    now = time.time()
    a = from_ts or (now - 30 * 86400)
    b = to_ts or (now + 90 * 86400)
    out = []

    def add(kind, when, title, note="", link="", state=""):
        if when and a <= when <= b:
            out.append({"kind": kind, "at": when, "title": title,
                        "note": note, "link": link, "state": state})

    try:
        for r in con.execute(
                "SELECT id,name,kind,venue,city,starts,active,"
                " COALESCE(archived,0) AS archived FROM store_events"
                " WHERE starts BETWEEN ? AND ?", (a, b)):
            if r["archived"]:
                continue
            add("event", r["starts"], r["name"],
                " · ".join(x for x in (r["kind"], r["venue"], r["city"]) if x),
                "#/events", "live" if r["active"] else "hidden")
    except Exception:                                        # noqa: BLE001
        pass
    try:
        for r in con.execute(
                "SELECT t.id,t.title,t.due,t.col,t.priority,u.name AS who"
                " FROM tickets t LEFT JOIN users u ON u.id=t.assignee_id"
                " WHERE t.due BETWEEN ? AND ?", (a, b)):
            add("ticket", r["due"], r["title"],
                " · ".join(x for x in (r["col"], r["priority"], r["who"])
                           if x), "#/board", r["col"])
    except Exception:                                        # noqa: BLE001
        pass
    try:
        for r in con.execute(
                "SELECT d.label, d.planned, d.actual, e.name AS client,"
                " e.id AS eid FROM engagement_dates d"
                " JOIN engagements e ON e.id=d.engagement_id"):
            for stamp, state in ((r["actual"], "done"),
                                 (r["planned"], "planned")):
                ts = _day_ts(stamp)
                if ts:
                    add("milestone", ts, f"{r['client']} — {r['label']}",
                        state, f"#/clients/{r['eid']}", state)
                    break
    except Exception:                                        # noqa: BLE001
        pass
    try:
        for r in con.execute(
                "SELECT s.id, s.started_at, c.name AS course"
                " FROM class_sessions s JOIN courses c ON c.id=s.course_id"
                " WHERE s.started_at BETWEEN ? AND ?", (a, b)):
            add("class", r["started_at"], r["course"], "class held",
                "#/learning", "held")
    except Exception:                                        # noqa: BLE001
        pass
    out.sort(key=lambda x: x["at"])
    return {"from": a, "to": b, "items": out}


def _day_ts(day: str) -> float:
    """'2026-11-06' as a timestamp, or 0. The dates table stores days as
    text because a milestone is a day, not a moment."""
    if not day or len(str(day)) < 8:
        return 0.0
    try:
        return time.mktime(time.strptime(str(day)[:10], "%Y-%m-%d"))
    except ValueError:
        return 0.0
