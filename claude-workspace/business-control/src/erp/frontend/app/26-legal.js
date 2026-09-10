// ---------- the legal register ----------
/* The vault holds the contract; this holds the fact that it renews in
   March unless somebody says otherwise ninety days before. A filing
   cabinet is not a diary, and the businesses that get caught by a notice
   period are the ones that filed the contract correctly. */
async function renderLegal() {
  const d = await api("/api/legal");
  const day = 86400;
  const when = (t) => {
    const days = Math.round((t - d.now) / day);
    if (days < 0) return `${-days} day${days === -1 ? "" : "s"} ago`;
    if (days === 0) return "today";
    return `in ${days} day${days === 1 ? "" : "s"}`;
  };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Legal register</h2>
        <p class="dim">What this business is committed to and what falls due
          when. It records decisions somebody made; it is not advice, and it
          does not know your jurisdiction.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="lgl-oblig">Add an obligation</button>
        <button class="btn" id="lgl-new">Add a matter</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Active</span><b>${d.counts.active}</b></div>
      <div class="card tile"><span class="dim">Need a decision</span>
        <b>${d.counts.attention}</b>
        <span class="dim">inside a notice period, or ending soon</span></div>
      <div class="card tile"><span class="dim">Overdue</span><b>${d.counts.overdue}</b></div>
      <div class="card tile"><span class="dim">High risk</span><b>${d.counts.high_risk}</b></div>
    </div>
    <h3>What falls due</h3>
    ${d.diary.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>what</th><th>under</th><th></th></tr></thead>
      <tbody>${d.diary.map((x) => `<tr class="${x.overdue ? "" : "dim"}">
        <td>${fmtDate(x.at)}<br><span class="dim">${when(x.at)}</span></td>
        <td>${x.overdue ? '<span class="pill bad">overdue</span> ' : ""}${esc(x.what)}
          ${x.every_months ? `<span class="dim">every ${x.every_months} month${x.every_months === 1 ? "" : "s"}</span>` : ""}</td>
        <td class="dim">${esc(x.matter || "")}</td>
        <td>${x.kind === "obligation"
          ? `<button class="btn alt sm" data-lgldone="${x.id}">Done</button>`
          : `<button class="btn alt sm" data-lglopen="${x.id}">Open it</button>`}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("calendar", "Nothing due in the next six months",
          "Add the lease, the insurance and the licences, with the dates "
          + "that matter, and this becomes the page you check.")}
    <h3>The register</h3>
    ${d.matters.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>what</th><th>with</th><th>runs</th><th>decide by</th>
        <th>status</th><th></th></tr></thead>
      <tbody>${d.matters.map((m) => `<tr class="${m.status === "active" ? "" : "dim"}">
        <td><b>${esc(m.title)}</b><br><span class="dim">${esc(m.kind_label)}${
          m.risk === "high" ? " · high risk" : ""}</span></td>
        <td>${esc(m.counterparty || "")}${m.jurisdiction
          ? `<br><span class="dim">${esc(m.jurisdiction)}</span>` : ""}</td>
        <td class="dim">${m.starts ? fmtDate(m.starts) : "—"} to
          ${m.ends ? fmtDate(m.ends) : "open ended"}
          ${m.value_cents ? `<br>${money(m.value_cents)}${m.value_period ? " " + esc(m.value_period) : ""}` : ""}</td>
        <td>${m.decide_by
          ? `${fmtDate(m.decide_by)}<br><span class="${m.needs_attention ? "" : "dim"}">${when(m.decide_by)}</span>`
          : '<span class="dim">nothing to decide</span>'}
          ${m.renews === "auto" ? '<br><span class="pill warn">renews on its own</span>' : ""}</td>
        <td><span class="pill ${m.status === "active" ? "ok" : ""}">${esc(m.status)}</span></td>
        <td><button class="btn alt sm" data-lgledit="${m.id}">Edit</button></td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("shield2", "Nothing on the register yet",
          "A matter is a contract, a policy, a licence, a filing or a "
          + "dispute — anything with a date somebody has to act on.")}`;

  const matterForm = (m) => {
    const dv = (t) => t ? new Date(t * 1000).toISOString().slice(0, 10) : "";
    modal(`<h3>${m ? "Edit" : "Add"} a matter</h3>
      <div class="row2">
        <div><label>Kind</label><select id="lgl-kind">${d.kinds.map((k) =>
          `<option value="${k.k}" ${m && m.kind === k.k ? "selected" : ""}>${esc(k.label)}</option>`).join("")}</select></div>
        <div><label>Status</label><select id="lgl-status">${d.statuses.map((s) =>
          `<option value="${s}" ${m && m.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
      </div>
      <label>Title</label><input id="lgl-title" value="${esc(m ? m.title : "")}"
        placeholder="Unit 4 lease">
      <div class="row2">
        <div><label>With</label><input id="lgl-party" value="${esc(m ? m.counterparty : "")}"></div>
        <div><label>Their reference</label><input id="lgl-ref" value="${esc(m ? m.reference : "")}"></div>
      </div>
      <div class="row2">
        <div><label>Starts</label><input id="lgl-starts" type="date" value="${dv(m && m.starts)}"></div>
        <div><label>Ends</label><input id="lgl-ends" type="date" value="${dv(m && m.ends)}"></div>
      </div>
      <div class="row2">
        <div><label>Notice period (days)</label><input id="lgl-notice" type="number" min="0"
          value="${m ? m.notice_days : 0}"></div>
        <div><label>Renews</label><select id="lgl-renews">${d.renews.map((r) =>
          `<option value="${r}" ${m && m.renews === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Worth / costs ($)</label><input id="lgl-value" type="number" step="0.01"
          value="${m && m.value_cents ? (m.value_cents / 100).toFixed(2) : ""}"></div>
        <div><label>Per</label><select id="lgl-period">
          ${["", "once", "monthly", "yearly"].map((v) =>
            `<option value="${v}" ${m && m.value_period === v ? "selected" : ""}>${v || "—"}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Risk</label><select id="lgl-risk">${d.risks.map((r) =>
          `<option value="${r}" ${m && m.risk === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
        <div><label>Jurisdiction</label><input id="lgl-juris" value="${esc(m ? m.jurisdiction : "")}"></div>
      </div>
      <label>Notes</label><textarea id="lgl-note" rows="3">${esc(m ? m.note : "")}</textarea>
      <p><button class="btn" id="lgl-save">Save</button></p>`, "wide");
    $("#lgl-save").onclick = async () => {
      const ts = (id) => {
        const v = $(id).value;
        return v ? new Date(v).getTime() / 1000 : 0;
      };
      try {
        await api("/api/legal/matters", { body: {
          id: m ? m.id : 0, kind: $("#lgl-kind").value, title: $("#lgl-title").value,
          counterparty: $("#lgl-party").value, reference: $("#lgl-ref").value,
          jurisdiction: $("#lgl-juris").value, starts: ts("#lgl-starts"),
          ends: ts("#lgl-ends"), notice_days: +$("#lgl-notice").value || 0,
          renews: $("#lgl-renews").value,
          value_cents: Math.round(parseFloat($("#lgl-value").value || 0) * 100),
          value_period: $("#lgl-period").value, status: $("#lgl-status").value,
          risk: $("#lgl-risk").value, note: $("#lgl-note").value } });
        closeModal(); renderLegal();
      } catch (e) { toast(e.message); }
    };
  };
  $("#lgl-new").onclick = () => matterForm(null);
  view().querySelectorAll("[data-lgledit]").forEach((b) => b.onclick = () =>
    matterForm(d.matters.find((m) => m.id === +b.dataset.lgledit)));
  view().querySelectorAll("[data-lglopen]").forEach((b) => b.onclick = () =>
    matterForm(d.matters.find((m) => m.id === +b.dataset.lglopen)));
  $("#lgl-oblig").onclick = () => {
    modal(`<h3>Add an obligation</h3>
      <p class="dim">Something that has to be done by a date. Where it
        repeats, marking it done opens the next one.</p>
      <label>What</label><input id="lgl-owhat" placeholder="Quarterly fire inspection">
      <div class="row2">
        <div><label>Due</label><input id="lgl-odue" type="date"></div>
        <div><label>Repeat every (months)</label><input id="lgl-oevery" type="number"
          min="0" max="120" value="0"></div>
      </div>
      <label>Under which matter</label><select id="lgl-omatter">
        <option value="0">— a standing duty of its own —</option>
        ${d.matters.map((m) => `<option value="${m.id}">${esc(m.title)}</option>`).join("")}
      </select>
      <label>Detail</label><textarea id="lgl-odetail" rows="2"></textarea>
      <p><button class="btn" id="lgl-osave">Add</button></p>`);
    $("#lgl-osave").onclick = async () => {
      try {
        await api("/api/legal/obligations", { body: {
          what: $("#lgl-owhat").value, detail: $("#lgl-odetail").value,
          due: $("#lgl-odue").value ? new Date($("#lgl-odue").value).getTime() / 1000 : 0,
          every_months: +$("#lgl-oevery").value || 0,
          matter_id: +$("#lgl-omatter").value } });
        closeModal(); renderLegal();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-lgldone]").forEach((b) => b.onclick = async () => {
    try {
      const r = await api(`/api/legal/obligations/${b.dataset.lgldone}/done`, { body: {} });
      toast(r.next_id ? "done — the next one is on the diary" : "done");
      renderLegal();
    } catch (e) { toast(e.message); }
  });
}
