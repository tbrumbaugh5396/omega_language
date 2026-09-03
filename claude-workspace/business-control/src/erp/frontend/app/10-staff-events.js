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
        <button class="btn" id="cu-new" title="somebody who phoned an
          order in, or walked up to the counter — they can sign in by name
          afterwards">${opsIcon("user", "btn-ic")} Add a customer</button>
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
        <button class="btn" id="staff-new">${opsIcon("users", "btn-ic")}
          Add a person</button>
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
/* Which events the desk is showing. Not a search — four answers a person
   actually wants: what is coming, what already happened, what is hidden
   from the public page, and what has been put away. */
let EV_FILTER = "upcoming";
const EV_FILTERS = [
  ["upcoming", "Upcoming"], ["past", "Past"], ["hidden", "Hidden"],
  ["archived", "Archived"], ["all", "Everything"],
];

async function renderEvents() {
  const all = await api("/api/store/admin/events");
  const now = Date.now() / 1000;
  const live = all.filter((e) => !e.archived);
  const rows = {
    upcoming: live.filter((e) => e.starts >= now),
    past: live.filter((e) => e.starts < now),
    hidden: live.filter((e) => !e.active),
    archived: all.filter((e) => e.archived),
    all,
  }[EV_FILTER] || live;
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
        <span class="pill ${e.archived ? "" : e.active ? "ok" : "warn"}">${
          e.archived ? "archived" : e.active ? "live" : "hidden"}</span>
        <button class="btn alt sm" data-evshow="${e.id}:${e.active ? 0 : 1}"
          title="${e.active ? "take it off the public events page — the "
            + "record stays" : "put it back on the public page"}">${
          e.active ? "Hide" : "Show"}</button>
        <button class="btn alt sm" data-evarch="${e.id}:${e.archived ? 0 : 1}"
          title="${e.archived ? "back to the working list"
            : "off the desk, not deleted — shifts point at events, and a "
              + "market that ran is why somebody was paid"}">${
          e.archived ? "Restore" : "Archive"}</button>
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
    <div class="chips">${EV_FILTERS.map(([k, label]) =>
      `<button class="btn ${EV_FILTER === k ? "" : "alt "}sm"
        data-evfilter="${k}">${label}</button>`).join("")}</div>
    <h3>Upcoming (${upcoming.length})</h3>
    ${upcoming.map(card).join("") || '<div class="card empty"><span class="e-ic">'
      + opsIcon("calendar") + '</span><b>Nothing scheduled</b></div>'}
    ${past.length ? `<h3>Past (${past.length})</h3>${past.map(card).join("")}` : ""}`;
  $("#ev-new").onclick = () => eventForm(null);
  view().querySelectorAll("[data-evfilter]").forEach((b) => b.onclick = () => {
    EV_FILTER = b.dataset.evfilter; renderEvents();
  });
  view().querySelectorAll("[data-evshow]").forEach((b) => b.onclick =
    async () => {
      const [id, on] = b.dataset.evshow.split(":");
      const ev = all.find((x) => x.id === +id);
      try {
        await api(`/api/store/admin/events/${id}`,
          { method: "PATCH", body: { ...ev, active: +on } });
        renderEvents();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-evarch]").forEach((b) => b.onclick =
    async () => {
      const [id, on] = b.dataset.evarch.split(":");
      try {
        await api(`/api/store/admin/events/${id}/archive`,
          { body: { archived: on === "1" } });
        toast(on === "1" ? "archived — the record stays" : "back on the list");
        renderEvents();
      } catch (err) { toast(err.message); }
    });
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


/* ---------- the board ----------
   Work that is somebody's, in a state, with a date. Five columns, fixed:
   every team that gets to invent its own ends up with eleven, three of
   which mean "waiting", and no two people agreeing which. */
const COL_LABEL = { backlog: "Backlog", doing: "Doing", review: "Review",
                    blocked: "Blocked", done: "Done" };
const PRI_PILL = { low: "", normal: "", high: "warn", urgent: "bad" };
let BOARD_MINE = false;

async function renderBoard() {
  const d = await api(`/api/tickets${BOARD_MINE ? "?mine=1" : ""}`);
  const byCol = {};
  d.columns.forEach((c) => (byCol[c] = []));
  d.tickets.forEach((t) => (byCol[t.col] || byCol.backlog).push(t));
  const card = (t) => `
    <div class="tk${t.overdue ? " tk-late" : ""}" data-tk="${t.id}">
      <div class="tk-title">${esc(t.title)}</div>
      <div class="tk-meta">
        ${t.priority !== "normal" ? `<span class="pill ${
          PRI_PILL[t.priority] || ""}">${esc(t.priority)}</span>` : ""}
        ${t.assignee_name ? `<span class="dim">${esc(t.assignee_name)}</span>`
          : '<span class="dim">unassigned</span>'}
        ${t.due ? `<span class="${t.overdue ? "low" : "dim"}">${
          fmtDate(t.due)}</span>` : ""}
        ${t.client_name ? `<span class="pill">${esc(t.client_name)}</span>`
          : ""}
      </div>
    </div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Board</h2>
        <p class="dim">Everything somebody is meant to be doing, in one
          list you can move. A card carries who it is for, how urgent it
          is and when it is due — and its due date shows on the
          calendar.</p></div>
      <div class="top-actions">
        <button class="btn alt${BOARD_MINE ? " on" : ""}" id="bd-mine">${
          BOARD_MINE ? "Everyone's" : "Only mine"}</button>
        <button class="btn" id="bd-new">${opsIcon("list", "btn-ic")}
          New ticket</button>
      </div>
    </div>
    <div class="board">
      ${d.columns.map((c) => `
        <div class="board-col" data-col="${c}">
          <div class="board-head">${esc(COL_LABEL[c] || c)}
            <span class="dim">${byCol[c].length}</span></div>
          ${byCol[c].map(card).join("")
            || '<p class="dim" style="padding:6px 2px">nothing here</p>'}
        </div>`).join("")}
    </div>`;
  $("#bd-mine").onclick = () => { BOARD_MINE = !BOARD_MINE; renderBoard(); };
  $("#bd-new").onclick = () => ticketForm(null, d);
  view().querySelectorAll("[data-tk]").forEach((el) => el.onclick = () =>
    ticketForm(d.tickets.find((t) => t.id === +el.dataset.tk), d));
}

/* One card, opened. Moving it is a select rather than a drag: a drag is
   lovely on a desk and unusable on the phone somebody is holding in a
   warehouse, and this has to work in both. */
function ticketForm(t, d) {
  const sel = (id, list, cur, label) => `
    <div><label>${label}</label><select id="${id}">
      ${list.map((x) => `<option value="${esc(x.v)}"
        ${String(cur) === String(x.v) ? "selected" : ""}>${esc(x.n)}</option>`)
        .join("")}</select></div>`;
  const people = [{ v: 0, n: "— nobody yet —" },
    ...d.people.map((p) => ({ v: p.id, n: p.name }))];
  const due = t && t.due
    ? new Date(t.due * 1000).toISOString().slice(0, 10) : "";
  modal(`<h3>${t ? "Ticket" : "New ticket"}</h3>
    <label>Title <span class="req">required</span></label>
    <input id="tk-title" value="${esc(t ? t.title : "")}">
    <label>Detail <span class="opt">what "done" means, if it isn't
      obvious</span></label>
    <textarea id="tk-body" rows="4">${esc((t && t.body) || "")}</textarea>
    <div class="row2">
      ${sel("tk-col", d.columns.map((c) => ({ v: c, n: COL_LABEL[c] || c })),
            t ? t.col : "backlog", "Column")}
      ${sel("tk-pri", d.priorities.map((x) => ({ v: x, n: x })),
            t ? t.priority : "normal", "Priority")}
    </div>
    <div class="row2">
      ${sel("tk-who", people, t ? t.assignee_id : 0, "Assigned to")}
      <div><label>Due <span class="opt">shows on the calendar</span></label>
        <input id="tk-due" type="date" value="${due}"></div>
    </div>
    <label>Labels <span class="opt">comma separated</span></label>
    <input id="tk-labels" value="${esc(((t && t.labels) || []).join(", "))}">
    <div class="modal-foot">
      ${t ? `<button class="btn alt" id="tk-del"
        style="margin-right:auto">Delete</button>` : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="tk-save">${t ? "Save" : "Open it"}</button>
    </div>`);
  $("#tk-save").onclick = async () => {
    const body = {
      title: $("#tk-title").value.trim(),
      body: $("#tk-body").value.trim(),
      col: $("#tk-col").value, priority: $("#tk-pri").value,
      assignee_id: +$("#tk-who").value,
      labels: $("#tk-labels").value.trim(),
      due: $("#tk-due").value
        ? new Date($("#tk-due").value + "T09:00").getTime() / 1000 : 0,
    };
    if (!body.title) return toast("a ticket needs a title");
    try {
      if (t) await api(`/api/tickets/${t.id}`, { method: "PATCH", body });
      else await api("/api/tickets", { body });
      closeModal(); renderBoard();
    } catch (err) { toast(err.message); }
  };
  if ($("#tk-del")) $("#tk-del").onclick = async () => {
    if (!confirm("Delete this ticket?\n\nIts history goes with it.")) return;
    try {
      await api(`/api/tickets/${t.id}`, { method: "DELETE" });
      closeModal(); renderBoard();
    } catch (err) { toast(err.message); }
  };
}

/* ---------- the calendar ----------
   Every dated thing this business has, laid over each other for once:
   events, ticket due dates, a client's milestones, classes held. They
   were always dated rows in one database; there was never a reason they
   could not be one answer. */
const CAL_ICON = { event: "calendar", ticket: "list", milestone: "handshake",
                   class: "pen" };
const MONTHS = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December"];
let CAL_MONTH = null;

async function renderCalendar() {
  const base = CAL_MONTH ? new Date(CAL_MONTH) : new Date();
  base.setDate(1); base.setHours(0, 0, 0, 0);
  CAL_MONTH = base.getTime();
  const end = new Date(base); end.setMonth(end.getMonth() + 1);
  const d = await api(`/api/calendar?from_ts=${base.getTime() / 1000}`
    + `&to_ts=${end.getTime() / 1000}`);
  const byDay = {};
  d.items.forEach((it) => {
    const k = new Date(it.at * 1000).toDateString();
    (byDay[k] = byDay[k] || []).push(it);
  });
  // A month starts on the weekday it starts on; the grid has to lead with
  // that many blanks or every date lands under the wrong name.
  const lead = base.getDay();
  const days = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push("<div class='cal-cell out'></div>");
  const today = new Date().toDateString();
  for (let n = 1; n <= days; n++) {
    const dt = new Date(base.getFullYear(), base.getMonth(), n);
    const items = byDay[dt.toDateString()] || [];
    cells.push(`<div class="cal-cell${
      dt.toDateString() === today ? " cal-today" : ""}"
      data-calday="${dt.getTime() / 1000}">
      <div class="cal-n">${n}</div>
      ${items.map((it) => `<a class="cal-it cal-${esc(it.kind)}"
        href="${esc(it.link || "#")}" title="${esc(it.note || "")}">
        ${esc(it.title)}</a>`).join("")}
    </div>`);
  }
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${base.toLocaleString(undefined,
        { month: "long", year: "numeric" })}</h2>
        <p class="dim">Everything with a date on it: events, what is due on
          the board, a client's milestones, and classes that were held.
          One month, four calendars' worth — and any day opens.</p></div>
      <div class="top-actions">
        <select id="cal-mon" title="month">${MONTHS.map((m, i) =>
          `<option value="${i}"${i === base.getMonth() ? " selected" : ""}
            >${m}</option>`).join("")}</select>
        <select id="cal-year" title="year">${(() => {
          const y = base.getFullYear(); const out = [];
          /* Five back and five on: far enough for last year's accounts and
             next year's booked-in work, short enough to be one glance. A
             year outside it is a step away with the arrows. */
          for (let i = y - 5; i <= y + 5; i++)
            out.push(`<option value="${i}"${i === y ? " selected" : ""}
              >${i}</option>`);
          return out.join("");
        })()}</select>
        <button class="btn alt icon-btn" id="cal-prev"
          title="the month before">&larr;</button>
        <button class="btn alt" id="cal-today">Today</button>
        <button class="btn alt icon-btn" id="cal-next"
          title="the month after">&rarr;</button>
      </div>
    </div>
    <div class="cal-legend">
      ${Object.keys(CAL_ICON).map((k) => `<span class="cal-key cal-${k}">
        ${esc(k)}</span>`).join("")}
    </div>
    <div class="cal-grid">
      ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((w) =>
        `<div class="cal-w">${w}</div>`).join("")}
      ${cells.join("")}
    </div>
    ${d.items.length ? "" : '<div class="card empty"><b>Nothing dated this '
      + 'month</b><span class="dim">Events, ticket due dates and client '
      + 'milestones all land here.</span></div>'}`;
  const move = (n) => {
    const x = new Date(CAL_MONTH); x.setMonth(x.getMonth() + n);
    CAL_MONTH = x.getTime(); renderCalendar();
  };
  $("#cal-prev").onclick = () => move(-1);
  $("#cal-next").onclick = () => move(1);
  $("#cal-today").onclick = () => { CAL_MONTH = null; renderCalendar(); };
  const jump = () => {
    CAL_MONTH = new Date(+$("#cal-year").value, +$("#cal-mon").value, 1)
      .getTime();
    renderCalendar();
  };
  $("#cal-mon").onchange = jump;
  $("#cal-year").onchange = jump;
  // A day is a thing with a shape of its own — who is on it, what is due,
  // who could cover it. The grid can only ever say there are three.
  view().querySelectorAll("[data-calday]").forEach((c) => c.onclick = (ev) => {
    if (ev.target.closest("a")) return;      // an item is its own link
    dayView(+c.dataset.calday, S.user && S.user.is_admin ? true : null);
  });
}
