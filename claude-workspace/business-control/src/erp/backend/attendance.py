"""Attendance + payroll — the PURE core of the class-session loop. Ported whole from lingua-portal.

Nothing here touches the database, the clock, or the network: every function takes the state it
needs and returns a decision. That is what makes the interesting rules (who may check in, when is
late, what is a teacher owed) testable exhaustively in milliseconds, and it keeps the storage layer
free to change without touching the rules.

The loop this models:

    teacher starts a class   -> a SESSION opens
    students check in        -> CHECKIN rows (self-service, or marked by the teacher)
    teacher works the roster -> statuses corrected, with WHO marked it recorded
    teacher ends the class   -> the session closes and its duration is fixed
    payroll                  -> DERIVED from closed sessions, never entered by hand

One decision worth stating up front, because everything else follows from it:

    **Payroll is a derivation, not a ledger.**

Pay is computed from the sessions a teacher actually taught. There is no editable "amount owed"
field that can drift away from the sessions behind it. What administrators *do* own is an
**overlay**: approve / hold / mark-paid, keyed by session. The money always traces back to a class
that happened, and an audit can always ask "which sessions is this figure made of?".

The same discipline applies to attendance: a check-in records its METHOD (self vs teacher-marked)
and its ACTOR, so "present" is never an anonymous assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

# ── vocabulary ───────────────────────────────────────────────────────────────
# Statuses are a closed set: an unknown status is a bug, not a new category to be tolerated.
PRESENT = "present"
LATE = "late"
ABSENT = "absent"
EXCUSED = "excused"
ATTENDANCE_STATUSES = (PRESENT, LATE, ABSENT, EXCUSED)

# Who asserted the status. Self check-in is convenient but weaker evidence than a teacher marking
# the roster, so the two are never collapsed into one flag.
BY_SELF = "self"
BY_TEACHER = "teacher"
BY_SYSTEM = "system"  # e.g. auto-absent at close for students who never checked in

SESSION_OPEN = "open"
SESSION_CLOSED = "closed"
SESSION_CANCELLED = "cancelled"

# Payroll overlay states. `pending` is the absence of a decision, not a stored row.
PAY_PENDING = "pending"
PAY_APPROVED = "approved"
PAY_HELD = "held"
PAY_PAID = "paid"

# Defaults, overridable per course. Minutes.
DEFAULT_LATE_AFTER_MIN = 10
DEFAULT_CHECKIN_OPENS_BEFORE_MIN = 15


class DomainError(Exception):
    """A rule was violated. Carries a code so the HTTP layer can map it without string-matching.

    `status` exists because not every broken rule is a 409: a rate limit is a 429, and the
    difference is what tells a client whether retrying could ever work. `details` carries structured
    facts the client needs to act — `retry_after` being the one that matters — so the caller does not
    have to parse them back out of an English sentence written for a human.
    """

    def __init__(self, code: str, message: str, *, status: int = 409, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


@dataclass(frozen=True)
class Session:
    """One class meeting. `started_at`/`ended_at` are epoch seconds (UTC), never local time."""

    id: int
    course_id: int
    teacher_id: int
    started_at: int
    ended_at: int | None = None
    status: str = SESSION_OPEN
    late_after_min: int = DEFAULT_LATE_AFTER_MIN
    scheduled_minutes: int | None = None  # what the class was *supposed* to run, if scheduled

    @property
    def is_open(self) -> bool:
        return self.status == SESSION_OPEN

    def duration_minutes(self, now: int | None = None) -> int:
        """Elapsed minutes. An open session is measured against `now` so a live UI can show it."""
        end = self.ended_at if self.ended_at is not None else now
        if end is None:
            raise DomainError("session_open", "an open session needs `now` to be measured")
        return max(0, int(round((end - self.started_at) / 60.0)))


@dataclass(frozen=True)
class CheckIn:
    session_id: int
    student_id: int
    at: int
    status: str
    method: str
    marked_by: int | None = None  # the person who asserted it; None for self check-in
    note: str = ""


@dataclass(frozen=True)
class RosterRow:
    """A student's standing in one session — enrollment joined with whatever check-in exists."""

    student_id: int
    name: str
    status: str
    method: str | None = None
    at: int | None = None
    marked_by: int | None = None
    note: str = ""

    @property
    def counted_present(self) -> bool:
        """Late still counts as attending. Excused does not count as present but is not a no-show."""
        return self.status in (PRESENT, LATE)


# ── session lifecycle ────────────────────────────────────────────────────────

def start_session(
    *,
    course_id: int,
    teacher_id: int,
    now: int,
    open_sessions: Sequence[Session] = (),
    late_after_min: int = DEFAULT_LATE_AFTER_MIN,
    scheduled_minutes: int | None = None,
) -> dict:
    """Validate starting a class and return the row to insert.

    Refuses a second open session for the same course: two concurrent sessions would split the
    roster and double-count the teacher's pay. Reopening is an explicit act, not an accident.
    """
    for s in open_sessions:
        if s.course_id == course_id and s.is_open:
            raise DomainError("already_open", f"course {course_id} already has an open session ({s.id})")
    if late_after_min < 0:
        raise DomainError("bad_late_window", "late_after_min cannot be negative")
    return {
        "course_id": course_id,
        "teacher_id": teacher_id,
        "started_at": now,
        "ended_at": None,
        "status": SESSION_OPEN,
        "late_after_min": late_after_min,
        "scheduled_minutes": scheduled_minutes,
    }


def close_session(session: Session, *, now: int, actor_id: int) -> dict:
    """End a class. Only the teaching teacher (or an admin, checked above this layer) may close."""
    if session.status == SESSION_CLOSED:
        raise DomainError("already_closed", f"session {session.id} is already closed")
    if session.status == SESSION_CANCELLED:
        raise DomainError("cancelled", f"session {session.id} was cancelled")
    if now < session.started_at:
        raise DomainError("ends_before_start", "a class cannot end before it started")
    return {"ended_at": now, "status": SESSION_CLOSED, "closed_by": actor_id}


# ── check-in ─────────────────────────────────────────────────────────────────

def classify_arrival(session: Session, at: int) -> str:
    """present vs late, from the session's own late window."""
    minutes_in = (at - session.started_at) / 60.0
    return LATE if minutes_in > session.late_after_min else PRESENT


def check_in(
    session: Session,
    *,
    student_id: int,
    at: int,
    enrolled_ids: Iterable[int],
    existing: CheckIn | None = None,
    method: str = BY_SELF,
    marked_by: int | None = None,
    status: str | None = None,
    checkin_opens_before_min: int = DEFAULT_CHECKIN_OPENS_BEFORE_MIN,
) -> CheckIn:
    """Record (or correct) one student's attendance.

    Rules, in the order they matter:
      * the session must be open — attendance is not editable after the fact through this path;
        correcting a closed session is a separate, audited amend (see `amend_closed`).
      * the student must be enrolled in the course.
      * self check-in cannot happen before the door opens, and cannot *set* an arbitrary status —
        a student may say "I am here", not "I was excused".
      * a teacher may set any status, and always wins over a self check-in (stronger evidence).
    """
    if not session.is_open:
        raise DomainError("session_not_open", "the class is not open for check-in")
    if student_id not in set(enrolled_ids):
        raise DomainError("not_enrolled", f"student {student_id} is not enrolled in this course")

    if method == BY_SELF:
        if status is not None and status not in (PRESENT, LATE):
            raise DomainError("self_status_forbidden", "a student may only check themselves in")
        if at < session.started_at - checkin_opens_before_min * 60:
            raise DomainError("too_early", "check-in is not open yet")
        if existing is not None and existing.method == BY_TEACHER:
            # a teacher already ruled on this student; self check-in does not overwrite it
            raise DomainError("teacher_marked", "the teacher has already marked your attendance")
        resolved = classify_arrival(session, at)
        return CheckIn(session.id, student_id, at, resolved, BY_SELF, None)

    if method == BY_TEACHER:
        if marked_by is None:
            raise DomainError("actor_required", "a teacher-marked check-in must record who marked it")
        resolved = status or classify_arrival(session, at)
        if resolved not in ATTENDANCE_STATUSES:
            raise DomainError("bad_status", f"unknown attendance status {resolved!r}")
        return CheckIn(session.id, student_id, at, resolved, BY_TEACHER, marked_by)

    raise DomainError("bad_method", f"unknown check-in method {method!r}")


def finalize_roster(
    session: Session,
    *,
    enrolled: Sequence[tuple[int, str]],
    checkins: Sequence[CheckIn],
    now: int,
) -> list[RosterRow]:
    """The roster as the teacher sees it: every enrolled student, with their standing.

    A student with no check-in reads as ABSENT once the class is closed; while it is still open they
    read as absent too, but the UI can tell the difference because the session is open. Absence is
    the default, and it is never silently upgraded.
    """
    by_student = {c.student_id: c for c in checkins}
    rows: list[RosterRow] = []
    for student_id, name in enrolled:
        c = by_student.get(student_id)
        if c is None:
            rows.append(RosterRow(student_id, name, ABSENT, None, None, None, ""))
        else:
            rows.append(RosterRow(student_id, name, c.status, c.method, c.at, c.marked_by, c.note))
    rows.sort(key=lambda r: r.name.lower())
    return rows


def attendance_summary(rows: Sequence[RosterRow]) -> dict:
    counts = {s: 0 for s in ATTENDANCE_STATUSES}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    enrolled = len(rows)
    attended = sum(1 for r in rows if r.counted_present)
    return {
        "enrolled": enrolled,
        "attended": attended,
        "counts": counts,
        # rate over students who were *expected* — excused students are removed from the denominator
        # rather than counted against the class.
        "rate": round(attended / max(1, enrolled - counts.get(EXCUSED, 0)), 4),
    }


# ── payroll (derived) ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PayRate:
    """How a teacher is paid. Hourly is the common case; per-session supports fixed-fee classes."""

    teacher_id: int
    hourly_cents: int = 0
    per_session_cents: int = 0
    currency: str = "USD"


@dataclass(frozen=True)
class PayLine:
    session_id: int
    course_id: int
    teacher_id: int
    started_at: int
    minutes: int
    billable_minutes: int
    amount_cents: int
    students_attended: int
    state: str = PAY_PENDING


def billable_minutes(session: Session, *, minimum_minutes: int = 0, round_to_min: int = 1) -> int:
    """Minutes a teacher is actually paid for.

    Two knobs that real schools need: a MINIMUM (a class that ends early still pays the floor —
    the teacher showed up and prepared) and ROUNDING (bill in 5- or 15-minute blocks). Rounding is
    UP, deliberately: the ambiguity favours the person who did the work.
    """
    if session.ended_at is None:
        raise DomainError("session_open", "an open session is not billable yet")
    actual = session.duration_minutes()
    billed = max(actual, minimum_minutes)
    if round_to_min > 1:
        blocks = (billed + round_to_min - 1) // round_to_min
        billed = blocks * round_to_min
    return billed


def pay_for_session(
    session: Session,
    rate: PayRate,
    *,
    students_attended: int,
    state: str = PAY_PENDING,
    minimum_minutes: int = 0,
    round_to_min: int = 1,
    pay_cancelled: bool = False,
) -> PayLine:
    """One session's pay. Cancelled sessions pay nothing unless the school says otherwise."""
    if session.status == SESSION_CANCELLED and not pay_cancelled:
        return PayLine(session.id, session.course_id, session.teacher_id, session.started_at,
                       0, 0, 0, students_attended, state)
    mins = billable_minutes(session, minimum_minutes=minimum_minutes, round_to_min=round_to_min)
    amount = rate.per_session_cents + int(round(rate.hourly_cents * mins / 60.0))
    return PayLine(
        session_id=session.id,
        course_id=session.course_id,
        teacher_id=session.teacher_id,
        started_at=session.started_at,
        minutes=session.duration_minutes(),
        billable_minutes=mins,
        amount_cents=amount,
        students_attended=students_attended,
        state=state,
    )


def payroll_period(
    lines: Sequence[PayLine],
    *,
    include_states: Sequence[str] = (PAY_PENDING, PAY_APPROVED, PAY_PAID),
) -> dict:
    """Roll session lines into a period total, grouped by teacher.

    Held lines are excluded from the payable total by default but are still reported, so a
    disagreement is visible rather than silently deducted.
    """
    by_teacher: dict[int, dict] = {}
    for ln in lines:
        t = by_teacher.setdefault(ln.teacher_id, {
            "teacher_id": ln.teacher_id, "sessions": 0, "minutes": 0,
            "billable_minutes": 0, "amount_cents": 0, "held_cents": 0, "lines": [],
        })
        t["lines"].append(ln)
        if ln.state == PAY_HELD:
            t["held_cents"] += ln.amount_cents
            continue
        if ln.state not in include_states:
            continue
        t["sessions"] += 1
        t["minutes"] += ln.minutes
        t["billable_minutes"] += ln.billable_minutes
        t["amount_cents"] += ln.amount_cents
    total = sum(t["amount_cents"] for t in by_teacher.values())
    return {
        "teachers": sorted(by_teacher.values(), key=lambda t: t["teacher_id"]),
        "total_cents": total,
        "held_cents": sum(t["held_cents"] for t in by_teacher.values()),
    }


def money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "")
    return f"{sign}{sym}{c // 100}.{c % 100:02d}"
