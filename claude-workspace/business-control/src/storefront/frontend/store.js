/* Zenjoy storefront — talks to the brain only through /api/store/* and the
   shared funnel/order rails. */
"use strict";

const $ = (s) => document.querySelector(s);
/* Bind a click only if the element is on this page. The shell now serves
   several page shapes (home, partner pages, events, locator), and a missing
   optional control used to throw at module scope and take the rest of the
   script — including the menu — down with it. */
const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; return el; };

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

/* Region, language and currency live in the preferences panel (with the
   accessibility controls), not the top bar — one quiet corner for everything
   about "how this site speaks to me", Celsius-style. Always populated, even
   with one option, so the shopper can see what they're set to. */
function buildPickers() {
  const cs = $("#currency-select"), ls = $("#locale-select"),
    rs = $("#region-select");
  if (cs) {
    const curs = I18N.currencies.length
      ? I18N.currencies : [{ code: "USD", symbol: "$", rate: 1 }];
    cs.innerHTML = curs.map((c) =>
      `<option value="${c.code}" ${c.code === CUR.code ? "selected" : ""}>
        ${c.symbol} ${c.code}</option>`).join("");
    cs.disabled = curs.length < 2;
    cs.onchange = () => {
      CUR = I18N.currencies.find((c) => c.code === cs.value) || CUR;
      localStorage.setItem("sf_cur", CUR.code);
      drawGrid(); drawCart();
    };
  }
  if (ls) {
    ls.innerHTML = I18N.locales.map((l) =>
      `<option value="${l}" ${l === LOCALE ? "selected" : ""}>
        ${l.toUpperCase()}</option>`).join("");
    ls.disabled = I18N.locales.length < 2;
    ls.onchange = () => {
      LOCALE = ls.value; localStorage.setItem("sf_locale", LOCALE);
      location.reload();
    };
  }
  if (rs) {
    const regions = I18N.regions && I18N.regions.length
      ? I18N.regions : ["Everywhere"];
    const saved = localStorage.getItem("sf_region") || regions[0];
    rs.innerHTML = regions.map((r) =>
      `<option value="${r}" ${r === saved ? "selected" : ""}>${r}</option>`)
      .join("");
    rs.onchange = () => localStorage.setItem("sf_region", rs.value);
  }
}

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
// the shell now serves partner pages, events and the locator too, so record
// the path rather than always claiming "home"
pageview(location.pathname === "/" ? "home" : location.pathname.slice(0, 60));

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

const ico = (name, cls = "ico") =>
  `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

// Flavour colour drives the card, the PDP and the cart line. Falls back to
// brand purple for anything without merchandising meta.
const flavourOf = (p) => p.colour || "#6c00bf";

/* Stand-in product art until photography exists.
   Draws the can using the brand's packaging grammar — same geometry, one ring
   colour per flavour (docs/brand/zen-artwork.html). It lives in a 4:5 slot so
   dropping real photos in later is a swap with no layout change. */
function canSVG(p, opts = {}) {
  const c = flavourOf(p);
  const id = "cg" + p.id + (opts.k || "");
  const label = (p.flavour === "pack" ? "" : (pname(p) || "").split(" —")[0]);
  return `<svg class="can" viewBox="0 0 200 320" role="img"
    aria-label="${(pname(p) || "").replace(/"/g, "&quot;")} can">
   <defs>
     <linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
       <stop offset="0" stop-color="${c}" stop-opacity=".95"/>
       <stop offset="1" stop-color="${c}" stop-opacity=".72"/>
     </linearGradient>
     <clipPath id="${id}c"><rect x="40" y="26" width="120" height="268" rx="26"/></clipPath>
   </defs>
   <ellipse cx="100" cy="300" rx="52" ry="7" fill="rgba(27,24,31,.13)"/>
   <rect x="40" y="26" width="120" height="268" rx="26" fill="url(#${id})"/>
   <g clip-path="url(#${id}c)" fill="none" stroke="#fff">
     <circle cx="100" cy="182" r="10" stroke-width="6" opacity=".95"/>
     <circle cx="100" cy="182" r="26" stroke-width="4.6" opacity=".8"/>
     <circle cx="100" cy="182" r="44" stroke-width="3.4" opacity=".6"/>
     <circle cx="100" cy="182" r="63" stroke-width="2.4" opacity=".42"/>
     <circle cx="100" cy="182" r="83" stroke-width="1.8" opacity=".26"/>
   </g>
   <rect x="40" y="26" width="120" height="268" rx="26" fill="none"
     stroke="rgba(27,24,31,.10)"/>
   <path d="M52 32h96" stroke="rgba(255,255,255,.55)" stroke-width="7"
     stroke-linecap="round"/>
   <ellipse cx="100" cy="26" rx="60" ry="9" fill="#d9d4dd"/>
   <ellipse cx="100" cy="24" rx="52" ry="7" fill="#eceaef"/>
   ${opts.mini ? "" : `<text x="100" y="92" text-anchor="middle" fill="#fff"
     font-size="21" font-family="Quicksand, sans-serif" font-weight="700"
     letter-spacing="-.5" aria-hidden="true">zenjoy<tspan fill="#ffd9b8">.</tspan></text>`}
   ${label && !opts.mini ? `<text x="100" y="266" text-anchor="middle" fill="#fff"
     font-size="13" font-family="Inter, sans-serif" font-weight="600"
     opacity=".95" aria-hidden="true">${label}</text>` : ""}
  </svg>`;
}

// The concentric-ring mark on its own — flavour chips and pickers.
function ringSVG(colour, cls = "ring") {
  return `<svg class="${cls}" viewBox="0 0 120 120" aria-hidden="true">
    <g fill="none" stroke="${colour}">
      <circle cx="60" cy="60" r="9" stroke-width="11"/>
      <circle cx="60" cy="60" r="26" stroke-width="8"/>
      <circle cx="60" cy="60" r="44" stroke-width="5.5" opacity=".7"/>
    </g></svg>`;
}

function art(p, cls = "art", badge = true, mini = false) {
  const style = ` style="--flavour:${flavourOf(p)};--flavour-soft:${
    flavourOf(p)}1f"`;
  const media = p.media || [];
  const first = media[0];
  if (first) {
    const alt = (first.alt || p.name).replace(/"/g, "&quot;");
    const count = badge && media.length > 1
      ? `<span class="media-count">${media.length} ${
          media.some((m) => m.kind === "video") ? "video" : "photos"}</span>` : "";
    return `<div class="${cls}"${style}><img src="${first.thumb}" alt="${alt}"
      loading="lazy">${count}</div>`;
  }
  if (p.image) return `<div class="${cls}"${style}>
    <img src="/media/product/${p.id}" alt="${p.name}" loading="lazy"></div>`;
  return `<div class="${cls}"${style}>${canSVG(p, { k: cls, mini })}</div>`;
}

function drawTabs() {
  const host = $("#collection-tabs");
  if (!host) return;
  // Flavour-led filtering: one chip per flavour, colour-coded, plus the
  // editor's collections. Flavour is the way people actually shop a range.
  const flavs = [];
  for (const p of CATALOG.products) {
    if (!p.flavour || p.flavour === "pack") continue;
    if (!flavs.some((f) => f.slug === p.flavour)) {
      flavs.push({ slug: p.flavour, name: pname(p), colour: flavourOf(p) });
    }
  }
  const tabs = [{ slug: null, name: "All" },
    ...CATALOG.collections.map((c) => ({ slug: c.id, name: c.name })),
    ...flavs.map((f) => ({ slug: "f:" + f.slug, name: f.name, colour: f.colour }))];
  host.innerHTML = tabs.map((tb) =>
    `<button class="tab ${activeCollection === tb.slug ? "on" : ""}"
      data-col="${tb.slug ?? ""}">${tb.colour
        ? `<span class="swatch" style="background:${tb.colour}"></span>` : ""
      }${tb.name}</button>`).join("");
  host.querySelectorAll(".tab").forEach((b) => b.onclick = () => {
    const v = b.dataset.col;
    activeCollection = v === "" ? null : (v.startsWith("f:") ? v : +v);
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
  else if (typeof activeCollection === "string"
           && activeCollection.startsWith("f:")) {
    const f = activeCollection.slice(2);
    prods = prods.filter((p) => p.flavour === f);
  } else {
    const col = CATALOG.collections.find(
      (c) => c.id === (activeCollection ?? pinned));
    if (col) prods = prods.filter((p) => col.product_ids.includes(p.id));
  }
  if (limit > 0) prods = prods.slice(0, limit);
  gridHost.innerHTML = prods.map((p) => `
    <div class="product" style="--flavour:${flavourOf(p)}">
      ${p.badge ? `<span class="badge">${p.badge}</span>` : ""}
      <a href="/product/${p.id}-${p.slug}" aria-label="${pname(p)}">${art(p)}</a>
      <div class="body">
        <a href="/product/${p.id}-${p.slug}"><b>${pname(p)}</b></a>
        ${p.review_avg ? `<span class="stars" data-rev="${p.id}">
            ${ico("star", "ico").repeat(Math.round(p.review_avg))}
            ${p.review_avg} (${p.review_count})</span>` : ""}
        <span class="note">${p.note || pdesc(p)}</span>
        ${p.variants.length ? `<select class="var-sel" data-varsel="${p.id}"
          aria-label="Choose an option">
          ${p.variants.map((v) => `<option value="${v.id}"
            data-price="${v.price_cents}" ${v.stock <= 0 ? "disabled" : ""}>
            ${v.name} — ${money(v.price_cents)}${v.stock <= 0 ? " · sold out" : ""}
          </option>`).join("")}</select>` : ""}
        <div class="price-row">
          <span class="price" data-price-for="${p.id}">
            ${money(p.variants.length ? p.variants[0].price_cents : p.price_cents)}</span>
          <button class="add-btn" data-add="${p.id}">${t("add_to_cart", "Add")}</button>
        </div>
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

/* The menu is a storefront in miniature, not a list of links — every product
   shows its face (Primal Queen-style), so the range is browsable before the
   page even scrolls. */
function drawSideMenu() {
  const host = $("#side-collections");
  // Browse first: the shopper picks a lane, then sees the faces. Putting the
  // tiles above the filters made people scroll past the filters entirely.
  let html = '<div class="menu-headline">Shop the range</div>' +
    '<div class="side-group">Browse</div><div class="menu-cols">' +
    `<a class="side-item" href="/#shop" data-close>${ico("bag", "ico ico-sm")}
      All products</a>`;
  for (const c of CATALOG.collections) {
    html += `<a class="side-item" href="/#shop" data-close
      data-colnav="${c.id}">${c.name}</a>`;
  }
  html += '</div><div class="side-group">Every flavour</div>' +
    '<div class="menu-tiles">';
  for (const p of CATALOG.products) {
    html += `<a class="menu-tile" href="/product/${p.id}-${p.slug}"
      style="--flavour:${flavourOf(p)};--flavour-soft:${flavourOf(p)}1f">
      ${art(p, "art", false)}
      <b>${pname(p)}</b>
      <span>${money(p.variants.length
        ? p.variants[0].price_cents : p.price_cents)}</span></a>`;
  }
  html += "</div>";
  host.innerHTML = html;
  host.querySelectorAll("[data-colnav]").forEach((a) => a.onclick = () => {
    activeCollection = +a.dataset.colnav; drawTabs(); drawGrid();
  });
  host.querySelectorAll("[data-close]").forEach((a) =>
    a.addEventListener("click", closeMenus));
}

/* The hero sells the product, so the product has to be in it. Picks the first
   single flavour and shows its photo if one exists, else the drawn can. */
function hydrateHero() {
  const stage = $("#hero-stage");
  if (!stage) return;
  const p = CATALOG.products.find((x) => x.flavour && x.flavour !== "pack")
    || CATALOG.products[0];
  if (!p) return;
  const shot = (p.media || [])[0];
  // the ripple breathes behind the can — the packaging grammar at page scale
  const rings = `<svg class="hero-rings" viewBox="0 0 400 400" aria-hidden="true">
    <g fill="none" stroke="${flavourOf(p)}">
      <circle cx="200" cy="200" r="70" stroke-width="2" opacity=".28"/>
      <circle cx="200" cy="200" r="115" stroke-width="1.6" opacity=".2"/>
      <circle cx="200" cy="200" r="160" stroke-width="1.3" opacity=".13"/>
      <circle cx="200" cy="200" r="198" stroke-width="1" opacity=".07"/>
    </g></svg>`;
  stage.innerHTML = `${rings}<a href="/product/${p.id}-${p.slug}"
    aria-label="${pname(p)}">${shot
      ? `<img src="${shot.thumb}" alt="${(shot.alt || pname(p))
          .replace(/"/g, "&quot;")}" style="border-radius:var(--r-lg)">`
      : canSVG(p, { k: "hero" })}</a>`;
}

/* The buy button that never scrolls away. With items it opens the cart;
   empty it takes you to the range. */
(function wireBuyFab() {
  const fab = $("#buy-fab");
  if (!fab) return;
  fab.onclick = () => {
    const n = Object.values(CART).reduce((a, b) => a + b, 0);
    if (n) { drawCart(); openCart(); return; }
    const shop = document.getElementById("shop");
    if (shop) shop.scrollIntoView({ behavior: "smooth" });
    else location.href = "/#shop";
  };
})();

async function loadCatalog() {
  const r = await fetch("/api/store/catalog");
  CATALOG = await r.json();
  drawTabs(); drawGrid(); drawSideMenu(); drawReviewWall(); hydrateHero();
}

// ---------- review wall + review modal ----------
async function drawReviewWall() {
  const host = $("#review-wall");
  if (!host) return;         // the reviews section renders server-side now
  const top = CATALOG.products.filter((p) => p.review_count > 0).slice(0, 3);
  if (!top.length) {
    host.innerHTML = `<div class="review-card"><span class="stars">${ico("star").repeat(5)}</span>
      <p>"The calm I didn't know a can could hold."</p>
      <span class="who">— early tester · reviews go live with your first customers</span></div>`;
    return;
  }
  const cards = [];
  for (const p of top) {
    const revs = await (await fetch(`/api/store/reviews/${p.id}`)).json();
    for (const rv of revs.slice(0, 2)) {
      cards.push(`<div class="review-card">
        <span class="stars">${ico("star").repeat(rv.rating)}</span>
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
      <span class="stars">${ico("star").repeat(rv.rating)}</span>
      ${rv.verified ? `<span class="dim">${ico("check","ico ico-sm")} verified buyer</span>` : ""}
      <p>${rv.body || ""}</p><span class="who">— ${rv.name}</span></div>`)
      .join("") || '<p class="dim">No reviews yet — start the party.</p>'}
    <h3 style="margin-top:16px">Leave yours</h3>
    <label>Name</label><input id="rv-name" placeholder="Your name">
    <label>Email <span class="dim">(order email earns a verified-buyer badge)</span></label>
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
    if (r.ok) { toast("Thanks — your review appears once approved.");
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
  const fc = $("#buy-fab-count");
  if (fc) { fc.hidden = !n; fc.textContent = n; }
  const mc = $("#menu-cart-count");
  if (mc) mc.textContent = n;
}

function addToCart(pid, vid = 0) {
  const key = `${pid}:${vid}`;
  CART[key] = (CART[key] || 0) + 1;
  saveCart(); drawCart(); openCart();
  funnel("add_to_cart", { product_id: pid });
  toast("Added to cart");
}

const FREE_SHIP_AT = 4000;

function drawCart() {
  const host = $("#cart-items");
  const lines = Object.entries(CART).map(([key, qty]) => {
    const l = cartLine(key);
    if (!l) return "";
    return `<div class="cart-line" style="--flavour:${flavourOf(l.p)}">
      ${art(l.p, "art", false, true)}
      <div><b>${l.label}</b>
        <span class="dim">${money(l.unit)} each</span>
        <span class="line-price">${money(l.unit * qty)}</span></div>
      <div class="qty">
        <button data-dec="${key}" aria-label="Remove one ${l.label}">
          ${ico("minus", "ico ico-sm")}</button>
        <span>${qty}</span>
        <button data-inc="${key}" aria-label="Add one ${l.label}">
          ${ico("plus", "ico ico-sm")}</button>
      </div></div>`;
  }).join("");
  host.innerHTML = lines || `<div class="cart-empty">
    ${ico("bag", "ico")}<p>Your cart is empty.</p>
    <button class="btn-pill ghost sm" id="cart-empty-shop"
      style="margin-top:14px">Shop the range</button></div>`;
  const shopBtn = $("#cart-empty-shop");
  if (shopBtn) shopBtn.onclick = () => {
    closeMenus();
    const shop = document.getElementById("shop");
    if (shop) shop.scrollIntoView({ behavior: "smooth" });
    else location.href = "/#shop";
  };
  host.querySelectorAll("[data-inc]").forEach((b) => b.onclick = () => {
    CART[b.dataset.inc]++; saveCart(); drawCart(); });
  host.querySelectorAll("[data-dec]").forEach((b) => b.onclick = () => {
    const k = b.dataset.dec;
    if (--CART[k] <= 0) delete CART[k];
    saveCart(); drawCart(); });

  const sub = cartSubtotal();
  let total = sub;
  const rows = [];
  if (sub) rows.push(`<div class="row"><span>Subtotal</span>
    <span>${money(sub)}</span></div>`);
  if (DISCOUNT) {
    const off = Math.min(DISCOUNT.amount_cents || 0, total);
    total = Math.max(0, total - off);
    rows.push(`<div class="row"><span>${DISCOUNT.code} · ${DISCOUNT.label}</span>
      <span>−${money(off)}</span></div>`);
  }
  if (GIFT) {
    const used = Math.min(GIFT.balance_cents, total);
    total = Math.max(0, total - used);
    rows.push(`<div class="row"><span>Gift card ${GIFT.code}</span>
      <span>−${money(used)}</span></div>`);
  }
  const freeShip = (DISCOUNT && DISCOUNT.free_shipping) || sub >= FREE_SHIP_AT;
  if (sub) rows.push(`<div class="row"><span>Shipping</span>
    <span>${freeShip ? "Free" : "calculated at checkout"}</span></div>`);
  if (sub) rows.push(`<div class="row grand"><span>Total</span>
    <span>${money(total)}</span></div>`);
  $("#cart-total").innerHTML = rows.join("");
  const co = $("#checkout-btn");
  co.disabled = !sub;
  // the button carries the total — Recess-style, no hunting for the number
  co.innerHTML = sub
    ? `Checkout · ${money(total)} ${ico("arrow", "ico ico-sm")}`
    : `Checkout ${ico("arrow", "ico ico-sm")}`;
  const n = Object.values(CART).reduce((a, b) => a + b, 0);
  const hc = $("#cart-head-count");
  if (hc) hc.textContent = n ? `(${n} ${n === 1 ? "can" : "items"})` : "";

  // Free-shipping meter: the single highest-leverage thing in a cart drawer.
  const meter = $("#ship-meter");
  if (meter) {
    meter.hidden = !sub;
    if (sub) {
      const pct = Math.min(100, (sub / FREE_SHIP_AT) * 100);
      const left = FREE_SHIP_AT - sub;
      $("#ship-meter-msg").innerHTML = freeShip
        ? `${ico("truck", "ico ico-sm")} <b>Free shipping unlocked.</b>`
        : `You're <b>${money(left)}</b> from free shipping.`;
      $("#ship-meter-fill").style.width = pct + "%";
    }
  }
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
    $("#discount-msg").textContent = `${out.label} applied`; }
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
    $("#gift-msg").textContent = `${money(GIFT.balance_cents)} available`; }
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
        : `<span class="upsell-emoji">${canSVG(u, { k: "up", mini: true })}</span>`}
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
      <b>${ico("repeat", "ico ico-sm")} Make it a monthly box</b>
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
    openModal(`<h3>Order placed</h3>
      <p>Order <b>#${out.id || out.order_id || ""}</b> is in. Track it any
      time with the parcel button in the header.</p>
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
    "Welcome to the club — check your inbox." : "hmm, try a real email?";
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
  $("#scrim").classList.add("show");
  document.body.classList.add("drawer-open"); }
function closeMenus() {
  $("#cart-drawer").classList.remove("open");
  $("#side-menu").classList.remove("open");
  $("#side-menu").setAttribute("aria-hidden", "true");
  const panel = $("#a11y-panel");
  if (panel) panel.classList.remove("open");
  $("#scrim").classList.remove("show");
  document.body.classList.remove("drawer-open");
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

/* Every way to work with us, mirrored from PATHS in partners.py. Kept here
   rather than server-rendered so the menu is identical on every page,
   including the ones the section engine doesn't render. */
const PARTNER_LINKS = [
  ["stock-zen", "box", "Stock Zenjoy", "Get the range into your store"],
  ["reorder", "repeat", "Reorder for my store", "Already carrying us"],
  ["distribute", "truck", "Distribute Zenjoy", "Run routes in your region"],
  ["brand", "sparkle", "We'll distribute your brand", "Get onto our trucks"],
  ["partner-brand", "shield", "Stock a partner brand",
    "Other brands we carry, same invoice"],
];

(function drawPartnerLinks() {
  const host = $("#menu-partners");
  if (!host) return;
  host.innerHTML = PARTNER_LINKS.map(([slug, icn, label, sub]) =>
    `<a class="menu-link" href="/partners/${slug}">${ico(icn)}
      <span>${label}<small>${sub}</small></span></a>`).join("");
})();

function openMenu() {
  $("#side-menu").classList.add("open");
  $("#side-menu").setAttribute("aria-hidden", "false");
  $("#scrim").classList.add("show");
  document.body.classList.add("drawer-open");
}
$("#menu-btn").onclick = openMenu;
// the hamburger in the menu bar collapses it again
$("#menu-cart-btn").onclick = () => { closeMenus(); drawCart(); openCart(); };
$("#menu-account").onclick = (e) => { e.preventDefault(); closeMenus();
  openAccount(); };
$("#menu-track").onclick = (e) => { e.preventDefault(); closeMenus();
  openTracking(); };
$("#menu-support").onclick = (e) => { e.preventDefault(); closeMenus();
  openSupport(); };
$("#menu-prefs").onclick = (e) => { e.preventDefault(); closeMenus();
  openPrefs(); };
$("#menu-close").onclick = closeMenus;
$("#cart-btn").onclick = () => { drawCart(); openCart(); };
$("#cart-close").onclick = closeMenus;
$("#scrim").onclick = closeMenus;
$("#modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal(); });
$("#track-btn").onclick = openTracking;
on("#foot-track", (e) => { e.preventDefault(); openTracking(); });
on("#foot-support", (e) => { e.preventDefault(); openSupport(); });
// ---------- customer account: orders + subscription self-service ----------
function acctToken() {
  try { return JSON.parse(localStorage.getItem("sf_support") || "{}").token; }
  catch { return null; }
}

/* One sign-in for the whole storefront.
   Account and support used to raise two different modals against the same
   endpoint and the same stored token, which read as two accounts. This is the
   single door; callers say what they want to do once they're through. */
function signIn(intro, onDone) {
  if (acctToken()) { onDone(); return; }
  openModal(`<h3>Sign in</h3>
    <p class="dim">${intro}</p>
    <label>Name</label><input id="si-name" placeholder="Your name"
      autocomplete="name">
    <label>Email <span class="dim">(the one you ordered with)</span></label>
    <input id="si-email" type="email" autocomplete="email">
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Later</button>
      <button class="btn-pill primary sm" id="si-go">Sign in</button>
    </div>`);
  const go = async () => {
    const name = $("#si-name").value.trim();
    if (!name) { $("#si-name").focus(); return; }
    const out = await (await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, role: "customer",
        email: $("#si-email").value.trim() }) })).json();
    if (!out.token) { toast("Couldn't sign you in — try again"); return; }
    localStorage.setItem("sf_support",
      JSON.stringify({ token: out.token, me: out.id }));
    SUPPORT.token = out.token; SUPPORT.me = out.id;
    onDone();
  };
  $("#si-go").onclick = go;
  $("#si-name").onkeydown = (e) => { if (e.key === "Enter") go(); };
  $("#si-email").onkeydown = (e) => { if (e.key === "Enter") go(); };
  setTimeout(() => $("#si-name").focus(), 30);
}

function openAccount() {
  signIn("Orders, monthly boxes and rewards — all in one place.", drawAccount);
}

async function drawAccount() {
  const H = { Authorization: "Bearer " + acctToken() };
  const [orders, subs] = await Promise.all([
    (await fetch("/api/store/account/orders", { headers: H })).json(),
    (await fetch("/api/store/account/subscriptions", { headers: H })).json()]);
  const aff = await (await fetch("/api/store/affiliate/stats",
    { headers: H })).json().catch(() => ({ joined: false }));
  const affBlock = aff.joined ? `
    <h3 style="font-size:15px;margin-top:14px">Affiliate</h3>
    <div class="ship-opt"><b>${location.origin}/r/${aff.code}</b></div>
    <div class="ship-opt">
      <span class="dim">${aff.clicks} clicks · ${aff.landing_views} landing
      views · ${aff.orders} orders</span>
      <b>${money(aff.earned_cents)} earned</b>
      <a class="btn-pill ghost sm" href="${aff.landing}">view page</a>
    </div>` : `
    <h3 style="font-size:15px;margin-top:14px">Affiliate</h3>
    <div class="ship-opt"><span class="dim">Share what you love and earn on
      every order.</span>
      <a class="btn-pill ghost sm" href="/affiliates">Join the program</a>
    </div>`;
  const cutoffNote = subs.changes_open ? "" :
    `<p class="dim">⏳ Box changes are closed for this cycle (curation is
     locked) — skip reopens after shipping.</p>`;
  openModal(`<h3>My account</h3>
    <h3 style="font-size:15px;margin-top:6px">Monthly boxes</h3>
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
      '<p class="dim">No boxes yet — choose a monthly box at checkout.</p>'}
    <h3 style="font-size:15px;margin-top:14px">Orders</h3>
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
  signIn("Real humans on the other end — the same system the team runs on.",
    startSupportChat);
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
  openModal(`<h3>Support</h3>
    <div id="sp-msgs" style="max-height:300px;overflow-y:auto;
      background:#f7f4fb;border-radius:12px;padding:12px;margin:8px 0;
      display:flex;flex-direction:column;gap:6px"></div>
    <div class="row"><input id="sp-input" placeholder="Type a message…">
      <button class="btn-pill primary sm" id="sp-send"
        style="flex:0 0 auto">Send</button></div>
    <p class="dim" style="margin-top:6px">Messages land in the team's inbox
    (support chat in the ops app) — replies appear here live.</p>`);
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
    body: "Hey — how can we help?" }]);
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
    if (r.ok) openModal(`<h3>Payment confirmed</h3>
      <p>Order <b>#${+oid}</b> is paid and in the queue — receipt's in your
      inbox, and your account has the details.</p>
      <div class="modal-actions">
        <button class="btn-pill primary sm" data-close-modal>Done</button>
      </div>`);
    else toast("Payment is still settling — check your account in a minute");
  } catch {}
}
if (qs.get("cancelled")) toast("Checkout cancelled — your cart is still here");

/* ---------- accessibility preferences ----------
   Applied as classes on <html> so every surface — storefront, product page,
   cart drawer — inherits them, and persisted per device. Deliberately small:
   the four controls people actually use, not a widget that repaints the site.
   The OS-level prefers-reduced-motion is still honoured on its own in CSS. */
const A11Y_KEY = "sf_a11y";
let A11Y = { text: "", contrast: false, motion: false, links: false };
try { A11Y = { ...A11Y, ...JSON.parse(localStorage.getItem(A11Y_KEY) || "{}") }; }
catch {}

function applyA11y() {
  const r = document.documentElement;
  r.classList.remove("a11y-text-lg", "a11y-text-xl");
  if (A11Y.text) r.classList.add("a11y-text-" + A11Y.text);
  r.classList.toggle("a11y-contrast", !!A11Y.contrast);
  r.classList.toggle("a11y-motion", !!A11Y.motion);
  r.classList.toggle("a11y-links", !!A11Y.links);
  localStorage.setItem(A11Y_KEY, JSON.stringify(A11Y));
  const seg = $("#a11y-text");
  if (seg) {
    seg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("on", (b.dataset.size || "") === A11Y.text));
  }
  for (const k of ["contrast", "motion", "links"]) {
    const btn = $("#a11y-" + k);
    if (!btn) continue;
    btn.classList.toggle("on", !!A11Y[k]);
    btn.setAttribute("aria-checked", A11Y[k] ? "true" : "false");
  }
}

let openPrefs = () => {};

(function wireA11y() {
  const panel = $("#a11y-panel");
  if (!panel) return;
  const setOpen = (open) => {
    panel.classList.toggle("open", open);
    $("#scrim").classList.toggle("show", open);
    if (open) panel.querySelector("button").focus();
  };
  openPrefs = () => setOpen(true);
  on("#a11y-fab", (e) => { e.stopPropagation(); setOpen(true); });
  const closer = $("#prefs-close");
  if (closer) closer.onclick = () => setOpen(false);
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("open")) setOpen(false);
  });
  $("#a11y-text").querySelectorAll("button").forEach((b) =>
    b.onclick = () => { A11Y.text = b.dataset.size || ""; applyA11y(); });
  for (const k of ["contrast", "motion", "links"]) {
    $("#a11y-" + k).onclick = () => { A11Y[k] = !A11Y[k]; applyA11y(); };
  }
  $("#a11y-reset").onclick = () => {
    A11Y = { text: "", contrast: false, motion: false, links: false };
    applyA11y();
    // region & language reset too — the button says "all"
    localStorage.removeItem("sf_region");
    localStorage.removeItem("sf_cur");
    CUR = I18N.currencies[0] || { code: "USD", symbol: "$", rate: 1 };
    buildPickers(); drawGrid(); drawCart();
    if (LOCALE !== "en") {
      localStorage.setItem("sf_locale", "en"); location.reload();
    }
  };
  applyA11y();
})();

/* ---------- partner enquiry forms ---------- */
(function wireEnquiry() {
  const form = $("#enq-form");
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = $("#enq-msg");
    const body = { kind: form.dataset.kind };
    for (const el of form.elements) if (el.name) body[el.name] = el.value.trim();
    if (!body.name) { msg.className = "enq-msg bad";
      msg.textContent = "We need a name to reply to."; return; }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const r = await fetch("/api/store/enquiry", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.json()).detail || "failed");
      form.reset();
      msg.className = "enq-msg ok";
      msg.textContent = "Got it — we'll come back to you within two working days.";
      // Not funnel(): FUNNEL_STEPS is the ordered purchase funnel, and a B2B
      // enquiry is a parallel path, not a step toward checkout. The lead is
      // already recorded in store_enquiries, the ERP pipeline and a webhook.
      pageview("enquiry:" + body.kind);
    } catch (err) {
      msg.className = "enq-msg bad";
      msg.textContent = "That didn't send. Try again, or use the chat.";
    } finally { btn.disabled = false; }
  };
})();

/* ---------- events ---------- */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

(async function drawEvents() {
  const host = $("#event-list");
  if (!host) return;
  const evs = await (await fetch("/api/store/events")).json();
  const regions = [...new Set(evs.map((e) => e.region).filter(Boolean))];
  let active = null;
  const filters = $("#event-filters");
  const paint = () => {
    const shown = active ? evs.filter((e) => e.region === active) : evs;
    host.innerHTML = shown.map((e) => {
      const d = new Date(e.starts * 1000);
      return `<article class="event-card">
        <div class="event-date"><b>${d.getDate()}</b>
          <span>${MONTHS[d.getMonth()]}</span></div>
        <div>
          <span class="event-kind">${e.kind}</span>
          <h3>${e.name}</h3>
          <p class="where">${ico("pin", "ico ico-sm")}
            ${[e.venue, e.city].filter(Boolean).join(" · ")}</p>
          <p>${e.body || ""}</p>
          ${e.url ? `<p style="margin-top:10px"><a class="text-link"
            href="${e.url}">More details</a></p>` : ""}
        </div></article>`;
    }).join("") || `<p class="dim">Nothing on the calendar in that region yet.
      <a class="text-link" href="/partners/work">Ask us to come to you.</a></p>`;
  };
  filters.innerHTML = [["All", null], ...regions.map((r) => [r, r])]
    .map(([label, val]) =>
      `<button class="tab ${val === active ? "on" : ""}"
        data-region="${val ?? ""}">${label}</button>`).join("");
  filters.querySelectorAll(".tab").forEach((b) => b.onclick = () => {
    active = b.dataset.region || null;
    filters.querySelectorAll(".tab").forEach((x) =>
      x.classList.toggle("on", x === b));
    paint();
  });
  paint();
})();

/* ---------- store locator ---------- */
(async function drawLocator() {
  const host = $("#loc-list");
  if (!host) return;
  const stores = await (await fetch("/api/store/locations")).json();
  const regions = [...new Set(stores.map((s) => s.region).filter(Boolean))];
  let active = null, query = "", here = null;

  // straight-line distance is honest for "which of these is nearest" and
  // needs no map tiles or third-party call
  const milesBetween = (a, b, c, d) => {
    const R = 3958.8, rad = (x) => x * Math.PI / 180;
    const dLat = rad(c - a), dLng = rad(d - b);
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  };

  const paint = () => {
    let shown = stores.slice();
    if (active) shown = shown.filter((s) => s.region === active);
    if (query) {
      const q = query.toLowerCase();
      shown = shown.filter((s) => (s.name + " " + s.city).toLowerCase()
        .includes(q));
    }
    if (here) {
      shown.forEach((s) => s._d = (s.lat && s.lng)
        ? milesBetween(here.lat, here.lng, s.lat, s.lng) : Infinity);
      shown.sort((a, b) => a._d - b._d);
    }
    $("#loc-empty").hidden = shown.length > 0;
    host.innerHTML = shown.map((s) => `<div class="loc-card">
      <b>${s.name}</b>
      <div class="where">${ico("pin", "ico ico-sm")}
        ${[s.city, s.region].filter(Boolean).join(" · ")}</div>
      ${here && isFinite(s._d)
        ? `<span class="dist">${s._d.toFixed(1)} miles away</span>` : ""}
    </div>`).join("");
  };

  $("#loc-filters").innerHTML = [["All", null], ...regions.map((r) => [r, r])]
    .map(([label, val]) => `<button class="tab ${val === active ? "on" : ""}"
      data-region="${val ?? ""}">${label}</button>`).join("");
  $("#loc-filters").querySelectorAll(".tab").forEach((b) => b.onclick = () => {
    active = b.dataset.region || null;
    $("#loc-filters").querySelectorAll(".tab").forEach((x) =>
      x.classList.toggle("on", x === b));
    paint();
  });
  let t;
  $("#loc-search").oninput = (e) => {
    clearTimeout(t);
    t = setTimeout(() => { query = e.target.value.trim(); paint(); }, 180);
  };
  $("#loc-near").onclick = () => {
    if (!navigator.geolocation) { toast("This browser won't share location"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      active = null;
      $("#loc-filters").querySelectorAll(".tab").forEach((x, i) =>
        x.classList.toggle("on", i === 0));
      paint();
      toast("Sorted by distance from you");
    }, () => toast("Couldn't get your location"));
  };
  paint();
})();

// ---------- boot ----------
buildPickers();
saveCart();
loadCatalog().then(() => {
  loadPromos();
  confirmPaidReturn();
  if (qs.get("cart")) { drawCart(); openCart(); }  // back from product page
});
