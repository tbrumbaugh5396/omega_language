"""Hours: what was worked, what is owed, and who said so.

The clock could already record a shift. It could not answer the question
a payroll run is: for this fortnight, for each person, how many hours,
how many of them at time and a half, how much of it was holiday, and has
somebody with authority looked at it.

Three things live here.

  * A **week** of somebody's shifts, totalled, with overtime split out at
    the line the business sets rather than assumed.
  * **Time off** — asked for, approved or declined, with a reason and a
    name against the decision. Holiday and sick hours land in the same
    total as worked hours, because payroll pays both and a screen that
    shows only one is a screen that gets somebody underpaid.
  * **Approval.** A period a manager has signed off stops being editable
    by the person who worked it, and the signature is a row, not a flag:
    who approved which fortnight, when, and what the total was at the
    moment they said yes.

Shifts stay where they were. This does not move the clock; it reads it.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db
from .main import CFG, current_user, get_con

router = APIRouter()

# What a business calls the hours somebody did not work. Kept short: a
# list nobody can hold in their head is a list people file wrongly.
LEAVE_KINDS = ("holiday", "sick", "unpaid", "bereavement", "other")
LEAVE_STATES = ("requested", "approved", "declined", "cancelled")

TABLES = """
CREATE TABLE IF NOT EXISTS time_off (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'holiday',    -- see LEAVE_KINDS
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  hours REAL DEFAULT 0,                    -- what it is worth in pay
  note TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'requested', -- see LEAVE_STATES
  decided_by TEXT DEFAULT '',
  decided_at REAL DEFAULT 0,
  decided_note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS time_off_who ON time_off(user_id, starts);

/* A signature on a period, not a flag on a row. "Approved" has to say who
   and when and what the number was when they said it, or it is worth
   nothing the first time somebody disputes a cheque. */
CREATE TABLE IF NOT EXISTS timesheet_approvals (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  period_start REAL NOT NULL,
  period_end REAL NOT NULL,
  worked_hours REAL DEFAULT 0,
  overtime_hours REAL DEFAULT 0,
  leave_hours REAL DEFAULT 0,
  approved_by TEXT NOT NULL,
  approved_at REAL NOT NULL,
  note TEXT DEFAULT '',
  UNIQUE(user_id, period_start)
);
"""


def init_tables(con):
    con.executescript(TABLES)


def _ot_line() -> float:
    """Hours in a week after which the rest is overtime. Configurable
    because the answer is 40 in one country and 38 in another, and a
    number baked into a payroll screen is a number somebody will be paid
    wrongly by."""
    try:
        return float(CFG.get("overtime_after_hours") or 40)
    except (TypeError, ValueError):
        return 40.0


def _week_start(ts: float) -> float:
    """Monday, local, at midnight. Weeks are how overtime is counted, so
    the boundary has to be one thing everywhere."""
    lt = time.localtime(ts)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            0, 0, 0, 0, 0, -1))
    return midnight - lt.tm_wday * 86400


def _office(user) -> bool:
    """Who may look at everybody's hours and sign them off. The owner, an
    admin, and anyone the permissions grid has given the money areas —
    which is how an office manager gets it without being made an owner."""
    if user["is_admin"] or user["role"] == "owner":
        return True
    perms = (user["permissions"] or "").split(",")
    return any(p.strip() in ("*", "settings", "finance", "workforce")
               for p in perms)


def _require_office(user) -> None:
    if not _office(user):
        raise HTTPException(403, "somebody else's hours are not yours to "
                                 "read")


def hours_for(con, uid: int, a: float, b: float) -> dict:
    """One person, one period: worked, overtime, leave, and the shifts
    themselves so a manager can see what the number is made of."""
    shifts = [dict(r) for r in con.execute(
        "SELECT s.id, s.clock_in, s.clock_out, s.event_id, p.name AS event"
        " FROM shifts s LEFT JOIN promos p ON p.id=s.event_id"
        " WHERE s.user_id=? AND s.clock_in>=? AND s.clock_in<?"
        " ORDER BY s.clock_in", (uid, a, b))]
    by_week: dict = {}
    worked = 0.0
    for sh in shifts:
        out = sh["clock_out"] or 0
        sh["hours"] = round(max(0.0, (out - sh["clock_in"]) / 3600), 2) \
            if out else 0.0
        sh["open"] = not out
        worked += sh["hours"]
        wk = _week_start(sh["clock_in"])
        by_week[wk] = by_week.get(wk, 0.0) + sh["hours"]
    line = _ot_line()
    overtime = round(sum(max(0.0, h - line) for h in by_week.values()), 2)
    leave = [dict(r) for r in con.execute(
        "SELECT * FROM time_off WHERE user_id=? AND state='approved'"
        " AND starts < ? AND ends >= ?", (uid, b, a))]
    leave_hours = round(sum(x["hours"] or 0 for x in leave), 2)
    return {"shifts": shifts, "worked_hours": round(worked, 2),
            "overtime_hours": overtime,
            "regular_hours": round(worked - overtime, 2),
            "leave": leave, "leave_hours": leave_hours,
            "paid_hours": round(worked + leave_hours, 2),
            "overtime_after": line}


@router.get("/api/hours")
def my_hours(from_ts: float = 0, to_ts: float = 0,
             user=Depends(current_user), con=Depends(get_con)):
    """My own hours. Everybody can see their own — a timesheet somebody
    cannot check is a timesheet they cannot dispute."""
    a = from_ts or (_week_start(time.time()) - 13 * 86400)
    b = to_ts or (time.time() + 86400)
    out = hours_for(con, user["id"], a, b)
    out["approved"] = _approval(con, user["id"], a)
    return {"from": a, "to": b, "user_id": user["id"],
            "name": user["name"], **out}


def _approval(con, uid: int, period_start: float):
    r = con.execute(
        "SELECT approved_by, approved_at, worked_hours, overtime_hours,"
        " leave_hours, note FROM timesheet_approvals"
        " WHERE user_id=? AND period_start=?",
        (uid, period_start)).fetchone()
    return dict(r) if r else None


@router.get("/api/hours/everyone")
def everyone(from_ts: float = 0, to_ts: float = 0,
             user=Depends(current_user), con=Depends(get_con)):
    """The payroll screen: every person who worked in the period, what
    they are owed hours for, and whether anybody has said yes to it."""
    _require_office(user)
    a = from_ts or (_week_start(time.time()) - 13 * 86400)
    b = to_ts or (time.time() + 86400)
    people = con.execute(
        "SELECT id, name, role, job, employment FROM users"
        " WHERE active=1 AND (is_admin=1 OR role IN"
        "  ('employee','owner','teacher','volunteer','director'))"
        " ORDER BY name").fetchall()
    rows = []
    for p in people:
        h = hours_for(con, p["id"], a, b)
        if not (h["worked_hours"] or h["leave_hours"] or h["shifts"]):
            continue
        rows.append({"user_id": p["id"], "name": p["name"],
                     "role": p["role"], "job": p["job"],
                     "employment": p["employment"],
                     "approved": _approval(con, p["id"], a), **h})
    return {"from": a, "to": b, "rows": rows,
            "overtime_after": _ot_line(),
            "totals": {
                "worked": round(sum(r["worked_hours"] for r in rows), 2),
                "overtime": round(sum(r["overtime_hours"] for r in rows), 2),
                "leave": round(sum(r["leave_hours"] for r in rows), 2)}}


class ShiftEditBody(BaseModel):
    clock_in: float | None = None
    clock_out: float | None = None
    note: str = ""


@router.patch("/api/hours/shift/{sid}")
def edit_shift(sid: int, body: ShiftEditBody, user=Depends(current_user),
               con=Depends(get_con)):
    """Correct a punch. Somebody forgets to clock out roughly once a week
    in any business with a clock, and a timesheet nobody can fix is a
    timesheet that gets fixed in a spreadsheet instead — which is where
    payroll disputes come from."""
    _require_office(user)
    sh = con.execute("SELECT * FROM shifts WHERE id=?", (sid,)).fetchone()
    if sh is None:
        raise HTTPException(404, "no such shift")
    if _approval(con, sh["user_id"], _week_start(sh["clock_in"])):
        raise HTTPException(400, "that week has been approved — reopen it "
                                 "first, so the correction is on the record "
                                 "rather than behind a signature")
    a = body.clock_in if body.clock_in is not None else sh["clock_in"]
    b = body.clock_out if body.clock_out is not None else sh["clock_out"]
    if b and b < a:
        raise HTTPException(400, "a shift cannot end before it starts")
    con.execute("UPDATE shifts SET clock_in=?, clock_out=? WHERE id=?",
                (a, b or None, sid))
    con.commit()
    return {"ok": True}


class ApproveBody(BaseModel):
    user_id: int
    period_start: float
    period_end: float
    note: str = ""
    approve: bool = True


@router.post("/api/hours/approve")
def approve(body: ApproveBody, user=Depends(current_user),
            con=Depends(get_con)):
    """Sign off a period, or reopen one. The numbers are recomputed here
    and stored WITH the signature: what the manager approved is what the
    manager saw, not what the shifts happen to say later."""
    _require_office(user)
    if not body.approve:
        con.execute("DELETE FROM timesheet_approvals WHERE user_id=? AND"
                    " period_start=?", (body.user_id, body.period_start))
        con.commit()
        return {"ok": True, "approved": False}
    h = hours_for(con, body.user_id, body.period_start, body.period_end)
    con.execute(
        "INSERT INTO timesheet_approvals(user_id,period_start,period_end,"
        " worked_hours,overtime_hours,leave_hours,approved_by,approved_at,"
        " note) VALUES(?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user_id, period_start) DO UPDATE SET"
        "  worked_hours=excluded.worked_hours,"
        "  overtime_hours=excluded.overtime_hours,"
        "  leave_hours=excluded.leave_hours,"
        "  approved_by=excluded.approved_by,"
        "  approved_at=excluded.approved_at, note=excluded.note",
        (body.user_id, body.period_start, body.period_end,
         h["worked_hours"], h["overtime_hours"], h["leave_hours"],
         user["name"], db.now(), body.note.strip()[:300]))
    con.commit()
    return {"ok": True, "approved": True, **h}


# ---------- time off ----------

class LeaveBody(BaseModel):
    kind: str = "holiday"
    starts: float
    ends: float
    hours: float = 0
    note: str = ""
    user_id: int = 0            # an office may file on somebody's behalf


@router.get("/api/time-off")
def list_leave(mine: int = 0, state: str = "",
               user=Depends(current_user), con=Depends(get_con)):
    """Mine always; everybody's if the office may see it."""
    if mine or not _office(user):
        rows = con.execute(
            "SELECT t.*, u.name AS who FROM time_off t"
            " JOIN users u ON u.id=t.user_id WHERE t.user_id=?"
            " ORDER BY t.starts DESC LIMIT 200", (user["id"],)).fetchall()
    else:
        q = ("SELECT t.*, u.name AS who FROM time_off t"
             " JOIN users u ON u.id=t.user_id")
        args: tuple = ()
        if state in LEAVE_STATES:
            q += " WHERE t.state=?"
            args = (state,)
        rows = con.execute(q + " ORDER BY t.starts DESC LIMIT 400",
                           args).fetchall()
    return {"requests": [dict(r) for r in rows],
            "kinds": list(LEAVE_KINDS), "office": _office(user),
            "me": user["id"]}


@router.post("/api/time-off")
def ask_leave(body: LeaveBody, user=Depends(current_user),
              con=Depends(get_con)):
    if body.kind not in LEAVE_KINDS:
        raise HTTPException(400, f"kind must be one of {LEAVE_KINDS}")
    if body.ends < body.starts:
        raise HTTPException(400, "it cannot end before it starts")
    uid = user["id"]
    if body.user_id and body.user_id != user["id"]:
        _require_office(user)
        uid = body.user_id
    days = max(1, round((body.ends - body.starts) / 86400))
    hours = body.hours if body.hours > 0 else days * 8
    cur = con.execute(
        "INSERT INTO time_off(user_id,kind,starts,ends,hours,note,state,"
        " created_at) VALUES(?,?,?,?,?,?,'requested',?)",
        (uid, body.kind, body.starts, body.ends, hours,
         body.note.strip()[:400], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid, "hours": hours}


class DecideBody(BaseModel):
    state: str
    note: str = ""


@router.post("/api/time-off/{rid}/decide")
def decide_leave(rid: int, body: DecideBody, user=Depends(current_user),
                 con=Depends(get_con)):
    """Approve, decline, or withdraw. A request nobody answered is the
    thing people actually complain about, so a decision carries a name."""
    r = con.execute("SELECT * FROM time_off WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such request")
    if body.state not in LEAVE_STATES:
        raise HTTPException(400, f"state must be one of {LEAVE_STATES}")
    if body.state == "cancelled":
        # your own to withdraw; anybody else's needs the office
        if r["user_id"] != user["id"]:
            _require_office(user)
    else:
        _require_office(user)
        if r["user_id"] == user["id"] and not user["is_admin"]:
            raise HTTPException(400, "somebody else approves your own time "
                                     "off")
    con.execute("UPDATE time_off SET state=?, decided_by=?, decided_at=?,"
                " decided_note=? WHERE id=?",
                (body.state, user["name"], db.now(),
                 body.note.strip()[:300], rid))
    con.commit()
    from . import notify
    try:
        notify.push(con, f"Time off {body.state}",
                    f"{user['name']} {body.state} your "
                    f"{r['kind']} request.", kind="achievement",
                    user_id=r["user_id"])
    except Exception:                                        # noqa: BLE001
        pass
    return {"ok": True, "state": body.state}
