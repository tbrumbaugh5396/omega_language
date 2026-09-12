// ---------- connections that live on a working screen ----------
/* The ad platforms, the job boards, the delivery apps, the listings and
   the forms are all providers in the same registry as Slack, and the All
   connections page lists them. But a person setting up TikTok is on the
   Advertising screen, so the card is drawn THERE, from the same provider
   declaration, by this one helper. One card shape for thirty providers:
   status, the form to connect, the settings a connection needs after it
   exists, the key an inbound one issues, and Test / Disconnect. */
async function connectionCards(names, refresh, box) {
  if (!box) return null;
  const d = await api("/api/admin/integrations").catch(() => null);
  if (!d) {
    box.innerHTML = `<p class="dim">Connections are set up by an admin.</p>`;
    return null;
  }
  const ps = names.map((n) => d.providers.find((p) => p.name === n)).filter(Boolean);
  box.innerHTML = ps.map((p) => {
    const inbound = p.auth === "inbound" || p.inbound;
    const state = p.connected
      ? `<span class="pill ok">connected${p.account ? " · " + esc(p.account) : ""}</span>`
      : (p.auth === "inbound"
          ? (p.inbound_ready ? `<span class="pill ok">listening · ${p.received} received</span>`
                             : '<span class="pill">not set up</span>')
          : '<span class="pill">not connected</span>');
    return `<div class="card intg" data-cxn="${p.name}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.label)}</b>
          <span class="dim">${esc(p.blurb)}</span></div>
        ${state}
        ${p.connected && p.auth !== "none" ? `<button class="btn alt sm" data-cxtest="${p.name}">Test</button>` : ""}
        ${(p.connected && p.auth !== "none") || (p.auth === "inbound" && p.inbound_ready)
          ? `<button class="btn alt sm" data-cxoff="${p.name}">${
              p.auth === "inbound" ? "New key" : "Disconnect"}</button>` : ""}
      </div>
      <p class="dim intg-does">${esc(p.does)}</p>
      ${p.events.length ? `<p class="dim intg-when">Fires when ${p.events.map(esc).join(", ")}.</p>` : ""}
      ${p.connected || p.auth === "inbound" ? "" : `<div class="intg-form" id="f-${p.name}"></div>`}
      ${inbound ? `<div class="intg-form" data-cxin="${p.name}">
        <button class="btn${p.auth === "inbound" ? "" : " alt"} sm" data-cxkey="${p.name}">${
          p.inbound_ready ? "Show the address and key" : "Set up the address"}</button>
        <div data-cxkeyout="${p.name}"></div></div>` : ""}
      ${p.connected && p.settings_fields.length ? `<div class="intg-form" data-cxset="${p.name}">
        ${p.settings_fields.map((f) => `<label class="f">${esc(f.label)}
          ${f.hint ? `<span class="dim">${esc(f.hint)}</span>` : ""}
          <input data-cxf="${f.k}" ${f.secret ? 'type="password"' : ""} autocomplete="off"
            value="${f.secret ? "" : esc(p.settings[f.k] || "")}"
            placeholder="${f.secret && p.settings_have.includes(f.k) ? "saved — paste to replace" : ""}"></label>`).join("")}
        <button class="btn alt sm" data-cxsave="${p.name}">Save settings</button></div>` : ""}
    </div>`;
  }).join("") || '<p class="dim">Nothing to connect here.</p>';

  ps.forEach((p) => {
    if (p.auth !== "inbound" && !p.connected) drawForm(p, refresh);
  });
  box.querySelectorAll("[data-cxkey]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.cxkey;
    try {
      const r = await api(`/api/admin/integrations/${name}/inbound-key`, { method: "POST" });
      box.querySelector(`[data-cxkeyout="${name}"]`).innerHTML = `<div class="card" style="margin-top:10px">
        <label>POST to</label><input value="${esc(r.url)}" readonly>
        <label>With header <code>X-API-Key</code> (or <code>?key=</code> on the URL)</label>
        <input value="${esc(r.key)}" readonly>
        <p class="dim">The key is the whole of the security on that address, so
          treat it like a password. Issue a new one and the old stops at once.</p></div>`;
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-cxsave]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.cxsave;
    const fields = {};
    box.querySelectorAll(`[data-cxset="${name}"] [data-cxf]`).forEach((i) => {
      if (i.value.trim()) fields[i.dataset.cxf] = i.value.trim();
    });
    try {
      await api(`/api/admin/integrations/${name}/settings`, { body: { fields } });
      toast("saved");
      refresh();
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-cxtest]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api(`/api/admin/integrations/${b.dataset.cxtest}/test`, { method: "POST" });
      toast(`Still working — ${r.detail}`);
    } catch (e) { toast(e.message); } finally { b.disabled = false; }
  });
  box.querySelectorAll("[data-cxoff]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.cxoff;
    const p = ps.find((x) => x.name === name);
    if (p.auth === "inbound") {
      if (!confirm("Issue a new key? Whatever uses the old one stops until it is updated.")) return;
      await api(`/api/admin/integrations/${name}/inbound-key?rotate=1`, { method: "POST" });
      toast("New key issued");
    } else {
      if (!confirm(`Disconnect ${p.label}?`)) return;
      await api(`/api/admin/integrations/${name}`, { method: "DELETE" });
    }
    refresh();
  });
  return d;
}

const cxnNum = (n) => (n || 0).toLocaleString();

// ---------- advertising ----------
/* One ledger for nine platforms. Read, never written: nothing here buys
   media. What it does is put the month's spend in one column, and file
   it as an expense so the tax summary already knows. */
async function renderAds() {
  const d = await api("/api/ads");
  const tot = d.platforms.reduce((a, p) => ({
    spend: a.spend + p.totals.spend_cents, imp: a.imp + p.totals.impressions,
    clicks: a.clicks + p.totals.clicks, results: a.results + p.totals.results }),
    { spend: 0, imp: 0, clicks: 0, results: 0 });
  const admin = S.user.is_admin || S.user.role === "admin" || S.user.role === "owner";
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Advertising</h2>
        <p class="dim">Every platform's spend and what it returned, in one
          column. Pulled from the ones that have an API; typed for the ones
          that don't. Window: ${esc(d.window.from)} to ${esc(d.window.to)}.</p></div>
      <div class="top-actions">
        ${admin ? '<button class="btn" id="adl-manual">Log spend by hand</button>' : ""}
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Spend</span><b>${money(tot.spend)}</b></div>
      <div class="card tile"><span class="dim">Impressions</span><b>${cxnNum(tot.imp)}</b></div>
      <div class="card tile"><span class="dim">Clicks</span><b>${cxnNum(tot.clicks)}</b>
        <span class="dim">${tot.imp ? (tot.clicks * 100 / tot.imp).toFixed(2) + "% CTR" : ""}</span></div>
      <div class="card tile"><span class="dim">Results</span><b>${cxnNum(tot.results)}</b>
        <span class="dim">${tot.clicks ? money(Math.round(tot.spend / tot.clicks)) + " per click" : ""}</span></div>
    </div>
    <h3>By platform</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>platform</th><th></th><th>campaigns</th><th>spend</th>
        <th>impressions</th><th>clicks</th><th>results</th><th>pulled</th><th></th></tr></thead>
      <tbody>${d.platforms.map((p) => `<tr>
        <td><b>${esc(p.label)}</b>${p.note ? `<br><span class="dim">${esc(p.note)}</span>` : ""}</td>
        <td>${p.provider ? (p.connected ? '<span class="pill ok">connected</span>'
          : '<span class="pill">not connected</span>') : '<span class="pill">typed</span>'}</td>
        <td>${p.totals.campaigns}</td><td>${money(p.totals.spend_cents)}</td>
        <td>${cxnNum(p.totals.impressions)}</td><td>${cxnNum(p.totals.clicks)}</td>
        <td>${cxnNum(p.totals.results)}</td>
        <td class="dim">${p.totals.synced_at ? fmtAgo(p.totals.synced_at) : "never"}</td>
        <td class="chips">${admin && p.connected ? `<button class="btn alt sm" data-adpull="${p.key}">Pull now</button>` : ""}
          ${admin && p.totals.spend_cents ? `<button class="btn alt sm" data-adexp="${p.key}">File as expense</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>
    <h3>Campaigns</h3>
    ${d.campaigns.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>campaign</th><th>platform</th><th>status</th><th>spend</th>
        <th>impressions</th><th>clicks</th><th>CTR</th><th>CPC</th><th>results</th><th></th></tr></thead>
      <tbody>${d.campaigns.map((c) => `<tr>
        <td>${esc(c.name)}${c.note ? `<br><span class="dim">${esc(c.note)}</span>` : ""}</td>
        <td class="dim">${esc((d.platforms.find((p) => p.key === c.platform) || {}).label || c.platform)}${
          c.source === "manual" ? " · typed" : ""}</td>
        <td><span class="pill ${/active|enabled|running/.test(c.status) ? "ok" : ""}">${esc(c.status || "—")}</span></td>
        <td>${money(c.spend_cents)}</td><td>${cxnNum(c.impressions)}</td><td>${cxnNum(c.clicks)}</td>
        <td class="dim">${(c.ctr_bps / 100).toFixed(2)}%</td><td class="dim">${c.clicks ? money(c.cpc_cents) : "—"}</td>
        <td>${cxnNum(c.results)}</td>
        <td class="chips">${admin && c.source === "manual" ? `<button class="btn alt sm" data-adedit="${c.id}">Edit</button>` : ""}
          ${admin ? `<button class="btn alt sm" data-addel="${c.id}">Remove</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("megaphone", "No campaigns in the ledger",
          "Connect a platform and pull, or log what you spent by hand.")}
    ${admin ? `<h3>Platforms</h3>
    <p class="dim">Each is read-only: it brings numbers in and sends nothing
      out. Google Ads and Meta need an app registered with them first; the
      others take a token. Twitch has no API for this and is typed.</p>
    <div id="adl-cxn"></div>` : ""}`;

  const manualForm = (c) => {
    modal(`<h3>${c ? "Edit" : "Log"} spend</h3>
      <div class="row2">
        <div><label>Platform</label><select id="adl-plat">${d.platforms.map((p) =>
          `<option value="${p.key}" ${c && c.platform === p.key ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></div>
        <div><label>Campaign</label><input id="adl-name" value="${esc(c ? c.name : "")}" placeholder="Spring flyer run"></div>
      </div>
      <div class="row2">
        <div><label>Spend ($)</label><input id="adl-spend" type="number" step="0.01" min="0" value="${c ? (c.spend_cents / 100).toFixed(2) : ""}"></div>
        <div><label>Results</label><input id="adl-res" type="number" min="0" value="${c ? c.results : 0}"></div>
      </div>
      <div class="row2">
        <div><label>Impressions</label><input id="adl-imp" type="number" min="0" value="${c ? c.impressions : 0}"></div>
        <div><label>Clicks</label><input id="adl-clk" type="number" min="0" value="${c ? c.clicks : 0}"></div>
      </div>
      <div class="row2">
        <div><label>From</label><input id="adl-from" type="date" value="${esc(c ? c.window_from : d.window.from)}"></div>
        <div><label>To</label><input id="adl-to" type="date" value="${esc(c ? c.window_to : d.window.to)}"></div>
      </div>
      <label>Note</label><input id="adl-note" value="${esc(c ? c.note : "")}">
      <p><button class="btn" id="adl-save">Save</button></p>`);
    $("#adl-save").onclick = async () => {
      try {
        await api("/api/ads/manual", { body: {
          id: c ? c.id : 0, platform: $("#adl-plat").value, name: $("#adl-name").value,
          spend_cents: Math.round(parseFloat($("#adl-spend").value || 0) * 100),
          results: +$("#adl-res").value || 0, impressions: +$("#adl-imp").value || 0,
          clicks: +$("#adl-clk").value || 0, window_from: $("#adl-from").value,
          window_to: $("#adl-to").value, note: $("#adl-note").value } });
        closeModal(); renderAds();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#adl-manual")) $("#adl-manual").onclick = () => manualForm(null);
  view().querySelectorAll("[data-adedit]").forEach((b) => b.onclick = () =>
    manualForm(d.campaigns.find((c) => c.id === +b.dataset.adedit)));
  view().querySelectorAll("[data-addel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this row from the ledger?")) return;
    await api(`/api/ads/${b.dataset.addel}`, { method: "DELETE" });
    renderAds();
  });
  view().querySelectorAll("[data-adpull]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api(`/api/ads/${b.dataset.adpull}/pull`, { method: "POST" });
      toast(`${r.pulled} campaign(s) pulled`); renderAds();
    } catch (e) { toast(e.message); } finally { b.disabled = false; }
  });
  view().querySelectorAll("[data-adexp]").forEach((b) => b.onclick = async () => {
    if (!confirm("File this platform's spend as an approved advertising expense?")) return;
    try {
      const r = await api(`/api/ads/${b.dataset.adexp}/expense`, { method: "POST" });
      toast(`${money(r.amount_cents)} filed under Advertising`);
    } catch (e) { toast(e.message); }
  });
  connectionCards(d.platforms.filter((p) => p.provider).map((p) => p.provider),
                  renderAds, $("#adl-cxn"));
}

// ---------- listings and reviews ----------
async function renderListings() {
  const d = await api("/api/listings");
  const p = d.profile;
  const admin = S.user.is_admin || S.user.role === "admin" || S.user.role === "owner";
  const g = d.connections.find((c) => c.name === "google_business") || {};
  const y = d.connections.find((c) => c.name === "yelp") || {};
  const stars = (n) => `${n} of 5`;
  const dayLabel = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Listings & reviews</h2>
        <p class="dim">What the map says about you, and what people say under
          it. Edit the profile here and push it to Google; pull the reviews
          in and answer them here.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="lst-ask">Ask a customer for a review</button>
        ${admin ? '<button class="btn" id="lst-save">Save profile</button>' : ""}
      </div>
    </div>
    <div class="tiles">
      ${["google_business", "yelp"].map((k) => {
        const s = d.summary[k];
        return `<div class="card tile"><span class="dim">${k === "yelp" ? "Yelp" : "Google"}</span>
          <b>${s ? s.avg.toFixed(1) : "—"}</b>
          <span class="dim">${s ? `${s.n} review${s.n === 1 ? "" : "s"}${s.unanswered ? ` · ${s.unanswered} unanswered` : ""}` : "nothing pulled yet"}</span></div>`;
      }).join("")}
      <div class="card tile"><span class="dim">Asked for a review</span><b>${d.requests.length}</b>
        <span class="dim">${d.review_link ? "link ready" : "no link yet"}</span></div>
    </div>
    <h3>The profile</h3>
    <div class="card">
      <div class="row2">
        <div><label>Name</label><input id="lst-name" value="${esc(p.name)}"></div>
        <div><label>Category</label><input id="lst-cat" value="${esc(p.category)}" placeholder="Language school"></div>
      </div>
      <div class="row2">
        <div><label>Phone</label><input id="lst-phone" value="${esc(p.phone)}"></div>
        <div><label>Website</label><input id="lst-web" value="${esc(p.website)}"></div>
      </div>
      <label>Address</label><input id="lst-addr" value="${esc(p.address)}">
      <div class="row2">
        <div><label>City</label><input id="lst-city" value="${esc(p.city)}"></div>
        <div><label>Region / state</label><input id="lst-region" value="${esc(p.region)}"></div>
      </div>
      <div class="row2">
        <div><label>Postal code</label><input id="lst-postal" value="${esc(p.postal)}"></div>
        <div><label>Country</label><input id="lst-country" value="${esc(p.country)}" placeholder="US"></div>
      </div>
      <label>Description <span class="dim">(Google shows up to 750 characters)</span></label>
      <textarea id="lst-desc" rows="3">${esc(p.description)}</textarea>
      <div class="row2">
        <div><label>Google Maps link</label><input id="lst-maps" value="${esc(p.maps_url)}" placeholder="https://maps.app.goo.gl/…"></div>
        <div><label>Yelp page</label><input id="lst-yelp" value="${esc(p.yelp_url)}"></div>
      </div>
      <label>Hours <span class="dim">(blank = closed; two spans a day as 09:00-12:00, 13:00-17:00)</span></label>
      <div class="tablewrap"><table><tbody>${d.days.map((k) => `<tr><td>${dayLabel[k]}</td>
        <td><input data-lsthour="${k}" value="${esc((p.hours[k] || []).map((s) => s.join("-")).join(", "))}"
          placeholder="closed"></td></tr>`).join("")}</tbody></table></div>
      <div class="chips" style="margin-top:10px">
        ${admin && g.connected ? `<button class="btn alt sm" id="lst-gpull">Pull from Google</button>
          <button class="btn alt sm" id="lst-gpush">Push to Google</button>` : ""}
        ${admin && y.connected ? `<button class="btn alt sm" id="lst-ypull">Compare with Yelp</button>` : ""}
      </div>
      ${d.yelp ? `<p class="dim" style="margin-top:8px">Yelp has: <b>${esc(d.yelp.name)}</b>,
        ${esc(d.yelp.phone)}, ${esc(d.yelp.address)} — rated ${d.yelp.rating} from
        ${d.yelp.review_count} reviews. Yelp takes no edits by API; change it on
        <a href="${esc(d.yelp.url)}" target="_blank" rel="noopener">the page</a>.</p>` : ""}
    </div>
    <h3>Reviews</h3>
    <div class="chips" style="margin-bottom:8px">
      ${admin && g.connected ? '<button class="btn alt sm" id="lst-grev">Pull Google reviews</button>' : ""}
      ${admin && y.connected ? '<button class="btn alt sm" id="lst-yrev">Pull Yelp reviews</button>' : ""}
    </div>
    ${d.reviews.length ? d.reviews.map((r) => `<div class="card" data-review="${r.id}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(r.author)}</b>
          <span class="dim">${stars(r.rating)} · ${r.provider === "yelp" ? "Yelp" : "Google"} · ${fmtDate(r.at)}</span></div>
        ${r.reply ? '<span class="pill ok">answered</span>'
          : r.provider === "yelp" ? `<a class="btn alt sm" href="${esc(r.url)}" target="_blank" rel="noopener">Answer on Yelp</a>`
          : admin ? `<button class="btn alt sm" data-lstreply="${r.id}">Reply</button>` : '<span class="pill warn">unanswered</span>'}
      </div>
      <p>${esc(r.body)}</p>
      ${r.reply ? `<p class="dim"><b>You:</b> ${esc(r.reply)}</p>` : ""}
      <div data-lstreplybox="${r.id}"></div>
    </div>`).join("")
      : emptyState("pin", "No reviews pulled yet",
          "Connect Google Business Profile or Yelp below and pull them in.")}
    ${d.requests.length ? `<h3>Asked</h3><div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>when</th><th>sent</th></tr></thead>
      <tbody>${d.requests.map((q) => `<tr><td>${esc(q.to_name || q.to_email)}</td>
        <td class="dim">${fmtDate(q.sent_at)}</td><td class="dim">${esc(q.status || "")}</td></tr>`).join("")}</tbody>
      </table></div></div>` : ""}
    ${admin ? `<h3>Connections</h3><div id="lst-cxn"></div>
      <div id="lst-glocs"></div>` : ""}`;

  const readProfile = () => {
    const hours = {};
    view().querySelectorAll("[data-lsthour]").forEach((i) => {
      const spans = i.value.split(",").map((s) => s.trim()).filter(Boolean)
        .map((s) => s.split("-").map((x) => x.trim())).filter((s) => s.length === 2);
      if (spans.length) hours[i.dataset.lsthour] = spans;
    });
    return { name: $("#lst-name").value, category: $("#lst-cat").value,
      phone: $("#lst-phone").value, website: $("#lst-web").value,
      address: $("#lst-addr").value, city: $("#lst-city").value,
      region: $("#lst-region").value, postal: $("#lst-postal").value,
      country: $("#lst-country").value, description: $("#lst-desc").value,
      maps_url: $("#lst-maps").value, yelp_url: $("#lst-yelp").value, hours };
  };
  if ($("#lst-save")) $("#lst-save").onclick = async () => {
    try { await api("/api/listings/profile", { body: readProfile() }); toast("saved"); renderListings(); }
    catch (e) { toast(e.message); }
  };
  const post = async (path, after) => {
    try { const r = await api(path, { method: "POST" }); toast(after(r)); renderListings(); }
    catch (e) { toast(e.message); }
  };
  if ($("#lst-gpull")) $("#lst-gpull").onclick = () =>
    post("/api/listings/google_business/pull", () => "pulled from Google");
  if ($("#lst-gpush")) $("#lst-gpush").onclick = () =>
    post("/api/listings/google_business/push", () => "pushed to Google");
  if ($("#lst-ypull")) $("#lst-ypull").onclick = () =>
    post("/api/listings/yelp/pull", (r) => `Yelp has ${r.name}`);
  if ($("#lst-grev")) $("#lst-grev").onclick = () =>
    post("/api/listings/google_business/reviews/pull", (r) => `${r.pulled} Google review(s)`);
  if ($("#lst-yrev")) $("#lst-yrev").onclick = () =>
    post("/api/listings/yelp/reviews/pull", (r) => `${r.pulled} Yelp review(s)`);
  view().querySelectorAll("[data-lstreply]").forEach((b) => b.onclick = () => {
    const id = b.dataset.lstreply;
    const box = view().querySelector(`[data-lstreplybox="${id}"]`);
    box.innerHTML = `<textarea data-lsttext rows="3" placeholder="Thank you for coming in…"></textarea>
      <div class="chips" style="margin-top:6px"><button class="btn sm" data-lstsend="${id}">Post reply</button></div>`;
    box.querySelector("[data-lstsend]").onclick = async () => {
      try {
        await api(`/api/listings/reviews/${id}/reply`, { body: { text: box.querySelector("[data-lsttext]").value } });
        toast("replied on Google"); renderListings();
      } catch (e) { toast(e.message); }
    };
  });
  $("#lst-ask").onclick = () => {
    modal(`<h3>Ask for a review</h3>
      <p class="dim">${d.review_link ? `They get a short note with this link: <code>${esc(d.review_link)}</code>`
        : "Set a place id on the Google connection, or a Maps link on the profile, first."}</p>
      <div class="row2">
        <div><label>Name</label><input id="lst-askname"></div>
        <div><label>Email</label><input id="lst-askmail" type="email"></div>
      </div>
      <p><button class="btn" id="lst-asksend" ${d.review_link ? "" : "disabled"}>Send</button></p>`);
    $("#lst-asksend").onclick = async () => {
      try {
        const r = await api("/api/listings/ask", { body: { email: $("#lst-askmail").value, name: $("#lst-askname").value } });
        closeModal(); toast(`sent (${r.status || "queued"})`); renderListings();
      } catch (e) { toast(e.message); }
    };
  };
  connectionCards(["google_business", "yelp"], renderListings, $("#lst-cxn")).then((dd) => {
    if (!dd || !g.connected || !$("#lst-glocs")) return;
    $("#lst-glocs").innerHTML = `<div class="card"><b>Which Google location is this business?</b>
      <p class="dim">${g.settings && g.settings.location ? "Now: " + esc(g.settings.location) : "Not chosen yet."}</p>
      <button class="btn alt sm" id="lst-glist">List my locations</button><div id="lst-glocout"></div></div>`;
    $("#lst-glist").onclick = async () => {
      try {
        const r = await api("/api/listings/google_business/locations");
        $("#lst-glocout").innerHTML = r.locations.length ? `<div class="chips" style="margin-top:8px">${r.locations.map((l) =>
          `<button class="btn alt sm" data-lstpick="${esc(l.name)}" data-acct="${esc(l.account)}">${esc(l.title)} · ${esc(l.where)}</button>`).join("")}</div>`
          : '<p class="dim">No locations came back.</p>';
        $("#lst-glocout").querySelectorAll("[data-lstpick]").forEach((b) => b.onclick = async () => {
          await api("/api/listings/google_business/location", { body: { location: b.dataset.lstpick, account: b.dataset.acct } });
          toast("location set"); renderListings();
        });
      } catch (e) { toast(e.message); }
    };
  });
}
