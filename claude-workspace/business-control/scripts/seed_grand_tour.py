#!/usr/bin/env python3
"""Seed "The Grand Tour — free demo": one free course that exercises every
Learning feature, so there is always a safe place to click everything.

What it plants, on any tenant with the Learning capability:

- a course taught by María Solís (or the first employee found), free —
  no product attached, seats are a clerk's act
- two published lessons showing the teacher-markdown rendering and
  explaining the live-class flow, the ID card and the calendar
- one published quiz, "Every kind of question": six questions across all
  five kinds — instant-graded choice, partial-credit multi, auto-marked
  text (accents forgiven), teacher-marked text, and speaking + video
  recorded answers that wait in the grading queue
- seats for Ana Ruiz and Bo Chen when they exist, otherwise the first
  few customers

It does NOT open a class session — that is the teacher's act, and the
demo of it: sign in at /ops as the course's teacher, open the course,
Start class. The banner, self check-in, badge scanning and the video
room all light up from that one click.

Idempotent: refuses to run if the course already exists on the tenant.
Usage: seed_grand_tour.py [tenant]     (default: lingua)
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TENANT = sys.argv[1] if len(sys.argv) > 1 else "lingua"
DB = ROOT / "data" / "tenants" / TENANT / "business_control.db"

COURSE = "The Grand Tour — free demo"

LESSON_1 = """# Welcome to the tour

This lesson shows the **markdown** a teacher writes: *emphasis*, `code`,
lists and links.

- Mark it done below — progress derives from published lessons and
  passed quizzes
- A teacher can attach an **audio or video drill** to any lesson
  (ops: Learning, this course, Edit lesson, Record)
- Draft lessons are invisible to learners until published

```
nothing here executes — code blocks are just prose
```"""

LESSON_2 = """# When class is on

When the teacher starts a session, this course page grows a
**Class is in session** banner: check in with one tap, or join the video
room. Your **Me** tab holds the printable ID card a teacher can scan at
the door instead.

The **Calendar** below the lessons shows every class held — your own
attendance dot, and any recording the teacher attached."""

QUESTIONS = (
    ("choice", "Which answer is graded instantly?",
     ["a single choice like this one", "a spoken answer", "an essay"],
     [0], [], 2),
    ("multi", "Which of these earn partial credit? (pick every correct one)",
     ["multi-select questions", "wrong picks (they subtract)", "this decoy",
      "floored at zero, never negative"], [0, 1, 3], [], 4),
    ("text", "Type the Spanish for 'thank you' (auto-marked: accents and"
     " case forgiven)", [], [], ["gracias"], 2),
    ("text", "In one sentence: why does the app never show a provisional"
     " score? (a teacher marks this one)", [], [], [], 3),
    ("speaking", "Record yourself saying hello in any language you're"
     " learning", [], [], [], 3),
    ("video", "On camera: introduce yourself in ten seconds",
     [], [], [], 3),
)


def main():
    import sqlite3
    if not DB.exists():
        print(f"no tenant database at {DB} — is the tenant stood up?")
        sys.exit(1)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT 1 FROM courses WHERE name=?",
                   (COURSE,)).fetchone():
        print(f"{TENANT} already has {COURSE!r} — nothing to do "
              "(idempotence, not laziness)")
        sys.exit(0)
    now = time.time()

    teacher = con.execute(
        "SELECT id FROM users WHERE name='María Solís' AND active=1"
        ).fetchone() or con.execute(
        "SELECT id FROM users WHERE role='employee' AND active=1"
        " ORDER BY id LIMIT 1").fetchone()
    if teacher is None:
        print("no employee to teach it — create a teacher first")
        sys.exit(1)

    cid = con.execute(
        "INSERT INTO courses(name,language,level,blurb,teacher_id,active,"
        " created_at) VALUES(?,?,?,?,?,1,?)",
        (COURSE, "Demo", "all",
         "One free course that exercises every feature: lessons, all five "
         "question kinds, live class with check-in and video, the "
         "calendar, and your ID card at the door.",
         teacher["id"], now)).lastrowid

    for i, (title, body) in enumerate((
            ("1 · How lessons work", LESSON_1),
            ("2 · The class, the call, the card", LESSON_2))):
        con.execute(
            "INSERT INTO lessons(course_id,title,body,position,published,"
            " created_by,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?)",
            (cid, title, body, i, teacher["id"], now, now))

    quiz = con.execute(
        "INSERT INTO quizzes(course_id,title,intro,pass_mark,published,"
        " created_by,created_at) VALUES(?,?,?,50,1,?,?)",
        (cid, "Every kind of question",
         "Six questions, five kinds. Accents and case are forgiven; "
         "recorded and free-text answers wait for a teacher, and you "
         "never see a provisional score.", teacher["id"], now)).lastrowid
    for pos, (kind, prompt, choices, answer, accepted, pts) in enumerate(
            QUESTIONS):
        con.execute(
            "INSERT INTO quiz_questions(quiz_id,position,kind,prompt,"
            " choices_json,answer_json,accepted_json,points)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (quiz, pos, kind, prompt, json.dumps(choices),
             json.dumps(answer), json.dumps(accepted), pts))

    named = [r["id"] for r in con.execute(
        "SELECT id FROM users WHERE name IN ('Ana Ruiz','Bo Chen')"
        " AND active=1")]
    seats = named or [r["id"] for r in con.execute(
        "SELECT id FROM users WHERE role='customer' AND active=1"
        " ORDER BY id LIMIT 4")]
    for uid in seats:
        con.execute(
            "INSERT OR IGNORE INTO enrollments(course_id,user_id,since,"
            " source) VALUES(?,?,?,'grand-tour seed')", (cid, uid, now))

    con.commit()
    con.close()
    print(f"seeded {COURSE!r} on {TENANT}: 2 lessons, a 6-question quiz "
          f"across all five kinds, {len(seats)} seat(s)")
    print("to light up the live-class features: sign in at /ops as the "
          "teacher, open the course, Start class")


if __name__ == "__main__":
    main()
