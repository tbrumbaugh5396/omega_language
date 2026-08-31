"""Learning — courses, lessons, quizzes, enrollment. The LMS behind the
Learning capability, ported from lingua-portal.

What moved and what changed in the move:

- The grading rules came over untouched — they live in `assessment.py`
  (pure, no database, no clock) and this module only loads and saves
  around them. The one rule with teeth carried over with them: **students
  never receive the answer key** — `quiz_for_student` strips it at the
  source, because filtering in the UI leaves the key sitting in the
  network tab.
- The source's `people` roles (student/teacher/admin) map onto this app's
  users: an admin or the course's appointed teacher may edit; everyone
  else is a learner, and *enrollment* — not role — is what lets a learner
  read published lessons and take quizzes. A customer, an employee being
  cross-trained, a distributor's buyer: all enrol the same way.
- The source had no payments, so enrollment was always a clerk's act.
  Here a course can name a product (`courses.product_id`), and buying
  that product enrols you — the storefront's whole checkout rail becomes
  the admissions office. Manual enrollment stays for comped seats.
- Lesson ordering renormalises to 0,1,2,… on every move, exactly as the
  source did: sparse indices save a write and eventually produce two
  lessons at the same position.
- Recorded answers (speaking/video) are understood by the grading engine
  but not yet authorable — the classroom phase of the port brings the
  recording flow with it. A text question with no answer key already
  exercises the human-grading path end to end.
"""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import assessment as A
from . import db, notify

TABLES = """
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  language TEXT DEFAULT '',
  level TEXT DEFAULT '',
  blurb TEXT DEFAULT '',
  teacher_id INTEGER,                 -- users.id; may edit besides admins
  product_id INTEGER,                 -- buying this product enrols you
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  since REAL NOT NULL,
  until REAL,                         -- NULL = current
  source TEXT DEFAULT 'manual',       -- manual | order:<id>
  UNIQUE(course_id, user_id)
);

CREATE TABLE IF NOT EXISTS lessons (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT DEFAULT '',               -- markdown
  position INTEGER NOT NULL DEFAULT 0,
  published INTEGER DEFAULT 0,
  created_by INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson_progress (
  lesson_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  done_at REAL NOT NULL,
  PRIMARY KEY (lesson_id, user_id)
);

CREATE TABLE IF NOT EXISTS quizzes (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  lesson_id INTEGER,
  title TEXT NOT NULL,
  intro TEXT DEFAULT '',
  pass_mark INTEGER DEFAULT 60,
  published INTEGER DEFAULT 0,
  created_by INTEGER,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_questions (
  id INTEGER PRIMARY KEY,
  quiz_id INTEGER NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL,                 -- choice|multi|text (speaking/video await the classroom phase)
  prompt TEXT NOT NULL,
  choices_json TEXT DEFAULT '[]',
  answer_json TEXT DEFAULT '[]',
  accepted_json TEXT DEFAULT '[]',
  points INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
  id INTEGER PRIMARY KEY,
  quiz_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  started_at REAL NOT NULL,
  submitted_at REAL,
  graded_at REAL,
  graded_by INTEGER,
  state TEXT NOT NULL DEFAULT 'open'  -- open|submitted|graded
);

CREATE TABLE IF NOT EXISTS quiz_responses (
  attempt_id INTEGER NOT NULL,
  question_id INTEGER NOT NULL,
  chosen_json TEXT DEFAULT '[]',
  text TEXT DEFAULT '',
  awarded REAL,
  feedback TEXT DEFAULT '',
  PRIMARY KEY (attempt_id, question_id)
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── access rules ─────────────────────────────────────────────────────────────

def may_edit(con, user, course_id: int) -> bool:
    if user["is_admin"]:
        return True
    r = con.execute("SELECT teacher_id FROM courses WHERE id=?",
                    (course_id,)).fetchone()
    return bool(r and r["teacher_id"] == user["id"])


def enrolled_in(con, course_id: int, user_id: int) -> bool:
    r = con.execute(
        "SELECT 1 FROM enrollments WHERE course_id=? AND user_id=?"
        " AND (until IS NULL OR until > ?)",
        (course_id, user_id, time.time())).fetchone()
    return r is not None


def visible_to(con, user, lesson) -> bool:
    """The single visibility rule, straight from the source: drafts are for
    whoever may edit the course; published lessons are for the enrolled."""
    if may_edit(con, user, lesson["course_id"]):
        return True
    if not lesson["published"]:
        return False
    return enrolled_in(con, lesson["course_id"], user["id"])


# ── enrollment ───────────────────────────────────────────────────────────────

def enroll(con, course_id: int, user_id: int, source: str = "manual") -> bool:
    """Idempotent: re-enrolling a lapsed seat revives it, an active one is a
    no-op. Returns whether anything changed."""
    cur = con.execute(
        "SELECT id, until FROM enrollments WHERE course_id=? AND user_id=?",
        (course_id, user_id)).fetchone()
    if cur is None:
        con.execute(
            "INSERT INTO enrollments(course_id,user_id,since,source)"
            " VALUES(?,?,?,?)", (course_id, user_id, time.time(), source))
        return True
    if cur["until"] is not None:
        con.execute("UPDATE enrollments SET until=NULL, since=?, source=?"
                    " WHERE id=?", (time.time(), source, cur["id"]))
        return True
    return False


def enroll_by_order(con, order_id: int, user_id: int) -> list:
    """A placed order enrols its buyer in every course whose product it
    contains. The order is admissions — no clerk in the loop."""
    rows = con.execute(
        "SELECT DISTINCT c.id, c.name FROM order_items oi"
        " JOIN courses c ON c.product_id = oi.product_id AND c.active=1"
        " WHERE oi.order_id=?", (order_id,)).fetchall()
    enrolled = []
    for r in rows:
        if enroll(con, r["id"], user_id, source=f"order:{order_id}"):
            enrolled.append(r["name"])
    return enrolled


# ── lessons ──────────────────────────────────────────────────────────────────

def renumber(con, course_id: int) -> None:
    for i, r in enumerate(con.execute(
            "SELECT id FROM lessons WHERE course_id=? ORDER BY position, id",
            (course_id,)).fetchall()):
        con.execute("UPDATE lessons SET position=? WHERE id=?", (i, r["id"]))


def lessons_for(con, user, course_id: int) -> list:
    rows = [dict(r) for r in con.execute(
        "SELECT id, course_id, title, position, published, updated_at"
        " FROM lessons WHERE course_id=? ORDER BY position, id",
        (course_id,)).fetchall()]
    return [r for r in rows if visible_to(con, user, r)]


# ── quiz storage around the pure engine ──────────────────────────────────────

def questions(con, quiz_id: int) -> list:
    return [A.Question(
        id=r["id"], kind=r["kind"], prompt=r["prompt"],
        choices=json.loads(r["choices_json"] or "[]"),
        answer=json.loads(r["answer_json"] or "[]"),
        accepted=json.loads(r["accepted_json"] or "[]"),
        points=r["points"], position=r["position"],
    ) for r in con.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id=? ORDER BY position, id",
        (quiz_id,)).fetchall()]


def responses(con, attempt_id: int) -> list:
    return [A.Response(
        question_id=r["question_id"],
        chosen=json.loads(r["chosen_json"] or "[]"),
        text=r["text"] or "", awarded=r["awarded"],
        feedback=r["feedback"] or "")
        for r in con.execute(
            "SELECT * FROM quiz_responses WHERE attempt_id=?",
            (attempt_id,)).fetchall()]


def get_quiz(con, quiz_id: int):
    r = con.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "quiz not found")
    return dict(r)


def quiz_for_student(con, user, quiz_id: int) -> dict:
    """The quiz as a LEARNER may receive it — answer key removed at the
    source, not in the UI."""
    quiz = get_quiz(con, quiz_id)
    editable = may_edit(con, user, quiz["course_id"])
    if not quiz["published"] and not editable:
        raise HTTPException(403, "this quiz is not published")
    if not editable and not enrolled_in(con, quiz["course_id"], user["id"]):
        raise HTTPException(403, "you are not enrolled in this course")
    qs = []
    for q in questions(con, quiz_id):
        item = {"id": q.id, "kind": q.kind, "prompt": q.prompt,
                "points": q.points, "position": q.position}
        if q.kind in (A.CHOICE, A.MULTI):
            item["choices"] = q.choices     # options yes — which are correct, no
        if editable:                        # authors see the key
            item["answer"] = q.answer
            item["accepted"] = q.accepted
        qs.append(item)
    quiz["questions"] = qs
    quiz["may_edit"] = editable
    return quiz


def own_attempt(con, user, attempt_id: int) -> dict:
    a = con.execute("SELECT * FROM quiz_attempts WHERE id=?",
                    (attempt_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "attempt not found")
    a = dict(a)
    if a["user_id"] != user["id"] and not may_edit(
            con, user, get_quiz(con, a["quiz_id"])["course_id"]):
        raise HTTPException(403, "that is not your attempt")
    return a


def start_attempt(con, user, quiz_id: int) -> dict:
    quiz = get_quiz(con, quiz_id)
    if not quiz["published"]:
        raise HTTPException(403, "this quiz is not open yet")
    if not enrolled_in(con, quiz["course_id"], user["id"]):
        raise HTTPException(403, "you are not enrolled in this course")
    prev = con.execute(
        "SELECT * FROM quiz_attempts WHERE quiz_id=? AND user_id=?"
        " ORDER BY id DESC LIMIT 1", (quiz_id, user["id"])).fetchone()
    if prev and prev["state"] == "open":
        return dict(prev)                   # resume, never a silent second attempt
    cur = con.execute(
        "INSERT INTO quiz_attempts(quiz_id,user_id,started_at,state)"
        " VALUES(?,?,?,'open')", (quiz_id, user["id"], time.time()))
    return dict(con.execute("SELECT * FROM quiz_attempts WHERE id=?",
                            (cur.lastrowid,)).fetchone())


def save_answer(con, user, attempt_id: int, question_id: int, *,
                chosen=None, text: str = "") -> None:
    a = own_attempt(con, user, attempt_id)
    if a["state"] != "open":
        raise HTTPException(409, "this attempt has been submitted")
    con.execute(
        "INSERT INTO quiz_responses(attempt_id,question_id,chosen_json,text)"
        " VALUES(?,?,?,?)"
        " ON CONFLICT(attempt_id,question_id) DO UPDATE SET"
        "  chosen_json=excluded.chosen_json, text=excluded.text",
        (attempt_id, question_id, json.dumps(list(chosen or [])),
         str(text or "")[:5000]))


def attempt_result(con, user, attempt_id: int) -> dict:
    a = own_attempt(con, user, attempt_id)
    quiz = get_quiz(con, a["quiz_id"])
    grade = A.grade_attempt(questions(con, a["quiz_id"]),
                            responses(con, attempt_id),
                            pass_mark=quiz["pass_mark"])
    out = {"attempt": a, "quiz": {k: quiz[k] for k in
                                  ("id", "title", "course_id", "pass_mark")},
           "grade": grade}
    if not may_edit(con, user, quiz["course_id"]):
        # A provisional score is never shown as a score.
        out["grade"] = {**A.summarise_for_student(grade),
                        "marks_visible": grade["is_final"]}
        if grade["is_final"]:
            out["grade"]["marks"] = grade["marks"]
    return out


def submit_attempt(con, user, attempt_id: int) -> dict:
    a = own_attempt(con, user, attempt_id)
    if a["state"] != "open":
        return attempt_result(con, user, attempt_id)
    con.execute("UPDATE quiz_attempts SET submitted_at=?, state='submitted'"
                " WHERE id=?", (time.time(), attempt_id))
    quiz = get_quiz(con, a["quiz_id"])
    grade = A.grade_attempt(questions(con, a["quiz_id"]),
                            responses(con, attempt_id),
                            pass_mark=quiz["pass_mark"])
    if grade["is_final"]:                   # nothing needs a human — settle now
        con.execute("UPDATE quiz_attempts SET state='graded', graded_at=?"
                    " WHERE id=?", (time.time(), attempt_id))
    else:
        notify.push(
            con, f"Quiz to grade: {quiz['title']}",
            f"{user['name']} submitted answers that need a human mark",
            kind="learning", dedup=f"grade:{attempt_id}")
    return attempt_result(con, user, attempt_id)


def grade_response(con, grader, attempt_id: int, question_id: int, *,
                   awarded: float, feedback: str = "") -> dict:
    """A teacher marks one written answer; when nothing is left pending the
    attempt settles and the learner is told."""
    a = con.execute("SELECT * FROM quiz_attempts WHERE id=?",
                    (attempt_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "attempt not found")
    quiz = get_quiz(con, a["quiz_id"])
    if not may_edit(con, grader, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    con.execute(
        "INSERT INTO quiz_responses(attempt_id,question_id,awarded,feedback)"
        " VALUES(?,?,?,?)"
        " ON CONFLICT(attempt_id,question_id) DO UPDATE SET"
        "  awarded=excluded.awarded, feedback=excluded.feedback",
        (attempt_id, question_id, float(awarded), str(feedback or "")[:2000]))
    grade = A.grade_attempt(questions(con, a["quiz_id"]),
                            responses(con, attempt_id),
                            pass_mark=quiz["pass_mark"])
    if grade["is_final"] and a["state"] != "graded":
        con.execute("UPDATE quiz_attempts SET state='graded', graded_at=?,"
                    " graded_by=? WHERE id=?",
                    (time.time(), grader["id"], attempt_id))
        notify.push(con, f"Your quiz was graded: {quiz['title']}",
                    f"scored {grade['percent']}%", kind="learning",
                    user_id=a["user_id"], dedup=f"graded:{attempt_id}")
    return grade


def grading_queue(con, user) -> list:
    """Submitted attempts in courses this user teaches that still need a
    human mark."""
    rows = con.execute(
        "SELECT a.*, q.title AS quiz_title, q.course_id, u.name AS student"
        " FROM quiz_attempts a JOIN quizzes q ON q.id=a.quiz_id"
        " JOIN users u ON u.id=a.user_id"
        " WHERE a.state='submitted' ORDER BY a.submitted_at").fetchall()
    out = []
    for r in rows:
        if not may_edit(con, user, r["course_id"]):
            continue
        grade = A.grade_attempt(questions(con, r["quiz_id"]),
                                responses(con, r["id"]))
        if grade["is_final"]:
            continue
        item = dict(r)
        item["pending"] = grade["pending"]
        out.append(item)
    return out


# ── progress ─────────────────────────────────────────────────────────────────

def course_progress(con, course_id: int, user_id: int) -> dict:
    """What the deck promised as 'progress': published lessons done, quizzes
    passed. Derived, never stored — like every grade here."""
    total = con.execute(
        "SELECT COUNT(*) AS n FROM lessons WHERE course_id=? AND published=1",
        (course_id,)).fetchone()["n"]
    done = con.execute(
        "SELECT COUNT(*) AS n FROM lesson_progress p"
        " JOIN lessons l ON l.id=p.lesson_id"
        " WHERE l.course_id=? AND l.published=1 AND p.user_id=?",
        (course_id, user_id)).fetchone()["n"]
    quizzes_total = con.execute(
        "SELECT COUNT(*) AS n FROM quizzes WHERE course_id=? AND published=1",
        (course_id,)).fetchone()["n"]
    passed = 0
    for q in con.execute(
            "SELECT id, pass_mark FROM quizzes WHERE course_id=?"
            " AND published=1", (course_id,)).fetchall():
        for a in con.execute(
                "SELECT id FROM quiz_attempts WHERE quiz_id=? AND user_id=?"
                " AND state='graded'", (q["id"], user_id)).fetchall():
            g = A.grade_attempt(questions(con, q["id"]),
                                responses(con, a["id"]),
                                pass_mark=q["pass_mark"])
            if g["is_final"] and g["passed"]:
                passed += 1
                break
    return {"lessons_done": done, "lessons_total": total,
            "quizzes_passed": passed, "quizzes_total": quizzes_total,
            "percent": round(100.0 * (done + passed) /
                             max(1, total + quizzes_total))}


# ── ops routes ───────────────────────────────────────────────────────────────
# The staff side: authoring, enrollment and grading, under the ops app's own
# auth. The learner side lives on the storefront (storefront/backend/learn.py)
# behind the tenant's Learning entitlement.

router = APIRouter()

# main.py imports this module only after those dependencies exist (schema init
# and router registration both happen late in main), so the import back is
# safe — and it means one auth story, not a copy.
from .main import admin_user, current_user, get_con  # noqa: E402


class CourseBody(BaseModel):
    name: str = ""
    language: str = ""
    level: str = ""
    blurb: str = ""
    teacher_id: int | None = None
    product_id: int | None = None
    active: int = 1


@router.get("/api/learning/courses")
def ops_courses(user=Depends(current_user), con=Depends(get_con)):
    rows = [dict(r) for r in con.execute(
        "SELECT c.*, u.name AS teacher_name,"
        " (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id"
        "   AND (e.until IS NULL OR e.until > ?)) AS enrolled,"
        " (SELECT COUNT(*) FROM lessons l WHERE l.course_id=c.id) AS lessons,"
        " (SELECT COUNT(*) FROM quizzes q WHERE q.course_id=c.id) AS quizzes"
        " FROM courses c LEFT JOIN users u ON u.id=c.teacher_id"
        " ORDER BY c.active DESC, c.name", (time.time(),)).fetchall()]
    if not user["is_admin"]:
        rows = [r for r in rows if r["teacher_id"] == user["id"]]
    return rows


@router.post("/api/learning/courses")
def ops_course_create(body: CourseBody, user=Depends(admin_user),
                      con=Depends(get_con)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a course needs a name")
    cur = con.execute(
        "INSERT INTO courses(name,language,level,blurb,teacher_id,product_id,"
        " active,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (name[:200], body.language.strip()[:60], body.level.strip()[:60],
         body.blurb.strip()[:2000], body.teacher_id, body.product_id,
         1 if body.active else 0, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/learning/courses/{cid}")
def ops_course_update(cid: int, body: CourseBody, user=Depends(current_user),
                      con=Depends(get_con)):
    if not may_edit(con, user, cid):
        raise HTTPException(403, "you do not teach this course")
    if con.execute("SELECT 1 FROM courses WHERE id=?", (cid,)).fetchone() is None:
        raise HTTPException(404, "course not found")
    # teacher/product/active are commercial facts — admins only
    if user["is_admin"]:
        con.execute(
            "UPDATE courses SET name=?, language=?, level=?, blurb=?,"
            " teacher_id=?, product_id=?, active=? WHERE id=?",
            (body.name.strip()[:200] or "Untitled",
             body.language.strip()[:60], body.level.strip()[:60],
             body.blurb.strip()[:2000], body.teacher_id, body.product_id,
             1 if body.active else 0, cid))
    else:
        con.execute("UPDATE courses SET name=?, language=?, level=?, blurb=?"
                    " WHERE id=?",
                    (body.name.strip()[:200] or "Untitled",
                     body.language.strip()[:60], body.level.strip()[:60],
                     body.blurb.strip()[:2000], cid))
    con.commit()
    return {"ok": True}


@router.get("/api/learning/courses/{cid}")
def ops_course_detail(cid: int, user=Depends(current_user),
                      con=Depends(get_con)):
    c = con.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "course not found")
    if not may_edit(con, user, cid):
        raise HTTPException(403, "you do not teach this course")
    d = dict(c)
    d["lessons"] = [dict(r) for r in con.execute(
        "SELECT id, title, position, published, updated_at FROM lessons"
        " WHERE course_id=? ORDER BY position, id", (cid,)).fetchall()]
    d["quizzes"] = [dict(r) for r in con.execute(
        "SELECT q.*, (SELECT COUNT(*) FROM quiz_questions x"
        "  WHERE x.quiz_id=q.id) AS questions"
        " FROM quizzes q WHERE q.course_id=? ORDER BY q.id", (cid,)).fetchall()]
    d["enrollments"] = [dict(r) for r in con.execute(
        "SELECT e.id, e.user_id, e.since, e.until, e.source, u.name, u.role"
        " FROM enrollments e JOIN users u ON u.id=e.user_id"
        " WHERE e.course_id=? ORDER BY e.since DESC", (cid,)).fetchall()]
    for e in d["enrollments"]:
        e["progress"] = course_progress(con, cid, e["user_id"])
    return d


class EnrollBody(BaseModel):
    user_id: int = 0
    name: str = ""


@router.post("/api/learning/courses/{cid}/enroll")
def ops_enroll(cid: int, body: EnrollBody, user=Depends(admin_user),
               con=Depends(get_con)):
    if con.execute("SELECT 1 FROM courses WHERE id=?", (cid,)).fetchone() is None:
        raise HTTPException(404, "course not found")
    uid = body.user_id
    if not uid and body.name.strip():
        u = con.execute("SELECT id FROM users WHERE name=? AND active=1",
                        (body.name.strip(),)).fetchone()
        if u is None:
            raise HTTPException(404, "no user by that name")
        uid = u["id"]
    if not con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        raise HTTPException(404, "user not found")
    enroll(con, cid, uid, source=f"manual:{user['name']}")
    con.commit()
    return {"ok": True}


@router.post("/api/learning/enrollments/{eid}/end")
def ops_unenroll(eid: int, user=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE enrollments SET until=? WHERE id=? AND until IS NULL",
                (time.time(), eid))
    con.commit()
    return {"ok": True}


class LessonBody(BaseModel):
    course_id: int = 0
    title: str = ""
    body: str = ""
    published: int | None = None


@router.post("/api/learning/lessons")
def ops_lesson_create(body: LessonBody, user=Depends(current_user),
                      con=Depends(get_con)):
    if not may_edit(con, user, body.course_id):
        raise HTTPException(403, "you do not teach this course")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a lesson needs a title")
    nxt = con.execute(
        "SELECT COALESCE(MAX(position),-1)+1 AS p FROM lessons"
        " WHERE course_id=?", (body.course_id,)).fetchone()["p"]
    now = time.time()
    cur = con.execute(
        "INSERT INTO lessons(course_id,title,body,position,published,"
        " created_by,created_at,updated_at) VALUES(?,?,?,?,0,?,?,?)",
        (body.course_id, title[:200], body.body, nxt, user["id"], now, now))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/learning/lessons/{lid}")
def ops_lesson_update(lid: int, body: LessonBody, user=Depends(current_user),
                      con=Depends(get_con)):
    r = con.execute("SELECT course_id FROM lessons WHERE id=?",
                    (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    if not may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    con.execute(
        "UPDATE lessons SET title=?, body=?, published=?, updated_at=?"
        " WHERE id=?",
        (body.title.strip()[:200] or "Untitled", body.body,
         1 if body.published else 0, time.time(), lid))
    con.commit()
    return {"ok": True}


@router.get("/api/learning/lessons/{lid}")
def ops_lesson_get(lid: int, user=Depends(current_user),
                   con=Depends(get_con)):
    r = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    if not may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    return dict(r)


class MoveBody(BaseModel):
    direction: int = 1


@router.post("/api/learning/lessons/{lid}/move")
def ops_lesson_move(lid: int, body: MoveBody, user=Depends(current_user),
                    con=Depends(get_con)):
    r = con.execute("SELECT course_id, position FROM lessons WHERE id=?",
                    (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    if not may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    # position*2 gives room to land between neighbours; renumber re-densifies
    con.execute("UPDATE lessons SET position=? WHERE id=?",
                (r["position"] * 2 + (3 if body.direction > 0 else -3), lid))
    con.execute("UPDATE lessons SET position=position*2"
                " WHERE course_id=? AND id != ?", (r["course_id"], lid))
    renumber(con, r["course_id"])
    con.commit()
    return {"ok": True}


@router.post("/api/learning/lessons/{lid}/delete")
def ops_lesson_delete(lid: int, user=Depends(current_user),
                      con=Depends(get_con)):
    r = con.execute("SELECT course_id FROM lessons WHERE id=?",
                    (lid,)).fetchone()
    if r is None:
        return {"ok": True}
    if not may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    con.execute("DELETE FROM lessons WHERE id=?", (lid,))
    con.execute("DELETE FROM lesson_progress WHERE lesson_id=?", (lid,))
    renumber(con, r["course_id"])
    con.commit()
    return {"ok": True}


class QuizBody(BaseModel):
    course_id: int = 0
    lesson_id: int | None = None
    title: str = ""
    intro: str = ""
    pass_mark: int = 60
    published: int | None = None


@router.post("/api/learning/quizzes")
def ops_quiz_create(body: QuizBody, user=Depends(current_user),
                    con=Depends(get_con)):
    if not may_edit(con, user, body.course_id):
        raise HTTPException(403, "you do not teach this course")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a quiz needs a title")
    cur = con.execute(
        "INSERT INTO quizzes(course_id,lesson_id,title,intro,pass_mark,"
        " published,created_by,created_at) VALUES(?,?,?,?,?,0,?,?)",
        (body.course_id, body.lesson_id, title[:200], body.intro[:2000],
         int(body.pass_mark), user["id"], time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/learning/quizzes/{qid}")
def ops_quiz_update(qid: int, body: QuizBody, user=Depends(current_user),
                    con=Depends(get_con)):
    quiz = get_quiz(con, qid)
    if not may_edit(con, user, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    con.execute(
        "UPDATE quizzes SET title=?, intro=?, pass_mark=?, published=?"
        " WHERE id=?",
        (body.title.strip()[:200] or quiz["title"], body.intro[:2000],
         int(body.pass_mark), 1 if body.published else 0, qid))
    con.commit()
    return {"ok": True}


@router.get("/api/learning/quizzes/{qid}")
def ops_quiz_get(qid: int, user=Depends(current_user), con=Depends(get_con)):
    quiz = get_quiz(con, qid)
    if not may_edit(con, user, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    return quiz_for_student(con, user, qid)   # editors get the key back


class QuestionBody(BaseModel):
    kind: str = "choice"
    prompt: str = ""
    choices: list[str] = []
    answer: list[int] = []
    accepted: list[str] = []
    points: int = 1


@router.post("/api/learning/quizzes/{qid}/questions")
def ops_question_add(qid: int, body: QuestionBody, user=Depends(current_user),
                     con=Depends(get_con)):
    quiz = get_quiz(con, qid)
    if not may_edit(con, user, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    if body.kind in A.RECORDED_KINDS:
        raise HTTPException(400, "recorded answers arrive with the classroom"
                                 " phase of the port — not yet authorable")
    try:
        A.validate_question(body.kind, body.prompt, body.choices, body.answer,
                            body.accepted, int(body.points))
    except A.QuizError as e:
        raise HTTPException(400, e.message)
    pos = con.execute(
        "SELECT COALESCE(MAX(position),-1)+1 AS p FROM quiz_questions"
        " WHERE quiz_id=?", (qid,)).fetchone()["p"]
    cur = con.execute(
        "INSERT INTO quiz_questions(quiz_id,position,kind,prompt,"
        " choices_json,answer_json,accepted_json,points)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (qid, pos, body.kind, body.prompt.strip()[:2000],
         json.dumps(body.choices), json.dumps(body.answer),
         json.dumps(body.accepted), int(body.points)))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/learning/questions/{xid}/delete")
def ops_question_delete(xid: int, user=Depends(current_user),
                        con=Depends(get_con)):
    r = con.execute("SELECT quiz_id FROM quiz_questions WHERE id=?",
                    (xid,)).fetchone()
    if r is None:
        return {"ok": True}
    quiz = get_quiz(con, r["quiz_id"])
    if not may_edit(con, user, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    con.execute("DELETE FROM quiz_questions WHERE id=?", (xid,))
    con.commit()
    return {"ok": True}


@router.get("/api/learning/grading")
def ops_grading(user=Depends(current_user), con=Depends(get_con)):
    return grading_queue(con, user)


@router.get("/api/learning/attempts/{aid}")
def ops_attempt(aid: int, user=Depends(current_user), con=Depends(get_con)):
    a = con.execute("SELECT * FROM quiz_attempts WHERE id=?",
                    (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "attempt not found")
    quiz = get_quiz(con, a["quiz_id"])
    if not may_edit(con, user, quiz["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    qs = questions(con, a["quiz_id"])
    rs = {r.question_id: r for r in responses(con, aid)}
    grade = A.grade_attempt(qs, list(rs.values()), pass_mark=quiz["pass_mark"])
    student = con.execute("SELECT name FROM users WHERE id=?",
                          (a["user_id"],)).fetchone()
    return {
        "attempt": dict(a), "quiz": quiz, "grade": grade,
        "student": student["name"] if student else "?",
        "items": [{
            "question_id": q.id, "kind": q.kind, "prompt": q.prompt,
            "choices": q.choices, "answer": q.answer, "accepted": q.accepted,
            "points": q.points,
            "chosen": rs[q.id].chosen if q.id in rs else [],
            "text": rs[q.id].text if q.id in rs else "",
            "awarded": rs[q.id].awarded if q.id in rs else None,
            "feedback": rs[q.id].feedback if q.id in rs else "",
        } for q in qs],
    }


class GradeBody(BaseModel):
    question_id: int = 0
    awarded: float = 0
    feedback: str = ""


@router.post("/api/learning/attempts/{aid}/grade")
def ops_grade(aid: int, body: GradeBody, user=Depends(current_user),
              con=Depends(get_con)):
    grade = grade_response(con, user, aid, body.question_id,
                           awarded=body.awarded, feedback=body.feedback)
    con.commit()
    return grade
