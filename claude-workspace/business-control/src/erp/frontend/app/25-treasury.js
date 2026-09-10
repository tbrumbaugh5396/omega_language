// ---------- cash and holdings ----------
/* Where the money is, what is spoken for, and how long it lasts. Balances
   are stated rather than derived, because a bank account has a balance
   whether or not the books are up to date — and where an account names a
   ledger account, the difference between the two is shown, which is where
   a reconciliation starts. */
async function renderTreasury() {
  const d = await api("/api/treasury");
  const runway = d.runway_days;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Cash & holdings</h2>
        <p class="dim">What is in each account, what is set aside and must
          not be spent, and what that leaves.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="tre-move">Move money</button>
        <button class="btn alt" id="tre-hold">Add a holding</button>
        <button class="btn" id="tre-acct">Add an account</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">In the accounts</span>
        <b>${money(d.total_cents)}</b></div>
      <div class="card tile"><span class="dim">Set aside</span>
        <b>${money(d.reserved_cents)}</b>
        <span class="dim">${d.accounts.filter((a) => a.reserved_cents)
          .map((a) => esc(a.reserved_for || a.name)).join(", ") || "nothing"}</span></div>
      <div class="card tile"><span class="dim">Free to spend</span>
        <b>${money(d.free_cents)}</b></div>
      <div class="card tile"><span class="dim">Runway</span>
        <b>${runway === null ? "not burning" : runway + " days"}</b>
        <span class="dim">${d.burn.per_day_cents >= 0
          ? money(d.burn.per_day_cents) + " a day, net in"
          : money(-d.burn.per_day_cents) + " a day, net out"}</span></div>
    </div>
    <p class="dim">${esc(d.runway_note)}</p>
    <h3>Accounts</h3>
    ${d.accounts.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>account</th><th>kind</th><th>balance</th><th>set aside</th>
        <th>free</th><th>as of</th><th></th></tr></thead>
      <tbody>${d.accounts.map((a) => `<tr>
        <td><b>${esc(a.name)}</b>${a.reference ? `<br><span class="dim">${esc(a.reference)}</span>` : ""}</td>
        <td class="dim">${esc(a.kind)}</td>
        <td><b>${money(a.balance_cents)}</b></td>
        <td>${a.reserved_cents ? money(a.reserved_cents) : ""}
          ${a.reserved_for ? `<span class="dim">${esc(a.reserved_for)}</span>` : ""}</td>
        <td>${money(a.balance_cents - a.reserved_cents)}</td>
        <td class="dim">${a.as_of ? fmtAgo(a.as_of) : "never stated"}</td>
        <td><button class="btn alt sm" data-treedit="${a.id}">Edit</button></td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("card", "No accounts yet",
          "Add the bank account the business actually uses, and the rest "
          + "of this screen starts working.")}
    ${d.reconciliation.length ? `<h3>Against the books</h3>
    <div class="card">
      <p class="dim">A difference is not automatically an error. The books
        may simply be behind — post what is waiting on Books and look
        again.</p>
      <div class="tablewrap"><table>
        <thead><tr><th>account</th><th>stated here</th><th>in the ledger</th>
          <th>difference</th></tr></thead>
        <tbody>${d.reconciliation.map((r) => `<tr>
          <td>${esc(r.name)} <span class="dim">${esc(r.ledger_account)}</span></td>
          <td>${money(r.stated_cents)}</td><td>${money(r.ledger_cents)}</td>
          <td>${r.difference_cents
            ? `<span class="pill warn">${money(r.difference_cents)}</span>`
            : '<span class="pill ok">agrees</span>'}</td>
        </tr>`).join("")}</tbody></table></div>
    </div>` : ""}
    ${d.holdings.length ? `<h3>Holdings</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>what</th><th>kind</th><th>units</th><th>cost</th>
        <th>worth</th><th>gain</th><th></th></tr></thead>
      <tbody>${d.holdings.map((h) => `<tr>
        <td><b>${esc(h.name)}</b>${h.account_name ? `<br><span class="dim">held at ${esc(h.account_name)}</span>` : ""}</td>
        <td class="dim">${esc(h.kind)}</td><td>${h.units || ""}</td>
        <td>${money(h.cost_cents)}</td><td>${money(h.value_cents)}</td>
        <td><b>${money(h.gain_cents)}</b>
          <span class="dim">${h.valued_at ? "marked " + fmtAgo(h.valued_at) : ""}</span></td>
        <td class="chips"><button class="btn alt sm" data-treh="${h.id}">Edit</button>
          <button class="btn alt sm" data-trehx="${h.id}">Close</button></td>
      </tr>`).join("")}
      <tr><td><b>Total</b></td><td></td><td></td>
        <td><b>${money(d.holdings_cost_cents)}</b></td>
        <td><b>${money(d.holdings_value_cents)}</b></td>
        <td><b>${money(d.holdings_value_cents - d.holdings_cost_cents)}</b></td>
        <td></td></tr>
      </tbody></table></div></div>` : ""}
    ${d.movements.length ? `<h3>What has moved</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>account</th><th>what</th><th>amount</th>
        <th>who</th></tr></thead>
      <tbody>${d.movements.map((m) => `<tr>
        <td class="dim">${fmtDate(m.at)}</td><td>${esc(m.account_name)}</td>
        <td>${esc(m.memo || m.kind)}</td>
        <td>${money(m.amount_cents)}</td>
        <td class="dim">${esc(m.by_name || "")}</td>
      </tr>`).join("")}</tbody></table></div></div>` : ""}`;

  const acctForm = (a) => {
    modal(`<h3>${a ? "Edit" : "Add"} an account</h3>
      <div class="row2">
        <div><label>Name</label><input id="tre-name" value="${esc(a ? a.name : "")}"></div>
        <div><label>Kind</label><select id="tre-kind">${d.kinds.map((k) =>
          `<option value="${k}" ${a && a.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Balance ($)</label><input id="tre-bal" type="number" step="0.01"
          value="${a ? (a.balance_cents / 100).toFixed(2) : ""}"></div>
        <div><label>Reference</label><input id="tre-ref" value="${esc(a ? a.reference : "")}"
          placeholder="last four"></div>
      </div>
      <div class="row2">
        <div><label>Set aside ($)</label><input id="tre-res" type="number" step="0.01"
          value="${a ? (a.reserved_cents / 100).toFixed(2) : "0"}"></div>
        <div><label>What for</label><input id="tre-resfor" value="${esc(a ? a.reserved_for : "")}"
          placeholder="sales tax"></div>
      </div>
      <label>Ledger account <span class="dim">(optional; lets the two be compared)</span></label>
      <input id="tre-ledger" value="${esc(a ? a.ledger_account : "")}" placeholder="1010">
      <p><button class="btn" id="tre-save">Save</button></p>`);
    $("#tre-save").onclick = async () => {
      try {
        await api("/api/treasury/accounts", { body: {
          id: a ? a.id : 0, name: $("#tre-name").value, kind: $("#tre-kind").value,
          balance_cents: Math.round(parseFloat($("#tre-bal").value || 0) * 100),
          reference: $("#tre-ref").value,
          reserved_cents: Math.round(parseFloat($("#tre-res").value || 0) * 100),
          reserved_for: $("#tre-resfor").value,
          ledger_account: $("#tre-ledger").value.trim() } });
        closeModal(); renderTreasury();
      } catch (e) { toast(e.message); }
    };
  };
  $("#tre-acct").onclick = () => acctForm(null);
  view().querySelectorAll("[data-treedit]").forEach((b) => b.onclick = () =>
    acctForm(d.accounts.find((a) => a.id === +b.dataset.treedit)));
  $("#tre-move").onclick = () => {
    const opts = d.accounts.map((a) =>
      `<option value="${a.id}">${esc(a.name)} · ${money(a.balance_cents)}</option>`).join("");
    modal(`<h3>Move money</h3>
      <p class="dim">Between two of your own accounts. Not income and not a
        cost — recorded as either, it inflates a year that never earned it.</p>
      <div class="row2">
        <div><label>From</label><select id="tre-from">${opts}</select></div>
        <div><label>To</label><select id="tre-to">${opts}</select></div>
      </div>
      <label>Amount ($)</label><input id="tre-amt" type="number" step="0.01" min="0">
      <label>Note</label><input id="tre-memo">
      <p><button class="btn" id="tre-go">Move it</button></p>`);
    $("#tre-go").onclick = async () => {
      try {
        await api("/api/treasury/transfer", { body: {
          from_id: +$("#tre-from").value, to_id: +$("#tre-to").value,
          amount_cents: Math.round(parseFloat($("#tre-amt").value || 0) * 100),
          memo: $("#tre-memo").value } });
        closeModal(); renderTreasury();
      } catch (e) { toast(e.message); }
    };
  };
  const holdForm = (h) => {
    modal(`<h3>${h ? "Edit" : "Add"} a holding</h3>
      <div class="row2">
        <div><label>What</label><input id="tre-hname" value="${esc(h ? h.name : "")}"></div>
        <div><label>Kind</label><select id="tre-hkind">${d.holding_kinds.map((k) =>
          `<option value="${k}" ${h && h.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Cost ($)</label><input id="tre-hcost" type="number" step="0.01"
          value="${h ? (h.cost_cents / 100).toFixed(2) : ""}"></div>
        <div><label>Worth now ($)</label><input id="tre-hval" type="number" step="0.01"
          value="${h ? (h.value_cents / 100).toFixed(2) : ""}"></div>
      </div>
      <div class="row2">
        <div><label>Units</label><input id="tre-hunits" type="number" step="any"
          value="${h ? h.units : ""}"></div>
        <div><label>Held at</label><select id="tre-hacct"><option value="0">—</option>
          ${d.accounts.map((a) => `<option value="${a.id}" ${h && h.account_id === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select></div>
      </div>
      <p><button class="btn" id="tre-hsave">Save</button></p>`);
    $("#tre-hsave").onclick = async () => {
      try {
        await api("/api/treasury/holdings", { body: {
          id: h ? h.id : 0, name: $("#tre-hname").value, kind: $("#tre-hkind").value,
          units: parseFloat($("#tre-hunits").value || 0),
          cost_cents: Math.round(parseFloat($("#tre-hcost").value || 0) * 100),
          value_cents: Math.round(parseFloat($("#tre-hval").value || 0) * 100),
          account_id: +$("#tre-hacct").value } });
        closeModal(); renderTreasury();
      } catch (e) { toast(e.message); }
    };
  };
  $("#tre-hold").onclick = () => holdForm(null);
  view().querySelectorAll("[data-treh]").forEach((b) => b.onclick = () =>
    holdForm(d.holdings.find((h) => h.id === +b.dataset.treh)));
  view().querySelectorAll("[data-trehx]").forEach((b) => b.onclick = async () => {
    if (!confirm("Close this holding? It stops counting toward the total.")) return;
    await api(`/api/treasury/holdings/${b.dataset.trehx}`, { method: "DELETE" });
    renderTreasury();
  });
}
