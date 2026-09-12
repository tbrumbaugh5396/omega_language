// ---------- health: patients, their records, and the day's queue ----------
/* The front desk's screen: who is booked today and where each of them
   is in the queue, then the patients, then one record open — insurance
   on file, allergies and medications, the visits, the files, and who
   has looked. Every open of a record is logged on the server; the
   screen shows that log, because the question a patient asks is not
   "what is in my record" but "who has read it". */
let HEA_SEL = 0;

async function renderHealth(q = "") {
  const d = await api(`/api/health${q ? "?q=" + encodeURIComponent(q) : ""}`);
  const st = { arrived: "arrived", waiting: "waiting", with_practitioner: "with practitioner",
    done: "seen", left: "left" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Patients</h2>
        <p class="dim">The day's queue, the patients, and one record at a time.
          Not a certified health record and not a billing system: a locked
          cabinet that logs who opened it.</p></div>
      <div class="top-actions">
        <input id="hea-q" placeholder="find a patient" value="${esc(q)}" aria-label="find a patient">
        <button class="btn alt" id="hea-desk">Front desk view</button>
        <button class="btn" id="hea-new">Add a patient</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Patients</span><b>${d.counts.patients}</b></div>
      <div class="card tile"><span class="dim">Seen in 30 days</span><b>${d.counts.seen_30d}</b></div>
      <div class="card tile"><span class="dim">In the waiting room</span><b>${d.counts.waiting}</b></div>
    </div>
    <h3>Today</h3>
    <div class="card" id="hea-queue">${heaQueue(d, st)}</div>
    <div class="hea-split">
      <div class="card hea-list">
        ${d.patients.length ? `<ul class="hea-people">${d.patients.map((p) => `<li data-hea="${p.id}" class="${p.id === HEA_SEL ? "on" : ""}">
          <b>${esc(p.name)}</b> <span class="dim">${p.mrn ? "#" + esc(p.mrn) + " · " : ""}${p.birth_date ? esc(p.birth_date) + " · " : ""}${
            p.last_seen ? "seen " + fmtDate(p.last_seen) : "never seen"}${p.policies ? " · insured" : ""}</span></li>`).join("")}</ul>`
          : `<p class="dim">No patients yet. Add one from the customer book; a patient is a person with a record beside them.</p>`}
      </div>
      <div class="card hea-record" id="hea-record"><p class="dim">Open a patient to see their record.</p></div>
    </div>`;
  $("#hea-q").onkeydown = (e) => { if (e.key === "Enter") renderHealth(e.target.value.trim()); };
  $("#hea-new").onclick = () => heaPickPerson();
  $("#hea-desk").onclick = () => heaDesk(d, st);
  view().querySelectorAll("[data-hea]").forEach((li) => li.onclick = () => heaOpen(+li.dataset.hea, d));
  heaQueueWire(d, st);
  if (HEA_SEL) heaOpen(HEA_SEL, d);
}

function heaQueue(d, st) {
  if (!d.queue.length) return `<p class="dim">Nobody booked today. Appointments come from Bookings; walk-ins are booked there too.</p>`;
  return `<div class="tablewrap"><table><thead><tr><th>time</th><th>who</th><th>for</th><th>with</th><th>where</th><th></th></tr></thead>
    <tbody>${d.queue.map((r) => `<tr class="${r.checkin_state === "done" || r.checkin_state === "left" ? "dim" : ""}">
      <td>${new Date(r.starts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</td>
      <td>${r.user_id ? `<a data-heaopen="${r.user_id}">${esc(r.name)}</a>` : esc(r.name)}</td>
      <td class="dim">${esc(r.service || "")}</td>
      <td class="dim">${esc(r.practitioner || "")}</td>
      <td>${r.checkin_state ? `<span class="pill${r.checkin_state === "with_practitioner" ? " ok" : r.checkin_state === "done" ? "" : " warn"}">${st[r.checkin_state]}</span>${
        r.waited_min ? ` <span class="dim">${r.waited_min} min</span>` : ""}${r.method === "portal" ? ' <span class="dim">self</span>' : ""}` : '<span class="dim">not arrived</span>'}</td>
      <td><select data-heast="${r.id}" aria-label="queue state"><option value="">move…</option>
        ${d.checkin_states.map((s) => `<option value="${s}">${st[s]}</option>`).join("")}</select></td>
    </tr>`).join("")}</tbody></table></div>`;
}

function heaQueueWire(d, st) {
  view().querySelectorAll("[data-heast]").forEach((sel) => sel.onchange = async () => {
    if (!sel.value) return;
    try { await api("/api/health/checkin", { body: { appointment_id: +sel.dataset.heast, state: sel.value } }); renderHealth(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-heaopen]").forEach((a) => a.onclick = () => heaOpen(+a.dataset.heaopen, d));
}

/* The queue alone, large, for the screen at the counter. It refreshes
   itself every half minute so the desk sees a portal check-in land. */
function heaDesk(d, st) {
  modal(`<h3>Front desk</h3><div id="hea-deskq">${heaQueue(d, st)}</div>
    <p class="dim">Refreshes every 30 seconds. Close to go back.</p>`, "wide");
  let timer = setInterval(async () => {
    if (!$("#hea-deskq")) return clearInterval(timer);
    const fresh = await api("/api/health").catch(() => null);
    if (fresh) { $("#hea-deskq").innerHTML = heaQueue(fresh, st); }
  }, 30000);
  modalBody().querySelectorAll("[data-heast]").forEach((sel) => sel.onchange = async () => {
    if (!sel.value) return;
    try { await api("/api/health/checkin", { body: { appointment_id: +sel.dataset.heast, state: sel.value } });
      const fresh = await api("/api/health"); $("#hea-deskq").innerHTML = heaQueue(fresh, st); } catch (e) { toast(e.message); }
  });
}

function heaPickPerson() {
  modal(`<h3>Add a patient</h3>
    <p class="dim">A patient is a person in the customer book with a record beside them.
      Find them; if they are not there yet, add them as a customer first.</p>
    <input id="hea-pq" placeholder="name or email"><div id="hea-pr"></div>`);
  $("#hea-pq").oninput = async () => {
    const q = $("#hea-pq").value.trim();
    if (q.length < 2) return;
    const r = await api(`/api/health/people?q=${encodeURIComponent(q)}`);
    $("#hea-pr").innerHTML = r.people.length ? `<ul class="hea-people">${r.people.map((p) => `<li data-heapick="${p.id}"><b>${esc(p.name)}</b> <span class="dim">${esc(p.email || "")}</span></li>`).join("")}</ul>` : `<p class="dim">nobody by that name</p>`;
    $("#hea-pr").querySelectorAll("[data-heapick]").forEach((li) => li.onclick = async () => {
      await api(`/api/health/patients/${li.dataset.heapick}`, { body: {} });
      closeModal(); HEA_SEL = +li.dataset.heapick; renderHealth();
    });
  };
}

async function heaOpen(uid, d) {
  HEA_SEL = uid;
  view().querySelectorAll("[data-hea]").forEach((li) => li.classList.toggle("on", +li.dataset.hea === uid));
  let r;
  try { r = await api(`/api/health/patients/${uid}`); } catch (e) { toast(e.message); return; }
  const p = r.patient;
  const box = $("#hea-record");
  box.innerHTML = `
    <div class="hea-head">
      <div><b>${esc(r.person.name)}</b> <span class="dim">${p.mrn ? "#" + esc(p.mrn) + " · " : ""}${
        p.birth_date ? esc(p.birth_date) + (p.age != null ? ` (${p.age})` : "") + " · " : ""}${esc(p.sex || "")}</span>
        ${p.consent_at ? `<span class="pill ok">consent ${fmtDate(p.consent_at)}</span>` : '<span class="pill warn">no consent recorded</span>'}
        ${p.portal ? "" : '<span class="pill">portal off</span>'}</div>
      <span><button class="btn alt sm" id="hea-edit">Edit record</button>
        <button class="btn alt sm" id="hea-ins">Add insurance</button>
        <button class="btn sm" id="hea-visit">New visit</button></span>
    </div>
    <div class="hea-grid">
      <div><span class="dim">Allergies</span><div class="${p.allergies ? "low" : "dim"}">${esc(p.allergies || "none recorded")}</div></div>
      <div><span class="dim">Medications</span><div>${esc(p.medications || "none recorded")}</div></div>
      <div><span class="dim">Conditions</span><div>${esc(p.conditions || "none recorded")}</div></div>
      <div><span class="dim">Emergency contact</span><div>${esc(p.emergency_contact || "—")}</div></div>
      <div><span class="dim">Practitioner</span><div>${esc(p.primary_practitioner || "—")}</div></div>
      <div><span class="dim">Phone</span><div>${esc(p.phone || "—")}</div></div>
    </div>
    ${p.notes ? `<p class="dim">Desk notes: ${esc(p.notes)}</p>` : ""}
    <h4>Insurance</h4>
    ${r.insurance.length ? `<ul class="hea-ins">${r.insurance.map((i) => `<li>
      <b>${esc(i.payer)}</b> ${i.plan ? esc(i.plan) : ""} <span class="dim">member ${esc(i.member_id || "—")}${i.group_no ? " · group " + esc(i.group_no) : ""}${
        i.relationship !== "self" ? " · " + esc(i.relationship) + " of " + esc(i.subscriber) : ""}${i.copay_cents ? " · copay " + money(i.copay_cents) : ""}${
        i.expires ? " · to " + esc(i.expires) : ""}</span>
      ${i.primary_policy ? '<span class="pill">primary</span>' : ""}
      ${i.verified_at ? `<span class="pill ok">verified ${fmtDate(i.verified_at)}</span>` : `<a class="dim" data-heaverify="${i.id}">mark verified</a>`}
      <a class="dim" data-heainsedit="${i.id}">edit</a> <a class="dim" data-heainsdel="${i.id}">remove</a></li>`).join("")}</ul>`
      : '<p class="dim">None on file.</p>'}
    <h4>Appointments</h4>
    ${r.appointments.length ? `<ul class="hea-ins">${r.appointments.map((a) => `<li>${fmtDate(a.starts)} ${new Date(a.starts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
      <span class="dim">${esc(a.service || "")}</span> ${a.checkin_state ? `<span class="pill">${esc(a.checkin_state)}</span>` : ""}</li>`).join("")}</ul>` : '<p class="dim">Nothing booked.</p>'}
    <h4>Visits and notes</h4>
    ${r.encounters.length ? r.encounters.map((e) => `<div class="hea-enc">
      <div><b>${fmtDate(e.at)}</b> <span class="pill">${esc(e.kind)}</span> <span class="dim">${esc(e.practitioner)}</span>
        ${e.shared ? "" : '<span class="pill warn">not shared</span>'}
        <a class="dim" data-heaencedit="${e.id}">edit</a></div>
      ${e.reason ? `<div><b>${esc(e.reason)}</b></div>` : ""}
      ${Object.keys(e.vitals).length ? `<div class="dim">${Object.entries(e.vitals).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}</div>` : ""}
      ${e.notes ? `<div class="hea-notes">${esc(e.notes)}</div>` : ""}
      ${e.plan ? `<div><span class="dim">Plan:</span> ${esc(e.plan)}</div>` : ""}
      ${e.followup_at ? `<div class="dim">follow up ${fmtDate(e.followup_at)}</div>` : ""}
    </div>`).join("") : '<p class="dim">No visits recorded.</p>'}
    <h4>Files</h4>
    ${r.files.length ? `<ul class="hea-ins">${r.files.map((f) => `<li>
      <a href="/api/health/patients/${uid}/files/${f.id}?t=${encodeURIComponent(S.user.token)}" target="_blank" rel="noopener">${esc(f.name)}</a>
      <span class="dim">${esc(f.kind)} · ${(f.bytes / 1024).toFixed(0)} KB · ${esc(f.by_name)} · ${fmtDate(f.created_at)}</span>
      ${f.shared ? "" : '<span class="pill warn">not shared</span>'} <a class="dim" data-heafdel="${f.id}">remove</a></li>`).join("")}</ul>` : ""}
    <div class="tk-add"><select id="hea-fkind">${d.file_kinds.map((k) => `<option value="${k}">${k}</option>`).join("")}</select>
      <label class="chk"><input type="checkbox" id="hea-fshared" checked> patient may see it</label>
      <label class="btn alt sm">Attach a file<input type="file" hidden id="hea-file"></label></div>
    <details><summary class="dim">Who has looked (${r.access.length})</summary>
      ${r.access.map((a) => `<div class="dim">${fmtDate(a.at)} · ${esc(a.by_name)} · ${esc(a.what)}</div>`).join("")}</details>`;
  const redo = () => heaOpen(uid, d);
  $("#hea-edit").onclick = () => heaPatientForm(uid, r, d, redo);
  $("#hea-ins").onclick = () => heaPolicyForm(uid, null, d, redo);
  $("#hea-visit").onclick = () => heaEncounterForm(uid, null, d, redo);
  box.querySelectorAll("[data-heainsedit]").forEach((a) => a.onclick = () =>
    heaPolicyForm(uid, r.insurance.find((i) => i.id === +a.dataset.heainsedit), d, redo));
  box.querySelectorAll("[data-heaverify]").forEach((a) => a.onclick = async () => {
    const i = r.insurance.find((x) => x.id === +a.dataset.heaverify);
    await api(`/api/health/patients/${uid}/insurance`, { body: { ...i, primary_policy: !!i.primary_policy, verified: true } }); redo();
  });
  box.querySelectorAll("[data-heainsdel]").forEach((a) => a.onclick = async () => {
    if (!confirm("Remove this policy from the record?")) return;
    await api(`/api/health/patients/${uid}/insurance/${a.dataset.heainsdel}`, { method: "DELETE" }); redo();
  });
  box.querySelectorAll("[data-heaencedit]").forEach((a) => a.onclick = () =>
    heaEncounterForm(uid, r.encounters.find((e) => e.id === +a.dataset.heaencedit), d, redo));
  box.querySelectorAll("[data-heafdel]").forEach((a) => a.onclick = async () => {
    if (!confirm("Remove this file from the record?")) return;
    await api(`/api/health/patients/${uid}/files/${a.dataset.heafdel}`, { method: "DELETE" }); redo();
  });
  $("#hea-file").onchange = async () => {
    const f = $("#hea-file").files[0];
    if (!f) return;
    try {
      const rr = await fetch(`/api/health/patients/${uid}/files`, { method: "POST", body: f,
        headers: { Authorization: "Bearer " + S.user.token, "x-filename": f.name,
                   "x-kind": $("#hea-fkind").value, "x-shared": $("#hea-fshared").checked ? "1" : "0" } });
      if (!rr.ok) throw new Error((await rr.json()).detail || rr.statusText);
      redo();
    } catch (e) { toast(e.message); }
  };
}

function heaPatientForm(uid, r, d, after) {
  const p = r.patient;
  modal(`<h3>${esc(r.person.name)}</h3>
    <div class="row2">
      <label>Record number <input id="hea-f-mrn" value="${esc(p.mrn)}"></label>
      <label>Date of birth <input id="hea-f-dob" type="date" value="${esc(p.birth_date)}"></label>
    </div>
    <div class="row2">
      <label>Sex <input id="hea-f-sex" value="${esc(p.sex)}"></label>
      <label>Phone <input id="hea-f-phone" value="${esc(p.phone)}"></label>
    </div>
    <label>Address <input id="hea-f-addr" value="${esc(p.address)}"></label>
    <label>Emergency contact <input id="hea-f-emg" value="${esc(p.emergency_contact)}" placeholder="name, relationship, phone"></label>
    <label>Practitioner <select id="hea-f-pract"><option value="0">—</option>${d.practitioners.map((x) => `<option value="${x.id}" ${x.id === p.primary_practitioner_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
    <label>Allergies <textarea id="hea-f-all" rows="2">${esc(p.allergies)}</textarea></label>
    <label>Medications <textarea id="hea-f-med" rows="2">${esc(p.medications)}</textarea></label>
    <label>Conditions <textarea id="hea-f-cond" rows="2">${esc(p.conditions)}</textarea></label>
    <label>Desk notes <span class="opt">not shown to the patient</span><textarea id="hea-f-notes" rows="2">${esc(p.notes || "")}</textarea></label>
    <label class="chk"><input type="checkbox" id="hea-f-consent" ${p.consent_at ? "checked" : ""}> Consent to keep a record was given${p.consent_at ? ` (recorded ${fmtDate(p.consent_at)} by ${esc(p.consent_by)})` : ""}</label>
    <label class="chk"><input type="checkbox" id="hea-f-portal" ${p.portal ? "checked" : ""}> The patient may see their record on their portal</label>
    <div class="actions"><button class="btn" id="hea-f-save">Save</button></div>`);
  $("#hea-f-save").onclick = async () => {
    try {
      await api(`/api/health/patients/${uid}`, { body: {
        mrn: $("#hea-f-mrn").value, birth_date: $("#hea-f-dob").value, sex: $("#hea-f-sex").value,
        phone: $("#hea-f-phone").value, address: $("#hea-f-addr").value, emergency_contact: $("#hea-f-emg").value,
        primary_practitioner_id: +$("#hea-f-pract").value, allergies: $("#hea-f-all").value,
        medications: $("#hea-f-med").value, conditions: $("#hea-f-cond").value, notes: $("#hea-f-notes").value,
        consent: $("#hea-f-consent").checked, portal: $("#hea-f-portal").checked } });
      closeModal(); after();
    } catch (e) { toast(e.message); }
  };
}

function heaPolicyForm(uid, i, d, after) {
  modal(`<h3>${i ? "Edit insurance" : "Add insurance"}</h3>
    <div class="row2">
      <label>Insurer <input id="hea-i-payer" value="${esc(i ? i.payer : "")}" placeholder="Blue Cross"></label>
      <label>Plan <input id="hea-i-plan" value="${esc(i ? i.plan : "")}"></label>
    </div>
    <div class="row2">
      <label>Member ID <input id="hea-i-member" value="${esc(i ? i.member_id : "")}"></label>
      <label>Group <input id="hea-i-group" value="${esc(i ? i.group_no : "")}"></label>
    </div>
    <div class="row2">
      <label>Relationship to subscriber <select id="hea-i-rel">${d.relationships.map((x) => `<option value="${x}" ${i && i.relationship === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Subscriber, if not the patient <input id="hea-i-sub" value="${esc(i ? i.subscriber : "")}"></label>
    </div>
    <div class="row2">
      <label>Effective <input id="hea-i-eff" type="date" value="${esc(i ? i.effective : "")}"></label>
      <label>Expires <input id="hea-i-exp" type="date" value="${esc(i ? i.expires : "")}"></label>
    </div>
    <div class="row2">
      <label>Copay (cents) <input id="hea-i-copay" type="number" min="0" value="${i ? i.copay_cents : 0}"></label>
      <label>Insurer phone <input id="hea-i-phone" value="${esc(i ? i.payer_phone : "")}"></label>
    </div>
    <label>Note <input id="hea-i-note" value="${esc(i ? i.note : "")}"></label>
    <label class="chk"><input type="checkbox" id="hea-i-primary" ${!i || i.primary_policy ? "checked" : ""}> Primary policy</label>
    <div class="actions"><button class="btn" id="hea-i-save">Save</button></div>`);
  $("#hea-i-save").onclick = async () => {
    try {
      await api(`/api/health/patients/${uid}/insurance`, { body: {
        id: i ? i.id : 0, payer: $("#hea-i-payer").value, plan: $("#hea-i-plan").value,
        member_id: $("#hea-i-member").value, group_no: $("#hea-i-group").value,
        relationship: $("#hea-i-rel").value, subscriber: $("#hea-i-sub").value,
        effective: $("#hea-i-eff").value, expires: $("#hea-i-exp").value,
        copay_cents: +$("#hea-i-copay").value, payer_phone: $("#hea-i-phone").value,
        note: $("#hea-i-note").value, primary_policy: $("#hea-i-primary").checked } });
      closeModal(); after();
    } catch (e) { toast(e.message); }
  };
}

function heaEncounterForm(uid, e, d, after) {
  const at = e ? new Date(e.at * 1000) : new Date();
  const v = (e && e.vitals) || {};
  modal(`<h3>${e ? "Edit visit" : "New visit"}</h3>
    <div class="row2">
      <label>Kind <select id="hea-e-kind">${d.encounter_kinds.map((k) => `<option value="${k}" ${e && e.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></label>
      <label>When <input id="hea-e-at" type="datetime-local" value="${new Date(at.getTime() - at.getTimezoneOffset() * 60000).toISOString().slice(0, 16)}"></label>
    </div>
    <label>Practitioner <select id="hea-e-pract">${d.practitioners.map((x) => `<option value="${x.id}" ${(e ? e.practitioner_id : S.user.id) === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
    <label>Reason <input id="hea-e-reason" value="${esc(e ? e.reason : "")}" placeholder="what they came about"></label>
    <div class="row2">
      <label>Blood pressure <input id="hea-e-bp" value="${esc(v.bp || "")}" placeholder="120/80"></label>
      <label>Pulse <input id="hea-e-pulse" value="${esc(v.pulse || "")}"></label>
    </div>
    <div class="row2">
      <label>Temperature <input id="hea-e-temp" value="${esc(v.temp || "")}"></label>
      <label>Weight <input id="hea-e-weight" value="${esc(v.weight || "")}"></label>
    </div>
    <label>Notes <textarea id="hea-e-notes" rows="6">${esc(e ? e.notes : "")}</textarea></label>
    <label>Plan <textarea id="hea-e-plan" rows="2">${esc(e ? e.plan : "")}</textarea></label>
    <label>Follow up <input id="hea-e-fu" type="date" value="${e && e.followup_at ? new Date(e.followup_at * 1000).toISOString().slice(0, 10) : ""}"></label>
    <label class="chk"><input type="checkbox" id="hea-e-shared" ${!e || e.shared ? "checked" : ""}> The patient may see this on their portal</label>
    <div class="actions"><button class="btn" id="hea-e-save">Save</button></div>`);
  $("#hea-e-save").onclick = async () => {
    try {
      await api(`/api/health/patients/${uid}/encounters`, { body: {
        id: e ? e.id : 0, kind: $("#hea-e-kind").value,
        at: new Date($("#hea-e-at").value).getTime() / 1000,
        practitioner_id: +$("#hea-e-pract").value, reason: $("#hea-e-reason").value,
        notes: $("#hea-e-notes").value, plan: $("#hea-e-plan").value,
        vitals: { bp: $("#hea-e-bp").value, pulse: $("#hea-e-pulse").value, temp: $("#hea-e-temp").value, weight: $("#hea-e-weight").value },
        followup_at: $("#hea-e-fu").value ? new Date($("#hea-e-fu").value + "T09:00").getTime() / 1000 : 0,
        shared: $("#hea-e-shared").checked, appointment_id: e ? e.appointment_id : 0 } });
      closeModal(); after();
    } catch (e2) { toast(e2.message); }
  };
}
