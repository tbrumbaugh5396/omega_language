// ---------- onboarding ----------
/* Hiring wrote a six-line list when it opened an account, which was right
   and was not enough: the same six went to a driver and a teacher, nothing
   had a date, so nothing could be late. A template per role, steps that
   carry a day, and a step that can be waiting on a document — because
   "we asked for their right-to-work" and "we have it" are different
   states and only one of them is done. */
async function renderOnboarding() {
  const d = await api("/api/onboarding");
  const day = 86400;
  const now = Date.now() / 1000;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Onboarding</h2>
        <p class="dim">Who is finding their feet, what is still to do, and
          what each role's first fortnight looks like.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="onb-start">Start somebody</button>
        <button class="btn" id="onb-template">New template</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">In progress</span>
        <b>${d.counts.in_progress}</b></div>
      <div class="card tile"><span class="dim">Overdue steps</span>
        <b>${d.counts.overdue}</b></div>
      <div class="card tile"><span class="dim">Waiting on a document</span>
        <b>${d.counts.waiting}</b></div>
      <div class="card tile"><span class="dim">Templates</span>
        <b>${d.templates.length}</b></div>
    </div>
    <h3>People</h3>
    ${d.journeys.length ? d.journeys.map((j) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(j.name)}</b>
          <span class="dim">${esc(j.role)} · started ${fmtDate(j.starts)}
            ${j.complete ? "" : `· next: ${esc(j.next)}`}</span></div>
        <span class="pill ${j.complete ? "ok" : ""}">${j.done} of ${j.total}</span>
        ${j.overdue ? `<span class="pill bad">${j.overdue} overdue</span>` : ""}
        ${j.waiting_on_documents ? `<span class="pill warn">${j.waiting_on_documents} waiting on a document</span>` : ""}
      </div>
      <div class="perm-grid">${j.tasks.map((t) => `<label class="perm">
        <input type="checkbox" data-onbtask="${t.id}"
          data-needsdoc="${t.needs_document && !t.document_id ? "1" : ""}"
          ${t.done_at ? "checked" : ""}>
        <span><b>${esc(t.title)}</b><small>${t.done_at
          ? `done by ${esc(t.done_by)} ${fmtAgo(t.done_at)}`
          : `${t.due ? (t.due < now ? "overdue since " : "due ") + fmtDate(t.due) : "no date"}${
              t.tab ? ` · on the ${esc(t.tab)} screen` : ""}${
              t.needs_document && !t.document_id ? " · needs a document" : ""}`}</small></span>
      </label>`).join("")}</div>
    </div>`).join("")
      : emptyState("list", "Nobody is onboarding",
          "Hiring starts somebody automatically. You can also start a "
          + "person who was already here on a list.")}
    <h3>Templates</h3>
    ${d.templates.map((t) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(t.name)}</b>
          <span class="dim">${t.role ? "for " + esc(t.role) : "for anybody"}${
            t.note ? " · " + esc(t.note) : ""}</span></div>
        <span class="pill ${t.active ? "ok" : ""}">${t.active ? "in use" : "off"}</span>
        <button class="btn alt sm" data-onbstep="${t.id}">Add a step</button>
        <button class="btn alt sm" data-onbedit="${t.id}">Edit</button>
      </div>
      ${t.steps.length ? `<div class="tablewrap"><table>
        <thead><tr><th>day</th><th>step</th><th>on</th><th>document</th><th></th></tr></thead>
        <tbody>${t.steps.map((s) => `<tr>
          <td class="dim">${s.days_after === 0 ? "day one" : "day " + (s.days_after + 1)}</td>
          <td>${esc(s.title)}</td><td class="dim">${esc(s.tab || "")}</td>
          <td>${s.needs_document ? '<span class="pill warn">needed</span>' : ""}</td>
          <td><button class="btn alt sm" data-onbdel="${s.id}">Remove</button></td>
        </tr>`).join("")}</tbody></table></div>`
        : '<p class="dim">No steps yet.</p>'}
    </div>`).join("")}`;

  view().querySelectorAll("[data-onbtask]").forEach((cb) => cb.onchange = async () => {
    let documentId = 0;
    if (cb.dataset.needsdoc && cb.checked) {
      const answer = prompt("This step is waiting on a document. Enter the "
        + "document's id from the vault, or cancel and take the requirement "
        + "off the template.");
      if (!answer) { cb.checked = false; return; }
      documentId = +answer || 0;
    }
    try {
      await api(`/api/onboarding/tasks/${cb.dataset.onbtask}/done`,
                { body: { document_id: documentId } });
      renderOnboarding();
    } catch (e) { toast(e.message); cb.checked = !cb.checked; }
  });
  const templateForm = (t) => {
    modal(`<h3>${t ? "Edit" : "New"} template</h3>
      <label>Name</label><input id="onb-name" value="${esc(t ? t.name : "")}"
        placeholder="Driver">
      <label>For which role <span class="dim">(blank = anybody)</span></label>
      <select id="onb-role"><option value="">anybody</option>
        ${d.roles.map((r) => `<option value="${r}" ${t && t.role === r ? "selected" : ""}>${r}</option>`).join("")}</select>
      <label>Note</label><input id="onb-note" value="${esc(t ? t.note : "")}">
      <label class="perm"><input type="checkbox" id="onb-active"
        ${!t || t.active ? "checked" : ""}><span>In use</span></label>
      <p><button class="btn" id="onb-tsave">Save</button></p>`);
    $("#onb-tsave").onclick = async () => {
      try {
        await api("/api/onboarding/templates", { body: {
          id: t ? t.id : 0, name: $("#onb-name").value, role: $("#onb-role").value,
          note: $("#onb-note").value, active: $("#onb-active").checked } });
        closeModal(); renderOnboarding();
      } catch (e) { toast(e.message); }
    };
  };
  $("#onb-template").onclick = () => templateForm(null);
  view().querySelectorAll("[data-onbedit]").forEach((b) => b.onclick = () =>
    templateForm(d.templates.find((t) => t.id === +b.dataset.onbedit)));
  view().querySelectorAll("[data-onbstep]").forEach((b) => b.onclick = () => {
    const t = d.templates.find((x) => x.id === +b.dataset.onbstep);
    modal(`<h3>Add a step to ${esc(t.name)}</h3>
      <label>What</label><input id="onb-stitle" placeholder="Licence on file">
      <div class="row2">
        <div><label>Days after they start</label>
          <input id="onb-sdays" type="number" min="0" max="365" value="0"></div>
        <div><label>Done on which screen</label><input id="onb-stab" placeholder="docs"></div>
      </div>
      <label class="perm"><input type="checkbox" id="onb-sdoc">
        <span><b>Waiting on a document</b><small>it cannot be ticked until
          one is attached, which is the difference between asking and
          having</small></span></label>
      <p><button class="btn" id="onb-ssave">Add</button></p>`);
    $("#onb-ssave").onclick = async () => {
      try {
        await api(`/api/onboarding/templates/${t.id}/steps`, { body: {
          title: $("#onb-stitle").value, tab: $("#onb-stab").value,
          days_after: +$("#onb-sdays").value || 0,
          needs_document: $("#onb-sdoc").checked,
          position: t.steps.length } });
        closeModal(); renderOnboarding();
      } catch (e) { toast(e.message); }
    };
  });
  view().querySelectorAll("[data-onbdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this step? Lists already started keep it.")) return;
    await api(`/api/onboarding/steps/${b.dataset.onbdel}`, { method: "DELETE" });
    renderOnboarding();
  });
  $("#onb-start").onclick = () => {
    modal(`<h3>Start somebody</h3>
      <label>Who</label><select id="onb-who">${d.staff.map((s) =>
        `<option value="${s.id}">${esc(s.name)} · ${esc(s.role)}</option>`).join("")}</select>
      <label>On which list</label><select id="onb-tmpl">
        <option value="0">the one for their role</option>
        ${d.templates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
      <label>Their start date <span class="dim">(the dates count from it)</span></label>
      <input id="onb-starts" type="date">
      <p><button class="btn" id="onb-go">Start</button></p>`);
    $("#onb-go").onclick = async () => {
      try {
        const r = await api("/api/onboarding/start", { body: {
          user_id: +$("#onb-who").value, template_id: +$("#onb-tmpl").value,
          starts: $("#onb-starts").value
            ? new Date($("#onb-starts").value).getTime() / 1000 : 0 } });
        closeModal();
        toast(r.already ? "they were already on that list" : `${r.steps} steps`);
        renderOnboarding();
      } catch (e) { toast(e.message); }
    };
  };
}
