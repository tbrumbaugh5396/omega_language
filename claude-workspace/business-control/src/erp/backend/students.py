"""The student as a person, and the student as a record.

`users` holds what a sign-in needs: a name, an address, a role. A school
needs more than that about the people in its classes — how old they are,
where they are from, what they already speak, what schooling they have
had — and it needs it in columns somebody can read and correct, not in
a free-text note. That is the **profile**: one row per person, every
field optional, and an `extra` bag for the questions this school asks
that the next one does not.

The **record** is everything the school knows the student did. Most of
it is derived on read from tables that already exist — enrollments,
check-ins, graded attempts, achievements, tutoring asks — because a
copy of a grade is a grade that can disagree with the grade. The one
thing stored here is the **log**: what a member of staff noticed and
wrote down, an achievement worth recording, a concern, a milestone.
Those are facts the data cannot derive, so they are rows.

The learner's own transcript (`/api/learn/record`) and the office's
student page read the same `record_of`, so the two never disagree.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db

TABLES = """
CREATE TABLE IF NOT EXISTS student_profiles (
  user_id INTEGER PRIMARY KEY,
  birth_date TEXT DEFAULT '',            -- YYYY-MM-DD
  gender TEXT DEFAULT '',
  nationality TEXT DEFAULT '',
  origin TEXT DEFAULT '',                -- where they are from: city, country
  native_language TEXT DEFAULT '',
  other_languages TEXT DEFAULT '',
  education TEXT DEFAULT '',             -- history and background, in prose
  occupation TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  address TEXT DEFAULT '',
  guardian TEXT DEFAULT '',              -- for a minor: who answers for them
  emergency_contact TEXT DEFAULT '',
  goals TEXT DEFAULT '',
  needs TEXT DEFAULT '',                 -- accessibility, health, anything to know
  notes TEXT DEFAULT '',
  extra TEXT DEFAULT '{}',               -- JSON {label: value} for the rest
  status TEXT DEFAULT 'active',          -- see STATUSES
  status_note TEXT DEFAULT '',
  status_at REAL DEFAULT 0,
  updated_at REAL DEFAULT 0,
  updated_by TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS student_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'note',     -- see LOG_KINDS
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  at REAL NOT NULL,                      -- when it happened
  by_id INTEGER DEFAULT 0,
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS student_log_who ON student_log(user_id, at);
"""

PROFILE_FIELDS = ("birth_date", "gender", "nationality", "origin",
                  "native_language", "other_languages", "education",
                  "occupation", "phone", "address", "guardian",
                  "emergency_contact", "goals", "needs", "notes")
LONG_FIELDS = ("education", "goals", "needs", "notes", "address")
LOG_KINDS = ("achievement", "milestone", "note", "concern", "status")

# Achievements worth a line that the system cannot see for itself. A
# menu rather than a blank, so two teachers file the same thing the
# same way and a report can count them.
ACHIEVEMENT_PRESETS = (
    "New job", "Promotion at work", "Certification at work",
    "Started a business", "Passed a professional exam",
    "Passed the citizenship test", "Got a driver's licence",
    "Read a chapter of a book", "Read a book",
)

# Why somebody is no longer here, when they are not. `active` is the
# default and the only state that means "expect them in class".
STATUSES = ("active", "inactive", "left", "moved", "deceased")
STATUS_LABELS = {"active": "active", "inactive": "inactive",
                 "left": "no longer attends", "moved": "moved away",
                 "deceased": "passed away"}


def init_tables(con):
    con.executescript(TABLES)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(student_profiles)")}
    for col, ddl in (("status", "TEXT DEFAULT 'active'"),
                     ("status_note", "TEXT DEFAULT ''"),
                     ("status_at", "REAL DEFAULT 0")):
        if col not in cols:
            con.execute(f"ALTER TABLE student_profiles ADD COLUMN {col} {ddl}")
    con.commit()


def _office(user) -> bool:
    """Who reads and edits a student's record: the office, and the
    teaching staff. A volunteer at the door sees the register, not
    somebody's schooling."""
    return bool(user["is_admin"] or user["role"] in (
        "employee", "teacher", "director", "owner"))


def _require_office(user) -> None:
    if not _office(user):
        raise HTTPException(403, "a student's record is for the office and"
                                 " the teaching staff")


def _age(birth: str, now: float | None = None) -> int | None:
    try:
        y, m, d = (int(x) for x in birth.split("-"))
    except (ValueError, AttributeError):
        return None
    t = time.localtime(now or time.time())
    age = t.tm_year - y - (1 if (t.tm_mon, t.tm_mday) < (m, d) else 0)
    return age if 0 <= age < 130 else None


def profile_of(con, uid: int) -> dict:
    r = con.execute("SELECT * FROM student_profiles WHERE user_id=?",
                    (uid,)).fetchone()
    out = {k: "" for k in PROFILE_FIELDS}
    out.update({"extra": {}, "updated_at": 0, "updated_by": "",
                "status": "active", "status_note": "", "status_at": 0})
    if r is not None:
        out["status"] = r["status"] or "active"
        out["status_note"] = r["status_note"] or ""
        out["status_at"] = r["status_at"] or 0
        for k in PROFILE_FIELDS:
            out[k] = r[k] or ""
        try:
            out["extra"] = json.loads(r["extra"] or "{}")
            if not isinstance(out["extra"], dict):
                out["extra"] = {}
        except ValueError:
            out["extra"] = {}
        out["updated_at"] = r["updated_at"] or 0
        out["updated_by"] = r["updated_by"] or ""
    out["age"] = _age(out["birth_date"])
    out["status_label"] = STATUS_LABELS.get(out["status"], out["status"])
    return out


def save_profile(con, uid: int, fields: dict, extra: dict | None,
                 by: str) -> dict:
    """Write what was sent; leave what was not. `extra` replaces the bag
    whole when given, because a bag half-edited is a bag nobody trusts."""
    cur = profile_of(con, uid)
    for k in PROFILE_FIELDS:
        if k in fields and fields[k] is not None:
            v = str(fields[k]).strip()
            cur[k] = v[:4000] if k in LONG_FIELDS else v[:200]
    if cur["birth_date"] and _age(cur["birth_date"]) is None:
        raise HTTPException(400, "a birth date is YYYY-MM-DD, and in the"
                                 " past")
    if extra is not None:
        clean = {}
        for k, v in list(extra.items())[:40]:
            k = str(k).strip()[:60]
            if k:
                clean[k] = str(v).strip()[:400]
        cur["extra"] = clean
    con.execute(
        "INSERT INTO student_profiles(user_id," + ",".join(PROFILE_FIELDS)
        + ",extra,updated_at,updated_by) VALUES(?" + ",?" * len(PROFILE_FIELDS)
        + ",?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
        + ",".join(f"{k}=excluded.{k}" for k in PROFILE_FIELDS)
        + ",extra=excluded.extra,updated_at=excluded.updated_at,"
          "updated_by=excluded.updated_by",
        (uid, *[cur[k] for k in PROFILE_FIELDS],
         json.dumps(cur["extra"]), time.time(), by[:120]))
    return profile_of(con, uid)


def set_status(con, uid: int, status: str, note: str, at: float,
               by, end_seats: bool) -> dict:
    """Why somebody is no longer here — or that they are back. Written
    to the profile, and to the log, so the timeline says when it changed
    and who said so. Ending their seats is offered, not assumed: a
    student who moved away may keep a seat in the online class."""
    if status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    profile_of(con, uid)                       # ensures the row exists
    con.execute(
        "INSERT INTO student_profiles(user_id,status,status_note,status_at,"
        " updated_at,updated_by) VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,"
        " status_note=excluded.status_note, status_at=excluded.status_at,"
        " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (uid, status, note.strip()[:400], at, time.time(), by["name"][:120]))
    ended = 0
    if end_seats and status != "active":
        ended = con.execute(
            "UPDATE enrollments SET until=? WHERE user_id=? AND until IS NULL",
            (at, uid)).rowcount
    title = (STATUS_LABELS[status].capitalize() if status != "active"
             else "Active again")
    con.execute(
        "INSERT INTO student_log(user_id,kind,title,body,at,by_id,by_name,"
        " created_at) VALUES(?,?,?,?,?,?,?,?)",
        (uid, "status", title,
         note.strip()[:400] + (f" · {ended} seat{'s' if ended != 1 else ''}"
                               f" ended" if ended else ""),
         at, by["id"], by["name"], db.now()))
    return {"status": status, "ended": ended}


# ── the record ───────────────────────────────────────────────────────────────

def record_of(con, user) -> dict:
    """One student's whole standing: per-course progress, attendance and
    every FINAL quiz result, derived on read. Shared by the learner's
    transcript and the office's page."""
    from . import assessment as A
    from . import classroom as CR
    from . import learning as L
    uid = user["id"]
    courses = []
    for c in con.execute(
            "SELECT c.*, u.name AS teacher_name FROM courses c"
            " LEFT JOIN users u ON u.id=c.teacher_id"
            " WHERE c.active=1 ORDER BY c.name").fetchall():
        if not L.enrolled_in(con, c["id"], uid):
            continue
        progress = L.course_progress(con, c["id"], uid)
        results = []
        for q in con.execute(
                "SELECT id, title, pass_mark FROM quizzes WHERE course_id=?"
                " AND published=1 ORDER BY id", (c["id"],)).fetchall():
            best = None
            for a in con.execute(
                    "SELECT id, graded_at FROM quiz_attempts WHERE quiz_id=?"
                    " AND user_id=? AND state='graded'",
                    (q["id"], uid)).fetchall():
                g = A.grade_attempt(L.questions(con, q["id"]),
                                    L.responses(con, a["id"]),
                                    pass_mark=q["pass_mark"])
                if g["is_final"] and (best is None
                                      or g["percent"] > best["percent"]):
                    best = {"quiz": q["title"], "percent": g["percent"],
                            "passed": g["passed"],
                            "pass_mark": q["pass_mark"],
                            "graded_at": a["graded_at"]}
            if best:
                results.append(best)
        att = CR.attendance_of(con, c["id"], uid)
        complete = (progress["percent"] == 100
                    and progress["lessons_total"]
                    + progress["quizzes_total"] > 0)
        courses.append({
            "id": c["id"], "name": c["name"],
            "language": c["language"] or "", "level": c["level"] or "",
            "teacher": c["teacher_name"] or "",
            "progress": progress, "attendance": att,
            "results": results, "complete": complete})
    attended = con.execute(
        "SELECT COUNT(*) AS n FROM checkins WHERE student_id=?"
        " AND status IN ('present','late')", (uid,)).fetchone()["n"]
    return {
        "student": {"id": uid, "name": user["name"],
                    "email": user["email"] or ""},
        "generated_at": time.time(),
        "courses": courses,
        "achievements": L.achievements_of(con, uid),
        "totals": {"courses": len(courses), "classes_attended": attended,
                   "quizzes_passed": sum(
                       1 for c in courses for r in c["results"]
                       if r["passed"]),
                   "completed_courses": sum(
                       1 for c in courses if c["complete"])},
    }


def timeline_of(con, uid: int, limit: int = 300) -> list:
    """Everything that happened to this student, newest first, from the
    tables that recorded it: seats taken and left, every class attended
    or missed, every graded quiz, every badge, every ask for help, and
    what staff wrote down. Each entry says which table it came from, so
    a reader can tell a fact from an opinion."""
    from . import assessment as A
    from . import learning as L
    ev = []
    for r in con.execute(
            "SELECT e.since, e.until, e.source, c.name FROM enrollments e"
            " JOIN courses c ON c.id=e.course_id WHERE e.user_id=?",
            (uid,)):
        ev.append({"at": r["since"], "kind": "enrolled",
                   "title": f"Joined {r['name']}",
                   "body": "" if r["source"] == "manual" else r["source"]})
        if r["until"]:
            ev.append({"at": r["until"], "kind": "left",
                       "title": f"Left {r['name']}", "body": ""})
    for r in con.execute(
            "SELECT k.at, k.status, k.method, k.note, c.name,"
            " s.started_at FROM checkins k"
            " JOIN class_sessions s ON s.id=k.session_id"
            " JOIN courses c ON c.id=s.course_id WHERE k.student_id=?",
            (uid,)):
        ev.append({"at": r["at"], "kind": "class", "status": r["status"],
                   "title": f"{r['status'].title()} — {r['name']}",
                   "body": (f"marked by teacher" if r["method"] == "teacher"
                            else "checked in" if r["method"] == "self"
                            else "recorded")
                   + (f" · {r['note']}" if r["note"] else "")})
    for r in con.execute(
            "SELECT a.id, a.graded_at, q.title, q.pass_mark, q.id AS qid,"
            " c.name FROM quiz_attempts a JOIN quizzes q ON q.id=a.quiz_id"
            " JOIN courses c ON c.id=q.course_id"
            " WHERE a.user_id=? AND a.state='graded'", (uid,)):
        g = A.grade_attempt(L.questions(con, r["qid"]),
                            L.responses(con, r["id"]),
                            pass_mark=r["pass_mark"])
        if not g["is_final"]:
            continue
        ev.append({"at": r["graded_at"], "kind": "quiz",
                   "percent": g["percent"], "passed": g["passed"],
                   "title": f"{r['title']}: {g['percent']}%"
                            + (" — passed" if g["passed"] else " — not yet"),
                   "body": r["name"]})
    for a in L.achievements_of(con, uid):
        ev.append({"at": a["earned_at"], "kind": "achievement",
                   "title": a["name"], "body": a["what"]})
    for r in con.execute(
            "SELECT t.created_at, t.state, t.note, t.reply, c.name,"
            " u.name AS tutor FROM tutoring_requests t"
            " JOIN courses c ON c.id=t.course_id"
            " LEFT JOIN users u ON u.id=t.taken_by WHERE t.user_id=?",
            (uid,)):
        ev.append({"at": r["created_at"], "kind": "tutoring",
                   "title": f"Asked for tutoring — {r['name']}",
                   "body": (r["note"] or "")
                   + (f" · {r['state']}" + (f" by {r['tutor']}"
                                            if r["tutor"] else "")
                      if r["state"] != "open" else " · open")})
    for r in con.execute(
            "SELECT l.starts, l.hours, l.kind, l.note, l.state,"
            " u.name AS who FROM logged_hours l JOIN users u ON u.id=l.user_id"
            " WHERE l.student_id=? AND l.state IN ('approved','pending')",
            (uid,)):
        ev.append({"at": r["starts"], "kind": "session",
                   "title": f"{r['hours']:g}h {r['kind']} with {r['who']}",
                   "body": (r["note"] or "")
                   + ("" if r["state"] == "approved"
                      else " · awaiting approval")})
    for r in con.execute(
            "SELECT id, kind, title, body, at, by_name FROM student_log"
            " WHERE user_id=?", (uid,)):
        ev.append({"at": r["at"], "kind": "log:" + r["kind"], "id": r["id"],
                   "title": r["title"], "body": r["body"],
                   "by": r["by_name"]})
    for r in con.execute(
            "SELECT id, status, total_cents, created_at FROM orders"
            " WHERE user_id=? AND status!='cancelled'", (uid,)):
        ev.append({"at": r["created_at"], "kind": "order",
                   "title": f"Order #{r['id']} — {r['status']}",
                   "body": f"{r['total_cents'] / 100:.2f}"})
    ev.sort(key=lambda e: e["at"] or 0, reverse=True)
    return ev[:limit]


def summary_of(con, uid: int, record: dict) -> dict:
    """The numbers at the top of the page."""
    marks = con.execute(
        "SELECT status, COUNT(*) AS n FROM checkins WHERE student_id=?"
        " GROUP BY status", (uid,)).fetchall()
    by = {r["status"]: r["n"] for r in marks}
    marked = sum(by.values())
    present = by.get("present", 0) + by.get("late", 0)
    scores = [r["percent"] for c in record["courses"] for r in c["results"]]
    return {
        "classes_attended": present,
        "classes_marked": marked,
        "late": by.get("late", 0),
        "absent": by.get("absent", 0),
        "excused": by.get("excused", 0),
        "attendance_pct": round(100 * present / marked) if marked else None,
        "quizzes_taken": len(scores),
        "quizzes_passed": record["totals"]["quizzes_passed"],
        "average_score": round(sum(scores) / len(scores)) if scores else None,
        "courses": record["totals"]["courses"],
        "completed_courses": record["totals"]["completed_courses"],
        "progress_pct": round(sum(c["progress"]["percent"]
                                  for c in record["courses"])
                              / len(record["courses"]))
        if record["courses"] else None,
        "achievements": len(record["achievements"]) + con.execute(
            "SELECT COUNT(*) AS n FROM student_log WHERE user_id=?"
            " AND kind='achievement'", (uid,)).fetchone()["n"],
    }


# ── routes ───────────────────────────────────────────────────────────────────

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _student(con, uid: int):
    u = con.execute("SELECT * FROM users WHERE id=? AND erased_at IS NULL",
                    (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    return u


@router.get("/api/students/{uid}")
def student_page(uid: int, user=Depends(current_user), con=Depends(get_con)):
    _require_office(user)
    u = _student(con, uid)
    rec = record_of(con, u)
    logged = [dict(r) for r in con.execute(
        "SELECT id, kind, title, body, at, by_name FROM student_log"
        " WHERE user_id=? AND kind='achievement' ORDER BY at DESC", (uid,))]
    seats = [dict(r) for r in con.execute(
        "SELECT e.id, e.course_id, e.since, e.until, e.source, c.name"
        " FROM enrollments e JOIN courses c ON c.id=e.course_id"
        " WHERE e.user_id=? ORDER BY e.since DESC", (uid,))]
    return {
        "student": {"id": u["id"], "name": u["name"],
                    "email": u["email"] or "", "photo": u["photo"] or "",
                    "role": u["role"], "active": bool(u["active"]),
                    "created_at": u["created_at"],
                    "region": u["region"] or ""},
        "profile": profile_of(con, uid),
        "fields": list(PROFILE_FIELDS),
        "summary": summary_of(con, uid, rec),
        "courses": rec["courses"],
        "seats": seats,
        "achievements": rec["achievements"],
        "logged_achievements": logged,
        "timeline": timeline_of(con, uid),
        "log_kinds": list(LOG_KINDS),
        "achievement_presets": list(ACHIEVEMENT_PRESETS),
        "statuses": [{"code": k, "label": STATUS_LABELS[k]} for k in STATUSES],
        "may_edit": True,
        "admin": bool(user["is_admin"]),
    }


class ProfileBody(BaseModel):
    fields: dict = {}
    extra: dict | None = None


@router.post("/api/students/{uid}/profile")
def student_profile_save(uid: int, body: ProfileBody,
                         user=Depends(current_user), con=Depends(get_con)):
    _require_office(user)
    _student(con, uid)
    out = save_profile(con, uid, body.fields, body.extra, by=user["name"])
    con.commit()
    return {"ok": True, "profile": out}


class StatusBody(BaseModel):
    status: str = "active"
    note: str = ""
    at: float = 0
    end_seats: bool = False


@router.post("/api/students/{uid}/status")
def student_status(uid: int, body: StatusBody, user=Depends(current_user),
                   con=Depends(get_con)):
    _require_office(user)
    _student(con, uid)
    at = body.at or time.time()
    if at > time.time() + 86400:
        raise HTTPException(400, "a status is what is, not what will be")
    out = set_status(con, uid, body.status, body.note, at, user,
                     body.end_seats)
    con.commit()
    return {"ok": True, **out, "profile": profile_of(con, uid)}


class LogBody(BaseModel):
    kind: str = "note"
    title: str
    body: str = ""
    at: float = 0


@router.post("/api/students/{uid}/log")
def student_log_add(uid: int, body: LogBody, user=Depends(current_user),
                    con=Depends(get_con)):
    """Something a member of staff noticed and wrote down. Dated when it
    happened, not when it was typed — a prize won in March is a March
    fact even if it is filed in May."""
    _require_office(user)
    _student(con, uid)
    if body.kind not in LOG_KINDS:
        raise HTTPException(400, f"kind must be one of {LOG_KINDS}")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "say what it was")
    at = body.at or time.time()
    if at > time.time() + 86400:
        raise HTTPException(400, "the log records what happened, not what"
                                 " will")
    cur = con.execute(
        "INSERT INTO student_log(user_id,kind,title,body,at,by_id,by_name,"
        " created_at) VALUES(?,?,?,?,?,?,?,?)",
        (uid, body.kind, title[:200], body.body.strip()[:2000], at,
         user["id"], user["name"], db.now()))
    con.commit()
    if body.kind == "achievement":
        from . import notify
        try:
            notify.push(con, f"Achievement: {title[:120]}",
                        body.body.strip()[:200] or f"logged by {user['name']}",
                        kind="learning", user_id=uid)
        except Exception:                                    # noqa: BLE001
            pass
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/students/{uid}/log/{lid}")
def student_log_del(uid: int, lid: int, user=Depends(current_user),
                    con=Depends(get_con)):
    _require_office(user)
    r = con.execute("SELECT * FROM student_log WHERE id=? AND user_id=?",
                    (lid, uid)).fetchone()
    if r is None:
        raise HTTPException(404, "no such entry")
    if r["by_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "only its author or an admin removes an"
                                 " entry")
    con.execute("DELETE FROM student_log WHERE id=?", (lid,))
    con.commit()
    return {"ok": True}


# ── the learner's own hand on the profile ────────────────────────────────────

SELF_FIELDS = ("birth_date", "gender", "nationality", "origin",
               "native_language", "other_languages", "education",
               "occupation", "phone", "address", "guardian",
               "emergency_contact", "goals", "needs")


def self_view(con, uid: int) -> dict:
    """What the student may see and change of their own profile: every
    field but the office's notes. The office's extra questions they may
    see, not alter."""
    p = profile_of(con, uid)
    return {k: p[k] for k in SELF_FIELDS} | {"age": p["age"],
                                             "extra": p["extra"]}


def self_save(con, uid: int, fields: dict, by: str) -> dict:
    allowed = {k: v for k, v in fields.items() if k in SELF_FIELDS}
    save_profile(con, uid, allowed, None, by=by)
    return self_view(con, uid)
