// ---------- payroll ----------
/* Hours come from the same function the Hours screen uses, so a payslip
   and the timesheet behind it cannot disagree. A run is built, approved,
   then paid, and only paying reaches the ledger — until then a wage is a
   liability rather than a payment. No tax tables live here: deductions
   are the rates the operator typed, and the screen says so. */
async function renderPayroll() {
  const d = await api("/api/payroll");
  const stateLabel = { draft: "draft", approved: "approved", paid: "paid",
    cancelled: "cancelled" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Payroll</h2>
        <p class="dim">${esc(d.note)}</p></div>
      <div class="top-actions">
        <button class="btn alt" id="pay-ded">Deductions</button>
        <button class="btn alt" id="pay-rate">Set a rate</button>
        <button class="btn" id="pay-run">New run</button>
      </div>
    </div>
    ${d.without_rate.length ? `<div class="card">
      <b>${d.without_rate.length} on the payroll with no rate</b>
      <p class="dim">${d.without_rate.map(esc).join(", ")} — a run skips
        anybody without one rather than guessing at a number.</p>
    </div>` : ""}
    <h3>Runs</h3>
    ${d.runs.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>run</th><th>period</th><th>gross</th><th>deductions</th>
        <th>net</th><th>state</th><th></th></tr></thead>
      <tbody>${d.runs.map((r) => `<tr class="${r.state === "cancelled" ? "dim" : ""}">
        <td><b>${esc(r.label)}</b></td>
        <td class="dim">${fmtDate(r.period_start)} to ${fmtDate(r.period_end)}</td>
        <td>${money(r.gross_cents)}</td>
        <td>${money(r.deductions_cents)}
          ${r.employer_cents ? `<br><span class="dim">+${money(r.employer_cents)} employer</span>` : ""}</td>
        <td><b>${money(r.net_cents)}</b></td>
        <td><span class="pill ${r.state === "paid" ? "ok" : r.state === "approved" ? "warn" : ""}">${
          esc(stateLabel[r.state] || r.state)}</span>
          ${r.journal_id ? '<br><span class="dim">in the books</span>' : ""}</td>
        <td class="chips">
          <button class="btn alt sm" data-payopen="${r.id}">Payslips</button>
          ${r.state === "draft" ? `<button class="btn alt sm" data-paybuild="${r.id}">Build</button>
            <button class="btn sm" data-payok="${r.id}">Approve</button>
            <button class="btn alt sm" data-paycancel="${r.id}">Cancel</button>` : ""}
          ${r.state === "approved" ? `<button class="btn sm" data-paypaid="${r.id}">Mark paid</button>` : ""}
        </td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("users", "No runs yet",
          "A run is a period. Build it to work out the payslips, approve "
          + "to freeze them, and mark it paid when the money has gone.")}
    <h3>Rates</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>role</th><th>paid as</th><th>rate</th>
        <th>overtime</th><th>from</th></tr></thead>
      <tbody>${d.staff.map((s) => `<tr class="${s.rate ? "" : "dim"}">
        <td>${esc(s.name)}</td><td class="dim">${esc(s.role)}</td>
        <td class="dim">${esc(s.employment)}</td>
        <td>${s.rate ? (s.rate.kind === "salary"
          ? money(s.rate.rate_cents) + " a year"
          : money(s.rate.rate_cents) + " an hour") : "—"}</td>
        <td class="dim">${s.rate && s.rate.kind === "hourly"
          ? (s.rate.overtime_bps / 10000).toFixed(2) + "×" : ""}</td>
        <td class="dim">${s.rate ? fmtDate(s.rate.effective_from) : ""}</td>
      </tr>`).join("")}</tbody></table></div>
      <p class="dim">A rate is history, not a setting: a rise in April does
        not restate what March cost.</p>
    </div>`;

  $("#pay-run").onclick = () => {
    modal(`<h3>New run</h3>
      <label>Label</label><input id="pay-label" placeholder="March, or week 12">
      <div class="row2">
        <div><label>From</label><input id="pay-from" type="date"></div>
        <div><label>To</label><input id="pay-to" type="date"></div>
      </div>
      <label>Pay date <span class="dim">(when the money leaves)</span></label>
      <input id="pay-date" type="date">
      <p><button class="btn" id="payr-save">Create</button></p>`);
    $("#payr-save").onclick = async () => {
      const ts = (id) => $(id).value ? new Date($(id).value).getTime() / 1000 : 0;
      try {
        await api("/api/payroll/runs", { body: {
          label: $("#pay-label").value, period_start: ts("#pay-from"),
          period_end: ts("#pay-to"), pay_date: ts("#pay-date") } });
        closeModal(); renderPayroll();
      } catch (e) { toast(e.message); }
    };
  };
  $("#pay-rate").onclick = () => {
    modal(`<h3>Set a rate</h3>
      <label>Who</label><select id="pay-who">${d.staff.map((s) =>
        `<option value="${s.id}">${esc(s.name)} · ${esc(s.role)}</option>`).join("")}</select>
      <div class="row2">
        <div><label>Paid as</label><select id="pay-kind">${d.kinds.map((k) =>
          `<option value="${k}">${k}</option>`).join("")}</select></div>
        <div><label>Amount ($)</label><input id="pay-amt" type="number" step="0.01"></div>
      </div>
      <div class="row2">
        <div><label>Overtime multiplier</label><input id="pay-ot" type="number"
          step="0.05" value="1.5"></div>
        <div><label>From</label><input id="pay-eff" type="date"></div>
      </div>
      <p class="dim">An hourly rate is per hour; a salary is per year, and a
        run takes the period's share of it by how long the period is.</p>
      <p><button class="btn" id="pay-rsave">Save</button></p>`);
    $("#pay-rsave").onclick = async () => {
      try {
        await api("/api/payroll/rates", { body: {
          user_id: +$("#pay-who").value, kind: $("#pay-kind").value,
          rate_cents: Math.round(parseFloat($("#pay-amt").value || 0) * 100),
          overtime_bps: Math.round(parseFloat($("#pay-ot").value || 1.5) * 10000),
          effective_from: $("#pay-eff").value
            ? new Date($("#pay-eff").value).getTime() / 1000 : 0 } });
        closeModal(); renderPayroll();
      } catch (e) { toast(e.message); }
    };
  };
  $("#pay-ded").onclick = () => {
    modal(`<h3>Deductions</h3>
      <p class="dim">In order. A percentage can be of the gross or of what
        is left after the ones before it, which is what makes the order a
        field rather than an accident. Nothing here knows your tax rules.</p>
      ${d.deductions.length ? `<div class="tablewrap"><table>
        <thead><tr><th>#</th><th>what</th><th>how much</th><th>of</th>
          <th>side</th></tr></thead>
        <tbody>${d.deductions.map((x) => `<tr>
          <td class="dim">${x.position}</td><td>${esc(x.label)}</td>
          <td>${x.kind === "percent" ? (x.rate_bps / 100).toFixed(2) + "%"
            : money(x.amount_cents)}</td>
          <td class="dim">${x.of_remaining ? "what is left" : "gross"}</td>
          <td class="dim">${esc(x.side)}</td></tr>`).join("")}</tbody>
      </table></div>` : '<p class="dim">None yet — gross is net until you add one.</p>'}
      <h3 style="font-size:15px;margin-top:14px">Add one</h3>
      <div class="row2">
        <div><label>Code</label><input id="pay-dcode" placeholder="tax"></div>
        <div><label>Label</label><input id="pay-dlabel" placeholder="Income tax"></div>
      </div>
      <div class="row2">
        <div><label>Kind</label><select id="pay-dkind">
          <option value="percent">a percentage</option>
          <option value="fixed">a fixed amount</option></select></div>
        <div><label>Amount</label><input id="pay-dval" type="number" step="0.01"
          placeholder="20 for 20%, or 5.00"></div>
      </div>
      <div class="row2">
        <div><label>Side</label><select id="pay-dside">${d.sides.map((x) =>
          `<option value="${x}">${x === "employee" ? "off the employee" : "employer cost on top"}</option>`).join("")}</select></div>
        <div><label>Order</label><input id="pay-dpos" type="number" value="${d.deductions.length + 1}"></div>
      </div>
      <label class="perm"><input type="checkbox" id="pay-drem">
        <span>Take it from what is left, not from the gross</span></label>
      <p><button class="btn" id="pay-dsave">Add</button></p>`, "wide");
    $("#pay-dsave").onclick = async () => {
      const kind = $("#pay-dkind").value;
      const v = parseFloat($("#pay-dval").value || 0);
      try {
        await api("/api/payroll/deductions", { body: {
          code: $("#pay-dcode").value, label: $("#pay-dlabel").value, kind,
          rate_bps: kind === "percent" ? Math.round(v * 100) : 0,
          amount_cents: kind === "fixed" ? Math.round(v * 100) : 0,
          side: $("#pay-dside").value, of_remaining: $("#pay-drem").checked,
          position: +$("#pay-dpos").value || 0 } });
        closeModal(); renderPayroll();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-paybuild]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api(`/api/payroll/runs/${b.dataset.paybuild}/build`, { method: "POST" });
      toast(`${r.payslips} payslip(s), ${money(r.gross_cents)} gross`
        + (r.skipped.length ? ` · skipped ${r.skipped.length}` : ""));
      renderPayroll();
    } catch (e) { toast(e.message); } finally { b.disabled = false; }
  });
  view().querySelectorAll("[data-payok]").forEach((b) => b.onclick = async () => {
    if (!confirm("Approve this run?\n\nThe figures freeze. Nothing is "
      + "recomputed afterwards, whatever happens to the hours or the rates.")) return;
    try {
      await api(`/api/payroll/runs/${b.dataset.payok}/approve`, { body: {} });
      renderPayroll();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-paypaid]").forEach((b) => b.onclick = async () => {
    if (!confirm("Mark this run paid?\n\nThat is what puts it in the books: "
      + "the cost, what is held back, and what left the bank.")) return;
    try {
      const r = await api(`/api/payroll/runs/${b.dataset.paypaid}/paid`, { body: {} });
      toast(r.posting_problem
        ? `Paid, but the books refused it: ${r.posting_problem}`
        : `Paid, and posted as journal #${r.journal_id}`);
      renderPayroll();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-paycancel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Cancel this draft run?")) return;
    await api(`/api/payroll/runs/${b.dataset.paycancel}/cancel`, { body: {} });
    renderPayroll();
  });
  view().querySelectorAll("[data-payopen]").forEach((b) => b.onclick = async () => {
    const r = await api(`/api/payroll/runs/${b.dataset.payopen}`);
    modal(`<h3>${esc(r.label)}</h3>
      <p class="dim">${fmtDate(r.period_start)} to ${fmtDate(r.period_end)} ·
        ${esc(r.state)}${r.approved_by ? " by " + esc(r.approved_by) : ""}</p>
      ${r.payslips.length ? r.payslips.map((s) => `<div class="card">
        <div class="doc-top"><div class="doc-main"><b>${esc(s.name)}</b>
          <span class="dim">${s.kind === "salary" ? "salary"
            : `${s.regular_hours}h regular, ${s.overtime_hours}h overtime`}</span></div>
          <span class="pill">net ${money(s.net_cents)}</span></div>
        <div class="tablewrap"><table><tbody>
          ${s.lines.map((l) => `<tr><td>${esc(l.what)}
            ${l.hours ? `<span class="dim">${l.hours}h at ${money(l.rate_cents)}</span>` : ""}</td>
            <td>${money(l.amount_cents)}</td></tr>`).join("")}
          <tr><td><b>Gross</b></td><td><b>${money(s.gross_cents)}</b></td></tr>
          ${s.deductions.map((x) => `<tr><td>${esc(x.label)}
            <span class="dim">${x.rate_bps ? (x.rate_bps / 100).toFixed(2) + "% of " + esc(x.basis) : ""}${
              x.side === "employer" ? " · employer" : ""}</span></td>
            <td>${x.side === "employer" ? "" : "−"}${money(x.amount_cents)}</td></tr>`).join("")}
          <tr><td><b>Net</b></td><td><b>${money(s.net_cents)}</b></td></tr>
        </tbody></table></div></div>`).join("")
        : '<p class="dim">Nothing built yet.</p>'}`, "wide");
  });
}
