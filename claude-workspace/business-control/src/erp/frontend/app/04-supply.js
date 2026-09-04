// ---------- sourcing, supply and manufacturing ----------

let SUP = null;

async function renderSupply() {
  SUP = await api("/api/supply");
  const [products, fc] = await Promise.all([
    api("/api/products"), api("/api/supply/forecast").catch(() => null)]);
  const st = SUP.stats;
  const money0 = (c) => money(c);
  const day = (t) => t ? fmtDate(t) : "—";

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Sourcing &amp; supply</h2>
        <p class="dim">Where the product comes from before it's a product:
          who supplies it, what's on hand, what's on order, and what's being
          made. Stock here moves by receipt, run or a recorded adjustment —
          never by typing a new number.</p></div>
      <span class="head-acts">
        <button class="btn alt" id="sp-supplier">Supplier</button>
        <button class="btn alt" id="sp-material">Material</button>
        <button class="btn" id="sp-po">Purchase order</button>
      </span>
    </div>

    <div class="stats">
      <div class="stat"><div class="n">${st.suppliers}</div>
        <div class="l">suppliers</div></div>
      <div class="stat"><div class="n ${st.low ? "low" : ""}">${st.low}</div>
        <div class="l">below reorder</div></div>
      <div class="stat"><div class="n">${st.open_pos}</div>
        <div class="l">open orders</div>
        <div class="d dim">${money0(st.on_order_cents)} committed</div></div>
      <div class="stat"><div class="n">${st.runs_planned}</div>
        <div class="l">runs planned</div></div>
    </div>

    ${fc && (fc.materials.length || fc.products.length) ? `
      <h3>Days of cover</h3>
      <div class="card">
        <p class="dim" style="margin-top:0">At the rate things have actually
          moved over the last ${fc.window_days} days. Anything that hasn't
          moved at all is left out — "we have plenty" and "nobody has touched
          it in a month" look identical in a number and aren't the same
          situation.</p>
        ${fc.materials.length ? `<table>
          <thead><tr><th>material</th><th class="num">on hand</th>
            <th class="num">on order</th><th class="num">per day</th>
            <th class="num">cover</th><th>what to do</th></tr></thead>
          <tbody>${fc.materials.map((m) => `<tr>
            <td>${esc(m.name)}</td>
            <td class="num">${m.on_hand} ${esc(m.unit)}</td>
            <td class="num dim">${m.incoming
              ? `${m.incoming}${m.eta_days != null
                  ? ` <span class="${m.covered_by_order ? "" : "low"}">in ${
                      m.eta_days}d</span>` : ""}` : "—"}</td>
            <td class="num dim">${m.per_day}</td>
            <td class="num ${m.urgent ? "low" : ""}">${m.days_cover} days${
              m.incoming ? `<span class="dim"> → ${
                m.days_cover_with_incoming}</span>` : ""}</td>
            <td>${m.covered_by_order
              ? '<span class="pill ok">covered by an order in transit</span>'
              : m.order_by_days <= 0
                ? `<span class="pill bad">order now — ${m.lead_days}-day lead</span>`
                : `<span class="dim">order within ${m.order_by_days} days</span>`}</td>
          </tr>`).join("")}</tbody></table>` : ""}
        ${fc.products.length ? `<table style="margin-top:12px">
          <thead><tr><th>product</th><th class="num">in stores</th>
            <th class="num">sold/day</th><th class="num">cover</th></tr></thead>
          <tbody>${fc.products.map((p) => `<tr>
            <td>${esc(p.name)}</td><td class="num">${p.on_hand}</td>
            <td class="num dim">${p.per_day}</td>
            <td class="num ${p.urgent ? "low" : ""}">${p.days_cover} days</td>
          </tr>`).join("")}</tbody></table>` : ""}
      </div>` : ""}

    <h3>Materials</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>material</th><th>supplier</th><th class="num">on hand</th>
        <th class="num">incoming</th><th class="num">reorder at</th>
        <th class="num">unit cost</th><th></th></tr></thead>
      <tbody>${SUP.materials.map((m) => `<tr class="${m.active ? "" : "off"}">
        <td><b>${esc(m.name)}</b>${m.code
          ? ` <span class="dim">${esc(m.code)}</span>` : ""}
          ${m.low ? '<span class="pill bad">low</span>' : ""}</td>
        <td class="dim">${esc(m.supplier_name || "—")}</td>
        <td class="num ${m.low ? "low" : ""}">${m.on_hand} ${esc(m.unit)}</td>
        <td class="num dim">${m.incoming ? m.incoming + " " + esc(m.unit) : "—"}</td>
        <td class="num dim">${m.reorder_point}</td>
        <td class="num">${money0(m.unit_cost_cents)}</td>
        <td><button class="btn alt sm" data-adj="${m.id}">Adjust</button>
          <button class="btn alt sm" data-moves="${m.id}">History</button>
          ${rowActions("material", m)}</td>
      </tr>`).join("") || `<tr><td colspan="7" class="dim">
        No materials yet — add the things you buy, then order some.</td></tr>`}
      </tbody></table></div></div>

    <h3>Purchase orders</h3>
    ${SUP.purchase_orders.map((p) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main">
          <b>${esc(p.reference || "PO #" + p.id)}</b>
          <span class="dim">${esc(p.supplier_name)} · ${p.lines.length} line(s)
            · ${money0(p.value_cents)}${p.expected
              ? " · expected " + day(p.expected) : ""}</span>
        </div>
        <span class="pill ${p.status === "received" ? "ok"
          : p.status === "cancelled" ? "bad"
          : p.status === "part" ? "warn" : ""}">${esc(p.status)}</span>
        ${p.status === "draft" ? `<button class="btn alt sm"
          data-posend="${p.id}">Mark sent</button>` : ""}
        ${["sent", "part"].includes(p.status) ? `<button class="btn sm"
          data-porecv="${p.id}">Receive</button>` : ""}
        <button class="btn alt sm" data-polink="${p.id}">${
          p.has_link ? "Supplier link" : "Get supplier link"}</button>
        <button class="btn alt sm" data-rowdel="po:${p.id}">Delete</button>
      </div>
      ${p.confirmed_at ? `<div class="warn-line" style="color:var(--good);
        background:rgba(63,189,130,.1)">Supplier confirmed
        ${fmtDate(p.confirmed_at)}</div>` : ""}
      <table style="margin-top:6px"><tbody>${p.lines.map((l) => `<tr>
        <td>${esc(l.material_name)}</td>
        <td class="num">${l.received}/${l.qty} ${esc(l.unit)}</td>
        <td class="num dim">${money0(l.unit_cost_cents)} each</td>
      </tr>`).join("")}</tbody></table>
    </div>`).join("") || `<div class="card empty"><span class="e-ic">${
      opsIcon("box")}</span><b>Nothing on order</b>
      <p class="dim">A purchase order records what you asked for, so
        receiving it can record what actually turned up.</p></div>`}

    <div class="page-head" style="margin-top:22px">
      <div><h3 style="margin:0">Production runs</h3></div>
      <button class="btn alt" id="sp-run">Schedule a run</button>
    </div>
    ${SUP.runs.map((r) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main">
          <b>${esc(r.product_name || "product #" + r.product_id)}</b>
          <span class="dim">${r.planned_cases} cases planned${
            r.actual_cases ? ` · ${r.actual_cases} made` : ""}${
            r.facility ? " · " + esc(r.facility) : ""}${
            r.scheduled ? " · " + day(r.scheduled) : ""}</span>
        </div>
        <span class="pill ${r.status === "done" ? "ok"
          : r.status === "scrapped" ? "bad" : ""}">${esc(r.status)}</span>
        ${r.status !== "done" && r.status !== "scrapped"
          ? `<button class="btn sm" data-runfin="${r.id}">Finish</button>
             <button class="btn alt sm" data-rowdel="run:${r.id}">Delete</button>`
          : ""}
      </div>
      ${(r.needs || []).length ? `<div class="warn-line">Short for this run:
        ${r.needs.map((n) => `${esc(n.name)} — need ${n.need} ${esc(n.unit)},
          have ${n.have}`).join(" · ")}</div>` : ""}
    </div>`).join("") || '<p class="dim">No runs scheduled.</p>'}

    <div class="page-head" style="margin-top:22px">
      <div><h3 style="margin:0">Inbound freight</h3></div>
      <button class="btn alt" id="sp-ship">Add shipment</button>
    </div>
    ${SUP.shipments.length ? `<div class="card"><table>
      <thead><tr><th>carrier</th><th>tracking</th><th>from</th><th>ETA</th>
        <th>status</th><th></th></tr></thead>
      <tbody>${SUP.shipments.map((sh) => `<tr>
        <td>${esc(sh.carrier || "—")}</td>
        <td class="dim">${esc(sh.tracking || "—")}</td>
        <td class="dim">${esc(sh.origin || "—")}</td>
        <td>${day(sh.eta)}</td>
        <td><select data-shst="${sh.id}">${SUP.ship_status.map((x) =>
          `<option ${x === sh.status ? "selected" : ""}>${x}</option>`).join("")}
        </select></td>
        <td><button class="btn alt sm" data-rowdel="ship:${sh.id}">Delete</button></td>
      </tr>`).join("")}</tbody></table></div>`
      : '<p class="dim">Nothing in transit.</p>'}

    <h3>Recipes</h3>
    <div class="card">
      <p class="dim" style="margin-top:0">What one case consumes. A run uses
        this to work out what it needs and what it used, which is how
        finishing a run can move materials on its own.</p>
      <label>Product</label>
      <select id="sp-bomprod">${products.map((p) =>
        `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <div id="sp-bom" style="margin-top:10px"></div>
    </div>`;

  const refresh = () => renderSupply();
  wireRows({ material: SUP.materials, supplier: SUP.suppliers }, refresh);

  $("#sp-supplier").onclick = () => supplierForm(refresh);
  $("#sp-material").onclick = () => materialForm(refresh);
  $("#sp-po").onclick = () => poForm(refresh);
  $("#sp-run").onclick = () => runForm(products, refresh);
  $("#sp-ship").onclick = () => shipForm(refresh);

  view().querySelectorAll("[data-posend]").forEach((b) => b.onclick = async () => {
    await api(`/api/supply/purchase-orders/${b.dataset.posend}/status`,
              { body: { status: "sent" } });
    refresh();
  });
  view().querySelectorAll("[data-porecv]").forEach((b) => b.onclick = () =>
    receiveForm(+b.dataset.porecv, refresh));
  view().querySelectorAll("[data-polink]").forEach((b) => b.onclick = () =>
    portalLinkForm(+b.dataset.polink, refresh));
  view().querySelectorAll("[data-runfin]").forEach((b) => b.onclick = () =>
    finishForm(+b.dataset.runfin, refresh));
  view().querySelectorAll("[data-adj]").forEach((b) => b.onclick = () =>
    adjustForm(+b.dataset.adj, refresh));
  view().querySelectorAll("[data-moves]").forEach((b) => b.onclick = () =>
    movesFor(+b.dataset.moves));
  view().querySelectorAll("[data-shst]").forEach((sel) => sel.onchange = async () => {
    await api(`/api/supply/shipments/${sel.dataset.shst}/status`,
              { body: { status: sel.value } });
    refresh();
  });

  // Suppliers live under the materials they supply; a separate list of names
  // with nothing next to them isn't worth a section of its own.
  const drawBom = async () => {
    const pid = $("#sp-bomprod").value;
    const { lines } = await api(`/api/supply/bom/${pid}`);
    $("#sp-bom").innerHTML = `
      <table><thead><tr><th>material</th><th class="num">per case</th>
        <th></th></tr></thead><tbody>
        ${lines.map((l) => `<tr><td>${esc(l.material_name)}</td>
          <td class="num">${l.qty_per_case} ${esc(l.unit)}</td>
          <td><button class="btn alt sm" data-bomrm="${l.material_id}"
            >Remove</button></td></tr>`).join("")
          || '<tr><td colspan="3" class="dim">No recipe yet.</td></tr>'}
      </tbody></table>
      <div class="row2" style="margin-top:10px">
        <select id="bom-mat">${SUP.materials.filter((m) => m.active).map((m) =>
          `<option value="${m.id}">${esc(m.name)} (${esc(m.unit)})</option>`).join("")}</select>
        <input id="bom-qty" type="number" step="any" placeholder="qty per case">
        <button class="btn alt" id="bom-add">Add</button>
      </div>`;
    $("#bom-add").onclick = async () => {
      const qty = Number($("#bom-qty").value);
      if (!qty) return toast("how much per case?");
      await api(`/api/supply/bom/${pid}`, { body: {
        material_id: +$("#bom-mat").value, qty_per_case: qty } });
      drawBom();
    };
    $("#sp-bom").querySelectorAll("[data-bomrm]").forEach((b) => b.onclick = async () => {
      await api(`/api/supply/bom/${pid}`, { body: {
        material_id: +b.dataset.bomrm, qty_per_case: 0 } });
      drawBom();
    });
  };
  $("#sp-bomprod").onchange = drawBom;
  if (products.length) drawBom();
}

async function portalLinkForm(pid, refresh, rotate = false) {
  const { url } = await api(
    `/api/supply/purchase-orders/${pid}/portal-link`,
    { body: { rotate } });
  modal(`<h3>Send this to your supplier</h3>
    <p class="dim">They confirm what they can ship and when — no account, no
      sign-in. Finding out about a short shipment now beats finding out on
      the loading dock.</p>
    <input id="po-url" value="${esc(url)}" readonly>
    <div style="text-align:center;padding:14px">${qrImg(url, 150)}</div>
    <p class="dim" style="font-size:12px">This link is the credential —
      anyone it reaches can answer as the supplier. Sent to the wrong
      address, replace it: that issues a new link and stops the old one in
      the same step. Revoke turns it off with nothing in its place.</p>
    <div class="modal-acts">
      <button class="btn alt" data-close>Close</button>
      <button class="btn alt" id="po-rotate">Replace link</button>
      <button class="btn alt danger-hint" id="po-revoke">Revoke</button>
      <button class="btn" id="po-copy">Copy link</button>
    </div>`);
  $("#po-copy").onclick = () => {
    $("#po-url").select();
    navigator.clipboard.writeText(url).then(() => toast("Copied"),
      () => toast("Select the link and copy it"));
  };
  $("#po-rotate").onclick = async () => {
    if (!confirm("Issue a new link? The current one stops working "
      + "immediately — including for the supplier, if they already have it."))
      return;
    closeModal();
    await portalLinkForm(pid, refresh, true);
    toast("New link issued — the old one no longer works");
  };
  $("#po-revoke").onclick = async () => {
    if (!confirm("Revoke this link? Nobody will be able to confirm this "
      + "order until you issue a new one.")) return;
    try {
      await api(`/api/supply/purchase-orders/${pid}/portal-link`,
                { method: "DELETE" });
      closeModal(); toast("Link revoked"); refresh();
    } catch (e) { toast(e.message); }
  };
}

// Purchase orders, runs and shipments delete through the same path as rows.
DELETE_ONLY.po = { title: "purchase order",
  path: (id) => `/api/supply/purchase-orders/${id}`,
  delAsk: "Delete this purchase order? One that has already received stock "
    + "is cancelled instead, so the paperwork still matches the warehouse." };
DELETE_ONLY.run = { title: "run",
  path: (id) => `/api/supply/runs/${id}` };
DELETE_ONLY.ship = { title: "shipment",
  path: (id) => `/api/supply/shipments/${id}` };

function supplierForm(refresh) {
  modal(`<h3>Add a supplier</h3>
    <label>Name</label><input id="su-name">
    <div class="row2">
      <div><label>Kind</label><select id="su-kind">${SUP.kinds.map((k) =>
        `<option>${k}</option>`).join("")}</select></div>
      <div><label>Lead time (days)</label>
        <input id="su-lead" type="number" value="14"></div>
    </div>
    <div class="row2">
      <div><label>Contact</label><input id="su-contact"></div>
      <div><label>Email</label><input id="su-email" type="email"></div>
    </div>
    <div class="row2">
      <div><label>Country</label><input id="su-country"></div>
      <div><label>Terms</label><input id="su-terms" placeholder="net 30"></div>
    </div>
    <p class="dim" style="font-size:12px;margin-top:8px">Lead time is a field
      rather than folklore: most shortages come down to someone assuming a
      shorter one.</p>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="su-save">Add</button></div>`);
  $("#su-save").onclick = async () => {
    try {
      await api("/api/supply/suppliers", { body: {
        name: $("#su-name").value, kind: $("#su-kind").value,
        lead_days: +$("#su-lead").value || 0,
        contact: $("#su-contact").value, email: $("#su-email").value,
        country: $("#su-country").value, terms: $("#su-terms").value } });
      closeModal(); refresh();
    } catch (e) { toast(e.message); }
  };
}

function materialForm(refresh) {
  modal(`<h3>Add a material</h3>
    <div class="row2">
      <div><label>Name</label><input id="ma-name"></div>
      <div><label>Code</label><input id="ma-code"></div>
    </div>
    <div class="row2">
      <div><label>Kind</label><select id="ma-kind">${SUP.kinds.map((k) =>
        `<option>${k}</option>`).join("")}</select></div>
      <div><label>Unit</label><select id="ma-unit">${SUP.units.map((u) =>
        `<option>${u}</option>`).join("")}</select></div>
    </div>
    <label>Supplier</label><select id="ma-sup"><option value="">—</option>
      ${SUP.suppliers.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}
    </select>
    <div class="row2">
      <div><label>Unit cost (cents)</label>
        <input id="ma-cost" type="number" value="0"></div>
      <div><label>Reorder at</label>
        <input id="ma-reorder" type="number" step="any" value="0"></div>
    </div>
    <p class="dim" style="font-size:12px;margin-top:8px">Stock starts at zero.
      Book it in with a purchase order, or use Adjust to record a count.</p>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ma-save">Add</button></div>`);
  $("#ma-save").onclick = async () => {
    try {
      await api("/api/supply/materials", { body: {
        name: $("#ma-name").value, code: $("#ma-code").value,
        kind: $("#ma-kind").value, unit: $("#ma-unit").value,
        supplier_id: $("#ma-sup").value ? +$("#ma-sup").value : null,
        unit_cost_cents: +$("#ma-cost").value || 0,
        reorder_point: +$("#ma-reorder").value || 0 } });
      closeModal(); refresh();
    } catch (e) { toast(e.message); }
  };
}

function poForm(refresh) {
  if (!SUP.suppliers.length) return toast("add a supplier first");
  if (!SUP.materials.length) return toast("add a material first");
  const line = (i) => `<div class="po-line" data-i="${i}">
    <select class="po-mat">${SUP.materials.filter((m) => m.active).map((m) =>
      `<option value="${m.id}" data-cost="${m.unit_cost_cents}"
        >${esc(m.name)} (${esc(m.unit)})</option>`).join("")}</select>
    <input class="po-qty" type="number" step="any" placeholder="qty">
    <input class="po-cost" type="number" placeholder="cents each">
  </div>`;
  modal(`<h3>New purchase order</h3>
    <div class="row2">
      <div><label>Supplier</label><select id="po-sup">${SUP.suppliers
        .filter((s) => s.active).map((s) =>
        `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></div>
      <div><label>Reference</label><input id="po-ref" placeholder="PO-2026-014"></div>
    </div>
    <label>Expected</label><input id="po-eta" type="date">
    <label>Lines</label>
    <div id="po-lines">${line(0)}</div>
    <button class="btn alt sm" id="po-addline">Add a line</button>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="po-save">Create</button></div>`);
  let n = 1;
  $("#po-addline").onclick = () => {
    $("#po-lines").insertAdjacentHTML("beforeend", line(n++));
  };
  $("#po-save").onclick = async () => {
    const lines = [...document.querySelectorAll("#po-lines .po-line")]
      .map((el) => ({
        material_id: +el.querySelector(".po-mat").value,
        qty: Number(el.querySelector(".po-qty").value),
        unit_cost_cents: +el.querySelector(".po-cost").value || 0,
      })).filter((l) => l.qty > 0);
    if (!lines.length) return toast("add at least one line with a quantity");
    const eta = $("#po-eta").value;
    try {
      await api("/api/supply/purchase-orders", { body: {
        supplier_id: +$("#po-sup").value, reference: $("#po-ref").value,
        expected: eta ? Date.parse(eta) / 1000 : 0, lines } });
      closeModal(); refresh();
    } catch (e) { toast(e.message); }
  };
}

function receiveForm(pid, refresh) {
  const po = SUP.purchase_orders.find((p) => p.id === pid);
  const c = po.confirmation;
  /* Three numbers belong on this screen: what we ordered, what they promised,
     and what turned up. Any two of them can agree while the third doesn't,
     and the gap is the whole reason to ask a supplier to confirm. */
  modal(`<h3>Receive ${esc(po.reference || "PO #" + po.id)}</h3>
    <p class="dim">What actually turned up. Partial deliveries are normal —
      the order stays open until every line is satisfied.</p>
    ${c ? `<p class="dim" style="font-size:12px">${esc(c.by)} confirmed this
      on ${fmtDate(c.at)}${c.eta ? `, for ${fmtDate(c.eta)}` : ""}.${
      c.message ? ` “${esc(c.message)}”` : ""}</p>` : ""}
    <table style="margin:8px 0"><thead><tr><th>item</th>
      <th class="num">ordered</th>${c ? '<th class="num">promised</th>' : ""}
      <th class="num">arrived</th></tr></thead>
      <tbody>${po.lines.map((l) => `<tr>
        <td>${esc(l.material_name)}
          <span class="dim">${l.received}/${l.qty} ${esc(l.unit)} so far</span></td>
        <td class="num dim">${l.qty}</td>
        ${c ? `<td class="num ${l.confirmed != null && l.confirmed < l.qty
          ? "low" : "dim"}">${l.confirmed == null ? "—" : l.confirmed}</td>` : ""}
        <td class="num"><input class="inv-n" type="number" step="any"
          data-recv="${l.id}" data-said="${l.confirmed == null ? "" : l.confirmed}"
          max="${l.qty - l.received}" placeholder="0"></td>
      </tr>`).join("")}</tbody></table>
    <div id="recv-gap"></div>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="recv-save">Book in</button></div>`);

  // Say so as it's typed, rather than after the stock has already moved.
  const check = () => {
    const gaps = [];
    document.querySelectorAll("[data-recv]").forEach((el) => {
      const said = el.dataset.said;
      const got = Number(el.value);
      if (said === "" || !got) return;
      if (Math.abs(got - Number(said)) > 1e-9) {
        const row = po.lines.find((l) => String(l.id) === el.dataset.recv);
        gaps.push(`${row.material_name}: ${got} arrived against ${said} promised`);
      }
    });
    $("#recv-gap").innerHTML = gaps.length
      ? `<div class="warn-line">Different from what was confirmed —
         ${gaps.map(esc).join("; ")}. Book what actually arrived; the gap is
         worth raising with them.</div>` : "";
  };
  document.querySelectorAll("[data-recv]").forEach((el) => el.oninput = check);

  $("#recv-save").onclick = async () => {
    const lines = {};
    document.querySelectorAll("[data-recv]").forEach((el) => {
      if (Number(el.value) > 0) lines[el.dataset.recv] = Number(el.value);
    });
    try {
      const r = await api(`/api/supply/purchase-orders/${pid}/receive`,
                          { body: { lines } });
      closeModal();
      toast(r.complete ? "Received in full" : "Partly received — order stays open");
      refresh();
    } catch (e) { toast(e.message); }
  };
}

function runForm(products, refresh) {
  modal(`<h3>Schedule a production run</h3>
    <label>Product</label><select id="rn-prod">${products.map((p) =>
      `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
    <div class="row2">
      <div><label>Cases planned</label><input id="rn-cases" type="number" value="0"></div>
      <div><label>When</label><input id="rn-when" type="date"></div>
    </div>
    <label>Facility</label><input id="rn-fac" placeholder="co-packer or your own line">
    <label>Notes</label><textarea id="rn-notes" rows="2"></textarea>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="rn-save">Schedule</button></div>`);
  $("#rn-save").onclick = async () => {
    const when = $("#rn-when").value;
    try {
      const r = await api("/api/supply/runs", { body: {
        product_id: +$("#rn-prod").value,
        planned_cases: +$("#rn-cases").value || 0,
        scheduled: when ? Date.parse(when) / 1000 : 0,
        facility: $("#rn-fac").value, notes: $("#rn-notes").value } });
      closeModal();
      if (r.shortfall && r.shortfall.length) {
        toast(`Scheduled — short of ${r.shortfall.map((s) => s.name).join(", ")}`);
      }
      refresh();
    } catch (e) { toast(e.message); }
  };
}

function finishForm(rid, refresh) {
  const run = SUP.runs.find((r) => r.id === rid);
  modal(`<h3>Finish this run</h3>
    <p class="dim">Materials are consumed against what was actually made, not
      what was planned — those differ, and the materials followed the real
      number.</p>
    <label>Cases produced</label>
    <input id="fin-cases" type="number" value="${run.planned_cases}">
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="fin-save">Finish</button></div>`);
  $("#fin-save").onclick = async () => {
    try {
      const r = await api(`/api/supply/runs/${rid}/finish`,
        { body: { actual_cases: +$("#fin-cases").value || 0 } });
      closeModal();
      toast(r.went_negative.length
        ? `Done — but ${r.went_negative.join(", ")} went negative, so the `
          + "recipe or the counts need a look"
        : `Done — ${r.cases} cases, materials consumed`);
      refresh();
    } catch (e) { toast(e.message); }
  };
}

function adjustForm(mid, refresh) {
  const m = SUP.materials.find((x) => x.id === mid);
  modal(`<h3>Adjust ${esc(m.name)}</h3>
    <p class="dim">On hand: <b>${m.on_hand} ${esc(m.unit)}</b>. Enter the
      change, not the new total — a count that moves without a reason is the
      thing this screen exists to prevent.</p>
    <label>Change (+ or −)</label>
    <input id="adj-qty" type="number" step="any" placeholder="e.g. -4.5">
    <label>Reason</label>
    <input id="adj-note" placeholder="stocktake, spoilage, breakage…">
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="adj-save">Record</button></div>`);
  $("#adj-save").onclick = async () => {
    try {
      await api(`/api/supply/materials/${mid}/adjust`, { body: {
        qty: Number($("#adj-qty").value), note: $("#adj-note").value } });
      closeModal(); refresh();
    } catch (e) { toast(e.message); }
  };
}

async function movesFor(mid) {
  const m = SUP.materials.find((x) => x.id === mid);
  const rows = await api(`/api/supply/materials/${mid}/moves`);
  modal(`<h3>${esc(m.name)} — every movement</h3>
    <p class="dim">The stock number is the sum of this, not a field someone
      typed.</p>
    <div class="tablewrap" style="max-height:50vh;overflow:auto"><table>
      <thead><tr><th>when</th><th class="num">change</th><th>reason</th>
        <th>who</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td class="dim">${fmtDate(r.created_at)}</td>
        <td class="num ${r.qty < 0 ? "low" : ""}">${r.qty > 0 ? "+" : ""}${r.qty}</td>
        <td>${esc(r.reason)}${r.note ? ` <span class="dim">${esc(r.note)}</span>` : ""}</td>
        <td class="dim">${esc(r.actor || "—")}</td></tr>`).join("")
        || '<tr><td colspan="4" class="dim">No movements yet.</td></tr>'}
      </tbody></table></div>
    <div class="modal-acts"><button class="btn" data-close>Close</button></div>`);
}

function shipForm(refresh) {
  modal(`<h3>Add an inbound shipment</h3>
    <label>Against a purchase order</label>
    <select id="sh-po"><option value="">—</option>
      ${SUP.purchase_orders.map((p) => `<option value="${p.id}"
        >${esc(p.reference || "PO #" + p.id)} — ${esc(p.supplier_name)}</option>`).join("")}
    </select>
    <div class="row2">
      <div><label>Carrier</label><input id="sh-carrier"></div>
      <div><label>Tracking</label><input id="sh-track"></div>
    </div>
    <div class="row2">
      <div><label>From</label><input id="sh-origin"></div>
      <div><label>ETA</label><input id="sh-eta" type="date"></div>
    </div>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="sh-save">Add</button></div>`);
  $("#sh-save").onclick = async () => {
    const eta = $("#sh-eta").value;
    try {
      await api("/api/supply/shipments", { body: {
        po_id: $("#sh-po").value ? +$("#sh-po").value : null,
        carrier: $("#sh-carrier").value, tracking: $("#sh-track").value,
        origin: $("#sh-origin").value,
        eta: eta ? Date.parse(eta) / 1000 : 0 } });
      closeModal(); refresh();
    } catch (e) { toast(e.message); }
  };
}

// ---------- the audit log ----------

async function renderAudit() {
  const d = await api(`/api/admin/audit?limit=300${
    S.auditActor ? "&actor=" + encodeURIComponent(S.auditActor) : ""}${
    S.auditQ ? "&entity=" + encodeURIComponent(S.auditQ) : ""}`);
  view().innerHTML = `
    <h2>Audit log</h2>
    <p class="dim">Every change anyone made, recorded where the changes go
      through rather than inside each screen — so it's complete by
      construction rather than by everyone remembering. Values that look like
      credentials are replaced with a marker; the field names stay, which is
      what you need to reconstruct what happened.</p>
    <p class="dim" style="font-size:12px;margin-top:-4px">Kept for
      ${d.retention.days} days. Anything touching access — permissions, PINs,
      staff, keys, the raw tables — is kept for
      ${Math.round(d.retention.sensitive_days / 365)} years instead: those are
      the rows you go looking for long after the fact, usually because
      something went wrong.${d.oldest
        ? ` Oldest entry here is from ${fmtDate(d.oldest)}.` : ""}</p>

    <div class="filters">
      <input id="au-q" placeholder="Filter by what changed" value="${esc(S.auditQ || "")}">
      <select id="au-actor"><option value="">everyone</option>
        ${d.actors.map((a) => `<option ${a.actor === S.auditActor ? "selected" : ""}
          >${esc(a.actor)}</option>`).join("")}</select>
      <span class="dim">${d.total.toLocaleString()} entries</span>
    </div>

    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>who</th><th>what</th><th>detail</th>
        <th class="num">result</th></tr></thead>
      <tbody>${d.entries.map((e) => `<tr class="${
        e.status >= 400 ? "au-fail" : ""}">
        <td class="dim">${fmtDate(e.created_at)}</td>
        <td>${esc(e.actor || "—")}</td>
        <td><code>${esc(e.action)}</code></td>
        <td class="dim">${esc(e.detail || "")}</td>
        <td class="num"><span class="pill ${e.status >= 400 ? "bad"
          : e.status ? "ok" : ""}">${e.status || "—"}</span></td>
      </tr>`).join("") || `<tr><td colspan="5" class="dim">
        Nothing recorded yet.</td></tr>`}
      </tbody></table></div></div>`;
  let t;
  $("#au-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.auditQ = e.target.value; renderAudit(); }, 250); };
  $("#au-actor").onchange = (e) => { S.auditActor = e.target.value; renderAudit(); };
}

// ---------- the database, directly ----------

async function renderDb() {
  const ov = await api("/api/admin/db");
  if (!S.dbTable) S.dbTable = ov.tables[0] && ov.tables[0].name;
  view().innerHTML = `
    <h2>Database</h2>
    <p class="dim">For the rows no screen covers. Anything that looks like a
      credential is hidden and can't be written from here, identity columns
      are read-only, and there's no free-text SQL box — the value of one is a
      query tool and the cost is a dropped table one paste away. Every change
      lands in the audit log.</p>
    <div class="db-exports">
      <button class="btn alt sm" id="db-json">Export all tables (JSON)</button>
      <button class="btn alt sm" id="db-backup">Download a full backup</button>
      <span class="dim">Exports redact anything credential-shaped, the same
        as the screen. The backup doesn't — a backup with the credentials
        stripped out only looks like one until you need it, so keep it
        somewhere you'd keep the database itself.</span>
    </div>
    <div class="db-wrap">
      <div class="db-tables">${ov.tables.map((t) => `
        <button class="db-t ${t.name === S.dbTable ? "on" : ""}"
          data-dbt="${esc(t.name)}"><b>${esc(t.name)}</b>
          <span class="dim">${t.rows.toLocaleString()}</span></button>`).join("")}
      </div>
      <div class="db-main" id="db-main"></div>
    </div>`;
  view().querySelectorAll("[data-dbt]").forEach((b) => b.onclick = () => {
    S.dbTable = b.dataset.dbt; S.dbOffset = 0; S.dbQ = ""; renderDb();
  });
  $("#db-json").onclick = () => download("/api/admin/db/export.json");
  $("#db-backup").onclick = () => {
    if (!confirm("Download a full backup?\n\n"
      + "It contains everything, credentials included — treat the file the "
      + "way you'd treat the database.")) return;
    download("/api/admin/db/backup.db");
  };
  drawDbTable();
}

async function drawDbTable() {
  const box = $("#db-main");
  if (!box || !S.dbTable) return;
  const off = S.dbOffset || 0;
  let d;
  try {
    d = await api(`/api/admin/db/${encodeURIComponent(S.dbTable)}?limit=50`
      + `&offset=${off}&q=${encodeURIComponent(S.dbQ || "")}`);
  } catch (e) {
    box.innerHTML = `<div class="card dim">${esc(e.message)}</div>`;
    return;
  }
  const cols = d.columns;
  box.innerHTML = `
    <div class="filters">
      <input id="db-q" placeholder="Search ${esc(d.table)}" value="${esc(S.dbQ || "")}">
      <span class="dim">${d.total.toLocaleString()} row(s)</span>
      <button class="btn alt sm" id="db-csv">Export ${esc(d.table)} (CSV)</button>
      ${d.total > d.limit ? `<span class="pager">
        <button class="btn alt sm" id="db-prev" ${off ? "" : "disabled"}>←</button>
        <span class="dim">${off + 1}–${Math.min(off + d.limit, d.total)}</span>
        <button class="btn alt sm" id="db-next"
          ${off + d.limit >= d.total ? "disabled" : ""}>→</button></span>` : ""}
    </div>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr>${cols.map((c) => `<th title="${esc(c.type)}${
        c.locked ? " · read-only" : ""}">${esc(c.name)}${
        c.secret ? " ●" : ""}</th>`).join("")}<th></th></tr></thead>
      <tbody>${d.rows.map((r, i) => `<tr>
        ${cols.map((c) => `<td class="${c.secret ? "dim" : ""}">${
          esc(r[c.name] == null ? "" : String(r[c.name]))}</td>`).join("")}
        <td><button class="btn alt sm" data-dbedit="${i}">Edit</button>
          <button class="btn alt sm" data-dbdel="${i}">Delete</button></td>
      </tr>`).join("") || `<tr><td colspan="${cols.length + 1}" class="dim">
        No rows.</td></tr>`}
      </tbody></table></div></div>`;
  let t;
  $("#db-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.dbQ = e.target.value; S.dbOffset = 0;
      drawDbTable(); }, 250); };
  $("#db-csv").onclick = () =>
    download(`/api/admin/db/${encodeURIComponent(d.table)}/export.csv`);
  if ($("#db-prev")) $("#db-prev").onclick = () => {
    S.dbOffset = Math.max(0, off - d.limit); drawDbTable(); };
  if ($("#db-next")) $("#db-next").onclick = () => {
    S.dbOffset = off + d.limit; drawDbTable(); };

  const pk = (cols.find((c) => c.pk) || {}).name;
  box.querySelectorAll("[data-dbedit]").forEach((b) => b.onclick = () =>
    dbEdit(d, cols, d.rows[+b.dataset.dbedit], pk));
  box.querySelectorAll("[data-dbdel]").forEach((b) => b.onclick = async () => {
    const row = d.rows[+b.dataset.dbdel];
    if (!confirm(`Delete row ${row[pk]} from ${d.table}?\n\n`
      + "Nothing here checks what else points at this row — that's what the "
      + "proper screens are for. This is the raw table.")) return;
    try {
      await api(`/api/admin/db/${encodeURIComponent(d.table)}/${row[pk]}`,
                { method: "DELETE" });
      drawDbTable();
    } catch (e) { toast(e.message); }
  });
}

function dbEdit(d, cols, row, pk) {
  modal(`<h3>${esc(d.table)} · row ${esc(String(row[pk]))}</h3>
    <div class="edit-grid">${cols.map((c) => c.locked
      ? `<label>${esc(c.name)} <span class="dim">${c.secret
          ? "hidden" : "read-only"}</span></label>
         <input value="${esc(row[c.name] == null ? "" : String(row[c.name]))}"
           disabled>`
      : `<label>${esc(c.name)} <span class="dim">${esc(c.type)}</span></label>
         <input data-dbf="${esc(c.name)}"
           value="${esc(row[c.name] == null ? "" : String(row[c.name]))}">`
    ).join("")}</div>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="db-save">Save</button></div>`);
  $("#db-save").onclick = async () => {
    const values = {};
    document.querySelectorAll("#ops-modal [data-dbf]").forEach((el) => {
      values[el.dataset.dbf] = el.value;
    });
    try {
      await api(`/api/admin/db/${encodeURIComponent(d.table)}/${row[pk]}`,
                { method: "PATCH", body: { values } });
      closeModal(); toast("Saved"); drawDbTable();
    } catch (e) { toast(e.message); }
  };
}


/* ---------- the field ----------
   Delivering cases, resetting a shelf, taking a pallet off a truck: four
   departments, one shape. A visit has a place, a list, evidence and a
   moment it was finished — and what makes it evidence rather than a
   claim is that the pictures carry their own coordinates and clock. */
const VISIT_ICON = { delivery: "truck", merchandising: "store",
                     receiving: "box", production: "tools", visit: "pin" };

async function renderField() {
  const [d, inb] = await Promise.all([
    api(`/api/field/visits?days=30${FIELD_MINE ? "&mine=1" : ""}`),
    api("/api/field/inbound").catch(() => null)]);
  const isAdmin = S.user && S.user.is_admin;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Field</h2>
        <p class="dim">Deliveries, merchandising calls, goods coming in.
          Every visit carries its list, its pictures and where they were
          taken — a photo of a shelf proves nothing about which shelf, and
          the same photo with a fix on it proves both.</p></div>
      <div class="top-actions">
        <button class="btn alt${FIELD_MINE ? " on" : ""}" id="fd-mine">${
          FIELD_MINE ? "Everyone's" : "Only mine"}</button>
        ${isAdmin ? `<button class="btn alt" id="fd-tpl">Checklists</button>
          <button class="btn" id="fd-new">${opsIcon("truck", "btn-ic")}
            Book a visit</button>` : ""}
      </div>
    </div>
    <div class="mrr-heads">
      <div class="mrr-fig"><span class="dim">visits, 30 days</span>
        <b>${d.count}</b></div>
      <div class="mrr-fig"><span class="dim">finished</span>
        <b>${d.done}</b></div>
      <div class="mrr-fig" title="finished with nothing left open and
        nothing failed — a visit marked done over a half-ticked list is
        the thing this exists to make visible">
        <span class="dim">clean</span>
        <b class="${d.clean_pct === null ? "" : d.clean_pct >= 80 ? "good"
          : "low"}">${d.clean_pct === null ? "—" : d.clean_pct + "%"}</b></div>
      <div class="mrr-fig"><span class="dim">miles driven</span>
        <b>${d.km}</b></div>
      <div class="mrr-fig"><span class="dim">pictures</span>
        <b>${d.photos}</b></div>
    </div>
    ${inb && inb.deliveries.length ? inboundBox(inb) : ""}
    ${d.failed.length ? `<div class="card alert">
      <b>${d.failed.length} visit${d.failed.length === 1 ? "" : "s"} came
        back with something failed</b>
      <div class="chips">${d.failed.map((f) => `<button class="btn alt sm"
        data-visit="${f.id}">${esc(f.who)} · ${esc(f.failed.join(", "))
        }</button>`).join("")}</div></div>` : ""}
    ${d.visits.length ? `<div class="sig-rows">${d.visits.map((v) => `
      <div class="doc-line fieldline${v.state === "done" ? "" : " dl-awaiting"}"
        data-visit="${v.id}">
        <span class="dl-title">
          <span class="doc-ic">${opsIcon(VISIT_ICON[v.kind] || "pin")}</span>
          <b>${esc(v.title || v.kind)}</b>
          <span class="dim">${esc(v.who)}${v.store
            ? " · " + esc(v.store.name) : ""}</span></span>
        <span class="fl-tags">
          <span class="pill ${v.state === "done" ? "ok"
            : v.state === "abandoned" ? "bad" : "warn"}">${esc(v.state)}</span>
          ${v.failed_steps.length
            ? `<span class="pill bad">${v.failed_steps.length} failed</span>`
            : ""}
          ${v.open_steps ? `<span class="pill warn">${v.open_steps} left
            open</span>` : ""}
        </span>
        <span class="dim fieldline-m">${v.media.length} photo${
          v.media.length === 1 ? "" : "s"}${v.km ? ` · ${v.km} km` : ""}</span>
        <span class="dim fieldline-w">${v.started_at
          ? fmtDate(v.started_at) : "not started"}</span>
      </div>`).join("")}</div>`
      : emptyState("truck", "Nothing in the field yet",
                   "Book a visit, or make a checklist for the kind of call "
                   + "your people actually do.")}`;
  $("#fd-mine").onclick = () => { FIELD_MINE = !FIELD_MINE; renderField(); };
  if ($("#fd-new")) $("#fd-new").onclick = () => bookVisitForm();
  if ($("#fd-tpl")) $("#fd-tpl").onclick = () => templateForm();
  view().querySelectorAll("[data-visit]").forEach((el) =>
    el.onclick = () => openVisit(+el.dataset.visit));
  view().querySelectorAll("[data-meet]").forEach((b) => b.onclick =
    async (ev) => {
      ev.stopPropagation();
      try {
        const r = await api("/api/field/inbound/meet",
                            { body: { po_id: +b.dataset.meet } });
        toast("booked — it is on the field list");
        openVisit(r.id);
      } catch (e) { toast(e.message); }
    });
}

/* What is on its way in. An order the supplier has confirmed is a
   delivery with a date on it; the ones with nobody booked to meet them
   are the ones counted by whoever happens to be near the door, which is
   the receiving that goes wrong. */
function inboundBox(d) {
  return `
    <h3>Coming in</h3>
    ${d.unbooked || d.overdue ? `<p class="dim">${d.unbooked
      ? `${d.unbooked} with nobody booked to meet ${d.unbooked === 1
        ? "it" : "them"}` : ""}${d.unbooked && d.overdue ? " · " : ""}${
      d.overdue ? `${d.overdue} past the date the supplier gave` : ""}.</p>`
      : ""}
    <div class="sig-rows">${d.deliveries.map((x) => `
      <div class="doc-line inbound${x.overdue ? " dl-awaiting" : ""}">
        <span class="dl-title">
          <b>${esc(x.supplier)}</b>
          <span class="dim">${esc(x.reference || "PO " + x.po_id)} ·
            ${x.lines.map((l) => `${l.name} ${
              l.promised !== null && l.promised !== l.outstanding
                ? `${l.promised}${l.unit ? " " + l.unit : ""} of ${
                  l.outstanding}` : l.outstanding + (l.unit
                    ? " " + l.unit : "")}`).join(", ")}</span></span>
        <span class="fl-tags">
          ${x.confirmed
            ? `<span class="pill ok">confirmed${x.confirmed_by
              ? " by " + esc(x.confirmed_by.split(" ")[0]) : ""}</span>`
            : '<span class="pill warn" title="the supplier has not said '
              + 'what is coming or when — this is an order, not yet a '
              + 'delivery">not confirmed</span>'}
        </span>
        <span class="dim inbound-eta">${x.eta
          ? fmtDate(x.eta) : "no date given"}</span>
        <span class="dl-acts inbound-acts">${x.visit
          ? `<button class="btn alt sm" data-visit="${x.visit.id}">${
            x.visit.state === "done" ? "Received" : "Open"}</button>`
          : '<button class="btn alt sm" data-meet="' + x.po_id
            + '">Meet it</button>'}</span>
      </div>`).join("")}</div>`;
}
let FIELD_MINE = false;

async function bookVisitForm() {
  const [tpls, stores, people] = await Promise.all([
    api("/api/field/templates"), api("/api/stores"),
    api("/api/admin/users").catch(() => [])]);
  modal(`<h3>Book a visit</h3>
    <label>Checklist</label>
    <select id="bv-tpl">${tpls.map((t) =>
      `<option value="${t.id}">${esc(t.name)} · ${esc(t.kind)}</option>`)
      .join("") || '<option value="0">none — a bare visit</option>'}</select>
    <div class="row2">
      <div><label>Who</label><select id="bv-who">${people
        .filter((p) => p.active).map((p) =>
          `<option value="${p.id}">${esc(p.name)}</option>`).join("")}
        </select></div>
      <div><label>Where</label><select id="bv-store">
        <option value="0">nowhere in particular</option>
        ${stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`)
          .join("")}</select></div>
    </div>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="bv-go">Book it</button></div>`);
  $("#bv-go").onclick = async () => {
    try {
      await api("/api/field/visits", { body: {
        template_id: +$("#bv-tpl").value || 0,
        user_id: +$("#bv-who").value || 0,
        store_id: +$("#bv-store").value || 0 } });
      closeModal(); renderField();
    } catch (e) { toast(e.message); }
  };
}

function templateForm() {
  modal(`<h3>A checklist</h3>
    <p class="dim">What this kind of call asks. One line per step; put a
      * at the end of a line that wants a picture.</p>
    <div class="row2">
      <div><label>Name</label><input id="tp-name"
        placeholder="Shelf reset"></div>
      <div><label>Kind</label><select id="tp-kind">
        ${["delivery", "merchandising", "receiving", "production", "visit"]
          .map((k) => `<option>${k}</option>`).join("")}</select></div>
    </div>
    <label>Steps</label>
    <textarea id="tp-steps" rows="6" placeholder="Photo of the shelf before *
Face and rotate stock
Check date codes
Photo after *"></textarea>
    <label class="perm"><input type="checkbox" id="tp-sig">
      <span><b>Signed for</b><small>somebody at the place puts their name
        on it — a delivery accepted by "manager" is a delivery nobody
        accepted</small></span></label>
    <label class="perm"><input type="checkbox" id="tp-odo">
      <span><b>Odometer</b><small>read at both ends. Mileage from the
        odometer, not the GPS trail: a phone in a loading bay invents a
        straight line through a building, and mileage is a payment
        </small></span></label>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="tp-go">Save it</button></div>`);
  $("#tp-go").onclick = async () => {
    const steps = $("#tp-steps").value.split("\n").map((l) => l.trim())
      .filter(Boolean).map((l) => ({
        label: l.replace(/\s*\*$/, ""), photo: /\*$/.test(l) }));
    if (!$("#tp-name").value.trim() || !steps.length)
      return toast("a name and at least one step");
    try {
      await api("/api/field/templates", { body: {
        name: $("#tp-name").value.trim(), kind: $("#tp-kind").value, steps,
        needs_signature: $("#tp-sig").checked,
        needs_mileage: $("#tp-odo").checked } });
      closeModal(); toast("checklist saved");
    } catch (e) { toast(e.message); }
  };
}

async function openVisit(vid) {
  const v = await api(`/api/field/visits/${vid}`);
  const live = v.state === "started";
  const draw = () => {
    modalBody().innerHTML = `
      <div class="page-head">
        <div><h3>${esc(v.title || v.kind)}</h3>
          <p class="dim">${esc(v.who)}${v.store
            ? " · " + esc(v.store.name) : ""} · ${esc(v.state)}${
            v.metres_from_store !== null
              ? ` · started ${v.metres_from_store} m from the pin` : ""}</p>
        </div>
        <div class="top-actions">
          ${v.state === "planned"
            ? '<button class="btn" data-vstart>Start</button>' : ""}
          ${live ? '<button class="btn" data-vend>Finish</button>' : ""}
          <button class="btn alt" data-close>Close</button>
        </div>
      </div>
      ${v.steps.length ? `<div class="sig-rows">${v.steps.map((s) => `
        <div class="doc-line vstep vstep-${s.state}">
          <span class="dl-title"><b>${esc(s.label)}</b>
            ${s.note ? `<span class="dim">${esc(s.note)}</span>` : ""}</span>
          <span class="pill ${s.state === "done" ? "ok"
            : s.state === "failed" ? "bad"
            : s.state === "skipped" ? "warn" : ""}">${esc(s.state)}</span>
          <span class="dl-acts vstep-acts">
            ${live ? `<button class="btn alt sm" data-sdone="${s.id}"
              >Done</button>
              <button class="btn alt sm" data-sskip="${s.id}">Skip</button>
              <button class="btn alt sm" data-sfail="${s.id}">Fail</button>
              ${s.wants_photo ? `<label class="btn alt sm phot">Photo
                <input type="file" accept="image/*" capture="environment"
                  data-sphoto="${s.id}" hidden></label>` : "<span></span>"}`
              : ""}
          </span>
        </div>`).join("")}</div>` : ""}
      ${live ? `<div class="page-head cal-add">
        <p class="dim">A picture of anything — the pallet, the paperwork,
          the shelf. It records where and when your phone says it was
          taken.</p>
        <div class="top-actions">
          <label class="btn alt phot">Add a picture
            <input type="file" accept="image/*" capture="environment"
              data-vphoto hidden></label>
        </div></div>` : ""}
      ${v.media.length ? `<h4 class="mrr-h">Evidence</h4>
        <div class="vshots">${v.media.map((m) => `
          <figure class="vshot">
            <img src="/media/visit/${esc(m.token)}" alt="${esc(m.caption)}">
            <figcaption class="dim">${esc(m.caption || m.kind)}<br>
              ${m.lat ? `${m.lat.toFixed(4)}, ${m.lng.toFixed(4)}${
                m.accuracy_m ? ` ±${Math.round(m.accuracy_m)}m` : ""}`
                : "no fix"}<br>${fmtDate(m.taken_at)}</figcaption>
          </figure>`).join("")}</div>` : ""}
      ${v.signature ? `<p class="dim">Signed <b>${esc(v.signature)}</b>${
        v.contact_role ? ` · ${esc(v.contact_role)}` : ""}${
        v.km ? ` · ${v.km} km driven` : ""}</p>` : ""}`;
    wire();
  };
  const again = async () => {
    const fresh = await api(`/api/field/visits/${vid}`);
    Object.assign(v, fresh); draw();
  };
  const shoot = async (file, stepId) => {
    const raw = await new Promise((yes) => {
      const fr = new FileReader();
      fr.onload = () => yes(fr.result);
      fr.readAsDataURL(file);
    });
    const at = await punchWhere();
    try {
      await api("/api/field/photo", { body: {
        visit_id: vid, step_id: stepId || 0, data_url: raw,
        taken_at: Math.round(file.lastModified / 1000) || 0,
        lat: at.lat, lng: at.lng, accuracy_m: at.accuracy_m } });
      again();
    } catch (e) { toast(e.message); }
  };
  function wire() {
    modalBody().querySelectorAll("[data-close]").forEach((b) =>
      b.onclick = closeModal);
    const st = modalBody().querySelector("[data-vstart]");
    if (st) st.onclick = async () => {
      const odo = prompt("Odometer now, if this visit is driven to");
      if (odo === null && !confirm("Start without a reading?")) return;
      const at = await punchWhere();
      try {
        Object.assign(v, await api(`/api/field/visits/${vid}/start`,
          { body: { ...at, odo_km: odo ? +odo : null } }));
        draw();
      } catch (e) { toast(e.message); }
    };
    const en = modalBody().querySelector("[data-vend]");
    if (en) en.onclick = () => finishVisit(v, () => { closeModal();
      renderField(); });
    modalBody().querySelectorAll("[data-sdone]").forEach((b) =>
      b.onclick = async () => {
        await api(`/api/field/steps/${b.dataset.sdone}`,
                  { body: { state: "done" } }).catch((e) => toast(e.message));
        again();
      });
    const why = (id, state) => async () => {
      const note = prompt(state === "skipped" ? "Why skipped?" : "What failed?");
      if (!note || !note.trim()) return;
      try {
        await api(`/api/field/steps/${id}`, { body: { state, note } });
        again();
      } catch (e) { toast(e.message); }
    };
    modalBody().querySelectorAll("[data-sskip]").forEach((b) =>
      b.onclick = why(b.dataset.sskip, "skipped"));
    modalBody().querySelectorAll("[data-sfail]").forEach((b) =>
      b.onclick = why(b.dataset.sfail, "failed"));
    modalBody().querySelectorAll("[data-sphoto]").forEach((inp) =>
      inp.onchange = (e) => e.target.files[0]
        && shoot(e.target.files[0], +inp.dataset.sphoto));
    const one = modalBody().querySelector("[data-vphoto]");
    if (one) one.onchange = (e) => e.target.files[0] && shoot(e.target.files[0]);
  }
  modal("<h3>…</h3>", "wide");
  draw();
}

function finishVisit(v, after) {
  modal(`<h3>Finish ${esc(v.title || v.kind)}</h3>
    ${v.open_steps ? `<div class="card alert"><b>${v.open_steps} step${
      v.open_steps === 1 ? " is" : "s are"} still open.</b>
      <span class="dim">You can close it anyway — the field is not tidy,
        and refusing would only teach people to tick everything. What is
        left open stays on the record.</span></div>` : ""}
    <div class="row2">
      <div><label>Who was there</label>
        <input id="fv-name" placeholder="their name"></div>
      <div><label>Their job</label>
        <input id="fv-role" placeholder="store manager"></div>
    </div>
    <label>They sign <span class="opt">their name, typed by them</span></label>
    <input id="fv-sig" placeholder="name">
    <div class="row2">
      <div><label>Odometer</label>
        <input id="fv-odo" type="number" step="0.1"
          placeholder="${v.start_odo_km || ""}"></div>
      <div><label>Note</label><input id="fv-note"></div>
    </div>
    <div class="modal-foot">
      <button class="btn alt" id="fv-abandon">Could not do it</button>
      <button class="btn" id="fv-go">Finish</button></div>`);
  const send = async (abandon) => {
    const at = await punchWhere();
    const body = { ...at,
      odo_km: $("#fv-odo").value ? +$("#fv-odo").value : null,
      contact_name: $("#fv-name").value.trim(),
      contact_role: $("#fv-role").value.trim(),
      signature: $("#fv-sig").value.trim(),
      note: $("#fv-note").value.trim() };
    if (abandon) {
      const why = prompt("What stopped it?");
      if (!why || !why.trim()) return;
      body.abandon_because = why.trim();
    }
    try {
      const out = await api(`/api/field/visits/${v.id}/finish`, { body });
      closeModal();
      const r = out.received;
      if (r && r.short && r.short.length) {
        toast(`${r.short.length} line${r.short.length === 1 ? "" : "s"} short `
          + "of what the supplier promised — worth saying so now, while the "
          + "driver is here");
      } else if (r && r.short_of_order && r.short_of_order.length) {
        toast(`Booked in. ${r.short_of_order.length} line${
          r.short_of_order.length === 1 ? " is" : "s are"} short of what we `
          + "ordered — but the supplier told us that, so it is the buyer's "
          + "conversation, not the driver's");
      }
      if (after) after();
    } catch (e) { toast(e.message); }
  };
  $("#fv-go").onclick = () => send(false);
  $("#fv-abandon").onclick = () => send(true);
}
