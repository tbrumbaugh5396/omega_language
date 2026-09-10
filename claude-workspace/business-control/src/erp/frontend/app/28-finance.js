// ---------- owed and planned ----------
/* Accounting records what happened, Treasury says where the money is now,
   and neither answers who owes us, whether we are where we said we would
   be, and what the next few weeks look like. Receivables and payables are
   derived from rows that already exist, so nothing can be paid here and
   still owed there. Only the budget is stored, being the one number that
   is not a consequence of something else. */
async function renderFinance() {
  const d = await api("/api/finance");
  const r = d.receivables;
  const p = d.payables;
  const f = d.forecast;
  const w = d.working_capital;
  const aged = [["current", "under 30 days"], ["30", "30 to 60"],
                ["60", "60 to 90"], ["90", "over 90 days"]];
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Owed & planned</h2>
        <p class="dim">What is owed each way, how the year is going against
          the plan, and what the weeks ahead look like.</p></div>
      <div class="top-actions">
        <button class="btn" id="fin-budget">New budget</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Owed to us</span>
        <b>${money(r.total_cents)}</b>
        <span class="dim">${r.rows.length} unpaid order${r.rows.length === 1 ? "" : "s"}</span></div>
      <div class="card tile"><span class="dim">We owe</span>
        <b>${money(p.total_cents)}</b>
        <span class="dim">${money(p.staff_cents)} to staff, ${money(p.po_cents)} on order</span></div>
      <div class="card tile"><span class="dim">Working capital</span>
        <b>${money(w.working_capital_cents)}</b>
        <span class="dim">${w.ratio_bps ? (w.ratio_bps / 10000).toFixed(2) + "× cover" : "nothing owed"}</span></div>
      <div class="card tile"><span class="dim">Lowest point ahead</span>
        <b>${money(f.lowest_cents)}</b>
        <span class="dim">${f.goes_negative ? "runs out inside the window" : "stays positive"}</span></div>
    </div>
    <h3>Owed to us</h3>
    <div class="card">
      <div class="chips">${aged.map(([k, label]) =>
        `<span class="pill ${k === "90" && r.aged[k] ? "bad" : k === "60" && r.aged[k] ? "warn" : ""}">${
          esc(label)}: ${money(r.aged[k])}</span>`).join("")}</div>
      ${r.rows.length ? `<div class="tablewrap" style="margin-top:10px"><table>
        <thead><tr><th>order</th><th>who</th><th>placed</th><th>age</th>
          <th>amount</th></tr></thead>
        <tbody>${r.rows.slice(0, 60).map((x) => `<tr>
          <td>#${x.id}</td><td>${esc(x.who || "—")}
            ${x.email ? `<br><span class="dim">${esc(x.email)}</span>` : ""}</td>
          <td class="dim">${fmtDate(x.created_at)}</td>
          <td class="${x.days > 60 ? "" : "dim"}">${x.days} days</td>
          <td>${money(x.total_cents)}</td></tr>`).join("")}</tbody>
      </table></div>
      ${r.rows.length > 60 ? `<p class="dim">Showing 60 of ${r.rows.length}.</p>` : ""}`
        : '<p class="dim">Nothing outstanding.</p>'}
    </div>
    <h3>We owe</h3>
    <div class="card">
      ${p.staff.length ? `<b>To staff, for things they paid for</b>
      <div class="tablewrap"><table>
        <thead><tr><th>who</th><th>what</th><th>when</th><th>amount</th></tr></thead>
        <tbody>${p.staff.map((x) => `<tr>
          <td>${esc(x.who)}</td><td>${esc(x.category)} ${esc(x.vendor || "")}</td>
          <td class="dim">${fmtDate(x.spent_at)}</td>
          <td>${money(x.amount_cents)}</td></tr>`).join("")}</tbody>
      </table></div>` : ""}
      ${p.purchase_orders.length ? `<b style="display:block;margin-top:10px">On order and not yet received</b>
      <div class="tablewrap"><table>
        <thead><tr><th>order</th><th>supplier</th><th>status</th>
          <th>still to come</th></tr></thead>
        <tbody>${p.purchase_orders.map((x) => `<tr>
          <td>#${x.id}</td><td>${esc(x.who || "—")}</td>
          <td class="dim">${esc(x.status)}</td>
          <td>${money(x.total_cents)}</td></tr>`).join("")}</tbody>
      </table></div>` : ""}
      ${!p.staff.length && !p.purchase_orders.length
        ? '<p class="dim">Nothing owed.</p>' : ""}
    </div>
    <h3>Against the plan</h3>
    ${d.budget ? `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(d.budget.label)}</b>
          <span class="dim">${fmtDate(d.budget.starts)} to ${fmtDate(d.budget.ends)}</span></div>
        <button class="btn alt sm" id="fin-line">Add a line</button>
      </div>
      ${d.budget.lines.length ? `<div class="tablewrap"><table>
        <thead><tr><th>account</th><th>planned</th><th>actual</th>
          <th>difference</th><th></th></tr></thead>
        <tbody>${d.budget.lines.map((l) => `<tr>
          <td>${esc(l.account)} ${esc(l.name)}
            <span class="dim">${esc(l.kind)}</span></td>
          <td>${money(l.planned_cents)}</td><td>${money(l.actual_cents)}</td>
          <td>${money(l.variance_cents)}</td>
          <td>${l.on_track ? '<span class="pill ok">on track</span>'
            : '<span class="pill warn">off</span>'}
            <button class="btn alt sm" data-findel="${esc(l.account)}">Remove</button></td>
        </tr>`).join("")}</tbody></table></div>
        <p class="dim">Actuals come from the ledger, so a budget and the
          books cannot drift into two definitions of a cost. For a cost,
          under plan is on track; for income it is the other way round.</p>`
        : '<p class="dim">No lines yet — add one per account you plan against.</p>'}
    </div>` : emptyState("chart", "No budget yet",
        "A budget is a line per account for a period, and the useful thing "
        + "to do with one is put the actual beside it.")}
    <h3>The weeks ahead</h3>
    <div class="card">
      <p class="dim">${esc(f.note)}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>week of</th><th>in</th><th>out</th><th>closing</th></tr></thead>
        <tbody>${f.weeks.map((x) => `<tr>
          <td class="dim">${fmtDate(x.starts)}</td>
          <td>${x.in_cents ? money(x.in_cents) : ""}</td>
          <td>${x.out_cents ? money(x.out_cents) : ""}</td>
          <td class="${x.closing_cents < 0 ? "" : "dim"}">
            ${x.closing_cents < 0 ? '<span class="pill bad">' : ""}${money(x.closing_cents)}${
              x.closing_cents < 0 ? "</span>" : ""}</td>
        </tr>`).join("")}</tbody></table></div>
    </div>`;

  $("#fin-budget").onclick = () => {
    modal(`<h3>New budget</h3>
      <label>Label</label><input id="fin-label" placeholder="2027">
      <div class="row2">
        <div><label>From</label><input id="fin-from" type="date"></div>
        <div><label>To</label><input id="fin-to" type="date"></div>
      </div>
      <p><button class="btn" id="finb-save">Create</button></p>`);
    $("#finb-save").onclick = async () => {
      try {
        await api("/api/finance/budgets", { body: {
          label: $("#fin-label").value,
          starts: new Date($("#fin-from").value).getTime() / 1000,
          ends: new Date($("#fin-to").value).getTime() / 1000 } });
        closeModal(); renderFinance();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#fin-line")) $("#fin-line").onclick = () => {
    modal(`<h3>Add a budget line</h3>
      <label>Account</label><select id="fin-acct">${d.accounts.map((a) =>
        `<option value="${esc(a.code)}">${esc(a.code)} ${esc(a.name)} · ${esc(a.kind)}</option>`).join("")}</select>
      <label>Planned for the period ($)</label>
      <input id="fin-amt" type="number" step="0.01">
      <p><button class="btn" id="fin-lsave">Add</button></p>`);
    $("#fin-lsave").onclick = async () => {
      try {
        await api(`/api/finance/budgets/${d.budget.id}/lines`, { body: {
          account: $("#fin-acct").value,
          amount_cents: Math.round(parseFloat($("#fin-amt").value || 0) * 100) } });
        closeModal(); renderFinance();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-findel]").forEach((b) => b.onclick = async () => {
    await api(`/api/finance/budgets/${d.budget.id}/lines/${b.dataset.findel}`,
              { method: "DELETE" });
    renderFinance();
  });
}
