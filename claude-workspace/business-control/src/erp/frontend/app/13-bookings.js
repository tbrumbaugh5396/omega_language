/* Bookings: services that happen at a time, and who is coming.

   Two lists. The services — what the shop sells by the hour, each one
   saying which room and which people it needs — and the diary: every
   appointment ahead, held or confirmed, with the three things a shop
   says about one afterwards. A held one is a person mid-checkout and
   is shown, not hidden: a slot that looks free and is not is how two
   people get told 2:30. */

const BK_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const BK_STATE = {
  held: ["held", "somebody is mid-checkout — it frees itself if they don't finish"],
  confirmed: ["booked", "paid for, or booked by staff"],
  done: ["done", ""], no_show: ["no-show", "did not turn up"],
  cancelled: ["cancelled", ""],
};

function bkHM(min) {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${
    String(min % 60).padStart(2, "0")}`;
}
function bkWhen(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric",
    month: "short" }) + " " + d.toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit" });
}

async function renderBookings() {
  const [sv, ap] = await Promise.all([
    api("/api/store/admin/services").catch((e) => ({ services: [], err: e })),
    api("/api/store/admin/appointments?days=14").catch(() => ({ appointments: [] })),
  ]);
  const services = sv.services || [];
  const appts = ap.appointments || [];
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Bookings</h2>
        <p class="dim">${esc(sv.note || "Things that happen at a time.")}</p></div>
      <span class="chips">
        <button class="btn alt" id="bk-staffbook" ${services.length ? "" : "disabled"}
          title="the phone rang — book on somebody's behalf">Book for someone</button>
        <button class="btn" id="bk-new">${opsIcon("calendar", "btn-ic")}
          Add a service</button></span>
    </div>
    ${services.length ? `<div class="sig-rows">${services.map((s) => `
      <div class="doc-line bk-line${s.active ? "" : " dim"}">
        <span class="dl-title"><b>${esc(s.name)}</b>
          <span class="dim">${s.duration_min} min${s.buffer_min
            ? " + " + s.buffer_min + " turnaround" : ""}${s.product
            ? " · " + esc(s.product) + " · " + money(s.price_cents)
            : " · not sold online"}${s.active ? "" : " · off"}</span></span>
        <span class="bk-needs dim">
          ${s.room ? `<span title="needs this room free">${esc(s.room)}</span>` : ""}
          ${s.staff.length ? `<span title="needs one of these free">${
            s.staff.map((u) => esc(u.name)).join(" / ")}</span>` : ""}
          ${!s.room && !s.staff.length ? `<span>${s.capacity} at a time</span>` : ""}
        </span>
        <span class="bk-hours dim">${s.days.map((on, i) => on ? BK_DAYS[i] : "")
          .filter(Boolean).join(" ")} · ${bkHM(s.from_min)}–${bkHM(s.to_min)}</span>
        <span class="bk-count"><b>${s.upcoming}</b> <span class="dim">ahead</span></span>
        <span class="dl-acts">
          <button class="btn alt sm" data-bkedit="${s.id}">Edit</button>
        </span>
      </div>`).join("")}</div>`
      : `<div class="card empty"><b>Nothing bookable yet</b>
         <span class="dim">Add a service: how long it takes, when it runs,
         and whether it needs a room, a person, or just a count.</span></div>`}

    <h3 style="margin-top:18px">Coming up
      <span class="dim" style="font-weight:400">· next 14 days${ap.today
        ? ` · ${ap.today} today` : ""}</span></h3>
    ${appts.length ? `<div class="card"><table>
      <thead><tr><th>when</th><th>who</th><th>what</th><th>with</th>
        <th></th><th>intake</th><th></th></tr></thead>
      <tbody>${appts.map((a) => `<tr class="${a.state === "held" ? "dim" : ""}">
        <td>${bkWhen(a.starts)}</td>
        <td><b>${esc(a.who)}</b>${a.email
          ? `<span class="dim"> ${esc(a.email)}</span>` : ""}</td>
        <td>${esc(a.service)}${a.room ? `<span class="dim"> · ${esc(a.room)}</span>` : ""}</td>
        <td class="dim">${esc(a.staff || "—")}</td>
        <td><span class="pill ${a.state === "confirmed" ? "ok"
          : a.state === "no_show" ? "bad" : ""}" title="${
          (BK_STATE[a.state] || [])[1] || ""}">${(BK_STATE[a.state] || [a.state])[0]}</span></td>
        <td>${(a.answers || []).length ? `<details class="bk-answers"><summary>${
          a.answers.length} answer${a.answers.length === 1 ? "" : "s"}</summary>${
          a.answers.map((x) => `<div><span class="dim">${esc(x.label)}</span> ${esc(x.answer || "—")}</div>`).join("")}
          </details>` : (a.missing || []).length ? `<span class="dim" title="${esc(a.missing.join("; "))}">form unfinished</span>` : ""}</td>
        <td class="row-acts">${a.state === "confirmed" ? `
          <button class="btn alt sm" data-bkstate="${a.id}:done">Done</button>
          <button class="btn alt sm" data-bkstate="${a.id}:no_show">No-show</button>
          <button class="btn alt sm" data-bkstate="${a.id}:cancelled">Cancel</button>`
          : a.state === "held" ? `<span class="dim">holding</span>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">Nobody booked in the next fortnight.</p>`}`;

  $("#bk-new").onclick = () => bkServiceForm(null);
  const sb = $("#bk-staffbook");
  if (sb) sb.onclick = () => bkStaffBook(services);
  view().querySelectorAll("[data-bkedit]").forEach((b) => b.onclick = () =>
    bkServiceForm(services.find((s) => s.id === +b.dataset.bkedit)));
  view().querySelectorAll("[data-bkstate]").forEach((b) => b.onclick = async () => {
    const [id, state] = b.dataset.bkstate.split(":");
    try {
      await api(`/api/store/admin/appointments/${id}/state`, { body: { state } });
      toast(state === "cancelled" ? "cancelled — the time is free again"
        : `marked ${BK_STATE[state][0]}`);
      renderBookings();
    } catch (e) { toast(e.message); }
  });
}

const BK_QKINDS = { text: "short answer", long: "a paragraph", number: "a number",
  yesno: "yes / no", choice: "one of a list" };
function bkQuestionRow(q) {
  return `<div class="bk-qrow" data-qkey="${esc(q.key || "")}">
    <input data-qlabel placeholder="Dog's name and breed" value="${esc(q.label || "")}">
    <select data-qkind>${Object.entries(BK_QKINDS).map(([k, l]) =>
      `<option value="${k}" ${(q.kind || "text") === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <label class="chip ${q.required ? "on" : ""}" title="the order will not go through without it">
      <input type="checkbox" data-qreq hidden ${q.required ? "checked" : ""}>required</label>
    <input data-qchoices placeholder="choices, comma-separated" value="${esc((q.choices || []).join(", "))}"
      ${(q.kind || "text") === "choice" ? "" : "hidden"}>
    <button class="btn alt sm" type="button" data-qdel>remove</button>
  </div>`;
}

/* What the customer would have typed, typed by whoever answered the
   phone. Same questions, same rows, so the day's sheet reads the same
   whichever way the booking came in. */
function bkIntakeFields(qs) {
  return (qs || []).map((q) => `<label class="bk-iq">${esc(q.label)}${q.required
      ? ' <span class="dim">(required online)</span>' : ""}
    ${q.kind === "long" ? `<textarea data-iq="${esc(q.key)}" rows="2"></textarea>`
      : q.kind === "yesno" ? `<select data-iq="${esc(q.key)}"><option value="">—</option>
          <option>yes</option><option>no</option></select>`
      : q.kind === "choice" ? `<select data-iq="${esc(q.key)}"><option value="">—</option>${
          (q.choices || []).map((c) => `<option>${esc(c)}</option>`).join("")}</select>`
      : `<input data-iq="${esc(q.key)}" ${q.kind === "number" ? 'type="number"' : ""}>`}
  </label>`).join("");
}

/* The form asks the three questions a slot is made of — a room, some
   people, a count — and lets any of them be blank. */
async function bkServiceForm(s) {
  const [prods, rms, users] = await Promise.all([
    api("/api/products").catch(() => []),
    api("/api/rooms").catch(() => ({ rooms: [] })),
    api("/api/admin/users").catch(() => []),
  ]);
  const staff = (Array.isArray(users) ? users : users.users || [])
    .filter((u) => u.role !== "customer");
  const v = s || { name: "", product_id: 0, duration_min: 60, buffer_min: 0,
    capacity: 1, room_id: 0, staff_ids: [], days: [1, 1, 1, 1, 1, 0, 0],
    from_min: 540, to_min: 1020, lead_hours: 2, horizon_days: 30,
    blurb: "", active: true };
  modal(`<h3>${s ? "Edit " + esc(s.name) : "A bookable service"}</h3>
    <div class="edit-grid">
      <label>Name<input id="bk-name" value="${esc(v.name)}"
        placeholder="Full groom"></label>
      <label>Sold as
        <select id="bk-product">
          <option value="0">not sold online — staff book it</option>
          ${(Array.isArray(prods) ? prods : []).map((p) => `<option value="${p.id}"
            ${p.id === v.product_id ? "selected" : ""}>${esc(p.name)} · ${
            money(p.price_cents)}</option>`).join("")}
        </select></label>
      <label>Takes (minutes)<input id="bk-dur" type="number" min="5"
        value="${v.duration_min}"></label>
      <label>Turnaround after (minutes)<input id="bk-buf" type="number" min="0"
        value="${v.buffer_min}"></label>
      <label>Needs this room
        <select id="bk-svc-room"><option value="0">no room</option>
          ${(rms.rooms || []).map((r) => `<option value="${r.id}"
            ${r.id === v.room_id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}
        </select></label>
      <label>At a time (if no room or person)<input id="bk-cap" type="number"
        min="1" value="${v.capacity}"></label>
    </div>
    <p class="dim" style="margin:10px 0 4px">Needs one of these people free
      <span class="dim">— their rota is respected; nobody named means nobody needed</span></p>
    <div class="chips" id="bk-staff">${staff.map((u) => `
      <label class="chip ${v.staff_ids.includes(u.id) ? "on" : ""}">
        <input type="checkbox" value="${u.id}" hidden
          ${v.staff_ids.includes(u.id) ? "checked" : ""}>${esc(u.name)}</label>`).join("")}</div>
    <p class="dim" style="margin:10px 0 4px">Runs on</p>
    <div class="chips" id="bk-days">${BK_DAYS.map((d, i) => `
      <label class="chip ${v.days[i] ? "on" : ""}">
        <input type="checkbox" value="${i}" hidden ${v.days[i] ? "checked" : ""}>${d}</label>`).join("")}</div>
    <div class="edit-grid" style="margin-top:10px">
      <label>From<input id="bk-from" type="time" value="${bkHM(v.from_min)}"></label>
      <label>Until<input id="bk-to" type="time" value="${bkHM(v.to_min)}"></label>
      <label>Notice needed (hours)<input id="bk-lead" type="number" min="0"
        value="${v.lead_hours}"></label>
      <label>Bookable ahead (days)<input id="bk-horizon" type="number" min="1"
        value="${v.horizon_days}"></label>
    </div>
    <label style="display:block;margin-top:10px">What the customer reads
      <textarea id="bk-blurb" rows="2">${esc(v.blurb)}</textarea></label>
    <p class="dim" style="margin:12px 0 4px">Ask before the appointment
      <span class="dim">— answered once the time is held; the order will not go
      through until the required ones are</span></p>
    <div id="bk-qs">${(v.intake || []).map(bkQuestionRow).join("")}</div>
    <button class="btn alt sm" id="bk-addq" type="button">Add a question</button>
    ${s ? `<div><label class="chip bk-toggle ${v.active ? "on" : ""}">
      <input type="checkbox" id="bk-active" hidden ${v.active ? "checked" : ""}>
      taking bookings</label></div>` : ""}
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="bk-save">${s ? "Save" : "Add"}</button></div>`, "wide");
  document.querySelectorAll("#bk-staff .chip, #bk-days .chip, label.chip").forEach((c) => {
    const box = c.querySelector("input");
    c.onclick = (e) => { e.preventDefault(); box.checked = !box.checked;
      c.classList.toggle("on", box.checked); };
  });
  const mins = (id) => { const [h, m] = $(id).value.split(":").map(Number);
    return h * 60 + (m || 0); };
  const wireQs = () => {
    document.querySelectorAll("#bk-qs [data-qdel]").forEach((b) => b.onclick = () =>
      b.closest(".bk-qrow").remove());
    document.querySelectorAll("#bk-qs select[data-qkind]").forEach((sel) => sel.onchange = () => {
      const row = sel.closest(".bk-qrow");
      row.querySelector("[data-qchoices]").hidden = sel.value !== "choice";
    });
  };
  wireQs();
  $("#bk-addq").onclick = () => {
    $("#bk-qs").insertAdjacentHTML("beforeend", bkQuestionRow({}));
    wireQs();
  };
  $("#bk-save").onclick = async () => {
    const body = {
      name: $("#bk-name").value, product_id: +$("#bk-product").value,
      duration_min: +$("#bk-dur").value, buffer_min: +$("#bk-buf").value,
      capacity: +$("#bk-cap").value, room_id: +$("#bk-svc-room").value,
      staff_ids: [...document.querySelectorAll("#bk-staff input:checked")]
        .map((i) => +i.value),
      days: BK_DAYS.map((_, i) => !!document.querySelector(
        `#bk-days input[value="${i}"]:checked`)),
      from_min: mins("#bk-from"), to_min: mins("#bk-to"),
      lead_hours: +$("#bk-lead").value, horizon_days: +$("#bk-horizon").value,
      blurb: $("#bk-blurb").value,
      active: s ? $("#bk-active").checked : true,
      intake: [...document.querySelectorAll("#bk-qs .bk-qrow")].map((row) => ({
        key: row.dataset.qkey || "",
        label: row.querySelector("[data-qlabel]").value,
        kind: row.querySelector("[data-qkind]").value,
        required: row.querySelector("[data-qreq]").checked,
        choices: row.querySelector("[data-qchoices]").value.split(",")
          .map((x) => x.trim()).filter(Boolean),
      })).filter((q) => q.label.trim()),
    };
    try {
      if (s) await api(`/api/store/admin/services/${s.id}`,
        { method: "PATCH", body });
      else await api("/api/store/admin/services", { body });
      closeModal(); toast("Saved"); renderBookings();
    } catch (e) { toast(e.message); }
  };
}

/* Booking on somebody's behalf: pick the service, pick the day, pick from
   the times that are actually free. Same slot query the storefront uses,
   so the phone and the website never disagree about 2:30. */
async function bkStaffBook(services) {
  const live = services.filter((s) => s.active);
  const today = new Date(); today.setHours(12, 0, 0, 0);
  modal(`<h3>Book for someone</h3>
    <div class="edit-grid">
      <label>Service<select id="bks-svc">${live.map((s) => `
        <option value="${s.id}">${esc(s.name)} · ${s.duration_min} min</option>`).join("")}
      </select></label>
      <label>Day<input id="bks-day" type="date"
        value="${today.toISOString().slice(0, 10)}"></label>
      <label>Name<input id="bks-name" placeholder="who it's for"></label>
      <label>Email<input id="bks-email" type="email" placeholder="optional"></label>
    </div>
    <div id="bks-intake"></div>
    <label style="display:block;margin-top:10px">Note
      <input id="bks-note" placeholder="anything else they said"></label>
    <p class="dim" style="margin:10px 0 4px">Free times — pick one to book</p>
    <div class="chips bk-slots" id="bks-slots"><span class="dim">loading…</span></div>
    <div class="modal-foot"><button class="btn alt" data-close>Close</button></div>`,
  "wide");
  let picked = null;
  const askQs = () => {
    const sv = live.find((x) => x.id === +$("#bks-svc").value);
    $("#bks-intake").innerHTML = sv && (sv.intake || []).length
      ? `<p class="dim" style="margin:10px 0 4px">Ask them</p>${bkIntakeFields(sv.intake)}` : "";
  };
  askQs();
  const load = async () => {
    const sid = +$("#bks-svc").value;
    const day = new Date($("#bks-day").value + "T12:00:00").getTime() / 1000;
    const host = $("#bks-slots");
    host.innerHTML = `<span class="dim">loading…</span>`;
    try {
      const d = await api(`/api/store/services/${sid}/slots?day=${day}`);
      const slots = d.days[0].slots;
      host.innerHTML = slots.length ? slots.map((x) => `
        <button class="chip ${x.free ? "" : "off"}" ${x.free ? "" : "disabled"}
          data-slot="${x.starts}" title="${x.free ? "" : esc(x.why)}">${
          new Date(x.starts * 1000).toLocaleTimeString(undefined,
            { hour: "2-digit", minute: "2-digit" })}${x.free ? "" : ` · ${esc(x.why)}`}
        </button>`).join("")
        : `<span class="dim">does not run that day</span>`;
      host.querySelectorAll("[data-slot]").forEach((b) => b.onclick = async () => {
        picked = +b.dataset.slot;
        try {
          const answers = {};
          document.querySelectorAll("#bks-intake [data-iq]").forEach((el) => {
            if (el.value) answers[el.dataset.iq] = el.value; });
          const r = await api("/api/store/admin/appointments", { body: {
            service_id: sid, starts: picked, name: $("#bks-name").value,
            email: $("#bks-email").value, note: $("#bks-note").value, answers } });
          closeModal(); renderBookings();
          toast((r.missing || []).length ? `booked — still to ask: ${r.missing.join("; ")}` : "booked");
        } catch (e) { toast(e.message); }
      });
    } catch (e) { host.innerHTML = `<span class="dim">${esc(e.message)}</span>`; }
  };
  $("#bks-svc").onchange = () => { askQs(); load(); }; $("#bks-day").onchange = load;
  load();
}
