// ---------- the books ----------
/* Double entry, which is a different claim from the P&L on Analytics.
   That one adds up what happened; this one is a ledger that must balance,
   can be closed, and is corrected by reversal rather than by editing. The
   screen leads with the trial balance for that reason: it is the number
   that says whether any of the rest can be trusted. */
async function renderBooks() {
  const d = await api("/api/accounting");
  const tb = d.trial_balance;
  const st = d.statements;
  const unposted = d.unposted.orders + d.unposted.expenses;
  const kindLabel = { asset: "Assets", liability: "Owed", equity: "Equity",
    income: "Income", expense: "Costs" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Books</h2>
        <p class="dim">Double-entry, posted from what the business actually
          did. Corrections reverse rather than overwrite, so the history a
          return was filed from stays put.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="acc-journal">Add a journal</button>
        <button class="btn" id="acc-sync">Post what is waiting</button>
      </div>
    </div>
    ${unposted ? `<div class="card">
      <b>${unposted} thing${unposted === 1 ? "" : "s"} the books do not know about</b>
      <p class="dim">${d.unposted.orders} paid order${d.unposted.orders === 1 ? "" : "s"}
        and ${d.unposted.expenses} approved expense${d.unposted.expenses === 1 ? "" : "s"}
        have no entry yet. Posting is safe to repeat: nothing is posted twice.</p>
    </div>` : ""}
    <div class="tiles">
      <div class="card tile"><span class="dim">Trial balance</span>
        <b>${tb.balanced ? "balances" : "out by " + money(Math.abs(tb.out_by_cents))}</b>
        <span class="dim">${money(tb.debits_cents)} each side</span></div>
      <div class="card tile"><span class="dim">Revenue this year</span>
        <b>${money(st.revenue_cents)}</b></div>
      <div class="card tile"><span class="dim">Costs</span>
        <b>${money(st.expenses_cents)}</b></div>
      <div class="card tile"><span class="dim">Profit</span>
        <b>${money(st.profit_cents)}</b>
        <span class="dim">${fmtDate(st.since)} to ${fmtDate(st.upto)}</span></div>
    </div>
    ${tb.balanced ? "" : `<div class="card">
      <b>The trial balance does not balance.</b>
      <p class="dim">Debits and credits differ by
        ${money(Math.abs(tb.out_by_cents))}. Every journal here was checked
        when it was posted, so this means a row was changed underneath the
        ledger rather than through it.</p></div>`}
    <h3>Trial balance</h3>
    ${tb.rows.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>code</th><th>account</th><th>type</th><th>debits</th>
        <th>credits</th><th>balance</th></tr></thead>
      <tbody>${tb.rows.map((r) => `<tr>
        <td class="dim">${esc(r.code)}</td>
        <td><button class="btn alt sm" data-accledger="${esc(r.code)}">${esc(r.name)}</button></td>
        <td class="dim">${esc(r.kind)}</td>
        <td>${r.debit_cents ? money(r.debit_cents) : ""}</td>
        <td>${r.credit_cents ? money(r.credit_cents) : ""}</td>
        <td><b>${money(r.balance_cents)}</b></td>
      </tr>`).join("")}
      <tr><td></td><td><b>Total</b></td><td></td>
        <td><b>${money(tb.debits_cents)}</b></td>
        <td><b>${money(tb.credits_cents)}</b></td><td></td></tr>
      </tbody></table></div></div>`
      : emptyState("list", "Nothing posted yet",
          "Post what is waiting, and the orders and expenses already "
          + "recorded become entries.")}
    <h3>This year</h3>
    <div class="card">
      <div class="tablewrap"><table>
        <thead><tr><th>income</th><th></th></tr></thead>
        <tbody>${st.income.map((r) => `<tr><td>${esc(r.name)}</td>
          <td>${money(r.balance_cents)}</td></tr>`).join("")
          || '<tr><td class="dim">nothing yet</td><td></td></tr>'}
          <tr><td><b>Revenue</b></td><td><b>${money(st.revenue_cents)}</b></td></tr>
        </tbody></table></div>
      <div class="tablewrap" style="margin-top:10px"><table>
        <thead><tr><th>costs</th><th></th></tr></thead>
        <tbody>${st.costs.map((r) => `<tr><td>${esc(r.name)}</td>
          <td>${money(r.balance_cents)}</td></tr>`).join("")
          || '<tr><td class="dim">nothing yet</td><td></td></tr>'}
          <tr><td><b>Total costs</b></td><td><b>${money(st.expenses_cents)}</b></td></tr>
          <tr><td><b>Profit</b></td><td><b>${money(st.profit_cents)}</b></td></tr>
        </tbody></table></div>
    </div>
    <h3>What the business holds</h3>
    <div class="card">
      <p class="dim">${st.sheet_balanced
        ? "Assets equal what is owed plus what is owned, which is the check."
        : "Out by " + money(Math.abs(st.sheet_out_by_cents)) + " — something is posted to an account whose type is wrong."}</p>
      <div class="tablewrap"><table>
        <tbody>${["assets", "liabilities", "equity"].map((k) => `
          <tr><td colspan="2"><b>${kindLabel[k === "assets" ? "asset"
            : k === "liabilities" ? "liability" : "equity"]}</b></td></tr>
          ${(st[k] || []).map((r) => `<tr><td>${esc(r.name)}</td>
            <td>${money(r.balance_cents)}</td></tr>`).join("")
            || '<tr><td class="dim">nothing</td><td></td></tr>'}`).join("")}
          <tr><td><b>Profit not yet carried over</b></td>
            <td><b>${money(st.earnings_cents)}</b></td></tr>
        </tbody></table></div>
    </div>
    <h3>Journals</h3>
    ${d.journals.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>ref</th><th>what</th><th>from</th>
        <th>amount</th><th></th></tr></thead>
      <tbody>${d.journals.map((j) => `<tr class="${j.reversed_by ? "dim" : ""}">
        <td class="dim">${fmtDate(j.at)}</td>
        <td class="dim">${esc(j.ref || "")}</td>
        <td>${esc(j.memo || "")}${j.reversed_by ? " · reversed" : ""}${
          j.reverses ? " · a correction" : ""}</td>
        <td class="dim">${esc(j.source)}</td>
        <td>${money(j.total_cents)}</td>
        <td class="chips"><button class="btn alt sm" data-accjrn="${j.id}">Lines</button>
          ${j.reversed_by || j.reverses ? "" :
            `<button class="btn alt sm" data-accrev="${j.id}">Reverse</button>`}</td>
      </tr>`).join("")}</tbody></table></div></div>` : ""}
    <h3>Periods</h3>
    <div class="card">
      <p class="dim">Closing a period refuses any later posting dated inside
        it. A year you filed from should not be able to change afterwards.</p>
      ${d.periods.length ? `<div class="tablewrap"><table>
        <thead><tr><th>period</th><th>from</th><th>to</th><th></th></tr></thead>
        <tbody>${d.periods.map((p) => `<tr>
          <td>${esc(p.label)}</td><td class="dim">${fmtDate(p.starts)}</td>
          <td class="dim">${fmtDate(p.ends)}</td>
          <td>${p.closed_at ? `<span class="pill ok">closed by ${esc(p.closed_by)}</span>`
            : `<button class="btn alt sm" data-accclose="${p.id}">Close it</button>`}</td>
        </tr>`).join("")}</tbody></table></div>` : '<p class="dim">No periods yet.</p>'}
      <div class="chips" style="margin-top:10px">
        <button class="btn alt sm" id="acc-period">Add a period</button>
      </div>
    </div>`;

  $("#acc-sync").onclick = async () => {
    try {
      const r = await api("/api/accounting/sync", { method: "POST" });
      toast(r.posted ? `${r.posted} posted` : "nothing was waiting");
      if (r.skipped.length) toast(`${r.skipped.length} could not post: ${r.skipped[0].why}`);
      renderBooks();
    } catch (e) { toast(e.message); }
  };
  $("#acc-journal").onclick = () => {
    const row = (n) => `<div class="row2" data-accline="${n}">
      <div><label>Account</label><select data-accacct>${d.accounts.map((a) =>
        `<option value="${esc(a.code)}">${esc(a.code)} ${esc(a.name)}</option>`).join("")}</select></div>
      <div><label>Debit</label><input data-accdr type="number" step="0.01" min="0"></div>
      <div><label>Credit</label><input data-acccr type="number" step="0.01" min="0"></div>
    </div>`;
    modal(`<h3>Add a journal</h3>
      <p class="dim">Debits must equal credits. Anything else is refused,
        which is what makes the trial balance mean something.</p>
      <label>What it is for</label><input id="acc-memo" placeholder="Owner's contribution">
      <label>Reference</label><input id="acc-ref">
      <div id="acc-lines">${row(0)}${row(1)}</div>
      <div class="chips" style="margin-top:8px">
        <button class="btn alt sm" id="acc-addline">Another line</button>
      </div>
      <p><button class="btn" id="acc-save">Post it</button></p>`, "wide");
    let n = 2;
    $("#acc-addline").onclick = () => {
      $("#acc-lines").insertAdjacentHTML("beforeend", row(n));
      n += 1;
    };
    $("#acc-save").onclick = async () => {
      const lines = [...modalBody().querySelectorAll("[data-accline]")].map((el) => ({
        account: el.querySelector("[data-accacct]").value,
        debit_cents: Math.round(parseFloat(el.querySelector("[data-accdr]").value || 0) * 100),
        credit_cents: Math.round(parseFloat(el.querySelector("[data-acccr]").value || 0) * 100),
      })).filter((l) => l.debit_cents || l.credit_cents);
      try {
        await api("/api/accounting/journals", { body: {
          memo: $("#acc-memo").value, ref: $("#acc-ref").value, lines } });
        closeModal(); renderBooks();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-accjrn]").forEach((b) => b.onclick = async () => {
    const j = await api(`/api/accounting/journals/${b.dataset.accjrn}`);
    modal(`<h3>${esc(j.memo || "Journal")}</h3>
      <p class="dim">${fmtDate(j.at)} · ${esc(j.source)} · ${esc(j.by_name || "")}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>account</th><th>debit</th><th>credit</th></tr></thead>
        <tbody>${j.lines.map((l) => `<tr>
          <td>${esc(l.account)} ${esc(l.account_name)}<br>
            <span class="dim">${esc(l.memo || "")}</span></td>
          <td>${l.debit_cents ? money(l.debit_cents) : ""}</td>
          <td>${l.credit_cents ? money(l.credit_cents) : ""}</td></tr>`).join("")}
        </tbody></table></div>`);
  });
  view().querySelectorAll("[data-accrev]").forEach((b) => b.onclick = async () => {
    if (!confirm("Reverse this journal?\n\nIt stays where it is; a new one "
      + "undoes it. That is what a correction is in a ledger.")) return;
    try {
      await api(`/api/accounting/journals/${b.dataset.accrev}/reverse`, { body: {} });
      renderBooks();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-accledger]").forEach((b) => b.onclick = async () => {
    const l = await api(`/api/accounting/ledger/${b.dataset.accledger}`);
    modal(`<h3>${esc(l.account.code)} ${esc(l.account.name)}</h3>
      <p class="dim">${esc(l.account.kind)} · balance ${money(l.balance_cents)}</p>
      ${l.rows.length ? `<div class="tablewrap"><table>
        <thead><tr><th>when</th><th>what</th><th>debit</th><th>credit</th>
          <th>running</th></tr></thead>
        <tbody>${l.rows.map((r) => `<tr>
          <td class="dim">${fmtDate(r.at)}</td>
          <td>${esc(r.memo || r.line_memo || "")}</td>
          <td>${r.debit_cents ? money(r.debit_cents) : ""}</td>
          <td>${r.credit_cents ? money(r.credit_cents) : ""}</td>
          <td>${money(r.running_cents)}</td></tr>`).join("")}</tbody>
      </table></div>` : '<p class="dim">Nothing has touched this account.</p>'}`,
      "wide");
  });
  $("#acc-period").onclick = () => {
    modal(`<h3>Add a period</h3>
      <label>Label</label><input id="acc-plabel" placeholder="2026">
      <div class="row2">
        <div><label>From</label><input id="acc-pfrom" type="date"></div>
        <div><label>To</label><input id="acc-pto" type="date"></div>
      </div>
      <p><button class="btn" id="acc-psave">Add</button></p>`);
    $("#acc-psave").onclick = async () => {
      try {
        await api("/api/accounting/periods", { body: {
          label: $("#acc-plabel").value,
          starts: new Date($("#acc-pfrom").value).getTime() / 1000,
          ends: new Date($("#acc-pto").value).getTime() / 1000 } });
        closeModal(); renderBooks();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-accclose]").forEach((b) => b.onclick = async () => {
    if (!confirm("Close this period?\n\nNothing dated inside it can be "
      + "posted afterwards.")) return;
    try {
      await api(`/api/accounting/periods/${b.dataset.accclose}/close`, { body: {} });
      toast("closed"); renderBooks();
    } catch (e) { toast(e.message); }
  });
}
