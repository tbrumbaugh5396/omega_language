/* Devices: who has been here, and roughly where they are.

   A device is one browser on one machine — not a person, not a cookie —
   recognised by what it volunteers: user-agent, language, timezone,
   screen. "Where" is the browser's own clock and keyboard, which is a
   good guess and never a claim; a real address lookup needs a GeoIP
   database this install does not ship, and this screen says so rather
   than drawing a map it cannot stand behind. */

async function renderDevices() {
  const days = S.devDays || 30;
  const [an, ls] = await Promise.all([
    api(`/api/admin/devices/analysis?days=${days}`).catch((e) => ({ err: e.message })),
    api(`/api/admin/devices?days=${days}&q=${encodeURIComponent(S.devQ || "")}`).catch(() => ({ devices: [] })),
  ]);
  const bar = (rows, total) => rows.map((r) => `<div class="dv-bar">
    <span class="dv-k" title="${esc(r.k)}">${esc(r.k)}</span>
    <i style="width:${total ? Math.round(r.n / total * 100) : 0}%"></i>
    <b>${r.n}</b></div>`).join("") || `<span class="dim">nothing yet</span>`;
  const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60);
    return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`; };
  const devs = ls.devices || [];
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Devices</h2><p class="dim">${esc(an.note || ls.note || "")}</p></div>
      <span class="chips">${[7, 30, 90].map((n) => `<button class="btn ${n === days ? "" : "alt"} sm" data-dvdays="${n}">${n}d</button>`).join("")}</span>
    </div>
    ${an.err ? `<div class="card empty"><b>${esc(an.err)}</b></div>` : `
    <div class="row">
      <div class="card stat"><span class="big">${an.devices}</span><span class="dim">devices seen</span></div>
      <div class="card stat"><span class="big">${an.returning}</span><span class="dim">came back</span></div>
      <div class="card stat"><span class="big">${an.signed_in}</span><span class="dim">signed in on one</span></div>
    </div>
    <div class="row">
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>Where their clocks are</b>
        <span class="dim">timezone</span></div>${bar(an.by_tz, an.devices)}</div>
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>Language</b></div>${bar(an.by_lang, an.devices)}</div>
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>Browser</b></div>${bar(an.by_browser, an.devices)}</div>
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>System</b></div>${bar(an.by_os, an.devices)}</div>
    </div>
    <div class="row">
      <div class="card" style="flex:2;min-width:min(300px,100%)"><div class="card-head"><b>By day</b><span class="dim">devices · page loads</span></div>
        <div class="dv-days">${(an.by_day || []).map((d) => {
          const mx = Math.max(1, ...an.by_day.map((x) => x.devices));
          return `<div class="dv-day" title="${d.day}: ${d.devices} devices, ${d.hits} loads"><i style="height:${Math.round(d.devices / mx * 100)}%"></i><small>${d.day.slice(5)}</small></div>`; }).join("")
          || '<span class="dim">nothing yet</span>'}</div></div>
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>Pages</b></div>
        ${(an.paths || []).map((p) => `<div class="dv-bar"><span class="dv-k" title="${esc(p.path)}">${esc(p.path)}</span><b>${p.hits}</b></div>`).join("") || '<span class="dim">nothing yet</span>'}</div>
      <div class="card" style="flex:1;min-width:min(240px,100%)"><div class="card-head"><b>Addresses</b><span class="dim">devices · loads</span></div>
        ${(an.ips || []).map((p) => `<div class="dv-bar"><span class="dv-k"><code>${esc(p.ip)}</code></span><b>${p.devices} · ${p.hits}</b></div>`).join("") || '<span class="dim">nothing yet</span>'}</div>
    </div>`}
    <h3 style="margin-top:18px">Every device <span class="dim" style="font-weight:400">· last ${days} days</span>
      <input id="dv-q" class="dv-q" placeholder="find an address, a browser, a person" value="${esc(S.devQ || "")}"></h3>
    ${devs.length ? `<div class="card"><table>
      <thead><tr><th>last seen</th><th>who</th><th>browser</th><th>where (clock)</th><th>screen</th><th>address</th><th>visits</th></tr></thead>
      <tbody>${devs.map((d) => `<tr>
        <td class="dim" title="first ${new Date(d.first_seen * 1000).toLocaleString()}">${ago(d.last_seen)}</td>
        <td>${d.who ? `<b>${esc(d.who)}</b>` : `<span class="dim">${d.visitor_id ? "visitor" : "no script"}</span>`}
          <div class="dim">${esc(d.surface)}</div></td>
        <td>${esc(d.browser)} <span class="dim">on ${esc(d.os)}${d.touch ? " · touch" : ""}</span>
          <div class="dim" title="${esc(d.ua)}" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.ua)}</div></td>
        <td>${esc(d.tz || "—")}<div class="dim">${esc(d.lang || "")}</div></td>
        <td class="dim">${esc(d.screen || "—")}</td>
        <td><code>${esc(d.ip)}</code>${d.ips.length > 1 ? `<div class="dim" title="${esc(d.ips.map((x) => x.ip).join(", "))}">+${d.ips.length - 1} more</div>` : ""}</td>
        <td><b>${d.hits}</b> <span class="dim">on ${d.days} day${d.days === 1 ? "" : "s"}</span></td>
      </tr>`).join("")}</tbody></table></div>`
      : `<p class="dim">No devices in that window${S.devQ ? " matching that" : ""}.</p>`}`;
  view().querySelectorAll("[data-dvdays]").forEach((b) => b.onclick = () => { S.devDays = +b.dataset.dvdays; renderDevices(); });
  const q = $("#dv-q");
  if (q) { let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.devQ = q.value; renderDevices(); }, 350); }; }
}
