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
  { id: "till", label: "Till", icon: "card", group: "Sell",
    roles: ["admin", "employee", "cashier"], perm: "till" },
  { id: "orders", label: "Orders", icon: "box", group: "Sell", roles: "*" },
  { id: "customers", label: "Customers", icon: "users", group: "Sell",
    roles: ["admin", "employee"] },
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
  { id: "field", label: "Field", icon: "pin", group: "Operate",
    roles: ["admin", "employee", "cashier"] },
  { id: "routes", label: "Routes", icon: "truck", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "supply", label: "Sourcing", icon: "tools", group: "Operate",
    roles: ["admin"], perm: "supply" },
  { id: "outreach", label: "Outreach", icon: "handshake", group: "Operate",
    roles: ["admin", "employee"] },
  { id: "learning", label: "Learning", icon: "pen", group: "Operate",
    roles: ["admin", "employee", "teacher"] },
  { id: "nutrition", label: "Nutrition", icon: "bag", group: "Operate",
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
  // Work and dates, where the work is. The board is what everyone is
  // doing; the calendar is everything this business has a date for, laid
  // over each other for once.
  { id: "rota", label: "Rota", icon: "calendar", group: "Operate",
    roles: ["admin", "employee", "teacher", "volunteer"] },
  { id: "hours", label: "Hours", icon: "clock", group: "Operate",
    roles: ["admin", "employee", "teacher"] },
  { id: "board", label: "Board", icon: "list", group: "Operate",
    roles: ["admin", "employee", "teacher"] },
  { id: "calendar", label: "Calendar", icon: "calendar", group: "Operate",
    roles: ["admin", "employee", "teacher"] },
  { id: "email", label: "Email", icon: "megaphone", group: "Grow",
    roles: ["admin"] },
  { id: "docs", label: "Documents", icon: "file", group: "Company",
    roles: ["admin", "employee"] },
  { id: "staff", label: "Team & access", icon: "users", group: "Company",
    roles: ["admin"] },
  // Every connection lives in one group. Four of them earned bespoke
  // screens because they do more than connect — Slack reads channels,
  // Trello syncs cards — and the rest share one screen whose whole story
  // is "is it connected, what has it carried, and can I test it". Which
  // is a screen, and belongs where a person looks for it rather than
  // three clicks inside a list. The list itself leads, because that is
  // where a connection is set up and where your own ones are declared.
  { id: "integrations", label: "All connections", icon: "link",
    group: "Connections", roles: ["admin"] },
  { id: "discord", label: "Discord", icon: "chat", group: "Connections",
    roles: ["admin"] },
  { id: "slack", label: "Slack", icon: "megaphone", group: "Connections",
    roles: ["admin"] },
  { id: "trello", label: "Trello", icon: "list", group: "Connections",
    roles: ["admin"] },
  { id: "dropbox", label: "Dropbox", icon: "file", group: "Connections",
    roles: ["admin"] },
  { id: "ig-quickbooks", label: "QuickBooks", icon: "chart",
    group: "Connections", roles: ["admin"] },
  { id: "ig-pipedrive", label: "Pipedrive", icon: "handshake",
    group: "Connections", roles: ["admin"] },
  { id: "ig-google_calendar", label: "Google Calendar", icon: "calendar",
    group: "Connections", roles: ["admin"] },
  { id: "ig-google_drive", label: "Google Drive", icon: "file",
    group: "Connections", roles: ["admin"] },
  { id: "ig-gmail", label: "Google Mail", icon: "megaphone",
    group: "Connections", roles: ["admin"] },
  { id: "ig-canva", label: "Canva", icon: "pen",
    group: "Connections", roles: ["admin"] },
  { id: "ig-docusign", label: "DocuSign", icon: "file",
    group: "Connections", roles: ["admin"] },
  { id: "ig-laceup", label: "LaceUp", icon: "truck",
    group: "Connections", roles: ["admin"] },
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
  shop: "selling", orders: "selling", customers: "selling",
  promos: "marketing", email: "marketing", experiments: "marketing",
  clients: "crm", outreach: "crm",
  clock: "workforce", staff: "workforce",
  inventory: "inventory", supply: "sourcing",
  routes: "distribution", stores: "distribution",
  analytics: "intelligence", events: "events", affiliates: "affiliates",
  learning: "learning", nutrition: "nutrition",
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
  learning: "Learning", nutrition: "Nutrition",
  api: "API & data platform", infosec: "InfoSec",
};
// null caps = everything on: legacy installs, the provider, and any tenant
// stood up before entitlements existed keep the whole product.
const capLocked = (t) => {
  const need = TAB_CAP[t.id];
  const caps = S.meta && S.meta.caps;
  return !!(need && Array.isArray(caps) && !caps.includes(need));
};

const NAV_GROUPS = ["Sell", "Operate", "Grow", "Company",
                    "Connections"];
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
      <span class="ic">${opsIcon(t.icon)}</span>
      <span class="tab-label">${t.label}</span>${
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
    return (tabs.length > 5
      ? `<div class="nav-group tab-group">${g}</div>` : "") +
      group.map(btn).join("");
  }).join("");
  nav.scrollTop = navScroll;
  ensureRailGrip();          // the redraw above takes the grip with it
  trackTopbar();
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
    <b>${title}</b>${hint}</div>`;
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
    staff: renderStaff, events: renderEvents, customers: renderCustomers,
    board: renderBoard, calendar: renderCalendar, hours: renderHours,
    rota: renderSchedule,
    profile: renderProfile, stores: renderStores,
    email: renderEmail, discord: renderDiscord,
    supply: renderSupply, audit: renderAudit, dbview: renderDb,
    till: renderTill, field: renderField,
    integrations: renderIntegrations, slack: renderSlack,
    // every "ig:<name>" tab lands on the same screen, told which one
    ...Object.fromEntries(TABS.filter((t) => t.id.startsWith("ig-"))
      .map((t) => [t.id, () => renderOneIntegration(t.id.slice(3), t.label)])),
    trello: renderTrello, dropbox: renderDropbox,
    hq: renderHQ, fleet: renderFleet, admin: renderAdmin,
    learning: renderLearning,
    nutrition: renderNutrition,
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


// ---------- the grant editor: what a tenant is entitled to ----------
/* One editor, two doors: the Platform tab's row and the client's own
   page. It fetches the fleet board itself when not handed one, saves the
   grant, and grows the site additively for what was newly granted. */
async function capsEditor(tid, opts = {}) {
  let f = opts.fleet;
  try { if (!f) f = await api("/api/store/admin/fleet"); }
  catch (err) { toast(err.message); return; }
  const ten = f.nodes.flatMap((n) => n.tenants).find((t) => t.id === tid);
  if (!ten) { toast(`no install named '${tid}' on the fleet`); return; }
  const cur = new Set(ten.cap_ids || []);
  const all = !cur.size;
  const done = opts.after || renderFleet;
  // the quote's own capability list, for the coverage line — a grant that
  // outruns what was sold should be a visible choice, not a drift
  let quote = null;
  if (ten.client && ten.client.engagement_id) {
    try {
      quote = (await api("/api/store/admin/engagements/"
        + `${ten.client.engagement_id}/stand-up`)).suggestion;
    } catch { quote = null; }
  }
  const groups = [];
  for (const cc of f.cap_catalog) {
    let g = groups.find((x) => x.name === cc.group);
    if (!g) { g = { name: cc.group, items: [] }; groups.push(g); }
    g.items.push(cc);
  }
  modal(`<h3>Capabilities — ${esc(tid)}</h3>
    <p class="dim">${all
      ? "No grant recorded — <b>everything is on</b>. Ticking boxes "
        + "replaces that with an explicit grant."
      : "What the quote sold, editable — this is the button that "
        + "fulfils a capability ask."}</p>
    ${groups.map((g) => `
      <div class="cap-group">${esc(g.name || "Capabilities")}</div>
      <div class="cap-grid">${g.items.map((cc) => `
        <label><input type="checkbox" value="${cc.id}" data-cg
          data-price="${cc.price}"
          ${all || cur.has(cc.id) ? "checked" : ""}> ${esc(cc.name)}
          ${cc.price ? `<span class="cap-price">$${cc.price} ·
            ${esc(cc.band)}</span>` : ""}
        </label>`).join("")}</div>`).join("")}
    <p id="cg-total" style="margin-top:10px;font-size:13.5px"></p>
    <p class="dim" id="cg-quote" style="font-size:12.5px"></p>
    <label style="display:flex;gap:8px;align-items:center;margin-top:10px">
      <input type="checkbox" id="cg-extend" checked style="width:auto">
      Keep their storefront in step — adds what new capabilities earn;
      a revoked capability's untouched scaffolding is removed, and an
      edited section is hidden, kept, and restored if the capability
      returns</label>
    <div class="modal-foot">
      <button class="btn" id="cg-go">Save grant</button>
      <button class="btn alt sm" id="cg-clear" title="back to no grant
        recorded — everything on">Clear grant</button>
      <button class="btn alt" data-close>Cancel</button>
    </div>`);
  /* The money, while approving the money: the live total from the same
     parse every other price on the platform comes from, and how much of
     it the quote actually sold. */
  const retally = () => {
    const on = [...document.querySelectorAll("[data-cg]:checked")];
    const sum = on.reduce((a, x) => a + (+x.dataset.price || 0), 0);
    $("#cg-total").innerHTML = `${on.length} capabilities →
      <b>$${sum}/mo</b>${f.core_price
        ? ` + Platform Core $${f.core_price}` : ""}, before volume
      discount`;
    const qc = quote && quote.cap_ids ? new Set(quote.cap_ids) : null;
    $("#cg-quote").textContent = qc
      ? `The ${quote.signed ? "signed" : "latest (unsigned)"} quote covers `
        + `${on.filter((x) => qc.has(x.value)).length} of these `
        + `${on.length} — anything beyond it is a grant you are choosing `
        + "to make unbilled."
      : "No quote on file — nothing here is billed until one exists.";
  };
  retally();
  document.querySelectorAll("[data-cg]").forEach((x) =>
    x.addEventListener("change", retally));
  $("#cg-go").onclick = async () => {
    const caps = [...document.querySelectorAll("[data-cg]:checked")]
      .map((x) => x.value);
    try {
      const out = await api(
        `/api/store/admin/fleet/tenants/${tid}/caps`,
        { body: { caps, extend_site: $("#cg-extend").checked } });
      closeModal();
      const g = out.grown || {};
      const grew = [...(g.sections || []), ...(g.pages || []),
                    ...(g.restored || []).map((x) => `${x} (restored)`)];
      toast(`${tid}: ${out.caps.length} capabilities`
        + (out.added && out.added.length
           ? ` (+${out.added.join(", ")})` : "")
        + (out.removed && out.removed.length
           ? ` (−${out.removed.join(", ")})` : "")
        + (grew.length ? ` — site grew: ${grew.join(", ")}` : "")
        + (out.trimmed && out.trimmed.length
           ? ` — site trimmed: ${out.trimmed.join(", ")}` : "")
        + (out.hidden && out.hidden.length
           ? ` — hidden (edited, kept): ${out.hidden.join(", ")}` : ""));
      done();
    } catch (err) { toast(err.message); }
  };
  $("#cg-clear").onclick = async () => {
    try {
      await api(`/api/store/admin/fleet/tenants/${tid}/caps`,
        { body: { clear: true } });
      closeModal(); toast(`${tid}: everything on`); done();
    } catch (err) { toast(err.message); }
  };
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
  /* Two explicit doors, like the storefront's. Signing in refuses to mint
     an account from a typo — the old find-or-create quietly created a
     customer under any name typed here, which is how "Boss" the founder on
     one tenant became "boss" the shopper on another. Creating a team
     account is a deliberate act that needs the admin key: the key IS the
     authority the role-request queue exists to consult. Everyone else
     creates their account on the storefront door, which files a claim. */
  const door = S.loginDoor || "signin";
  /* Widths come from the grid, not from inline max-widths on each card. The
     old version pinned the form at 420px and the QR panel at 280px, so on a
     half-width window the two sat as narrow columns with the inputs at
     whatever width the browser felt like, and on a wide one they hugged the
     left edge. */
  view().innerHTML = `
    <h2>Sign in</h2>
    <div class="signin">
      <div class="card signin-form">
        <div class="row" style="margin-bottom:12px">
          <button class="btn sm ${door === "signin" ? "" : "alt"}"
            id="ld-in">Sign in</button>
          <button class="btn sm ${door === "create" ? "" : "alt"}"
            id="ld-new">New team account</button>
        </div>
        <form id="login-form">
          <label>Name<input id="li-name" required autocomplete="name"></label>
          ${door === "create" ? `
          <div class="signin-two">
            <label>Role
              <select id="li-role">
                <option value="customer">customer</option>
                <option value="distributor">distributor</option>
                <option value="influencer">influencer</option>
                <option value="employee">employee / office staff</option>
                <option value="teacher">teacher</option>
                <option value="volunteer">volunteer</option>
                <option value="director">executive director</option>
                <option value="board">board member</option>
                <option value="donor">donor</option>
                <option value="owner">founder / owner</option>
              </select></label>
            <label>Region
              <select id="li-region"><option value=""></option>${regions}</select></label>
          </div>
          <label>Email <span class="dim">for order updates &amp; offers</span>
            <input id="li-email" type="email" placeholder="optional"
              autocomplete="email"></label>` : ""}
          <label>Password<input id="li-pass" type="password"
            autocomplete="current-password"
            placeholder="${door === "create"
              ? "sets on first sign-in, then required"
              : "required if the account has one"}"></label>
          <label>Admin key <span class="dim">${door === "create"
            ? "required — the key is what makes this a grant"
            : "optional — also claims admin on this account"}</span>
            <input id="li-admin" type="password" autocomplete="off"></label>
          ${door === "create" ? `<p class="dim">No key? Create your account
            on <a href="/">the storefront</a> instead — picking a role there
            files a request the office confirms.</p>`
          : `<p class="dim">No account yet? Team accounts are created with
            the admin key (New team account), or from
            <a href="/">the storefront</a> door, which files a role
            request.</p>`}
          <button class="btn">${door === "create"
            ? "Create team account" : "Sign in"}</button>
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

  $("#ld-in").onclick = () => { S.loginDoor = "signin"; renderLogin(); };
  $("#ld-new").onclick = () => { S.loginDoor = "create"; renderLogin(); };
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
    if (door === "create" && !$("#li-admin").value.trim()) {
      toast("Creating a team account needs the admin key");
      return;
    }
    try {
      const u = await api("/api/login", { body: {
        name: $("#li-name").value,
        role: door === "create" ? $("#li-role").value : "customer",
        region: door === "create" ? $("#li-region").value : "",
        admin_key: $("#li-admin").value,
        email: door === "create" ? $("#li-email").value : "",
        password: $("#li-pass").value,
        mode: door === "create" ? "create" : "signin" } });
      S.user = u;
      localStorage.setItem("bc_user", JSON.stringify(u));
      // Somewhere in particular if they were sent here mid-task; otherwise
      // an employee's job home, or the shop.
      S.tab = S.afterLogin
        || (u.role === "employee" && JOB_HOME[u.job])
        || (u.role === "teacher" && "learning") || "shop";
      S.afterLogin = null;
      startNotifPoll();
      connectWS();
      render();
    } catch (err) { toast(err.message); }
  };
}


/* ---------- the rail ----------
   Folded or wide, and any width in between. Somebody who knows this app
   wants the screen back; somebody learning it wants the words. Both are
   right, so it is remembered per person rather than decided for them —
   and the brand is the switch, because that is where a hand already goes. */
function wireRail() {
  const brand = document.getElementById("brand");
  const nav = document.getElementById("tabs");
  if (!brand || !nav || brand.dataset.railed) return;
  brand.dataset.railed = "1";

  const applyWidth = (px) => {
    document.documentElement.style.setProperty("--rail", px + "px");
  };
  const folded = localStorage.getItem("bc_rail_folded") === "1";
  document.body.classList.toggle("rail-folded", folded);
  const w = +localStorage.getItem("bc_rail_w") || 0;
  if (w) applyWidth(w);

  brand.title = "fold the menu away, or bring it back";
  brand.onclick = () => {
    const now = !document.body.classList.contains("rail-folded");
    document.body.classList.toggle("rail-folded", now);
    localStorage.setItem("bc_rail_folded", now ? "1" : "");
  };

  ensureRailGrip();
}

/* The nav is redrawn on every tab change, which takes the grip with it —
   so it is put back after each draw rather than once at boot. */
/* The top bar's height is not a constant: its account line wraps on a
   narrow window. Everything sticky hangs off the measured height rather
   than a number in the stylesheet that is right at one width. */
function trackTopbar() {
  const bar = document.getElementById("topbar");
  if (!bar || trackTopbar.watching) return;
  trackTopbar.watching = true;
  const set = () => document.documentElement.style.setProperty(
    "--topbar", Math.round(bar.getBoundingClientRect().height) + "px");
  set();
  if (window.ResizeObserver) new ResizeObserver(set).observe(bar);
  else addEventListener("resize", set);
}

function ensureRailGrip() {
  const nav = document.getElementById("tabs");
  if (!nav || document.getElementById("rail-grip")) return;
  const applyWidth = (px) => {
    document.documentElement.style.setProperty("--rail", px + "px");
  };
  const grip = document.createElement("div");
  grip.id = "rail-grip";
  // NOT position:relative here. The nav is sticky, which is already a
  // positioned ancestor for the grip — and overwriting it with relative
  // took the nav off the top bar, so a long list of tabs ran off the
  // bottom of the page and the last of them could only be reached by
  // scrolling the document.
  nav.appendChild(grip);
  let dragging = false;
  grip.onpointerdown = (e) => {
    dragging = true;
    grip.setPointerCapture(e.pointerId);
    document.body.style.userSelect = "none";
  };
  grip.onpointermove = (e) => {
    if (!dragging) return;
    // Clamped: a rail dragged to nothing is a rail somebody cannot find
    // again, and one dragged across the screen is a screen with no room
    // left to work in.
    const px = Math.max(54, Math.min(340, e.clientX - nav.getBoundingClientRect().left));
    applyWidth(px);
    document.body.classList.toggle("rail-folded", px < 96);
  };
  grip.onpointerup = () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = "";
    const px = parseInt(getComputedStyle(document.documentElement)
      .getPropertyValue("--rail"), 10) || 176;
    localStorage.setItem("bc_rail_w", px);
    localStorage.setItem("bc_rail_folded",
      document.body.classList.contains("rail-folded") ? "1" : "");
  };
}
