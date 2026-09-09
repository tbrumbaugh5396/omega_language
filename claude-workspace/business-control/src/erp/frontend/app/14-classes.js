/* Classes: a course with a clock, a tutor, and a door that stays open.

   The Learning tab is about content — lessons, quizzes, grading. This is
   about people and time: who teaches it this term, who is in it this
   week, when it meets, who is asking for more help, and whether it is
   still running. Same rows underneath; a different desk. */

const CL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const clHM = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const clMins = (v) => { const [h, m] = String(v || "0:0").split(":").map(Number); return h * 60 + (m || 0); };

async function renderClasses() {
  const [cl, tq, tr] = await Promise.all([
    api("/api/learning/classes").catch((e) => ({ classes: [], err: e.message })),
    api("/api/learning/tutoring").catch(() => ({ requests: [] })),
    api("/api/learning/trainings").catch(() => ({ trainings: [] })),
  ]);
  const classes = cl.classes || [];
  const asks = tq.requests || [];
  const trainings = tr.trainings || [];
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Classes</h2>
        <p class="dim">${esc(cl.note || "")}</p></div>
      <span class="chips">
        <button class="btn alt" id="cl-training">${opsIcon("calendar", "btn-ic")} New training</button>
        <button class="btn" id="cl-new">${opsIcon("users", "btn-ic")} New class</button></span>
    </div>
    ${cl.err ? `<div class="card empty"><b>Could not read the classes</b><span class="dim">${esc(cl.err)}</span></div>` : ""}
    ${classes.length ? `<div class="sig-rows">${classes.map((c) => `
      <div class="doc-line cl-line${c.active ? "" : " dim"}">
        <span class="dl-title"><b>${esc(c.name)}</b>
          <span class="dim">${c.tutor ? "with " + esc(c.tutor) : "no tutor yet"}${c.active ? "" : " · ended"}</span></span>
        <span class="cl-when dim" title="${esc(c.when)}">${esc(c.when)}</span>
        <span class="cl-count"><b>${c.enrolled}</b> <span class="dim">in</span>${c.left
          ? ` <span class="dim">· ${c.left} left</span>` : ""}${c.asking
          ? ` <span class="pill warn" title="asking for tutoring">${c.asking} asking</span>` : ""}${c.open_session_id
          ? ` <span class="pill ok">in session</span>` : ""}</span>
        <span class="dl-acts">
          <button class="btn alt sm" data-clopen="${c.id}">Open</button>
        </span>
      </div>`).join("")}</div>`
      : `<div class="card empty"><b>No classes yet</b><span class="dim">A class is a course with people and a weekly time. Make one, name a tutor, add people as they arrive.</span></div>`}

    <h3 style="margin-top:18px">Asking for tutoring
      <span class="dim" style="font-weight:400">· ${asks.length} open</span></h3>
    ${asks.length ? `<div class="card"><table>
      <thead><tr><th>who</th><th>class</th><th>how</th><th>when they can</th><th>what they said</th><th></th></tr></thead>
      <tbody>${asks.map((r) => `<tr>
        <td><b>${esc(r.who)}</b>${r.email ? `<span class="dim"> ${esc(r.email)}</span>` : ""}</td>
        <td>${esc(r.course)}</td>
        <td><span class="pill${r.mode === "remote" ? " warn" : ""}">${esc(r.how || "either")}</span></td>
        <td class="dim">${esc(r.when)}</td>
        <td>${esc(r.note || "—")}</td>
        <td class="row-acts">
          <button class="btn alt sm" data-tq="${r.id}:taken">I'll take it</button>
          <button class="btn alt sm" data-tq="${r.id}:done">Done</button>
          <button class="btn alt sm" data-tq="${r.id}:declined">Decline</button>
          <button class="btn alt sm" data-tqlog="${r.id}" title="file the hours you spent — an admin accepts them">Log hours</button></td>
      </tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">Nobody is asking right now. Students ask from their course page, with the times they could do.</p>`}

    <h3 style="margin-top:18px">One-time trainings
      <span class="dim" style="font-weight:400">· ${esc(tr.note || "")}</span></h3>
    ${trainings.length ? `<div class="card"><table>
      <thead><tr><th>training</th><th>film</th><th>watched</th><th>link</th><th></th></tr></thead>
      <tbody>${trainings.map((t) => `<tr class="${t.active ? "" : "dim"}">
        <td><b>${esc(t.title)}</b>${t.blurb ? `<div class="dim">${esc(t.blurb).slice(0, 90)}</div>` : ""}</td>
        <td class="dim">${t.material_id ? esc(t.original || t.kind) : "not up yet"}</td>
        <td><b>${t.viewers}</b> <span class="dim">people · ${t.views} views</span>
          ${t.watched_by.length ? `<details class="bk-answers"><summary>who</summary>${
            t.watched_by.map((w) => `<div>${esc(w.name || w.who)} <span class="dim">· ${w.views}×</span></div>`).join("")}</details>` : ""}</td>
        <td><code class="cl-link">${esc(t.url)}</code>
          <button class="btn alt sm" data-copy="${esc(t.url)}">Copy</button></td>
        <td class="row-acts">
          <label class="btn alt sm">Upload film<input type="file" hidden data-film="${t.id}"></label>
          <button class="btn alt sm" data-tredit="${t.id}">Edit</button></td>
      </tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">None yet. A training is one film and a link you send to everybody — nobody enrols.</p>`}`;

  $("#cl-new").onclick = () => courseForm(null);
  $("#cl-training").onclick = () => clTrainingForm(null);
  view().querySelectorAll("[data-clopen]").forEach((b) => b.onclick = () => clOpen(+b.dataset.clopen));
  view().querySelectorAll("[data-tq]").forEach((b) => b.onclick = async () => {
    const [id, state] = b.dataset.tq.split(":");
    const reply = state === "declined" ? (prompt("A word back to them (optional)") || "") : "";
    try { await api(`/api/learning/tutoring/${id}/state`, { body: { state, reply } }); renderClasses(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-tqlog]").forEach((b) => b.onclick = () => {
    const r = asks.find((x) => String(x.id) === b.dataset.tqlog);
    if (!r) return;
    loggedHoursForm({ kind: "tutoring", tutoring_id: r.id, student_id: r.user_id || 0,
      course_id: r.course_id || 0, with_name: r.who, note: r.course });
  });
  view().querySelectorAll("[data-copy]").forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("link copied"); } catch (e) { toast(b.dataset.copy); }
  });
  view().querySelectorAll("[data-film]").forEach((inp) => inp.onchange = async () => {
    const f = inp.files && inp.files[0]; if (!f) return;
    toast(`uploading ${f.name}…`);
    try {
      const r = await fetch(`/api/learning/trainings/${inp.dataset.film}/film`, { method: "POST", body: f,
        headers: { "Content-Type": f.type || "application/octet-stream", "X-Filename": f.name,
                   Authorization: "Bearer " + S.user.token } });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      toast("film is up"); renderClasses();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-tredit]").forEach((b) => b.onclick = () =>
    clTrainingForm(trainings.find((t) => t.id === +b.dataset.tredit)));
}

/* One class, open: the tutor, the people, the week, the files. */
async function clOpen(cid) {
  const [d, users, rooms] = await Promise.all([
    api(`/api/learning/courses/${cid}`),
    api("/api/admin/users").catch(() => []),
    api("/api/rooms").catch(() => ({ rooms: [] })),
  ]);
  const staff = (Array.isArray(users) ? users : []).filter((u) => u.role !== "customer");
  const everyone = Array.isArray(users) ? users : [];
  const sched = await api(`/api/learning/classes`).then((r) =>
    (r.classes.find((c) => c.id === cid) || {}).schedule || []).catch(() => []);
  const mats = (d.materials || []);
  const seats = d.enrollments || [];
  const inNow = seats.filter((e) => !e.until);
  view().innerHTML = `
    <div class="page-head">
      <div><span class="dim" id="cl-back" style="cursor:pointer">&larr; Classes</span>
        <h2>${esc(d.name)}</h2>
        <p class="dim">${d.active ? "running" : "ended"} · ${inNow.length} in it now · ${
          seats.length - inNow.length} have left${d.open_session_id ? " · in session" : ""}</p></div>
      <span class="chips">
        ${d.open_session_id ? `<button class="btn" id="cl-roster">Register</button>`
          : `<button class="btn" id="cl-start" ${d.active ? "" : "disabled"}>Start class</button>`}
        <button class="btn alt" id="cl-learning" title="lessons, quizzes and grading live on the Learning tab">Content &rarr;</button>
      </span>
    </div>
    <div class="row">
      <div class="card" style="flex:1;min-width:min(260px,100%)">
        <div class="card-head"><b>Tutor</b></div>
        <select id="cl-tutor"><option value="0">nobody yet</option>${staff.map((u) =>
          `<option value="${u.id}" ${u.id === d.teacher_id ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select>
        <p class="dim" style="margin:6px 0 0">The tutor changes; the class does not. The old tutor keeps every session they taught.</p>
        <div class="card-head" style="margin-top:12px"><b>Also teaching it</b>
          <span class="chips"><select id="cl-cot"><option value="">add a teacher…</option>${
            staff.filter((u) => u.id !== d.teacher_id && !(d.teachers || []).some((t) => t.id === u.id)).map((u) =>
              `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select>
            <button class="btn sm" id="cl-cot-add">Add</button></span></div>
        ${(d.teachers || []).filter((t) => !t.lead).length
          ? (d.teachers || []).filter((t) => !t.lead).map((t) => `<div class="cl-cot-row">
              <b>${esc(t.name)}</b> <span class="dim">since ${fmtDate(t.since)}</span>
              <button class="btn alt sm" data-cotdel="${t.id}">remove</button></div>`).join("")
          : `<p class="dim">Nobody else yet. A second teacher sees the class, edits it, runs the register and takes its tutoring asks.</p>`}
      </div>
      <div class="card" style="flex:2;min-width:min(300px,100%)">
        <div class="card-head"><b>When it meets</b>
          <button class="btn alt sm" id="cl-addslot">Add a time</button></div>
        <div id="cl-slots">${sched.map((sl) => clSlotRow(sl, rooms.rooms || [])).join("")}</div>
        ${sched.length ? "" : `<p class="dim">No set time — add one and it appears on the week and the room's timetable.</p>`}
        <p class="dim" style="margin-top:8px"><button class="btn sm" id="cl-saveslots">Save times</button>
          <span class="dim"> — a slot naming a room is checked against the room's diary</span></p>
      </div>
    </div>
    <div class="row">
      <div class="card cl-people" style="flex:2;min-width:min(300px,100%)">
        <div class="card-head"><b>People</b> <span class="dim">rolling — join and leave while it runs</span>
          <span class="chips"><select id="cl-who"><option value="">add someone…</option>${
            everyone.filter((u) => !inNow.some((e) => e.user_id === u.id)).map((u) =>
              `<option value="${u.id}">${esc(u.name)}${u.role === "customer" ? "" : " · " + esc(u.role)}</option>`).join("")}</select>
            <button class="btn sm" id="cl-add">Add</button></span></div>
        ${inNow.length ? `<table><thead><tr><th>who</th><th>since</th><th>progress</th><th></th></tr></thead>
          <tbody>${inNow.map((e) => `<tr><td><a href="#/customers/${e.user_id}" class="cl-link" data-stu="${e.user_id}"><b>${esc(e.name)}</b></a></td>
            <td class="dim">${fmtDate(e.since)}</td>
            <td class="dim">${e.progress ? e.progress.percent + "%" : ""}</td>
            <td class="row-acts"><button class="btn alt sm" data-clend="${e.id}">Leaves today</button></td></tr>`).join("")}
          </tbody></table>` : `<p class="dim">Nobody in it yet.</p>`}
        ${seats.length - inNow.length ? `<details style="margin-top:8px"><summary class="dim">${seats.length - inNow.length} who left</summary>${
          seats.filter((e) => e.until).map((e) => `<div class="dim">${esc(e.name)} · ${fmtDate(e.since)} – ${fmtDate(e.until)}</div>`).join("")}</details>` : ""}
      </div>
      <div class="card" style="flex:1;min-width:min(260px,100%)">
        <div class="card-head"><b>Files for the class</b>
          <label class="btn alt sm">Upload<input type="file" hidden id="cl-file"></label></div>
        <p class="dim">Slides, films, PDFs — shown on the course page and in every session's Shared tab.</p>
        ${mats.length ? mats.map((m) => `<div class="lrn-file" style="display:flex;justify-content:space-between;gap:8px;padding:4px 0">
          <a href="/media/${esc(m.path)}" target="_blank" rel="noopener">${esc(m.original || m.kind)}</a>
          <span class="dim">${esc(m.kind)} <button class="btn alt sm" data-clmat="${m.id}">remove</button></span></div>`).join("")
          : `<p class="dim">Nothing yet.</p>`}
      </div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="card-head"><b>Ending it</b></div>
      <p class="dim">A class that has run its course: everybody's seat ends today, the times come off the week,
        an open session is closed, and it is archived. Nothing is deleted — every transcript and attendance stays.</p>
      <button class="btn alt" id="cl-end" ${d.active ? "" : "disabled"}>End this class</button>
    </div>`;
  $("#cl-back").onclick = renderClasses;
  $("#cl-learning").onclick = () => learningCourse(cid);
  $("#cl-cot-add").onclick = async () => {
    const uid = +$("#cl-cot").value;
    if (!uid) return toast("pick somebody");
    try { await api(`/api/learning/courses/${cid}/teachers`, { body: { user_id: uid } }); clOpen(cid); }
    catch (err) { toast(err.message); }
  };
  view().querySelectorAll("[data-cotdel]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/learning/courses/${cid}/teachers/${b.dataset.cotdel}`, { method: "DELETE" }); clOpen(cid); }
    catch (err) { toast(err.message); }
  });
  $("#cl-tutor").onchange = async (e) => {
    try { await api(`/api/learning/courses/${cid}/tutor`, { body: { teacher_id: +e.target.value } }); toast("tutor changed"); }
    catch (err) { toast(err.message); }
  };
  const wireSlots = () => view().querySelectorAll("[data-sldel]").forEach((b) => b.onclick = () => b.closest(".cl-slot").remove());
  wireSlots();
  $("#cl-addslot").onclick = () => { $("#cl-slots").insertAdjacentHTML("beforeend",
    clSlotRow({ weekday: 1, from_min: 1080, to_min: 1170, room_id: 0 }, rooms.rooms || [])); wireSlots(); };
  $("#cl-saveslots").onclick = async () => {
    const slots = [...view().querySelectorAll(".cl-slot")].map((row) => ({
      weekday: +row.querySelector("[data-slday]").value,
      from_min: clMins(row.querySelector("[data-slfrom]").value),
      to_min: clMins(row.querySelector("[data-slto]").value),
      room_id: +row.querySelector("[data-slroom]").value }));
    try { await api(`/api/learning/courses/${cid}/schedule`, { body: { slots } }); toast("times saved"); clOpen(cid); }
    catch (err) { toast(err.message); }
  };
  $("#cl-add").onclick = async () => {
    const uid = +$("#cl-who").value; if (!uid) return;
    try { await api(`/api/learning/courses/${cid}/enroll`, { body: { user_id: uid } }); clOpen(cid); }
    catch (err) { toast(err.message); }
  };
  view().querySelectorAll("[data-stu]").forEach((a) => a.onclick = (e) => {
    e.preventDefault(); studentPage(+a.dataset.stu, () => clOpen(cid));
  });
  view().querySelectorAll("[data-clend]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/learning/enrollments/${b.dataset.clend}/end`, { body: {} }); clOpen(cid); }
    catch (err) { toast(err.message); }
  });
  const fi = $("#cl-file");
  if (fi) fi.onchange = async () => {
    const f = fi.files && fi.files[0]; if (!f) return;
    toast(`uploading ${f.name}…`);
    try {
      const r = await fetch(`/api/learning/courses/${cid}/material`, { method: "POST", body: f,
        headers: { "Content-Type": f.type || "application/octet-stream", "X-Filename": f.name,
                   Authorization: "Bearer " + S.user.token } });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      clOpen(cid);
    } catch (err) { toast(err.message); }
  };
  view().querySelectorAll("[data-clmat]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/learning/materials/${b.dataset.clmat}/delete`, { body: {} }); clOpen(cid); }
    catch (err) { toast(err.message); }
  });
  const st = $("#cl-start");
  if (st) st.onclick = async () => {
    try { const r = await api("/api/learning/sessions", { body: { course_id: cid } }); sessionRoster(r.session.id, cid); }
    catch (err) { toast(err.message); }
  };
  const ro = $("#cl-roster");
  if (ro) ro.onclick = () => sessionRoster(d.open_session_id, cid);
  $("#cl-end").onclick = async () => {
    if (!confirm(`End ${d.name}? Everybody's seat ends today. Nothing is deleted.`)) return;
    try { const r = await api(`/api/learning/courses/${cid}/end`, { body: {} });
      toast(`ended — ${r.seats_ended} seat${r.seats_ended === 1 ? "" : "s"} closed`); renderClasses(); }
    catch (err) { toast(err.message); }
  };
}

function clSlotRow(sl, rooms) {
  return `<div class="cl-slot">
    <select data-slday>${CL_DAYS.map((d, i) => `<option value="${i}" ${i === sl.weekday ? "selected" : ""}>${d}</option>`).join("")}</select>
    <input type="time" data-slfrom value="${clHM(sl.from_min)}">
    <span class="dim">–</span>
    <input type="time" data-slto value="${clHM(sl.to_min)}">
    <select data-slroom data-cur="${sl.room_id || 0}"><option value="0">no room</option>${(rooms || []).map((r) =>
      `<option value="${r.id}" ${r.id === sl.room_id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>
    <button class="btn alt sm" type="button" data-sldel>remove</button>
  </div>`;
}

function clTrainingForm(t) {
  modal(`<h3>${t ? "Edit training" : "A one-time training"}</h3>
    <p class="dim">One film and a link. Send the link to everybody; nobody has to enrol or sign in to watch, and you see who did.</p>
    <label>Title<input id="tr-title" value="${esc(t ? t.title : "")}" placeholder="The new till system — 6 minutes"></label>
    <label>What it is<textarea id="tr-blurb" rows="3">${esc(t ? t.blurb : "")}</textarea></label>
    ${t ? `<label class="chip bk-toggle ${t.active ? "on" : ""}"><input type="checkbox" id="tr-active" hidden ${t.active ? "checked" : ""}>link is live</label>` : ""}
    <div class="modal-foot"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="tr-save">${t ? "Save" : "Create — then upload the film"}</button></div>`);
  const tg = $("#tr-active"); const lab = tg && tg.closest("label");
  if (lab) lab.onclick = (e) => { e.preventDefault(); tg.checked = !tg.checked; lab.classList.toggle("on", tg.checked); };
  $("#tr-save").onclick = async () => {
    const body = { title: $("#tr-title").value, blurb: $("#tr-blurb").value, active: t ? tg.checked : true };
    try {
      if (t) await api(`/api/learning/trainings/${t.id}`, { body });
      else await api("/api/learning/trainings", { body });
      closeModal(); renderClasses();
    } catch (e) { toast(e.message); }
  };
}
