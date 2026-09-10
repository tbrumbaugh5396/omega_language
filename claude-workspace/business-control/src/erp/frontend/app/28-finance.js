// ---------- owed and planned ----------
/* Accounting records what happened, Treasury says where the money is now,
   and neither answers who owes us, whether we are where we said we would
   be, and what the next few weeks look like. Receivables and payables are
   derived from rows that already exist, so nothing can be paid here and
   still owed there. Only the budget is stored, being the one number that
   is not a consequence of something else. */
let FIN_TAB = "owed";

async function renderFinance() {
  if (FIN_TAB === "invoices") return renderInvoices();
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
        <button class="btn alt" id="finb-inv">Invoices</button>
        <button class="btn" id="finb-budget">New budget</button>
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

  $("#finb-inv").onclick = () => { FIN_TAB = "invoices"; renderFinance(); };
  $("#finb-budget").onclick = () => {
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

// ---------- invoices ----------
/* An unpaid order is a receivable; an invoice is a receivable you can
   SEND, which is the half of a business that bills rather than sells. A
   draft is editable and an issued one is not: it is somebody else's copy
   now, and a correction is a credit note that reverses it. Same rule the
   ledger keeps, for the same reason. */
async function renderInvoices() {
  const d = await api("/api/finance/invoices");
  const stateLabel = { draft: "draft", issued: "issued", part_paid: "part paid",
    paid: "paid", void: "credited" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Invoices</h2>
        <p class="dim">What you have billed and what has come back. An
          issued invoice cannot be edited — raise a credit note against it,
          because somebody already has a copy of what it said.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="inv-back">Owed & planned</button>
        <button class="btn" id="invc-new">New invoice</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Outstanding</span>
        <b>${money(d.outstanding_cents)}</b></div>
      <div class="card tile"><span class="dim">Overdue</span>
        <b>${money(d.overdue_cents)}</b></div>
      <div class="card tile"><span class="dim">Invoices</span>
        <b>${d.invoices.length}</b></div>
    </div>
    ${d.invoices.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>number</th><th>to</th><th>issued</th><th>due</th>
        <th>total</th><th>outstanding</th><th>state</th><th></th></tr></thead>
      <tbody>${d.invoices.map((i) => `<tr class="${i.state === "void" ? "dim" : ""}">
        <td><b>${esc(i.number || "draft")}</b>
          ${i.credits ? '<br><span class="dim">credit note</span>' : ""}</td>
        <td>${esc(i.bill_to)}${i.reference ? `<br><span class="dim">${esc(i.reference)}</span>` : ""}</td>
        <td class="dim">${i.issued_at ? fmtDate(i.issued_at) : "—"}</td>
        <td class="${i.overdue ? "" : "dim"}">${i.due_at ? fmtDate(i.due_at) : "—"}
          ${i.overdue ? `<br><span class="pill bad">${i.days_overdue} days late</span>` : ""}</td>
        <td>${money(i.total_cents)}</td>
        <td>${i.outstanding_cents ? money(i.outstanding_cents) : ""}</td>
        <td><span class="pill ${i.state === "paid" ? "ok"
          : i.state === "part_paid" ? "warn" : ""}">${esc(stateLabel[i.state] || i.state)}</span>
          ${i.sent_at ? '<br><span class="dim">sent</span>' : ""}
          ${i.viewed_at ? '<span class="dim"> · opened</span>' : ""}</td>
        <td class="chips">
          <button class="btn alt sm" data-invopen="${i.id}">Open</button>
          ${i.state === "draft" ? `<button class="btn sm" data-invissue="${i.id}">Issue</button>
            <button class="btn alt sm" data-invedit="${i.id}">Edit</button>` : ""}
          ${["issued", "part_paid"].includes(i.state)
            ? `<button class="btn alt sm" data-invpay="${i.id}">Payment</button>
               <button class="btn alt sm" data-invsend="${i.id}">Send</button>` : ""}
          ${i.state !== "draft" && !i.credits && !i.credited_by
            ? `<button class="btn alt sm" data-invcredit="${i.id}">Credit</button>` : ""}
        </td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("file", "No invoices yet",
          "An invoice is a receivable you can send — for the work that is "
          + "billed rather than sold over a counter.")}`;

  $("#inv-back").onclick = () => { FIN_TAB = "owed"; renderFinance(); };
  const invForm = (inv) => {
    const row = (l) => `<div class="row2" data-invline>
      <div><label>What</label><input data-invwhat value="${esc(l ? l.what : "")}"></div>
      <div><label>Qty</label><input data-invqty type="number" step="any" value="${l ? l.qty : 1}"></div>
      <div><label>Each ($)</label><input data-invunit type="number" step="0.01"
        value="${l ? (l.unit_cents / 100).toFixed(2) : ""}"></div>
      <div><label>Tax %</label><input data-invtax type="number" step="0.01"
        value="${l ? (l.tax_bps / 100).toFixed(2) : "0"}"></div>
    </div>`;
    modal(`<h3>${inv ? "Edit draft" : "New invoice"}</h3>
      <div class="row2">
        <div><label>Bill to</label><input id="inv-to" value="${esc(inv ? inv.bill_to : "")}"></div>
        <div><label>Their email</label><input id="inv-email" type="email"
          value="${esc(inv ? inv.bill_email : "")}"></div>
      </div>
      <div class="row2">
        <div><label>Their reference</label><input id="inv-ref" value="${esc(inv ? inv.reference : "")}"
          placeholder="PO number"></div>
        <div><label>Terms (days)</label><input id="inv-terms" type="number" min="0"
          value="${inv ? inv.terms_days : 30}"></div>
      </div>
      <label>Address</label><textarea id="inv-addr" rows="2">${esc(inv ? inv.bill_address : "")}</textarea>
      <h3 style="font-size:15px;margin-top:12px">Lines</h3>
      <div id="inv-lines">${(inv && inv.lines.length ? inv.lines : [null]).map(row).join("")}</div>
      <div class="chips" style="margin-top:6px">
        <button class="btn alt sm" id="inv-addline">Another line</button>
      </div>
      <label>Note on the invoice</label><textarea id="inv-note" rows="2">${esc(inv ? inv.note : "")}</textarea>
      <label>Payment terms text</label><input id="inv-termstext"
        value="${esc(inv ? inv.terms_text : "")}" placeholder="Bank details, how to pay">
      <p><button class="btn" id="inv-save">Save draft</button></p>`, "wide");
    $("#inv-addline").onclick = () =>
      $("#inv-lines").insertAdjacentHTML("beforeend", row(null));
    $("#inv-save").onclick = async () => {
      const lines = [...modalBody().querySelectorAll("[data-invline]")].map((el) => ({
        what: el.querySelector("[data-invwhat]").value.trim(),
        qty: parseFloat(el.querySelector("[data-invqty]").value || 0),
        unit_cents: Math.round(parseFloat(el.querySelector("[data-invunit]").value || 0) * 100),
        tax_bps: Math.round(parseFloat(el.querySelector("[data-invtax]").value || 0) * 100),
      })).filter((l) => l.what);
      try {
        await api("/api/finance/invoices", { body: {
          id: inv ? inv.id : 0, bill_to: $("#inv-to").value,
          bill_email: $("#inv-email").value, bill_address: $("#inv-addr").value,
          reference: $("#inv-ref").value, terms_days: +$("#inv-terms").value || 0,
          note: $("#inv-note").value, terms_text: $("#inv-termstext").value,
          lines } });
        closeModal(); renderInvoices();
      } catch (e) { toast(e.message); }
    };
  };
  $("#invc-new").onclick = () => invForm(null);
  view().querySelectorAll("[data-invedit]").forEach((b) => b.onclick = async () =>
    invForm(await api(`/api/finance/invoices/${b.dataset.invedit}`)));
  view().querySelectorAll("[data-invopen]").forEach((b) => b.onclick = async () => {
    const i = await api(`/api/finance/invoices/${b.dataset.invopen}`);
    modal(`<h3>${esc(i.number || "Draft")} — ${esc(i.bill_to)}</h3>
      <p class="dim">${i.issued_at ? "Issued " + fmtDate(i.issued_at) : "Not issued"}
        ${i.due_at ? " · due " + fmtDate(i.due_at) : ""}
        ${i.viewed_at ? " · they opened it " + fmtAgo(i.viewed_at) : ""}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>what</th><th>qty</th><th>each</th><th>amount</th></tr></thead>
        <tbody>${i.lines.map((l) => `<tr><td>${esc(l.what)}</td>
          <td>${l.qty}</td><td>${money(l.unit_cents)}</td>
          <td>${money(l.amount_cents)}</td></tr>`).join("")}
          <tr><td colspan="3"><b>Total</b></td><td><b>${money(i.total_cents)}</b></td></tr>
          ${i.payments.map((p) => `<tr><td colspan="3" class="dim">Paid ${fmtDate(p.at)}
            ${esc(p.method || "")} ${esc(p.reference || "")}</td>
            <td class="dim">−${money(p.amount_cents)}</td></tr>`).join("")}
          <tr><td colspan="3"><b>Outstanding</b></td>
            <td><b>${money(i.outstanding_cents)}</b></td></tr>
        </tbody></table></div>
      ${i.number ? `<p><label>The link they were sent</label>
        <input value="${esc(i.link)}" readonly>
        <a class="btn alt sm" href="/api/finance/invoices/${i.id}/pdf?token=${
          encodeURIComponent(S.user.token)}" target="_blank" rel="noopener">Open the PDF</a></p>` : ""}`,
      "wide");
  });
  view().querySelectorAll("[data-invissue]").forEach((b) => b.onclick = async () => {
    if (!confirm("Issue this invoice?\n\nIt gets a number, goes into the "
      + "books as owed to you, and stops being editable.")) return;
    try {
      const r = await api(`/api/finance/invoices/${b.dataset.invissue}/issue`, { body: {} });
      toast(r.posting_problem ? `Issued ${r.number}, but the books refused it: ${r.posting_problem}`
        : `Issued as ${r.number}`);
      renderInvoices();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-invsend]").forEach((b) => b.onclick = async () => {
    try {
      const r = await api(`/api/finance/invoices/${b.dataset.invsend}/send`, { body: {} });
      toast(`sent (${r.status || "queued"})`);
      renderInvoices();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-invpay]").forEach((b) => b.onclick = () => {
    const i = d.invoices.find((x) => x.id === +b.dataset.invpay);
    modal(`<h3>Payment on ${esc(i.number)}</h3>
      <p class="dim">${money(i.outstanding_cents)} outstanding. Part payment
        is normal, so record what actually arrived.</p>
      <div class="row2">
        <div><label>Amount ($)</label><input id="inv-amt" type="number" step="0.01"
          value="${(i.outstanding_cents / 100).toFixed(2)}"></div>
        <div><label>How</label><input id="inv-method" placeholder="transfer"></div>
      </div>
      <label>Reference</label><input id="inv-payref">
      <p><button class="btn" id="inv-paysave">Record it</button></p>`);
    $("#inv-paysave").onclick = async () => {
      try {
        await api(`/api/finance/invoices/${i.id}/payments`, { body: {
          amount_cents: Math.round(parseFloat($("#inv-amt").value || 0) * 100),
          method: $("#inv-method").value, reference: $("#inv-payref").value } });
        closeModal(); renderInvoices();
      } catch (e) { toast(e.message); }
    };
  });
  view().querySelectorAll("[data-invcredit]").forEach((b) => b.onclick = () => {
    modal(`<h3>Credit note</h3>
      <p class="dim">This reverses the invoice in the books and marks it
        credited. The original stays exactly as it was sent, which is the
        whole point of one.</p>
      <label>Why</label><input id="inv-why" placeholder="Work cancelled">
      <p><button class="btn" id="inv-creditgo">Raise it</button></p>`);
    $("#inv-creditgo").onclick = async () => {
      try {
        const r = await api(`/api/finance/invoices/${b.dataset.invcredit}/credit`,
                            { body: { reason: $("#inv-why").value } });
        closeModal(); toast(`credit note ${r.number}`); renderInvoices();
      } catch (e) { toast(e.message); }
    };
  });
}
