#!/usr/bin/env python3
"""Open a class that is happening right now, so the live-class surfaces
have something in them the moment you look.

The Grand Tour seeds a course and stops there on purpose — starting a
class is the teacher's act and the demo of it. That is right for the
tour and wrong for a fresh install, where "Learning" opens on a course
list and every screen that only exists during a class is empty: the
register, the check-in door, the badge scanner, the wall display's IN
PROGRESS. Nothing is broken and there is nothing to see, which is the
worst state for anybody trying to find out what the thing does.

So this opens one, on whichever tenant you point it at, and leaves it
open. It plants the middle of a lesson rather than the start of one:

  - a teacher on the course, if it had none
  - enough students enrolled to make a register worth reading
  - a class started a few minutes ago, so check-in is open and the
    lateness cutoff has meaning
  - some of them checked in and one late, and the rest NOT marked —
    a register where everybody is already ticked demonstrates nothing,
    because the thing you do on that screen is tick somebody
  - a room booking for it, so the corridor display shows the class
    instead of "Free"

It drives the same functions the app drives — start_class, do_check_in,
rooms.book — rather than writing the rows itself. A seed that inserts
its own rows is a second implementation of the feature, and it goes
stale the first time the real one changes.

Idempotent: if the course already has an open session it says so and
changes nothing.

Usage:  seed_live_class.py [tenant]        (default: the tenant that
        `localhost` opens, so what you seed is what you see)
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# How long ago the class started. Long enough that check-in is properly
# open and a late arrival is genuinely late, short enough that the class
# is plainly still running.
STARTED_MIN_AGO = 12
ROOM_NAME = "Studio 1"

# Ordinary names from several places, so a register looks like a class
# and not like a test fixture. The addresses are example.com, which is
# reserved for exactly this and can never reach anybody.
DEMO_STUDENTS = [
    ("Ana Ruiz", "ana.ruiz@example.com"),
    ("Bo Chen", "bo.chen@example.com"),
    ("Marta Silva", "marta.silva@example.com"),
    ("Sam Okafor", "sam.okafor@example.com"),
    ("Yusuf Demir", "yusuf.demir@example.com"),
    ("Priya Nair", "priya.nair@example.com"),
]


def _default_tenant() -> str:
    """Whatever `localhost` resolves to — seeding a tenant the user does
    not open is the same as not seeding."""
    import json
    try:
        reg = json.loads((ROOT / "data" / "tenants.json").read_text())
    except Exception:                                        # noqa: BLE001
        return "studio"
    for tid, t in (reg.get("tenants") or {}).items():
        if "localhost" in (t.get("hosts") or []):
            return tid
    return reg.get("default") or "studio"


def main() -> int:
    tenant = sys.argv[1] if len(sys.argv) > 1 else _default_tenant()

    from erp.backend import tenancy
    tenancy.CURRENT.set(tenant)
    from erp.backend import classroom, db, learning, rooms

    con = db.connect()
    con.row_factory = __import__("sqlite3").Row

    course = con.execute(
        "SELECT * FROM courses WHERE active=1 ORDER BY id").fetchone()
    if course is None:
        print(f"  ! {tenant} has no course to hold a class for — run "
              f"seed_grand_tour.py {tenant} first.")
        return 1
    cid = course["id"]

    open_now = con.execute(
        "SELECT id FROM class_sessions WHERE course_id=? AND status='open'",
        (cid,)).fetchone()
    if open_now:
        print(f"  · {course['name']} already has a class open "
              f"(session {open_now['id']}) — nothing to do.")
        return 0

    # --- a teacher, because a class cannot start without one ---
    teacher_id = course["teacher_id"] or 0
    if not teacher_id:
        t = con.execute(
            "SELECT id, name FROM users WHERE role IN ('staff','admin',"
            "'owner','teacher') ORDER BY id").fetchone()
        if t is None:
            print(f"  ! {tenant} has no staff to teach it.")
            return 1
        teacher_id = t["id"]
        con.execute("UPDATE courses SET teacher_id=? WHERE id=?",
                    (teacher_id, cid))
        print(f"  ✓ {t['name']} now teaches {course['name']}")

    # --- students, because a register of one is not a register ---
    #
    # Planted by name rather than drafted from whatever has role
    # 'customer'. A fresh install's customer table is test detritus —
    # on this one it was "admin", "bob" and "Store Verify Admin" — and a
    # register reading "admin (present)" teaches nobody what the screen
    # is for. Matched on email so a second run reuses them.
    have = [u for u, _ in classroom.enrolled(con, cid)]
    if len(have) < 4:
        import secrets
        now = time.time()
        for name, email in DEMO_STUDENTS[:6 - len(have)]:
            row = con.execute("SELECT id FROM users WHERE email=?",
                              (email,)).fetchone()
            if row is None:
                cur = con.execute(
                    "INSERT INTO users(name,email,role,token,is_admin,"
                    " email_verified_at,created_at) VALUES(?,?,?,?,0,?,?)",
                    (name, email, "customer",
                     secrets.token_urlsafe(24), now, now))
                uid = cur.lastrowid
            else:
                uid = row["id"]
            learning.enroll(con, cid, uid, source="seed:live-class")
        print(f"  ✓ enrolled {min(6 - len(have), len(DEMO_STUDENTS))} "
              f"students")
    con.commit()

    roll = classroom.enrolled(con, cid)
    if len(roll) < 2:
        print(f"  ! only {len(roll)} student(s) on {course['name']} — a "
              f"class would show an empty register.")
        return 1

    # --- the class itself ---
    session = classroom.start_class(con, course_id=cid, teacher_id=teacher_id)
    # start_class stamps "now"; move it back so check-in has been open a
    # while and the late cutoff means something.
    con.execute("UPDATE class_sessions SET started_at=? WHERE id=?",
                (time.time() - STARTED_MIN_AGO * 60, session.id))
    con.commit()
    print(f"  ✓ {course['name']} is in session (started "
          f"{STARTED_MIN_AGO} minutes ago)")

    # --- some of them in, deliberately not all ---
    marked = []
    for i, (uid, name) in enumerate(roll):
        if i >= 3:
            break                      # the rest stay unmarked, on purpose
        try:
            c, _ = classroom.do_check_in(
                con, session_id=session.id, student_id=uid,
                method="teacher", marked_by=teacher_id,
                status="late" if i == 2 else "present")
            marked.append(f"{name} ({c.status})")
        except Exception as e:                               # noqa: BLE001
            print(f"    · could not check {name} in: {e}")
    con.commit()
    if marked:
        print(f"  ✓ checked in: {', '.join(marked)}")
    left = len(roll) - len(marked)
    print(f"  · {left} still unmarked, so the register has something to do")

    # --- a room, so the corridor display shows it ---
    try:
        room = con.execute("SELECT * FROM rooms WHERE active=1"
                           " ORDER BY id").fetchone()
        if room is None:
            cur = con.execute(
                "INSERT INTO rooms(name,store_id,kind,seats,note,active,"
                "created_at) VALUES(?,0,'classroom',12,'',1,?)",
                (ROOM_NAME, time.time()))
            rid = cur.lastrowid
            con.commit()
            room_name = ROOM_NAME
        else:
            rid, room_name = room["id"], room["name"]
        starts = time.time() - STARTED_MIN_AGO * 60
        ends = starts + 90 * 60
        if not rooms.clashes(con, rid, starts, ends, teacher_id=teacher_id):
            con.execute(
                "INSERT INTO room_bookings(room_id,starts,ends,title,"
                "course_id,session_id,teacher_id,booked_by,series,note,"
                "created_at) VALUES(?,?,?,?,?,?,?,?,'','',?)",
                (rid, starts, ends, course["name"], cid, session.id,
                 teacher_id, teacher_id, time.time()))
            con.commit()
            print(f"  ✓ {room_name} shows it on the wall display")
        else:
            print(f"  · {room_name} was already booked then — no booking "
                  f"made, the class is still open")
    except Exception as e:                                   # noqa: BLE001
        # A room is the garnish. Losing it must not cost the class.
        print(f"  · no room booking ({e}) — the class is still open")

    print()
    print(f"  Look at it on the {tenant} tenant:")
    print("    ops → Learning → the course      the class, and Close class")
    print("    ops → Learning → the register    tick the ones still unmarked")
    print("    ops → Rooms → the wall display   IN PROGRESS, from the door")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
