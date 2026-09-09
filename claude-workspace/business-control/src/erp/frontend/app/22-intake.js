// ---------- forms, gifts and results ----------
/* Three trays of things that arrive from outside as records: form
   responses, gifts, test results. Each row can become the thing it was
   really about. */
async function renderIntake() {
  const d = await api("/api/intake");
  const admin = S.user.is_admin || S.user.role === "admin" || S.user.role === "owner";
  const forms = d.connections.find((c) => c.name === "google_forms") || {};
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Forms, gifts & results</h2>
        <p class="dim">What arrives from outside as records: the answers to a
          form, the gifts made to you, the tests your learners pass elsewhere.
          Each row can be turned into the thing it was about.</p></div>
      <div class="top-actions">
        ${admin ? `<button class="btn alt" id="ink-gift">Log a gift by hand</button>
          ${forms.connected ? '<button class="btn" id="ink-pull">Pull form responses</button>' : ""}` : ""}
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Form responses</span><b>${d.responses.length}</b>
        <span class="dim">${d.responses.filter((r) => !r.handled_as).length} not yet handled</span></div>
      <div class="card tile"><span class="dim">Gifts</span><b>${money(d.gift_totals.cents)}</b>
        <span class="dim">${d.gift_totals.n} gift${d.gift_totals.n === 1 ? "" : "s"} from ${d.gift_totals.donors} donor${d.gift_totals.donors === 1 ? "" : "s"}</span></div>
      <div class="card tile"><span class="dim">Test results</span><b>${d.results.length}</b>
        <span class="dim">${d.unmatched ? `${d.unmatched} not matched to a student` : "all matched"}</span></div>
    </div>
    <h3>Form responses</h3>
    ${d.responses.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>form</th><th>when</th><th>answers</th><th></th></tr></thead>
      <tbody>${d.responses.map((r) => `<tr>
        <td><b>${esc(r.name || "—")}</b><br><span class="dim">${esc(r.email || "")}${r.phone ? " · " + esc(r.phone) : ""}</span></td>
        <td class="dim">${esc(r.form_title || r.form_id)}</td>
        <td class="dim">${fmtDate(r.submitted_at)}</td>
        <td><button class="btn alt sm" data-inkview="${r.id}">${Object.keys(r.answers).length} answers</button></td>
        <td class="chips">${r.handled_as ? `<span class="pill ok">${esc(r.handled_as)} #${r.handled_id}</span>`
          : admin ? `<button class="btn alt sm" data-inkas="${r.id}" data-kind="enquiry">To an enquiry</button>
            <button class="btn alt sm" data-inkas="${r.id}" data-kind="student">To a student</button>
            <button class="btn alt sm" data-inkas="${r.id}" data-kind="customer">To a customer</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("file", "No responses yet", "Connect Google Forms and pull, or add the Apps Script trigger below.")}
    <h3>Gifts</h3>
    ${d.gifts.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>donor</th><th>amount</th><th>fund</th><th>when</th><th>via</th></tr></thead>
      <tbody>${d.gifts.map((g) => `<tr>
        <td><b>${esc(g.donor || "Anonymous")}</b>${g.email ? `<br><span class="dim">${esc(g.email)}</span>` : ""}</td>
        <td>${money(g.amount_cents)}${g.recurring ? ' <span class="pill">recurring</span>' : ""}</td>
        <td class="dim">${esc(g.fund || "")}</td><td class="dim">${fmtDate(g.at)}</td>
        <td class="dim">${esc(g.provider)}</td></tr>`).join("")}</tbody></table></div></div>`
      : emptyState("card", "No gifts recorded", "Point Network for Good at the address below, import its CSV, or log one by hand.")}
    <h3>Test results</h3>
    ${d.results.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>taker</th><th>student</th><th>test</th><th>score</th><th>when</th></tr></thead>
      <tbody>${d.results.map((t) => `<tr>
        <td>${esc(t.taker)}<br><span class="dim">${esc(t.email || "")}</span></td>
        <td>${t.user_id ? `<a href="#/student/${t.user_id}">${esc(t.student)}</a>`
          : admin ? `<button class="btn alt sm" data-inkmatch="${t.id}">Match</button>` : '<span class="pill warn">unmatched</span>'}</td>
        <td>${esc(t.provider === "gedmanager" ? "GED" : "NorthStar")} · ${esc(t.subject)}</td>
        <td><span class="pill ${t.passed ? "ok" : ""}">${t.score}${t.max_score ? " / " + t.max_score : ""}${t.passed ? " · pass" : ""}</span>
          ${t.certificate ? `<span class="dim">${esc(t.certificate)}</span>` : ""}</td>
        <td class="dim">${fmtDate(t.taken_at)}</td></tr>`).join("")}</tbody></table></div></div>`
      : emptyState("pen", "No results imported", "Export the score report from GED Manager or NorthStar and import it on the cards below.")}
    ${admin ? `<h3>Where it comes from</h3>
    <div class="card">
      <b>Google Forms, as it lands</b>
      <p class="dim">In the form: Extensions, Apps Script. Paste this, add an
        "On form submit" trigger. Each submission arrives the moment it is sent.
        The key comes from the Google Forms card once the address is set up.</p>
      <textarea readonly rows="8" style="font-family:monospace;font-size:12px">${esc(d.apps_script)}</textarea>
    </div>
    <div class="card">
      <b>CSV exports</b>
      <p class="dim">GED Manager and NorthStar export score reports; Network for
        Good exports donations. Pick the file and the source. Columns are read by
        what they mean, so an export with different headings still lands.</p>
      <div class="row2">
        <div><label>Source</label><select id="ink-src">
          <option value="gedmanager">GED Manager score report</option>
          <option value="northstar">NorthStar results</option>
          <option value="network4good">Network for Good donations</option></select></div>
        <div><label>File</label><input type="file" id="ink-csv" accept=".csv"></div>
      </div>
      <div id="ink-csvout"></div>
    </div>
    <div id="ink-cxn"></div>` : ""}`;

  view().querySelectorAll("[data-inkview]").forEach((b) => b.onclick = () => {
    const r = d.responses.find((x) => x.id === +b.dataset.inkview);
    modal(`<h3>${esc(r.name || "Response")}</h3><p class="dim">${esc(r.form_title || r.form_id)} · ${fmtDate(r.submitted_at)}</p>
      <div class="tablewrap"><table><tbody>${Object.entries(r.answers).map(([k, v]) =>
        `<tr><td class="dim">${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</tbody></table></div>`);
  });
  view().querySelectorAll("[data-inkas]").forEach((b) => b.onclick = async () => {
    try {
      const r = await api(`/api/intake/forms/${b.dataset.inkas}/as`, { body: { kind: b.dataset.kind } });
      toast(`now ${b.dataset.kind} #${r.id}`); renderIntake();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-inkmatch]").forEach((b) => b.onclick = async () => {
    const t = d.results.find((x) => x.id === +b.dataset.inkmatch);
    const people = await api("/api/customers?q=" + encodeURIComponent((t.email || t.taker || "").split(" ")[0])).catch(() => []);
    const list = Array.isArray(people) ? people : (people.customers || []);
    modal(`<h3>Whose result is this?</h3>
      <p class="dim">${esc(t.taker)} ${esc(t.email || "")} — ${esc(t.subject)}, ${t.score}</p>
      <div class="chips">${list.slice(0, 12).map((u) => `<button class="btn alt sm" data-inkpick="${u.id}">${esc(u.name)}${u.email ? " · " + esc(u.email) : ""}</button>`).join("")
        || '<span class="dim">Nobody similar found. Search on Customers, then match by id below.</span>'}</div>
      <label>Or a student id</label><input id="ink-uid" type="number">
      <p><button class="btn" id="ink-match">Match</button></p>`);
    const go = async (uid) => {
      try { await api(`/api/intake/results/${t.id}/match`, { body: { user_id: uid } }); closeModal(); renderIntake(); }
      catch (e) { toast(e.message); }
    };
    modalBody().querySelectorAll("[data-inkpick]").forEach((p) => p.onclick = () => go(+p.dataset.inkpick));
    $("#ink-match").onclick = () => go(+$("#ink-uid").value);
  });
  if ($("#ink-pull")) $("#ink-pull").onclick = async () => {
    try { const r = await api("/api/intake/forms/pull", { method: "POST" }); toast(`${r.new} new from ${r.forms} form(s)`); renderIntake(); }
    catch (e) { toast(e.message); }
  };
  if ($("#ink-gift")) $("#ink-gift").onclick = () => {
    modal(`<h3>Log a gift</h3>
      <div class="row2">
        <div><label>Donor</label><input id="ink-gdonor"></div>
        <div><label>Email</label><input id="ink-gmail" type="email"></div>
      </div>
      <div class="row2">
        <div><label>Amount ($)</label><input id="ink-gamt" type="number" step="0.01" min="0"></div>
        <div><label>Fund</label><input id="ink-gfund"></div>
      </div>
      <label class="perm"><input type="checkbox" id="ink-grec"><span>Recurring</span></label>
      <label>Note</label><input id="ink-gnote">
      <p><button class="btn" id="ink-gsave">Record</button></p>`);
    $("#ink-gsave").onclick = async () => {
      try {
        await api("/api/intake/gifts", { body: { donor: $("#ink-gdonor").value, email: $("#ink-gmail").value,
          amount_cents: Math.round(parseFloat($("#ink-gamt").value || 0) * 100), fund: $("#ink-gfund").value,
          recurring: $("#ink-grec").checked, note: $("#ink-gnote").value } });
        closeModal(); renderIntake();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#ink-csv")) $("#ink-csv").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(`/api/admin/integrations/${$("#ink-src").value}/import`, {
        method: "POST", headers: { Authorization: "Bearer " + S.user.token }, body: fd });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "import failed");
      $("#ink-csvout").innerHTML = `<p class="dim">Imported ${out.imported}${"matched" in out ? `, ${out.matched} matched to a student` : ""}.${
        out.skipped.length ? ` Skipped ${out.skipped.length}: ` + out.skipped.map((s) => esc(`row ${s.row} — ${s.why}`)).join("; ") : ""}</p>`;
      renderIntake();
    } catch (err) { toast(err.message); }
  };
  connectionCards(["google_forms", "network4good", "gedmanager", "northstar"], renderIntake, $("#ink-cxn"));
}
