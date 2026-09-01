"""The library — a lending desk, ported from lingua-portal's inventory
service. Books, materials and equipment go out to a person and come back.

The one design rule carried over whole: **nothing about a loan is stored
that can be derived.** There is no `available` column and no `state`
column — availability is copies minus open loans, overdue is a comparison
against the clock, both computed on read. A stored counter is a counter
that drifts; a derived one can only be late, never wrong.

The desk is staff-side: admins and anyone teaching an active course check
items out and back in (a teacher lending a textbook after class is the
common case). A learner sees their own loans on /learn. Checking anything
out is a badge moment — the bookworm badge is "ever borrowed", awarded at
the desk.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import notify

KINDS = ("book", "material", "equipment")
MAX_COPIES = 10000

TABLES = """
CREATE TABLE IF NOT EXISTS library_items (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'book'
    CHECK (kind IN ('book','material','equipment')),
  copies INTEGER NOT NULL DEFAULT 1 CHECK (copies >= 0),
  notes TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS library_loans (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  out_at REAL NOT NULL,
  due_at REAL,                              -- NULL = no due date
  returned_at REAL,                         -- NULL = still out
  checked_out_by INTEGER                    -- the staff member at the desk
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── derived state ────────────────────────────────────────────────────────────

def _open_loans(con, item_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) AS n FROM library_loans WHERE item_id=?"
        " AND returned_at IS NULL", (int(item_id),)).fetchone()["n"]


def items(con) -> list:
    now = time.time()
    out = []
    for r in con.execute("SELECT * FROM library_items"
                         " ORDER BY kind, name COLLATE NOCASE").fetchall():
        d = dict(r)
        d["out"] = _open_loans(con, d["id"])
        d["available"] = d["copies"] - d["out"]
        out.append(d)
    return out


def open_loans(con) -> list:
    """The desk's worklist: everything still out, no-due-date rows last."""
    now = time.time()
    rows = con.execute(
        "SELECT l.*, i.name AS item_name, i.kind, u.name AS borrower"
        " FROM library_loans l JOIN library_items i ON i.id=l.item_id"
        " JOIN users u ON u.id=l.user_id"
        " WHERE l.returned_at IS NULL"
        " ORDER BY l.due_at IS NULL, l.due_at, l.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["overdue"] = bool(d["due_at"] and d["due_at"] < now)
        out.append(d)
    return out


def my_loans(con, user_id: int) -> list:
    now = time.time()
    rows = con.execute(
        "SELECT l.id, l.item_id, l.out_at, l.due_at, l.returned_at,"
        " i.name AS item_name, i.kind"
        " FROM library_loans l JOIN library_items i ON i.id=l.item_id"
        " WHERE l.user_id=? ORDER BY l.returned_at IS NOT NULL, l.out_at DESC"
        " LIMIT 100", (int(user_id),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["overdue"] = bool(d["due_at"] and not d["returned_at"]
                            and d["due_at"] < now)
        out.append(d)
    return out


# ── the desk ─────────────────────────────────────────────────────────────────

def add_item(con, *, name: str, kind: str = "book", copies: int = 1,
             notes: str = "") -> int:
    name = str(name or "").strip()[:200]
    if not name:
        raise HTTPException(400, "an item needs a name")
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    copies = int(copies)
    if not (0 < copies <= MAX_COPIES):
        raise HTTPException(400, f"copies must be 1-{MAX_COPIES}")
    cur = con.execute(
        "INSERT INTO library_items(name,kind,copies,notes,created_at)"
        " VALUES(?,?,?,?,?)",
        (name, kind, copies, str(notes or "")[:400], time.time()))
    return cur.lastrowid


def checkout(con, actor, *, item_id: int, user_id: int,
             due_days: int | None = 14) -> int:
    item = con.execute("SELECT * FROM library_items WHERE id=?",
                       (int(item_id),)).fetchone()
    if item is None:
        raise HTTPException(404, "no such item")
    person = con.execute("SELECT * FROM users WHERE id=? AND active=1",
                         (int(user_id),)).fetchone()
    if person is None:
        raise HTTPException(404, "no such person")
    if _open_loans(con, item["id"]) >= item["copies"]:
        raise HTTPException(409,
                            f"every copy of \"{item['name']}\" is already out")
    due = time.time() + int(due_days) * 86400 if due_days else None
    cur = con.execute(
        "INSERT INTO library_loans(item_id,user_id,out_at,due_at,"
        " checked_out_by) VALUES(?,?,?,?,?)",
        (item["id"], person["id"], time.time(), due, actor["id"]))
    # the badge moment: bookworm is "ever borrowed", derived like the rest
    from . import learning
    learning.award_achievements(con, person["id"])
    days = f" — due back in {int(due_days)} days" if due_days else ""
    notify.push(con, "Checked out to you",
                f"{item['name']}{days}", kind="learning",
                user_id=person["id"], dedup=f"loan:{cur.lastrowid}")
    return cur.lastrowid


def check_in(con, loan_id: int) -> None:
    cur = con.execute(
        "UPDATE library_loans SET returned_at=? WHERE id=?"
        " AND returned_at IS NULL", (time.time(), int(loan_id)))
    # rowcount, not lastrowid: a double return must fail loudly, not
    # silently rewrite the timestamp of a return that already happened
    if cur.rowcount == 0:
        raise HTTPException(404, "no open loan with that id")


# ── ops routes ───────────────────────────────────────────────────────────────

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)
from . import community as CM  # noqa: E402


def _desk(con, user):
    """Admins and teachers run the desk — the same people rosters trust."""
    if not CM.is_staff(con, user):
        raise HTTPException(403, "the lending desk is staff-only")


@router.get("/api/learning/library")
def ops_library(user=Depends(current_user), con=Depends(get_con)):
    _desk(con, user)
    return {"items": items(con), "loans": open_loans(con)}


class ItemBody(BaseModel):
    name: str = ""
    kind: str = "book"
    copies: int = 1
    notes: str = ""


@router.post("/api/learning/library/items")
def ops_library_add(body: ItemBody, user=Depends(current_user),
                    con=Depends(get_con)):
    _desk(con, user)
    iid = add_item(con, name=body.name, kind=body.kind, copies=body.copies,
                   notes=body.notes)
    con.commit()
    return {"id": iid}


class CheckoutBody(BaseModel):
    item_id: int = 0
    user_id: int = 0
    name: str = ""                 # alternative to user_id, like enrolment
    due_days: int | None = 14


@router.post("/api/learning/library/checkout")
def ops_library_checkout(body: CheckoutBody, user=Depends(current_user),
                         con=Depends(get_con)):
    _desk(con, user)
    uid = body.user_id
    if not uid and body.name.strip():
        u = con.execute("SELECT id FROM users WHERE name=? AND active=1",
                        (body.name.strip(),)).fetchone()
        if u is None:
            raise HTTPException(404, "no user by that name")
        uid = u["id"]
    lid = checkout(con, user, item_id=body.item_id, user_id=uid,
                   due_days=body.due_days)
    con.commit()
    return {"id": lid}


@router.post("/api/learning/library/return/{lid}")
def ops_library_return(lid: int, user=Depends(current_user),
                       con=Depends(get_con)):
    _desk(con, user)
    check_in(con, lid)
    con.commit()
    return {"ok": True}
