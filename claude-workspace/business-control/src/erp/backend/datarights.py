"""Data rights — per-person export, and erasure with a shown plan.
Ported from lingua-portal and adapted to this platform's records.

**Export** is everything held about one person, as data they could take
with them: admins for anyone, everyone else for themselves only. Their
password hash is not theirs to receive; direct messages are deliberately
absent, because a DM belongs to two people and exporting a conversation
would hand one of them the other's words.

**Erasure is a tombstone, not a hole.** Deleting the row would destroy
records the business is required to keep (attendance, payroll, orders) —
and would also just dangle every reference. Instead the row survives with
every identifying field replaced, and the plan is SHOWN before anything
runs: what gets deleted for good, what gets anonymised, what is retained
and why. The confirmation is the person's typed name, exactly — the
difference between erasing the right person and the wrong one is one row
of vertical travel with a mouse.

Order of operations, deliberate:

1. **Files before rows** — a row deleted before its file leaves an orphan
   on disk that nobody will ever find again.
2. Community rows (messages both ways, contacts, blocks, ghosts, prefs,
   conduct reports involving them) and applications go entirely.
3. Sign-ins die: the bearer token is rotated to a fresh secret nobody
   holds, passwords/PINs/badge tokens cleared, QR login tokens deleted.
4. The tombstone: name becomes "Erased person #N", active=0, uid gone.
5. The audit log keeps its rows (what happened, happened) but their name
   comes off them: rows they performed lose the denormalised actor name,
   and rows about their account lose the summarised detail.
"""

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

RETAINED_NOTE = (
    "Retained records keep pointing at this person's id, which will no "
    "longer identify anyone. They are kept because attendance, teaching "
    "pay and orders are the business's own records — erasing a student "
    "must not delete the class they attended.")


def _person(con, user_id: int) -> dict:
    r = con.execute("SELECT * FROM users WHERE id=?",
                    (int(user_id),)).fetchone()
    if r is None:
        raise HTTPException(404, "no such person")
    return dict(r)


def _rows(con, sql: str, args=()) -> list:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def export_person(con, actor, user_id: int) -> dict:
    """The bundle. Secrets never leave: token, PINs, password hash, badge
    token are stripped — a hash of their password is not theirs to
    receive, and the live token is a working key."""
    person = _person(con, user_id)
    if int(actor["id"]) != int(user_id) and not actor["is_admin"]:
        raise HTTPException(403, "you may only export your own record")
    pid = int(user_id)
    for secret in ("token", "pin", "pin_hash", "clock_token",
                   "password_hash"):
        person.pop(secret, None)
    email = str(person.get("email") or "").lower()
    return {
        "exported_at": time.time(),
        "person": person,
        "enrollments": _rows(con,
            "SELECT e.*, c.name AS course FROM enrollments e"
            " JOIN courses c ON c.id=e.course_id WHERE e.user_id=?", (pid,)),
        "attendance": _rows(con,
            "SELECT ch.*, s.started_at AS class_started, c.name AS course"
            " FROM checkins ch JOIN class_sessions s ON s.id=ch.session_id"
            " JOIN courses c ON c.id=s.course_id WHERE ch.student_id=?",
            (pid,)),
        "classes_taught": _rows(con,
            "SELECT * FROM class_sessions WHERE teacher_id=?", (pid,)),
        "quiz_attempts": _rows(con,
            "SELECT a.*, q.title FROM quiz_attempts a"
            " JOIN quizzes q ON q.id=a.quiz_id WHERE a.user_id=?", (pid,)),
        "achievements": _rows(con,
            "SELECT code, earned_at FROM student_achievements"
            " WHERE user_id=?", (pid,)),
        "library_loans": _rows(con,
            "SELECT l.out_at, l.due_at, l.returned_at, i.name AS item"
            " FROM library_loans l JOIN library_items i ON i.id=l.item_id"
            " WHERE l.user_id=?", (pid,)),
        "recordings": _rows(con,
            "SELECT id, kind, original, mime, bytes, created_at"
            " FROM learning_materials WHERE owner_id=?", (pid,)),
        "applications": _rows(con,
            "SELECT * FROM registrations WHERE person_id=?"
            " OR lower(email)=?", (pid, email)),
        "orders": _rows(con,
            "SELECT id, status, total_cents, created_at FROM orders"
            " WHERE user_id=?", (pid,)),
        "their_actions": _rows(con,
            "SELECT id, action, entity, status, created_at FROM audit_log"
            " WHERE user_id=? ORDER BY id DESC LIMIT 5000", (pid,)),
    }


def _guard(con, actor, user_id: int) -> dict:
    person = _person(con, user_id)
    if person.get("erased_at"):
        raise HTTPException(409, "this person is already erased")
    if int(actor["id"]) == int(user_id):
        raise HTTPException(409, "you cannot erase yourself — somebody must"
                                 " be left able to undo a mistake")
    if person["is_admin"]:
        others = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin=1 AND active=1"
            " AND id != ?", (int(user_id),)).fetchone()["n"]
        if others == 0:
            raise HTTPException(409, "that is the last administrator")
    return person


def plan(con, actor, user_id: int) -> dict:
    """The shown plan: label -> count, three buckets. The UI renders the
    labels as-is, so they are written for a person, not a parser."""
    person = _guard(con, actor, user_id)
    pid = int(user_id)
    email = str(person.get("email") or "").lower()

    def n(sql, args=()):
        return con.execute(sql, args).fetchone()["n"]

    return {
        "person": {"id": pid, "name": person["name"],
                   "email": person["email"], "role": person["role"]},
        "deleted": {
            "recordings and uploads": n(
                "SELECT COUNT(*) AS n FROM learning_materials WHERE"
                " owner_id=? OR id IN (SELECT material_id FROM quiz_responses"
                "  r JOIN quiz_attempts a ON a.id=r.attempt_id"
                "  WHERE a.user_id=? AND r.material_id IS NOT NULL)",
                (pid, pid)),
            "messages": n(
                "SELECT COUNT(*) AS n FROM dm_messages WHERE from_id=?"
                " OR to_id=?", (pid, pid)),
            "contacts": n(
                "SELECT COUNT(*) AS n FROM contacts WHERE a_id=? OR b_id=?",
                (pid, pid)),
            "blocks and ghosts": n(
                "SELECT (SELECT COUNT(*) FROM blocks WHERE blocker_id=?"
                "  OR blocked_id=?) + (SELECT COUNT(*) FROM ghosts WHERE"
                "  owner_id=? OR hidden_from_id=?) AS n",
                (pid, pid, pid, pid)),
            "conduct reports": n(
                "SELECT COUNT(*) AS n FROM conduct_reports WHERE"
                " reporter_id=? OR subject_id=?", (pid, pid)),
            "applications": n(
                "SELECT COUNT(*) AS n FROM registrations WHERE person_id=?"
                " OR lower(email)=?", (pid, email)),
            "sign-in keys": n(
                "SELECT COUNT(*) + 1 AS n FROM login_tokens WHERE user_id=?",
                (pid,)),
        },
        "anonymised": {
            "audit entries naming them": n(
                "SELECT COUNT(*) AS n FROM audit_log WHERE user_id=?"
                " OR entity=?", (pid, f"users/{pid}")),
        },
        "retained": {
            "attendance records": n(
                "SELECT COUNT(*) AS n FROM checkins WHERE student_id=?",
                (pid,)),
            "classes taught": n(
                "SELECT COUNT(*) AS n FROM class_sessions WHERE teacher_id=?",
                (pid,)),
            "quiz attempts (answer text cleared)": n(
                "SELECT COUNT(*) AS n FROM quiz_attempts WHERE user_id=?",
                (pid,)),
            "orders": n(
                "SELECT COUNT(*) AS n FROM orders WHERE user_id=?", (pid,)),
            "library loan history": n(
                "SELECT COUNT(*) AS n FROM library_loans WHERE user_id=?",
                (pid,)),
        },
        "note": RETAINED_NOTE,
    }


def erase(con, actor, user_id: int, *, confirm_name: str,
          reason: str = "") -> dict:
    from . import materials as M
    person = _guard(con, actor, user_id)
    pid = int(user_id)
    if str(confirm_name).strip() != str(person["name"]).strip():
        raise HTTPException(400, "type the person's name exactly as shown"
                                 " to confirm — this cannot be undone")
    email = str(person.get("email") or "").lower()
    removed = {}

    # 1. files first, then their rows — a spoken/video answer is a material
    #    the response points at, not one the student owns, so both sweeps
    for r in con.execute(
            "SELECT id, path FROM learning_materials WHERE owner_id=?"
            " OR id IN (SELECT material_id FROM quiz_responses r"
            "  JOIN quiz_attempts a ON a.id=r.attempt_id"
            "  WHERE a.user_id=? AND r.material_id IS NOT NULL)",
            (pid, pid)).fetchall():
        M.unlink(r["path"])
    removed["recordings and uploads"] = con.execute(
        "DELETE FROM learning_materials WHERE owner_id=?"
        " OR id IN (SELECT material_id FROM quiz_responses r"
        "  JOIN quiz_attempts a ON a.id=r.attempt_id"
        "  WHERE a.user_id=? AND r.material_id IS NOT NULL)",
        (pid, pid)).rowcount
    # free-text answers are the student's own words — the mark is kept,
    # the prose is not
    con.execute(
        "UPDATE quiz_responses SET text='', material_id=NULL WHERE"
        " attempt_id IN (SELECT id FROM quiz_attempts WHERE user_id=?)",
        (pid,))

    # 2. the community goes entirely: messages both ways, edges, prefs,
    #    and the reports either side of them
    removed["messages"] = con.execute(
        "DELETE FROM dm_messages WHERE from_id=? OR to_id=?",
        (pid, pid)).rowcount
    removed["contacts"] = con.execute(
        "DELETE FROM contacts WHERE a_id=? OR b_id=?", (pid, pid)).rowcount
    removed["blocks and ghosts"] = (
        con.execute("DELETE FROM blocks WHERE blocker_id=? OR blocked_id=?",
                    (pid, pid)).rowcount
        + con.execute("DELETE FROM ghosts WHERE owner_id=?"
                      " OR hidden_from_id=?", (pid, pid)).rowcount)
    removed["conduct reports"] = con.execute(
        "DELETE FROM conduct_reports WHERE reporter_id=? OR subject_id=?",
        (pid, pid)).rowcount
    con.execute("DELETE FROM community_prefs WHERE user_id=?", (pid,))
    removed["applications"] = con.execute(
        "DELETE FROM registrations WHERE person_id=? OR lower(email)=?",
        (pid, email)).rowcount

    # 3. sign-ins die: rotate the bearer token to a secret nobody holds
    removed["sign-in keys"] = con.execute(
        "DELETE FROM login_tokens WHERE user_id=?", (pid,)).rowcount + 1
    con.execute(
        "UPDATE users SET token=?, password_hash='', pin='', pin_hash='',"
        " clock_token='', email_verified_at=0 WHERE id=?",
        (secrets.token_urlsafe(24), pid))

    # 4. open enrollments end (rosters stop listing them); history stays
    con.execute("UPDATE enrollments SET until=? WHERE user_id=?"
                " AND until IS NULL", (time.time(), pid))

    # 5. the tombstone
    con.execute(
        "UPDATE users SET name=?, email='', region='', uid=NULL, active=0,"
        " erased_at=? WHERE id=?",
        (f"Erased person #{pid}", time.time(), pid))

    # 6. the audit log keeps what happened; their name comes off it
    con.execute("UPDATE audit_log SET actor=? WHERE user_id=?",
                (f"Erased person #{pid}", pid))
    removed["audit entries anonymised"] = con.execute(
        "UPDATE audit_log SET detail='' WHERE (user_id=? OR entity=?)"
        " AND detail != ''", (pid, f"users/{pid}")).rowcount

    return {"person_id": pid, "erased": True, "removed": removed,
            "reason": str(reason or "erasure request")[:200]}


# ── ops routes ───────────────────────────────────────────────────────────────

router = APIRouter()

from .main import admin_user, current_user, get_con  # noqa: E402


@router.get("/api/learning/people/{uid}/export")
def ops_export(uid: int, user=Depends(current_user), con=Depends(get_con)):
    from fastapi.responses import JSONResponse
    data = export_person(con, user, uid)
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="person-{uid}.json"'})


@router.get("/api/learning/people/{uid}/erase-plan")
def ops_erase_plan(uid: int, user=Depends(admin_user), con=Depends(get_con)):
    return plan(con, user, uid)


class EraseBody(BaseModel):
    confirm_name: str = ""
    reason: str = ""


@router.post("/api/learning/people/{uid}/erase")
def ops_erase(uid: int, body: EraseBody, user=Depends(admin_user),
              con=Depends(get_con)):
    out = erase(con, user, uid, confirm_name=body.confirm_name,
                reason=body.reason)
    con.commit()
    return out
