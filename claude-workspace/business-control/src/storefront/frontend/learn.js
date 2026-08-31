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

  /* ── the tab bar: Courses | People ────────────────────────────────────── */
  let VIEW = "courses";
  function tabs() {
    return `<div class="lrn-tabs">
      <span class="lrn-tab ${VIEW === "courses" ? "on" : ""}" data-t="courses">Courses</span>
      <span class="lrn-tab ${VIEW === "people" ? "on" : ""}" data-t="people">People</span>
    </div>`;
  }
  function wireTabs() {
    root.querySelectorAll("[data-t]").forEach((el) => el.onclick = () => {
      VIEW = el.dataset.t;
      VIEW === "people" ? people() : home();
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
    const jc = document.getElementById("lrn-joincall");
    if (jc) jc.onclick = () => openCall(d.session.room, d.course.name);
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

  /* ── the call overlay ─────────────────────────────────────────────────── */
  let MESH = null;
  async function openCall(room, title) {
    if (MESH) { alert("You're already in a call — leave it first."); return; }
    if (!window.LinguaMesh) { alert("The call module didn't load."); return; }
    let cfg = { ice_servers: [] };
    try { cfg = await api("/api/learn/rtc/config"); } catch (err) {}
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
      <p class="lrn-meta" id="call-media" style="margin:4px 12px"></p>`;
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
    MESH = window.LinguaMesh.createMesh({
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
  home().catch((e) => {
    if (String(e.message).includes("sign in")) needSignIn();
    else root.innerHTML = `<p class="lrn-meta">${esc(e.message)}</p>`;
  });
})();
