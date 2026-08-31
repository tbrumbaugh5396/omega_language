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
  const m = location.hash.match(/^#\/([\w-]+)(?:\/(\d+))?$/);
  if (!m) return false;
  S.tab = m[1];
  S.engId = (m[1] === "clients" && m[2]) ? +m[2] : null;
  return true;
}
function syncRoute() {
  const want = (S.tab === "clients" && S.engId)
    ? `#/clients/${S.engId}` : `#/${S.tab || "shop"}`;
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
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20a7.5 7.5 0 0115 0"/>',
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
  { id: "clients", label: "Clients (B2B)", icon: "handshake", group: "Sell",
    roles: ["admin"], perm: "documents" },
  // The fleet lives next to the clients it deploys — burying the platform
  // at the bottom of Company meant the operator never saw it.
  { id: "fleet", label: "Platform", icon: "shield2", group: "Sell",
    roles: ["admin"], provider: true },
  { id: "clock", label: "Time Clock", icon: "clock", group: "Operate", roles: "*" },
  { id: "stores", label: "Stores", icon: "pin", group: "Operate",
    roles: ["admin", "employee", "distributor"] },
  { id: "inventory", label: "Inventory", icon: "store", group: "Operate",
    roles: ["admin", "employee", "distributor"] },
  { id: "routes", label: "Routes", icon: "truck", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "supply", label: "Sourcing", icon: "tools", group: "Operate",
    roles: ["admin"], perm: "supply" },
  { id: "outreach", label: "Outreach", icon: "handshake", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "scan", label: "Scan", icon: "camera", group: "Operate", roles: "*" },
  { id: "feed", label: "Feed", icon: "feed", group: "Grow", roles: "*" },
  { id: "affiliates", label: "Affiliates", icon: "link", group: "Grow", roles: "*" },
  { id: "experiments", label: "Experiments", icon: "flask", group: "Grow",
    roles: ["admin"] },
  { id: "analytics", label: "Analytics", icon: "chart", group: "Grow",
    roles: ["admin"] },
  { id: "events", label: "Events", icon: "calendar", group: "Grow",
    roles: ["admin", "employee"] },
  { id: "email", label: "Email", icon: "megaphone", group: "Grow",
    roles: ["admin"] },
  { id: "docs", label: "Documents", icon: "file", group: "Company",
    roles: ["admin", "employee"] },
  { id: "staff", label: "Team & access", icon: "users", group: "Company",
    roles: ["admin"] },
  { id: "discord", label: "Discord", icon: "chat", group: "Company",
    roles: ["admin"] },
  { id: "slack", label: "Slack", icon: "megaphone", group: "Company",
    roles: ["admin"] },
  { id: "trello", label: "Trello", icon: "list", group: "Company",
    roles: ["admin"] },
  { id: "dropbox", label: "Dropbox", icon: "file", group: "Company",
    roles: ["admin"] },
  { id: "integrations", label: "Integrations", icon: "link", group: "Company",
    roles: ["admin"] },
  { id: "audit", label: "Audit log", icon: "shield2", group: "Company",
    roles: ["admin"] },
  { id: "dbview", label: "Database", icon: "list", group: "Company",
    roles: ["admin"] },
  { id: "profile", label: "My profile", icon: "user", group: "Company",
    roles: "*" },
  { id: "chat", label: "Chat", icon: "chat", group: "Company", roles: "*" },
  { id: "hq", label: "HQ", icon: "hq", group: "Company", roles: ["admin"] },
  { id: "admin", label: "Admin", icon: "gear", group: "Company", roles: ["admin"] },
];
/* Which purchased capability each tab belongs to. Tabs with no entry are
   core — part of Platform Core, on for everyone. The ids are the price
   book's own (the same ones the quote carries), so the entitlement written
   at stand-up and the lock shown here can never speak different names. */
const TAB_CAP = {
  shop: "selling", orders: "selling",
  promos: "marketing", email: "marketing", experiments: "marketing",
  clients: "crm", outreach: "crm",
  clock: "workforce", staff: "workforce",
  inventory: "inventory", supply: "sourcing",
  routes: "distribution", stores: "distribution",
  analytics: "intelligence", events: "events", affiliates: "affiliates",
  chat: "comms", feed: "comms",
  integrations: "api", discord: "api", slack: "api", trello: "api",
  dropbox: "api",
  audit: "infosec",
};
const CAP_LABEL = {
  selling: "Selling", marketing: "Marketing", crm: "CRM & Support",
  workforce: "Workforce", inventory: "Inventory", sourcing: "Sourcing",
  distribution: "Distribution", intelligence: "Intelligence",
  events: "Events", affiliates: "Affiliates", comms: "Comms",
  api: "API & data platform", infosec: "InfoSec",
};
// null caps = everything on: legacy installs, the provider, and any tenant
// stood up before entitlements existed keep the whole product.
const capLocked = (t) => {
  const need = TAB_CAP[t.id];
  const caps = S.meta && S.meta.caps;
  return !!(need && Array.isArray(caps) && !caps.includes(need));
};

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
  const perms = (S.user.permissions || "").split(",").map((p) => p.trim());
  return TABS.filter((t) => {
    // The fleet belongs to whoever runs the platform. On a client's own
    // install the tab does not exist, rather than existing and refusing.
    if (t.provider && !(S.meta && S.meta.is_provider)) return false;
    if (t.roles === "*") return true;
    if (S.user.is_admin) return true;
    // A tab can also be opened by an explicit grant, so a screen doesn't
    // have to be admin-or-nothing.
    if (t.perm && perms.includes(t.perm)) return true;
    return t.roles.includes(S.user.role);
  });
}

function renderChrome() {
  const who = $("#whoami");
  if (S.user) {
    const unread = S.notifs ? S.notifs.unread : 0;
    const roleLabel = S.user.role === "employee" && S.user.job !== "general"
      ? JOB_LABEL[S.user.job] || S.user.role : S.user.role;
    // Your own name is the obvious way in to your own record — it's where
    // everyone reaches for it.
    who.innerHTML = `<a id="bell" title="notifications">${opsIcon("bell","bell-ic")}${unread
      ? `<span class="bell-n">${unread}</span>` : ""}</a> ·
      <a id="me-link" title="your profile">${esc(S.user.name)}</a> ·
      ${esc(roleLabel)}` +
      (S.user.is_admin ? " · admin" : "") + ` · <a id="logout">sign out</a>`;
    $("#logout").onclick = logout;
    $("#bell").onclick = toggleNotifPanel;
    $("#me-link").onclick = () => { S.tab = "profile"; render(); };
  } else {
    who.innerHTML = `<a id="login-link">sign in</a>`;
    $("#login-link").onclick = () => { S.tab = "login"; render(); };
  }
  const tabs = allowedTabs();
  if (S.tab !== "login" && !tabs.find((t) => t.id === S.tab)) S.tab = tabs[0].id;
  const btn = (t) =>
    `<button data-t="${t.id}" class="${t.id === S.tab ? "on" : ""}${
        capLocked(t) ? " cap-locked" : ""}">
      <span class="ic">${opsIcon(t.icon)}</span><span>${t.label}</span>${
        capLocked(t) ? `<span class="cap-lock-ic">${opsIcon("shield2")}</span>`
                     : ""}</button>`;
  /* Rewriting the nav resets its scroll to the top, so a tab picked from the
     bottom of the list would jump the menu back up and hide where you just
     were. Keep the offset across the rewrite. */
  const nav = $("#tabs");
  const navScroll = nav.scrollTop;
  nav.innerHTML = NAV_GROUPS.map((g) => {
    const group = tabs.filter((t) => t.group === g);
    if (!group.length) return "";
    return (tabs.length > 5 ? `<div class="nav-group">${g}</div>` : "") +
      group.map(btn).join("");
  }).join("");
  nav.scrollTop = navScroll;
  // And remember it across reloads, so a refresh doesn't lose your place
  // either. Written on scroll rather than on navigation, because the nav can
  // be scrolled without anything being clicked.
  if (!nav.dataset.wired) {
    nav.dataset.wired = "1";
    let save;
    nav.addEventListener("scroll", () => {
      clearTimeout(save);
      save = setTimeout(
        () => sessionStorage.setItem("bc_nav_scroll", nav.scrollTop), 150);
    }, { passive: true });
    const saved = +sessionStorage.getItem("bc_nav_scroll") || 0;
    if (saved) requestAnimationFrame(() => { nav.scrollTop = saved; });
  }
  /* Continuity is the point, but not at the cost of pointing somewhere else:
     a reload lands on the default tab, and restoring a scroll position from
     the previous session would leave the menu parked away from the tab
     you're actually on. So the remembered offset is honoured only while the
     current tab is still in view. */
  requestAnimationFrame(() => {
    const here = nav.querySelector("button.on");
    if (!here) return;
    const b = here.getBoundingClientRect(), n = nav.getBoundingClientRect();
    if (b.top < n.top || b.bottom > n.bottom) {
      here.scrollIntoView({ block: "nearest" });
    }
  });
  let bottom = $("#bottomnav");
  if (!bottom) {
    bottom = document.createElement("nav");
    bottom.id = "bottomnav";
    document.body.appendChild(bottom);
  }
  /* Four shortcuts and a way to everything else.

     The bottom bar used to be the only navigation under 720px, showing five
     tabs out of twenty-six — so twenty-one screens, Integrations and
     Sourcing and the audit log among them, had no route to them at all on a
     phone or a narrow window. Five shortcuts is the right number for a
     thumb; the mistake was letting that also be the whole menu. */
  const quick = MOBILE_PRIORITY
    .map((id) => tabs.find((t) => t.id === id)).filter(Boolean).slice(0, 4);
  const inQuick = new Set(quick.map((t) => t.id));
  bottom.innerHTML = quick.map(btn).join("")
    + `<button id="more-tabs" class="${
        tabs.some((t) => t.id === S.tab && !inQuick.has(t.id)) ? "on" : ""}">
        <span class="ic">${opsIcon("list")}</span><span>More</span></button>`;

  document.querySelectorAll("#tabs button, #bottomnav button[data-t]")
    .forEach((b) => {
      b.onclick = () => { S.promoLanding = null; S.tab = b.dataset.t; render(); };
    });
  $("#more-tabs").onclick = () => showAllTabs(tabs);
}

/* Every screen, grouped as the sidebar groups them. */
function showAllTabs(tabs) {
  const sheet = document.createElement("div");
  sheet.id = "tab-sheet";
  sheet.innerHTML = `<div class="sheet-card">
    <div class="sheet-head"><b>Go to</b>
      <button class="btn alt sm" data-close-sheet>Close</button></div>
    <input id="tab-find" placeholder="Find a screen" autocomplete="off">
    <div class="sheet-list">${NAV_GROUPS.map((g) => {
      const group = tabs.filter((t) => t.group === g);
      if (!group.length) return "";
      return `<div class="sheet-group">${g}</div>` + group.map((t) => `
        <button class="sheet-t ${t.id === S.tab ? "on" : ""}"
          data-go="${t.id}" data-label="${esc(t.label.toLowerCase())}">
          <span class="ic">${opsIcon(t.icon)}</span>${esc(t.label)}</button>`
      ).join("");
    }).join("")}</div></div>`;
  document.body.appendChild(sheet);

  const close = () => {
    sheet.remove();
    document.removeEventListener("keydown", esc2);
  };
  const esc2 = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc2);
  sheet.onclick = (e) => { if (e.target === sheet) close(); };
  sheet.querySelector("[data-close-sheet]").onclick = close;
  sheet.querySelectorAll("[data-go]").forEach((b) => b.onclick = () => {
    close();
    S.promoLanding = null;
    S.tab = b.dataset.go;
    render();
  });
  // Twenty-six screens is more than anyone scans, so let it be typed at.
  const find = sheet.querySelector("#tab-find");
  find.oninput = () => {
    const q = find.value.trim().toLowerCase();
    sheet.querySelectorAll("[data-go]").forEach((b) => {
      b.hidden = !!q && !b.dataset.label.includes(q);
    });
    sheet.querySelectorAll(".sheet-group").forEach((g) => {
      let n = g.nextElementSibling, any = false;
      while (n && n.matches("[data-go]")) {
        if (!n.hidden) any = true;
        n = n.nextElementSibling;
      }
      g.hidden = !any;
    });
  };
  setTimeout(() => find.focus(), 40);
}

const SKELETON = '<div class="skel"></div><div class="skel" style="height:180px">'
  + '</div><div class="skel"></div>';

function emptyState(icon, title, hint) {
  return `<div class="card empty"><span class="e-ic">${opsIcon(icon)}</span>
    <b>${title}</b><br>${hint}</div>`;
}

async function render() {
  renderChrome();
  syncRoute();
  clearInterval(S._dcTimer);        // stop polling Discord once you leave it
  clearInterval(S._slackTimer);     // and Slack
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
    docs: renderDocs, clients: renderClients,
    staff: renderStaff, events: renderEvents,
    profile: renderProfile, stores: renderStores,
    email: renderEmail, discord: renderDiscord,
    supply: renderSupply, audit: renderAudit, dbview: renderDb,
    integrations: renderIntegrations, slack: renderSlack,
    trello: renderTrello, dropbox: renderDropbox,
    hq: renderHQ, fleet: renderFleet, admin: renderAdmin,
    login: renderLogin,
  }[S.tab] || renderShop;
  const tabDef = TABS.find((t) => t.id === S.tab);
  if (tabDef && capLocked(tabDef)) {
    try { await renderCapLocked(tabDef); } catch (e) { view().innerHTML =
      `<div class="card">Error: ${esc(e.message)}</div>`; }
    document.querySelectorAll(".map-wrap").forEach((m) => wireMap(m.id));
    drawStoreRail();
    return;
  }
  try { await fn(); } catch (e) { view().innerHTML =
    `<div class="card">Error: ${esc(e.message)}</div>`; }
  // Maps are inserted as markup by whichever view drew them; wiring happens
  // here so every view gets pan/zoom without remembering to ask.
  document.querySelectorAll(".map-wrap").forEach((m) => wireMap(m.id));
  drawStoreRail();
}


// ---------- launch: the real address, and the sold capabilities ----------
/* One act: the hostname joins the tenant's registry row (.localhost door
   kept), public_base_url lands in their config, the capability grant
   refreshes from the signed quote, the engagement records the URL. DNS
   stays the operator's job — this makes the platform answer when the
   name arrives. */
async function launchSite(eid, name, currentUrl, after) {
  let sug = null;
  try { sug = (await api(
    `/api/store/admin/engagements/${eid}/stand-up`)).suggestion; }
  catch { sug = null; }
  modal(`<h3>Launch ${esc(name)}</h3>
    <p class="dim">Their install answers on its .localhost door today.
      Give it the real address — the platform starts answering to it the
      moment DNS points here.</p>
    <label>Live URL</label>
    <input id="ls-url" placeholder="https://shop.example.com"
      value="${esc(currentUrl || "")}">
    <p class="dim">${sug && sug.cap_ids && sug.cap_ids.length
      ? `${opsIcon("pen", "btn-ic")} The capability grant refreshes from
         the ${sug.signed ? "signed" : "latest"} quote:
         <b>${sug.cap_ids.length} capabilities</b>.`
      : "No quote on file — the capability grant stays as it is."}</p>
    <div class="modal-foot">
      <button class="btn" id="ls-go">Launch</button>
      <button class="btn alt" data-close>Later</button>
    </div>`);
  $("#ls-go").onclick = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${eid}/launch`,
        { body: { url: $("#ls-url").value.trim() } });
      closeModal();
      toast(`${name} is live at ${out.url}`
        + (out.caps.length ? ` with ${out.caps.length} capabilities` : ""));
      if (after) after();
    } catch (err) { toast(err.message); }
  };
}

// ---------- a capability the tenant hasn't bought ----------
/* The tab exists, greyed, and opens this instead of the screen: what the
   capability is, what it costs a month (from the provider's own price
   book, not a guess), and one button that opens a lead on the studio's
   sales board. The product sells its own upgrades. */
async function renderCapLocked(tab) {
  const cap = TAB_CAP[tab.id];
  let info = null;
  try { info = await api(`/api/capability-info/${cap}`); } catch {}
  const name = (info && info.name) || CAP_LABEL[cap] || cap;
  view().innerHTML = `
    <h2>${esc(tab.label)}</h2>
    <div class="card" style="max-width:560px">
      <b>${esc(name)} isn't on your plan yet.</b>
      <p class="dim">${info && info.note ? esc(info.note) + " " : ""}It's a
        capability of the platform you're already running on — turning it
        on is a plan change, not a build.</p>
      ${info && info.price ? `<p><b>$${info.price}/month</b>
        <span class="dim">· ${esc(info.band)} band, from the published
        price book${info.requires ? ` · requires ${esc(info.requires)}`
        : ""}</span></p>` : ""}
      ${S.user && S.user.is_admin ? `
      <div class="chips" style="margin-top:10px">
        <button class="btn" id="cap-ask">${opsIcon("handshake","btn-ic")}
          Ask us to turn this on</button>
      </div>
      <p class="dim" id="cap-ask-msg" style="margin-top:8px"></p>`
      : `<p class="dim" style="margin-top:10px">Your administrator can ask
        for this from the same screen — the request goes straight to the
        platform's sales board.</p>`}
    </div>`;
  const b = $("#cap-ask");
  if (b) b.onclick = async () => {
    b.disabled = true;
    try {
      await api("/api/capability-request", { body: { capability: cap } });
      $("#cap-ask-msg").textContent =
        "Asked — it's on our board, and we'll come back to you.";
    } catch (e) {
      b.disabled = false;
      $("#cap-ask-msg").textContent = e.message;
    }
  };
}

// ---------- login ----------

function renderLogin() {
  const regions = S.meta.regions.map((r) => `<option>${r}</option>`).join("");
  /* Widths come from the grid, not from inline max-widths on each card. The
     old version pinned the form at 420px and the QR panel at 280px, so on a
     half-width window the two sat as narrow columns with the inputs at
     whatever width the browser felt like, and on a wide one they hugged the
     left edge. */
  view().innerHTML = `
    <h2>Sign in</h2>
    <div class="signin">
      <div class="card signin-form">
        <form id="login-form">
          <label>Name<input id="li-name" required autocomplete="name"></label>
          <div class="signin-two">
            <label>I am a
              <select id="li-role">
                <option value="customer">customer</option>
                <option value="distributor">distributor</option>
                <option value="influencer">influencer</option>
                <option value="employee">employee</option>
                <option value="owner">founder / owner (needs admin key)</option>
              </select></label>
            <label>Region
              <select id="li-region"><option value=""></option>${regions}</select></label>
          </div>
          <label>Email <span class="dim">for order updates &amp; offers</span>
            <input id="li-email" type="email" placeholder="optional"
              autocomplete="email"></label>
          <label>Password<input id="li-pass" type="password"
            autocomplete="current-password"
            placeholder="sets on first sign-in, then required"></label>
          <label>Admin key <span class="dim">optional</span>
            <input id="li-admin" type="password" autocomplete="off"></label>
          <button class="btn">Sign in</button>
        </form>
      </div>

      <div class="card signin-qr">
        <h3>Sign in with a QR</h3>
        <p class="dim">If someone has issued you a sign-in QR — from a
          profile page or the Admin tab — scan it here instead of typing
          anything.</p>
        <button class="btn alt" id="li-scan">${opsIcon("camera", "btn-ic")}
          Scan a sign-in QR</button>
        <div id="li-scan-msg" class="dim"></div>
        <h3>Open on your phone</h3>
        <div id="lan-qr" class="dim">loading…</div>
        <p class="dim">Scan from a phone on the same wifi.</p>
      </div>
    </div>`;

  $("#li-scan").onclick = async () => {
    const msg = $("#li-scan-msg");
    msg.textContent = "";
    const r = await QRScan.signIn("Scan your sign-in QR");
    if (!r.ok && r.error) msg.textContent = r.error;
  };
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
      // Somewhere in particular if they were sent here mid-task; otherwise
      // an employee's job home, or the shop.
      S.tab = S.afterLogin
        || (u.role === "employee" && JOB_HOME[u.job]) || "shop";
      S.afterLogin = null;
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

// ---------- integrations ----------
/* One screen for all of them, drawn from what the server says each provider
   needs. Seven hand-written panels would drift the moment an eighth arrived;
   this way a new integration appears here the day it's added to the
   registry, with the right form and the right explanation. */

async function renderIntegrations() {
  const d = await api("/api/admin/integrations");

  const card = (p) => {
    const status = p.connected
      ? `<span class="pill ok">connected${p.account
          ? " · " + esc(p.account) : ""}</span>`
      : p.auth === "inbound"
        ? (p.inbound_ready
            ? `<span class="pill ok">ready · ${p.received} received</span>`
            : '<span class="pill">not set up</span>')
        : '<span class="pill">not connected</span>';
    return `<div class="card intg" data-p="${p.name}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.label)}</b>
          <span class="dim">${esc(p.blurb)}</span></div>
        ${status}
        ${p.connected && p.syncs ? `
          <span class="pill ${p.live ? "ok" : ""}">${p.live
            ? "live" : "on demand"}</span>
          <button class="btn alt sm" data-iglive="${p.name}">${p.live
            ? "Stop live updates" : "Go live"}</button>
          <button class="btn alt sm" data-igsync="${p.name}"
            >Sync now</button>` : ""}
        ${p.connected ? `<button class="btn alt sm" data-igtest="${p.name}"
          >Test</button>` : ""}
        ${p.connected || p.inbound_ready
          ? `<button class="btn alt sm" data-igoff="${p.name}">${
              p.auth === "inbound" ? "New key" : "Disconnect"}</button>` : ""}
      </div>
      <p class="dim intg-does">${esc(p.does)}</p>
      ${p.events.length ? `<p class="dim intg-when">Fires when
        ${p.events.map(esc).join(", ")}.</p>` : ""}
      ${p.connected ? "" : `<div class="intg-form" id="f-${p.name}"></div>`}
      ${p.name === "slack" && p.connected
        ? '<div class="intg-chat" id="slack-chat"></div>' : ""}
      ${p.name === "canva" && p.connected
        ? `<button class="btn alt sm" id="canva-list">List my designs</button>
           <div id="canva-out"></div>` : ""}
      ${p.name === "laceup"
        ? `<div class="intg-form" id="f-laceup-extra"></div>` : ""}
    </div>`;
  };

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Integrations</h2>
        <p class="dim">Each of these is connected once and then works on its
          own. Credentials are stored and never shown again — the screen can
          tell you what a connection reached, but not what it is.</p></div>
    </div>
    ${d.providers.map(card).join("")}
    ${d.log.length ? `<h3>Recent activity</h3>
      <div class="card"><div class="tablewrap"><table>
        <thead><tr><th>when</th><th>which</th><th>event</th><th>result</th>
          </tr></thead>
        <tbody>${d.log.map((l) => `<tr>
          <td class="dim">${fmtDate(l.created_at)}</td>
          <td>${esc(l.provider)}</td><td class="dim">${esc(l.event)}</td>
          <td>${l.ok ? '<span class="pill ok">ok</span>'
            : `<span class="pill bad">failed</span>
               <span class="dim">${esc(l.detail)}</span>`}</td>
        </tr>`).join("")}</tbody></table></div></div>` : ""}`;

  d.providers.forEach((p) => drawForm(p, () => renderIntegrations()));
  if ($("#slack-chat")) drawSlackChat();

  view().querySelectorAll("[data-iglive]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.iglive;
    const on = d.providers.find((x) => x.name === name).live;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      if (on) {
        await api(`/api/admin/integrations/${name}/webhook`,
                  { method: "DELETE" });
        toast("Live updates off — sync by hand from here");
      } else {
        await api(`/api/admin/integrations/${name}/webhook`,
                  { method: "POST" });
        toast("Live — changes over there now arrive as they happen");
      }
      renderIntegrations();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  view().querySelectorAll("[data-igsync]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/api/admin/integrations/${b.dataset.igsync}/sync`,
                          { method: "POST" });
      toast(r.changed.length
        ? `${r.changed.length} of ${r.checked} moved on over there — `
          + r.changed.map((x) => `${x.kind} #${x.id} ${x.applied}`).join(", ")
        : `${r.checked} checked, nothing has changed`);
      renderIntegrations();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  view().querySelectorAll("[data-igtest]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/api/admin/integrations/${b.dataset.igtest}/test`,
                          { method: "POST" });
      toast(`Still working — ${r.detail}`);
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  view().querySelectorAll("[data-igoff]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.igoff;
    const p = d.providers.find((x) => x.name === name);
    if (p.auth === "inbound") {
      if (!confirm("Issue a new key? Whatever is using the old one stops "
        + "working until it's updated.")) return;
      const r = await api(
        `/api/admin/integrations/${name}/inbound-key?rotate=1`,
        { method: "POST" });
      toast("New key issued");
      renderIntegrations();
      return;
    }
    if (!confirm(`Disconnect ${p.label}?`)) return;
    await api(`/api/admin/integrations/${name}`, { method: "DELETE" });
    renderIntegrations();
  });

  if ($("#canva-list")) $("#canva-list").onclick = async () => {
    try {
      const r = await api("/api/admin/integrations/canva/designs");
      const items = r.items || r.designs || [];
      $("#canva-out").innerHTML = items.length
        ? `<table style="margin-top:8px">${items.slice(0, 20).map((x) =>
            `<tr><td>${esc(x.title || x.id)}</td>
             <td class="dim">${esc(x.id || "")}</td></tr>`).join("")}</table>`
        : '<p class="dim">No designs came back.</p>';
    } catch (e) { toast(e.message); }
  };
}

/* Slack its own screen, beside Discord, because that is where you look for
   a conversation — not inside a settings page. The integrations screen still
   holds the connection; this holds the talking. */
async function renderSlack() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "slack");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Slack</h2>
        <p class="dim">${p.connected
          ? "Alerts go out on their own. Read the channels and answer here."
          : "Not connected yet."}</p></div>
      <button class="btn alt" id="sl-setup">${p.connected
        ? "Connection settings" : "Connect Slack"}</button>
    </div>
    ${p.connected ? '<div id="slack-chat"></div>' : `
      <div class="card empty"><span class="e-ic">${opsIcon("megaphone")}</span>
        <b>Slack isn't connected</b>
        <p class="dim">Add an incoming webhook and the business starts
          posting to your channel. Add a bot token as well and you can read
          the channels and reply from here.</p>
        <button class="btn" id="sl-go">Set it up</button></div>`}`;
  const toSettings = () => { S.tab = "integrations"; render(); };
  $("#sl-setup").onclick = toSettings;
  if ($("#sl-go")) $("#sl-go").onclick = toSettings;
  if (p.connected) {
    drawSlackChat();
    // Without a bot token the reader explains itself; say it here too, so
    // the empty panel isn't a mystery.
    setTimeout(() => {
      const box = $("#slack-chat");
      if (box && !box.innerHTML.trim()) {
        box.innerHTML = '<p class="dim">Add a bot token under Integrations '
          + "to read and reply here.</p>";
      }
    }, 1200);
  }
}

/* Reading and answering Slack from here. Same shape as the Discord reader,
   deliberately: two chat surfaces that behave differently are two things to
   learn for no reason. */
async function drawSlackChat() {
  const box = $("#slack-chat");
  if (!box) return;
  let list;
  try {
    list = await api("/api/admin/integrations/slack/channels");
  } catch (e) {
    box.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
    return;
  }
  if (list.error) {
    box.innerHTML = `<p class="dim">${esc(list.error)}</p>`;
    return;
  }
  if (!list.channels.length) {
    box.innerHTML = '<p class="dim">No channels came back — check the '
      + "app has channels:read.</p>";
    return;
  }
  const readable = list.channels.filter((c) => c.member);
  if (!S.slackChan || !list.channels.some((c) => c.id === S.slackChan)) {
    S.slackChan = (readable[0] || list.channels[0]).id;
  }
  box.innerHTML = `
    <div class="dc-wrap">
      <div class="dc-list">${list.channels.map((c) => `
        <button class="dc-c ${c.id === S.slackChan ? "on" : ""}"
          data-slc="${c.id}"><b>#${esc(c.name)}</b>
          ${c.member ? (c.topic ? `<span class="dim">${esc(c.topic)}</span>`
            : "") : '<span class="dim">not joined</span>'}</button>`).join("")}
      </div>
      <div class="dc-room">
        <div class="dc-msgs" id="slack-msgs"><p class="dim">Loading…</p></div>
        <form class="dc-say" id="slack-say">
          <input id="slack-text" autocomplete="off"
            placeholder="Message #${esc((list.channels.find(
              (c) => c.id === S.slackChan) || {}).name || "")}">
          <button class="btn">Send</button>
        </form>
      </div>
    </div>`;
  box.querySelectorAll("[data-slc]").forEach((b) => b.onclick = () => {
    S.slackChan = b.dataset.slc; drawSlackChat();
  });
  $("#slack-say").onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#slack-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await api(`/api/admin/integrations/slack/${S.slackChan}/messages`,
                { body: { text } });
      loadSlackMsgs();
    } catch (err) { toast(err.message); input.value = text; }
  };
  loadSlackMsgs();
  clearInterval(S._slackTimer);
  S._slackTimer = setInterval(() => {
    if ((S.tab === "slack" || S.tab === "integrations") && $("#slack-msgs")) {
      loadSlackMsgs();
    }
    else clearInterval(S._slackTimer);
  }, 20000);
}

async function loadSlackMsgs() {
  const el = $("#slack-msgs");
  if (!el) return;
  try {
    const d = await api(
      `/api/admin/integrations/slack/${S.slackChan}/messages`);
    if (d.error) {
      el.innerHTML = `<p class="dim">${esc(d.error)}</p>`;
      return;
    }
    // Only redraw on change, so a poll doesn't yank the scroll position out
    // from under someone reading.
    const sig = d.messages.map((m) => m.id).join(",");
    if (sig === el.dataset.sig) return;
    el.dataset.sig = sig;
    el.innerHTML = d.messages.map((m) => `
      <div class="dc-m${m.bot ? " bot" : ""}">
        <div class="dc-who">${esc(m.author)}${m.bot
          ? '<span class="pill">bot</span>' : ""}
          <span class="dim">${fmtDate(m.at)}</span></div>
        <div class="dc-body">${esc(m.content) || '<i class="dim">—</i>'}</div>
      </div>`).join("") || '<p class="dim">Nothing here yet.</p>';
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    el.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
  }
}

/* The connect form for one provider, from its declared fields. */
function drawForm(p, refresh) {
  const box = $(`#f-${p.name}`);

  if (p.name === "laceup") {
    const extra = $("#f-laceup-extra");
    if (extra) {
      extra.innerHTML = `
        <p class="dim">LaceUp publishes no API to call, so this goes the
          other way: it posts orders to an address of ours, or you drop in a
          file. Lines are matched to products by SKU — the code printed on
          the case, not our internal ids.</p>
        <button class="btn alt sm" id="lu-key">${p.inbound_ready
          ? "Show the endpoint" : "Set up the endpoint"}</button>
        <label class="f" style="margin-top:10px">Or import an order CSV
          <span class="dim">columns: reference, customer, email, city, sku,
            qty — one row per line</span>
          <input type="file" id="lu-csv" accept=".csv"></label>
        <div id="lu-out"></div>`;
      $("#lu-key").onclick = async () => {
        const r = await api(`/api/admin/integrations/laceup/inbound-key`,
                            { method: "POST" });
        $("#lu-out").innerHTML = `<div class="card" style="margin-top:10px">
          <label>POST orders to</label>
          <input value="${esc(r.url)}" readonly>
          <label>With header <code>X-API-Key</code></label>
          <input value="${esc(r.key)}" readonly>
          <p class="dim">This key is the whole of the security on that
            address, so treat it like a password. Issue a new one and the old
            stops working immediately.</p></div>`;
      };
      $("#lu-csv").onchange = async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        try {
          const r = await fetch("/api/admin/integrations/laceup/import", {
            method: "POST", headers: { Authorization: "Bearer " + S.user.token },
            body: fd });
          const out = await r.json();
          if (!r.ok) throw new Error(out.detail || "import failed");
          $("#lu-out").innerHTML = `<p class="dim">Placed
            ${out.placed.length} order(s).${out.skipped.length
              ? ` Skipped ${out.skipped.length}: ` + out.skipped.map((s) =>
                  esc(`${s.row} — ${s.why}`)).join("; ") : ""}</p>`;
        } catch (err) { toast(err.message); }
      };
    }
    return;
  }

  if (!box) return;

  if (p.auth === "oauth2") {
    box.innerHTML = `
      <p class="dim">${p.app_ready
        ? "App registered. Connecting opens " + esc(p.label)
          + " so you can approve access."
        : "First register an app with " + esc(p.label) + " and paste its "
          + "client id and secret. They belong to your company, not to this "
          + "software, which is why they aren't shipped with it."}</p>
      ${p.app_ready ? "" : `
        <label class="f">Client ID<input id="app-id-${p.name}"></label>
        <label class="f">Client secret
          <input id="app-secret-${p.name}" type="password"></label>
        <button class="btn alt sm" data-appsave="${p.name}">Save app</button>`}
      ${p.app_ready ? `<button class="btn" data-auth="${p.name}"
        >Connect ${esc(p.label)}</button>` : ""}
      <p class="dim" id="app-msg-${p.name}"></p>`;

    const save = box.querySelector("[data-appsave]");
    if (save) save.onclick = async () => {
      try {
        const r = await api(`/api/admin/integrations/${p.name}/app`, {
          body: { client_id: $(`#app-id-${p.name}`).value,
                  client_secret: $(`#app-secret-${p.name}`).value } });
        toast(`Saved. Add ${r.redirect_uri} as the redirect URI.`);
        refresh();
      } catch (e) { toast(e.message); }
    };
    const go = box.querySelector("[data-auth]");
    if (go) go.onclick = async () => {
      try {
        const r = await api(`/api/admin/integrations/${p.name}/authorize`);
        location.href = r.url;
      } catch (e) {
        $(`#app-msg-${p.name}`).innerHTML =
          `<span class="low">${esc(e.message)}</span>`;
      }
    };
    return;
  }

  box.innerHTML = `
    ${p.fields.map((f) => `<label class="f">${esc(f.label)}
      ${f.hint ? `<span class="dim">${esc(f.hint)}</span>` : ""}
      <input id="fld-${p.name}-${f.k}" ${f.secret ? 'type="password"' : ""}
        autocomplete="off"></label>`).join("")}
    <button class="btn" data-conn="${p.name}">Connect</button>
    <p class="dim" id="msg-${p.name}"></p>`;
  box.querySelector("[data-conn]").onclick = async () => {
    const b = box.querySelector("[data-conn]");
    const msg = $(`#msg-${p.name}`);
    const fields = {};
    p.fields.forEach((f) => {
      fields[f.k] = $(`#fld-${p.name}-${f.k}`).value;
    });
    b.disabled = true; b.setAttribute("aria-busy", "true");
    msg.textContent = `checking with ${p.label}…`;
    try {
      const r = await api(`/api/admin/integrations/${p.name}/connect`,
                          { body: { fields } });
      toast(`${p.label} connected${r.account ? " — " + r.account : ""}`);
      refresh();
    } catch (e) {
      msg.innerHTML = `<span class="low">${esc(e.message)}</span>`;
    } finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
}

// ---------- Trello ----------
/* What we sent to the board and what became of it. Read from our own
   records rather than from the board, because the question is "what did we
   raise and did anyone deal with it" — a board has plenty on it this system
   never put there. */
async function renderTrello() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "trello");
  if (!p.connected) {
    view().innerHTML = `
      <h2>Trello</h2>
      <div class="card empty"><span class="e-ic">${opsIcon("list")}</span>
        <b>Trello isn't connected</b>
        <p class="dim">Connect it and every enquiry, support ticket and
          low-stock warning becomes a card on the list you choose.</p>
        <button class="btn" id="tr-go">Set it up</button></div>`;
    $("#tr-go").onclick = () => { S.tab = "integrations"; render(); };
    return;
  }
  const { cards } = await api("/api/admin/integrations/trello/cards");
  const open = cards.filter((c) => c.local_state !== "closed");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Trello</h2>
        <p class="dim">${esc(p.account)} · ${p.live
          ? "changes on the board arrive here as they happen"
          : "press sync to read the board — or go live under Integrations"}
        </p></div>
      <span class="head-acts">
        <button class="btn alt" id="tr-sync">Sync now</button>
      </span>
    </div>
    <div class="stats">
      <div class="stat"><div class="n">${cards.length}</div>
        <div class="l">cards raised</div></div>
      <div class="stat"><div class="n ${open.length ? "" : ""}">${open.length}</div>
        <div class="l">still open here</div></div>
      <div class="stat"><div class="n">${p.live ? "live" : "manual"}</div>
        <div class="l">updates</div></div>
    </div>
    ${cards.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>what</th><th>raised for</th><th>on the board</th>
        <th>here</th><th>last read</th><th></th></tr></thead>
      <tbody>${cards.map((c) => `<tr>
        <td>${esc(c.kind)} #${c.local_id}</td>
        <td>${esc(c.label || "—")}</td>
        <td>${c.remote_state
          ? `<span class="pill">${esc(c.remote_state)}</span>`
          : '<span class="dim">not read yet</span>'}</td>
        <td><span class="pill ${c.local_state === "closed" ? "ok" : ""}"
          >${esc(c.local_state || "—")}</span></td>
        <td class="dim">${c.synced_at ? timeAgo(c.synced_at) : "never"}</td>
        <td>${c.url ? `<a class="btn alt sm" href="${esc(c.url)}"
          target="_blank" rel="noopener">Open</a>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : `<div class="card empty"><span class="e-ic">${opsIcon("list")}</span>
         <b>No cards raised yet</b>
         <p class="dim">The next enquiry, ticket or low-stock warning will
           make one.</p></div>`}`;
  $("#tr-sync").onclick = async () => {
    const b = $("#tr-sync");
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api("/api/admin/integrations/trello/sync",
                          { method: "POST" });
      toast(r.changed.length
        ? `${r.changed.length} of ${r.checked} moved on`
        : `${r.checked} checked, nothing has changed`);
      renderTrello();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
}

// ---------- Dropbox ----------
/* The folder, not a promise about it. An integration that files things
   somewhere you can't see is one you take on faith, and the first time
   anybody checks is the day they need the file. */
async function renderDropbox() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "dropbox");
  if (!p.connected) {
    view().innerHTML = `
      <h2>Dropbox</h2>
      <div class="card empty"><span class="e-ic">${opsIcon("file")}</span>
        <b>Dropbox isn't connected</b>
        <p class="dim">Connect it and signed documents are filed
          automatically, and the database backup has somewhere to live that
          isn't this machine.</p>
        <button class="btn" id="db-go">Set it up</button></div>`;
    $("#db-go").onclick = () => { S.tab = "integrations"; render(); };
    return;
  }
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Dropbox</h2>
        <p class="dim">${esc(p.account)} · signed documents are filed here as
          they're signed.</p></div>
      <span class="head-acts">
        <button class="btn" id="dbx-backup">Back up the database</button>
        <button class="btn alt" id="dbx-refresh">Refresh</button>
      </span>
    </div>
    <p class="dim" style="max-width:640px">A backup goes up whole and
      unredacted — credentials included — because one with the secrets
      stripped out only looks like a backup until you need it. Treat the
      folder the way you'd treat the database.</p>
    <div id="dbx-files"><div class="skel"></div></div>`;
  const draw = async () => {
    try {
      const d = await api("/api/admin/integrations/dropbox/files");
      $("#dbx-files").innerHTML = d.files.length
        ? `<div class="card"><div class="tablewrap"><table>
            <thead><tr><th>file</th><th>where</th><th class="num">size</th>
              <th>filed</th></tr></thead>
            <tbody>${d.files.map((f) => `<tr>
              <td>${esc(f.name)}</td>
              <td class="dim">${esc(f.path.replace("/" + f.name, "") || "/")}</td>
              <td class="num">${(f.size / 1024).toFixed(0)} KB</td>
              <td class="dim">${esc((f.modified || "").replace("T", " ")
                .replace("Z", ""))}</td>
            </tr>`).join("")}</tbody></table></div></div>`
        : `<div class="card empty"><span class="e-ic">${opsIcon("file")}</span>
           <b>Nothing filed yet</b><p class="dim">${esc(d.note
             || "Sign a document, or back the database up, and it appears here.")}
           </p></div>`;
    } catch (e) {
      $("#dbx-files").innerHTML = `<div class="card dim">${esc(e.message)}</div>`;
    }
  };
  $("#dbx-refresh").onclick = draw;
  $("#dbx-backup").onclick = async () => {
    const b = $("#dbx-backup");
    if (!confirm("Send a full backup to Dropbox?\n\nIt contains everything, "
      + "credentials included.")) return;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api("/api/admin/integrations/dropbox/backup",
                          { method: "POST" });
      toast(`Backed up — ${(r.bytes / 1024).toFixed(0)} KB`);
      draw();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
  draw();
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
  clearTimeout(S._wsRetry);
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/ws?token=${encodeURIComponent(S.user.token)}`);
  S._ws = ws;
  ws.onopen = () => { S._wsWait = 0; };
  ws.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (d.type === "msg") onChatMessage(d);
    else if (d.type === "signal") onSignal(d);
  };
  /* Back off rather than retrying on a fixed timer. A socket the server
     keeps refusing — a stale token, an old tab left open overnight — used to
     mean a reconnect every three seconds forever, which is a connection
     storm nobody is watching and which multiplies by the number of open
     tabs. Doubling to a minute makes a broken tab cheap. */
  ws.onclose = () => {
    S._ws = null;
    if (!S.user) return;
    S._wsWait = Math.min((S._wsWait || 2000) * 2, 60000);
    S._wsRetry = setTimeout(connectWS, S._wsWait);
  };
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
          <div class="dm-start">
            <input id="dm-name" list="dm-names" placeholder="Message someone by name…"
              autocomplete="off">
            <datalist id="dm-names">${staff.staff.map((u) =>
              `<option value="${esc(u.name)}">${
                staff.online.includes(u.id) ? "online" : ""}</option>`).join("")}</datalist>
            <button class="btn sm" id="dm-go">Start</button>
          </div>` : ""}
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
  if ($("#dm-go")) {
    const startDm = async () => {
      const typed = $("#dm-name").value.trim().toLowerCase();
      if (!typed) return;
      // Exact name first, then a unique partial — so "dev" finds Dev Patel
      // but an ambiguous fragment asks rather than guessing.
      const all = (staff && staff.staff) || [];
      let hit = all.find((u) => u.name.toLowerCase() === typed);
      if (!hit) {
        const near = all.filter((u) => u.name.toLowerCase().includes(typed));
        if (near.length === 1) hit = near[0];
        else if (near.length > 1) {
          return toast(`${near.length} people match "${typed}" — be more specific`);
        }
      }
      if (!hit) return toast(`nobody on the team matches "${typed}"`);
      const r = await api("/api/chat/dm", { body: { user_id: hit.id } });
      S.chatConv = r.conv_id;
      $("#dm-name").value = "";
      render();
    };
    $("#dm-go").onclick = startDm;
    $("#dm-name").onkeydown = (e) => { if (e.key === "Enter") startDm(); };
  }
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
/* Where each kind of alert should take you. A notification is a prompt to do
   something; landing on the screen where you do it is the whole point. */
const NOTIF_TAB = {
  order: "orders", inventory: "inventory", logistics: "routes",
  affiliate: "affiliates", analytics: "analytics",
  experiment: "experiments", achievement: "profile",
  document: "docs", ticket: "chat", enquiry: "outreach",
  engagement: "clients",
  // a capability ask is fulfilled on the Platform tab — the notification
  // lands you where the grant button is, not on a board to hunt through
  lead: "fleet",
};
const NOTIF_LABEL = {
  order: "open orders", inventory: "open inventory", logistics: "open routes",
  affiliate: "open affiliates", analytics: "open analytics",
  experiment: "open experiments", achievement: "see your profile",
  document: "open documents", ticket: "open chat", enquiry: "open outreach",
  lead: "open the Platform tab",
};

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
      <div class="notif ${i.is_read ? "" : "unread"} ${
        NOTIF_TAB[i.kind] ? "clickable" : ""}"
        ${NOTIF_TAB[i.kind] ? `data-ngo="${i.kind}"` : ""}>
        <div>${esc(i.title)}</div>
        ${i.body ? `<div class="dim" style="font-size:12px">${esc(i.body)}</div>` : ""}
        <div class="dim" style="font-size:11px">${timeAgo(i.created_at)}${
          NOTIF_TAB[i.kind] ? " · " + NOTIF_LABEL[i.kind] : ""}</div>
      </div>`).join("")
    : '<div class="dim">nothing yet</div>');
  document.body.appendChild(panel);
  $("#push-btn").onclick = enablePush;
  // A notification that tells you something happened but not where to deal
  // with it makes you hunt for the tab. Each kind knows its own destination.
  panel.querySelectorAll("[data-ngo]").forEach((el) => el.onclick = () => {
    const tab = NOTIF_TAB[el.dataset.ngo];
    panel.remove();
    if (tab && tab !== S.tab) { S.tab = tab; render(); }
    else if (tab) render();
  });
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
            ${p.active ? "turn off" : "turn on"}</button>
          ${rowActions("promo", p)}</span>` : ""}
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
  wireRows({ promo: list }, renderPromos);
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
  return panZoomMap({
    id: "hq-map",
    pins: pts.map((st) => ({
      lat: st.lat, lng: st.lng,
      color: REGION_COLORS[st.region] || "#8b98a5",
      size: st.kind === "distributor_dc" ? 10 : 6,
      label: st.name, sub: st.city })),
  }) + `<div class="map-legend">${Object.entries(REGION_COLORS).map(([r, c]) =>
      `<span><i style="background:${c}"></i>${r}</span>`).join("")}</div>`;
}

function pnlTable(p) {
  const row = (l, v, neg) => `<tr><td>${l}</td>
    <td style="text-align:right">${neg ? "−" : ""}${money(v)}</td></tr>`;
  return `<table>
    ${row("Revenue", p.revenue_cents)}
    ${row(`COGS${p.cogs_measured_pct
      ? ` — ${p.cogs_measured_pct}% from recipes` : ""}`, p.cogs_cents, 1)}
    ${p.cogs_measured_cents ? `<tr class="sub"><td class="dim">from recipes
        and material costs</td>
      <td style="text-align:right" class="dim">−${money(p.cogs_measured_cents)}</td></tr>
      <tr class="sub"><td class="dim">estimated at
        ${p.assumptions.cogs_bps / 100}% on the rest</td>
      <td style="text-align:right" class="dim">−${money(p.cogs_estimated_cents)}</td></tr>`
      : ""}
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
  <div class="dim" style="font-size:12px;margin-top:6px">${
    p.assumptions.recipes_priced
      ? `${p.assumptions.recipes_priced} product(s) have a priced recipe, so
         their cost is measured rather than assumed. Anything without one
         falls back to ${p.assumptions.cogs_bps / 100}% of revenue — add a
         recipe under Sourcing to replace the guess.`
      : `COGS is an assumption at ${p.assumptions.cogs_bps / 100}% of revenue.
         Give a product a recipe under Sourcing and its real cost is used
         instead.`}
    Wage and per-km cost are assumptions — edit them in data/config.json.</div>`;
}

/* ---------- the fleet: nodes, and who lives on them ----------
   The platform operator's own screen. Capacity is units, not tenants —
   the deck's weights, made clickable — and the two rules that keep the
   bill honest are enforced here as well as on the server: a node with
   room takes the next client, and a node nobody is left on goes away. */
/* Stand a client up — callable from the Platform tab AND from the moment
   the contract gate closes on an engagement page. Fetches the fleet board
   itself when not handed one, and when the client has an engagement, asks
   what size the QUOTE says they are: the operator is offered what was
   sold, not a guess. */
async function standUpClient(slug, eid, name, opts = {}) {
  let f = opts.fleet;
  try { if (!f) f = await api("/api/store/admin/fleet"); }
  catch (err) { toast(err.message); return; }
  let sug = opts.suggestion;
  if (sug === undefined && eid) {
    try { sug = (await api(
      `/api/store/admin/engagements/${eid}/stand-up`)).suggestion; }
    catch { sug = null; }
  }
  const klass = (sug && f.classes[sug.klass]) ? sug.klass : "growing";
  const nodeOptions = (extra) => f.nodes.map((n) =>
    `<option value="${esc(n.id)}">${esc(n.id)} — ${n.free} of ${n.capacity}
      units free</option>`).join("") + (extra || "");

  modal(`<h3>Stand up ${esc(name || slug)}</h3>
    <p class="dim">A tenant of their own: database, config, secrets,
      hostname. Nothing is shared with anyone else's install.</p>
    <div class="row2">
      <div><label>Tenant id <span class="req">required</span></label>
        <input id="t-id" value="${esc(slug || "")}"></div>
      <div><label>Brand</label><input id="t-brand"
        value="${esc(name || "")}"></div>
    </div>
    <label>Hostname</label>
    <input id="t-host" placeholder="acme.localhost"
      value="${slug ? esc(slug) + ".localhost" : ""}">
    ${f.public_suffix ? `<p class="dim" id="t-pubnote">They'll also answer
      publicly at <b id="t-pub"></b> — added automatically, TLS on
      demand.</p>` : ""}
    <div class="row2">
      <div><label>Size</label><select id="t-class">${
        Object.entries(f.classes).map(([k, v]) =>
          `<option value="${k}"${k === klass ? " selected" : ""}>${k}
            — ${v.units || "whole node"} unit${v.units === 1 ? "" : "s"}
            · ${esc(v.note)}</option>`).join("")}</select></div>
      <div><label>Where</label><select id="t-node">${nodeOptions(
        `<option value="new">+ a new node, just for them</option>`)}</select>
      </div>
    </div>
    ${sug ? `<p class="dim">${opsIcon("pen", "btn-ic")} Sized from the
      quote: ${esc(sug.reason)}${sug.shape ? ` · starter layout:
      <b>${esc(sug.shape)}</b>` : ""}</p>` : ""}
    <div id="t-newnode" hidden>
      <div class="row2">
        <div><label>New node id</label>
          <input id="t-nid" placeholder="node-2"
            value="${slug ? "node-" + esc(slug) : ""}"></div>
        <div><label>Size</label><input id="t-nsize" value="4gb"></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" id="t-go">Stand it up</button>
      <button class="btn alt" data-close>Cancel</button>
    </div>`);
  const sel = $("#t-node");
  sel.onchange = () => { $("#t-newnode").hidden = sel.value !== "new"; };
  // The hostname and the new node's name follow the id while nobody has
  // touched them. Opened blank, the old prefill produced ".localhost" —
  // a hostname with no name in front of it, which is not one.
  const follow = (el, make) => {
    if (el.value !== make(slug || "")) el.dataset.touched = "1";
    el.oninput = () => { el.dataset.touched = "1"; };
    return () => { if (!el.dataset.touched) el.value = make($("#t-id").value.trim()); };
  };
  const host = follow($("#t-host"), (v) => v ? `${v}.localhost` : "");
  const nid = follow($("#t-nid"), (v) => v ? `node-${v}` : "");
  const pub = () => { const el = $("#t-pub"); if (el) el.textContent =
    `${$("#t-id").value.trim() || "…"}.${f.public_suffix}`; };
  pub();
  $("#t-id").oninput = () => { host(); nid(); pub(); };
  $("#t-go").onclick = async () => {
    try {
      const out = await api("/api/store/admin/fleet/tenants", {
        body: { id: $("#t-id").value.trim(),
                brand: $("#t-brand").value.trim(),
                hosts: [$("#t-host").value.trim()],
                node: sel.value,
                new_node: ($("#t-nid") || {}).value || "",
                node_size: ($("#t-nsize") || {}).value || "4gb",
                klass: $("#t-class").value,
                engagement_id: eid || 0 } });
      closeModal();
      toast(`${out.tenant} is live on ${out.node}`
        + (out.shipped ? " (shipped to its machine)" : "")
        + (out.public_url ? ` at ${out.public_url}` : "")
        + (out.layout ? ` with a ${out.layout} starter layout` : "")
        + (out.hosting_doc
           ? " — hosting schedule filed in their binder, ready to sign"
           : ""));
      (opts.after || renderFleet)();
    } catch (err) { toast(err.message); }
  };
}

async function renderFleet() {
  const f = await api("/api/store/admin/fleet");
  const bar = (n) => {
    const pct = n.capacity ? Math.round((n.used / n.capacity) * 100) : 0;
    return `<div class="cap-bar" title="${n.used} of ${n.capacity} units">
      <i style="width:${Math.min(100, pct)}%"></i></div>`;
  };
  const nodeCard = (n) => `
    <div class="card node-card">
      <div class="card-head">
        <b>${opsIcon("shield2", "inline-ic")} ${esc(n.id)}</b>
        <span class="dim">${esc(n.size || "")}${n.region
          ? " · " + esc(n.region) : ""} · ${esc(n.provider || "")}</span>
        <span class="dim">${n.used} / ${n.capacity} units${n.free
          ? "" : " · full"}</span>
        ${n.addr ? `<span class="pill ok" title="${esc(n.addr)}">machine
          </span>` : n.id !== "local"
          ? `<span class="pill" title="no address — provision_cmd or the
             Address field turns a booking into a machine">booking</span>`
          : ""}
        ${n.id === "local" ? `<span class="pill">this machine</span>`
          : `<button class="btn alt sm" data-nodekill="${esc(n.id)}"
               ${n.tenants.length ? "disabled title='move or shut down its "
               + "tenants first'" : ""}>Destroy</button>`}
      </div>
      ${bar(n)}
      <div class="sig-rows">${n.tenants.length ? n.tenants.map((t) => `
        <div class="doc-line${t.status === "suspended" ? " dl-awaiting" : ""}">
          <span class="dl-title">
            <b>${esc(t.client ? t.client.name : t.id)}</b>
            <span class="dim">${esc(t.id)}</span>
            ${t.provider ? `<span class="pill ok">runs the platform</span>`
              : ""}
            <span class="pill">${esc(t.class)} · ${t.units}u</span>
            ${t.caps ? `<span class="pill" title="capabilities granted from
              their quote">${t.caps} caps</span>` : ""}
            ${t.billing ? `<span class="pill bad" title="their ${esc(
              t.billing.plan)} subscription — the card processor says so">
              card ${esc(t.billing.status)}</span>` : ""}
            ${t.status === "suspended"
              ? `<span class="pill warn">suspended</span>` : ""}
            <span class="dim">${(t.hosts || []).map(esc).join(" · ")}</span>
          </span>
          <span class="dl-acts" style="grid-template-columns:74px 74px 70px">
            ${t.provider ? "<span></span><span></span><span></span>" : `
            <button class="btn alt sm" data-tactas="${esc(t.id)}"
              title="open their ops app as an admin of THEIR install —
              minted in their own user directory, written to the fleet
              history and their file">Act as admin</button>
            <button class="btn alt sm" data-tcaps="${esc(t.id)}"
              title="what they're entitled to — grants fulfil capability
              asks, and the site grows the pieces new capabilities earn"
              >Capabilities</button>
            <button class="btn alt sm" data-tmove="${esc(t.id)}"
              title="move this client to another node">Move</button>
            <button class="btn alt sm" data-tstatus="${esc(t.id)}"
              data-to="${t.status === "suspended" ? "active" : "suspended"}"
              title="${t.status === "suspended"
                ? "start answering again" : "stop answering, keep every byte"}"
              >${t.status === "suspended" ? "Resume" : "Suspend"}</button>
            <button class="btn alt sm" data-tkill="${esc(t.id)}"
              data-name="${esc(t.client ? t.client.name : t.id)}"
              title="remove from the fleet — data retired, not deleted"
              >Remove</button>`}
          </span>
        </div>`).join("") : `<p class="dim">Empty — this node will be
          destroyed the moment anything else releases it, or destroy it
          now.</p>`}
      </div>
    </div>`;

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Platform</h2>
        <p class="dim">Nodes, and the businesses living on them. Capacity is
          measured in units — a corner shop and a fifty-location
          distributor are not the same load. A node nobody is left on is
          destroyed automatically.</p></div>
      <span class="chips">
        ${f.backup && f.backup.never
          ? `<span class="pill" title="run scripts/backup.py — the DEPLOY
               runbook has the cron line">no backup yet</span>`
          : f.backup && (f.backup.stale || !f.backup.ok)
          ? `<span class="pill bad" title="${esc((f.backup.failures
               && Object.entries(f.backup.failures).map(([t, r]) =>
               `${t}: ${r}`).join("; ")) || "older than a day")}">backup
               ${f.backup.ok ? "stale" : "FAILED"}</span>`
          : f.backup
          ? `<span class="pill ok" title="${esc(f.backup.archive || "")}">
               backed up ${fmtAgo(f.backup.at)}</span>`
          : ""}
        <button class="btn alt" id="node-new">${opsIcon("shield2","btn-ic")}
          New node</button>
        <button class="btn" id="tenant-new">${opsIcon("users","btn-ic")}
          Stand up a client</button></span>
    </div>
    ${f.unplaced.length ? `<div class="card alert">
      <b>${f.unplaced.length} client${f.unplaced.length === 1 ? "" : "s"}
        with no install</b>
      <p class="dim">On the books, but not running on the platform —
        either they host elsewhere, or they are waiting to be stood up.</p>
      <div class="chips">${f.unplaced.map((c) => `
        <button class="chip" data-standup="${esc(c.slug)}"
          data-eid="${c.engagement_id}" data-name="${esc(c.name)}"
          >${esc(c.name)} — stand up</button>`).join("")}</div>
    </div>` : ""}
    ${f.nodes.map(nodeCard).join("")}
    ${f.events.length ? `<div class="card"><b>Fleet history</b>
      <div class="log-lines">${f.events.map((e) => `
        <div class="log-line"><span class="dim">${fmtDate(e.at)}</span>
          <b>${esc(e.actor)}</b>
          <span class="dim">${esc(e.what)}${e.detail
            ? " — " + esc(e.detail) : ""}</span></div>`).join("")}
      </div></div>` : ""}`;

  const nn = $("#node-new");
  if (nn) nn.onclick = () => {
    modal(`<h3>New node</h3>
      <p class="dim">Runs the provisioning command from Admin → fleet when
        one is configured; otherwise it books the node here and you build
        it by hand.</p>
      <div class="row2">
        <div><label>Id</label><input id="n-id" placeholder="node-2"></div>
        <div><label>Size</label><input id="n-size" value="4gb"></div>
      </div>
      <div class="row2">
        <div><label>Region</label><input id="n-region"
          placeholder="ash / fsn1"></div>
        <div><label>Capacity (units)</label>
          <input id="n-units" type="number" value="25"></div>
      </div>
      <label>Address <span class="dim">(optional — the node process's
        URL; set it and tenants are actually shipped there)</span></label>
      <input id="n-addr" placeholder="http://10.0.0.2:8860">
      <div class="modal-foot">
        <button class="btn" id="n-go">Provision</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#n-go").onclick = async () => {
      try {
        await api("/api/store/admin/fleet/nodes", {
          body: { id: $("#n-id").value.trim(), size: $("#n-size").value,
                  region: $("#n-region").value,
                  units: +$("#n-units").value || 25,
                  addr: $("#n-addr").value.trim() } });
        closeModal(); toast("node provisioned"); renderFleet();
      } catch (err) { toast(err.message); }
    };
  };
  const tn = $("#tenant-new");
  if (tn) tn.onclick = () => standUpClient("", 0, "", { fleet: f });
  view().querySelectorAll("[data-standup]").forEach((b) => b.onclick = () =>
    standUpClient(b.dataset.standup, +b.dataset.eid, b.dataset.name,
                  { fleet: f }));

  view().querySelectorAll("[data-nodekill]").forEach((b) => b.onclick =
    async () => {
      if (!confirm(`Destroy ${b.dataset.nodekill}? It carries nothing, so `
        + `nothing is lost — but if it is a real server it is handed back.`))
        return;
      try {
        await api(`/api/store/admin/fleet/nodes/${b.dataset.nodekill}`,
          { method: "DELETE" });
        toast("node destroyed"); renderFleet();
      } catch (err) { toast(err.message); }
    });

  view().querySelectorAll("[data-tstatus]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/store/admin/fleet/tenants/${b.dataset.tstatus}/status`,
          { body: { status: b.dataset.to } });
        toast(b.dataset.to === "suspended"
          ? "suspended — the data is untouched, the hostname says so"
          : "resumed");
        renderFleet();
      } catch (err) { toast(err.message); }
    });

  view().querySelectorAll("[data-tactas]").forEach((b) => b.onclick =
    async () => {
      try {
        const out = await api("/api/store/admin/fleet/tenants/"
          + `${b.dataset.tactas}/act-as`, { body: {} });
        window.open(out.url, "_blank");
        toast(`opened as ${out.account} — logged on the fleet history`);
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-tcaps]").forEach((b) => b.onclick = () => {
    const tid = b.dataset.tcaps;
    const ten = f.nodes.flatMap((n) => n.tenants)
      .find((t) => t.id === tid);
    const cur = new Set(ten.cap_ids || []);
    const all = !cur.size;
    modal(`<h3>Capabilities — ${esc(tid)}</h3>
      <p class="dim">${all
        ? "No grant recorded — <b>everything is on</b>. Ticking boxes "
          + "replaces that with an explicit grant."
        : "What the quote sold, editable — this is the button that "
          + "fulfils a capability ask."}</p>
      <div class="cap-grid">${f.cap_catalog.map((cc) => `
        <label><input type="checkbox" value="${cc.id}" data-cg
          ${all || cur.has(cc.id) ? "checked" : ""}> ${esc(cc.name)}
        </label>`).join("")}</div>
      <label style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <input type="checkbox" id="cg-extend" checked style="width:auto">
        Grow their storefront for newly granted capabilities (additive —
        never rewrites their pages)</label>
      <div class="modal-foot">
        <button class="btn" id="cg-go">Save grant</button>
        <button class="btn alt sm" id="cg-clear" title="back to no grant
          recorded — everything on">Clear grant</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#cg-go").onclick = async () => {
      const caps = [...document.querySelectorAll("[data-cg]:checked")]
        .map((x) => x.value);
      try {
        const out = await api(
          `/api/store/admin/fleet/tenants/${tid}/caps`,
          { body: { caps, extend_site: $("#cg-extend").checked } });
        closeModal();
        const g = out.grown || {};
        const grew = [...(g.sections || []), ...(g.pages || [])];
        toast(`${tid}: ${out.caps.length} capabilities`
          + (out.added && out.added.length
             ? ` (+${out.added.join(", ")})` : "")
          + (grew.length ? ` — site grew: ${grew.join(", ")}` : ""));
        renderFleet();
      } catch (err) { toast(err.message); }
    };
    $("#cg-clear").onclick = async () => {
      try {
        await api(`/api/store/admin/fleet/tenants/${tid}/caps`,
          { body: { clear: true } });
        closeModal(); toast(`${tid}: everything on`); renderFleet();
      } catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-tmove]").forEach((b) => b.onclick = () => {
    modal(`<h3>Move ${esc(b.dataset.tmove)}</h3>
      <p class="dim">Whichever node it leaves behind empty is destroyed.</p>
      <label>To</label>
      <select id="mv-node">${nodeOptions(
        `<option value="new">+ a new node of its own</option>`)}</select>
      <div class="modal-foot">
        <button class="btn" id="mv-go">Move</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#mv-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/fleet/tenants/${b.dataset.tmove}/move`,
          { body: { node: $("#mv-node").value } });
        closeModal(); toast(`moved to ${out.node}`); renderFleet();
      } catch (err) { toast(err.message); }
    };
  });

  view().querySelectorAll("[data-tkill]").forEach((b) => b.onclick = () => {
    modal(`<h3>Remove ${esc(b.dataset.name)}</h3>
      <p class="dim">Their hostname stops answering and they leave the
        fleet. If they were the last tenant on their node, that node is
        destroyed too.</p>
      <label><input type="checkbox" id="k-keep" checked> Retire their data
        to <code>data/retired/</code> rather than deleting it — a business
        that leaves still owns its records, and the week after a
        cancellation is exactly when someone asks for an export.</label>
      <div class="modal-foot">
        <button class="btn" id="k-go">Remove from the fleet</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#k-go").onclick = async () => {
      try {
        const keep = $("#k-keep").checked ? 1 : 0;
        const out = await api(
          `/api/store/admin/fleet/tenants/${b.dataset.tkill}?keep_data=${keep}`,
          { method: "DELETE" });
        closeModal();
        toast(`${b.dataset.name} removed`
          + (out.nodes_destroyed.length
             ? ` — ${out.nodes_destroyed.join(", ")} destroyed with it` : "")
          + (out.kept ? " · data retired" : ""));
        renderFleet();
      } catch (err) { toast(err.message); }
    };
  });
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
        <div class="ach-ic">${opsIcon(a.icon || "shield2")}</div>
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
  const isAdmin = S.user && S.user.is_admin;
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
  const [products, stores, employees, users, emailCfg, emailLog, cyclesList,
         pay, plans] = await Promise.all([
      api("/api/products"), api("/api/stores"), api("/api/admin/employees"),
      api("/api/admin/users"), api("/api/admin/email/config"),
      api("/api/admin/email/log"), api("/api/cycles"),
      api("/api/admin/payments"), api("/api/store/admin/plans")]);
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
  };
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
}
boot();

// ---------- documents & signatures ----------
let DOCS = null;

// ---------- B2B client engagements ----------
// The studio kit run from here: one record per client, documents generated
// from the kit's own templates into the vault, signatures through the vault's
// flow, and the per-client folder generated on demand — never kept by hand.

/* A token that lists its own values — [A / B / C], [Yes / No] — is a set
   of options, not a free blank; render it as a select. Everything else is
   optional by design: blank keeps the brackets. */
function fillField(tok, suggestedVal) {
  const parts = tok.split(" / ").map((x) => x.trim());
  const isChoice = parts.length >= 2 && parts.every(
    (x) => x && x.length <= 24 && !x.includes(":"));
  const label = `<label>[${esc(tok)}]
    <span class="opt">optional</span></label>`;
  if (isChoice) {
    return `${label}<select data-fill="${esc(tok)}">
      <option value="">— leave the brackets —</option>
      ${parts.map((x) => `<option ${suggestedVal === x ? "selected" : ""}
        >${esc(x)}</option>`).join("")}</select>`;
  }
  return `${label}<input data-fill="${esc(tok)}"
    value="${esc(suggestedVal || "")}"
    placeholder="leave blank to keep the brackets">`;
}

function engDatesForm(id, dates) {
  const row = (r) => `<div class="row2" style="margin-bottom:6px">
    <input class="ed-label" placeholder="Milestone" value="${esc(r.label || "")}">
    <div style="display:flex;gap:6px">
      <input class="ed-planned" placeholder="Planned" value="${esc(r.planned || "")}">
      <input class="ed-actual" placeholder="Actual" value="${esc(r.actual || "")}">
      <input class="ed-moved" placeholder="Moved because" value="${esc(r.moved_because || "")}">
    </div></div>`;
  modal(`<h3>The dates that matter</h3>
    <p class="dim">Planned next to actual, with the honest reason when they
      differ. Shown on the client portal. Blank labels are dropped.</p>
    <div id="ed-rows">${(dates.length ? dates : [{}]).map(row).join("")}</div>
    <button class="btn alt sm" id="ed-add">+ row</button>
    <div class="modal-foot"><button class="btn" id="ed-save">Save</button></div>`);
  $("#ed-add").onclick = () => $("#ed-rows").insertAdjacentHTML("beforeend", row({}));
  $("#ed-save").onclick = async () => {
    const out = [...document.querySelectorAll("#ed-rows > div")].map((d) => ({
      label: d.querySelector(".ed-label").value.trim(),
      planned: d.querySelector(".ed-planned").value.trim(),
      actual: d.querySelector(".ed-actual").value.trim(),
      moved_because: d.querySelector(".ed-moved").value.trim(),
    })).filter((r) => r.label);
    try {
      await api(`/api/store/admin/engagements/${id}/dates`,
        { method: "PUT", body: { dates: out } });
      closeModal(); renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
}

/* "3 of 15" for a page that isn't paginated: a page is one printable sheet
   at letter aspect for this content width, and the frame draws a rule at
   every boundary — so the number always names a line you can see. Fields
   growing repaginate, which is why input recounts. */
/* Which page a frame is showing, and how tall a page is on it — the same
   arithmetic wirePageCount uses, so reading and restoring agree. */
function framePageH(doc) {
  return Math.max(420, Math.round((doc.body.clientWidth || 760) * 11 / 8.5));
}
function framePage(frame) {
  try {
    const doc = frame.contentDocument, win = frame.contentWindow;
    if (!doc || !doc.body) return 1;
    return 1 + Math.floor((win.scrollY || 0) / framePageH(doc));
  } catch { return 1; }
}
function goToPage(frame, page) {
  try {
    const doc = frame.contentDocument;
    if (!doc || !doc.body || !page || page < 2) return;
    frame.contentWindow.scrollTo(0, (page - 1) * framePageH(doc));
  } catch {}
}

/* Where you were reading, in terms the other rendering also understands.
   Page number alone drifts: the editor's input boxes are taller than the
   text they replace, so the same page number lands on earlier content. And
   a whole binder section is too coarse — the same offset inside a taller
   section is the same drift again. So: which section, which block inside
   it, and how far past that block — the finest thing both renderings agree
   on. `.bd-note` is skipped because only the editor has it. */
function _anchorParts(frame) {
  const doc = frame.contentDocument, win = frame.contentWindow;
  const y = win.scrollY || 0;
  const topOf = (el) => el.getBoundingClientRect().top + y;
  const kidsOf = (el) => [...el.children].filter(
    (k) => !k.classList.contains("bd-note"));
  return { doc, win, y, topOf, kidsOf };
}

function frameAnchor(frame) {
  try {
    const { doc, y, topOf, kidsOf } = _anchorParts(frame);
    if (!doc || !doc.body) return null;
    const secs = [...doc.querySelectorAll(".binder-doc")];
    let secIdx = -1, scope = doc.body;
    secs.forEach((sec, i) => {
      if (topOf(sec) <= y + 8) { secIdx = i; scope = sec; }
    });
    let elIdx = -1, top = topOf(scope);
    kidsOf(scope).forEach((el, i) => {
      const t = topOf(el);
      if (t <= y + 8) { elIdx = i; top = t; }
    });
    return { secIdx, elIdx, delta: y - top, page: framePage(frame) };
  } catch { return null; }
}

function restoreAnchor(frame, a) {
  if (!a) return;
  try {
    const { doc, win, topOf, kidsOf } = _anchorParts(frame);
    if (!doc || !doc.body) return;
    const secs = [...doc.querySelectorAll(".binder-doc")];
    const scope = a.secIdx >= 0 ? secs[a.secIdx] : doc.body;
    if (!scope) return goToPage(frame, a.page);
    const el = a.elIdx >= 0 ? (kidsOf(scope)[a.elIdx] || scope) : scope;
    win.scrollTo(0, Math.max(0, topOf(el) + (a.delta || 0)));
  } catch {}
}

/* A one-row answer box that grows to what you type: it starts the height
   of the printed write-in line it replaces, so the editor paginates close
   to the page, and it never traps text in a scrollbar. */
function wireAutoGrow(doc) {
  const grow = (el) => {
    el.style.height = "auto";
    el.style.height = (el.scrollHeight + 2) + "px";
  };
  const all = [...doc.querySelectorAll("textarea.ph-area")];
  all.forEach(grow);
  doc.addEventListener("input", (e) => {
    if (e.target.classList && e.target.classList.contains("ph-area"))
      grow(e.target);
  });
  return () => all.forEach(grow);
}

/* Sections fold, and stay folded: a client's page is a long page, and the
   stage you are not working in is noise until you are. Kept per section
   name rather than per client, because the stage you don't care about on
   one client is usually the one you don't care about on the next. */
const FOLDED = (() => {
  try { return JSON.parse(localStorage.getItem("bc_folded") || "{}"); }
  catch { return {}; }
})();

function foldable(key, title, right, body, summary) {
  const shut = !!FOLDED[key];
  return `<div class="card foldable${shut ? " folded" : ""}"
      data-fold="${esc(key)}">
    <div class="card-head fold-head">
      <b><span class="fold-caret">\u25be</span> ${title}</b>
      <span class="fold-sum dim">${esc(summary || "")}</span>
      ${right || ""}
    </div>
    <div class="fold-body">${body}</div>
  </div>`;
}

/* Set by whatever page owns a fold-all control, so folding one section by
   hand still corrects what the control says it will do next. */
let foldAllSync = null;

function wireFolds(scope) {
  scope.querySelectorAll("[data-fold] .fold-head").forEach((h) => {
    h.onclick = (ev) => {
      if (ev.target.closest("button, a, input, select")) return;
      const card = h.closest("[data-fold]");
      const shut = card.classList.toggle("folded");
      FOLDED[card.dataset.fold] = shut;
      try { localStorage.setItem("bc_folded", JSON.stringify(FOLDED)); }
      catch {}
      if (foldAllSync) foldAllSync();
    };
  });
}

/* A title made of parts still has to be one string when it is saved, and
   each part has to be as wide as what is in it. */
function sizeTitle(el) {
  if (!el.classList || !el.classList.contains("bd-title")) return;
  el.size = Math.max((el.value || "").length + 1, el.dataset.part ? 2 : 6);
}
// the tokens that live on the client record, mirrored from the server
const GLOBAL_TOKS = new Set(["CLIENT", "CLIENT NAME", "PROJECT",
  "PROJECT NAME", "CLIENT POC", "APPROVER", "INTERNAL POC", "ORIGINATOR",
  "DATE", "BRAND", "PACKAGE", "VALUE"]);

function composeTitle(scope) {
  const part = (sel) => scope.querySelector(sel);
  const pre = part('input.bd-title[data-part="pre"]');
  const cl = part("input.bd-title-cl");
  const post = part('input.bd-title[data-part="post"]');
  if (!cl) return (pre ? pre.value : "").trim();
  return ((pre ? pre.value : "") + cl.value
          + (post ? post.value : "")).trim();
}

function wirePageCount(frame, label) {
  /* The count is also the way in: the number is a field, so a hundred-page
     binder is one keystroke from any page in it rather than a scrollbar to
     aim at. */
  let doc, win;
  try { doc = frame.contentDocument; win = frame.contentWindow; }
  catch { label.textContent = ""; return () => {}; }
  if (!doc || !doc.body) { label.textContent = ""; return () => {}; }
  label.innerHTML = `Page <input class="pg-in" type="text" inputmode="numeric"
    aria-label="page number — type one and press enter"> of
    <span class="pg-tot"></span>`;
  const box = label.querySelector(".pg-in");
  const tot = label.querySelector(".pg-tot");
  const pageH = () =>
    Math.max(420, Math.round((doc.body.clientWidth || 760) * 11 / 8.5));
  const update = () => {
    const h = pageH();
    doc.documentElement.style.setProperty("--page-h", h + "px");
    const total = Math.max(1, Math.ceil(doc.body.scrollHeight / h));
    const cur = Math.min(total, 1 + Math.floor((win.scrollY || 0) / h));
    if (doc.activeElement !== box && box !== document.activeElement)
      box.value = cur;
    tot.textContent = total;
    box.dataset.total = total;
  };
  const go = () => {
    const total = +box.dataset.total || 1;
    const want = Math.min(total, Math.max(1, parseInt(box.value, 10) || 1));
    const h = pageH();
    // A page you typed is a jump, not a glide: gliding forty pages is two
    // seconds of blur. Neighbouring pages still slide, because there the
    // movement tells you which way you went.
    const near = Math.abs(want - 1 - (win.scrollY || 0) / h) <= 3;
    win.scrollTo({ top: (want - 1) * h,
                   behavior: near ? "smooth" : "auto" });
    box.value = want;
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); go(); }
  });
  box.addEventListener("blur", update);
  box.addEventListener("focus", () => box.select());
  win.addEventListener("scroll", update, { passive: true });
  win.addEventListener("resize", update);
  doc.addEventListener("input", update);
  update();
  return update;
}

async function fillInDoc(did, title, after, anchor) {
  /* The document as the form: bracket tokens, write-in answer lines,
     paragraph boxes and checkboxes, all live where they sit in the text.
     Same-name tokens type together, because the backend fills one value per
     token everywhere it appears — the editor shows that truth live. */
  try {
    const r = await fetch(`/api/store/admin/documents/${did}/editable`,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    const url = URL.createObjectURL(
      new Blob([await r.text()], { type: "text/html" }));
    modal(`<h3>Fill in the document — ${esc(title)}</h3>
      <p class="dim">Type straight into the highlighted fields — named
        blanks, answer lines, paragraphs and checkboxes. Amber is still
        empty; green is filled. Fields with the same name fill together.</p>
      <iframe class="doc-viewer" src="${url}" id="fid-frame"
        title="fill in the document"></iframe>
      <div class="modal-foot">
        <span class="dim" id="fid-pages"></span>
        <span class="dim" id="fid-count" style="margin-right:auto"></span>
        <button class="btn alt" id="fid-sign" title="save the fills, then
          send for signature or sign in the room">Save &amp; sign</button>
        <button class="btn" id="fid-save">Save</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`, "wide");
    const frame = $("#fid-frame");
    let initialChecks = {};
    frame.onload = () => {
      const doc = frame.contentDocument;
      const toks = [...doc.querySelectorAll("input.ph[data-tok]")];
      const areas = [...doc.querySelectorAll(
        "input.ph-line, textarea.ph-area")];
      doc.querySelectorAll("input.ph-check").forEach((c) => {
        initialChecks[c.dataset.region] = c.checked;
      });
      const paint = () => {
        toks.forEach((i) => {
          i.classList.toggle("filled", !!i.value.trim());
          i.size = Math.max((i.value || i.placeholder).length + 2, 10);
        });
        areas.forEach((i) =>
          i.classList.toggle("filled", !!i.value.trim()));
        const left = new Set(toks.filter((i) => !i.value.trim())
          .map((i) => i.dataset.tok)).size
          + areas.filter((i) => !i.value.trim()).length;
        $("#fid-count").textContent = left
          ? `${left} field${left === 1 ? "" : "s"} still empty`
          : "everything is filled in";
      };
      doc.querySelectorAll("input.bd-title").forEach((i) => sizeTitle(i));
      doc.addEventListener("input", (e) => {
        if (e.target.classList && e.target.classList.contains("bd-title"))
          sizeTitle(e.target);
      });
      toks.forEach((inp) => inp.addEventListener("input", () => {
        // a record field moves all of its twins, here as in the binder
        toks.forEach((o) => {
          const same = inp.dataset.global
            ? o.dataset.global === inp.dataset.global
            : (!o.dataset.global && o.dataset.tok === inp.dataset.tok);
          if (o !== inp && same) o.value = inp.value;
        });
        paint();
      }));
      areas.forEach((inp) => inp.addEventListener("input", paint));
      paint();
      wireAutoGrow(doc);
      const recount = wirePageCount(frame, $("#fid-pages"));
      restoreAnchor(frame, anchor);
      recount();
    };
    const saveEdits = async () => {
      const doc = frame.contentDocument;
      const tIn = doc.querySelector('input.bd-title[data-part="pre"]');
      if (tIn && tIn.value !== tIn.defaultValue)
        await api(`/api/store/admin/documents/${did}`,
          { method: "PATCH", body: { title: composeTitle(doc) } });
      const fills = {}, regions = {};
      doc.querySelectorAll("input.ph[data-tok]").forEach((i) => {
        if (i.value.trim()) fills[i.dataset.tok] = i.value.trim();
      });
      doc.querySelectorAll("input.ph-line, textarea.ph-area").forEach((i) => {
        if (i.value.trim()) regions[i.dataset.region] = i.value.trim();
      });
      doc.querySelectorAll("input.ph-check").forEach((c) => {
        // only send toggles that changed — an untouched box is not an edit
        if (c.checked !== initialChecks[c.dataset.region])
          regions[c.dataset.region] = c.checked ? "true" : "false";
      });
      return api(`/api/store/admin/documents/${did}/edit`,
        { body: { fills, regions } });
    };
    $("#fid-save").onclick = async () => {
      try {
        const out = await saveEdits();
        closeModal();
        const rec = (out.record || []).length
          ? " · client record updated everywhere" : "";
        toast((out.unfilled.length
          ? `Saved — ${out.unfilled.length} bracket${
              out.unfilled.length === 1 ? "" : "s"} left`
          : "Saved — no brackets left") + rec);
        if (after) after();
      } catch (err) { toast(err.message); }
    };
    $("#fid-sign").onclick = async () => {
      /* Fill, then sign, without leaving the flow — the edits land first,
         because a signature attests to the text as it stands. */
      try {
        const out = await saveEdits();
        closeModal();
        if (out.party) {
          engSignForm(did, out.party, after);
        } else {
          engSignForm(did, {}, after);
        }
      } catch (err) { toast(err.message); }
    };
  } catch (err) { toast(err.message); }
}

async function binderEditMode(engId, e, anchor) {
  /* The whole binder, editable in place. Each section knows what it is:
     data-doc sections save through the document editor; data-tpl sections
     are blank forms — any edit generates the document for this client,
     then applies the rest. Signed pages sit read-only between them. */
  try {
    const html = await (await fetch(
      `/api/store/admin/engagements/${engId}/binder/editable`,
      { headers: { Authorization: "Bearer " + S.user.token } })).text();
    const frame = $("#bd-frame");
    frame.src = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    $("#bd-edit").hidden = true;
    $("#bd-dl").hidden = true;
    $("#bd-save").hidden = false;
    $("#bd-hint").textContent = "Type anywhere the fields glow — amber is "
      + "empty, green is filled. Signed pages are read-only. Saving writes "
      + "every touched page, and a touched blank form becomes a real "
      + "document for this client.";
    const initialChecks = new Map();
    const initialToks = new Map();
    const initialTitles = new Map();
    let signCard = null;
    frame.onload = () => {
      const doc = frame.contentDocument;
      doc.querySelectorAll("input.ph-check").forEach((c) =>
        initialChecks.set(c, c.checked));
      /* suggested values arrive pre-filled; a card only counts as touched
         by what YOU changed, or every blank form would "save" itself into
         existence on the strength of its own suggestions */
      doc.querySelectorAll("input.ph[data-tok]").forEach((i) =>
        initialToks.set(i, i.value));
      doc.querySelectorAll("input.bd-title").forEach((i) => {
        initialTitles.set(i, i.value);
        sizeTitle(i);
      });
      const paint = (scope) => {
        scope.querySelectorAll("input.ph[data-tok]").forEach((i) => {
          i.classList.toggle("filled", !!i.value.trim());
          i.size = Math.max((i.value || i.placeholder).length + 2, 10);
        });
        scope.querySelectorAll("input.ph-line, textarea.ph-area")
          .forEach((i) => i.classList.toggle("filled", !!i.value.trim()));
      };
      wireAutoGrow(doc);
      const recount = wirePageCount(frame, $("#bd-pages"));
      restoreAnchor(frame, anchor);
      recount();
      /* A record field is the same fact wherever it appears — the client
         does not change from one form to the next — so editing one moves
         every one of them, in every document in the book. A plain token
         stays local to its own page. */
      doc.addEventListener("input", (ev) => {
        const inp = ev.target;
        if (inp.classList && inp.classList.contains("bd-title"))
          sizeTitle(inp);
        if (!inp.dataset || !inp.dataset.global) return;
        doc.querySelectorAll(
          `input[data-global="${inp.dataset.global}"]`).forEach((o) => {
            if (o !== inp) { o.value = inp.value; sizeTitle(o); }
          });
        doc.querySelectorAll(".binder-doc").forEach(paint);
      });
      doc.querySelectorAll(".binder-doc[data-doc], .binder-doc[data-tpl]")
        .forEach((card) => {
          /* Signing lives on the page, not in the footer: a book has many
             signatures and they belong to different pages. Injected here
             rather than rendered server-side, so the printable binder
             stays a printable binder. */
          const sign = doc.createElement("button");
          sign.type = "button";
          sign.className = "bd-sign";
          sign.textContent = "Sign this page";
          sign.title = "saves this page, then opens the pad — or sends it";
          sign.onclick = () => signCard && signCard(card);
          card.insertBefore(sign, card.firstChild);
          card.addEventListener("input", (ev) => {
            const inp = ev.target;
            if (inp.dataset && inp.dataset.tok && !inp.dataset.global) {
              card.querySelectorAll(
                `input.ph[data-tok]`).forEach((o) => {
                  if (o !== inp && o.dataset.tok === inp.dataset.tok)
                    o.value = inp.value;
                });
            }
            paint(card);
          });
          paint(card);
        });
    };
    /* One page's worth of saving, so that Save-the-binder and Sign-this-page
       write by exactly the same rules — a signature that attested to a
       slightly different save path would be a signature to argue about.
       Returns the document id the page now has, or null if there was
       nothing to write.

       Record fields ride along in the ordinary fills — the server knows
       they belong to the client and writes them there instead of baking
       them into whichever page you happened to type on. */
    const saveCard = async (card, force) => {
      const fills = {}, regions = {};
      card.querySelectorAll("input.ph[data-tok]").forEach((i) => {
        if (i.value.trim() && i.value !== initialToks.get(i))
          fills[i.dataset.tok] = i.value.trim();
      });
      card.querySelectorAll("input.ph-line, textarea.ph-area")
        .forEach((i) => {
          if (i.value.trim()) regions[i.dataset.region] = i.value.trim();
        });
      card.querySelectorAll("input.ph-check").forEach((c) => {
        if (c.checked !== initialChecks.get(c))
          regions[c.dataset.region] = c.checked ? "true" : "false";
      });
      // the title is fields on the card: what it is called, and who
      // for — the second being the record's own client field
      const tIn = card.querySelector('input.bd-title[data-part="pre"]');
      const titleChanged = tIn && tIn.value !== initialTitles.get(tIn);
      // A record field is the client's, not this page's: changing the
      // client must not conjure twenty blank forms into existence just
      // because their copy of the client's name moved with it.
      const own = Object.keys(fills).filter((k) => !GLOBAL_TOKS.has(k));
      const touched = own.length || Object.keys(regions).length
        || titleChanged;
      if (card.dataset.doc) {
        if (!touched) return { id: +card.dataset.doc, wrote: false };
        if (titleChanged)
          await api(`/api/store/admin/documents/${card.dataset.doc}`,
            { method: "PATCH", body: { title: composeTitle(card) } });
        let record = [];
        if (Object.keys(fills).length || Object.keys(regions).length) {
          const out = await api(
            `/api/store/admin/documents/${card.dataset.doc}/edit`,
            { body: { fills, regions } });
          record = out.record || [];
        }
        return { id: +card.dataset.doc, wrote: true, record };
      }
      if (!touched && !force) return null;
      /* a blank form someone wrote on becomes a real document — the
         token fills ride along at generation; the regions land right
         after, on the same scan order. Signing one generates it too:
         you cannot sign a page that does not exist yet. */
      const out = await api(
        `/api/store/admin/engagements/${engId}/docs`,
        { body: { template_path: card.dataset.tpl, fills } });
      if (Object.keys(regions).length)
        await api(`/api/store/admin/documents/${out.doc_id}/edit`,
          { body: { fills: {}, regions } });
      card.dataset.doc = out.doc_id;
      return { id: out.doc_id, wrote: true, generated: true };
    };

    /* Sign the page you are looking at, from inside the book. The pad is
       the same one an emailed signer gets — drawn with the mouse — and the
       page is saved first, because a signature attests to the text as it
       stands. */
    signCard = async (card) => {
      try {
        const out = await saveCard(card, true);
        closeModal();
        engSignForm(out.id, { name: e.approver_name, email: e.approver_email },
          () => renderEngagement(engId));
      } catch (err) { toast(err.message); }
    };

    $("#bd-save").onclick = async () => {
      const doc = frame.contentDocument;
      const cards = [...doc.querySelectorAll(
        ".binder-doc[data-doc], .binder-doc[data-tpl]")];
      let saved = 0, generated = 0, failed = 0, recordChanged = false;
      for (const card of cards) {
        try {
          const out = await saveCard(card);
          if (!out || !out.wrote) continue;
          if (out.generated) generated += 1; else saved += 1;
          if ((out.record || []).length) recordChanged = true;
        } catch (err) { failed += 1; toast(
          `${card.dataset.name || "page"}: ${err.message}`); }
      }
      closeModal();
      toast(`Binder saved — ${saved} page${saved === 1 ? "" : "s"} updated`
        + (recordChanged ? ", client record updated everywhere" : "")
        + (generated ? `, ${generated} generated from blank forms` : "")
        + (failed ? `, ${failed} failed` : ""));
      renderEngagement(engId);
    };
  } catch (err) { toast(err.message); }
}

async function renderClients() {
  if (S.engId) return renderEngagement(S.engId);
  const data = await api("/api/store/admin/engagements"
    + (S.engArchived ? "?archived=1" : ""));
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Clients (B2B)</h2>
        <p class="dim">Studio engagements — the kit's stages, documents and
          signatures, run from one place.</p></div>
      <div class="top-actions" style="display:flex;gap:8px">
        ${data.archived_count || S.engArchived ? `<button
          class="btn alt ${S.engArchived ? "on" : ""}" id="eng-arch-toggle"
          title="clients put away — everything they have is intact"
          >Archived${data.archived_count ? ` (${data.archived_count})`
            : ""}</button>` : ""}
        <button class="btn" id="eng-new">${opsIcon("handshake","btn-ic")} New client</button>
      </div>
    </div>
    ${data.kit_available ? "" : `<div class="card alert"><b>The template kit
      isn't on this install</b><p class="dim">docs/business-control-b2b-client/
      is missing, so documents can't be generated here — records and exports
      still work.</p></div>`}
    <div id="eng-list">${data.engagements.map((e) => `
      <div class="doc-card eng-card" data-eng="${e.id}"
        style="cursor:pointer">
        <div class="eng-top">
          <span class="doc-ic">${opsIcon("handshake")}</span>
          <div class="doc-main"><b>${esc(e.name)}</b>
            <span class="dim">${esc(e.stage.replace(/^(\d\d)-/, "$1 · ").replace(/-/g, " "))} · ${
              e.package ? "package " + esc(e.package) + " · " : ""}${
              e.value_cents ? money(e.value_cents) + " · " : ""}content ${
              e.content_pct}% · ${e.docs} document${e.docs === 1 ? "" : "s"}, ${
              e.signed} signed${e.portal_seen_at
                ? " · client looked " + fmtDate(e.portal_seen_at) : ""}</span></div>
          ${e.tenant_id ? `<span class="pill ok" title="this client runs
            on the platform — their install answers at
            ${esc(e.tenant_id)}.localhost">${opsIcon("shield2","btn-ic")}
            ${esc(e.tenant_id)}</span>` : ""}
          ${(e.warnings || []).map((w) =>
            `<span class="pill warn">${esc(w)}</span>`).join("")}
          ${e.status === "closed" ? '<span class="pill">closed</span>' : ""}
          ${e.launch_target ? `<span class="dim">launch ${esc(e.launch_target)}</span>` : ""}
          <button class="btn alt sm" data-engarch="${e.id}"
            data-name="${esc(e.name)}"
            data-on="${e.status === "archived" ? 1 : 0}">${
            e.status === "archived" ? "Restore" : "Archive"}</button>
          <button class="btn alt sm" data-engdel="${e.id}"
            data-name="${esc(e.name)}" data-docs="${e.docs}"
            data-signed="${e.signed}">Delete</button>
        </div>
      </div>`).join("")
      || `<div class="card empty"><span class="e-ic">${opsIcon("handshake")}</span>
          <b>${S.engArchived ? "Nothing archived" : "No clients yet"}</b>
          <p class="dim">${S.engArchived
            ? "Archiving a client puts them away without removing anything."
            : "Create one, then generate its documents from the kit's templates."
          }</p></div>`}</div>`;
  $("#eng-new").onclick = () => engForm(null);
  const at = $("#eng-arch-toggle");
  if (at) at.onclick = () => { S.engArchived = !S.engArchived;
    renderClients(); };
  view().querySelectorAll("[data-engarch]").forEach((b) => b.onclick =
    async (ev) => {
      ev.stopPropagation();
      const on = b.dataset.on === "1";
      try {
        await api(`/api/store/admin/engagements/${b.dataset.engarch}/archive`,
          { body: { archived: !on } });
        toast(on ? `${b.dataset.name} restored`
          : `${b.dataset.name} archived — everything they have is intact`);
        renderClients();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-eng]").forEach((el) => el.onclick = (ev) => {
    // the row is a link; its own buttons are not
    if (ev.target.closest("[data-engdel], [data-engarch]")) return;
    S.engId = +el.dataset.eng; render();
  });
  view().querySelectorAll("[data-engdel]").forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation();
    const n = +b.dataset.docs, sg = +b.dataset.signed;
    modal(`<h3>Delete ${esc(b.dataset.name)}?</h3>
      <p class="dim">This removes the client, their stages, dates, activity
        and exported folder${n ? `, and the ${n} document${n === 1 ? "" : "s"}
        filed under them` : ""}.</p>
      ${sg ? `<p class="dim"><b>${sg} signed document${sg === 1 ? " is" :
        "s are"} kept.</b> A signature is evidence that a named person
        agreed to a specific text on a date — deleting the client does not
        un-agree it. ${sg === 1 ? "It moves" : "They move"} to Documents →
        Archived, where deleting ${sg === 1 ? "it" : "them"} is its own
        decision.</p>` : ""}
      <p class="dim">There is no undo.</p>
      <div class="modal-foot">
        <button class="btn danger" id="ed-go">Delete the client</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#ed-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/engagements/${b.dataset.engdel}`,
          { method: "DELETE" });
        closeModal();
        toast(`${out.name} deleted — ${out.removed} document${
          out.removed === 1 ? "" : "s"} removed`
          + (out.kept ? `, ${out.kept} signed kept in Documents` : ""));
        S.engId = null;
        renderClients();
      } catch (err) { toast(err.message); }
    };
  });
}

function engForm(e) {
  modal(`<h3>${e ? "Edit client" : "New client"}</h3>
    <label>Client name <span class="req">required</span></label>
    <input id="ef-name" value="${esc(e ? e.name : "")}">
    <div class="row2">
      <div><label>Package (A / B / C)</label>
        <input id="ef-pkg" value="${esc(e ? e.package : "")}"></div>
      <div><label>Value ($)</label>
        <input id="ef-val" type="number" min="0"
          value="${e && e.value_cents ? e.value_cents / 100 : ""}"></div>
    </div>
    <div class="row2">
      <div><label>Client POC name</label>
        <input id="ef-appr" value="${esc(e ? e.approver_name : "")}"></div>
      <div><label>Client POC email</label>
        <input id="ef-email" type="email" value="${esc(e ? e.approver_email : "")}"></div>
    </div>
    <div class="row2">
      <div><label>Internal POC
          <span class="opt">must accept if it isn't you</span></label>
        <input id="ef-ipoc" value="${esc(e ? e.internal_poc || ""
          : (S.user ? S.user.name : ""))}"></div>
      <div><label>Originator</label>
        <input id="ef-orig" value="${esc(e ? e.originator || ""
          : (S.user ? S.user.name : ""))}"></div>
    </div>
    <div class="row2">
      <div><label>Launch target</label>
        <input id="ef-launch" placeholder="e.g. 2026-11-06"
          value="${esc(e ? e.launch_target : "")}"></div>
      <div><label>Status</label>
        <select id="ef-status">
          <option value="active" ${!e || e.status === "active" ? "selected" : ""}>active</option>
          <option value="closed" ${e && e.status === "closed" ? "selected" : ""}>closed</option>
          <option value="archived" ${e && e.status === "archived" ? "selected" : ""}>archived</option>
        </select></div>
    </div>
    <div class="row2">
      <div><label>Staging URL</label>
        <input id="ef-stag" value="${esc(e ? e.staging_url : "")}"></div>
      <div><label>Live URL</label>
        <input id="ef-live" value="${esc(e ? e.live_url : "")}"></div>
    </div>
    <div class="row2">
      <div><label>Content received (%)</label>
        <input id="ef-pct" type="number" min="0" max="100"
          value="${e ? e.content_pct : 0}"></div>
      <div><label>This week, in one sentence (shown on the portal)</label>
        <input id="ef-week" value="${esc(e ? e.week_note : "")}"></div>
    </div>
    <label>Blockers — one per line, empty when none (shown on the portal)</label>
    <textarea id="ef-block" rows="2">${esc(e ? e.blockers : "")}</textarea>
    <label>Notes (internal)</label>
    <textarea id="ef-notes" rows="3">${esc(e ? e.notes : "")}</textarea>
    ${e ? "" : `<label>Attachments
        <span class="opt">filed with the client, listed in the binder</span>
      </label>
      <input type="file" id="ef-files" multiple
        accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.csv,.txt">`}
    <div class="modal-foot"><button class="btn" id="ef-save">Save</button></div>`);
  $("#ef-save").onclick = async () => {
    const body = {
      name: $("#ef-name").value.trim(),
      package: $("#ef-pkg").value.trim(),
      value_cents: Math.round((+$("#ef-val").value || 0) * 100),
      approver_name: $("#ef-appr").value.trim(),
      approver_email: $("#ef-email").value.trim(),
      internal_poc: $("#ef-ipoc").value.trim(),
      originator: $("#ef-orig").value.trim(),
      launch_target: $("#ef-launch").value.trim(),
      staging_url: $("#ef-stag").value.trim(),
      live_url: $("#ef-live").value.trim(),
      notes: $("#ef-notes").value.trim(),
      status: $("#ef-status").value,
      content_pct: Math.max(0, Math.min(100, +$("#ef-pct").value || 0)),
      week_note: $("#ef-week").value.trim(),
      blockers: $("#ef-block").value.trim(),
    };
    try {
      if (e) await api(`/api/store/admin/engagements/${e.id}`,
        { method: "PATCH", body });
      else {
        const out = await api("/api/store/admin/engagements",
          { method: "POST", body });
        S.engId = out.id;
        // attachments ride in with the client: each becomes its own vault
        // document, filed under the first stage, listed in the binder
        const files = [...($("#ef-files")?.files || [])];
        for (const f of files) {
          try {
            const doc = await api("/api/store/admin/documents", { body: {
              title: f.name.slice(0, 190), category: "other",
              party_kind: "partner", party_name: body.name,
            } });
            const fd = new FormData();
            fd.append("file", f);
            const up = await fetch(
              `/api/store/admin/documents/${doc.id}/file`,
              { method: "POST", body: fd,
                headers: { Authorization: "Bearer " + S.user.token } });
            if (!up.ok) throw new Error((await up.json()).detail);
            await api(`/api/store/admin/engagements/${out.id}/attach`,
              { body: { doc_id: doc.id, stage: "01-potential-customer",
                        side: "to_client" } });
          } catch (err) { toast(`${f.name}: ${err.message}`); }
        }
        if (files.length) toast(`${files.length} attachment${
          files.length === 1 ? "" : "s"} filed`);
      }
      closeModal(); render();
    } catch (err) { toast(err.message); }
  };
}

async function renderEngagement(id) {
  let d;
  try { d = await api(`/api/store/admin/engagements/${id}`); }
  catch { S.engId = null; return renderClients(); }
  const e = d.engagement;
  const byStage = {};
  d.docs.forEach((x) => (byStage[x.stage] = byStage[x.stage] || []).push(x));

  const docRowE = (x) => `
    <div class="doc-line foldable${FOLDED["doc:" + x.id] ? " folded" : ""}${
      x.signed ? " dl-signed" : x.awaiting ? " dl-awaiting" : ""}"
      data-fold="doc:${x.id}">
      <span class="dl-title fold-head"><span class="fold-caret">\u25be</span>
        <b title="${esc(x.title)}">${esc(x.title)}</b>
        <span class="dl-meta">
          <span class="dm-state">${x.awaiting && x.signed
            /* both at once is a real state — two parties, one of them
               done — and a slot that shows only the newer of the two
               would report a half-signed contract as unsigned */
            ? `<span class="pill warn">${x.signed} of ${
                x.signed + x.awaiting} signed</span>`
            : x.awaiting ? `<span class="pill warn">${x.awaiting} awaiting</span>`
            : x.signed ? `<span class="pill ok">${x.signed} signed</span>`
            : ""}</span>
          <span class="dm-side"><span class="pill ${
            x.side === "internal" ? "warn" : "ok"}">${
            x.side === "internal" ? "internal" : "to client"}</span></span>
          <span class="dm-blanks fold-sum dim">${x.blanks
            ? x.blanks + " blank" + (x.blanks === 1 ? "" : "s") + " left"
            : "no blanks left"}</span>
        </span>
      </span>
      <span class="dl-acts fold-body">
        <span class="ga-slot">${x.blanks ? `<button class="btn alt sm"
          data-engfill="${x.id}" title="the brackets still unfilled — same
          form as generation, shorter each time">Fill (${x.blanks})</button>`
          : ""}</span>
        <button class="btn alt sm" data-engview="${x.id}"
          data-kind="${x.has_body ? "body" : "file"}" data-ext="${x.ext || ""}"
          data-signed="${x.signed || 0}"${x.quote ? ' data-quote="1"' : ""}
          title="${x.quote
            ? "opens the quote as the bench presents it"
            : "opens the document — signatures shown on it"}">View</button>
        <button class="btn alt sm" data-engdl="${x.id}"
          data-kind="${x.has_body ? "body" : "file"}" data-ext="${x.ext || ""}"
          data-name="${esc(x.filename || x.title)}">PDF</button>
        <button class="btn alt sm" data-engsign="${x.id}">Sign</button>
        <button class="btn alt sm" data-engopen="${esc(x.title)}">Open</button>
        <button class="btn alt sm" data-engscan="${x.id}"
          data-stage="${x.stage}" data-side="${x.side}"
          data-title="${esc(x.title)}" title="file the signed paper's scan
          or photo beside this document">Scan</button>
        <button class="btn alt sm" data-engrm="${x.id}"
          data-title="${esc(x.title)}">Remove</button>
      </span>
    </div>`;

  // Two kit stages can share one client folder (the enquiry scripts file
  // under consultation); merge them so the page shows the client's stages,
  // exactly like the exported folder does.
  const merged = [];
  d.stages.forEach((st) => {
    const prev = merged.find((m) => m.client_stage === st.client_stage);
    if (prev) { prev.templates = prev.templates.concat(st.templates);
      prev.kit = prev.kit.concat([st.stage]); }
    else merged.push({ ...st, kit: [st.stage] });
  });

  const stageName = (st) => st.replace(/^(\d\d)-/, "$1 · ").replace(/-/g, " ");

  /* The one thing to do next, derived from the same gates the stage is.
     Each gate names the kit stage whose templates satisfy it, so "generate
     the right document for THIS client" is one click, prefilled from the
     record. */
  const GATE_STAGE = {
    proposal_accepted: "03-proposal", contract_signed: "04-agreement",
    requirements_signed: "06-requirements",
    art_direction_signed: "07-brand-exploration",
    round1_signed_off: "08-build", round2_signed_off: "08-build",
    handover_accepted: "10-handover",
    ongoing_support_agreed: "11-aftercare",
  };

  /* The gates as a track: done · now · waiting on them · waiting on us ·
     upcoming. "Waiting on the client" is a real state, not a mood — a
     signature request that is out, or a payment link that is unpaid, is
     time we cannot spend. Everything derives from the same gates the stage
     does, so the picture and the list can never disagree. */
  function gateState(g, isNext) {
    if (g.passed_at) return "done";
    const doc = d.docs.find((x) => x.id === g.doc_id);
    if (doc && doc.awaiting) return "client";
    if (g.kind === "money" && g.has_payment_link) return "client";
    return isNext ? "now" : "later";
  }
  const STATE_LABEL = { done: "done", now: "do this next",
    client: "waiting on the client", later: "upcoming" };

  function trackHtml() {
    const live = d.gates.filter((g) => g.active);
    const firstOpen = live.find((g) => !g.passed_at);
    return `<div class="track">
      ${live.map((g) => {
        const st = gateState(g, g === firstOpen);
        return `<div class="tk-node tk-${st}"
          title="${esc(g.label)} — ${STATE_LABEL[st]}">
          <span class="tk-dot"></span>
          <span class="tk-label">${esc(g.label)}</span>
        </div>`;
      }).join("")}
    </div>
    <div class="tk-key">
      <span class="tk-k tk-done">done</span>
      <span class="tk-k tk-now">do next</span>
      <span class="tk-k tk-client">waiting on the client</span>
      <span class="tk-k tk-later">upcoming</span>
    </div>`;
  }

  /* What can run alongside what. The gates are a chain — each waits on the
     one before — but the WORK inside a stage mostly isn't: content
     gathering, brand exploration and build overlap in every real project,
     which is exactly what a client asks when they ask "can we start X
     while Y finishes?" */
  const PARALLEL = [
    { name: "Discovery & requirements", from: "proposal_accepted",
      to: "requirements_signed", lane: 0 },
    { name: "Content & assets from the client", from: "contract_signed",
      to: "round2_signed_off", lane: 1,
      note: "starts at kickoff and runs to the end — the critical path" },
    { name: "Brand exploration", from: "requirements_signed",
      to: "art_direction_signed", lane: 2, optional: true },
    { name: "Build", from: "requirements_signed", to: "round2_signed_off",
      lane: 2, note: "overlaps brand once the direction is signed" },
    { name: "Launch & handover", from: "round2_signed_off",
      to: "handover_accepted", lane: 0 },
    { name: "Money", from: "contract_signed", to: "final_invoice_paid",
      lane: 3, note: "deposit up front, final before launch" },
    { name: "Ongoing — security, monitoring, updates, support",
      from: "handover_accepted", to: "ongoing_support_agreed", lane: 1,
      note: "continuous work, carried by the care plan agreed in the "
        + "contract — it starts when handover ends and does not stop" },
  ];

  function ganttModal() {
    const live = d.gates.filter((g) => g.active);
    const idx = {};
    live.forEach((g, i) => (idx[g.gate] = i));
    const n = live.length || 1;
    const pct = (i) => (i / n) * 100;
    const bars = PARALLEL.filter((b) => idx[b.from] !== undefined
      && idx[b.to] !== undefined).map((b) => {
      const a = idx[b.from], z = idx[b.to];
      const doneTo = live.filter((g) => g.passed_at).length;
      const state = z < doneTo ? "done" : a <= doneTo ? "now" : "later";
      return `<div class="gt-row">
        <span class="gt-name">${esc(b.name)}${b.optional
          ? ' <span class="opt">optional</span>' : ""}</span>
        <span class="gt-track">
          <span class="gt-bar gt-${state}"
            style="left:${pct(a)}%;width:${Math.max(pct(z - a), 6)}%"
            title="${esc(b.note || "")}"></span>
        </span>
      </div>`;
    }).join("");
    modal(`<h3>What can run in parallel</h3>
      <p class="dim">The stages are a chain — each waits on the one before.
        The work between them is not: bars on different rows that overlap
        horizontally can be in flight at the same time.</p>
      <div class="gt">
        <div class="gt-row gt-head"><span class="gt-name"></span>
          <span class="gt-track">${live.map((g, i) =>
            `<span class="gt-tick" style="left:${pct(i)}%"
               title="${esc(g.label)}">${g.passed_at ? "•" : "○"}</span>`)
            .join("")}</span></div>
        ${bars}
      </div>
      <p class="dim" style="margin-top:14px">Content is the one that decides
        the launch date — it starts at kickoff and runs the whole way, so a
        week lost there is a week lost at the end.</p>
      <div class="modal-foot"><button class="btn" data-close>Close</button></div>`,
      "wide");
  }

  function nextStep() {
    const g = d.gates.find((x) => x.active && !x.passed_at);
    if (!g) return { text: "Every stage has closed — aftercare from here.",
                     actions: [] };
    const actions = [];
    if (g.kind === "money") {
      actions.push({ label: g.has_payment_link ? "Check payment"
        : "Payment link", act: g.has_payment_link ? "paycheck" : "paylink",
        gate: g.gate });
      actions.push({ label: "Confirm by hand", act: "pass", gate: g.gate });
      return { text: `${g.label} is the open stage. Send the link with the `
        + "invoice, or confirm when the money arrives.", actions };
    }
    if (g.doc_id) {
      const doc = d.docs.find((x) => x.id === g.doc_id) || {};
      if (doc.awaiting)
        return { text: `${g.label}: "${doc.title}" is out for signature — `
          + "chase warmly, or reopen and relink if it went to the wrong "
          + "person.", actions: [] };
      if (doc.blanks)
        return { text: `${g.label}: "${doc.title}" still has `
          + `${doc.blanks} blank${doc.blanks === 1 ? "" : "s"} — finish it, `
          + "then send it for signature.",
          actions: [{ label: `Fill blanks (${doc.blanks})`, act: "fill",
                      doc: doc.id }] };
      return { text: `${g.label}: "${doc.title}" is ready — send it for `
        + "signature.",
        actions: [{ label: "Send for signature", act: "sign", doc: g.doc_id }] };
    }
    const stage = GATE_STAGE[g.gate];
    const st = merged.find((m) => m.kit.includes(stage))
      || d.stages.find((x) => x.stage === stage);
    const stageDocs = (byStage[stage] || []);
    if (stageDocs.length)
      return { text: `${g.label}: a document is filed under this stage — `
        + "link the one whose signature closes the stage.",
        actions: [{ label: "Link doc", act: "link", gate: g.gate }] };
    const tpls = (st && st.templates) || [];
    return { text: `${g.label} is the open stage, and nothing is drafted `
      + `yet — `
      + `generate it for ${esc(e.name)}.`,
      actions: tpls.slice(0, 4).map((t) => (
        { label: `Generate: ${t.name}`, act: "gen", path: t.path })) };
  }

  const gateRow = (g) => {
    if (!g.active) return "";
    /* The pill says where the gate stands, in one word that is the same
       width on every row; who and when belong with the evidence, because
       that is the sentence they finish — "signed, by Tom, on the 26th, on
       this document" reads as one fact, not four columns. */
    const state = g.passed_at
      ? `<span class="pill ok">${g.via === "signature"
          ? "signed" : "confirmed"}</span>`
      : g.doc_id
        ? '<span class="pill warn">awaiting</span>'
        : '<span class="pill">open</span>';
    const by = [g.signed_by || g.actor || "",
      g.passed_at ? fmtDate(g.passed_at) : ""].filter(Boolean).join(", ");
    const docBit = [g.doc_title ? esc(g.doc_title)
      : g.note && !g.doc_id ? esc(g.note) : "",
      g.passed_at ? esc(by) : ""].filter(Boolean).join(" · ");
    /* Three fixed slots, right to left: [payment] [link] [pass]. A row that
       lacks a button keeps its empty slot, so Link doc sits under Link doc
       and Confirm under Mark closed all the way down. */
    const slot = (h) => `<span class="ga-slot">${h || ""}</span>`;
    const pay = g.kind === "money" && !g.passed_at
      ? (g.has_payment_link
          ? `<button class="btn alt sm" data-gate-paycheck="${g.gate}"
               title="ask Stripe whether the link was paid">Check pay</button>`
          : `<button class="btn alt sm" data-gate-paylink="${g.gate}"
               title="a Stripe checkout link to send with the invoice">Pay
               link</button>`)
      : "";
    const acts = g.passed_at || g.doc_id
      ? slot("") + slot("") + slot(`<button class="btn alt sm"
          data-gate-reopen="${g.gate}">Reopen</button>`)
      : slot(pay)
        + slot(`<button class="btn alt sm" data-gate-link="${g.gate}">Link
            doc</button>`)
        + slot(`<button class="btn alt sm" data-gate-pass="${g.gate}"
            data-kind="${g.kind}">${g.kind === "money"
              ? "Confirm" : "Mark closed"}</button>`);
    /* The schedule, on the gate it schedules. Planned comes from the
       Dates table (matched server-side); overdue = planned in the past on
       a gate still open. When the gate closed, the actual date (stamped
       at close, or written by hand) outranks the plan. */
    const today = new Date().toISOString().slice(0, 10);
    const dateBit = g.passed_at
      ? (g.actual_date ? `<span class="pill ok">done ${esc(g.actual_date)}
          </span>` : "")
      : g.planned
        ? `<span class="pill ${g.planned < today ? "bad" : ""}"
             title="from the Dates table">${g.planned < today ? "overdue · "
             : "planned "}${esc(g.planned)}</span>`
        : "";
    return `<div class="gate-line">
      <b title="${esc(g.label)}">${esc(g.label)}</b>
      <span class="gl-state">${state}</span>
      <span class="gl-doc dim" title="${docBit}">${docBit}</span>
      <span class="gl-date">${dateBit}</span>
      <span class="gl-closes dim">stage ${esc(stageName(g.stage))}</span>
      <span class="gl-acts">${acts}</span>
    </div>`;
  };

  const stageCard = (st) => {
    const docs = st.kit.flatMap((k) => byStage[k] || []);
    if (!docs.length && !st.templates.length) return "";
    const label = "Stage " + esc(st.client_stage
      .replace(/^\d\d-/, (m) => m.slice(0, 2) + " · ").replace(/-/g, " "));
    const sum = [docs.length ? `${docs.length} document${
        docs.length === 1 ? "" : "s"}` : "",
      st.templates.length ? `${st.templates.length} to generate` : ""]
      .filter(Boolean).join(" · ");
    const report = docs.find((x) => x.title.startsWith("Progress update"));
    return foldable(`stage:${st.client_stage}`, label,
      `<button class="btn alt sm" data-report="${esc(st.client_stage)}"
        title="write this stage up for the client — where it stands, what
        they have, what is waiting on them">${report
          ? "Refresh update" : "Progress update"}</button>`
      + (report ? `<button class="btn alt sm" data-send="${report.id}"
          title="email it to the client as a link to their own portal — the
          live document, not a PDF that stops being true">Send</button>` : ""),
      `${docs.length ? `<div class="sig-rows">${docs.map(docRowE).join("")}</div>` : ""}
      ${st.templates.length ? `<div class="tpl-list">
        <span class="tpl-head">Generate for ${esc(e.name)}</span>
        ${st.templates.map((t) => `<button class="tpl-line"
          data-gen="${esc(t.path)}">
          <span class="tpl-plus">+</span>
          <span class="tpl-name">${esc(t.name)}</span>
          <span class="pill ${t.side === "internal" ? "warn" : "ok"}">${
            t.side === "internal" ? "internal" : "to client"}</span>
        </button>`).join("")}</div>` : ""}`,
      sum);
  };

  view().innerHTML = `
    <div class="page-head">
      <div>
        <button class="btn alt sm" id="eng-back">← All clients</button>
        <h2 style="display:inline;margin-left:8px">${esc(e.name)}</h2>
        <p class="dim"><span class="pill ok">stage: ${esc(stageName(d.current_stage))}</span>
          ${e.package ? " package " + esc(e.package) + " · " : ""}${
          e.value_cents ? money(e.value_cents) + " · " : ""}${
          e.approver_name ? "client POC " + esc(e.approver_name) + " · " : ""}${
          e.internal_poc ? "internal POC " + esc(e.internal_poc)
            + (e.internal_poc_status === "pending"
                ? ' <span class="pill warn">unconfirmed</span>'
                : e.internal_poc_status === "declined"
                  ? ' <span class="pill bad">declined</span>' : "")
            + " · " : ""}${
          e.launch_target ? "launch " + esc(e.launch_target) : ""}</p>
      </div>
      <div class="top-actions eng-actions">
        <button class="btn alt sm" id="eng-edit">Edit</button>
        <button class="btn alt sm" id="eng-dates">Dates</button>
        ${e.portal_url
          ? `<button class="btn alt sm" id="eng-portal-copy"
               title="the client's live roadmap — everything on it is the
               to-client side only">Portal link</button>
             <button class="btn alt sm" id="eng-portal-rotate"
               title="the old link dies the moment a new one exists">Rotate</button>
             <button class="btn alt sm" id="eng-portal-revoke">Revoke</button>`
          : `<button class="btn alt sm" id="eng-portal-make">Create
               portal</button>`}
        <button class="btn alt sm" id="eng-export" title="write the folder
          tree under data/exports/clients/">Export</button>
        <button class="btn alt sm" id="eng-binder" title="the whole packet
          as one PDF — cover, contents, then every client-side paper with
          its signatures">Binder PDF</button>
        <button class="btn sm" id="eng-bundle" title="zip of the to-client
          side only — the internal wall holds">Client bundle</button>
        <button class="btn alt sm" id="eng-bundle-send" title="email the
          client a link to their roadmap, where the same bundle downloads
          fresh">Send bundle</button>
        <button class="btn alt sm" id="eng-quote" title="price this client on
          the bench, then file the quote as a paper — it opens where the last
          quote left off">Quote</button>
        ${S.meta && S.meta.is_provider
          ? (e.tenant_id
            ? `<button class="btn alt sm" id="eng-launch" title="put their
                 install on its real address, with the capabilities the
                 quote sold">${e.live_url ? "Relaunch" : "Launch site"}
               </button>`
            : `<button class="btn alt sm" id="eng-standup" title="a tenant
                 of their own — sized and shaped from the quote, on a node
                 with room">Stand up</button>`)
          : ""}
      </div>
    </div>
    ${e.internal_poc_status === "pending" && S.user
        && e.internal_poc_user_id === S.user.id ? `
    <div class="card" style="border-left:3px solid var(--warn)">
      <b>You've been named internal POC for ${esc(e.name)}</b>
      <p class="dim">${esc(e.originator || "Someone")} put your name on this
        client. It's a job, not a label — take it or hand it back, and
        declining tells them so nobody assumes it's covered.</p>
      <div class="chips">
        <button class="btn sm" id="poc-accept">I'm the internal POC</button>
        <button class="btn alt sm" id="poc-decline">Decline</button>
      </div>
    </div>` : ""}
    ${(() => { const n = nextStep(); return `
    <div class="card" style="border-left:3px solid var(--accent, #7b5cff)">
      <b>Next step</b>
      <p class="dim">${n.text}</p>
      ${n.actions.length ? `<div class="chips">${n.actions.map((a, i) =>
        `<button class="btn ${i ? "alt " : ""}sm" data-next="${i}">${a.label}</button>`)
        .join("")}</div>` : ""}
    </div>`; })()}
    ${foldable("gates", "Stages",
      `<button class="btn alt sm" id="eng-gantt">Gantt chart</button>`,
      `<p class="dim">Where the project is, is the first stage that hasn't
         closed — a stage that closes on a signature reads its state from
         the linked document, live.</p>
       ${trackHtml()}
       <div class="sig-rows">${d.gates.map(gateRow).join("")}</div>`,
      (() => { const live = d.gates.filter((g) => g.active);
        const done = live.filter((g) => g.passed_at).length;
        return `${done} of ${live.length} closed`; })())}
    ${merged.some((st) => st.kit.some((k) => byStage[k]) || st.templates.length)
      ? `<div class="fold-all"><span class="dim">Stages</span>
          <button class="btn alt sm" id="fold-all">Fold all</button></div>` : ""}
    ${merged.map(stageCard).join("")}
    ${d.log.length ? foldable("activity", "Activity", "",
      `<div class="log-lines">${d.log.map((l) => `
        <div class="log-line"><span class="dim">${fmtDate(l.at)}</span>
          <b title="${esc(l.actor)}">${esc(l.actor)}</b>
          <span class="dim">${esc(l.what)}</span></div>`).join("")}</div>`,
      `${d.log.length} entr${d.log.length === 1 ? "y" : "ies"}`) : ""}`;

  const nActs = nextStep().actions;
  view().querySelectorAll("[data-next]").forEach((b) => b.onclick = () => {
    const a = nActs[+b.dataset.next];
    if (!a) return;
    if (a.act === "gen") return engGenerate(id, a.path);
    if (a.act === "sign") return engSignForm(a.doc,
      { name: e.approver_name, email: e.approver_email },
      () => renderEngagement(id));
    if (a.act === "fill")
      return view().querySelector(`[data-engfill="${a.doc}"]`)?.click();
    if (a.act === "link")
      return view().querySelector(`[data-gate-link="${a.gate}"]`)?.click();
    if (a.act === "pass")
      return view().querySelector(`[data-gate-pass="${a.gate}"]`)?.click();
    if (a.act === "paylink")
      return view().querySelector(`[data-gate-paylink="${a.gate}"]`)?.click();
    if (a.act === "paycheck")
      return view().querySelector(`[data-gate-paycheck="${a.gate}"]`)?.click();
  });

  foldAllSync = null;
  wireFolds(view());
  const foldAll = $("#fold-all");
  if (foldAll) {
    const stages = () => [...view().querySelectorAll('[data-fold^="stage:"]')];
    const sync = () => { foldAll.textContent =
      stages().every((c) => c.classList.contains("folded"))
        ? "Unfold all" : "Fold all"; };
    foldAllSync = sync;
    sync();
    foldAll.onclick = () => {
      const shut = foldAll.textContent === "Fold all";
      stages().forEach((c) => {
        c.classList.toggle("folded", shut);
        FOLDED[c.dataset.fold] = shut;
      });
      try { localStorage.setItem("bc_folded", JSON.stringify(FOLDED)); } catch {}
      sync();
    };
  }
  $("#eng-back").onclick = () => { S.engId = null; render(); };
  $("#eng-edit").onclick = () => engForm(e);
  $("#eng-dates").onclick = () => engDatesForm(id, d.dates || []);
  $("#eng-gantt").onclick = ganttModal;
  const lb = $("#eng-launch");
  if (lb) lb.onclick = () =>
    launchSite(id, e.name, e.live_url, () => renderEngagement(id));
  const su2 = $("#eng-standup");
  if (su2) su2.onclick = () =>
    standUpClient(e.slug, id, e.name,
      { after: () => renderEngagement(id) });
  $("#eng-binder").onclick = async () => {
    // The first open lays the whole book out to number its contents; say so
    // rather than leaving a dead button under the cursor.
    toast("Building the binder — numbering the contents…");
    /* The preview frame shows the HTML rendering — an embedded PDF is a
       lottery across browsers, and a blank frame reads as a broken binder.
       The download is the real PDF, from the same section gatherer. */
    try {
      const hasBinder = d.docs.some((x) =>
        x.title.startsWith("Project binder"));
      if (!hasBinder) {
        const made = await api(
          `/api/store/admin/engagements/${id}/binder`, { method: "POST" });
        if (made.created) { toast("Binder created — cover page filed under "
          + "consultation"); return renderEngagement(id); }
      }
      const html = await (await authBlob(
        `/api/store/admin/engagements/${id}/binder.html`)).text();
      const url = URL.createObjectURL(
        new Blob([html], { type: "text/html" }));
      modal(`<h3>${esc(e.name)} — the binder</h3>
        <p class="dim" id="bd-hint">Cover, contents mirroring the stages and
          their stages, every generated paper, and a blank form for
          everything not yet generated — printable and fillable with a
          pen.</p>
        <iframe class="doc-viewer" src="${url}" id="bd-frame"
          title="binder" onload="void 0"></iframe>
        <div class="modal-foot dv-foot">
          <span class="dim" id="bd-pages" style="margin-right:auto"></span>
          <button class="btn alt" id="bd-edit"
            title="every unsigned page becomes editable in place — typing
            into a blank form generates it for this client">Edit the
            binder</button>
          <button class="btn" id="bd-save" hidden>Save the binder</button>
          <button class="btn" id="bd-dl">Download binder PDF</button>
          <button class="btn alt" data-close>Close</button>
        </div>`, "wide");
      const bdFrame = $("#bd-frame");
      bdFrame.onload = () => wirePageCount(bdFrame, $("#bd-pages"));
      if (bdFrame.contentDocument
          && bdFrame.contentDocument.readyState === "complete")
        wirePageCount(bdFrame, $("#bd-pages"));
      $("#bd-edit").onclick = () =>
        binderEditMode(id, e, frameAnchor(bdFrame));
      $("#bd-dl").onclick = async () => {
        try {
          const pdf = new Blob([await authBlob(
            `/api/store/admin/engagements/${id}/binder.pdf`)],
            { type: "application/pdf" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(pdf);
          a.download = `${e.slug}-binder.pdf`;
          document.body.appendChild(a); a.click(); a.remove();
          URL.revokeObjectURL(a.href);
        } catch (err) { toast(err.message); }
      };
    } catch (err) { toast(err.message); }
  };
  const pocAcc = $("#poc-accept");
  if (pocAcc) pocAcc.onclick = async () => {
    try { await api(`/api/store/admin/engagements/${id}/poc/accept`,
      { method: "POST" }); toast("Yours now"); renderEngagement(id); }
    catch (err) { toast(err.message); }
  };
  const pocDec = $("#poc-decline");
  if (pocDec) pocDec.onclick = async () => {
    try { await api(`/api/store/admin/engagements/${id}/poc/decline`,
      { method: "POST" });
      toast("Declined — the originator has been told");
      renderEngagement(id); }
    catch (err) { toast(err.message); }
  };
  const makePortal = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/portal`,
        { method: "POST" });
      try { await navigator.clipboard.writeText(out.url); } catch {}
      toast("Portal link copied — the old one, if any, is dead");
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  const pMake = $("#eng-portal-make");
  if (pMake) pMake.onclick = makePortal;
  const pRot = $("#eng-portal-rotate");
  if (pRot) pRot.onclick = () => {
    if (confirm("Rotate the portal link? The current link stops working " +
                "immediately.")) makePortal();
  };
  const pCopy = $("#eng-portal-copy");
  if (pCopy) pCopy.onclick = async () => {
    try { await navigator.clipboard.writeText(location.origin + e.portal_url);
      toast("Portal link copied"); } catch { toast(e.portal_url); }
  };
  const pRev = $("#eng-portal-revoke");
  if (pRev) pRev.onclick = async () => {
    if (!confirm("Revoke the portal link? The client loses access until a " +
                 "new one is made.")) return;
    try {
      await api(`/api/store/admin/engagements/${id}/portal`,
        { method: "DELETE" });
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  $("#eng-export").onclick = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/export`,
        { method: "POST" });
      toast(`${out.files.length} files → ${out.root}`);
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  $("#eng-bundle").onclick = async () => {
    try {
      const r = await fetch(`/api/store/admin/engagements/${id}/export.zip`,
        { headers: { Authorization: "Bearer " + S.user.token } });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${e.slug}-client-bundle.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message); }
  };
  /* The quote bench, embedded. The bench owns the arithmetic — bands,
     dependencies, discounts, care plans — and this page owns the filing:
     it seeds the bench with the client and the last quote's saved state,
     and files what comes back as a to-client paper under the proposal
     stage, where it previews, prints, signs and sends like the rest. */
  /* The bench, in a frame. One opener, two doors: the Quote button opens
     the studio view on the latest state to work a price; a quote row's
     View opens the client view on THAT paper's state, because the quote's
     own presentation — the tape, the parts, the running total — is the
     thing worth showing, and the flat paper is one click away inside.
     The frame is a same-origin blob, so the wiring is two function calls,
     not a broadcast: bcInit seeds it, bcFile is how it answers. No window
     listener — this app has a rule about those, and it has teeth. */
  const openBench = async (opts) => {
    try {
      const saved = await api(`/api/store/admin/engagements/${id}/quote`
        + (opts.doc ? `?did=${opts.doc}` : ""));
      const html = await (await fetch("/api/store/admin/quote-bench",
        { headers: { Authorization: "Bearer " + S.user.token } })).text();
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      modal(`<h3>Quote — ${esc(e.name)}${saved.signed
          ? ' <span class="pill ok">signed</span>'
          : saved.doc_id
            ? ' <span class="pill ok">continuing the filed quote</span>'
            : ""}</h3>
        <iframe class="doc-viewer qb-tall" src="${url}" id="qb-frame"
          title="quote bench"></iframe>
        <div class="modal-foot">
          <span class="dim" style="margin-right:auto">${opts.doc
            ? "The bench's own presentation of the filed quote — edits here "
              + "refile it when you File to client."
            : "File to client, up in the bench's own toolbar, saves it as "
              + "a paper on this client."}</span>
          ${opts.doc ? `<button class="btn alt" id="qb-paper" title="the
            printable, signable paper this quote filed as">The
            paper</button>` : ""}
          <button class="btn alt" data-close>Close</button>
        </div>`, "wide");
      const frame = $("#qb-frame");
      frame.onload = () => {
        const w = frame.contentWindow;
        w.bcFile = async (d) => {
          try {
            const out = await api(`/api/store/admin/engagements/${id}/quote`,
              { body: { title: d.title, markdown: d.markdown,
                        state: d.state } });
            closeModal();
            toast(out.refreshed
              ? "Quote refreshed — same paper, new numbers"
              : "Quote filed under the proposal stage");
            renderEngagement(id);
          } catch (err) { toast(err.message); }
        };
        /* Re-prove the person before the studio face shows costs and
           margins — the bench asks, this answers. The token proves the
           session; the password proves the one holding the screen is
           still ours, which matters exactly when a client is watching. */
        w.bcVerify = (pw) =>
          api("/api/store/admin/verify", { body: { password: pw } })
            .then(() => true).catch(() => false);
        if (w.bcInit) w.bcInit({ client: e.name, state: saved.state || "",
                                 view: opts.view });
      };
      const paper = $("#qb-paper");
      if (paper) paper.onclick = () => {
        closeModal();
        docViewer(opts.doc, "body", "", opts.name || `Quote — ${e.name}`,
          saved.signed, () => renderEngagement(id),
          { name: e.approver_name, email: e.approver_email });
      };
    } catch (err) { toast(err.message); }
  };
  /* Client view on both doors: a quote is as likely to be opened with
     the client in the room as not, and the safe face is the one that
     shows first. The studio face is a toggle away, behind a password. */
  $("#eng-quote").onclick = () => openBench({ view: "client" });
  view().querySelectorAll("[data-gen]").forEach((b) => b.onclick = () =>
    engGenerate(id, b.dataset.gen));
  /* The stage, written up for the client. Composed on the server from the
     same rows the board reads, filed as a to-client document, and opened
     the way any other document opens — the point is that it is a paper in
     the vault, not a screen you can only look at here. */
  /* Sending is outward-facing and cannot be taken back, so the recipient is
     on screen before the click that sends, not in a toast afterwards. One
     modal for everything that goes to a client: what is being sent changes,
     the care taken over sending it does not. */
  const sendToClient = (path, hint) => {
    modal(`<h3>Send to the client</h3>
      <p class="dim">${hint}</p>
      <label>To <span class="req">required</span></label>
      <input id="sd-to" type="email" value="${esc(e.approver_email || "")}">
      <label>A line with it <span class="opt">optional</span></label>
      <textarea id="sd-msg" rows="2"></textarea>
      <div class="modal-foot">
        <button class="btn" id="sd-go">Send</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#sd-go").onclick = async () => {
      try {
        const out = await api(path,
          { body: { to: $("#sd-to").value.trim(),
                    message: $("#sd-msg").value.trim() } });
        closeModal();
        /* "dry" is the honest word for a pipeline that ran with no SMTP
           configured. Reporting it as sent is the one outcome that would
           cost someone a client. */
        if (out.status === "sent") toast(`Sent to ${out.to}`);
        else if (out.status === "dry") {
          try { await navigator.clipboard.writeText(out.link); } catch {}
          toast("No mail is configured, so nothing was sent — the link is "
            + "copied, send it yourself");
        } else toast(`Not sent — ${out.status}`);
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
  };
  view().querySelectorAll("[data-send]").forEach((b) => b.onclick = () =>
    sendToClient(
      `/api/store/admin/engagements/${id}/docs/${b.dataset.send}/send`,
      `They get a link to their own portal copy — the live document, which
       still says the truth next week. The page they land on offers the
       PDF.`));
  $("#eng-bundle-send").onclick = () =>
    sendToClient(`/api/store/admin/engagements/${id}/bundle/send`,
      `They get a link to their roadmap, where everything on their side of
       the wall downloads as one zip — built when they click it, so it is
       never the version that was true the day you sent it.`);
  view().querySelectorAll("[data-report]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(
        `/api/store/admin/engagements/${id}/stages/${b.dataset.report}/report`,
        { method: "POST" });
      toast(out.refreshed
        ? "Progress update refreshed — same document, current facts"
        : "Progress update written — filed on the client's side");
      await renderEngagement(id);
      view().querySelector(`[data-engview="${out.doc_id}"]`)?.click();
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-engsign]").forEach((b) => b.onclick = () =>
    engSignForm(+b.dataset.engsign,
      { name: e.approver_name, email: e.approver_email },
      () => renderEngagement(id)));
  // "Open" lands on the Documents tab, searched to this title, where the
  // vault's own editor finishes what the fill form started.
  view().querySelectorAll("[data-engopen]").forEach((b) => b.onclick = () => {
    S.docQ = b.dataset.engopen; S.tab = "docs"; render();
  });
  const authBlob = async (path) => {
    const r = await fetch(path,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    return r.blob();
  };
  view().querySelectorAll("[data-engview]").forEach((b) => b.onclick = () => {
    /* One shared viewer with the Documents tab — in-app, never a popup:
       a window opened by script after an awaited fetch has left the
       user-gesture call stack and blockers silently eat it. */
    const name = (b.closest(".doc-line, .sig-row")?.querySelector("b")
      ?.textContent || "document").trim();
    if (b.dataset.quote)
      return openBench({ view: "client", doc: +b.dataset.engview, name });
    docViewer(+b.dataset.engview, b.dataset.kind, b.dataset.ext, name,
              b.dataset.signed, () => renderEngagement(id),
              { name: e.approver_name, email: e.approver_email });
  });
  view().querySelectorAll("[data-engdl]").forEach((b) => b.onclick = async () => {
    const did = b.dataset.engdl;
    const isPdfable = b.dataset.kind === "body" || b.dataset.ext === "pdf";
    const path = isPdfable
      ? `/api/store/admin/documents/${did}/pdf?download=1`
      : `/api/store/admin/documents/${did}/file`;
    try {
      const blob = await authBlob(path);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = b.dataset.name
        + (b.dataset.kind === "body" ? ".pdf" : "");
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-engscan]").forEach((b) => b.onclick = () => {
    /* The paper came back — a photo or a scanned PDF. It becomes its own
       vault document filed beside the original in the same stage, so the
       original's authored text stays exactly what was (or will be) signed
       electronically, and the wet-ink copy is evidence alongside it. */
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".pdf,.png,.jpg,.jpeg";
    inp.onchange = async () => {
      const f = inp.files[0];
      if (!f) return;
      try {
        const doc = await api("/api/store/admin/documents", { body: {
          title: `Signed scan — ${b.dataset.title}`.slice(0, 190),
          category: "contract", party_kind: "partner",
          party_name: e.name,
          notes: `wet-ink scan of document #${b.dataset.engscan}`,
        } });
        const fd = new FormData();
        fd.append("file", f);
        const up = await fetch(
          `/api/store/admin/documents/${doc.id}/file`,
          { method: "POST", body: fd,
            headers: { Authorization: "Bearer " + S.user.token } });
        if (!up.ok) throw new Error((await up.json()).detail || up.status);
        await api(`/api/store/admin/engagements/${id}/attach`, { body: {
          doc_id: doc.id, stage: b.dataset.stage,
          side: b.dataset.side } });
        toast("Scan filed beside the document");
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
    inp.click();
  });
  view().querySelectorAll("[data-engrm]").forEach((b) => b.onclick = () => {
    modal(`<h3>Remove — ${esc(b.dataset.title)}</h3>
      <p class="dim">Unfiling takes it out of this client's folder but keeps
        it in the Documents vault. Deleting removes it from the vault too —
        signed documents are archived there, never destroyed.</p>
      <div class="modal-foot">
        <button class="btn alt" id="rm-unfile">Unfile from this client</button>
        <button class="btn alt" id="rm-del">Delete from the vault</button>
        <button class="btn" data-close>Cancel</button>
      </div>`);
    $("#rm-unfile").onclick = async () => {
      try {
        await api(`/api/store/admin/engagements/${id}/docs/${b.dataset.engrm}`,
          { method: "DELETE" });
        closeModal(); renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
    $("#rm-del").onclick = async () => {
      try {
        const out = await api(`/api/store/admin/documents/${b.dataset.engrm}`,
          { method: "DELETE" });
        closeModal();
        toast(out.archived
          ? "Archived — it carries signatures, so it stays as evidence"
          : "Deleted");
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-engfill]").forEach((b) => b.onclick = async () => {
    const did = +b.dataset.engfill;
    try {
      const t = await api(`/api/store/admin/engagements/${id}/docs/${did}/blanks`);
      const field = (tok) => fillField(tok, t.suggested[tok]);
      modal(`<h3>Fill blanks — ${esc(t.title)}</h3>
        <p class="dim">Each value fills its token everywhere it appears.
          The document goes active on its own when the last bracket is
          gone.</p>
        ${t.placeholders.map(field).join("")}
        <div class="modal-foot">
          <button class="btn alt" id="fb-indoc" style="margin-right:auto"
            title="type into the fields where they sit in the text">Fill in
            the document instead</button>
          <button class="btn" id="fb-go">Fill</button>
        </div>`);
      $("#fb-indoc").onclick = () => { closeModal();
        fillInDoc(did, t.title, () => renderEngagement(id)); };
      $("#fb-go").onclick = async () => {
        const fills = {};
        document.querySelectorAll("[data-fill]").forEach((i) => {
          if (i.value.trim()) fills[i.dataset.fill] = i.value.trim();
        });
        try {
          const out = await api(
            `/api/store/admin/engagements/${id}/docs/${did}/fill`,
            { body: { fills } });
          closeModal();
          toast(out.unfilled.length
            ? `${out.unfilled.length} blank${out.unfilled.length === 1
                ? "" : "s"} left`
            : "Complete — no brackets left");
          renderEngagement(id);
        } catch (err) { toast(err.message); }
      };
    } catch (err) { toast(err.message); }
  });

  const gateDone = (out) => {
    if (out.warnings && out.warnings.length)
      toast("Out of order — still open: " + out.warnings.join(", "));
    if (out.date_stamped)
      toast(`Dates table: '${out.date_stamped}' marked done today`);
    if (out.launch) {
      modal(`<h3>Ready to launch</h3>
        <p class="dim">${esc(out.launch.name)} runs on the platform but has
          no public address yet. Launch them now — the URL, and the
          capabilities the quote sold, in one act?</p>
        <div class="modal-foot">
          <button class="btn" id="gl-launch">Launch…</button>
          <button class="btn alt" data-close>Later — the button stays on
            their page</button>
        </div>`);
      $("#gl-launch").onclick = () => {
        closeModal();
        launchSite(id, e.name, e.live_url, () => renderEngagement(id));
      };
      return;
    }
    if (out.stand_up) {
      // The contract just closed and no install exists: the next thing an
      // operator was going to do anyway is offered, sized from the quote.
      const su = out.stand_up;
      modal(`<h3>The contract is signed</h3>
        <p class="dim">${esc(su.name)} has no install yet. Stand them up on
          the platform now? ${su.suggestion
            ? `The quote sizes them: <b>${esc(su.suggestion.reason)}</b>.`
            : "No quote is filed, so the size will be a choice, not a "
              + "derivation."}</p>
        <div class="modal-foot">
          <button class="btn" id="su-go">Stand them up</button>
          <button class="btn alt" data-close>Later — it stays on the
            Platform tab</button>
        </div>`);
      $("#su-go").onclick = () => {
        closeModal();
        standUpClient(su.slug, id, su.name,
          { suggestion: su.suggestion,
            after: () => renderEngagement(id) });
      };
      return;
    }
    renderEngagement(id);
  };
  view().querySelectorAll("[data-gate-pass]").forEach((b) => b.onclick = async () => {
    const money = b.dataset.kind === "money";
    const note = prompt(money
      ? "Confirm — note (e.g. the wire reference), optional:"
      : "Passing without a linked document — where is the evidence filed?");
    if (note === null) return;
    if (!money && !note.trim()) { toast("a signature stage needs the note"); return; }
    try { gateDone(await api(
      `/api/store/admin/engagements/${id}/gates/${b.dataset.gatePass}`,
      { body: { note: note.trim() } })); }
    catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-link]").forEach((b) => b.onclick = () => {
    if (!d.docs.length) { toast("no documents filed yet — generate one first"); return; }
    modal(`<h3>Link a document</h3>
      <p class="dim">The stage closes when this document is signed — read
        from the vault, never copied.</p>
      <label>Document</label>
      <select id="gl-doc">${d.docs.map((x) =>
        `<option value="${x.id}">${esc(x.title)}${x.signed ? " (signed)" : ""}</option>`).join("")}</select>
      <div class="modal-foot"><button class="btn" id="gl-go">Link</button></div>`);
    $("#gl-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/engagements/${id}/gates/${b.dataset.gateLink}`,
          { body: { doc_id: +$("#gl-doc").value } });
        closeModal(); gateDone(out);
      } catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-gate-paylink]").forEach((b) => b.onclick = async () => {
    const suggested = b.dataset.gatePaylink === "deposit_cleared" && e.value_cents
      ? e.value_cents / 200 : "";
    const amt = prompt("Amount ($):", suggested);
    if (amt === null) return;
    try {
      const out = await api(`/api/store/admin/engagements/${id}/gates/${
        b.dataset.gatePaylink}/payment-link`,
        { body: { amount_cents: Math.round((+amt || 0) * 100) } });
      try { await navigator.clipboard.writeText(out.url); } catch {}
      toast(`Payment link for ${money(out.amount_cents)} copied — send it ` +
            "with the invoice");
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-paycheck]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/gates/${
        b.dataset.gatePaycheck}/payment-check`, { method: "POST" });
      toast(out.paid ? "Paid — stage closed, verified by Stripe"
                     : out.detail);
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-reopen]").forEach((b) => b.onclick = async () => {
    if (!confirm("Reopen this stage? The signed document, if any, stays in the vault.")) return;
    try {
      await api(`/api/store/admin/engagements/${id}/gates/${b.dataset.gateReopen}`,
        { method: "DELETE" });
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
}

async function engGenerate(id, path) {
  const t = await api(`/api/store/admin/engagements/${id}/template?path=`
    + encodeURIComponent(path));
  const field = (tok) => fillField(tok, t.suggested[tok]);
  modal(`<h3>Generate: ${esc(t.name)}</h3>
    <p class="dim">Each value fills its token everywhere it appears. Blanks
      stay bracketed — finish them in the document editor.</p>
    <label>Title</label><input id="gen-title" value="">
    <label>Side</label>
    <select id="gen-side">
      <option value="to_client" ${t.side === "to_client" ? "selected" : ""}>to client</option>
      <option value="internal" ${t.side === "internal" ? "selected" : ""}>internal — never sent</option>
    </select>
    ${t.placeholders.map(field).join("")}
    <div class="modal-foot"><button class="btn" id="gen-go">Generate</button></div>`);
  $("#gen-go").onclick = async () => {
    const fills = {};
    document.querySelectorAll("[data-fill]").forEach((i) => {
      if (i.value.trim()) fills[i.dataset.fill] = i.value.trim();
    });
    try {
      const out = await api(`/api/store/admin/engagements/${id}/docs`, {
        body: { template_path: path, fills,
          title: $("#gen-title").value.trim(),
          side: $("#gen-side").value },
      });
      closeModal();
      toast(out.unfilled.length
        ? `Created — ${out.unfilled.length} blank${out.unfilled.length === 1
            ? "" : "s"} left to finish in the editor`
        : "Created, fully filled");
      await renderEngagement(id);
      /* Then open it. Generating a document is asking for the document,
         and the next thing anyone does is look at what came out. Clicking
         its own View button rather than calling the viewer directly keeps
         one path: whatever the row knows about the document — its name,
         whether it is a body or a file, what it is signed with — the
         viewer is told by the row, and cannot be told something else. */
      view().querySelector(`[data-engview="${out.doc_id}"]`)?.click();
    } catch (err) { toast(err.message); }
  };
}

function engSignForm(docId, preset, after) {
  preset = preset || {};
  after = after || (() => renderEngagement(S.engId));
  modal(`<h3>Request a signature</h3>
    <div class="row2">
      <div><label>Signer name <span class="req">required</span></label>
        <input id="es-name" value="${esc(preset.name || "")}"></div>
      <div><label>Signer email <span class="req">required</span></label>
        <input id="es-email" type="email" value="${esc(preset.email || "")}"></div>
    </div>
    <label>Message <span class="opt">optional</span></label>
    <textarea id="es-msg" rows="2"></textarea>
    <div class="modal-foot">
      <button class="btn alt" id="es-here" title="the pad opens right here —
        drawn with the mouse; the only email is the receipt, after
        signing">Sign now — in person</button>
      <button class="btn" id="es-go">Send request</button>
    </div>`);
  const sendIt = async (inPerson) => {
      const out = await api(`/api/store/admin/documents/${docId}/request-signature`, {
        body: { signer_name: $("#es-name").value.trim(),
          signer_email: $("#es-email").value.trim(),
          role: "approver", message: $("#es-msg").value.trim(),
          in_person: !!inPerson },
      });
      closeModal();
      return out;
  };
  $("#es-here").onclick = async () => {
    try {
      const out = await sendIt(true);
      // The signing page, in the viewer modal — the same page an emailed
      // signer would see, pad and all; closing it refreshes the gate state.
      modal(`<h3>Sign here</h3>
        <iframe class="doc-viewer" src="${out.link}" title="sign"></iframe>
        <div class="modal-foot" style="margin-top:10px">
          <button class="btn" id="sh-done">Done</button>
        </div>`, "wide");
      $("#sh-done").onclick = () => { closeModal(); after(); };
    } catch (err) { toast(err.message); }
  };
  $("#es-go").onclick = async () => {
    try {
      const out = await sendIt(false);
      if (out.provider === "docusign") {
        toast("Sent via DocuSign — they'll get DocuSign's own email; " +
              "check the request to pull the status back");
      } else {
        try { await navigator.clipboard.writeText(out.link); } catch {}
        toast("Signature link created and copied — emailed too, if mail is set up");
      }
      after();
    } catch (err) { toast(err.message); }
  };
}

async function renderDocs() {
  const q = S.docQ || "";
  const kind = S.docKind || "";
  DOCS = await api("/api/store/admin/documents?party_kind="
    + encodeURIComponent(kind) + "&q=" + encodeURIComponent(q)
    + (S.docArchived ? "&archived=1" : ""));
  /* The paperwork our studio holds for US — the other side of the client
     relationship. A business that runs on this platform is usually also a
     client of the studio that built it; its contracts, quotes and progress
     updates live in the studio's pipeline, and this reads them across the
     wall (to-client side only, read-only, no second login). */
  if (S.studioDocs === undefined) {
    try { S.studioDocs = await api("/api/store/admin/studio"); }
    catch { S.studioDocs = { connected: false }; }
  }

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
    ${S.studioDocs && S.studioDocs.connected ? `
    <div class="card studio-docs">
      <div class="card-head"><b>From ${esc(S.studioDocs.studio)}</b>
        <span class="dim">stage ${esc(S.studioDocs.stage || "")} ·
          ${S.studioDocs.gates_closed} of ${S.studioDocs.gates_total}
          stages closed</span>
        ${S.studioDocs.portal_url ? `<button class="btn alt sm"
          id="studio-portal" data-url="${esc(S.studioDocs.portal_url)}"
          title="the live roadmap the studio keeps for you">Open the
          roadmap</button>` : ""}</div>
      <p class="dim">Your paperwork with the studio that runs this
        platform — read straight from their pipeline, so it is always
        current. Signing and questions happen on the roadmap.</p>
      <div class="sig-rows">${S.studioDocs.docs.map((d) => `
        <div class="doc-line">
          <span class="dl-title"><b title="${esc(d.title)}">${esc(d.title)}</b>
            ${d.signed ? `<span class="pill ok">${d.signed} signed</span>` : ""}
            ${d.awaiting ? `<span class="pill warn">${d.awaiting} awaiting
              your signature</span>` : ""}</span>
          <span class="dl-acts" style="grid-template-columns: 56px 50px">
            <button class="btn alt sm" data-studioview="${d.id}"
              data-title="${esc(d.title)}"
              data-ext="${d.ext || ""}">View</button>
            ${d.ext ? "" : `<button class="btn alt sm"
              data-studiopdf="${d.id}"
              data-title="${esc(d.title)}">PDF</button>`}
          </span>
        </div>`).join("")}
      </div>
    </div>` : ""}
    <div class="filters">
      <input id="doc-q" placeholder="Search titles, parties, notes" value="${esc(q)}">
      <div class="chips"><button class="chip ${kind ? "" : "on"}" data-kind="">All</button>${kinds}
        ${DOCS.archived_count || S.docArchived ? `<button class="chip ${
          S.docArchived ? "on" : ""}" id="doc-arch" title="kept as evidence —
          signed papers whose client was deleted, and superseded versions"
          >Archived${DOCS.archived_count ? ` (${DOCS.archived_count})`
            : ""}</button>` : ""}</div>
    </div>
    <div id="doc-list">${DOCS.documents.map(docRow).join("")
      || '<div class="card empty"><span class="e-ic">' + opsIcon("file")
       + '</span><b>Nothing filed yet</b><p class="dim">Upload a contract or write one here, then send it for signature.</p></div>'}</div>`;

  $("#doc-new").onclick = () => docForm(null);
  let t;
  $("#doc-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.docQ = e.target.value; renderDocs(); }, 250); };
  view().querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => {
    S.docKind = b.dataset.kind; renderDocs(); });
  const arch = $("#doc-arch");
  if (arch) arch.onclick = () => { S.docArchived = !S.docArchived;
    renderDocs(); };
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
  /* Same column discipline as a client's stages: title block, then a fixed
     state column so every "signed" pill starts at the same x down the whole
     list, then the actions in fixed slots. */
  return `<div class="doc-card${d.fully_signed ? " dl-signed"
      : d.awaiting ? " dl-awaiting" : ""}" data-doc="${d.id}">
    <div class="doc-top">
      <span class="doc-ic">${opsIcon("file")}</span>
      <div class="doc-main">
        <b title="${esc(d.title)}">${esc(d.title)}</b>
        <span class="dim">${esc(d.category_label)}${
          d.party_name ? " · " + esc(d.party_name) : ""} ·
          <span class="tag">${esc(d.party_label)}</span></span>
      </div>
      <span class="dt-state">${state}</span>
      <span class="dt-exp">${exp}</span>
      <span class="dt-acts">
        <button class="btn alt sm" data-docview="${d.id}"
          data-kind="${(d.body || "").trim() ? "body" : d.has_file ? "file" : "body"}"
          data-ext="${d.ext || ""}" data-signed="${(d.signatures || [])
            .filter((x) => x.status === "signed").length}"
          data-name="${esc(d.title)}">View</button>
        <button class="btn alt sm" data-docedit="${d.id}">Edit</button>
        <button class="btn alt sm" data-sign="${d.id}">Sign</button>
        <button class="btn alt sm" data-rowdel="doc:${d.id}">Delete</button>
      </span>
    </div>
    ${sigs.length ? `<div class="sig-rows">${sigs.map((s) => `
      <div class="sig-line sig-${s.status}">
        <b title="${esc(s.signer_name)}">${esc(s.signer_name)}</b>
        <span class="sl-mail dim">${esc(s.signer_email)}</span>
        <span class="sl-role dim">${esc(s.role)}</span>
        <span class="sl-state"><span class="pill ${s.status === "signed" ? "ok"
          : s.status === "declined" ? "bad" : "warn"}">${s.status}</span>${
          s.provider === "docusign"
            ? ' <span class="tag">DocuSign</span>' : ""}</span>
        <span class="sl-when dim">${s.status === "signed"
          ? fmtDate(s.signed_at) : ""}</span>
        <span class="sl-acts">${s.status === "signed" ? ""
          : `${s.provider === "docusign"
              ? `<button class="btn alt sm" data-sigcheck="${s.id}">check</button>`
              : ""}<button class="btn alt sm" data-void="${s.id}">void</button>`}
        </span>
      </div>`).join("")}</div>` : ""}
  </div>`;
}

async function docViewer(did, kind, ext, name, signedN, after, preset) {
  /* One viewer for both tabs: the rendered document with its signature
     block, and the signed PDF as the primary download. */
  const auth = async (path) => {
    const r = await fetch(path,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    return r.blob();
  };
  const isPdfable = kind === "body" || ext === "pdf";
  try {
    let frameUrl;
    if (kind === "body") {
      const html = await (await auth(
        `/api/store/admin/documents/${did}/preview`)).text();
      frameUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    } else {
      frameUrl = URL.createObjectURL(
        await auth(`/api/store/admin/documents/${did}/file`));
    }
    const pdfUrl = isPdfable ? URL.createObjectURL(new Blob(
      [await auth(`/api/store/admin/documents/${did}/pdf`)],
      { type: "application/pdf" })) : frameUrl;
    const signed = +signedN > 0;
    modal(`<h3>${esc(name)}${signed
        ? ' <span class="pill ok">signed</span>' : ""}</h3>
      ${signed ? `<p class="dim">The signature block is at the end of the
        document — scroll down, and it's on the last page of the PDF.</p>` : ""}
      <iframe class="doc-viewer" src="${frameUrl}" title="${esc(name)}"></iframe>
      <div class="modal-foot dv-foot">
        <span class="dim" id="dv-pages" style="margin-right:auto"></span>
        ${kind === "body" && !signed ? `<button class="btn alt" id="dv-edit"
          title="type into the blanks where they sit in the text"
          >Edit</button>` : ""}
        <button class="btn alt" id="dv-sign" title="send it for signature, or
          open the pad here and sign with the mouse">${
          signed ? "Add a signature" : "Sign"}</button>
        <button class="btn" id="dv-dl">${opsIcon("file", "btn-ic")}
          Download ${signed ? "signed " : ""}${isPdfable ? "PDF" : "file"}</button>
        <button class="btn alt" id="dv-open">Open ${isPdfable ? "PDF" : ""}
          in tab</button>
        <button class="btn alt" data-close>Close</button>
      </div>`, "wide");
    const dvFrame = document.querySelector("#ops-modal iframe.doc-viewer");
    if (dvFrame) dvFrame.onload = () => wirePageCount(dvFrame, $("#dv-pages"));
    /* Signing belongs where you are reading: having just read the thing,
       closing the viewer to find the row's button is a step that exists
       only because of how the page was built. */
    $("#dv-sign").onclick = () => {
      closeModal();
      engSignForm(did, preset || {}, after || (() => render()));
    };
    const dvEdit = $("#dv-edit");
    if (dvEdit) dvEdit.onclick = () => {
      const at = frameAnchor(dvFrame);     // read it before the modal goes
      closeModal();
      fillInDoc(did, name, after, at);
    };
    /* Buttons, not anchors: .btn styling is scoped to button.btn, and a
       synchronous handler keeps the user gesture, so the new tab is never
       popup-blocked and the download never depends on anchor semantics. */
    $("#dv-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = pdfUrl;
      a.download = name + (isPdfable ? ".pdf" : "");
      document.body.appendChild(a); a.click(); a.remove();
      toast("Downloading — the PDF carries the document and every "
        + "signature on it");
    };
    $("#dv-open").onclick = () => {
      const w = window.open(pdfUrl, "_blank");
      if (!w) { $("#dv-dl").click(); }   // a blocker still gets the file
    };
  } catch (err) { toast(err.message); }
}

function wireDocRows() {
  wireRows({}, renderDocs);
  const sp = $("#studio-portal");
  if (sp) sp.onclick = () => window.open(sp.dataset.url, "_blank");
  view().querySelectorAll("[data-studioview]").forEach((b) => b.onclick =
    async () => {
      try {
        const r = await fetch(`/api/store/admin/studio/doc/${b.dataset.studioview}`,
          { headers: { Authorization: "Bearer " + S.user.token } });
        if (!r.ok) throw new Error((await r.json()).detail || r.status);
        const url = URL.createObjectURL(await r.blob());
        modal(`<h3>${esc(b.dataset.title)} <span class="pill ok">from the
            studio</span></h3>
          <iframe class="doc-viewer" src="${url}"
            title="${esc(b.dataset.title)}"></iframe>
          <div class="modal-foot">
            <span class="dim" style="margin-right:auto">Read-only — this is
              the studio's copy. Signing happens on your roadmap.</span>
            <button class="btn alt" data-close>Close</button>
          </div>`, "wide");
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-studiopdf]").forEach((b) => b.onclick =
    async () => {
      try {
        const r = await fetch(
          `/api/store/admin/studio/doc/${b.dataset.studiopdf}/pdf`,
          { headers: { Authorization: "Bearer " + S.user.token } });
        if (!r.ok) throw new Error((await r.json()).detail || r.status);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await r.blob());
        a.download = b.dataset.title + ".pdf";
        document.body.appendChild(a); a.click(); a.remove();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-docview]").forEach((b) => b.onclick = () =>
    docViewer(+b.dataset.docview, b.dataset.kind, b.dataset.ext,
              b.dataset.name, b.dataset.signed, renderDocs));
  view().querySelectorAll("[data-docedit]").forEach((b) => b.onclick = () =>
    docForm(DOCS.documents.find((x) => x.id === +b.dataset.docedit)));
  view().querySelectorAll("[data-sign]").forEach((b) => b.onclick = () =>
    signForm(+b.dataset.sign));
  view().querySelectorAll("[data-sigcheck]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(`/api/store/admin/signatures/${b.dataset.sigcheck}/refresh`,
        { method: "POST" });
      toast(out.status === "signed" ? "Signed — pulled back from DocuSign"
        : out.detail || `status: ${out.status}`);
      renderDocs();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-void]").forEach((b) => b.onclick = async () => {
    if (!confirm("Void this signature request?")) return;
    try { await api(`/api/store/admin/signatures/${b.dataset.void}/void`,
      { method: "POST" }); renderDocs(); }
    catch (e) { toast(e.message); }
  });
}

function docForm(d) {
  const cats = Object.entries(DOCS.categories).map(([k, v]) =>
    `<option value="${k}" ${d && d.category === k ? "selected" : ""}>${v}</option>`).join("");
  const kinds = Object.entries(DOCS.party_kinds).map(([k, v]) =>
    `<option value="${k}" ${d && d.party_kind === k ? "selected" : ""}>${v}</option>`).join("");
  const day = (t) => t ? new Date(t * 1000).toISOString().slice(0, 10) : "";
  modal(`<h3>${d ? "Edit document" : "New document"}</h3>
    <label>Title</label>
    <input id="nd-title" value="${esc((d && d.title) || "")}"
      placeholder="Supply agreement — Hudson DC">
    <div class="row2">
      <div><label>Category</label><select id="nd-cat">${cats}</select></div>
      <div><label>Concerns</label><select id="nd-kind">${kinds}</select></div>
    </div>
    <div class="row2">
      <div><label>Party name</label>
        <input id="nd-party" value="${esc((d && d.party_name) || "")}"></div>
      <div><label>Party email</label>
        <input id="nd-email" type="email" value="${esc((d && d.party_email) || "")}"></div>
    </div>
    <div class="row2">
      <div><label>Effective</label>
        <input id="nd-eff" type="date" value="${day(d && d.effective)}"></div>
      <div><label>Expires <span class="dim">(optional)</span></label>
        <input id="nd-exp" type="date" value="${day(d && d.expires)}"></div>
    </div>
    <label>File ${d && d.has_file
      ? `<span class="dim">— currently ${esc(d.filename || "attached")};
         uploading replaces it</span>` : '<span class="dim">(PDF, image or Office)</span>'}</label>
    <input id="nd-file" type="file">
    <label>${d && d.has_file ? "Notes for the reader" : "Or write the document"}</label>
    <textarea id="nd-body" rows="5"
      placeholder="Paste or write the agreement text. This is what a signer sees."
      >${esc((d && d.body) || "")}</textarea>
    <label>Internal notes</label>
    <input id="nd-notes" value="${esc((d && d.notes) || "")}">
    ${d ? `<label>Status</label><select id="nd-status">
      ${["draft", "active", "superseded", "archived"].map((st) =>
        `<option ${d.status === st ? "selected" : ""}>${st}</option>`).join("")}
      </select>` : ""}
    ${d && d.signatures && d.signatures.some((s) => s.status === "signed")
      ? `<p class="dim" style="font-size:12px;margin-top:10px">This document
         has been signed. Editing the text or replacing the file will make the
         signing certificate report a fingerprint mismatch — which is the
         point, but supersede it with a new document instead if you want a
         clean record.</p>` : ""}
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="nd-save">Save</button>
    </div>`);
  $("#nd-save").onclick = async () => {
    const title = $("#nd-title").value.trim();
    if (!title) return toast("a document needs a title");
    const dt = (v) => v ? new Date(v + "T12:00").getTime() / 1000 : 0;
    const payload = { title, category: $("#nd-cat").value,
      party_kind: $("#nd-kind").value,
      party_name: $("#nd-party").value.trim(),
      party_email: $("#nd-email").value.trim(),
      body: $("#nd-body").value, notes: $("#nd-notes").value.trim(),
      effective: dt($("#nd-eff").value), expires: dt($("#nd-exp").value) };
    try {
      let id = d && d.id;
      if (d) await api(`/api/store/admin/documents/${d.id}`,
        { method: "PATCH", body: payload });
      else id = (await api("/api/store/admin/documents", { body: payload })).id;
      if (d && $("#nd-status")) await api(
        `/api/store/admin/documents/${d.id}/status`,
        { body: { status: $("#nd-status").value } });
      const f = $("#nd-file").files[0];
      if (f) {
        const fd = new FormData(); fd.append("file", f);
        const r = await fetch(`/api/store/admin/documents/${id}/file`, {
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

// ---------- stores rail ----------
/* A persistent list of accounts beside the work. Field staff spend the day
   asking "which stores are in this region and what's low" — making them
   change tab to find out was the wrong default. */
async function drawStoreRail() {
  const rail = $("#store-rail");
  if (!rail || !S.user) return;
  if (!["shop", "inventory", "routes", "outreach", "orders", "hq"]
      .includes(S.tab)) { rail.innerHTML = ""; rail.hidden = true; return; }
  rail.hidden = false;
  let stores = S._stores;
  if (!stores) { stores = S._stores = await api("/api/stores"); }
  const q = (S.railQ || "").toLowerCase();
  const shown = stores.filter((st) =>
    !q || (st.name + " " + st.city + " " + st.region).toLowerCase().includes(q));
  const byRegion = {};
  shown.forEach((st) => (byRegion[st.region] = byRegion[st.region] || []).push(st));
  rail.innerHTML = `
    <div class="rail-head">
      <b>Stores</b><span class="dim">${shown.length}</span>
    </div>
    <input id="rail-q" placeholder="Filter" value="${esc(S.railQ || "")}">
    <div class="rail-list">
      ${Object.entries(byRegion).map(([region, list]) => `
        <div class="rail-group">
          <span class="rail-region"><i style="background:${
            REGION_COLORS[region] || "#8b98a5"}"></i>${esc(region)}</span>
          ${list.map((st) => `
            <button class="rail-item ${S.railPick === st.id ? "on" : ""}"
              data-rail="${st.id}">
              <b>${esc(st.name)}</b>
              <span class="dim">${esc(st.city)}${
                st.kind === "distributor_dc" ? " · DC" : ""}</span>
            </button>`).join("")}
        </div>`).join("") || '<p class="dim" style="padding:8px">No matches.</p>'}
    </div>`;
  let t;
  $("#rail-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.railQ = e.target.value; drawStoreRail(); }, 200); };
  rail.querySelectorAll("[data-rail]").forEach((b) => b.onclick = async () => {
    S.railPick = +b.dataset.rail;
    const st = stores.find((x) => x.id === S.railPick);
    const inv = await api("/api/inventory").catch(() => []);
    const mine = inv.filter((i) => i.store_id === st.id);
    modal(`<h3>${esc(st.name)}</h3>
      <p class="dim">${esc(st.city)} · ${esc(st.region)}${
        st.kind === "distributor_dc" ? " · distribution centre" : ""}${
        st.contact ? " · " + esc(st.contact) : ""}</p>
      ${mine.length ? `<table><thead><tr><th>product</th><th class="num">on hand</th>
        <th class="num">par</th></tr></thead><tbody>
        ${mine.map((i) => `<tr class="${i.low ? "low" : ""}">
          <td>${esc(i.product_name || i.product_id)}</td>
          <td class="num">${i.qty}</td><td class="num">${i.par}</td></tr>`).join("")}
        </tbody></table>` : '<p class="dim">No inventory recorded here yet.</p>'}
      <div class="modal-acts"><button class="btn alt" data-close>Close</button></div>`);
    drawStoreRail();
  });
}

// ---------- staff permissions ----------
async function renderStaff() {
  const data = await api("/api/store/admin/staff");
  const perms = Object.entries(data.permissions);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Team & permissions</h2>
        <p class="dim">Who can see what in the back office. Owners keep full
          access; everyone else gets exactly what's ticked. Changes are
          recorded in the audit log.</p></div>
    </div>
    ${data.staff.map((u) => `
      <div class="card">
        <div class="doc-top">
          <div class="doc-main">
            <b>${esc(u.name)}</b>
            <span class="dim">${esc(u.role)}${u.is_admin ? " · owner" : ""}${
              u.active ? "" : " · inactive"}</span>
          </div>
          ${u.effective.includes("*")
            ? '<span class="pill ok">full access</span>'
            : `<span class="pill">${u.effective.length} area(s)</span>`}
          <button class="btn alt sm" data-setpin="${u.id}:${esc(u.name)}"
            >Time-clock PIN</button>
          <button class="btn alt sm" data-badge="${u.id}:${esc(u.name)}"
            >Badge</button>
        </div>
        ${u.is_admin ? '<p class="dim" style="margin-top:8px">Owner accounts always have every permission.</p>' : `
        <div class="perm-grid">
          ${perms.map(([k, label]) => `
            <label class="perm">
              <input type="checkbox" data-perm="${u.id}:${k}"
                ${u.effective.includes(k) ? "checked" : ""}>
              <span><b>${k}</b><small>${esc(label)}</small></span>
            </label>`).join("")}
        </div>
        <div style="margin-top:10px">
          <button class="btn sm" data-saveperm="${u.id}">Save permissions</button>
        </div>`}
      </div>`).join("")}`;
  view().querySelectorAll("[data-badge]").forEach((b) => b.onclick = async () => {
    const [uid, name] = b.dataset.badge.split(":");
    const { token } = await api(`/api/admin/users/${uid}/badge`,
                                { method: "POST" });
    modal(`<h3>${esc(name)}'s clock badge</h3>
      <p class="dim">Print it, or let them photograph it. Holding it up to
        the clock tablet punches them in or out. It is not a sign-in: a copy
        can only clock them in, which you would see on the timesheet.</p>
      <div style="text-align:center;padding:12px">${qrImg(token, 170)}</div>
      <div class="modal-acts">
        <button class="btn alt" data-close>Close</button>
        <button class="btn alt danger-hint" id="badge-reset">Issue a new one</button>
        <button class="btn" onclick="window.print()">Print</button>
      </div>`);
    $("#badge-reset").onclick = async () => {
      if (!confirm("Issue a new badge? Anything already printed stops "
        + "working.")) return;
      const r = await api(`/api/admin/users/${uid}/badge?reset=1`,
                          { method: "POST" });
      $("#ops-modal").querySelector("div[style*='text-align:center']")
        .innerHTML = qrImg(r.token, 170);
      toast("New badge issued");
    };
  });
  view().querySelectorAll("[data-setpin]").forEach((b) => b.onclick = () => {
    const [uid, name] = b.dataset.setpin.split(":");
    modal(`<h3>Time-clock PIN — ${esc(name)}</h3>
      <p class="dim">PINs are stored hashed, so nobody — including you — can
        look one up. Forgotten means issued again, which is the right answer
        anyway: a PIN a manager can read is a PIN a manager can use to clock
        someone in.</p>
      <label>New PIN <span class="dim">(4–8 digits)</span></label>
      <input id="pin-new" inputmode="numeric" autocomplete="off">
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn alt" id="pin-clear">Remove their PIN</button>
        <button class="btn" id="pin-save">Set PIN</button>
      </div>`);
    const send = async (pin) => {
      try {
        const r = await api(`/api/admin/users/${uid}/pin`, { body: { pin } });
        closeModal();
        toast(r.cleared ? `${name} can no longer clock in with a PIN`
                        : `New PIN set for ${name} — tell them in person`);
        renderStaff();
      } catch (e) { toast(e.message); }
    };
    $("#pin-save").onclick = () => send($("#pin-new").value.trim());
    $("#pin-clear").onclick = () => send("");
  });
  view().querySelectorAll("[data-saveperm]").forEach((b) => b.onclick = async () => {
    const uid = b.dataset.saveperm;
    const picked = [...view().querySelectorAll(`[data-perm^="${uid}:"]`)]
      .filter((c) => c.checked).map((c) => c.dataset.perm.split(":")[1]);
    try {
      await api(`/api/store/admin/staff/${uid}/permissions`,
        { body: { permissions: picked } });
      toast("Permissions saved");
      renderStaff();
    } catch (e) { toast(e.message); }
  });
}

// ---------- events ----------
async function renderEvents() {
  const rows = await api("/api/store/admin/events");
  const now = Date.now() / 1000;
  const upcoming = rows.filter((e) => e.starts >= now);
  const past = rows.filter((e) => e.starts < now);
  const card = (e) => `
    <div class="card ${e.starts < now ? "dim-card" : ""}">
      <div class="doc-top">
        <span class="ev-date"><b>${new Date(e.starts * 1000)
          .getDate()}</b>${new Date(e.starts * 1000)
          .toLocaleString(undefined, { month: "short" }).toUpperCase()}</span>
        <div class="doc-main">
          <b>${esc(e.name)}</b>
          <span class="dim">${esc(e.kind)}${
            e.venue ? " · " + esc(e.venue) : ""}${
            e.city ? " · " + esc(e.city) : ""}${
            e.region ? " · " + esc(e.region) : ""}</span>
        </div>
        <span class="pill ${e.active ? "ok" : ""}">${e.active ? "live" : "hidden"}</span>
        <button class="btn alt sm" data-evedit="${e.id}">Edit</button>
        <button class="btn alt sm" data-rowdel="event:${e.id}">Delete</button>
      </div>
      ${e.body ? `<p class="dim" style="margin-top:8px">${esc(e.body)}</p>` : ""}
    </div>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Events</h2>
        <p class="dim">Tastings, pop-ups and markets. These appear on
          <a href="/events" target="_blank">the public events page</a>; past
          events drop off it automatically.</p></div>
      <button class="btn" id="ev-new">${opsIcon("calendar","btn-ic")} New event</button>
    </div>
    <h3>Upcoming (${upcoming.length})</h3>
    ${upcoming.map(card).join("") || '<div class="card empty"><span class="e-ic">'
      + opsIcon("calendar") + '</span><b>Nothing scheduled</b></div>'}
    ${past.length ? `<h3>Past (${past.length})</h3>${past.map(card).join("")}` : ""}`;
  $("#ev-new").onclick = () => eventForm(null);
  view().querySelectorAll("[data-evedit]").forEach((b) => b.onclick = () =>
    eventForm(rows.find((x) => x.id === +b.dataset.evedit)));
  wireRows({}, renderEvents);
}

function eventForm(e) {
  const kinds = ["tasting", "popup", "market", "class"];
  const d = e && e.starts
    ? new Date(e.starts * 1000).toISOString().slice(0, 10) : "";
  modal(`<h3>${e ? "Edit event" : "New event"}</h3>
    <label>Name</label><input id="ef-name" value="${esc((e && e.name) || "")}">
    <div class="row2">
      <div><label>Kind</label><select id="ef-kind">${kinds.map((k) =>
        `<option ${e && e.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      <div><label>Date</label><input id="ef-date" type="date" value="${d}"></div>
    </div>
    <div class="row2">
      <div><label>Venue</label><input id="ef-venue" value="${esc((e && e.venue) || "")}"></div>
      <div><label>City</label><input id="ef-city" value="${esc((e && e.city) || "")}"></div>
    </div>
    <div class="row2">
      <div><label>Region</label><input id="ef-region" value="${esc((e && e.region) || "")}"></div>
      <div><label>Link</label><input id="ef-url" value="${esc((e && e.url) || "")}"></div>
    </div>
    <label>Details</label><textarea id="ef-body" rows="3">${esc((e && e.body) || "")}</textarea>
    <label class="perm" style="margin-top:14px">
      <input type="checkbox" id="ef-live" ${!e || e.active ? "checked" : ""}>
      <span><b>Live</b><small>Shown on the public events page</small></span></label>
    <div class="modal-acts">
      ${e ? '<button class="btn alt" id="ef-del" style="margin-right:auto">Delete</button>' : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ef-save">Save</button>
    </div>`);
  $("#ef-save").onclick = async () => {
    const name = $("#ef-name").value.trim();
    if (!name) return toast("an event needs a name");
    const dv = $("#ef-date").value;
    const payload = { name, kind: $("#ef-kind").value,
      venue: $("#ef-venue").value.trim(), city: $("#ef-city").value.trim(),
      region: $("#ef-region").value.trim(), url: $("#ef-url").value.trim(),
      body: $("#ef-body").value.trim(),
      active: $("#ef-live").checked ? 1 : 0,
      starts: dv ? new Date(dv + "T12:00").getTime() / 1000
        : (e ? e.starts : Date.now() / 1000) };
    try {
      if (e) await api(`/api/store/admin/events/${e.id}`,
        { method: "PATCH", body: payload });
      else await api("/api/store/admin/events", { body: payload });
      closeModal(); renderEvents();
    } catch (err) { toast(err.message); }
  };
  if (e && $("#ef-del")) $("#ef-del").onclick = async () => {
    if (!confirm(`Delete "${e.name}"?`)) return;
    await api(`/api/store/admin/events/${e.id}`, { method: "DELETE" });
    closeModal(); renderEvents();
  };
}

// ---------- profile ----------
async function renderProfile() {
  /* Your own record is the one screen that has to work for everyone signed
     in. Achievements and company level are the business's scoreboard, and
     both endpoints are owner-only — awaiting them alongside /api/me meant a
     customer or an employee opening their own profile got nothing at all,
     because one rejected promise fails the whole batch. They're optional
     now, and the sections they feed simply aren't drawn without them. */
  const [me, ach, game] = await Promise.all([
    api("/api/me"),
    api("/api/achievements").catch(() => []),
    api("/api/game").catch(() => null)]);
  const earned = ach.filter((a) => a.unlocked_at);
  const locked = ach.filter((a) => !a.unlocked_at);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${esc(me.name)}</h2>
        <p class="dim">${esc(me.role)}${me.is_admin ? " · owner" : ""}
          ${me.job && me.job !== "general" ? " · " + esc(JOB_LABEL[me.job] || me.job) : ""}
          ${me.region ? " · " + esc(me.region) : ""}</p></div>
      <button class="btn" id="pf-edit">Edit profile</button>
    </div>

    <div class="stats">
      ${ach.length ? `<div class="stat"><div class="n">${earned.length}</div>
        <div class="l">achievements</div>
        <div class="d dim">of ${ach.length}</div></div>` : ""}
      ${game ? `<div class="stat"><div class="n">${esc(game.company.level)}</div>
        <div class="l">company level</div></div>` : ""}
      <div class="stat"><div class="n">${me.has_pin ? "set" : "—"}</div>
        <div class="l">time-clock PIN</div>
        <div class="d dim">${me.has_pin ? "ready to clock in" : "not set"}</div></div>
      <div class="stat"><div class="n">${me.member_since
        ? fmtDate(me.member_since) : "—"}</div>
        <div class="l">member since</div></div>
    </div>

    <div class="row">
      <div class="card" style="flex:2;min-width:300px">
        <h3 style="margin-top:0">Sign in on your phone</h3>
        <p class="dim">Scan this and your phone lands signed in as you. Single
          use, expires in a few minutes — quicker than typing a password on a
          handset in a cold warehouse.</p>
        <div id="pf-qr" style="text-align:center;padding:10px"></div>
        <button class="btn alt" id="pf-qr-go">Generate a sign-in QR</button>
      </div>
      <div class="card" style="flex:1;min-width:240px">
        <h3 style="margin-top:0">Your time-clock badge</h3>
        <p class="dim">Hold this up to the clock tablet to punch in or out.
          It identifies you, but it isn't a sign-in — someone who copies it
          can only clock you in, not open your account. Print it, or keep it
          on your phone.</p>
        <div id="pf-badge" style="text-align:center;padding:10px"></div>
        <button class="btn alt" id="pf-badge-go">Show my badge</button>
        <button class="btn alt" id="pf-badge-reset">Issue a new one</button>
      </div>
      <div class="card" style="flex:1;min-width:220px">
        <h3 style="margin-top:0">Account</h3>
        <table>
          <tr><td class="dim">Email</td><td>${esc(me.email || "—")}</td></tr>
          <tr><td class="dim">Region</td><td>${esc(me.region || "—")}</td></tr>
          <tr><td class="dim">Employment</td><td>${esc(me.employment || "—")}</td></tr>
        </table>
      </div>
    </div>

    ${ach.length ? `<h3>Achievements</h3>
    <div class="ach-grid">
      ${earned.map((a) => `<div class="ach-card on">
        <span class="ach-ic">${opsIcon(a.icon || "shield2")}</span>
        <b>${esc(a.name)}</b><span class="dim">${esc(a.desc || "")}</span>
        <span class="ach-when">${fmtDate(a.unlocked_at)}</span></div>`).join("")}
      ${locked.map((a) => `<div class="ach-card">
        <span class="ach-ic">${opsIcon(a.icon || "shield2")}</span>
        <b>${esc(a.name)}</b><span class="dim">${esc(a.desc || "")}</span>
        <span class="ach-when">${esc(a.progress || "locked")}</span></div>`)
        .join("")}
    </div>` : ""}`;

  const showBadge = async (reset) => {
    if (reset && !confirm("Issue a new badge? The old one stops working, so "
      + "anything printed with it needs replacing.")) return;
    const { token } = await api(
      `/api/me/badge${reset ? "?reset=1" : ""}`, { method: "POST" });
    $("#pf-badge").innerHTML = qrImg(token, 150);
  };
  $("#pf-badge-go").onclick = () => showBadge(false);
  $("#pf-badge-reset").onclick = () => showBadge(true);

  $("#pf-edit").onclick = () => {
    modal(`<h3>Edit profile</h3>
      <label>Name</label><input id="me-name" value="${esc(me.name)}">
      <label>Email</label><input id="me-email" type="email" value="${esc(me.email || "")}">
      <div class="row2">
        <div><label>Region</label><select id="me-region">
          <option value="">—</option>
          ${S.meta.regions.map((r) => `<option ${r === me.region ? "selected" : ""}>${r}</option>`).join("")}
        </select></div>
        <div><label>Time-clock PIN</label>
          <input id="me-pin" inputmode="numeric" placeholder="${me.has_pin ? "leave blank to keep" : "4–8 digits"}"></div>
      </div>
      <p class="dim" style="font-size:12px;margin-top:10px">Role and
        permissions aren't editable here — those are granted by an owner, not
        chosen.</p>
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="me-save">Save</button>
      </div>`);
    $("#me-save").onclick = async () => {
      const payload = { name: $("#me-name").value, email: $("#me-email").value,
        region: $("#me-region").value };
      if ($("#me-pin").value.trim()) payload.pin = $("#me-pin").value.trim();
      try {
        await api("/api/me", { body: payload });
        closeModal();
        if (S.user) { S.user.name = payload.name;
          localStorage.setItem("bc_user", JSON.stringify(S.user)); }
        toast("Profile saved"); renderProfile(); renderChrome();
      } catch (e) { toast(e.message); }
    };
  };
  $("#pf-qr-go").onclick = async () => {
    const out = await api("/api/me/qr", { method: "POST" });
    $("#pf-qr").innerHTML = `${qrImg(out.url, 190)}
      <div class="dim" style="font-size:12px;margin-top:6px">
        expires in ${Math.round(out.expires_sec / 60)} minutes · single use</div>`;
  };
}

// ---------- stores ----------
async function renderStores() {
  const stores = S._stores = await api("/api/stores");
  const inv = await api("/api/inventory").catch(() => []);
  const lowBy = {};
  inv.forEach((i) => { if (i.low) lowBy[i.store_id] = (lowBy[i.store_id] || 0) + 1; });
  const q = (S.storeQ || "").toLowerCase();
  const shown = stores.filter((s) =>
    !q || (s.name + " " + s.city + " " + s.region).toLowerCase().includes(q));
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Stores</h2>
        <p class="dim">Every account, where it is, and what's low. Retail
          shops and distribution centres.</p></div>
      ${S.user && S.user.is_admin
        ? `<button class="btn" id="st-new">${opsIcon("store","btn-ic")} Add store</button>` : ""}
    </div>
    <div class="stats">
      <div class="stat"><div class="n">${stores.length}</div><div class="l">accounts</div></div>
      <div class="stat"><div class="n">${stores.filter((s) => s.kind === "distributor_dc").length}</div>
        <div class="l">distribution centres</div></div>
      <div class="stat"><div class="n">${Object.keys(lowBy).length}</div>
        <div class="l">stores with low stock</div></div>
    </div>
    ${panZoomMap({ id: "stores-map", pins: stores.map((s) => ({
      lat: s.lat, lng: s.lng, color: REGION_COLORS[s.region] || "#8b98a5",
      size: s.kind === "distributor_dc" ? 10 : 6,
      label: s.name, sub: s.city })) })}
    <div class="filters">
      <input id="st-q" placeholder="Filter stores" value="${esc(S.storeQ || "")}">
    </div>
    <div class="card"><table>
      <thead><tr><th>store</th><th>city</th><th>region</th><th>kind</th>
        <th class="num">low items</th><th>contact</th><th></th></tr></thead>
      <tbody>${shown.map((s) => `<tr>
        <td><b>${esc(s.name)}</b></td><td>${esc(s.city || "—")}</td>
        <td>${esc(s.region)}</td>
        <td>${s.kind === "distributor_dc" ? "DC" : "retail"}</td>
        <td class="num ${lowBy[s.id] ? "low" : ""}">${lowBy[s.id] || 0}</td>
        <td class="dim">${esc(s.contact || "—")}</td>
        <td>${rowActions("store", s)}</td></tr>`).join("")}
      </tbody></table></div>`;
  wireRows({ store: stores }, renderStores);
  let t;
  $("#st-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.storeQ = e.target.value; renderStores(); }, 200); };
  if ($("#st-new")) $("#st-new").onclick = () => {
    modal(`<h3>Add store</h3>
      <label>Name</label><input id="ns-name">
      <div class="row2">
        <div><label>City</label><input id="ns-city"></div>
        <div><label>Region</label><select id="ns-region">
          ${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Latitude</label><input id="ns-lat" type="number" step="0.0001"></div>
        <div><label>Longitude</label><input id="ns-lng" type="number" step="0.0001"></div>
      </div>
      <label>Kind</label><select id="ns-kind">
        <option value="retail">Retail</option>
        <option value="distributor_dc">Distribution centre</option></select>
      <label>Contact</label><input id="ns-contact">
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="ns-save">Add</button></div>`);
    $("#ns-save").onclick = async () => {
      if (!$("#ns-name").value.trim()) return toast("a store needs a name");
      try {
        await api("/api/admin/stores", { body: {
          name: $("#ns-name").value.trim(), city: $("#ns-city").value.trim(),
          region: $("#ns-region").value, kind: $("#ns-kind").value,
          contact: $("#ns-contact").value.trim(),
          lat: +$("#ns-lat").value || null, lng: +$("#ns-lng").value || null } });
        closeModal(); S._stores = null; renderStores();
      } catch (e) { toast(e.message); }
    };
  };
}

// ---------- email campaigns ----------
async function renderEmail() {
  const d = await api("/api/store/admin/email/campaigns");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Email campaigns</h2>
        <p class="dim">Write once, send to an audience that stays accurate on
          its own. Orders are counted from the ledger via the campaign's
          discount code, not from an open-tracking pixel.</p></div>
      <button class="btn" id="em-new">${opsIcon("megaphone","btn-ic")} New campaign</button>
    </div>
    <div class="stats">
      ${Object.entries(d.audiences).map(([k, label]) => `
        <div class="stat"><div class="n">${d.sizes[k] ?? 0}</div>
          <div class="l">${esc(label)}</div></div>`).join("")}
      <div class="stat"><div class="n">${d.unsubscribed}</div>
        <div class="l">unsubscribed</div></div>
    </div>
    ${d.campaigns.map((c) => {
      const last = c.sends[0];
      return `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(c.name)}</b>
            <span class="dim">${esc(c.subject)} · ${esc(c.audience_label)}${
              c.discount_code ? " · " + esc(c.discount_code) : ""}</span></div>
          <span class="pill ${c.status === "sent" ? "ok" : ""}">${c.status}</span>
          <button class="btn alt sm" data-emedit="${c.id}">Edit</button>
          <button class="btn alt sm" data-emsend="${c.id}">Send…</button>
        </div>
        ${c.sends.length ? `<div class="cp-stats" style="margin-top:10px">
          <span><b>${last.recipients}</b> recipients</span>
          <span><b>${last.delivered}</b> delivered</span>
          ${last.failed ? `<span class="low"><b>${last.failed}</b> failed</span>` : ""}
          <span><b>${c.orders}</b> orders</span>
          <span><b>${money(c.revenue_cents)}</b> revenue</span>
          <span class="dim">last sent ${fmtDate(last.started_at)}</span>
        </div>` : '<p class="dim" style="margin-top:8px">Never sent.</p>'}
      </div>`;
    }).join("") || `<div class="card empty"><span class="e-ic">${
      opsIcon("megaphone")}</span><b>No campaigns yet</b>
      <p class="dim">Write one, preview it, send a test to yourself, then
        send it for real.</p></div>`}`;
  $("#em-new").onclick = () => emailForm(null, d);
  view().querySelectorAll("[data-emedit]").forEach((b) => b.onclick = () =>
    emailForm(d.campaigns.find((c) => c.id === +b.dataset.emedit), d));
  view().querySelectorAll("[data-emsend]").forEach((b) => b.onclick = () =>
    emailSend(d.campaigns.find((c) => c.id === +b.dataset.emsend), d));
}

function emailForm(c, d) {
  modal(`<h3>${c ? "Edit campaign" : "New campaign"}</h3>
    <label>Name <span class="dim">(internal)</span></label>
    <input id="ec-name" value="${esc((c && c.name) || "")}">
    <div class="row2">
      <div><label>Audience</label><select id="ec-aud">
        ${Object.entries(d.audiences).map(([k, label]) =>
          `<option value="${k}" ${c && c.audience === k ? "selected" : ""}>
            ${esc(label)} (${d.sizes[k] ?? 0})</option>`).join("")}
      </select></div>
      <div><label>Discount code</label>
        <input id="ec-code" value="${esc((c && c.discount_code) || "")}"
          placeholder="optional"></div>
    </div>
    <label>Subject</label><input id="ec-subj" value="${esc((c && c.subject) || "")}">
    <label>Body</label>
    <textarea id="ec-body" rows="8">${esc((c && c.body) || "")}</textarea>
    <p class="dim" style="font-size:12px;margin-top:8px">Placeholders:
      <code>{name}</code> <code>{email}</code> <code>{code}</code>.
      An unsubscribe link is appended to every send automatically.</p>
    <div class="modal-acts">
      ${c ? '<button class="btn alt" id="ec-del" style="margin-right:auto">Delete</button>' : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ec-save">Save</button>
    </div>`);
  $("#ec-save").onclick = async () => {
    const payload = { name: $("#ec-name").value, subject: $("#ec-subj").value,
      body: $("#ec-body").value, audience: $("#ec-aud").value,
      discount_code: $("#ec-code").value };
    try {
      if (c) await api(`/api/store/admin/email/campaigns/${c.id}`,
        { method: "PATCH", body: payload });
      else await api("/api/store/admin/email/campaigns", { body: payload });
      closeModal(); renderEmail();
    } catch (e) { toast(e.message); }
  };
  if (c && $("#ec-del")) $("#ec-del").onclick = async () => {
    if (!confirm(`Delete "${c.name}"?`)) return;
    await api(`/api/store/admin/email/campaigns/${c.id}`, { method: "DELETE" });
    closeModal(); renderEmail();
  };
}

async function emailSend(c) {
  const p = await api(`/api/store/admin/email/campaigns/${c.id}/preview`);
  modal(`<h3>Send "${esc(c.name)}"</h3>
    <p class="dim">Going to <b>${p.recipients}</b> people
      (${esc(c.audience_label)}). Unsubscribes are removed at send time.</p>
    <div class="card" style="background:var(--bg)">
      <div class="dim" style="font-size:11px">SUBJECT</div>
      <b>${esc(p.subject)}</b>
      <div class="dim" style="font-size:11px;margin-top:10px">BODY</div>
      <div style="white-space:pre-wrap;font-size:13px">${esc(p.body)}</div>
    </div>
    <label>Send a test first</label>
    <div class="row2">
      <input id="es-test" type="email" placeholder="you@example.com">
      <button class="btn alt" id="es-testgo">Send test</button>
    </div>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="es-go">Send to ${p.recipients} people</button>
    </div>
    <p class="msg" id="es-msg"></p>`);
  $("#es-testgo").onclick = async () => {
    try {
      await api(`/api/store/admin/email/campaigns/${c.id}/send`,
        { body: { test_to: $("#es-test").value.trim() } });
      $("#es-msg").textContent = "Test sent.";
    } catch (e) { $("#es-msg").textContent = e.message; }
  };
  $("#es-go").onclick = async () => {
    if (!confirm(`Send to ${p.recipients} people? This can't be undone.`)) return;
    try {
      const out = await api(`/api/store/admin/email/campaigns/${c.id}/send`,
        { body: {} });
      closeModal();
      toast(`Sending to ${out.recipients} people…`);
      setTimeout(renderEmail, 2500);
    } catch (e) { $("#es-msg").textContent = e.message; }
  };
}

// ---------- discord ----------
async function renderDiscord() {
  const d = await api("/api/store/admin/discord");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Discord</h2>
        <p class="dim">Let the business talk to the room the team already
          sits in — and answer from here. Webhooks push alerts out; connect a
          bot and you can read the channels and reply without leaving.</p></div>
      <button class="btn" id="dc-add">Add channel</button>
    </div>

    <div class="card dc-bot">
      <div class="doc-top">
        <div class="doc-main">
          <b>${d.bot ? esc(d.bot.guild_name || "Discord server") : "Read and reply"}</b>
          <span class="dim">${d.bot
            ? `connected as ${esc(d.bot.bot_name)} — channels below are live`
            : "connect a bot to read channels and reply from here"}</span>
        </div>
        <button class="btn ${d.bot ? "alt" : ""} sm" id="dc-bot">${
          d.bot ? "Disconnect" : "Connect a bot"}</button>
      </div>
    </div>
    ${d.bot ? '<div id="dc-chat"></div>' : ""}

    <h3>Alert channels</h3>
    ${d.channels.map((c) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(c.label)}</b>
          <span class="dim">webhook stored · added ${fmtDate(c.created_at)}</span></div>
        <span class="pill ${c.active ? "ok" : ""}">${c.active ? "active" : "off"}</span>
        <button class="btn alt sm" data-dctest="${c.id}">Send test</button>
        <button class="btn alt sm" data-dcdel="${c.id}">Remove</button>
      </div></div>`).join("") || `<div class="card empty"><span class="e-ic">${
        opsIcon("chat")}</span><b>No channels yet</b>
        <p class="dim">In Discord: Server settings → Integrations → Webhooks →
          New webhook, then paste the URL here.</p></div>`}

    ${d.channels.length ? `
      <div class="page-head" style="margin-top:22px">
        <div><h3 style="margin:0">Rules</h3></div>
        <button class="btn" id="dc-rule">Add rule</button>
      </div>
      ${d.rules.map((r) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main">
            <b>${esc(d.events[r.event] || r.event)} → ${esc(r.channel_label)}</b>
            <span class="dim">${r.condition_field
              ? `only when ${esc(r.condition_field)} ${esc(r.condition_op)} ${esc(r.condition_value)}`
              : "every time"} · fired ${r.fired}×${
              r.last_fired ? " · last " + fmtDate(r.last_fired) : ""}</span>
          </div>
          <label class="perm" style="border:none;padding:0">
            <input type="checkbox" data-dcon="${r.id}" ${r.active ? "checked" : ""}>
            <span><b>on</b></span></label>
          <button class="btn alt sm" data-dcruledel="${r.id}">Remove</button>
        </div></div>`).join("") || '<p class="dim">No rules yet.</p>'}` : ""}

    ${d.log.length ? `<h3>Recent deliveries</h3>
      <div class="card"><table>
        <thead><tr><th>when</th><th>event</th><th>result</th></tr></thead>
        <tbody>${d.log.map((l) => `<tr>
          <td class="dim">${fmtDate(l.created_at)}</td>
          <td>${esc(l.event)}</td>
          <td>${l.ok ? '<span class="pill ok">sent</span>'
            : `<span class="pill bad">failed</span> <span class="dim">${esc(l.detail)}</span>`}</td>
        </tr>`).join("")}</tbody></table></div>` : ""}`;

  $("#dc-add").onclick = () => {
    modal(`<h3>Add a Discord channel</h3>
      <p class="dim">In Discord: <b>Server settings → Integrations → Webhooks
        → New webhook</b>. Pick the channel, copy the URL, paste it here.</p>
      <label>Label</label><input id="dc-label" placeholder="#orders">
      <label>Webhook URL</label>
      <input id="dc-url" placeholder="https://discord.com/api/webhooks/...">
      <p class="dim" style="font-size:12px;margin-top:8px">Anyone with this URL
        can post to the channel, so it's stored as a secret and never shown
        again after saving.</p>
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="dc-save">Add</button></div>`);
    $("#dc-save").onclick = async () => {
      try {
        await api("/api/store/admin/discord/channels", { body: {
          label: $("#dc-label").value, webhook: $("#dc-url").value } });
        closeModal(); renderDiscord();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#dc-rule")) $("#dc-rule").onclick = () => {
    modal(`<h3>Add a rule</h3>
      <div class="row2">
        <div><label>When this happens</label><select id="dr-event">
          ${Object.entries(d.events).map(([k, v]) =>
            `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
        <div><label>Post to</label><select id="dr-chan">
          ${d.channels.map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}
        </select></div>
      </div>
      <label>Only when <span class="dim">(optional)</span></label>
      <div class="row2">
        <input id="dr-field" placeholder="field, e.g. total_cents">
        <select id="dr-op"><option value="">—</option>
          ${d.ops.map((o) => `<option>${o}</option>`).join("")}</select>
        <input id="dr-val" placeholder="value">
      </div>
      <label>Message <span class="dim">(blank uses the default)</span></label>
      <input id="dr-tpl" placeholder="">
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="dr-save">Add rule</button></div>`);
    $("#dr-event").onchange = () => {
      $("#dr-tpl").placeholder = d.defaults[$("#dr-event").value] || "";
    };
    $("#dr-event").onchange();
    $("#dr-save").onclick = async () => {
      try {
        await api("/api/store/admin/discord/rules", { body: {
          channel_id: +$("#dr-chan").value, event: $("#dr-event").value,
          condition_field: $("#dr-field").value,
          condition_op: $("#dr-op").value,
          condition_value: $("#dr-val").value,
          template: $("#dr-tpl").value } });
        closeModal(); renderDiscord();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-dctest]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/store/admin/discord/channels/${b.dataset.dctest}/test`,
      { method: "POST" }); toast("Test posted to Discord"); renderDiscord(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-dcdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this channel and its rules?")) return;
    await api(`/api/store/admin/discord/channels/${b.dataset.dcdel}`,
      { method: "DELETE" }); renderDiscord();
  });
  view().querySelectorAll("[data-dcruledel]").forEach((b) => b.onclick = async () => {
    await api(`/api/store/admin/discord/rules/${b.dataset.dcruledel}`,
      { method: "DELETE" }); renderDiscord();
  });
  view().querySelectorAll("[data-dcon]").forEach((c) => c.onchange = async () => {
    await api(`/api/store/admin/discord/rules/${c.dataset.dcon}`,
      { method: "PATCH", body: { active: c.checked } }); renderDiscord();
  });

  $("#dc-bot").onclick = () => d.bot ? disconnectBot() : connectBotModal();
  if (d.bot) drawDiscordChat();
}

function connectBotModal() {
  modal(`<h3>Connect a Discord bot</h3>
    <p class="dim">A webhook can only push messages out. Reading a channel or
      replying in it needs a bot, so this step is separate — skip it and the
      alerts still work.</p>
    <ol class="dim" style="font-size:13px;padding-left:18px;line-height:1.7">
      <li>At <b>discord.com/developers/applications</b>, make an application
        and add a bot.</li>
      <li>Under <b>Bot</b>, reset and copy the token.</li>
      <li>Invite it to your server with <b>View Channels</b>,
        <b>Read Message History</b> and <b>Send Messages</b>.</li>
      <li>Right-click the server name → <b>Copy Server ID</b>.</li>
    </ol>
    <label>Bot token</label><input id="dc-token" type="password"
      placeholder="paste the token">
    <label>Server ID</label><input id="dc-guild" placeholder="e.g. 913…">
    <p class="dim" style="font-size:12px;margin-top:8px">The token can post as
      the bot anywhere it's a member, so it's stored as a secret and never
      shown again.</p>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="dc-bot-save">Connect</button></div>`);
  $("#dc-bot-save").onclick = async () => {
    const b = $("#dc-bot-save");
    b.disabled = true; b.setAttribute("aria-busy", "true");
    b.textContent = "checking…";
    try {
      const r = await api("/api/store/admin/discord/bot", { body: {
        token: $("#dc-token").value, guild_id: $("#dc-guild").value } });
      closeModal();
      toast(`Connected as ${r.bot_name} in ${r.guild_name}`);
      renderDiscord();
    } catch (e) {
      toast(e.message); b.disabled = false; b.textContent = "Connect";
    }
  };
}

async function disconnectBot() {
  if (!confirm("Disconnect the bot? Alert webhooks keep working.")) return;
  await api("/api/store/admin/discord/bot", { method: "DELETE" });
  renderDiscord();
}

/* The channel reader. Kept deliberately plain: this is for seeing what the
   room is saying and answering it, not for reimplementing Discord. */
async function drawDiscordChat() {
  const box = $("#dc-chat");
  if (!box) return;
  let list;
  try {
    list = await api("/api/store/admin/discord/chat/channels");
  } catch (e) {
    box.innerHTML = `<div class="card"><p class="dim">${esc(e.message)}</p></div>`;
    return;
  }
  if (!list.channels.length) {
    box.innerHTML = `<div class="card"><p class="dim">The bot can't see any
      text channels — give it <b>View Channel</b> on the ones you want
      here.</p></div>`;
    return;
  }
  if (!S.dcChan || !list.channels.some((c) => c.id === S.dcChan)) {
    S.dcChan = list.channels[0].id;
  }
  box.innerHTML = `
    <div class="dc-wrap">
      <div class="dc-list">${list.channels.map((c) => `
        <button class="dc-c ${c.id === S.dcChan ? "on" : ""}" data-dcc="${c.id}">
          <b>#${esc(c.name)}</b>${c.topic
            ? `<span class="dim">${esc(c.topic)}</span>` : ""}</button>`).join("")}
      </div>
      <div class="dc-room">
        <div class="dc-msgs" id="dc-msgs"><p class="dim">Loading…</p></div>
        <form class="dc-say" id="dc-say">
          <input id="dc-text" placeholder="Message #${esc(
            (list.channels.find((c) => c.id === S.dcChan) || {}).name || "")}"
            autocomplete="off">
          <button class="btn">Send</button>
        </form>
      </div>
    </div>`;
  box.querySelectorAll("[data-dcc]").forEach((b) => b.onclick = () => {
    S.dcChan = b.dataset.dcc; drawDiscordChat();
  });
  $("#dc-say").onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#dc-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await api(`/api/store/admin/discord/chat/${S.dcChan}/messages`,
                { body: { content: text } });
      loadDiscordMsgs();
    } catch (err) { toast(err.message); input.value = text; }
  };
  loadDiscordMsgs();
  // Poll while the tab is open. Cleared on any tab change by render().
  clearInterval(S._dcTimer);
  S._dcTimer = setInterval(() => {
    if (S.tab === "discord" && $("#dc-msgs")) loadDiscordMsgs();
    else clearInterval(S._dcTimer);
  }, 15000);
}

async function loadDiscordMsgs() {
  const el = $("#dc-msgs");
  if (!el) return;
  try {
    const d = await api(
      `/api/store/admin/discord/chat/${S.dcChan}/messages`);
    // Only redraw when something changed, so a poll doesn't yank the
    // scroll position out from under someone reading.
    const sig = d.messages.map((m) => m.id).join(",");
    if (sig === el.dataset.sig) return;
    el.dataset.sig = sig;
    el.innerHTML = d.messages.map((m) => `
      <div class="dc-m${m.bot ? " bot" : ""}">
        <div class="dc-who">${esc(m.author)}${m.bot
          ? '<span class="pill">bot</span>' : ""}
          <span class="dim">${fmtDate(Date.parse(m.at) / 1000)}</span></div>
        <div class="dc-body">${esc(m.content) || '<i class="dim">—</i>'}${
          m.attachments.map((a) =>
            `<span class="pill">${esc(a)}</span>`).join("")}</div>
      </div>`).join("") || '<p class="dim">Nothing here yet.</p>';
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    el.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
  }
}
