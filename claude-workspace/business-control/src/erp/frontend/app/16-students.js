// ---------- the student's page ----------
/* Click a student anywhere — the customer book, a class's people — and
   this is what opens: who they are (the profile the office keeps and
   corrects), where they stand (attendance, scores, progress, per course),
   what they have earned, and everything that happened to them in order.
   The numbers are derived on read from the tables that recorded them; the
   only thing typed here is the profile and the staff log. */
const STU_LONG = ["education", "goals", "needs", "notes", "address"];

async function studentPage(uid, back) {
  if (location.hash !== `#/customers/${uid}`)
    history.pushState(null, "", `#/customers/${uid}`);
  let d;
  try { d = await api(`/api/students/${uid}`); }
  catch (err) { toast(err.message); return; }
  const st = d.student, p = d.profile, s = d.summary;
  const label = (k) => { const t = k.replace(/_/g, " "); return t[0].toUpperCase() + t.slice(1); };
  const stat = (n, v, sub) => `<div class="stu-stat"><b>${v == null || v === ""
    ? "—" : v}</b><span class="dim">${n}</span>${sub
    ? `<span class="dim stu-sub">${sub}</span>` : ""}</div>`;
  const field = (k) => STU_LONG.includes(k)
    ? `<div class="wide"><label>${label(k)}</label>
        <textarea data-pf="${k}" rows="${k === "education" ? 4 : 2}">${esc(p[k])}</textarea></div>`
    : `<div><label>${label(k)}${k === "birth_date" && p.age != null
        ? ` <span class="dim">· ${p.age} years old</span>` : ""}</label>
        <input data-pf="${k}" value="${esc(p[k])}"${k === "birth_date"
          ? ' type="date"' : k === "phone" ? ' type="tel"' : ""}></div>`;
  const extras = Object.entries(p.extra || {});
  const kindPill = (k) => {
    const base = k.startsWith("log:") ? k.slice(4) : k;
    const cls = base === "achievement" ? "ok"
      : base === "concern" || base === "left" ? "bad"
      : base === "class" ? "" : base === "quiz" ? "" : "";
    return `<span class="pill ${cls} stu-kind">${esc(base)}</span>`;
  };
  const when = (t) => new Date(t * 1000).toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${st.photo ? `<img class="roster-face" src="/media/${esc(st.photo)}" alt="">` : ""}
          ${esc(st.name)}${st.active ? "" : ' <span class="pill bad">deactivated</span>'}${
          p.status !== "active" ? ` <span class="pill warn" title="${esc(p.status_note)}">${esc(p.status_label)}${
            p.status_at ? " · " + fmtDate(p.status_at) : ""}</span>` : ""}</h2>
        <p class="dim">${esc(st.role)} since ${fmtDate(st.created_at)}${
          st.email ? " · " + esc(st.email) : ""}${p.phone ? " · " + esc(p.phone) : ""}${
          p.age != null ? " · " + p.age : ""}${p.nationality ? " · " + esc(p.nationality) : ""}${
          p.native_language ? " · speaks " + esc(p.native_language) : ""}</p></div>
      <div class="top-actions">
        <button class="btn alt" id="stu-back">&larr; Back</button>
        <button class="btn alt" id="stu-status" title="no longer attends, moved, passed away, inactive — or back">Status</button>
        <button class="btn alt" id="stu-note">Add a note</button>
        <button class="btn" id="stu-ach">Log an achievement</button>
      </div>
    </div>
    <div class="stu-stats">
      ${stat("attendance", s.attendance_pct == null ? null : s.attendance_pct + "%",
        `${s.classes_attended} of ${s.classes_marked} marked${s.late ? " · " + s.late + " late" : ""}`)}
      ${stat("average score", s.average_score == null ? null : s.average_score + "%",
        `${s.quizzes_passed} of ${s.quizzes_taken} passed`)}
      ${stat("progress", s.progress_pct == null ? null : s.progress_pct + "%",
        `${s.completed_courses} of ${s.courses} course${s.courses === 1 ? "" : "s"} complete`)}
      ${stat("achievements", s.achievements)}
      ${stat("classes attended", s.classes_attended)}
    </div>
    <div class="card">
      <div class="card-head"><b>About</b>
        <span class="dim">${p.updated_at ? `last corrected ${fmtAgo(p.updated_at)} by ${esc(p.updated_by)}`
          : "nothing filled in yet"}</span>
        <button class="btn sm" id="stu-save" style="margin-left:auto">Save</button></div>
      <div class="stu-grid">${d.fields.map(field).join("")}</div>
      <details style="margin-top:10px"${extras.length ? " open" : ""}>
        <summary class="dim">Anything else the school asks <span class="dim">(${extras.length})</span></summary>
        <div id="stu-extra">${extras.map(([k, v]) => `<div class="stu-extra">
          <input class="stu-xk" value="${esc(k)}" placeholder="what">
          <input class="stu-xv" value="${esc(v)}" placeholder="answer">
          <button class="btn alt sm" data-xdel>remove</button></div>`).join("")}</div>
        <button class="btn alt sm" id="stu-xadd" style="margin-top:6px">Add a field</button>
      </details>
    </div>
    <div class="row">
      <div class="card" style="flex:2;min-width:min(320px,100%)">
        <div class="card-head"><b>Courses</b></div>
        ${d.courses.length ? `<div class="tablewrap"><table>
          <thead><tr><th>course</th><th>teacher</th><th>progress</th><th>attendance</th><th>best results</th></tr></thead>
          <tbody>${d.courses.map((c) => `<tr>
            <td><b>${esc(c.name)}</b>${c.level ? ` <span class="dim">${esc(c.level)}</span>` : ""}${
              c.complete ? ' <span class="pill ok">complete</span>' : ""}</td>
            <td class="dim">${esc(c.teacher || "—")}</td>
            <td>${c.progress.percent}% <span class="dim">· ${c.progress.lessons_done}/${
              c.progress.lessons_total} lessons · ${c.progress.quizzes_passed}/${
              c.progress.quizzes_total} quizzes</span></td>
            <td>${c.attendance.attended}/${c.attendance.classes_held}</td>
            <td class="dim">${c.results.map((r) => `${esc(r.quiz)} ${r.percent}%${
              r.passed ? "" : " (below " + r.pass_mark + ")"}`).join("<br>") || "—"}</td>
          </tr>`).join("")}</tbody></table></div>` : '<p class="dim">Not in any course now.</p>'}
        ${d.seats.some((e) => e.until) ? `<details style="margin-top:8px"><summary class="dim">Past seats</summary>${
          d.seats.filter((e) => e.until).map((e) => `<div class="dim">${esc(e.name)} · ${
            fmtDate(e.since)} – ${fmtDate(e.until)}</div>`).join("")}</details>` : ""}
      </div>
      <div class="card" style="flex:1;min-width:min(260px,100%)">
        <div class="card-head"><b>Achievements</b></div>
        ${d.logged_achievements.map((a) => `<div class="stu-ach">
          <b>${esc(a.title)}</b> <span class="dim">${when(a.at)} · logged by ${esc(a.by_name)}</span>${
          a.body ? `<div class="dim">${esc(a.body)}</div>` : ""}</div>`).join("")}
        ${d.achievements.map((a) => `<div class="stu-ach"><b>${esc(a.name)}</b>
          <span class="dim">${when(a.earned_at)} · earned</span>
          <div class="dim">${esc(a.what)}</div></div>`).join("")}
        ${d.achievements.length + d.logged_achievements.length ? "" : '<p class="dim">None yet.</p>'}
      </div>
    </div>
    <div class="card">
      <div class="card-head"><b>Timeline</b> <span class="dim">${d.timeline.length} things, newest first</span></div>
      ${d.timeline.length ? `<ul class="stu-tl">${d.timeline.map((e) => `<li>
        <time>${when(e.at)}</time>${kindPill(e.kind)}
        <div class="stu-tl-main"><b>${esc(e.title)}</b>${e.body ? ` <span class="dim">${esc(e.body)}</span>` : ""}${
          e.by ? ` <span class="dim">— ${esc(e.by)}</span>` : ""}</div>
        ${e.kind.startsWith("log:") ? `<button class="btn alt sm" data-stulog="${e.id}">remove</button>` : ""}
      </li>`).join("")}</ul>` : '<p class="dim">Nothing yet.</p>'}
    </div>`;
  $("#stu-back").onclick = () => back ? back() : renderCustomers();
  $("#stu-note").onclick = () => studentLogForm(uid, "note", () => studentPage(uid, back), d);
  $("#stu-ach").onclick = () => studentLogForm(uid, "achievement", () => studentPage(uid, back), d);
  $("#stu-status").onclick = () => studentStatusForm(uid, d, () => studentPage(uid, back));
  const extraRow = (k, v) => {
    const div = document.createElement("div");
    div.className = "stu-extra";
    div.innerHTML = `<input class="stu-xk" value="${esc(k || "")}" placeholder="what">
      <input class="stu-xv" value="${esc(v || "")}" placeholder="answer">
      <button class="btn alt sm" data-xdel>remove</button>`;
    div.querySelector("[data-xdel]").onclick = () => div.remove();
    return div;
  };
  view().querySelectorAll("[data-xdel]").forEach((b) => b.onclick = () => b.parentElement.remove());
  $("#stu-xadd").onclick = () => $("#stu-extra").appendChild(extraRow("", ""));
  $("#stu-save").onclick = async () => {
    const fields = {};
    view().querySelectorAll("[data-pf]").forEach((el) => { fields[el.dataset.pf] = el.value; });
    const extra = {};
    view().querySelectorAll(".stu-extra").forEach((row) => {
      const k = row.querySelector(".stu-xk").value.trim();
      if (k) extra[k] = row.querySelector(".stu-xv").value.trim();
    });
    try {
      await api(`/api/students/${uid}/profile`, { body: { fields, extra } });
      toast("saved");
      studentPage(uid, back);
    } catch (err) { toast(err.message); }
  };
  view().querySelectorAll("[data-stulog]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this entry from the log?")) return;
    try {
      await api(`/api/students/${uid}/log/${b.dataset.stulog}`, { method: "DELETE" });
      studentPage(uid, back);
    } catch (err) { toast(err.message); }
  });
}

/* Something staff noticed and wrote down. Dated when it happened, not
   when it was typed — a prize won in March is a March fact. */
function studentLogForm(uid, kind, after, d) {
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  const presets = (d && d.achievement_presets) || [];
  modal(`<h3>${kind === "achievement" ? "Log an achievement" : "Add to the log"}</h3>
    ${presets.length ? `<p class="dim">Pick one, or write your own below.</p>
      <div class="chips" id="sl-presets">${presets.map((t) =>
        `<button type="button" class="btn alt sm" data-preset="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
    <div class="row2">
      <div><label>Kind</label><select id="sl-kind">${
        ["achievement", "milestone", "note", "concern"].map((k) =>
          `<option${k === kind ? " selected" : ""}>${k}</option>`).join("")}</select></div>
      <div><label>When</label><input id="sl-at" type="date" value="${today}"></div>
    </div>
    <label>What</label>
    <input id="sl-title" placeholder="${kind === "achievement"
      ? "won the class speaking prize" : "what happened"}">
    <label>Detail <span class="opt">optional</span></label>
    <textarea id="sl-body" rows="3"></textarea>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="sl-save">Save</button></div>`);
  document.querySelectorAll("[data-preset]").forEach((b) => b.onclick = () => {
    $("#sl-title").value = b.dataset.preset;
    $("#sl-kind").value = "achievement";
    document.querySelectorAll("[data-preset]").forEach((x) => x.classList.toggle("on", x === b));
  });
  $("#sl-save").onclick = async () => {
    const title = $("#sl-title").value.trim();
    if (!title) return toast("say what it was");
    const at = $("#sl-at").value ? new Date($("#sl-at").value + "T12:00").getTime() / 1000 : 0;
    try {
      await api(`/api/students/${uid}/log`, { body: {
        kind: $("#sl-kind").value, title, body: $("#sl-body").value.trim(), at } });
      closeModal();
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}

/* Why somebody is no longer here — no longer attends, moved away, passed
   away, gone quiet — or that they are back. Ending their seats is offered,
   not assumed: a student who moved may keep the online class. */
function studentStatusForm(uid, d, after) {
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  const cur = d.profile.status || "active";
  modal(`<h3>Status</h3>
    <p class="dim">Now: <b>${esc(d.profile.status_label)}</b>${d.profile.status_note
      ? ` — ${esc(d.profile.status_note)}` : ""}</p>
    <div class="row2">
      <div><label>Status</label><select id="ss-status">${d.statuses.map((x) =>
        `<option value="${x.code}"${x.code === cur ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>
      <div><label>Since</label><input id="ss-at" type="date" value="${today}"></div>
    </div>
    <label>Why, or anything to know <span class="opt">optional</span></label>
    <input id="ss-note" placeholder="e.g. moved to Valencia; family in touch">
    <label class="dim" style="display:flex;gap:8px;align-items:center;margin-top:8px">
      <input type="checkbox" id="ss-end" checked> End their seats in every class today</label>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ss-save">Save</button></div>`);
  const sel = $("#ss-status");
  const endRow = $("#ss-end").parentElement;
  const sync = () => { endRow.hidden = sel.value === "active"; };
  sel.onchange = sync; sync();
  $("#ss-save").onclick = async () => {
    const at = $("#ss-at").value ? new Date($("#ss-at").value + "T12:00").getTime() / 1000 : 0;
    try {
      const r = await api(`/api/students/${uid}/status`, { body: {
        status: sel.value, note: $("#ss-note").value.trim(), at,
        end_seats: sel.value !== "active" && $("#ss-end").checked } });
      closeModal();
      toast(r.ended ? `saved — ${r.ended} seat${r.ended === 1 ? "" : "s"} ended` : "saved");
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}
