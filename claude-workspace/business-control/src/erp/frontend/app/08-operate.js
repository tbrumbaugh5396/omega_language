// ---------- inventory ----------

async function renderInventory() {
  const isStaff = S.user && (S.user.is_admin ||
    ["employee", "owner"].includes(S.user.role));
  const isAdmin = S.user && S.user.is_admin;
  const [inv, stores, picks, prods] = await Promise.all([
    api("/api/inventory"), api("/api/stores"),
    isStaff ? api("/api/warehouse/picklist").catch(() => []) : [],
    api("/api/products").catch(() => [])]);
  const byStore = {};
  inv.forEach((i) => {
    (byStore[i.store_id] = byStore[i.store_id] || { name: i.store_name,
      region: i.region, rows: [] }).rows.push(i);
  });
  const lows = inv.filter((i) => i.low);
  /* What we sell that has no shelf. A plan, a care contract, a build or a
     licence is carried by every location at once and has no count — but
     leaving them out of the inventory means the only complete list of
     what this business sells is on the shop page. So they are here,
     grouped and tinted like everywhere else, and said plainly to be
     unstocked rather than shown as a quantity of zero. */
  const svc = kindGroups(prods.filter((p) => p.kind && p.kind !== "goods"))
    .filter((g) => g.label);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Inventory — all stores</h2></div>
      ${isAdmin ? `<div class="top-actions">
        <button class="btn" id="inv-new" title="a new line, in draft — it
          stays off the shop until you publish it">${
          opsIcon("box", "btn-ic")} New product</button>
      </div>` : ""}
    </div>
    ${svc.length ? `<div class="card">
      <b>Sold everywhere, stocked nowhere</b>
      <p class="dim">Services carry no count: every location sells them,
        none holds any. Prices are the shop's; what a client is actually
        on lives on their own record.</p>
      ${svc.map((g) => `
        <h3 class="kind-head" style="--kind:${esc(g.colour)}">${esc(g.label)}
          <small class="dim">${g.items.length}</small></h3>
        <div class="tablewrap"><table class="svc-table"><tbody>
        ${g.items.map((p) => `<tr>
          <td>${esc(p.name)}</td>
          <td class="dim">${esc(p.sku)}</td>
          <td class="svc-price">${money(p.price_cents)}</td>
          <td class="dim svc-from">${p.quote ? "from — quoted" : ""}</td>
        </tr>`).join("")}</tbody></table></div>`).join("")}
    </div>` : ""}
    ${picks.length ? `<div class="card">
      <h3 style="margin-top:0">Pick list — ${picks.length} order(s) to pack</h3>
      <div class="tablewrap"><table><thead><tr><th>#</th><th>kind</th><th>items</th>
        <th>ship to</th><th>status</th></tr></thead><tbody>
      ${picks.map((o) => `<tr><td>${o.id}</td><td>${o.kind}</td>
        <td>${o.items.map((i) => `${esc(i.name)} × ${i.qty}${o.kind === "distributor"
          ? ` cs (${i.qty * i.case_size} units)` : ""}`).join(", ")}</td>
        <td class="dim">${esc(o.ship_name || "")} ${esc(o.city || "")}</td>
        <td><span class="pill ${o.status === "confirmed" ? "ok" : ""}">${o.status}</span></td>
      </tr>`).join("")}</tbody></table></div>
      <div class="dim" style="font-size:12px;margin-top:4px">Stock is consumed
        automatically when an admin marks the order shipped.</div></div>` : ""}
    ${lows.length ? `<div class="card"><b class="low">${lows.length} low-stock
      line(s):</b> ${lows.map((l) =>
        `${esc(l.store_name)}: ${esc(l.product_name)} (${l.qty})`).join(" · ")}</div>` : ""}
    ${stores.map((s) => {
      const d = byStore[s.id];
      if (!d) return "";
      return `<div class="card"><b>${esc(s.name)}</b>
        <span class="dim">· ${esc(s.city)} · ${esc(s.region)}</span>
        <table style="margin-top:6px"><thead><tr><th>product</th><th>qty</th>
        <th>par</th>${isAdmin ? "<th></th>" : ""}</tr></thead><tbody>
        ${d.rows.map((r) => `<tr>
          <td>${esc(r.product_name)}</td>
          ${isAdmin ? `<td><input class="inv-n ${r.low ? "low" : ""}"
              type="number" data-invq="${s.id}:${r.product_id}"
              value="${r.qty}"></td>
            <td><input class="inv-n" type="number"
              data-invp="${s.id}:${r.product_id}" value="${r.par}"></td>
            <td><button class="btn alt sm"
              data-invdel="${s.id}:${r.product_id}">Remove</button></td>`
          : `<td class="${r.low ? "low" : ""}">${r.qty}</td>
             <td class="dim">${r.par}</td>`}
        </tr>`).join("")}
        </tbody></table></div>`;
    }).join("")}`;

  if ($("#inv-new")) $("#inv-new").onclick = () => productForm();
  /* Stock is edited in place rather than through a dialog: correcting a
     count is something you do to a whole shelf at once, and a modal per row
     turns twenty corrections into sixty clicks. */
  const saveCell = async (el) => {
    const [store, product] = (el.dataset.invq || el.dataset.invp).split(":");
    const row = view().querySelector(`[data-invq="${store}:${product}"]`);
    const par = view().querySelector(`[data-invp="${store}:${product}"]`);
    try {
      await api("/api/admin/inventory", { body: {
        store_id: +store, product_id: +product,
        qty: +row.value, par: +par.value } });
      el.classList.add("saved");
      setTimeout(() => el.classList.remove("saved"), 900);
    } catch (e) { toast(e.message); }
  };
  view().querySelectorAll("[data-invq],[data-invp]").forEach((el) => {
    el.onchange = () => saveCell(el);
  });
  view().querySelectorAll("[data-invdel]").forEach((b) => b.onclick = async () => {
    const [store, product] = b.dataset.invdel.split(":");
    if (!confirm("Remove this product from this store's list?\n\n"
      + "That says the store doesn't carry it — different from having none "
      + "left, which is a quantity of zero.")) return;
    try {
      await api(`/api/admin/inventory/${store}/${product}`,
                { method: "DELETE" });
      renderInventory();
    } catch (e) { toast(e.message); }
  });
}

// ---------- routes ----------

function routeMap(stops) {
  const pts = (stops || []).filter((p) => p.lat && p.lng);
  if (!pts.length) return "";
  const legs = [];
  for (let i = 0; i + 1 < pts.length; i++) legs.push([pts[i], pts[i + 1]]);
  const id = "rmap" + (++MAP_SEQ);
  return panZoomMap({
    id,
    legs,
    pins: pts.map((p, i) => ({
      lat: p.lat, lng: p.lng, n: i + 1,
      color: p.delivered ? "#3fbd82" : "#8a6ff0",
      size: 11, label: p.name, sub: p.city })),
  });
}

async function renderRoutes() {
  const [trucks, routes, stores] = await Promise.all([
    api("/api/trucks"), api("/api/routes"), api("/api/stores")]);
  view().innerHTML = `
    <h2>Trucking routes</h2>
    <div class="card">
      <h3 style="margin-top:0">Plan a route</h3>
      <form class="inline" id="plan-form">
        <label class="f">truck <select id="pf-truck">
          ${trucks.map((t) => `<option value="${t.id}">${esc(t.name)}
            (${t.capacity_cases} cases)</option>`).join("")}</select></label>
        <label class="f">region <select id="pf-region">
          ${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select></label>
        <label class="f">date <input id="pf-date" type="date"></label>
        <button class="btn">Plan (optimize stops)</button>
      </form>
      <div class="dim" style="margin-top:6px">Plans over every active store in
        the region; stop order is optimized for drive distance, with time
        estimates (${S.meta.regions.length} regions).</div>
      ${S.user && S.user.is_admin ? `<div style="margin-top:8px">
        <button class="btn alt" id="auto-cover">Auto-plan coverage —
          all regions</button>
        <span class="dim">regenerates each region's coverage route; also runs
          automatically whenever a store is added</span></div>` : ""}
    </div>
    ${S.user && S.user.is_admin ? `<div class="card">
      <h3 style="margin-top:0">Truck QRs — print one for each cab</h3>
      <div class="row">${trucks.map((t) => `<div style="text-align:center">
        ${qrImg("bc:truck:" + t.id, 100)}
        <div class="dim" style="font-size:12px">${esc(t.name)}</div></div>`).join("")}
      </div>
      <div class="dim" style="font-size:12px;margin-top:6px">A signed-in driver
        scans the cab QR (Scan tab) to check in to the truck and pull up its
        current route with ETAs.</div>
    </div>` : ""}
    ${routes.map((r) => `
      <div class="card">
        <b>${esc(r.name)}</b>
        <span class="pill ${r.status === "done" ? "ok" : r.status === "active" ? "warn" : ""}">${r.status}</span>
        <span class="dim">· ${r.total_km} km · ~${fmtMin(r.total_min)} ·
          ${esc((trucks.find((t) => t.id === r.truck_id) || {}).name || "unassigned")}
          ${r.route_date ? "· " + r.route_date : ""}</span>
        <span style="float:right">
          ${["planned", "active", "done"].filter((s) => s !== r.status).map((s) =>
            `<button class="btn alt" data-rs="${r.id}:${s}">${s}</button>`).join(" ")}
        </span>
        ${routeMap(r.stops)}
        <table><thead><tr><th>#</th><th>store</th><th>city</th><th>leg</th>
          <th>drive</th><th>ETA</th><th>done</th><th>proof</th>
          </tr></thead><tbody>
        ${r.stops.map((s) => `<tr><td>${s.seq + 1}</td><td>${esc(s.name)}</td>
          <td class="dim">${esc(s.city)}</td><td>${s.leg_km} km</td>
          <td>${fmtMin(s.drive_min)}</td><td>+${fmtMin(s.eta_min)}</td>
          <td><input type="checkbox" data-stop="${r.id}:${s.seq}"
            ${s.delivered ? "checked" : ""}
            title="marking it here is somebody's word for it; taking the
              stop records who took it and what they photographed"></td>
          <td>${s.visit
            ? `<button class="btn alt sm" data-svisit="${s.visit.id}"
                 title="${s.proved
                   ? "signed by " + esc(s.visit.contact_name
                       || s.visit.signature) + ", " + s.visit.photos
                       + " photo(s)"
                   : "in progress"}">${s.proved
                 ? "signed · " + esc((s.visit.who || "").split(" ")[0])
                 : esc(s.visit.state)}</button>`
            : `<button class="btn alt sm" data-take-stop="${r.id}:${s.seq}"
                 >Take it</button>`}</td></tr>`).join("")}
        </tbody></table>
      </div>`).join("")}`;
  if ($("#auto-cover")) $("#auto-cover").onclick = async () => {
    try {
      const made = await api("/api/admin/routes/auto", { body: {} });
      toast(`planned ${made.length} coverage route(s)`);
      render();
    } catch (err) { toast(err.message); }
  };
  $("#plan-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/routes/plan", { body: {
        truck_id: +$("#pf-truck").value, region: $("#pf-region").value,
        route_date: $("#pf-date").value } });
      toast(`Route planned — ${r.total_km} km over ${r.stops.length} stops`);
      render();
    } catch (err) { toast(err.message); }
  };
  document.querySelectorAll("[data-rs]").forEach((b) => {
    b.onclick = async () => {
      const [rid, status] = b.dataset.rs.split(":");
      await api(`/api/routes/${rid}/status`, { body: { status } });
      render();
    };
  });
  document.querySelectorAll("[data-take-stop]").forEach((b) => {
    b.onclick = async () => {
      const [rid, seq] = b.dataset.takeStop.split(":");
      try {
        const r = await api(`/api/field/route/${rid}/stop/${seq}/take`,
                            { body: {} });
        toast(r.lines
          ? `${r.lines} line(s) owed at that door`
          : "nothing outstanding there — it is a call, not a drop");
        S.tab = "field";
        render();
        setTimeout(() => openVisit(r.id), 400);
      } catch (e) { toast(e.message); }
    };
  });
  document.querySelectorAll("[data-svisit]").forEach((b) => {
    b.onclick = () => { S.tab = "field"; render();
      setTimeout(() => openVisit(+b.dataset.svisit), 400); };
  });
  document.querySelectorAll("[data-stop]").forEach((cb) => {
    cb.onchange = async () => {
      const [rid, seq] = cb.dataset.stop.split(":");
      await api(`/api/routes/${rid}/stop`,
        { body: { seq: +seq, delivered: cb.checked } });
    };
  });
}

// ---------- outreach ----------

const STAGES = ["lead", "contacted", "sampled", "stocked", "lost"];

async function renderOutreach() {
  let items = await api("/api/outreach");
  if (S.outreachMine) items = items.filter(
    (i) => i.owner_user_id === S.user.id);
  const byStage = Object.fromEntries(STAGES.map((s) => [s, []]));
  items.forEach((i) => (byStage[i.stage] || byStage.lead).push(i));
  view().innerHTML = `
    <h2>Regional outreach
      <label style="font-size:13px;font-weight:400;margin-left:10px">
        <input type="checkbox" id="or-mine" ${S.outreachMine ? "checked" : ""}>
        my accounts only</label></h2>
    <div class="card"><form class="inline" id="or-form">
      <input id="or-name" placeholder="store / account name" required>
      <select id="or-region">${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select>
      <input id="or-city" placeholder="city">
      <input id="or-next" placeholder="next action">
      <button class="btn">Add lead</button>
    </form></div>
    <div class="kanban">${STAGES.map((st) => `
      <div class="col"><h3 style="margin-top:0">${st} (${byStage[st].length})</h3>
        ${byStage[st].map((i) => `
          <div class="item" data-or="${i.id}">
            <b>${esc(i.name)}</b><br>
            <span class="dim">${esc(i.city)} · ${esc(i.region)}</span>
            ${i.next_action ? `<br>→ ${esc(i.next_action)}
              ${i.next_action_date ? `<span class="dim">(${esc(i.next_action_date)})</span>` : ""}` : ""}
            <br><select data-stage="${i.id}">
              ${STAGES.map((s) => `<option ${s === i.stage ? "selected" : ""}>${s}</option>`).join("")}
            </select>
          </div>`).join("")}
      </div>`).join("")}</div>`;
  $("#or-mine").onchange = (e) => { S.outreachMine = e.target.checked;
    render(); };
  $("#or-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/outreach", { body: {
      name: $("#or-name").value, region: $("#or-region").value,
      city: $("#or-city").value, next_action: $("#or-next").value } });
    render();
  };
  document.querySelectorAll("[data-stage]").forEach((sel) => {
    sel.onclick = (e) => e.stopPropagation();
    sel.onchange = async () => {
      const note = prompt("Log a note for this change (optional):") || "";
      await api(`/api/outreach/${sel.dataset.stage}/update`,
        { body: { stage: sel.value, note } });
      render();
    };
  });
}

// ---------- experiments ----------

async function renderExperiments() {
  const exps = await api("/api/experiments");
  view().innerHTML = `
    <h2>A/B experiments</h2>
    <div class="card">
      <form class="inline" id="ax-form">
        <label class="f">goal <select id="ax-goal">
          <option value="purchase">purchase</option>
          <option value="add_to_cart">add_to_cart</option></select></label>
        <label class="f">variants <select id="ax-n">
          <option>2</option><option selected>3</option><option>4</option></select></label>
        <button class="btn">Auto-generate experiment</button>
      </form>
      <div class="dim" style="margin-top:6px">Picks your top-selling product and
        generates grouped headline/CTA/theme variants automatically.</div>
    </div>
    ${exps.map((r) => {
      const e = r.experiment;
      return `<div class="card">
        <b>${esc(e.name)}</b>
        <span class="pill ${e.status === "running" ? "ok" : ""}">${e.status}</span>
        <span class="dim">· goal: ${esc(r.goal)} ·
          needs ${r.min_exposures} exposures/variant</span>
        ${e.status === "running" ? `<button class="btn alt" style="float:right"
          data-stop-exp="${e.id}">Stop & pick winner</button>` : ""}
        <table style="margin-top:8px"><thead><tr><th>variant</th><th>headline</th>
          <th>cta</th><th>exposures</th><th>conversions</th><th>rate</th>
          <th>z vs A</th></tr></thead><tbody>
        ${r.variants.map((v) => `<tr
          ${r.winner && r.winner.variant_id === v.variant.id
            ? 'style="outline:1px solid var(--accent)"' : ""}>
          <td>${esc(v.variant.name)}</td><td>${esc(v.variant.headline)}</td>
          <td>${esc(v.variant.cta)}</td><td>${v.exposures}</td>
          <td>${v.conversions}</td><td>${(v.rate * 100).toFixed(1)}%</td>
          <td>${v.z_vs_control ?? "—"}</td></tr>`).join("")}
        </tbody></table>
        ${r.winner ? `<div style="margin-top:8px">Suggested winner:
          <b>${esc(r.winner.name)}</b> at ${(r.winner.rate * 100).toFixed(1)}%
          ${r.winner.significant
            ? '<span class="pill ok">statistically significant</span>'
            : '<span class="pill warn">not yet significant</span>'}</div>`
        : `<div class="dim" style="margin-top:8px">Collecting data…</div>`}
      </div>`;
    }).join("")}`;
  $("#ax-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/experiments/auto", { body: {
      goal: $("#ax-goal").value, n_variants: +$("#ax-n").value } });
    toast("experiment launched");
    render();
  };
  document.querySelectorAll("[data-stop-exp]").forEach((b) => {
    b.onclick = async () => {
      const r = await api(`/api/admin/experiments/${b.dataset.stopExp}/stop`,
        { body: {} });
      toast(r.winner ? `winner: ${r.winner.name}` : "stopped (no winner yet)");
      render();
    };
  });
}

// ---------- analytics ----------

async function renderAnalytics() {
  const [regions, funnel, engagement, pnl, proj, mrr, days, pipe, shop,
         graph] = await Promise.all([
      api("/api/analytics/regions"), api("/api/analytics/funnel"),
      api("/api/analytics/engagement"), api("/api/analytics/pnl"),
      api("/api/analytics/projection?months=6").catch(() => null),
      api("/api/analytics/mrr?months=12").catch(() => null),
      api("/api/analytics/days?days=90").catch(() => null),
      api("/api/store/admin/pipeline").catch(() => null),
      api("/api/analytics/commerce?days=90").catch(() => null),
      api("/api/store/admin/page-graph?days=90").catch(() => null)]);
  const maxV = Math.max(...funnel.steps.map((s) => s.visitors), 1);
  const maxD = Math.max(...engagement.daily.map((d) => d.total), 1);
  view().innerHTML = `
    <h2>Analytics — last 30 days</h2>
    ${engagement.alerts.length ? `<div class="card">
      ${engagement.alerts.map((a) => `<div><span class="pill bad">engagement
        falling off</span> <b>${esc(a.scope)}</b>: ${a.last_7} events this week
        vs ${a.prior_7} last week</div>`).join("")}</div>` : ""}
    ${mrr && mrr.months.length ? mrrSection(mrr) : ""}
    ${days ? daysSection(days) : ""}
    ${shop && shop.basket.orders ? shopSection(shop) : ""}
    ${pipe && pipe.engagements ? pipeSection(pipe) : ""}
    ${proj ? `<h3>Next six months</h3>
    <div class="card">
      <p class="dim">${esc(proj.note)}${proj.thin
        ? " There are only " + proj.history_days + " days of orders behind "
          + "this, so read the trend half as a placeholder rather than a "
          + "forecast."
        : ""}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>month</th><th>committed</th><th>trend</th>
          <th>total</th><th></th></tr></thead>
        <tbody>${proj.months.map((m) => {
          const top = Math.max(...proj.months.map((x) => x.total_cents), 1);
          const w = (c) => Math.round(100 * c / top);
          return `<tr>
            <td>${esc(m.month)}</td>
            <td>${money(m.committed_cents)}</td>
            <td class="dim">${money(m.trend_cents)}</td>
            <td><b>${money(m.total_cents)}</b></td>
            <td style="min-width:140px">
              <div class="proj-bar">
                <span class="proj-fixed" style="width:${
                  w(m.committed_cents)}%"></span>
                <span class="proj-trend" style="width:${
                  w(m.trend_cents)}%"></span>
              </div></td></tr>`;
        }).join("")}</tbody></table></div>
      <p class="dim"><span class="proj-key proj-fixed"></span> committed —
        signed plans and care <span class="proj-key proj-trend"></span>
        trend — one-off sales, projected flat</p>
    </div>` : ""}
    <h3>P&L</h3>
    <div class="card" style="max-width:520px">${pnlTable(pnl)}</div>
    <h3>By region</h3>
    <div class="card"><table><thead><tr><th>region</th><th>revenue</th>
      <th>orders</th><th>distributor orders</th><th>visitors</th><th>stores</th>
    </tr></thead><tbody>
    ${regions.map((r) => `<tr><td>${esc(r.region) || "—"}</td>
      <td>${money(r.revenue_cents)}</td><td>${r.orders}</td>
      <td>${r.distributor_orders}</td><td>${r.visitors}</td>
      <td>${r.stores}</td></tr>`).join("")}</tbody></table></div>
    <h3>Sales funnel</h3>
    <div class="card">
      ${funnel.steps.map((s) => `<div class="funnel-row">
        <span class="lbl">${s.step}</span>
        <span class="n">${s.visitors}</span>
        <div class="bar" style="width:${(s.visitors / maxV) * 100}%"></div>
        <span class="dim">${s.drop_rate !== undefined && s.drop_rate > 0
          ? "−" + (s.drop_rate * 100).toFixed(0) + "%" : ""}</span>
      </div>`).join("")}
      ${funnel.worst_dropoff ? `<div style="margin-top:8px">Biggest drop-off:
        <b>${esc(funnel.worst_dropoff.from)} → ${esc(funnel.worst_dropoff.to)}</b>
        loses ${(funnel.worst_dropoff.drop_rate * 100).toFixed(0)}% —
        focus fixes here.</div>` : ""}
    </div>
    ${graph ? graphSection(graph) : ""}
    <h3>Engagement (events/day, 28d)</h3>
    <div class="card"><div style="display:flex;align-items:flex-end;gap:2px;height:90px">
      ${engagement.daily.map((d) => `<div title="day ${d.day}: ${d.total}"
        style="flex:1;background:var(--accent2);border-radius:2px 2px 0 0;
        height:${(d.total / maxD) * 100}%"></div>`).join("")}
    </div>
    <div class="dim" style="margin-top:6px">last 7 days: ${engagement.overall.last_7}
      events · prior 7: ${engagement.overall.prior_7}
      ${engagement.overall.falling_off
        ? '<span class="pill bad">falling off</span>'
        : '<span class="pill ok">healthy</span>'}</div></div>`;
  if ($("#pg-by")) $("#pg-by").onchange = (e) => {
    GRAPH_BY = e.target.value; renderAnalytics();
  };
  if ($("#cal-day")) $("#cal-day").onclick = () => markDayForm();
  if ($("#sky-get")) $("#sky-get").onclick = async (ev) => {
    ev.target.disabled = true;
    ev.target.textContent = "asking…";
    try {
      const r = await api("/api/analytics/weather?days=90", { method: "POST" });
      toast(`${r.days} days of weather, ${r.from} to ${r.to}`);
      renderAnalytics();
    } catch (err) {
      toast(err.message);
      ev.target.disabled = false;
      ev.target.textContent = "Fetch the weather";
    }
  };
}

/* The site drawn as the chain it is. A step funnel says how many reached
   checkout and a transition list says which page leaks; neither says
   which page the traffic RUNS THROUGH, which is a question about the
   shape of the whole graph. Laid left to right by where in a path each
   page typically appears, so the drawing reads in the order people walk
   it rather than in dictionary order. */
function graphSection(g) {
  if (!g.nodes.length) return "";
  const COLS = Math.min(5, Math.max(2, Math.ceil(g.nodes.length / 3)));
  const per = Math.ceil(g.nodes.length / COLS);
  const W = 150, H = 96, PAD = 70;
  const pos = {};
  g.nodes.forEach((n, i) => {
    const col = Math.min(COLS - 1, Math.floor(i / per));
    const inCol = g.nodes.filter((_, j) =>
      Math.min(COLS - 1, Math.floor(j / per)) === col).length;
    const row = i - col * per;
    pos[n.page] = { x: PAD + col * W,
                    y: 46 + row * H + (inCol < per ? (per - inCol) * H / 2 : 0),
                    n };
  });
  // Size by rank or by views. They disagree exactly where the answer is
  // interesting — a page everybody passes through against a page
  // everybody looks at — so it is a switch rather than a decision made
  // once on somebody's behalf.
  const by = GRAPH_BY;
  const val = (n) => by === "views" ? n.views : n.rank;
  const maxV = Math.max(...g.nodes.map(val), 0.0001);
  const width = PAD * 2 + (COLS - 1) * W;
  const height = 46 + per * H;
  const r = (n) => 9 + 17 * Math.sqrt(val(n) / maxV);
  const short = (p) => p.length > 20 ? p.slice(0, 19) + "…" : p;
  // Two pages that link both ways drew one arrow exactly on top of the
  // other, and the return trip is usually the more interesting half. So
  // every edge bows to ITS OWN side: the arc is offset perpendicular to
  // the line, and the sign of the offset comes from the direction — A→B
  // bows one way and B→A the other, whatever order they arrive in.
  const edges = g.edges.map((e) => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return "";
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const back = (dx || dy) < 0 ? -1 : 1;      // which way this one runs
    const lift = Math.min(56, 14 + len * 0.13) * back;
    // Perpendicular to the line, so the bow shows on verticals too.
    const cx = (a.x + b.x) / 2 - (dy / len) * lift;
    const cy = (a.y + b.y) / 2 + (dx / len) * lift;
    return `<path class="pg-edge" d="M${a.x} ${a.y} Q${cx.toFixed(1)} ${
      cy.toFixed(1)}, ${b.x} ${b.y}"
      stroke-width="${(0.6 + 5 * e.p).toFixed(2)}"
      marker-end="url(#pg-arrow)">
      <title>${esc(e.from)} → ${esc(e.to)} · ${e.n} time${
        e.n === 1 ? "" : "s"} · ${Math.round(e.p * 100)}% of what happens
        next on ${esc(e.from)}</title></path>`;
  }).join("");
  return `
    <div class="page-head graph-head">
      <h3>How the pages connect</h3>
      <div class="top-actions">
        <select id="pg-by">
          <option value="rank"${by === "rank" ? " selected" : ""}
            >size by rank</option>
          <option value="views"${by === "views" ? " selected" : ""}
            >size by views</option>
        </select>
      </div>
    </div>
    <div class="card">
      <p class="dim">${esc(g.note)}</p>
      <div class="graph-wrap">
      <svg viewBox="0 0 ${width} ${height}" width="${width}"
        height="${height}" role="img"
        aria-label="pages as a chain of transitions">
        <defs><marker id="pg-arrow" viewBox="0 0 8 8" refX="7" refY="4"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L8 4 L0 8 z" fill="currentColor" opacity=".55"/>
        </marker></defs>
        ${edges}
        ${g.nodes.map((n) => {
          const p = pos[n.page];
          return `<g class="pg-node${n.exit_rate >= 50 ? " pg-leaky" : ""}">
            <circle cx="${p.x}" cy="${p.y}" r="${r(n).toFixed(1)}"></circle>
            <text x="${p.x}" y="${p.y + r(n) + 13}" text-anchor="middle"
              >${esc(short(n.page))}</text>
            <text class="pg-sub" x="${p.x}" y="${p.y + r(n) + 25}"
              text-anchor="middle">${n.views} view${n.views === 1 ? "" : "s"}
              · ${Math.round(n.rank * 100)}% rank</text>
            <title>${esc(n.page)} — ${n.views} views, ${n.entries} arrived
              here first, ${n.exit_rate}% left from here. Rank ${
              (n.rank * 100).toFixed(1)}%: the share of a wandering
              visitor's time this page holds.</title>
          </g>`;
        }).join("")}
      </svg>
      </div>
      <p class="dim">${by === "rank"
        ? "Circle size is rank — the share of a wandering visitor's time "
          + "each page holds. It disagrees with views exactly where a quiet "
          + "page sits on everybody's way through, which is the interesting "
          + "case."
        : "Circle size is raw views. Useful for seeing what gets looked "
          + "at; switch to rank to see what the traffic runs through."}
        Amber is a page more than half of visits end on. ${g.sessions}
        session${g.sessions === 1 ? "" : "s"} over ${g.days} days.</p>
    </div>`;
}
/* Which measure the circles are drawn at. Kept outside the render so
   changing it does not lose the rest of the page's scroll. */
let GRAPH_BY = "rank";

/* What a basket is worth, and whether anybody comes back. The median
   sits beside every average on purpose: one wholesale order in a month of
   tea tins moves the mean past every real basket in the list, and a shop
   that reprices off that number reprices off one customer. */
function shopSection(d) {
  const b = d.basket, r = d.repeat, co = d.cohorts;
  const wide = Math.max(...co.cohorts.map((c) => c.cells.length), 0);
  const heat = (p) => `background:color-mix(in srgb, var(--accent) ${
    Math.round(Math.min(100, p) * 0.55)}%, transparent)`;
  return `
    <h3>Baskets and returns</h3>
    <div class="card">
      <div class="mrr-heads">
        <div class="mrr-fig" title="the mean — one big order moves it">
          <span class="dim">average order</span>
          <b>${money(b.aov_cents)}</b></div>
        <div class="mrr-fig" title="the middle order, which is what most
          customers actually spend"><span class="dim">median order</span>
          <b>${money(b.median_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">items per order</span>
          <b>${b.units_per_order === null ? "—" : b.units_per_order}</b></div>
        <div class="mrr-fig" title="of everybody who has ever bought, the
          share who bought more than once">
          <span class="dim">buy again</span>
          <b class="${r.repeat_ever_pct >= 30 ? "good" : ""}">${
            r.repeat_ever_pct === null ? "—"
              : r.repeat_ever_pct + "%"}</b></div>
        <div class="mrr-fig"><span class="dim">orders each</span>
          <b>${r.orders_per_customer === null ? "—"
            : r.orders_per_customer}</b></div>
      </div>
      <p class="dim">${b.orders} order${b.orders === 1 ? "" : "s"} in
        ${b.days} days${b.spread
          ? `; the middle half fall between ${money(b.spread.p25)} and
             ${money(b.spread.p75)}` : ""}.
        ${b.aov_cents > b.median_cents * 1.6
          ? "The average is well above the middle order, so a few large "
            + "ones are carrying it — price off the median."
          : ""}</p>
      ${b.by_kind.length > 1 ? `<div class="wd-rows">${b.by_kind.map((k) => `
        <div class="wd-row kind-row">
          <span class="wd-n pipe-n">${esc(k.kind)}</span>
          <span class="dim">${k.orders} orders</span>
          <span class="wd-v">${money(k.aov_cents)} avg</span>
          <span class="wd-v">${money(k.median_cents)} mid</span>
        </div>`).join("")}</div>
        <p class="dim">Kept apart because a case going to a distributor and
          a tin going to somebody's kitchen are not the same
          transaction — one average over both describes neither.</p>` : ""}
      <h4 class="mrr-h">Coming back</h4>
      <p class="dim">${r.repeat_ever_pct}% of ${r.customers_ever} customers
        have bought more than once${r.median_gap_days !== null
          ? `, taking a median ${r.median_gap_days} days over the second
             one` : ""}. ${r.returning_pct !== null
          ? `${r.returning_pct}% of the last ${r.days} days' revenue came
             from people who had bought before` : ""}${
        r.returning_pct !== null && r.returning_pct < 40
          ? " — a business growing on strangers is growing the most "
            + "expensive way there is." : "."}</p>
      ${d.lines && d.lines.lines.length ? linesBox(d.lines) : ""}
      ${co.cohorts.length ? `<h4 class="mrr-h">Cohorts</h4>
        <div class="tablewrap"><table class="cohort">
          <thead><tr><th>first bought</th><th>customers</th>
            ${Array.from({ length: wide }, (_, i) =>
              `<th>+${i + 1}</th>`).join("")}</tr></thead>
          <tbody>${co.cohorts.map((c) => `<tr>
            <td>${esc(c.cohort)}${c.partial
              ? ' <span class="pill">this month</span>' : ""}</td>
            <td>${c.size}</td>
            ${Array.from({ length: wide }, (_, i) => {
              const cell = c.cells[i];
              if (!cell) return '<td class="dim"></td>';
              return `<td class="${cell.partial ? "dim coh-part" : ""}"
                style="${cell.partial ? "" : heat(cell.pct)}"
                title="${cell.n} of ${c.size} bought again in ${
                  esc(cell.tag)}">${cell.pct}%${cell.partial
                    ? "<sup>*</sup>" : ""}</td>`;
            }).join("")}</tr>`).join("")}</tbody>
        </table></div>
        <p class="dim">${esc(co.note)}${co.cohorts.some((c) =>
          c.cells.some((x) => x.partial))
            ? " Cells marked * are in the month that is still running."
            : ""}</p>` : ""}
    </div>`;
}

/* The shelf, line by line. An overall margin is an average of things that
   are not alike: it can read healthy while a third of the range is sold
   at a loss, and the only way to find that out is to ask each line. */
function linesBox(d) {
  const top = Math.max(...d.categories.map((c) => c.revenue_cents), 1);
  return `<h4 class="mrr-h">By category</h4>
    <div class="wd-rows">${d.categories.map((c) => `
      <div class="wd-row cat-row">
        <span class="wd-n pipe-n">${esc(c.category)}</span>
        <div class="wd-bar"><span style="width:${
          Math.round(100 * c.revenue_cents / top)}%"></span></div>
        <span class="wd-v">${money(c.revenue_cents)}</span>
        <span class="dim">${c.share_pct}%</span>
        <span class="wd-v ${c.margin_pct === null ? "dim"
          : c.margin_pct < 0 ? "low" : ""}">${c.margin_pct === null
            ? "no recipe" : c.margin_pct + "% margin"}</span>
      </div>`).join("")}</div>
    <h4 class="mrr-h">By line</h4>
    <div class="tablewrap"><table>
      <thead><tr><th>product</th><th>units</th><th>revenue</th>
        <th>avg price</th><th>margin</th>
        <th title="how often it is in a basket with something else rather
          than alone on the receipt">attach</th>
        <th>buyers</th></tr></thead>
      <tbody>${d.lines.slice(0, 20).map((x) => `<tr${
        x.margin_pct !== null && x.margin_pct < 0 ? ' class="dl-awaiting"'
          : ""}>
        <td>${esc(x.name)}<span class="dim"> · ${esc(x.category)}</span></td>
        <td>${x.units}</td>
        <td>${money(x.revenue_cents)}</td>
        <td class="dim">${money(x.avg_price_cents)}</td>
        <td class="${x.margin_pct === null ? "dim"
          : x.margin_pct < 0 ? "low" : "good"}">${x.margin_pct === null
            ? "—" : x.margin_pct + "%"}</td>
        <td class="dim">${x.attach_pct === null ? "—"
          : x.attach_pct + "%"}</td>
        <td class="dim">${x.buyers}</td>
      </tr>`).join("")}</tbody></table></div>
    <p class="dim">${esc(d.note)} ${d.priced_pct}% of revenue is on lines
      with a recipe behind them${d.top_fifth_pct !== null
        ? `; the best fifth of the range carries ${d.top_fifth_pct}% of it`
        : ""}.${d.losing.length
        ? ` <b class="low">${d.losing.length} line${
          d.losing.length === 1 ? " is" : "s are"} sold under cost.</b>` : ""}
      Attach rate is the argument for keeping a thin-margin line: one
      mostly bought alone earns its shelf on its own margin, one almost
      always in company earns it on the basket's.</p>`;
}

/* The studio's own numbers. Nothing here is measured on purpose: the
   gates already know when each one passed and the dates table already
   holds planned against actual, so this is addition, not instrumentation.
   The one that earns its place is concentration — a studio with most of
   its revenue in one client is one phone call from a bad year, and that
   belongs on a screen long before the call. */
function pipeSection(d) {
  const conc = d.concentration.build;
  const mono = d.concentration.monthly;
  const dl = d.delivery;
  const risky = conc && conc.top_pct >= 40;
  return `
    <h3>Studio pipeline</h3>
    <div class="card">
      <div class="mrr-heads">
        <div class="mrr-fig"><span class="dim">open</span>
          <b>${money(d.open_value_cents)}</b></div>
        <div class="mrr-fig" title="won, and being built"><span class="dim">
          in delivery</span><b>${money(d.delivering_value_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">win rate</span>
          <b>${d.win_rate_pct === null ? "—" : d.win_rate_pct + "%"}</b></div>
        <div class="mrr-fig"><span class="dim">avg deal</span>
          <b>${money(d.avg_deal_cents)}</b></div>
        <div class="mrr-fig" title="from first contact to a signed
          contract"><span class="dim">cycle</span>
          <b>${d.median_cycle_days === null ? "—"
            : d.median_cycle_days + "d"}</b></div>
      </div>
      ${conc ? `<div class="card ${risky ? "alert" : ""} conc-card">
        <b>${conc.top_pct}% of the build book is ${esc(conc.top_name)}</b>
        <span class="dim">Top three are ${conc.top3_pct}% of
          ${money(conc.total_cents)}.${mono
            ? ` On the monthly book it is ${mono.top_pct}%
               (${esc(mono.top_name)}).` : ""}
          ${risky ? "A studio with most of its revenue in one client is one "
            + "phone call from a bad year." : ""}</span>
      </div>` : ""}
      <h4 class="mrr-h">Where the work is</h4>
      <div class="wd-rows">${d.stages.map((s) => {
        const top = Math.max(...d.stages.map((x) => x.value_cents), 1);
        return `<div class="wd-row pipe-row">
          <span class="wd-n pipe-n">${esc(s.label)}</span>
          <div class="wd-bar"><span style="width:${
            Math.round(100 * s.value_cents / top)}%"></span></div>
          <span class="wd-v">${money(s.value_cents)}</span>
          <span class="dim">${s.n}</span>
        </div>`;
      }).join("")}</div>
      <h4 class="mrr-h">How far they get</h4>
      <div class="tablewrap"><table>
        <thead><tr><th>stage</th><th>reached</th><th>of all</th>
          <th>median days to it</th></tr></thead>
        <tbody>${d.funnel.map((f) => `<tr>
          <td>${esc(f.label)}</td><td>${f.reached}</td>
          <td class="dim">${f.pct}%</td>
          <td class="dim">${f.median_days === null ? "—"
            : f.median_days + "d"}</td></tr>`).join("")}</tbody>
      </table></div>
      ${d.stuck.length ? `<h4 class="mrr-h">Longest without a move</h4>
        <div class="sig-rows">${d.stuck.map((x) => `
          <div class="doc-line mrr-line">
            <span class="dl-title"><b>${esc(x.name)}</b>
              <span class="dim">${esc(x.stage_label)}</span></span>
            <span class="pill ${x.idle_days > 30 ? "warn" : ""}">${
              Math.round(x.idle_days)}d</span>
            <span class="mrr-amt">${money(x.value_cents)}</span>
          </div>`).join("")}</div>` : ""}
      <h4 class="mrr-h">Delivery</h4>
      <p class="dim">${dl.dated
        ? `${dl.on_time_pct}% of ${dl.dated} dated milestones landed on or
           before the day they were planned for${dl.median_slip_days !== null
             ? `; the median moved ${dl.median_slip_days} day${
               Math.abs(dl.median_slip_days) === 1 ? "" : "s"}` : ""}.${
           dl.launch_on_time_pct !== null
             ? ` ${dl.launch_on_time_pct}% of launches hit their target
                date.` : ""}`
        : "No milestone has both a planned and an actual date yet — "
          + "delivery is measured off the Dates table, and it is empty."}</p>
      ${dl.reasons.length ? `<div class="chips">${dl.reasons.map((r) =>
        `<span class="pill">${esc(r.why)} · ${r.n}</span>`).join("")}</div>
        <p class="dim">A date that moved with a reason beside it is a
          project being managed. One that moved silently will move
          again.</p>` : ""}
    </div>`;
}

/* The trading calendar. A month has four weekends or five; Easter moves;
   a holiday closes the shop or triples it. Comparing this month with the
   last without knowing which days were trading days is reporting the
   calendar as performance — and nobody notices, because the number
   always comes out. */
const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function daysSection(d) {
  const c = d.compare;
  const top = Math.max(...d.days.map((x) => x.revenue_cents), 1);
  const bestW = Math.max(...d.weekdays.map((w) => w.avg_cents), 1);
  const arrow = (v) => v === null ? '<span class="dim">—</span>'
    : `<b class="${v > 0 ? "good" : v < 0 ? "low" : ""}">${
      v > 0 ? "+" : ""}${v}%</b>`;
  return `
    <h3>Trading days</h3>
    <div class="card">
      <div class="mrr-heads">
        <div class="mrr-fig"><span class="dim">this month to date</span>
          <b>${money(c.this.revenue_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">same days last month</span>
          <b>${money(c.last.revenue_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">raw</span>
          ${arrow(c.raw_pct)}</div>
        <div class="mrr-fig" title="the same difference with the shape of
          the month taken out — read this one when the two disagree">
          <span class="dim">per trading day</span>
          ${arrow(c.per_day_pct)}</div>
        <div class="mrr-fig"><span class="dim">trading days</span>
          <b>${c.this.trading_days} v ${c.last.trading_days}${
          c.trading_day_gap ? ` (${c.trading_day_gap > 0 ? "+" : ""}${
            c.trading_day_gap})` : ""}</b></div>
      </div>
      <p class="dim">${esc(c.note)}</p>
      <div class="day-strip">${d.days.map((x) => `
        <span class="day-bar${x.holiday ? " day-hol" : ""}${
          x.closed ? " day-shut" : ""}"
          style="height:${Math.max(2, Math.round(
            100 * x.revenue_cents / top))}%"
          title="${x.day} · ${WD[x.weekday]} · ${money(x.revenue_cents)} · ${
            x.orders} order(s)${x.holiday ? " · " + esc(x.holiday) : ""}">
        </span>`).join("")}</div>
      <p class="dim">${d.days.length} days · ${d.trading_days} trading${
        d.closed_days ? ` · ${d.closed_days} shut` : ""} ·
        ${money(d.avg_cents)} on an average trading day${
        d.holiday_lift_pct !== null
          ? ` · holidays run ${d.holiday_lift_pct > 0 ? "+" : ""}${
             d.holiday_lift_pct}% against an ordinary day`
          : d.holidays_n ? ` · ${d.holidays_n} holiday${
             d.holidays_n === 1 ? "" : "s"} in the window, too few to read a
             lift from` : ""}</p>
      <h4 class="mrr-h">By weekday</h4>
      <div class="wd-rows">${d.weekdays.map((w) => `
        <div class="wd-row">
          <span class="wd-n">${WD[w.weekday]}</span>
          <div class="wd-bar"><span style="width:${
            Math.round(100 * w.avg_cents / bestW)}%"></span></div>
          <span class="wd-v">${money(w.avg_cents)}</span>
          <span class="dim">${w.days}d</span>
        </div>`).join("")}</div>
      ${d.holidays.length ? `<h4 class="mrr-h">Marked days in the window</h4>
        <div class="chips">${d.holidays.map((h) => `<span class="pill">${
          esc(h.day)} · ${esc(h.name)} · ${money(h.revenue_cents)}</span>`)
          .join("")}</div>` : ""}
      <div class="page-head cal-add">
        <p class="dim">A closure, a stocktake, a day the doors were shut —
          it belongs beside the public holidays, or every average quietly
          includes a day nothing could have happened on.</p>
        <div class="top-actions">
          <button class="btn alt" id="cal-day">Mark a day</button>
        </div>
      </div>
      ${labourBox(d.labour)}
      ${skyBox(d.sky)}
    </div>`;
}

/* What the hours bought, and whether the rota held. Two numbers that need
   each other: sales per hour says whether the staffing was worth it,
   adherence says whether the staffing that was planned is the staffing
   that happened. Read the first alone and you congratulate yourself on a
   productive day that was two people not turning up. */
function labourBox(l) {
  if (!l || !l.hours) return "";
  const r = l.rota;
  return `<h4 class="mrr-h">Hours</h4>
    <p class="dim">${money(l.per_hour_cents)} of sales per labour hour
      across ${l.hours} hours${l.best_day
        ? `; the best day made ${money(l.best_day.cents)} an hour` : ""}.
      ${r.planned
        ? `${r.adherence_pct}% of ${r.planned} published shift${
           r.planned === 1 ? "" : "s"} were clocked into${r.missed
             ? `, ${r.missed} not at all` : ""}${r.late
             ? `, ${r.late} more than five minutes late (median ${
                r.median_late_min} min)` : ""}.`
        : "No published shifts in the window to measure the clock "
          + "against."}</p>`;
}

/* Weather is not a KPI. "It rained" explains nothing; "wet Saturdays run
   14% under dry ones across eleven of them" is something to staff
   against. So it is only ever reported as a comparison with enough days
   behind it. */
function skyBox(s) {
  if (!s) return "";
  if (!s.enough) {
    return `<h4 class="mrr-h">Weather</h4>
      <div class="page-head cal-add">
        <p class="dim">${esc(s.why || "No weather on these days yet.")}
          It lands on the day beside the money, because "it rained" is not
          a metric and "Saturday was down 18% and it rained" is the start
          of one.</p>
        <div class="top-actions">
          <button class="btn alt" id="sky-get">Fetch the weather</button>
        </div>
      </div>`;
  }
  const line = (x) => x ? `<div class="wd-row sky-row">
      <span class="wd-n">${esc(x.hi_label)}</span>
      <span class="dim">${x.hi_days}d · ${money(x.hi_avg_cents)}</span>
      <span class="wd-n">${esc(x.lo_label)}</span>
      <span class="dim">${x.lo_days}d · ${money(x.lo_avg_cents)}</span>
      <b class="${x.diff_pct > 0 ? "good" : x.diff_pct < 0 ? "low" : ""}">${
        x.diff_pct > 0 ? "+" : ""}${x.diff_pct}%</b>
    </div>` : "";
  return `<h4 class="mrr-h">Weather <span class="dim">${s.have} days</span>
    </h4>
    <div class="wd-rows">${line(s.rain)}${line(s.warm)}${line(s.cloud)}</div>
    <p class="dim">${esc(s.note)}</p>
    <div class="page-head cal-add">
      <p class="dim">Observed, not forecast — afterwards the question is
        what the weather was, and a forecast that was wrong is exactly the
        day you are trying to explain.</p>
      <div class="top-actions">
        <button class="btn alt" id="sky-get">Refresh the weather</button>
      </div>
    </div>`;
}

function markDayForm() {
  modal(`<h3>Mark a day</h3>
    <p class="dim">A day of this company's own. Marking it shut takes it
      out of the trading-day averages, which is the point: an average that
      includes the days you were closed is an average of a different
      business.</p>
    <div class="row2">
      <div><label>Day</label><input id="md-day" type="date"></div>
      <div><label>What it is</label>
        <input id="md-name" placeholder="stocktake, staff party"></div>
    </div>
    <label class="f" style="margin-top:10px">
      <input type="checkbox" id="md-shut" checked> the doors were shut
    </label>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="md-save">Mark it</button></div>`);
  $("#md-save").onclick = async () => {
    if (!$("#md-day").value) return toast("which day?");
    try {
      await api("/api/analytics/calendar", { body: {
        day: $("#md-day").value, name: $("#md-name").value.trim(),
        closed: $("#md-shut").checked, kind: "company" } });
      closeModal(); renderAnalytics();
    } catch (err) { toast(err.message); }
  };
}

/* Recurring revenue, and what moved it. The projection says what next
   month looks like if nothing changes; this says what changed — and the
   four movements add up to the change exactly, because a growth number
   nobody can take apart is a number nobody acts on. */
function mrrSection(d) {
  const last = d.months[d.months.length - 1];
  const bars = d.months.slice(-12);
  const top = Math.max(...bars.map((m) => m.mrr_cents), 1);
  const pct = (v) => (v === null || v === undefined ? "—" : v + "%");
  const moved = (m) => [
    ["new", m.new_cents], ["expansion", m.expansion_cents],
    ["contraction", -m.contraction_cents], ["churn", -m.churn_cents],
  ].filter(([, c]) => c);
  return `
    <h3>Recurring revenue</h3>
    <div class="card">
      <div class="mrr-heads">
        <div class="mrr-fig"><span class="dim">MRR</span>
          <b>${money(last.mrr_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">ARR</span>
          <b>${money(last.arr_cents)}</b></div>
        <div class="mrr-fig"><span class="dim">accounts</span>
          <b>${last.accounts}</b></div>
        <div class="mrr-fig"><span class="dim">ARPA</span>
          <b>${money(last.arpa_cents)}</b></div>
        <div class="mrr-fig" title="of the money that was already here a
          month ago, how much is still here — new customers deliberately
          left out, so it answers whether what you sell keeps being worth
          its price">
          <span class="dim">net revenue retention</span>
          <b class="${last.nrr_pct === null ? ""
            : last.nrr_pct >= 100 ? "good" : "low"}">${
            pct(last.nrr_pct)}</b></div>
        <div class="mrr-fig" title="1 divided by the monthly churn rate —
          how long the average customer stays if this month repeats">
          <span class="dim">avg lifetime</span>
          <b>${d.lifetime.implied_months
            ? d.lifetime.implied_months + " mo" : "—"}</b></div>
        <div class="mrr-fig" title="what one customer is worth over that
          lifetime, at the gross margin the P&L reports — revenue is not
          value, and the difference is what runs the business">
          <span class="dim">lifetime value</span>
          <b>${d.lifetime.ltv_cents
            ? money(d.lifetime.ltv_cents) : "—"}</b></div>
      </div>
      <p class="dim mrr-life">${d.lifetime.implied_months
        ? `Lifetime is 1 ÷ ${d.lifetime.churn_pct}% churn, averaged over
           ${d.lifetime.months_of_churn} month${
           d.lifetime.months_of_churn === 1 ? "" : "s"}${
           d.lifetime.margin_pct
             ? `, valued at the ${d.lifetime.margin_pct}% gross margin the
                P&amp;L reports` : ""}.`
        : "Lifetime needs a churn rate, and a churn rate needs two months "
          + "with a customer lost between them."}${
        d.lifetime.observed_months
          ? ` The plans that have actually ended lasted
             ${d.lifetime.observed_months} months on average
             (${d.lifetime.observed_n}) — biased short, because the ones
             still running are not in it.` : ""}</p>
      ${d.recorded_months < 2 ? `<p class="dim">${d.recorded_months} month
        recorded so far. Movement needs two — the second one is where this
        starts saying anything.</p>` : ""}
      ${d.undated_cancellations ? `<p class="dim">${d.undated_cancellations}
        cancelled plan${d.undated_cancellations === 1 ? " has" : "s have"} no
        date on ${d.undated_cancellations === 1 ? "it" : "them"} — from
        before that was recorded, so ${d.undated_cancellations === 1
          ? "it is" : "they are"} left out of the past rather than guessed
        at. Everything cancelled from now on is dated.</p>` : ""}
      <div class="tablewrap"><table>
        <thead><tr><th>month</th><th>MRR</th><th>new</th><th>expansion</th>
          <th>contraction</th><th>churn</th><th>net new</th><th>NRR</th>
          <th title="customers gained and lost, as a share of the month you
            started with">logos ±</th><th></th></tr></thead>
        <tbody>${bars.map((m) => `<tr${m.seam ? ' class="dim"' : ""}>
          <td>${esc(m.month)}${m.origin === "backfill"
            ? ' <span class="pill" title="reconstructed from subscription '
              + 'start and cancellation dates — invoiced clients are not in '
              + 'it">reconstructed</span>' : ""}</td>
          <td><b>${money(m.mrr_cents)}</b></td>
          <td class="${m.new_cents ? "good" : "dim"}">${m.new_cents
            ? "+" + money(m.new_cents) : "—"}</td>
          <td class="${m.expansion_cents ? "good" : "dim"}">${m.expansion_cents
            ? "+" + money(m.expansion_cents) : "—"}</td>
          <td class="${m.contraction_cents ? "low" : "dim"}">${
            m.contraction_cents ? "−" + money(m.contraction_cents) : "—"}</td>
          <td class="${m.churn_cents ? "low" : "dim"}">${m.churn_cents
            ? "−" + money(m.churn_cents) : "—"}</td>
          <td>${m.seam ? '<span class="dim">—</span>'
            : `<b class="${m.net_new_cents > 0 ? "good"
              : m.net_new_cents < 0 ? "low" : ""}">${
              m.net_new_cents > 0 ? "+" : ""}${money(m.net_new_cents)}</b>`}</td>
          <td class="${m.nrr_pct === null ? "dim"
            : m.nrr_pct >= 100 ? "good" : "low"}">${pct(m.nrr_pct)}</td>
          <td class="dim">${m.logo_new_pct === null ? "—"
            : `<span class="good">+${m.logo_new_pct}%</span> /
               <span class="low">−${m.logo_churn_pct}%</span>`}</td>
          <td style="min-width:120px"><div class="proj-bar">
            <span class="proj-fixed" style="width:${
              Math.round(100 * m.mrr_cents / top)}%"></span></div></td>
        </tr>`).join("")}</tbody></table></div>
      ${bars.some((m) => m.seam) ? `<p class="dim">A greyed row is the seam
        between reconstructed months and recorded ones. The step across it
        is what could not be reconstructed, not business that was won —
        so it is not counted as any.</p>` : ""}
      ${moved(last).length ? `<h4 class="mrr-h">What moved this month</h4>
        <div class="sig-rows">${["new", "expansion", "contraction", "churn"]
          .flatMap((k) => (last.movers[k] || []).map((x) => `
            <div class="doc-line mrr-line">
              <span class="dl-title"><b>${esc(x.label || x.account)}</b></span>
              <span class="pill ${k === "new" || k === "expansion" ? "ok"
                : "warn"}">${k}</span>
              <span class="mrr-amt ${k === "new" || k === "expansion"
                ? "good" : "low"}">${k === "new" || k === "expansion"
                ? "+" : "−"}${money(x.cents)}</span>
            </div>`)).join("")}</div>` : ""}
      <p class="dim">${esc(d.note)}</p>
    </div>`;
}

// ---------- admin ----------

const ROLES = ["customer", "distributor", "influencer", "cashier",
               "employee", "owner"];

async function renderAdmin() {
  const [products, stores, employees, users, emailCfg, emailLog, cyclesList,
         pay, plans, inv] = await Promise.all([
      api("/api/products"), api("/api/stores"), api("/api/admin/employees"),
      api("/api/admin/users"), api("/api/admin/email/config"),
      api("/api/admin/email/log"), api("/api/cycles"),
      api("/api/admin/payments"), api("/api/store/admin/plans"),
      api("/api/inventory").catch(() => [])]);
  view().innerHTML = `
    <h2>Admin</h2>

    <details class="sect" ${pay.enabled ? "" : "open"}><summary>Card payments
      ${pay.enabled ? `<span class="pill ok">on · ${esc(pay.mode)} key
        ····${esc(pay.tail)}</span>`
        : '<span class="pill warn">off — pay on delivery only</span>'}
    </summary>
    <div class="inner">
      <p class="dim">Card payments run on Stripe's own hosted checkout, so no
        card number ever reaches this server. Paste the <b>secret</b> key from
        your Stripe dashboard (Developers → API keys) — the one starting
        <code>sk_</code>, not the publishable <code>pk_</code>.</p>
      <p class="dim">It's checked against Stripe before it's saved, so a typo
        surfaces here rather than at someone's checkout. Start with a
        <code>sk_test_</code> key if you want to try it first — test cards
        won't charge anyone.</p>
      <label class="f">Stripe secret key
        <input id="pay-key" type="password" autocomplete="off"
          placeholder="${pay.key_set ? "saved — paste a new one to replace it"
            : "sk_test_… or sk_live_…"}"></label>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" id="pay-save">Save key</button>
        ${pay.key_set ? `<button class="btn alt danger-hint" id="pay-off"
          >Turn card payments off</button>` : ""}
      </div>
      <p class="dim" id="pay-msg"></p>
    </div></details>
    <details class="sect" open><summary>All users (${users.length})</summary>
    <div class="inner"><div class="tablewrap"><table><thead><tr><th>name</th><th>role</th>
      <th>job</th><th>region</th><th>admin</th><th>active</th><th>sign-in</th></tr></thead><tbody>
      ${users.map((u) => {
        const self = u.id === S.user.id;
        return `<tr class="${u.active ? "" : "dim"}">
          <td>${esc(u.name)}${self ? ' <span class="pill">you</span>' : ""}</td>
          <td>${self ? esc(u.role) : `<select data-ur="${u.id}">
            ${ROLES.map((r) => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}
          </select>`}</td>
          <td>${u.role === "employee" ? `<select data-uj="${u.id}">
              ${(S.meta.jobs || []).map((j) => `<option value="${j}"
                ${j === u.job ? "selected" : ""}>${JOB_LABEL[j] || j}</option>`).join("")}
            </select><select data-ue="${u.id}" title="employment type">
              <option value="employee" ${u.employment === "employee" ? "selected" : ""}>W-2</option>
              <option value="contractor" ${u.employment === "contractor" ? "selected" : ""}>1099</option>
            </select>` : '<span class="dim">—</span>'}</td>
          <td class="dim">${esc(u.region)}</td>
          <td><input type="checkbox" data-ua="${u.id}" ${u.is_admin ? "checked" : ""}
            ${self || u.role === "owner" ? "disabled" : ""}></td>
          <td><input type="checkbox" data-uact="${u.id}" ${u.active ? "checked" : ""}
            ${self ? "disabled" : ""}></td>
          <td>${u.active ? `<button class="btn alt" data-uqr="${u.id}"
            style="padding:3px 9px">QR</button>` : ""}
            ${u.password_set && !self ? `<button class="btn alt"
              data-upw="${u.id}" style="padding:3px 9px"
              title="clear their password; they set a new one at next sign-in">
              reset pw</button>` : ""}</td>
        </tr>`;
      }).join("")}</tbody></table></div>
      <div id="user-qr"></div>
      <div class="dim" style="margin-top:6px">Owners always have admin. Unticking
        "active" blocks sign-in and PIN punches without deleting history.
        <b>QR</b> issues a one-time sign-in link (10&nbsp;min, single use) —
        the user scans it and lands signed in on their phone.</div>
    </div></details>
    <details class="sect"><summary>Branding</summary><div class="inner">
      <form class="inline" id="brand-form">
        <label class="f">brand name <input id="br-name"
          value="${esc(S.meta.brand || "")}"></label>
        <label class="f">tagline <input id="br-tag"
          value="${esc(S.meta.tagline || "")}"
          placeholder="Small batch. Big flavor." style="min-width:220px"></label>
        <label class="f">accent color <input id="br-accent" type="color"
          value="${esc(S.meta.accent || "#35b26b")}"
          style="height:36px;width:60px;padding:2px"></label>
        <button class="btn">Save</button>
      </form>
      <div class="dim" style="margin-top:6px">Name and tagline show in the top
        bar and PWA; the accent recolors buttons, highlights, and charts
        across the whole app.</div>
    </div></details>
    <details class="sect"><summary>Analytics pixels</summary><div class="inner">
      <form class="inline" id="trk-form">
        <label class="f">Google Analytics 4 (G-…)
          <input id="trk-ga" value="${esc(S.meta.tracking?.ga_measurement_id || "")}"
            placeholder="G-XXXXXXXXXX"></label>
        <label class="f">Meta pixel (Facebook + Instagram)
          <input id="trk-meta" value="${esc(S.meta.tracking?.meta_pixel_id || "")}"
            placeholder="1234567890"></label>
        <label class="f">TikTok pixel
          <input id="trk-tt" value="${esc(S.meta.tracking?.tiktok_pixel_id || "")}"
            placeholder="XXXXXXXXXXXXXXXXXX"></label>
        <button class="btn">Save</button>
      </form>
      <div class="dim" style="margin-top:6px">Paste the IDs from each platform's
        ads manager. Empty = that pixel never loads. Instagram is covered by the
        Meta pixel. The storefront then reports view_item / add_to_cart /
        begin_checkout / purchase (with order value) to every configured
        platform, matching the internal funnel.</div>
    </div></details>
    <details class="sect"><summary>Catalog, stores &amp; team</summary>
    <div class="inner">
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-bottom:12px">
      ${products.map((p) => `<div class="product">
        <div class="art">${productArt(p)}</div>
        <div class="body"><div class="name" style="font-size:13px">${esc(p.name)}</div>
          <label class="btn alt" style="text-align:center;font-size:12px;cursor:pointer">
            ${p.image ? "replace photo" : "add photo"}
            <input type="file" accept="image/*" data-img="${p.id}" hidden>
          </label></div>
      </div>`).join("")}
    </div>
    <div class="row">
      <div class="card">
        <h3 style="margin-top:0">Add employee (time-clock PIN)</h3>
        <form class="inline" id="emp-form">
          <input id="emp-name" placeholder="name" required>
          <input id="emp-pin" placeholder="PIN" required>
          <select id="emp-region">${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select>
          <select id="emp-job">${(S.meta.jobs || []).map((j) =>
            `<option value="${j}">${JOB_LABEL[j] || j}</option>`).join("")}</select>
          <select id="emp-empl"><option value="employee">employee (hourly)</option>
            <option value="contractor">contractor (per route)</option></select>
          <button class="btn">Add</button>
        </form>
        <table style="margin-top:8px"><tbody>
          ${employees.map((e) => `<tr><td>${esc(e.name)}</td>
            <td class="dim">${esc(e.region)}</td><td>PIN ${esc(e.pin)}</td></tr>`).join("")}
        </tbody></table>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Add product</h3>
        <form class="inline" id="prod-form" style="flex-direction:column;align-items:stretch">
          <input id="pr-sku" placeholder="SKU" required>
          <input id="pr-name" placeholder="name" required>
          <input id="pr-cat" placeholder="category">
          <input id="pr-price" placeholder="unit price (e.g. 7.99)" required>
          <input id="pr-case" placeholder="case price (e.g. 69.00)" required>
          <button class="btn">Add product</button>
        </form>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Add store</h3>
        <form class="inline" id="store-form" style="flex-direction:column;align-items:stretch">
          <input id="st-name" placeholder="name" required>
          <select id="st-kind"><option value="retail">retail</option>
            <option value="distributor_dc">distributor DC</option></select>
          <select id="st-region">${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select>
          <input id="st-city" placeholder="city">
          <input id="st-lat" placeholder="lat" required>
          <input id="st-lng" placeholder="lng" required>
          <button class="btn">Add store</button>
        </form>
      </div>
    </div>
    </div></details>
    <details class="sect" ${plans.plans.length ? "open" : ""}>
    <summary>Plans — who is on what
      ${plans.active ? `<span class="pill ok">${plans.active} active ·
        ${money(plans.mrr_cents)}/mo</span>` : ""}
      ${plans.invoiced ? `<span class="pill warn">${plans.invoiced}
        invoiced by hand</span>` : ""}</summary><div class="inner">
      ${plans.plans.length ? `<div class="tablewrap"><table class="tbl">
        <thead><tr><th>Customer</th><th>Plan</th><th>Price</th>
          <th>Status</th><th>Billing</th><th>Started</th><th>Pays for</th>
        </tr></thead>
        <tbody>${plans.plans.map((r) => `<tr>
          <td>${esc(r.who)}<div class="dim">${esc(r.email || "")}</div></td>
          <td>${esc(r.plan)}</td>
          <td>${money(r.price_cents * r.qty)}/${esc(r.interval)}</td>
          <td>${r.status === "active" ? '<span class="pill ok">active</span>'
            : `<span class="pill">${esc(r.status)}</span>`}</td>
          <td>${r.payment_ref ? '<span class="pill ok">card</span>'
            : '<span class="pill warn">invoice</span>'}</td>
          <td>${new Date(r.created_at * 1000).toLocaleDateString()}</td>
          <td>${S.meta && S.meta.is_provider ? `<select data-subten="${r.id}"
              title="which install this plan pays for — links the card's
              health to the fleet board">
              <option value="">— not linked —</option>
              ${(plans.tenants || []).map((tid) => `<option value="${esc(tid)}"
                ${r.tenant_id === tid ? "selected" : ""}>${esc(tid)}</option>`
              ).join("")}</select>` : esc(r.tenant_id || "")}</td>
        </tr>`).join("")}</tbody></table></div>` : `<div class="dim">Nobody is
          on a plan yet. A product becomes one by setting its
          <code>billing</code> to <code>month</code> in the store admin.</div>`}
      <div class="dim" style="font-size:12px;margin-top:6px">The monthly
        figure is what each subscriber <b>agreed to</b>, not today's list
        price — the two part company the moment anyone is grandfathered, and
        this is the one that will actually arrive.
        ${plans.card_enabled ? "Cancelling here stops the charge at the "
          + "processor too." : "Card payments are off, so these are billed "
          + "by hand — turn Stripe on above and new plans check out on a "
          + "hosted page."}</div>
    </div></details>

    <details class="sect" ${cyclesList.length ? "open" : ""}>
    <summary>Box cycles (cutoff orchestration)</summary><div class="inner">
      <form class="inline" id="cyc-form">
        <label class="f">month <input id="cy-month" type="month" required></label>
        <button class="btn">Generate from template</button>
        <span class="dim">bill 1st · dunning +5d · curation lock 8th ·
          ship 15th (edit in config: box_cycle)</span>
      </form>
      ${cyclesList.length ? `<div class="tablewrap"><table style="margin-top:8px">
        <thead><tr><th>cycle</th><th>phase</th><th>bill</th><th>dunning ends</th>
        <th>curation locks</th><th>ship</th><th>billed</th><th>skipped</th>
        <th>allocated</th><th>portal</th><th></th></tr></thead><tbody>
        ${cyclesList.map((c) => `<tr class="${c.closed ? "dim" : ""}">
          <td><b>${esc(c.month)}</b></td>
          <td><span class="pill ${{billing: "warn", curation: "warn",
            packing: "ok", shipped: "ok"}[c.phase] || ""}">${c.phase}</span>
            ${c.phase !== "upcoming" && !c.closed && c.billed_count > 0
              && c.allocated_count < c.billed_count && c.phase !== "billing"
              ? '<span class="pill bad">short</span>' : ""}</td>
          <td>${esc(c.bill_date)}</td><td>${esc(c.dunning_close)}</td>
          <td>${esc(c.curation_lock)}</td><td>${esc(c.ship_date)}</td>
          <td><input type="number" data-cyb="${c.id}" value="${c.billed_count}"
            style="width:64px"></td>
          <td><input type="number" data-cys="${c.id}" value="${c.skipped_count}"
            style="width:64px"></td>
          <td><input type="number" data-cya="${c.id}" value="${c.allocated_count}"
            style="width:64px"></td>
          <td>${c.changes_open ? '<span class="pill ok">skip/swap open</span>'
            : '<span class="pill">locked</span>'}</td>
          <td>${c.closed ? "" : `<button class="btn alt" data-cyc-close="${c.id}"
            style="padding:2px 8px">close</button>`}</td>
        </tr>`).join("")}</tbody></table></div>` : `<div class="dim"
          style="margin-top:6px">No cycles yet — generate next month's to start
          the bill → curate → ship clock. Counts sync from your subscription
          provider later; enter them by hand until then.</div>`}
      <div class="dim" style="font-size:12px;margin-top:6px">The sweep warns
        the day before and the day of each cutoff, and flags allocation
        shortfalls after curation lock. <code>/api/cycles/current</code> →
        <code>changes_open</code> is the flag the subscriber portal must obey.</div>
    </div></details>
    <details class="sect"><summary>Email — SMTP, and everything sent</summary>
      <div class="inner">
      <form class="inline" id="email-form">
        <label class="f">SMTP host <input id="em-host"
          value="${esc(emailCfg.host)}" placeholder="smtp.gmail.com"></label>
        <label class="f">port <input id="em-port" type="number"
          value="${emailCfg.port}" style="width:80px"></label>
        <label class="f">username <input id="em-user"
          value="${esc(emailCfg.username)}"></label>
        <label class="f">password <input id="em-pass" type="password"
          placeholder="${emailCfg.password_set ? "(saved)" : ""}"></label>
        <label class="f">from <input id="em-from"
          value="${esc(emailCfg.email_from)}" style="min-width:200px"></label>
        <label class="f">playbooks
          <span><label><input type="checkbox" id="em-cart"
            ${emailCfg.playbooks.abandoned_cart ? "checked" : ""}> abandoned cart</label>
          <label style="margin-left:8px"><input type="checkbox" id="em-winback"
            ${emailCfg.playbooks.winback ? "checked" : ""}> win-back (30d)</label></span></label>
        <button class="btn">Save</button>
      </form>
      <form class="inline" id="email-test-form" style="margin-top:8px">
        <input id="em-test-to" type="email" placeholder="you@example.com"
          value="${esc(S.user.email || "")}">
        <button class="btn alt">Send test email</button>
        <span id="em-test-out" class="dim"></span>
      </form>
      <div class="dim" style="margin-top:6px">These credentials carry
        <b>everything</b> the system sends — signature requests, signing
        receipts, progress updates and client bundles as well as the
        marketing playbooks — and every one of them lands in the log
        below, whichever screen it was sent from. For Gmail: host
        <code>smtp.gmail.com</code>, port <code>587</code>, your address as
        the username, and an <b>app password</b> rather than your own
        (Google Account → Security → 2-Step Verification → App passwords).
        Then send yourself a test before it matters.
        No SMTP host = dry mode: the
        playbooks run and log below, but nothing sends. Abandoned-cart emails
        go to signed-in customers with an email who added to cart 1–48h ago
        and didn't buy (once/week max). Win-back targets customers quiet for
        30+ days (once/30d). Blast a promo from the Promos tab.</div>
      ${emailLog.length ? `<table style="margin-top:8px"><thead><tr>
        <th>when</th><th>to</th><th>kind</th><th>subject</th><th>status</th>
        </tr></thead><tbody>
        ${emailLog.slice(0, 15).map((l) => `<tr>
          <td class="dim">${timeAgo(l.created_at)}</td>
          <td>${esc(l.name || "")} <span class="dim">${esc(l.email || "")}</span></td>
          <td>${esc(l.kind)}</td><td class="dim">${esc(l.subject)}</td>
          <td><span class="pill ${l.status === "sent" ? "ok"
            : l.status === "dry" ? "" : "bad"}">${esc(l.status)}</span></td>
        </tr>`).join("")}</tbody></table>` : ""}
    </div></details>
    <details class="sect"><summary>Inventory
      ${inv.length ? `<span class="pill">${inv.length} row${
        inv.length === 1 ? "" : "s"}</span>` : ""}</summary><div class="inner">
    ${stores.length ? "" : `<p class="dim">No stores yet — inventory lives
      at a store, so add one on the Stores tab first.</p>`}
    <form class="inline" id="inv-form">
      <select id="iv-store">${stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
      <select id="iv-prod">${products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <input id="iv-qty" type="number" placeholder="qty" required style="width:90px">
      <input id="iv-par" type="number" placeholder="par" value="24" style="width:90px">
      <button class="btn">Add / set</button>
    </form>
    ${inv.length ? `<table><thead><tr><th>Store</th><th>Product</th>
      <th>Qty</th><th>Par</th><th></th></tr></thead><tbody>
      ${inv.map((r) => `<tr>
        <td>${esc(r.store_name)}</td><td>${esc(r.product_name)}</td>
        <td><input type="number" value="${r.qty}" style="width:80px"
          data-ivq="${r.store_id}:${r.product_id}"></td>
        <td><input type="number" value="${r.par}" style="width:80px"
          data-ivp="${r.store_id}:${r.product_id}"></td>
        <td><button class="btn alt sm" data-invset="${r.store_id}:${r.product_id}">Set</button>
          <button class="btn alt sm" data-invdel="${r.store_id}:${r.product_id}">Delete</button></td>
      </tr>`).join("")}</tbody></table>` : ""}
    </div></details>`;
  $("#cyc-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/cycles", { body: { month: $("#cy-month").value } });
      toast("cycle generated");
      render();
    } catch (err) { toast(err.message); }
  };
  const cycUpdate = async (cid, patch) => {
    try {
      await api(`/api/admin/cycles/${cid}/update`, { body: patch });
      toast("cycle updated");
    } catch (err) { toast(err.message); render(); }
  };
  document.querySelectorAll("[data-cyb]").forEach((i) => {
    i.onchange = () => cycUpdate(+i.dataset.cyb, { billed_count: +i.value });
  });
  document.querySelectorAll("[data-cys]").forEach((i) => {
    i.onchange = () => cycUpdate(+i.dataset.cys, { skipped_count: +i.value });
  });
  document.querySelectorAll("[data-cya]").forEach((i) => {
    i.onchange = () => cycUpdate(+i.dataset.cya, { allocated_count: +i.value });
  });
  document.querySelectorAll("[data-cyc-close]").forEach((b) => {
    b.onclick = async () => {
      await cycUpdate(+b.dataset.cycClose, { closed: true });
      render();
    };
  });
  document.querySelectorAll("[data-subten]").forEach((sel) => {
    sel.onchange = async () => {
      try {
        await api(`/api/store/admin/plans/${sel.dataset.subten}/tenant`,
          { body: { tenant_id: sel.value } });
        toast(sel.value ? `linked to ${sel.value}` : "unlinked");
      } catch (e) { toast(e.message); }
    };
  });
  $("#brand-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/branding", { body: {
      brand_name: $("#br-name").value, tagline: $("#br-tag").value,
      accent: $("#br-accent").value } });
    S.meta.brand = $("#br-name").value;
    S.meta.tagline = $("#br-tag").value;
    S.meta.accent = $("#br-accent").value;
    $("#brand").innerHTML = esc(S.meta.brand) + (S.meta.tagline
      ? `<span class="tagline">${esc(S.meta.tagline)}</span>` : "");
    document.documentElement.style.setProperty("--accent", S.meta.accent);
    toast("branding saved");
  };
  document.querySelectorAll("[data-img]").forEach((inp) => {
    inp.onchange = () => {
      const file = inp.files[0];
      if (!file) return;
      if (file.size > 2_000_000) return toast("image too large (2 MB max)");
      const rd = new FileReader();
      rd.onload = async () => {
        try {
          await api(`/api/admin/products/${inp.dataset.img}/image`,
            { body: { data_url: rd.result } });
          toast("photo saved");
          render();
        } catch (err) { toast(err.message); }
      };
      rd.readAsDataURL(file);
    };
  });
  const updateUser = async (uid, patch) => {
    try {
      await api(`/api/admin/users/${uid}/update`, { body: patch });
      toast("user updated");
    } catch (err) { toast(err.message); }
    render();
  };
  $("#pay-save").onclick = async () => {
    const b = $("#pay-save"), msg = $("#pay-msg");
    const key = $("#pay-key").value.trim();
    if (!key) return toast("paste a key first");
    b.disabled = true; b.setAttribute("aria-busy", "true");
    msg.textContent = "checking the key with Stripe…";
    try {
      const r = await api("/api/admin/payments", { body: { secret_key: key } });
      $("#pay-key").value = "";
      toast(`Card payments on — ${r.mode} mode`);
      S.meta = await api("/api/meta");     // the checkout form reads this
      renderAdmin();
    } catch (e) {
      msg.innerHTML = `<span class="low">${esc(e.message)}</span>`;
    } finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
  if ($("#pay-off")) $("#pay-off").onclick = async () => {
    if (!confirm("Turn card payments off? Orders fall back to paying on "
      + "delivery.")) return;
    await api("/api/admin/payments", { body: { secret_key: "" } });
    S.meta = await api("/api/meta");
    renderAdmin();
  };
  document.querySelectorAll("[data-ur]").forEach((sel) => {
    sel.onchange = () => updateUser(+sel.dataset.ur, { role: sel.value });
  });
  document.querySelectorAll("[data-ua]").forEach((cb) => {
    cb.onchange = () => updateUser(+cb.dataset.ua, { is_admin: cb.checked });
  });
  document.querySelectorAll("[data-uact]").forEach((cb) => {
    cb.onchange = () => updateUser(+cb.dataset.uact, { active: cb.checked });
  });
  document.querySelectorAll("[data-upw]").forEach((b) => {
    b.onclick = () => updateUser(+b.dataset.upw, { clear_password: true });
  });
  document.querySelectorAll("[data-uj]").forEach((sel) => {
    sel.onchange = () => updateUser(+sel.dataset.uj, { job: sel.value });
  });
  document.querySelectorAll("[data-ue]").forEach((sel) => {
    sel.onchange = () => updateUser(+sel.dataset.ue, { employment: sel.value });
  });
  document.querySelectorAll("[data-uqr]").forEach((b) => {
    b.onclick = async () => {
      try {
        const q = await api(`/api/admin/users/${b.dataset.uqr}/qr`, { body: {} });
        $("#user-qr").innerHTML = `<div style="margin-top:10px">
          One-time sign-in for <b>${esc(q.name)}</b>
          (expires in ${Math.round(q.expires_sec / 60)} min):<br>
          ${qrImg(q.url, 150)}
          <div class="dim" style="font-size:12px">${esc(q.url)}</div></div>`;
      } catch (err) { toast(err.message); }
    };
  });
  $("#trk-form").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/admin/tracking", { body: {
      ga_measurement_id: $("#trk-ga").value,
      meta_pixel_id: $("#trk-meta").value,
      tiktok_pixel_id: $("#trk-tt").value } });
    S.meta.tracking = r.tracking;
    toast("pixels saved — they load on next page load");
  };
  $("#email-test-form").onsubmit = async (e) => {
    e.preventDefault();
    $("#em-test-out").textContent = "sending…";
    try {
      const r = await api("/api/admin/email/test",
        { body: { to: $("#em-test-to").value } });
      $("#em-test-out").innerHTML = r.status === "sent"
        ? '<span class="pill ok">sent — check the inbox</span>'
        : r.status === "dry"
          ? '<span class="pill warn">dry — no SMTP host saved yet</span>'
          : `<span class="pill bad">${esc(r.status)}</span>`;
    } catch (err) { $("#em-test-out").textContent = err.message; }
  };
  $("#email-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/email/config", { body: {
      host: $("#em-host").value, port: +$("#em-port").value || 587,
      username: $("#em-user").value, password: $("#em-pass").value,
      email_from: $("#em-from").value,
      abandoned_cart: $("#em-cart").checked,
      winback: $("#em-winback").checked } });
    toast($("#em-host").value ? "email config saved — live"
      : "saved — dry mode (no SMTP host)");
    render();
  };
  $("#emp-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/employees", { body: { name: $("#emp-name").value,
        pin: $("#emp-pin").value, region: $("#emp-region").value,
        job: $("#emp-job").value, employment: $("#emp-empl").value } });
      toast("employee added");
      render();
    } catch (err) { toast(err.message); }
  };
  $("#prod-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/products", { body: {
      sku: $("#pr-sku").value, name: $("#pr-name").value,
      category: $("#pr-cat").value,
      price_cents: Math.round(parseFloat($("#pr-price").value) * 100),
      case_price_cents: Math.round(parseFloat($("#pr-case").value) * 100) } });
    toast("product added");
    render();
  };
  $("#store-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/stores", { body: {
      name: $("#st-name").value, kind: $("#st-kind").value,
      region: $("#st-region").value, city: $("#st-city").value,
      lat: parseFloat($("#st-lat").value), lng: parseFloat($("#st-lng").value) } });
    toast("store added");
    render();
  };
  $("#inv-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/admin/inventory", { body: {
      store_id: +$("#iv-store").value, product_id: +$("#iv-prod").value,
      qty: +$("#iv-qty").value, par: +$("#iv-par").value } });
    toast("inventory set");
    renderAdmin();
  };
  view().querySelectorAll("[data-invset]").forEach((b) => b.onclick =
    async () => {
      const [sid, pid] = b.dataset.invset.split(":");
      await api("/api/admin/inventory", { body: {
        store_id: +sid, product_id: +pid,
        qty: +view().querySelector(`[data-ivq="${b.dataset.invset}"]`).value,
        par: +view().querySelector(`[data-ivp="${b.dataset.invset}"]`).value,
      } });
      toast("inventory set");
    });
  view().querySelectorAll("[data-invdel]").forEach((b) => b.onclick =
    async () => {
      const [sid, pid] = b.dataset.invdel.split(":");
      await api(`/api/admin/inventory/${sid}/${pid}`, { method: "DELETE" });
      toast("inventory row removed");
      renderAdmin();
    });
}

// ---------- boot ----------

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/ops/sw.js",
    /* never from the HTTP cache: the worker is the thing that
       ships the fix, so it cannot be the thing that arrives
       stale */
    { updateViaCache: "none" }).catch(() => {});
  }
  S.meta = await api("/api/meta").catch(() => S.meta);
  $("#brand").innerHTML = esc(S.meta.brand || "Business Control") +
    (S.meta.tagline ? `<span class="tagline">${esc(S.meta.tagline)}</span>` : "");
  if (S.meta.accent) {
    document.documentElement.style.setProperty("--accent", S.meta.accent);
  }
  initPixels(S.meta.tracking);
  S.ab = await api("/api/ab/active?visitor=" + visitorId()).catch(() => []);
  track("visit");
  if (S.user) { startNotifPoll(); connectWS(); }
  if (S._confirmPay && S.user) {
    try {
      await api(`/api/orders/${S._confirmPay.order_id}/confirm-payment`,
        { body: { session_id: S._confirmPay.session_id } });
      toast(`Payment confirmed for order #${S._confirmPay.order_id}`);
      S.tab = "orders";
    } catch (e) { toast("payment not confirmed: " + e.message); }
    S._confirmPay = null;
  }
  if (S._payCancelled) {
    toast("payment cancelled — your order is saved as pay-on-delivery");
    S._payCancelled = false;
  }
  applyRoute();          // a shared #/clients/3 link opens where it points
  render();
  wireRail();
  // A locked kiosk survives a refresh. Otherwise the way out of it is the
  // reload button, which is no lock at all.
  if (localStorage.getItem("bc_kiosk") === "1" && S.user) {
    api("/api/promos?kind=event").catch(() => []).then((evs) =>
      openKiosk(Array.isArray(evs) ? evs : [], true));
  }
}
boot();
