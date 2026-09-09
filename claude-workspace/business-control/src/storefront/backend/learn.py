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
import html as _html

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
        # A course you teach is yours too. Without this a teacher on the
        # learner page saw her own course in the catalogue with "Ask to
        # join", because the teacher's surface used to be ops alone —
        # and the register and the handouts now live on this page.
        teaching = L.may_edit(con, user, r["id"])
        if teaching or L.enrolled_in(con, r["id"], user["id"]):
            d["progress"] = L.course_progress(con, r["id"], user["id"])
            d["teaching"] = teaching
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
            "may_edit": L.may_edit(con, user, cid),
            "materials": MAT.of_course(con, cid),
            "schedule": L.schedule_of(con, cid),
            "my_tutoring": [dict(r) for r in con.execute(
                "SELECT id, state, note, reply, created_at FROM tutoring_requests"
                " WHERE course_id=? AND user_id=? ORDER BY id DESC LIMIT 3",
                (cid, user["id"]))],
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
            "may_edit": L.may_edit(con, user, lesson["course_id"]),
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
    privacy_photo: int | None = None
    invisible: int | None = None
    open_dm: int | None = None


@router.post("/api/learn/prefs")
def prefs_set(body: PrefsBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("learning")
    _member(con, user)
    out = CM.set_prefs(con, user["id"], privacy_name=body.privacy_name,
                       privacy_photo=body.privacy_photo,
                       invisible=body.invisible, open_dm=body.open_dm)
    con.commit()
    return out


@router.post("/api/learn/me/photo")
async def me_photo(request: Request, user=Depends(current_customer),
                   con=Depends(get_con)):
    """The person's photo — self-uploaded ONLY, and uploading is the
    consent. It lands token-named in the sharded store like every other
    media file, is shared by their own privacy_photo switch, and leaves
    with them: removal here, erasure everywhere."""
    _require_cap("learning")
    data = await MAT.read_upload(request)
    saved = MAT.save(data, allow=("image",))
    if user["photo"]:
        MAT.unlink(user["photo"])
    con.execute("UPDATE users SET photo=? WHERE id=?",
                (saved["path"], user["id"]))
    con.commit()
    return {"photo": saved["path"]}


@router.delete("/api/learn/me/photo")
def me_photo_remove(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    if user["photo"]:
        MAT.unlink(user["photo"])
    con.execute("UPDATE users SET photo='' WHERE id=?", (user["id"],))
    con.commit()
    return {"ok": True}


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
    out = CM._rtc_join(room, body.peer or None,
                       {"name": user["name"], "user_id": user["id"]})
    out["actor"] = {"id": user["id"], "name": user["name"]}
    return out


class RtcMarkBody(BaseModel):
    peer: str = ""
    screen: bool = False


@router.post("/api/learn/rtc/{room}/mark")
def rtc_mark(room: str, body: RtcMarkBody, user=Depends(current_customer),
             con=Depends(get_con)):
    """Sharing a screen is said to the room, so the tile can be labelled
    and the people list can show who is presenting."""
    _require_cap("learning")
    _member(con, user)
    CM._rtc_mark(room, body.peer, screen=body.screen)
    return {"ok": True}


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


def _class_and_seat(con, user, sid: int):
    """The open session, and whether this person may be in its room:
    enrolled, or the door (teacher, staff, volunteer). Same rule as the
    live list, so what you can see you can also talk in."""
    s = con.execute("SELECT s.*, c.name AS course FROM class_sessions s"
                    " JOIN courses c ON c.id=s.course_id WHERE s.id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "no such class")
    is_door = (user["is_admin"] or CM.is_staff(con, user)
               or user["role"] in ("volunteer", "employee")
               or L.may_edit(con, user, s["course_id"]))
    if not (is_door or L.enrolled_in(con, s["course_id"], user["id"])):
        raise HTTPException(403, "that class is not one of yours")
    return s, is_door


@router.get("/api/learn/sessions/{sid}/chat")
def class_chat(sid: int, since: int = 0, user=Depends(current_customer),
               con=Depends(get_con)):
    """Everything said since message `since` — polled beside the call's
    own poll, so one transport carries both."""
    _require_cap("learning")
    _class_and_seat(con, user, sid)
    rows = [dict(r) for r in con.execute(
        "SELECT id, user_id, name, body, at FROM class_chat"
        " WHERE session_id=? AND id>? ORDER BY id LIMIT 200",
        (sid, since))]
    return {"messages": rows, "me": user["id"]}


class ChatBody(BaseModel):
    body: str = ""


@router.post("/api/learn/sessions/{sid}/chat")
def class_say(sid: int, body: ChatBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("learning")
    s, _ = _class_and_seat(con, user, sid)
    if s["status"] != "open":
        raise HTTPException(409, "the class has ended")
    text = body.body.strip()[:2000]
    if not text:
        raise HTTPException(400, "nothing to say")
    cur = con.execute("INSERT INTO class_chat(session_id,user_id,name,body,at)"
                      " VALUES(?,?,?,?,?)",
                      (sid, user["id"], user["name"], text, time.time()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


# ── asking for more: tutoring ────────────────────────────────────────────────

class TutoringBody(BaseModel):
    note: str = ""
    availability: list = []


@router.post("/api/learn/courses/{cid}/tutoring")
def ask_tutoring(cid: int, body: TutoringBody, user=Depends(current_customer),
                 con=Depends(get_con)):
    """A student asks for extra help, saying when they could take it.
    One open ask per person per course — asking twice is the same ask,
    updated, not a second row in somebody's queue."""
    _require_cap("learning")
    if not L.enrolled_in(con, cid, user["id"]):
        raise HTTPException(403, "you are not in this course")
    slots = []
    for a in body.availability[:14]:
        try:
            wd, f, t = int(a.get("weekday", 0)), int(a.get("from_min", 0)), int(a.get("to_min", 0))
        except (AttributeError, ValueError, TypeError):
            continue
        if 0 <= wd <= 6 and 0 <= f < t <= 24 * 60:
            slots.append({"weekday": wd, "from_min": f, "to_min": t})
    import json as _j
    now = time.time()
    r = con.execute("SELECT id FROM tutoring_requests WHERE course_id=? AND"
                    " user_id=? AND state='open'", (cid, user["id"])).fetchone()
    if r:
        con.execute("UPDATE tutoring_requests SET note=?, availability=?,"
                    " updated_at=? WHERE id=?",
                    (body.note.strip()[:1000], _j.dumps(slots), now, r["id"]))
        rid = r["id"]
    else:
        cur = con.execute(
            "INSERT INTO tutoring_requests(course_id,user_id,note,availability,"
            "state,created_at,updated_at) VALUES(?,?,?,?,'open',?,?)",
            (cid, user["id"], body.note.strip()[:1000], _j.dumps(slots), now, now))
        rid = cur.lastrowid
        c = con.execute("SELECT name, teacher_id FROM courses WHERE id=?", (cid,)).fetchone()
        from erp.backend import notify
        notify.push(con, f"{user['name']} is asking for tutoring",
                    f"{c['name']} — see Classes", kind="learning",
                    user_id=c["teacher_id"] or None)
    con.commit()
    return {"ok": True, "id": rid}


@router.post("/api/learn/tutoring/{rid}/withdraw")
def withdraw_tutoring(rid: int, user=Depends(current_customer),
                      con=Depends(get_con)):
    _require_cap("learning")
    con.execute("UPDATE tutoring_requests SET state='declined', reply='withdrawn',"
                " updated_at=? WHERE id=? AND user_id=? AND state='open'",
                (time.time(), rid, user["id"]))
    con.commit()
    return {"ok": True}


# ── a training: the link is the door ─────────────────────────────────────────

@router.get("/training/{token}", response_class=HTMLResponse)
def training_page(token: str, request: Request, con=Depends(get_con)):
    """One film, one page, no sign-in. Who watched is counted by account
    when the browser carries one, by visitor id when it does not, so the
    office can see the list without anybody having to register to watch
    a five-minute demo."""
    _require_cap("learning")
    t = con.execute("SELECT t.*, m.kind, m.path, m.mime, m.original FROM trainings t"
                    " LEFT JOIN learning_materials m ON m.id=t.material_id"
                    " WHERE t.token=?", (token,)).fetchone()
    if t is None or not t["active"]:
        return HTMLResponse("<h3>No training at this address.</h3>", 404)
    from erp.backend.main import CFG
    e = _html.escape
    shop = CFG.get("brand_name") or "this shop"
    media = ""
    if t["kind"] == "video":
        media = f'<video controls playsinline preload="metadata" src="/media/{e(t["path"])}"></video>'
    elif t["kind"] == "audio":
        media = f'<audio controls src="/media/{e(t["path"])}"></audio>'
    elif t["kind"] == "image":
        media = f'<img src="/media/{e(t["path"])}" alt="">'
    elif t["kind"] == "document":
        media = (f'<p><a class="btn" href="/media/{e(t["path"])}" target="_blank" rel="noopener">'
                 f'Open {e(t["original"] or "the file")}</a></p>')
    else:
        media = '<p class="k">The film is not up yet — check back shortly.</p>'
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{e(t['title'])} — {e(shop)}</title>
<style>:root{{color-scheme:light}}
body{{font:16px/1.55 system-ui,sans-serif;max-width:48rem;margin:4vh auto;
padding:0 1.2rem;color:#16202b;background:#fff}}
h1{{font-size:1.5rem;margin:0 0 .2rem}} .k{{color:#5b6b7c;font-size:.92rem}}
video,img{{width:100%;border-radius:.6rem;background:#000;margin:1rem 0}}
audio{{width:100%;margin:1rem 0}}
.btn{{display:inline-block;padding:.6rem 1rem;border-radius:.5rem;
background:#4634d9;color:#fff;text-decoration:none}}
.blurb{{white-space:pre-wrap}}
</style>
<h1>{e(t['title'])}</h1>
<p class=k>{e(shop)} · a training</p>
{media}
<p class=blurb>{e(t['blurb'])}</p>
<p class=k id=seen></p>
<script>
(function(){{
  var tok=null; try{{tok=JSON.parse(localStorage.getItem("sf_support")||"{{}}").token;}}catch(e){{}}
  var vid=localStorage.getItem("sf_vid"); if(!vid){{vid=crypto.randomUUID(); localStorage.setItem("sf_vid",vid);}}
  fetch("/api/learn/training/{e(token)}/seen",{{method:"POST",headers:Object.assign({{"Content-Type":"application/json"}},
    tok?{{Authorization:"Bearer "+tok}}:{{}}),body:JSON.stringify({{visitor_id:vid}})}})
    .then(function(r){{return r.json();}}).then(function(j){{
      var s=document.getElementById("seen"); if(s&&j.as) s.textContent="Counted as watched by "+j.as+".";
    }}).catch(function(){{}});
}})();
</script>""")


class SeenBody(BaseModel):
    visitor_id: str = ""


@router.post("/api/learn/training/{token}/seen")
def training_seen(token: str, body: SeenBody, request: Request,
                  con=Depends(get_con)):
    _require_cap("learning")
    t = con.execute("SELECT id FROM trainings WHERE token=? AND active=1",
                    (token,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such training")
    from erp.backend import auth
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    u = auth.user_for_token(con, tok) if tok else None
    who = f"user:{u['id']}" if u else f"visitor:{(body.visitor_id or 'anon')[:64]}"
    name = u["name"] if u else ""
    now = time.time()
    con.execute("INSERT INTO training_views(training_id,who,name,first_at,last_at,views)"
                " VALUES(?,?,?,?,?,1) ON CONFLICT(training_id,who) DO UPDATE SET"
                " last_at=excluded.last_at, views=views+1, name=excluded.name",
                (t["id"], who, name, now, now))
    con.commit()
    return {"ok": True, "as": name or "this browser"}


# ── the course board ─────────────────────────────────────────────────────────

def _seat(con, user, cid: int):
    if not (L.enrolled_in(con, cid, user["id"]) or L.may_edit(con, user, cid)):
        raise HTTPException(403, "you are not in this course")


@router.get("/api/learn/courses/{cid}/threads")
def board(cid: int, user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("learning")
    _seat(con, user, cid)
    from erp.backend import discuss as D
    return {"threads": D.threads(con, cid),
            "may_moderate": L.may_edit(con, user, cid), "me": user["id"]}


class ThreadBody(BaseModel):
    title: str = ""
    body: str = ""


@router.post("/api/learn/courses/{cid}/threads")
def board_start(cid: int, body: ThreadBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    _seat(con, user, cid)
    if not body.title.strip():
        raise HTTPException(400, "a thread needs a title")
    from erp.backend import discuss as D
    tid = D.start(con, cid, user["id"], body.title, body.body)
    con.commit()
    return {"ok": True, "id": tid}


@router.get("/api/learn/threads/{tid}")
def board_thread(tid: int, user=Depends(current_customer),
                 con=Depends(get_con)):
    _require_cap("learning")
    from erp.backend import discuss as D
    t = D.thread(con, tid)
    if t is None:
        raise HTTPException(404, "no such thread")
    _seat(con, user, t["course_id"])
    t["may_moderate"] = L.may_edit(con, user, t["course_id"])
    t["me"] = user["id"]
    return t


class PostBody(BaseModel):
    body: str = ""


@router.post("/api/learn/threads/{tid}/posts")
def board_reply(tid: int, body: PostBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("learning")
    from erp.backend import discuss as D
    t = D.thread(con, tid)
    if t is None:
        raise HTTPException(404, "no such thread")
    _seat(con, user, t["course_id"])
    if not body.body.strip():
        raise HTTPException(400, "nothing to post")
    pid = D.reply(con, tid, user["id"], body.body)
    con.commit()
    return {"ok": True, "id": pid}


@router.post("/api/learn/posts/{pid}/delete")
def board_post_delete(pid: int, user=Depends(current_customer),
                      con=Depends(get_con)):
    """The author's, or the teacher's. The row stays with the body gone,
    so a thread does not renumber under the people replying to it."""
    _require_cap("learning")
    r = con.execute("SELECT p.*, t.course_id FROM course_posts p"
                    " JOIN course_threads t ON t.id=p.thread_id"
                    " WHERE p.id=?", (pid,)).fetchone()
    if r is None:
        return {"ok": True}
    if r["user_id"] != user["id"] and not L.may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "not yours to delete")
    con.execute("UPDATE course_posts SET deleted=1, body='' WHERE id=?", (pid,))
    con.commit()
    return {"ok": True}


@router.post("/api/learn/threads/{tid}/delete")
def board_thread_delete(tid: int, user=Depends(current_customer),
                        con=Depends(get_con)):
    _require_cap("learning")
    r = con.execute("SELECT * FROM course_threads WHERE id=?", (tid,)).fetchone()
    if r is None:
        return {"ok": True}
    if r["user_id"] != user["id"] and not L.may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "not yours to delete")
    con.execute("UPDATE course_threads SET deleted=1 WHERE id=?", (tid,))
    con.commit()
    return {"ok": True}


@router.get("/api/learn/sessions/{sid}/shared")
def class_shared(sid: int, user=Depends(current_customer),
                 con=Depends(get_con)):
    """What the teacher put in front of the class: files attached to this
    session, and the drills on the lesson it is teaching. Read from the
    panel, in the call or from a phone in the room."""
    _require_cap("learning")
    s, _ = _class_and_seat(con, user, sid)
    items = []
    for m in con.execute(
            "SELECT id, kind, path, original, mime, bytes, created_at"
            " FROM learning_materials WHERE session_id=?"
            " ORDER BY id DESC", (sid,)):
        items.append({"id": m["id"], "kind": m["kind"],
                      "title": m["original"] or m["kind"],
                      "url": f"/media/{m['path']}", "bytes": m["bytes"],
                      "at": m["created_at"]})
    for m in MAT.of_course(con, s["course_id"]):
        items.append({"id": m["id"], "kind": m["kind"],
                      "title": m["original"] or f"course {m['kind']}",
                      "url": f"/media/{m['path']}", "bytes": m["bytes"],
                      "at": m["created_at"], "course": True})
    if s["lesson_id"]:
        for m in con.execute(
                "SELECT id, kind, path, original, bytes, created_at"
                " FROM learning_materials WHERE lesson_id=? ORDER BY id",
                (s["lesson_id"],)):
            items.append({"id": m["id"], "kind": m["kind"],
                          "title": m["original"] or f"lesson {m['kind']}",
                          "url": f"/media/{m['path']}", "bytes": m["bytes"],
                          "at": m["created_at"], "lesson": True})
    return {"items": items, "course_id": s["course_id"],
            "lesson_id": s["lesson_id"]}


@router.get("/api/learn/live")
def live_now(user=Depends(current_customer), con=Depends(get_con)):
    """Every class in session across MY courses — the check-in screen and
    the live-class screen both draw from this one answer."""
    _require_cap("learning")
    # Door staff — volunteers, teachers, office staff, admins — see EVERY
    # open class, flagged, so the person at the entrance can run the
    # scanner from the portal they already live in.
    is_door = (user["is_admin"] or CM.is_staff(con, user)
               or user["role"] in ("volunteer", "employee"))
    from erp.backend.main import base_url
    base = base_url()
    out = []
    for s in con.execute(
            "SELECT s.*, c.name AS course, c.language, u.name AS teacher"
            " FROM class_sessions s JOIN courses c ON c.id=s.course_id"
            " LEFT JOIN users u ON u.id=s.teacher_id"
            " WHERE s.status='open' ORDER BY s.started_at").fetchall():
        member = L.enrolled_in(con, s["course_id"], user["id"])
        if not member and not is_door:
            continue
        mine = con.execute(
            "SELECT status FROM checkins WHERE session_id=? AND student_id=?",
            (s["id"], user["id"])).fetchone()
        out.append({"id": s["id"], "course_id": s["course_id"],
                    "course": s["course"], "language": s["language"] or "",
                    "teacher": s["teacher"] or "",
                    "started_at": s["started_at"], "room": s["room"],
                    "my_status": mine["status"] if mine else None,
                    "member": bool(member), "door": is_door,
                    # The teacher's register lives on this page too, for a
                    # teacher who is in the room rather than at a desk.
                    "may_mark": bool(is_door
                                     or L.may_edit(con, user, s["course_id"])),
                    # A link that opens straight into the call, for the
                    # class WhatsApp group. It still needs a seat: the
                    # room is for people who are in the course.
                    "join_url": f"{base}/learn?join={s['id']}",
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
    from erp.backend import roles as R
    return {"id": user["id"], "name": user["name"],
            "photo": user["photo"] or "",
            "prefs": CM.prefs_of(con, user["id"]),
            "email": user["email"] or "", "role": user["role"],
            "role_label": R.LABELS.get(user["role"], user["role"]),
            "requested_role": user["requested_role"] or "",
            "requested_label": R.LABELS.get(user["requested_role"] or "", ""),
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


# ── the record: performance across every course, exportable ─────────────────

@router.get("/api/learn/record")
def my_record(user=Depends(current_customer), con=Depends(get_con)):
    """The student's whole standing in one answer: per-course progress,
    attendance and every FINAL quiz result — derived on read like all
    grades here, so the record can never disagree with the data. The
    client turns this into the printable transcript and certificates;
    the server hands over facts, not stationery."""
    _require_cap("learning")
    from erp.backend import assessment as A
    courses = []
    for c in con.execute(
            "SELECT c.*, u.name AS teacher_name FROM courses c"
            " LEFT JOIN users u ON u.id=c.teacher_id"
            " WHERE c.active=1 ORDER BY c.name").fetchall():
        if not L.enrolled_in(con, c["id"], user["id"]):
            continue
        progress = L.course_progress(con, c["id"], user["id"])
        results = []
        for q in con.execute(
                "SELECT id, title, pass_mark FROM quizzes WHERE course_id=?"
                " AND published=1 ORDER BY id", (c["id"],)).fetchall():
            best = None
            for a in con.execute(
                    "SELECT id, graded_at FROM quiz_attempts WHERE quiz_id=?"
                    " AND user_id=? AND state='graded'",
                    (q["id"], user["id"])).fetchall():
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
        att = CR.attendance_of(con, c["id"], user["id"])
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
        " AND status IN ('present','late')", (user["id"],)).fetchone()["n"]
    return {
        "student": {"id": user["id"], "name": user["name"],
                    "email": user["email"] or ""},
        "school": brand_name(con),
        "generated_at": time.time(),
        "courses": courses,
        "achievements": L.achievements_of(con, user["id"]),
        "totals": {"courses": len(courses), "classes_attended": attended,
                   "quizzes_passed": sum(
                       1 for c in courses for r in c["results"]
                       if r["passed"]),
                   "completed_courses": sum(
                       1 for c in courses if c["complete"])},
    }


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
    r = con.execute("SELECT mime, kind, original FROM learning_materials"
                    " WHERE path=?", (f"{shard}/{name}",)).fetchone()
    headers = {"X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=31536000, immutable"}
    if r and r["kind"] == "document" and r["original"]:
        # A handout saved to a desk should keep the name it was handed
        # out under, not a hex token.
        safe = re.sub(r"[^\w.\- ]", "_", r["original"])[:120]
        headers["Content-Disposition"] = f'inline; filename="{safe}"'
    return FileResponse(path, media_type=(r["mime"] if r else
                                          "application/octet-stream"),
                        headers=headers)


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
 .lrn-avatar{{width:34px;height:34px;border-radius:50%;object-fit:cover;flex:none;display:inline-flex;align-items:center;justify-content:center;background:rgba(127,127,127,.25);font-weight:700;vertical-align:middle}}
 .lrn-me-photo{{display:flex;flex-direction:column;gap:8px;align-items:center;max-width:150px;text-align:center}}
 .lrn-me-photo .lrn-avatar{{width:72px;height:72px;font-size:1.6em}}
 .lrn-toast{{position:fixed;left:50%;bottom:26px;transform:translate(-50%,20px);background:var(--bg,#111);border:1px solid rgba(127,127,127,.5);border-radius:10px;padding:10px 18px;z-index:300;opacity:0;transition:.25s;pointer-events:none;box-shadow:0 8px 30px rgba(0,0,0,.4)}}
 .lrn-toast.on{{opacity:1;transform:translate(-50%,0)}}
 .lrn-person-acts{{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}}
 .lrn-unread{{background:currentColor;color:var(--bg,#fff);border-radius:999px;padding:0 8px;font-size:.8em}}
 .lrn-prefs{{display:grid;gap:10px;max-width:480px}}
 .lrn-thread{{max-height:50vh;overflow-y:auto;border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}}
 .lrn-msg{{max-width:75%;padding:8px 12px;border-radius:10px;background:rgba(127,127,127,.15);position:relative}}
 .lrn-msg.mine{{align-self:flex-end;background:rgba(127,127,127,.3)}}
 .lrn-msg-report{{position:absolute;top:2px;right:-18px;cursor:pointer;opacity:.4}}
 .lrn-msg-report:hover{{opacity:1}}
 #lrn-call{{position:fixed;inset:auto 12px 12px 12px;max-height:70vh;background:var(--bg,#111);color:inherit;border:1px solid rgba(127,127,127,.4);border-radius:14px;z-index:200;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.4)}}
 .lrn-call-head{{display:flex;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid rgba(127,127,127,.25);flex-wrap:wrap}}
 .lrn-call-side code{{word-break:break-all}}
 .lrn-call-grid{{display:grid;gap:8px;padding:12px;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));overflow-y:auto}}
 .lrn-call-grid video{{width:100%;border-radius:10px;background:#000;aspect-ratio:4/3;object-fit:cover}}
 .lrn-call-body{{display:flex;min-height:0;flex:1}}
 .lrn-call-body .lrn-call-grid{{flex:1;align-content:start}}
 .lrn-call-side{{width:min(340px,42vw);border-left:1px solid rgba(127,127,127,.25);display:flex;flex-direction:column;min-height:0}}
 .lrn-tile{{position:relative}}
 .lrn-tile.screen video{{object-fit:contain;background:#000}}
 .lrn-tile-name{{position:absolute;left:8px;bottom:8px;font-size:12px;padding:2px 8px;border-radius:999px;background:rgba(0,0,0,.55);color:#fff}}
 .lrn-panel-tabs{{display:flex;gap:2px;padding:8px 10px 0;border-bottom:1px solid rgba(127,127,127,.25)}}
 .lrn-ptab{{padding:6px 10px;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;opacity:.7}}
 .lrn-ptab.on{{opacity:1;background:rgba(127,127,127,.15)}}
 .lrn-ptab b{{font-weight:600;margin-left:4px}}
 .lrn-pane{{display:flex;flex-direction:column;min-height:0;flex:1;padding:10px}}
 .lrn-pane[hidden],.lrn-call-side[hidden],.lrn-panel-host[hidden]{{display:none}}
 .lrn-chat{{flex:1;overflow-y:auto;min-height:120px;max-height:40vh;display:flex;flex-direction:column;gap:8px}}
 .lrn-msg{{font-size:14px;line-height:1.35}} .lrn-msg.mine b{{color:var(--accent,#5ac8b0)}}
 .lrn-msg b{{font-size:13px}} .lrn-msg a{{word-break:break-all}}
 .lrn-say{{display:flex;gap:6px;margin-top:8px}} .lrn-say input{{flex:1;min-width:0}}
 .lrn-person{{display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid rgba(127,127,127,.15);font-size:14px}}
 .lrn-dot{{width:8px;height:8px;border-radius:50%;background:#3ccf8e;flex:none}}
 .lrn-shared{{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid rgba(127,127,127,.15)}}
 .lrn-panel-host{{border:1px solid rgba(127,127,127,.25);border-radius:12px;margin:0 0 14px;display:flex;flex-direction:column}}
 .lrn-tut-day{{display:flex;gap:8px;align-items:center;padding:3px 0}} .lrn-tut-day label{{min-width:60px}}
 .lrn-reg{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid rgba(127,127,127,.2)}}
 .lrn-reg img{{width:34px;height:34px;border-radius:50%;object-fit:cover;background:rgba(127,127,127,.2)}}
 .lrn-reg .lrn-regbtns{{margin-left:auto;display:flex;gap:4px;flex-wrap:wrap}}
 .lrn-reg .lrn-btn.on{{outline:2px solid var(--accent,#5ac8b0)}}
 .lrn-thread{{display:flex;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid rgba(127,127,127,.2)}}
 .lrn-thread b{{flex:1;cursor:pointer}}
 .lrn-post{{padding:10px 0;border-bottom:1px solid rgba(127,127,127,.15)}}
 .lrn-post .lrn-meta{{display:block;margin-bottom:3px}}
 .lrn-post p{{margin:0;white-space:pre-wrap}}
 .lrn-attach{{display:flex;gap:8px;align-items:center;margin:8px 0}}
 .lrn-file{{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid rgba(127,127,127,.15)}}
 @media (max-width:720px){{ .lrn-call-body{{flex-direction:column}} .lrn-call-side{{width:auto;border-left:0;border-top:1px solid rgba(127,127,127,.25)}} #lrn-call{{max-height:88vh}} }}
 .lrn-cal{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;max-width:420px}}
 .lrn-cal .dow{{font-size:.75em;opacity:.6;text-align:center;padding:2px 0}}
 .lrn-cal .day{{text-align:center;padding:6px 0;border-radius:8px;border:1px solid transparent}}
 .lrn-cal .day.dim{{opacity:.3}}
 .lrn-cal button.day{{border-color:rgba(127,127,127,.4);background:none;color:inherit;cursor:pointer}}
 .lrn-cal button.day.sel{{border-color:currentColor;font-weight:700}}
 .lrn-cal .dot{{display:block;margin:2px auto 0;width:6px;height:6px;border-radius:3px;background:currentColor;opacity:.5}}
 .lrn-cal .dot.present,.lrn-cal .dot.late{{background:#3c9;opacity:1}}
 .lrn-cal .dot.absent{{background:#e66;opacity:1}}
 /* The bell lives in the site header's icon cluster (learn.js mounts it
    next to the cart), so the dropdown is a fixed panel under that corner
    rather than a strip inside the portal. */
 #lrn-bell{{position:relative}}
 #lrn-bell .lrn-bell-dot{{position:absolute;top:0;right:-2px;background:var(--accent,currentColor);color:var(--bg,#fff);border-radius:999px;font-size:.62rem;line-height:1;padding:2px 5px;font-weight:700}}
 #lrn-noti{{position:fixed;top:74px;right:14px;z-index:210;width:min(400px,92vw)}}
 .lrn-noti-panel{{border:1px solid rgba(127,127,127,.35);border-radius:12px;padding:10px 14px;max-height:320px;overflow-y:auto;background:var(--bg,#111);box-shadow:0 12px 40px rgba(0,0,0,.4)}}
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
 .lrn-rtotals{{display:flex;gap:26px;flex-wrap:wrap;margin:2px 0 16px}}
 .lrn-rtotals b{{font-size:1.5em;display:block}}
 .lrn-rcourse{{border:1px solid rgba(127,127,127,.35);border-radius:12px;padding:14px 18px;margin-bottom:14px}}
 .lrn-rtable{{width:100%;border-collapse:collapse;margin-top:8px}}
 .lrn-rtable th,.lrn-rtable td{{text-align:left;padding:6px 8px;border-bottom:1px solid rgba(127,127,127,.2);font-size:.92em}}
 .lrn-rtable th{{opacity:.65;font-weight:600}}
 .pill-done{{border:1px solid #3c9;color:#3c9;border-radius:999px;padding:1px 9px;font-size:.75em;vertical-align:middle}}
 .lrn-doc{{max-width:720px;margin:0 auto;padding:12px 4px}}
 .lrn-doc .rule{{border-top:2px solid currentColor;margin:12px 0}}
 .lrn-cert{{border:6px double currentColor;border-radius:6px;padding:48px 36px;text-align:center;max-width:680px;margin:24px auto}}
 .lrn-cert h1{{font-size:2.1em;letter-spacing:.04em;margin:8px 0}}
 .lrn-cert .who{{font-size:1.7em;margin:18px 0 6px}}
 /* Printing a transcript or certificate: the document is the only thing
    on the paper — chrome, hero, fabs and the bell's dropdown all vanish. */
 @media print{{.lrn-tabs,.lrn-back,.no-print,header,footer,nav,.partner-head,#lrn-noti,.lrn-lookup,.buy-fab,.a11y-fab{{display:none !important}}
  body{{background:#fff !important;color:#000 !important}}}}
</style>
<script src="/rtc-mesh.js?v={v}"></script>
<script src="/learn.js?v={v}"></script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"Learning — {_brand}",
        description=f"{_brand} courses: lessons, quizzes and your progress."))
