#!/usr/bin/env python3
"""Seed the lingua tenant with lingua-portal's own demo school, so the full
experience is explorable the moment you open lingua.localhost.

This is the source's scripts/seed.py, ported row for row onto this
platform's tables: two languages, a teacher with an hourly rate and one
with a per-session rate, students enrolled across courses, CLOSED sessions
in the past so payroll has something to derive from on first load, a small
curriculum with one draft (which students must not see), pending
applications so admissions isn't empty, and a starter conversation that
demonstrates the accept gate the moment anyone signs in as Ana.

It also dresses the tenant in lingua-portal's identity: dark ground, teal
accent, clean sans — the palette from the source's one stylesheet — and
replaces the untouched drinks-era home scaffold with the courses shape.

Idempotent: refuses to run over a tenant that already has courses.
Sign-ins are by NAME (dev mode, require_passwords off): Ana Ruiz, Bo Chen,
María Solís, Admin Ada, …
"""

import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DAY = 86400

TENANT = sys.argv[1] if len(sys.argv) > 1 else "lingua"
DB = ROOT / "data" / "tenants" / TENANT / "business_control.db"

# lingua-portal's palette, from src/frontend/styles/app.css: dark by
# default, teal accent, no serif anywhere.
THEME = {
    "brand": "lingua", "dot": ".",
    "title": "Lingua — learn a language with us",
    "description": "Small classes, real teachers, and progress you can see.",
    "purple": "#2dd4bf",       # the accent (links, brand marks)
    "lavender": "#5eead4",     # its lighter step
    "orange": "#0d9488",       # the one hot button
    "ink": "#e8eaed", "bg": "#14161a",
    "font": "Inter", "display_font": "Inter", "wordmark_font": "Inter",
    "announce": [], "art": "card",
    "footer": "Lingua — a language school",
}


def main():
    import sqlite3
    if not DB.exists():
        print(f"no tenant database at {DB} — is the tenant stood up?")
        sys.exit(1)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT COUNT(*) AS n FROM courses").fetchone()["n"]:
        print("the school already has courses — nothing to do "
              "(this seed never runs over real data)")
        sys.exit(0)
    now = time.time()

    def person(name, email, *, role="customer", is_admin=0):
        existing = con.execute("SELECT id FROM users WHERE name=?",
                               (name,)).fetchone()
        if existing:
            return existing["id"]
        cur = con.execute(
            "INSERT INTO users(name,email,role,token,is_admin,"
            " email_verified_at,created_at) VALUES(?,?,?,?,?,?,?)",
            (name, email, role, secrets.token_urlsafe(24), is_admin,
             now, now))
        return cur.lastrowid

    # the seeded school has one of each interesting role, so the model is
    # visible the moment you sign in rather than something to construct
    ada = person("Admin Ada", "ada@school.test", role="employee", is_admin=1)
    t_maria = person("María Solís", "maria@school.test", role="employee")
    t_kenji = person("Kenji Arata", "kenji@school.test", role="employee")
    students = {n: person(n, f"{n.split()[0].lower()}@student.test")
                for n in ("Ana Ruiz", "Bo Chen", "Cy Novak", "Dana Okoro",
                          "Eli Toft", "Fatima Nasser")}
    ana, bo, cy, dana, eli, fatima = (students[n] for n in
        ("Ana Ruiz", "Bo Chen", "Cy Novak", "Dana Okoro", "Eli Toft",
         "Fatima Nasser"))

    for tid, hourly, per_sess, minimum, rnd in (
            (t_maria, 4500, 0, 45, 15),    # $45/h, 45-min floor, 15-min blocks
            (t_kenji, 0, 6000, 0, 1)):     # flat $60 per class
        con.execute(
            "INSERT INTO pay_rates(teacher_id,hourly_cents,per_session_cents,"
            " minimum_minutes,round_to_min,updated_at) VALUES(?,?,?,?,?,?)",
            (tid, hourly, per_sess, minimum, rnd, now))

    # course seats are PRODUCTS here — the admissions office the source
    # never had: buying the seat enrols you
    def product(sku, name, cents):
        cur = con.execute(
            "INSERT INTO products(sku,name,description,category,price_cents,"
            " case_price_cents,active) VALUES(?,?,?,?,?,?,1)",
            (sku, name, "A seat in the course — buying it enrols you.",
             "Courses", cents, cents))
        return cur.lastrowid

    p_es = product("LNG-ES-A1", "Spanish A1 — course seat", 12000)
    p_ja = product("LNG-JA-A1", "Japanese A1 — course seat", 12000)

    def course(name, language, level, teacher, blurb, product_id=None):
        cur = con.execute(
            "INSERT INTO courses(name,language,level,blurb,teacher_id,"
            " product_id,active,created_at) VALUES(?,?,?,?,?,?,1,?)",
            (name, language, level, blurb, teacher, product_id, now))
        return cur.lastrowid

    c_es = course("Spanish A1 — Conversation", "Spanish", "A1", t_maria,
                  "Say hello, order food, survive a market. Small group, "
                  "lots of talking.", p_es)
    c_es2 = course("Spanish B1 — Grammar", "Spanish", "B1", t_maria,
                   "The subjunctive will not defeat you.")
    c_ja = course("Japanese A1 — Hiragana", "Japanese", "A1", t_kenji,
                  "Read your first menu by week three.", p_ja)

    for cid, uid in ((c_es, ana), (c_es, bo), (c_es, cy), (c_es, dana),
                     (c_es2, ana), (c_es2, eli),
                     (c_ja, bo), (c_ja, eli), (c_ja, fatima)):
        con.execute("INSERT INTO enrollments(course_id,user_id,since,source)"
                    " VALUES(?,?,?,'manual:seed')", (cid, uid, now - 30 * DAY))
    # anyone already on this tenant gets a seat too, so the person running
    # the demo lands in a class under their own name
    for r in con.execute("SELECT id FROM users WHERE active=1").fetchall():
        if r["id"] not in (t_maria, t_kenji) and not con.execute(
                "SELECT 1 FROM enrollments WHERE course_id=? AND user_id=?",
                (c_es, r["id"])).fetchone():
            con.execute("INSERT INTO enrollments(course_id,user_id,since,"
                        " source) VALUES(?,?,?,'manual:seed')",
                        (c_es, r["id"], now))

    # a small curriculum for Spanish A1 — three published, one draft
    # (which students must not see or step onto)
    lessons = []
    for i, (title, body, pub) in enumerate((
        ("Greetings & introductions",
         "# Hola\n\nSaying hello, goodbye, and introducing yourself.\n\n"
         "- hola — hello\n- adiós — goodbye\n- me llamo… — my name is…\n\n"
         "Practice with a neighbour: introduce yourself, ask their name, "
         "say goodbye. **Accents matter on paper, not in your mouth** — "
         "speak first, spell later.", 1),
        ("Numbers 1–100",
         "# Los números\n\nCounting, prices, and phone numbers.\n\n"
         "- uno, dos, tres… — the first ten are pure memory\n"
         "- veinte, treinta… — the tens\n- setenta y siete — 77\n\n"
         "Say your own phone number out loud, digit by digit.", 1),
        ("Ordering food",
         "# En el restaurante\n\nMenus, ordering, and paying the bill.\n\n"
         "- la carta — the menu\n- quisiera… — I would like…\n"
         "- la cuenta, por favor — the bill, please", 1),
        ("DRAFT: subjunctive teaser", "not ready", 0))):
        cur = con.execute(
            "INSERT INTO lessons(course_id,title,body,position,published,"
            " created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (c_es, title, body, i, pub, t_maria, now, now))
        lessons.append(cur.lastrowid)

    # one quiz on the first lesson — the very questions the grading
    # engine's own tests are written around
    quiz = con.execute(
        "INSERT INTO quizzes(course_id,lesson_id,title,intro,pass_mark,"
        " published,created_by,created_at) VALUES(?,?,?,?,60,1,?,?)",
        (c_es, lessons[0], "Greetings check",
         "Two minutes, no pressure. Accents are forgiven.",
         t_maria, now)).lastrowid
    for pos, (kind, prompt, choices, answer, accepted, pts) in enumerate((
            ("choice", "¿Cómo se dice 'hello'?",
             ["adiós", "hola", "gracias"], [1], [], 2),
            ("multi", "Which of these are greetings?",
             ["hola", "mesa", "buenos días", "silla"], [0, 2], [], 4),
            ("text", "Translate: 'good morning'", [], [],
             ["buenos días"], 1))):
        con.execute(
            "INSERT INTO quiz_questions(quiz_id,position,kind,prompt,"
            " choices_json,answer_json,accepted_json,points)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (quiz, pos, kind, prompt, json.dumps(choices),
             json.dumps(answer), json.dumps(accepted), pts))

    # past sessions, CLOSED, so payroll derives real lines on first load
    def past_session(course_id, teacher_id, days_ago, minutes, present,
                     late=(), excused=(), lesson_id=None):
        start = now - days_ago * DAY
        end = start + minutes * 60
        sid = con.execute(
            "INSERT INTO class_sessions(course_id,teacher_id,started_at,"
            " ended_at,status,late_after_min,closed_by,lesson_id,room)"
            " VALUES(?,?,?,?,'closed',10,?,?,?)",
            (course_id, teacher_id, start, end, teacher_id, lesson_id,
             "rm-" + secrets.token_hex(4))).lastrowid
        for uid in present:
            con.execute("INSERT INTO checkins(session_id,student_id,at,"
                        " status,method) VALUES(?,?,?,'present','self')",
                        (sid, uid, start + 120))
        for uid in late:
            con.execute("INSERT INTO checkins(session_id,student_id,at,"
                        " status,method) VALUES(?,?,?,'late','self')",
                        (sid, uid, start + 15 * 60))
        for uid in excused:
            con.execute(
                "INSERT INTO checkins(session_id,student_id,at,status,"
                " method,marked_by,note) VALUES(?,?,?,'excused','teacher',"
                " ?,'notified in advance')", (sid, uid, start, teacher_id))
        return sid

    s1 = past_session(c_es, t_maria, 7, 60, [ana, bo], [cy], [dana],
                      lesson_id=lessons[0])
    s2 = past_session(c_es, t_maria, 4, 52, [ana, cy, dana],
                      lesson_id=lessons[1])
    s3 = past_session(c_ja, t_kenji, 5, 90, [bo, eli, fatima])
    past_session(c_es2, t_maria, 2, 31, [ana, eli])  # exercises 15-min rounding

    # one approved + one held, so payroll shows all three states at once
    con.execute("INSERT INTO payroll_overlay(session_id,state,decided_by,"
                " decided_at,note) VALUES(?,'approved',?,?,'')",
                (s1, ada, now))
    con.execute("INSERT INTO payroll_overlay(session_id,state,decided_by,"
                " decided_at,note) VALUES(?,'held',?,?,"
                " 'confirm room booking')", (s3, ada, now))

    # the lessons those classes taught are done for who attended them
    for uid, lids in ((ana, lessons[:2]), (bo, lessons[:1]),
                      (cy, lessons[:2]), (dana, lessons[1:2])):
        for lid in lids:
            con.execute("INSERT OR IGNORE INTO lesson_progress(lesson_id,"
                        " user_id,done_at) VALUES(?,?,?)",
                        (lid, uid, now - 3 * DAY))

    # derived achievements land where the data already says they should
    for uid in (ana, bo, cy, dana, eli, fatima):
        con.execute("INSERT OR IGNORE INTO student_achievements(user_id,"
                    " code,earned_at) VALUES(?,'first_checkin',?)",
                    (uid, now - 7 * DAY))

    # pending applications, so the admissions queue isn't empty
    for name, email, lang, level, goals, cid in (
            ("Nadia Haddad", "nadia@applicant.test", "Spanish", "A2",
             "I work with Spanish-speaking clients", c_es),
            ("Tomas Vogel", "tomas@applicant.test", "Japanese", "A1",
             "planning to live in Osaka", c_ja)):
        con.execute(
            "INSERT INTO registrations(name,email,phone,language,level,"
            " goals,availability,course_id,state,created_at)"
            " VALUES(?,?,'',?,?,?,'weekday evenings',?,'pending',?)",
            (name, email, lang, level, goals, cid, now - DAY))

    # a starter conversation, so the People tab isn't empty: Ana and Bo are
    # contacts with two messages, and María has a request WAITING on Ana —
    # the accept gate, demonstrated the moment anyone signs in as Ana
    a, b = min(ana, bo), max(ana, bo)
    con.execute("INSERT INTO contacts(a_id,b_id,state,requested_by,"
                " created_at,decided_at) VALUES(?,?,'accepted',?,?,?)",
                (a, b, ana, now - 10 * DAY, now - 10 * DAY))
    con.execute("INSERT INTO dm_messages(from_id,to_id,kind,body,at,read_at)"
                " VALUES(?,?,'text',?,?,?)",
                (ana, bo, "¡Hola Bo! ¿Hiciste la tarea de los números?",
                 now - 2 * DAY, now - 2 * DAY))
    con.execute("INSERT INTO dm_messages(from_id,to_id,kind,body,at)"
                " VALUES(?,?,'text',?,?)",
                (bo, ana, "Casi… ¿me explicas el 77? Setenta y… ¿qué?",
                 now - 2 * DAY + 600))
    a2, b2 = min(t_maria, ana), max(t_maria, ana)
    con.execute("INSERT INTO contacts(a_id,b_id,state,requested_by,"
                " created_at) VALUES(?,?,'pending',?,?)",
                (a2, b2, t_maria, now - DAY))
    con.execute("INSERT OR IGNORE INTO student_achievements(user_id,code,"
                " earned_at) VALUES(?,'first_friend',?)", (ana, now - 10 * DAY))
    con.execute("INSERT OR IGNORE INTO student_achievements(user_id,code,"
                " earned_at) VALUES(?,'first_friend',?)", (bo, now - 10 * DAY))

    # two students demonstrate the privacy dial — search for them as Ana
    con.execute("INSERT INTO community_prefs(user_id,privacy_name)"
                " VALUES(?,'initial')", (cy,))       # Cy → "Cy N."
    con.execute("INSERT INTO community_prefs(user_id,privacy_name)"
                " VALUES(?,'class')", (fatima,))     # classmates only

    # ── the look: lingua-portal's identity, and the courses-shape site ──
    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES('theme',?)",
                (json.dumps(THEME),))
    con.commit()

    from storefront.backend import layouts
    layouts.apply(con, ["learning", "selling", "payments", "comms"],
                  "Lingua")
    # the school's own door, first in the nav
    con.execute("UPDATE store_menus SET position=position+1")
    for loc in ("header", "footer"):
        con.execute("INSERT INTO store_menus(location,label,url,position)"
                    " VALUES(?,?,?,0)", (loc, "Learning", "/learn"))

    # the shape ships scaffolding copy ("Replace this") — a demo school
    # writes its real words over its own scaffolding
    def rewrite(heading_like, **changes):
        for r in con.execute(
                "SELECT id, settings FROM page_sections WHERE"
                " page_slug='home'").fetchall():
            s = json.loads(r["settings"])
            if heading_like.lower() in (s.get("heading") or "").lower():
                s.update(changes)
                con.execute("UPDATE page_sections SET settings=? WHERE id=?",
                            (json.dumps(s), r["id"]))

    rewrite("What they'll be able to do", heading="Speak it by spring.",
            sub="Small classes, real teachers, and progress you can see. "
                "Spanish and Japanese, from the first hola to the first "
                "menu you read on your own.",
            stat1="3|courses", stat2="2|languages", stat3="7|students")
    rewrite("How the teaching works", items=[
        {"icon": "check", "title": "Live classes",
         "text": "Real teachers, small groups, and a check-in when you "
                 "arrive. Attendance is part of learning."},
        {"icon": "sparkle", "title": "Lessons that stack",
         "text": "Short written lessons in order, quizzes when you're "
                 "ready — accents forgiven, always."},
        {"icon": "shield", "title": "Honest grades",
         "text": "Scores only become final once every answer is marked. "
                 "A written answer may wait for a teacher; we never show "
                 "you a guess."}])
    rewrite("Who teaches this", body=(
        "María Solís teaches our Spanish track — conversation first, "
        "grammar when you need it. Kenji Arata runs Japanese A1 and will "
        "have you reading hiragana by week three.\n\nEvery class carries "
        "a video room, so you can join from anywhere; check in, and it "
        "counts."))
    rewrite("Frequently asked", items=[
        {"q": "How long do I have access?",
         "a": "As long as you're enrolled — lessons, quizzes and your "
              "progress stay with your account."},
        {"q": "What if I miss a class?",
         "a": "Attendance is recorded honestly (an excused absence is "
              "not a no-show), and the lesson the class taught is on the "
              "learning page to catch up on."},
        {"q": "How do I join?",
         "a": "Buy a course seat in the shop, or apply on the learning "
              "page — an administrator reviews every application."}])
    rewrite("Not ready to enrol", body=(
        "Apply on the learning page and tell us your goals — we read "
        "every application, and approval is what opens your seat."))
    con.commit()
    con.close()

    print(f"seeded the {TENANT} school:")
    print("  sign in on the storefront BY NAME (dev mode, no passwords):")
    print("    students: Ana Ruiz (the loaded one) · Bo Chen · Cy Novak ·")
    print("              Dana Okoro · Eli Toft · Fatima Nasser")
    print("    teachers: María Solís ($45/h) · Kenji Arata ($60/class)")
    print("              — they run classes from the ops app (/ops)")
    print("    office:   Admin Ada (ops admin)")
    print("  courses: Spanish A1 · Spanish B1 · Japanese A1")
    print("  4 closed classes (payroll: pending + approved + held) ·")
    print("  3 lessons + 1 draft · 1 quiz · 2 applications waiting ·")
    print("  Ana and Bo are friends; María's request waits on Ana")


if __name__ == "__main__":
    main()
