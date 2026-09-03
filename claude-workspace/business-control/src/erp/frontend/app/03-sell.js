// ---------- shop ----------



/* A new line. Opened in DRAFT on purpose: the reason this form did not
   exist on the shop page was that adding a product put it straight in
   front of customers, so the only safe place to do it was a settings
   screen nobody thinks to look at. A draft is safe anywhere. */
async function productForm() {
  let kinds = [];
  try { kinds = await api("/api/admin/product-kinds"); } catch (e) { }
  modal(`<h3>New product</h3>
    <p class="dim">It opens as a draft: yours to price and describe, and
      invisible to the shop until you publish it.</p>
    <div class="row2">
      <div><label>Name <span class="req">required</span></label>
        <input id="npd-name"></div>
      <div><label>SKU <span class="opt">how you refer to it</span></label>
        <input id="npd-sku"></div>
    </div>
    <div class="row2">
      <div><label>Kind <span class="opt">the lane it sits in</span></label>
        <select id="npd-kind">${kinds.map((k) => `<option value="${esc(k.id)}"
          ${k.id === "goods" ? "selected" : ""}>${esc(k.label)}</option>`)
          .join("")}</select></div>
      <div><label>Category <span class="opt">free text, shown on the
        card</span></label><input id="npd-cat"></div>
    </div>
    <div class="row2">
      <div><label>Price <span class="req">required</span></label>
        <input id="npd-price" type="number" min="0" step="0.01"></div>
      <div><label>Case price <span class="opt">for distributors; blank
        matches the unit price</span></label>
        <input id="npd-case" type="number" min="0" step="0.01"></div>
    </div>
    <label>Description</label>
    <textarea id="npd-desc" rows="3"></textarea>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="npd-save">Add as a draft</button></div>`);
  $("#npd-save").onclick = async () => {
    const name = $("#npd-name").value.trim();
    const price = Math.round((+$("#npd-price").value || 0) * 100);
    if (!name) return toast("a product needs a name");
    if (!price) return toast("a product needs a price");
    const sku = $("#npd-sku").value.trim()
      || name.toUpperCase().replace(/[^A-Z0-9]+/g, "-").slice(0, 24);
    try {
      await api("/api/admin/products", { body: {
        sku, name, description: $("#npd-desc").value.trim(),
        category: $("#npd-cat").value.trim() || "General",
        price_cents: price, case_size: 12,
        case_price_cents: Math.round((+$("#npd-case").value || 0) * 100)
          || price } });
      const made = (await api("/api/products")).find((p) => p.sku === sku);
      if (made) {
        await api(`/api/admin/products/${made.id}/shelf`, { body: {
          kind: $("#npd-kind").value, draft: true } });
      }
      closeModal();
      toast(`${name} is a draft — publish it when it is ready`);
      renderShop();
    } catch (err) { toast(err.message); }
  };
}

/* Which lane a product sits in, and the lanes themselves. A bakery has
   trays and a studio has retainers; neither is served by being filed
   under Goods, because the lane is how a customer finds it. */
async function kindPicker(pid, prod) {
  let kinds = [];
  try { kinds = await api("/api/admin/product-kinds"); }
  catch (err) { return toast(err.message); }
  modal(`<h3>${esc(prod ? prod.name : "Kind")}</h3>
    <p class="dim">The lane it sits in on the shop's shelf, and the colour
      it wears there.</p>
    <label>Kind</label>
    <select id="kp-kind">${kinds.map((k) => `<option value="${esc(k.id)}"
      ${prod && prod.kind === k.id ? "selected" : ""}>${esc(k.label)}${
      k.custom ? " (yours)" : ""}</option>`).join("")}</select>
    <details class="sect" style="margin-top:12px">
      <summary>A kind of your own</summary>
      <div class="row2">
        <div><label>Name</label><input id="kp-new" placeholder="Trays"></div>
        <div><label>Colour</label>
          <input id="kp-col" type="color" value="#6b7280"></div>
      </div>
      <label>One line about it <span class="opt">shown under the heading on
        the shop</span></label>
      <input id="kp-note" placeholder="baked this morning, gone by noon">
      <button class="btn alt sm" id="kp-add">Add the kind</button>
      ${kinds.filter((k) => k.custom).length ? `<p class="dim"
        style="margin-top:8px">Yours: ${kinds.filter((k) => k.custom)
        .map((k) => `${esc(k.label)} <button class="btn alt sm"
          data-kpdel="${esc(k.id)}">remove</button>`).join(" · ")}</p>` : ""}
    </details>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="kp-save">Save</button></div>`);
  $("#kp-add").onclick = async () => {
    const label = $("#kp-new").value.trim();
    if (!label) return toast("a kind needs a name");
    try {
      await api("/api/admin/product-kinds", { body: {
        label, colour: $("#kp-col").value, note: $("#kp-note").value.trim() } });
      closeModal(); kindPicker(pid, prod);
    } catch (err) { toast(err.message); }
  };
  document.querySelectorAll("[data-kpdel]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/admin/product-kinds/${b.dataset.kpdel}`,
                  { method: "DELETE" });
        closeModal(); kindPicker(pid, prod);
      } catch (err) { toast(err.message); }
    });
  $("#kp-save").onclick = async () => {
    try {
      await api(`/api/admin/products/${pid}/shelf`,
                { body: { kind: $("#kp-kind").value } });
      closeModal(); renderShop();
    } catch (err) { toast(err.message); }
  };
}

/* Products, grouped by what they ARE and tinted by it — the same kinds
   the shop groups by, carried on the row so the two faces of the
   catalogue cannot sort it differently. Order comes from the server; a
   catalogue of one kind is left ungrouped, because a heading that names
   the only thing on the page tells nobody anything. */
function kindGroups(prods) {
  const seen = [];
  prods.forEach((p) => {
    let g = seen.find((x) => x.id === (p.kind || "goods"));
    if (!g) {
      g = { id: p.kind || "goods", label: p.kind_label || "Goods",
            colour: p.colour || "#6b7280", items: [] };
      seen.push(g);
    }
    g.items.push(p);
  });
  return seen.length < 2
    ? [{ id: "", label: "", colour: "", items: prods, only: true }]
    : seen;
}

function productArt(p) {
  if (p.image) return `<img src="/media/product/${p.id}" alt="" loading="lazy">`;
  return opsIcon("bag", "art-ic");
}

async function renderShop() {
  S.products = await api("/api/products");
  const hero = S.ab[0];
  const isDist = S.user && S.user.role === "distributor";
  view().innerHTML = `
    ${hero ? `<div class="hero ${esc(hero.theme)}">
        <div class="h">${esc(hero.headline)}</div>
        <button class="btn" id="hero-cta">${esc(hero.cta)}</button>
      </div>` : ""}
    <div class="page-head">
      <div><h2>Shop ${isDist
        ? '<span class="pill ok">wholesale — priced per case</span>' : ""}
        </h2></div>
      <div class="top-actions">
        ${S.products.some((p) => ["pack", "bundle"].includes(p.kind))
          ? `<a class="btn alt" href="/plan-builder" target="_blank"
               title="the capability menu with a running total — the page a
               client can price themselves on">${opsIcon("tools", "btn-ic")}
               Plan builder</a>` : ""}
        ${S.user && S.user.is_admin ? `<button class="btn" id="sh-new"
          title="a new line, in draft — it stays off the shop until you
          publish it">${opsIcon("bag", "btn-ic")} New product</button>` : ""}
      </div>
    </div>
    ${kindGroups(S.products).map((g) => `
      ${g.label ? `<h3 class="kind-head" style="--kind:${esc(g.colour)}">
        ${esc(g.label)} <small class="dim">${g.items.length} line${
          g.items.length === 1 ? "" : "s"}</small></h3>` : ""}
      <div class="grid">${g.items.map((p) => `
      <div class="product" data-p="${p.id}" style="--kind:${esc(g.colour)}">
        <div class="art">${productArt(p)}</div>
        <div class="body">
          <div class="name">${esc(p.name)}</div>
          <div class="dim" style="font-size:12px">${esc(p.category)} · ${esc(p.sku)}${
            p.unlisted ? ' · <span class="pill warn">not on the shelf</span>'
              : ""}${p.draft
            ? ' · <span class="pill warn">draft</span>' : ""}</div>
          <div class="price">${isDist
            ? `${money(p.case_price_cents)} <span class="dim"
                style="font-size:12px;font-weight:400">/ case of ${p.case_size}</span>`
            : money(p.price_cents)}${p.quote
            ? ' <span class="dim" style="font-size:12px;font-weight:400">'
              + "from — quoted after discovery</span>" : ""}</div>
          ${p.quote ? "" : `<div class="stepper" data-step="${p.id}">
            <button data-dec="${p.id}" aria-label="remove one">−</button>
            <span class="q" data-q="${p.id}">${S.cart[p.id] || 0}</span>
            <button data-inc="${p.id}" aria-label="add one">+</button>
          </div>`}
          ${rowActions("product", p)}
          ${p.unlisted ? "" : `<button class="btn alt sm"
            data-shelf="${p.id}:${p.draft ? 0 : 1}"
            title="${p.draft
              ? "put it on the shop's shelf"
              : "take it off the shelf while you work on it — the back "
                + "office still sees it"}">${p.draft
              ? "Publish" : "Unpublish"}</button>
          <button class="btn alt sm" data-kind="${p.id}"
            title="which lane it sits in on the shelf">Kind</button>`}
        </div>
      </div>`).join("")}
    </div>`).join("")}
    <div class="card" style="margin-top:14px" id="cart-card"></div>
    <div id="checkout-box"></div>`;

  const setQty = (id, qty) => {
    if (qty <= 0) delete S.cart[id];
    else S.cart[id] = qty;
    const q = document.querySelector(`[data-q="${id}"]`);
    if (q) q.textContent = S.cart[id] || 0;
    renderCartCard();
  };
  const renderCartCard = () => {
    const lines = Object.entries(S.cart).map(([pid, qty]) => {
      const p = S.products.find((x) => x.id === +pid);
      return p ? { p, qty } : null;
    }).filter(Boolean);
    const subtotal = lines.reduce((a, l) => a + l.qty *
      (isDist ? l.p.case_price_cents : l.p.price_cents), 0);
    $("#cart-card").innerHTML = !lines.length
      ? `<span class="dim">Your cart is empty — use the + on any product.</span>
         ${S.user ? "" : ' <span class="dim">Sign in to place an order.</span>'}`
      : `${lines.map((l) => `<div class="cartline">
          <span class="n">${esc(l.p.name)}
            <span class="dim">${isDist ? "case" : "unit"} ×</span></span>
          <div class="stepper">
            <button data-cdec="${l.p.id}">−</button>
            <span class="q">${l.qty}</span>
            <button data-cinc="${l.p.id}">+</button>
          </div>
          <span class="num" style="min-width:70px;text-align:right">
            ${money(l.qty * (isDist ? l.p.case_price_cents : l.p.price_cents))}</span>
          <button class="x" data-cdel="${l.p.id}" title="remove">✕</button>
        </div>`).join("")}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
          <b>Subtotal ${money(subtotal)}</b>
          <span>
            ${localStorage.getItem("bc_ref") ? `<span class="pill ok">referred
              by ${esc(localStorage.getItem("bc_ref"))}</span>` : ""}
            <button class="btn" id="checkout">Checkout</button>
          </span>
        </div>`;
    $("#cart-card").querySelectorAll("[data-cinc]").forEach((b) => {
      b.onclick = () => setQty(+b.dataset.cinc, (S.cart[b.dataset.cinc] || 0) + 1);
    });
    $("#cart-card").querySelectorAll("[data-cdec]").forEach((b) => {
      b.onclick = () => setQty(+b.dataset.cdec, (S.cart[b.dataset.cdec] || 0) - 1);
    });
    $("#cart-card").querySelectorAll("[data-cdel]").forEach((b) => {
      b.onclick = () => setQty(+b.dataset.cdel, 0);
    });
    const co = $("#checkout");
    /* Signed out, this is still the button you press — it just goes to the
       sign-in first. Disabling it left someone with a full cart and no
       affordance except a line of grey text that wasn't a link. The cart is
       held in memory and survives the tab change, so they come back to it. */
    // Signed in or not — an account is offered at the delivery step, not
    // demanded before it. Making someone register before they can see what
    // shipping costs is how a full cart becomes an abandoned one.
    if (co) co.onclick = onCheckout;
  };

  document.querySelectorAll("[data-inc]").forEach((b) => {
    b.onclick = () => {
      setQty(+b.dataset.inc, (S.cart[b.dataset.inc] || 0) + 1);
      track("add_to_cart", { product_id: +b.dataset.inc });
    };
  });
  document.querySelectorAll("[data-dec]").forEach((b) => {
    b.onclick = () => setQty(+b.dataset.dec, (S.cart[b.dataset.dec] || 0) - 1);
  });
  document.querySelectorAll(".product").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest(".stepper")) return;
      track("view_product", { product_id: +el.dataset.p });
    };
  });
  if ($("#hero-cta")) $("#hero-cta").onclick = () =>
    window.scrollTo({ top: 300, behavior: "smooth" });
  const isDistributor = S.user && S.user.role === "distributor";

  const cartTotals = (method) => {
    let subtotal = 0;
    for (const [pid, qty] of Object.entries(S.cart)) {
      const p = S.products.find((x) => x.id === +pid);
      if (p) subtotal += qty *
        (isDistributor ? p.case_price_cents : p.price_cents);
    }
    const tax = isDistributor ? 0
      : Math.floor(subtotal * (S.meta.tax_bps || 0) / 10000);
    /* Delivery is priced for whichever option is selected, by the same rule
       the server applies: standard (position 0) is free over the threshold,
       anything faster is paid for however big the order. A checkout that
       quotes one number and charges another is worse than one quoting
       nothing. */
    const free = subtotal >= (S.meta.free_shipping_over_cents || 0);
    let shipping;
    if (isDistributor || !subtotal) shipping = 0;
    else if (method) shipping = (method.position === 0 && free)
      ? 0 : method.price_cents;
    else shipping = free ? 0 : (S.meta.shipping_flat_cents || 0);
    return { subtotal, tax, shipping, total: subtotal + tax + shipping };
  };

  const placeOrder = async (extra) => {
    const items = Object.entries(S.cart).map(([pid, qty]) =>
      ({ product_id: +pid, qty }));
    track("checkout");
    try {
      const o = await api("/api/orders", { body: {
        items, visitor_id: visitorId(),
        affiliate_code: localStorage.getItem("bc_ref") || "", ...extra } });

      /* Paying on delivery holds the first order from an unconfirmed
         address, so there is no order number to report yet — saying one was
         placed would be a lie, and the customer would sit waiting for goods
         that were never ordered. */
      if (o.awaiting_confirmation) {
        S.cart = {};
        $("#checkout-box").innerHTML = `<div class="card">
          <h3 style="margin-top:0">Check your email</h3>
          <p>We've sent a link to <b>${esc(o.email)}</b>. Because you're
            paying on delivery, we confirm the address before sending
            anything — one click and the order is placed.</p>
          <p class="dim">The link works for ${o.expires_in_days} days.
            Nothing has been ordered until you use it. Prefer not to wait?
            Paying by card skips this step.</p>
        </div>`;
        $("#checkout-box").scrollIntoView({ behavior: "smooth" });
        renderCartCard();
        return;
      }

      track("purchase", { value_cents: o.total_cents || o.subtotal_cents });
      S.cart = {};
      if (o.checkout_url) {
        toast("redirecting to secure payment…");
        location.href = o.checkout_url;   // Stripe's hosted page
        return;
      }
      toast(`Order #${o.id} placed — ${money(o.total_cents)}`
        + (o.payment_status === "cod" ? " (pay on delivery)" : ""));
      if (!S.user) {
        /* A guest has no order history to send them to — the Orders tab
           would bounce them to a sign-in, which is a poor thing to meet
           immediately after paying. Confirm it here instead. */
        renderShop().then(() => {
          $("#checkout-box").innerHTML = `<div class="card">
            <h3 style="margin-top:0">Order #${o.id} placed</h3>
            <p>Thank you. A receipt is on its way to
              <b>${esc(extra.email || "your email")}</b>, and tracking follows
              when it ships.</p>
            <p class="dim">Want to see it later? Sign in with that email and
              this order will be waiting.</p>
            <button class="btn alt" id="ok-signin">Sign in</button>
          </div>`;
          $("#checkout-box").scrollIntoView({ behavior: "smooth" });
          $("#ok-signin").onclick = () => { S.tab = "login"; render(); };
        });
        return;
      }
      S.tab = "orders";
      render();
    } catch (e) { toast(e.message); }
  };

  const onCheckout = async () => {
    if (!Object.keys(S.cart).length) return toast("cart is empty");
    if (isDistributor) return placeOrder({});     // wholesale ships on terms

    const methods = await api("/api/store/shipping").catch(() => []);
    /* Whether an email is still needed depends on the account, not on
       whether someone is signed in. An owner, or a customer whose address
       was never confirmed, has to give one too — otherwise the form offers
       no way to supply what the server is about to insist on, and
       pay-on-delivery dead-ends on an error with nothing to type into. */
    const me = S.user ? await api("/api/me").catch(() => null) : null;
    const needEmail = !me || !me.email || !me.email_confirmed;

    const chosen = () => methods.find((m) => String(m.id) === S.shipMethod)
      || methods[0];

    const draw = () => {
      const m = chosen();
      const t = cartTotals(m);
      const paying = ($("#sh-pay") || {}).value
        || (S.meta.stripe_enabled ? "card" : "cod");
      $("#checkout-box").innerHTML = `
      <div class="card checkout-card">
        <h3 style="margin-top:0">Delivery details</h3>
        ${S.user ? "" : `<p class="dim">No account needed — the email is
          where the receipt and tracking go. You can
          <a id="sh-signin">sign in</a> instead if you'd rather see this
          order in your history.</p>`}
        <form id="ship-form">
          <input id="sh-name" placeholder="full name"
            value="${esc(S.user ? S.user.name : "")}" required>
          ${needEmail ? `<input id="sh-email" type="email" required
            value="${esc(me && me.email ? me.email : "")}"
            placeholder="email — for the receipt and tracking"
            autocomplete="email">` : ""}
          <input id="sh-addr" placeholder="street address" required>
          <div class="row2">
            <input id="sh-city" placeholder="city" required style="flex:1">
            <input id="sh-postal" placeholder="ZIP" style="width:90px">
          </div>
          <input id="sh-phone" placeholder="phone (optional)">

          ${methods.length ? `<div class="ship-opts">
            <div class="dim">Delivery</div>
            ${methods.map((x) => {
              const price = (x.position === 0
                && t.subtotal >= (S.meta.free_shipping_over_cents || 0))
                ? 0 : x.price_cents;
              return `<label class="ship-opt ${
                m && x.id === m.id ? "on" : ""}">
                <input type="radio" name="shipm" value="${x.id}"
                  ${m && x.id === m.id ? "checked" : ""}>
                <span class="s-n"><b>${esc(x.name)}</b>
                  ${x.eta ? `<span class="dim">${esc(x.eta)}</span>` : ""}</span>
                <span class="s-p">${price ? money(price) : "FREE"}</span>
              </label>`;
            }).join("")}
          </div>` : ""}

          ${S.meta.stripe_enabled ? `<label class="f">Payment
            <select id="sh-pay">
              <option value="card" ${paying === "card" ? "selected" : ""}
                >Card — pay now</option>
              <option value="cod" ${paying === "cod" ? "selected" : ""}
                >Pay on delivery</option></select></label>`
          : `<div class="dim">Payment: on delivery (card payments aren't
             set up)</div>`}

          ${paying === "cod" ? `<div class="cod-note">Paying on delivery, so
            the email gets confirmed before anything is dispatched — you'll
            get a link, and nothing is delivered until it's used.</div>` : ""}

          <div class="dim">subtotal ${money(t.subtotal)} · tax ${money(t.tax)}
            · delivery ${t.shipping ? money(t.shipping) : "FREE"} ·
            <b style="color:var(--text)">total ${money(t.total)}</b></div>
          <button class="btn">Place order — ${money(t.total)}</button>
        </form>
      </div>`;

      // Re-draw on either choice: both move the total, and a total that only
      // updates when you submit is a total nobody believes.
      $("#checkout-box").querySelectorAll('[name="shipm"]').forEach((r) => {
        r.onchange = () => { S.shipMethod = r.value; draw(); };
      });
      if ($("#sh-pay")) $("#sh-pay").onchange = draw;
      if ($("#sh-signin")) {
        $("#sh-signin").onclick = () => {
          S.afterLogin = "shop"; S.tab = "login"; render();
        };
      }
      $("#ship-form").onsubmit = submit;
    };

    const submit = (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button.btn");
      btn.disabled = true; btn.setAttribute("aria-busy", "true");
      const paySel = $("#sh-pay");
      const email = $("#sh-email");
      const m = chosen();
      placeOrder({
        ship_name: $("#sh-name").value, address: $("#sh-addr").value,
        city: $("#sh-city").value, postal: $("#sh-postal").value,
        phone: $("#sh-phone").value,
        email: email ? email.value : "",
        shipping_method_id: m ? m.id : null,
        pay_method: paySel ? paySel.value : "cod" })
        .finally(() => {
          btn.disabled = false; btn.removeAttribute("aria-busy");
        });
    };

    draw();
    $("#checkout-box").scrollIntoView({ behavior: "smooth" });
  };

  renderCartCard();
  if ($("#sh-new")) $("#sh-new").onclick = () => productForm();
  view().querySelectorAll("[data-shelf]").forEach((b) => b.onclick =
    async () => {
      const [pid, draft] = b.dataset.shelf.split(":");
      try {
        await api(`/api/admin/products/${pid}/shelf`,
                  { body: { draft: draft === "1" } });
        toast(draft === "1" ? "off the shelf — still here" : "on the shelf");
        renderShop();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-kind]").forEach((b) => b.onclick =
    () => kindPicker(+b.dataset.kind, S.products.find(
      (p) => p.id === +b.dataset.kind)));
  wireRows({ product: S.products }, renderShop);
}

// ---------- orders ----------

async function renderOrders() {
  if (!S.user) { S.tab = "login"; return renderLogin(); }
  const isAdmin = S.user.is_admin;
  const orders = await api("/api/orders" + (isAdmin ? "?all=1" : ""));
  const statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"];
  const payPill = (o) => {
    const cls = o.payment_status === "paid" ? "ok"
      : o.payment_status === "unpaid" ? "bad" : "warn";
    return `<span class="pill ${cls}">${esc(o.payment_status || "")}</span>`;
  };
  view().innerHTML = `
    <h2>${isAdmin ? "All orders" : "My orders"}</h2>
    <div class="card"><table><thead><tr>
      <th>#</th>${isAdmin ? "<th>who</th>" : ""}<th>kind</th><th>items</th>
      <th>total</th><th>payment</th>${isAdmin ? "<th>ship to</th>" : ""}
      <th>region</th><th>status</th>${isAdmin ? "<th></th><th></th>" : ""}
    </tr></thead><tbody>
    ${orders.map((o) => `<tr>
      <td>${o.id}</td>${isAdmin ? `<td>${esc(o.user_name)}</td>` : ""}
      <td>${o.kind}</td>
      <td class="dim">${o.items.map((i) => `${esc(i.name)}×${i.qty}`).join(", ")}</td>
      <td title="subtotal ${money(o.subtotal_cents)} · tax ${money(o.tax_cents || 0)}
        · shipping ${money(o.shipping_cents || 0)}">
        ${money(o.total_cents || o.subtotal_cents)}</td>
      <td>${payPill(o)}
        ${isAdmin && o.payment_status !== "paid" ? `<button class="btn alt"
          data-paid="${o.id}" style="padding:2px 8px">mark paid</button>` : ""}</td>
      ${isAdmin ? `<td class="dim" style="font-size:12px">
        ${esc(o.ship_name || "")}${o.address ? ", " + esc(o.address) : ""}
        ${o.city ? ", " + esc(o.city) : ""} ${esc(o.postal || "")}</td>` : ""}
      <td>${esc(o.region)}</td>
      <td><span class="pill ${o.status === "delivered" ? "ok" :
        o.status === "cancelled" ? "bad" : ""}">${o.status}</span></td>
      ${isAdmin ? `<td><select data-o="${o.id}">
        ${statuses.map((s) => `<option ${s === o.status ? "selected" : ""}>${s}</option>`).join("")}
      </select></td>
      <td>${rowActions("order", o)}</td>` : ""}
    </tr>`).join("")}</tbody></table>
    <div id="awaiting"></div>
    ${orders.length ? "" : emptyState("box", "No orders yet",
      isAdmin ? "They'll appear here the moment a customer checks out."
      : "Head to the Shop, add something to your cart, and check out.")}</div>`;
  /* Orders held for email confirmation. They aren't in the orders table —
     that is what keeps them out of revenue — but staff still have to see
     that someone asked for them, or the demand is invisible. */
  if (isAdmin) {
    api("/api/admin/orders/awaiting").then((waiting) => {
      if (!waiting.length || !$("#awaiting")) return;
      $("#awaiting").innerHTML = `<h3>Waiting on email confirmation
        (${waiting.length})</h3>
        <div class="card"><p class="dim" style="margin-top:0">Paying on
          delivery, so nothing is dispatched until the address is confirmed.
          These aren't orders yet and aren't counted anywhere.</p>
        <table><thead><tr><th>who</th><th>email</th><th>where</th>
          <th class="num">items</th><th>asked</th><th></th></tr></thead>
        <tbody>${waiting.map((w) => `<tr>
          <td>${esc(w.name)}</td><td class="dim">${esc(w.email)}</td>
          <td class="dim">${esc(w.city || "—")}</td>
          <td class="num">${w.items}</td>
          <td class="dim">${timeAgo(w.created_at)}</td>
          <td><button class="btn alt sm" data-resend="${w.id}"
            >Resend link</button></td></tr>`).join("")}
        </tbody></table></div>`;
      $("#awaiting").querySelectorAll("[data-resend]").forEach((b) => {
        b.onclick = async () => {
          try {
            const r = await api(
              `/api/admin/orders/awaiting/${b.dataset.resend}/resend`,
              { method: "POST" });
            toast(`Link sent again to ${r.email}`);
          } catch (e) { toast(e.message); }
        };
      });
    }).catch(() => {});
  }
  document.querySelectorAll("[data-o]").forEach((sel) => {
    sel.onchange = async () => {
      await api(`/api/admin/orders/${sel.dataset.o}/status`,
        { body: { status: sel.value } });
      toast(sel.value === "shipped"
        ? "updated — stock consumed at the fulfilling store" : "updated");
    };
  });
  document.querySelectorAll("[data-paid]").forEach((b) => {
    b.onclick = async () => {
      await api(`/api/admin/orders/${b.dataset.paid}/paid`, { body: {} });
      toast("marked paid");
      render();
    };
  });
  wireRows({ order: orders }, renderOrders);
}

// ---------- time clock ----------

async function renderClock() {
  const mine = S.user ? await api("/api/shifts").catch(() => []) : [];
  // an open shift is one with no clock_out: the button says the verb that
  // is actually available rather than making somebody guess
  const mineOpen = mine.some((sh) => !sh.clock_out);
  const isAdmin = S.user && S.user.is_admin;
  const all = isAdmin ? await api("/api/shifts?all=1") : [];
  const events = await api("/api/promos?kind=event").catch(() => []);
  const fmt = (t) => new Date(t * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  view().innerHTML = `
    <h2>Time Clock</h2>
    <div class="card punch-card">
      <label class="dim" for="pin">Enter your PIN to clock in or out</label>
      <input id="pin" type="password" inputmode="numeric" placeholder="••••"
        autocomplete="off">
      ${events.length ? `<select id="clock-event">
        <option value="">Regular shift</option>
        ${events.map((ev) => `<option value="${ev.id}">Event: ${esc(ev.name)}${
          ev.city ? " (" + esc(ev.city) + ")" : ""}</option>`).join("")}
        </select>` : ""}
      <div class="punch-acts">
        ${S.user ? `<button class="btn" id="punch-me"
          title="you are already signed in — starting your own shift does
          not need a second secret">${mineOpen ? "Clock out" : "Clock in"}
          as ${esc(S.user.name)}</button>` : ""}
        <button class="btn${S.user ? " alt" : ""}" id="punch">Punch</button>
        <button class="btn alt" id="badge-btn"
          title="scan an employee badge instead of typing a PIN">${
          opsIcon("camera", "btn-ic")} Scan a badge</button>
        <button class="btn alt" id="kiosk-btn"
          title="full-screen keypad for the store tablet">Kiosk mode</button>
        ${S.user ? `<button class="btn alt" id="kiosk-lock"
          title="hand the tablet over: the keypad cannot be closed without
          your PIN or password, and a wrong answer signs this session
          out">Lock in kiosk mode</button>` : ""}
      </div>
      <div id="punch-msg"></div>
    </div>
    ${S.user && mine.length ? `<h3>My shifts</h3>
      <div class="card"><table><thead><tr><th>in</th><th>out</th><th>hours</th></tr></thead>
      <tbody>${mine.map((s) => `<tr><td>${fmt(s.clock_in)}</td>
        <td>${s.clock_out ? fmt(s.clock_out) : '<span class="pill ok">on shift</span>'}</td>
        <td>${s.hours}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${isAdmin ? `<h3>Timesheet (all employees)</h3>
      <div class="card"><div class="tablewrap"><table><thead><tr><th>who</th>
        <th>job</th><th>in</th><th>out</th>
        <th>hours</th><th>event</th></tr></thead>
      <tbody>${all.map((s) => `<tr><td>${esc(s.name)}</td>
        <td class="dim">${esc(JOB_LABEL[s.job] || s.job || "")}${
          s.employment === "contractor" ? ' <span class="pill warn">1099</span>' : ""}</td>
        <td>${fmt(s.clock_in)}</td>
        <td>${s.clock_out ? fmt(s.clock_out) : '<span class="pill ok">on shift</span>'}</td>
        <td>${s.hours}</td>
        <td class="dim">${esc(s.event_name || "")}</td></tr>`).join("")}</tbody></table></div></div>` : ""}`;
  /* The badge is the other way in. On a tablet by the door, holding a
     lanyard up to the camera beats typing four digits with cold hands, and
     the badge identifies without authenticating — the worst a stolen one can
     do is clock its owner in, which a supervisor can see and undo. */
  $("#badge-btn").onclick = async () => {
    const code = await QRScan.scan({ title: "Scan your badge" });
    if (!code) return;
    const evSel = $("#clock-event");
    try {
      const r = await api("/api/clock/badge", { body: {
        token: code, event_id: evSel && evSel.value ? +evSel.value : null } });
      $("#punch-msg").innerHTML = r.action === "clock_in"
        ? `<b>${esc(r.name)}</b> clocked in${r.event
            ? " at " + esc(r.event) : ""}. Have a good one.`
        : `<b>${esc(r.name)}</b> clocked out — ${r.hours}h.`;
      renderClock();
    } catch (e) {
      $("#punch-msg").innerHTML = `<span class="low">${esc(e.message)}</span>`;
    }
  };

  const punch = async () => {
    try {
      const evSel = $("#clock-event");
      const r = await api("/api/clock", { body: { pin: $("#pin").value,
        event_id: evSel && evSel.value ? +evSel.value : null } });
      $("#punch-msg").innerHTML = r.action === "clock_in"
        ? `<span class="pill ok">Welcome, ${esc(r.name)} — clocked in
            ${r.event ? "at " + esc(r.event) : ""}</span>`
        : `<span class="pill warn">Bye ${esc(r.name)} — ${r.hours}h logged</span>`;
      $("#pin").value = "";
      setTimeout(render, 1600);
    } catch (e) { $("#punch-msg").innerHTML =
      `<span class="pill bad">${esc(e.message)}</span>`; }
  };
  $("#punch").onclick = punch;
  $("#pin").onkeydown = (e) => { if (e.key === "Enter") punch(); };
  $("#kiosk-btn").onclick = () => openKiosk(events);
  if ($("#kiosk-lock")) $("#kiosk-lock").onclick = () => {
    localStorage.setItem("bc_kiosk", "1");
    openKiosk(events, true);
  };
  if ($("#punch-me")) $("#punch-me").onclick = async () => {
    try {
      const r = await api("/api/clock/me", { body: {} });
      toast(r.action === "clock_in"
        ? `On shift${r.event ? " — " + r.event : ""}`
        : `Clocked out — ${r.hours}h logged`);
      renderClock();
    } catch (err) { toast(err.message); }
  };
}

/* Full-screen punch keypad for a store tablet. No sign-in involved — and
   when LOCKED, no way back out of it either: the tablet is sitting on a
   counter with somebody's whole back office behind it, so the exit asks
   for that person's own PIN or password, and anyone who does not know it
   gets the session signed out rather than a second guess. */
function openKiosk(events, locked) {
  const k = document.createElement("div");
  k.id = "kiosk";
  let pin = "";
  k.innerHTML = `
    <button class="btn alt exit" id="k-exit">${locked
      ? "unlock" : "exit"}</button>
    <div class="big">${esc(S.meta.brand || "Time Clock")}</div>
    <div class="dim">enter your PIN to clock in or out</div>
    ${events.length ? `<select id="k-event">
      <option value="">regular shift</option>
      ${events.map((ev) => `<option value="${ev.id}">event: ${esc(ev.name)}</option>`).join("")}
    </select>` : ""}
    <div class="k-ways">
      <button class="btn alt sm" id="k-badge">Scan a badge</button>
      <button class="btn alt sm" id="k-name">Name and password</button>
    </div>
    <div class="pin-dots" id="k-dots"></div>
    <div class="pad">
      ${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) =>
        `<button data-k="${n}">${n}</button>`).join("")}
      <button data-k="clear">⌫</button>
      <button data-k="0">0</button>
      <button data-k="go" style="background:var(--accent);color:#06130b">✓</button>
    </div>
    <div class="msg-big" id="k-msg"></div>`;
  document.body.appendChild(k);
  const dots = () => { k.querySelector("#k-dots").textContent =
    "●".repeat(pin.length); };
  const kPunch = async () => {
    if (!pin) return;
    const evSel = k.querySelector("#k-event");
    try {
      const r = await api("/api/clock", { body: { pin,
        event_id: evSel && evSel.value ? +evSel.value : null } });
      k.querySelector("#k-msg").innerHTML = r.action === "clock_in"
        ? `<span class="pill ok" style="font-size:16px">Welcome, ${esc(r.name)}
            ${r.event ? "— " + esc(r.event) : ""}</span>`
        : `<span class="pill warn" style="font-size:16px">Bye ${esc(r.name)}
            — ${r.hours}h logged</span>`;
    } catch (e) {
      k.querySelector("#k-msg").innerHTML =
        `<span class="pill bad" style="font-size:16px">${esc(e.message)}</span>`;
    }
    pin = "";
    dots();
    setTimeout(() => { const m = k.querySelector("#k-msg");
      if (m) m.textContent = ""; }, 3200);
  };
  k.querySelectorAll("[data-k]").forEach((b) => {
    b.onclick = () => {
      const v = b.dataset.k;
      if (v === "clear") pin = pin.slice(0, -1);
      else if (v === "go") return kPunch();
      else if (pin.length < 8) pin += v;
      dots();
    };
  });
  /* Three ways in, because the people most likely to forget a PIN are the
     people who work the fewest shifts. A badge is a scan, a name and
     password is what they already have, and none of the three mints a
     session — a tablet by the door records that somebody arrived and
     nothing else. */
  const kSay = (html) => { k.querySelector("#k-msg").innerHTML = html;
    setTimeout(() => { const m = k.querySelector("#k-msg");
      if (m) m.innerHTML = ""; }, 3600); };
  const kSaid = (r) => kSay(r.action === "clock_in"
    ? `<span class="pill ok" style="font-size:16px">Welcome, ${esc(r.name)}
        ${r.event ? "— " + esc(r.event) : ""}</span>`
    : `<span class="pill warn" style="font-size:16px">Bye ${esc(r.name)}
        — ${r.hours}h logged</span>`);
  const kEvent = () => {
    const sel = k.querySelector("#k-event");
    return sel && sel.value ? +sel.value : null;
  };
  k.querySelector("#k-badge").onclick = async () => {
    try {
      const code = await QRScan.scan({ title: "Scan your badge" });
      if (!code) return;
      kSaid(await api("/api/clock/badge",
        { body: { token: code, event_id: kEvent() } }));
    } catch (e) {
      kSay(`<span class="pill bad" style="font-size:16px">${
        esc(e.message)}</span>`);
    }
  };
  k.querySelector("#k-name").onclick = () => {
    const box = document.createElement("div");
    box.className = "k-unlock";
    box.innerHTML = `<div class="k-unlock-card">
      <b>Clock in by name</b>
      <p class="dim">The password you already use here. It starts your
        shift and nothing else — no session is opened on this tablet.</p>
      <input id="kn-name" placeholder="Your name" autocomplete="off">
      <input id="kn-pw" type="password" placeholder="Password"
        autocomplete="off">
      <div class="k-unlock-acts">
        <button class="btn alt" id="kn-cancel">Back</button>
        <button class="btn" id="kn-go">Punch</button>
      </div></div>`;
    k.appendChild(box);
    box.querySelector("#kn-name").focus();
    box.querySelector("#kn-cancel").onclick = () => box.remove();
    box.querySelector("#kn-go").onclick = async () => {
      try {
        const r = await api("/api/clock/name", { body: {
          name: box.querySelector("#kn-name").value.trim(),
          password: box.querySelector("#kn-pw").value,
          event_id: kEvent() } });
        box.remove();
        kSaid(r);
      } catch (e) {
        box.querySelector(".dim").innerHTML =
          `<span class="low">${esc(e.message)}</span>`;
      }
    };
    box.querySelector("#kn-pw").onkeydown = (e) => {
      if (e.key === "Enter") box.querySelector("#kn-go").click();
    };
  };
  k.querySelector("#k-exit").onclick = () => {
    if (!locked) { k.remove(); return; }
    kioskUnlock(k);
  };
}

/* The way out of a locked kiosk. One question, asked of the server so a
   tablet cannot answer it for itself, and one wrong answer ends the
   session — the worst case for a tablet left on a counter is a keypad
   nobody can get past, not a back office anybody can walk into. */
function kioskUnlock(k) {
  const box = document.createElement("div");
  box.className = "k-unlock";
  box.innerHTML = `
    <div class="k-unlock-card">
      <b>Your PIN or password</b>
      <p class="dim">This tablet is signed in as ${esc(
        (S.user && S.user.name) || "somebody")}. Getting out needs their
        answer — a wrong one signs the session out and leaves the clock
        running for everybody else.</p>
      <input id="ku-secret" type="password" autocomplete="off"
        inputmode="text">
      <div class="k-unlock-acts">
        <button class="btn alt" id="ku-cancel">Back to the keypad</button>
        <button class="btn" id="ku-go">Unlock</button>
      </div>
      <button class="btn alt sm" id="ku-out">I don't know it — sign out</button>
    </div>`;
  k.appendChild(box);
  const secret = box.querySelector("#ku-secret");
  secret.focus();
  const signOut = () => {
    localStorage.removeItem("bc_kiosk");
    localStorage.removeItem("bc_user");
    location.href = "/ops";
  };
  box.querySelector("#ku-cancel").onclick = () => box.remove();
  box.querySelector("#ku-out").onclick = signOut;
  box.querySelector("#ku-go").onclick = async () => {
    try {
      await api("/api/kiosk/unlock", { body: { secret: secret.value } });
      localStorage.removeItem("bc_kiosk");
      k.remove();
    } catch (err) {
      // Not a retry loop: somebody who does not know it does not get to
      // keep guessing at the owner's back office.
      signOut();
    }
  };
  secret.onkeydown = (e) => {
    if (e.key === "Enter") box.querySelector("#ku-go").click();
  };
}

// ---------- affiliates ----------

async function renderAffiliates() {
  if (!S.user) { S.tab = "login"; return renderLogin(); }
  const mine = await api("/api/affiliates/mine");
  const isAdmin = S.user.is_admin;
  const all = isAdmin ? await api("/api/admin/affiliates") : [];
  view().innerHTML = `
    <h2>Affiliate program</h2>
    ${mine.joined ? `
      <div class="row">
        <div class="card"><div class="dim">your link</div>
          <div class="big" style="font-size:17px">${location.origin}${mine.link}</div>
          <button class="btn alt" id="copy">Copy</button>
          <div id="aff-qr" style="margin-top:10px"></div>
          <div class="dim" style="font-size:12px">QR of your link — for
            packaging, table tents, or stories</div></div>
        <div class="card"><div class="dim">clicks</div><div class="big">${mine.clicks}</div></div>
        <div class="card"><div class="dim">referred orders</div><div class="big">${mine.orders}</div></div>
        <div class="card"><div class="dim">earned (${mine.rate_bps / 100}%)</div>
          <div class="big">${money(mine.earned_cents)}</div></div>
      </div>`
    : `<div class="card"><div class="doc-top">
        <div class="doc-main">Share a personal link, earn a commission on
          every order it brings in.</div>
        <button class="btn" id="join">Get my link</button></div></div>`}
    ${isAdmin ? `<h3>All influencers</h3>
      <div class="card"><table><thead><tr><th>who</th><th>code</th><th>rate</th>
      <th>clicks</th><th>orders</th><th>earned</th></tr></thead>
      <tbody>${all.map((a) => `<tr><td>${esc(a.name)}</td><td>${esc(a.code)}</td>
        <td>${a.rate_bps / 100}%</td><td>${a.clicks}</td><td>${a.ref_orders}</td>
        <td>${money(a.earned)}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  if ($("#join")) $("#join").onclick = async () => {
    await api("/api/affiliates/join", { body: {} });
    render();
  };
  if (mine.joined) api("/api/net").then((n) => {
    if ($("#aff-qr")) $("#aff-qr").innerHTML = qrImg(n.lan_url + mine.link, 110);
  }).catch(() => {});
  if ($("#copy")) $("#copy").onclick = () => {
    navigator.clipboard.writeText(location.origin + mine.link);
    toast("copied");
  };
}

// ---------- affiliate feed ----------

function timeAgo(t) {
  const s = Date.now() / 1000 - t;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

async function renderFeed() {
  if (!S.user) { S.tab = "login"; return renderLogin(); }
  const [posts, mine] = await Promise.all([
    api("/api/feed"), api("/api/affiliates/mine")]);
  const canPost = mine.joined || S.user.is_admin;
  view().innerHTML = `
    <h2>Affiliate feed</h2>
    ${canPost ? `<div class="card">
      <form id="post-form" class="inline" style="flex-direction:column;align-items:stretch">
        <textarea id="pf-body" rows="2"
          placeholder="What are you saying about the brand?"></textarea>
        <input id="pf-url" placeholder="link to your post (TikTok / YouTube / X / anything) — optional">
        <div><button class="btn" id="pf-btn">Post</button>
          <span class="dim">links get a preview pulled from the platform</span></div>
      </form></div>`
    : `<div class="card dim">Join the affiliate program (Affiliates tab) to
        post here. Everyone signed in can read the feed.</div>`}
    ${posts.map((p) => `
      <div class="card post">
        <div><b>${esc(p.name)}</b>
          ${p.code ? `<span class="pill ok">${esc(p.code)}</span>` : ""}
          <span class="dim">· ${esc(p.region) || "no region"} ·
            ${timeAgo(p.created_at)}</span>
          ${p.week_orders !== undefined && p.code ? `<span class="pill"
            title="orders via ${esc(p.code)} in the last 7 days">
            ${p.week_orders} order(s) this week</span>` : ""}
          ${S.user.is_admin ? `<span style="float:right">${
            rowActions("post", p)}</span>` : ""}
        </div>
        ${p.body ? `<div style="margin:8px 0">${esc(p.body)}</div>` : ""}
        ${p.url ? `<a class="preview" href="${esc(p.url)}" target="_blank" rel="noopener">
          ${p.image ? `<img src="${esc(p.image)}" alt="" loading="lazy">` : ""}
          <span class="pv-text">
            <span class="pill">${esc(p.provider || "link")}</span>
            ${p.title ? `<b>${esc(p.title)}</b>` : `<span class="dim">${esc(p.url)}</span>`}
            ${p.description ? `<span class="dim">${esc(p.description)}</span>` : ""}
          </span></a>` : ""}
      </div>`).join("")}
    ${posts.length ? "" : '<div class="card dim">nothing posted yet</div>'}`;
  if ($("#post-form")) $("#post-form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#pf-btn");
    btn.disabled = true; btn.setAttribute("aria-busy", "true");
    btn.textContent = "Posting…";
    try {
      await api("/api/feed", { body: {
        body: $("#pf-body").value, url: $("#pf-url").value } });
      render();
    } catch (err) { toast(err.message); btn.disabled = false;
      btn.textContent = "Post"; }
  };
  wireRows({ post: posts }, renderFeed);
}


/* ---------- hours ----------
   The clock records shifts; this is what payroll asks of them. One
   fortnight, one person per row, with overtime split out and a signature
   against the period rather than a flag on it. */
let HRS_FROM = null;

function fortnight(back) {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));   // Monday
  d.setDate(d.getDate() - 7 - 14 * (back || 0));     // last full fortnight
  return d.getTime() / 1000;
}

async function renderHours() {
  const from = HRS_FROM == null ? fortnight(0) : HRS_FROM;
  const to = from + 14 * 86400;
  const qs = `?from_ts=${from}&to_ts=${to}`;
  const mine = await api(`/api/hours${qs}`);
  const all = await api(`/api/hours/everyone${qs}`).catch(() => null);
  const off = await api("/api/time-off").catch(() => null);
  const day = (t) => new Date(t * 1000).toLocaleDateString(undefined,
    { month: "short", day: "numeric" });
  const clock = (t) => t ? new Date(t * 1000).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit" }) : "—";
  const person = (r) => `
    <div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(r.name)}</b>
          <span class="dim">${esc(r.role)}${r.job ? " · " + esc(r.job) : ""}
            · ${esc(r.employment || "employee")}</span></div>
        <span class="dim">${r.regular_hours}h regular</span>
        ${r.overtime_hours ? `<span class="pill warn">${r.overtime_hours}h
          overtime</span>` : ""}
        ${r.leave_hours ? `<span class="pill">${r.leave_hours}h leave</span>`
          : ""}
        <span class="pill ${r.approved ? "ok" : ""}">${r.approved
          ? "approved by " + esc(r.approved.approved_by) : "not approved"}
        </span>
        <button class="btn ${r.approved ? "alt " : ""}sm"
          data-hrappr="${r.user_id}:${r.approved ? 0 : 1}">${r.approved
          ? "Reopen" : "Approve"}</button>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>day</th><th>in</th><th>out</th><th>hours</th>
          <th>for</th><th></th></tr></thead>
        <tbody>${r.shifts.map((sh) => `<tr${sh.open ? ' class="au-fail"' : ""}>
          <td>${day(sh.clock_in)}</td><td>${clock(sh.clock_in)}</td>
          <td>${sh.open ? '<span class="pill warn">still open</span>'
            : clock(sh.clock_out)}</td>
          <td>${sh.hours || "—"}</td>
          <td class="dim">${esc(sh.event || "")}</td>
          <td>${r.approved ? "" : `<button class="btn alt sm"
            data-hrfix="${sh.id}:${sh.clock_in}:${sh.clock_out || 0}"
            >Fix</button>`}</td>
        </tr>`).join("") || '<tr><td colspan="6" class="dim">no shifts</td>'
          + "</tr>"}</tbody></table></div>
    </div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Hours</h2>
        <p class="dim">${day(from)} – ${day(to - 1)}. Overtime is anything
          past ${all ? all.overtime_after : mine.overtime_after} hours in a
          week. Approving a period stores the numbers WITH the signature:
          what was approved is what was seen.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="hr-prev">&larr; earlier</button>
        <button class="btn alt" id="hr-next">later &rarr;</button>
        <button class="btn" id="hr-off">${opsIcon("calendar", "btn-ic")}
          Ask for time off</button>
      </div>
    </div>
    ${all ? `<div class="card">
      <b>Everyone</b>
      <span class="dim"> · ${all.totals.worked}h worked ·
        ${all.totals.overtime}h overtime · ${all.totals.leave}h leave</span>
    </div>
    ${all.rows.map(person).join("")
      || '<div class="card empty"><b>Nobody clocked in this period</b></div>'}`
      : person({ ...mine, user_id: mine.user_id, name: mine.name,
                 role: "you", approved: mine.approved })}
    ${off ? `<h3>Time off</h3>
      ${off.requests.length ? off.requests.map((r) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(r.who)} — ${esc(r.kind)}</b>
            <span class="dim">${day(r.starts)} – ${day(r.ends)} ·
              ${r.hours}h${r.note ? " · " + esc(r.note) : ""}</span></div>
          <span class="pill ${r.state === "approved" ? "ok"
            : r.state === "declined" ? "bad" : "warn"}">${esc(r.state)}${
            r.decided_by ? " · " + esc(r.decided_by) : ""}</span>
          ${off.office && r.state === "requested" ? `
            <button class="btn sm" data-offok="${r.id}">Approve</button>
            <button class="btn alt sm" data-offno="${r.id}">Decline</button>`
            : ""}
          ${r.user_id === off.me && r.state === "requested"
            ? `<button class="btn alt sm" data-offcancel="${r.id}"
                >Withdraw</button>` : ""}
        </div></div>`).join("")
        : '<div class="card empty"><b>Nothing booked</b><span class="dim">'
          + 'Holiday, sick days and unpaid leave all land here, and approved '
          + 'hours count toward the period.</span></div>'}` : ""}`;
  $("#hr-prev").onclick = () => { HRS_FROM = from - 14 * 86400; renderHours(); };
  $("#hr-next").onclick = () => { HRS_FROM = from + 14 * 86400; renderHours(); };
  $("#hr-off").onclick = () => timeOffForm();
  view().querySelectorAll("[data-hrappr]").forEach((b) => b.onclick =
    async () => {
      const [uid, on] = b.dataset.hrappr.split(":");
      try {
        await api("/api/hours/approve", { body: {
          user_id: +uid, period_start: from, period_end: to,
          approve: on === "1" } });
        renderHours();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-hrfix]").forEach((b) => b.onclick = () => {
    const [sid, cin, cout] = b.dataset.hrfix.split(":");
    shiftFixForm(+sid, +cin, +cout);
  });
  view().querySelectorAll("[data-offok],[data-offno],[data-offcancel]")
    .forEach((b) => b.onclick = async () => {
      const id = b.dataset.offok || b.dataset.offno || b.dataset.offcancel;
      const state = b.dataset.offok ? "approved"
        : b.dataset.offno ? "declined" : "cancelled";
      try {
        await api(`/api/time-off/${id}/decide`, { body: { state } });
        renderHours();
      } catch (err) { toast(err.message); }
    });
}

/* Somebody forgets to clock out roughly once a week in any business with
   a clock. A timesheet nobody can correct is one that gets corrected in a
   spreadsheet instead, which is where payroll disputes come from. */
function shiftFixForm(sid, cin, cout) {
  const local = (t) => t ? new Date((t - new Date().getTimezoneOffset() * 60)
    * 1000).toISOString().slice(0, 16) : "";
  modal(`<h3>Correct this shift</h3>
    <p class="dim">The change stands on the record. A period that has been
      approved has to be reopened first, so a correction never happens
      behind a signature.</p>
    <div class="row2">
      <div><label>Clocked in</label>
        <input id="sf-in" type="datetime-local" value="${local(cin)}"></div>
      <div><label>Clocked out <span class="opt">blank leaves it
        open</span></label>
        <input id="sf-out" type="datetime-local" value="${local(cout)}"></div>
    </div>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="sf-save">Save</button></div>`);
  $("#sf-save").onclick = async () => {
    const val = (id) => $(id).value
      ? new Date($(id).value).getTime() / 1000 : 0;
    try {
      await api(`/api/hours/shift/${sid}`, { method: "PATCH", body: {
        clock_in: val("#sf-in") || cin, clock_out: val("#sf-out") } });
      closeModal(); renderHours();
    } catch (err) { toast(err.message); }
  };
}

function timeOffForm() {
  modal(`<h3>Ask for time off</h3>
    <p class="dim">Approved hours count toward the period the same way
      worked hours do — payroll pays both, and a screen that shows only one
      is a screen that gets somebody underpaid.</p>
    <div class="row2">
      <div><label>What kind</label>
        <select id="to-kind">
          ${["holiday", "sick", "unpaid", "bereavement", "other"].map((k) =>
            `<option>${k}</option>`).join("")}</select></div>
      <div><label>Hours <span class="opt">blank counts 8 a day</span></label>
        <input id="to-hours" type="number" min="0" step="0.5"></div>
    </div>
    <div class="row2">
      <div><label>From</label><input id="to-from" type="date"></div>
      <div><label>To</label><input id="to-to" type="date"></div>
    </div>
    <label>Anything they should know</label>
    <input id="to-note" placeholder="optional">
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="to-save">Ask</button></div>`);
  $("#to-save").onclick = async () => {
    const d = (id) => $(id).value
      ? new Date($(id).value + "T09:00").getTime() / 1000 : 0;
    const starts = d("#to-from"), ends = d("#to-to") || starts;
    if (!starts) return toast("pick the first day");
    try {
      await api("/api/time-off", { body: {
        kind: $("#to-kind").value, starts, ends,
        hours: +$("#to-hours").value || 0,
        note: $("#to-note").value.trim() } });
      closeModal(); toast("asked — somebody will answer it"); renderHours();
    } catch (err) { toast(err.message); }
  };
}


/* ---------- availability and the rota ----------
   Two different facts, deliberately not one: what somebody says about
   their own week, and what the business is asking of them. A rota that
   confuses the two is how people get rostered onto their evening class. */
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"];
/* Set by whatever drew the rota, so an edit made in a dialog on top
   of it lands on the page underneath before the dialog closes. */
let ROTA_REDRAW = null;
let ROTA_FROM = null;

const hhmm = (mins) => `${String(Math.floor(mins / 60)).padStart(2, "0")}:`
  + String(mins % 60).padStart(2, "0");

async function renderSchedule() {
  const from = ROTA_FROM || (() => {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime() / 1000;
  })();
  const to = from + 14 * 86400;
  const [sched, avail] = await Promise.all([
    api(`/api/schedule?from_ts=${from}&to_ts=${to}`),
    api("/api/availability")]);
  const byDay = {};
  sched.shifts.forEach((s) => {
    const k = new Date(s.starts * 1000).toDateString();
    (byDay[k] = byDay[k] || []).push(s);
  });
  const t = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit" });
  const cells = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date((from + i * 86400) * 1000);
    const list = byDay[d.toDateString()] || [];
    cells.push(`<div class="rota-day">
      <button class="rota-head" data-rotaday="${from + i * 86400}"
        title="open this day: who is on it, who could be">${
        DAYS[(d.getDay() + 6) % 7]}
        <span class="dim">${d.getDate()}</span></button>
      ${list.map((s) => `<div class="rota-shift${s.published
        ? "" : " rota-draft"}${s.fits ? "" : " rota-clash"}"
        title="${s.fits ? "inside what they said they could do"
          : "outside the hours they gave — allowed, but worth a word"}">
        <b>${esc(s.name)}</b>
        <span class="dim">${t(s.starts)}–${t(s.ends)}${
          s.store ? " · " + esc(s.store) : ""}</span>
        ${sched.office ? `<button class="btn alt sm"
          data-rotadel="${s.id}">×</button>` : ""}
      </div>`).join("")
        || '<span class="dim" style="font-size:11.5px">—</span>'}
      ${sched.office ? `<button class="btn alt sm rota-add"
        data-rotaadd="${from + i * 86400}">+</button>` : ""}
    </div>`);
  }
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Rota</h2>
        <p class="dim">What the business is asking of people, over what
          they said they could do. A shift outside somebody's hours is
          allowed and marked — a rota that refuses to let a manager ask is
          a rota that ends up in a spreadsheet.</p></div>
      <div class="top-actions">
        <button class="btn alt icon-btn" id="rt-prev"
          title="the fortnight before">&larr;</button>
        <button class="btn alt icon-btn" id="rt-next"
          title="the fortnight after">&rarr;</button>
        ${sched.office ? `<button class="btn alt" id="rt-said"
          title="who has told you when they can work, and who has not"
          >${opsIcon("users", "btn-ic")} Who has said</button>
        <button class="btn alt" id="rt-free"
          title="a day and a time, and everybody measured against it"
          >${opsIcon("clock", "btn-ic")} Who is free</button>` : ""}
        <button class="btn alt" id="rt-avail">${opsIcon("clock", "btn-ic")}
          My availability</button>
        ${sched.office ? `<button class="btn" id="rt-pub">${
          opsIcon("calendar", "btn-ic")} Publish these two weeks</button>`
          : ""}
      </div>
    </div>
    ${sched.shifts.some((s) => !s.published) && sched.office
      ? `<div class="card alert"><b>Draft shifts on this rota.</b>
         <span class="dim">Nobody but the office can see them until you
           publish — a rota half-built is not a promise anybody should be
           arranging childcare around.</span></div>` : ""}
    <div class="rota">${cells.join("")}</div>
    <h3>My week</h3>
    <div class="card">
      ${avail.week.some((w) => w.windows.length) || avail.slots.length
        ? `<div class="av-week">${avail.week.map((w, i) => `
            <button class="av-wday" data-myday="${i}">
              <b>${DAYS[i]}</b>
              ${w.windows.length
                ? w.windows.map((x) => `<span class="pill ok">${hhmm(x[0])}–${
                    hhmm(x[1])}</span>`).join("")
                : `<span class="pill">${avail.slots.some((x) =>
                    x.weekday === i) ? "off" : "—"}</span>`}
              ${w.why.length ? `<span class="dim av-why">${w.why.length}
                exception${w.why.length === 1 ? "" : "s"}</span>` : ""}
            </button>`).join("")}</div>
           ${avail.blackouts.length ? `<p class="dim">${
             avail.blackouts.length} date${avail.blackouts.length === 1
               ? "" : "s"} blacked out ahead.</p>` : ""}`
        : '<span class="dim">You have not said when you can work. Nobody '
          + 'can roster around hours they do not know about.</span>'}
    </div>`;
  $("#rt-prev").onclick = () => { ROTA_FROM = from - 14 * 86400;
    renderSchedule(); };
  $("#rt-next").onclick = () => { ROTA_FROM = from + 14 * 86400;
    renderSchedule(); };
  ROTA_REDRAW = renderSchedule;
  $("#rt-avail").onclick = () => availabilityForm();
  if ($("#rt-said")) $("#rt-said").onclick = () => whoHasSaid();
  if ($("#rt-free")) $("#rt-free").onclick = () => whoIsFree(from
    + 9 * 3600, 480);
  view().querySelectorAll("[data-rotaday]").forEach((b) => b.onclick = () =>
    dayView(+b.dataset.rotaday, sched.office ? sched.people : null));
  if ($("#rt-pub")) $("#rt-pub").onclick = async () => {
    try {
      const r = await api("/api/schedule/publish", { body: {
        from_ts: from, to_ts: to, published: true } });
      toast(`${r.changed} shift(s) on the wall`);
      renderSchedule();
    } catch (err) { toast(err.message); }
  };
  view().querySelectorAll("[data-rotaadd]").forEach((b) => b.onclick = () =>
    planShiftForm(+b.dataset.rotaadd, sched.people));
  view().querySelectorAll("[data-myday]").forEach((b) => b.onclick = () => {
    AV_DAY = +b.dataset.myday; availabilityForm();
  });
  view().querySelectorAll("[data-rotadel]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/schedule/${b.dataset.rotadel}`, { method: "DELETE" });
        renderSchedule();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-availdel]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/availability/${b.dataset.availdel}`,
                  { method: "DELETE" });
        renderSchedule();
      } catch (err) { toast(err.message); }
    });
}

function planShiftForm(dayTs, people) {
  const d = new Date(dayTs * 1000);
  modal(`<h3>${d.toLocaleDateString(undefined,
    { weekday: "long", month: "short", day: "numeric" })}</h3>
    <label>Who</label>
    <select id="ps-who">${people.map((p) =>
      `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
    <div class="row2">
      <div><label>From</label><input id="ps-from" type="time" value="09:00">
      </div>
      <div><label>To</label><input id="ps-to" type="time" value="17:00"></div>
    </div>
    <label>Note <span class="opt">what they are on</span></label>
    <input id="ps-note" placeholder="counter, deliveries, the market">
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ps-save">Draft it</button></div>`);
  $("#ps-save").onclick = async () => {
    const at = (v) => {
      const [h, m] = v.split(":").map(Number);
      return dayTs + h * 3600 + m * 60;
    };
    try {
      const r = await api("/api/schedule", { body: {
        user_id: +$("#ps-who").value,
        starts: at($("#ps-from").value), ends: at($("#ps-to").value),
        note: $("#ps-note").value.trim() } });
      closeModal();
      if (!r.fits) toast("drafted — that is outside the hours they gave");
      renderSchedule();
    } catch (err) { toast(err.message); }
  };
}

/* ---------- what a person can work ----------
   One editor, three answers deep. The ordinary week is the top layer and
   the one most people only ever touch. Underneath it, a weekday can be
   stepped into and carved up — Tuesdays yes, but not between twelve and
   one, and this Tuesday not at all. A week that can only say "yes" or
   "no" to a whole day gets filled in wrong by everybody whose life has an
   afternoon in it. */
let AV_DAY = null;                 // the weekday being edited, 0 = Monday

async function availabilityForm(uid) {
  const d = await api("/api/availability" + (uid ? `?user_id=${uid}` : ""));
  const who = uid ? ` — filling in for ${esc(d.name || "them")}` : "";
  if (AV_DAY === null) AV_DAY = (new Date().getDay() + 6) % 7;
  const draw = () => {
    const day = d.week[AV_DAY] || { windows: [], why: [], said: false };
    const slots = d.slots.filter((x) => x.weekday === AV_DAY);
    const open = slots.filter((x) => (x.kind || "open") === "open");
    const shut = slots.filter((x) => x.kind === "shut");
    modalBody().innerHTML = `
      <h3>When you can work${who}</h3>
      <p class="dim">Nobody can roster around hours they do not know
        about. The week is what an ordinary ${DAYS_LONG[AV_DAY]} looks
        like; the dates below are the ones it is not true of.</p>
      <div class="av-days">${DAYS.map((n, i) => {
        const w = d.week[i] || { windows: [] };
        const hrs = w.windows.reduce((t, x) =>
          t + (x[1] - x[0]) / 60, 0);
        return `<button class="chip${i === AV_DAY ? " on" : ""}"
          data-avday="${i}">${n}
          <span class="dim">${hrs ? hrs + "h" : "—"}</span></button>`;
      }).join("")}</div>

      <div class="card av-card">
        <div class="doc-top">
          <div class="doc-main"><b>${DAYS_LONG[AV_DAY]}</b>
            <span class="dim">${day.windows.length
              ? day.windows.map((w) => hhmm(w[0]) + "–" + hhmm(w[1]))
                  .join(", ") + " free"
              : slots.length ? "nothing left free — every hour is carved out"
                : "nothing said yet"}</span></div>
          <button class="btn alt sm" data-avoff>Mark the day off</button>
        </div>
        ${open.length ? `<p class="dim av-lbl">Can work</p>
          <div class="chips">${open.map((x) => `<span class="pill ok">${
            hhmm(x.from_min)}–${hhmm(x.to_min)}${x.note
              ? " · " + esc(x.note) : ""}
            <button class="btn alt sm" data-avdel="${x.id}">×</button>
          </span>`).join("")}</div>` : ""}
        ${shut.length ? `<p class="dim av-lbl">Except, every week</p>
          <div class="chips">${shut.map((x) => `<span class="pill warn">${
            x.from_min === 0 && x.to_min === 1440 ? "all day"
              : hhmm(x.from_min) + "–" + hhmm(x.to_min)}${x.note
              ? " · " + esc(x.note) : ""}
            <button class="btn alt sm" data-avdel="${x.id}">×</button>
          </span>`).join("")}</div>` : ""}
        <div class="row3 av-add">
          <div><label>From</label>
            <input id="av-from" type="time" value="09:00"></div>
          <div><label>To</label>
            <input id="av-to" type="time" value="17:00"></div>
          <div><label>Note <span class="opt">optional</span></label>
            <input id="av-note" placeholder="school run, class"></div>
        </div>
        <div class="chips">
          <button class="btn sm" data-avadd="open">I can work this</button>
          <button class="btn alt sm" data-avadd="shut">Every week, not
            this</button>
        </div>
      </div>

      <h4 class="av-h">Dates the week is not true of</h4>
      <p class="dim">A holiday, a fortnight away, an afternoon at the
        dentist. A blackout beats the week it lands in.</p>
      ${d.blackouts.length ? `<div class="chips av-bl">${d.blackouts.map((b) =>
        `<span class="pill warn">${esc(b.from_day)}${
          b.to_day !== b.from_day ? " → " + esc(b.to_day) : ""}${
          b.from_min === 0 && b.to_min === 1440 ? ""
            : " · " + hhmm(b.from_min) + "–" + hhmm(b.to_min)}${
          b.note ? " · " + esc(b.note) : ""}
        <button class="btn alt sm" data-bldel="${b.id}">×</button>
        </span>`).join("")}</div>` : '<p class="dim">None coming up.</p>'}
      <div class="row2">
        <div><label>From</label><input id="bl-from" type="date"></div>
        <div><label>To <span class="opt">same day if left empty</span></label>
          <input id="bl-to" type="date"></div>
      </div>
      <div class="row3">
        <div><label>From <span class="opt">all day if left empty</span></label>
          <input id="bl-fmin" type="time"></div>
        <div><label>To</label><input id="bl-tmin" type="time"></div>
        <div><label>Note</label><input id="bl-note" placeholder="away"></div>
      </div>
      <div class="modal-foot">
        <button class="btn alt" data-close>Done</button>
        <button class="btn" id="bl-save">Add the dates</button></div>`;
    wire();
  };

  const mins = (v) => {
    const [h, m] = String(v || "").split(":").map(Number);
    return (h || 0) * 60 + (m || 0);
  };
  const again = async () => {
    const fresh = await api("/api/availability"
      + (uid ? `?user_id=${uid}` : ""));
    d.slots = fresh.slots; d.week = fresh.week; d.blackouts = fresh.blackouts;
    draw();
    if (typeof ROTA_REDRAW === "function") ROTA_REDRAW();
  };

  function wire() {
    modalBody().querySelectorAll("[data-avday]").forEach((b) =>
      b.onclick = () => { AV_DAY = +b.dataset.avday; draw(); });
    modalBody().querySelectorAll("[data-avadd]").forEach((b) =>
      b.onclick = async () => {
        try {
          await api("/api/availability", { body: {
            weekday: AV_DAY, kind: b.dataset.avadd,
            from_min: mins($("#av-from").value),
            to_min: mins($("#av-to").value),
            note: $("#av-note").value.trim(), user_id: uid || 0 } });
          again();
        } catch (err) { toast(err.message); }
      });
    modalBody().querySelector("[data-avoff]").onclick = async () => {
      try {
        await api("/api/availability", { body: {
          weekday: AV_DAY, kind: "shut", from_min: 0, to_min: 1440,
          note: "", user_id: uid || 0 } });
        again();
      } catch (err) { toast(err.message); }
    };
    modalBody().querySelectorAll("[data-avdel]").forEach((b) =>
      b.onclick = async () => {
        try {
          await api(`/api/availability/${b.dataset.avdel}`,
                    { method: "DELETE" });
          again();
        } catch (err) { toast(err.message); }
      });
    modalBody().querySelectorAll("[data-bldel]").forEach((b) =>
      b.onclick = async () => {
        try {
          await api(`/api/blackouts/${b.dataset.bldel}`,
                    { method: "DELETE" });
          again();
        } catch (err) { toast(err.message); }
      });
    $("#bl-save").onclick = async () => {
      const from = $("#bl-from").value;
      if (!from) return toast("which day?");
      const a = $("#bl-fmin").value, b = $("#bl-tmin").value;
      try {
        await api("/api/blackouts", { body: {
          from_day: from, to_day: $("#bl-to").value || from,
          from_min: a ? mins(a) : 0, to_min: b ? mins(b) : 1440,
          note: $("#bl-note").value.trim(), user_id: uid || 0 } });
        again();
      } catch (err) { toast(err.message); }
    };
  }

  modal("<h3>When you can work</h3>");
  draw();
}


/* ---------- one day, in full ----------
   A month grid says a day has three things on it; it cannot say who is
   working it, who could be, or what is in the way. Stepping into a day
   from either calendar lands here, and from here a manager can fill it. */
async function dayView(dayTs, people) {
  const d = new Date(dayTs * 1000);
  const title = d.toLocaleDateString(undefined,
    { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  modal(`<h3>${title}</h3><p class="dim">Reading the day…</p>`, "wide");
  const t = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit" });
  const [cal, sched, free] = await Promise.all([
    api(`/api/calendar?from_ts=${dayTs}&to_ts=${dayTs + 86400}`)
      .catch(() => ({ items: [] })),
    api(`/api/schedule?from_ts=${dayTs}&to_ts=${dayTs + 86400}`)
      .catch(() => ({ shifts: [], office: false, people: [] })),
    people ? api(`/api/availability/who?at=${dayTs + 9 * 3600}&mins=480`)
      .catch(() => null) : null]);
  const draw = () => {
    modalBody().innerHTML = `
      <div class="page-head">
        <div><h3>${title}</h3></div>
        <div class="top-actions">
          <button class="btn alt sm" data-dayback>&larr;</button>
          <button class="btn alt sm" data-dayfwd>&rarr;</button>
          ${sched.office ? `<button class="btn sm" data-dayadd>Add a
            shift</button>` : ""}
          <button class="btn alt sm" data-close>Close</button>
        </div>
      </div>
      <h4 class="av-h">On the rota</h4>
      ${sched.shifts.length ? `<div class="sig-rows">${sched.shifts
        .sort((a, b) => a.starts - b.starts).map((s) => `
        <div class="doc-line dayline${s.published ? "" : " dl-awaiting"}">
          <span class="dl-title"><b>${esc(s.name)}</b>
            <span class="dim">${t(s.starts)}–${t(s.ends)}${
              s.store ? " · " + esc(s.store) : ""}${
              s.note ? " · " + esc(s.note) : ""}</span>
            ${s.published ? "" : '<span class="pill warn">draft</span>'}
            ${s.fits ? "" : '<span class="pill bad">outside their hours'
              + "</span>"}</span>
          <span class="dl-acts dayline-acts">
            ${sched.office ? `<button class="btn alt sm" data-daycover="${
              s.starts}" data-ends="${s.ends}" title="who else could take
              this window">Who is free</button>
            <button class="btn alt sm" data-daydel="${s.id}">Drop</button>`
              : ""}</span>
        </div>`).join("")}</div>`
        : emptyState("clock", "Nobody is on this day",
                     sched.office ? "Add a shift, or see who is free for it."
                       : "Nothing published for this day.")}
      ${cal.items.length ? `<h4 class="av-h">Also dated today</h4>
        <div class="chips">${cal.items.map((it) => `<span class="pill">${
          esc(it.kind)} · ${esc(it.title)}</span>`).join("")}</div>` : ""}
      ${free ? `<h4 class="av-h">Who could work it
        <span class="dim">${free.people.filter((p) => p.state === "free")
          .length} free of ${free.people.length}</span></h4>
        <p class="dim">Measured against ${hhmm(free.from_min)}–${
          hhmm(free.to_min)}. Change the window with Who is free.</p>
        ${freeRows(free, dayTs)}` : ""}`;
    wire();
  };
  function wire() {
    const step = (n) => { closeModal(); dayView(dayTs + n * 86400, people); };
    modalBody().querySelector("[data-dayback]").onclick = () => step(-1);
    modalBody().querySelector("[data-dayfwd]").onclick = () => step(1);
    modalBody().querySelectorAll("[data-close]").forEach((b) =>
      b.onclick = closeModal);
    const add = modalBody().querySelector("[data-dayadd]");
    if (add) add.onclick = () => { closeModal();
      planShiftForm(dayTs, sched.people); };
    modalBody().querySelectorAll("[data-daycover]").forEach((b) =>
      b.onclick = () => { closeModal(); whoIsFree(+b.dataset.daycover,
        Math.round((+b.dataset.ends - +b.dataset.daycover) / 60)); });
    modalBody().querySelectorAll("[data-daydel]").forEach((b) =>
      b.onclick = async () => {
        try {
          await api(`/api/schedule/${b.dataset.daydel}`, { method: "DELETE" });
          closeModal(); dayView(dayTs, people);
          if (typeof ROTA_REDRAW === "function") ROTA_REDRAW();
        } catch (err) { toast(err.message); }
      });
    if (free) wireFreeRows(modalBody(), dayTs, free, () => { closeModal();
      dayView(dayTs, people); });
  }
  draw();
}


/* The answer to "who can cover Saturday afternoon" — including the people
   who cannot, with the reason, because a manager without the reason rings
   round to find it out anyway. */
const FREE_LABEL = { free: "free", part: "part of it", booked: "on a shift",
                     away: "away", outside: "outside their hours",
                     unsaid: "has not said" };
const FREE_PILL = { free: "ok", part: "warn", booked: "", away: "warn",
                    outside: "", unsaid: "" };

function freeRows(free, dayTs) {
  return `<div class="sig-rows">${free.people.map((p) => `
    <div class="doc-line freeline">
      <span class="dl-title"><b>${esc(p.name)}</b>
        <span class="dim">${esc(p.job || p.role)}${p.windows.length
          ? " · " + p.windows.map((w) => hhmm(w.from_min) + "–"
              + hhmm(w.to_min)).join(", ") : ""}</span></span>
      <span class="freeline-why dim">${esc(p.why)}</span>
      <span class="pill ${FREE_PILL[p.state] || ""}">${
        FREE_LABEL[p.state] || p.state}</span>
      <span class="dl-acts freeline-acts">
        <button class="btn alt sm" data-freeadd="${p.user_id}"
          data-name="${esc(p.name)}" title="draft them onto ${hhmm(
          free.from_min)}–${hhmm(free.to_min)} that day">Roster them</button>
      </span>
    </div>`).join("")}</div>`;
}

function wireFreeRows(scope, dayTs, win, done) {
  scope.querySelectorAll("[data-freeadd]").forEach((b) =>
    b.onclick = async () => {
      // The window the list was measured against is the window the shift
      // gets — rostering somebody into different hours than the ones they
      // were just judged against is how a rota tells a lie.
      const box = (sel, fb) => {
        const el = scope.querySelector(sel);
        if (!el || !el.value) return fb;
        const [h, m] = el.value.split(":").map(Number);
        return h * 60 + m;
      };
      const at = (mins) => dayTs + mins * 60;
      try {
        const r = await api("/api/schedule", { body: {
          user_id: +b.dataset.freeadd,
          starts: at(box("[data-freefrom]", win.from_min)),
          ends: at(box("[data-freeto]", win.to_min)), note: "" } });
        toast(r.fits ? `${b.dataset.name} is drafted on`
          : `${b.dataset.name} is drafted on — outside the hours they gave`);
        if (typeof ROTA_REDRAW === "function") ROTA_REDRAW();
        if (done) done();
      } catch (err) { toast(err.message); }
    });
}

async function whoIsFree(at, mins) {
  const day = new Date(at * 1000);
  const midnight = new Date(day); midnight.setHours(0, 0, 0, 0);
  const dayTs = midnight.getTime() / 1000;
  const pad = (n) => String(n).padStart(2, "0");
  const free = await api(`/api/availability/who?at=${at}&mins=${mins}`);
  modal(`<div class="page-head">
      <div><h3>Who is free</h3>
        <p class="dim">Everybody measured against one window of one day —
          the ones who cannot, with the reason, so nobody has to ring
          round to find out.</p></div>
      <div class="top-actions">
        <button class="btn alt sm" data-close>Close</button></div>
    </div>
    <div class="row3">
      <div><label>Day</label><input id="wf-day" type="date"
        value="${day.getFullYear()}-${pad(day.getMonth() + 1)}-${
        pad(day.getDate())}"></div>
      <div><label>From</label><input id="wf-from" type="time"
        data-freefrom value="${hhmm(free.from_min)}"></div>
      <div><label>To</label><input id="wf-to" type="time"
        data-freeto value="${hhmm(free.to_min)}"></div>
    </div>
    <p class="dim wf-count">${free.people.filter((p) =>
      p.state === "free").length} free of ${free.people.length} ·
      ${free.people.filter((p) => p.state === "unsaid").length} have not
      said</p>
    ${freeRows(free, dayTs)}`, "wide");
  const reload = () => {
    const [y, m, dd] = $("#wf-day").value.split("-").map(Number);
    const [h, mi] = $("#wf-from").value.split(":").map(Number);
    const [h2, mi2] = $("#wf-to").value.split(":").map(Number);
    const start = new Date(y, m - 1, dd, h, mi).getTime() / 1000;
    const len = (h2 * 60 + mi2) - (h * 60 + mi);
    closeModal();
    whoIsFree(start, Math.max(15, len));
  };
  ["#wf-day", "#wf-from", "#wf-to"].forEach((sel) => {
    $(sel).onchange = reload;
  });
  wireFreeRows(modalBody(), dayTs, free, () => { closeModal();
    whoIsFree(at, mins); });
}


/* A rota built on three people's stated hours and five people's silence
   is not a rota, and the silence is invisible until somebody is rostered
   wrongly. So the silence gets a list of its own. */
async function whoHasSaid() {
  const d = await api("/api/availability/filled");
  const said = d.people.filter((p) => p.said);
  const not = d.people.filter((p) => !p.said);
  modal(`<div class="page-head">
      <div><h3>Who has said when they can work</h3>
        <p class="dim">${d.said} of ${d.of}. Anyone missing can be filled
          in for — somebody always tells you in person.</p></div>
      <div class="top-actions">
        <button class="btn alt sm" data-close>Close</button></div>
    </div>
    ${not.length ? `<h4 class="av-h">Has not said</h4>
      <div class="sig-rows">${not.map((p) => `
        <div class="doc-line dl-awaiting">
          <span class="dl-title"><b>${esc(p.name)}</b>
            <span class="dim">${esc(p.role)}</span></span>
          <span class="dl-acts saidline-acts">
            <button class="btn alt sm" data-saidfor="${p.user_id}"
              >Fill it in</button></span>
        </div>`).join("")}</div>` : ""}
    ${said.length ? `<h4 class="av-h">Has</h4>
      <div class="sig-rows">${said.map((p) => `
        <div class="doc-line">
          <span class="dl-title"><b>${esc(p.name)}</b>
            <span class="dim">${p.days} day${p.days === 1 ? "" : "s"} ·
              ${p.hours}h a week${p.blackouts
                ? " · " + p.blackouts + " blacked out" : ""}</span></span>
          <span class="dim saidline-when">${p.updated_at
            ? fmtDate(p.updated_at) : ""}</span>
          <span class="dl-acts saidline-acts">
            <button class="btn alt sm" data-saidfor="${p.user_id}"
              >Open</button></span>
        </div>`).join("")}</div>` : ""}`, "wide");
  modalBody().querySelectorAll("[data-saidfor]").forEach((b) =>
    b.onclick = () => { closeModal(); AV_DAY = null;
      availabilityForm(+b.dataset.saidfor); });
}
