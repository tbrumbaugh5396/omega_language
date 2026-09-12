// ---------- the annual report: the year added up, with the words around it ----------
/* Every number here is derived from the rows when the page opens, so the
   report never drifts from the books. The words — a title, the letter,
   the highlights, the thanks — are kept by year, because they are the
   part nobody can regenerate. Print opens the report as a document;
   the CSV is the numbers for whoever wants to check them. */
let ANN_YEAR = 0;

async function renderAnnual() {
  const d = await api(`/api/reports/annual${ANN_YEAR ? "?year=" + ANN_YEAR : ""}`);
  ANN_YEAR = d.year;
  const S_ = d.sections, W = d.words;
  const P = d.prior || {};
  /* How a number moved against the year before: the same measure, derived
     the same way. Shown only when both years have it and last year was
     not zero — a rise from nothing is not a percentage. */
  const delta = (sec, key, isMoney) => {
    const now = (S_[sec] || {})[key], then = (P[sec] || {})[key];
    if (typeof now !== "number" || typeof then !== "number" || !then) return "";
    const pct = Math.round((now - then) / Math.abs(then) * 100);
    return `<span class="ann-delta ${pct > 0 ? "up" : pct < 0 ? "down" : ""}" title="${d.year - 1}: ${isMoney ? money(then) : then}">${
      pct > 0 ? "+" : ""}${pct}% vs ${d.year - 1}</span>`;
  };
  const tile = (label, v, sub = "", dl = "") => `<div class="card tile"><span class="dim">${label}</span><b>${v}</b>${sub ? `<span class="dim">${sub}</span>` : ""}${dl}</div>`;
  const max = Math.max(1, ...((S_.sales && S_.sales.by_month_cents) || [0]));
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Annual report ${d.year}</h2>
        <p class="dim">The year, added up from what this install recorded, with
          the words around it. Numbers are worked out fresh each time; the
          words are kept.</p></div>
      <div class="top-actions">
        <select id="ann-year" aria-label="year">${d.years.map((y) => `<option value="${y}" ${y === d.year ? "selected" : ""}>${y}</option>`).join("")}</select>
        <a class="btn alt" href="/api/reports/annual.csv?year=${d.year}&t=${encodeURIComponent(S.user.token)}" download>CSV</a>
        <button class="btn alt" id="ann-print">Print</button>
        <button class="btn" id="ann-save">Save the words</button>
      </div>
    </div>
    <div class="card ann-words">
      <label>Title <input id="ann-title" value="${esc(W.title || "")}" placeholder="${esc(d.brand || "Our")} year in ${d.year}"></label>
      <label>The letter <span class="opt">from the owner, the director, the board — what the year meant</span>
        <textarea id="ann-letter" rows="8">${esc(W.letter || "")}</textarea></label>
      <label>Highlights <span class="opt">one per line</span>
        <textarea id="ann-hl" rows="4">${esc((W.highlights || []).join("\n"))}</textarea></label>
      <label>Thanks <textarea id="ann-thanks" rows="3">${esc(W.thanks || "")}</textarea></label>
      <label class="chk"><input type="checkbox" id="ann-pub" ${W.published ? "checked" : ""}> Finished — ready to share</label>
      ${W.updated_at ? `<p class="dim">last saved ${fmtDate(W.updated_at)} by ${esc(W.by_name)}</p>` : ""}
    </div>
    ${S_.sales ? `<h3>Sales</h3>
    <div class="tiles">
      ${tile("Revenue", money(S_.sales.revenue_cents), `${S_.sales.orders} orders`, delta("sales", "revenue_cents", true))}
      ${tile("Average order", money(S_.sales.average_order_cents), "", delta("sales", "average_order_cents", true))}
      ${tile("New customers", S_.sales.new_customers, `${S_.sales.returning} came back`, delta("sales", "new_customers"))}
      ${S_.sales.donations_cents ? tile("Given at checkout", money(S_.sales.donations_cents)) : ""}
    </div>
    <div class="card ann-months">${S_.sales.by_month_cents.map((c, i) => {
      const pm = (P._months || [])[i] || 0, mx = Math.max(max, ...(P._months || [0]));
      return `<div class="ann-bar" title="${money(c)}${pm ? ` (${d.year - 1}: ${money(pm)})` : ""}">
      ${pm ? `<u style="height:${Math.round(pm / mx * 100)}%"></u>` : ""}<i style="height:${Math.round(c / mx * 100)}%"></i><span>${d.months[i]}</span></div>`; }).join("")}
      ${(P._months || []).some((x) => x) ? `<p class="dim ann-key">grey: ${d.year - 1}</p>` : ""}</div>
    ${S_.sales.top_products.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>what sold</th><th>units</th><th>revenue</th></tr></thead>
      <tbody>${S_.sales.top_products.map((p) => `<tr><td>${esc(p.name)}</td><td>${p.qty}</td><td>${money(p.cents)}</td></tr>`).join("")}</tbody>
    </table></div></div>` : ""}` : ""}
    ${S_.learning ? `<h3>Learning</h3>
    <div class="tiles">
      ${tile("Students", S_.learning.students, `${S_.learning.new_seats} new seats`, delta("learning", "students"))}
      ${tile("Courses", S_.learning.courses)}
      ${"sessions_held" in S_.learning ? tile("Sessions held", S_.learning.sessions_held, `${S_.learning.attendances || 0} attendances`) : ""}
      ${"quizzes_taken" in S_.learning ? tile("Quizzes taken", S_.learning.quizzes_taken) : ""}
      ${"applications_opened" in S_.learning ? tile("Applications", S_.learning.applications_opened, `${S_.learning.applications_accepted} accepted`) : ""}
    </div>` : ""}
    <h3>People</h3>
    <div class="tiles">
      ${tile("Staff at year end", S_.people.staff_at_end, `${S_.people.joined} joined${"left" in S_.people ? `, ${S_.people.left} left` : ""}`)}
      ${"hours_worked" in S_.people ? tile("Hours worked", S_.people.hours_worked.toLocaleString(), "", delta("people", "hours_worked")) : ""}
      ${"payroll_gross_cents" in S_.people ? tile("Payroll", money(S_.people.payroll_gross_cents), `${money(S_.people.payroll_net_cents)} net`) : ""}
      ${"applicants" in S_.people ? tile("Applicants", S_.people.applicants) : ""}
    </div>
    ${S_.money ? `<h3>Money out, and money given</h3>
    <div class="tiles">
      ${"expenses_cents" in S_.money ? tile("Expenses", money(S_.money.expenses_cents), "", delta("money", "expenses_cents", true)) : ""}
      ${"invoiced_cents" in S_.money ? tile("Invoiced", money(S_.money.invoiced_cents), `${S_.money.invoices_issued} invoices · ${money(S_.money.invoices_collected_cents)} collected`) : ""}
      ${"gifts_cents" in S_.money ? tile("Gifts received", money(S_.money.gifts_cents), `${S_.money.gifts} gifts from ${S_.money.donors} donors`, delta("money", "gifts_cents", true)) : ""}
      ${"political_giving_cents" in S_.money && S_.money.political_giving_cents ? tile("Political giving", money(S_.money.political_giving_cents), "disclosed on the civics register") : ""}
    </div>
    ${S_.money.expenses_by_category && S_.money.expenses_by_category.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>expense category</th><th>items</th><th>business share</th></tr></thead>
      <tbody>${S_.money.expenses_by_category.map((r) => `<tr><td>${esc(r.category)}</td><td>${r.n}</td><td>${money(r.cents)}</td></tr>`).join("")}</tbody>
    </table></div></div>` : ""}` : ""}
    ${S_.books ? `<h3>The books</h3>
    <div class="tiles">
      ${tile("Income", money(S_.books.income_cents))}
      ${tile("Cost of sales", money(S_.books.cost_of_sales_cents))}
      ${tile("Operating", money(S_.books.operating_cents))}
      ${tile("Surplus", money(S_.books.surplus_cents))}
    </div>` : `<p class="dim">No journals posted for ${d.year}, so no books section; sync the books on Books to add one.</p>`}
    ${S_.service ? `<h3>Service</h3>
    <div class="tiles">
      ${"tickets_closed" in S_.service ? tile("Tickets closed", S_.service.tickets_closed) : ""}
      ${"support_requests" in S_.service ? tile("Support requests", S_.service.support_requests) : ""}
      ${"appointments" in S_.service ? tile("Appointments", S_.service.appointments) : ""}
      ${"events_held" in S_.service ? tile("Events", S_.service.events_held) : ""}
    </div>` : ""}`;
  $("#ann-year").onchange = (e) => { ANN_YEAR = +e.target.value; renderAnnual(); };
  $("#ann-save").onclick = async () => {
    try {
      await api("/api/reports/annual", { body: {
        year: d.year, title: $("#ann-title").value, letter: $("#ann-letter").value,
        highlights: $("#ann-hl").value.split("\n"), thanks: $("#ann-thanks").value,
        published: $("#ann-pub").checked } });
      toast("saved"); renderAnnual();
    } catch (e) { toast(e.message); }
  };
  $("#ann-print").onclick = () => {
    const w = window.open("", "_blank");
    if (!w) return toast("the browser blocked the print window — allow pop-ups for this site");
    w.document.write(annualDoc(d, {
      title: $("#ann-title").value, letter: $("#ann-letter").value,
      highlights: $("#ann-hl").value.split("\n").filter((x) => x.trim()),
      thanks: $("#ann-thanks").value }));
    w.document.close();
  };
}

/* The report as a document: the words first, then each section as a
   short table. Plain, black on white, the kind of thing that survives a
   photocopier. */
function annualDoc(d, W) {
  const S_ = d.sections;
  const row = (k, v) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`;
  const sec = (title, rows) => rows.length ? `<h2>${esc(title)}</h2><table>${rows.join("")}</table>` : "";
  const sales = S_.sales ? [row("Orders", S_.sales.orders), row("Revenue", money(S_.sales.revenue_cents)),
    row("Average order", money(S_.sales.average_order_cents)), row("New customers", S_.sales.new_customers),
    row("Returning customers", S_.sales.returning),
    ...(S_.sales.donations_cents ? [row("Given at checkout", money(S_.sales.donations_cents))] : []),
    ...S_.sales.top_products.map((p) => row(`Sold: ${p.name}`, `${p.qty} · ${money(p.cents)}`))] : [];
  const learn = S_.learning ? Object.entries(S_.learning).map(([k, v]) => row(k.replace(/_/g, " "), v)) : [];
  const people = Object.entries(S_.people).map(([k, v]) => row(k.replace(/_/g, " ").replace(" cents", ""), k.endsWith("_cents") ? money(v) : v));
  const moneyRows = S_.money ? Object.entries(S_.money).filter(([k]) => k !== "expenses_by_category")
    .map(([k, v]) => row(k.replace(/_/g, " ").replace(" cents", ""), k.endsWith("_cents") ? money(v) : v))
    .concat((S_.money.expenses_by_category || []).map((r) => row(`Expenses: ${r.category}`, money(r.cents)))) : [];
  const books = S_.books ? Object.entries(S_.books).map(([k, v]) => row(k.replace(/_/g, " ").replace(" cents", ""), money(v))) : [];
  const service = S_.service ? Object.entries(S_.service).map(([k, v]) => row(k.replace(/_/g, " "), v)) : [];
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(W.title || `${d.brand} ${d.year}`)}</title>
<style>
@page { size: letter; margin: .8in; }
body { font-family: Georgia, "Times New Roman", serif; color: #000; background: #fff; max-width: 7in; margin: 0 auto; padding: 24px; line-height: 1.45; }
h1 { font-size: 26pt; margin: 0 0 4px; } .k { color: #444; margin: 0 0 18px; font-family: system-ui, sans-serif; font-size: 10pt; }
h2 { font-size: 13pt; margin: 22px 0 6px; border-bottom: 1px solid #999; padding-bottom: 3px; font-family: system-ui, sans-serif; text-transform: uppercase; letter-spacing: .05em; }
table { border-collapse: collapse; width: 100%; font-family: system-ui, sans-serif; font-size: 10.5pt; }
td { padding: 4px 6px; border-bottom: 1px solid #e3e3e3; } td:last-child { text-align: right; white-space: nowrap; }
.letter { white-space: pre-wrap; font-size: 12pt; } ul { padding-left: 20px; }
.bars { display: flex; gap: 4px; align-items: flex-end; height: 90px; margin: 10px 0; font-family: system-ui, sans-serif; font-size: 8pt; }
.bars div { flex: 1; text-align: center; } .bars i { display: block; background: #333; margin: 0 4px 3px; }
@media print { body { padding: 0; } }
</style></head><body>
<h1>${esc(W.title || `${d.brand || "Our"} year in ${d.year}`)}</h1>
<p class="k">${esc(d.brand)} · annual report ${d.year} · prepared ${new Date().toLocaleDateString()}</p>
${W.letter ? `<div class="letter">${esc(W.letter)}</div>` : ""}
${W.highlights.length ? `<h2>Highlights</h2><ul>${W.highlights.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}
${S_.sales ? `<h2>Sales by month</h2><div class="bars">${(() => { const mx = Math.max(1, ...S_.sales.by_month_cents);
  return S_.sales.by_month_cents.map((c, i) => `<div><i style="height:${Math.round(c / mx * 70)}px"></i>${d.months[i]}</div>`).join(""); })()}</div>` : ""}
${sec("Sales", sales)}${sec("Learning", learn)}${sec("People", people)}${sec("Money out, and money given", moneyRows)}${sec("The books", books)}${sec("Service", service)}
${W.thanks ? `<h2>Thanks</h2><div class="letter">${esc(W.thanks)}</div>` : ""}
<script>setTimeout(function () { window.print(); }, 200);</script>
</body></html>`;
}
