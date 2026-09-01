"""The learner's door — /learn on the storefront.

The staff side of Learning lives in the ops app (erp/backend/learning.py);
this is the side a student sees: their courses, the lessons in order, the
quizzes, and a progress line that is derived on every read — never stored.

Three rules, all enforced here at the server rather than hoped for in the UI:

- The whole surface sits behind the tenant's Learning entitlement, the same
  `cap_on` gate as every other public capability page. Revoke the capability
  and /learn is a 404, not a husk.
- A learner reads only PUBLISHED lessons in courses they are ENROLLED in —
  `learning.visible_to`, the single visibility rule.
- The quiz payload a learner receives has the answer key stripped at the
  source (`learning.quiz_for_student`).

Sign-in is the storefront's one door: the same token the account and support
flows already store. A course the learner is not enrolled in shows its blurb
and — when the course names a product — a link to buy the seat.
"""

import os
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from pydantic import BaseModel

from erp.backend import classroom as CR
from erp.backend import community as CM
from erp.backend import datarights as DR
from erp.backend import identity as ID
from erp.backend import learning as L
from erp.backend import library as LIB
from erp.backend import lookup as LK
from erp.backend import materials as MAT
from . import sections as sect
from .api import current_customer, get_con, rate_limit, render_shell
from .partners import _require_cap, brand_name, cap_on

router = APIRouter()


# ── a small, safe markdown renderer ─────────────────────────────────────────
# Lesson bodies are teacher-authored markdown. Escape first, transform after:
# nothing an author types can become markup we didn't choose.

def render_markdown(text: str) -> str:
    out, in_list, in_code = [], False, False
    for raw in str(text or "").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                if in_list:
                    out.append("</ul>"); in_list = False
                out.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(sect.esc(line))
            continue
        s = sect.esc(line)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        if s.startswith("- ") or s.startswith("* "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{s[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        if s.startswith("### "):
            out.append(f"<h4>{s[4:]}</h4>")
        elif s.startswith("## "):
            out.append(f"<h3>{s[3:]}</h3>")
        elif s.startswith("# "):
            out.append(f"<h2>{s[2:]}</h2>")
        elif s.strip():
            out.append(f"<p>{s}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


# ── learner APIs ─────────────────────────────────────────────────────────────

@router.get("/api/learn/courses")
def my_courses(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    mine, more = [], []
    for r in con.execute(
            "SELECT c.*, u.name AS teacher_name FROM courses c"
            " LEFT JOIN users u ON u.id=c.teacher_id"
            " WHERE c.active=1 ORDER BY c.name").fetchall():
        d = {k: r[k] for k in ("id", "name", "language", "level", "blurb",
                               "product_id")}
        d["teacher"] = r["teacher_name"] or ""
        if L.enrolled_in(con, r["id"], user["id"]):
            d["progress"] = L.course_progress(con, r["id"], user["id"])
            mine.append(d)
        else:
            # the catalogue: blurb and a door, never the content
            d.pop("product_id", None)
            p = r["product_id"] and con.execute(
                "SELECT id, name, price_cents FROM products"
                " WHERE id=? AND active=1", (r["product_id"],)).fetchone()
            if p:
                d["product"] = dict(p)
            d["requested"] = con.execute(
                "SELECT 1 FROM registrations WHERE person_id=? AND"
                " course_id=? AND state='pending'",
                (user["id"], r["id"])).fetchone() is not None
            more.append(d)
    return {"enrolled": mine, "available": more,
            "achievements": L.achievements_of(con, user["id"])}


@router.get("/api/learn/courses/{cid}")
def course_view(cid: int, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    c = con.execute("SELECT * FROM courses WHERE id=? AND active=1",
                    (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "course not found")
    if not L.enrolled_in(con, cid, user["id"]) and not L.may_edit(con, user, cid):
        raise HTTPException(403, "you are not enrolled in this course")
    done = {r["lesson_id"] for r in con.execute(
        "SELECT lesson_id FROM lesson_progress WHERE user_id=?",
        (user["id"],)).fetchall()}
    lessons = [{**l, "done": l["id"] in done}
               for l in L.lessons_for(con, user, cid)]
    quizzes = []
    for q in con.execute(
            "SELECT id, title, intro, pass_mark, lesson_id FROM quizzes"
            " WHERE course_id=? AND published=1 ORDER BY id",
            (cid,)).fetchall():
        d = dict(q)
        a = con.execute(
            "SELECT id, state FROM quiz_attempts WHERE quiz_id=? AND user_id=?"
            " ORDER BY id DESC LIMIT 1", (q["id"], user["id"])).fetchone()
        d["attempt"] = dict(a) if a else None
        quizzes.append(d)
    open_s = CR.open_session_for_course(con, cid)
    session = None
    if open_s:
        mine = con.execute(
            "SELECT status FROM checkins WHERE session_id=? AND student_id=?",
            (open_s.id, user["id"])).fetchone()
        room = con.execute("SELECT room FROM class_sessions WHERE id=?",
                           (open_s.id,)).fetchone()["room"]
        session = {"id": open_s.id, "started_at": open_s.started_at,
                   "my_status": mine["status"] if mine else None,
                   "room": room,
                   # the enrolled count travels with the room: it decides
                   # which video transport the call opens with, so a full
                   # class picks the SFU on the FIRST join
                   "enrolled": len(CR.enrolled(con, cid))}
    return {"course": {k: c[k] for k in ("id", "name", "language", "level",
                                         "blurb")},
            "lessons": lessons, "quizzes": quizzes,
            "progress": L.course_progress(con, cid, user["id"]),
            "session": session,
            "attendance": CR.attendance_of(con, cid, user["id"])}


@router.get("/api/learn/lessons/{lid}")
def lesson_view(lid: int, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    r = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    lesson = dict(r)
    if not L.visible_to(con, user, lesson):
        raise HTTPException(403, "you cannot read this lesson")
    done = con.execute(
        "SELECT 1 FROM lesson_progress WHERE lesson_id=? AND user_id=?",
        (lid, user["id"])).fetchone() is not None
    return {"id": lesson["id"], "course_id": lesson["course_id"],
            "title": lesson["title"], "html": render_markdown(lesson["body"]),
            "position": lesson["position"], "done": done,
            "materials": MAT.of_lesson(con, lid)}


@router.post("/api/learn/lessons/{lid}/done")
def lesson_done(lid: int, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    r = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    if not L.visible_to(con, user, dict(r)):
        raise HTTPException(403, "you cannot read this lesson")
    import time
    con.execute(
        "INSERT OR IGNORE INTO lesson_progress(lesson_id,user_id,done_at)"
        " VALUES(?,?,?)", (lid, user["id"], time.time()))
    con.commit()
    return {"ok": True}


@router.post("/api/learn/quizzes/{qid}/start")
def quiz_start(qid: int, user=Depends(current_customer),
               con=Depends(get_con)):
    _require_cap("learning")
    attempt = L.start_attempt(con, user, qid)
    con.commit()
    quiz = L.quiz_for_student(con, user, qid)
    answered = {r.question_id: {"chosen": r.chosen, "text": r.text,
                                "material_id": r.material_id}
                for r in L.responses(con, attempt["id"])}
    return {"attempt": attempt, "quiz": quiz, "answered": answered}


class AnswerBody(BaseModel):
    question_id: int = 0
    chosen: list[int] = []
    text: str = ""


@router.post("/api/learn/attempts/{aid}/answer")
def quiz_answer(aid: int, body: AnswerBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    L.save_answer(con, user, aid, body.question_id,
                  chosen=body.chosen, text=body.text)
    con.commit()
    return {"ok": True}


@router.post("/api/learn/attempts/{aid}/submit")
def quiz_submit(aid: int, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    out = L.submit_attempt(con, user, aid)
    con.commit()
    return out


@router.get("/api/learn/attempts/{aid}")
def quiz_result(aid: int, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    return L.attempt_result(con, user, aid)


@router.post("/api/learn/sessions/{sid}/checkin")
def session_checkin(sid: int, user=Depends(current_customer),
                    con=Depends(get_con)):
    """Self check-in: a student may say "I am here" — the pure rules decide
    present vs late, refuse the unenrolled, and never let self-service
    overwrite a teacher's ruling."""
    _require_cap("learning")
    c, fresh = CR.do_check_in(con, session_id=sid, student_id=user["id"])
    con.commit()
    return {"status": c.status, "at": c.at, "new_achievements": fresh}


# ── the community: people, messages, safety ──────────────────────────────────
# The social layer, scoped to the school. Every endpoint requires membership:
# enrolled, teaching, or administering — a shopper who only ever bought
# sparkling water has no place in a student directory.

def _member(con, user):
    if not CM.in_community(con, user["id"]):
        raise HTTPException(403, "the community opens when you join a course")
    return user


@router.get("/api/learn/people/search")
def people_search(q: str = "", user=Depends(current_customer),
                  con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    return CM.search(con, user, q)


@router.get("/api/learn/people")
def people_home(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    out = CM.contacts(con, user)
    out["prefs"] = CM.prefs_of(con, user["id"])
    return out


class PersonActBody(BaseModel):
    accept: bool = True
    reason: str = ""
    message_id: int | None = None


@router.post("/api/learn/people/{pid}/{act}")
def people_act(pid: int, act: str, body: PersonActBody,
               user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    if act == "request":
        out = CM.request(con, user, pid)
    elif act == "respond":
        out = CM.respond(con, user, pid, body.accept)
    elif act == "remove":
        out = CM.remove(con, user, pid)
    elif act == "block":
        out = CM.block(con, user, pid)
    elif act == "unblock":
        out = CM.unblock(con, user, pid)
    elif act == "ghost":
        out = CM.ghost(con, user, pid)
    elif act == "unghost":
        out = CM.unghost(con, user, pid)
    elif act == "report":
        out = CM.report(con, user, pid, body.reason,
                        message_id=body.message_id)
    else:
        raise HTTPException(404, "unknown action")
    con.commit()
    return out


@router.get("/api/learn/thread/{pid}")
def thread_read(pid: int, since: float = 0, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    msgs = CM.thread(con, user, pid, since=since)
    con.commit()                            # the read receipts
    return {"messages": msgs, "me": user["id"]}


class SendBody(BaseModel):
    body: str = ""
    kind: str = "text"
    room: str = ""


@router.post("/api/learn/thread/{pid}")
def thread_send(pid: int, body: SendBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    out = CM.send(con, user, pid, body.body, kind=body.kind, room=body.room)
    con.commit()
    return out


class PrefsBody(BaseModel):
    privacy_name: str | None = None
    invisible: int | None = None
    open_dm: int | None = None


@router.post("/api/learn/prefs")
def prefs_set(body: PrefsBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    out = CM.set_prefs(con, user["id"], privacy_name=body.privacy_name,
                       invisible=body.invisible, open_dm=body.open_dm)
    con.commit()
    return out


# ── live video: the signaling mailboxes ──────────────────────────────────────
# The server never touches media — it relays SDP/ICE between browsers and
# answers "who is in the room". Room ids are unguessable and rooms are keyed
# by tenant. Teachers reach these same doors from the ops roster screen:
# one signaling path, not two.

@router.get("/api/learn/rtc/config")
def rtc_config(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    from erp.backend.main import CFG
    return CM.rtc_config(CFG)


class RtcBody(BaseModel):
    peer: str = ""
    to: str = ""
    payload: dict | None = None


@router.post("/api/learn/rtc/{room}/join")
def rtc_join(room: str, body: RtcBody, user=Depends(current_customer),
             con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    out = CM._rtc_join(room, body.peer or None)
    out["actor"] = {"id": user["id"], "name": user["name"]}
    return out


@router.post("/api/learn/rtc/{room}/signal")
def rtc_signal(room: str, body: RtcBody, user=Depends(current_customer),
               con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    CM._rtc_signal(room, body.to, body.peer, body.payload)
    return {"ok": True}


@router.get("/api/learn/rtc/{room}/poll")
def rtc_poll(room: str, peer: str = "", user=Depends(current_customer),
             con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    return CM._rtc_poll(room, peer)


@router.post("/api/learn/rtc/{room}/leave")
def rtc_leave(room: str, body: RtcBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("learning")
    CM._rtc_leave(room, body.peer)
    return {"ok": True}


# ── the calendar: my sessions, month by month ────────────────────────────────
# One JSON list per course; the month grid, navigation and day panels are all
# client-side. Each row carries only what the viewer is entitled to: `mine`
# is their OWN attendance and nobody else's — the roster stays teacher-side.

@router.get("/api/learn/courses/{cid}/sessions")
def course_sessions(cid: int, user=Depends(current_customer),
                    con=Depends(get_con)):
    _require_cap("learning")
    if not L.enrolled_in(con, cid, user["id"]) \
            and not L.may_edit(con, user, cid):
        raise HTTPException(403, "you are not enrolled in this course")
    rows = con.execute(
        "SELECT s.id, s.started_at, s.ended_at, s.status, s.lesson_id,"
        " (SELECT l.title FROM lessons l WHERE l.id=s.lesson_id)"
        "   AS lesson_title,"
        " (SELECT COUNT(*) FROM checkins ch WHERE ch.session_id=s.id"
        "   AND ch.status IN ('present','late')) AS attended,"
        " (SELECT COUNT(*) FROM learning_materials m"
        "   WHERE m.session_id=s.id) AS recordings,"
        " (SELECT ch.status FROM checkins ch WHERE ch.session_id=s.id"
        "   AND ch.student_id=?) AS mine"
        " FROM class_sessions s WHERE s.course_id=?"
        " AND s.status != 'cancelled' ORDER BY s.started_at",
        (user["id"], cid)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/learn/sessions/{sid}/recordings")
def session_recordings(sid: int, user=Depends(current_customer),
                       con=Depends(get_con)):
    """Gated on enrolment, not attendance: missing the class is the
    commonest reason to want the recording, so gating on attendance would
    withhold it from exactly the people it is most for."""
    _require_cap("learning")
    s = con.execute("SELECT course_id FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    if not L.enrolled_in(con, s["course_id"], user["id"]) \
            and not L.may_edit(con, user, s["course_id"]):
        raise HTTPException(403, "you are not enrolled in this course")
    return MAT.of_session(con, sid)


# ── the portal surfaces: notifications, live now, my quizzes, me ─────────────
# The bell reads what the platform already pushes at learners (grades,
# achievements, class starts, seat decisions) — the rows were always
# written; this is the reader they never had on /learn.

@router.get("/api/learn/notifications")
def my_notifications(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    from erp.backend import notify
    items, unread = notify.for_user(con, user)
    return {"items": items, "unread": unread}


@router.post("/api/learn/notifications/read")
def my_notifications_read(user=Depends(current_customer),
                          con=Depends(get_con)):
    _require_cap("learning")
    from erp.backend import notify
    notify.mark_all_read(con, user)
    return {"ok": True}


@router.get("/api/learn/live")
def live_now(user=Depends(current_customer), con=Depends(get_con)):
    """Every class in session across MY courses — the check-in screen and
    the live-class screen both draw from this one answer."""
    _require_cap("learning")
    out = []
    for s in con.execute(
            "SELECT s.*, c.name AS course, c.language, u.name AS teacher"
            " FROM class_sessions s JOIN courses c ON c.id=s.course_id"
            " LEFT JOIN users u ON u.id=s.teacher_id"
            " WHERE s.status='open' ORDER BY s.started_at").fetchall():
        if not L.enrolled_in(con, s["course_id"], user["id"]):
            continue
        mine = con.execute(
            "SELECT status FROM checkins WHERE session_id=? AND student_id=?",
            (s["id"], user["id"])).fetchone()
        out.append({"id": s["id"], "course_id": s["course_id"],
                    "course": s["course"], "language": s["language"] or "",
                    "teacher": s["teacher"] or "",
                    "started_at": s["started_at"], "room": s["room"],
                    "my_status": mine["status"] if mine else None,
                    "enrolled": len(CR.enrolled(con, s["course_id"]))})
    return out


@router.get("/api/learn/quizzes")
def my_quizzes(user=Depends(current_customer), con=Depends(get_con)):
    """Published quizzes across my courses with where I stand on each —
    the portal's Quizzes tab in one answer."""
    _require_cap("learning")
    out = []
    for q in con.execute(
            "SELECT q.id, q.title, q.intro, q.pass_mark, q.course_id,"
            " c.name AS course FROM quizzes q"
            " JOIN courses c ON c.id=q.course_id"
            " WHERE q.published=1 AND c.active=1 ORDER BY c.name, q.id"
            ).fetchall():
        if not L.enrolled_in(con, q["course_id"], user["id"]):
            continue
        a = con.execute(
            "SELECT id, state FROM quiz_attempts WHERE quiz_id=? AND"
            " user_id=? ORDER BY id DESC LIMIT 1",
            (q["id"], user["id"])).fetchone()
        out.append({**dict(q), "attempt": dict(a) if a else None})
    return out


@router.get("/api/learn/me")
def me_view(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    attended = con.execute(
        "SELECT COUNT(*) AS n FROM checkins WHERE student_id=?"
        " AND status IN ('present','late')", (user["id"],)).fetchone()["n"]
    return {"id": user["id"], "name": user["name"],
            "email": user["email"] or "", "role": user["role"],
            "has_password": bool(user["password_hash"]),
            "attended": attended,
            "achievements": L.achievements_of(con, user["id"])}


class MeBody(BaseModel):
    email: str = ""


@router.post("/api/learn/me")
def me_update(body: MeBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("learning")
    email = body.email.strip()
    if email and "@" not in email:
        raise HTTPException(400, "that does not look like an email")
    con.execute("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
    con.commit()
    return {"ok": True}


@router.post("/api/learn/me/signout-all")
def me_signout_all(user=Depends(current_customer), con=Depends(get_con)):
    """Rotate the bearer token: every session on every device ends,
    including this one — which is the point when a device is lost."""
    _require_cap("learning")
    import secrets as _secrets
    con.execute("UPDATE users SET token=? WHERE id=?",
                (_secrets.token_urlsafe(24), user["id"]))
    con.execute("DELETE FROM login_tokens WHERE user_id=?", (user["id"],))
    con.commit()
    return {"ok": True}


# ── discovery: ask to join a course you can see ──────────────────────────────

class JoinBody(BaseModel):
    note: str = ""


@router.post("/api/learn/courses/{cid}/request")
def course_request(cid: int, body: JoinBody,
                   user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    out = L.request_seat(con, user, cid, note=body.note)
    con.commit()
    return out


# ── the library: my loans ────────────────────────────────────────────────────

@router.get("/api/learn/loans")
def my_loans(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    return LIB.my_loans(con, user["id"])


# ── QR identity: my card, and the handshake ──────────────────────────────────

@router.get("/api/learn/me/card")
def my_card(request: Request, user=Depends(current_customer),
            con=Depends(get_con)):
    """The printable ID card. The QR carries a URL built from the request's
    own host — no configured hostname to get wrong — so a card printed on
    the LAN carries the LAN address an iPhone camera can open."""
    _require_cap("learning")
    uid = ID.ensure_uid(con, user["id"])
    con.commit()
    from erp.backend.main import base_url
    return {"uid": uid, "payload": ID.payload_for(uid, base=base_url()),
            "plain": ID.payload_for(uid)}


@router.post("/api/learn/me/qr/reissue")
def my_card_reissue(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    uid = ID.reissue(con, user["id"])
    con.commit()
    from erp.backend.main import base_url
    return {"uid": uid, "payload": ID.payload_for(uid, base=base_url())}


class ScanBody(BaseModel):
    payload: str = ""


@router.post("/api/learn/people/scan")
def people_scan(body: ScanBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    return ID.resolve_handshake(con, user, body.payload)


@router.get("/p/{uid}")
def person_deeplink(uid: str):
    """The iPhone path: the Camera app opens the card's URL, landing here
    already holding the code. The SPA finishes the handshake."""
    _require_cap("learning")
    return RedirectResponse(f"/learn?scan={uid}", status_code=302)


# ── data rights: my own export ───────────────────────────────────────────────

@router.get("/api/learn/me/export")
def my_export(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    data = DR.export_person(con, user, user["id"])
    return JSONResponse(data, headers={
        "Content-Disposition":
            f'attachment; filename="my-data-{user["id"]}.json"'})


# ── voice & translation: lookup + the speech panel's server half ─────────────
# Its own capability ($30, depends Learning): revoked = these four doors are
# 404s and the panel never renders. Dictation and TTS are browser-side and
# need no server at all.

@router.get("/api/learn/voice/providers")
def voice_providers(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _require_cap("voice")
    from erp.backend.main import CFG
    return LK.providers(CFG)


@router.get("/api/learn/voice/translate")
def voice_translate(q: str = "", source: str = "en", target: str = "es",
                    user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _require_cap("voice")
    from erp.backend.main import CFG
    return LK.translate(CFG, q, source=source[:8], target=target[:8])


@router.get("/api/learn/voice/thesaurus")
def voice_thesaurus(q: str = "", lang: str = "en",
                    user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _require_cap("voice")
    from erp.backend.main import CFG
    return LK.thesaurus(CFG, q, lang=lang[:8])


# ── recordings: spoken and video answers, and playback ───────────────────────

@router.post("/api/learn/attempts/{aid}/recording")
async def attempt_recording(aid: int, request: Request, question_id: int = 0,
                            user=Depends(current_customer),
                            con=Depends(get_con)):
    """A spoken or video answer: raw bytes in, stored as a material, linked
    to the question through the same save path as any other answer."""
    _require_cap("learning")
    L.own_attempt(con, user, aid)           # theirs, and it must exist
    data = await MAT.read_upload(request)
    saved = MAT.save(data, allow=("audio", "video"))
    mid = MAT.record(con, saved=saved, owner_id=user["id"],
                     original=f"answer to question {question_id}")
    L.save_answer(con, user, aid, question_id, material_id=mid)
    con.commit()
    return {"ok": True, "material_id": mid, **saved}


@router.get("/media/{shard}/{name}")
def serve_media(shard: str, name: str, con=Depends(get_con)):
    """Stored media, by its unguessable token name. The token IS the read
    capability — a <video src> cannot send a bearer token, exactly as in
    the source. nosniff + a fixed mime, never executed."""
    _require_cap("learning")
    if not re.fullmatch(r"[0-9a-f]{2}", shard) \
            or not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{2,5}", name):
        raise HTTPException(404, "no such file")
    path = os.path.join(MAT.uploads_root(), shard, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "no such file")
    r = con.execute("SELECT mime FROM learning_materials WHERE path=?",
                    (f"{shard}/{name}",)).fetchone()
    return FileResponse(path, media_type=(r["mime"] if r else
                                          "application/octet-stream"),
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Cache-Control":
                                     "private, max-age=31536000, immutable"})


# ── the public door: programmes + registration ───────────────────────────────
# No sign-in required. Submitting grants nothing — an administrator approves
# the application in ops, and THAT creates the account and the seat.

@router.get("/api/learn/programs")
def programs(con=Depends(get_con)):
    _require_cap("learning")
    return L.public_programs(con)


class RegisterBody(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    language: str = ""
    level: str = "A1"
    goals: str = ""
    availability: str = ""
    course_id: int | None = None


@router.post("/api/learn/register")
def register(body: RegisterBody, request: Request, con=Depends(get_con)):
    _require_cap("learning")
    rate_limit(request)
    rid = L.register_submit(
        con, name=body.name, email=body.email, language=body.language,
        level=body.level, phone=body.phone, goals=body.goals,
        availability=body.availability, course_id=body.course_id)
    con.commit()
    return {"ok": True, "id": rid}


# ── the page ─────────────────────────────────────────────────────────────────
# One server-rendered shell; the little SPA inside talks to the APIs above
# with the storefront's own stored sign-in.

@router.get("/learn")
def learn_page(con=Depends(get_con)):
    _require_cap("learning")
    from .api import asset_version
    _brand = brand_name(con)
    v = asset_version()
    body = f"""
<section class="section partner-head">
 <span class="eyebrow">Learning</span>
 <h1>Your courses</h1>
 <p class="lede">Lessons in order, quizzes when you're ready, and your
  progress as you go. Scores only become final once every answer is marked —
  written answers may wait for a teacher, and that's the point.</p>
</section>
<section class="section"><div id="learn-root">
 <p class="dim">Loading…</p>
</div></section>
<style>
 .lrn-grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}}
 .lrn-card{{border:1px solid rgba(127,127,127,.25);border-radius:12px;padding:16px;cursor:pointer}}
 .lrn-card h3{{margin:0 0 6px}}
 .lrn-bar{{height:6px;border-radius:3px;background:rgba(127,127,127,.2);margin-top:10px;overflow:hidden}}
 .lrn-bar i{{display:block;height:100%;background:currentColor}}
 .lrn-list{{list-style:none;padding:0;margin:12px 0}}
 .lrn-list li{{display:flex;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(127,127,127,.15)}}
 .lrn-done{{opacity:.6;text-decoration:line-through}}
 .lrn-q{{border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:14px;margin:10px 0}}
 .lrn-q label{{display:block;margin:6px 0;cursor:pointer}}
 .lrn-back{{margin-bottom:14px;display:inline-block;cursor:pointer;text-decoration:underline}}
 .lrn-btn{{padding:8px 16px;border-radius:8px;border:1px solid currentColor;background:none;color:inherit;cursor:pointer}}
 .lrn-btn.primary{{font-weight:700}}
 .lrn-btn.sm{{padding:4px 10px;font-size:.85em}}
 .lrn-meta{{opacity:.7;font-size:.9em}}
 .lrn-lesson h2,.lrn-lesson h3,.lrn-lesson h4{{margin-top:1.2em}}
 .lrn-lesson pre{{background:rgba(127,127,127,.12);padding:12px;border-radius:8px;overflow-x:auto}}
 .lrn-live{{border:1px solid currentColor;border-radius:10px;padding:12px 16px;margin:12px 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
 .lrn-badges{{display:flex;gap:8px;flex-wrap:wrap}}
 .lrn-badge{{border:1px solid rgba(127,127,127,.4);border-radius:999px;padding:4px 12px;font-size:.9em}}
 .lrn-tabs{{display:flex;gap:4px;margin-bottom:18px;border-bottom:1px solid rgba(127,127,127,.25)}}
 .lrn-tab{{padding:8px 18px;cursor:pointer;border-radius:8px 8px 0 0}}
 .lrn-tab.on{{font-weight:700;border:1px solid rgba(127,127,127,.25);border-bottom-color:transparent}}
 .lrn-search input{{width:100%;max-width:420px;padding:10px;border-radius:8px;border:1px solid rgba(127,127,127,.4);background:none;color:inherit}}
 .lrn-person{{display:flex;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(127,127,127,.15)}}
 .lrn-person-acts{{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}}
 .lrn-unread{{background:currentColor;color:var(--bg,#fff);border-radius:999px;padding:0 8px;font-size:.8em}}
 .lrn-prefs{{display:grid;gap:10px;max-width:480px}}
 .lrn-thread{{max-height:50vh;overflow-y:auto;border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}}
 .lrn-msg{{max-width:75%;padding:8px 12px;border-radius:10px;background:rgba(127,127,127,.15);position:relative}}
 .lrn-msg.mine{{align-self:flex-end;background:rgba(127,127,127,.3)}}
 .lrn-msg-report{{position:absolute;top:2px;right:-18px;cursor:pointer;opacity:.4}}
 .lrn-msg-report:hover{{opacity:1}}
 #lrn-call{{position:fixed;inset:auto 12px 12px 12px;max-height:70vh;background:var(--bg,#111);color:inherit;border:1px solid rgba(127,127,127,.4);border-radius:14px;z-index:200;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.4)}}
 .lrn-call-head{{display:flex;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid rgba(127,127,127,.25)}}
 .lrn-call-grid{{display:grid;gap:8px;padding:12px;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));overflow-y:auto}}
 .lrn-call-grid video{{width:100%;border-radius:10px;background:#000;aspect-ratio:4/3;object-fit:cover}}
 .lrn-cal{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;max-width:420px}}
 .lrn-cal .dow{{font-size:.75em;opacity:.6;text-align:center;padding:2px 0}}
 .lrn-cal .day{{text-align:center;padding:6px 0;border-radius:8px;border:1px solid transparent}}
 .lrn-cal .day.dim{{opacity:.3}}
 .lrn-cal button.day{{border-color:rgba(127,127,127,.4);background:none;color:inherit;cursor:pointer}}
 .lrn-cal button.day.sel{{border-color:currentColor;font-weight:700}}
 .lrn-cal .dot{{display:block;margin:2px auto 0;width:6px;height:6px;border-radius:3px;background:currentColor;opacity:.5}}
 .lrn-cal .dot.present,.lrn-cal .dot.late{{background:#3c9;opacity:1}}
 .lrn-cal .dot.absent{{background:#e66;opacity:1}}
 .lrn-tabs .lrn-spacer{{flex:1;border-bottom:none}}
 .lrn-tabs #lrn-bell{{align-self:center;margin-bottom:6px}}
 .lrn-noti-panel{{border:1px solid rgba(127,127,127,.35);border-radius:12px;padding:10px 14px;margin-bottom:14px;max-height:320px;overflow-y:auto}}
 .lrn-item{{display:flex;gap:10px;align-items:baseline;padding:9px 2px;border-bottom:1px solid rgba(127,127,127,.15)}}
 .lrn-item .grow{{flex:1}}
 .lrn-item.lrn-new b{{border-left:3px solid currentColor;padding-left:8px}}
 .lrn-row-click{{cursor:pointer}}
 .lrn-row-click:hover b{{text-decoration:underline}}
 .lrn-row-gap{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
 .pill-live{{border:1px solid #3c9;color:#3c9;border-radius:999px;padding:1px 9px;font-size:.75em;vertical-align:middle}}
 .lrn-idcard{{border:1px solid rgba(127,127,127,.4);border-radius:14px;padding:20px;max-width:340px;text-align:center}}
 .lrn-idcard img{{width:220px;height:220px;background:#fff;padding:8px;border-radius:8px}}
 .lrn-lookup{{position:fixed;right:16px;bottom:84px;z-index:47;max-width:340px}}
 /* bottom:84px + z-index below the buy-fab (48): the lookup stacks ABOVE
    the floating Buy now instead of fighting it for the same corner */
 .lrn-lookup .panel{{background:var(--bg,#111);border:1px solid rgba(127,127,127,.4);border-radius:14px;padding:14px;box-shadow:0 12px 40px rgba(0,0,0,.4)}}
 .lrn-lookup input,.lrn-lookup select{{padding:6px 8px;border-radius:8px;border:1px solid rgba(127,127,127,.4);background:none;color:inherit}}
 .lrn-rec{{border:1px dashed rgba(127,127,127,.4);border-radius:10px;padding:10px;margin:8px 0}}
 .lrn-rec .state{{opacity:.7;font-size:.9em}}
 audio,video.lrn-media{{max-width:100%;border-radius:8px}}
 @media print{{.lrn-tabs,.lrn-back,.no-print,header,footer,nav{{display:none !important}}}}
</style>
<script src="/rtc-mesh.js?v={v}"></script>
<script src="/learn.js?v={v}"></script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"Learning — {_brand}",
        description=f"{_brand} courses: lessons, quizzes and your progress."))
