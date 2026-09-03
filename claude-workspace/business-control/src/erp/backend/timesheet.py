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


ROTA_TABLES = """
/* When somebody can work, and when they are being asked to.

   These are two different facts and a rota that confuses them is how
   people end up rostered on their one evening class. Availability is
   what a person says about their own week and nobody else edits.
   A scheduled shift is what the business asks of them — drafted, then
   published, because a rota half-built is not a promise anybody should
   be reading off a wall. */
CREATE TABLE IF NOT EXISTS availability (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  weekday INTEGER NOT NULL,                -- 0 Monday .. 6 Sunday
  from_min INTEGER NOT NULL,               -- minutes past midnight
  to_min INTEGER NOT NULL,
  note TEXT DEFAULT '',
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS availability_who ON availability(user_id, weekday);

CREATE TABLE IF NOT EXISTS scheduled_shifts (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  store_id INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  published INTEGER DEFAULT 0,
  created_by TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS scheduled_when ON scheduled_shifts(starts);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.executescript(ROTA_TABLES)


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


# ---------- availability and the rota ----------

class SlotBody(BaseModel):
    weekday: int
    from_min: int
    to_min: int
    note: str = ""
    user_id: int = 0


@router.get("/api/availability")
def availability(user_id: int = 0, user=Depends(current_user),
                 con=Depends(get_con)):
    """What people say about their own weeks. Yours always; everybody's if
    you are rostering."""
    if user_id and user_id != user["id"]:
        _require_office(user)
    uid = user_id or user["id"]
    rows = con.execute(
        "SELECT * FROM availability WHERE user_id=?"
        " ORDER BY weekday, from_min", (uid,)).fetchall()
    out = {"user_id": uid, "slots": [dict(r) for r in rows],
           "office": _office(user)}
    if _office(user) and not user_id:
        out["everyone"] = [dict(r) for r in con.execute(
            "SELECT a.*, u.name FROM availability a"
            " JOIN users u ON u.id=a.user_id"
            " ORDER BY u.name, a.weekday, a.from_min")]
    return out


@router.post("/api/availability")
def set_availability(body: SlotBody, user=Depends(current_user),
                     con=Depends(get_con)):
    """Add one window. Somebody else's week is theirs to describe, so an
    office can read it and only a manager may write it on their behalf —
    which happens, because somebody always tells you in person."""
    uid = user["id"]
    if body.user_id and body.user_id != user["id"]:
        _require_office(user)
        uid = body.user_id
    if not 0 <= body.weekday <= 6:
        raise HTTPException(400, "weekday is 0 (Monday) to 6")
    if not 0 <= body.from_min < body.to_min <= 24 * 60:
        raise HTTPException(400, "that window starts after it ends")
    cur = con.execute(
        "INSERT INTO availability(user_id,weekday,from_min,to_min,note,"
        " updated_at) VALUES(?,?,?,?,?,?)",
        (uid, body.weekday, body.from_min, body.to_min,
         body.note.strip()[:120], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/availability/{sid}")
def del_availability(sid: int, user=Depends(current_user),
                     con=Depends(get_con)):
    r = con.execute("SELECT user_id FROM availability WHERE id=?",
                    (sid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such window")
    if r["user_id"] != user["id"]:
        _require_office(user)
    con.execute("DELETE FROM availability WHERE id=?", (sid,))
    con.commit()
    return {"ok": True}


class ShiftPlanBody(BaseModel):
    user_id: int
    starts: float
    ends: float
    store_id: int = 0
    note: str = ""
    published: bool = False


def _fits(con, uid: int, starts: float, ends: float) -> bool:
    """Is this inside something the person said they could do?

    A soft check, deliberately: the answer is shown to whoever is
    rostering rather than enforced, because a rota that refuses to let a
    manager ask is a rota that gets kept in a spreadsheet instead.
    """
    lt = time.localtime(starts)
    lte = time.localtime(ends)
    a_min = lt.tm_hour * 60 + lt.tm_min
    b_min = lte.tm_hour * 60 + lte.tm_min
    if b_min <= a_min:
        b_min = 24 * 60
    rows = con.execute("SELECT from_min, to_min FROM availability"
                       " WHERE user_id=? AND weekday=?",
                       (uid, lt.tm_wday)).fetchall()
    if not rows:
        return False
    return any(r["from_min"] <= a_min and b_min <= r["to_min"] for r in rows)


@router.get("/api/schedule")
def schedule(from_ts: float = 0, to_ts: float = 0,
             user=Depends(current_user), con=Depends(get_con)):
    """The rota. Everybody sees what is published; whoever rosters sees
    the draft as well, marked as one."""
    a = from_ts or (_week_start(time.time()))
    b = to_ts or (a + 14 * 86400)
    office = _office(user)
    q = ("SELECT s.*, u.name, st.name AS store FROM scheduled_shifts s"
         " JOIN users u ON u.id=s.user_id"
         " LEFT JOIN stores st ON st.id=s.store_id"
         " WHERE s.starts>=? AND s.starts<?")
    args = [a, b]
    if not office:
        q += " AND (s.published=1 OR s.user_id=?)"
        args.append(user["id"])
    rows = [dict(r) for r in con.execute(q + " ORDER BY s.starts", args)]
    for r in rows:
        r["fits"] = _fits(con, r["user_id"], r["starts"], r["ends"])
    people = [dict(p) for p in con.execute(
        "SELECT id, name FROM users WHERE active=1 AND"
        " (is_admin=1 OR role IN ('employee','owner','teacher','volunteer'))"
        " ORDER BY name")] if office else []
    return {"from": a, "to": b, "shifts": rows, "people": people,
            "office": office, "me": user["id"]}


@router.post("/api/schedule")
def plan_shift(body: ShiftPlanBody, user=Depends(current_user),
               con=Depends(get_con)):
    _require_office(user)
    if body.ends <= body.starts:
        raise HTTPException(400, "a shift cannot end before it starts")
    cur = con.execute(
        "INSERT INTO scheduled_shifts(user_id,starts,ends,store_id,note,"
        " published,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (body.user_id, body.starts, body.ends, body.store_id,
         body.note.strip()[:200], 1 if body.published else 0,
         user["name"], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid,
            "fits": _fits(con, body.user_id, body.starts, body.ends)}


@router.delete("/api/schedule/{sid}")
def unplan_shift(sid: int, user=Depends(current_user), con=Depends(get_con)):
    _require_office(user)
    con.execute("DELETE FROM scheduled_shifts WHERE id=?", (sid,))
    con.commit()
    return {"ok": True}


class PublishBody(BaseModel):
    from_ts: float
    to_ts: float
    published: bool = True


@router.post("/api/schedule/publish")
def publish_schedule(body: PublishBody, user=Depends(current_user),
                     con=Depends(get_con)):
    """Put the rota on the wall, or take it back down.

    Drafted first on purpose: a rota half-built is not a promise anybody
    should be arranging childcare around, and publishing is the moment it
    becomes one.
    """
    _require_office(user)
    cur = con.execute(
        "UPDATE scheduled_shifts SET published=? WHERE starts>=? AND starts<?",
        (1 if body.published else 0, body.from_ts, body.to_ts))
    con.commit()
    if body.published:
        from . import notify
        for r in con.execute(
                "SELECT DISTINCT user_id FROM scheduled_shifts"
                " WHERE published=1 AND starts>=? AND starts<?",
                (body.from_ts, body.to_ts)).fetchall():
            try:
                notify.push(con, "Your shifts are up",
                            "The rota for this period has been published.",
                            kind="achievement", user_id=r["user_id"])
            except Exception:                                # noqa: BLE001
                pass
    return {"ok": True, "changed": cur.rowcount}
