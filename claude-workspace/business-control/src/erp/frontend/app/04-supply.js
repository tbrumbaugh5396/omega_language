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
