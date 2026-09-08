"""Appointments: a thing you buy that happens at a time.

A grooming slot, a fitting, an hour in a studio. The shop already sells
courses that way — buying the product enrols you, the course owns a
nullable product_id and products know nothing about it — and this is
the same rail with a clock on it.

Three things make a slot free, and a service can need any of them:

  a person   the groomer's rota, via timesheet.free_windows(), minus
             appointments they already hold
  a room     the grooming table, via room_bookings and the same clashes()
             check the classroom timetable uses
  a count    N at a time, for a service with no named resource

They are ANDed. A service that names a room and two groomers is free
when the room is free and at least one of the two is.

The walk to checkout is the awkward bit. Between "I'll take 2:30" and
the order landing there is a form, maybe a card, maybe a confirmation
email — minutes in which somebody else can take 2:30. So a slot is HELD
first, for a short while, keyed to the visitor rather than to an order
that does not exist yet; the order confirms it at placement, beside
enroll_by_order, in the same transaction. A hold that never becomes an
order simply expires. Nothing is booked by a page somebody closed.

What this deliberately is not: a calendar for staff (the rota is), a
timetable for classes (rooms.py is), or a queue. It is the customer's
side of one appointment, and the shop's view of who is coming.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import admin_user, get_con
from .api import current_customer as _customer

router = APIRouter()

HOLD_SECS = 15 * 60          # long enough to pay, short enough to matter
STATES = ("held", "confirmed", "cancelled", "done", "no_show")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

TABLES = """
CREATE TABLE IF NOT EXISTS bookable_services (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  product_id INTEGER DEFAULT 0,        -- 0 = not sold, staff-booked only
  duration_min INTEGER NOT NULL DEFAULT 60,
  buffer_min INTEGER NOT NULL DEFAULT 0,   -- turnaround after each one
  capacity INTEGER NOT NULL DEFAULT 1,     -- at once, per slot
  room_id INTEGER DEFAULT 0,               -- 0 = no room needed
  staff_ids TEXT DEFAULT '[]',             -- JSON; [] = nobody needed
  days TEXT DEFAULT '[1,1,1,1,1,0,0]',     -- JSON, mon..sun
  from_min INTEGER NOT NULL DEFAULT 540,   -- 09:00
  to_min INTEGER NOT NULL DEFAULT 1020,    -- 17:00
  step_min INTEGER NOT NULL DEFAULT 0,     -- 0 = duration + buffer
  lead_hours INTEGER NOT NULL DEFAULT 2,   -- no slot sooner than this
  horizon_days INTEGER NOT NULL DEFAULT 30,
  blurb TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY,
  service_id INTEGER NOT NULL,
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  staff_id INTEGER DEFAULT 0,
  room_id INTEGER DEFAULT 0,
  user_id INTEGER DEFAULT 0,
  visitor_id TEXT DEFAULT '',
  order_id INTEGER DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'held',
  held_until REAL DEFAULT 0,
  name TEXT DEFAULT '',
  email TEXT DEFAULT '',
  note TEXT DEFAULT '',
  source TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS appt_when ON appointments(starts, ends);
CREATE INDEX IF NOT EXISTS appt_staff ON appointments(staff_id, starts);
CREATE INDEX IF NOT EXISTS appt_order ON appointments(order_id);

-- What the shop needs to know before the appointment, answered at
-- booking. ROWS, not a blob: "which dogs are reactive" has to be a
-- query, and a JSON column makes it a grep.
CREATE TABLE IF NOT EXISTS appointment_answers (
  appointment_id INTEGER NOT NULL,
  q_key TEXT NOT NULL,
  label TEXT NOT NULL,
  answer TEXT DEFAULT '',
  PRIMARY KEY (appointment_id, q_key)
);
"""

INTAKE_KINDS = ("text", "long", "number", "yesno", "choice")
MAX_QUESTIONS = 20


def init_tables(con) -> None:
    con.executescript(TABLES)
    try:
        con.execute("ALTER TABLE bookable_services ADD COLUMN intake TEXT"
                    " DEFAULT '[]'")
    except Exception:                                        # noqa: BLE001
        pass                                # already there


def _questions(s) -> list:
    """The service's intake questions, in a shape the rest can trust."""
    try:
        raw = json.loads(s["intake"] or "[]")
    except (ValueError, TypeError, KeyError, IndexError):
        return []
    out = []
    for q in raw if isinstance(raw, list) else []:
        if not isinstance(q, dict) or not str(q.get("label", "")).strip():
            continue
        kind = q.get("kind", "text")
        out.append({"key": str(q.get("key") or "")[:40] or f"q{len(out) + 1}",
                    "label": str(q["label"]).strip()[:160],
                    "kind": kind if kind in INTAKE_KINDS else "text",
                    "required": bool(q.get("required")),
                    "choices": [str(c).strip()[:60] for c in
                                (q.get("choices") or []) if str(c).strip()][:12],
                    "help": str(q.get("help") or "").strip()[:200]})
    return out[:MAX_QUESTIONS]


def _clean_questions(qs: list) -> list:
    """What a shop typed into the form, made safe and keyed. Keys are
    minted from position when absent so an edit that reorders questions
    keeps old answers matched to old questions by key, not by slot."""
    out, seen = [], set()
    for i, q in enumerate(qs or []):
        if not isinstance(q, dict):
            continue
        label = str(q.get("label", "")).strip()
        if not label:
            continue
        key = str(q.get("key") or "").strip()[:40]
        if not key or key in seen:
            key = f"q{i + 1}"
            while key in seen:
                key += "_"
        seen.add(key)
        kind = q.get("kind", "text")
        if kind not in INTAKE_KINDS:
            raise HTTPException(400, f"question kind is one of {INTAKE_KINDS}")
        choices = [str(c).strip()[:60] for c in (q.get("choices") or [])
                   if str(c).strip()][:12]
        if kind == "choice" and len(choices) < 2:
            raise HTTPException(400, f"'{label[:40]}' needs at least two "
                                     "choices")
        out.append({"key": key, "label": label[:160], "kind": kind,
                    "required": bool(q.get("required")), "choices": choices,
                    "help": str(q.get("help") or "").strip()[:200]})
    if len(out) > MAX_QUESTIONS:
        raise HTTPException(400, f"{MAX_QUESTIONS} questions is plenty — a "
                                 "form nobody finishes is a booking nobody "
                                 "makes")
    return out


def answers_of(con, aid: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT q_key AS key, label, answer FROM appointment_answers"
        " WHERE appointment_id=? ORDER BY rowid", (aid,))]


def intake_missing(con, aid: int) -> list:
    """Required questions with no answer yet — the reason an order may
    not go through, said as a list rather than a bool so the message can
    name them."""
    a = con.execute("SELECT service_id FROM appointments WHERE id=?",
                    (aid,)).fetchone()
    if a is None:
        return []
    s = _svc(con, a["service_id"])
    have = {r["key"]: r["answer"] for r in answers_of(con, aid)}
    return [q["label"] for q in _questions(s)
            if q["required"] and not str(have.get(q["key"], "")).strip()]


def _store_answers(con, aid: int, service, answers: dict) -> list:
    """Validate against the questions and write the rows. Unknown keys
    are dropped — an answer to a question the service does not ask is
    not a fact about the appointment."""
    qs = _questions(service)
    written = []
    for q in qs:
        v = answers.get(q["key"])
        if v is None:
            continue
        v = str(v).strip()[:2000]
        if q["kind"] == "number" and v:
            try:
                float(v)
            except ValueError:
                raise HTTPException(400, f"'{q['label']}' wants a number")
        if q["kind"] == "yesno" and v and v.lower() not in ("yes", "no"):
            raise HTTPException(400, f"'{q['label']}' is yes or no")
        if q["kind"] == "choice" and v and v not in q["choices"]:
            raise HTTPException(400, f"'{q['label']}' is one of "
                                     f"{', '.join(q['choices'])}")
        con.execute("INSERT INTO appointment_answers(appointment_id,q_key,"
                    "label,answer) VALUES(?,?,?,?) ON CONFLICT(appointment_id,"
                    "q_key) DO UPDATE SET answer=excluded.answer,"
                    " label=excluded.label", (aid, q["key"], q["label"], v))
        written.append(q["key"])
    return written


# ---------- reading a service ----------

def _svc(con, sid: int):
    s = con.execute("SELECT * FROM bookable_services WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "no such service")
    return s


def _staff_ids(s) -> list:
    try:
        return [int(x) for x in json.loads(s["staff_ids"] or "[]")]
    except (ValueError, TypeError):
        return []


def _days(s) -> list:
    try:
        d = json.loads(s["days"] or "[]")
        return [bool(x) for x in d][:7] + [False] * (7 - len(d))
    except (ValueError, TypeError):
        return [True] * 5 + [False, False]


def _shape(con, s) -> dict:
    d = dict(s)
    d["staff_ids"] = _staff_ids(s)
    d["days"] = _days(s)
    d["staff"] = [dict(r) for r in con.execute(
        f"SELECT id, name FROM users WHERE id IN"
        f" ({','.join('?' * len(d['staff_ids']))})", d["staff_ids"])] \
        if d["staff_ids"] else []
    r = con.execute("SELECT name FROM rooms WHERE id=?",
                    (d["room_id"],)).fetchone() if d["room_id"] else None
    d["room"] = r["name"] if r else ""
    p = con.execute("SELECT name, price_cents FROM products WHERE id=?",
                    (d["product_id"],)).fetchone() if d["product_id"] else None
    d["product"] = p["name"] if p else ""
    d["price_cents"] = p["price_cents"] if p else 0
    d["intake"] = _questions(s)
    return d


def _live(con, at: float | None = None) -> None:
    """Holds that ran out are not appointments. Swept on read rather than
    by a timer, so nothing depends on a process that might not be
    running — a hold is checked the moment somebody asks about the
    slot, which is the only moment it matters."""
    con.execute("UPDATE appointments SET state='cancelled',"
                " note=CASE WHEN note='' THEN 'hold expired' ELSE note END"
                " WHERE state='held' AND held_until < ?", (at or time.time(),))


def _taken(con, service, starts: float, ends: float,
           ignore: int = 0) -> dict:
    """What already holds any of that stretch, by the three things a
    slot can be made of. Strict inequality, so touching is not
    overlapping — same rule as the classroom timetable, for the same
    reason: back-to-back must be bookable."""
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM appointments WHERE state IN ('held','confirmed')"
        " AND id!=? AND starts < ? AND ends > ?",
        (ignore, ends, starts))]
    same = [r for r in rows if r["service_id"] == service["id"]]
    by_staff: dict = {}
    for r in rows:
        if r["staff_id"]:
            by_staff.setdefault(r["staff_id"], []).append(r)
    room_busy = []
    if service["room_id"]:
        room_busy = [r for r in rows if r["room_id"] == service["room_id"]]
        try:
            from erp.backend import rooms as _rooms
            room_busy += _rooms.clashes(con, service["room_id"], starts, ends)
        except Exception:                                    # noqa: BLE001
            pass
    return {"same": same, "by_staff": by_staff, "room": room_busy}


def _free_staff(con, service, starts: float, ends: float,
                taken: dict, prefer: int = 0) -> int | None:
    """Which of the service's people can take it, or None. `prefer` is
    a customer asking for somebody by name; honoured if they are free,
    otherwise the answer is honest rather than a substitute."""
    ids = _staff_ids(service)
    if not ids:
        return 0                          # nobody needed; 0 = unassigned
    order = ([prefer] if prefer in ids else []) + [i for i in ids
                                                  if i != prefer]
    if prefer and prefer not in ids:
        return None
    from erp.backend import timesheet as _ts
    a_min = _min_of(starts)
    b_min = _min_of(ends) or 24 * 60
    for uid in order:
        if taken["by_staff"].get(uid):
            continue
        try:
            fw = _ts.free_windows(con, uid, starts)
        except Exception:                                    # noqa: BLE001
            fw = {"said": False, "windows": []}
        # Somebody who never said their hours is not thereby free at
        # 3am. Their working day is the service's window until they
        # say otherwise.
        windows = fw["windows"] if fw["said"] else \
            [(service["from_min"], service["to_min"])]
        if any(a <= a_min and b_min <= b for a, b in windows):
            return uid
        if prefer == uid:
            return None
    return None


def _min_of(ts: float) -> int:
    lt = time.localtime(ts)
    return lt.tm_hour * 60 + lt.tm_min


def _midnight(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0,
                        0, 0, -1))


def _at_minute(day_ts: float, minute: int) -> float:
    """A wall-clock minute on a day, through mktime, so a slot at 14:30
    is at 14:30 on the day the clocks change too."""
    lt = time.localtime(day_ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                        minute // 60, minute % 60, 0, 0, 0, -1))


def slots(con, service, day_ts: float, prefer_staff: int = 0,
          now: float | None = None) -> list:
    """Every start on that day a customer may take, and why the rest
    cannot be. The refusals ride along because a page of greyed-out
    times with no reason is a page somebody rings up about."""
    now = now or time.time()
    _live(con, now)
    out = []
    if not _days(service)[time.localtime(day_ts).tm_wday]:
        return out
    dur = service["duration_min"] * 60
    step = (service["step_min"] or
            service["duration_min"] + service["buffer_min"]) * 60
    earliest = now + service["lead_hours"] * 3600
    latest = now + service["horizon_days"] * 86400
    m = service["from_min"]
    while m + service["duration_min"] <= service["to_min"]:
        starts = _at_minute(day_ts, m)
        ends = starts + dur
        m += max(5, step // 60)
        if starts < earliest or starts > latest:
            continue
        taken = _taken(con, service, starts,
                       ends + service["buffer_min"] * 60)
        if len(taken["same"]) >= service["capacity"]:
            out.append({"starts": starts, "ends": ends, "free": False,
                        "why": "full"})
            continue
        if taken["room"]:
            out.append({"starts": starts, "ends": ends, "free": False,
                        "why": "room taken"})
            continue
        who = _free_staff(con, service, starts, ends, taken, prefer_staff)
        if who is None:
            out.append({"starts": starts, "ends": ends, "free": False,
                        "why": "nobody free"})
            continue
        out.append({"starts": starts, "ends": ends, "free": True,
                    "staff_id": who})
    return out


# ---------- what the shop sells ----------

@router.get("/api/store/services")
def public_services(con=Depends(get_con)):
    """The bookable things, with the product each one is sold as."""
    _live(con)
    con.commit()
    return {"services": [
        {k: v for k, v in _shape(con, s).items()
         if k not in ("staff_ids", "created_at")}
        for s in con.execute("SELECT * FROM bookable_services WHERE active=1"
                             " ORDER BY name")]}


@router.get("/api/store/services/{sid}/slots")
def public_slots(sid: int, day: float = 0, days: int = 1, staff_id: int = 0,
                 con=Depends(get_con)):
    """Starts a customer may take, one day or a run of them. `day` is any
    moment in the day wanted; the whole day comes back."""
    s = _svc(con, sid)
    if not s["active"]:
        raise HTTPException(404, "not taking bookings")
    day = day or time.time()
    out = []
    for i in range(max(1, min(14, days))):
        d = _midnight(day) + i * 86400 + 12 * 3600    # noon, DST-safe
        got = slots(con, s, d, staff_id)
        out.append({"day": _midnight(d), "slots": got,
                    "free": sum(1 for x in got if x["free"])})
    con.commit()
    return {"service": {"id": s["id"], "name": s["name"],
                        "duration_min": s["duration_min"]},
            "days": out,
            "note": "A slot is held for fifteen minutes once chosen and "
                    "is yours when the order goes through."}


class HoldBody(BaseModel):
    service_id: int
    starts: float
    staff_id: int = 0
    visitor_id: str = ""
    name: str = ""
    email: str = ""
    note: str = ""


@router.post("/api/store/appointments/hold")
def hold(body: HoldBody, con=Depends(get_con)):
    """Take a slot for a quarter of an hour, in the visitor's name.

    Not the order's name, because there is no order yet, and not the
    account's, because the checkout signs people in at the END. The
    visitor id is the one thing the browser already carries the whole
    way through. Re-holding from the same visitor replaces their
    earlier hold rather than stacking a second one.
    """
    s = _svc(con, body.service_id)
    if not s["active"]:
        raise HTTPException(409, f"{s['name']} is not taking bookings")
    now = time.time()
    _live(con, now)
    if body.starts < now + s["lead_hours"] * 3600 - 60:
        raise HTTPException(409, f"{s['name']} needs {s['lead_hours']} "
                                 f"hours' notice")
    ends = body.starts + s["duration_min"] * 60
    if body.visitor_id:
        con.execute("UPDATE appointments SET state='cancelled',"
                    " note='replaced by a later choice'"
                    " WHERE state='held' AND visitor_id=? AND service_id=?",
                    (body.visitor_id, s["id"]))
    taken = _taken(con, s, body.starts, ends + s["buffer_min"] * 60)
    if len(taken["same"]) >= s["capacity"]:
        raise HTTPException(409, "that time has just been taken")
    if taken["room"]:
        raise HTTPException(409, f"{s['name']} — the room is booked then")
    who = _free_staff(con, s, body.starts, ends, taken, body.staff_id)
    if who is None:
        raise HTTPException(409, "nobody is free at that time")
    cur = con.execute(
        "INSERT INTO appointments(service_id,starts,ends,staff_id,room_id,"
        "visitor_id,state,held_until,name,email,note,source,created_at)"
        " VALUES(?,?,?,?,?,?,'held',?,?,?,?,'store',?)",
        (s["id"], body.starts, ends, who, s["room_id"] or 0,
         (body.visitor_id or "")[:64], now + HOLD_SECS,
         body.name.strip()[:80], body.email.strip()[:120],
         body.note.strip()[:500], now))
    con.commit()
    staff = con.execute("SELECT name FROM users WHERE id=?",
                        (who,)).fetchone() if who else None
    return {"ok": True, "appointment_id": cur.lastrowid,
            "starts": body.starts, "ends": ends,
            "staff": staff["name"] if staff else "",
            "held_until": now + HOLD_SECS,
            "product_id": s["product_id"],
            "intake": _questions(s),
            "note": f"Held until {time.strftime('%H:%M', time.localtime(now + HOLD_SECS))} "
                    f"— finish the order to keep it."}


@router.delete("/api/store/appointments/hold/{aid}")
def release(aid: int, visitor_id: str = "", con=Depends(get_con)):
    """Give a held slot back. Only the visitor who took it may."""
    con.execute("UPDATE appointments SET state='cancelled', note='released'"
                " WHERE id=? AND state='held' AND visitor_id=?",
                (aid, visitor_id))
    con.commit()
    return {"ok": True}


class IntakeBody(BaseModel):
    visitor_id: str = ""
    answers: dict = {}


def _own_hold(con, aid: int, visitor_id: str, user=None):
    a = con.execute("SELECT * FROM appointments WHERE id=?", (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such appointment")
    owner = (a["state"] == "held" and visitor_id and a["visitor_id"] == visitor_id) \
        or (user is not None and a["user_id"] == user["id"])
    if not owner:
        raise HTTPException(403, "that appointment is not yours")
    return a


@router.post("/api/store/appointments/{aid}/intake")
def intake(aid: int, body: IntakeBody, con=Depends(get_con)):
    """The answers, from the visitor who holds the slot. Asked after the
    time is held rather than before, because a form is a reason to
    leave and a held time is a reason to stay."""
    a = _own_hold(con, aid, body.visitor_id)
    s = _svc(con, a["service_id"])
    _store_answers(con, aid, s, body.answers or {})
    con.commit()
    missing = intake_missing(con, aid)
    return {"ok": True, "missing": missing,
            "complete": not missing, "answers": answers_of(con, aid)}


@router.get("/api/store/appointments/{aid}/intake")
def intake_get(aid: int, visitor_id: str = "", con=Depends(get_con)):
    a = _own_hold(con, aid, visitor_id)
    s = _svc(con, a["service_id"])
    return {"questions": _questions(s), "answers": answers_of(con, aid),
            "missing": intake_missing(con, aid)}


def book_by_order(con, order_id: int, user_id: int, item_holds: dict,
                  visitor_id: str = "") -> list:
    """The order lands; the holds it carries become appointments.

    Called from order placement beside enroll_by_order, in the same
    transaction, so a paid order and its slot cannot part company. The
    holds are matched by id and must still be held and still belong to
    the visitor who took them — a hold id typed into somebody else's
    order is not their appointment.

    Returns what was booked, in words, for the notification.
    """
    out = []
    now = time.time()
    for pid, aid in item_holds.items():
        a = con.execute("SELECT a.*, s.name AS service FROM appointments a"
                        " JOIN bookable_services s ON s.id=a.service_id"
                        " WHERE a.id=?", (aid,)).fetchone()
        if a is None or a["state"] != "held":
            raise HTTPException(409, "your held time has run out — pick "
                                     "another and try again")
        if visitor_id and a["visitor_id"] and a["visitor_id"] != visitor_id:
            raise HTTPException(409, "that held time is not yours")
        if a["service_id"] and con.execute(
                "SELECT product_id FROM bookable_services WHERE id=?",
                (a["service_id"],)).fetchone()["product_id"] != pid:
            raise HTTPException(400, "that time belongs to a different "
                                     "service")
        missing = intake_missing(con, aid)
        if missing:
            raise HTTPException(400, f"{a['service']} still needs: "
                                     + "; ".join(missing))
        con.execute(
            "UPDATE appointments SET state='confirmed', order_id=?,"
            " user_id=?, held_until=0, source=? WHERE id=?",
            (order_id, user_id, f"order:{order_id}", aid))
        out.append(f"{a['service']} at "
                   f"{time.strftime('%a %d %b %H:%M', time.localtime(a['starts']))}")
    return out


def extend_holds(con, item_holds: dict, until: float,
                 visitor_id: str = "") -> None:
    """An order parked for email confirmation may sit for days, and a
    fifteen-minute hold would be long gone by the time it is confirmed —
    the customer would do everything right and lose the slot hours
    later, from an email they were told to expect. So parking the order
    extends the hold to the parking window. The slot shows as held in
    the shop's list the whole time, which is true: a person is
    mid-checkout, just slowly."""
    for aid in item_holds.values():
        a = con.execute("SELECT state, visitor_id FROM appointments"
                        " WHERE id=?", (aid,)).fetchone()
        if a is None or a["state"] != "held":
            raise HTTPException(409, "your held time has run out — pick "
                                     "another and try again")
        if visitor_id and a["visitor_id"] and a["visitor_id"] != visitor_id:
            raise HTTPException(409, "that held time is not yours")
        missing = intake_missing(con, aid)
        if missing:
            raise HTTPException(400, "still needs: " + "; ".join(missing))
        con.execute("UPDATE appointments SET held_until=? WHERE id=?",
                    (until, aid))


def holds_required(con, items) -> dict:
    """Which cart lines are services and so must carry a hold.
    {product_id: service_id} for every line that is one."""
    need = {}
    for it in items:
        s = con.execute("SELECT id FROM bookable_services WHERE product_id=?"
                        " AND active=1", (it.product_id,)).fetchone()
        if s:
            need[it.product_id] = s["id"]
    return need


# ---------- the customer's own ----------

@router.get("/api/store/account/appointments")
def my_appointments(con=Depends(get_con), user=Depends(_customer)):
    """What is coming, and what happened — the customer's own."""
    rows = _mine(con, user)
    con.commit()
    now = time.time()
    return {"appointments": rows,
            "upcoming": [r for r in rows if r["state"] == "confirmed"
                         and r["starts"] > now]}


def _mine(con, user) -> list:
    _live(con)
    rows = [dict(r) for r in con.execute(
        "SELECT a.id, a.starts, a.ends, a.state, a.order_id, a.note,"
        " s.name AS service, s.duration_min, COALESCE(u.name,'') AS staff,"
        " COALESCE(r.name,'') AS room FROM appointments a"
        " JOIN bookable_services s ON s.id=a.service_id"
        " LEFT JOIN users u ON u.id=a.staff_id"
        " LEFT JOIN rooms r ON r.id=a.room_id"
        " WHERE a.user_id=? AND a.state!='cancelled'"
        " ORDER BY a.starts DESC LIMIT 50", (user["id"],))]
    for r in rows:
        r["answers"] = answers_of(con, r["id"])
    return rows


# ---------- what the shop runs ----------

class ServiceBody(BaseModel):
    name: str = ""
    product_id: int = 0
    duration_min: int = 60
    buffer_min: int = 0
    capacity: int = 1
    room_id: int = 0
    staff_ids: list[int] = []
    days: list[bool] = [True, True, True, True, True, False, False]
    from_min: int = 540
    to_min: int = 1020
    step_min: int = 0
    lead_hours: int = 2
    horizon_days: int = 30
    blurb: str = ""
    active: bool = True
    intake: list = []


def _check(body: ServiceBody) -> None:
    if not body.name.strip():
        raise HTTPException(400, "a service needs a name")
    if body.duration_min < 5 or body.duration_min > 24 * 60:
        raise HTTPException(400, "duration is minutes, between 5 and a day")
    if body.to_min <= body.from_min:
        raise HTTPException(400, "it has to close after it opens")
    if body.capacity < 1:
        raise HTTPException(400, "capacity is at least one")
    if not any(body.days):
        raise HTTPException(400, "pick at least one day it runs")


@router.get("/api/store/admin/services")
def list_services(user=Depends(admin_user), con=Depends(get_con)):
    _live(con)
    con.commit()
    rows = [_shape(con, s) for s in con.execute(
        "SELECT * FROM bookable_services ORDER BY active DESC, name")]
    for r in rows:
        r["upcoming"] = con.execute(
            "SELECT COUNT(*) FROM appointments WHERE service_id=? AND"
            " state='confirmed' AND starts>?", (r["id"], time.time())
        ).fetchone()[0]
    return {"services": rows,
            "note": "A service is sold as a product and happens at a time. "
                    "Name a room and it needs the room free; name people "
                    "and it needs one of them free; name neither and it "
                    "takes up to its capacity at once."}


@router.post("/api/store/admin/services")
def add_service(body: ServiceBody, user=Depends(admin_user),
                con=Depends(get_con)):
    _check(body)
    if body.product_id and con.execute(
            "SELECT 1 FROM products WHERE id=?", (body.product_id,)
    ).fetchone() is None:
        raise HTTPException(400, "no such product")
    qs = _clean_questions(body.intake)
    cur = con.execute(
        "INSERT INTO bookable_services(name,product_id,duration_min,"
        "buffer_min,capacity,room_id,staff_ids,days,from_min,to_min,"
        "step_min,lead_hours,horizon_days,blurb,active,intake,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.name.strip()[:120], body.product_id, body.duration_min,
         max(0, body.buffer_min), body.capacity, body.room_id,
         json.dumps(body.staff_ids), json.dumps(body.days[:7]),
         body.from_min, body.to_min, max(0, body.step_min),
         max(0, body.lead_hours), max(1, body.horizon_days),
         body.blurb.strip()[:400], 1 if body.active else 0,
         json.dumps(qs), time.time()))
    if body.product_id:
        # The product IS a service now, so the shelf files it as one
        # and the cart knows not to ship it.
        con.execute("INSERT OR IGNORE INTO product_kinds(id,label,colour,"
                    "note,position,created_at) VALUES('service','Bookings',"
                    "'#0d8f7a','things that happen at a time',50,?)",
                    (time.time(),))
        con.execute("INSERT OR REPLACE INTO store_product_meta(product_id,"
                    "k,v) VALUES(?,'kind','service')", (body.product_id,))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/store/admin/services/{sid}")
def edit_service(sid: int, body: ServiceBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    _svc(con, sid)
    _check(body)
    qs = _clean_questions(body.intake)
    con.execute(
        "UPDATE bookable_services SET name=?,product_id=?,duration_min=?,"
        "buffer_min=?,capacity=?,room_id=?,staff_ids=?,days=?,from_min=?,"
        "to_min=?,step_min=?,lead_hours=?,horizon_days=?,blurb=?,active=?,"
        "intake=? WHERE id=?",
        (body.name.strip()[:120], body.product_id, body.duration_min,
         max(0, body.buffer_min), body.capacity, body.room_id,
         json.dumps(body.staff_ids), json.dumps(body.days[:7]),
         body.from_min, body.to_min, max(0, body.step_min),
         max(0, body.lead_hours), max(1, body.horizon_days),
         body.blurb.strip()[:400], 1 if body.active else 0,
         json.dumps(qs), sid))
    if body.product_id:
        con.execute("INSERT OR REPLACE INTO store_product_meta(product_id,"
                    "k,v) VALUES(?,'kind','service')", (body.product_id,))
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/appointments")
def list_appointments(days: int = 14, past: int = 0,
                      user=Depends(admin_user), con=Depends(get_con)):
    """Who is coming, in order. Confirmed ones, and the holds still
    ticking — a hold is a person mid-checkout, worth knowing about."""
    _live(con)
    con.commit()
    now = time.time()
    lo = now - past * 86400
    hi = now + max(1, days) * 86400
    rows = [dict(r) for r in con.execute(
        "SELECT a.*, s.name AS service, COALESCE(u.name,'') AS staff,"
        " COALESCE(r.name,'') AS room, COALESCE(c.name,'') AS customer,"
        " COALESCE(c.email,'') AS customer_email FROM appointments a"
        " JOIN bookable_services s ON s.id=a.service_id"
        " LEFT JOIN users u ON u.id=a.staff_id"
        " LEFT JOIN rooms r ON r.id=a.room_id"
        " LEFT JOIN users c ON c.id=a.user_id"
        " WHERE a.state IN ('held','confirmed','done','no_show')"
        " AND a.starts>=? AND a.starts<? ORDER BY a.starts", (lo, hi))]
    for r in rows:
        r["who"] = r["customer"] or r["name"] or "(no name)"
        r["email"] = r["customer_email"] or r["email"]
        r["answers"] = answers_of(con, r["id"])
        r["missing"] = intake_missing(con, r["id"]) if r["state"] == "held" else []
    return {"appointments": rows, "days": days,
            "today": sum(1 for r in rows if r["state"] == "confirmed"
                         and _midnight(r["starts"]) == _midnight(now))}


class StateBody(BaseModel):
    state: str
    note: str = ""


@router.post("/api/store/admin/appointments/{aid}/state")
def set_state(aid: int, body: StateBody, user=Depends(admin_user),
              con=Depends(get_con)):
    """done, no_show, cancelled — the three things a shop says about an
    appointment after the fact. Cancelling frees the slot; nothing is
    deleted, because who did not turn up is a fact worth keeping."""
    if body.state not in ("done", "no_show", "cancelled", "confirmed"):
        raise HTTPException(400, "state is done, no_show, cancelled or "
                                 "confirmed")
    a = con.execute("SELECT * FROM appointments WHERE id=?",
                    (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such appointment")
    con.execute("UPDATE appointments SET state=?, note=? WHERE id=?",
                (body.state, body.note.strip()[:500] or a["note"], aid))
    con.commit()
    return {"ok": True}


class StaffBookBody(BaseModel):
    service_id: int
    starts: float
    staff_id: int = 0
    name: str = ""
    email: str = ""
    user_id: int = 0
    note: str = ""
    answers: dict = {}


@router.post("/api/store/admin/appointments")
def staff_book(body: StaffBookBody, user=Depends(admin_user),
               con=Depends(get_con)):
    """The phone rings. Somebody books on the customer's behalf, with no
    product and no order — confirmed straight away, because the person
    typing it is the shop."""
    s = _svc(con, body.service_id)
    now = time.time()
    _live(con, now)
    ends = body.starts + s["duration_min"] * 60
    taken = _taken(con, s, body.starts, ends + s["buffer_min"] * 60)
    if len(taken["same"]) >= s["capacity"]:
        raise HTTPException(409, "that time is full")
    if taken["room"]:
        raise HTTPException(409, "the room is booked then")
    who = _free_staff(con, s, body.starts, ends, taken, body.staff_id)
    if who is None:
        raise HTTPException(409, "nobody is free then")
    cur = con.execute(
        "INSERT INTO appointments(service_id,starts,ends,staff_id,room_id,"
        "user_id,state,name,email,note,source,created_at)"
        " VALUES(?,?,?,?,?,?,'confirmed',?,?,?,?,?)",
        (s["id"], body.starts, ends, who, s["room_id"] or 0, body.user_id,
         body.name.strip()[:80], body.email.strip()[:120],
         body.note.strip()[:500], f"staff:{user['id']}", now))
    # Taken down over the phone rather than typed by the customer; the
    # required ones are not enforced here, because "she'll tell us on
    # the day" is an answer the shop is allowed to accept from itself.
    _store_answers(con, cur.lastrowid, s, body.answers or {})
    con.commit()
    return {"ok": True, "id": cur.lastrowid, "staff_id": who,
            "missing": intake_missing(con, cur.lastrowid)}
