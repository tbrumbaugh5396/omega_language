"""The classroom — where lingua-portal's pure attendance rules meet this
platform's storage. The port of the source's `services/classes.py`.

This layer does three things and deliberately no more — load the state a rule
needs, call the rule in `attendance.py`, persist what it returned. Every
decision (may this student check in? is this teacher owed anything?) lives in
the pure module so it can be tested without a database; this file is wiring.

The loop, unchanged from the source:

    teacher starts a class   -> a SESSION opens (one per course, refused twice)
    students check in        -> CHECKIN rows, self-service from /learn or
                                marked by the teacher on the ops roster
    teacher works the roster -> statuses corrected, with WHO marked recorded
    teacher ends the class   -> auto-absent rows for the silent, duration fixed
    payroll                  -> DERIVED from closed sessions, never entered by
                                hand; administrators own only an overlay
                                (approve / hold / paid), keyed by session

Role mapping onto this platform's users: the course's appointed teacher (or
any admin) runs sessions and marks rosters; enrollment — not role — is what
lets someone check themselves in.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import attendance as A
from . import notify

TABLES = """
CREATE TABLE IF NOT EXISTS class_sessions (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  teacher_id INTEGER NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','closed','cancelled')),
  late_after_min INTEGER NOT NULL DEFAULT 10,
  scheduled_minutes INTEGER,
  closed_by INTEGER,
  lesson_id INTEGER,                       -- the lesson this class taught
  room TEXT,                               -- video room id when class meets online
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS checkins (
  session_id INTEGER NOT NULL,
  student_id INTEGER NOT NULL,
  at REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('present','late','absent','excused')),
  method TEXT NOT NULL CHECK (method IN ('self','teacher','system')),
  marked_by INTEGER,
  note TEXT DEFAULT '',
  PRIMARY KEY (session_id, student_id)
);

CREATE TABLE IF NOT EXISTS pay_rates (
  teacher_id INTEGER PRIMARY KEY,
  hourly_cents INTEGER NOT NULL DEFAULT 0,
  per_session_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  minimum_minutes INTEGER NOT NULL DEFAULT 0,
  round_to_min INTEGER NOT NULL DEFAULT 1,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_overlay (
  session_id INTEGER PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('pending','approved','held','paid')),
  decided_by INTEGER,
  decided_at REAL NOT NULL,
  note TEXT DEFAULT ''
);
"""


# Columns added after the tables first shipped. CREATE TABLE IF NOT EXISTS
# leaves an existing table exactly as it was, so installs from before these
# existed need them added explicitly.
MIGRATIONS = (
    "ALTER TABLE class_sessions ADD COLUMN room TEXT",
)


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass            # already there
    con.commit()


def _err(e: A.DomainError) -> HTTPException:
    return HTTPException(e.status, e.message)


# ── loading ──────────────────────────────────────────────────────────────────

def _session_from_row(r) -> A.Session:
    return A.Session(
        id=r["id"], course_id=r["course_id"], teacher_id=r["teacher_id"],
        started_at=int(r["started_at"]),
        ended_at=int(r["ended_at"]) if r["ended_at"] is not None else None,
        status=r["status"], late_after_min=r["late_after_min"],
        scheduled_minutes=r["scheduled_minutes"],
    )


def get_session(con, session_id: int) -> A.Session:
    r = con.execute("SELECT * FROM class_sessions WHERE id=?",
                    (session_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "session not found")
    return _session_from_row(r)


def open_session_for_course(con, course_id: int):
    r = con.execute("SELECT * FROM class_sessions WHERE course_id=?"
                    " AND status='open'", (course_id,)).fetchone()
    return _session_from_row(r) if r else None


def enrolled(con, course_id: int) -> list:
    """(student_id, name) for everyone currently enrolled."""
    rows = con.execute(
        "SELECT u.id, u.name FROM enrollments e JOIN users u ON u.id=e.user_id"
        " WHERE e.course_id=? AND (e.until IS NULL OR e.until > ?)"
        " AND u.active=1 ORDER BY u.name COLLATE NOCASE",
        (course_id, time.time())).fetchall()
    return [(r["id"], r["name"]) for r in rows]


def checkins_for(con, session_id: int) -> list:
    rows = con.execute("SELECT * FROM checkins WHERE session_id=?",
                       (session_id,)).fetchall()
    return [A.CheckIn(r["session_id"], r["student_id"], int(r["at"]),
                      r["status"], r["method"], r["marked_by"], r["note"] or "")
            for r in rows]


# ── lifecycle ────────────────────────────────────────────────────────────────

def start_class(con, *, course_id: int, teacher_id: int,
                lesson_id: int | None = None) -> A.Session:
    course = con.execute("SELECT * FROM courses WHERE id=?",
                         (course_id,)).fetchone()
    if course is None:
        raise HTTPException(404, "course not found")
    # A class may name the lesson it teaches — but only a lesson of ITS OWN
    # course, or a session could claim to have taught another course's
    # material.
    if lesson_id is not None:
        ok_lesson = con.execute(
            "SELECT id FROM lessons WHERE id=? AND course_id=?",
            (int(lesson_id), course_id)).fetchone()
        if ok_lesson is None:
            raise HTTPException(400, "that lesson is not part of this course")
    existing = con.execute("SELECT * FROM class_sessions WHERE course_id=?"
                           " AND status='open'", (course_id,)).fetchall()
    try:
        row = A.start_session(
            course_id=course_id, teacher_id=teacher_id, now=int(time.time()),
            open_sessions=[_session_from_row(r) for r in existing])
    except A.DomainError as e:
        raise _err(e)
    import secrets
    cur = con.execute(
        "INSERT INTO class_sessions(course_id,teacher_id,started_at,ended_at,"
        " status,late_after_min,scheduled_minutes,lesson_id,room)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (row["course_id"], row["teacher_id"], row["started_at"], None,
         row["status"], row["late_after_min"], row["scheduled_minutes"],
         int(lesson_id) if lesson_id is not None else None,
         "rm-" + secrets.token_hex(4)))    # every class carries a video room
    sid = cur.lastrowid
    # every enrolled student gets the word: class is on, check-in is live
    for uid, _name in enrolled(con, course_id):
        notify.push(con, f"{course['name']} is in session",
                    "check in from the learning page", kind="learning",
                    user_id=uid, dedup=f"class:{sid}:{uid}")
    return get_session(con, sid)


def end_class(con, *, session_id: int, actor_id: int,
              auto_absent: bool = True) -> A.Session:
    """Close a class. Students who never checked in are recorded as
    system-marked absent — without that row, "no check-in" is ambiguous
    between *absent* and *nobody took attendance*."""
    s = get_session(con, session_id)
    try:
        upd = A.close_session(s, now=int(time.time()), actor_id=actor_id)
    except A.DomainError as e:
        raise _err(e)
    if auto_absent:
        seen = {c.student_id for c in checkins_for(con, session_id)}
        for student_id, _name in enrolled(con, s.course_id):
            if student_id not in seen:
                con.execute(
                    "INSERT INTO checkins(session_id,student_id,at,status,"
                    " method,marked_by,note) VALUES(?,?,?,?,?,?,?)",
                    (session_id, student_id, upd["ended_at"], A.ABSENT,
                     A.BY_SYSTEM, None, "no check-in before class ended"))
    con.execute("UPDATE class_sessions SET ended_at=?, status=?, closed_by=?"
                " WHERE id=?",
                (upd["ended_at"], upd["status"], upd["closed_by"], session_id))
    return get_session(con, session_id)


# ── check-in ─────────────────────────────────────────────────────────────────

def do_check_in(con, *, session_id: int, student_id: int,
                method: str = A.BY_SELF, marked_by: int | None = None,
                status: str | None = None, note: str = ""):
    """Returns (checkin, newly_earned_achievements) — a check-in is the
    commonest badge moment, and the caller shows what it minted."""
    s = get_session(con, session_id)
    er = con.execute("SELECT * FROM checkins WHERE session_id=? AND"
                     " student_id=?", (session_id, student_id)).fetchone()
    existing = None
    if er:
        existing = A.CheckIn(er["session_id"], er["student_id"], int(er["at"]),
                             er["status"], er["method"], er["marked_by"],
                             er["note"] or "")
    try:
        c = A.check_in(
            s, student_id=student_id, at=int(time.time()),
            enrolled_ids=[i for i, _ in enrolled(con, s.course_id)],
            existing=existing, method=method, marked_by=marked_by,
            status=status)
    except A.DomainError as e:
        raise _err(e)
    con.execute(
        "INSERT INTO checkins(session_id,student_id,at,status,method,"
        " marked_by,note) VALUES(?,?,?,?,?,?,?)"
        " ON CONFLICT(session_id,student_id) DO UPDATE SET"
        "  at=excluded.at, status=excluded.status, method=excluded.method,"
        "  marked_by=excluded.marked_by, note=excluded.note",
        (c.session_id, c.student_id, c.at, c.status, c.method, c.marked_by,
         note))
    fresh = []
    if c.status in (A.PRESENT, A.LATE):
        from . import learning
        fresh = learning.award_achievements(con, c.student_id)
    return c, fresh


def roster(con, session_id: int) -> dict:
    """Everything the teacher's attendance screen needs, in one call."""
    s = get_session(con, session_id)
    rows = A.finalize_roster(s, enrolled=enrolled(con, s.course_id),
                             checkins=checkins_for(con, session_id),
                             now=int(time.time()))
    # Faces on the sheet: the roster is a staff surface (the same people
    # full names already trust), so photos ride it regardless of the
    # student's community switch — attendance cannot run on initials.
    _ids = [r.student_id for r in rows]
    _ph = {p["id"]: p["photo"] or "" for p in con.execute(
        f"SELECT id, photo FROM users WHERE id IN"
        f" ({','.join('?' * len(_ids))})", _ids)} if _ids else {}
    course = con.execute("SELECT id, name, language, level FROM courses"
                         " WHERE id=?", (s.course_id,)).fetchone()
    lesson = con.execute(
        "SELECT l.id, l.title FROM class_sessions se"
        " JOIN lessons l ON l.id=se.lesson_id WHERE se.id=?",
        (session_id,)).fetchone()
    room = con.execute("SELECT room FROM class_sessions WHERE id=?",
                       (session_id,)).fetchone()["room"]
    return {
        "session": {"id": s.id, "course_id": s.course_id,
                    "teacher_id": s.teacher_id, "started_at": s.started_at,
                    "ended_at": s.ended_at, "status": s.status,
                    "late_after_min": s.late_after_min, "room": room,
                    "minutes": s.duration_minutes(now=int(time.time()))},
        "course": dict(course) if course else None,
        "lesson": dict(lesson) if lesson else None,
        "roster": [{"student_id": r.student_id, "name": r.name,
                    "photo": _ph.get(r.student_id, ""),
                    "status": r.status, "method": r.method, "at": r.at,
                    "marked_by": r.marked_by, "note": r.note} for r in rows],
        "summary": A.attendance_summary(rows),
    }


def sessions_for_course(con, course_id: int, limit: int = 30) -> list:
    out = []
    for r in con.execute(
            "SELECT * FROM class_sessions WHERE course_id=?"
            " ORDER BY started_at DESC, id DESC LIMIT ?",
            (course_id, limit)).fetchall():
        s = _session_from_row(r)
        rows = A.finalize_roster(s, enrolled=enrolled(con, course_id),
                                 checkins=checkins_for(con, s.id),
                                 now=int(time.time()))
        d = {"id": s.id, "started_at": s.started_at, "ended_at": s.ended_at,
             "status": s.status, "teacher_id": s.teacher_id,
             "summary": A.attendance_summary(rows)}
        if s.status != A.SESSION_OPEN and s.ended_at:
            d["minutes"] = s.duration_minutes()
        out.append(d)
    return out


def attendance_of(con, course_id: int, user_id: int) -> dict:
    """One student's standing in one course: classes held vs attended."""
    held = con.execute(
        "SELECT COUNT(*) AS n FROM class_sessions WHERE course_id=?"
        " AND status='closed'", (course_id,)).fetchone()["n"]
    attended = con.execute(
        "SELECT COUNT(*) AS n FROM checkins c"
        " JOIN class_sessions s ON s.id=c.session_id"
        " WHERE s.course_id=? AND c.student_id=?"
        " AND c.status IN ('present','late')",
        (course_id, user_id)).fetchone()["n"]
    return {"classes_held": held, "attended": attended}


# ── payroll (derived on read) ────────────────────────────────────────────────

def _rate(con, teacher_id: int):
    r = con.execute("SELECT * FROM pay_rates WHERE teacher_id=?",
                    (teacher_id,)).fetchone()
    if r is None:
        return A.PayRate(teacher_id), 0, 1
    return (A.PayRate(teacher_id, r["hourly_cents"], r["per_session_cents"],
                      r["currency"]),
            r["minimum_minutes"], r["round_to_min"])


def pay_lines(con, *, teacher_id: int | None = None, since=None,
              until=None) -> list:
    """Derive pay for every CLOSED session in range. Nothing is read from a
    stored amount — the money always traces back to a class that happened."""
    sql = "SELECT * FROM class_sessions WHERE status IN ('closed','cancelled')"
    args = []
    if teacher_id is not None:
        sql += " AND teacher_id=?"; args.append(teacher_id)
    if since is not None:
        sql += " AND started_at >= ?"; args.append(since)
    if until is not None:
        sql += " AND started_at < ?"; args.append(until)
    sql += " ORDER BY started_at DESC"
    lines = []
    for r in con.execute(sql, args).fetchall():
        s = _session_from_row(r)
        rate, minimum, rounding = _rate(con, s.teacher_id)
        attended = con.execute(
            "SELECT COUNT(*) AS n FROM checkins WHERE session_id=?"
            " AND status IN ('present','late')", (s.id,)).fetchone()["n"]
        ov = con.execute("SELECT state FROM payroll_overlay WHERE session_id=?",
                         (s.id,)).fetchone()
        lines.append(A.pay_for_session(
            s, rate, students_attended=attended,
            state=(ov["state"] if ov else A.PAY_PENDING),
            minimum_minutes=minimum, round_to_min=rounding))
    return lines


def payroll(con, **kw) -> dict:
    return A.payroll_period(pay_lines(con, **kw))


def set_pay_state(con, *, session_id: int, state: str, actor_id: int,
                  note: str = "") -> None:
    if state not in (A.PAY_PENDING, A.PAY_APPROVED, A.PAY_HELD, A.PAY_PAID):
        raise HTTPException(400, f"unknown payroll state {state!r}")
    con.execute(
        "INSERT INTO payroll_overlay(session_id,state,decided_by,decided_at,"
        " note) VALUES(?,?,?,?,?)"
        " ON CONFLICT(session_id) DO UPDATE SET state=excluded.state,"
        "  decided_by=excluded.decided_by, decided_at=excluded.decided_at,"
        "  note=excluded.note",
        (session_id, state, actor_id, time.time(), str(note or "")[:400]))


# ── ops routes ───────────────────────────────────────────────────────────────

router = APIRouter()

from .main import admin_user, current_user, get_con  # noqa: E402
from .learning import may_edit  # noqa: E402


def _teaches(con, user, course_id: int):
    if not may_edit(con, user, course_id):
        raise HTTPException(403, "you do not teach this course")


class StartBody(BaseModel):
    course_id: int = 0
    lesson_id: int | None = None


@router.post("/api/learning/sessions")
def ops_start_class(body: StartBody, user=Depends(current_user),
                    con=Depends(get_con)):
    _teaches(con, user, body.course_id)
    s = start_class(con, course_id=body.course_id, teacher_id=user["id"],
                    lesson_id=body.lesson_id)
    con.commit()
    return roster(con, s.id)


@router.get("/api/learning/sessions/{sid}")
def ops_roster(sid: int, user=Depends(current_user), con=Depends(get_con)):
    s = get_session(con, sid)
    _teaches(con, user, s.course_id)
    return roster(con, sid)


@router.post("/api/learning/sessions/{sid}/close")
def ops_end_class(sid: int, user=Depends(current_user), con=Depends(get_con)):
    s = get_session(con, sid)
    _teaches(con, user, s.course_id)
    end_class(con, session_id=sid, actor_id=user["id"])
    con.commit()
    # The tapes come home with the class. Best-effort: a segment the SFU
    # is still finalising waits for the collect-tape route — closing a
    # class must never fail because a recording was slow.
    try:
        from . import materials
        row = con.execute("SELECT * FROM class_sessions WHERE id=?",
                          (sid,)).fetchone()
        materials.collect_sfu_tapes(con, row, owner_id=user["id"])
    except Exception:
        pass
    return roster(con, sid)


class MarkBody(BaseModel):
    student_id: int = 0
    status: str = "present"
    note: str = ""


@router.post("/api/learning/sessions/{sid}/mark")
def ops_mark(sid: int, body: MarkBody, user=Depends(current_user),
             con=Depends(get_con)):
    s = get_session(con, sid)
    _teaches(con, user, s.course_id)
    do_check_in(con, session_id=sid, student_id=body.student_id,
                method=A.BY_TEACHER, marked_by=user["id"],
                status=body.status, note=body.note)[0]
    con.commit()
    return roster(con, sid)


class RateBody(BaseModel):
    teacher_id: int = 0
    hourly_cents: int = 0
    per_session_cents: int = 0
    minimum_minutes: int = 0
    round_to_min: int = 1


@router.post("/api/learning/payrates")
def ops_set_rate(body: RateBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    if body.round_to_min < 1:
        raise HTTPException(400, "rounding blocks are at least one minute")
    con.execute(
        "INSERT INTO pay_rates(teacher_id,hourly_cents,per_session_cents,"
        " minimum_minutes,round_to_min,updated_at) VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(teacher_id) DO UPDATE SET"
        "  hourly_cents=excluded.hourly_cents,"
        "  per_session_cents=excluded.per_session_cents,"
        "  minimum_minutes=excluded.minimum_minutes,"
        "  round_to_min=excluded.round_to_min, updated_at=excluded.updated_at",
        (body.teacher_id, body.hourly_cents, body.per_session_cents,
         body.minimum_minutes, body.round_to_min, time.time()))
    con.commit()
    return {"ok": True}


@router.get("/api/learning/payroll")
def ops_payroll(user=Depends(admin_user), con=Depends(get_con),
                since: float | None = None, until: float | None = None):
    p = payroll(con, since=since, until=until)
    names = {r["id"]: r["name"] for r in con.execute(
        "SELECT id, name FROM users").fetchall()}
    course_names = {r["id"]: r["name"] for r in con.execute(
        "SELECT id, name FROM courses").fetchall()}
    return {
        "total_cents": p["total_cents"], "held_cents": p["held_cents"],
        "teachers": [{
            "teacher_id": t["teacher_id"],
            "name": names.get(t["teacher_id"], "?"),
            "sessions": t["sessions"], "minutes": t["minutes"],
            "billable_minutes": t["billable_minutes"],
            "amount_cents": t["amount_cents"], "held_cents": t["held_cents"],
            "lines": [{
                "session_id": ln.session_id, "course_id": ln.course_id,
                "course": course_names.get(ln.course_id, "?"),
                "started_at": ln.started_at, "minutes": ln.minutes,
                "billable_minutes": ln.billable_minutes,
                "amount_cents": ln.amount_cents,
                "students_attended": ln.students_attended, "state": ln.state,
            } for ln in t["lines"]],
        } for t in p["teachers"]],
        "rates": [dict(r) for r in con.execute(
            "SELECT * FROM pay_rates").fetchall()],
    }


class PayStateBody(BaseModel):
    state: str = "approved"
    note: str = ""


@router.post("/api/learning/payroll/{sid}/state")
def ops_pay_state(sid: int, body: PayStateBody, user=Depends(admin_user),
                  con=Depends(get_con)):
    get_session(con, sid)
    set_pay_state(con, session_id=sid, state=body.state, actor_id=user["id"],
                  note=body.note)
    con.commit()
    return {"ok": True}
