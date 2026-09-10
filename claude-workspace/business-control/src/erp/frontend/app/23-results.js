// ---------- test results ----------
/* What a learner passed somewhere else. Its own screen under Teach,
   because a school buys Learning for exactly this and had no reason to
   buy Fundraising to reach it — which is where it lived when one screen
   held forms, gifts and scores together.

   GED Manager and NorthStar publish no API. Both export a CSV, and the
   reader looks for what a column MEANS rather than for a fixed heading,
   so an export with different titles still lands. A row that matches
   nobody is kept and marked, never guessed at: a score on the wrong
   student's record is worse than a score in a tray. */
async function renderResults() {
  const d = await api("/api/results");
  const admin = S.user.is_admin || S.user.role === "admin"
    || S.user.role === "owner";
  const src = (p) => (p === "gedmanager" ? "GED" : "NorthStar");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Test results</h2>
        <p class="dim">What your learners passed elsewhere, on their record
          here. A pass is logged as an achievement they can see; anything
          that matches nobody waits until you say whose it is.</p></div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Results</span><b>${d.results.length}</b>
        <span class="dim">${d.passed} passed</span></div>
      <div class="card tile"><span class="dim">Learners</span><b>${d.learners}</b></div>
      <div class="card tile"><span class="dim">Waiting on you</span>
        <b>${d.unmatched}</b>
        <span class="dim">${d.unmatched ? "not matched to a student" : "all matched"}</span></div>
    </div>
    ${d.results.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>taker</th><th>student</th><th>test</th><th>score</th>
        <th>when</th></tr></thead>
      <tbody>${d.results.map((t) => `<tr class="${t.user_id ? "" : "dim"}">
        <td>${esc(t.taker)}<br><span class="dim">${esc(t.email || "")}</span></td>
        <td>${t.user_id ? `<a href="#/student/${t.user_id}">${esc(t.student)}</a>`
          : admin ? `<button class="btn alt sm" data-resmatch="${t.id}">Match</button>`
          : '<span class="pill warn">unmatched</span>'}</td>
        <td>${esc(src(t.provider))} · ${esc(t.subject)}</td>
        <td><span class="pill ${t.passed ? "ok" : ""}">${t.score}${
          t.max_score ? " / " + t.max_score : ""}${t.passed ? " · pass" : ""}</span>
          ${t.certificate ? `<span class="dim">${esc(t.certificate)}</span>` : ""}</td>
        <td class="dim">${fmtDate(t.taken_at)}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("chart", "No results imported yet",
          "Export the score report from GED Manager or NorthStar and import "
          + "it below.")}
    ${admin ? `<h3>Where they come from</h3>
    <div class="card">
      <p class="dim">Neither publishes an API, so this is the direction that
        exists: the score report each of them exports. A taker is matched to
        a student by email, then by an exact name. Columns are read by what
        they mean, so an export with different headings still lands.</p>
      <div class="row2">
        <div><label>Source</label><select id="res-src">
          <option value="gedmanager">GED Manager score report</option>
          <option value="northstar">NorthStar results</option></select></div>
        <div><label>File</label><input type="file" id="res-csv" accept=".csv"></div>
      </div>
      <div id="res-csvout"></div>
    </div>
    <div id="res-cxn"></div>` : ""}`;

  view().querySelectorAll("[data-resmatch]").forEach((b) => b.onclick = async () => {
    const t = d.results.find((x) => x.id === +b.dataset.resmatch);
    const people = await api("/api/customers?q="
      + encodeURIComponent((t.email || t.taker || "").split(" ")[0])).catch(() => []);
    const list = Array.isArray(people) ? people : (people.customers || []);
    modal(`<h3>Whose result is this?</h3>
      <p class="dim">${esc(t.taker)} ${esc(t.email || "")} — ${esc(t.subject)},
        ${t.score}</p>
      <div class="chips">${list.slice(0, 12).map((u) =>
        `<button class="btn alt sm" data-respick="${u.id}">${esc(u.name)}${
          u.email ? " · " + esc(u.email) : ""}</button>`).join("")
        || '<span class="dim">Nobody similar found. Search on Customers, then match by id below.</span>'}</div>
      <label>Or a student id</label><input id="res-uid" type="number">
      <p><button class="btn" id="res-match">Match</button></p>`);
    const go = async (uid) => {
      try {
        await api(`/api/intake/results/${t.id}/match`, { body: { user_id: uid } });
        closeModal(); renderResults();
      } catch (e) { toast(e.message); }
    };
    modalBody().querySelectorAll("[data-respick]").forEach((p) =>
      p.onclick = () => go(+p.dataset.respick));
    $("#res-match").onclick = () => go(+$("#res-uid").value);
  });

  if ($("#res-csv")) $("#res-csv").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(`/api/admin/integrations/${$("#res-src").value}/import`, {
        method: "POST", headers: { Authorization: "Bearer " + S.user.token },
        body: fd });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "import failed");
      $("#res-csvout").innerHTML = `<p class="dim">Imported ${out.imported},
        ${out.matched} matched to a student.${out.skipped.length
          ? ` Skipped ${out.skipped.length}: ` + out.skipped.map((s) =>
              esc(`row ${s.row} — ${s.why}`)).join("; ") : ""}</p>`;
      renderResults();
    } catch (err) { toast(err.message); }
  };
  if ($("#res-cxn"))
    connectionCards(["gedmanager", "northstar"], renderResults, $("#res-cxn"));
}
