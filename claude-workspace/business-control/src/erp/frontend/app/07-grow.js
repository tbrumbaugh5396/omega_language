// ---------- promotions & events ----------

async function renderPromos() {
  const isAdmin = S.user && S.user.is_admin;
  const [list, products, net] = await Promise.all([
    isAdmin ? api("/api/admin/promos") : api("/api/promos"),
    api("/api/products"), api("/api/net").catch(() => null)]);
  view().innerHTML = `
    <h2>Promotions & events</h2>
    ${isAdmin ? `<div class="card">
      <form class="inline" id="promo-form">
        <label class="f">type <select id="pm-kind">
          <option value="promo">promo (scannable offer)</option>
          <option value="event">event (in person)</option></select></label>
        <label class="f">name <input id="pm-name" required></label>
        <label class="f">pitch <input id="pm-body" style="min-width:220px"></label>
        <label class="f">product <select id="pm-prod"><option value="">—</option>
          ${products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}
        </select></label>
        <label class="f">% off <input id="pm-disc" type="number" value="0"
          style="width:70px"></label>
        <label class="f">region <select id="pm-region"><option value=""></option>
          ${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select></label>
        <label class="f">city <input id="pm-city" style="width:110px"></label>
        <label class="f">when <input id="pm-starts" type="datetime-local"></label>
        <label class="f">video URL <input id="pm-video" style="min-width:180px"
          placeholder="YouTube / stream / .mp4"></label>
        <button class="btn">Create</button>
      </form>
      <div class="dim" style="margin-top:6px">Each promo gets a QR — put it on
        shelf talkers, packaging, or the event table. Scans land on a branded
        page with an "install the app" pipeline and are counted below.</div>
    </div>` : ""}
    ${list.map((p) => `
      <div class="card">
        <b>${esc(p.name)}</b>
        <span class="pill ${p.kind === "event" ? "warn" : "ok"}">${p.kind}</span>
        ${p.active ? "" : '<span class="pill bad">off</span>'}
        ${p.discount_pct ? `<span class="pill ok">${p.discount_pct}% off</span>` : ""}
        <span class="dim">· ${esc(p.city)} ${esc(p.region)}
          ${p.starts ? "· " + esc(p.starts).replace("T", " ") : ""}</span>
        ${isAdmin ? `<span style="float:right">
          <span class="pill">${p.scans} scan(s) · ${p.unique_scans} unique</span>
          ${p.kind === "event" ? `<span class="pill">${p.staff_hours}h staffed</span>` : ""}
          ${p.active ? `<button class="btn alt" data-pm-blast="${p.id}"
            title="email this promo to every customer">Email blast</button>` : ""}
          <button class="btn alt" data-pm-toggle="${p.id}">
            ${p.active ? "turn off" : "turn on"}</button>
          ${rowActions("promo", p)}</span>` : ""}
        ${p.body ? `<div style="margin:8px 0">${esc(p.body)}</div>` : ""}
        <div class="row">
          ${net ? `<div>${qrImg(`${net.lan_url}/?promo=${p.id}`, 120)}
            <div class="dim" style="font-size:12px">${esc(net.lan_url)}/?promo=${p.id}</div></div>` : ""}
          ${p.video_url ? `<div style="flex:1;min-width:240px">${videoEmbed(p.video_url)}</div>` : ""}
        </div>
        ${p.kind === "event" ? `<div class="dim" style="margin-top:6px">
          Employees: pick this event on the Time Clock when you punch in.</div>` : ""}
      </div>`).join("")}
    ${list.length ? "" : '<div class="card dim">no promotions yet</div>'}`;
  if ($("#promo-form")) $("#promo-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/promos", { body: {
      kind: $("#pm-kind").value, name: $("#pm-name").value,
      body: $("#pm-body").value,
      product_id: $("#pm-prod").value ? +$("#pm-prod").value : null,
      discount_pct: +$("#pm-disc").value || 0,
      region: $("#pm-region").value, city: $("#pm-city").value,
      starts: $("#pm-starts").value, video_url: $("#pm-video").value } });
    toast("created — QR is ready below");
    render();
  };
  wireRows({ promo: list }, renderPromos);
  document.querySelectorAll("[data-pm-toggle]").forEach((b) => {
    b.onclick = async () => {
      await api(`/api/admin/promos/${b.dataset.pmToggle}/toggle`, { body: {} });
      render();
    };
  });
  document.querySelectorAll("[data-pm-blast]").forEach((b) => {
    b.onclick = async () => {
      try {
        const r = await api("/api/admin/email/blast",
          { body: { promo_id: +b.dataset.pmBlast } });
        toast(`emailed ${r.sent} of ${r.targeted} customer(s)`
          + (r.already_sent ? ` (${r.already_sent} already had it)` : ""));
      } catch (e) { toast(e.message); }
    };
  });
}

// Public landing page for scanned promo QRs (?promo=<id>).
async function renderPromoLanding() {
  const id = S.promoLanding;
  let p;
  try {
    p = await api(`/api/promos/${id}/scan`,
      { body: { visitor_id: visitorId() } });
  } catch (e) {
    S.promoLanding = null;
    view().innerHTML = `<div class="card">This promotion has ended.
      <button class="btn" id="promo-shop">Browse the shop</button></div>`;
    $("#promo-shop").onclick = () => { S.tab = "shop"; render(); };
    return;
  }
  view().innerHTML = `
    <div class="hero warm">
      <div class="h">${esc(p.name)}</div>
      ${p.discount_pct ? `<span class="pill ok">${p.discount_pct}% off</span>` : ""}
      ${p.body ? `<div style="margin:10px 0">${esc(p.body)}</div>` : ""}
      ${p.product ? `<div style="margin:8px 0"><b>${esc(p.product.name)}</b>
        — ${money(p.product.price_cents)}</div>` : ""}
      <button class="btn" id="promo-shop">Shop now</button>
    </div>
    ${p.video_url ? `<div class="card">${videoEmbed(p.video_url)}</div>` : ""}
    ${p.kind === "event" ? `<div class="card">${opsIcon("pin","inline-ic")} ${esc(p.city)} ·
      ${esc(p.region)} ${p.starts ? "· " + esc(p.starts).replace("T", " ") : ""}</div>` : ""}
    <div class="card"><b>Get the app:</b> on iPhone open the Share menu →
      <b>Add to Home Screen</b>; on Android/desktop Chrome use menu →
      <b>Install app</b>. New drops, rewards, and one-tap reorders live there.</div>`;
  if (p.product) track("view_product", { product_id: p.product.id });
  $("#promo-shop").onclick = () => {
    S.promoLanding = null;
    S.tab = "shop";
    if (p.product) {
      S.cart[p.product.id] = (S.cart[p.product.id] || 0) + 1;
      track("add_to_cart", { product_id: p.product.id });
    }
    render();
  };
}

// ---------- HQ: the owners' map ----------

const REGION_COLORS = { Northeast: "#4a9eda", Southeast: "#35b26b",
  Midwest: "#d4a017", Southwest: "#d0564f", West: "#a06ad4" };

function hqMap(stores) {
  const pts = stores.filter((s) => s.lat != null);
  if (!pts.length) return "";
  return panZoomMap({
    id: "hq-map",
    pins: pts.map((st) => ({
      lat: st.lat, lng: st.lng,
      color: REGION_COLORS[st.region] || "#8b98a5",
      size: st.kind === "distributor_dc" ? 10 : 6,
      label: st.name, sub: st.city })),
  }) + `<div class="map-legend">${Object.entries(REGION_COLORS).map(([r, c]) =>
      `<span><i style="background:${c}"></i>${r}</span>`).join("")}</div>`;
}

function pnlTable(p) {
  const row = (l, v, neg) => `<tr><td>${l}</td>
    <td style="text-align:right">${neg ? "−" : ""}${money(v)}</td></tr>`;
  return `<table>
    ${row("Revenue", p.revenue_cents)}
    ${row(`COGS${p.cogs_measured_pct
      ? ` — ${p.cogs_measured_pct}% from recipes` : ""}`, p.cogs_cents, 1)}
    ${p.cogs_measured_cents ? `<tr class="sub"><td class="dim">from recipes
        and material costs</td>
      <td style="text-align:right" class="dim">−${money(p.cogs_measured_cents)}</td></tr>
      <tr class="sub"><td class="dim">estimated at
        ${p.assumptions.cogs_bps / 100}% on the rest</td>
      <td style="text-align:right" class="dim">−${money(p.cogs_estimated_cents)}</td></tr>`
      : ""}
    ${row("<b>Gross profit</b>", p.gross_cents)}
    ${row("Affiliate commissions", p.commissions_cents, 1)}
    ${row(`Labor (${p.labor_hours}h)`, p.labor_cents, 1)}
    ${p.contractor_cents ? row(`Contractor routes (${p.contractor_routes})`,
      p.contractor_cents, 1) : ""}
    ${row(`Trucking (${p.logistics_km} km)`, p.logistics_cents, 1)}
    <tr><td><b>Net</b></td><td style="text-align:right"
      class="${p.net_cents < 0 ? "low" : ""}"><b>${money(p.net_cents)}</b>
      (${p.margin_pct}%)</td></tr>
  </table>
  <div class="dim" style="font-size:12px;margin-top:6px">${
    p.assumptions.recipes_priced
      ? `${p.assumptions.recipes_priced} product(s) have a priced recipe, so
         their cost is measured rather than assumed. Anything without one
         falls back to ${p.assumptions.cogs_bps / 100}% of revenue — add a
         recipe under Sourcing to replace the guess.`
      : `COGS is an assumption at ${p.assumptions.cogs_bps / 100}% of revenue.
         Give a product a recipe under Sourcing and its real cost is used
         instead.`}
    Wage and per-km cost are assumptions — edit them in data/config.json.</div>`;
}

/* ---------- the fleet: nodes, and who lives on them ----------
   The platform operator's own screen. Capacity is units, not tenants —
   the deck's weights, made clickable — and the two rules that keep the
   bill honest are enforced here as well as on the server: a node with
   room takes the next client, and a node nobody is left on goes away. */
/* Stand a client up — callable from the Platform tab AND from the moment
   the contract gate closes on an engagement page. Fetches the fleet board
   itself when not handed one, and when the client has an engagement, asks
   what size the QUOTE says they are: the operator is offered what was
   sold, not a guess. */
async function standUpClient(slug, eid, name, opts = {}) {
  let f = opts.fleet;
  try { if (!f) f = await api("/api/store/admin/fleet"); }
  catch (err) { toast(err.message); return; }
  let sug = opts.suggestion;
  if (sug === undefined && eid) {
    try { sug = (await api(
      `/api/store/admin/engagements/${eid}/stand-up`)).suggestion; }
    catch { sug = null; }
  }
  const klass = (sug && f.classes[sug.klass]) ? sug.klass : "growing";
  const nodeOptions = (extra) => f.nodes.map((n) =>
    `<option value="${esc(n.id)}">${esc(n.id)} — ${n.free} of ${n.capacity}
      units free</option>`).join("") + (extra || "");

  modal(`<h3>Stand up ${esc(name || slug)}</h3>
    <p class="dim">A tenant of their own: database, config, secrets,
      hostname. Nothing is shared with anyone else's install.</p>
    <div class="row2">
      <div><label>Tenant id <span class="req">required</span></label>
        <input id="t-id" value="${esc(slug || "")}"></div>
      <div><label>Brand</label><input id="t-brand"
        value="${esc(name || "")}"></div>
    </div>
    <label>Hostname</label>
    <input id="t-host" placeholder="acme.localhost"
      value="${slug ? esc(slug) + ".localhost" : ""}">
    ${f.public_suffix ? `<p class="dim" id="t-pubnote">They'll also answer
      publicly at <b id="t-pub"></b> — added automatically, TLS on
      demand.</p>` : ""}
    <div class="row2">
      <div><label>Size</label><select id="t-class">${
        Object.entries(f.classes).map(([k, v]) =>
          `<option value="${k}"${k === klass ? " selected" : ""}>${k}
            — ${v.units || "whole node"} unit${v.units === 1 ? "" : "s"}
            · ${esc(v.note)}</option>`).join("")}</select></div>
      <div><label>Where</label><select id="t-node">${nodeOptions(
        `<option value="new">+ a new node, just for them</option>`)}</select>
      </div>
    </div>
    ${sug ? `<p class="dim">${opsIcon("pen", "btn-ic")} Sized from the
      quote: ${esc(sug.reason)}${sug.shape ? ` · starter layout:
      <b>${esc(sug.shape)}</b>` : ""}</p>` : ""}
    <div id="t-newnode" hidden>
      <div class="row2">
        <div><label>New node id</label>
          <input id="t-nid" placeholder="node-2"
            value="${slug ? "node-" + esc(slug) : ""}"></div>
        <div><label>Size</label><input id="t-nsize" value="4gb"></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" id="t-go">Stand it up</button>
      <button class="btn alt" data-close>Cancel</button>
    </div>`);
  const sel = $("#t-node");
  sel.onchange = () => { $("#t-newnode").hidden = sel.value !== "new"; };
  // The hostname and the new node's name follow the id while nobody has
  // touched them. Opened blank, the old prefill produced ".localhost" —
  // a hostname with no name in front of it, which is not one.
  const follow = (el, make) => {
    if (el.value !== make(slug || "")) el.dataset.touched = "1";
    el.oninput = () => { el.dataset.touched = "1"; };
    return () => { if (!el.dataset.touched) el.value = make($("#t-id").value.trim()); };
  };
  const host = follow($("#t-host"), (v) => v ? `${v}.localhost` : "");
  const nid = follow($("#t-nid"), (v) => v ? `node-${v}` : "");
  const pub = () => { const el = $("#t-pub"); if (el) el.textContent =
    `${$("#t-id").value.trim() || "…"}.${f.public_suffix}`; };
  pub();
  $("#t-id").oninput = () => { host(); nid(); pub(); };
  $("#t-go").onclick = async () => {
    try {
      const out = await api("/api/store/admin/fleet/tenants", {
        body: { id: $("#t-id").value.trim(),
                brand: $("#t-brand").value.trim(),
                hosts: [$("#t-host").value.trim()],
                node: sel.value,
                new_node: ($("#t-nid") || {}).value || "",
                node_size: ($("#t-nsize") || {}).value || "4gb",
                klass: $("#t-class").value,
                engagement_id: eid || 0 } });
      closeModal();
      toast(`${out.tenant} is live on ${out.node}`
        + (out.shipped ? " (shipped to its machine)" : "")
        + (out.public_url ? ` at ${out.public_url}` : "")
        + (out.layout ? ` with a ${out.layout} starter layout` : "")
        + (out.hosting_doc
           ? " — hosting schedule filed in their binder, ready to sign"
           : ""));
      (opts.after || renderFleet)();
    } catch (err) { toast(err.message); }
  };
}

/* Who to ring today. The client dossier answers this one install at a
   time, which is the wrong shape for the question it is usually asked
   in — not "how is Zenjoy doing" but "who is waiting on us". Loaded
   after the board rather than with it: this asks every tenant on every
   node, and a board that waits for the slowest one is a board nobody
   leaves open. */
const PRESSURE_WORDS = {
  asking: ["asking", "turned away and not yet answered"],
  over: ["over", "using more than they are covered for"],
  pinned: ["full", "at the limit; the next busy day is a refusal"],
  spare: ["spare room", "paying for what they have never used"],
  idle: ["idle tablets", "kiosks switched on, billed, and not touched"],
  settled: ["settled", "was turned away, since resolved"],
  unreachable: ["unreachable", "their node did not answer"],
};

async function fleetPressure() {
  const box = $("#fleet-pressure");
  if (!box) return;
  let d;
  try { d = await api("/api/store/admin/fleet/pressure"); }
  catch (e) {
    box.innerHTML = `<b>Limits across the fleet</b>
      <p class="dim">Could not read it: ${esc(e.message)}</p>`;
    return;
  }
  const live = d.rows.filter((r) => r.worst !== "quiet");
  const chip = (n, k) => n
    ? `<span class="pill ${k === "asking" || k === "over" ? "bad" : ""}"
         title="${PRESSURE_WORDS[k][1]}">${n} ${PRESSURE_WORDS[k][0]}</span>`
    : "";
  box.innerHTML = `
    <div class="card-head"><b>Limits across the fleet</b>
      <span class="chips">${chip(d.asking, "asking")}${chip(d.over, "over")}
        ${chip(d.pinned, "pinned")}${chip(d.idle, "idle")}
        ${chip(d.spare, "spare")}${chip(d.unreachable, "unreachable")}</span>
      <span class="dim">${d.upside_cents
        ? "+" + money(d.upside_cents) + " a month if they bought what they "
          + "keep reaching for" : ""}${d.unused_cents
        ? " · " + money(d.unused_cents) + " a month paid for unused room"
        : ""}</span>
    </div>
    ${live.length ? `<div class="sig-rows">${live.map((r) => `
      <div class="doc-line press-line">
        <span class="dl-title"><b>${esc(r.tenant)}</b>
          <span class="dim">${esc(r.node)}</span></span>
        <span class="press-state"><span class="pill ${
          r.worst === "asking" || r.worst === "over" ? "bad"
          : r.worst === "unreachable" ? "warn" : ""}"
          title="${PRESSURE_WORDS[r.worst]
            ? PRESSURE_WORDS[r.worst][1] : ""}">${PRESSURE_WORDS[r.worst]
            ? PRESSURE_WORDS[r.worst][0] : esc(r.worst)}</span></span>
        <span class="press-why dim">${r.why ? esc(r.why)
          : r.lines.map((l) => `${esc(l.kind)}: ${esc(l.verdict)}${
              (l.by_store || []).length > 1
                ? " (" + l.by_store.slice(0, 3).map((w) =>
                    `${esc(w.store)} ${w.peak}`).join(", ") + ")" : ""}`)
              .join(" \u00b7 ")}</span>
        <span class="press-money ${r.at_stake_cents < 0 ? "dim" : ""}">${
          r.at_stake_cents
            ? (r.at_stake_cents > 0 ? "+" : "\u2212")
              + money(Math.abs(r.at_stake_cents)) + "/mo"
            : ""}</span>
        <span class="dl-acts press-acts">
          <button class="btn alt sm" data-plim="${esc(r.tenant)}"
            >Limits</button>
          <button class="btn alt sm" data-prep="${esc(r.tenant)}"
            >Report</button></span>
      </div>`).join("")}</div>`
    : `<p class="dim">Nobody is pressed against a limit and nobody is
       paying for room they never use. This is the quiet answer, not a
       missing one.</p>`}
    <p class="dim">${esc(d.note)}${d.rows.length - live.length
      ? ` ${d.rows.length - live.length} install${
          d.rows.length - live.length === 1 ? "" : "s"} had nothing to
        say.` : ""}</p>`;
  box.querySelectorAll("[data-plim]").forEach((b) =>
    b.onclick = () => limitsForm(b.dataset.plim));
  box.querySelectorAll("[data-prep]").forEach((b) =>
    b.onclick = () => clientDossier(b.dataset.prep));
}

async function renderFleet() {
  const f = await api("/api/store/admin/fleet");
  const bar = (n) => {
    const pct = n.capacity ? Math.round((n.used / n.capacity) * 100) : 0;
    return `<div class="cap-bar" title="${n.used} of ${n.capacity} units">
      <i style="width:${Math.min(100, pct)}%"></i></div>`;
  };
  const nodeCard = (n) => `
    <div class="card node-card">
      <div class="card-head">
        <b>${opsIcon("shield2", "inline-ic")} ${esc(n.id)}</b>
        <span class="dim">${esc(n.size || "")}${n.region
          ? " · " + esc(n.region) : ""} · ${esc(n.provider || "")}</span>
        <span class="dim">${n.used} / ${n.capacity} units${n.free
          ? "" : " · full"}</span>
        ${n.addr ? `<span class="pill ok" title="${esc(n.addr)}">machine
          </span>` : n.id !== "local"
          ? `<span class="pill" title="no address — provision_cmd or the
             Address field turns a booking into a machine">booking</span>`
          : ""}
        ${n.id === "local" ? `<span class="pill">this machine</span>
          ${Object.entries(f.services || {}).map(([s, up]) =>
            `<span class="pill ${up ? "ok" : "bad"}"
               title="node service: shared by every tenant on this machine
               — ${up ? "answering" : "declared but not answering"}">${
              esc(s)}</span>`).join("")}`
          : `${n.addr ? `<button class="btn alt sm" data-njoin="${esc(n.id)}"
               title="the one command that installs the worker on the fresh
               machine">Join cmd</button>
             <button class="btn alt sm" data-ncheck="${esc(n.id)}"
               title="ping the machine: alive, version, tenants">Check</button>
             <button class="btn alt sm" data-nupdate="${esc(n.id)}"
               title="push this box's code and wait for the node to come
               back wearing it">Update</button>` : ""}
             <button class="btn alt sm" data-nodekill="${esc(n.id)}"
               ${n.tenants.length ? "disabled title='move or shut down its "
               + "tenants first'" : ""}>Destroy</button>`}
      </div>
      ${bar(n)}
      <div class="sig-rows">${n.tenants.length ? n.tenants.map((t) => `
        <div class="doc-line fleet-line${
          t.status === "suspended" ? " dl-awaiting" : ""}">
          <span class="dl-title fl-who">
            <b>${esc(t.client ? t.client.name : t.id)}</b>
            <span class="dim">${esc(t.id)}</span>
          </span>
          <span class="fl-tags">
            ${t.provider ? `<span class="pill ok">runs the platform</span>`
              : ""}
            <span class="pill">${esc(t.class)} · ${t.units}u</span>
            ${t.billing ? `<span class="pill bad" title="their ${esc(
              t.billing.plan)} subscription — the card processor says so">
              card ${esc(t.billing.status)}</span>` : ""}
            ${t.status === "suspended"
              ? `<span class="pill warn">suspended</span>` : ""}
          </span>
          <span class="fl-caps">${t.caps ? `<span class="pill"
            title="capabilities granted from their quote">${t.caps}
            caps</span>` : ""}</span>
          <span class="fl-hosts dim">${(t.hosts || []).map(esc)
            .join(" · ")}</span>
          <span class="dl-acts fleet-acts">
            ${t.provider ? "<span></span><span></span><span></span>" : `
            <button class="btn alt sm" data-treport="${esc(t.id)}"
              title="the client dossier: scale, traffic, a live meter per
              capability, and the advisory notes — read from their own
              tables at ask time">Report</button>
            <button class="btn alt sm" data-tactas="${esc(t.id)}"
              title="open their ops app as an admin of THEIR install —
              minted in their own user directory, written to the fleet
              history and their file">Act as admin</button>
            <button class="btn alt sm" data-tlim="${esc(t.id)}"
              title="how many tills, kiosks, locations and seats they
              bought — enforced on their install">Limits</button>
            <button class="btn alt sm" data-tcaps="${esc(t.id)}"
              title="what they're entitled to — grants fulfil capability
              asks, and the site grows the pieces new capabilities earn"
              >Capabilities</button>
            <button class="btn alt sm" data-tmove="${esc(t.id)}"
              title="move this client to another node">Move</button>
            <button class="btn alt sm" data-tstatus="${esc(t.id)}"
              data-to="${t.status === "suspended" ? "active" : "suspended"}"
              title="${t.status === "suspended"
                ? "start answering again" : "stop answering, keep every byte"}"
              >${t.status === "suspended" ? "Resume" : "Suspend"}</button>
            <button class="btn alt sm" data-tkill="${esc(t.id)}"
              data-name="${esc(t.client ? t.client.name : t.id)}"
              title="remove from the fleet — data retired, not deleted"
              >Remove</button>`}
          </span>
        </div>`).join("") : `<p class="dim">Empty — this node will be
          destroyed the moment anything else releases it, or destroy it
          now.</p>`}
      </div>
    </div>`;

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Platform</h2>
        <p class="dim">Nodes, and the businesses living on them. Capacity is
          measured in units — a corner shop and a fifty-location
          distributor are not the same load. A node nobody is left on is
          destroyed automatically.</p></div>
      <span class="chips">
        ${f.backup && f.backup.never
          ? `<span class="pill" title="run scripts/backup.py — the DEPLOY
               runbook has the cron line">no backup yet</span>`
          : f.backup && (f.backup.stale || !f.backup.ok)
          ? `<span class="pill bad" title="${esc((f.backup.failures
               && Object.entries(f.backup.failures).map(([t, r]) =>
               `${t}: ${r}`).join("; ")) || "older than a day")}">backup
               ${f.backup.ok ? "stale" : "FAILED"}</span>`
          : f.backup
          ? `<span class="pill ok" title="${esc(f.backup.archive || "")}">
               backed up ${fmtAgo(f.backup.at)}</span>`
          : ""}
        <button class="btn alt" id="node-new">${opsIcon("shield2","btn-ic")}
          New node</button>
        <button class="btn" id="tenant-new">${opsIcon("users","btn-ic")}
          Stand up a client</button></span>
    </div>
    ${f.unplaced.length ? `<div class="card alert">
      <b>${f.unplaced.length} client${f.unplaced.length === 1 ? "" : "s"}
        with no install</b>
      <p class="dim">On the books, but not running on the platform —
        either they host elsewhere, or they are waiting to be stood up.</p>
      <div class="chips">${f.unplaced.map((c) => `
        <button class="chip" data-standup="${esc(c.slug)}"
          data-eid="${c.engagement_id}" data-name="${esc(c.name)}"
          >${esc(c.name)} — stand up</button>`).join("")}</div>
    </div>` : ""}
    <div class="card" id="fleet-pressure"><b>Limits across the fleet</b>
      <p class="dim">Reading every install…</p></div>
    ${f.nodes.map(nodeCard).join("")}
    ${f.events.length ? `<div class="card"><b>Fleet history</b>
      <div class="log-lines">${f.events.map((e) => `
        <div class="log-line"><span class="dim">${fmtDate(e.at)}</span>
          <b>${esc(e.actor)}</b>
          <span class="dim">${esc(e.what)}${e.detail
            ? " — " + esc(e.detail) : ""}</span></div>`).join("")}
      </div></div>` : ""}`;

  fleetPressure();

  const nn = $("#node-new");
  if (nn) nn.onclick = () => {
    modal(`<h3>New node</h3>
      <p class="dim">Runs the provisioning command from Admin → fleet when
        one is configured; otherwise it books the node here and you build
        it by hand.</p>
      <div class="row2">
        <div><label>Id</label><input id="n-id" placeholder="node-2"></div>
        <div><label>Size</label><input id="n-size" value="4gb"></div>
      </div>
      <div class="row2">
        <div><label>Region</label><input id="n-region"
          placeholder="ash / fsn1"></div>
        <div><label>Capacity (units)</label>
          <input id="n-units" type="number" value="25"></div>
      </div>
      <label>Address <span class="dim">(optional — the node process's
        URL; set it and tenants are actually shipped there)</span></label>
      <input id="n-addr" placeholder="http://10.0.0.2:8860">
      <div class="modal-foot">
        <button class="btn" id="n-go">Provision</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#n-go").onclick = async () => {
      try {
        await api("/api/store/admin/fleet/nodes", {
          body: { id: $("#n-id").value.trim(), size: $("#n-size").value,
                  region: $("#n-region").value,
                  units: +$("#n-units").value || 25,
                  addr: $("#n-addr").value.trim() } });
        closeModal(); toast("node provisioned"); renderFleet();
      } catch (err) { toast(err.message); }
    };
  };
  const tn = $("#tenant-new");
  if (tn) tn.onclick = () => standUpClient("", 0, "", { fleet: f });
  view().querySelectorAll("[data-standup]").forEach((b) => b.onclick = () =>
    standUpClient(b.dataset.standup, +b.dataset.eid, b.dataset.name,
                  { fleet: f }));

  view().querySelectorAll("[data-njoin]").forEach((b) => b.onclick =
    async () => {
      try {
        const j = await api(
          `/api/store/admin/fleet/nodes/${b.dataset.njoin}/join`);
        modal(`<h3>Join ${esc(b.dataset.njoin)} to the fleet</h3>
          <p class="dim">Run this on the fresh machine as root. It fetches
            the app bundle, installs the systemd service with the node's
            identity, and proves the node answers before claiming success.
            The key travels only in this command.</p>
          <textarea id="nj-cmd" readonly rows="4"
            style="width:100%;font-family:monospace;font-size:12px"
            >${esc(j.command)}</textarea>
          <p class="dim">${esc(j.note)}</p>
          <div class="modal-foot">
            <button class="btn" data-close>Done</button></div>`);
        const box = document.getElementById("nj-cmd");
        box.onfocus = () => box.select();
        box.focus();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-ncheck]").forEach((b) => b.onclick =
    async () => {
      try {
        const r = await api(
          `/api/store/admin/fleet/nodes/${b.dataset.ncheck}/check`);
        const svc = Object.entries(r.services || {});
        toast(`${b.dataset.ncheck}: up · code ${r.version}`
          + (r.version === r.current ? " (current)" : ` — provider is on `
            + `${r.current}, push Update`)
          + ` · ${r.tenants} tenant${r.tenants === 1 ? "" : "s"}`
          + (svc.length ? " · services: " + svc.map(([s, up]) =>
              `${s}${up ? "" : " (down)"}`).join(", ") : ""));
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-nupdate]").forEach((b) => b.onclick =
    async () => {
      b.disabled = true;
      b.textContent = "Updating…";
      try {
        const r = await api(
          `/api/store/admin/fleet/nodes/${b.dataset.nupdate}/update`,
          { method: "POST", body: {} });
        toast(r.updated
          ? `${b.dataset.nupdate} restarted on ${r.version}`
          : `${b.dataset.nupdate} was already on ${r.version}`);
      } catch (err) { toast(err.message); }
      renderFleet();
    });
  view().querySelectorAll("[data-nodekill]").forEach((b) => b.onclick =
    async () => {
      if (!confirm(`Destroy ${b.dataset.nodekill}? It carries nothing, so `
        + `nothing is lost — but if it is a real server it is handed back.`))
        return;
      try {
        await api(`/api/store/admin/fleet/nodes/${b.dataset.nodekill}`,
          { method: "DELETE" });
        toast("node destroyed"); renderFleet();
      } catch (err) { toast(err.message); }
    });

  view().querySelectorAll("[data-tstatus]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/store/admin/fleet/tenants/${b.dataset.tstatus}/status`,
          { body: { status: b.dataset.to } });
        toast(b.dataset.to === "suspended"
          ? "suspended — the data is untouched, the hostname says so"
          : "resumed");
        renderFleet();
      } catch (err) { toast(err.message); }
    });

  view().querySelectorAll("[data-treport]").forEach((b) => b.onclick =
    () => clientDossier(b.dataset.treport));
  view().querySelectorAll("[data-tactas]").forEach((b) => b.onclick =
    async () => {
      try {
        const out = await api("/api/store/admin/fleet/tenants/"
          + `${b.dataset.tactas}/act-as`, { body: {} });
        window.open(out.url, "_blank");
        toast(`opened as ${out.account} — logged on the fleet history`);
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-tlim]").forEach((b) => b.onclick = () =>
    limitsForm(b.dataset.tlim));
  view().querySelectorAll("[data-tcaps]").forEach((b) => b.onclick = () =>
    capsEditor(b.dataset.tcaps, { fleet: f }));
  view().querySelectorAll("[data-tmove]").forEach((b) => b.onclick = () => {
    modal(`<h3>Move ${esc(b.dataset.tmove)}</h3>
      <p class="dim">Whichever node it leaves behind empty is destroyed.</p>
      <label>To</label>
      <select id="mv-node">${nodeOptions(
        `<option value="new">+ a new node of its own</option>`)}</select>
      <div class="modal-foot">
        <button class="btn" id="mv-go">Move</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#mv-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/fleet/tenants/${b.dataset.tmove}/move`,
          { body: { node: $("#mv-node").value } });
        closeModal(); toast(`moved to ${out.node}`); renderFleet();
      } catch (err) { toast(err.message); }
    };
  });

  view().querySelectorAll("[data-tkill]").forEach((b) => b.onclick = () => {
    modal(`<h3>Remove ${esc(b.dataset.name)}</h3>
      <p class="dim">Their hostname stops answering and they leave the
        fleet. If they were the last tenant on their node, that node is
        destroyed too.</p>
      <label><input type="checkbox" id="k-keep" checked> Retire their data
        to <code>data/retired/</code> rather than deleting it — a business
        that leaves still owns its records, and the week after a
        cancellation is exactly when someone asks for an export.</label>
      <div class="modal-foot">
        <button class="btn" id="k-go">Remove from the fleet</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#k-go").onclick = async () => {
      try {
        const keep = $("#k-keep").checked ? 1 : 0;
        const out = await api(
          `/api/store/admin/fleet/tenants/${b.dataset.tkill}?keep_data=${keep}`,
          { method: "DELETE" });
        closeModal();
        toast(`${b.dataset.name} removed`
          + (out.nodes_destroyed.length
             ? ` — ${out.nodes_destroyed.join(", ")} destroyed with it` : "")
          + (out.kept ? " · data retired" : ""));
        renderFleet();
      } catch (err) { toast(err.message); }
    };
  });
}

async function renderHQ() {
  const [g, stores, ach] = await Promise.all([
    api("/api/game"), api("/api/stores"), api("/api/achievements")]);
  const earned = ach.filter((a) => a.unlocked_at);
  const c = g.company;
  view().innerHTML = `
    <h2>HQ — run the business</h2>
    <div class="row">
      <div class="card"><div class="dim">company level</div>
        <div class="big lvl-${c.level}">${c.level.toUpperCase()}</div>
        <div class="dim">${Math.round(c.penetration * 100)}% market penetration</div></div>
      <div class="card"><div class="dim">net profit, 30d</div>
        <div class="big ${c.net_30d_cents < 0 ? "low" : ""}">${money(c.net_30d_cents)}</div></div>
      <div class="card"><div class="dim">experiments running</div>
        <div class="big">${c.running_experiments}</div></div>
      <div class="card"><div class="dim">staffing</div>
        ${(g.staffing || []).length ? (g.staffing || []).map((s) =>
          `<div style="font-size:13px">${s.n} × ${esc(JOB_LABEL[s.job] || s.job)}${
            s.employment === "contractor" ? " (1099)" : ""}</div>`).join("")
        : '<div class="dim">no staff yet</div>'}</div>
    </div>
    ${hqMap(stores)}
    <h3>Territories</h3>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">
      ${g.regions.map((r) => {
        const delta = r.revenue_prev_30d_cents
          ? (r.revenue_30d_cents - r.revenue_prev_30d_cents) / r.revenue_prev_30d_cents : 0;
        return `<div class="card">
          <b style="color:${REGION_COLORS[r.region] || "inherit"}">${esc(r.region)}</b>
          <span class="pill lvl-${r.level}">${r.level}</span>
          <div class="penbar"><div style="width:${r.penetration * 100}%"></div></div>
          <div class="dim" style="font-size:13px;margin:6px 0">
            ${r.stores} store(s) · ${r.stocked} stocked · ${r.prospects} prospect(s)<br>
            ${money(r.revenue_30d_cents)} last 30d
            ${r.revenue_prev_30d_cents ? `<span class="${delta < 0 ? "low" : ""}">
              (${delta >= 0 ? "+" : ""}${Math.round(delta * 100)}%)</span>` : ""}
          </div>
          ${r.playbook.map((a) => `<button class="btn alt" style="margin:2px"
            data-pb="${a.action}:${esc(r.region)}">${esc(a.label)}</button>`).join("")}
          ${r.playbook.length ? "" : '<span class="pill ok">territory humming</span>'}
        </div>`;
      }).join("")}
    </div>
    <h3>Achievements — ${earned.length}/${ach.length}</h3>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(190px,1fr))">
      ${ach.map((a) => `<div class="card ach ${a.unlocked_at ? "" : "locked"}">
        <div class="ach-ic">${opsIcon(a.icon || "shield2")}</div>
        <b>${esc(a.name)}</b>
        <div class="dim" style="font-size:12px">${esc(a.desc)}</div>
        ${a.unlocked_at
          ? `<span class="pill ok">unlocked ${timeAgo(a.unlocked_at)}</span>`
          : `<span class="pill">${esc(a.progress)}</span>`}
      </div>`).join("")}
    </div>
    <h3>P&L — last 30 days</h3>
    <div class="card" style="max-width:520px">${pnlTable(g.pnl)}</div>`;
  document.querySelectorAll("[data-pb]").forEach((b) => {
    b.onclick = async () => {
      const [action, region] = b.dataset.pb.split(":");
      try {
        if (action === "experiment") {
          await api("/api/admin/experiments/auto", { body: { goal: "purchase" } });
          toast("A/B experiment launched");
        } else if (action === "auto_route") {
          const made = await api("/api/admin/routes/auto", { body: { region } });
          toast(`coverage route planned — ${made[0].total_km} km`);
        } else if (action === "outreach") {
          S.tab = "outreach";
        }
        render();
      } catch (e) { toast(e.message); }
    };
  });
}


/* ---------- the client dossier ----------
   Which plan fits them? — answered from their own tables, live, in five
   tabs: the overview an advisor reads down the phone, a filterable meter
   per capability, traffic drawn as bars, the node and the billing that
   keep the lights on, and this client's slice of the maintenance record. */
const DSECS = [["overview", "Overview"], ["meters", "Meters"],
               ["traffic", "Traffic"], ["infra", "Node & billing"],
               ["history", "History"]];

async function clientDossier(tid, sec = "overview") {
  let d;
  try {
    d = await api(`/api/store/admin/fleet/tenants/${tid}/report`);
  } catch (err) { return toast(err.message); }
  dossierModal(tid, d, sec);
}

function dossierModal(tid, d, sec) {
  const n = (v) => (v || 0).toLocaleString();
  const day = (ts) => ts ? new Date(ts * 1000).toLocaleDateString() : "?";
  const ni = d.node_info || {};
  const bl = d.billing || {};

  const overview = () => `
    <div class="lrn-rtotals" style="display:flex;gap:26px;flex-wrap:wrap">
      <span><b>${n(d.scale.locations)}</b><span class="dim"> locations</span></span>
      <span><b>${n(d.scale.seats_used)}</b><span class="dim"> seats used</span></span>
      <span><b>${n(d.scale.customers)}</b><span class="dim"> customers</span></span>
      <span><b>${n(d.traffic.visitors)}</b><span class="dim"> visitors /30d</span></span>
      <span><b>${n(d.traffic.pageviews)}</b><span class="dim"> pageviews /30d</span></span>
    </div>
    ${d.notes.length ? `<div class="card" style="margin-top:12px">
      <b>The advice</b>
      ${d.notes.map((x) => `<p class="dim" style="display:flex;gap:8px;
        align-items:center;justify-content:space-between">
        <span>· ${esc(x)}</span>
        ${/granted but idle/.test(x) ? `<button class="btn alt sm"
          data-dtrim title="open the capability editor — trim or keep">
          adjust</button>` : ""}</p>`).join("")}
    </div>` : `<p class="dim" style="margin-top:12px">Nothing to flag —
      scale fits the plan and every capability shows use.</p>`}`;

  const meters = () => `
    <div style="display:flex;gap:10px;margin:4px 0 8px">
      <input id="dq" placeholder="filter capabilities…" style="flex:1">
      <label class="dim" style="display:flex;gap:6px;align-items:center">
        <input type="checkbox" id="dz"> hide idle</label>
    </div>
    <div class="tablewrap"><table>
      <thead><tr><th>capability</th><th>price</th><th>use</th></tr></thead>
      <tbody id="ds-mrows"></tbody></table></div>`;

  const meterRows = (q, hideIdle) => d.caps.filter((c) => {
    const vals = d.meters[c.id] || [];
    if (q && !c.name.toLowerCase().includes(q)) return false;
    if (hideIdle && !vals.some((v) => v.value)) return false;
    return true;
  }).map((c) => {
    const vals = (d.meters[c.id] || []).map((v) =>
      `${v.label === "revenue_cents" ? "revenue " + money(v.value)
        : `${v.label} ${n(v.value)}`}${v.period ? ` <span class="dim">/${
        v.period}</span>` : ""}`).join(" · ");
    return `<tr><td>${esc(c.name)}</td>
      <td class="dim">\$${c.price}/mo</td>
      <td>${vals || '<span class="dim">no meter yet</span>'}</td></tr>`;
  }).join("") || `<tr><td colspan="3" class="dim">nothing matches</td></tr>`;

  const bars = (rows, label, val) => {
    const top = Math.max(1, ...rows.map(val));
    return rows.map((r) => `<div style="margin:6px 0">
      <div class="dim" style="display:flex;justify-content:space-between">
        <span>${esc(label(r))}</span><span>${n(val(r))}</span></div>
      <div style="height:6px;border-radius:3px;background:var(--line,#333)">
        <div style="height:6px;border-radius:3px;width:${
          Math.round(100 * val(r) / top)}%;background:var(--acc,#7c5cff)">
        </div></div></div>`).join("");
  };

  const traffic = () => `<div class="row2">
    <div><h3>Top pages <span class="dim">by visitors /30d</span></h3>
      ${bars(d.traffic.top_pages || [], (r) => `${r.page} (${
        n(r.hits)} views)`, (r) => r.visitors)
        || '<p class="dim">no traffic recorded yet</p>'}</div>
    <div><h3>Referred from <span class="dim">across the internet /30d</span></h3>
      ${bars(d.traffic.top_referrers || [], (r) => r.referrer,
             (r) => r.visitors)
        || '<p class="dim">no off-site referrals yet</p>'}</div></div>`;

  const infra = () => {
    const sub = bl.subscription;
    const pills = Object.entries(ni.services || {}).map(([k, up]) =>
      `<span class="pill" style="border-color:${up ? "#2dd4bf" : "#f66"}">
       ${esc(k)} ${up ? "up" : "down"}</span>`).join(" ");
    return `<div class="row2">
    <div class="card"><b>The node</b>
      <p class="dim">${esc(ni.id || "?")} · ${esc(ni.size || "")}
        ${ni.region ? " · " + esc(ni.region) : ""}
        ${ni.provider ? " · " + esc(ni.provider) : ""}</p>
      <p class="dim">${ni.alive
        ? `answering · code ${esc(ni.version || "?")}`
        : `<span style="color:#f66">NOT ANSWERING</span> — ${
           esc(ni.error || "")}`}</p>
      <p class="dim">capacity ${n(ni.used)} / ${n(ni.capacity)} units —
        this client is ${n(ni.tenant_units)} of them, sharing with
        ${n(ni.neighbours)} neighbour(s)</p>
      <div style="height:6px;border-radius:3px;background:var(--line,#333)">
        <div style="height:6px;border-radius:3px;background:var(--acc,#7c5cff);
          width:${Math.round(100 * (ni.used || 0)
          / Math.max(1, ni.capacity || 1))}%"></div></div>
      ${pills ? `<p style="margin-top:8px">${pills}</p>` : ""}</div>
    <div class="card"><b>The billing</b>
      ${sub ? `<p class="dim">${esc(sub.plan)} — ${money(sub.price_cents)}
          ${esc(sub.interval || "")} · ${esc(sub.status)} · since
          ${day(sub.created_at)}</p>
        <p class="dim">payment: ${esc(sub.payment_status || "—")}</p>`
        : `<p class="dim">no linked subscription — this install is not
           billed through the store (invoice-mode, or internal)</p>`}
      ${bl.flag ? `<p style="color:#f66">card processor says
        "${esc(bl.flag.status)}" on ${esc(bl.flag.plan)} — money is NOT
        arriving</p>` : ""}
      <p class="dim">backup: ${bl.backup && bl.backup.missed
        ? '<span style="color:#f66">MISSED last night</span>'
        : bl.backup && bl.backup.stale
          ? '<span style="color:#f66">stale — no fresh archive</span>'
          : `covered, ${day((bl.backup || {}).at)}`}</p>
      ${bl.engagement ? `<button class="btn alt sm" id="ds-eng">
        open engagement: ${esc(bl.engagement.name)} →</button>` : ""}
    </div></div>`;
  };

  const history = () => (d.history || []).length
    ? (d.history || []).map((e) => `<p class="dim">
        <b>${day(e.at)}</b> · ${esc(e.actor || "system")} —
        ${esc(e.what)}${e.detail ? ` · ${esc(e.detail)}` : ""}</p>`).join("")
    : '<p class="dim">no fleet events mention this client yet</p>';

  const body = { overview, meters, traffic, infra, history };
  modal(`<h3>${esc(d.tenant)} — the dossier</h3>
    <p class="dim">${esc(d.class)} class · ${esc(d.status)} ·
      software \$${d.monthly_software}/mo ·
      ${(d.hosts || []).map(esc).join(", ")}</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">
      ${DSECS.map(([k, t]) => `<button class="btn sm ${k === sec ? ""
        : "alt"}" data-dsec="${k}">${t}</button>`).join("")}</div>
    <div id="ds-body">${body[sec]()}</div>
    <div class="modal-foot" style="display:flex;gap:8px">
      <button class="btn alt" id="ds-refresh"
        title="read their tables again, right now">Refresh</button>
      <button class="btn alt" id="ds-actas">Act as admin</button>
      <button class="btn alt" id="ds-caps">Capabilities</button>
      <button class="btn" data-close>Done</button></div>`, "wide");

  document.querySelectorAll("[data-dsec]").forEach((b) => b.onclick =
    () => dossierModal(tid, d, b.dataset.dsec));
  document.querySelectorAll("[data-dtrim]").forEach((b) => b.onclick =
    () => capsEditor(tid, { after: () => clientDossier(tid) }));
  $("#ds-refresh").onclick = () => clientDossier(tid, sec);
  $("#ds-caps").onclick =
    () => capsEditor(tid, { after: () => clientDossier(tid, sec) });
  $("#ds-actas").onclick = async () => {
    try {
      const out = await api(
        `/api/store/admin/fleet/tenants/${tid}/act-as`, { body: {} });
      window.open(out.url, "_blank");
      toast(`opened as ${out.account} — logged on the fleet history`);
    } catch (err) { toast(err.message); }
  };
  if ($("#ds-eng")) $("#ds-eng").onclick = () => {
    closeModal(); location.hash = `#/clients/${bl.engagement.id}`;
  };
  const paint = () => { $("#ds-mrows").innerHTML =
    meterRows(($("#dq").value || "").toLowerCase(), $("#dz").checked); };
  if (sec === "meters") {
    paint();
    $("#dq").oninput = paint;
    $("#dz").onchange = paint;
  }
}
