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
        session = {"id": open_s.id, "started_at": open_s.started_at,
                   "my_status": mine["status"] if mine else None}
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
    _brand = brand_name(con)
    body = """
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
 .lrn-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
 .lrn-card{border:1px solid rgba(127,127,127,.25);border-radius:12px;padding:16px;cursor:pointer}
 .lrn-card h3{margin:0 0 6px}
 .lrn-bar{height:6px;border-radius:3px;background:rgba(127,127,127,.2);margin-top:10px;overflow:hidden}
 .lrn-bar i{display:block;height:100%;background:currentColor}
 .lrn-list{list-style:none;padding:0;margin:12px 0}
 .lrn-list li{display:flex;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(127,127,127,.15)}
 .lrn-done{opacity:.6;text-decoration:line-through}
 .lrn-q{border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:14px;margin:10px 0}
 .lrn-q label{display:block;margin:6px 0;cursor:pointer}
 .lrn-back{margin-bottom:14px;display:inline-block;cursor:pointer;text-decoration:underline}
 .lrn-btn{padding:8px 16px;border-radius:8px;border:1px solid currentColor;background:none;color:inherit;cursor:pointer}
 .lrn-btn.primary{font-weight:700}
 .lrn-meta{opacity:.7;font-size:.9em}
 .lrn-lesson h2,.lrn-lesson h3,.lrn-lesson h4{margin-top:1.2em}
 .lrn-lesson pre{background:rgba(127,127,127,.12);padding:12px;border-radius:8px;overflow-x:auto}
 .lrn-live{border:1px solid currentColor;border-radius:10px;padding:12px 16px;margin:12px 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 .lrn-badges{display:flex;gap:8px;flex-wrap:wrap}
 .lrn-badge{border:1px solid rgba(127,127,127,.4);border-radius:999px;padding:4px 12px;font-size:.9em}
</style>
<script>
(() => {
  const root = document.getElementById("learn-root");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const token = () => {
    try { return JSON.parse(localStorage.getItem("sf_support")||"{}").token; }
    catch { return null; }
  };
  async function api(path, body) {
    const r = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + token() },
      body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch {}
      throw new Error(m);
    }
    return r.json();
  }
  async function needSignIn() {
    let programs = [];
    try { programs = await api("/api/learn/programs"); } catch {}
    root.innerHTML = `<p>Already a student? Sign in with the
      <b>account</b> door on <a href="/">the shop</a> (the same sign-in you
      order with), then come back here.</p>
      <h2 style="margin-top:28px">Apply to join</h2>
      <p class="lrn-meta">Applying doesn't create an account — we review
        every application, and approval is what opens your seat.</p>
      <form id="lrn-apply" style="max-width:480px;display:grid;gap:10px">
        <label>Your name<br><input name="name" required style="width:100%"></label>
        <label>Email<br><input name="email" type="email" required style="width:100%"></label>
        <label>Phone <span class="lrn-meta">(optional)</span><br>
          <input name="phone" style="width:100%"></label>
        <label>What do you want to learn?<br>
          <input name="language" required style="width:100%"
            placeholder="Spanish, French, …"></label>
        ${programs.length ? `<label>Course<br>
          <select name="course_id" style="width:100%">
            <option value="">Let us suggest one</option>
            ${programs.map((p) => `<option value="${p.id}">${esc(p.name)}${
              p.language ? " — " + esc(p.language) : ""}${
              p.level ? " (" + esc(p.level) + ")" : ""}</option>`).join("")}
          </select></label>` : ""}
        <label>Your goals <span class="lrn-meta">(optional)</span><br>
          <textarea name="goals" rows="3" style="width:100%"></textarea></label>
        <button class="lrn-btn primary" type="submit">Apply</button>
      </form>`;
    document.getElementById("lrn-apply").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        await api("/api/learn/register", {
          name: f.name.value, email: f.email.value, phone: f.phone.value,
          language: f.language.value, goals: f.goals.value,
          course_id: f.course_id && f.course_id.value
            ? +f.course_id.value : null });
        root.innerHTML = `<h2>Application received</h2>
          <p>Thank you — we read every application. Once it's approved
          you'll have an account and a seat, and this page becomes your
          classroom.</p>`;
      } catch (err) {
        alert(err.message);
      }
    };
  }
  async function home() {
    const d = await api("/api/learn/courses");
    const card = (c) => `<div class="lrn-card" data-c="${c.id}">
      <h3>${esc(c.name)}</h3>
      <p class="lrn-meta">${esc([c.language, c.level].filter(Boolean).join(" · "))}${
        c.teacher ? " · " + esc(c.teacher) : ""}</p>
      ${c.progress ? `<div class="lrn-bar"><i style="width:${c.progress.percent}%"></i></div>
        <p class="lrn-meta">${c.progress.lessons_done}/${c.progress.lessons_total} lessons ·
         ${c.progress.quizzes_passed}/${c.progress.quizzes_total} quizzes · ${c.progress.percent}%</p>` : ""}
      </div>`;
    const offer = (c) => `<div class="lrn-card" style="cursor:default">
      <h3>${esc(c.name)}</h3>
      <p class="lrn-meta">${esc([c.language, c.level].filter(Boolean).join(" · "))}</p>
      ${c.blurb ? `<p>${esc(c.blurb)}</p>` : ""}
      ${c.product ? `<a class="lrn-btn" href="/product/${c.product.id}">Get this course —
        $${(c.product.price_cents/100).toFixed(2)}</a>`
        : '<p class="lrn-meta">Ask us about joining this course.</p>'}</div>`;
    root.innerHTML = (d.enrolled.length
        ? `<div class="lrn-grid">${d.enrolled.map(card).join("")}</div>`
        : "<p>You aren't enrolled in a course yet.</p>")
      + (d.achievements && d.achievements.length
        ? `<h2 style="margin-top:28px">Achievements</h2>
           <div class="lrn-badges">${d.achievements.map((a) =>
             `<span class="lrn-badge" title="you ${esc(a.what)}">${
               esc(a.name)}</span>`).join("")}</div>` : "")
      + (d.available.length
        ? `<h2 style="margin-top:28px">More courses</h2>
           <div class="lrn-grid">${d.available.map(offer).join("")}</div>` : "");
    root.querySelectorAll("[data-c]").forEach((el) =>
      el.onclick = () => course(+el.dataset.c));
  }
  async function course(cid) {
    const d = await api("/api/learn/courses/" + cid);
    const att = d.attendance || {};
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; My courses</span>
      <h2>${esc(d.course.name)}</h2>
      ${d.session ? `<div class="lrn-live">
        <b>Class is in session.</b>
        ${d.session.my_status
          ? ` You're checked in — ${esc(d.session.my_status)}.`
          : ` <button class="lrn-btn primary" id="lrn-here">I'm here</button>`}
        </div>` : ""}
      <div class="lrn-bar"><i style="width:${d.progress.percent}%"></i></div>
      <p class="lrn-meta">${d.progress.lessons_done}/${d.progress.lessons_total} lessons done ·
        ${d.progress.quizzes_passed}/${d.progress.quizzes_total} quizzes passed${
        att.classes_held ? ` · attended ${att.attended}/${att.classes_held} classes` : ""}</p>
      <h3>Lessons</h3>
      <ul class="lrn-list">${d.lessons.map((l) =>
        `<li><a href="#" data-l="${l.id}" class="${l.done ? "lrn-done" : ""}">${
          esc(l.title)}</a>${l.done ? " ✓" : ""}</li>`).join("")
        || "<li class='lrn-meta'>No lessons published yet.</li>"}</ul>
      ${d.quizzes.length ? `<h3>Quizzes</h3>
        <ul class="lrn-list">${d.quizzes.map((q) =>
        `<li><a href="#" data-q="${q.id}">${esc(q.title)}</a>
          <span class="lrn-meta">${q.attempt ? q.attempt.state : ""}</span></li>`).join("")}</ul>` : ""}`;
    document.getElementById("lrn-back").onclick = home;
    const here = document.getElementById("lrn-here");
    if (here) here.onclick = async () => {
      try {
        const r = await api(`/api/learn/sessions/${d.session.id}/checkin`, {});
        alert("Checked in — " + r.status
          + (r.new_achievements.length
            ? ". Achievement: " + r.new_achievements[0].name : ""));
        course(cid);
      } catch (err) { alert(err.message); }
    };
    root.querySelectorAll("[data-l]").forEach((el) => el.onclick = (e) => {
      e.preventDefault(); lesson(+el.dataset.l, cid); });
    root.querySelectorAll("[data-q]").forEach((el) => el.onclick = (e) => {
      e.preventDefault(); quiz(+el.dataset.q, cid); });
  }
  async function lesson(lid, cid) {
    const d = await api("/api/learn/lessons/" + lid);
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; Course</span>
      <div class="lrn-lesson"><h2>${esc(d.title)}</h2>${d.html}</div>
      ${d.done ? '<p class="lrn-meta">Done ✓</p>'
        : '<button class="lrn-btn primary" id="lrn-done">Mark as done</button>'}`;
    document.getElementById("lrn-back").onclick = () => course(cid);
    const b = document.getElementById("lrn-done");
    if (b) b.onclick = async () => {
      await api("/api/learn/lessons/" + lid + "/done", {});
      course(cid);
    };
  }
  async function quiz(qid, cid) {
    const d = await api("/api/learn/quizzes/" + qid + "/start", {});
    if (d.attempt.state !== "open") { return result(d.attempt.id, cid); }
    const qs = d.quiz.questions;
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; Course</span>
      <h2>${esc(d.quiz.title)}</h2>
      ${d.quiz.intro ? `<p>${esc(d.quiz.intro)}</p>` : ""}
      ${qs.map((q, i) => `<div class="lrn-q" data-qq="${q.id}">
        <b>${i + 1}. ${esc(q.prompt)}</b>
        <span class="lrn-meta"> (${q.points} pt${q.points === 1 ? "" : "s"})</span>
        ${q.kind === "choice" ? q.choices.map((c, j) =>
          `<label><input type="radio" name="q${q.id}" value="${j}"> ${esc(c)}</label>`).join("")
        : q.kind === "multi" ? q.choices.map((c, j) =>
          `<label><input type="checkbox" name="q${q.id}" value="${j}"> ${esc(c)}</label>`).join("")
        : `<textarea rows="2" style="width:100%" name="q${q.id}"></textarea>`}
      </div>`).join("")}
      <button class="lrn-btn primary" id="lrn-submit">Submit answers</button>`;
    document.getElementById("lrn-back").onclick = () => course(cid);
    const saved = d.answered || {};
    qs.forEach((q) => {
      const box = root.querySelector(`[data-qq="${q.id}"]`);
      const prev = saved[q.id];
      if (prev) {
        box.querySelectorAll("input").forEach((el) => {
          el.checked = (prev.chosen || []).includes(+el.value); });
        const t = box.querySelector("textarea");
        if (t) t.value = prev.text || "";
      }
    });
    document.getElementById("lrn-submit").onclick = async () => {
      for (const q of qs) {
        const box = root.querySelector(`[data-qq="${q.id}"]`);
        const chosen = [...box.querySelectorAll("input:checked")]
          .map((el) => +el.value);
        const t = box.querySelector("textarea");
        await api(`/api/learn/attempts/${d.attempt.id}/answer`,
          { question_id: q.id, chosen, text: t ? t.value : "" });
      }
      const res = await api(`/api/learn/attempts/${d.attempt.id}/submit`, {});
      showResult(res, cid);
    };
  }
  async function result(aid, cid) {
    showResult(await api("/api/learn/attempts/" + aid), cid);
  }
  function showResult(res, cid) {
    const g = res.grade;
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; Course</span>
      <h2>${esc(res.quiz.title)}</h2>
      ${g.is_final
        ? `<p><b>${g.percent}%</b> — ${g.earned}/${g.total} points ·
            ${g.passed ? "passed" : "not passed (pass mark " + g.pass_mark + "%)"}</p>`
        : `<p>${esc(g.message)}</p>
           <p class="lrn-meta">Your score appears once a teacher has marked
            every answer — we never show a provisional number.</p>`}`;
    document.getElementById("lrn-back").onclick = () => course(cid);
  }
  if (!token()) return needSignIn();
  home().catch((e) => {
    if (String(e.message).includes("sign in")) needSignIn();
    else root.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
  });
})();
</script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"Learning — {_brand}",
        description=f"{_brand} courses: lessons, quizzes and your progress."))
