/* Storefront — talks to the brain only through /api/store/* and the
   shared funnel/order rails. */
"use strict";

const $ = (s) => document.querySelector(s);
/* Bind a click only if the element is on this page. The shell now serves
   several page shapes (home, partner pages, events, locator), and a missing
   optional control used to throw at module scope and take the rest of the
   script — including the menu — down with it. */
const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; return el; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- currency + locale ----------
/* The brand, read from the shell the server already branded — the nav
   carries the theme's wordmark text, so there is no second source. */
function BRAND() {
  const el = document.querySelector(".topbar .brand, .brand");
  const t = (el ? el.textContent : "").replace(/\.$/, "").trim();
  return t || "our brand";
}
const BRAND_T = () => BRAND().replace(/\b\w/g, (c) => c.toUpperCase());

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

/* The admin's heatmap renders this page in an iframe. Without a guard that
   preview would record its own pageviews, funnel steps and pixel events, so
   looking at the data would change it. Every telemetry path checks this. */
const PREVIEW = qs.get("__preview") === "1";

function funnel(step, extra = {}) {
  if (PREVIEW) return;
  fetch("/api/events", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: VID, step, ...extra }) })
    .catch(() => {});
}
function pageview(page) {
  if (PREVIEW) return;
  fetch("/api/store/track", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: VID, page }) }).catch(() => {});
}
funnel("visit");
// the shell now serves partner pages, events and the locator too, so record
// the path rather than always claiming "home"
pageview(location.pathname === "/" ? "home" : location.pathname.slice(0, 60));
// PIXEL is defined further down; fire the page view once it exists.
addEventListener("DOMContentLoaded", () => {
  if (typeof PIXEL !== "undefined") PIXEL.track("page_view");
});

// ---------- shader hero (fragment-shader gradient flow) ----------
/* Only drawn when the "shader" hero style is chosen in the page builder.

   It repaints a full-screen fragment shader, so it is gated three ways:
   it stops when the hero scrolls out of view, stops when the tab is hidden,
   and never starts at all if the visitor asked for reduced motion. An
   animation that keeps running behind a background tab is how a marketing
   site ends up holding a laptop fan open all afternoon — the loop used to
   be unconditional, which was fine only because nothing on the live site
   selected this hero. */
(function shaderHero() {
  const canvas = $("#shader-bg");
  if (!canvas) return;            // hero may use a gradient/image background
  const still = "linear-gradient(135deg,#6c00bf,#8a77e1)";
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
    canvas.style.background = still;
    return;
  }
  const gl = canvas.getContext("webgl");
  if (!gl) { canvas.style.background = still; return; }
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

  let raf = 0, onScreen = true;
  const running = () => onScreen && !document.hidden;
  function frame(ms) {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h);
    }
    gl.uniform1f(uT, ms / 1000);
    gl.uniform2f(uR, w, h);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = running() ? requestAnimationFrame(frame) : 0;
  }
  const start = () => { if (!raf && running()) raf = requestAnimationFrame(frame); };
  const stop = () => { if (raf) { cancelAnimationFrame(raf); raf = 0; } };
  new IntersectionObserver(([e]) => {
    onScreen = e.isIntersecting;
    onScreen ? start() : stop();
  }).observe(canvas);
  document.addEventListener("visibilitychange", () =>
    document.hidden ? stop() : start());
  start();
})();

// ---------- catalog ----------
let CATALOG = { products: [], collections: [] };
let activeCollection = null;

const ico = (name, cls = "ico") =>
  `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

// Flavour colour drives the card, the PDP and the cart line. Falls back to
// brand purple for anything without merchandising meta.
/* A product with no colour of its own draws in the tenant's accent — the
   theme injects --purple into :root before this file runs, so the
   drinks-era fallback only fires when there is no theme at all. */
const THEME_ACCENT = (getComputedStyle(document.documentElement)
  .getPropertyValue("--purple") || "").trim();
const flavourOf = (p) => p.colour || THEME_ACCENT || "#6c00bf";

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
     letter-spacing="-.5" aria-hidden="true">${BRAND()}<tspan fill="#ffd9b8">.</tspan></text>`}
   ${label && !opts.mini ? `<text x="100" y="266" text-anchor="middle" fill="#fff"
     font-size="13" font-family="Inter, sans-serif" font-weight="600"
     opacity=".95" aria-hidden="true">${label}</text>` : ""}
  </svg>`;
}

/* The neutral stand-in — a panel with the ring mark, for a tenant selling
   something that does not come in a can. Twin of card_svg() in api.py. */
// A wordmark is as long as the business's name — fit it to the panel.
const MARK_SIZE = (name) =>
  Math.min(14, Math.max(8, Math.floor(150 / Math.max(name.length, 1) * 1.35)));

function cardSVG(p, opts = {}) {
  const c = flavourOf(p);
  const id = "pk" + p.id + (opts.k || "");
  return `<svg class="can card-art" viewBox="0 0 200 320" role="img"
    aria-label="${(pname(p) || "").replace(/"/g, "&quot;")}">
   <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
     <stop offset="0" stop-color="${c}" stop-opacity=".95"/>
     <stop offset="1" stop-color="${c}" stop-opacity=".70"/></linearGradient></defs>
   <ellipse cx="100" cy="296" rx="62" ry="6" fill="rgba(27,24,31,.10)"/>
   <rect x="22" y="40" width="156" height="240" rx="18" fill="url(#${id})"/>
   <g fill="none" stroke="#fff" opacity=".85">
     <circle cx="100" cy="152" r="12" stroke-width="7"/>
     <circle cx="100" cy="152" r="30" stroke-width="5" opacity=".72"/>
     <circle cx="100" cy="152" r="50" stroke-width="3.4" opacity=".46"/>
   </g>
   <rect x="22" y="40" width="156" height="240" rx="18" fill="none"
     stroke="rgba(27,24,31,.10)"/>
   ${opts.mini ? "" : `<text x="100" y="78" text-anchor="middle" fill="#fff"
     font-size="${MARK_SIZE(BRAND())}" font-weight="700" letter-spacing=".8"
     opacity=".85" aria-hidden="true">${BRAND().toUpperCase()}</text>`}
  </svg>`;
}

/* Which stand-in this shop draws, from the theme the server sent. */
const ART = () => ((window.STORE_I18N || {}).art === "can" ? canSVG : cardSVG);

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
  // Only the colour: the tint derives from it in CSS, so the two can
  // never drift apart.
  const style = ` style="--flavour:${flavourOf(p)}"`;
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
  return `<div class="${cls}"${style}>${ART()(p, { k: cls, mini })}</div>`;
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

/* The multipack is merchandised differently everywhere it appears: it is the
   basket-builder, and a 4-can landscape shot squeezed into a single-can slot
   reads as a mistake. Recognised by category so a rename cannot lose it. */
const isCase = (p) => (p.category || "") === "multipacks";


const CARD_MIN = 230;           // narrowest a product card reads well at

function layoutGrid(host, n) {
  if (!n) return;
  const w = host.clientWidth || host.getBoundingClientRect().width;
  const fits = Math.max(1, Math.min(4, Math.floor((w + 22) / (CARD_MIN + 22))));
  let cols = fits;
  for (let c = fits; c >= 2; c--) {
    if (n <= c || n % c !== 1) { cols = c; break; }
  }
  host.style.setProperty("--cols", String(cols));
}

/* Widths change without the catalog changing, so the count is recomputed on
   resize rather than only when the grid is drawn. */
addEventListener("resize", () => {
  const host = $("#product-grid");
  if (host) layoutGrid(host, host.querySelectorAll(".product:not(.feature)").length);
});

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

  // The case leads, on a row of its own, and is not repeated below.
  const feature = prods.find(isCase);
  prods = prods.filter((p) => !isCase(p));
  const featureHtml = !feature ? "" : `
    <div class="product feature" style="--flavour:${flavourOf(feature)}">
      <a class="feature-art" href="/product/${feature.id}-${feature.slug}"
         aria-label="${pname(feature)}">${art(feature)}</a>
      <div class="body">
        ${feature.badge ? `<span class="feature-kicker">${feature.badge}</span>` : ""}
        <a href="/product/${feature.id}-${feature.slug}">
          <b>${pname(feature)}</b></a>
        <span class="note">${feature.note || pdesc(feature)}</span>
        <div class="price-row">
          <span class="price">${priceOf(feature)}</span>
          ${isPlan(feature)
            ? `<button class="add-btn" data-plan="${feature.id}">
                 ${t("start_plan", "Start")}</button>`
            : `<button class="add-btn" data-add="${feature.id}">
                 ${t("add_to_cart", "Add")}</button>`}
        </div>
      </div>
    </div>`;

  /* Column count is a decision, not a side effect of width. Picking by
     width alone (auto-fill, or a media query) is what left four flavours
     as a row of three and one lone can. So: work out how many *fit*, then
     take the largest count at or below that which does not strand a single
     card — `n % c === 1` is the case being avoided. */
  layoutGrid(gridHost, prods.length);

  gridHost.innerHTML = featureHtml + prods.map((p) => `
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
          <span class="price" data-price-for="${p.id}">${priceOf(p)}</span>
          ${isPlan(p)
            ? `<button class="add-btn" data-plan="${p.id}">
                 ${t("start_plan", "Start")}</button>`
            : `<button class="add-btn" data-add="${p.id}">
                 ${t("add_to_cart", "Add")}</button>`}
        </div>
      </div>
    </div>`).join("") || (featureHtml ? "" :
    `<p class="dim">${SEARCH != null ? "Nothing matched — try another word."
      : "No products yet — add some in the store admin."}</p>`);
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
  document.querySelectorAll("[data-plan]").forEach((b) =>
    b.onclick = () => startPlan(+b.dataset.plan));
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
  let html = `<div class="menu-headline">${t("shop_cta")}</div>` +
    '<div class="side-group">Browse</div><div class="menu-cols">' +
    `<a class="side-item" href="/#shop" data-close>${ico("bag", "ico ico-sm")}
      All products</a>`;
  for (const c of CATALOG.collections) {
    html += `<a class="side-item" href="/#shop" data-close
      data-colnav="${c.id}">${c.name}</a>`;
  }
  html += "</div>";                     // closes .menu-cols
  const kase = CATALOG.products.find(isCase);
  if (kase) {
    html += '<div class="side-group">The case</div>' +
      `<a class="menu-tile wide" href="/product/${kase.id}-${kase.slug}"
        style="--flavour:${flavourOf(kase)}">
        ${art(kase, "art", false)}
        <div class="mt-copy"><b>${pname(kase)}</b>
        <span>${money(kase.price_cents)} · all four flavors</span></div></a>`;
  }
  html += '<div class="side-group">Every flavor</div>' +
    '<div class="menu-tiles">';
  for (const p of CATALOG.products.filter((x) => !isCase(x))) {
    html += `<a class="menu-tile" href="/product/${p.id}-${p.slug}"
      style="--flavour:${flavourOf(p)}">
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

/* The hero sells the product, so the product has to be in it. Takes the one
   the merchant flagged; failing that the first single flavour, and failing
   that whatever sorts first. Shows its photo if one exists, else the drawn
   stand-in. */
function hydrateHero() {
  const stage = $("#hero-stage");
  if (!stage) return;
  const p = CATALOG.products.find((x) => x.featured)
    || CATALOG.products.find((x) => x.flavour && x.flavour !== "pack")
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
      : ART()(p, { k: "hero" })}</a>`;
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
  wireReviewButtons();
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
  PIXEL.track("add_to_cart", { value_cents: (cartLine(key) || {}).unit || 0 });
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
      style="margin-top:14px">${t("shop_cta")}</button></div>`;
  drawCodes();
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

let GIFT = null;

/* One field, two kinds of code.

   The discount preview is tried first because it is the endpoint that can
   explain itself — "expired", "minimum spend", "already used" — and that
   reason is worth more than a generic rejection. Only when it declines does
   this fall back to a gift-card lookup, so a gift card typed into the one
   box still works instead of being called invalid.

   Both can be live at once; they are separate slots, and the chips below
   show what is actually applied so a single input never leaves you guessing. */
async function applyCode() {
  const el = $("#code-input"), msg = $("#code-msg");
  const code = el.value.trim();
  if (!code) return;
  msg.textContent = "Checking…";

  const r = await fetch("/api/store/discount/preview", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, subtotal_cents: cartSubtotal() }) });
  const out = await r.json().catch(() => ({}));
  if (r.ok) {
    DISCOUNT = out;
    msg.textContent = `${out.label} applied`;
    el.value = ""; drawCart(); return;
  }

  const g = await fetch(`/api/store/gift-card/${encodeURIComponent(code)}`);
  if (g.ok) {
    GIFT = await g.json();
    msg.textContent = `Gift card applied · ${money(GIFT.balance_cents)} available`;
    el.value = ""; drawCart(); return;
  }

  // The discount endpoint's reason beats "not found" whenever it gave one.
  msg.textContent = out.detail
    || "We don't recognise that as a discount or gift card code.";
  drawCart();
}

$("#code-apply").onclick = applyCode;
$("#code-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); applyCode(); }
});

/* What is applied, and how to take it off again. */
function drawCodes() {
  const host = $("#code-chips");
  if (!host) return;
  const chips = [];
  if (DISCOUNT) chips.push(`<span class="code-chip">${DISCOUNT.code}
    <button data-drop="discount" aria-label="Remove discount ${DISCOUNT.code}">
      ${ico("close", "ico ico-sm")}</button></span>`);
  if (GIFT) chips.push(`<span class="code-chip">Gift ${GIFT.code}
    <button data-drop="gift" aria-label="Remove gift card ${GIFT.code}">
      ${ico("close", "ico ico-sm")}</button></span>`);
  host.innerHTML = chips.join("");
  host.querySelectorAll("[data-drop]").forEach((b) => b.onclick = () => {
    if (b.dataset.drop === "discount") DISCOUNT = null; else GIFT = null;
    $("#code-msg").textContent = "";
    drawCart();
  });
}

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
    ${show.map((r) => `<div class="upsell-row"
        style="--flavour:${flavourOf(r)}">
      ${r.media && r.media[0]
        ? `<img src="${r.media[0].thumb}" alt="">`
        : `<span class="upsell-emoji">${ART()(r, { k: "up", mini: true })}</span>`}
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
  PIXEL.track("checkout", { value_cents: cartSubtotal() });
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
    PIXEL.track("purchase", { value_cents: out.total_cents || 0 });
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
  if (r.ok) { $("#subscribe-email").value = ""; PIXEL.track("subscribe"); }
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
function openCart() {
  /* Draw on open, not only when a line changes. The cart is restored from
     localStorage on load, so opening it after a reload used to show whatever
     markup was last rendered — for a returning visitor, an empty drawer over
     a non-empty cart. */
  drawCart();
  $("#cart-drawer").classList.add("open");
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
  ["stock-zen", "box", "Stock the range", "Get the range into your store"],
  ["reorder", "repeat", "Reorder for my store", "Already carrying us"],
  ["distribute", "truck", "Distribute the brand", "Run routes in your region"],
  ["brand", "sparkle", "We'll distribute your brand", "Get onto our trucks"],
  ["partner-brand", "shield", "Stock a partner brand",
    "Other brands we carry, same invoice"],
];

(function drawPartnerLinks() {
  const host = $("#menu-partners");
  if (!host) return;
  // The stock/reorder/distribute story is the distribution capability's;
  // a school without it should not offer trucks in its menu.
  host.innerHTML = PARTNER_LINKS.map(([slug, icn, label, sub]) =>
    `<a class="menu-link" href="/partners/${slug}" data-cap="distribution">${ico(icn)}
      <span>${label}<small>${sub}</small></span></a>`).join("")
    // The affiliate programme is a way to work with us too, and it was
    // only reachable from a footer link.
    + `<a class="menu-link" href="/affiliates" data-cap="affiliates">${ico("link")}
      <span>Affiliates<small>Share your link, earn on every order</small></span></a>`;
})();

/* The menu follows the grant, same as the header nav: the shell stamps the
   tenant's capability list onto <body data-caps>, and any menu entry tagged
   data-cap disappears when its capability is off. An empty attribute (no
   grant recorded) means everything — the same null rule as the server. A
   fold whose links all vanish takes its heading with it. */
(function pruneMenuByCaps() {
  let caps = null;
  try { caps = JSON.parse(document.body.dataset.caps || "null"); }
  catch { caps = null; }
  if (!Array.isArray(caps)) return;
  document.querySelectorAll("[data-cap]").forEach((el) => {
    if (!caps.includes(el.dataset.cap)) el.remove();
  });
  document.querySelectorAll(".menu-fold").forEach((fold) => {
    const links = fold.querySelector(".menu-links");
    if (links && !links.querySelector(".menu-link")) fold.remove();
  });
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
  /* Three honest doors, not one ambiguous one: signing in refuses to mint
     an account from a typo, creating refuses to silently join somebody
     else's, and applying to a programme creates nothing at all — an
     administrator's approval is what opens a seat. */
  let door = "signin";
  const finish = (out) => {
    localStorage.setItem("sf_support",
      JSON.stringify({ token: out.token, me: out.id }));
    SUPPORT.token = out.token; SUPPORT.me = out.id;
    // The learner and nutrition portals render who-you-are pages; a
    // sign-in on one of them means the whole page changes, not just the
    // modal — reload so "Apply to join" becomes "Your courses" at once.
    if (document.getElementById("learn-root")
        || document.getElementById("nutrition-root")) {
      closeModal(); location.reload(); return;
    }
    onDone();
  };
  const login = async (payload) => {
    const res = await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
    const out = await res.json().catch(() => ({}));
    if (!res.ok || !out.token) {
      const msg = $("#si-msg");
      if (msg) msg.textContent = out.detail
        || "Couldn't sign you in — try again";
      return null;
    }
    return out;
  };
  const doorTabs = () => `<div class="door-tabs">
    ${[["signin", "Sign in"], ["create", "Create account"],
       ["apply", "Apply to a programme"]].map(([id, label]) =>
      `<button class="btn-pill sm ${door === id ? "primary" : "ghost"}"
        data-door="${id}">${label}</button>`).join("")}</div>`;
  const draw = async () => {
    if (door === "signin") {
      openModal(`<h3>Sign in</h3>
        <p class="dim">${intro}</p>
        ${doorTabs()}
        <label>Name</label><input id="si-name" placeholder="Your name"
          autocomplete="name">
        <label>Email <span class="dim">(optional)</span></label>
        <input id="si-email" type="email" autocomplete="email">
        <label>Password <span class="dim">(only if you set one)</span></label>
        <input id="si-pass" type="password" autocomplete="current-password">
        <div class="modal-actions">
          <button class="btn-pill ghost sm" data-close-modal>Later</button>
          <button class="btn-pill ghost sm" id="si-scan">Scan a QR</button>
          <button class="btn-pill primary sm" id="si-go">Sign in</button>
        </div>
        <p class="dim" id="si-msg"></p>
        <p class="dim" style="margin-top:14px;padding-top:12px;
          border-top:1px solid var(--line)">On the team — teaching,
          coaching, running the place?
          <a class="text-link" href="/ops/">Team sign-in →</a> ·
          <a class="text-link" href="/admin">Store admin →</a></p>`);
      on("#si-scan", async () => {
        const msg = $("#si-msg");
        if (msg) msg.textContent = "";
        const r = await QRScan.signIn("Scan your sign-in QR");
        if (!r.ok && r.error && msg) msg.textContent = r.error;
      });
      const go = async () => {
        const name = $("#si-name").value.trim();
        if (!name) { $("#si-name").focus(); return; }
        const out = await login({ name, role: "customer", mode: "signin",
          email: $("#si-email").value.trim(),
          password: $("#si-pass").value });
        if (out) finish(out);
      };
      $("#si-go").onclick = go;
      ["#si-name", "#si-email", "#si-pass"].forEach((s) => {
        $(s).onkeydown = (e) => { if (e.key === "Enter") go(); }; });
      setTimeout(() => $("#si-name").focus(), 30);
    } else if (door === "create") {
      openModal(`<h3>Create an account</h3>
        <p class="dim">For people who already have a place here. Applying
          to a programme is the tab on the right.</p>
        ${doorTabs()}
        <label>Your name</label><input id="cr-name" autocomplete="name">
        <label>Email</label>
        <input id="cr-email" type="email" autocomplete="email">
        <label>Password</label>
        <input id="cr-pass" type="password" autocomplete="new-password">
        <label>Repeat password</label>
        <input id="cr-pass2" type="password" autocomplete="new-password">
        <label>I am a…</label>
        <select id="cr-role">
          <option value="customer">Student — I want to take classes</option>
          <option value="employee">Team — I teach, coach or help out</option>
        </select>
        <p class="dim">Anything other than Student is confirmed by the
          office before it opens anything. A short phrase you will remember
          beats a short password with symbols in it.</p>
        <div class="modal-actions">
          <button class="btn-pill ghost sm" data-close-modal>Later</button>
          <button class="btn-pill primary sm" id="cr-go">Create account</button>
        </div>
        <p class="dim" id="si-msg"></p>`);
      $("#cr-go").onclick = async () => {
        const name = $("#cr-name").value.trim();
        const msg = $("#si-msg");
        if (!name) { $("#cr-name").focus(); return; }
        if ($("#cr-pass").value !== $("#cr-pass2").value) {
          if (msg) msg.textContent = "the passwords do not match";
          return;
        }
        const out = await login({ name, mode: "create",
          role: $("#cr-role").value,
          email: $("#cr-email").value.trim(),
          password: $("#cr-pass").value });
        if (out) finish(out);
      };
      setTimeout(() => $("#cr-name").focus(), 30);
    } else {
      let programs = null;
      try {
        const r = await fetch("/api/learn/programs");
        if (r.ok) programs = await r.json();
      } catch (e) { /* no Learning capability: the form still sends */ }
      openModal(`<h3>Apply to a programme</h3>
        <p class="dim">Tell us what you would like to learn. This does not
          create an account — an administrator reviews every application,
          and approval is what opens your seat.</p>
        ${doorTabs()}
        <label>Your name</label><input id="ap-name" autocomplete="name">
        <label>Email</label>
        <input id="ap-email" type="email" autocomplete="email">
        <label>Phone <span class="dim">(optional)</span></label>
        <input id="ap-phone" autocomplete="tel">
        ${programs && programs.length ? `<label>Programme</label>
          <select id="ap-course"><option value="">— choose a class —</option>
          ${programs.map((p) => `<option value="${p.id}">${esc(p.name)}${
            p.language ? " — " + esc(p.language) : ""}</option>`).join("")}
          </select>` : ""}
        <label>What do you want to learn?</label>
        <input id="ap-lang" placeholder="Spanish, Japanese, …">
        <label>What do you want to get out of it?
          <span class="dim">(optional)</span></label>
        <textarea id="ap-goals" rows="3"></textarea>
        <div class="modal-actions">
          <button class="btn-pill ghost sm" data-close-modal>Later</button>
          <button class="btn-pill primary sm" id="ap-go">Send application</button>
        </div>
        <p class="dim" id="si-msg"></p>`);
      $("#ap-go").onclick = async () => {
        const msg = $("#si-msg");
        const sel = $("#ap-course");
        const res = await fetch("/api/learn/register", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: $("#ap-name").value.trim(),
            email: $("#ap-email").value.trim(),
            phone: $("#ap-phone").value.trim(),
            language: $("#ap-lang").value.trim(),
            goals: $("#ap-goals").value.trim(),
            course_id: sel && sel.value ? +sel.value : null }) });
        const out = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (msg) msg.textContent = out.detail || "that didn't send";
          return;
        }
        openModal(`<h3>Application received</h3>
          <p>Thank you — we read every application. Once it is approved
            you will have an account and a seat.</p>
          <div class="modal-actions">
            <button class="btn-pill primary sm" data-close-modal>Done</button>
          </div>`);
      };
      setTimeout(() => $("#ap-name").focus(), 30);
    }
    document.querySelectorAll("[data-door]").forEach((b) => b.onclick =
      () => { door = b.dataset.door; draw(); });
  };
  draw();
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
  // the account panel follows the grant too: no affiliates capability,
  // no programme to join (same data-caps the side menu reads)
  let capsOn = null;
  try { capsOn = JSON.parse(document.body.dataset.caps || "null"); }
  catch { capsOn = null; }
  const affOff = Array.isArray(capsOn) && !capsOn.includes("affiliates");
  const affBlock = affOff ? "" : aff.joined ? `
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
  const rows = subs.subscriptions || [];
  const boxes = rows.filter((s) => !s.plan);
  const plans = rows.filter((s) => s.plan);
  // Skip is a box verb. A plan has no shipment to move, so it is not
  // offered one — and the cutoff note only applies where a cycle exists.
  const cutoffNote = (subs.changes_open || !boxes.length) ? "" :
    `<p class="dim">⏳ Box changes are closed for this cycle (curation is
     locked) — skip reopens after shipping.</p>`;
  const subRow = (s, verbs) => `
      <div class="ship-opt"><b>${s.name}${s.qty > 1 ? ` × ${s.qty}` : ""}</b>
       <span class="dim">${money(s.price_cents * s.qty)}/mo · ${s.status}</span>
       ${verbs}
       <button class="btn-pill ghost sm" data-sub="${s.id}:cancel">cancel</button>
      </div>`;
  openModal(`<h3>My account</h3>
    ${plans.length ? `
      <h3 style="font-size:15px;margin-top:6px">${t("plans_heading")}</h3>
      ${plans.map((s) => subRow(s, s.status === "active"
        ? `<button class="btn-pill ghost sm" data-sub="${s.id}:pause">pause</button>`
        : `<button class="btn-pill ghost sm" data-sub="${s.id}:resume">resume</button>`
      )).join("")}` : ""}
    ${boxes.length || !plans.length ? `
      <h3 style="font-size:15px;margin-top:${plans.length ? 14 : 6}px">Monthly
        boxes</h3>
      ${cutoffNote}
      ${boxes.map((s) => subRow(s, s.status === "active"
        ? `<button class="btn-pill ghost sm" data-sub="${s.id}:skip">skip next</button>
           <button class="btn-pill ghost sm" data-sub="${s.id}:pause">pause</button>`
        : s.status === "skipped_next"
        ? `<button class="btn-pill ghost sm" data-sub="${s.id}:unskip">unskip</button>`
        : `<button class="btn-pill ghost sm" data-sub="${s.id}:resume">resume</button>`
      )).join("") ||
        `<p class="dim">${t("no_plans")}</p>`}` : ""}
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
    localStorage.removeItem("sf_support"); closeModal();
    // Same as signing in: on a portal page the content IS the account,
    // so signing out must take the page with it.
    if (document.getElementById("learn-root")
        || document.getElementById("nutrition-root")) location.reload();
  };
}

$("#account-btn").onclick = openAccount;

/* ---------- plans: the products that bill every month ----------
   A plan is not a thing you add to a cart. It shows its price with the
   period attached, its button starts a subscription, and it needs a signed-in
   customer because somebody has to be the one being billed. */
const isPlan = (p) => !!p.billing;
const planPrice = (p) => `${money(p.price_cents)}<small
  class="per">/${p.billing === "month" ? "mo" : p.billing}</small>`;
const priceOf = (p) => isPlan(p) ? planPrice(p)
  : money(p.variants.length ? p.variants[0].price_cents : p.price_cents);

async function startPlan(pid) {
  const p = CATALOG.products.find((x) => x.id === pid);
  signIn(`Starting ${p ? pname(p) : "a plan"} — a plan is billed to
    somebody, so we need to know who.`, async () => {
    const r = await fetch("/api/store/plans/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + acctToken() },
      body: JSON.stringify({ product_id: pid }) });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) { toast(out.detail || "couldn't start that plan"); return; }
    if (out.checkout_url) { location.href = out.checkout_url; return; }
    closeModal();
    toast(out.message || "Your plan is set up.");
  });
}

/* Back from the hosted checkout. The subscription id comes from Stripe when
   the server asks it, never from this query string — which is why the only
   thing carried here is which row to go and check. */
async function confirmPlanReturn() {
  const q = new URLSearchParams(location.search);
  const sid = q.get("subscribed");
  if (!sid || !acctToken()) return;
  const r = await fetch(`/api/store/plans/${+sid}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json",
               Authorization: "Bearer " + acctToken() },
    body: JSON.stringify({ session_id: q.get("sid") || "" }) });
  const out = await r.json().catch(() => ({}));
  toast(out.ok ? "You're on. The plan starts today."
    : (out.detail || "The payment did not complete."));
  history.replaceState({}, "", location.pathname);
}

// ---------- live support chat (rides the ERP Comms module) ----------
let SUPPORT = { token: "", conv: null, ws: null, lastId: 0, me: null };

/* Voice and video to the support desk.
   The ops app already implements the calling half of this over /ws, and the
   support conversation already names a `call_target` (whichever staff member
   is on). So the storefront speaks the same signaling protocol rather than
   growing a second one — a call placed here rings in the ops app exactly as a
   staff-to-staff call does. */
const CALL = { pc: null, stream: null, peer: null, state: "idle",
  media: "audio", pendingIce: [] };

/* One socket for both chat and calls. Chat used to open its own, so calling
   from the hub would have raced a second connection against it. */
function ensureSupportSocket() {
  if (SUPPORT.ws && SUPPORT.ws.readyState <= 1) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      SUPPORT.ws = new WebSocket(
        `${proto}://${location.host}/ws?token=${SUPPORT.token}`);
      SUPPORT.ws.onopen = () => resolve();
      SUPPORT.ws.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === "signal") { onCallSignal(d); return; }
        if (SUPPORT.onMessage) SUPPORT.onMessage(d);
      };
      SUPPORT.ws.onclose = () => { SUPPORT.ws = null; };
      setTimeout(resolve, 1200);        // don't hang if the socket is slow
    } catch { resolve(); }
  });
}

function callSignal(payload) {
  if (SUPPORT.ws && SUPPORT.ws.readyState === 1) {
    SUPPORT.ws.send(JSON.stringify({ type: "signal", to: CALL.peer, payload }));
  }
}

function endCall(notify) {
  if (notify) callSignal({ call: "hangup" });
  if (CALL.pc) { try { CALL.pc.close(); } catch {} }
  if (CALL.stream) CALL.stream.getTracks().forEach((t) => t.stop());
  CALL.pc = null; CALL.stream = null; CALL.peer = null;
  CALL.state = "idle"; CALL.pendingIce = [];
  const o = $("#sf-call");
  if (o) o.remove();
}

function callOverlay(status) {
  let o = $("#sf-call");
  if (!o) {
    o = document.createElement("div");
    o.id = "sf-call";
    o.className = "sf-call";
    o.innerHTML = `
      <video id="sf-call-remote" autoplay playsinline></video>
      <video id="sf-call-local" autoplay playsinline muted></video>
      <div class="sf-call-bar">
        <span id="sf-call-status"></span>
        <button class="btn-pill primary sm" id="sf-call-end">End call</button>
      </div>`;
    document.body.appendChild(o);
    $("#sf-call-end").onclick = () => endCall(true);
  }
  o.classList.toggle("video", CALL.media === "video");
  $("#sf-call-status").textContent = status;
  return o;
}

async function startSupportCall(media) {
  if (CALL.state !== "idle") return toast("already in a call");
  const H = { Authorization: "Bearer " + SUPPORT.token };
  const convs = await (await fetch("/api/chat/convs", { headers: H })).json();
  const conv = convs.convs.find((c) => c.kind === "support");
  if (!conv || !conv.call_target) {
    toast("nobody's free to take a call — try chat or leave a message");
    return openSupport();
  }
  await ensureSupportSocket();
  CALL.peer = conv.call_target; CALL.media = media; CALL.state = "calling";
  closeModal();
  try {
    CALL.stream = await navigator.mediaDevices.getUserMedia(
      { audio: true, video: media === "video" });
  } catch (e) {
    toast("mic/camera unavailable: " + e.message);
    return endCall(false);
  }
  const pc = new RTCPeerConnection(
    { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  CALL.pc = pc;
  CALL.stream.getTracks().forEach((t) => pc.addTrack(t, CALL.stream));
  pc.onicecandidate = (e) => {
    if (e.candidate) callSignal({ call: "ice", ice: e.candidate });
  };
  pc.ontrack = (e) => {
    const v = $("#sf-call-remote");
    if (v && v.srcObject !== e.streams[0]) v.srcObject = e.streams[0];
  };
  pc.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(pc.connectionState)
        && CALL.state !== "idle") { toast("call ended"); endCall(false); }
  };
  callOverlay("calling the team…");
  const lv = $("#sf-call-local");
  if (lv) lv.srcObject = CALL.stream;
  await pc.setLocalDescription(await pc.createOffer());
  callSignal({ call: "offer", sdp: pc.localDescription, media });
}

async function onCallSignal(d) {
  const p = d.payload || {};
  if (p.call === "answer" && CALL.pc) {
    await CALL.pc.setRemoteDescription(p.sdp);
    for (const ice of CALL.pendingIce) {
      await CALL.pc.addIceCandidate(ice).catch(() => {});
    }
    CALL.pendingIce = [];
    CALL.state = "active";
    callOverlay("connected");
  } else if (p.call === "ice") {
    if (CALL.pc && CALL.pc.remoteDescription) {
      await CALL.pc.addIceCandidate(p.ice).catch(() => {});
    } else CALL.pendingIce.push(p.ice);
  } else if (["hangup", "decline", "busy"].includes(p.call)) {
    toast(p.call === "busy" ? "the desk is on another call" : "call ended");
    endCall(false);
  }
}

/* The support hub. Four ways to reach a person, offered in the order that
   suits the moment rather than the order that suits us: live chat and a call
   while someone is on, a ticket and a phone number when nobody is. */
let SUPPORT_CFG = null;

async function openSupport() {
  try {
    SUPPORT_CFG = await (await fetch("/api/store/support/config")).json();
  } catch { SUPPORT_CFG = null; }
  const c = SUPPORT_CFG || { topics: {}, staff_online: 0 };
  const live = c.staff_online > 0;
  openModal(`<h3>Support</h3>
    <p class="dim">${live
      ? "Someone's on right now — chat or call and you'll get a human."
      : `Nobody's on the desk this minute. Leave a message and we'll reply
         ${c.reply_target || "within one working day"}.`}</p>
    <div class="sup-options">
      <button class="sup-opt" data-sup="chat">
        ${ico("chat", "ico ico-lg")}
        <span><b>Live chat</b><small>${live
          ? "Usually answered in a few minutes" : "Leaves a message if nobody replies"}</small></span>
        ${live ? '<span class="sup-live">online</span>' : ""}</button>
      ${c.calls_enabled ? `
      <button class="sup-opt" data-sup="voice">
        ${ico("chat", "ico ico-lg")}
        <span><b>Voice call</b><small>Talk to whoever's on the desk</small></span></button>
      <button class="sup-opt" data-sup="video">
        ${ico("play", "ico ico-lg")}
        <span><b>Video call</b><small>Useful for showing us a damaged box</small></span></button>` : ""}
      <button class="sup-opt" data-sup="ticket">
        ${ico("box", "ico ico-lg")}
        <span><b>Send a message</b><small>We reply by email, ${
          c.reply_target || "within one working day"}</small></span></button>
      ${c.phone ? `
      <a class="sup-opt" href="tel:${c.phone.replace(/[^+\d]/g, "")}">
        ${ico("user", "ico ico-lg")}
        <span><b>${c.phone}</b><small>${c.phone_hours || ""}</small></span></a>` : ""}
      <button class="sup-opt" data-sup="lookup">
        ${ico("search", "ico ico-lg")}
        <span><b>Check on a message</b><small>Look it up by reference</small></span></button>
    </div>`);
  document.querySelectorAll("[data-sup]").forEach((b) => b.onclick = () => {
    const what = b.dataset.sup;
    if (what === "ticket") return openTicketForm();
    if (what === "lookup") return openTicketLookup();
    // chat and calls both need an account, so they share the one door
    const go = what === "chat" ? startSupportChat
      : () => startSupportCall(what);
    const saved = JSON.parse(localStorage.getItem("sf_support") || "null");
    if (saved && saved.token) {
      SUPPORT.token = saved.token; SUPPORT.me = saved.me; go(); return;
    }
    signIn("Real humans on the other end — the same system the team runs on.",
      go);
  });
}

function openTicketForm() {
  const topics = (SUPPORT_CFG && SUPPORT_CFG.topics) || { other: "Something else" };
  openModal(`<h3>Send us a message</h3>
    <p class="dim">A person reads these. You'll get a reference straight away
      and a reply by email.</p>
    <label>What's it about</label>
    <select id="tk-topic">${Object.entries(topics)
      .map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
    <div class="row">
      <div><label>Your name</label><input id="tk-name" autocomplete="name"></div>
      <div><label>Email</label><input id="tk-email" type="email"
        autocomplete="email"></div>
    </div>
    <label>Order reference <span class="dim">(if it's about an order)</span></label>
    <input id="tk-order" placeholder="#1234">
    <label>Message</label><textarea id="tk-body" rows="4"></textarea>
    <div class="modal-actions">
      <span class="dim" id="tk-msg" style="margin-right:auto"></span>
      <button class="btn-pill ghost sm" data-close-modal>Cancel</button>
      <button class="btn-pill primary sm" id="tk-send">Send</button>
    </div>`);
  $("#tk-send").onclick = async () => {
    const name = $("#tk-name").value.trim(), body = $("#tk-body").value.trim();
    if (!name || !body) { $("#tk-msg").textContent =
      "We need a name and a message."; return; }
    const btn = $("#tk-send"); btn.disabled = true;
    try {
      const H = { "Content-Type": "application/json" };
      if (acctToken()) H.Authorization = "Bearer " + acctToken();
      const r = await fetch("/api/store/support/ticket", { method: "POST",
        headers: H, body: JSON.stringify({ name,
          email: $("#tk-email").value.trim(), topic: $("#tk-topic").value,
          order_ref: $("#tk-order").value.trim(), body }) });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "failed");
      openModal(`<h3>Got it</h3>
        <p>Your reference is <b>${out.ref}</b> — keep it and you can check
          back any time. We'll reply by email
          ${(SUPPORT_CFG || {}).reply_target || "within one working day"}.</p>
        <div class="modal-actions">
          <button class="btn-pill primary sm" data-close-modal>Done</button>
        </div>`);
    } catch (e) {
      $("#tk-msg").textContent = String(e.message || e);
      btn.disabled = false;
    }
  };
}

function openTicketLookup() {
  openModal(`<h3>Check on a message</h3>
    <label>Reference</label><input id="tl-ref" placeholder="ZJ-4F2A">
    <div class="modal-actions">
      <button class="btn-pill ghost sm" data-close-modal>Close</button>
      <button class="btn-pill primary sm" id="tl-go">Look it up</button>
    </div>
    <div id="tl-out"></div>`);
  $("#tl-go").onclick = async () => {
    const ref = $("#tl-ref").value.trim();
    if (!ref) return;
    const r = await fetch("/api/store/support/ticket/"
      + encodeURIComponent(ref));
    if (!r.ok) { $("#tl-out").innerHTML =
      '<p class="dim" style="margin-top:12px">No message with that reference.</p>';
      return; }
    const t = await r.json();
    $("#tl-out").innerHTML = `<div style="margin-top:14px;padding-top:14px;
      border-top:1px solid var(--line)">
      <span class="event-kind">${t.status}</span>
      <p style="margin:8px 0">${t.body}</p>
      ${t.replies.map((rp) => `<div class="review-card"
        style="margin-top:10px;padding:14px">
        <b style="font-size:13px">${rp.staff ? rp.author : "You"}</b>
        <p style="font-size:14px;margin:4px 0 0">${rp.body}</p></div>`).join("")
        || '<p class="dim">No reply yet.</p>'}</div>`;
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
  if (!hist.length) draw([{ id: 0.5, user_id: -1, name: BRAND_T(),
    body: "Hey — how can we help?" }]);
  // realtime: the same /ws the team uses, shared with call signaling
  SUPPORT.onMessage = (d) => {
    if (d.type === "msg" && d.conv_id === SUPPORT.conv) draw([d.message]);
  };
  ensureSupportSocket();
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
  navigator.serviceWorker.register("/sf-sw.js",
    /* never from the HTTP cache: the worker is the thing that
       ships the fix, so it cannot be the thing that arrives
       stale */
    { updateViaCache: "none" }).catch(() => {});

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
      PIXEL.track("enquiry");
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
  let active = null, query = "", here = null, focused = null;

  // straight-line distance is honest for "which of these is nearest" and
  // needs no map tiles or third-party call
  const milesBetween = (a, b, c, d) => {
    const R = 3958.8, rad = (x) => x * Math.PI / 180;
    const dLat = rad(c - a), dLng = rad(d - b);
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  };

  /* A map without tiles. An equirectangular projection over the lower-48
     bounding box is accurate enough to answer "roughly where is this", costs
     no third-party request, and can't leak the shopper's viewing habits to a
     tile server. The outline is a coarse path — it reads as the US at this
     size without shipping a 200KB topology. */
  const BOX = { w: -125, e: -66.5, n: 49.5, s: 24.5 };
  const MAP_W = 1000, MAP_H = 560;
  const project = (lat, lng) => [
    ((lng - BOX.w) / (BOX.e - BOX.w)) * MAP_W,
    ((BOX.n - lat) / (BOX.n - BOX.s)) * MAP_H,
  ];
  /* Coarse lower-48 outline as real [lat, lng] waypoints, projected through
     the same function as the pins. Hand-drawing the path in SVG units put
     stores outside the country — deriving both from one projection makes that
     impossible. The Great Lakes are traced along their southern shores rather
     than cut out; at this size that reads correctly. */
  const US_EDGE = [
    [49.0, -123.0], [48.4, -124.7], [46.2, -124.0], [44.6, -124.1],
    [42.0, -124.2], [40.4, -124.4], [38.0, -123.0], [36.6, -121.9],
    [34.4, -120.5], [33.7, -118.3], [32.5, -117.1],
    [32.5, -114.8], [31.3, -111.0], [31.8, -106.5], [29.8, -102.4],
    [25.9, -97.4], [27.8, -97.4], [29.3, -94.8], [29.7, -93.3],
    [29.2, -90.0], [30.2, -88.0], [30.4, -86.5], [29.7, -84.9],
    [28.0, -82.8], [25.1, -80.9], [25.8, -80.2], [28.4, -80.6],
    [32.0, -80.8], [33.9, -78.0], [35.2, -75.5], [37.0, -76.0],
    [38.8, -75.1], [40.5, -74.0], [41.4, -71.5], [42.0, -70.1],
    [43.7, -70.0], [44.8, -67.0], [47.0, -69.2], [45.0, -71.5],
    [45.0, -74.7], [43.3, -79.1], [42.3, -83.0], [46.0, -84.4],
    [46.8, -90.0], [47.4, -92.0], [49.0, -95.2],
  ];
  const US_PATH = US_EDGE.map(([la, ln], i) => {
    const [x, y] = project(la, ln);
    return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ") + " Z";

  const drawMap = (shown) => {
    const host = $("#loc-map");
    if (!host) return;
    const pins = shown.filter((s) => s.lat && s.lng).map((s) => {
      const [x, y] = project(s.lat, s.lng);
      const on = s.id === focused;
      return `<g class="loc-pin ${on ? "on" : ""}" data-pin="${s.id}"
        transform="translate(${x.toFixed(1)},${y.toFixed(1)})"
        tabindex="0" role="button"
        aria-label="${s.name}, ${s.city}">
        <circle class="halo" r="${on ? 26 : 18}"/>
        <circle class="dot" r="${on ? 9 : 6.5}"/>
        <title>${s.name} — ${s.city}</title></g>`;
    }).join("");
    const me = here ? (() => {
      const [x, y] = project(here.lat, here.lng);
      return `<g class="loc-me" transform="translate(${x.toFixed(1)},${y.toFixed(1)})">
        <circle class="me-halo" r="22"/><circle class="me-dot" r="7"/>
        <title>You are here</title></g>`;
    })() : "";
    host.innerHTML = `<svg viewBox="0 0 ${MAP_W} ${MAP_H}" class="loc-map"
      role="img" aria-label="Map of stores carrying the brand">
      <path class="us" d="${US_PATH}"/>${me}${pins}</svg>`;
    host.querySelectorAll("[data-pin]").forEach((g) => {
      const pick = () => {
        focused = +g.dataset.pin;
        paint();
        const card = document.querySelector(`[data-loc="${focused}"]`);
        if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
      };
      g.onclick = pick;
      g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") {
        e.preventDefault(); pick(); } };
    });
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
    host.innerHTML = shown.map((s) => `<div class="loc-card
      ${s.id === focused ? "on" : ""}" data-loc="${s.id}">
      <b>${s.name}</b>
      <div class="where">${ico("pin", "ico ico-sm")}
        ${[s.city, s.region].filter(Boolean).join(" · ")}</div>
      ${here && isFinite(s._d)
        ? `<span class="dist">${s._d.toFixed(1)} miles away</span>` : ""}
    </div>`).join("");
    host.querySelectorAll("[data-loc]").forEach((c) => c.onclick = () => {
      focused = focused === +c.dataset.loc ? null : +c.dataset.loc;
      paint();
    });
    drawMap(shown);
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

/* ---------- blog comments ---------- */
(function wireComments() {
  const f = document.querySelector(".cmt-form");
  if (!f) return;
  f.onsubmit = async (e) => {
    e.preventDefault();
    const msg = f.querySelector(".cmt-msg");
    const body = {};
    for (const el of f.elements) if (el.name) body[el.name] = el.value.trim();
    if (!body.name || !body.body) {
      msg.textContent = "A name and a comment, please."; return; }
    const btn = f.querySelector("button"); btn.disabled = true;
    try {
      const r = await fetch(`/api/store/blog/${f.dataset.slug}/comments`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.json()).detail || "failed");
      f.reset();
      msg.textContent = "Thanks — your comment appears once it's approved.";
    } catch (err) {
      msg.textContent = String(err.message || err);
    } finally { btn.disabled = false; }
  };
})();

/* ---------- marketing pixels + consent ----------
   The snippet in <head> defines window.__pixelConfig and a __pixelLoad() that
   only runs once consent is given. This half translates the storefront's own
   events into each provider's vocabulary and mirrors every one to our own log,
   so the merchant can reconcile the platforms' numbers against the ledger. */
const PIXEL = (() => {
  const cfg = window.__pixelConfig;
  const KEY = "sf_consent";
  let consent = null;
  try { consent = JSON.parse(localStorage.getItem(KEY)); } catch {}

  const paintToggle = () => {
    const t = $("#pref-consent");
    if (!t) return;
    t.classList.toggle("on", consent === true);
    t.setAttribute("aria-checked", consent === true ? "true" : "false");
  };

  const applyConsent = (yes) => {
    consent = yes;
    localStorage.setItem(KEY, JSON.stringify(yes));
    if (yes && window.__pixelLoad) {
      window.__pixelConsent = true; window.__pixelLoad();
    }
    const bar = $("#consent-bar");
    if (bar) bar.hidden = true;
    clearBarRoom();
    paintToggle();
  };

  /* The consent bar and the Buy now button both live in the bottom-right
     corner, and the bar wins on z-index — so while it is up it covers the
     one control the whole page exists to lead to.

     The bar's height is not a constant to hard-code against: its copy is
     merchant-editable and it wraps to two or three lines on a narrow window.
     So it is measured, published as a custom property, and the floating
     controls are lifted by that much. ResizeObserver keeps it right when the
     text reflows on rotate or zoom. */
  let barWatch = null;
  function makeBarRoom(bar) {
    const apply = () => document.documentElement.style.setProperty(
      "--consent-h", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
    apply();
    document.body.classList.add("consent-open");
    if ("ResizeObserver" in window) {
      barWatch = new ResizeObserver(apply);
      barWatch.observe(bar);
    }
  }
  function clearBarRoom() {
    document.body.classList.remove("consent-open");
    document.documentElement.style.removeProperty("--consent-h");
    if (barWatch) { barWatch.disconnect(); barWatch = null; }
  }

  // Show the bar only when there is actually something to consent to.
  if (PREVIEW) { consent = false; } else if (cfg && cfg.consentRequired && consent === null) {
    const bar = $("#consent-bar");
    if (bar) {
      $("#consent-text").textContent = cfg.consentText || "We use cookies to "
        + "measure our ads. You can say no — the shop works exactly the same "
        + "either way.";
      bar.hidden = false;
      makeBarRoom(bar);
      $("#consent-yes").onclick = () => applyConsent(true);
      $("#consent-no").onclick = () => applyConsent(false);
    }
  } else if (cfg && !cfg.consentRequired) {
    consent = true;
  } else if (consent === true && window.__pixelLoad) {
    window.__pixelConsent = true; window.__pixelLoad();
  }

  /* Withdrawing consent has to be as easy as giving it, so the choice lives
     in the preferences panel too — the bar only ever appears once. Only shown
     when there is actually something to consent to. */
  if (cfg && cfg.consentRequired && !PREVIEW) {
    const row = $("#pref-consent-row"), grp = $("#pref-privacy-group");
    if (row && grp) {
      row.hidden = false; grp.hidden = false;
      paintToggle();
      $("#pref-consent").onclick = () => {
        const turningOff = consent === true;
        applyConsent(!turningOff);
        // Scripts already in the page can't be unloaded, so turning it off
        // reloads — otherwise "off" would be a label rather than a fact.
        if (turningOff) location.reload();
      };
    }
  }

  return {
    track(event, { value_cents = 0, ...extra } = {}) {
      if (PREVIEW) return;
      // Always record it first-party — that's ours, and it's what makes the
      // platforms' numbers checkable. Consent only gates the third parties.
      fetch("/api/store/pixel-event", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event, value_cents,
          consent: consent === true }) }).catch(() => {});
      if (!cfg || !cfg.events || !cfg.events[event] || consent !== true) return;
      const map = (cfg.map || {})[event] || {};
      const val = value_cents / 100;
      const money = val ? { value: val, currency: "USD" } : {};
      try {
        if (cfg.ids.meta && window.fbq && map.meta) {
          window.fbq("track", map.meta, { ...money, ...extra });
        }
        if (cfg.ids.tiktok && window.ttq && map.tiktok) {
          window.ttq.track(map.tiktok, money);
        }
        if ((cfg.ids.ga4 || cfg.ids.gads) && window.gtag) {
          window.gtag("event", event, money);
        }
        if (cfg.ids.pinterest && window.pintrk && map.pinterest) {
          window.pintrk("track", map.pinterest, money);
        }
        if (cfg.ids.snap && window.snaptr && map.snap) {
          window.snaptr("track", map.snap, val ? { price: val } : {});
        }
      } catch {}
    },
  };
})();

/* ---------- interaction heatmap ----------
   Records where on the page people click and how far they scroll, so the
   admin can see a page the way its visitors use it. Coordinates are stored as
   a fraction of the page box rather than pixels, so one recording replays at
   any viewport. Nothing identifying is captured — no visitor id, no typed
   text, and password/email fields are skipped entirely. */
(function heatmap() {
  if (PREVIEW) return;          // never record the admin's own preview
  const HITS = [];
  let deepest = 0;

  const trackDepth = () => {
    const h = document.documentElement.scrollHeight - innerHeight;
    deepest = Math.max(deepest, h > 0 ? Math.min(1, scrollY / h) : 1);
  };
  addEventListener("scroll", trackDepth, { passive: true });
  trackDepth();

  // A coarse description of what was hit — tag plus its first class, or an
  // id. Never the element's text, which can contain what someone typed.
  const describe = (el) => {
    if (!el || !el.tagName) return "";
    const t = el.tagName.toLowerCase();
    if (el.id) return `${t}#${el.id}`;
    const cls = (el.className || "").toString().trim().split(/\s+/)[0];
    return cls ? `${t}.${cls}` : t;
  };

  addEventListener("click", (e) => {
    const el = e.target;
    if (el && el.closest && el.closest("input[type=password], input[type=email]")) return;
    const doc = document.documentElement;
    const w = doc.scrollWidth, h = doc.scrollHeight;
    if (!w || !h) return;
    HITS.push({
      x: +(e.pageX / w).toFixed(4),
      y: +(e.pageY / h).toFixed(4),
      vw: innerWidth,
      label: describe(el.closest("a,button,input,select,summary") || el),
      depth: +deepest.toFixed(3),
    });
    if (HITS.length >= 60) flush();
  }, { passive: true, capture: true });

  function flush() {
    if (!HITS.length) return;
    const body = JSON.stringify({
      page: location.pathname.slice(0, 120),
      hits: HITS.splice(0, HITS.length),
    });
    // sendBeacon survives the page going away; fetch is the fallback
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/store/clicks",
        new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/store/clicks", { method: "POST", keepalive: true,
        headers: { "Content-Type": "application/json" }, body }).catch(() => {});
    }
  }
  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  addEventListener("pagehide", flush);
})();

/* ---------- showcase carousel ----------

   Position is read back from scrollLeft rather than kept in a variable. A
   scroll-snap rail can be moved by a drag, a trackpad, a shift-wheel or a
   focus jump, none of which go through the arrow handlers — anything that
   remembers an index drifts out of step with what is actually on screen the
   first time someone swipes.

   The film is muted so it can autoplay at all (browsers block sound), and it
   is paused whenever it scrolls out of view: a hero video that keeps
   decoding behind six product slides costs battery for something nobody is
   watching. */
(function showcase() {
  const rail = $("#show-rail");
  if (!rail) return;
  const slides = [...rail.children];
  const dots = [...document.querySelectorAll(".show-dot")];
  const prev = $("#show-prev"), next = $("#show-next");
  const video = $("#show-video");

  /* Two separate reasons to hold the film: it is not the slide on screen,
     and the carousel itself has scrolled off the page. Keeping them as one
     flag conflated them, and a stale value meant the film could stay dark
     while sitting in plain view. */
  let onScreen = true;

  const sound = $("#show-sound");
  let watched = false;                 // has the film genuinely played here?

  /* Sound is wanted on. Browsers will not autoplay audible media without a
     prior user gesture, so this asks for sound, and falls back to muted
     playback rather than to no playback at all — a silent film beats a
     frozen poster. `wantSound` remembers the intent so the first gesture
     can turn it on for real, and so an explicit mute is not undone. */
  let wantSound = true;

  function paintSound() {
    if (!sound) return;
    sound.setAttribute("aria-pressed", String(!video.muted));
    sound.querySelector("span").textContent =
      video.muted ? "Sound on" : "Sound off";
    sound.setAttribute("aria-label",
      video.muted ? "Turn sound on" : "Turn sound off");
  }

  function tryAudible() {
    if (!video || !wantSound || !video.muted) return;
    video.muted = false;
    video.play().catch(() => { video.muted = true; paintSound(); });
    paintSound();
  }

  if (video) {
    video.muted = false;
    video.play().catch(() => {          // policy said no; play it silent
      video.muted = true;
      video.play().catch(() => {});
    }).finally(paintSound);

    /* If it was blocked, the first deliberate interaction is a gesture the
       policy accepts. Scoped to the carousel so a click in the footer can
       never start sound out of nowhere. */
    $("#showcase").addEventListener("pointerdown", tryAudible);

    /* The film is not looped any more: it runs once and hands over to the
       first product. Looping would mean `ended` never fires. */
    /* Hand over only if the film genuinely played here. `ended` also fires
       for a restored element that was already at the end, before anyone
       has seen a frame — that is what opened the carousel on Mango. A
       real viewing crosses the 1s mark through timeupdate; a stale flag
       never does. */
    watched = false;
    video.addEventListener("timeupdate", () => {
      if (video.currentTime > 1 && !video.paused) watched = true;
    });
    video.addEventListener("ended", () => { if (onScreen && watched) go(1); });

    /* ---- pause on click, and a timeline you can scrub ----
       `held` is a *person's* pause, distinct from the pauses sync() applies
       when the film scrolls off. Without the distinction, scrolling away
       and back would restart a film someone had deliberately stopped. */
    const playBtn = $("#show-play");
    const scrub = $("#show-scrub"), fill = $("#show-scrub-fill");
    const knob = $("#show-scrub-knob"), buf = $("#show-scrub-buf");
    let held = false;

    function paintPlay() {
      const paused = video.paused;
      playBtn.querySelector("use").setAttribute("href",
        paused ? "#i-play" : "#i-pause");
      playBtn.setAttribute("aria-label", paused ? "Play film" : "Pause film");
      playBtn.setAttribute("aria-pressed", String(!paused));
      playBtn.classList.toggle("is-paused", paused);
    }
    function toggle() {
      if (video.paused) { held = false; video.play().catch(() => {}); }
      else { held = true; video.pause(); }
      paintPlay();
    }
    video.addEventListener("click", toggle);
    playBtn.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
    video.addEventListener("play", paintPlay);
    video.addEventListener("pause", paintPlay);
    // sync() may hold the film for scroll reasons; expose the human flag
    video._held = () => held;

    function paintTime() {
      if (!video.duration) return;
      const p = video.currentTime / video.duration * 100;
      fill.style.width = p + "%";
      knob.style.left = p + "%";
      scrub.setAttribute("aria-valuenow", String(Math.round(p)));
      if (video.buffered.length) {
        buf.style.width = (video.buffered.end(video.buffered.length - 1)
                           / video.duration * 100) + "%";
      }
    }
    video.addEventListener("timeupdate", paintTime);
    video.addEventListener("progress", paintTime);
    video.addEventListener("loadedmetadata", paintTime);

    /* Seeking: pointer capture keeps the drag alive if the finger wanders
       off the track, and it lets one handler serve mouse, pen and touch. */
    const seekTo = (clientX) => {
      const r = scrub.getBoundingClientRect();
      const f = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      if (video.duration) video.currentTime = f * video.duration;
      paintTime();
    };
    scrub.addEventListener("pointerdown", (e) => {
      e.preventDefault(); e.stopPropagation();
      scrub.setPointerCapture(e.pointerId);
      scrub.classList.add("dragging");
      seekTo(e.clientX);
    });
    scrub.addEventListener("pointermove", (e) => {
      if (scrub.classList.contains("dragging")) seekTo(e.clientX);
    });
    const endDrag = (e) => {
      if (!scrub.classList.contains("dragging")) return;
      scrub.classList.remove("dragging");
      try { scrub.releasePointerCapture(e.pointerId); } catch {}
    };
    scrub.addEventListener("pointerup", endDrag);
    scrub.addEventListener("pointercancel", endDrag);
    scrub.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 5 : 1;
      if (e.key === "ArrowRight") { e.preventDefault();
        video.currentTime = Math.min(video.duration || 0, video.currentTime + step); }
      if (e.key === "ArrowLeft") { e.preventDefault();
        video.currentTime = Math.max(0, video.currentTime - step); }
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); }
    });
    paintPlay();
  }

  /* Clamped, because the two ways this reads wrong both end in
     `slides[i]` being undefined and sync() throwing:
       - a rail that has not been laid out yet (or is inside something
         hidden) has clientWidth 0, and 0/0 is NaN;
       - a rounding that lands one past the last slide.
     Neither is exotic — the first happens on any load where this runs
     before layout settles. */
  const at = () => {
    const w = rail.clientWidth;
    if (!w) return 0;
    return Math.max(0, Math.min(slides.length - 1,
                                Math.round(rail.scrollLeft / w)));
  };
  const go = (i) => rail.scrollTo({
    left: Math.max(0, Math.min(slides.length - 1, i)) * rail.clientWidth,
  });

  function sync() {
    const i = at();
    // Published so the shared controls (arrows) can take the active slide's
    // colours; they sit on the section, not inside the slide.
    $("#showcase").dataset.active = slides[i].dataset.pattern || "";
    dots.forEach((d, k) => d.classList.toggle("on", k === i));
    prev.disabled = i <= 0;
    next.disabled = i >= slides.length - 1;
    if (video) {
      const want = onScreen && slides[i] === video.closest(".show-slide")
                   && !(video._held && video._held());
      /* Guarded both ways: play() returns a promise that rejects if a
         pause() lands before it settles, and calling either redundantly is
         how that race gets started. */
      if (want && video.paused) video.play().catch(() => {});
      else if (!want && !video.paused) video.pause();
    }
  }

  prev.onclick = () => go(at() - 1);
  next.onclick = () => go(at() + 1);
  dots.forEach((d) => (d.onclick = () => go(+d.dataset.go)));
  rail.addEventListener("scroll", () => {
    clearTimeout(rail._t);
    rail._t = setTimeout(sync, 90);       // settle first, then read
  }, { passive: true });

  /* Arrow keys only while the carousel has focus — hijacking them globally
     breaks scrolling the rest of the page. */
  rail.tabIndex = 0;
  rail.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); go(at() + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(at() - 1); }
  });

  if (sound && video) {
    sound.onclick = () => {
      video.muted = !video.muted;
      wantSound = !video.muted;           // an explicit choice, remembered
      if (!video.muted) video.play().catch(() => { video.muted = true;
                                                   paintSound(); });
      paintSound();
    };
  }

  /* Stop the film when the carousel itself scrolls off the page. */
  if (video && "IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => {
      onScreen = e.isIntersecting;
      sync();
    }, { threshold: 0.25 }).observe($("#showcase"));
  }

  rail.querySelectorAll("[data-add]").forEach((b) => {
    b.onclick = () => addToCart(+b.dataset.add, 0);
  });

  /* Sound must not follow the visitor. Three ways to leave, three hooks:
     - another tab / app  → visibilitychange (a hidden tab keeps playing
                            audio otherwise, which is the classic complaint)
     - a route inside the shop (product page, journal) → the carousel is
                            no longer on screen; the IntersectionObserver
                            already handles that, but a pushState swap can
                            remove the section entirely, so watch for that
     - leaving the page  → pagehide; and bfcache can restore the page with
                            the film mid-play, so pause on pageshow too and
                            let sync() decide whether it should resume. */
  if (video) {
    /* Pause on *transition* to hidden, not on the standing state. Some
       embedded and split-screen contexts report document.hidden=true while
       the page is plainly on a screen; gating play on it would keep the
       film dark there. What we care about is the moment the visitor
       switches away — that is when sound following them is a complaint. */
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) video.pause();
      else sync();
    });
    addEventListener("pagehide", () => video.pause());
    addEventListener("pageshow", () => { video.pause(); sync(); });
    new MutationObserver(() => {
      if (!document.body.contains(video)) video.pause();
    }).observe(document.body, { childList: true, subtree: true });
  }
  addEventListener("resize", () => go(at()));

  /* Browsers restore a scroll container's position across a reload, and a
     snap container does not re-snap on its own — so a reload taken halfway
     through the rail reopened the page wedged between two slides. The film
     is the opener; start there every time. Assigning scrollLeft rather than
     scrollTo() skips the smooth behaviour, so it is the first frame rather
     than a visible slide-back. */
  /* Opening the carousel means opening it on the film, from the top. Two
     things fight that:
       - the browser restores the rail's scroll position after the first
         frame on a back/forward navigation, overwriting a rAF reset — so
         this runs on pageshow as well, which fires after restoration;
       - a film that already ran to the end (a bfcache restore, or a media
         element the browser kept warm) reports ended=true immediately, and
         the ended→next-slide handoff fires before anyone has seen it — the
         carousel opened on Mango instead of the film. Rewinding it here is
         what makes "start on the film" actually mean it. */
  function openOnFilm() {
    rail.scrollLeft = 0;
    if (video && (video.ended || video.currentTime > 0.5)) {
      video.currentTime = 0;
    }
    sync();
  }
  requestAnimationFrame(openOnFilm);
  addEventListener("pageshow", openOnFilm);
  addEventListener("popstate", () => { if (rail.isConnected) openOnFilm(); });
  /* A reload can hand back a media element already sitting at the end,
     and it does so *after* the first frame — the rAF above sees t=0 and
     leaves it, then the real state arrives at 14.6s with ended=true. The
     metadata event is the moment that state is trustworthy. Guarded on
     `watched` so a viewer's own seek is never undone. */
  if (video) {
    video.addEventListener("loadedmetadata", () => {
      if (!watched && (video.ended || video.currentTime > 0.5)) {
        video.currentTime = 0;
        rail.scrollLeft = 0;
        sync();
      }
    });
  }
  sync();
})();

/* ---------- first-visit offer ----------

   Held back until the visitor has shown some intent — a scroll past the
   opener, or twenty seconds — because an overlay in the first second is
   what trained everyone to close these without reading. Shown once ever:
   the flag is set whether they join, skip or close, so it cannot nag.

   The discount code is not minted here. The client asks for it and the
   server decides; a code the page could invent would be a code anyone
   could invent. */
(function firstVisitOffer() {
  const wrap = $("#offer");
  if (!wrap || PREVIEW) return;
  const KEY = "sf_offer_seen";
  try { if (localStorage.getItem(KEY)) return; } catch { return; }

  let armed = true;
  const settle = (why) => {
    armed = false;
    try { localStorage.setItem(KEY, why); } catch {}
    removeEventListener("scroll", onScroll);
    clearTimeout(timer);
  };
  const close = (why) => {
    settle(why);
    wrap.hidden = true;
    document.body.classList.remove("offer-open");
  };
  const show = () => {
    if (!armed || document.body.classList.contains("drawer-open")) return;
    armed = false;                       // opened once; the flag is set on exit
    wrap.hidden = false;
    document.body.classList.add("offer-open");
    $("#offer-email").focus();
  };

  const onScroll = () => { if (scrollY > innerHeight * 0.6) show(); };
  addEventListener("scroll", onScroll, { passive: true });
  const timer = setTimeout(show, 20000);

  $("#offer-close").onclick = () => close("closed");
  $("#offer-skip").onclick = () => close("skipped");
  wrap.onclick = (e) => { if (e.target === wrap) close("closed"); };
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !wrap.hidden) close("closed");
  });

  $("#offer-form").onsubmit = async (e) => {
    e.preventDefault();
    const email = $("#offer-email").value.trim();
    const msg = $("#offer-msg"), go = $("#offer-go");
    go.disabled = true;
    msg.textContent = "Signing you up…";
    try {
      const r = await fetch("/api/store/subscribe", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, source: "first-visit-offer" }) });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(out.detail || "that didn't go through");
      settle("joined");
      // The code comes back from the server, or falls back to the standing
      // welcome discount — never invented on the client.
      const code = out.code || "WELCOME10";
      wrap.querySelector(".offer-card").innerHTML = `
        <span class="offer-badge">You're in</span>
        <h2>Here's 10% off.</h2>
        <p>Use this at checkout — we've also emailed it to you.</p>
        <div class="offer-code"><b>${code}</b>
          <button class="btn-pill ghost sm" id="offer-copy">Copy</button></div>
        <button class="offer-skip" id="offer-done">Start shopping</button>`;
      $("#offer-copy").onclick = () => {
        navigator.clipboard?.writeText(code);
        $("#offer-copy").textContent = "Copied";
      };
      $("#offer-done").onclick = () => close("joined");
    } catch (err) {
      msg.textContent = err.message || "That didn't go through — try again.";
      go.disabled = false;
    }
  };
})();

/* ---------- entry points into the review form ----------

   openReviews() has always contained a complete write-a-review form; what
   it lacked was any way in. The product page knows which product it is and
   says so in a data attribute. The home page's wall is the whole range, so
   it has to ask. */
function wireReviewButtons() {
  document.querySelectorAll("[data-review-for]").forEach((b) => {
    b.onclick = () => openReviews(+b.dataset.reviewFor);
  });
  const wall = $("#write-review");
  if (wall) {
    wall.onclick = () => {
      const list = CATALOG.products.map((p) => `
        <button class="rev-pick" data-pick="${p.id}"
                style="--flavour:${flavourOf(p)}">
          ${art(p, "art", false, true)}<b>${pname(p)}</b></button>`).join("");
      openModal(`<h3>Which one are you reviewing?</h3>
        <div class="rev-picks">${list}</div>`);
      document.querySelectorAll("[data-pick]").forEach((b) => {
        b.onclick = () => openReviews(+b.dataset.pick);
      });
    };
  }
}

// ---------- boot ----------
buildPickers();
saveCart();
loadCatalog().then(() => {
  loadPromos();
  confirmPaidReturn();
  confirmPlanReturn();
  if (qs.get("cart")) { drawCart(); openCart(); }  // back from product page
});
