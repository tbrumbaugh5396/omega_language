/* The patient's portal. Reads one record — their own — and offers the
   three things a patient does: check in, look, and keep their insurance
   card on file. */
(() => {
  const root = document.getElementById("hp-root");
  if (!root) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const token = () => { try { return JSON.parse(localStorage.getItem("bc_user") || "{}").token || localStorage.getItem("sf_token") || ""; } catch (e) { return ""; } };
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { method: opts.method || (opts.body ? "POST" : "GET"),
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
      body: opts.body ? JSON.stringify(opts.body) : undefined });
    if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
    return r.json();
  };
  const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  async function draw() {
    let r;
    try { r = await api("/api/health/me"); }
    catch (e) {
      root.innerHTML = `<p class="lrn-meta">${esc(e.message)}${/sign in/i.test(e.message) ? ' — <a href="/#account">sign in</a>' : ""}</p>`;
      return;
    }
    const p = r.patient;
    root.innerHTML = `
      <h2>Appointments</h2>
      ${r.appointments.length ? r.appointments.map((a) => `<div class="hp-card hp-row">
        <div><b>${day(a.starts)} ${clock(a.starts)}</b> <span class="lrn-meta">${esc(a.service || "")}</span></div>
        ${a.checkin_state ? `<span class="hp-pill">${a.checkin_state === "arrived" || a.checkin_state === "waiting" ? "checked in" : esc(a.checkin_state.replace("_", " "))}</span>`
          : a.can_check_in ? `<button class="lrn-btn sm" data-hpcheck="${a.id}">I have arrived</button>`
          : `<span class="lrn-meta">check in from three hours before</span>`}
      </div>`).join("") : `<p class="lrn-meta">Nothing booked. Appointments are booked from the shop's booking page.</p>`}
      <h2>On file</h2>
      <div class="hp-card">
        <div class="hp-grid">
          <div><span>Record number</span>${esc(p.mrn || "—")}</div>
          <div><span>Date of birth</span>${esc(p.birth_date || "—")}</div>
          <div><span>Practitioner</span>${esc(p.primary_practitioner || "—")}</div>
          <div><span>Allergies</span>${esc(p.allergies || "none recorded")}</div>
          <div><span>Medications</span>${esc(p.medications || "none recorded")}</div>
          <div><span>Conditions</span>${esc(p.conditions || "none recorded")}</div>
          <div><span>Emergency contact</span>${esc(p.emergency_contact || "—")}</div>
        </div>
        <p class="lrn-meta">Something wrong? Tell the practice; only they can change the record.</p>
      </div>
      <h2>Insurance</h2>
      ${r.insurance.map((i) => `<div class="hp-card hp-row">
        <div><b>${esc(i.payer)}</b> ${esc(i.plan || "")} <span class="lrn-meta">member ${esc(i.member_id || "—")}${i.group_no ? " · group " + esc(i.group_no) : ""}</span></div>
        ${i.verified_at ? '<span class="hp-pill">verified</span>' : `<span class="lrn-meta">not yet verified</span> <button class="lrn-btn sm" data-hpins="${i.id}">Edit</button>`}
      </div>`).join("")}
      <div class="hp-card"><button class="lrn-btn sm" id="hp-ins-new">Add an insurance card</button>
        <div id="hp-ins-form"></div></div>
      <h2>Visits</h2>
      ${r.encounters.length ? r.encounters.map((e) => `<div class="hp-enc">
        <div><b>${day(e.at)}</b> <span class="hp-pill">${esc(e.kind)}</span> <span class="lrn-meta">${esc(e.practitioner)}</span></div>
        ${e.reason ? `<div>${esc(e.reason)}</div>` : ""}
        ${e.notes ? `<div class="hp-notes">${esc(e.notes)}</div>` : ""}
        ${e.plan ? `<div><span class="lrn-meta">Plan:</span> ${esc(e.plan)}</div>` : ""}
        ${e.followup_at ? `<div class="lrn-meta">follow up ${day(e.followup_at)}</div>` : ""}
      </div>`).join("") : `<p class="lrn-meta">No visits shared yet.</p>`}
      <h2>Documents</h2>
      ${r.files.length ? `<ul>${r.files.map((f) => `<li><a href="/api/health/me/files/${f.id}" data-hpfile="${f.id}">${esc(f.name)}</a> <span class="lrn-meta">${esc(f.kind)} · ${day(f.created_at)}</span></li>`).join("")}</ul>`
        : `<p class="lrn-meta">Nothing shared yet.</p>`}`;
    root.querySelectorAll("[data-hpcheck]").forEach((b) => b.onclick = async () => {
      try { await api("/api/health/me/checkin", { body: { appointment_id: +b.dataset.hpcheck } }); draw(); }
      catch (e) { alert(e.message); }
    });
    root.querySelectorAll("[data-hpfile]").forEach((a) => a.onclick = async (ev) => {
      ev.preventDefault();
      const rr = await fetch(a.getAttribute("href"), { headers: { Authorization: "Bearer " + token() } });
      if (!rr.ok) return alert("could not open the file");
      const url = URL.createObjectURL(await rr.blob());
      window.open(url, "_blank");
    });
    const form = (i) => {
      document.getElementById("hp-ins-form").innerHTML = `<div class="hp-form">
        <input id="hp-i-payer" placeholder="Insurer" value="${esc(i ? i.payer : "")}">
        <input id="hp-i-plan" placeholder="Plan" value="${esc(i ? i.plan : "")}">
        <input id="hp-i-member" placeholder="Member ID" value="${esc(i ? i.member_id : "")}">
        <input id="hp-i-group" placeholder="Group number" value="${esc(i ? i.group_no : "")}">
        <select id="hp-i-rel">${["self", "spouse", "child", "other"].map((x) => `<option value="${x}" ${i && i.relationship === x ? "selected" : ""}>${x === "self" ? "my own policy" : x + " of the subscriber"}</option>`).join("")}</select>
        <input id="hp-i-sub" placeholder="Subscriber's name, if not you" value="${esc(i ? i.subscriber : "")}">
        <input id="hp-i-phone" placeholder="Insurer phone" value="${esc(i ? i.payer_phone : "")}">
        <button class="lrn-btn sm" id="hp-i-save">Save</button>
        <span class="lrn-meta">The practice verifies it at your next visit.</span></div>`;
      document.getElementById("hp-i-save").onclick = async () => {
        try {
          await api("/api/health/me/insurance", { body: { id: i ? i.id : 0,
            payer: document.getElementById("hp-i-payer").value, plan: document.getElementById("hp-i-plan").value,
            member_id: document.getElementById("hp-i-member").value, group_no: document.getElementById("hp-i-group").value,
            relationship: document.getElementById("hp-i-rel").value, subscriber: document.getElementById("hp-i-sub").value,
            payer_phone: document.getElementById("hp-i-phone").value } });
          draw();
        } catch (e) { alert(e.message); }
      };
    };
    document.getElementById("hp-ins-new").onclick = () => form(null);
    root.querySelectorAll("[data-hpins]").forEach((b) => b.onclick = () => form(r.insurance.find((x) => x.id === +b.dataset.hpins)));
  }
  draw();
})();
