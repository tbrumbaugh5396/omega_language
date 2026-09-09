// ---------- expenses, mileage, and the year ----------
/* Money out, and what the return will want. Everyone on staff files an
   expense or a trip here; the office accepts, declines and pays; the year
   card is what the accountant gets — income, sales tax collected,
   deductible expenses by category, mileage, what is owed to people, and
   a rough estimate of the tax on what is left. */
let EXP_YEAR = null, EXP_VIEW = "expenses";

async function renderExpenses() {
  const meta = await api("/api/expenses/meta");
  const year = EXP_YEAR || meta.year;
  const s = meta.settings;
  const [ex, tr, sum] = await Promise.all([
    api(`/api/expenses?year=${year}`),
    api(`/api/trips?year=${year}`),
    meta.office ? api(`/api/expenses/summary?year=${year}`).catch(() => null) : null,
  ]);
  const day = (t) => new Date(t * 1000).toLocaleDateString(undefined,
    { month: "short", day: "numeric", year: "numeric" });
  const pill = (st) => `<span class="pill ${st === "approved" ? "ok" : st === "paid" ? "ok"
    : st === "declined" ? "bad" : st === "pending" ? "warn" : ""}">${esc(st)}</span>`;
  const decideBtns = (kind, r) => `
    ${meta.office && r.state === "pending" ? `
      <button class="btn sm" data-xd="${kind}:${r.id}:approved">Accept</button>
      <button class="btn alt sm" data-xd="${kind}:${r.id}:declined">Decline</button>` : ""}
    ${meta.office && r.state === "approved" && (kind === "e" ? r.paid_by === "me" : r.vehicle === "own")
      ? `<button class="btn sm" data-xd="${kind}:${r.id}:paid">Mark paid</button>` : ""}
    ${r.user_id === meta.me && r.state === "pending"
      ? `<button class="btn alt sm" data-xd="${kind}:${r.id}:withdrawn">Withdraw</button>` : ""}`;
  const expRow = (r) => `<tr>
    <td>${day(r.spent_at)}</td>
    <td><b>${esc(r.category_label)}</b>${r.vendor ? `<div class="dim">${esc(r.vendor)}</div>` : ""}</td>
    <td class="dim">${esc(r.who)}${r.paid_by === "me" ? ' <span class="pill">claim</span>' : ""}${
      r.recurring ? ` <span class="dim">· ${esc(r.recurring)}</span>` : ""}</td>
    <td class="num">${money(r.amount_cents)}${r.business_pct !== 100
      ? `<div class="dim">${r.business_pct}% · ${money(r.deductible_cents)}</div>` : ""}</td>
    <td class="dim">${esc(r.note || "")}</td>
    <td>${r.receipt_url ? `<a href="${esc(r.receipt_url)}" target="_blank" rel="noopener">receipt</a>`
      : (r.user_id === meta.me || meta.office) ? `<label class="btn alt sm">Add receipt<input type="file"
          hidden data-xr="${r.id}" accept="image/*,.pdf"></label>` : '<span class="dim">none</span>'}</td>
    <td>${pill(r.state)}${r.decided_by ? `<div class="dim">${esc(r.decided_by)}${
      r.decided_note ? " · " + esc(r.decided_note) : ""}</div>` : ""}</td>
    <td class="row-acts">${decideBtns("e", r)}</td>
  </tr>`;
  const tripRow = (r) => `<tr>
    <td>${day(r.driven_at)}</td>
    <td><b>${esc(r.purpose || (r.from_place + " → " + r.to_place))}</b>${
      r.purpose && (r.from_place || r.to_place) ? `<div class="dim">${esc(r.from_place)} → ${esc(r.to_place)}</div>` : ""}</td>
    <td class="dim">${esc(r.who)}</td>
    <td class="num">${r.distance} ${esc(r.unit)}</td>
    <td class="dim">${r.vehicle === "own" ? "own car" : esc(r.truck || "company vehicle")}</td>
    <td class="num">${r.vehicle === "own" ? money(r.amount_cents) : '<span class="dim">—</span>'}</td>
    <td>${pill(r.state)}${r.decided_by ? `<div class="dim">${esc(r.decided_by)}${
      r.decided_note ? " · " + esc(r.decided_note) : ""}</div>` : ""}</td>
    <td class="row-acts">${decideBtns("t", r)}</td>
  </tr>`;
  const stat = (n, v, sub) => `<div class="stu-stat"><b>${v}</b><span class="dim">${n}</span>${
    sub ? `<span class="dim stu-sub">${sub}</span>` : ""}</div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Expenses &amp; mileage</h2>
        <p class="dim">What went out, and what the return will want. File an
          expense or a trip; the office accepts it; the year adds up.</p></div>
      <div class="top-actions">
        <span class="chips">
          <button class="btn alt sm${year === meta.year - 1 ? " on" : ""}" data-xy="${meta.year - 1}">${meta.year - 1}</button>
          <button class="btn alt sm${year === meta.year ? " on" : ""}" data-xy="${meta.year}">${meta.year}</button>
        </span>
        ${meta.may_file ? `<button class="btn alt" id="xp-trip">Log a trip</button>
          <button class="btn" id="xp-new">Log an expense</button>` : ""}
      </div>
    </div>
    ${sum ? `<div class="card">
      <div class="card-head"><b>The year ${sum.year}</b>
        <span class="dim">${day(sum.from)} – ${day(sum.to - 1)}</span>
        <span class="chips" style="margin-left:auto">
          <a class="btn alt sm" href="/api/expenses/export.csv?year=${sum.year}" download
            title="one line per accepted expense and trip, deductible share worked out">CSV for the accountant</a>
          <button class="btn alt sm" id="xp-settings">Rates &amp; tax year</button></span></div>
      <div class="stu-stats">
        ${stat("income", money(sum.income_cents), `${sum.orders} orders`)}
        ${stat("sales tax collected", money(sum.sales_tax_collected_cents),
          s.sales_tax_bps ? `at ${(s.sales_tax_bps / 100).toFixed(2)}%` : "no rate set")}
        ${stat("deductible expenses", money(sum.deductible_cents), `of ${money(sum.expenses_total_cents)} spent`)}
        ${stat("mileage", `${sum.mileage.distance} ${esc(sum.mileage.unit)}`,
          `${money(sum.mileage.amount_cents)} · ${sum.mileage.trips} trip${sum.mileage.trips === 1 ? "" : "s"}`)}
        ${stat("net before tax", money(sum.net_before_tax_cents))}
        ${stat("estimated tax", money(sum.estimated_tax_cents), `${s.income_tax_pct}% estimate`)}
      </div>
      <p class="dim">${esc(sum.estimate_note)}</p>
      <div class="row">
        <div style="flex:2;min-width:min(300px,100%)">
          ${sum.by_category.length ? `<div class="tablewrap"><table>
            <thead><tr><th>category</th><th class="num">spent</th><th class="num">deductible</th><th class="num">items</th></tr></thead>
            <tbody>${sum.by_category.map((k) => `<tr><td>${esc(k.label)}</td>
              <td class="num">${money(k.total_cents)}</td><td class="num">${money(k.deductible_cents)}</td>
              <td class="num">${k.count}</td></tr>`).join("")}</tbody></table></div>`
            : '<p class="dim">Nothing accepted for this year yet.</p>'}
        </div>
        <div style="flex:1;min-width:min(240px,100%)">
          <b>Owed to people</b> <span class="dim">· ${money(sum.owed_cents)}</span>
          ${sum.owed.length ? sum.owed.map((o) => `<div class="xp-owed"><span>${esc(o.name)}
            <span class="dim">· ${o.items} item${o.items === 1 ? "" : "s"}</span></span>
            <b>${money(o.cents)}</b></div>`).join("")
            : '<p class="dim">Nobody is waiting on a reimbursement.</p>'}
          ${sum.pending ? `<p class="dim"><span class="pill warn">${sum.pending} awaiting a decision</span></p>` : ""}
        </div>
      </div>
    </div>` : ""}
    <div class="chips" style="margin:6px 0 10px">
      <button class="btn alt sm${EXP_VIEW === "expenses" ? " on" : ""}" data-xv="expenses">Expenses
        <b>${ex.expenses.length}</b></button>
      <button class="btn alt sm${EXP_VIEW === "trips" ? " on" : ""}" data-xv="trips">Trips
        <b>${tr.trips.length}</b></button>
    </div>
    ${EXP_VIEW === "expenses" ? `<div class="card">
      ${ex.expenses.length ? `<div class="tablewrap"><table>
        <thead><tr><th>day</th><th>what</th><th>who</th><th class="num">amount</th><th>note</th><th>receipt</th><th>state</th><th></th></tr></thead>
        <tbody>${ex.expenses.map(expRow).join("")}</tbody></table></div>`
        : `<div class="empty"><b>Nothing filed for ${year}</b><span class="dim">Phone, hosting, fuel, a
          tyre, a course — log it with the receipt and the business share.</span></div>`}
    </div>` : `<div class="card">
      ${tr.unclaimed_routes.length ? `<div class="xp-unclaimed"><b>Finished routes you have not claimed</b>
        ${tr.unclaimed_routes.map((r) => `<div class="xp-owed"><span>${esc(r.name)}
          <span class="dim">· ${esc(r.truck)} · ${r.total_km} km · ${esc(r.route_date || day(r.created_at))}</span></span>
          <button class="btn sm" data-xroute="${r.id}">Claim</button></div>`).join("")}</div>` : ""}
      ${tr.trips.length ? `<div class="tablewrap"><table>
        <thead><tr><th>day</th><th>trip</th><th>who</th><th class="num">distance</th><th>vehicle</th><th class="num">owed</th><th>state</th><th></th></tr></thead>
        <tbody>${tr.trips.map(tripRow).join("")}</tbody></table></div>`
        : `<div class="empty"><b>No trips for ${year}</b><span class="dim">Own car at
          ${(s.mileage_rate_cents / 100).toFixed(2)} per ${esc(s.distance_unit)} is reimbursed;
          a company vehicle's trip is a record of distance.</span></div>`}
    </div>`}`;
  view().querySelectorAll("[data-xy]").forEach((b) => b.onclick = () => { EXP_YEAR = +b.dataset.xy; renderExpenses(); });
  view().querySelectorAll("[data-xv]").forEach((b) => b.onclick = () => { EXP_VIEW = b.dataset.xv; renderExpenses(); });
  if ($("#xp-new")) $("#xp-new").onclick = () => expenseForm(meta, renderExpenses);
  if ($("#xp-trip")) $("#xp-trip").onclick = () => tripForm(meta, renderExpenses);
  if ($("#xp-settings")) $("#xp-settings").onclick = () => expenseSettingsForm(meta, renderExpenses);
  view().querySelectorAll("[data-xd]").forEach((b) => b.onclick = async () => {
    const [kind, id, state] = b.dataset.xd.split(":");
    let note = "";
    if (state === "declined") note = prompt("Why not? (they will see this)") || "";
    try {
      await api(`/api/${kind === "e" ? "expenses" : "trips"}/${id}/decide`, { body: { state, note } });
      renderExpenses();
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-xroute]").forEach((b) => b.onclick = async () => {
    try { const r = await api(`/api/trips/from-route/${b.dataset.xroute}`, { body: {} });
      toast(`claimed — ${r.distance} ${r.unit}`); renderExpenses(); }
    catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-xr]").forEach((inp) => inp.onchange = async () => {
    const f = inp.files && inp.files[0];
    if (!f) return;
    try {
      const r = await fetch(`/api/expenses/${inp.dataset.xr}/receipt`, {
        method: "POST",
        headers: { "Content-Type": f.type || "application/octet-stream",
                   "X-Filename": f.name, Authorization: "Bearer " + S.user.token },
        body: f });
      if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
      toast("receipt kept"); renderExpenses();
    } catch (err) { toast(err.message); }
  });
}

/* One thing paid for. The category carries a default business share — a
   phone is half work, a meal usually half allowed — which the person can
   correct. Who paid decides whether it is a fact or a claim. */
function expenseForm(meta, after) {
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const cats = meta.categories;
  modal(`<h3>Log an expense</h3>
    <div class="row2">
      <div><label>What for</label>
        <select id="xf-cat">${cats.map((c) => `<option value="${esc(c.code)}" data-pct="${c.default_pct}"
          data-hint="${esc(c.hint || "")}">${esc(c.label)}</option>`).join("")}</select>
        <span class="dim" id="xf-hint"></span></div>
      <div><label>Amount</label><input id="xf-amt" type="number" min="0.01" step="0.01" placeholder="0.00"></div>
    </div>
    <div class="row2">
      <div><label>Paid on</label><input id="xf-day" type="date" value="${today}"></div>
      <div><label>Business share <span class="opt">%</span></label>
        <input id="xf-pct" type="number" min="0" max="100" value="${cats[0] ? cats[0].default_pct : 100}"></div>
    </div>
    <div class="row2">
      <div><label>Who paid</label>
        <select id="xf-paid"><option value="company">The company</option>
          <option value="me">Me — I want it back</option></select></div>
      <div><label>Repeats</label>
        <select id="xf-rec"><option value="">once</option><option value="monthly">monthly</option>
          <option value="yearly">yearly</option></select></div>
    </div>
    <label>Vendor <span class="opt">optional</span></label>
    <input id="xf-vendor" placeholder="who was paid">
    <label>Note <span class="opt">optional</span></label>
    <input id="xf-note" placeholder="what it was for">
    <p class="dim">Add the receipt from the list afterwards — a deduction without one is a story.</p>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="xf-save">File it</button></div>`);
  const sel = $("#xf-cat");
  const sync = () => {
    const o = sel.options[sel.selectedIndex];
    $("#xf-pct").value = o.dataset.pct;
    $("#xf-hint").textContent = o.dataset.hint || "";
  };
  sel.onchange = sync; sync();
  $("#xf-save").onclick = async () => {
    const amt = Math.round(parseFloat($("#xf-amt").value || "0") * 100);
    if (!amt) return toast("an amount");
    try {
      const r = await api("/api/expenses", { body: {
        category: sel.value, amount_cents: amt,
        spent_at: $("#xf-day").value ? new Date($("#xf-day").value + "T12:00").getTime() / 1000 : 0,
        business_pct: +$("#xf-pct").value, paid_by: $("#xf-paid").value,
        recurring: $("#xf-rec").value, vendor: $("#xf-vendor").value.trim(),
        note: $("#xf-note").value.trim() } });
      closeModal();
      toast(r.state === "approved" ? "filed" : "filed — the office will accept it");
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}

/* A trip: distance, or two odometer readings. Own car is reimbursed at the
   rate; a company vehicle's trip is a record — its fuel and wear are
   expenses of their own. */
function tripForm(meta, after) {
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const s = meta.settings;
  modal(`<h3>Log a trip</h3>
    <div class="row2">
      <div><label>Day</label><input id="trp-day" type="date" value="${today}"></div>
      <div><label>Vehicle</label>
        <select id="trp-veh"><option value="own">My own car — reimburse me at ${(s.mileage_rate_cents / 100).toFixed(2)}/${esc(s.distance_unit)}</option>
          ${meta.trucks.map((t) => `<option value="company:${t.id}">${esc(t.name)} (company)</option>`).join("")}
          <option value="company:0">Another company vehicle</option></select></div>
    </div>
    <div class="row2">
      <div><label>From</label><input id="trp-from" placeholder="the office"></div>
      <div><label>To</label><input id="trp-to" placeholder="a client, a school, a supplier"></div>
    </div>
    <label>Purpose</label><input id="trp-why" placeholder="what the trip was for">
    <div class="row2">
      <div><label>Distance <span class="opt">${esc(s.distance_unit)}</span></label>
        <input id="trp-dist" type="number" min="0" step="0.1"></div>
      <div><label>Or odometer <span class="opt">start → end</span></label>
        <div style="display:flex;gap:6px"><input id="trp-o1" type="number" step="0.1" placeholder="start">
          <input id="trp-o2" type="number" step="0.1" placeholder="end"></div></div>
    </div>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="trp-save">File it</button></div>`);
  $("#trp-save").onclick = async () => {
    const [veh, tid] = $("#trp-veh").value.split(":");
    const o1 = $("#trp-o1").value, o2 = $("#trp-o2").value;
    try {
      const r = await api("/api/trips", { body: {
        driven_at: $("#trp-day").value ? new Date($("#trp-day").value + "T12:00").getTime() / 1000 : 0,
        from_place: $("#trp-from").value.trim(), to_place: $("#trp-to").value.trim(),
        purpose: $("#trp-why").value.trim(), distance: parseFloat($("#trp-dist").value || "0"),
        start_odo: o1 === "" ? null : +o1, end_odo: o2 === "" ? null : +o2,
        vehicle: veh, truck_id: +(tid || 0) } });
      closeModal();
      toast(`${r.distance} ${r.unit} filed${r.vehicle === "own" ? " — " + money(r.amount_cents) + " once accepted" : ""}`);
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}

function expenseSettingsForm(meta, after) {
  const s = meta.settings;
  modal(`<h3>Rates &amp; tax year</h3>
    <p class="dim">The mileage rate is whatever your tax authority publishes for the year;
      the income-tax percentage only drives the estimate on the year card.</p>
    <div class="row2">
      <div><label>Distance in</label>
        <select id="xs-unit"><option value="mi"${s.distance_unit === "mi" ? " selected" : ""}>miles</option>
          <option value="km"${s.distance_unit === "km" ? " selected" : ""}>kilometres</option></select></div>
      <div><label>Mileage rate <span class="opt">cents per unit</span></label>
        <input id="xs-rate" type="number" min="0" max="1000" value="${s.mileage_rate_cents}"></div>
    </div>
    <div class="row2">
      <div><label>Income tax estimate <span class="opt">%</span></label>
        <input id="xs-pct" type="number" min="0" max="100" step="0.5" value="${s.income_tax_pct}"></div>
      <div><label>Tax year starts in</label>
        <select id="xs-month">${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
          .map((m, i) => `<option value="${i + 1}"${s.tax_year_start_month === i + 1 ? " selected" : ""}>${m}</option>`).join("")}</select></div>
    </div>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="xs-save">Save</button></div>`);
  $("#xs-save").onclick = async () => {
    try {
      await api("/api/expenses/settings", { body: {
        distance_unit: $("#xs-unit").value, mileage_rate_cents: +$("#xs-rate").value,
        income_tax_pct: +$("#xs-pct").value, tax_year_start_month: +$("#xs-month").value } });
      closeModal(); if (after) after();
    } catch (err) { toast(err.message); }
  };
}
