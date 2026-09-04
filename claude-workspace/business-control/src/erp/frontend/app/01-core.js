/* Business Control — single-page PWA frontend. */
"use strict";

/* Arriving as somebody: the Platform tab's "Act as admin" opens this app
   with ?actas=<token> — a fresh admin token minted in THIS tenant's own
   user directory. Trade it for the account, drop it from the URL (tokens
   do not belong in history), and reload signed in. */
(() => {
  const q = new URLSearchParams(location.search);
  const t = q.get("actas");
  if (!t) return;
  fetch("/api/me", { headers: { Authorization: "Bearer " + t } })
    .then((r) => r.ok ? r.json() : Promise.reject())
    .then((me) => {
      localStorage.setItem("bc_user", JSON.stringify({ ...me, token: t }));
      location.replace(location.pathname + location.hash);
    })
    .catch(() => location.replace(location.pathname + location.hash));
})();

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

/* ---------- routes ----------
   The unique pages get real URLs: #/orders, #/clients, #/clients/3 — enough
   to bookmark, share, and use the back button; the hash is read on load and
   written on every render, so the address bar and the app can't disagree. */
function applyRoute() {
  // The second segment is usually a row id, but not always: a kiosk is
  // named by the token it was minted with, and a route that only accepts
  // digits cannot link to one at all.
  const m = location.hash.match(/^#\/([\w-]+)(?:\/([\w-]+))?$/);
  if (!m) return false;
  const num = m[2] && /^\d+$/.test(m[2]);
  S.tab = m[1];
  S.deepKey = (m[2] && !num) ? m[2] : null;
  S.engId = (m[1] === "clients" && num) ? +m[2] : null;
  // Deep views beyond clients: #/learning/5 opens the course, and
  // #/customers/12 opens the card — consumed once by that tab's
  // renderer, so a later click on the tab lands on its list.
  S.deepId = (m[1] !== "clients" && num) ? +m[2] : null;
  return true;
}
function syncRoute() {
  const want = (S.tab === "clients" && S.engId)
    ? `#/clients/${S.engId}`
    : (S.tab === "kiosks" && S.deepKey) ? `#/kiosks/${S.deepKey}`
      : `#/${S.tab || "shop"}`;
  if (location.hash !== want) history.pushState(null, "", want);
}
addEventListener("hashchange", () => { if (applyRoute()) render(); });
addEventListener("popstate", () => { if (applyRoute()) render(); });
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
    if (r.status === 401 && S.user) {
      // A session can be ended from elsewhere — an admin rotating tokens,
      // an account deactivated. Dumping to the login screen with no word
      // reads as the app breaking; one line of truth reads as what it is.
      toast("Signed out — this session was ended elsewhere. Sign in "
        + "again.");
      logout();
    }
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
  clearTimeout(S._wsRetry);          // a pending reconnect outlives the session
  clearInterval(S._dcTimer);
  const panel = $("#notif-panel");
  if (panel) panel.remove();
  render();
}


// ---------- small shared helpers ----------
const fmtDate = (t) => t ? new Date(t * 1000).toLocaleDateString(undefined,
  { day: "numeric", month: "short", year: "numeric" }) : "—";
// "3h ago" — for the freshness chips, where a date reads as older than
// it is and an exact time is more digits than the question deserves.
const fmtAgo = (t) => {
  if (!t) return "—";
  const m = Math.max(0, (Date.now() / 1000 - t) / 60);
  return m < 60 ? `${Math.round(m)}m ago`
    : m < 60 * 36 ? `${Math.round(m / 60)}h ago`
    : `${Math.round(m / 1440)}d ago`;
};

/* A modal. The ops app previously did every form inline in a view, which is
   fine for a settings page and poor for anything you open from a list. */
/* Downloads have to go through fetch rather than a plain link: auth here is
   a bearer token in localStorage, and an <a href> sends no headers, so the
   server would answer 401. The file is therefore held in memory once before
   being handed to the browser — fine at this scale, and the alternative is a
   second, signed URL scheme existing only to make links work. */
async function download(path) {
  try {
    const r = await fetch(path, { headers: S.user
      ? { Authorization: "Bearer " + S.user.token } : {} });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      return toast(e.detail || `Download failed (${r.status})`);
    }
    const name = (r.headers.get("content-disposition") || "")
      .match(/filename="([^"]+)"/);
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = name ? name[1] : "export";
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoked on the next tick; too soon and the download never starts.
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast("Downloaded");
  } catch (e) { toast(e.message); }
}

function modal(html, cls) {
  closeModal();
  const o = document.createElement("div");
  o.id = "ops-modal";
  o.innerHTML = `<div class="ops-modal-card ${cls || ""}">${html}</div>`;
  o.onclick = (e) => { if (e.target === o) closeModal(); };
  document.body.appendChild(o);
  o.querySelectorAll("[data-close]").forEach((b) => b.onclick = closeModal);
  const first = o.querySelector("input,select,textarea");
  if (first) setTimeout(() => first.focus(), 30);
  document.addEventListener("keydown", modalEsc);
}
/* The card itself, for a dialog that redraws in place: stepping between
   the days of a week should not shut and reopen the thing you are in. */
function modalBody() {
  const o = $("#ops-modal");
  return o && o.querySelector(".ops-modal-card");
}
function closeModal() {
  const o = $("#ops-modal");
  if (o) o.remove();
  document.removeEventListener("keydown", modalEsc);
}
function modalEsc(e) { if (e.key === "Escape") closeModal(); }


/* ---------- pan & zoom map ----------
   One component for HQ and for routes. Coordinates are real lat/lng projected
   through a single function, so pins and the drawn coastline can't disagree —
   the same lesson as the storefront locator, where a hand-drawn outline put
   stores in the ocean.

   No tiles: nothing is fetched from a map server, which keeps the ops app
   working offline in a warehouse and stops a third party learning the
   company's delivery pattern. */
/* A world map in equirectangular projection, opened at the US.

   Coastlines are a coarse polygon set — enough to place a pin in the right
   country at continental zoom, which is what an ops map is for. Everything
   (outline and pins) goes through one projection, so they can't disagree.
   Still no tiles: nothing is fetched, so this works in a warehouse basement
   and no third party learns the delivery pattern. */
const MAP_W = 1000, MAP_H = 500;          // 360° x 180°, 2:1
const mapProject = (lat, lng) => [
  (lng + 180) / 360 * MAP_W,
  (90 - lat) / 180 * MAP_H,
];

// [lat, lng] rings. Coarse on purpose — this is an ops map, not an atlas.
const WORLD = [
  /* Each ring is a single closed loop that never crosses itself. A ring that
     doubles back — one loop trying to cover both Americas, say — fills as a
     wedge across the ocean under the nonzero rule, which is how you get a
     "map" that puts land where the water is. */
  // North America: Alaska → arctic → east coast → Gulf → Central America,
  // then back up the Pacific side.
  [[71,-156],[70,-141],[69,-131],[68,-110],[74,-95],[73,-80],[63,-78],[60,-65],
   [55,-60],[52,-56],[47,-53],[45,-60],[41,-70],[38,-75],[35,-76],[31,-81],
   [25,-80],[30,-84],[29,-95],[26,-97],[21,-97],[18,-95],[19,-91],[21,-87],
   [18,-88],[16,-88],[15,-83],[11,-83],[9,-82],[8,-77],[8,-83],[11,-86],
   [13,-88],[16,-95],[19,-104],[23,-106],[23,-110],[28,-114],[32,-117],
   [34,-120],[37,-122],[42,-124],[46,-124],[49,-125],[52,-131],[57,-133],
   [60,-140],[59,-145],[57,-153],[55,-162],[58,-158],[60,-165],[65,-166],
   [71,-156]],
  // South America
  [[11,-72],[10,-64],[8,-60],[5,-52],[0,-50],[-5,-35],[-13,-38],[-23,-43],
   [-33,-53],[-38,-58],[-42,-63],[-48,-66],[-52,-69],[-55,-67],[-52,-73],
   [-46,-75],[-42,-74],[-33,-72],[-23,-70],[-18,-70],[-12,-77],[-5,-81],
   [0,-80],[3,-77],[8,-77],[11,-74],[11,-72]],
  // Europe + Africa + Asia (one coarse landmass ring)
  [[71,25],[70,30],[66,42],[68,55],[73,70],[73,80],[76,100],[73,113],[71,130],
   [70,160],[66,170],[62,179],[59,163],[54,142],[46,143],[43,135],[39,127],
   [35,126],[31,122],[23,117],[22,110],[10,107],[9,100],[1,104],[7,98],
   [16,95],[21,90],[22,88],[16,81],[8,77],[15,74],[23,68],[25,57],[22,59],
   [26,50],[30,48],[24,38],[13,43],[11,51],[2,46],[-6,39],[-18,36],[-26,33],
   [-34,26],[-34,18],[-23,14],[-12,13],[-6,12],[4,9],[6,-3],[5,-8],[10,-16],
   [15,-17],[21,-17],[28,-13],[33,-8],[36,-6],[37,10],[33,11],[31,20],[31,32],
   [36,36],[36,30],[41,29],[41,41],[45,38],[46,31],[45,29],[44,23],[41,20],
   [43,15],[45,13],[44,12],[40,18],[38,16],[41,13],[44,10],[43,7],[43,3],
   [39,0],[37,-6],[43,-9],[44,-2],[47,-2],[49,0],[51,2],[53,5],[55,9],
   [57,11],[59,11],[63,8],[68,15],[71,25]],
  // British Isles
  [[58,-5],[57,-2],[54,0],[51,1],[50,-4],[52,-5],[55,-6],[58,-7],[58,-5]],
  // Australia
  [[-11,131],[-12,137],[-15,141],[-19,147],[-28,153],[-37,150],[-38,145],
   [-35,138],[-32,133],[-34,123],[-35,117],[-32,116],[-26,113],[-22,114],
   [-18,122],[-14,127],[-11,131]],
  // New Zealand
  [[-35,173],[-38,178],[-42,174],[-46,168],[-45,167],[-41,172],[-37,174],
   [-35,173]],
  // Japan
  [[45,142],[43,145],[41,141],[38,141],[35,140],[34,136],[35,133],[34,131],
   [37,137],[40,140],[43,141],[45,142]],
  // Madagascar
  [[-12,49],[-16,50],[-22,48],[-25,47],[-23,44],[-16,44],[-12,49]],
  // Greenland
  [[83,-32],[80,-20],[75,-20],[70,-22],[63,-42],[68,-53],[75,-58],[80,-60],
   [83,-45],[83,-32]],
];
/* National borders, as open lines rather than rings — a border is a
   separation, not a shape, and drawing it as a polygon would fill it.
   Densest where the business operates and coarser elsewhere: the job is to
   tell you which country a pin is in, not to settle a boundary dispute. */
const BORDERS = [
  // Canada / United States: the 49th parallel, the Lakes, then Maine
  [[49,-123],[49,-95],[48.5,-93],[48,-89.5],[46.5,-84.5],[43,-82.5],
   [42,-83],[42.3,-81],[43.3,-79],[44.5,-76.5],[45,-74.5],[45,-71.5],
   [47.3,-69],[46,-67.8],[45,-67]],
  // United States / Mexico: the border fence west, then the Rio Grande
  [[32.5,-117.1],[32.5,-114.7],[31.3,-111],[31.3,-108.2],[31.8,-106.5],
   [29.8,-102.3],[29.3,-100.9],[26.4,-99],[25.9,-97.1]],
  // Central America
  [[17.8,-91.4],[17.8,-89.1],[15.9,-89.2],[14.5,-92.2]],   // MX / GT-BZ
  [[15.9,-88.2],[14.9,-88.2],[13.8,-87.7],[13.2,-87.8]],   // HN / GT-SV
  [[15,-83.2],[14.1,-85.7],[13,-86.7],[12.9,-87.7]],       // HN / NI
  [[11,-83.7],[10.9,-85.6]],                               // NI / CR
  [[9.6,-82.6],[8.1,-82.9]],                               // CR / PA
  // South America
  [[12.2,-71.3],[9,-71],[7.1,-70.1],[1.4,-66.9],[0.7,-69.8]],   // CO / VE
  [[-4.2,-70],[-2,-70],[1.8,-67.2],[3.8,-63],[5.2,-60.7],
   [1.2,-56.5],[2.2,-52.6],[4.5,-51.6]],                        // BR north
  [[-9.4,-73],[-11,-68.8],[-16,-58.4],[-20,-58],[-22.1,-57.9],
   [-25.6,-54.6],[-27,-54.5],[-30,-57.6],[-33.7,-53.4]],        // BR south
  [[-18.3,-70.3],[-17.5,-69.5],[-22.9,-68.2],[-27,-68.8],
   [-35,-70.4],[-41,-71.9],[-46,-71.9],[-52,-72],[-52.4,-68.6]],// CL / AR
  [[-22.9,-62.8],[-22,-62.6],[-21.8,-60],[-22,-57.9]],          // PY / BO-AR
  // Europe (coarse — enough to separate the big markets)
  [[43.4,-1.8],[42.6,0.7],[42.5,3.2]],                     // ES / FR
  [[51.1,2.5],[50.8,4],[50.7,6.1],[49.5,6.4],[47.5,7.6]],  // FR / BE-DE
  [[47.5,7.6],[46.5,10.1],[46.6,12.4],[46.9,16],[48.6,17.2],
   [50.8,15],[51.1,12],[53.6,8.5]],                        // DE / south-east
  [[46.4,6.8],[45.9,7.6],[46.5,10.5],[46.6,13.6]],         // IT north
  [[55,14.5],[54.8,19],[54.4,23.5],[52.1,23.6],[50.3,24],
   [48.4,22.9],[47.9,18.8],[48.7,16.9]],                   // PL / east
  // Asia and Africa (coarsest — one line where a continent divides)
  [[42,80],[45,83],[47,85],[49,87],[50,106],[46,119],[42,131]],  // RU / CN-MN
  [[35,71],[35,77],[30,79],[28,84],[27.9,89],[27,92],[24,97],
   [21,99],[14,109]],                                            // CN south
  [[31,25],[22,25],[22,36]],                                     // EG / LY-SD
  [[19,-17],[21,-13],[27,-8.7],[27,-4.8],[22,0],[19,4],[19,12],
   [15,15],[12,22],[10,24],[4,30],[-1,30],[-1,34],[-4.7,39.2]],  // Sahel / east
  [[-17.8,11.7],[-17.8,25.2],[-22,29],[-26,31.5]],               // southern
];
const linePath = (pts) => pts.map(([la, ln], i) => {
  const [x, y] = mapProject(la, ln);
  return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
}).join(" ");
const BORDER_PATH = BORDERS.map(linePath).join(" ");
const WORLD_PATH = WORLD.map((ring) => linePath(ring) + " Z").join(" ");

// Opening view: the lower 48, so the map is useful the moment it appears.
const HOME_VIEW = { lat: [24, 50], lng: [-126, -66] };

let MAP_SEQ = 0;

/* opts: { pins:[{lat,lng,label,sub,color,size}], legs:[[from,to]], id }
   Returns markup; call wireMap(id) after inserting it. */
function panZoomMap(opts) {
  const id = opts.id || ("map" + (++MAP_SEQ));
  const pins = (opts.pins || []).filter((p) => p.lat && p.lng);
  const legs = (opts.legs || []).map(([a, b]) => {
    const [x1, y1] = mapProject(a.lat, a.lng), [x2, y2] = mapProject(b.lat, b.lng);
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
      x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" class="map-leg"/>`;
  }).join("");
  const dots = pins.map((p, i) => {
    const [x, y] = mapProject(p.lat, p.lng);
    /* The inner group carries the counter-scale. Zoom multiplies everything
       inside .map-vp, so without it a dot becomes a saucer at 6x — the pin
       has to keep its screen size while its position keeps the map's. */
    return `<g class="map-pin" transform="translate(${x.toFixed(1)},${y.toFixed(1)})">
      <g class="pin-s">
        <circle class="halo" r="${(p.size || 7) + 9}" fill="${p.color || "#8a6ff0"}"/>
        <circle class="dot" r="${p.size || 7}" fill="${p.color || "#8a6ff0"}"/>
        ${p.n != null ? `<text class="pin-n" y="4">${p.n}</text>` : ""}
      </g>
      <title>${esc(p.label || "")}${p.sub ? " — " + esc(p.sub) : ""}</title>
    </g>`;
  }).join("");
  return `<div class="map-wrap" id="${id}">
    <svg class="map" viewBox="0 0 ${MAP_W} ${MAP_H}">
      <g class="map-vp">
        <path class="map-land" d="${WORLD_PATH}"/>
        <path class="map-border" d="${BORDER_PATH}"/>
        ${legs}${dots}
      </g>
    </svg>
    <div class="map-ctl">
      <button class="btn alt sm" data-mz="in" title="zoom in">+</button>
      <button class="btn alt sm" data-mz="out" title="zoom out">−</button>
      <button class="btn alt sm" data-mz="fit" title="reset">reset</button>
    </div>
    <span class="map-hint">drag to pan · scroll to zoom</span>
  </div>`;
}

function wireMap(id) {
  const wrap = document.getElementById(id);
  if (!wrap) return;
  const vp = wrap.querySelector(".map-vp");
  const svg = wrap.querySelector("svg");
  let k = 1, tx = 0, ty = 0, dragging = false, sx = 0, sy = 0;

  /* Open on a region rather than the whole globe. Defaults to the US; if the
     pins sit outside it — an international account, a European route — frame
     those instead, because a map opening on the wrong continent is worse
     than one opening on none. */
  const homeView = () => {
    const pins = [...vp.querySelectorAll(".map-pin")].map((g) => {
      const t = g.getAttribute("transform").match(/-?[\d.]+/g);
      return [parseFloat(t[0]), parseFloat(t[1])];
    });
    let [x1, y1] = mapProject(HOME_VIEW.lat[1], HOME_VIEW.lng[0]);
    let [x2, y2] = mapProject(HOME_VIEW.lat[0], HOME_VIEW.lng[1]);
    if (pins.length) {
      const xs = pins.map((p) => p[0]), ys = pins.map((p) => p[1]);
      const outside = Math.min(...xs) < x1 - 4 || Math.max(...xs) > x2 + 4 ||
                      Math.min(...ys) < y1 - 4 || Math.max(...ys) > y2 + 4;
      if (outside) {
        const pad = 30;
        x1 = Math.min(...xs) - pad; x2 = Math.max(...xs) + pad;
        y1 = Math.min(...ys) - pad; y2 = Math.max(...ys) + pad;
      }
    }
    const w = Math.max(1, x2 - x1), h = Math.max(1, y2 - y1);
    k = Math.max(1, Math.min(12, Math.min(MAP_W / w, MAP_H / h)));
    tx = -(x1 + x2) / 2 * k + MAP_W / 2;
    ty = -(y1 + y2) / 2 * k + MAP_H / 2;
    clamp(); apply();
  };

  const apply = () => {
    vp.setAttribute("transform", `translate(${tx} ${ty}) scale(${k})`);
    // Counter-scale the pins so a dot stays a dot at every zoom level
    // instead of becoming a blob. Set as an attribute rather than a CSS
    // variable: scaling about the pin's own origin is unambiguous here,
    // where a CSS transform-origin on an SVG group is not.
    const inv = `scale(${(1 / k).toFixed(4)})`;
    vp.querySelectorAll(".pin-s").forEach((g) => g.setAttribute("transform", inv));
  };
  const clamp = () => {
    k = Math.max(1, Math.min(12, k));
    const span = MAP_W * (k - 1), spanY = MAP_H * (k - 1);
    tx = Math.max(-span, Math.min(0, tx));
    ty = Math.max(-spanY, Math.min(0, ty));
  };
  // Zoom about the cursor, so the thing under the pointer stays put.
  const zoomAt = (factor, px, py) => {
    const k0 = k;
    k = Math.max(1, Math.min(12, k * factor));
    tx = px - (px - tx) * (k / k0);
    ty = py - (py - ty) * (k / k0);
    clamp(); apply();
  };
  const svgPoint = (e) => {
    const r = svg.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width * MAP_W,
            (e.clientY - r.top) / r.height * MAP_H];
  };

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [px, py] = svgPoint(e);
    zoomAt(e.deltaY < 0 ? 1.18 : 1 / 1.18, px, py);
  }, { passive: false });

  /* Pointer events with capture, rather than mousedown on the SVG plus
     mousemove/mouseup on window.

     That older pairing leaked: every map render added two window listeners
     that were never removed, and each closed over the map's SVG — so a
     session that visited Stores or Routes a few dozen times ended up with
     hundreds of live handlers firing on every mouse movement, each pinning
     a whole detached map in memory. Nothing ever released them, because
     there was no teardown hook to release them from.

     Capture fixes the reason window was used in the first place: a drag has
     to keep tracking after the pointer leaves the element. With
     setPointerCapture the events keep coming to the SVG itself, so every
     listener now lives and dies with the node it is attached to, and the
     leak cannot come back by inspection. It also covers touch, which is why
     the separate touchstart/touchmove/touchend handling is gone. */
  const pointers = new Map();       // active pointers, for pinch
  let pinchDist = 0;

  svg.addEventListener("pointerdown", (e) => {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    svg.setPointerCapture(e.pointerId);
    if (pointers.size === 1) {
      dragging = true; sx = e.clientX; sy = e.clientY;
      svg.classList.add("grab");
    } else if (pointers.size === 2) {
      dragging = false;
      const [p1, p2] = [...pointers.values()];
      pinchDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
    }
  });

  svg.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const r = svg.getBoundingClientRect();
    if (pointers.size === 2 && pinchDist) {
      const [p1, p2] = [...pointers.values()];
      const d = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      const cx = ((p1.x + p2.x) / 2 - r.left) / r.width * MAP_W;
      const cy = ((p1.y + p2.y) / 2 - r.top) / r.height * MAP_H;
      zoomAt(d / pinchDist, cx, cy);
      pinchDist = d;
      e.preventDefault();
    } else if (dragging) {
      tx += (e.clientX - sx) / r.width * MAP_W;
      ty += (e.clientY - sy) / r.height * MAP_H;
      sx = e.clientX; sy = e.clientY;
      clamp(); apply();
    }
  });

  const release = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinchDist = 0;
    if (!pointers.size) { dragging = false; svg.classList.remove("grab"); }
    try { svg.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
  };
  svg.addEventListener("pointerup", release);
  svg.addEventListener("pointercancel", release);
  // A drag has to end even if the pointer is lost some other way.
  svg.addEventListener("lostpointercapture", release);

  homeView();
  wrap.querySelectorAll("[data-mz]").forEach((b) => b.onclick = () => {
    if (b.dataset.mz === "fit") homeView();
    else zoomAt(b.dataset.mz === "in" ? 1.5 : 1 / 1.5, MAP_W / 2, MAP_H / 2);
  });
}

// ---------- editing and removing rows, in one place ----------
/* Eight screens grew a "create" form and stopped. Rather than eight
   hand-written edit dialogs that drift apart, each screen declares what its
   record looks like and this builds the form, the PATCH and the DELETE from
   that. A new editable thing is a table entry, not a new dialog. */
const ROW_KINDS = {
  product: {
    title: "product", label: (r) => r.name,
    path: (id) => `/api/admin/products/${id}`,
    fields: [
      { k: "name", label: "Name" },
      { k: "sku", label: "SKU" },
      { k: "category", label: "Category" },
      { k: "description", label: "Description", type: "textarea" },
      { k: "price_cents", label: "Unit price (cents)", type: "number" },
      { k: "case_size", label: "Case size", type: "number" },
      { k: "case_price_cents", label: "Case price (cents)", type: "number" },
      { k: "active", label: "Listed", type: "check" },
    ],
  },
  order: {
    title: "order", label: (r) => "#" + r.id,
    path: (id) => `/api/admin/orders/${id}`,
    delVerb: "Cancel",
    delAsk: "Cancel this order? It stays on the books as cancelled.",
    fields: [
      { k: "status", label: "Status", type: "select",
        options: ["pending", "confirmed", "shipped", "delivered", "cancelled"] },
      { k: "ship_name", label: "Ship to" },
      { k: "address", label: "Address" },
      { k: "city", label: "City" },
      { k: "postal", label: "Postcode" },
      { k: "phone", label: "Phone" },
      { k: "note", label: "Note", type: "textarea" },
    ],
    note: "Totals aren't editable — they come from the line items and the "
      + "discounts applied at the time. Use Refund to move money.",
  },
  promo: {
    title: "promo", label: (r) => r.name,
    path: (id) => `/api/admin/promos/${id}`,
    fields: [
      { k: "name", label: "Name" },
      { k: "body", label: "Body", type: "textarea" },
      { k: "discount_pct", label: "Discount %", type: "number" },
      { k: "region", label: "Region" },
      { k: "city", label: "City" },
      { k: "starts", label: "Starts" },
      { k: "video_url", label: "Video URL" },
      { k: "active", label: "Running", type: "check" },
    ],
  },
  store: {
    title: "store", label: (r) => r.name,
    path: (id) => `/api/admin/stores/${id}`,
    fields: [
      { k: "name", label: "Name" },
      { k: "kind", label: "Kind", type: "select",
        options: ["retail", "distribution", "partner"] },
      { k: "region", label: "Region" },
      { k: "city", label: "City" },
      { k: "lat", label: "Latitude", type: "number", step: "any" },
      { k: "lng", label: "Longitude", type: "number", step: "any" },
      { k: "contact", label: "Contact" },
      { k: "active", label: "Open", type: "check" },
    ],
  },
  post: {
    title: "post", label: (r) => (r.body || "").slice(0, 40),
    path: (id) => `/api/admin/feed/${id}`,
    fields: [{ k: "body", label: "Post", type: "textarea" }],
  },
  supplier: {
    title: "supplier", label: (r) => r.name,
    path: (id) => `/api/supply/suppliers/${id}`,
    fields: [
      { k: "name", label: "Name" },
      { k: "kind", label: "Kind", type: "select",
        options: ["ingredient", "packaging", "co-packer", "logistics", "service"] },
      { k: "contact", label: "Contact" },
      { k: "email", label: "Email" },
      { k: "phone", label: "Phone" },
      { k: "country", label: "Country" },
      { k: "lead_days", label: "Lead time (days)", type: "number" },
      { k: "terms", label: "Terms" },
      { k: "notes", label: "Notes", type: "textarea" },
      { k: "active", label: "In use", type: "check" },
    ],
  },
  material: {
    title: "material", label: (r) => r.name,
    path: (id) => `/api/supply/materials/${id}`,
    fields: [
      { k: "name", label: "Name" },
      { k: "code", label: "Code" },
      { k: "kind", label: "Kind", type: "select",
        options: ["ingredient", "packaging", "co-packer", "logistics", "service"] },
      { k: "unit", label: "Unit", type: "select",
        options: ["kg", "L", "each", "case", "roll", "pallet"] },
      { k: "unit_cost_cents", label: "Unit cost (cents)", type: "number" },
      { k: "reorder_point", label: "Reorder at", type: "number", step: "any" },
      { k: "active", label: "In use", type: "check" },
    ],
    note: "Stock on hand isn't here — it only moves by receiving a purchase "
      + "order, finishing a run, or a recorded adjustment.",
  },
};

/* The buttons. Admin only: everyone else sees the row without them rather
   than seeing them and being refused. */
function rowActions(kind, row) {
  if (!S.user || !S.user.is_admin) return "";
  const k = ROW_KINDS[kind];
  return `<span class="row-acts">
    ${k ? `<button class="btn alt sm" data-rowedit="${kind}:${row.id}"
      >Edit</button>` : ""}
    <button class="btn alt sm danger-hint" data-rowdel="${kind}:${row.id}"
      >${(k && k.delVerb) || "Delete"}</button></span>`;
}

/* Call once after painting a view. `rows` maps kind -> array, so the dialog
   can be filled from data already on the page instead of refetching. */
function wireRows(rows, refresh) {
  view().querySelectorAll("[data-rowedit]").forEach((b) => b.onclick = () => {
    const [kind, id] = b.dataset.rowedit.split(":");
    const row = (rows[kind] || []).find((r) => String(r.id) === id);
    if (row) editRow(kind, row, refresh);
  });
  view().querySelectorAll("[data-rowdel]").forEach((b) => b.onclick = async () => {
    const [kind, id] = b.dataset.rowdel.split(":");
    const k = ROW_KINDS[kind] || DELETE_ONLY[kind];
    if (!k) return;
    if (!confirm(k.delAsk || `Delete this ${k.title}?`)) return;
    try {
      const r = await api(k.path(id), { method: "DELETE" });
      // The server decides between removing and retiring, because only it
      // knows what still points at the row. Say which happened.
      if (r && (r.retired || r.closed || r.cancelled || r.archived)) {
        toast(`Kept and hidden — other records still reference this ${k.title}`);
      } else {
        toast(`${k.title} deleted`);
      }
      refresh();
    } catch (e) { toast(e.message); }
  });
}

// Things you can remove but not edit here — they have their own edit screens.
const DELETE_ONLY = {
  event: { title: "event", path: (id) => `/api/store/admin/events/${id}` },
  doc: { title: "document", path: (id) => `/api/store/admin/documents/${id}`,
         delAsk: "Delete this document? A signed one is archived instead, "
           + "because the signature has to keep pointing at something." },
};

function editRow(kind, row, refresh) {
  const k = ROW_KINDS[kind];
  const input = (f) => {
    const v = row[f.k];
    if (f.type === "check") {
      return `<label class="perm"><input type="checkbox" data-f="${f.k}"
        ${v ? "checked" : ""}><span><b>${esc(f.label)}</b></span></label>`;
    }
    if (f.type === "select") {
      return `<label>${esc(f.label)}</label><select data-f="${f.k}">
        ${f.options.map((o) => `<option ${o === v ? "selected" : ""}
          >${esc(o)}</option>`).join("")}</select>`;
    }
    if (f.type === "textarea") {
      return `<label>${esc(f.label)}</label>
        <textarea data-f="${f.k}" rows="3">${esc(v == null ? "" : v)}</textarea>`;
    }
    return `<label>${esc(f.label)}</label><input data-f="${f.k}"
      type="${f.type || "text"}" ${f.step ? `step="${f.step}"` : ""}
      value="${esc(v == null ? "" : String(v))}">`;
  };
  modal(`<h3>Edit ${esc(k.title)} — ${esc(k.label(row) || "")}</h3>
    <div class="edit-grid">${k.fields.map(input).join("")}</div>
    ${k.note ? `<p class="dim" style="font-size:12px;margin-top:10px">${
      esc(k.note)}</p>` : ""}
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="row-save">Save</button></div>`);
  $("#row-save").onclick = async () => {
    const payload = {};
    document.querySelectorAll("#ops-modal [data-f]").forEach((el) => {
      const f = k.fields.find((x) => x.k === el.dataset.f);
      if (f.type === "check") payload[f.k] = el.checked ? 1 : 0;
      else if (f.type === "number") {
        payload[f.k] = el.value === "" ? null : Number(el.value);
      } else payload[f.k] = el.value;
    });
    try {
      await api(k.path(row.id), { method: "PATCH", body: payload });
      closeModal(); toast("Saved"); refresh();
    } catch (e) { toast(e.message); }
  };
}
