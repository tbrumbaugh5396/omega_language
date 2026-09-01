// ---------- shop ----------



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
    <h2>Shop ${isDist ? '<span class="pill ok">wholesale — priced per case</span>' : ""}</h2>
    <div class="grid">${S.products.map((p) => `
      <div class="product" data-p="${p.id}">
        <div class="art">${productArt(p)}</div>
        <div class="body">
          <div class="name">${esc(p.name)}</div>
          <div class="dim" style="font-size:12px">${esc(p.category)} · ${esc(p.sku)}</div>
          <div class="price">${isDist
            ? `${money(p.case_price_cents)} <span class="dim"
                style="font-size:12px;font-weight:400">/ case of ${p.case_size}</span>`
            : money(p.price_cents)}</div>
          <div class="stepper" data-step="${p.id}">
            <button data-dec="${p.id}" aria-label="remove one">−</button>
            <span class="q" data-q="${p.id}">${S.cart[p.id] || 0}</span>
            <button data-inc="${p.id}" aria-label="add one">+</button>
          </div>
          ${rowActions("product", p)}
        </div>
      </div>`).join("")}
    </div>
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
        <button class="btn" id="punch">Punch</button>
        <button class="btn alt" id="badge-btn"
          title="scan an employee badge instead of typing a PIN">${
          opsIcon("camera", "btn-ic")} Scan a badge</button>
        <button class="btn alt" id="kiosk-btn"
          title="full-screen keypad for the store tablet">Kiosk mode</button>
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
}

// Full-screen punch keypad for a store tablet. No sign-in involved.
function openKiosk(events) {
  const k = document.createElement("div");
  k.id = "kiosk";
  let pin = "";
  k.innerHTML = `
    <button class="btn alt exit" id="k-exit">exit</button>
    <div class="big">${esc(S.meta.brand || "Time Clock")}</div>
    <div class="dim">enter your PIN to clock in or out</div>
    ${events.length ? `<select id="k-event">
      <option value="">regular shift</option>
      ${events.map((ev) => `<option value="${ev.id}">event: ${esc(ev.name)}</option>`).join("")}
    </select>` : ""}
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
  k.querySelector("#k-exit").onclick = () => k.remove();
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
    : `<div class="card">Share a personal link, earn a commission on every
        order it brings in. <button class="btn" id="join">Get my link</button></div>`}
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
