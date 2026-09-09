// ---------- delivery apps ----------
/* One menu, and the apps have copies. Tick what is on the menu, push it,
   and their orders land in the queue like a counter order. */
async function renderMarketplaces() {
  const d = await api("/api/marketplaces");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Delivery apps</h2>
        <p class="dim">Your products, with their prices, as the menu on Uber Eats
          and DoorDash — pushed from here and pushed again when a price changes.
          Their orders come in by SKU and join the queue.</p></div>
    </div>
    ${d.providers.map((p) => `<div class="card" data-mkp="${p.name}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.label)}</b>
          <span class="dim">${p.connected ? esc(p.account || "connected") : "not connected — set it up below"}</span></div>
        ${p.connected ? `<span class="pill ${p.open ? "ok" : "warn"}">${p.open ? "taking orders" : "paused"}</span>
          <button class="btn alt sm" data-mkpopen="${p.name}" data-to="${p.open ? 0 : 1}">${p.open ? "Pause the store" : "Resume"}</button>
          <button class="btn sm" data-mkppush="${p.name}">Push the menu</button>` : ""}
      </div>
      ${p.connected ? `
        <p class="dim">Orders arrive at <code>${esc(p.inbound_url)}</code> — paste that as the
          order webhook in the partner portal. ${p.inbound_url.includes("?key=") ? "" : "Set up the address on the card below to get a key."}</p>
        <b>On the menu</b> <span class="dim">(${p.menu.filter((m) => m.listed).length} of ${p.menu.length})</span>
        <div class="perm-grid">${p.menu.map((m) => `<label class="perm">
          <input type="checkbox" data-mkpitem="${p.name}" value="${m.id}" ${m.listed ? "checked" : ""}>
          <span><b>${esc(m.name)}</b><small>${esc(m.sku)} · ${money(m.price_cents)}${m.category ? " · " + esc(m.category) : ""}</small></span>
        </label>`).join("") || '<p class="dim">No active products to list.</p>'}</div>
        <div class="chips" style="margin-top:8px"><button class="btn alt sm" data-mkpsave="${p.name}">Save the menu</button></div>
        ${p.orders.length ? `<h3>Orders from ${esc(p.label)}</h3><div class="tablewrap"><table>
          <thead><tr><th>theirs</th><th>ours</th><th>state</th><th>when</th></tr></thead>
          <tbody>${p.orders.map((o) => `<tr><td class="dim">${esc(o.external_id)}</td>
            <td>${o.order_id ? "#" + o.order_id : "—"}</td>
            <td><span class="pill ${o.state === "accepted" ? "ok" : "bad"}">${esc(o.state)}</span>
              ${o.detail ? `<span class="dim">${esc(o.detail)}</span>` : ""}</td>
            <td class="dim">${fmtAgo(o.created_at)}</td></tr>`).join("")}</tbody></table></div>` : ""}` : ""}
    </div>`).join("")}
    <h3>Connections</h3>
    <p class="dim">Both are partner APIs: the platform approves the integration
      and issues the credential. Until then the cards say not connected, and
      that is the truth of it.</p>
    <div id="mkp-cxn"></div>`;

  view().querySelectorAll("[data-mkpsave]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.mkpsave;
    const ids = [...view().querySelectorAll(`[data-mkpitem="${name}"]:checked`)].map((c) => +c.value);
    try { const r = await api(`/api/marketplaces/${name}/menu`, { body: { product_ids: ids } }); toast(`${r.listed} on the menu`); renderMarketplaces(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-mkppush]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try { const r = await api(`/api/marketplaces/${b.dataset.mkppush}/push`, { method: "POST" }); toast(`${r.items} item(s) pushed`); renderMarketplaces(); }
    catch (e) { toast(e.message); } finally { b.disabled = false; }
  });
  view().querySelectorAll("[data-mkpopen]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/marketplaces/${b.dataset.mkpopen}/status`, { body: { open: b.dataset.to === "1" } }); renderMarketplaces(); }
    catch (e) { toast(e.message); }
  });
  connectionCards(["ubereats", "doordash"], renderMarketplaces, $("#mkp-cxn"));
}
