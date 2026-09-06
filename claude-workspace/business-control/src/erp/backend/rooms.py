"""Rooms, and who has them when.

A class had a teacher, a course and a start time, and no place. That is
fine right up until two of them want the same four walls at six o'clock
on a Tuesday, which is a conversation every school has had and no
software here could help with.

A room is a place inside a location: Studio 2 at the Camden shop. A
booking is a room, a stretch of time, and a reason — most often a course
that is about to be taught in it, sometimes a staff meeting, sometimes
the floor being sanded.

Three decisions worth stating, because each of them is a thing that
could reasonably have gone the other way.

Bookings are checked for overlap and refused, not warned about. A rota
that lets a manager ask is one thing; a room that says yes to two
classes is a room where thirty people stand in a corridor. The refusal
names the booking already there, because "no" without "because Anna has
it" is a message that sends somebody hunting.

A repeat is materialised into individual bookings rather than kept as a
rule. Ten Tuesdays is ten rows, so the fourth one can be cancelled for a
bank holiday without inventing an exceptions table, and so a person
reading next Tuesday sees what is actually true of next Tuesday.

And a booking is made before a class exists. A class here comes into
being when a teacher starts one; a timetable that could only show
classes already started would be a timetable of the past. So a booking
carries the course it is FOR, and picks up the session id when the class
actually begins — which is also what lets a screen in the room say
"scheduled, not started yet" rather than showing nothing.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db
from .main import current_user, get_con, permitted

router = APIRouter()

# A room is for something. The kind does not gate anything — it is what
# somebody calls it when they are looking down a list of eleven.
KINDS = ("classroom", "studio", "meeting", "hall", "other")

TABLES = """
CREATE TABLE IF NOT EXISTS rooms (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  store_id INTEGER DEFAULT 0,          -- the location it is inside
  kind TEXT NOT NULL DEFAULT 'classroom',
  seats INTEGER DEFAULT 0,             -- 0 = nobody has said
  note TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rooms_store ON rooms(store_id, active);

CREATE TABLE IF NOT EXISTS room_bookings (
  id INTEGER PRIMARY KEY,
  room_id INTEGER NOT NULL,
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  title TEXT DEFAULT '',               -- what it is, when it is not a course
  course_id INTEGER DEFAULT 0,         -- the course this is FOR
  session_id INTEGER DEFAULT 0,        -- the class, once it has begun
  teacher_id INTEGER DEFAULT 0,
  booked_by INTEGER DEFAULT 0,
  series TEXT DEFAULT '',              -- ties a repeat together
  state TEXT NOT NULL DEFAULT 'booked' -- booked | cancelled
    CHECK (state IN ('booked','cancelled')),
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS room_bookings_when
  ON room_bookings(room_id, starts, ends);
CREATE INDEX IF NOT EXISTS room_bookings_series ON room_bookings(series);
"""


def init_tables(con) -> None:
    con.executescript(TABLES)


def _room(con, rid: int):
    r = con.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such room")
    return r


def clashes(con, room_id: int, starts: float, ends: float,
            ignore: int = 0) -> list:
    """Bookings already holding any part of that stretch.

    Touching is not overlapping: a class ending at six and one starting
    at six are two bookings, not a clash, which is why this is strict
    inequality on both sides. Get that wrong and every timetable built
    back to back is unbookable.
    """
    return [dict(r) for r in con.execute(
        "SELECT b.*, COALESCE(u.name,'') AS teacher,"
        " COALESCE(c.name,'') AS course FROM room_bookings b"
        " LEFT JOIN users u ON u.id=b.teacher_id"
        " LEFT JOIN courses c ON c.id=b.course_id"
        " WHERE b.room_id=? AND b.state='booked' AND b.id!=?"
        " AND b.starts < ? AND b.ends > ?"
        " ORDER BY b.starts", (room_id, ignore, ends, starts))]


def _said(b: dict) -> str:
    """What a booking is, in the words somebody would use for it."""
    return (b.get("title") or b.get("course") or "").strip() or "a booking"


# ---------- rooms ----------

class RoomBody(BaseModel):
    name: str = ""
    store_id: int = 0
    kind: str = "classroom"
    seats: int = 0
    note: str = ""
    active: bool = True


@router.get("/api/rooms")
def list_rooms(store_id: int = 0, user=Depends(current_user),
               con=Depends(get_con)):
    where = " WHERE r.store_id=?" if store_id else ""
    args = (store_id,) if store_id else ()
    rows = [dict(r) for r in con.execute(
        "SELECT r.*, COALESCE(s.name,'') AS store FROM rooms r"
        " LEFT JOIN stores s ON s.id=r.store_id" + where +
        " ORDER BY r.active DESC, s.name, r.name", args)]
    now = db.now()
    for r in rows:
        # What is in it at this moment, which is the question anybody
        # standing in a corridor is actually asking.
        cur = con.execute(
            "SELECT b.*, COALESCE(c.name,'') AS course,"
            " COALESCE(u.name,'') AS teacher FROM room_bookings b"
            " LEFT JOIN courses c ON c.id=b.course_id"
            " LEFT JOIN users u ON u.id=b.teacher_id"
            " WHERE b.room_id=? AND b.state='booked'"
            " AND b.starts<=? AND b.ends>? LIMIT 1",
            (r["id"], now, now)).fetchone()
        r["now"] = dict(cur) if cur else None
        nxt = con.execute(
            "SELECT b.starts, COALESCE(c.name,'') AS course, b.title"
            " FROM room_bookings b LEFT JOIN courses c ON c.id=b.course_id"
            " WHERE b.room_id=? AND b.state='booked' AND b.starts>?"
            " ORDER BY b.starts LIMIT 1", (r["id"], now)).fetchone()
        r["next"] = dict(nxt) if nxt else None
    return {"rooms": rows, "kinds": list(KINDS)}


@router.post("/api/rooms")
def add_room(body: RoomBody, user=Depends(permitted("rooms")),
             con=Depends(get_con)):
    name = body.name.strip()[:80]
    if not name:
        raise HTTPException(400, "a room needs a name")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    cur = con.execute(
        "INSERT INTO rooms(name,store_id,kind,seats,note,active,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (name, max(0, body.store_id), body.kind, max(0, body.seats),
         body.note.strip()[:300], 1 if body.active else 0, db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/rooms/{rid}")
def edit_room(rid: int, body: RoomBody, user=Depends(permitted("rooms")),
              con=Depends(get_con)):
    _room(con, rid)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    con.execute(
        "UPDATE rooms SET name=?, store_id=?, kind=?, seats=?, note=?,"
        " active=? WHERE id=?",
        (body.name.strip()[:80] or "room", max(0, body.store_id), body.kind,
         max(0, body.seats), body.note.strip()[:300],
         1 if body.active else 0, rid))
    con.commit()
    return {"ok": True}


@router.delete("/api/rooms/{rid}")
def drop_room(rid: int, user=Depends(permitted("rooms")),
              con=Depends(get_con)):
    """A room with history is deactivated, not deleted.

    Deleting it would take the bookings with it, and last term's
    timetable is how somebody answers "where was that class" a month
    later.
    """
    _room(con, rid)
    n = con.execute("SELECT COUNT(*) AS n FROM room_bookings WHERE room_id=?",
                    (rid,)).fetchone()["n"]
    if n:
        con.execute("UPDATE rooms SET active=0 WHERE id=?", (rid,))
        con.commit()
        return {"ok": True, "archived": True, "bookings": n,
                "note": "It has been used, so it is switched off rather "
                        "than deleted — its bookings are the answer to "
                        "'where was that class'."}
    con.execute("DELETE FROM rooms WHERE id=?", (rid,))
    con.commit()
    return {"ok": True, "deleted": True}


# ---------- the timetable ----------

class BookBody(BaseModel):
    room_id: int = 0
    starts: float = 0
    ends: float = 0
    title: str = ""
    course_id: int = 0
    teacher_id: int = 0
    note: str = ""
    repeat_weeks: int = 0        # 0 = once. 10 = this one and nine more.


@router.get("/api/rooms/bookings")
def timetable(from_ts: float = 0, to_ts: float = 0, room_id: int = 0,
              user=Depends(current_user), con=Depends(get_con)):
    """Everything booked in a stretch of time, in the order it happens."""
    now = db.now()
    a = from_ts or (now - 86400)
    b = to_ts or (now + 14 * 86400)
    where = " AND b.room_id=?" if room_id else ""
    args = [a, b] + ([room_id] if room_id else [])
    rows = [dict(r) for r in con.execute(
        "SELECT b.*, r.name AS room, r.seats, r.store_id,"
        " COALESCE(s.name,'') AS store, COALESCE(c.name,'') AS course,"
        " COALESCE(u.name,'') AS teacher FROM room_bookings b"
        " JOIN rooms r ON r.id=b.room_id"
        " LEFT JOIN stores s ON s.id=r.store_id"
        " LEFT JOIN courses c ON c.id=b.course_id"
        " LEFT JOIN users u ON u.id=b.teacher_id"
        " WHERE b.ends>? AND b.starts<?" + where +
        " ORDER BY b.starts, r.name", args)]
    for r in rows:
        r["live"] = bool(r["session_id"]) and r["state"] == "booked"
        r["said"] = _said(r)
    return {"from": a, "to": b, "bookings": rows,
            "note": "A booking is made before its class exists — a class "
                    "here begins when a teacher starts one, so a "
                    "timetable of started classes would be a timetable of "
                    "the past."}


@router.post("/api/rooms/bookings")
def book(body: BookBody, user=Depends(permitted("rooms")),
         con=Depends(get_con)):
    room = _room(con, body.room_id)
    if not room["active"]:
        raise HTTPException(409, f"{room['name']} is switched off")
    if body.ends <= body.starts:
        raise HTTPException(400, "it has to end after it starts")
    if body.ends - body.starts > 24 * 3600:
        raise HTTPException(400, "a booking longer than a day is usually a "
                                 "typo in a date; make it a run of days")
    weeks = max(1, min(52, body.repeat_weeks or 1))
    made, refused = [], []
    for i in range(weeks):
        starts = _plus_weeks(body.starts, i)
        ends = starts + (body.ends - body.starts)
        hit = clashes(con, body.room_id, starts, ends)
        if hit:
            refused.append({"starts": starts, "taken_by": _said(hit[0]),
                            "by_whom": hit[0].get("teacher", "")})
            continue
        made.append((starts, ends))
    if not made:
        first = refused[0] if refused else {}
        raise HTTPException(
            409, f"{room['name']} is already taken then"
                 + (f" — {first.get('taken_by')}" if first else "")
                 + (f" ({first['by_whom']})" if first.get("by_whom") else "")
                 + ". Nothing was booked.")
    series = f"s{int(db.now() * 1000)}" if len(made) > 1 else ""
    ids = []
    for starts, ends in made:
        cur = con.execute(
            "INSERT INTO room_bookings(room_id,starts,ends,title,course_id,"
            "teacher_id,booked_by,series,note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body.room_id, starts, ends, body.title.strip()[:120],
             max(0, body.course_id), max(0, body.teacher_id), user["id"],
             series, body.note.strip()[:300], db.now()))
        ids.append(cur.lastrowid)
    con.commit()
    return {"ok": True, "ids": ids, "booked": len(ids),
            "series": series,
            # The weeks that could not be booked are named rather than
            # silently dropped: somebody asking for ten Tuesdays and
            # getting nine should be told which nine.
            "refused": refused,
            "note": (f"{len(ids)} booked"
                     + (f", {len(refused)} skipped — that room was already "
                        f"taken on those days" if refused else "")
                     + ".")}


@router.delete("/api/rooms/bookings/{bid}")
def cancel(bid: int, whole_series: int = 0,
           user=Depends(permitted("rooms")), con=Depends(get_con)):
    """Cancelled, not deleted: a room that was booked and given back is a
    different fact from a room nobody ever asked for, and only one of
    them explains why a class did not happen."""
    row = con.execute("SELECT * FROM room_bookings WHERE id=?",
                      (bid,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such booking")
    if whole_series and row["series"]:
        n = con.execute(
            "UPDATE room_bookings SET state='cancelled'"
            " WHERE series=? AND state='booked' AND starts>=?",
            (row["series"], db.now())).rowcount
    else:
        con.execute("UPDATE room_bookings SET state='cancelled' WHERE id=?",
                    (bid,))
        n = 1
    con.commit()
    return {"ok": True, "cancelled": n}


class AttachBody(BaseModel):
    session_id: int = 0


@router.post("/api/rooms/bookings/{bid}/session")
def attach(bid: int, body: AttachBody, user=Depends(permitted("rooms")),
           con=Depends(get_con)):
    """Tie a class that has just started to the slot it was booked into.

    This is the join that makes a room screen able to say the difference
    between "due at six" and "started, they are in there now".
    """
    row = con.execute("SELECT * FROM room_bookings WHERE id=?",
                      (bid,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such booking")
    con.execute("UPDATE room_bookings SET session_id=? WHERE id=?",
                (max(0, body.session_id), bid))
    con.commit()
    return {"ok": True}


def _capturing(con, session_id: int) -> bool:
    """Is this class actually being recorded, right now.

    Not "does it have a video room" — that is a different claim, and a
    screen that says RECORDING because a room id exists is a screen that
    lies to a class about being on tape. The SFU writes segments as it
    forwards, so a directory with something recent in it is the honest
    answer, and no answer at all is False.
    """
    if not session_id:
        return False
    try:
        import glob
        import os
        from . import services, tenancy
        s = services.service("sfu")
        rec = (s or {}).get("record_dir") or ""
        row = con.execute("SELECT room FROM class_sessions WHERE id=?",
                          (session_id,)).fetchone()
        room = (row["room"] if row else "") or ""
        if not (rec and room):
            return False
        tid = tenancy.CURRENT.get() or "default"
        cut = time.time() - 300          # something written in five minutes
        for f in glob.glob(os.path.join(rec, f"bc-{tid}-{room}-*", "*")):
            try:
                if os.path.getmtime(f) > cut:
                    return True
            except OSError:
                continue
    except Exception:                                        # noqa: BLE001
        return False
    return False


@router.get("/api/rooms/{rid}/display")
def display(rid: int, con=Depends(get_con)):
    """What a screen on the wall of this room should say.

    Deliberately open, like the enrolment claim: this is a screen bolted
    to a wall in a corridor, and putting a login between it and the
    timetable means somebody signs a tablet in as an owner and leaves it
    that way, which is a worse thing to have in a corridor than a
    timetable anybody could have read on the door.

    It says the room, what is in it, and what is next. Nothing else is on
    it — no register, no roster, no names of children — because a screen
    in a corridor is read by whoever walks past.
    """
    room = _room(con, rid)
    now = db.now()

    def one(extra, args):
        r = con.execute(
            "SELECT b.starts, b.ends, b.title, b.session_id,"
            " COALESCE(c.name,'') AS course, COALESCE(u.name,'') AS teacher,"
            # A session id on the booking says a class was started, not
            # that one is running. A wall reading "in progress" twenty
            # minutes after everybody left is worse than a blank one:
            # it is the screen being confidently wrong in a corridor.
            " COALESCE(cs.status,'') AS class_state"
            " FROM room_bookings b"
            " LEFT JOIN courses c ON c.id=b.course_id"
            " LEFT JOIN users u ON u.id=b.teacher_id"
            " LEFT JOIN class_sessions cs ON cs.id=b.session_id"
            " WHERE b.room_id=? AND b.state='booked'" + extra,
            args).fetchone()
        if not r:
            return None
        d = dict(r)
        d["said"] = _said(d)
        d["started"] = d["class_state"] == "open"
        d["finished"] = d["class_state"] in ("closed", "cancelled")
        d["recording"] = (_capturing(con, d["session_id"] or 0)
                          if d["started"] else False)
        return d

    cur = one(" AND b.starts<=? AND b.ends>? LIMIT 1", (rid, now, now))
    nxt = one(" AND b.starts>? ORDER BY b.starts LIMIT 1", (rid, now))
    later = [dict(r) for r in con.execute(
        "SELECT b.starts, b.title, COALESCE(c.name,'') AS course"
        " FROM room_bookings b LEFT JOIN courses c ON c.id=b.course_id"
        " WHERE b.room_id=? AND b.state='booked' AND b.starts>?"
        " ORDER BY b.starts LIMIT 4", (rid, now))]
    for x in later:
        x["said"] = _said(x)
    can = _startable(con, rid, now)
    return {"room": {"id": room["id"], "name": room["name"],
                     "seats": room["seats"]},
            "at": now, "now": cur, "next": nxt, "later": later[1:],
            # A button that cannot do anything is worse than no button:
            # somebody taps it, types a code, and learns nothing about
            # why. So the wall is only offered the one it can act on.
            "can_start": bool(can),
            "can_end": bool(cur and cur["started"]),
            "starting": dict(can)["course"] if can else "",
            "state": ("in progress" if cur and cur["started"]
                      else "finished" if cur and cur["finished"]
                      else "due" if cur else "free")}


# ---------- starting a class from the wall ----------
#
# The display has no session, on purpose: it is bolted up in a corridor
# and a tablet signed in as somebody is worse to leave there than a
# timetable. So a teacher proves who they are the way this software
# already lets people prove it at a shared device — a PIN, the same one
# the time clock takes.
#
# Two things keep that from being a hole. The blast radius is one class:
# the only thing a correct PIN can start is the class already booked into
# THIS room, now, by somebody who teaches that course. Nothing else on
# the wall can be reached, and a wrong PIN does nothing at all.
#
# And it is throttled, which matters more than the first point. A wrong
# PIN doing nothing is not the risk; the risk is a corridor screen
# working as an oracle — somebody standing there trying four-digit codes
# until one is accepted, and then walking to the time clock with it. Five
# wrong tries and the room stops answering for a minute, doubling.
_TRIES: dict = {}
_MAX_TRIES = 5


def _throttled(rid: int) -> float:
    """Seconds this room is refusing PINs for, or 0."""
    n, until = _TRIES.get(rid, (0, 0.0))
    return max(0.0, until - time.time())


def _wrong(rid: int) -> None:
    n, _ = _TRIES.get(rid, (0, 0.0))
    n += 1
    wait = 0.0
    if n >= _MAX_TRIES:
        # 60s, then 120, then 240 — long enough that guessing ten
        # thousand codes stops being an afternoon's work.
        wait = 60.0 * (2 ** (n - _MAX_TRIES))
    _TRIES[rid] = (n, time.time() + wait)


def _right(rid: int) -> None:
    _TRIES.pop(rid, None)


def _refuse(rid: int, course: str):
    """A code that is real but not this class's teacher.

    It does NOT say whose code it is. The first version did — "Anna, you
    do not teach Spanish A2" — on the reasoning that a real teacher at
    the wrong door deserves a straight answer. That was the wrong trade:
    the real teacher already knows their own name, and the only person
    who learns anything from it is a stranger typing codes in a corridor,
    who is told that the one they guessed is real and whose it is.

    It counts against the throttle for the same reason. Somebody working
    through four-digit codes is going to find valid ones belonging to
    people who do not teach here, and a limit that only counts
    unrecognised codes would let them keep going all afternoon.
    """
    _wrong(rid)
    raise HTTPException(
        403, f"that code cannot start {course}. Its teacher, or an "
             f"owner, can — or start it from the Learning page.")


class PinBody(BaseModel):
    pin: str = ""


def _startable(con, rid: int, now: float):
    """The booking this room could start right now.

    Fifteen minutes early is still on time: a teacher who arrives before
    the hour and cannot start the class stands there until the clock
    agrees with them, which is a worse rule than the one it enforces.
    """
    return con.execute(
        "SELECT b.*, COALESCE(c.name,'') AS course FROM room_bookings b"
        " LEFT JOIN courses c ON c.id=b.course_id"
        " WHERE b.room_id=? AND b.state='booked' AND b.session_id=0"
        " AND b.course_id>0 AND b.starts<=? AND b.ends>?"
        " ORDER BY b.starts LIMIT 1", (rid, now + 900, now)).fetchone()


def _who(con, rid: int, pin: str):
    """The person behind this PIN, or a refusal that does not say which
    part was wrong."""
    wait = _throttled(rid)
    if wait:
        raise HTTPException(
            429, f"too many wrong codes on this screen. Try again in "
                 f"{int(wait) + 1} seconds, or start the class from the "
                 f"Learning page.")
    from .main import CFG
    from . import auth
    u = auth.check_pin(con, pin, CFG["pin_pepper"])
    if u is None:
        _wrong(rid)
        raise HTTPException(403, "that code was not recognised")
    # Deliberately NOT clearing the count here. Recognising a code is not
    # the same as it being allowed to do this, and clearing on
    # recognition would hand the budget straight back to somebody
    # guessing their way through valid codes. The caller clears it when
    # the whole thing actually worked.
    return u


@router.post("/api/rooms/{rid}/start")
def start_here(rid: int, body: PinBody, con=Depends(get_con)):
    """Start the class this room is booked for, from the wall."""
    _room(con, rid)
    now = db.now()
    bk = _startable(con, rid, now)
    if bk is None:
        raise HTTPException(
            409, "there is no class booked in here to start. A booking "
                 "without a course is a room held for something else, and "
                 "a class already running is already running.")
    user = _who(con, rid, body.pin)
    from . import classroom, learning
    if not learning.may_edit(con, user, bk["course_id"]):
        _refuse(rid, bk["course"])
    sess = classroom.start_class(con, course_id=bk["course_id"],
                                 teacher_id=user["id"])
    sid = sess.id
    con.execute("UPDATE room_bookings SET session_id=?, teacher_id=?"
                " WHERE id=?", (sid, user["id"], bk["id"]))
    con.commit()
    _right(rid)
    return {"ok": True, "session_id": sid, "started_by": user["name"],
            "course": bk["course"]}


@router.post("/api/rooms/{rid}/end")
def end_here(rid: int, body: PinBody, con=Depends(get_con)):
    """Close the class running in here, on the way out of the door."""
    _room(con, rid)
    now = db.now()
    bk = con.execute(
        "SELECT b.*, COALESCE(c.name,'') AS course FROM room_bookings b"
        " LEFT JOIN courses c ON c.id=b.course_id"
        " JOIN class_sessions cs ON cs.id=b.session_id AND cs.status='open'"
        " WHERE b.room_id=? AND b.state='booked' AND b.session_id>0"
        " AND b.starts<=? ORDER BY b.starts DESC LIMIT 1",
        (rid, now + 900)).fetchone()
    if bk is None:
        raise HTTPException(409, "nothing is running in here")
    user = _who(con, rid, body.pin)
    from . import classroom, learning
    if not learning.may_edit(con, user, bk["course_id"]):
        _refuse(rid, bk["course"])
    classroom.end_class(con, session_id=bk["session_id"],
                        actor_id=user["id"])
    con.commit()
    _right(rid)
    return {"ok": True, "ended_by": user["name"], "course": bk["course"]}


@router.get("/api/rooms/{rid}/now")
def what_is_on(rid: int, user=Depends(current_user), con=Depends(get_con)):
    """What this room holds now and next.

    The shape a screen on the wall wants: one thing happening, one thing
    coming, and enough about each to be read from across the room.
    """
    room = _room(con, rid)
    now = db.now()
    def one(sql, args):
        r = con.execute(sql, args).fetchone()
        if not r:
            return None
        d = dict(r)
        d["said"] = _said(d)
        d["live"] = bool(d.get("session_id"))
        return d
    sel = ("SELECT b.*, COALESCE(c.name,'') AS course,"
           " COALESCE(u.name,'') AS teacher FROM room_bookings b"
           " LEFT JOIN courses c ON c.id=b.course_id"
           " LEFT JOIN users u ON u.id=b.teacher_id"
           " WHERE b.room_id=? AND b.state='booked'")
    return {
        "room": dict(room), "at": now,
        "now": one(sel + " AND b.starts<=? AND b.ends>? LIMIT 1",
                   (rid, now, now)),
        "next": one(sel + " AND b.starts>? ORDER BY b.starts LIMIT 1",
                    (rid, now)),
    }


def _plus_weeks(ts: float, n: int) -> float:
    """`n` weeks on, at the same wall-clock time.

    Not n * 604800: a term booked from October runs through the clocks
    changing, and seconds-arithmetic would move a six o'clock class to
    five for half of it.
    """
    if not n:
        return ts
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 7 * n,
                        lt.tm_hour, lt.tm_min, int(lt.tm_sec), 0, 0, -1))
