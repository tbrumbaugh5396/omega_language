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

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from erp.backend import classroom as CR
from erp.backend import community as CM
from erp.backend import learning as L
from . import sections as sect
from .api import current_customer, get_con, rate_limit, render_shell
from .partners import _require_cap, brand_name

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
                   "room": room}
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
            "position": lesson["position"], "done": done}


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
    answered = {r.question_id: {"chosen": r.chosen, "text": r.text}
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
</style>
<script src="/rtc-mesh.js?v={v}"></script>
<script src="/learn.js?v={v}"></script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"Learning — {_brand}",
        description=f"{_brand} courses: lessons, quizzes and your progress."))
