// ---------- traffic: who is asking, and the door ----------
/* The last hour of requests, who is asking the most and what each looks
   like, and beside each one the buttons that act on it. Rules — bans,
   blocks, the allow list — under that, each with its reason and its
   expiry, and a settings card for the automatic bans. */
let TRF = { minutes: 60, ip: "", path: "", status: "", ua: "", kind: "" };

async function renderTraffic() {
  const q = new URLSearchParams({ minutes: TRF.minutes });
  for (const k of ["ip", "path", "status", "ua", "kind"]) if (TRF[k]) q.set(k, TRF[k]);
  const d = await api("/api/traffic?" + q.toString());
  const s = d.settings;
  const when = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const st = (x) => `<span class="${x.blocked ? "pill bad" : x.status >= 500 ? "pill bad" : x.status >= 400 ? "pill warn" : "dim"}">${x.blocked ? "refused" : x.status}</span>`;
  const left = (r) => r.expires_at ? `until ${fmtDate(r.expires_at)} ${new Date(r.expires_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "for good";
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Traffic and bans</h2>
        <p class="dim">Every request, written down as it happens; who is asking the most;
          and the door — ban an address, block a user agent, refuse a path — in one click,
          with a reason. Rules are checked before anything else the server does.</p></div>
      <div class="top-actions">
        <a class="btn alt" href="/api/traffic/export.csv?minutes=1440&t=${encodeURIComponent(S.user.token)}" download>CSV, last day</a>
        <button class="btn alt" id="trf-rule">Add a rule</button>
        <button class="btn" id="trf-refresh">Refresh</button>
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Last hour</span><b>${d.counts.hour}</b></div>
      <div class="card tile"><span class="dim">Last day</span><b>${d.counts.day}</b><span class="dim">${d.counts.addresses_day} addresses</span></div>
      <div class="card tile"><span class="dim">Refused, last day</span><b>${d.counts.blocked_day}</b></div>
      <div class="card tile"><span class="dim">Guard</span><b>${s.enabled ? "on" : "off"}</b><span class="dim">auto-ban ${s.auto_ban ? "on" : "off"}</span></div>
    </div>
    <h3>Who is asking the most <span class="dim">last ${TRF.minutes} min</span></h3>
    <div class="card">${d.talkers.length ? `<div class="tablewrap"><table>
      <thead><tr><th>address</th><th>requests</th><th>errors</th><th>paths</th><th>looks like</th><th>asked for</th><th></th></tr></thead>
      <tbody>${d.talkers.map((t) => `<tr class="${t.blocked ? "dim" : ""}">
        <td><code>${esc(t.ip)}</code>${t.user_id ? ` <span class="dim">user ${t.user_id}</span>` : ""}</td>
        <td><b>${t.n}</b></td><td>${t.errors || 0}${t.blocked ? ` <span class="pill bad">${t.blocked} refused</span>` : ""}</td>
        <td>${t.paths}</td>
        <td><span class="pill${/bot|no user agent|crawling|errors/.test(t.looks_like) ? " warn" : ""}">${esc(t.looks_like)}</span>
          <div class="dim trf-ua" title="${esc(t.ua || "")}">${esc((t.ua || "").slice(0, 60))}</div></td>
        <td class="dim">${t.sample_paths.map(esc).join("<br>")}</td>
        <td class="row-acts">
          <button class="btn alt sm" data-trfsee="${esc(t.ip)}">See</button>
          <button class="btn sm" data-trfban="${esc(t.ip)}">Ban</button>
          ${t.ua ? `<button class="btn alt sm" data-trfua="${esc(t.ua)}">Block agent</button>` : ""}
        </td></tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">Nothing in this window.</p>`}</div>
    <h3>Requests</h3>
    <div class="card trf-filters">
      <select id="trf-min">${[15, 60, 360, 1440].map((m) => `<option value="${m}" ${m === TRF.minutes ? "selected" : ""}>last ${m < 60 ? m + " min" : m / 60 + " h"}</option>`).join("")}</select>
      <input id="trf-ip" placeholder="address" value="${esc(TRF.ip)}">
      <input id="trf-path" placeholder="path contains" value="${esc(TRF.path)}">
      <input id="trf-uaq" placeholder="user agent contains" value="${esc(TRF.ua)}">
      <select id="trf-status"><option value="">any status</option>${["blocked", "4xx", "5xx", "200", "401", "403", "404"].map((x) => `<option value="${x}" ${x === TRF.status ? "selected" : ""}>${x}</option>`).join("")}</select>
      <select id="trf-kind"><option value="">pages and api</option>${["page", "api", "asset"].map((x) => `<option value="${x}" ${x === TRF.kind ? "selected" : ""}>${x}</option>`).join("")}</select>
      <button class="btn alt sm" id="trf-apply">Filter</button>
      <button class="btn alt sm" id="trf-clear">Clear</button>
    </div>
    <div class="card">${d.recent.length ? `<div class="tablewrap"><table class="trf-log">
      <thead><tr><th>when</th><th>address</th><th>request</th><th>status</th><th>ms</th><th>agent</th></tr></thead>
      <tbody>${d.recent.map((x) => `<tr class="${x.blocked ? "trf-blocked" : ""}">
        <td class="dim">${when(x.at)}</td>
        <td><a data-trfsee="${esc(x.ip)}"><code>${esc(x.ip)}</code></a>${x.user_id ? ` <span class="dim">u${x.user_id}</span>` : ""}</td>
        <td><span class="dim">${esc(x.method)}</span> ${esc(x.path)}${x.query ? `<span class="dim">?${esc(x.query.slice(0, 60))}</span>` : ""}</td>
        <td>${st(x)}</td><td class="dim">${x.ms}</td>
        <td class="dim trf-ua" title="${esc(x.ua)}">${esc((x.ua || "").slice(0, 40))}</td>
      </tr>`).join("")}</tbody></table></div>` : `<p class="dim">No requests match.</p>`}</div>
    <h3>Rules <span class="dim">${d.rules.length}</span></h3>
    <div class="card">${d.rules.length ? `<div class="tablewrap"><table>
      <thead><tr><th>kind</th><th>target</th><th>value</th><th>scope</th><th>reason</th><th>expires</th><th>hits</th><th></th></tr></thead>
      <tbody>${d.rules.map((r) => `<tr>
        <td><span class="pill${r.kind === "deny" ? " bad" : " ok"}">${esc(r.kind)}</span>${r.auto ? ' <span class="dim">auto</span>' : ""}</td>
        <td>${esc(r.target)}</td><td><code>${esc(r.value)}</code></td><td class="dim">${esc(r.scope || "everything")}</td>
        <td>${esc(r.reason)}${r.by_name ? ` <span class="dim">· ${esc(r.by_name)}</span>` : ""}</td>
        <td class="dim">${left(r)}</td><td>${r.hits}</td>
        <td><button class="btn alt sm" data-trflift="${r.id}">Lift</button></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">No rules. The door is open to everyone; automatic bans ${s.auto_ban ? "will appear here as they happen" : "are off"}.</p>`}</div>
    <h3>Automatic bans</h3>
    <div class="card trf-settings">
      <label class="chk"><input type="checkbox" id="trf-enabled" ${s.enabled ? "checked" : ""}> Log requests and check the door</label>
      <label class="chk"><input type="checkbox" id="trf-auto" ${s.auto_ban ? "checked" : ""}> Ban automatically</label>
      <label class="chk"><input type="checkbox" id="trf-assets" ${s.log_assets ? "checked" : ""}> Log assets too (scripts, images, fonts — noisy)</label>
      <div class="row2">
        <label>Requests a minute from one address <input id="trf-rate" type="number" min="1" value="${s.rate_per_minute}"></label>
        <label>Errors a minute from one address <input id="trf-errs" type="number" min="1" value="${s.errors_per_minute}"></label>
      </div>
      <div class="row2">
        <label>Rate ban, minutes <input id="trf-rateban" type="number" min="1" value="${s.rate_ban_minutes}"></label>
        <label>Probe ban, hours <input id="trf-probeban" type="number" min="1" value="${s.probe_ban_hours}"></label>
      </div>
      <label>Probe paths <span class="opt">one per line; one request for any of these is a scanner</span>
        <textarea id="trf-probes" rows="4">${esc((s.probe_paths || []).join("\n"))}</textarea></label>
      <label>Keep the log, days <input id="trf-keep" type="number" min="1" value="${s.keep_days}"></label>
      <div class="actions"><button class="btn" id="trf-save">Save</button></div>
    </div>`;
  $("#trf-refresh").onclick = () => renderTraffic();
  $("#trf-rule").onclick = () => trafficRuleForm({});
  const apply = () => { TRF = { minutes: +$("#trf-min").value, ip: $("#trf-ip").value.trim(), path: $("#trf-path").value.trim(),
    ua: $("#trf-uaq").value.trim(), status: $("#trf-status").value, kind: $("#trf-kind").value }; renderTraffic(); };
  $("#trf-apply").onclick = apply;
  $("#trf-min").onchange = apply;
  $("#trf-clear").onclick = () => { TRF = { minutes: 60, ip: "", path: "", status: "", ua: "", kind: "" }; renderTraffic(); };
  view().querySelectorAll("[data-trfsee]").forEach((b) => b.onclick = () => { TRF.ip = b.dataset.trfsee; renderTraffic(); });
  view().querySelectorAll("[data-trfban]").forEach((b) => b.onclick = () => trafficRuleForm({ target: "ip", value: b.dataset.trfban }));
  view().querySelectorAll("[data-trfua]").forEach((b) => b.onclick = () => trafficRuleForm({ target: "ua", value: b.dataset.trfua }));
  view().querySelectorAll("[data-trflift]").forEach((b) => b.onclick = async () => {
    await api(`/api/traffic/rules/${b.dataset.trflift}`, { method: "DELETE" }); renderTraffic();
  });
  $("#trf-save").onclick = async () => {
    try {
      await api("/api/traffic/settings", { body: { patch: {
        enabled: $("#trf-enabled").checked, auto_ban: $("#trf-auto").checked, log_assets: $("#trf-assets").checked,
        rate_per_minute: +$("#trf-rate").value, errors_per_minute: +$("#trf-errs").value,
        rate_ban_minutes: +$("#trf-rateban").value, probe_ban_hours: +$("#trf-probeban").value,
        probe_paths: $("#trf-probes").value.split("\n").map((x) => x.trim()).filter(Boolean),
        keep_days: +$("#trf-keep").value } } });
      toast("saved"); renderTraffic();
    } catch (e) { toast(e.message); }
  };
}

/* One rule: what to refuse or allow, where, for how long, and why. The
   reason is required — a ban with no reason is one nobody lifts with
   confidence. */
function trafficRuleForm(pre) {
  modal(`<h3>${pre.value ? "Ban or block" : "Add a rule"}</h3>
    <div class="row2">
      <label>Kind <select id="trf-f-kind">
        <option value="deny">deny — refuse</option>
        <option value="allow">allow — only these may pass the scope</option></select></label>
      <label>Target <select id="trf-f-target">
        <option value="ip" ${pre.target === "ip" ? "selected" : ""}>address or network (CIDR)</option>
        <option value="ua" ${pre.target === "ua" ? "selected" : ""}>user agent contains</option>
        <option value="path" ${pre.target === "path" ? "selected" : ""}>path starts with</option></select></label>
    </div>
    <label>Value <input id="trf-f-value" value="${esc(pre.value || "")}" placeholder="203.0.113.0/24, or curl, or /wp-login"></label>
    <div class="row2">
      <label>Scope <span class="opt">blank = the whole site</span><input id="trf-f-scope" placeholder="/ops or /admin"></label>
      <label>For <select id="trf-f-hours">
        <option value="1">an hour</option><option value="24" selected>a day</option>
        <option value="168">a week</option><option value="720">a month</option><option value="0">for good</option></select></label>
    </div>
    <label>Reason <span class="req">required</span><input id="trf-f-reason" placeholder="hammering the checkout; scanning for wp-login"></label>
    <p class="dim">An allow rule on a scope locks that scope to the listed addresses — include your own first.</p>
    <div class="actions"><button class="btn" id="trf-f-save">Save rule</button></div>`);
  $("#trf-f-save").onclick = async () => {
    try {
      await api("/api/traffic/rules", { body: {
        kind: $("#trf-f-kind").value, target: $("#trf-f-target").value, value: $("#trf-f-value").value,
        scope: $("#trf-f-scope").value.trim(), hours: +$("#trf-f-hours").value, reason: $("#trf-f-reason").value } });
      closeModal(); renderTraffic();
    } catch (e) { toast(e.message); }
  };
}
