// ---------- staff permissions ----------
/* Customers — the consumer half of the CRM. Clients (B2B) had a tab from
   day one; the people who simply buy things could place orders the ERP
   would happily count without ever being visible as people. */
async function renderCustomers(q) {
  if (S.deepId) {                    // #/customers/12 — card over list
    const _id = S.deepId;
    S.deepId = null;
    renderCustomers().then(() => customerCard(_id));
    return;
  }
  if (location.hash.startsWith("#/customers/"))
    history.pushState(null, "", "#/customers");
  const rows = await api(`/api/customers?q=${encodeURIComponent(q || "")}`);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Customers</h2>
        <p class="dim">Everyone who shops (or studies) here — with what
          they've bought and where they're enrolled. B2B relationships
          live under Clients.</p></div>
      <div class="top-actions">
        <button class="btn sm" id="cu-new" title="somebody who phoned an
          order in, or walked up to the counter — they can sign in by name
          afterwards">Add a customer</button>
      </div>
    </div>
    <div class="card"><input id="cu-q" placeholder="Search name or email"
      value="${esc(q || "")}" style="max-width:340px"></div>
    ${rows.map((r) => `<div class="card${r.active ? "" : " dim-card"}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(r.name)}</b>
          <span class="dim">${[r.email, r.region].filter(Boolean)
            .map(esc).join(" · ") || "no contact on file"}${
            r.active ? "" : " · deactivated"}</span></div>
        <span class="dim">${r.orders} order${r.orders === 1 ? "" : "s"}
          · ${money(r.spent_cents)}</span>
        <button class="btn alt sm" data-editcust="${r.id}">Edit</button>
        <button class="btn alt sm" data-cust="${r.id}">Open</button>
      </div></div>`).join("")
      || '<div class="card empty"><b>No customers yet</b><span class="dim">They appear here the moment somebody signs up or orders.</span></div>'}`;
  $("#cu-new").onclick = () => personForm({ role: "customer", _new: true },
    () => renderCustomers(q));
  view().querySelectorAll("[data-editcust]").forEach((b) => b.onclick = () =>
    personForm(rows.find((r) => r.id === +b.dataset.editcust),
               () => renderCustomers(q)));
  let t = null;
  $("#cu-q").oninput = () => {
    clearTimeout(t);
    t = setTimeout(() => renderCustomers($("#cu-q").value), 300);
  };
  if (q !== undefined) {
    const el = $("#cu-q");
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }
  view().querySelectorAll("[data-cust]").forEach((b) => b.onclick =
    () => customerCard(+b.dataset.cust));
}

async function customerCard(uid) {
  if (location.hash !== `#/customers/${uid}`)
    history.pushState(null, "", `#/customers/${uid}`);
  const d = await api(`/api/customers/${uid}`);
  const isAdmin = S.user && S.user.is_admin;
  modal(`<h3>${esc(d.name)}</h3>
    <p class="dim">customer since ${fmtDate(d.created_at)}${
      d.active ? "" : " · deactivated"}${d.requested_role
      ? ` · asked to be ${esc(d.requested_role)}` : ""}</p>
    <label>Email</label>
    <input id="cu-email" value="${esc(d.email || "")}" ${isAdmin ? "" : "disabled"}>
    ${d.courses.length ? `<p><b>Enrolled:</b>
      ${d.courses.map(esc).join(", ")}</p>` : ""}
    ${d.orders.length ? `<table><thead><tr><th>Order</th><th>Status</th>
      <th>Total</th><th>When</th></tr></thead><tbody>
      ${d.orders.map((o) => `<tr><td>#${o.id}</td><td>${esc(o.status)}</td>
        <td>${money(o.total_cents)}</td><td>${fmtDate(o.created_at)}</td>
      </tr>`).join("")}</tbody></table>`
      : '<p class="dim">No orders yet.</p>'}
    ${isAdmin ? `<div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn sm" id="cu-save">Save</button>
      <button class="btn alt sm" id="cu-toggle">${d.active
        ? "Deactivate" : "Reactivate"}</button>
    </div>` : ""}`);
  if ($("#cu-save")) $("#cu-save").onclick = async () => {
    await api(`/api/admin/users/${uid}/update`,
              { body: { email: $("#cu-email").value.trim() } });
    toast("saved");
    closeModal();
    renderCustomers();
  };
  if ($("#cu-toggle")) $("#cu-toggle").onclick = async () => {
    await api(`/api/admin/users/${uid}/update`,
              { body: { active: !d.active } });
    toast(d.active ? "deactivated" : "reactivated");
    closeModal();
    renderCustomers();
  };
}

/* Role requests: what somebody asked to be at sign-up (roles.py decides
   who may review what). One card, two homes — Team & access for any
   tenant with Workforce, and the Learning tab beside the applications
   queue, because a school's office lives there. */
function roleRequestsCard(requests) {
  if (!requests.length) return "";
  return `<div class="card">
    <h3 style="margin-top:0">Role requests</h3>
    <p class="dim">What people asked to be at sign-up. Approving is the
      promotion — it ends their sessions so the new role arrives whole —
      and declining leaves the account a student.</p>
    ${requests.map((r) => `
      <div class="doc-top">
        <div class="doc-main"><b>${esc(r.name)}</b>
          <span class="dim">asked to be ${esc(r.requested_label)}${
            r.email ? " · " + esc(r.email) : ""}</span></div>
        <button class="btn sm" data-roleok="${r.id}">Approve</button>
        <button class="btn alt sm" data-roleno="${r.id}">Decline</button>
      </div>`).join("")}
  </div>`;
}

function wireRoleRequests(rerender) {
  view().querySelectorAll("[data-roleok]").forEach((b) => b.onclick =
    async () => {
      await api(`/api/roles/requests/${b.dataset.roleok}/decide`,
                { method: "POST", body: { approve: true } });
      toast("Approved — they sign in again to pick it up");
      rerender();
    });
  view().querySelectorAll("[data-roleno]").forEach((b) => b.onclick =
    async () => {
      await api(`/api/roles/requests/${b.dataset.roleno}/decide`,
                { method: "POST", body: { approve: false } });
      toast("Declined");
      rerender();
    });
}

/* One form for adding somebody and for fixing what an account says.
   Every other door here mints people as a side effect — a sign-in, an
   invite, an approved application — and there was no way to simply add a
   person, or to correct a name somebody typed wrong on their first day.
   No password is set: the account adopts one when its owner first
   supplies it, exactly like every other door. */
const PERSON_ROLES = ["customer", "employee", "owner", "teacher",
                      "volunteer", "director", "board", "donor",
                      "distributor", "influencer"];
const PERSON_JOBS = ["general", "driver", "dsd", "warehouse", "sales_rep",
                     "ambassador", "event_staff"];

function personForm(u, after) {
  const isNew = !u || u._new;
  if (isNew && u) { u = { ...u, id: 0 }; }
  const opt = (list, cur) => list.map((x) =>
    `<option ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("");
  modal(`<h3>${isNew ? (u && u.role === "customer" ? "Add a customer"
      : "Add a person") : "Edit " + esc(u.name)}</h3>
    <p class="dim">${!isNew
      ? "What this account says about them. Changing a name changes it "
        + "everywhere they appear."
      : "They can sign in by name straight away; a password is adopted the "
        + "first time they supply one."}</p>
    <label>Name <span class="req">required</span></label>
    <input id="pf-name" value="${esc(!isNew ? u.name : "")}">
    <label>Email <span class="opt">where anything we send goes</span></label>
    <input id="pf-email" type="email" value="${esc((u && u.email) || "")}">
    <div class="row2">
      <div><label>Role</label>
        <select id="pf-role">${opt(PERSON_ROLES,
          (u && u.role) || "employee")}
        </select></div>
      <div><label>Job <span class="opt">for staff</span></label>
        <select id="pf-job">${opt(PERSON_JOBS, (u && u.job) || "general")}
        </select></div>
    </div>
    <div class="row2">
      <div><label>Employment</label>
        <select id="pf-emp">${opt(["employee", "contractor"],
          (u && u.employment) || "employee")}</select></div>
      <div><label>Time-clock PIN
          <span class="opt">${isNew ? "optional, 4-8 digits"
            : "set from the PIN button"}</span></label>
        <input id="pf-pin" inputmode="numeric" autocomplete="off"
          ${isNew ? "" : "disabled"}></div>
    </div>
    <label class="perm" style="margin-top:8px"><input type="checkbox"
      id="pf-admin" ${u && u.is_admin ? "checked" : ""}>
      <span><b>Full access</b><small>every area of the back office —
        owners always have it</small></span></label>
    ${!isNew ? `<label class="perm"><input type="checkbox" id="pf-active"
      ${u.active ? "checked" : ""}>
      <span><b>Active</b><small>an inactive account cannot sign in, and is
        signed out on the spot</small></span></label>
    <label class="perm"><input type="checkbox" id="pf-clearpw">
      <span><b>Forget their password</b><small>the next password they type
        becomes the new one</small></span></label>` : ""}
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="pf-save">${isNew ? "Add" : "Save"}</button>
    </div>`);
  $("#pf-save").onclick = async () => {
    const body = {
      name: $("#pf-name").value.trim(),
      email: $("#pf-email").value.trim(),
      role: $("#pf-role").value, job: $("#pf-job").value,
      employment: $("#pf-emp").value,
      is_admin: $("#pf-admin").checked,
    };
    if (!body.name) return toast("a person needs a name");
    try {
      if (!isNew) {
        body.active = $("#pf-active").checked;
        body.clear_password = $("#pf-clearpw").checked;
        await api(`/api/admin/users/${u.id}/update`, { body });
      } else {
        body.pin = $("#pf-pin").value.trim();
        await api("/api/admin/users", { body });
      }
      closeModal();
      toast(isNew ? `${body.name} has an account` : "saved");
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}

async function renderStaff() {
  const data = await api("/api/store/admin/staff");
  const requests = await api("/api/roles/requests").catch(() => []);
  const perms = Object.entries(data.permissions);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Team & permissions</h2>
        <p class="dim">Who can see what in the back office. Owners keep full
          access; everyone else gets exactly what's ticked. Changes are
          recorded in the audit log.</p></div>
      <div class="top-actions">
        <button class="btn sm" id="staff-new">Add a person</button>
      </div>
    </div>
    ${roleRequestsCard(requests)}
    ${data.staff.map((u) => `
      <div class="card">
        <div class="doc-top">
          <div class="doc-main">
            <b>${esc(u.name)}</b>
            <span class="dim">${esc(u.role)}${u.is_admin ? " · owner" : ""}${
              u.active ? "" : " · inactive"}</span>
          </div>
          ${u.effective.includes("*")
            ? '<span class="pill ok">full access</span>'
            : `<span class="pill">${u.effective.length} area(s)</span>`}
          <button class="btn alt sm" data-setpin="${u.id}:${esc(u.name)}"
            >Time-clock PIN</button>
          <button class="btn alt sm" data-badge="${u.id}:${esc(u.name)}"
            >Badge</button>
          <button class="btn alt sm" data-edituser="${u.id}">Edit</button>
        </div>
        ${u.is_admin ? '<p class="dim" style="margin-top:8px">Owner accounts always have every permission.</p>' : `
        <div class="perm-grid">
          ${perms.map(([k, label]) => `
            <label class="perm">
              <input type="checkbox" data-perm="${u.id}:${k}"
                ${u.effective.includes(k) ? "checked" : ""}>
              <span><b>${k}</b><small>${esc(label)}</small></span>
            </label>`).join("")}
        </div>
        <div style="margin-top:10px">
          <button class="btn sm" data-saveperm="${u.id}">Save permissions</button>
        </div>`}
      </div>`).join("")}`;
  wireRoleRequests(renderStaff);
  $("#staff-new").onclick = () => personForm(null, renderStaff);
  view().querySelectorAll("[data-edituser]").forEach((b) => b.onclick = () =>
    personForm(data.staff.find((u) => u.id === +b.dataset.edituser),
               renderStaff));
  view().querySelectorAll("[data-badge]").forEach((b) => b.onclick = async () => {
    const [uid, name] = b.dataset.badge.split(":");
    const { token } = await api(`/api/admin/users/${uid}/badge`,
                                { method: "POST" });
    modal(`<h3>${esc(name)}'s clock badge</h3>
      <p class="dim">Print it, or let them photograph it. Holding it up to
        the clock tablet punches them in or out. It is not a sign-in: a copy
        can only clock them in, which you would see on the timesheet.</p>
      <div style="text-align:center;padding:12px">${qrImg(token, 170)}</div>
      <div class="modal-acts">
        <button class="btn alt" data-close>Close</button>
        <button class="btn alt danger-hint" id="badge-reset">Issue a new one</button>
        <button class="btn" onclick="window.print()">Print</button>
      </div>`);
    $("#badge-reset").onclick = async () => {
      if (!confirm("Issue a new badge? Anything already printed stops "
        + "working.")) return;
      const r = await api(`/api/admin/users/${uid}/badge?reset=1`,
                          { method: "POST" });
      $("#ops-modal").querySelector("div[style*='text-align:center']")
        .innerHTML = qrImg(r.token, 170);
      toast("New badge issued");
    };
  });
  view().querySelectorAll("[data-setpin]").forEach((b) => b.onclick = () => {
    const [uid, name] = b.dataset.setpin.split(":");
    modal(`<h3>Time-clock PIN — ${esc(name)}</h3>
      <p class="dim">PINs are stored hashed, so nobody — including you — can
        look one up. Forgotten means issued again, which is the right answer
        anyway: a PIN a manager can read is a PIN a manager can use to clock
        someone in.</p>
      <label>New PIN <span class="dim">(4–8 digits)</span></label>
      <input id="pin-new" inputmode="numeric" autocomplete="off">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn alt" id="pin-clear">Remove their PIN</button>
        <button class="btn" id="pin-save">Set PIN</button>
      </div>`);
    const send = async (pin) => {
      try {
        const r = await api(`/api/admin/users/${uid}/pin`, { body: { pin } });
        closeModal();
        toast(r.cleared ? `${name} can no longer clock in with a PIN`
                        : `New PIN set for ${name} — tell them in person`);
        renderStaff();
      } catch (e) { toast(e.message); }
    };
    $("#pin-save").onclick = () => send($("#pin-new").value.trim());
    $("#pin-clear").onclick = () => send("");
  });
  view().querySelectorAll("[data-saveperm]").forEach((b) => b.onclick = async () => {
    const uid = b.dataset.saveperm;
    const picked = [...view().querySelectorAll(`[data-perm^="${uid}:"]`)]
      .filter((c) => c.checked).map((c) => c.dataset.perm.split(":")[1]);
    try {
      await api(`/api/store/admin/staff/${uid}/permissions`,
        { body: { permissions: picked } });
      toast("Permissions saved");
      renderStaff();
    } catch (e) { toast(e.message); }
  });
}

// ---------- events ----------
async function renderEvents() {
  const rows = await api("/api/store/admin/events");
  const now = Date.now() / 1000;
  const upcoming = rows.filter((e) => e.starts >= now);
  const past = rows.filter((e) => e.starts < now);
  const card = (e) => `
    <div class="card ${e.starts < now ? "dim-card" : ""}">
      <div class="doc-top">
        <span class="ev-date"><b>${new Date(e.starts * 1000)
          .getDate()}</b>${new Date(e.starts * 1000)
          .toLocaleString(undefined, { month: "short" }).toUpperCase()}</span>
        <div class="doc-main">
          <b>${esc(e.name)}</b>
          <span class="dim">${esc(e.kind)}${
            e.venue ? " · " + esc(e.venue) : ""}${
            e.city ? " · " + esc(e.city) : ""}${
            e.region ? " · " + esc(e.region) : ""}</span>
        </div>
        <span class="pill ${e.active ? "ok" : ""}">${e.active ? "live" : "hidden"}</span>
        <button class="btn alt sm" data-evedit="${e.id}">Edit</button>
        <button class="btn alt sm" data-rowdel="event:${e.id}">Delete</button>
      </div>
      ${e.body ? `<p class="dim" style="margin-top:8px">${esc(e.body)}</p>` : ""}
    </div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Events</h2>
        <p class="dim">Tastings, pop-ups and markets. These appear on
          <a href="/events" target="_blank">the public events page</a>; past
          events drop off it automatically.</p></div>
      <button class="btn" id="ev-new">${opsIcon("calendar","btn-ic")} New event</button>
    </div>
    <h3>Upcoming (${upcoming.length})</h3>
    ${upcoming.map(card).join("") || '<div class="card empty"><span class="e-ic">'
      + opsIcon("calendar") + '</span><b>Nothing scheduled</b></div>'}
    ${past.length ? `<h3>Past (${past.length})</h3>${past.map(card).join("")}` : ""}`;
  $("#ev-new").onclick = () => eventForm(null);
  view().querySelectorAll("[data-evedit]").forEach((b) => b.onclick = () =>
    eventForm(rows.find((x) => x.id === +b.dataset.evedit)));
  wireRows({}, renderEvents);
}

function eventForm(e) {
  const kinds = ["tasting", "popup", "market", "class"];
  const d = e && e.starts
    ? new Date(e.starts * 1000).toISOString().slice(0, 10) : "";
  modal(`<h3>${e ? "Edit event" : "New event"}</h3>
    <label>Name</label><input id="evf-name" value="${esc((e && e.name) || "")}">
    <div class="row2">
      <div><label>Kind</label><select id="evf-kind">${kinds.map((k) =>
        `<option ${e && e.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      <div><label>Date</label><input id="evf-date" type="date" value="${d}"></div>
    </div>
    <div class="row2">
      <div><label>Venue</label><input id="evf-venue" value="${esc((e && e.venue) || "")}"></div>
      <div><label>City</label><input id="evf-city" value="${esc((e && e.city) || "")}"></div>
    </div>
    <div class="row2">
      <div><label>Region</label><input id="evf-region" value="${esc((e && e.region) || "")}"></div>
      <div><label>Link</label><input id="evf-url" value="${esc((e && e.url) || "")}"></div>
    </div>
    <label>Details</label><textarea id="evf-body" rows="3">${esc((e && e.body) || "")}</textarea>
    <label class="perm" style="margin-top:14px">
      <input type="checkbox" id="evf-live" ${!e || e.active ? "checked" : ""}>
      <span><b>Live</b><small>Shown on the public events page</small></span></label>
    <div class="modal-acts">
      ${e ? '<button class="btn alt" id="evf-del" style="margin-right:auto">Delete</button>' : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="evf-save">Save</button>
    </div>`);
  $("#evf-save").onclick = async () => {
    const name = $("#evf-name").value.trim();
    if (!name) return toast("an event needs a name");
    const dv = $("#evf-date").value;
    const payload = { name, kind: $("#evf-kind").value,
      venue: $("#evf-venue").value.trim(), city: $("#evf-city").value.trim(),
      region: $("#evf-region").value.trim(), url: $("#evf-url").value.trim(),
      body: $("#evf-body").value.trim(),
      active: $("#evf-live").checked ? 1 : 0,
      starts: dv ? new Date(dv + "T12:00").getTime() / 1000
        : (e ? e.starts : Date.now() / 1000) };
    try {
      if (e) await api(`/api/store/admin/events/${e.id}`,
        { method: "PATCH", body: payload });
      else await api("/api/store/admin/events", { body: payload });
      closeModal(); renderEvents();
    } catch (err) { toast(err.message); }
  };
  if (e && $("#evf-del")) $("#evf-del").onclick = async () => {
    if (!confirm(`Delete "${e.name}"?`)) return;
    await api(`/api/store/admin/events/${e.id}`, { method: "DELETE" });
    closeModal(); renderEvents();
  };
}
