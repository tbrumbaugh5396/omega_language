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

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
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

/* The pieces of a ticket. A task is one line of the work with a box to
   tick; a link is the page in this product the ticket is about — the
   order, the student, the client — so the reader lands on it in one
   click; a file is what somebody attached. None is required, because
   the fastest way to lose a board is to make filing on it cost more
   than remembering. */
CREATE TABLE IF NOT EXISTS ticket_tasks (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  done INTEGER DEFAULT 0,
  assignee_id INTEGER DEFAULT 0,
  position INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  done_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ticket_tasks_t ON ticket_tasks(ticket_id, position);
CREATE TABLE IF NOT EXISTS ticket_links (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL,
  tab TEXT NOT NULL,                       -- a screen of this product
  ref_id INTEGER DEFAULT 0,                -- the row on it, if any
  label TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ticket_links_t ON ticket_links(ticket_id);
CREATE TABLE IF NOT EXISTS ticket_files (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  ext TEXT NOT NULL,
  mime TEXT DEFAULT '',
  bytes INTEGER DEFAULT 0,
  sha256 TEXT DEFAULT '',
  by_id INTEGER DEFAULT 0,
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ticket_files_t ON ticket_files(ticket_id);
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


def _team(user) -> None:
    """The board is the team's. A customer's account reaches the shop
    front, not the work behind it — and an attachment on a ticket is
    the work behind it."""
    if user["role"] in ("customer", "distributor", "influencer") and not user["is_admin"]:
        raise HTTPException(403, "the board is the team's")


def _row(con, tid: int):
    r = con.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such ticket")
    return r


def _log(con, tid: int, actor: str, what: str) -> None:
    con.execute("INSERT INTO ticket_log(ticket_id,at,actor,what)"
                " VALUES(?,?,?,?)", (tid, db.now(), actor[:80], what[:200]))


# The screens a ticket can point at, and what the number after them
# means. A ticket about an order links to the order; the reader lands on
# it. A screen with no rows (the till, the board itself) takes no number.
LINK_TABS = {
    "orders": "Order", "customers": "Customer", "clients": "Client",
    "learning": "Course", "students": "Student", "inventory": "Inventory",
    "bookings": "Booking", "events": "Event", "hiring": "Applicant",
    "expenses": "Expense", "civics": "Jurisdiction", "ideas": "Idea",
    "docs": "Document", "finance": "Invoice", "legal": "Matter",
    "supply": "Supplier", "rooms": "Room", "presentations": "Presentation",
    "cameras": "Camera", "shop": "Product", "promos": "Promo",
    "till": "", "rota": "", "accounting": "", "payroll": "",
    "onboarding": "", "automation": "", "treasury": "", "analytics": "",
}

# What may be attached: the vault's list, because a board that takes
# executables is a board somebody will regret.
FILE_EXT = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
    "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain", "csv": "text/csv", "md": "text/markdown",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation",
    "mp4": "video/mp4", "mov": "video/quicktime", "m4a": "audio/mp4",
    "mp3": "audio/mpeg", "zip": "application/zip", "json": "application/json",
}
MAX_FILE = 25 * 1024 * 1024


def _dir():
    from . import tenancy
    d = tenancy.data_dir() / "uploads" / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _shape(con, r) -> dict:
    d = dict(r)
    d["labels"] = [x.strip() for x in (r["labels"] or "").split(",")
                   if x.strip()]
    d["overdue"] = bool(r["due"] and r["due"] < time.time()
                        and r["col"] != "done")
    d["tasks"] = [dict(x) for x in con.execute(
        "SELECT t.*, u.name AS assignee_name FROM ticket_tasks t"
        " LEFT JOIN users u ON u.id=t.assignee_id"
        " WHERE t.ticket_id=? ORDER BY t.position, t.id", (r["id"],))]
    d["tasks_done"] = sum(1 for t in d["tasks"] if t["done"])
    d["links"] = [dict(x) for x in con.execute(
        "SELECT * FROM ticket_links WHERE ticket_id=? ORDER BY id",
        (r["id"],))]
    for l in d["links"]:
        l["href"] = f"#/{l['tab']}" + (f"/{l['ref_id']}" if l["ref_id"] else "")
        l["label"] = l["label"] or (
            f"{LINK_TABS.get(l['tab']) or l['tab']}"
            + (f" #{l['ref_id']}" if l["ref_id"] else ""))
    d["files"] = [dict(x) for x in con.execute(
        "SELECT id, name, ext, mime, bytes, by_name, created_at FROM"
        " ticket_files WHERE ticket_id=? ORDER BY id", (r["id"],))]
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
            "me": user["id"], "link_tabs": LINK_TABS,
            "file_ext": sorted(FILE_EXT)}


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
    # Its pieces go with it — and an attachment's bytes come off disk,
    # or the folder fills with files no row remembers.
    for f in con.execute("SELECT id, ext FROM ticket_files WHERE ticket_id=?",
                         (tid,)).fetchall():
        try:
            (_dir() / f"{f['id']}.{f['ext']}").unlink()
        except FileNotFoundError:
            pass
    for t in ("ticket_files", "ticket_links", "ticket_tasks", "ticket_log"):
        con.execute(f"DELETE FROM {t} WHERE ticket_id=?", (tid,))
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


# ---------- the pieces: tasks, links, files ----------

class TaskBody(BaseModel):
    title: str = ""
    done: bool | None = None
    assignee_id: int | None = None


@router.post("/api/tickets/{tid}/tasks")
def add_task(tid: int, body: TaskBody, user=Depends(current_user),
             con=Depends(get_con)):
    _team(user)
    _row(con, tid)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a task is a line of work — say what")
    pos = con.execute("SELECT COALESCE(MAX(position),0)+1 AS p FROM"
                      " ticket_tasks WHERE ticket_id=?", (tid,)).fetchone()["p"]
    cur = con.execute(
        "INSERT INTO ticket_tasks(ticket_id,title,assignee_id,position,"
        " created_at) VALUES(?,?,?,?,?)",
        (tid, title[:200], max(0, body.assignee_id or 0), pos, db.now()))
    _log(con, tid, user["name"], f"added task: {title[:80]}")
    con.execute("UPDATE tickets SET updated_at=? WHERE id=?", (db.now(), tid))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/tickets/{tid}/tasks/{kid}")
def edit_task(tid: int, kid: int, body: TaskBody, user=Depends(current_user),
              con=Depends(get_con)):
    _row(con, tid)
    t = con.execute("SELECT * FROM ticket_tasks WHERE id=? AND ticket_id=?",
                    (kid, tid)).fetchone()
    if t is None:
        raise HTTPException(404, "no such task")
    said = []
    if body.done is not None and bool(t["done"]) != body.done:
        con.execute("UPDATE ticket_tasks SET done=?, done_at=? WHERE id=?",
                    (int(body.done), db.now() if body.done else 0, kid))
        said.append(("ticked" if body.done else "unticked") + f": {t['title'][:60]}")
    if body.title.strip() and body.title.strip() != t["title"]:
        con.execute("UPDATE ticket_tasks SET title=? WHERE id=?",
                    (body.title.strip()[:200], kid))
        said.append("reworded a task")
    if body.assignee_id is not None and body.assignee_id != t["assignee_id"]:
        con.execute("UPDATE ticket_tasks SET assignee_id=? WHERE id=?",
                    (max(0, body.assignee_id), kid))
        who = con.execute("SELECT name FROM users WHERE id=?",
                          (body.assignee_id,)).fetchone()
        said.append(f"task to {who['name']}" if who else "task unassigned")
    if said:
        _log(con, tid, user["name"], ", ".join(said))
        con.execute("UPDATE tickets SET updated_at=? WHERE id=?", (db.now(), tid))
    con.commit()
    return {"ok": True}


@router.delete("/api/tickets/{tid}/tasks/{kid}")
def drop_task(tid: int, kid: int, user=Depends(current_user),
              con=Depends(get_con)):
    _row(con, tid)
    con.execute("DELETE FROM ticket_tasks WHERE id=? AND ticket_id=?", (kid, tid))
    _log(con, tid, user["name"], "removed a task")
    con.commit()
    return {"ok": True}


class LinkBody(BaseModel):
    tab: str
    ref_id: int = 0
    label: str = ""


@router.post("/api/tickets/{tid}/links")
def add_link(tid: int, body: LinkBody, user=Depends(current_user),
             con=Depends(get_con)):
    """The page this ticket is about. A ticket that says "the Ortiz order"
    and a ticket that opens the Ortiz order are different tickets."""
    _team(user)
    _row(con, tid)
    if body.tab not in LINK_TABS:
        raise HTTPException(400, f"tab is one of {sorted(LINK_TABS)}")
    if body.ref_id and not LINK_TABS[body.tab]:
        raise HTTPException(400, f"{body.tab} has no rows to point at")
    if LINK_TABS[body.tab] and not body.ref_id:
        raise HTTPException(400, f"which {LINK_TABS[body.tab].lower()}? give its number")
    if con.execute("SELECT 1 FROM ticket_links WHERE ticket_id=? AND tab=?"
                   " AND ref_id=?", (tid, body.tab, body.ref_id)).fetchone():
        return {"ok": True, "already": True}
    cur = con.execute(
        "INSERT INTO ticket_links(ticket_id,tab,ref_id,label,created_at)"
        " VALUES(?,?,?,?,?)",
        (tid, body.tab, max(0, body.ref_id), body.label.strip()[:120], db.now()))
    _log(con, tid, user["name"],
         f"linked {LINK_TABS.get(body.tab) or body.tab}"
         + (f" #{body.ref_id}" if body.ref_id else ""))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/tickets/{tid}/links/{lid}")
def drop_link(tid: int, lid: int, user=Depends(current_user),
              con=Depends(get_con)):
    _row(con, tid)
    con.execute("DELETE FROM ticket_links WHERE id=? AND ticket_id=?", (lid, tid))
    con.commit()
    return {"ok": True}


@router.post("/api/tickets/{tid}/files")
async def add_file(tid: int, request: Request, user=Depends(current_user),
                   con=Depends(get_con)):
    """Raw bytes with the name in a header, like every other upload here.
    Kept on disk under the tenant, one file per row, hashed so a reader
    can tell whether what they downloaded is what was attached."""
    _team(user)
    _row(con, tid)
    name = (request.headers.get("x-filename") or "file").strip()[:200]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in FILE_EXT:
        raise HTTPException(400, f"attach one of: {', '.join(sorted(FILE_EXT))}")
    data = await request.body()
    if not data:
        raise HTTPException(400, "the file is empty")
    if len(data) > MAX_FILE:
        raise HTTPException(413, "25 MB is the most one attachment may be")
    cur = con.execute(
        "INSERT INTO ticket_files(ticket_id,name,ext,mime,bytes,sha256,by_id,"
        " by_name,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (tid, name, ext, FILE_EXT[ext], len(data),
         hashlib.sha256(data).hexdigest(), user["id"], user["name"], db.now()))
    fid = cur.lastrowid
    (_dir() / f"{fid}.{ext}").write_bytes(data)
    _log(con, tid, user["name"], f"attached {name[:80]}")
    con.execute("UPDATE tickets SET updated_at=? WHERE id=?", (db.now(), tid))
    con.commit()
    return {"ok": True, "id": fid, "bytes": len(data)}


@router.get("/api/tickets/{tid}/files/{fid}")
def get_file(tid: int, fid: int, user=Depends(current_user),
             con=Depends(get_con)):
    _team(user)
    _row(con, tid)
    f = con.execute("SELECT * FROM ticket_files WHERE id=? AND ticket_id=?",
                    (fid, tid)).fetchone()
    if f is None:
        raise HTTPException(404, "no such attachment")
    path = _dir() / f"{fid}.{f['ext']}"
    if not path.exists():
        raise HTTPException(410, "the file is no longer on disk")
    # Never cached: ids are reused after a delete, and a browser that
    # remembered a 410 for this address would keep answering it.
    return FileResponse(path, media_type=f["mime"] or "application/octet-stream",
                        filename=f["name"], headers={"Cache-Control": "no-store"})


@router.delete("/api/tickets/{tid}/files/{fid}")
def drop_file(tid: int, fid: int, user=Depends(current_user),
              con=Depends(get_con)):
    _team(user)
    _row(con, tid)
    f = con.execute("SELECT * FROM ticket_files WHERE id=? AND ticket_id=?",
                    (fid, tid)).fetchone()
    if f is None:
        raise HTTPException(404, "no such attachment")
    con.execute("DELETE FROM ticket_files WHERE id=?", (fid,))
    try:
        (_dir() / f"{fid}.{f['ext']}").unlink()
    except FileNotFoundError:
        pass
    _log(con, tid, user["name"], f"removed attachment {f['name'][:60]}")
    con.commit()
    return {"ok": True}
