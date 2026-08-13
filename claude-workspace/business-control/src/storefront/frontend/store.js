/* Zenjoy storefront — talks to the brain only through /api/store/* and the
   shared funnel/order rails. */
"use strict";

const $ = (s) => document.querySelector(s);

// ---------- currency + locale ----------
const I18N = window.STORE_I18N || { currencies: [], locales: ["en"],
  ui: {}, strings: {} };
let CUR = I18N.currencies.find(
  (c) => c.code === localStorage.getItem("sf_cur")) ||
  I18N.currencies[0] || { code: "USD", symbol: "$", rate: 1 };
let LOCALE = localStorage.getItem("sf_locale") || "en";

const money = (c) => CUR.symbol + (c / 100 * (CUR.rate || 1)).toFixed(2);
// t(key, fallback) — merchant-managed translations, base copy when absent.
const t = (key, fallback) =>
  (I18N.strings[LOCALE] || {})[key] ?? fallback ?? I18N.ui[key] ?? key;
const pname = (p) => t(`product:${p.id}:name`, p.name);
const pdesc = (p) => t(`product:${p.id}:description`, p.description || "");

function buildPickers() {
  const cs = $("#currency-select"), ls = $("#locale-select");
  if (cs && I18N.currencies.length > 1) {
    cs.hidden = false;
    cs.innerHTML = I18N.currencies.map((c) =>
      `<option value="${c.code}" ${c.code === CUR.code ? "selected" : ""}>
        ${c.symbol} ${c.code}</option>`).join("");
    cs.onchange = () => {
      CUR = I18N.currencies.find((c) => c.code === cs.value);
      localStorage.setItem("sf_cur", CUR.code);
      drawGrid(); drawCart();
    };
  }
  if (ls && I18N.locales.length > 1) {
    ls.hidden = false;
    ls.innerHTML = I18N.locales.map((l) =>
      `<option value="${l}" ${l === LOCALE ? "selected" : ""}>
        ${l.toUpperCase()}</option>`).join("");
    ls.onchange = () => {
      LOCALE = ls.value; localStorage.setItem("sf_locale", LOCALE);
      location.reload();
    };
  }
}
const CATEGORY_ART = { beverage: "🧃", drink: "🧃", snack: "🍪", tea: "🍵",
  coffee: "☕", supplement: "💊", merch: "👕" };

// ---------- visitor id + funnel/pixel events ----------
const VID = localStorage.getItem("sf_vid") || crypto.randomUUID();
localStorage.setItem("sf_vid", VID);
const qs = new URLSearchParams(location.search);
// Affiliate attribution with an expiry window — a click shouldn't earn
// commission forever. Window comes from the server (default 30 days).
const REF_WINDOW_DAYS = (window.STORE_I18N || {}).affiliate_window_days || 30;
if (qs.get("ref") || qs.get("aff")) {
  const code = qs.get("ref") || qs.get("aff");
  localStorage.setItem("sf_ref_v2", JSON.stringify({ code, ts: Date.now() }));
  localStorage.setItem("sf_ref", code);
}
function activeRef() {
  try {
    const d = JSON.parse(localStorage.getItem("sf_ref_v2") || "null");
    if (d && d.code) {
      const age = (Date.now() - d.ts) / 86400000;
      if (age <= REF_WINDOW_DAYS) return d.code;
      localStorage.removeItem("sf_ref_v2");
      localStorage.removeItem("sf_ref");
      return "";
    }
  } catch {}
  return localStorage.getItem("sf_ref") || "";   // pre-window visitors
}

function funnel(step, extra = {}) {
  fetch("/api/events", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: VID, step, ...extra }) })
    .catch(() => {});
}
function pageview(page) {
  fetch("/api/store/track", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: VID, page }) }).catch(() => {});
}
funnel("visit");
pageview("home");

// ---------- shader hero (fragment-shader gradient flow) ----------
(function shaderHero() {
  const canvas = $("#shader-bg");
  if (!canvas) return;            // hero may use a gradient/image background
  const gl = canvas.getContext("webgl");
  if (!gl) { canvas.style.background =
    "linear-gradient(135deg,#6c00bf,#8a77e1)"; return; }
  const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  const fs = `precision mediump float;uniform float t;uniform vec2 r;
    // simplex-ish flowing gradient, Book of Shaders style
    float n(vec2 p){return sin(p.x)*sin(p.y);}
    void main(){
      vec2 uv=gl_FragCoord.xy/r; vec2 q=uv*3.0;
      float f=n(q+t*0.18)+0.5*n(q*2.1-t*0.12)+0.25*n(q*4.3+t*0.07);
      vec3 purple=vec3(0.424,0.0,0.749);
      vec3 lav=vec3(0.541,0.467,0.882);
      vec3 orange=vec3(1.0,0.412,0.0);
      vec3 col=mix(purple,lav,uv.y+0.35*f);
      col=mix(col,orange,smoothstep(0.75,1.25,f+uv.x*0.4)*0.35);
      gl_FragColor=vec4(col,1.0);}`;
  function sh(type, src) { const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s); return s; }
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog); gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const uT = gl.getUniformLocation(prog, "t");
  const uR = gl.getUniformLocation(prog, "r");
  function frame(ms) {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h);
    }
    gl.uniform1f(uT, ms / 1000);
    gl.uniform2f(uR, w, h);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

// ---------- catalog ----------
let CATALOG = { products: [], collections: [] };
let activeCollection = null;

function art(p, cls = "art", badge = true) {
  const media = p.media || [];
  const first = media[0];
  if (first) {
    const alt = (first.alt || p.name).replace(/"/g, "&quot;");
    const count = badge && media.length > 1
      ? `<span class="media-count">${media.length} ${
          media.some((m) => m.kind === "video") ? "▶" : "📷"}</span>` : "";
    return `<div class="${cls}"><img src="${first.thumb}" alt="${alt}"
      loading="lazy">${count}</div>`;
  }
  if (p.image) return `<div class="${cls}">
    <img src="/media/product/${p.id}" alt="${p.name}" loading="lazy"></div>`;
  const e = CATEGORY_ART[(p.category || "").toLowerCase()] || "🧃";
  return `<div class="${cls}">${e}</div>`;
}

function drawTabs() {
  const host = $("#collection-tabs");
  if (!host) return;
  const tabs = [{ slug: null, name: "All" },
    ...CATALOG.collections.map((c) => ({ slug: c.id, name: c.name }))];
  host.innerHTML = tabs.map((t) =>
    `<button class="tab ${activeCollection === t.slug ? "on" : ""}"
      data-col="${t.slug ?? ""}">${t.name}</button>`).join("");
  host.querySelectorAll(".tab").forEach((b) => b.onclick = () => {
    activeCollection = b.dataset.col === "" ? null : +b.dataset.col;
    drawTabs(); drawGrid();
  });
}

let SEARCH = null;  // Set of matching product ids, or null

function drawGrid() {
  const gridHost = $("#product-grid");
  if (!gridHost) return;
  // The section's own settings (chosen in the theme editor) scope the grid.
  const pinned = +gridHost.dataset.collection || null;
  const limit = +gridHost.dataset.limit || 0;
  let prods = CATALOG.products;
  if (SEARCH != null) prods = prods.filter((p) => SEARCH.has(p.id));
  else {
    const col = CATALOG.collections.find(
      (c) => c.id === (activeCollection ?? pinned));
    if (col) prods = prods.filter((p) => col.product_ids.includes(p.id));
  }
  if (limit > 0) prods = prods.slice(0, limit);
  gridHost.innerHTML = prods.map((p) => `
    <div class="product">
      <a href="/product/${p.id}-${p.slug}">${art(p)}</a>
      <a href="/product/${p.id}-${p.slug}"><b>${pname(p)}</b></a>
      <span class="stars" data-rev="${p.id}">
        ${p.review_avg ? "★".repeat(Math.round(p.review_avg)) +
          ` ${p.review_avg} (${p.review_count})` : "☆ be the first to review"}
      </span>
      <span class="desc">${pdesc(p)}</span>
      ${p.variants.length ? `<select class="var-sel" data-varsel="${p.id}">
        ${p.variants.map((v) => `<option value="${v.id}"
          data-price="${v.price_cents}" ${v.stock <= 0 ? "disabled" : ""}>
          ${v.name} — ${money(v.price_cents)}${v.stock <= 0 ? " · sold out" : ""}
        </option>`).join("")}</select>` : ""}
      <div class="price-row">
        <span class="price" data-price-for="${p.id}">
          ${money(p.variants.length ? p.variants[0].price_cents : p.price_cents)}</span>
        <button class="add-btn" data-add="${p.id}">${t("add_to_cart", "Add to cart")}</button>
      </div>
    </div>`).join("") ||
    `<p class="dim">${SEARCH != null ? "Nothing matched — try another word."
      : "No products yet — add some in the store admin."}</p>`;
  document.querySelectorAll("[data-varsel]").forEach((s) => s.onchange = () => {
    document.querySelector(`[data-price-for="${s.dataset.varsel}"]`)
      .textContent = money(+s.selectedOptions[0].dataset.price);
  });
  document.querySelectorAll("[data-add]").forEach((b) =>
    b.onclick = () => {
      const sel = document.querySelector(
        `[data-varsel="${b.dataset.add}"]`);
      addToCart(+b.dataset.add, sel ? +sel.value : 0);
    });
  document.querySelectorAll("[data-rev]").forEach((b) =>
    b.onclick = () => openReviews(+b.dataset.rev));
}

// ---------- search (FTS-backed) ----------
let searchTimer;
if ($("#search-input")) $("#search-input").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = $("#search-input").value.trim();
    if (!q) { SEARCH = null; drawGrid(); return; }
    const rows = await (await fetch(
      "/api/store/search?q=" + encodeURIComponent(q))).json();
    SEARCH = new Set(rows.map((r) => r.id));
    pageview("search:" + q.slice(0, 40));
    drawGrid();
  }, 250);
};

function drawSideMenu() {
  const host = $("#side-collections");
  let html = '<div class="side-group">Shop</div>' +
    '<a class="side-item" href="#shop" data-close>🛍 All products</a>';
  for (const c of CATALOG.collections) {
    html += `<a class="side-item" href="#shop" data-close
      data-colnav="${c.id}">▸ ${c.name}</a>`;
  }
  html += '<div class="side-group">Products</div>';
  for (const p of CATALOG.products.slice(0, 12)) {
    html += `<a class="side-item" href="#shop" data-close>· ${p.name}</a>`;
  }
  host.innerHTML = html;
  host.querySelectorAll("[data-colnav]").forEach((a) => a.onclick = () => {
    activeCollection = +a.dataset.colnav; drawTabs(); drawGrid();
  });
  host.querySelectorAll("[data-close]").forEach((a) =>
    a.addEventListener("click", closeMenus));
}

async function loadCatalog() {
  const r = await fetch("/api/store/catalog");
  CATALOG = await r.json();
  drawTabs(); drawGrid(); drawSideMenu(); drawReviewWall();
}

// ---------- review wall + review modal ----------
async function drawReviewWall() {
  const host = $("#review-wall");
  if (!host) return;         // the reviews section renders server-side now
  const top = CATALOG.products.filter((p) => p.review_count > 0).slice(0, 3);
  if (!top.length) {
    host.innerHTML = `<div class="review-card"><span class="stars">★★★★★</span>
      <p>"The calm I didn't know a can could hold."</p>
      <span class="who">— early tester · reviews go live with your first customers</span></div>`;
    return;
  }
  const cards = [];
  for (const p of top) {
    const revs = await (await fetch(`/api/store/reviews/${p.id}`)).json();
    for (const rv of revs.slice(0, 2)) {
      cards.push(`<div class="review-card">
        <span class="stars">${"★".repeat(rv.rating)}</span>
        <p>"${rv.body || "Love it."}"</p>
        <span class="who">— ${rv.name} · ${p.name}</span></div>`);
    }
  }
  host.innerHTML = cards.join("");
}

async function openReviews(pid) {
  funnel("view_product", { product_id: pid });
  pageview("product:" + pid);
  const p = CATALOG.products.find((x) => x.id === pid);
  const revs = await (await fetch(`/api/store/reviews/${pid}`)).json();
  openModal(`<h3>${p.name} — reviews</h3>
    ${revs.map((rv) => `<div class="review-card" style="margin-bottom:10px">
      <span class="stars">${"★".repeat(rv.rating)}</span>
      ${rv.verified ? '<span class="dim">✓ verified buyer</span>' : ""}
      <p>${rv.body || ""}</p><span class="who">— ${rv.name}</span></div>`)
      .join("") || '<p class="dim">No reviews yet — start the party.</p>'}
    <h3 style="margin-top:16px">Leave yours</h3>
    <label>Name</label><input id="rv-name" placeholder="Your name">
    <label>Email <span class="dim">(order email → ✓ verified-buyer badge)</span></label>
    <input id="rv-email" type="email">
    <label>Rating</label>
    <select id="rv-rating"><option>5</option><option>4</option><option>3</option>
      <option>2</option><option>1</option></select>
    <label>Review</label><textarea id="rv-body" rows="3"></textarea>
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Close</button>
      <button class="btn-pill primary sm" id="rv-send">Post review</button>
    </div>`);
  $("#rv-send").onclick = async () => {
    const r = await fetch("/api/store/reviews", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_id: pid,
        name: $("#rv-name").value, email: $("#rv-email").value,
        rating: +$("#rv-rating").value,
        body: $("#rv-body").value }) });
    if (r.ok) { toast("Thanks! Your review appears once approved 💜");
      closeModal(); }
  };
}

// ---------- cart (keys are "productId:variantId", 0 = no variant) ----------
let CART = JSON.parse(localStorage.getItem("sf_cart") || "{}");
for (const k of Object.keys(CART))  // migrate pre-variant carts
  if (!k.includes(":")) { CART[k + ":0"] = CART[k]; delete CART[k]; }
let DISCOUNT = null;

function cartLine(key) {
  const [pid, vid] = key.split(":").map(Number);
  const p = CATALOG.products.find((x) => x.id === pid);
  if (!p) return null;
  const v = vid ? (p.variants || []).find((x) => x.id === vid) : null;
  return { p, v, unit: v ? v.price_cents : p.price_cents,
    label: p.name + (v ? " · " + v.name : "") };
}

function saveCart() {
  localStorage.setItem("sf_cart", JSON.stringify(CART));
  const n = Object.values(CART).reduce((a, b) => a + b, 0);
  $("#cart-count").textContent = n;
}

function addToCart(pid, vid = 0) {
  const key = `${pid}:${vid}`;
  CART[key] = (CART[key] || 0) + 1;
  saveCart(); drawCart(); openCart();
  funnel("add_to_cart", { product_id: pid });
  toast("Added to cart 🛒");
}

function drawCart() {
  const host = $("#cart-items");
  const lines = Object.entries(CART).map(([key, qty]) => {
    const l = cartLine(key);
    if (!l) return "";
    return `<div class="cart-line">${art(l.p, "art", false)}
      <div><b>${l.label}</b><span class="dim">${money(l.unit)} each</span></div>
      <div class="qty">
        <button data-dec="${key}">−</button><span>${qty}</span>
        <button data-inc="${key}">+</button>
      </div></div>`;
  }).join("");
  host.innerHTML = lines || '<p class="dim">Cart\'s empty — fix that ✨</p>';
  host.querySelectorAll("[data-inc]").forEach((b) => b.onclick = () => {
    CART[b.dataset.inc]++; saveCart(); drawCart(); });
  host.querySelectorAll("[data-dec]").forEach((b) => b.onclick = () => {
    const k = b.dataset.dec;
    if (--CART[k] <= 0) delete CART[k];
    saveCart(); drawCart(); });
  const sub = Object.entries(CART).reduce((a, [key, q]) => {
    const l = cartLine(key);
    return a + (l ? l.unit * q : 0); }, 0);
  let total = sub, note = "";
  if (DISCOUNT) {
    total = Math.max(0, sub - (DISCOUNT.amount_cents || 0));
    note = `<span class="dim">${DISCOUNT.code} · ${DISCOUNT.label} ·
      <span class="strike">${money(sub)}</span></span>`;
  }
  if (GIFT) {
    const used = Math.min(GIFT.balance_cents, total);
    total = Math.max(0, total - used);
    note += `<span class="dim">🎁 ${GIFT.code} −${money(used)}</span>`;
  }
  const freeShip = DISCOUNT && DISCOUNT.free_shipping;
  $("#cart-total").innerHTML = sub ?
    `${t("total", "Total")}: ${money(total)} ${note}
     <span class="dim">${freeShip ? "🚚 free shipping applied"
       : sub >= 4000 ? "🎉 free shipping"
       : t("free_shipping_at", "free shipping at $40")}</span>` : "";
  drawUpsell();
}

function cartSubtotal() {
  return Object.entries(CART).reduce((a, [key, q]) => {
    const l = cartLine(key); return a + (l ? l.unit * q : 0); }, 0);
}

$("#discount-apply").onclick = async () => {
  const code = $("#discount-input").value.trim();
  if (!code) return;
  const r = await fetch("/api/store/discount/preview", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, subtotal_cents: cartSubtotal() }) });
  const out = await r.json();
  if (r.ok) { DISCOUNT = out;
    $("#discount-msg").textContent = `${out.label} applied ✔`; }
  else { DISCOUNT = null;
    // The server explains *why* (min spend, expired, already used…).
    $("#discount-msg").textContent = out.detail || "invalid code"; }
  drawCart();
};

// ---------- gift cards ----------
let GIFT = null;
$("#gift-apply").onclick = async () => {
  const code = $("#gift-input").value.trim();
  if (!code) return;
  const r = await fetch(`/api/store/gift-card/${encodeURIComponent(code)}`);
  if (r.ok) { GIFT = await r.json();
    $("#gift-msg").textContent = `${money(GIFT.balance_cents)} available ✔`; }
  else { GIFT = null; $("#gift-msg").textContent = "no such gift card"; }
  drawCart();
};

// ---------- cart cross-sell ----------
let upsellFor = null;
async function drawUpsell() {
  const host = $("#cart-upsell");
  if (!host) return;
  const keys = Object.keys(CART);
  if (!keys.length) { host.innerHTML = ""; upsellFor = null; return; }
  const pid = +keys[0].split(":")[0];
  if (upsellFor === pid) return;          // don't refetch on every redraw
  upsellFor = pid;
  const recs = await (await fetch(
    `/api/store/recommendations/${pid}?limit=2`)).json();
  const inCart = new Set(keys.map((k) => +k.split(":")[0]));
  const show = recs.filter((r) => !inCart.has(r.id)).slice(0, 2);
  host.innerHTML = show.length ? `<div class="upsell">
    <b>Goes well with</b>
    ${show.map((r) => `<div class="upsell-row">
      ${r.media && r.media[0]
        ? `<img src="${r.media[0].thumb}" alt="">`
        : '<span class="upsell-emoji">🧃</span>'}
      <div><b>${pname(r)}</b><span class="dim">${money(r.price_cents)}</span></div>
      <button class="btn-pill ghost sm" data-up="${r.id}">Add</button>
    </div>`).join("")}</div>` : "";
  host.querySelectorAll("[data-up]").forEach((b) =>
    b.onclick = () => addToCart(+b.dataset.up, 0));
}

// ---------- checkout (guest-friendly, rides the ERP rails) ----------
$("#checkout-btn").onclick = async () => {
  if (!Object.keys(CART).length) { toast("Cart is empty"); return; }
  funnel("checkout");
  pageview("checkout");
  const methods = await (await fetch("/api/store/shipping")).json();
  const sub = Object.entries(CART).reduce((a, [key, q]) => {
    const l = cartLine(key); return a + (l ? l.unit * q : 0); }, 0);
  const disc = DISCOUNT ? Math.round(sub * (100 - DISCOUNT.pct) / 100) : sub;
  openModal(`<h3>Checkout</h3>
    <label>Name</label><input id="co-name" placeholder="Full name">
    <label>Email</label><input id="co-email" type="email" placeholder="you@example.com">
    <label>Address</label><input id="co-addr" placeholder="Street address">
    <div class="row"><div><label>City</label><input id="co-city"></div>
      <div><label>Postal</label><input id="co-postal"></div></div>
    <label>Shipping</label>
    ${methods.map((m, i) => `<label class="ship-opt">
      <input type="radio" name="co-ship" value="${m.id}" ${i === 0 ? "checked" : ""}>
      <b>${m.name}</b><span class="dim">${m.eta}</span>
      <span>${m.position === 0 && disc >= 4000 ? "FREE" : money(m.price_cents)}</span>
    </label>`).join("")}
    <label>Payment</label>
    <label class="ship-opt"><input type="radio" name="co-pay" value="card" checked>
      <b>Card · Apple Pay · Google Pay</b><span class="dim">via Stripe</span></label>
    <label class="ship-opt"><input type="radio" name="co-pay" value="cod">
      <b>Pay on delivery</b></label>
    <label class="ship-opt"><input type="checkbox" id="co-subscribe">
      <b>🔁 Make it a monthly box</b>
      <span class="dim">skip · pause · cancel any time</span></label>
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Back</button>
      <button class="btn-pill primary sm" id="co-place">Place order</button>
    </div>
    <p class="dim" id="co-msg" style="margin-top:8px"></p>`);
  $("#co-place").onclick = placeOrder;
};

async function placeOrder() {
  const name = $("#co-name").value.trim();
  const email = $("#co-email").value.trim();
  const msg = $("#co-msg");
  if (!name || !$("#co-addr").value.trim() || !$("#co-city").value.trim()) {
    msg.textContent = "name, address and city are required"; return;
  }
  msg.textContent = "placing order…";
  try {
    const login = await (await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, role: "customer", email }) })).json();
    const shipEl = document.querySelector('[name="co-ship"]:checked');
    const payEl = document.querySelector('[name="co-pay"]:checked');
    const r = await fetch("/api/orders", { method: "POST",
      headers: { "Content-Type": "application/json",
        Authorization: "Bearer " + login.token },
      body: JSON.stringify({
        items: Object.entries(CART).map(([key, qty]) => {
          const [pid, vid] = key.split(":").map(Number);
          return { product_id: pid, qty, variant_id: vid || null };
        }),
        visitor_id: VID,
        affiliate_code: activeRef(),
        discount_code: DISCOUNT ? DISCOUNT.code : "",
        gift_card_code: GIFT ? GIFT.code : "",
        shipping_method_id: shipEl ? +shipEl.value : null,
        pay_method: payEl ? payEl.value : "",
        ship_name: name, address: $("#co-addr").value.trim(),
        city: $("#co-city").value.trim(),
        postal: $("#co-postal").value.trim() }) });
    const out = await r.json();
    if (!r.ok) { msg.textContent = out.detail || "order failed"; return; }
    funnel("purchase", { value_cents: out.total_cents || 0 });
    // Stay signed in after checkout (account, chat, payment confirmation).
    localStorage.setItem("sf_support",
      JSON.stringify({ token: login.token, me: login.id }));
    if ($("#co-subscribe")?.checked) {   // monthly box: subscription rows
      await fetch("/api/store/account/subscriptions", { method: "POST",
        headers: { "Content-Type": "application/json",
          Authorization: "Bearer " + login.token },
        body: JSON.stringify({ items: Object.entries(CART).map(
          ([key, qty]) => { const [pid, vid] = key.split(":").map(Number);
            return { product_id: pid, variant_id: vid || null, qty }; }) })
      }).catch(() => {});
    }
    if (out.checkout_url) {   // Stripe Checkout (cards + wallets)
      CART = {}; DISCOUNT = null; saveCart();
      location.href = out.checkout_url; return;
    }
    if (email) fetch("/api/store/subscribe", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, source: "checkout" }) });
    CART = {}; DISCOUNT = null; saveCart(); drawCart();
    closeModal(); closeMenus();
    openModal(`<h3>Order placed 💜</h3>
      <p>Order <b>#${out.id || out.order_id || ""}</b> is in. Track it any
      time with the 📦 button.</p>
      <div class="modal-actions">
        <button class="btn-pill primary sm" data-close-modal>Done</button>
      </div>`);
    wireModalClose();
  } catch (e) { msg.textContent = "network hiccup — try again"; }
}

// ---------- order tracking ----------
function openTracking() {
  openModal(`<h3>Track my order</h3>
    <label>Order number</label><input id="tr-id" type="number" placeholder="e.g. 42">
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Close</button>
      <button class="btn-pill primary sm" id="tr-go">Track</button>
    </div>
    <div id="tr-out"></div>`);
  $("#tr-go").onclick = async () => {
    const r = await fetch(`/api/store/order-status/${+$("#tr-id").value}`);
    const host = $("#tr-out");
    if (!r.ok) { host.innerHTML = '<p class="dim">order not found</p>'; return; }
    const o = await r.json();
    host.innerHTML = `<div class="track-steps">${o.steps.map((s, i) =>
      `<span class="${i <= o.step_index ? "done" : ""}">${s}</span>`)
      .join("")}</div>
      <p class="dim">Order #${o.id} · ${money(o.total_cents)}
      ${o.discount_cents ? `· ${o.discount_code} saved ${money(o.discount_cents)}` : ""}
      · payment ${o.payment_status}</p>`;
  };
}

// ---------- subscribe ----------
if ($("#subscribe-form")) $("#subscribe-form").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/store/subscribe", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: $("#subscribe-email").value,
      source: "rewards" }) });
  $("#subscribe-msg").textContent = r.ok ?
    "Welcome to the club — check your inbox 💌" : "hmm, try a real email?";
  if (r.ok) $("#subscribe-email").value = "";
};

// ---------- promo strip (limited-time offers) ----------
async function loadPromos() {
  const promos = await (await fetch("/api/store/promos")).json();
  const pid = qs.get("promo");
  const promo = (pid && promos.find((p) => p.id === +pid)) || promos[0];
  if (!promo) return;
  $("#promo-strip").hidden = false;
  $("#promo-name").textContent = promo.name +
    (promo.discount_pct ? ` — ${promo.discount_pct}% off` : "");
  $("#promo-body").textContent = promo.body || "limited time";
  const end = new Date(); end.setHours(23, 59, 59, 0);
  setInterval(() => {
    const s = Math.max(0, (end - Date.now()) / 1000 | 0);
    $("#promo-countdown").textContent =
      `${String(s / 3600 | 0).padStart(2, "0")}:` +
      `${String(s % 3600 / 60 | 0).padStart(2, "0")}:` +
      `${String(s % 60).padStart(2, "0")}`;
  }, 1000);
}

// ---------- menus, modal, toast plumbing ----------
function openCart() { $("#cart-drawer").classList.add("open");
  $("#scrim").classList.add("show"); }
function closeMenus() {
  $("#cart-drawer").classList.remove("open");
  $("#side-menu").classList.remove("open");
  $("#scrim").classList.remove("show");
}
function openModal(html) { $("#modal-card").innerHTML = html;
  $("#modal").classList.add("show"); wireModalClose(); }
function closeModal() { $("#modal").classList.remove("show"); }
function wireModalClose() {
  document.querySelectorAll("[data-close-modal]").forEach((b) =>
    b.onclick = closeModal);
}
let toastTimer;
function toast(txt) {
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast";
    document.body.appendChild(t); }
  t.textContent = txt; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2400);
}

$("#menu-btn").onclick = () => { $("#side-menu").classList.add("open");
  $("#scrim").classList.add("show"); };
$("#menu-close").onclick = closeMenus;
$("#cart-btn").onclick = () => { drawCart(); openCart(); };
$("#cart-close").onclick = closeMenus;
$("#scrim").onclick = closeMenus;
$("#modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal(); });
$("#track-btn").onclick = openTracking;
$("#foot-track").onclick = (e) => { e.preventDefault(); openTracking(); };
$("#side-track").onclick = (e) => { e.preventDefault(); closeMenus();
  openTracking(); };
// ---------- customer account: orders + subscription self-service ----------
function acctToken() {
  try { return JSON.parse(localStorage.getItem("sf_support") || "{}").token; }
  catch { return null; }
}

function openAccount() {
  if (!acctToken()) {
    openModal(`<h3>My account 👤</h3>
      <p class="dim">Sign in with the name (and email) you ordered with.</p>
      <label>Name</label><input id="ac-name" placeholder="Your name">
      <label>Email</label><input id="ac-email" type="email">
      <div class="modal-actions">
        <button class="btn-pill ghost sm" data-close-modal>Later</button>
        <button class="btn-pill primary sm" id="ac-go">Sign in</button>
      </div>`);
    $("#ac-go").onclick = async () => {
      const name = $("#ac-name").value.trim();
      if (!name) return;
      const out = await (await fetch("/api/login", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, role: "customer",
          email: $("#ac-email").value.trim() }) })).json();
      if (!out.token) return;
      localStorage.setItem("sf_support",
        JSON.stringify({ token: out.token, me: out.id }));
      drawAccount();
    };
    return;
  }
  drawAccount();
}

async function drawAccount() {
  const H = { Authorization: "Bearer " + acctToken() };
  const [orders, subs] = await Promise.all([
    (await fetch("/api/store/account/orders", { headers: H })).json(),
    (await fetch("/api/store/account/subscriptions", { headers: H })).json()]);
  const aff = await (await fetch("/api/store/affiliate/stats",
    { headers: H })).json().catch(() => ({ joined: false }));
  const affBlock = aff.joined ? `
    <h3 style="font-size:15px;margin-top:14px">🔗 Affiliate</h3>
    <div class="ship-opt"><b>${location.origin}/r/${aff.code}</b></div>
    <div class="ship-opt">
      <span class="dim">${aff.clicks} clicks · ${aff.landing_views} landing
      views · ${aff.orders} orders</span>
      <b>${money(aff.earned_cents)} earned</b>
      <a class="btn-pill ghost sm" href="${aff.landing}">view page</a>
    </div>` : `
    <h3 style="font-size:15px;margin-top:14px">🔗 Affiliate</h3>
    <div class="ship-opt"><span class="dim">Share what you love and earn on
      every order.</span>
      <a class="btn-pill ghost sm" href="/affiliates">Join the program</a>
    </div>`;
  const cutoffNote = subs.changes_open ? "" :
    `<p class="dim">⏳ Box changes are closed for this cycle (curation is
     locked) — skip reopens after shipping.</p>`;
  openModal(`<h3>My account 👤</h3>
    <h3 style="font-size:15px;margin-top:6px">🔁 Monthly boxes</h3>
    ${cutoffNote}
    ${(subs.subscriptions || []).map((s) => `
      <div class="ship-opt"><b>${s.name} × ${s.qty}</b>
       <span class="dim">${money(s.price_cents * s.qty)}/mo · ${s.status}</span>
       ${s.status === "active" ? `
         <button class="btn-pill ghost sm" data-sub="${s.id}:skip">skip next</button>
         <button class="btn-pill ghost sm" data-sub="${s.id}:pause">pause</button>`
       : s.status === "skipped_next" ? `
         <button class="btn-pill ghost sm" data-sub="${s.id}:unskip">unskip</button>`
       : `<button class="btn-pill ghost sm" data-sub="${s.id}:resume">resume</button>`}
       <button class="btn-pill ghost sm" data-sub="${s.id}:cancel">cancel</button>
      </div>`).join("") ||
      '<p class="dim">No boxes yet — tick 🔁 at checkout.</p>'}
    <h3 style="font-size:15px;margin-top:14px">📦 Orders</h3>
    ${(orders || []).map((o) => `
      <div class="ship-opt"><b>#${o.id}</b>
       <span class="dim">${o.items.map((i) =>
         `${i.qty}× ${i.name}${i.variant_name ? " · " + i.variant_name : ""}`)
         .join(", ").slice(0, 60)}</span>
       <span>${o.status} · ${money(o.total_cents)}</span>
      </div>`).join("") || '<p class="dim">No orders yet.</p>'}
    ${affBlock}
    <div class="modal-actions">
      <button class="btn-pill ghost sm" id="ac-out">Sign out</button>
      <button class="btn-pill primary sm" data-close-modal>Done</button>
    </div>`);
  document.querySelectorAll("[data-sub]").forEach((b) => b.onclick =
    async () => {
      const [sid, action] = b.dataset.sub.split(":");
      const r = await fetch(`/api/store/account/subscriptions/${sid}/action`,
        { method: "POST", headers: { "Content-Type": "application/json",
          ...H }, body: JSON.stringify({ action }) });
      if (!r.ok) toast((await r.json()).detail || "not allowed");
      drawAccount();
    });
  $("#ac-out").onclick = () => {
    localStorage.removeItem("sf_support"); closeModal(); };
}

$("#account-btn").onclick = openAccount;

// ---------- live support chat (rides the ERP Comms module) ----------
let SUPPORT = { token: "", conv: null, ws: null, lastId: 0, me: null };

function openSupport() {
  const saved = JSON.parse(localStorage.getItem("sf_support") || "null");
  if (saved && saved.token) { SUPPORT.token = saved.token;
    SUPPORT.me = saved.me; startSupportChat(); return; }
  openModal(`<h3>We're here 💬</h3>
    <p class="dim">Real humans on the other end — same system the team runs
    on. What should we call you?</p>
    <label>Name</label><input id="sp-name" placeholder="Your name">
    <label>Email (optional)</label><input id="sp-email" type="email">
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Later</button>
      <button class="btn-pill primary sm" id="sp-start">Start chat</button>
    </div>`);
  $("#sp-start").onclick = async () => {
    const name = $("#sp-name").value.trim();
    if (!name) return;
    const out = await (await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, role: "customer",
        email: $("#sp-email").value.trim() }) })).json();
    if (!out.token) return;
    SUPPORT.token = out.token; SUPPORT.me = out.id;
    localStorage.setItem("sf_support",
      JSON.stringify({ token: out.token, me: out.id }));
    startSupportChat();
  };
}

async function startSupportChat() {
  const H = { "Content-Type": "application/json",
    Authorization: "Bearer " + SUPPORT.token };
  const convs = await (await fetch("/api/chat/convs",
    { headers: H })).json();
  SUPPORT.me = convs.me;
  const conv = convs.convs.find((c) => c.kind === "support");
  if (!conv) return;
  SUPPORT.conv = conv.id;
  openModal(`<h3>Support 💬</h3>
    <div id="sp-msgs" style="max-height:300px;overflow-y:auto;
      background:#f7f4fb;border-radius:12px;padding:12px;margin:8px 0;
      display:flex;flex-direction:column;gap:6px"></div>
    <div class="row"><input id="sp-input" placeholder="Type a message…">
      <button class="btn-pill primary sm" id="sp-send"
        style="flex:0 0 auto">Send</button></div>
    <p class="dim" style="margin-top:6px">Messages land in the team's inbox
    (💬 in the ops app) — replies appear here live.</p>`);
  const draw = (msgs) => {
    const host = $("#sp-msgs");
    if (!host) return;
    for (const m of msgs) {
      if (m.id <= SUPPORT.lastId) continue;
      SUPPORT.lastId = m.id;
      const mine = m.user_id === SUPPORT.me;
      host.insertAdjacentHTML("beforeend",
        `<div style="align-self:${mine ? "flex-end" : "flex-start"};
          background:${mine ? "var(--purple)" : "#fff"};
          color:${mine ? "#fff" : "var(--ink)"};
          border-radius:12px;padding:7px 12px;max-width:82%;font-size:14px">
          ${mine ? "" : `<b style="font-size:11px;display:block;
            color:var(--lavender)">${m.name}</b>`}${m.body}</div>`);
    }
    host.scrollTop = host.scrollHeight;
  };
  const hist = await (await fetch(
    `/api/chat/convs/${SUPPORT.conv}/messages`, { headers: H })).json();
  SUPPORT.lastId = 0; draw(hist);
  if (!hist.length) draw([{ id: 0.5, user_id: -1, name: "Zenjoy",
    body: "Hey! How can we help? 💜" }]);
  // realtime: the same /ws the team uses
  try {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    SUPPORT.ws?.close();
    SUPPORT.ws = new WebSocket(
      `${proto}://${location.host}/ws?token=${SUPPORT.token}`);
    SUPPORT.ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === "msg" && d.conv_id === SUPPORT.conv)
        draw([d.message]);
    };
  } catch {}
  const send = async () => {
    const text = $("#sp-input").value.trim();
    if (!text) return;
    $("#sp-input").value = "";
    const m = await (await fetch(`/api/chat/convs/${SUPPORT.conv}/messages`, {
      method: "POST", headers: H,
      body: JSON.stringify({ body: text }) })).json();
    if (m && m.id) draw([{ ...m, name: "you" }]);
  };
  $("#sp-send").onclick = send;
  $("#sp-input").onkeydown = (e) => { if (e.key === "Enter") send(); };
}
$("#support-btn").onclick = openSupport;
$("#foot-support").onclick = (e) => { e.preventDefault(); openSupport(); };

// ---------- PWA ----------
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/sf-sw.js").catch(() => {});

// ---------- Stripe return: confirm payment server-side ----------
async function confirmPaidReturn() {
  const oid = qs.get("paid"), sid = qs.get("sid");
  if (!oid || !sid) return;
  history.replaceState(null, "", "/");
  const token = acctToken();
  if (!token) return;
  try {
    const r = await fetch(`/api/orders/${+oid}/confirm-payment`, {
      method: "POST", headers: { "Content-Type": "application/json",
        Authorization: "Bearer " + token },
      body: JSON.stringify({ session_id: sid }) });
    if (r.ok) openModal(`<h3>Payment confirmed 💳</h3>
      <p>Order <b>#${+oid}</b> is paid and in the queue — receipt's in your
      inbox, and 👤 has the details.</p>
      <div class="modal-actions">
        <button class="btn-pill primary sm" data-close-modal>Done</button>
      </div>`);
    else toast("Payment is still settling — check 👤 in a minute");
  } catch {}
}
if (qs.get("cancelled")) toast("Checkout cancelled — cart's still here 💜");

// ---------- boot ----------
buildPickers();
saveCart();
loadCatalog().then(() => {
  loadPromos();
  confirmPaidReturn();
  if (qs.get("cart")) { drawCart(); openCart(); }  // back from product page
});
