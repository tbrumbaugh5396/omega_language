/* The learner's app at /learn: courses, lessons, quizzes, the live class —
 * and the community: finding people, connecting, talking, calling.
 *
 * The server holds every rule (visibility, the accept gate, grading,
 * attendance); this file only renders answers and posts intents. If a rule
 * seems enforced here, that is a courtesy copy — the real one is server-side.
 */
(function () {
  "use strict";
  const root = document.getElementById("learn-root");
  if (!root) return;

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const token = () => {
    try { return JSON.parse(localStorage.getItem("sf_support") || "{}").token; }
    catch { return null; }
  };
  async function api(path, body) {
    const r = await fetch(path, {
      method: body !== undefined ? "POST" : "GET",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + token() },
      body: body !== undefined ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch {}
      throw new Error(m);
    }
    return r.json();
  }

  async function rawUpload(path, blob) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": blob.type || "application/octet-stream",
                 Authorization: "Bearer " + token() },
      body: blob });
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch {}
      throw new Error(m);
    }
    return r.json();
  }
  const loadScript = (src) => new Promise((res, rej) => {
    if (document.querySelector(`script[src="${src}"]`)) return res();
    const s = document.createElement("script");
    s.src = src;
    s.onload = res;
    s.onerror = () => rej(new Error(src + " did not load"));
    document.head.appendChild(s);
  });

  /* ── the tab bar: Courses | People | Me ───────────────────────────────── */
  let VIEW = "courses";
  function tabs() {
    return `<div class="lrn-tabs">
      <span class="lrn-tab ${VIEW === "courses" ? "on" : ""}" data-t="courses">Courses</span>
      <span class="lrn-tab ${VIEW === "people" ? "on" : ""}" data-t="people">People</span>
      <span class="lrn-tab ${VIEW === "me" ? "on" : ""}" data-t="me">Me</span>
    </div>`;
  }
  function wireTabs() {
    root.querySelectorAll("[data-t]").forEach((el) => el.onclick = () => {
      VIEW = el.dataset.t;
      VIEW === "people" ? people() : VIEW === "me" ? meView() : home();
    });
  }

  /* ── signed-out: the application form ─────────────────────────────────── */
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
            placeholder="Spanish, French, ..."></label>
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
      } catch (err) { alert(err.message); }
    };
  }

  /* ── courses ──────────────────────────────────────────────────────────── */
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
        $${(c.product.price_cents / 100).toFixed(2)}</a>`
        : '<p class="lrn-meta">Ask us about joining this course.</p>'}</div>`;
    root.innerHTML = tabs()
      + (d.enrolled.length
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
    wireTabs();
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
        ${d.session.room
          ? ` <button class="lrn-btn" id="lrn-joincall">Join video</button>` : ""}
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
          <span class="lrn-meta">${q.attempt ? q.attempt.state : ""}</span></li>`).join("")}</ul>` : ""}
      <h3>Calendar</h3>
      <div id="lrn-cal-box"><p class="lrn-meta">Loading the calendar…</p></div>`;
    document.getElementById("lrn-back").onclick = home;
    calendar(cid).catch(() => {
      const box = document.getElementById("lrn-cal-box");
      if (box) box.innerHTML = "";
    });
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
    const jc = document.getElementById("lrn-joincall");
    if (jc) jc.onclick = () => openCall(d.session.room, d.course.name,
      (d.session.enrolled || 0) + 1);
    root.querySelectorAll("[data-l]").forEach((el) => el.onclick = (e) => {
      e.preventDefault(); lesson(+el.dataset.l, cid); });
    root.querySelectorAll("[data-q]").forEach((el) => el.onclick = (e) => {
      e.preventDefault(); quiz(+el.dataset.q, cid); });
  }

  async function lesson(lid, cid) {
    const d = await api("/api/learn/lessons/" + lid);
    const media = (m) => m.kind === "audio"
      ? `<audio controls preload="metadata" src="/media/${m.path}"></audio>`
      : m.kind === "video"
        ? `<video class="lrn-media" controls preload="metadata"
            src="/media/${m.path}"></video>`
        : `<img class="lrn-media" src="/media/${m.path}" alt="">`;
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; Course</span>
      <div class="lrn-lesson"><h2>${esc(d.title)}</h2>${d.html}</div>
      ${(d.materials || []).length ? `<h3>Listen and watch</h3>
        ${d.materials.map((m) => `<p>${media(m)}</p>`).join("")}` : ""}
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
        : q.kind === "speaking" || q.kind === "video"
          ? recorderWidget(q.id, q.kind === "video" ? "video" : "audio")
        : `<textarea rows="2" style="width:100%" name="q${q.id}"></textarea>`}
      </div>`).join("")}
      <button class="lrn-btn primary" id="lrn-submit">Submit answers</button>`;
    document.getElementById("lrn-back").onclick = () => course(cid);
    const saved = d.answered || {};
    wireRecorders(d.attempt.id, saved);
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
        // a recorded answer already went up through its own door
        if (q.kind === "speaking" || q.kind === "video") continue;
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

  /* ── people: the community ────────────────────────────────────────────── */
  async function people() {
    let d;
    try { d = await api("/api/learn/people"); }
    catch (err) {
      root.innerHTML = tabs() + `<p class="lrn-meta">${esc(err.message)}</p>`;
      wireTabs();
      return;
    }
    const row = (p, acts) => `<div class="lrn-person" data-p="${p.id}">
      <b>${esc(p.name)}</b>
      ${p.unread ? `<span class="lrn-unread">${p.unread}</span>` : ""}
      <span class="lrn-person-acts">${acts}</span></div>`;
    root.innerHTML = tabs() + `
      <div class="lrn-search"><input id="pp-q" placeholder="Find people by name"
        autocomplete="off"><div id="pp-results"></div></div>
      ${d.incoming.length ? `<h3>Want to connect (${d.incoming.length})</h3>
        ${d.incoming.map((p) => row(p,
          `<button class="lrn-btn sm" data-acc="${p.id}">Accept</button>
           <button class="lrn-btn sm" data-dec="${p.id}">Decline</button>`)).join("")}` : ""}
      <h3>Contacts (${d.accepted.length})</h3>
      ${d.accepted.map((p) => row(p,
        `<button class="lrn-btn sm" data-chat="${p.id}" data-name="${esc(p.name)}">Message</button>
         <button class="lrn-btn sm" data-call="${p.id}" data-name="${esc(p.name)}">Call</button>
         ${p.ghosted
           ? `<button class="lrn-btn sm" data-unghost="${p.id}">Unghost</button>`
           : `<button class="lrn-btn sm" data-ghost="${p.id}">Ghost</button>`}
         <button class="lrn-btn sm" data-block="${p.id}">Block</button>`)).join("")
        || "<p class='lrn-meta'>Nobody yet — find a classmate above. " +
           "Messaging opens once someone accepts you: that's the rule that " +
           "keeps this safe.</p>"}
      ${d.outgoing.length ? `<h3>Asked (${d.outgoing.length})</h3>
        ${d.outgoing.map((p) => row(p,
          `<span class="lrn-meta">waiting</span>
           <button class="lrn-btn sm" data-dec="${p.id}">Withdraw</button>`)).join("")}` : ""}
      ${d.blocked.length ? `<h3>Blocked (${d.blocked.length})</h3>
        ${d.blocked.map((p) => row(p,
          `<button class="lrn-btn sm" data-unblock="${p.id}">Unblock</button>`)).join("")}` : ""}
      <h3>Privacy</h3>
      <div class="lrn-prefs">
        <label>Who sees my name
          <select id="pf-name">
            ${["everyone", "initial", "class", "contacts", "nobody"].map((l) =>
              `<option value="${l}" ${d.prefs.privacy_name === l ? "selected" : ""}>${
              ({ everyone: "everyone", initial: "first name + initial",
                 class: "my classes only", contacts: "contacts only",
                 nobody: "nobody" })[l]}</option>`).join("")}</select></label>
        <label><input type="checkbox" id="pf-open" ${d.prefs.open_dm ? "checked" : ""}>
          Open DMs — people can message me before I accept them</label>
        <label><input type="checkbox" id="pf-ghost" ${d.prefs.invisible ? "checked" : ""}>
          Ghost mode — invisible to everyone, messaging paused both ways</label>
      </div>`;
    wireTabs();
    const savePrefs = async () => {
      await api("/api/learn/prefs", {
        privacy_name: document.getElementById("pf-name").value,
        open_dm: document.getElementById("pf-open").checked ? 1 : 0,
        invisible: document.getElementById("pf-ghost").checked ? 1 : 0 });
    };
    document.getElementById("pf-name").onchange = savePrefs;
    document.getElementById("pf-open").onchange = savePrefs;
    document.getElementById("pf-ghost").onchange = savePrefs;
    let timer = null;
    document.getElementById("pp-q").oninput = (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => searchPeople(e.target.value), 250);
    };
    const act = async (pid, path, body) => {
      try { await api(`/api/learn/people/${pid}/${path}`, body || {}); people(); }
      catch (err) { alert(err.message); }
    };
    root.querySelectorAll("[data-acc]").forEach((b) => b.onclick =
      () => act(b.dataset.acc, "respond", { accept: true }));
    root.querySelectorAll("[data-dec]").forEach((b) => b.onclick =
      () => act(b.dataset.dec, "respond", { accept: false }));
    root.querySelectorAll("[data-ghost]").forEach((b) => b.onclick =
      () => act(b.dataset.ghost, "ghost"));
    root.querySelectorAll("[data-unghost]").forEach((b) => b.onclick =
      () => act(b.dataset.unghost, "unghost"));
    root.querySelectorAll("[data-block]").forEach((b) => b.onclick = () => {
      if (confirm("Block them? Your connection is removed and neither of "
        + "you sees the other.")) act(b.dataset.block, "block");
    });
    root.querySelectorAll("[data-unblock]").forEach((b) => b.onclick =
      () => act(b.dataset.unblock, "unblock"));
    root.querySelectorAll("[data-chat]").forEach((b) => b.onclick =
      () => thread(+b.dataset.chat, b.dataset.name));
    root.querySelectorAll("[data-call]").forEach((b) => b.onclick =
      () => startDmCall(+b.dataset.call, b.dataset.name));
  }

  async function searchPeople(q) {
    const box = document.getElementById("pp-results");
    if (!box) return;
    if (!q || q.trim().length < 2) { box.innerHTML = ""; return; }
    const rows = await api("/api/learn/people/search?q=" + encodeURIComponent(q));
    box.innerHTML = rows.map((p) => `<div class="lrn-person">
      <b>${esc(p.name)}</b>
      <span class="lrn-person-acts">${
        p.contact === "accepted" ? '<span class="lrn-meta">connected</span>'
        : p.contact === "pending" ? (p.requested_by_me
          ? '<span class="lrn-meta">asked</span>'
          : `<button class="lrn-btn sm" data-sacc="${p.id}">Accept</button>`)
        : `<button class="lrn-btn sm" data-sreq="${p.id}">Connect</button>`}${
        p.open_dm && p.contact !== "accepted"
          ? ` <button class="lrn-btn sm" data-schat="${p.id}"
              data-name="${esc(p.name)}">Message</button>` : ""}
      </span></div>`).join("")
      || "<p class='lrn-meta'>Nobody by that name — or they've chosen not to be found.</p>";
    box.querySelectorAll("[data-sreq]").forEach((b) => b.onclick = async () => {
      try { await api(`/api/learn/people/${b.dataset.sreq}/request`, {}); searchPeople(q); }
      catch (err) { alert(err.message); }
    });
    box.querySelectorAll("[data-sacc]").forEach((b) => b.onclick = async () => {
      try { await api(`/api/learn/people/${b.dataset.sacc}/respond`,
        { accept: true }); people(); }
      catch (err) { alert(err.message); }
    });
    box.querySelectorAll("[data-schat]").forEach((b) => b.onclick =
      () => thread(+b.dataset.schat, b.dataset.name));
  }

  /* ── one conversation ─────────────────────────────────────────────────── */
  async function thread(pid, name) {
    let d;
    try { d = await api("/api/learn/thread/" + pid); }
    catch (err) { return alert(err.message); }
    const me = d.me;
    root.innerHTML = `<span class="lrn-back" id="lrn-back">&larr; People</span>
      <h2>${esc(name)}</h2>
      <div class="lrn-thread" id="th-box">${d.messages.map((m) => `
        <div class="lrn-msg ${m.from_id === me ? "mine" : ""}" data-m="${m.id}">
          ${m.kind === "call"
            ? `<i>video call${m.room ? "" : " ended"}</i>${m.room
              ? ` <button class="lrn-btn sm" data-mjoin="${esc(m.room)}">Join</button>` : ""}`
            : esc(m.body)}
          ${m.from_id !== me
            ? `<span class="lrn-msg-report" data-rep="${m.id}" title="report this message">!</span>` : ""}
        </div>`).join("") || "<p class='lrn-meta'>Say hello.</p>"}</div>
      <form id="th-send" style="display:flex;gap:8px;margin-top:10px">
        <input id="th-text" style="flex:1" maxlength="2000"
          placeholder="Write a message" autocomplete="off">
        <button class="lrn-btn primary" type="submit">Send</button>
        <button class="lrn-btn" type="button" id="th-call">Call</button>
      </form>
      <p class="lrn-meta">Private — staff can't read this. If something's
        wrong, the ! on a message hands that one message to the office.</p>`;
    document.getElementById("lrn-back").onclick = people;
    const box = document.getElementById("th-box");
    box.scrollTop = box.scrollHeight;
    document.getElementById("th-send").onsubmit = async (e) => {
      e.preventDefault();
      const t = document.getElementById("th-text");
      if (!t.value.trim()) return;
      try {
        await api("/api/learn/thread/" + pid, { body: t.value });
        t.value = "";
        thread(pid, name);
      } catch (err) { alert(err.message); }
    };
    document.getElementById("th-call").onclick = () => startDmCall(pid, name);
    root.querySelectorAll("[data-rep]").forEach((el) => el.onclick = async () => {
      const reason = prompt("What's wrong? The office reads every report, "
        + "and this message goes with it.");
      if (!reason) return;
      try {
        await api(`/api/learn/people/${pid}/report`,
          { reason, message_id: +el.dataset.rep });
        alert("Reported — the office has the message.");
      } catch (err) { alert(err.message); }
    });
    root.querySelectorAll("[data-mjoin]").forEach((b) => b.onclick =
      () => openCall(b.dataset.mjoin, name));
  }

  async function startDmCall(pid, name) {
    const room = "dm-" + Math.random().toString(16).slice(2, 10);
    try {
      await api("/api/learn/thread/" + pid,
        { body: "", kind: "call", room });
    } catch (err) { return alert(err.message); }
    openCall(room, name);
  }

  /* ── the calendar: a month grid of class sessions ─────────────────────── */
  // Pure date helpers ported from the source's lib/cal.js. Weeks start
  // Monday; days are keyed by LOCAL YYYY-MM-DD on purpose — a class taught
  // Tuesday evening must appear on Tuesday for the people who were in it,
  // not on Wednesday because UTC rolled over.
  const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const dayKey = (epochSeconds) => {
    const d = new Date(epochSeconds * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${
      String(d.getDate()).padStart(2, "0")}`;
  };
  function monthGrid(year, month0) {
    const first = new Date(year, month0, 1);
    const lead = (first.getDay() + 6) % 7;   // Monday=0; walk back to it
    let cursor = new Date(year, month0, 1 - lead);
    const weeks = [];
    while (weeks.length < 6) {
      const week = [];
      for (let i = 0; i < 7; i++) {
        week.push({
          day: cursor.getDate(),
          key: `${cursor.getFullYear()}-${
            String(cursor.getMonth() + 1).padStart(2, "0")}-${
            String(cursor.getDate()).padStart(2, "0")}`,
          inMonth: cursor.getMonth() === month0,
        });
        cursor = new Date(cursor.getTime() + 86400000);
        // DST: adding 24h across a fall-back day can land on the SAME date
        // at 23:00 and duplicate a cell. Normalise to midnight.
        cursor = new Date(cursor.getFullYear(), cursor.getMonth(),
          cursor.getDate());
      }
      weeks.push(week);
      if (cursor.getMonth() !== month0 && weeks.length >= 4) break;
    }
    return { year, month0, label: `${MONTHS[month0]} ${year}`, weeks };
  }
  const shiftMonth = (y, m0, delta) => {
    const d = new Date(y, m0 + delta, 1);
    return [d.getFullYear(), d.getMonth()];
  };

  async function calendar(cid) {
    const sessions = await api(`/api/learn/courses/${cid}/sessions`);
    const box = document.getElementById("lrn-cal-box");
    if (!box) return;
    if (!sessions.length) {
      box.innerHTML = "<p class='lrn-meta'>No classes held yet.</p>";
      return;
    }
    const marks = new Map();
    for (const s of sessions) {
      const k = dayKey(s.started_at);
      if (!marks.has(k)) marks.set(k, []);
      marks.get(k).push(s);
    }
    // Open on the month of the LATEST class, not "now": deterministic from
    // the data, and it is the month a person almost always wants.
    const last = new Date(sessions[sessions.length - 1].started_at * 1000);
    let year = last.getFullYear(), month0 = last.getMonth(), sel = null;

    function drawCal() {
      const grid = monthGrid(year, month0);
      box.innerHTML = `
        <p><button class="lrn-btn sm" id="cal-prev">&larr;</button>
          <b style="margin:0 10px">${grid.label}</b>
          <button class="lrn-btn sm" id="cal-next">&rarr;</button></p>
        <div class="lrn-cal">
          ${DOW.map((d) => `<span class="dow">${d}</span>`).join("")}
          ${grid.weeks.flat().map((c) => {
            const here = marks.get(c.key) || [];
            if (!here.length) {
              return `<div class="day ${c.inMonth ? "" : "dim"}">${c.day}</div>`;
            }
            const mine = here.length === 1 ? here[0].mine : null;
            return `<button class="day ${sel === c.key ? "sel" : ""}"
              data-day="${c.key}" title="${here.length} class(es)">${c.day}
              <span class="dot ${esc(mine || "")}"></span></button>`;
          }).join("")}
        </div>
        <div id="cal-detail"></div>`;
      document.getElementById("cal-prev").onclick = () => {
        [year, month0] = shiftMonth(year, month0, -1); sel = null; drawCal();
      };
      document.getElementById("cal-next").onclick = () => {
        [year, month0] = shiftMonth(year, month0, 1); sel = null; drawCal();
      };
      box.querySelectorAll("[data-day]").forEach((b) => b.onclick = () => {
        sel = b.dataset.day; drawCal(); dayDetail(marks.get(sel) || []);
      });
      if (sel) dayDetail(marks.get(sel) || []);
    }

    async function dayDetail(list) {
      const det = document.getElementById("cal-detail");
      if (!det) return;
      const fmt = (t) => new Date(t * 1000).toLocaleTimeString([],
        { hour: "2-digit", minute: "2-digit" });
      det.innerHTML = list.map((s) => `<div class="lrn-q">
        <b>${fmt(s.started_at)}${s.ended_at ? " to " + fmt(s.ended_at) : ""}</b>
        ${s.lesson_title ? " — " + esc(s.lesson_title) : ""}
        <span class="lrn-meta">${s.status}${s.mine ? " · you were " + esc(s.mine) : ""}
          · ${s.attended} attended</span>
        <div data-recs="${s.id}">${s.recordings
          ? "<p class='lrn-meta'>Loading recordings…</p>" : ""}</div>
      </div>`).join("");
      for (const s of list) {
        if (!s.recordings) continue;
        try {
          const recs = await api(`/api/learn/sessions/${s.id}/recordings`);
          const slot = det.querySelector(`[data-recs="${s.id}"]`);
          if (slot) slot.innerHTML = recs.map((m) =>
            m.kind === "audio"
              ? `<audio controls preload="metadata" src="/media/${m.path}"></audio>`
              : `<video class="lrn-media" controls preload="metadata"
                  src="/media/${m.path}"></video>`).join("");
        } catch (e) { /* the class may predate recordings */ }
      }
    }
    drawCal();
  }

  /* ── Me: the ID card, my loans, my data ───────────────────────────────── */
  async function meView() {
    let card = null, loans = [];
    try { card = await api("/api/learn/me/card"); } catch (e) {}
    try { loans = await api("/api/learn/loans"); } catch (e) {}
    const day = (t) => t ? new Date(t * 1000).toLocaleDateString() : "";
    root.innerHTML = tabs() + `
      ${card ? `<h3>My ID card</h3>
      <div class="lrn-idcard">
        <img src="/api/qr.svg?data=${encodeURIComponent(card.payload)}"
          alt="my ID code">
        <p class="lrn-meta">Show this to check in at class, or let a
          classmate scan it to connect — handing over your code is the
          handshake.</p>
        <p class="no-print">
          <button class="lrn-btn sm" id="me-print">Print</button>
          <button class="lrn-btn sm" id="me-reissue">Reissue</button></p>
        <p class="lrn-meta no-print">Reissuing mints a new code and the old
          card stops working — do it if a card is lost.</p>
      </div>` : ""}
      <h3>My library loans</h3>
      ${loans.length ? `<ul class="lrn-list">${loans.map((l) => `<li>
          <span class="${l.returned_at ? "lrn-done" : ""}">${esc(l.item_name)}</span>
          <span class="lrn-meta">${l.returned_at
            ? "returned " + day(l.returned_at)
            : l.due_at ? (l.overdue ? "overdue since " : "due ") + day(l.due_at)
            : "out"}</span></li>`).join("")}</ul>`
        : "<p class='lrn-meta'>Nothing borrowed yet — ask at the desk.</p>"}
      <h3>My data</h3>
      <p class="lrn-meta">Everything held about you, as a file you can keep.
        Messages are not included: a conversation belongs to two people.</p>
      <button class="lrn-btn" id="me-export">Download my data</button>`;
    wireTabs();
    const pr = document.getElementById("me-print");
    if (pr) pr.onclick = () => window.print();
    const re = document.getElementById("me-reissue");
    if (re) re.onclick = async () => {
      try { await api("/api/learn/me/qr/reissue", {}); meView(); }
      catch (err) { alert(err.message); }
    };
    document.getElementById("me-export").onclick = async () => {
      try {
        const r = await fetch("/api/learn/me/export",
          { headers: { Authorization: "Bearer " + token() } });
        if (!r.ok) throw new Error("export failed");
        const blob = await r.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "my-data.json";
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (err) { alert(err.message); }
    };
  }

  /* ── the scan handshake (deep link from a card's URL) ─────────────────── */
  async function handleScan(codeText) {
    let p;
    try { p = await api("/api/learn/people/scan", { payload: codeText }); }
    catch (err) { return alert(err.message); }
    if (p.contact === "self") return alert("That is your own card.");
    VIEW = "people";
    if (p.contact === "accepted") {
      thread(p.id, p.name);
    } else if (p.contact === "pending" && !p.requested_by_me) {
      if (window.confirm(`${p.name} already asked to connect — accept?`)) {
        await api(`/api/learn/people/${p.id}/respond`, { accept: true });
      }
      people();
    } else if (p.contact === "none") {
      await api(`/api/learn/people/${p.id}/request`, {});
      alert(`Sent ${p.name} a connection request — scanning their card is`
        + " the handshake, they confirm on their side.");
      people();
    } else {
      people();
    }
  }

  /* ── voice & translation: the lookup panel + browser speech ───────────── */
  // Dictation and TTS never touch the server: SpeechRecognition in,
  // speechSynthesis out. One utterance per press, deliberately — the mic
  // light is off except while it means something.
  const recognizer = () =>
    (window.SpeechRecognition || window.webkitSpeechRecognition) || null;
  const canListen = () => !!recognizer();
  const canSpeak = () => !!(window.speechSynthesis
    && window.SpeechSynthesisUtterance);
  let _stopListen = null;
  function listen({ lang, onText, onEnd, onError }) {
    const R = recognizer();
    if (!R) { onError && onError("no speech recognition here"); return null; }
    const r = new R();
    if (lang) r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (e) => {
      const t = e.results[0] && e.results[0][0]
        ? e.results[0][0].transcript : "";
      if (t) onText && onText(t);
    };
    r.onerror = (e) => {
      const m = ["not-allowed", "service-not-allowed"].includes(e.error)
        ? "the browser is blocking the microphone — allow it in the address bar"
        : "could not hear that";
      onError && onError(m);
    };
    r.onend = () => { onEnd && onEnd(); };
    r.start();
    return () => { try { r.abort(); } catch (e) {} };
  }
  function speak(text, lang) {
    if (!canSpeak() || !text) return;
    window.speechSynthesis.cancel();     // two voices must never overlap
    const u = new SpeechSynthesisUtterance(text);
    if (lang) u.lang = lang;             // bare code: the browser picks a voice
    u.rate = 0.95;                       // a touch under full speed: learners
    window.speechSynthesis.speak(u);
  }

  let VOICE = null;                      // providers payload, or null = cap off
  async function probeVoice() {
    try { VOICE = await api("/api/learn/voice/providers"); }
    catch (e) { VOICE = null; return; }
    mountLookup();
  }
  function mountLookup() {
    if (!VOICE || document.getElementById("lrn-lookup")) return;
    const wrap = document.createElement("div");
    wrap.id = "lrn-lookup";
    wrap.className = "lrn-lookup";
    document.body.appendChild(wrap);
    let open = false, mode = "translate", from = "en", to = "es";
    const langs = Object.entries(VOICE.languages || { en: "English" });
    const draw = () => {
      if (!open) {
        wrap.innerHTML = `<button class="lrn-btn" id="lk-open">Look up…</button>`;
        wrap.querySelector("#lk-open").onclick = () => { open = true; draw(); };
        return;
      }
      wrap.innerHTML = `<div class="panel">
        <p style="margin:0 0 8px;display:flex;gap:6px;align-items:center">
          <b style="flex:1">Look up</b>
          <button class="lrn-btn sm ${mode === "translate" ? "primary" : ""}"
            id="lk-tr">Translate</button>
          <button class="lrn-btn sm ${mode === "thesaurus" ? "primary" : ""}"
            id="lk-th">Synonyms</button>
          <button class="lrn-btn sm" id="lk-close">&times;</button></p>
        <p style="display:flex;gap:6px;margin:0 0 8px">
          <input id="lk-q" style="flex:1" placeholder="${mode === "translate"
            ? "word or phrase" : "an English word"}" autocomplete="off">
          ${canListen()
            ? `<button class="lrn-btn sm" id="lk-mic" title="dictate">Mic</button>`
            : ""}</p>
        ${mode === "translate" ? `<p style="display:flex;gap:6px;margin:0 0 8px">
          <select id="lk-from">${langs.map(([c, n]) =>
            `<option value="${c}" ${c === from ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
          <span style="align-self:center">to</span>
          <select id="lk-to">${langs.map(([c, n]) =>
            `<option value="${c}" ${c === to ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></p>` : ""}
        <div id="lk-out" class="lrn-meta"></div>
      </div>`;
      wrap.querySelector("#lk-close").onclick = () => { open = false; draw(); };
      wrap.querySelector("#lk-tr").onclick = () => { mode = "translate"; draw(); };
      wrap.querySelector("#lk-th").onclick = () => { mode = "thesaurus"; draw(); };
      const q = wrap.querySelector("#lk-q");
      const go = async () => {
        const text = q.value.trim();
        if (!text) return;
        const out = wrap.querySelector("#lk-out");
        out.textContent = "…";
        try {
          let res;
          if (mode === "translate") {
            from = wrap.querySelector("#lk-from").value;
            to = wrap.querySelector("#lk-to").value;
            res = await api(`/api/learn/voice/translate?q=${
              encodeURIComponent(text)}&source=${from}&target=${to}`);
            out.innerHTML = res.found
              ? `<b style="font-size:1.2em">${esc(res.text)}</b>
                 ${canSpeak() ? `<button class="lrn-btn sm" id="lk-say"
                   data-value="${esc(res.text)}" data-lang="${esc(to)}">Say it</button>` : ""}
                 <br><span>via ${esc(res.via)}</span>`
              : esc(res.reason || "not found");
          } else {
            res = await api(`/api/learn/voice/thesaurus?q=${
              encodeURIComponent(text)}`);
            out.innerHTML = res.found
              ? `<b>${(res.synonyms || []).map(esc).join(", ")}</b>
                 <br><span>via ${esc(res.via)}</span>`
              : esc(res.reason || "not found");
          }
          const say = wrap.querySelector("#lk-say");
          if (say) say.onclick = () =>
            speak(say.dataset.value, say.dataset.lang);
        } catch (err) { out.textContent = err.message; }
      };
      q.onkeydown = (e) => { if (e.key === "Enter") go(); };
      q.onchange = go;
      const mic = wrap.querySelector("#lk-mic");
      if (mic) mic.onclick = () => {
        if (_stopListen) { _stopListen(); _stopListen = null;
          mic.textContent = "Mic"; return; }
        mic.textContent = "Listening…";
        _stopListen = listen({
          lang: mode === "translate" ? from : "en",
          onText: (t) => { q.value = t; go(); },
          onEnd: () => { _stopListen = null; mic.textContent = "Mic"; },
          onError: (m) => { alert(m); },
        });
      };
      q.focus();
    };
    draw();
  }

  /* ── the recorder widget (speaking / video answers) ───────────────────── */
  const RECORDERS = new Map();   // question_id -> recorder (module-scoped:
                                 // live handles must survive re-renders)
  function recorderWidget(qid, kind) {
    return `<div class="lrn-rec" data-rw="${qid}" data-kind="${kind}">
      <button class="lrn-btn sm" data-recbtn="${qid}">Record ${kind === "video"
        ? "video" : "voice"} answer</button>
      <span class="state" data-recstate="${qid}"></span>
      <span data-recplay="${qid}"></span>
      <button class="lrn-btn sm" data-recuse="${qid}" hidden>Use this take</button>
    </div>`;
  }
  async function wireRecorders(attemptId, answered) {
    const boxes = root.querySelectorAll("[data-rw]");
    if (!boxes.length) return;
    try { await loadScript("/rtc-compose.js"); }
    catch (e) { return; }
    boxes.forEach((box) => {
      const qid = +box.dataset.rw;
      const kind = box.dataset.kind;
      const btn = box.querySelector(`[data-recbtn="${qid}"]`);
      const state = box.querySelector(`[data-recstate="${qid}"]`);
      const play = box.querySelector(`[data-recplay="${qid}"]`);
      const use = box.querySelector(`[data-recuse="${qid}"]`);
      if ((answered[qid] || {}).material_id) {
        state.textContent = "answer recorded — record again to replace it";
      }
      if (!window.LinguaCompose.recSupported()) {
        state.textContent = "this browser cannot record";
        btn.disabled = true;
        return;
      }
      btn.onclick = async () => {
        let rec = RECORDERS.get(qid);
        if (rec && rec.seconds && btn.dataset.on === "1") {
          await rec.stop();
          btn.dataset.on = "";
          btn.textContent = `Record ${kind === "video" ? "video" : "voice"} answer`;
          if (rec.url) {
            play.innerHTML = kind === "video"
              ? `<video class="lrn-media" controls src="${rec.url}"></video>`
              : `<audio controls src="${rec.url}"></audio>`;
            use.hidden = false;
          }
          return;
        }
        rec = window.LinguaCompose.createRecorder({
          kind,
          maxSeconds: 300,
          onTick: (s) => { state.textContent =
            "recording " + window.LinguaCompose.fmtSecs(s); },
          onError: (m) => { state.textContent = m; },
        });
        RECORDERS.set(qid, rec);
        try {
          await rec.start();
          btn.dataset.on = "1";
          btn.textContent = "Stop";
          play.innerHTML = "";
          use.hidden = true;
        } catch (err) { state.textContent = err.message; }
      };
      use.onclick = async () => {
        const rec = RECORDERS.get(qid);
        if (!rec || !rec.blob) return;
        use.disabled = true;
        state.textContent = "uploading…";
        try {
          await rawUpload(`/api/learn/attempts/${attemptId}/recording`
            + `?question_id=${qid}`, rec.blob);
          state.textContent = "answer recorded";
          use.hidden = true;
          rec.discard();
          RECORDERS.delete(qid);
        } catch (err) { state.textContent = err.message; }
        use.disabled = false;
      };
    });
  }

  /* ── the call overlay ─────────────────────────────────────────────────── */
  let MESH = null;
  async function openCall(room, title, expected) {
    if (MESH) { alert("You're already in a call — leave it first."); return; }
    if (!window.LinguaMesh) { alert("The call module didn't load."); return; }
    let cfg = { ice_servers: [] };
    try { cfg = await api("/api/learn/rtc/config"); } catch (err) {}
    // How many encodes this DEVICE can stand is the device's own property,
    // so it joins the server's config here rather than being guessed there.
    cfg.hardware_concurrency = navigator.hardwareConcurrency || 0;
    // The enrolled roster size decides the transport on the FIRST join —
    // a full class must not start as a mesh and thrash mid-call.
    let factory = (o) => window.LinguaMesh.createMesh(o);
    let note = "";
    try {
      await loadScript("/rtc-sfu.js");
      const transport = window.LinguaSfu.chooseTransport(cfg, expected || 2);
      note = window.LinguaSfu.capacityNote(transport, cfg, expected || 2);
      if (transport === "sfu") {
        factory = (o) => window.LinguaSfu.createSfu({ ...o, config: cfg });
      }
    } catch (e) { /* no sfu module: the mesh carries on */ }
    const ov = document.createElement("div");
    ov.id = "lrn-call";
    ov.innerHTML = `<div class="lrn-call-head">
        <b>${esc(title || "Video call")}</b>
        <span class="lrn-meta" id="call-state">connecting…</span>
        <span style="flex:1"></span>
        <button class="lrn-btn sm" id="call-mic">Mute</button>
        <button class="lrn-btn sm" id="call-cam">Camera off</button>
        <button class="lrn-btn sm primary" id="call-leave">Leave</button>
      </div>
      <div class="lrn-call-grid" id="call-grid"></div>
      <p class="lrn-meta" id="call-media" style="margin:4px 12px"></p>
      ${note ? `<p class="lrn-meta" style="margin:0 12px 8px">${esc(note)}</p>` : ""}`;
    document.body.appendChild(ov);
    const grid = ov.querySelector("#call-grid");
    const tile = (id) => {
      let v = grid.querySelector(`[data-peer="${id}"]`);
      if (!v) {
        v = document.createElement("video");
        v.dataset.peer = id;
        v.autoplay = true;
        v.playsInline = true;
        if (id === "me") v.muted = true;
        grid.appendChild(v);
      }
      return v;
    };
    MESH = factory({
      room,
      api,
      iceServers: cfg.ice_servers,
      onLocal: (s) => { tile("me").srcObject = s; },
      onRemote: (id, s) => { tile(id).srcObject = s; },
      onLeave: (id) => {
        const v = grid.querySelector(`[data-peer="${id}"]`);
        if (v) v.remove();
      },
      onState: (m) => {
        const el = ov.querySelector("#call-state");
        if (el) el.textContent = m;
      },
      onMedia: (got) => {
        const el = ov.querySelector("#call-media");
        if (el) el.textContent = got.detail || "";
      },
      onError: () => {},
    });
    const close = () => {
      if (MESH) MESH.leave();
      MESH = null;
      ov.remove();
    };
    ov.querySelector("#call-leave").onclick = close;
    ov.querySelector("#call-mic").onclick = (e) => {
      const on = MESH && MESH.toggle("audio");
      e.target.textContent = on ? "Mute" : "Unmute";
    };
    ov.querySelector("#call-cam").onclick = (e) => {
      const on = MESH && MESH.toggle("video");
      e.target.textContent = on ? "Camera off" : "Camera on";
    };
    try { await MESH.join(); }
    catch (err) { alert(err.message); close(); }
  }

  /* ── boot ─────────────────────────────────────────────────────────────── */
  if (!token()) { needSignIn(); return; }
  // A scanned card's URL lands here as /learn?scan=<uuid> (the iPhone
  // path: the Camera app opened the deep link). Finish the handshake once
  // we know who is holding the phone.
  const scanned = new URLSearchParams(location.search).get("scan");
  if (scanned) {
    try { history.replaceState({}, "", "/learn"); } catch (e) {}
  }
  home().then(() => {
    probeVoice();
    if (scanned) handleScan(scanned);
  }).catch((e) => {
    if (String(e.message).includes("sign in")) needSignIn();
    else root.innerHTML = `<p class="lrn-meta">${esc(e.message)}</p>`;
  });
})();
