// ---------- automations ----------
/* When this happens, do that. Rules ride the same event bus as Discord
   and the integrations, so a rule that throws never fails the order it
   heard about. The action list is deliberately short: raise attention,
   open work, tell an outside system. Nothing that spends, publishes or
   mails a customer — if a rule wants to, what it wants is a ticket for
   a person. */
async function renderAutomations() {
  const d = await api("/api/automation");
  const byAction = Object.fromEntries(d.actions.map((a) => [a.k, a]));
  const runsFor = (id) => d.runs.filter((r) => r.rule_id === id);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Automations</h2>
        <p class="dim">Rules that watch what happens and act on it. They can
          raise attention, open work and tell an outside system. They cannot
          spend, publish or email a customer.</p></div>
      <div class="top-actions">
        <button class="btn" id="aut-new">New rule</button>
      </div>
    </div>
    ${d.rules.length ? d.rules.map((r) => {
      const runs = runsFor(r.id);
      const failed = runs.filter((x) => !x.ok).length;
      return `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(r.name)}</b>
            <span class="dim">when ${esc(r.event_label)}, ${esc(r.action_label).toLowerCase()}</span></div>
          <span class="pill ${r.active ? "ok" : ""}">${r.active ? "on" : "off"}</span>
          ${r.runs ? `<span class="pill ${failed ? "bad" : ""}">${r.runs} run${r.runs === 1 ? "" : "s"}${
            failed ? ` · ${failed} failed` : ""}</span>` : '<span class="pill">never run</span>'}
          <button class="btn alt sm" data-auttest="${r.id}">Test it</button>
          <button class="btn alt sm" data-autedit="${r.id}">Edit</button>
          <button class="btn alt sm" data-autdel="${r.id}">Remove</button>
        </div>
        ${r.conditions.length ? `<p class="dim">Only when
          ${r.conditions.map((c) => `<code>${esc(c.field)}</code> ${esc(
            (d.ops.find((o) => o.k === c.op) || {}).label || c.op)}
            ${c.op === "present" ? "" : `<b>${esc(c.value)}</b>`}`).join(" and ")}.</p>`
          : '<p class="dim">Every time.</p>'}
        <p class="dim">${esc((byAction[r.action] || {}).what || "")}
          ${r.cooldown_sec ? `At most once every ${r.cooldown_sec} seconds.` : ""}
          ${r.has_token ? "A token is saved." : ""}</p>
        ${runs.length ? `<div class="tablewrap"><table>
          <thead><tr><th>when</th><th>result</th></tr></thead>
          <tbody>${runs.slice(0, 5).map((x) => `<tr>
            <td class="dim">${fmtAgo(x.at)}</td>
            <td>${x.ok ? '<span class="pill ok">ok</span>' : '<span class="pill bad">failed</span>'}
              <span class="dim">${esc(x.detail || "")}</span></td>
          </tr>`).join("")}</tbody></table></div>` : ""}
      </div>`;
    }).join("")
      : emptyState("flask", "No rules yet",
          "A rule is an event, some conditions, and one thing to do. Start "
          + "with telling the team when a big order lands.")}
    <div class="card">
      <b>What a rule may do</b>
      ${d.actions.map((a) => `<p class="dim"><b>${esc(a.label)}</b> — ${esc(a.what)}</p>`).join("")}
      <p class="dim">Deliberately absent: anything that moves money,
        publishes in the business's name, or emails a customer. Those stay
        with a person, and a rule that seems to want one of them wants a
        ticket instead.</p>
    </div>`;

  const ruleForm = (r) => {
    const condRow = (c) => `<div class="row2" data-autcond>
      <div><label>Field</label><input data-autfield value="${esc(c ? c.field : "")}"
        placeholder="total_cents"></div>
      <div><label>Test</label><select data-autop>${d.ops.map((o) =>
        `<option value="${o.k}" ${c && c.op === o.k ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></div>
      <div><label>Value</label><input data-autval value="${esc(c ? c.value : "")}"></div>
    </div>`;
    const fieldsFor = (act, cfg) => (byAction[act] || { fields: [] }).fields
      .map((f) => `<label class="f">${esc(f.label)}${f.required ? "" : " (optional)"}
        <input data-autcfg="${esc(f.k)}" value="${esc((cfg || {})[f.k] || "")}"></label>`).join("");
    modal(`<h3>${r ? "Edit" : "New"} rule</h3>
      <label>Name it something you will recognise</label>
      <input id="aut-name" value="${esc(r ? r.name : "")}" placeholder="Big order needs a call">
      <div class="row2">
        <div><label>When</label><select id="aut-event">${d.events.map((e) =>
          `<option value="${e.k}" ${r && r.event === e.k ? "selected" : ""}>${esc(e.label)}</option>`).join("")}</select></div>
        <div><label>Do this</label><select id="aut-action">${d.actions.map((a) =>
          `<option value="${a.k}" ${r && r.action === a.k ? "selected" : ""}>${esc(a.label)}</option>`).join("")}</select></div>
      </div>
      <label>Only when <span class="dim">(leave empty for every time; use
        <code>{field}</code> in the text below to quote the event)</span></label>
      <div id="aut-conds">${(r && r.conditions.length ? r.conditions : []).map(condRow).join("")}</div>
      <div class="chips" style="margin-top:6px">
        <button class="btn alt sm" id="aut-addcond">Add a condition</button>
      </div>
      <div id="aut-fields" style="margin-top:12px">${fieldsFor(r ? r.action : d.actions[0].k, r && r.config)}</div>
      <div class="row2">
        <div><label>At most once every (seconds)</label>
          <input id="aut-cool" type="number" min="0" max="86400" value="${r ? r.cooldown_sec : 60}"></div>
        <div><label class="perm" style="margin-top:26px"><input type="checkbox" id="aut-active"
          ${!r || r.active ? "checked" : ""}><span>On</span></label></div>
      </div>
      <p><button class="btn" id="aut-save">Save</button></p>`, "wide");
    $("#aut-addcond").onclick = () =>
      $("#aut-conds").insertAdjacentHTML("beforeend", condRow(null));
    $("#aut-action").onchange = () => {
      $("#aut-fields").innerHTML = fieldsFor($("#aut-action").value, null);
    };
    $("#aut-save").onclick = async () => {
      const conditions = [...modalBody().querySelectorAll("[data-autcond]")]
        .map((el) => ({ field: el.querySelector("[data-autfield]").value.trim(),
                        op: el.querySelector("[data-autop]").value,
                        value: el.querySelector("[data-autval]").value }))
        .filter((c) => c.field);
      const config = {};
      modalBody().querySelectorAll("[data-autcfg]").forEach((i) => {
        if (i.value.trim()) config[i.dataset.autcfg] = i.value.trim();
      });
      try {
        await api("/api/automation/rules", { body: {
          id: r ? r.id : 0, name: $("#aut-name").value, event: $("#aut-event").value,
          action: $("#aut-action").value, conditions, config,
          active: $("#aut-active").checked,
          cooldown_sec: +$("#aut-cool").value || 0 } });
        closeModal(); renderAutomations();
      } catch (e) { toast(e.message); }
    };
  };
  $("#aut-new").onclick = () => ruleForm(null);
  view().querySelectorAll("[data-autedit]").forEach((b) => b.onclick = () =>
    ruleForm(d.rules.find((r) => r.id === +b.dataset.autedit)));
  view().querySelectorAll("[data-autdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this rule? What it already did stays done.")) return;
    await api(`/api/automation/rules/${b.dataset.autdel}`, { method: "DELETE" });
    renderAutomations();
  });
  view().querySelectorAll("[data-auttest]").forEach((b) => b.onclick = () => {
    const r = d.rules.find((x) => x.id === +b.dataset.auttest);
    modal(`<h3>Test ${esc(r.name)}</h3>
      <p class="dim">Fires it against a payload you write, ignoring the
        cooldown. A rule nobody has seen work is a rule somebody hoped
        about, and a real event is a bad time to find out the URL was
        wrong.</p>
      <label>The event, as JSON</label>
      <textarea id="aut-payload" rows="5">{"id": 1, "total_cents": 9900}</textarea>
      <p><button class="btn" id="aut-fire">Fire it</button></p>
      <p id="aut-out" class="dim"></p>`);
    $("#aut-fire").onclick = async () => {
      let payload;
      try { payload = JSON.parse($("#aut-payload").value); }
      catch (e) { $("#aut-out").textContent = "that is not JSON"; return; }
      try {
        const out = await api(`/api/automation/rules/${r.id}/test`, { body: { payload } });
        $("#aut-out").innerHTML = out.matched
          ? `<b>${out.ok ? "Ran" : "Failed"}:</b> ${esc(out.detail)}`
          : `<b>Did not match.</b> ${esc(out.detail)}`;
        renderAutomations();
      } catch (e) { $("#aut-out").textContent = e.message; }
    };
  });
}
