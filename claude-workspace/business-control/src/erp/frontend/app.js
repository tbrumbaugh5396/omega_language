/* Business Control — single-page PWA frontend. */
"use strict";

// ---------- state ----------
const S = {
  user: JSON.parse(localStorage.getItem("bc_user") || "null"),
  meta: { regions: [], funnel_steps: [] },
  cart: {},              // product_id -> qty
  products: [],
  ab: [],                // active experiment assignments for this visitor
  tab: null,
};

const $ = (sel) => document.querySelector(sel);
const view = () => $("#view");
const money = (c) => "$" + (c / 100).toFixed(2);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

function visitorId() {
  let v = localStorage.getItem("bc_visitor");
  if (!v) {
    v = "v" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem("bc_visitor", v);
  }
  return v;
}

// affiliate ref capture from /r/<code> redirect (?ref=), and promo QR landings
{
  const params = new URLSearchParams(location.search);
  const ref = params.get("ref");
  if (ref) localStorage.setItem("bc_ref", ref);
  const promo = params.get("promo");
  if (promo) S.promoLanding = +promo;
  // Stripe Checkout return: confirm the session server-side.
  const paid = params.get("paid");
  const sid = params.get("sid");
  if (paid && sid) S._confirmPay = { order_id: +paid, session_id: sid };
  if (params.get("cancelled")) S._payCancelled = true;
  if (ref || promo || paid || params.get("cancelled")) {
    history.replaceState(null, "", "/");
  }
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2600);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.user) headers["Authorization"] = "Bearer " + S.user.token;
  const r = await fetch(path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    if (r.status === 401 && S.user) { logout(); }
    throw new Error(msg);
  }
  return r.json();
}

// ---------- third-party pixels (GA4, Meta/Instagram, TikTok) ----------

function initPixels(t = {}) {
  if (t.ga_measurement_id) {
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" +
      encodeURIComponent(t.ga_measurement_id);
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    gtag("js", new Date());
    gtag("config", t.ga_measurement_id);
  }
  if (t.meta_pixel_id) {
    /* standard Meta pixel bootstrap (covers Facebook + Instagram) */
    !function (f, b, e, v, n, ts, s) {
      if (f.fbq) return; n = f.fbq = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      if (!f._fbq) f._fbq = n; n.push = n; n.loaded = true; n.version = "2.0";
      n.queue = []; ts = b.createElement(e); ts.async = true; ts.src = v;
      s = b.getElementsByTagName(e)[0]; s.parentNode.insertBefore(ts, s);
    }(window, document, "script", "https://connect.facebook.net/en_US/fbevents.js");
    fbq("init", t.meta_pixel_id);
    fbq("track", "PageView");
  }
  if (t.tiktok_pixel_id) {
    /* standard TikTok pixel bootstrap */
    !function (w, d, tt) {
      w.TiktokAnalyticsObject = tt; const ttq = w[tt] = w[tt] || [];
      ttq.methods = ["page", "track", "identify", "instances", "debug", "on",
        "off", "once", "ready", "alias", "group", "enableCookie",
        "disableCookie"];
      ttq.setAndDefer = function (o, e) { o[e] = function () {
        o.push([e].concat(Array.prototype.slice.call(arguments, 0))); }; };
      for (let i = 0; i < ttq.methods.length; i++) ttq.setAndDefer(ttq, ttq.methods[i]);
      ttq.load = function (e) {
        const u = "https://analytics.tiktok.com/i18n/pixel/events.js";
        ttq._i = ttq._i || {}; ttq._i[e] = []; ttq._i[e]._u = u;
        ttq._t = ttq._t || {}; ttq._t[e] = +new Date();
        ttq._o = ttq._o || {};
        const o = d.createElement("script"); o.async = true;
        o.src = u + "?sdkid=" + e + "&lib=" + tt;
        const a = d.getElementsByTagName("script")[0];
        a.parentNode.insertBefore(o, a);
      };
      ttq.load(t.tiktok_pixel_id);
      ttq.page();
    }(window, document, "ttq");
  }
}

// funnel step -> [GA4 event, Meta event, TikTok event]
const PIXEL_EVENTS = {
  view_product: ["view_item", "ViewContent", "ViewContent"],
  add_to_cart: ["add_to_cart", "AddToCart", "AddToCart"],
  checkout: ["begin_checkout", "InitiateCheckout", "InitiateCheckout"],
  purchase: ["purchase", "Purchase", "CompletePayment"],
};

function pixelTrack(step, extra) {
  const m = PIXEL_EVENTS[step];
  if (!m) return;
  const d = { currency: "USD", value: (extra.value_cents || 0) / 100 };
  try {
    if (window.gtag) gtag("event", m[0], d);
    if (window.fbq) fbq("track", m[1], d);
    if (window.ttq && window.ttq.track) window.ttq.track(m[2], d);
  } catch {}
}

function track(step, extra = {}) {
  const exp = S.ab[0] || {};
  pixelTrack(step, extra);
  api("/api/events", { body: {
    visitor_id: visitorId(), step,
    region: (S.user && S.user.region) || "",
    experiment_id: exp.experiment_id ?? null,
    variant_id: exp.variant_id ?? null,
    ...extra,
  } }).catch(() => {});
}

const qrImg = (data, size = 130) =>
  `<span class="qrbox"><img width="${size}" height="${size}"
    src="/api/qr.svg?data=${encodeURIComponent(data)}" alt="QR"></span>`;

function logout() {
  localStorage.removeItem("bc_user");
  S.user = null;
  S.notifs = null;
  clearInterval(S._notifTimer);
  endCall(true);
  if (S._ws) { S._ws.onclose = null; S._ws.close(); S._ws = null; }
  const panel = $("#notif-panel");
  if (panel) panel.remove();
  render();
}


// ---------- small shared helpers ----------
const fmtDate = (t) => t ? new Date(t * 1000).toLocaleDateString(undefined,
  { day: "numeric", month: "short", year: "numeric" }) : "—";

/* A modal. The ops app previously did every form inline in a view, which is
   fine for a settings page and poor for anything you open from a list. */
function modal(html) {
  closeModal();
  const o = document.createElement("div");
  o.id = "ops-modal";
  o.innerHTML = `<div class="ops-modal-card">${html}</div>`;
  o.onclick = (e) => { if (e.target === o) closeModal(); };
  document.body.appendChild(o);
  o.querySelectorAll("[data-close]").forEach((b) => b.onclick = closeModal);
  const first = o.querySelector("input,select,textarea");
  if (first) setTimeout(() => first.focus(), 30);
  document.addEventListener("keydown", modalEsc);
}
function closeModal() {
  const o = $("#ops-modal");
  if (o) o.remove();
  document.removeEventListener("keydown", modalEsc);
}
function modalEsc(e) { if (e.key === "Escape") closeModal(); }

// ---------- chrome ----------

/* Inline stroked icons. The nav used emoji, which render differently on
   every OS, can't take the accent colour, and read as placeholder art in a
   tool people stare at all day. */
const OPS_ICONS = {
  cart: '<path d="M3 4h2.2l2 11.2a2 2 0 002 1.6h7.9a2 2 0 002-1.6L20 7H6.4"/><circle cx="10" cy="20" r="1.3"/><circle cx="17.5" cy="20" r="1.3"/>',
  box: '<path d="M3 7.5L12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5l9 4.5 9-4.5M12 12v9"/>',
  megaphone: '<path d="M3 10v4a1 1 0 001 1h2l5 4V5L6 9H4a1 1 0 00-1 1z"/><path d="M16 8.5a5 5 0 010 7"/><path d="M19 6a9 9 0 010 12"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5.3l3.3 2"/>',
  store: '<path d="M4 9.5V20h16V9.5"/><path d="M3 5h18l1 4.5a3 3 0 01-5.6 1.6 3 3 0 01-5.4 0 3 3 0 01-5.4 0A3 3 0 012 9.5z"/><path d="M9.5 20v-5h5v5"/>',
  truck: '<path d="M2.5 6.5h11v10h-11zM13.5 10h4l3 3v3.5h-7z"/><circle cx="7" cy="18.5" r="1.8"/><circle cx="17" cy="18.5" r="1.8"/>',
  handshake: '<path d="M8 12l3-3 2.5 2.5a1.6 1.6 0 002.3-2.2L13 6H9.5L6 8.5"/><path d="M12 15l2 2M14.5 12.5l2.2 2.2M6 8.5L2.5 11l4 4.5 2.5-1"/><path d="M18 8.5l3.5 2.5-3.5 4"/>',
  camera: '<path d="M3 8h4l1.5-2.5h7L17 8h4v12H3z"/><circle cx="12" cy="13.5" r="3.5"/>',
  feed: '<path d="M4 5h16v14H4z"/><path d="M7.5 9h5M7.5 12.5h9M7.5 16h9"/>',
  link: '<path d="M10.5 13.5a4 4 0 005.7 0l2.6-2.6a4 4 0 10-5.7-5.7L11.6 6.7"/><path d="M13.5 10.5a4 4 0 00-5.7 0l-2.6 2.6a4 4 0 105.7 5.7l1.4-1.4"/>',
  flask: '<path d="M10 3v6.2L4.8 18a2 2 0 001.7 3h11a2 2 0 001.7-3L14 9.2V3"/><path d="M8.5 3h7M7.4 14.5h9.2"/>',
  chart: '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 16v-4M12.5 16V8M17 16v-6"/>',
  chat: '<path d="M21 12a7.5 7.5 0 01-11 6.6L4 20l1.4-4.2A7.5 7.5 0 1121 12z"/>',
  hq: '<path d="M3 21V9l5-3 5 3v12"/><path d="M13 21V12h8v9"/><path d="M6.5 12h3M6.5 15.5h3M16 15.5h2M16 18.5h2"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 14a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5V20a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H4a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H12a1.6 1.6 0 001-1.5V4a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V12a1.6 1.6 0 001.5 1H20a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"/>',
  bell: '<path d="M18 8.5a6 6 0 10-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5z"/><path d="M13.7 19a2 2 0 01-3.4 0"/>',
  phone: '<path d="M6.5 3.5h3l1.5 4-2 1.4a12 12 0 006 6l1.4-2 4 1.5v3a2 2 0 01-2.2 2A17 17 0 014.5 5.7 2 2 0 016.5 3.5z"/>',
  video: '<path d="M3.5 6.5h11v11h-11z"/><path d="M14.5 10.5l6-3v9l-6-3z"/>',
  pin: '<path d="M12 21s7-6.1 7-11a7 7 0 10-14 0c0 4.9 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  users: '<circle cx="9" cy="8" r="3.4"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><path d="M16 5.2a3.4 3.4 0 010 5.6M17.5 20a6.6 6.6 0 00-2-4.7"/>',
  palette: '<path d="M12 3a9 9 0 000 18c1.4 0 2-1 2-1.8 0-1.6-1.6-1.7-1.6-3 0-1 .8-1.7 1.9-1.7H16a5 5 0 005-5c0-3.6-4-6.5-9-6.5z"/><circle cx="8" cy="10" r="1.1"/><circle cx="12" cy="7.5" r="1.1"/><circle cx="16" cy="10" r="1.1"/>',
  tag: '<path d="M3.5 11.5V4h7.5l9 9-7.5 7.5z"/><circle cx="7.5" cy="8" r="1.4"/>',
  calendar: '<path d="M3.5 6.5h17v14h-17z"/><path d="M3.5 10.5h17M8 3.5v4M16 3.5v4"/>',
  card: '<path d="M2.5 6h19v12h-19z"/><path d="M2.5 10h19"/>',
  bag: '<path d="M5 7.5h14l-1 13H6z"/><path d="M8.8 10V6.6a3.2 3.2 0 016.4 0V10"/>',
  tools: '<path d="M14.5 6a3.5 3.5 0 014.8 4.4l-9 9-3.2 1 1-3.2 9-9"/><path d="M4 8.5a3.5 3.5 0 004.9 3.2"/>',
  file: '<path d="M14 3H6.5A1.5 1.5 0 005 4.5v15A1.5 1.5 0 006.5 21h11a1.5 1.5 0 001.5-1.5V8z"/><path d="M14 3v5h5"/><path d="M8.5 13h7M8.5 16.5h7"/>',
  pen: '<path d="M15.5 4.5l4 4L8 20l-4.5.5L4 16z"/><path d="M13.5 6.5l4 4"/>',
  shield2: '<path d="M12 3l7.5 3v6c0 5-3.3 8-7.5 9.5C7.8 20 4.5 17 4.5 12V6z"/>',
};
const opsIcon = (n, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${
    OPS_ICONS[n] || ""}</svg>`;


const TABS = [
  { id: "shop", label: "Shop", icon: "cart", group: "Sell", roles: "*" },
  { id: "orders", label: "Orders", icon: "box", group: "Sell", roles: "*" },
  { id: "promos", label: "Promos", icon: "megaphone", group: "Sell",
    roles: ["admin", "employee"] },
  { id: "clock", label: "Time Clock", icon: "clock", group: "Operate", roles: "*" },
  { id: "inventory", label: "Inventory", icon: "store", group: "Operate",
    roles: ["admin", "employee", "distributor"] },
  { id: "routes", label: "Routes", icon: "truck", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "outreach", label: "Outreach", icon: "handshake", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "scan", label: "Scan", icon: "camera", group: "Operate", roles: "*" },
  { id: "feed", label: "Feed", icon: "feed", group: "Grow", roles: "*" },
  { id: "affiliates", label: "Affiliates", icon: "link", group: "Grow", roles: "*" },
  { id: "experiments", label: "Experiments", icon: "flask", group: "Grow",
    roles: ["admin"] },
  { id: "analytics", label: "Analytics", icon: "chart", group: "Grow",
    roles: ["admin"] },
  { id: "docs", label: "Documents", icon: "file", group: "Company",
    roles: ["admin", "employee"] },
  { id: "chat", label: "Chat", icon: "chat", group: "Company", roles: "*" },
  { id: "hq", label: "HQ", icon: "hq", group: "Company", roles: ["admin"] },
  { id: "admin", label: "Admin", icon: "gear", group: "Company", roles: ["admin"] },
];
const NAV_GROUPS = ["Sell", "Operate", "Grow", "Company"];
// Where each staff job lands after sign-in.
const JOB_HOME = { driver: "routes", dsd: "routes", warehouse: "inventory",
  sales_rep: "outreach", ambassador: "feed", event_staff: "promos" };
const JOB_LABEL = { general: "general", driver: "delivery driver",
  dsd: "DSD", warehouse: "warehouse", sales_rep: "sales rep",
  ambassador: "brand ambassador", event_staff: "event staff" };
// The 5 most-used tabs win the phone bottom bar, picked per role.
const MOBILE_PRIORITY = ["shop", "orders", "clock", "chat", "scan", "routes",
  "hq", "admin"];

function allowedTabs() {
  if (!S.user) return TABS.filter((t) => ["shop", "clock", "scan"].includes(t.id));
  return TABS.filter((t) => {
    if (t.roles === "*") return true;
    if (S.user.is_admin) return true;
    return t.roles.includes(S.user.role);
  });
}

function renderChrome() {
  const who = $("#whoami");
  if (S.user) {
    const unread = S.notifs ? S.notifs.unread : 0;
    const roleLabel = S.user.role === "employee" && S.user.job !== "general"
      ? JOB_LABEL[S.user.job] || S.user.role : S.user.role;
    who.innerHTML = `<a id="bell" title="notifications">${opsIcon("bell","bell-ic")}${unread
      ? `<span class="bell-n">${unread}</span>` : ""}</a> ·
      ${esc(S.user.name)} · ${esc(roleLabel)}` +
      (S.user.is_admin ? " · admin" : "") + ` · <a id="logout">sign out</a>`;
    $("#logout").onclick = logout;
    $("#bell").onclick = toggleNotifPanel;
  } else {
    who.innerHTML = `<a id="login-link">sign in</a>`;
    $("#login-link").onclick = () => { S.tab = "login"; render(); };
  }
  const tabs = allowedTabs();
  if (S.tab !== "login" && !tabs.find((t) => t.id === S.tab)) S.tab = tabs[0].id;
  const btn = (t) =>
    `<button data-t="${t.id}" class="${t.id === S.tab ? "on" : ""}">
      <span class="ic">${opsIcon(t.icon)}</span><span>${t.label}</span></button>`;
  $("#tabs").innerHTML = NAV_GROUPS.map((g) => {
    const group = tabs.filter((t) => t.group === g);
    if (!group.length) return "";
    return (tabs.length > 5 ? `<div class="nav-group">${g}</div>` : "") +
      group.map(btn).join("");
  }).join("");
  let bottom = $("#bottomnav");
  if (!bottom) {
    bottom = document.createElement("nav");
    bottom.id = "bottomnav";
    document.body.appendChild(bottom);
  }
  bottom.innerHTML = MOBILE_PRIORITY
    .map((id) => tabs.find((t) => t.id === id)).filter(Boolean).slice(0, 5)
    .map(btn).join("");
  document.querySelectorAll("#tabs button, #bottomnav button").forEach((b) => {
    b.onclick = () => { S.promoLanding = null; S.tab = b.dataset.t; render(); };
  });
}

const SKELETON = '<div class="skel"></div><div class="skel" style="height:180px">'
  + '</div><div class="skel"></div>';

function emptyState(icon, title, hint) {
  return `<div class="card empty"><span class="e-ic">${opsIcon(icon)}</span>
    <b>${title}</b><br>${hint}</div>`;
}

async function render() {
  renderChrome();
  if (S.promoLanding) return renderPromoLanding();
  if (!S.user && S.tab === "login") return renderLogin();
  view().innerHTML = SKELETON;
  const fn = {
    shop: renderShop, orders: renderOrders, clock: renderClock,
    chat: renderChat, scan: renderScan,
    affiliates: renderAffiliates, feed: renderFeed,
    inventory: renderInventory,
    routes: renderRoutes, promos: renderPromos, outreach: renderOutreach,
    experiments: renderExperiments, analytics: renderAnalytics,
    docs: renderDocs,
    hq: renderHQ, admin: renderAdmin, login: renderLogin,
  }[S.tab] || renderShop;
  try { await fn(); } catch (e) { view().innerHTML =
    `<div class="card">Error: ${esc(e.message)}</div>`; }
}

// ---------- login ----------

function renderLogin() {
  const regions = S.meta.regions.map((r) => `<option>${r}</option>`).join("");
  view().innerHTML = `
    <h2>Sign in</h2>
    <div class="row" style="max-width:760px">
    <div class="card" style="max-width:420px">
      <form class="inline" id="login-form" style="flex-direction:column;align-items:stretch">
        <label class="f">name <input id="li-name" required></label>
        <label class="f">I am a
          <select id="li-role">
            <option value="customer">customer</option>
            <option value="distributor">distributor</option>
            <option value="influencer">influencer</option>
            <option value="employee">employee</option>
            <option value="owner">founder / owner (needs admin key)</option>
          </select></label>
        <label class="f">region <select id="li-region"><option value=""></option>${regions}</select></label>
        <label class="f">email (for order updates & offers)
          <input id="li-email" type="email" placeholder="optional"></label>
        <label class="f">password <input id="li-pass" type="password"
          placeholder="sets on first sign-in, then required"></label>
        <label class="f">admin key (optional) <input id="li-admin" type="password"></label>
        <button class="btn">Sign in</button>
      </form>
    </div>
    <div class="card" style="max-width:280px;text-align:center">
      <h3 style="margin-top:0">Open on your phone</h3>
      <div id="lan-qr" class="dim">loading…</div>
      <div class="dim" style="margin-top:8px;font-size:12px">Scan from a phone
        on the same wifi. Admins can also issue one-tap sign-in QRs per user
        from the Admin tab.</div>
    </div>
    </div>`;
  api("/api/net").then((n) => {
    $("#lan-qr").innerHTML = qrImg(n.lan_url) +
      `<div class="dim" style="font-size:12px;margin-top:6px">${esc(n.lan_url)}</div>`;
  }).catch(() => { $("#lan-qr").textContent = "unavailable"; });
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const u = await api("/api/login", { body: {
        name: $("#li-name").value, role: $("#li-role").value,
        region: $("#li-region").value, admin_key: $("#li-admin").value,
        email: $("#li-email").value, password: $("#li-pass").value } });
      S.user = u;
      localStorage.setItem("bc_user", JSON.stringify(u));
      S.tab = (u.role === "employee" && JOB_HOME[u.job]) || "shop";
      startNotifPoll();
      connectWS();
      render();
    } catch (err) { toast(err.message); }
  };
}

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
            <button class="btn" id="checkout" ${S.user ? "" : "disabled"}>
              Checkout</button>
            ${S.user ? "" : '<span class="dim">sign in to order</span>'}
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

  const cartTotals = () => {
    let subtotal = 0;
    for (const [pid, qty] of Object.entries(S.cart)) {
      const p = S.products.find((x) => x.id === +pid);
      if (p) subtotal += qty *
        (isDistributor ? p.case_price_cents : p.price_cents);
    }
    const tax = isDistributor ? 0
      : Math.floor(subtotal * (S.meta.tax_bps || 0) / 10000);
    const shipping = (isDistributor || !subtotal
      || subtotal >= (S.meta.free_shipping_over_cents || 0))
      ? 0 : (S.meta.shipping_flat_cents || 0);
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
      track("purchase", { value_cents: o.total_cents || o.subtotal_cents });
      S.cart = {};
      if (o.checkout_url) {
        toast("redirecting to secure payment…");
        location.href = o.checkout_url;   // Stripe's hosted page
        return;
      }
      toast(`Order #${o.id} placed — ${money(o.total_cents)}`
        + (o.payment_status === "cod" ? " (pay on delivery)" : ""));
      S.tab = "orders";
      render();
    } catch (e) { toast(e.message); }
  };

  const onCheckout = () => {
    if (!Object.keys(S.cart).length) return toast("cart is empty");
    if (isDistributor) return placeOrder({});     // wholesale ships on terms
    const t = cartTotals();
    $("#checkout-box").innerHTML = `
      <div class="card" style="max-width:440px">
        <h3 style="margin-top:0">Delivery details</h3>
        <form class="inline" id="ship-form"
          style="flex-direction:column;align-items:stretch">
          <input id="sh-name" placeholder="full name"
            value="${esc(S.user.name)}" required>
          <input id="sh-addr" placeholder="street address" required>
          <div style="display:flex;gap:8px">
            <input id="sh-city" placeholder="city" required style="flex:1">
            <input id="sh-postal" placeholder="ZIP" style="width:90px">
          </div>
          <input id="sh-phone" placeholder="phone (optional)">
          ${S.meta.stripe_enabled ? `<label class="f">payment
            <select id="sh-pay"><option value="card">card (secure checkout)</option>
            <option value="cod">pay on delivery</option></select></label>`
          : '<div class="dim">payment: on delivery (card payments not enabled)</div>'}
          <div class="dim">subtotal ${money(t.subtotal)} · tax ${money(t.tax)}
            · shipping ${t.shipping ? money(t.shipping) : "FREE"} ·
            <b style="color:var(--text)">total ${money(t.total)}</b></div>
          <button class="btn">Place order — ${money(t.total)}</button>
        </form>
      </div>`;
    $("#checkout-box").scrollIntoView({ behavior: "smooth" });
    $("#ship-form").onsubmit = (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button.btn");
      btn.disabled = true;
      const paySel = $("#sh-pay");
      placeOrder({
        ship_name: $("#sh-name").value, address: $("#sh-addr").value,
        city: $("#sh-city").value, postal: $("#sh-postal").value,
        phone: $("#sh-phone").value,
        pay_method: paySel ? paySel.value : "cod" })
        .finally(() => { btn.disabled = false; });
    };
  };
  renderCartCard();
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
      <th>region</th><th>status</th>${isAdmin ? "<th></th>" : ""}
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
      </select></td>` : ""}
    </tr>`).join("")}</tbody></table>
    ${orders.length ? "" : emptyState("box", "No orders yet",
      isAdmin ? "They'll appear here the moment a customer checks out."
      : "Head to the Shop, add something to your cart, and check out.")}</div>`;
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
    <div class="card" style="max-width:380px;text-align:center">
      <div class="dim">Enter your PIN to clock in or out</div>
      <div style="margin:12px 0">
        <input id="pin" type="password" inputmode="numeric" placeholder="PIN"
          style="font-size:22px;text-align:center;width:160px">
      </div>
      ${events.length ? `<div style="margin-bottom:10px">
        <select id="clock-event"><option value="">regular shift</option>
        ${events.map((ev) => `<option value="${ev.id}">event: ${esc(ev.name)}
          ${ev.city ? "(" + esc(ev.city) + ")" : ""}</option>`).join("")}
        </select></div>` : ""}
      <button class="btn" id="punch" style="font-size:17px">Punch</button>
      <button class="btn alt" id="kiosk-btn" style="margin-left:6px"
        title="full-screen keypad for the store tablet">Kiosk mode</button>
      <div id="punch-msg" style="margin-top:10px"></div>
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
          ${S.user.is_admin ? `<button class="btn danger" data-del="${p.id}"
            style="float:right;padding:3px 9px">delete</button>` : ""}
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
    btn.disabled = true;
    btn.textContent = "Posting…";
    try {
      await api("/api/feed", { body: {
        body: $("#pf-body").value, url: $("#pf-url").value } });
      render();
    } catch (err) { toast(err.message); btn.disabled = false;
      btn.textContent = "Post"; }
  };
  document.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => {
      await api(`/api/admin/feed/${b.dataset.del}/delete`, { body: {} });
      render();
    };
  });
}

// ---------- confetti (achievement unlocks) ----------

function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = document.createElement("canvas");
  cv.id = "confetti";
  cv.width = innerWidth;
  cv.height = innerHeight;
  document.body.appendChild(cv);
  const ctx = cv.getContext("2d");
  const colors = ["#35b26b", "#4a9eda", "#d4a017", "#d0564f", "#a06ad4"];
  const parts = Array.from({ length: 90 }, () => ({
    x: cv.width / 2 + (Math.random() - 0.5) * 220,
    y: cv.height * 0.28,
    vx: (Math.random() - 0.5) * 9,
    vy: -Math.random() * 9 - 3,
    s: Math.random() * 6 + 3,
    c: colors[Math.floor(Math.random() * colors.length)],
    r: Math.random() * Math.PI,
  }));
  const t0 = performance.now();
  (function step(t) {
    ctx.clearRect(0, 0, cv.width, cv.height);
    for (const p of parts) {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.28;
      p.r += 0.1;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.fillStyle = p.c;
      ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6);
      ctx.restore();
    }
    if (t - t0 < 1700) requestAnimationFrame(step);
    else cv.remove();
  })(t0);
}

// ---------- live socket (chat + call signaling) ----------

function connectWS() {
  if (!S.user || S._ws) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/ws?token=${encodeURIComponent(S.user.token)}`);
  S._ws = ws;
  ws.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (d.type === "msg") onChatMessage(d);
    else if (d.type === "signal") onSignal(d);
  };
  ws.onclose = () => { S._ws = null; if (S.user) setTimeout(connectWS, 3000); };
}

function wsSend(obj) {
  if (S._ws && S._ws.readyState === 1) {
    S._ws.send(JSON.stringify(obj));
    return true;
  }
  return false;
}

function onChatMessage(d) {
  const m = d.message;
  if (S.tab === "chat" && S.chatConv === d.conv_id && $("#chat-msgs")) {
    if (!document.querySelector(`[data-mid="${m.id}"]`)) chatAppend(m);
    setLastRead(d.conv_id, m.id);
  } else if (m.user_id !== S.user.id) {
    toast(`${m.name}: ${m.body.slice(0, 60)}`);
  }
}

// ---------- calls (WebRTC over the socket) ----------

const CALL = { pc: null, peer: null, media: "audio", stream: null,
  pendingIce: [], state: "idle", offer: null, timer: null, started: 0 };

// Audible ring via WebAudio — no asset files needed.
const RING = { ctx: null, timer: null };
function ringStart() {
  try {
    RING.ctx = RING.ctx || new (window.AudioContext ||
      window.webkitAudioContext)();
    const beep = () => {
      const o = RING.ctx.createOscillator();
      const g = RING.ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.12, RING.ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, RING.ctx.currentTime + 0.7);
      o.connect(g).connect(RING.ctx.destination);
      o.start();
      o.stop(RING.ctx.currentTime + 0.75);
    };
    beep();
    RING.timer = setInterval(beep, 1800);
  } catch {}
}
function ringStop() {
  clearInterval(RING.timer);
  RING.timer = null;
}

function signal(payload) { wsSend({ type: "signal", to: CALL.peer, payload }); }

async function startCall(peerId, media) {
  if (!peerId) return toast("nobody available to call right now");
  if (CALL.state !== "idle") return toast("already in a call");
  CALL.peer = peerId;
  CALL.media = media;
  CALL.state = "calling";
  await setupPC(true);
}

async function setupPC(isCaller, remoteOffer) {
  try {
    CALL.stream = await navigator.mediaDevices.getUserMedia(
      { audio: true, video: CALL.media === "video" });
  } catch (e) {
    toast("mic/camera unavailable: " + e.message);
    return endCall(true);
  }
  const pc = new RTCPeerConnection(
    { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  CALL.pc = pc;
  CALL.stream.getTracks().forEach((t) => pc.addTrack(t, CALL.stream));
  pc.onicecandidate = (e) => {
    if (e.candidate) signal({ call: "ice", ice: e.candidate });
  };
  pc.ontrack = (e) => {
    const v = $("#call-remote");
    if (v && v.srcObject !== e.streams[0]) v.srcObject = e.streams[0];
  };
  pc.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(pc.connectionState) &&
        CALL.state !== "idle") { toast("call dropped"); endCall(true); }
  };
  showCallOverlay(isCaller ? "calling…" : "connecting…");
  const lv = $("#call-local");
  if (lv) lv.srcObject = CALL.stream;
  if (isCaller) {
    await pc.setLocalDescription(await pc.createOffer());
    signal({ call: "offer", sdp: pc.localDescription, media: CALL.media });
  } else {
    await pc.setRemoteDescription(remoteOffer);
    for (const ice of CALL.pendingIce) await pc.addIceCandidate(ice).catch(() => {});
    CALL.pendingIce = [];
    await pc.setLocalDescription(await pc.createAnswer());
    signal({ call: "answer", sdp: pc.localDescription });
    CALL.state = "active";
    setCallStatus("connected");
  }
}

async function onSignal(d) {
  const p = d.payload || {};
  if (p.call === "offer") {
    if (CALL.state !== "idle") {
      wsSend({ type: "signal", to: d.from, payload: { call: "busy" } });
      return;
    }
    CALL.peer = d.from;
    CALL.media = p.media || "audio";
    CALL.state = "ringing";
    CALL.offer = p.sdp;
    showRing(d.from_name, p.media || "audio");
  } else if (p.call === "answer" && CALL.pc) {
    await CALL.pc.setRemoteDescription(p.sdp);
    for (const ice of CALL.pendingIce) await CALL.pc.addIceCandidate(ice).catch(() => {});
    CALL.pendingIce = [];
    CALL.state = "active";
    setCallStatus("connected");
  } else if (p.call === "ice") {
    if (CALL.pc && CALL.pc.remoteDescription) {
      await CALL.pc.addIceCandidate(p.ice).catch(() => {});
    } else CALL.pendingIce.push(p.ice);
  } else if (["hangup", "decline", "busy"].includes(p.call)) {
    toast(p.call === "busy" ? "they're on another call" : "call ended");
    endCall(false);
  }
}

function showCallOverlay(status) {
  let o = $("#call-overlay");
  if (!o) {
    o = document.createElement("div");
    o.id = "call-overlay";
    document.body.appendChild(o);
  }
  o.innerHTML = `
    <div class="call-box">
      <div id="call-status" class="dim">${esc(status)}</div>
      <video id="call-remote" autoplay playsinline
        ${CALL.media === "audio" ? 'style="height:60px;background:#0c1013"' : ""}></video>
      <video id="call-local" autoplay playsinline muted
        ${CALL.media === "audio" ? 'style="display:none"' : ""}></video>
      <button class="btn danger" id="call-end">Hang up</button>
    </div>`;
  $("#call-end").onclick = () => endCall(true);
}

function setCallStatus(s) {
  const el = $("#call-status");
  if (el) el.textContent = s;
  if (s === "connected" && !CALL.timer) {
    CALL.started = Date.now();
    CALL.timer = setInterval(() => {
      const sec = Math.floor((Date.now() - CALL.started) / 1000);
      const el2 = $("#call-status");
      if (el2) el2.textContent =
        `connected · ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    }, 1000);
  }
}

function showRing(name, media) {
  ringStart();
  let o = $("#call-overlay");
  if (!o) {
    o = document.createElement("div");
    o.id = "call-overlay";
    document.body.appendChild(o);
  }
  o.innerHTML = `
    <div class="call-box">
      <div style="font-size:17px">${opsIcon(media === "video" ? "video" : "phone","call-ic")}
        <b>${esc(name)}</b> is calling…</div>
      <div style="margin-top:12px">
        <button class="btn" id="call-accept">Accept</button>
        <button class="btn danger" id="call-decline">Decline</button>
      </div>
    </div>`;
  $("#call-accept").onclick = () => { ringStop(); setupPC(false, CALL.offer); };
  $("#call-decline").onclick = () => {
    ringStop();
    signal({ call: "decline" });
    endCall(false);
  };
}

function endCall(sendHangup) {
  ringStop();
  clearInterval(CALL.timer);
  if (sendHangup && CALL.peer && CALL.state !== "idle") {
    signal({ call: "hangup" });
  }
  if (CALL.pc) CALL.pc.close();
  if (CALL.stream) CALL.stream.getTracks().forEach((t) => t.stop());
  Object.assign(CALL, { pc: null, peer: null, stream: null, pendingIce: [],
    state: "idle", offer: null, timer: null });
  const o = $("#call-overlay");
  if (o) o.remove();
}

// ---------- chat ----------

function chatAppend(m) {
  const box = $("#chat-msgs");
  if (!box) return;
  const mine = m.user_id === S.user.id;
  const el = document.createElement("div");
  el.className = "msg" + (mine ? " mine" : "");
  el.dataset.mid = m.id;
  el.innerHTML = `${mine ? "" : `<span class="dim" style="font-size:11px">
    ${esc(m.name)}</span><br>`}${esc(m.body)}
    <span class="dim" style="font-size:10px"> ${timeAgo(m.created_at)}</span>`;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

const lastRead = () => JSON.parse(localStorage.getItem("bc_lastread") || "{}");
const setLastRead = (cid, mid) => {
  const lr = lastRead();
  lr[cid] = Math.max(lr[cid] || 0, mid || 0);
  localStorage.setItem("bc_lastread", JSON.stringify(lr));
};

async function renderChat() {
  if (!S.user) { S.tab = "login"; return renderLogin(); }
  connectWS();
  const data = await api("/api/chat/convs");
  const lr = lastRead();
  const isStaff = S.user.is_admin ||
    ["employee", "owner"].includes(S.user.role);
  if (!data.convs.find((c) => c.id === S.chatConv)) {
    S.chatConv = data.convs.length ? data.convs[0].id : null;
  }
  const conv = data.convs.find((c) => c.id === S.chatConv);
  const staff = isStaff ? await api("/api/chat/staff") : null;
  view().innerHTML = `
    <h2>Chat</h2>
    <div class="chat-wrap">
      <div class="chat-side">
        ${isStaff && staff && staff.staff.length ? `
          <select id="dm-pick"><option value="">+ direct message…</option>
            ${staff.staff.map((u) => `<option value="${u.id}">${esc(u.name)}
              ${staff.online.includes(u.id) ? " (online)" : ""}</option>`).join("")}
          </select>` : ""}
        ${data.convs.map((c) => {
          const unread = c.last && c.last.user_id !== data.me &&
            c.last.id > (lr[c.id] || 0);
          return `
          <div class="conv ${c.id === S.chatConv ? "on" : ""}" data-conv="${c.id}">
            ${unread ? '<span class="unread-dot"></span>' : ""}
            <b>${esc(c.name || c.kind)}</b>
            ${c.call_target && data.online.includes(c.call_target)
              ? '<span class="dot-online" title="online"></span>' : ""}
            ${c.last ? `<div class="dim" style="font-size:11px">
              ${esc(c.last.name)}: ${esc(c.last.body.slice(0, 26))}</div>` : ""}
          </div>`;
        }).join("")}
      </div>
      <div class="chat-main">
        ${conv ? `
          <div class="chat-head">
            <b>${esc(conv.name || conv.kind)}</b>
            ${conv.call_target ? `
              <span style="float:right">
                <button class="btn alt" id="call-audio" title="voice call">${opsIcon("phone","btn-ic")}</button>
                <button class="btn alt" id="call-video" title="video call">${opsIcon("video","btn-ic")}</button>
              </span>` : ""}
          </div>
          <div id="chat-msgs"></div>
          <form id="chat-form" class="inline" style="margin-top:8px">
            <input id="chat-input" style="flex:1" autocomplete="off"
              placeholder="message…">
            <button class="btn">Send</button>
          </form>`
        : '<div class="dim">no conversations yet</div>'}
      </div>
    </div>`;
  document.querySelectorAll("[data-conv]").forEach((el) => {
    el.onclick = () => { S.chatConv = +el.dataset.conv; render(); };
  });
  if ($("#dm-pick")) $("#dm-pick").onchange = async () => {
    const uid = +$("#dm-pick").value;
    if (!uid) return;
    const r = await api("/api/chat/dm", { body: { user_id: uid } });
    S.chatConv = r.conv_id;
    render();
  };
  if (!conv) return;
  const history = await api(`/api/chat/convs/${conv.id}/messages`);
  history.forEach(chatAppend);
  if (history.length) setLastRead(conv.id, history[history.length - 1].id);
  $("#chat-form").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("#chat-input").value.trim();
    if (!text) return;
    $("#chat-input").value = "";
    if (!wsSend({ type: "msg", conv_id: conv.id, body: text })) {
      const m = await api(`/api/chat/convs/${conv.id}/messages`,
        { body: { body: text } });
      chatAppend(m);
    }
  };
  if ($("#call-audio")) $("#call-audio").onclick = () =>
    startCall(conv.call_target, "audio");
  if ($("#call-video")) $("#call-video").onclick = () =>
    startCall(conv.call_target, "video");
}

// ---------- notifications ----------

async function fetchNotifs() {
  if (!S.user) return;
  try {
    const d = await api("/api/notifications");
    const prevTop = S.notifs && S.notifs.items[0] ? S.notifs.items[0].id : 0;
    S.notifs = d;
    const fresh = d.items.filter((i) => i.id > prevTop && !i.is_read);
    if (prevTop && fresh.length) {
      toast(fresh[0].title);
      if (fresh.some((i) => i.kind === "achievement")) confetti();
      if ("Notification" in window && Notification.permission === "granted") {
        fresh.slice(0, 3).forEach((i) =>
          new Notification(S.meta.brand || "Business Control",
            { body: i.title }));
      }
    }
    const bell = $("#bell");
    if (bell) bell.innerHTML = opsIcon("bell","bell-ic") + (d.unread
      ? `<span class="bell-n">${d.unread}</span>` : "");
  } catch {}
}

function b64ToU8(s) {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

async function enablePush() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return toast("push unsupported here — on iPhone, install the app to"
        + " your Home Screen first");
    }
    if ((await Notification.requestPermission()) !== "granted") {
      return toast("notifications not allowed");
    }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/pubkey");
    const sub = await reg.pushManager.subscribe(
      { userVisibleOnly: true, applicationServerKey: b64ToU8(key) });
    await api("/api/push/subscribe", { body: { subscription: sub.toJSON() } });
    toast("push enabled on this device");
  } catch (e) { toast("push failed: " + e.message); }
}

function startNotifPoll() {
  clearInterval(S._notifTimer);
  fetchNotifs();
  S._notifTimer = setInterval(fetchNotifs, 45000);
}

async function toggleNotifPanel() {
  const old = $("#notif-panel");
  if (old) { old.remove(); return; }
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
  const panel = document.createElement("div");
  panel.id = "notif-panel";
  const items = (S.notifs && S.notifs.items) || [];
  panel.innerHTML = `<h3 style="margin:4px 0 8px">Notifications
      <button class="btn alt" id="push-btn" style="float:right;padding:3px 9px"
        title="get these on this device even with the app closed">
        Enable push</button></h3>` +
    (items.length ? items.map((i) => `
      <div class="notif ${i.is_read ? "" : "unread"}">
        <div>${esc(i.title)}</div>
        ${i.body ? `<div class="dim" style="font-size:12px">${esc(i.body)}</div>` : ""}
        <div class="dim" style="font-size:11px">${timeAgo(i.created_at)}</div>
      </div>`).join("")
    : '<div class="dim">nothing yet</div>');
  document.body.appendChild(panel);
  $("#push-btn").onclick = enablePush;
  if (S.notifs && S.notifs.unread) {
    await api("/api/notifications/read", { body: {} }).catch(() => {});
    S.notifs.items.forEach((i) => { i.is_read = 1; });
    S.notifs.unread = 0;
    const bell = $("#bell");
    if (bell) bell.innerHTML = opsIcon("bell","bell-ic");
  }
}

// ---------- shared helpers: time, video, route summary ----------

const fmtMin = (m) => m >= 60
  ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${Math.round(m)}m`;

function videoEmbed(url) {
  if (!url) return "";
  const yt = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{6,})/);
  if (yt) return `<iframe width="100%" height="240"
    style="border:0;border-radius:8px"
    src="https://www.youtube.com/embed/${yt[1]}" allowfullscreen
    loading="lazy"></iframe>`;
  if (/\.(mp4|webm|mov|m4v)(\?|$)/i.test(url))
    return `<video controls playsinline
      style="width:100%;border-radius:8px" src="${esc(url)}"></video>`;
  return `<a href="${esc(url)}" target="_blank" rel="noopener">▶ video feed</a>`;
}

function routeSummary(r) {
  return `${routeMap(r.stops)}
    <div class="dim" style="margin:4px 0">${r.total_km} km ·
      about ${fmtMin(r.total_min)} including stops</div>
    <table><thead><tr><th>#</th><th>store</th><th>city</th><th>leg</th>
      <th>drive</th><th>ETA</th><th>done</th></tr></thead><tbody>
    ${r.stops.map((s) => `<tr><td>${s.seq + 1}</td><td>${esc(s.name)}</td>
      <td class="dim">${esc(s.city)}</td><td>${s.leg_km} km</td>
      <td>${fmtMin(s.drive_min)}</td><td>+${fmtMin(s.eta_min)}</td>
      <td>${s.delivered ? "✓" : ""}</td></tr>`).join("")}
    </tbody></table>`;
}

// ---------- camera QR scanner ----------

async function renderScan() {
  view().innerHTML = `
    <h2>Scan</h2>
    <div class="card" style="max-width:520px">
      <video id="scan-video" autoplay playsinline muted
        style="width:100%;border-radius:8px;background:#000"></video>
      <div id="scan-status" class="dim" style="margin:8px 0">starting camera…</div>
      <form class="inline" id="scan-manual">
        <input id="scan-code" style="flex:1"
          placeholder="or type a code / link (e.g. bc:truck:1)">
        <button class="btn alt">Go</button>
      </form>
      <div class="dim" style="font-size:12px;margin-top:6px">Drivers: scan the
        QR on your truck to check in and get today's route. Any app QR
        (sign-in, promo) works here too. On phones the camera needs the HTTPS
        start command.</div>
    </div>
    <div id="scan-result"></div>`;
  $("#scan-manual").onsubmit = (e) => {
    e.preventDefault();
    handleScan($("#scan-code").value.trim());
  };
  const status = $("#scan-status");
  if (!("BarcodeDetector" in window)) {
    status.textContent = "No built-in QR detector in this browser (e.g. iPhone "
      + "Safari) — use the box below, or open in Chrome.";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia(
      { video: { facingMode: "environment" } });
    const video = $("#scan-video");
    video.srcObject = stream;
    const det = new BarcodeDetector({ formats: ["qr_code"] });
    status.textContent = "point the camera at a QR code";
    let last = "";
    const loop = async () => {
      if (S.tab !== "scan" || !video.isConnected) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      try {
        const codes = await det.detect(video);
        if (codes.length && codes[0].rawValue !== last) {
          last = codes[0].rawValue;
          status.textContent = "scanned!";
          handleScan(last);
        }
      } catch {}
      setTimeout(loop, 400);
    };
    video.onloadedmetadata = loop;
  } catch (e) {
    status.textContent = `camera unavailable (${e.message}) — manual entry `
      + "below still works.";
  }
}

async function handleScan(text) {
  if (!text) return;
  const out = $("#scan-result");
  const truck = text.match(/^bc:truck:(\d+)$/);
  if (truck) {
    if (!S.user) { out.innerHTML =
      '<div class="card">Sign in first (ask an admin for your sign-in QR), '
      + "then scan the truck again.</div>"; return; }
    try {
      const r = await api(`/api/trucks/${truck[1]}/checkin`, { body: {} });
      out.innerHTML = `<div class="card">
        <b>Checked in to ${esc(r.truck.name)}</b> — drive safe, ${esc(r.driver)}.
        ${r.route ? `<h3>Your route: ${esc(r.route.name)}</h3>${routeSummary(r.route)}`
          : '<div class="dim">No route assigned to this truck yet — ask dispatch.</div>'}
        </div>`;
    } catch (e) {
      out.innerHTML = `<div class="card">Error: ${esc(e.message)}</div>`;
    }
    return;
  }
  try {
    const url = new URL(text);
    if (url.origin === location.origin) { location.href = url.href; return; }
    out.innerHTML = `<div class="card">External link:
      <a href="${esc(url.href)}" target="_blank" rel="noopener">${esc(url.href)}</a></div>`;
  } catch {
    out.innerHTML = `<div class="card">Scanned: ${esc(text)}</div>`;
  }
}

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
            ${p.active ? "turn off" : "turn on"}</button></span>` : ""}
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
  const lats = pts.map((s) => s.lat), lngs = pts.map((s) => s.lng);
  const pad = 1.5;
  const minLa = Math.min(...lats) - pad, maxLa = Math.max(...lats) + pad;
  const minLo = Math.min(...lngs) - pad, maxLo = Math.max(...lngs) + pad;
  const W = 860, H = 380;
  const x = (lo) => ((lo - minLo) / (maxLo - minLo || 1)) * (W - 40) + 20;
  const y = (la) => H - (((la - minLa) / (maxLa - minLa || 1)) * (H - 40) + 20);
  return `<svg class="map" viewBox="0 0 ${W} ${H}">
    ${pts.map((s) => `
      <circle cx="${x(s.lng).toFixed(1)}" cy="${y(s.lat).toFixed(1)}"
        r="${s.kind === "distributor_dc" ? 11 : 7}"
        fill="${REGION_COLORS[s.region] || "#8b98a5"}" fill-opacity="0.85"
        stroke="#0c1013"><title>${esc(s.name)} — ${esc(s.city)}</title></circle>`).join("")}
    ${Object.entries(REGION_COLORS).map(([r, c], i) => `
      <circle cx="${30 + i * 150}" cy="${H - 14}" r="6" fill="${c}"/>
      <text x="${42 + i * 150}" y="${H - 10}" font-size="12"
        fill="#8b98a5">${r}</text>`).join("")}
  </svg>`;
}

function pnlTable(p) {
  const row = (l, v, neg) => `<tr><td>${l}</td>
    <td style="text-align:right">${neg ? "−" : ""}${money(v)}</td></tr>`;
  return `<table>
    ${row("Revenue", p.revenue_cents)}
    ${row(`COGS (${p.assumptions.cogs_bps / 100}%)`, p.cogs_cents, 1)}
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
  <div class="dim" style="font-size:12px;margin-top:6px">COGS %, wage, and
    per-km cost are assumptions — edit them in data/config.json.</div>`;
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
        <div style="font-size:26px">${a.icon}</div>
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

// ---------- inventory ----------

async function renderInventory() {
  const isStaff = S.user && (S.user.is_admin ||
    ["employee", "owner"].includes(S.user.role));
  const [inv, stores, picks] = await Promise.all([
    api("/api/inventory"), api("/api/stores"),
    isStaff ? api("/api/warehouse/picklist").catch(() => []) : []]);
  const byStore = {};
  inv.forEach((i) => {
    (byStore[i.store_id] = byStore[i.store_id] || { name: i.store_name,
      region: i.region, rows: [] }).rows.push(i);
  });
  const lows = inv.filter((i) => i.low);
  view().innerHTML = `
    <h2>Inventory — all stores</h2>
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
        <th>par</th></tr></thead><tbody>
        ${d.rows.map((r) => `<tr><td>${esc(r.product_name)}</td>
          <td class="${r.low ? "low" : ""}">${r.qty}</td>
          <td class="dim">${r.par}</td></tr>`).join("")}
        </tbody></table></div>`;
    }).join("")}`;
}

// ---------- routes ----------

function routeMap(stops) {
  if (!stops.length) return "";
  const lats = stops.map((s) => s.lat), lngs = stops.map((s) => s.lng);
  const pad = 0.6;
  const minLa = Math.min(...lats) - pad, maxLa = Math.max(...lats) + pad;
  const minLo = Math.min(...lngs) - pad, maxLo = Math.max(...lngs) + pad;
  const W = 640, H = 300;
  const x = (lo) => ((lo - minLo) / (maxLo - minLo || 1)) * (W - 40) + 20;
  const y = (la) => H - (((la - minLa) / (maxLa - minLa || 1)) * (H - 40) + 20);
  const pts = stops.map((s) => `${x(s.lng).toFixed(1)},${y(s.lat).toFixed(1)}`);
  return `<svg class="map" viewBox="0 0 ${W} ${H}">
    <polyline points="${pts.join(" ")}" fill="none" stroke="#4a9eda"
      stroke-width="2" stroke-dasharray="5 4"/>
    ${stops.map((s, i) => `
      <circle cx="${x(s.lng)}" cy="${y(s.lat)}" r="9"
        fill="${s.delivered ? "#35b26b" : i === 0 ? "#d4a017" : "#232b34"}"
        stroke="#8b98a5"/>
      <text x="${x(s.lng)}" y="${y(s.lat) + 4}" text-anchor="middle"
        font-size="10" fill="#e6edf3">${i + 1}</text>
      <text x="${x(s.lng)}" y="${y(s.lat) - 13}" text-anchor="middle"
        font-size="10" fill="#8b98a5">${esc(s.city || s.name)}</text>`).join("")}
  </svg>`;
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
          <th>drive</th><th>ETA</th><th>delivered</th></tr></thead><tbody>
        ${r.stops.map((s) => `<tr><td>${s.seq + 1}</td><td>${esc(s.name)}</td>
          <td class="dim">${esc(s.city)}</td><td>${s.leg_km} km</td>
          <td>${fmtMin(s.drive_min)}</td><td>+${fmtMin(s.eta_min)}</td>
          <td><input type="checkbox" data-stop="${r.id}:${s.seq}"
            ${s.delivered ? "checked" : ""}></td></tr>`).join("")}
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
  const [regions, funnel, engagement, pnl] = await Promise.all([
    api("/api/analytics/regions"), api("/api/analytics/funnel"),
    api("/api/analytics/engagement"), api("/api/analytics/pnl")]);
  const maxV = Math.max(...funnel.steps.map((s) => s.visitors), 1);
  const maxD = Math.max(...engagement.daily.map((d) => d.total), 1);
  view().innerHTML = `
    <h2>Analytics — last 30 days</h2>
    ${engagement.alerts.length ? `<div class="card">
      ${engagement.alerts.map((a) => `<div><span class="pill bad">engagement
        falling off</span> <b>${esc(a.scope)}</b>: ${a.last_7} events this week
        vs ${a.prior_7} last week</div>`).join("")}</div>` : ""}
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
        ${s.drop_rate !== undefined && s.drop_rate > 0
          ? `<span class="dim">−${(s.drop_rate * 100).toFixed(0)}%</span>` : ""}
      </div>`).join("")}
      ${funnel.worst_dropoff ? `<div style="margin-top:8px">Biggest drop-off:
        <b>${esc(funnel.worst_dropoff.from)} → ${esc(funnel.worst_dropoff.to)}</b>
        loses ${(funnel.worst_dropoff.drop_rate * 100).toFixed(0)}% —
        focus fixes here.</div>` : ""}
    </div>
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
}

// ---------- admin ----------

const ROLES = ["customer", "distributor", "influencer", "employee", "owner"];

async function renderAdmin() {
  const [products, stores, employees, users, emailCfg, emailLog, cyclesList] =
    await Promise.all([
      api("/api/products"), api("/api/stores"), api("/api/admin/employees"),
      api("/api/admin/users"), api("/api/admin/email/config"),
      api("/api/admin/email/log"), api("/api/cycles")]);
  view().innerHTML = `
    <h2>Admin</h2>
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
    <details class="sect"><summary>Email marketing</summary><div class="inner">
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
      <div class="dim" style="margin-top:6px">No SMTP host = dry mode: the
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
    <details class="sect"><summary>Set inventory</summary><div class="inner">
    <form class="inline" id="inv-form">
      <select id="iv-store">${stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
      <select id="iv-prod">${products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <input id="iv-qty" type="number" placeholder="qty" required style="width:90px">
      <input id="iv-par" type="number" placeholder="par" value="24" style="width:90px">
      <button class="btn">Set</button>
    </form></div></details>`;
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
  };
}

// ---------- boot ----------

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/ops/sw.js").catch(() => {});
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
  render();
}
boot();

// ---------- documents & signatures ----------
let DOCS = null;

async function renderDocs() {
  const q = S.docQ || "";
  const kind = S.docKind || "";
  DOCS = await api("/api/store/admin/documents?party_kind="
    + encodeURIComponent(kind) + "&q=" + encodeURIComponent(q));

  const expiring = DOCS.expiring.filter((d) => !d.expired);
  const expired = DOCS.expiring.filter((d) => d.expired);
  const alert = (expired.length || expiring.length) ? `
    <div class="card alert">
      <b>${expired.length ? opsIcon("shield2", "inline-ic") + " " +
        expired.length + " expired" : ""}${
        expired.length && expiring.length ? " · " : ""}${
        expiring.length ? expiring.length + " expiring within 45 days" : ""}</b>
      <div class="doc-alerts">${DOCS.expiring.map((d) => `
        <span class="pill ${d.expired ? "bad" : "warn"}">${esc(d.title)} —
          ${d.expired ? "expired" : "expires"} ${fmtDate(d.expires)}</span>`).join("")}
      </div>
    </div>` : "";

  const kinds = Object.entries(DOCS.party_kinds).map(([k, v]) =>
    `<button class="chip ${kind === k ? "on" : ""}" data-kind="${k}">${v}</button>`).join("");

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Documents</h2>
        <p class="dim">Contracts, policies and certificates for customers,
          vendors, partners and staff — with signatures and an audit trail.</p></div>
      <button class="btn" id="doc-new">${opsIcon("file","btn-ic")} New document</button>
    </div>
    ${alert}
    <div class="filters">
      <input id="doc-q" placeholder="Search titles, parties, notes" value="${esc(q)}">
      <div class="chips"><button class="chip ${kind ? "" : "on"}" data-kind="">All</button>${kinds}</div>
    </div>
    <div id="doc-list">${DOCS.documents.map(docRow).join("")
      || '<div class="card empty"><span class="e-ic">' + opsIcon("file")
       + '</span><b>Nothing filed yet</b><p class="dim">Upload a contract or write one here, then send it for signature.</p></div>'}</div>`;

  $("#doc-new").onclick = docForm;
  let t;
  $("#doc-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.docQ = e.target.value; renderDocs(); }, 250); };
  view().querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => {
    S.docKind = b.dataset.kind; renderDocs(); });
  wireDocRows();
}

function docRow(d) {
  const sigs = d.signatures || [];
  const state = d.fully_signed ? '<span class="pill ok">signed</span>'
    : d.awaiting ? `<span class="pill warn">${d.awaiting} awaiting</span>`
    : "";
  const exp = d.expired ? '<span class="pill bad">expired</span>'
    : d.expiring_soon ? `<span class="pill warn">expires ${fmtDate(d.expires)}</span>`
    : d.expires ? `<span class="dim">expires ${fmtDate(d.expires)}</span>` : "";
  return `<div class="doc-card" data-doc="${d.id}">
    <div class="doc-top">
      <span class="doc-ic">${opsIcon("file")}</span>
      <div class="doc-main">
        <b>${esc(d.title)}</b>
        <span class="dim">${esc(d.category_label)}${
          d.party_name ? " · " + esc(d.party_name) : ""} ·
          <span class="tag">${esc(d.party_label)}</span></span>
      </div>
      ${state} ${exp}
      ${d.has_file ? `<a class="btn alt sm" href="/api/store/admin/documents/${d.id}/file"
        title="download">download</a>` : ""}
      <button class="btn alt sm" data-sign="${d.id}">${opsIcon("pen","btn-ic")} Sign</button>
    </div>
    ${sigs.length ? `<div class="sig-rows">${sigs.map((s) => `
      <div class="sig-row sig-${s.status}">
        <b>${esc(s.signer_name)}</b>
        <span class="dim">${esc(s.signer_email)} · ${esc(s.role)}</span>
        <span class="pill ${s.status === "signed" ? "ok"
          : s.status === "declined" ? "bad" : "warn"}">${s.status}</span>
        ${s.status === "signed"
          ? `<span class="dim">${fmtDate(s.signed_at)}</span>`
          : `<button class="btn alt sm" data-void="${s.id}">void</button>`}
      </div>`).join("")}</div>` : ""}
  </div>`;
}

function wireDocRows() {
  view().querySelectorAll("[data-sign]").forEach((b) => b.onclick = () =>
    signForm(+b.dataset.sign));
  view().querySelectorAll("[data-void]").forEach((b) => b.onclick = async () => {
    if (!confirm("Void this signature request?")) return;
    try { await api(`/api/store/admin/signatures/${b.dataset.void}/void`,
      { method: "POST" }); renderDocs(); }
    catch (e) { toast(e.message); }
  });
}

function docForm() {
  const cats = Object.entries(DOCS.categories).map(([k, v]) =>
    `<option value="${k}">${v}</option>`).join("");
  const kinds = Object.entries(DOCS.party_kinds).map(([k, v]) =>
    `<option value="${k}">${v}</option>`).join("");
  modal(`<h3>New document</h3>
    <label>Title</label><input id="nd-title" placeholder="Supply agreement — Hudson DC">
    <div class="row2">
      <div><label>Category</label><select id="nd-cat">${cats}</select></div>
      <div><label>Concerns</label><select id="nd-kind">${kinds}</select></div>
    </div>
    <div class="row2">
      <div><label>Party name</label><input id="nd-party"></div>
      <div><label>Party email</label><input id="nd-email" type="email"></div>
    </div>
    <div class="row2">
      <div><label>Effective</label><input id="nd-eff" type="date"></div>
      <div><label>Expires <span class="dim">(optional)</span></label>
        <input id="nd-exp" type="date"></div>
    </div>
    <label>File <span class="dim">(PDF, image or Office — or write the body below)</span></label>
    <input id="nd-file" type="file">
    <label>Or write the document</label>
    <textarea id="nd-body" rows="5" placeholder="Paste or write the agreement text. This is what a signer will see."></textarea>
    <label>Internal notes</label><input id="nd-notes">
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="nd-save">Save</button>
    </div>`);
  $("#nd-save").onclick = async () => {
    const title = $("#nd-title").value.trim();
    if (!title) return toast("a document needs a title");
    const d = (v) => v ? new Date(v + "T12:00").getTime() / 1000 : 0;
    try {
      const out = await api("/api/store/admin/documents", { body: {
        title, category: $("#nd-cat").value, party_kind: $("#nd-kind").value,
        party_name: $("#nd-party").value.trim(),
        party_email: $("#nd-email").value.trim(),
        body: $("#nd-body").value, notes: $("#nd-notes").value.trim(),
        effective: d($("#nd-eff").value), expires: d($("#nd-exp").value) } });
      const f = $("#nd-file").files[0];
      if (f) {
        const fd = new FormData(); fd.append("file", f);
        const r = await fetch(`/api/store/admin/documents/${out.id}/file`, {
          method: "POST", headers: { Authorization: "Bearer " + S.user.token },
          body: fd });
        if (!r.ok) toast("saved, but the file upload failed: "
          + ((await r.json()).detail || r.status));
      }
      closeModal(); renderDocs();
    } catch (e) { toast(e.message); }
  };
}

function signForm(did) {
  const d = DOCS.documents.find((x) => x.id === did);
  modal(`<h3>Request a signature</h3>
    <p class="dim">${esc(d.title)}</p>
    <div class="row2">
      <div><label>Signer name</label>
        <input id="sr-name" value="${esc(d.party_name || "")}"></div>
      <div><label>Signer email</label>
        <input id="sr-email" type="email" value="${esc(d.party_email || "")}"></div>
    </div>
    <label>Role</label>
    <select id="sr-role"><option value="signer">Signer</option>
      <option value="approver">Approver</option>
      <option value="witness">Witness</option></select>
    <label>Message <span class="dim">(optional)</span></label>
    <textarea id="sr-msg" rows="2"></textarea>
    <p class="dim" style="font-size:12px;margin-top:10px">They'll get a unique
      link. Signing records their name, time, IP and a fingerprint of the
      document — a simple electronic signature valid under ESIGN and eIDAS.</p>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="sr-send">Send request</button>
    </div>`);
  $("#sr-send").onclick = async () => {
    try {
      const out = await api(`/api/store/admin/documents/${did}/request-signature`,
        { body: { signer_name: $("#sr-name").value.trim(),
          signer_email: $("#sr-email").value.trim(),
          role: $("#sr-role").value, message: $("#sr-msg").value } });
      closeModal();
      toast("Signing link sent");
      prompt("Signing link (also emailed):", out.link);
      renderDocs();
    } catch (e) { toast(e.message); }
  };
}
