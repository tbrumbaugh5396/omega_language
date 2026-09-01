/* ---------- Learning ----------
   The LMS behind the Learning capability, ported from lingua-portal. Staff
   author courses, lessons and quizzes here and mark what a machine can't;
   learners meet the same content on the storefront at /learn. Grading rules
   live server-side in one pure module — this screen only displays them. */

async function renderLearning() {
  if (S.deepId) {                     // #/learning/5 — straight to it
    const _id = S.deepId;
    S.deepId = null;
    return learningCourse(_id);
  }
  if (location.hash.startsWith("#/learning/"))
    history.pushState(null, "", "#/learning");
  const [courses, queue, regs, conduct, roleReqs, team] = await Promise.all([
    api("/api/learning/courses"), api("/api/learning/grading"),
    S.user.is_admin ? api("/api/learning/registrations") : Promise.resolve([]),
    S.user.is_admin ? api("/api/learning/conduct") : Promise.resolve([]),
    api("/api/roles/requests").catch(() => []),
    S.user.is_admin ? api("/api/learning/team").catch(() => [])
                    : Promise.resolve([]),
  ]);
  const card = (c) => `
    <div class="card ${c.active ? "" : "dim-card"}" data-course="${c.id}"
      style="cursor:pointer">
      <div class="doc-top">
        <div class="doc-main">
          <b>${esc(c.name)}</b>
          <span class="dim">${esc([c.language, c.level].filter(Boolean)
            .join(" · ") || "course")}${
            c.teacher_name ? " · taught by " + esc(c.teacher_name) : ""}
            · ${c.enrolled} enrolled · ${c.lessons} lesson${
            c.lessons === 1 ? "" : "s"} · ${c.quizzes} quiz${
            c.quizzes === 1 ? "" : "zes"}</span>
        </div>
        <span class="pill ${c.active ? "ok" : ""}">${
          c.active ? "open" : "closed"}</span>
      </div>
      ${c.blurb ? `<p class="dim" style="margin-top:8px">${esc(c.blurb)}</p>` : ""}
    </div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Learning</h2>
        <p class="dim">Courses, lessons and quizzes. Learners take them on
          <a href="/learn" target="_blank">the storefront</a>; scores settle
          automatically except where a human must mark.</p></div>
      ${S.user.is_admin
        ? `<button class="btn" id="lc-new">${opsIcon("pen", "btn-ic")}
            New course</button>` : ""}
    </div>
    ${roleRequestsCard(roleReqs)}
    ${regs.length ? `<h3>Applications (${regs.length})</h3>
      ${regs.map((r) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(r.name)}</b>
            <span class="dim">${esc(r.email)} · wants ${esc(r.language)}${
              r.level ? " (" + esc(r.level) + ")" : ""}${
              r.course_name ? " · asked for " + esc(r.course_name) : ""}</span></div>
          <button class="btn sm" data-regok="${r.id}">Approve</button>
          <button class="btn alt sm" data-regno="${r.id}">Decline</button>
        </div>
        ${r.goals ? `<p class="dim" style="margin-top:8px">${esc(r.goals)}</p>` : ""}
      </div>`).join("")}` : ""}
    ${conduct.length ? `<h3>Conduct reports (${conduct.length})</h3>
      ${conduct.map((r) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(r.reporter_name)} reported
            ${esc(r.subject_name)}</b>
            <span class="dim">${esc(r.reason)}</span></div>
          <button class="btn sm" data-conres="${r.id}">Resolve</button>
        </div>
        ${r.body_snapshot ? `<p class="dim" style="margin-top:8px">The
          message, as it read when reported:
          <i>${esc(r.body_snapshot)}</i></p>` : ""}
      </div>`).join("")}` : ""}
    ${queue.length ? `<h3>Needs a human mark (${queue.length})</h3>
      ${queue.map((a) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(a.quiz_title)}</b>
            <span class="dim">${esc(a.student)} · ${a.pending} answer${
              a.pending === 1 ? "" : "s"} waiting</span></div>
          <button class="btn sm" data-grade="${a.id}">Grade</button>
        </div></div>`).join("")}` : ""}
    <h3>Courses (${courses.length})</h3>
    ${courses.map(card).join("") || `<div class="card empty"><span class="e-ic">${
      opsIcon("pen")}</span><b>No courses yet</b><span class="dim">${
      S.user.is_admin ? "Create one — lessons and quizzes hang off it."
        : "An owner can create one and appoint you its teacher."}</span></div>`}
    ${S.user.is_admin ? `<div class="page-head" style="margin-top:16px">
      <h3>The team (${team.length})</h3>
      <div style="display:flex;gap:8px">
        <button class="btn alt sm" id="lt-invite">Invite by link</button>
        <button class="btn sm" id="lt-add">Add person</button>
      </div>
    </div>
    ${team.map((p) => `<div class="card${p.active ? "" : " dim-card"}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.name)}</b>
          <span class="dim">${esc(p.role)}${p.is_admin ? " · admin" : ""}${
            p.email ? " · " + esc(p.email) : ""}${p.active
            ? "" : " · deactivated"}${p.teaches
            ? ` · teaches ${p.teaches} course${p.teaches === 1 ? "" : "s"}`
            : ""}</span></div>
        <button class="btn alt sm" data-tedit="${p.id}">Edit</button>
      </div></div>`).join("")}` : ""}`;
  if ($("#lc-new")) $("#lc-new").onclick = () => courseForm(null);
  if ($("#lt-add")) $("#lt-add").onclick = () => teamForm(null);
  if ($("#lt-invite")) $("#lt-invite").onclick = () => inviteForm(team);
  view().querySelectorAll("[data-tedit]").forEach((b) => b.onclick = () =>
    teamForm(team.find((p) => p.id === +b.dataset.tedit)));
  wireRoleRequests(renderLearning);
  view().querySelectorAll("[data-course]").forEach((el) =>
    el.onclick = () => learningCourse(+el.dataset.course));
  view().querySelectorAll("[data-grade]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); gradeAttempt(+b.dataset.grade); });
  // staff-only extras: the lending desk, and (admins) data rights + payroll
  if (S.user.is_admin || courses.length) learningLibrary();
  if (S.user.is_admin) learningDataRights();
  view().querySelectorAll("[data-regok]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(`/api/learning/registrations/${b.dataset.regok}/approve`,
        { body: {} });
      toast(out.existing_account
        ? `${out.person.name} already had an account — enrolled`
        : `Account created for ${out.person.name} — they sign in with that `
          + "name on the storefront");
      renderLearning();
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-regno]").forEach((b) => b.onclick = async () => {
    const note = prompt("Why? (kept on the record)") || "";
    await api(`/api/learning/registrations/${b.dataset.regno}/decline`,
      { body: { note } });
    renderLearning();
  });
  view().querySelectorAll("[data-conres]").forEach((b) => b.onclick = async () => {
    const note = prompt("Outcome note (kept on the record)") || "";
    await api(`/api/learning/conduct/${b.dataset.conres}/resolve`,
      { body: { note } });
    renderLearning();
  });
  if (S.user.is_admin) learningPayroll();
}

async function learningLibrary() {
  /* The lending desk. Availability is DERIVED — copies minus open loans —
     and overdue is a comparison, so neither can drift. */
  let d;
  try { d = await api("/api/learning/library"); } catch (e) { return; }
  const el = document.createElement("div");
  const day = (t) => t ? new Date(t * 1000).toLocaleDateString() : "";
  el.innerHTML = `
    <div class="page-head" style="margin-top:16px">
      <h3>Library (${d.items.length} item${d.items.length === 1 ? "" : "s"},
        ${d.loans.length} out)</h3>
      <div style="display:flex;gap:8px">
        <button class="btn alt sm" id="lib-scan">Scan item</button>
        <button class="btn sm" id="lib-add">Add item</button>
      </div>
    </div>
    ${d.loans.length ? d.loans.map((l) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(l.item_name)}</b>
          <span class="dim">out to ${esc(l.borrower)} since ${day(l.out_at)}${
            l.due_at ? (l.overdue ? " · overdue since " : " · due ")
              + day(l.due_at) : ""}</span></div>
        ${l.overdue ? '<span class="pill">overdue</span>' : ""}
        <button class="btn sm" data-libret="${l.id}">Returned</button>
      </div></div>`).join("") : ""}
    ${d.items.map((i) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(i.name)}</b>
          <span class="dim">${esc(i.kind)} · ${i.available} of ${i.copies}
            available${i.owner ? " · " + esc(i.owner) + "'s" : ""}${
            i.notes ? " · " + esc(i.notes) : ""}</span></div>
        <button class="btn alt sm" data-libqr="${i.id}">QR</button>
        <button class="btn alt sm" data-libedit="${i.id}">Edit</button>
        <button class="btn alt sm" data-libdel="${i.id}">Remove</button>
        <button class="btn alt sm" data-libout="${i.id}"
          ${i.available ? "" : "disabled"}>${i.available
            ? "Check out" : "all out"}</button>
      </div></div>`).join("")
      || '<div class="card empty"><b>No items yet</b><span class="dim">Books, materials, equipment — anything that goes out and comes back.</span></div>'}`;
  view().appendChild(el);
  $("#lib-add").onclick = () => {
    modal(`<h3>Add a library item</h3>
      <label>Name</label><input id="la-name">
      <div class="row2">
        <div><label>Kind</label><select id="la-kind">
          <option value="book">book</option>
          <option value="material">material</option>
          <option value="equipment">equipment</option></select></div>
        <div><label>Copies</label><input id="la-copies" type="number" value="1"></div>
      </div>
      <label>Notes <span class="dim">(optional)</span></label>
      <input id="la-notes">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="la-save">Add</button>
      </div>`);
    $("#la-save").onclick = async () => {
      try {
        await api("/api/learning/library/items", { body: {
          name: $("#la-name").value, kind: $("#la-kind").value,
          copies: +$("#la-copies").value || 1,
          notes: $("#la-notes").value } });
        closeModal(); renderLearning();
      } catch (err) { toast(err.message); }
    };
  };
  el.querySelectorAll("[data-libret]").forEach((b) => b.onclick = async () => {
    try {
      await api(`/api/learning/library/return/${b.dataset.libret}`, { body: {} });
      renderLearning();
    } catch (err) { toast(err.message); }
  });
  const checkoutModal = async (itemId, itemName) => {
    const users = await api("/api/admin/users").catch(() => null);
    modal(`<h3>Check out${itemName ? " — " + esc(itemName) : ""}</h3>
      <label>To</label>${users
        ? `<select id="lo-user">${users.filter((u) => u.active).map((u) =>
            `<option value="${u.id}">${esc(u.name)} (${esc(u.role)})</option>`)
            .join("")}</select>`
        : '<input id="lo-name" placeholder="their exact name">'}
      <label>Due back in (days; 0 = no due date)</label>
      <input id="lo-days" type="number" value="14">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="lo-save">Check out</button>
      </div>`);
    $("#lo-save").onclick = async () => {
      const body = { item_id: itemId,
        due_days: +$("#lo-days").value || null };
      if (users) body.user_id = +$("#lo-user").value;
      else body.name = $("#lo-name").value.trim();
      try {
        await api("/api/learning/library/checkout", { body });
        closeModal(); renderLearning();
      } catch (err) { toast(err.message); }
    };
  };
  el.querySelectorAll("[data-libout]").forEach((b) => b.onclick = () =>
    checkoutModal(+b.dataset.libout));
  el.querySelectorAll("[data-libqr]").forEach((b) => b.onclick = async () => {
    const item = d.items.find((i) => i.id === +b.dataset.libqr);
    try {
      const r = await api(`/api/learning/library/items/${b.dataset.libqr}/qr`);
      modal(`<h3>${esc(item ? item.name : "Item")} — QR label</h3>
        <p style="text-align:center"><img
          src="/api/qr.svg?data=${encodeURIComponent(r.payload)}"
          alt="item label" style="width:220px;background:#fff;padding:10px;
          border-radius:8px"></p>
        <p class="dim">Stick it on the item. Scanning it at the desk pulls
          the item straight up — the label survives renames, and a photo
          of it is only ever a library label.</p>
        <div class="modal-acts">
          <button class="btn alt" data-close>Done</button>
        </div>`);
    } catch (err) { toast(err.message); }
  });
  el.querySelectorAll("[data-libedit]").forEach((b) => b.onclick = () => {
    const i = d.items.find((x) => x.id === +b.dataset.libedit);
    if (!i) return;
    modal(`<h3>Edit — ${esc(i.name)}</h3>
      <label>Name</label><input id="le-name" value="${esc(i.name)}">
      <div class="row2">
        <div><label>Kind</label><select id="le-kind">
          ${["book", "material", "equipment"].map((k) =>
            `<option ${i.kind === k ? "selected" : ""}>${k}</option>`).join("")}
        </select></div>
        <div><label>Copies</label>
          <input id="le-copies" type="number" value="${i.copies}"></div>
      </div>
      <p class="dim">Lower the copies to retire worn-out ones — it can't
        drop below what's currently out (${i.out}).</p>
      <label>Owner <span class="dim">(whose property; blank = the school's)</span></label>
      <input id="le-owner" value="${esc(i.owner || "")}">
      <label>Notes</label><input id="le-notes" value="${esc(i.notes || "")}">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="le-save">Save</button>
      </div>`);
    $("#le-save").onclick = async () => {
      try {
        await api(`/api/learning/library/items/${i.id}`, {
          method: "PATCH", body: {
            name: $("#le-name").value, kind: $("#le-kind").value,
            copies: +$("#le-copies").value,
            owner: $("#le-owner").value, notes: $("#le-notes").value } });
        closeModal(); renderLearning();
      } catch (err) { toast(err.message); }
    };
  });
  el.querySelectorAll("[data-libdel]").forEach((b) => b.onclick = async () => {
    try {
      const r = await api(`/api/learning/library/items/${b.dataset.libdel}`,
                          { method: "DELETE" });
      toast(r.result === "retired"
        ? "retired — its loan history stands" : "deleted");
      renderLearning();
    } catch (err) { toast(err.message); }
  });
  $("#lib-scan").onclick = async () => {
    const text = await QRScan.scan({ title: "Scan the item's label" });
    if (!text) return;
    try {
      const item = await api("/api/learning/library/scan",
                             { body: { payload: text } });
      if (item.available) checkoutModal(item.id, item.name);
      else toast(`${item.name}: every copy is out`);
    } catch (err) { toast(err.message); }
  };
}

async function learningDataRights() {
  /* Export and erasure. The plan is SHOWN before anything runs, and the
     confirmation is the person's typed name — never a yes/no click. */
  const users = await api("/api/admin/users").catch(() => null);
  if (!users) return;
  const el = document.createElement("div");
  el.innerHTML = `
    <h3 style="margin-top:16px">Data rights</h3>
    <div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>Export or erase a person's data</b>
          <span class="dim">Export bundles everything held about them.
            Erasure tombstones the account: identity gone, the business's
            own records (attendance, pay, orders) kept.</span></div>
        <select id="dr-user">${users.filter((u) => u.active)
          .map((u) => `<option value="${u.id}">${esc(u.name)}</option>`)
          .join("")}</select>
        <button class="btn alt sm" id="dr-export">Export</button>
        <button class="btn sm" id="dr-erase">Erase…</button>
      </div></div>`;
  view().appendChild(el);
  $("#dr-export").onclick = async () => {
    const uid = +$("#dr-user").value;
    try {
      const r = await fetch(`/api/learning/people/${uid}/export`, {
        headers: { Authorization: "Bearer " + S.user.token } });
      if (!r.ok) throw new Error("export failed");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `person-${uid}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message); }
  };
  $("#dr-erase").onclick = async () => {
    const uid = +$("#dr-user").value;
    let p;
    try { p = await api(`/api/learning/people/${uid}/erase-plan`); }
    catch (err) { return toast(err.message); }
    const bucket = (title, obj) => {
      const rows = Object.entries(obj).filter(([, n]) => n > 0);
      if (!rows.length) return "";
      return `<p style="margin:10px 0 4px"><b>${title}</b></p>
        ${rows.map(([k, n]) => `<div class="dim">${esc(k)}: ${n}</div>`).join("")}`;
    };
    modal(`<h3>Erase ${esc(p.person.name)}</h3>
      <p class="dim">This cannot be undone. Export their data first if
        anyone might need it.</p>
      ${bucket("Deleted for good", p.deleted)}
      ${bucket("Made anonymous", p.anonymised)}
      ${bucket("Retained (the business's own records)", p.retained)}
      <p class="dim" style="margin-top:8px">${esc(p.note)}</p>
      <label style="margin-top:10px">Type their name exactly to confirm</label>
      <input id="er-name" autocomplete="off" placeholder="${esc(p.person.name)}">
      <label>Reason <span class="dim">(kept on the record)</span></label>
      <input id="er-reason">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="er-go">Erase for good</button>
      </div>`, "wide");
    $("#er-go").onclick = async () => {
      try {
        const out = await api(`/api/learning/people/${uid}/erase`, { body: {
          confirm_name: $("#er-name").value,
          reason: $("#er-reason").value } });
        closeModal();
        toast(`Erased — ${out.removed.messages} messages and `
          + `${out.removed["recordings and uploads"]} files gone`);
        renderLearning();
      } catch (err) { toast(err.message); }
    };
  };
}

async function renderNutrition() {
  /* The coach view. Oversight follows the SEAT: a member who tracks for
     themselves is on nobody's caseload — only bought or granted places
     appear here, exactly as courses gate lessons by enrolment. */
  const [programs, clients] = await Promise.all([
    api("/api/nutrition/programs"),
    api("/api/nutrition/clients").catch(() => []),
  ]);
  const wk = (a) => a.days.filter((d) => d.on_target).length;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Nutrition</h2>
        <p class="dim">Coaching programs and the caseload. Members track on
          <a href="/nutrition" target="_blank">the storefront</a>; buying a
          program's product opens the seat — checkout is the coaching
          desk.</p></div>
      ${S.user.is_admin
        ? `<button class="btn" id="np-new">${opsIcon("bag", "btn-ic")}
            New program</button>` : ""}
    </div>
    <h3>Programs (${programs.length})</h3>
    ${programs.map((p) => `<div class="card ${p.active ? "" : "dim-card"}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.name)}</b>
          <span class="dim">${p.coach_name ? "coached by "
            + esc(p.coach_name) + " · " : ""}${p.clients} client${
            p.clients === 1 ? "" : "s"}${p.product_id
            ? " · sold on the storefront (buying opens the seat)" : ""}</span></div>
        ${S.user.is_admin
          ? `<button class="btn alt sm" data-npedit="${p.id}">Edit</button>` : ""}
      </div>
      ${p.blurb ? `<p class="dim" style="margin-top:8px">${esc(p.blurb)}</p>` : ""}
    </div>`).join("") || `<div class="card empty"><span class="e-ic">${
      opsIcon("bag")}</span><b>No programs yet</b><span class="dim">A program
      names its coach and, optionally, the product that sells it.</span></div>`}
    <div class="page-head" style="margin-top:16px">
      <h3>Clients (${clients.filter((c) => !c.until).length})</h3>
      ${S.user.is_admin
        ? '<button class="btn sm" id="nc-new">Open a seat</button>' : ""}
    </div>
    ${clients.map((c) => `<div class="card ${c.until ? "dim-card" : ""}"
      ${c.until ? "" : `data-ncdetail="${c.user_id}" style="cursor:pointer"`}>
      <div class="doc-top">
        <div class="doc-main"><b>${esc(c.name)}</b>
          <span class="dim">${c.program ? esc(c.program) + " · " : ""}via
            ${esc(c.source)} · ${c.latest_kg
              ? c.latest_kg.toFixed(1) + " kg · " : ""}logging streak
            ${c.adherence.streaks.current} · ${wk(c.adherence)}/7 days on
            target${c.until ? " · ended" : ""}</span></div>
        ${!c.until && S.user.is_admin
          ? `<button class="btn alt sm" data-ncend="${c.id}">End seat</button>`
          : ""}
      </div></div>`).join("")
      || '<div class="card empty"><b>No clients yet</b><span class="dim">Link a program to a product, or open a seat by hand.</span></div>'}`;
  if ($("#np-new")) $("#np-new").onclick = () => nutritionProgramForm(null);
  view().querySelectorAll("[data-npedit]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    nutritionProgramForm(programs.find((p) => p.id === +b.dataset.npedit));
  });
  view().querySelectorAll("[data-ncend]").forEach((b) => b.onclick =
    async (e) => {
      e.stopPropagation();
      await api(`/api/nutrition/clients/${b.dataset.ncend}/end`, { body: {} });
      renderNutrition();
    });
  view().querySelectorAll("[data-ncdetail]").forEach((el) => el.onclick =
    () => nutritionClient(+el.dataset.ncdetail));
  if ($("#nc-new")) $("#nc-new").onclick = async () => {
    const users = await api("/api/admin/users");
    modal(`<h3>Open a coaching seat</h3>
      <label>Person</label><select id="ns-user">
        ${users.filter((u) => u.active).map((u) =>
          `<option value="${u.id}">${esc(u.name)} (${esc(u.role)})</option>`)
          .join("")}</select>
      <label>Program <span class="dim">(optional)</span></label>
      <select id="ns-prog"><option value="">— none —</option>
        ${programs.filter((p) => p.active).map((p) =>
          `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="ns-save">Open seat</button>
      </div>`);
    $("#ns-save").onclick = async () => {
      try {
        await api("/api/nutrition/clients", { body: {
          user_id: +$("#ns-user").value,
          program_id: +$("#ns-prog").value || null } });
        closeModal(); renderNutrition();
      } catch (err) { toast(err.message); }
    };
  };
}

async function nutritionProgramForm(p) {
  const [users, products] = await Promise.all([
    api("/api/admin/users"), api("/api/products").catch(() => [])]);
  const staff = users.filter((u) => u.active &&
    (u.role === "employee" || u.is_admin));
  modal(`<h3>${p ? "Edit program" : "New program"}</h3>
    <label>Name</label><input id="np-name" value="${esc((p && p.name) || "")}">
    <label>Blurb</label>
    <textarea id="np-blurb" rows="2">${esc((p && p.blurb) || "")}</textarea>
    <div class="row2">
      <div><label>Coach</label><select id="np-coach">
        <option value="">— none —</option>
        ${staff.map((u) => `<option value="${u.id}" ${p && p.coach_id === u.id
          ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select></div>
      <div><label>Sold as <span class="dim">(buying opens the seat)</span></label>
        <select id="np-product"><option value="">— not sold —</option>
        ${products.map((x) => `<option value="${x.id}" ${p && p.product_id === x.id
          ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
    </div>
    <label class="perm" style="margin-top:14px">
      <input type="checkbox" id="np-active" ${!p || p.active ? "checked" : ""}>
      <span><b>Open</b><small>Selling and seating stay live</small></span></label>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="np-save">Save</button>
    </div>`);
  $("#np-save").onclick = async () => {
    const body = { name: $("#np-name").value.trim(),
      blurb: $("#np-blurb").value.trim(),
      coach_id: +$("#np-coach").value || null,
      product_id: +$("#np-product").value || null,
      active: $("#np-active").checked ? 1 : 0 };
    if (!body.name) return toast("a program needs a name");
    try {
      if (p) await api(`/api/nutrition/programs/${p.id}`, { body });
      else await api("/api/nutrition/programs", { body });
      closeModal(); renderNutrition();
    } catch (err) { toast(err.message); }
  };
}

async function nutritionClient(uid) {
  let d;
  try { d = await api(`/api/nutrition/clients/${uid}/detail`); }
  catch (err) { return toast(err.message); }
  const t = d.targets;
  const a = d.adherence;
  modal(`<h3>${esc(d.person.name)}</h3>
    <p class="dim">${t.has_numbers
      ? `maintenance ${t.tdee}${t.override ? " (observed)" : ""} kcal ·
        target ${t.target} kcal · latest ${t.latest_kg
          ? t.latest_kg.toFixed(1) + " kg" : "-"}`
      : "no weigh-ins yet — targets wait for a number"}</p>
    <p class="dim">Logging streak ${a.streaks.current} (best
      ${a.streaks.best}) · ${a.days.filter((x) => x.on_target).length}/${
      a.days.length} days on target</p>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin:8px 0">
      ${a.days.map((x) => `<span class="pill ${x.on_target ? "ok" : ""}"
        title="${x.day}">${x.day.slice(8)}${x.logged
          ? " · " + Math.round(x.kcal) : ""}</span>`).join("")}
    </div>
    <h4>Recent log</h4>
    ${d.recent_log.map((e) => `<div class="doc-top">
      <div class="doc-main"><span>${esc(e.day)} · ${esc(e.slot)} ·
        ${esc(e.name)}</span>
        <span class="dim">${Math.round(e.cal)} kcal ·
          ${Math.round(e.protein)}g protein</span></div>
    </div>`).join("") || '<p class="dim">Nothing logged yet.</p>'}
    <div class="modal-acts"><button class="btn" data-close>Done</button></div>`,
    "wide");
}

async function learningPayroll() {
  /* Payroll is a DERIVATION, not a ledger: every figure traces to a closed
     class session; administrators own only the approve/hold/paid overlay. */
  const p = await api("/api/learning/payroll");
  if (!p.teachers.length) return;
  const money = (c) => "$" + (c / 100).toFixed(2);
  const el = document.createElement("div");
  el.innerHTML = `
    <h3 style="margin-top:16px">Teaching pay (derived from sessions)</h3>
    ${p.teachers.map((t) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(t.name)}</b>
          <span class="dim">${t.sessions} session${t.sessions === 1 ? "" : "s"}
            · ${t.billable_minutes} billable min
            · owed ${money(t.amount_cents)}${
            t.held_cents ? " · held " + money(t.held_cents) : ""}</span></div>
        <button class="btn alt sm" data-rate="${t.teacher_id}">Rate</button>
      </div>
      ${t.lines.map((ln) => `<div class="doc-top" style="margin-top:6px">
        <div class="doc-main"><span>${esc(ln.course)} ·
          ${new Date(ln.started_at * 1000).toLocaleDateString()}</span>
          <span class="dim">${ln.billable_minutes} min ·
            ${ln.students_attended} attended · ${money(ln.amount_cents)}</span></div>
        <span class="pill ${ln.state === "paid" ? "ok" : ""}">${ln.state}</span>
        ${["approved", "held", "paid"].filter((s) => s !== ln.state).map((s) =>
          `<button class="btn alt sm" data-pay="${ln.session_id}:${s}">${s}</button>`
        ).join("")}
      </div>`).join("")}
    </div>`).join("")}`;
  view().appendChild(el);
  el.querySelectorAll("[data-pay]").forEach((b) => b.onclick = async () => {
    const [sid, state] = b.dataset.pay.split(":");
    await api(`/api/learning/payroll/${sid}/state`, { body: { state } });
    renderLearning();
  });
  el.querySelectorAll("[data-rate]").forEach((b) => b.onclick = () =>
    payRateForm(+b.dataset.rate, p.rates.find(
      (r) => r.teacher_id === +b.dataset.rate)));
}

function payRateForm(teacherId, r) {
  modal(`<h3>Pay rate</h3>
    <p class="dim">Pay derives from closed sessions at these knobs — there is
      no editable "amount owed" anywhere.</p>
    <div class="row2">
      <div><label>Hourly ($)</label><input id="pr-h" type="number" step="0.01"
        value="${r ? (r.hourly_cents / 100).toFixed(2) : "0.00"}"></div>
      <div><label>Per session ($)</label><input id="pr-s" type="number" step="0.01"
        value="${r ? (r.per_session_cents / 100).toFixed(2) : "0.00"}"></div>
    </div>
    <div class="row2">
      <div><label>Minimum minutes</label><input id="pr-m" type="number"
        value="${r ? r.minimum_minutes : 0}"></div>
      <div><label>Round up to (min)</label><input id="pr-r" type="number"
        value="${r ? r.round_to_min : 1}"></div>
    </div>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="pr-save">Save</button>
    </div>`);
  $("#pr-save").onclick = async () => {
    try {
      await api("/api/learning/payrates", { body: {
        teacher_id: teacherId,
        hourly_cents: Math.round((+$("#pr-h").value || 0) * 100),
        per_session_cents: Math.round((+$("#pr-s").value || 0) * 100),
        minimum_minutes: +$("#pr-m").value || 0,
        round_to_min: +$("#pr-r").value || 1 } });
      closeModal(); renderLearning();
    } catch (err) { toast(err.message); }
  };
}

async function courseForm(c) {
  const [users, products] = await Promise.all([
    S.user.is_admin ? api("/api/admin/users") : Promise.resolve([]),
    api("/api/products").catch(() => [])]);
  const staff = users.filter((u) => u.active &&
    (u.role === "employee" || u.is_admin));
  modal(`<h3>${c ? "Edit course" : "New course"}</h3>
    <label>Name</label><input id="cf-name" value="${esc((c && c.name) || "")}">
    <div class="row2">
      <div><label>Language / subject</label>
        <input id="cf-lang" value="${esc((c && c.language) || "")}"></div>
      <div><label>Level</label>
        <input id="cf-level" value="${esc((c && c.level) || "")}"
          placeholder="beginner, B1, …"></div>
    </div>
    <label>Blurb <span class="dim">(shown to learners not yet enrolled)</span></label>
    <textarea id="cf-blurb" rows="2">${esc((c && c.blurb) || "")}</textarea>
    <div class="row2">
      <div><label>Teacher</label><select id="cf-teacher">
        <option value="">— none —</option>
        ${staff.map((u) => `<option value="${u.id}" ${c && c.teacher_id === u.id
          ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select></div>
      <div><label>Sold as <span class="dim">(buying enrols)</span></label>
        <select id="cf-product"><option value="">— not sold —</option>
        ${products.map((p) => `<option value="${p.id}" ${c && c.product_id === p.id
          ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>
    </div>
    <label class="perm" style="margin-top:14px">
      <input type="checkbox" id="cf-active" ${!c || c.active ? "checked" : ""}>
      <span><b>Open</b><small>Visible to learners on the storefront</small></span></label>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="cf-save">Save</button>
    </div>`);
  $("#cf-save").onclick = async () => {
    const name = $("#cf-name").value.trim();
    if (!name) return toast("a course needs a name");
    const body = { name, language: $("#cf-lang").value.trim(),
      level: $("#cf-level").value.trim(), blurb: $("#cf-blurb").value.trim(),
      teacher_id: +$("#cf-teacher").value || null,
      product_id: +$("#cf-product").value || null,
      active: $("#cf-active").checked ? 1 : 0 };
    try {
      if (c) await api(`/api/learning/courses/${c.id}`, { body });
      else await api("/api/learning/courses", { body });
      closeModal();
      c ? learningCourse(c.id) : renderLearning();
    } catch (err) { toast(err.message); }
  };
}

/* The team: teachers, tutors, office staff and volunteers, managed where
   the school's work is. Adding directly is an admin act; the invite link
   is the door for the person themself — bound to a premade account, their
   sign-up wires straight into it. */
const TEAM_ROLES = [["teacher", "teacher / tutor"], ["employee",
  "office staff"], ["volunteer", "volunteer"], ["director",
  "executive director"], ["board", "board member"], ["donor", "donor"]];

function teamForm(p) {
  modal(`<h3>${p ? "Edit " + esc(p.name) : "Add a person"}</h3>
    ${p ? "" : `<label>Name</label><input id="tf-name">`}
    <label>Role</label>
    <select id="tf-role">${TEAM_ROLES.map(([v, l]) =>
      `<option value="${v}" ${p && p.role === v ? "selected" : ""}>${l}</option>`)
      .join("")}</select>
    <label>Email</label>
    <input id="tf-email" value="${esc(p ? p.email || "" : "")}">
    ${p ? "" : `<p class="dim">This makes the account now, without its
      person — pair it with an invite link so their sign-up claims it,
      or hand them the name to sign in with.</p>`}
    <div style="display:flex;gap:8px;margin-top:10px">
      <button class="btn sm" id="tf-save">${p ? "Save" : "Add"}</button>
      ${p && p.id !== S.user.id ? `<button class="btn alt sm" id="tf-toggle">
        ${p.active ? "Deactivate" : "Reactivate"}</button>` : ""}
    </div>
    ${p ? `<p class="dim">Deactivating keeps every record they appear in —
      it only closes the door.</p>` : ""}`);
  $("#tf-save").onclick = async () => {
    try {
      if (p) {
        await api(`/api/admin/users/${p.id}/update`, { body: {
          role: $("#tf-role").value, email: $("#tf-email").value.trim() } });
      } else {
        await api("/api/learning/team", { body: {
          name: $("#tf-name").value.trim(), role: $("#tf-role").value,
          email: $("#tf-email").value.trim() } });
      }
      closeModal();
      renderLearning();
    } catch (err) { toast(err.message); }
  };
  if ($("#tf-toggle")) $("#tf-toggle").onclick = async () => {
    await api(`/api/admin/users/${p.id}/update`,
              { body: { active: !p.active } });
    closeModal();
    renderLearning();
  };
}

function inviteForm(team) {
  const premade = (team || []).filter((p) => p.active);
  modal(`<h3>Invite by link</h3>
    <p class="dim">The link carries the role — whoever opens it signs up
      straight in, no approval queue. Single-use.</p>
    <label>Role</label>
    <select id="iv-role">${TEAM_ROLES.map(([v, l]) =>
      `<option value="${v}">${l}</option>`).join("")}</select>
    <label>Bind to a premade account <span class="dim">(optional)</span></label>
    <select id="iv-person"><option value="">— a fresh account —</option>
      ${premade.map((p) =>
        `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
    <label>Their name <span class="dim">(optional prefill)</span></label>
    <input id="iv-name">
    <label>Their email <span class="dim">(optional)</span></label>
    <input id="iv-mail">
    <p><button class="btn sm" id="iv-make">Make the link</button></p>
    <p id="iv-out"></p>`);
  $("#iv-make").onclick = async () => {
    try {
      const out = await api("/api/roles/invites", { body: {
        role: $("#iv-role").value,
        person_id: +$("#iv-person").value || null,
        name: $("#iv-name").value.trim(),
        email: $("#iv-mail").value.trim() } });
      const url = location.origin + out.path;
      const sent = out.emailed === "sent"
        ? " Emailed to them too."
        : out.emailed === "dry"
          ? " (No SMTP configured, so nothing was emailed — send the link"
            + " yourself.)"
          : out.emailed
            ? ` (Email failed: ${esc(out.emailed)} — send the link`
              + ` yourself.)` : "";
      document.getElementById("iv-out").innerHTML =
        `<input id="iv-url" value="${esc(url)}" readonly style="width:100%">
         <span class="dim">Send this to your ${esc(out.role_label)} —
           it works once.${sent}</span>`;
      const box = document.getElementById("iv-url");
      box.onfocus = () => box.select();
      box.focus();
    } catch (err) { toast(err.message); }
  };
}

async function learningCourse(cid) {
  // the course is a place: give it the address the back button and
  // a pasted link both understand
  if (location.hash !== `#/learning/${cid}`)
    history.pushState(null, "", `#/learning/${cid}`);
  const d = await api(`/api/learning/courses/${cid}`);
  const lesson = (l) => `<div class="card">
    <div class="doc-top">
      <div class="doc-main"><b>${esc(l.title)}</b>
        <span class="dim">${l.published ? "published" : "draft"}</span></div>
      <button class="btn alt sm" data-lmove="${l.id}:-1" title="Move up">↑</button>
      <button class="btn alt sm" data-lmove="${l.id}:1" title="Move down">↓</button>
      <button class="btn alt sm" data-ledit="${l.id}">Edit</button>
      <button class="btn ${l.published ? "alt " : ""}sm" data-lpub="${l.id}">
        ${l.published ? "Unpublish" : "Publish"}</button>
    </div></div>`;
  const quiz = (q) => `<div class="card">
    <div class="doc-top">
      <div class="doc-main"><b>${esc(q.title)}</b>
        <span class="dim">${q.questions} question${q.questions === 1 ? "" : "s"}
          · pass ${q.pass_mark}% · ${q.published ? "published" : "draft"}</span></div>
      <button class="btn alt sm" data-qedit="${q.id}">Questions</button>
      <button class="btn ${q.published ? "alt " : ""}sm" data-qpub="${q.id}">
        ${q.published ? "Unpublish" : "Publish"}</button>
    </div></div>`;
  const seat = (e) => `<div class="card ${e.until ? "dim-card" : ""}">
    <div class="doc-top">
      <div class="doc-main"><b>${esc(e.name)}</b>
        <span class="dim">${esc(e.role)} · via ${esc(e.source)} ·
          ${e.progress.lessons_done}/${e.progress.lessons_total} lessons ·
          ${e.progress.quizzes_passed}/${e.progress.quizzes_total} quizzes
          ${e.until ? " · ended" : ""}</span></div>
      ${!e.until && S.user.is_admin
        ? `<button class="btn alt sm" data-eend="${e.id}">End seat</button>` : ""}
    </div></div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${esc(d.name)}</h2>
        <p class="dim">${esc([d.language, d.level].filter(Boolean).join(" · ")
          || "course")}${d.product_id
          ? " · sold on the storefront (buying enrols)" : ""}</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn alt" id="lc-back">All courses</button>
        <button class="btn alt" id="lc-edit">Edit course</button>
        ${S.user.is_admin ? `<button class="btn alt" id="lc-arch">
            ${d.active ? "Archive" : "Reopen"}</button>
          <button class="btn alt" id="lc-del">Delete</button>` : ""}
        ${d.open_session_id
          ? `<button class="btn" id="lc-session">Open class</button>`
          : `<button class="btn" id="lc-start">Start class</button>`}
      </div>
    </div>
    ${d.active ? "" : `<div class="card"><b>Archived.</b>
      <span class="dim">The storefront hides it and nobody new can enrol;
      every transcript, class record and payslip it produced stands.
      Reopen it any time.</span></div>`}
    <div class="page-head" style="margin-top:8px">
      <h3>Lessons (${d.lessons.length})</h3>
      <button class="btn sm" id="ll-new">New lesson</button>
    </div>
    ${d.lessons.map(lesson).join("")
      || '<div class="card empty"><b>No lessons yet</b></div>'}
    <div class="page-head" style="margin-top:16px">
      <h3>Quizzes (${d.quizzes.length})</h3>
      <button class="btn sm" id="lq-new">New quiz</button>
    </div>
    ${d.quizzes.map(quiz).join("")
      || '<div class="card empty"><b>No quizzes yet</b></div>'}
    <div class="page-head" style="margin-top:16px">
      <h3>Enrolled (${d.enrollments.filter((e) => !e.until).length})</h3>
      ${S.user.is_admin
        ? '<button class="btn sm" id="le-new">Enrol someone</button>' : ""}
    </div>
    ${d.enrollments.map(seat).join("")
      || '<div class="card empty"><b>Nobody enrolled yet</b><span class="dim">Link the course to a product, or enrol by hand.</span></div>'}
    ${d.sessions && d.sessions.length ? `
      <h3 style="margin-top:16px">Classes held</h3>
      ${d.sessions.map((s) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main">
            <b>${new Date(s.started_at * 1000).toLocaleString()}</b>
            <span class="dim">${s.status}${s.minutes ? " · " + s.minutes
              + " min" : ""} · ${s.summary.attended}/${s.summary.enrolled}
              attended${s.summary.counts.late
              ? " (" + s.summary.counts.late + " late)" : ""}</span></div>
          <button class="btn alt sm" data-sroster="${s.id}">Roster</button>
        </div></div>`).join("")}` : ""}`;
  $("#lc-back").onclick = renderLearning;
  $("#lc-edit").onclick = () => courseForm(d);
  if ($("#lc-arch")) $("#lc-arch").onclick = async () => {
    try {
      await api(`/api/learning/courses/${cid}`, { body: {
        name: d.name, language: d.language || "", level: d.level || "",
        blurb: d.blurb || "", teacher_id: d.teacher_id,
        product_id: d.product_id, active: d.active ? 0 : 1 } });
      toast(d.active ? "archived — reopen any time" : "reopened");
      learningCourse(cid);
    } catch (err) { toast(err.message); }
  };
  if ($("#lc-del")) $("#lc-del").onclick = async () => {
    try {
      await api(`/api/learning/courses/${cid}`, { method: "DELETE" });
      toast("course deleted");
      renderLearning();
    } catch (err) { toast(err.message); }
  };
  if ($("#lc-start")) $("#lc-start").onclick = async () => {
    try {
      const r = await api("/api/learning/sessions",
        { body: { course_id: cid } });
      sessionRoster(r.session.id, cid);
    } catch (err) { toast(err.message); }
  };
  if ($("#lc-session")) $("#lc-session").onclick = () =>
    sessionRoster(d.open_session_id, cid);
  view().querySelectorAll("[data-sroster]").forEach((b) => b.onclick = () =>
    sessionRoster(+b.dataset.sroster, cid));
  $("#ll-new").onclick = () => lessonForm(cid, null);
  $("#lq-new").onclick = async () => {
    modal(`<h3>New quiz</h3>
      <label>Title</label><input id="qf-title">
      <label>Intro <span class="dim">(optional)</span></label>
      <textarea id="qf-intro" rows="2"></textarea>
      <label>Pass mark %</label><input id="qf-pass" type="number" value="60">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="qf-save">Create</button>
      </div>`);
    $("#qf-save").onclick = async () => {
      const title = $("#qf-title").value.trim();
      if (!title) return toast("a quiz needs a title");
      try {
        const r = await api("/api/learning/quizzes", { body: {
          course_id: cid, title, intro: $("#qf-intro").value.trim(),
          pass_mark: +$("#qf-pass").value || 60 } });
        closeModal(); quizQuestions(r.id, cid);
      } catch (err) { toast(err.message); }
    };
  };
  if ($("#le-new")) $("#le-new").onclick = async () => {
    const users = await api("/api/admin/users");
    modal(`<h3>Enrol someone</h3>
      <label>Person</label><select id="en-user">
        ${users.filter((u) => u.active).map((u) =>
          `<option value="${u.id}">${esc(u.name)} (${esc(u.role)})</option>`)
          .join("")}</select>
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="en-save">Enrol</button>
      </div>`);
    $("#en-save").onclick = async () => {
      try {
        await api(`/api/learning/courses/${cid}/enroll`,
          { body: { user_id: +$("#en-user").value } });
        closeModal(); learningCourse(cid);
      } catch (err) { toast(err.message); }
    };
  };
  view().querySelectorAll("[data-ledit]").forEach((b) => b.onclick =
    () => lessonForm(cid, +b.dataset.ledit));
  view().querySelectorAll("[data-lpub]").forEach((b) => b.onclick = async () => {
    const l = await api(`/api/learning/lessons/${b.dataset.lpub}`);
    await api(`/api/learning/lessons/${l.id}`, { body: {
      title: l.title, body: l.body, published: l.published ? 0 : 1 } });
    learningCourse(cid);
  });
  view().querySelectorAll("[data-lmove]").forEach((b) => b.onclick = async () => {
    const [lid, dir] = b.dataset.lmove.split(":");
    await api(`/api/learning/lessons/${lid}/move`,
      { body: { direction: +dir } });
    learningCourse(cid);
  });
  view().querySelectorAll("[data-qedit]").forEach((b) => b.onclick =
    () => quizQuestions(+b.dataset.qedit, cid));
  view().querySelectorAll("[data-qpub]").forEach((b) => b.onclick = async () => {
    const q = d.quizzes.find((x) => x.id === +b.dataset.qpub);
    await api(`/api/learning/quizzes/${q.id}`, { body: {
      title: q.title, intro: q.intro, pass_mark: q.pass_mark,
      published: q.published ? 0 : 1 } });
    learningCourse(cid);
  });
  view().querySelectorAll("[data-eend]").forEach((b) => b.onclick = async () => {
    if (!confirm("End this seat? Their progress is kept.")) return;
    await api(`/api/learning/enrollments/${b.dataset.eend}/end`, { body: {} });
    learningCourse(cid);
  });
}

async function sessionRoster(sid, cid) {
  /* The attendance screen, straight from the source's loop: every enrolled
     student appears; no check-in reads as absent and is never silently
     upgraded; a teacher's mark records who made it and beats self check-in. */
  const d = await api(`/api/learning/sessions/${sid}`);
  const open = d.session.status === "open";
  const STATUSES = ["present", "late", "absent", "excused"];
  const row = (r) => `<div class="card">
    <div class="doc-top">
      ${r.photo ? `<img class="roster-face" src="/media/${esc(r.photo)}"
        alt="">` : ""}
      <div class="doc-main"><b>${esc(r.name)}</b>
        <span class="dim">${r.method
          ? `${esc(r.status)} · ${r.method === "self" ? "checked in"
            : r.method === "system" ? "auto-marked at close"
            : "marked by teacher"}${r.at ? " · " + new Date(r.at * 1000)
            .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}`
          : (open ? "not here yet" : esc(r.status))}${
          r.note ? " · " + esc(r.note) : ""}</span></div>
      <span class="pill ${["present", "late"].includes(r.status) ? "ok" : ""}">${
        esc(r.status)}</span>
      ${open ? STATUSES.map((s) =>
        `<button class="btn alt sm" data-mk="${r.student_id}:${s}">${s}</button>`
      ).join("") : ""}
    </div></div>`;
  const sum = d.summary;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${esc(d.course.name)} — ${open ? "class in session"
        : "class record"}</h2>
        <p class="dim">${new Date(d.session.started_at * 1000).toLocaleString()}
          · ${d.session.minutes} min${open ? " so far" : ""}
          · late after ${d.session.late_after_min} min
          · ${sum.attended}/${sum.enrolled} attended
          (${Math.round(sum.rate * 100)}%)</p></div>
      <div style="display:flex;gap:8px">
        <button class="btn alt" id="sr-back">Course</button>
        ${open && window.QRScan && QRScan.supported()
          ? '<button class="btn alt" id="sr-scan">Scan badge</button>' : ""}
        ${open && d.session.room
          ? '<button class="btn alt" id="sr-video">Join video</button>' : ""}
        ${open ? '<button class="btn" id="sr-close">End class</button>' : ""}
      </div>
    </div>
    ${d.roster.map(row).join("")
      || '<div class="card empty"><b>Nobody is enrolled</b></div>'}`;
  $("#sr-back").onclick = () => learningCourse(cid);
  if ($("#sr-scan")) $("#sr-scan").onclick = async () => {
    // Door mode: the scanner reopens after every card until cancelled —
    // students file past, nobody touches the screen between them.
    let door = 0;
    for (;;) {
      const code = await QRScan.scan(
        { title: door ? `${door} checked in — next card`
                      : "Scan a student's ID card" });
      if (!code) break;
      try {
        const r = await api(`/api/learning/sessions/${sid}/scan`,
          { body: { code } });
        door += 1;
        toast(`${r.student.name} — ${r.status}`);
      } catch (err) { toast(err.message); }
    }
    sessionRoster(sid, cid);
  };
  if ($("#sr-video")) $("#sr-video").onclick = () =>
    classCall(d.session.room, d.course.name,
      { sid, expected: sum.enrolled + 1 });
  if ($("#sr-close")) $("#sr-close").onclick = async () => {
    if (!confirm("End the class? Students who never checked in are recorded "
      + "absent.")) return;
    await api(`/api/learning/sessions/${sid}/close`, { body: {} });
    sessionRoster(sid, cid);
  };
  view().querySelectorAll("[data-mk]").forEach((b) => b.onclick = async () => {
    const [uid, status] = b.dataset.mk.split(":");
    try {
      await api(`/api/learning/sessions/${sid}/mark`,
        { body: { student_id: +uid, status } });
      sessionRoster(sid, cid);
    } catch (err) { toast(err.message); }
  });
}

/* The teacher's side of the class video call. One mesh client for the whole
   product: /rtc-mesh.js is the storefront's ported lingua mesh, loaded here
   on demand — the ops app and the learner page must never drift apart on
   how a call negotiates. The signaling endpoints are the /learn ones; any
   signed-in community member's token opens them, and a teacher is one. */
let RTC_CALL = null;

function loadMesh() {
  return new Promise((resolve, reject) => {
    if (window.LinguaMesh) return resolve();
    const s = document.createElement("script");
    s.src = "/rtc-mesh.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("the call module didn't load"));
    document.head.appendChild(s);
  });
}

function loadCallScript(src, ready) {
  return new Promise((resolve, reject) => {
    if (ready()) return resolve();
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(src + " didn't load"));
    document.head.appendChild(s);
  });
}

async function classCall(room, title, opts) {
  const { sid = null, expected = 0 } = opts || {};
  if (RTC_CALL) return toast("You're already in a call — leave it first.");
  try { await loadMesh(); } catch (e) { return toast(e.message); }
  let cfg = { ice_servers: [] };
  try { cfg = await api("/api/learn/rtc/config"); } catch (e) {}
  cfg.hardware_concurrency = navigator.hardwareConcurrency || 0;
  // Which transport: the enrolled roster size decides on the FIRST join, so
  // a full class starts on the SFU instead of thrashing a mesh mid-call.
  let makeCall = (o) => window.LinguaMesh.createMesh(o);
  try {
    await loadCallScript("/rtc-sfu.js", () => window.LinguaSfu);
    if (window.LinguaSfu.chooseTransport(cfg, expected || 2) === "sfu") {
      makeCall = (o) => window.LinguaSfu.createSfu({ ...o, config: cfg });
    }
  } catch (e) { /* no sfu module: the mesh carries on */ }
  const STREAMS = new Map();          // for the class recorder's compositor
  let composer = null, callRec = null;
  const ov = document.createElement("div");
  ov.id = "ops-call";
  ov.innerHTML = `<div class="ops-call-head">
      <b>${esc(title || "Class video")}</b>
      <span class="dim" id="opsc-state">connecting…</span>
      <span style="flex:1"></span>
      ${sid ? '<button class="btn alt sm" id="opsc-rec">Record class</button>' : ""}
      <button class="btn alt sm" id="opsc-mic">Mute</button>
      <button class="btn alt sm" id="opsc-cam">Camera off</button>
      <button class="btn sm" id="opsc-leave">Leave</button>
    </div>
    <div class="ops-call-grid" id="opsc-grid"></div>`;
  document.body.appendChild(ov);
  const grid = $("#opsc-grid");
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
  const meshApi = async (path, body) => {
    const r = await fetch(path, {
      method: body !== undefined ? "POST" : "GET",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + S.user.token },
      body: body !== undefined ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch (e) {}
      throw new Error(m);
    }
    return r.json();
  };
  RTC_CALL = makeCall({
    room, api: meshApi, iceServers: cfg.ice_servers,
    onLocal: (s) => { tile("me").srcObject = s; STREAMS.set("me", s); },
    onRemote: (id, s) => { tile(id).srcObject = s; STREAMS.set(id, s); },
    onLeave: (id) => {
      STREAMS.delete(id);
      const v = grid.querySelector(`[data-peer="${id}"]`);
      if (v) v.remove();
    },
    onState: (m) => { const el = $("#opsc-state"); if (el) el.textContent = m; },
    onMedia: (got) => { if (got.detail) toast(got.detail); },
    onError: () => {},
  });
  const stopRecording = async (upload) => {
    const rec = callRec;
    callRec = null;
    const btn = $("#opsc-rec");
    if (btn) btn.textContent = "Record class";
    if (!rec) return;
    const blob = await rec.stop();
    if (composer) { composer.stop(); composer = null; }
    if (upload && blob && blob.size && sid) {
      toast("Uploading the recording…");
      try {
        const r = await fetch(`/api/learning/sessions/${sid}/recording`, {
          method: "POST",
          headers: { "Content-Type": blob.type || "video/webm",
                     "X-Filename": rec.filename("class"),
                     Authorization: "Bearer " + S.user.token },
          body: blob });
        if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
        toast("Recording saved — learners find it on the calendar");
      } catch (err) { toast(err.message); }
    }
    rec.discard();
  };
  if ($("#opsc-rec")) $("#opsc-rec").onclick = async () => {
    if (callRec) return stopRecording(true);
    try { await loadCallScript("/rtc-compose.js", () => window.LinguaCompose); }
    catch (e) { return toast(e.message); }
    if (!window.LinguaCompose.composeSupported()) {
      return toast("this browser cannot record a composed call");
    }
    // Records what THIS browser received: close the tab and it stops; a
    // participant whose video never arrived is not in it.
    composer = window.LinguaCompose.composeCall({
      getStreams: () => [...STREAMS.values()] });
    callRec = window.LinguaCompose.createRecorder({
      kind: "video", maxSeconds: 4 * 3600, source: composer.stream,
      onTick: (s) => {
        const btn = $("#opsc-rec");
        if (btn) btn.textContent = "Stop " + window.LinguaCompose.fmtSecs(s);
      },
      onError: (m) => toast(m),
    });
    try { await callRec.start(); } catch (err) { return toast(err.message); }
    // Some browsers accept a canvas stream, start a recorder, and emit
    // nothing. Four seconds of zero bytes = a dead recorder, said plainly.
    setTimeout(() => {
      if (callRec && callRec.bytes === 0) {
        toast("this browser is producing no recording data — the class is"
          + " still running, but nothing is being recorded");
        stopRecording(false);
      }
    }, 4000);
  };
  const close = () => {
    if (callRec) stopRecording(true);
    if (composer) { composer.stop(); composer = null; }
    if (RTC_CALL) RTC_CALL.leave();
    RTC_CALL = null;
    ov.remove();
  };
  $("#opsc-leave").onclick = close;
  $("#opsc-mic").onclick = (e) => {
    const on = RTC_CALL && RTC_CALL.toggle("audio");
    e.target.textContent = on ? "Mute" : "Unmute";
  };
  $("#opsc-cam").onclick = (e) => {
    const on = RTC_CALL && RTC_CALL.toggle("video");
    e.target.textContent = on ? "Camera off" : "Camera on";
  };
  try { await RTC_CALL.join(); } catch (e) { toast(e.message); close(); }
}

async function lessonForm(cid, lid) {
  const l = lid ? await api(`/api/learning/lessons/${lid}`) : null;
  const mats = (l && l.materials) || [];
  const player = (m) => m.kind === "audio"
    ? `<audio controls preload="metadata" src="/media/${m.path}"></audio>`
    : m.kind === "video"
      ? `<video controls preload="metadata" src="/media/${m.path}"
          style="max-width:100%;border-radius:8px"></video>`
      : `<img src="/media/${m.path}" style="max-width:100%;border-radius:8px">`;
  modal(`<h3>${l ? "Edit lesson" : "New lesson"}</h3>
    <label>Title</label><input id="lf-title" value="${esc((l && l.title) || "")}">
    <label>Body <span class="dim">(markdown: # headings, **bold**, - lists,
      \`\`\` code)</span></label>
    <textarea id="lf-body" rows="14" style="font-family:monospace">${
      esc((l && l.body) || "")}</textarea>
    ${l ? `<h4 style="margin-top:12px">Drills
        <span class="dim">(recorded audio or video on this lesson)</span></h4>
      ${mats.map((m) => `<div class="doc-top" style="margin:6px 0">
        <div class="doc-main">${player(m)}</div>
        <button class="btn alt sm" data-mdel="${m.id}">Delete</button>
      </div>`).join("") || '<p class="dim">None yet.</p>'}
      <div style="display:flex;gap:8px;align-items:center">
        <button class="btn alt sm" id="lf-recaudio">Record audio drill</button>
        <button class="btn alt sm" id="lf-recvideo">Record video drill</button>
        <span class="dim" id="lf-recstate"></span>
      </div>` : ""}
    <div class="modal-acts">
      ${l ? '<button class="btn alt" id="lf-del" style="margin-right:auto">Delete</button>' : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="lf-save">Save</button>
    </div>`, "wide");
  if (l) {
    let rec = null;
    const state = (m) => { const el = $("#lf-recstate"); if (el) el.textContent = m; };
    const recDrill = async (kind, btn) => {
      try { await loadCallScript("/rtc-compose.js", () => window.LinguaCompose); }
      catch (e) { return toast(e.message); }
      if (rec) {                                 // second press = stop + upload
        const blob = await rec.stop();
        const stem = rec.filename("drill");
        rec.discard(); rec = null;
        $("#lf-recaudio").textContent = "Record audio drill";
        $("#lf-recvideo").textContent = "Record video drill";
        if (!blob || !blob.size) return state("nothing was recorded");
        state("uploading…");
        try {
          const r = await fetch(`/api/learning/lessons/${l.id}/material`, {
            method: "POST",
            headers: { "Content-Type": blob.type || "application/octet-stream",
                       "X-Filename": stem,
                       Authorization: "Bearer " + S.user.token },
            body: blob });
          if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
          closeModal(); lessonForm(cid, l.id);
        } catch (err) { state(err.message); }
        return;
      }
      rec = window.LinguaCompose.createRecorder({ kind,
        onTick: (s) => state("recording " + window.LinguaCompose.fmtSecs(s)),
        onError: (m) => state(m) });
      try {
        await rec.start();
        btn.textContent = "Stop and attach";
      } catch (err) { state(err.message); rec = null; }
    };
    $("#lf-recaudio").onclick = (e) => recDrill("audio", e.target);
    $("#lf-recvideo").onclick = (e) => recDrill("video", e.target);
    document.querySelectorAll("[data-mdel]").forEach((b) => b.onclick =
      async () => {
        await api(`/api/learning/materials/${b.dataset.mdel}/delete`,
          { body: {} });
        closeModal(); lessonForm(cid, l.id);
      });
  }
  $("#lf-save").onclick = async () => {
    const title = $("#lf-title").value.trim();
    if (!title) return toast("a lesson needs a title");
    const body = { course_id: cid, title, body: $("#lf-body").value,
      published: l ? l.published : 0 };
    try {
      if (l) await api(`/api/learning/lessons/${l.id}`, { body });
      else await api("/api/learning/lessons", { body });
      closeModal(); learningCourse(cid);
    } catch (err) { toast(err.message); }
  };
  if (l && $("#lf-del")) $("#lf-del").onclick = async () => {
    if (!confirm(`Delete "${l.title}"?`)) return;
    await api(`/api/learning/lessons/${l.id}/delete`, { body: {} });
    closeModal(); learningCourse(cid);
  };
}

async function quizQuestions(qid, cid) {
  const q = await api(`/api/learning/quizzes/${qid}`);
  const row = (x, i) => `<div class="card">
    <div class="doc-top">
      <div class="doc-main"><b>${i + 1}. ${esc(x.prompt)}</b>
        <span class="dim">${x.kind} · ${x.points} pt${x.points === 1 ? "" : "s"}${
          x.kind !== "text" ? " · " + x.choices.map((c, j) =>
            x.answer.includes(j) ? "✓" + esc(c) : esc(c)).join(" / ")
          : x.accepted.length ? " · accepts: " + x.accepted.map(esc).join(", ")
          : " · marked by a teacher"}</span></div>
      <button class="btn alt sm" data-xdel="${x.id}">Delete</button>
    </div></div>`;
  modal(`<h3>${esc(q.title)}</h3>
    <p class="dim">Learners never receive the answer key — it is stripped
      server-side before the quiz leaves the building.</p>
    ${q.questions.map(row).join("") || '<p class="dim">No questions yet.</p>'}
    <h4 style="margin-top:14px">Add a question</h4>
    <div class="row2">
      <div><label>Kind</label><select id="nq-kind">
        <option value="choice">single choice</option>
        <option value="multi">multiple answers (partial credit)</option>
        <option value="text">written answer</option>
        <option value="speaking">spoken answer (teacher marks it)</option>
        <option value="video">video answer (teacher marks it)</option></select></div>
      <div><label>Points</label><input id="nq-points" type="number" value="1"></div>
    </div>
    <label>Prompt</label><input id="nq-prompt">
    <div id="nq-choice-wrap">
      <label>Options <span class="dim">(one per line; prefix the correct
        one(s) with *)</span></label>
      <textarea id="nq-choices" rows="4" placeholder="*hola&#10;mesa&#10;buenos días"></textarea>
    </div>
    <div id="nq-text-wrap" style="display:none">
      <label>Accepted answers <span class="dim">(one per line; case, accents
        and punctuation are forgiven; empty = a teacher marks it)</span></label>
      <textarea id="nq-accepted" rows="3"></textarea>
    </div>
    <div class="modal-acts">
      <button class="btn alt" data-close>Done</button>
      <button class="btn" id="nq-add">Add question</button>
    </div>`, "wide");
  $("#nq-kind").onchange = () => {
    const kind = $("#nq-kind").value;
    const recorded = kind === "speaking" || kind === "video";
    $("#nq-choice-wrap").style.display =
      (kind === "text" || recorded) ? "none" : "";
    $("#nq-text-wrap").style.display = kind === "text" ? "" : "none";
  };
  $("#nq-add").onclick = async () => {
    const kind = $("#nq-kind").value;
    const lines = $("#nq-choices").value.split("\n")
      .map((s) => s.trim()).filter(Boolean);
    const body = { kind, prompt: $("#nq-prompt").value.trim(),
      points: +$("#nq-points").value || 1,
      choices: lines.map((s) => s.replace(/^\*/, "")),
      answer: lines.map((s, i) => s.startsWith("*") ? i : -1)
        .filter((i) => i >= 0),
      accepted: $("#nq-accepted").value.split("\n")
        .map((s) => s.trim()).filter(Boolean) };
    if (kind === "text" || kind === "speaking" || kind === "video") {
      body.choices = []; body.answer = [];
    }
    if (kind !== "text") body.accepted = [];
    try {
      await api(`/api/learning/quizzes/${qid}/questions`, { body });
      quizQuestions(qid, cid);
    } catch (err) { toast(err.message); }
  };
  // the buttons live in the modal, which hangs off <body>, not the view
  document.querySelectorAll("[data-xdel]").forEach((b) => b.onclick = async () => {
    await api(`/api/learning/questions/${b.dataset.xdel}/delete`, { body: {} });
    quizQuestions(qid, cid);
  });
}

async function gradeAttempt(aid) {
  const d = await api(`/api/learning/attempts/${aid}`);
  const item = (x, i) => {
    const recorded = x.kind === "speaking" || x.kind === "video";
    const needsMark = (x.kind === "text" && !x.accepted.length)
      || (recorded && x.material);
    return `<div class="card">
      <b>${i + 1}. ${esc(x.prompt)}</b>
      <span class="dim">(${x.points} pt${x.points === 1 ? "" : "s"})</span>
      <p style="margin:6px 0">${recorded
        ? (x.material
          ? (x.material.kind === "audio"
            ? `<audio controls preload="metadata"
                src="/media/${x.material.path}"></audio>`
            : `<video controls preload="metadata" src="/media/${x.material.path}"
                style="max-width:100%;border-radius:8px"></video>`)
          : "<i class='dim'>nothing recorded</i>")
        : x.kind === "text"
        ? (x.text ? esc(x.text) : "<i class='dim'>no answer</i>")
        : esc(x.chosen.map((j) => x.choices[j]).join(", ") || "no answer")}</p>
      ${needsMark ? `
        <div class="row2">
          <div><label>Points (0–${x.points})</label>
            <input type="number" id="aw-${x.question_id}" min="0"
              max="${x.points}" value="${x.awarded ?? ""}"></div>
          <div><label>Feedback</label>
            <input id="fb-${x.question_id}" value="${esc(x.feedback)}"></div>
        </div>
        <button class="btn sm" data-award="${x.question_id}"
          style="margin-top:6px">Save mark</button>`
        : `<span class="dim">${x.awarded !== null
          ? "marked: " + x.awarded
          : recorded ? "nothing recorded — scores zero" : "auto-graded"}</span>`}
    </div>`;
  };
  modal(`<h3>Grading — ${esc(d.student)}</h3>
    <p class="dim">${esc(d.quiz.title)} ·
      ${d.grade.pending} answer${d.grade.pending === 1 ? "" : "s"} pending ·
      provisional ${d.grade.percent}% (the learner sees no number until it
      is final)</p>
    ${d.items.map(item).join("")}
    <div class="modal-acts"><button class="btn" data-close>Done</button></div>`,
    "wide");
  document.querySelectorAll("[data-award]").forEach((b) => b.onclick =
    async () => {
      const qidn = +b.dataset.award;
      try {
        const g = await api(`/api/learning/attempts/${aid}/grade`, { body: {
          question_id: qidn, awarded: +$(`#aw-${qidn}`).value || 0,
          feedback: $(`#fb-${qidn}`).value } });
        toast(g.is_final ? "Attempt settled — the learner has their score"
          : "Saved — " + g.pending + " still pending");
        if (g.is_final) { closeModal(); renderLearning(); }
      } catch (err) { toast(err.message); }
    });
}
