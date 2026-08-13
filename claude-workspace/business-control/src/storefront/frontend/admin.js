/* Store admin — same accounts as the ERP; admin token required. */
"use strict";
const $ = (s) => document.querySelector(s);
const money = (c) => "$" + (c / 100).toFixed(2);
let TOKEN = "";
try { TOKEN = (JSON.parse(localStorage.getItem("bc_user") || "{}").token) || ""; }
catch {}

const H = () => ({ "Content-Type": "application/json",
  Authorization: "Bearer " + TOKEN });
const api = async (url, opts = {}) => {
  const r = await fetch(url, { headers: H(), ...opts,
    ...(opts.body ? { headers: H() } : {}) });
  if (!r.ok) throw new Error((await r.json()).detail || r.status);
  return r.json();
};

// ---------- sign in ----------
// One door for the whole team: sign in here, then get routed to the surface
// your permissions actually cover (back office here, or the ERP at /ops).
let ME = null;

async function tryBoot() {
  if (!TOKEN) return false;
  try { ME = await api("/api/store/admin/whoami"); return true; }
  catch { return false; }
}

$("#li-go").onclick = async () => {
  try {
    const out = await (await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#li-name").value.trim(),
        password: $("#li-pass").value,
        admin_key: $("#li-key").value.trim() }) })).json();
    if (!out.token) throw new Error(out.detail || "sign-in failed");
    TOKEN = out.token;
    localStorage.setItem("bc_user", JSON.stringify(out));
    try {
      ME = await api("/api/store/admin/whoami");
    } catch {
      // Signed in fine, but no back-office permissions — send them to the
      // ERP, which is where their work (time clock, routes, chat) lives.
      $("#li-msg").innerHTML =
        `Signed in as <b>${out.name}</b>. This account doesn't manage the
         store — taking you to the ERP…`;
      setTimeout(() => location.href = "/ops/", 1200);
      return;
    }
    boot();
  } catch (e) { $("#li-msg").textContent = String(e.message || e); }
};

// Which permission each tab needs; tabs you can't use are hidden.
const TAB_PERMS = {
  products: "products", orders: "orders", reviews: "content",
  pages: "content", collections: "products", discounts: "discounts",
  webhooks: "settings", api: "settings", blog: "content",
  affiliates: "customers",
  nav: "content", intl: "settings", staff: "settings",
  analytics: "analytics",
};

function applyPermissions() {
  if (!ME) return;
  const all = ME.permissions.includes("*");
  let firstVisible = null;
  document.querySelectorAll("#adm-tabs .tab").forEach((t) => {
    const need = TAB_PERMS[t.dataset.tab];
    const ok = all || !need || ME.permissions.includes(need);
    t.style.display = ok ? "" : "none";
    if (ok && !firstVisible) firstVisible = t;
  });
  // If the default tab is hidden for this person, open their first one.
  const active = document.querySelector("#adm-tabs .tab.on");
  if (firstVisible && (!active || active.style.display === "none"))
    firstVisible.click();
  const who = document.getElementById("who-label");
  if (who) who.textContent = all
    ? `${ME.name} · full access`
    : `${ME.name} · ${ME.permissions.join(", ") || "no permissions"}`;
}

// ---------- tabs ----------
document.querySelectorAll("#adm-tabs .tab").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#adm-tabs .tab").forEach((x) =>
    x.classList.toggle("on", x === b));
  document.querySelectorAll("[data-panel]").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.panel !== b.dataset.tab));
  if (b.dataset.tab === "analytics") drawAnalytics();
});

// ---------- products ----------
let PRODUCTS = [];
async function drawProducts() {
  PRODUCTS = (await (await fetch("/api/store/catalog")).json()).products;
  $("#pr-list").innerHTML = PRODUCTS.map((p) =>
    `<div class="adm-item"><b>${p.name}</b>
     <span class="dim">${p.sku} · ${p.category || "—"} ·
     ${money(p.price_cents)} · ★${p.review_avg ?? "–"}</span></div>`).join("");
  $("#co-products").innerHTML = PRODUCTS.map((p) =>
    `<label style="display:flex;gap:8px;align-items:center;font-weight:500">
     <input type="checkbox" style="width:auto" value="${p.id}"
      class="co-check"> ${p.name}</label>`).join("");
  fillProductSelect($("#md-product"));
}

$("#pr-add").onclick = async () => {
  const price = +$("#pr-price").value || 0;
  await api("/api/admin/products", { method: "POST",
    body: JSON.stringify({ sku: $("#pr-sku").value.trim(),
      name: $("#pr-name").value.trim(), category: $("#pr-cat").value.trim(),
      description: $("#pr-desc").value.trim(), price_cents: price,
      case_price_cents: +$("#pr-case").value || price * 10 }) });
  drawProducts();
};

// ---------- media ----------
function fillProductSelect(sel) {
  if (!sel || sel.options.length) return;
  sel.innerHTML = PRODUCTS.map((p) =>
    `<option value="${p.id}">${p.name}</option>`).join("");
}

async function drawMedia() {
  const sel = $("#md-product");
  fillProductSelect(sel);
  const pid = +sel.value || (PRODUCTS[0] && PRODUCTS[0].id);
  if (!pid) return;
  const rows = await api(`/api/store/admin/media/${pid}`);
  $("#md-grid").innerHTML = rows.map((m, i) => `
    <div class="md-card ${i === 0 ? "primary" : ""}">
      <div class="md-thumb">
        ${m.kind === "video" && m.video_url
          ? '<span style="font-size:34px">🎬</span>'
          : `<img src="${m.thumb}?v=${m.id}" alt="">`}
        ${i === 0 ? '<span class="md-tag">PRIMARY</span>' : ""}
        ${m.kind === "video" ? '<span class="md-tag" style="left:auto;right:6px;background:#282828">VIDEO</span>' : ""}
      </div>
      <div class="md-body">
        <input data-alt="${m.id}" value="${(m.alt || "").replace(/"/g, "&quot;")}"
          placeholder="alt text">
        <div class="md-acts">
          <button data-mv="${m.id}:primary" title="make primary">★</button>
          <button data-mv="${m.id}:up">←</button>
          <button data-mv="${m.id}:down">→</button>
          <button data-mdel="${m.id}" title="delete">✕</button>
        </div>
      </div>
    </div>`).join("") ||
    '<p class="dim">No media yet — the storefront falls back to a category emoji.</p>';
  $("#md-grid").querySelectorAll("[data-mv]").forEach((b) => b.onclick =
    async () => { const [mid, move] = b.dataset.mv.split(":");
      await api(`/api/store/admin/media/${mid}`, { method: "POST",
        body: JSON.stringify({ move }) }); drawMedia(); });
  $("#md-grid").querySelectorAll("[data-mdel]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/media/${b.dataset.mdel}`,
      { method: "DELETE" }); drawMedia(); drawProducts(); });
  $("#md-grid").querySelectorAll("[data-alt]").forEach((i) => i.onchange =
    async () => { await api(`/api/store/admin/media/${i.dataset.alt}`,
      { method: "POST", body: JSON.stringify({ alt: i.value }) }); });
}

$("#md-product") && ($("#md-product").onchange = drawMedia);
$("#md-add").onclick = async () => {
  const file = $("#md-file").files[0];
  const url = $("#md-url").value.trim();
  const msg = $("#md-msg");
  if (!file && !url) { msg.textContent = "pick a file or paste a URL"; return; }
  msg.textContent = "uploading…";
  const payload = { product_id: +$("#md-product").value,
    alt: $("#md-alt").value.trim(), video_url: url };
  if (file) {
    payload.data_url = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result); fr.onerror = rej;
      fr.readAsDataURL(file);
    });
  }
  try {
    await api("/api/store/admin/media", { method: "POST",
      body: JSON.stringify(payload) });
    msg.textContent = "added ✔";
    $("#md-file").value = ""; $("#md-url").value = ""; $("#md-alt").value = "";
    drawMedia(); drawProducts();
  } catch (e) { msg.textContent = String(e.message || e); }
};

// ---------- variants ----------
async function drawVariants() {
  const sel = $("#vr-product");
  if (!sel.options.length)
    sel.innerHTML = PRODUCTS.map((p) =>
      `<option value="${p.id}">${p.name}</option>`).join("");
  const pid = +sel.value || (PRODUCTS[0] && PRODUCTS[0].id);
  if (!pid) return;
  const rows = await api(`/api/store/admin/variants/${pid}`);
  $("#vr-list").innerHTML = rows.filter((v) => v.active).map((v) =>
    `<div class="adm-item"><b>${v.name}</b>
     <span class="dim">${v.sku || "—"} · ${money(v.price_cents)} ·
     stock ${v.stock}</span>
     <button class="btn-pill ghost mini" data-del="${v.id}">delete</button>
    </div>`).join("") || '<p class="dim">No variants for this product.</p>';
  $("#vr-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/variants/${b.dataset.del}`,
      { method: "DELETE" }); drawVariants(); });
}

$("#vr-product") && ($("#vr-product").onchange = drawVariants);
$("#vr-add").onclick = async () => {
  await api("/api/store/admin/variants", { method: "POST",
    body: JSON.stringify({ product_id: +$("#vr-product").value,
      name: $("#vr-name").value.trim(), option1: $("#vr-opt1").value.trim(),
      option2: $("#vr-opt2").value.trim(), sku: $("#vr-sku").value.trim(),
      price_cents: +$("#vr-price").value || 0,
      stock: +$("#vr-stock").value || 0 }) });
  drawVariants();
};

// ---------- shipping ----------
async function drawShipping() {
  const rows = await (await fetch("/api/store/shipping")).json();
  $("#sh-list").innerHTML = rows.map((m) =>
    `<div class="adm-item"><b>${m.name}</b>
     <span class="dim">${money(m.price_cents)} · ${m.eta || "—"} ·
     pos ${m.position}</span>
     <button class="btn-pill ghost mini" data-del="${m.id}">delete</button>
    </div>`).join("") || '<p class="dim">No methods.</p>';
  $("#sh-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/shipping/${b.dataset.del}`,
      { method: "DELETE" }); drawShipping(); });
}

$("#sh-add").onclick = async () => {
  await api("/api/store/admin/shipping", { method: "POST",
    body: JSON.stringify({ name: $("#sh-name").value.trim(),
      price_cents: +$("#sh-price").value || 0,
      eta: $("#sh-eta").value.trim(),
      position: +$("#sh-pos").value || 1 }) });
  drawShipping();
};

// ---------- pages ----------
async function drawPages() {
  const pages = await api("/api/store/admin/pages");
  $("#pg-list").innerHTML = pages.map((p) =>
    `<div class="adm-item"><b>${p.title}</b>
     <a class="dim" href="/p/${p.slug}" target="_blank">/p/${p.slug} ↗</a>
     <button class="btn-pill ghost mini" data-edit="${p.slug}">edit</button>
     <button class="btn-pill ghost mini" data-del="${p.slug}">delete</button>
    </div>`).join("") || '<p class="dim">No pages yet.</p>';
  $("#pg-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/pages/${b.dataset.del}`,
      { method: "DELETE" }); drawPages(); });
  $("#pg-list").querySelectorAll("[data-edit]").forEach((b) => b.onclick =
    () => { const p = pages.find((x) => x.slug === b.dataset.edit);
      $("#pg-slug").value = p.slug; $("#pg-title").value = p.title;
      $("#pg-html").value = p.content_html; $("#pg-css").value = p.content_css;
      $("#pg-js").value = p.content_js; $("#pg-liquid").value = p.liquid; });
}

$("#pg-save").onclick = async () => {
  await api("/api/store/admin/pages", { method: "POST",
    body: JSON.stringify({ slug: $("#pg-slug").value,
      title: $("#pg-title").value, content_html: $("#pg-html").value,
      content_css: $("#pg-css").value, content_js: $("#pg-js").value,
      liquid: $("#pg-liquid").value }) });
  drawPages();
};

// ---------- collections ----------
async function drawCollections() {
  const cols = (await (await fetch("/api/store/catalog")).json()).collections;
  $("#co-list").innerHTML = cols.map((c) =>
    `<div class="adm-item"><b>${c.name}</b>
     <span class="dim">${c.product_ids.length} products</span>
     <button class="btn-pill ghost mini" data-del="${c.slug}">delete</button>
    </div>`).join("") || '<p class="dim">No collections yet.</p>';
  $("#co-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/collections/${b.dataset.del}`,
      { method: "DELETE" }); drawCollections(); });
}

$("#co-save").onclick = async () => {
  const ids = [...document.querySelectorAll(".co-check:checked")]
    .map((c) => +c.value);
  await api("/api/store/admin/collections", { method: "POST",
    body: JSON.stringify({ slug: $("#co-slug").value,
      name: $("#co-name").value, product_ids: ids }) });
  drawCollections();
};

// ---------- discounts (percent · fixed · free shipping · BOGO) ----------
const DKIND = { percent: (d) => `−${d.pct}%`,
  fixed: (d) => `−${money(d.value_cents)}`,
  free_shipping: () => "free shipping",
  bogo: (d) => `buy ${d.bogo_buy} get ${d.bogo_get}` };

async function drawDiscounts() {
  const rows = await api("/api/store/admin/discounts2");
  $("#di-list").innerHTML = rows.map((d) => {
    const rules = [];
    if (d.min_subtotal_cents) rules.push(`min ${money(d.min_subtotal_cents)}`);
    if (d.usage_limit) rules.push(`${d.used_count}/${d.usage_limit} used`);
    else if (d.used_count) rules.push(`${d.used_count} used`);
    if (d.per_customer_limit) rules.push(`${d.per_customer_limit}/customer`);
    if (d.auto) rules.push("automatic");
    return `<div class="adm-item"><b>${d.code}</b>
      <span class="dim">${(DKIND[d.kind || "percent"] || DKIND.percent)(d)}
      ${rules.length ? " · " + rules.join(" · ") : ""}
      ${d.active ? "" : " · off"}</span></div>`;
  }).join("") || '<p class="dim">No codes yet.</p>';
  const sel = $("#di-bogo-product");
  if (sel && sel.options.length <= 1)
    sel.innerHTML = '<option value="">any product</option>' +
      PRODUCTS.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
}

$("#di-save").onclick = async () => {
  try {
    await api("/api/store/admin/discounts2", { method: "POST",
      body: JSON.stringify({ code: $("#di-code").value,
        kind: $("#di-kind").value, pct: +$("#di-pct").value,
        value_cents: +$("#di-value").value,
        min_subtotal_cents: +$("#di-min").value,
        usage_limit: +$("#di-limit").value,
        per_customer_limit: +$("#di-per").value,
        auto: $("#di-auto").value === "1",
        bogo_buy: +$("#di-buy").value, bogo_get: +$("#di-get").value,
        bogo_product_id: +$("#di-bogo-product").value || null }) });
    drawDiscounts();
  } catch (e) { alert(e.message); }
};

// ---------- gift cards ----------
async function drawGiftCards() {
  const rows = await api("/api/store/admin/gift-cards");
  $("#gc-list").innerHTML = rows.map((g) =>
    `<div class="adm-item"><b>${g.code}</b>
     <span class="dim">${money(g.balance_cents)} of ${money(g.initial_cents)}
     ${g.recipient_email ? " · " + g.recipient_email : ""}
     ${g.active ? "" : " · VOID"}</span>
     ${g.active ? `<button class="btn-pill ghost mini"
       data-void="${g.id}">void</button>` : ""}</div>`).join("") ||
    '<p class="dim">None issued.</p>';
  $("#gc-list").querySelectorAll("[data-void]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/gift-cards/${b.dataset.void}`,
      { method: "DELETE" }); drawGiftCards(); });
}

$("#gc-issue").onclick = async () => {
  const out = await api("/api/store/admin/gift-cards", { method: "POST",
    body: JSON.stringify({ amount_cents: +$("#gc-amount").value,
      recipient_email: $("#gc-email").value.trim(),
      note: $("#gc-note").value.trim() }) });
  $("#gc-new").innerHTML = `<p><b>Issued:</b>
    <code style="user-select:all">${out.code}</code> —
    ${money(out.balance_cents)}</p>`;
  drawGiftCards();
};

// ---------- affiliates ----------
async function drawAffiliates() {
  const rows = await api("/api/store/admin/affiliates");
  $("#af-list").innerHTML = rows.map((a) => `
    <div class="adm-item" style="flex-wrap:wrap;gap:8px">
      <b style="flex:0 0 140px">${a.name}</b>
      <span class="dim" style="flex:0 0 210px">
        <code>${a.link}</code> · ${a.rate_bps / 100}%</span>
      <span class="dim" style="flex:0 0 200px">${a.clicks} clicks ·
        ${a.landing_views} views · ${a.orders} orders ·
        <b>${money(a.earned)}</b></span>
      <label style="font-size:11.5px;font-weight:600;display:flex;gap:4px">
        <input type="checkbox" style="width:auto" data-afl="${a.id}"
          ${a.landing_enabled ? "checked" : ""}> landing page</label>
      <a class="btn-pill ghost mini" href="${a.landing}" target="_blank">open</a>
      <input data-afh="${a.id}" placeholder="headline"
        value="${(a.headline || "").replace(/"/g, "&quot;")}"
        style="flex:1;min-width:160px">
    </div>`).join("") ||
    '<p class="dim">No affiliates yet — share /affiliates to recruit.</p>';
  $("#af-list").querySelectorAll("[data-afl]").forEach((c) => c.onchange =
    async () => { await api(`/api/store/admin/affiliates/${c.dataset.afl}`,
      { method: "POST",
        body: JSON.stringify({ landing_enabled: c.checked }) }); });
  $("#af-list").querySelectorAll("[data-afh]").forEach((i) => i.onchange =
    async () => { await api(`/api/store/admin/affiliates/${i.dataset.afh}`,
      { method: "POST", body: JSON.stringify({ headline: i.value }) }); });
}

// ---------- blog ----------
async function drawPosts() {
  const rows = await api("/api/store/admin/posts");
  $("#bp-list").innerHTML = rows.map((p) =>
    `<div class="adm-item"><b>${p.title}</b>
     <a class="dim" href="${p.url}" target="_blank">${p.url} ↗</a>
     <button class="btn-pill ghost mini" data-pedit="${p.slug}">edit</button>
     <button class="btn-pill ghost mini" data-pdel="${p.slug}">delete</button>
    </div>`).join("") || '<p class="dim">No posts yet.</p>';
  $("#bp-list").querySelectorAll("[data-pdel]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/posts/${b.dataset.pdel}`,
      { method: "DELETE" }); drawPosts(); });
  $("#bp-list").querySelectorAll("[data-pedit]").forEach((b) => b.onclick =
    () => { const p = rows.find((x) => x.slug === b.dataset.pedit);
      $("#bp-title").value = p.title; $("#bp-slug").value = p.slug;
      $("#bp-author").value = p.author; $("#bp-excerpt").value = p.excerpt;
      $("#bp-body").value = p.body;
      if (p.media_id) $("#bp-media").value = p.media_id; });
  const sel = $("#bp-media");
  if (sel && !sel.options.length) {
    const cat = await (await fetch("/api/store/catalog")).json();
    sel.innerHTML = '<option value="">— none —</option>' +
      cat.products.flatMap((p) => (p.media || []).map((m) =>
        `<option value="${m.id}">${m.alt || p.name}</option>`)).join("");
  }
}

$("#bp-save").onclick = async () => {
  const out = await api("/api/store/admin/posts", { method: "POST",
    body: JSON.stringify({ slug: $("#bp-slug").value,
      title: $("#bp-title").value, excerpt: $("#bp-excerpt").value,
      body: $("#bp-body").value, author: $("#bp-author").value,
      media_id: +$("#bp-media").value || null }) });
  ["#bp-title", "#bp-slug", "#bp-excerpt", "#bp-body"].forEach((s) =>
    $(s).value = "");
  drawPosts();
};

// ---------- menus & redirects ----------
async function drawMenus() {
  const m = await api("/api/store/admin/menus");
  const all = [...(m.header || []), ...(m.footer || [])];
  $("#mn-list").innerHTML = all.map((x) =>
    `<div class="adm-item"><b>${x.label}</b>
     <span class="dim">${x.location} · ${x.url} · pos ${x.position}</span>
     <button class="btn-pill ghost mini" data-mdel2="${x.id}">delete</button>
    </div>`).join("") || '<p class="dim">No links.</p>';
  $("#mn-list").querySelectorAll("[data-mdel2]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/menus/${b.dataset.mdel2}`,
      { method: "DELETE" }); drawMenus(); });
}

$("#mn-add").onclick = async () => {
  await api("/api/store/admin/menus", { method: "POST",
    body: JSON.stringify({ location: $("#mn-loc").value,
      label: $("#mn-label").value, url: $("#mn-url").value,
      position: +$("#mn-pos").value }) });
  $("#mn-label").value = ""; $("#mn-url").value = "";
  drawMenus();
};

async function drawRedirects() {
  const rows = await api("/api/store/admin/redirects");
  $("#rd-list").innerHTML = rows.map((r) =>
    `<div class="adm-item"><b>${r.from_path}</b>
     <span class="dim">→ ${r.to_path} · ${r.code} · ${r.hits} hits</span>
     <button class="btn-pill ghost mini" data-rdel="${r.id}">delete</button>
    </div>`).join("") || '<p class="dim">No redirects.</p>';
  $("#rd-list").querySelectorAll("[data-rdel]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/redirects/${b.dataset.rdel}`,
      { method: "DELETE" }); drawRedirects(); });
}

$("#rd-add").onclick = async () => {
  try {
    await api("/api/store/admin/redirects", { method: "POST",
      body: JSON.stringify({ from_path: $("#rd-from").value,
        to_path: $("#rd-to").value, code: +$("#rd-code").value }) });
    $("#rd-from").value = ""; $("#rd-to").value = "";
    drawRedirects();
  } catch (e) { alert(e.message); }
};

// ---------- currencies & translations ----------
let CURRENCIES = [];
async function drawCurrencies() {
  const out = await (await fetch("/api/store/i18n")).json();
  CURRENCIES = out.currencies;
  renderCurrencyRows();
}

function renderCurrencyRows() {
  $("#cu-list").innerHTML = CURRENCIES.map((c, i) =>
    `<div class="adm-row" style="margin-bottom:6px">
      <div><input data-cu="${i}:code" value="${c.code}" placeholder="USD"></div>
      <div><input data-cu="${i}:symbol" value="${c.symbol}" placeholder="$"></div>
      <div><input data-cu="${i}:rate" type="number" step="0.0001"
        value="${c.rate}" ${i === 0 ? "readonly" : ""}></div>
      <div>${i === 0 ? '<span class="dim">base</span>' :
        `<button class="btn-pill ghost mini" data-curm="${i}">remove</button>`}</div>
    </div>`).join("");
  $("#cu-list").querySelectorAll("[data-cu]").forEach((el) => el.onchange =
    () => { const [i, k] = el.dataset.cu.split(":");
      CURRENCIES[+i][k] = k === "rate" ? +el.value : el.value; });
  $("#cu-list").querySelectorAll("[data-curm]").forEach((b) => b.onclick =
    () => { CURRENCIES.splice(+b.dataset.curm, 1); renderCurrencyRows(); });
}

$("#cu-add").onclick = () => {
  CURRENCIES.push({ code: "", symbol: "", rate: 1 }); renderCurrencyRows(); };
$("#cu-save").onclick = async () => {
  try {
    await api("/api/store/admin/currencies", { method: "POST",
      body: JSON.stringify({ currencies: CURRENCIES }) });
    alert("Currencies saved");
  } catch (e) { alert(e.message); }
};

let TR_BASE = {};
$("#tr-load").onclick = async () => {
  const loc = $("#tr-locale").value.trim().toLowerCase();
  if (!loc) return;
  const out = await api(`/api/store/admin/translations/${loc}`);
  TR_BASE = out.base;
  $("#tr-form").innerHTML = Object.entries(out.base).map(([k, v]) =>
    `<div style="margin:6px 0"><label style="font-size:11px;color:#8a82a0">
      ${k}</label>
     <div class="adm-row"><div class="dim" style="font-size:12.5px;
       padding-top:8px">${String(v).slice(0, 60)}</div>
     <div><input data-tr="${k}" value="${(out.values[k] || "")
       .replace(/"/g, "&quot;")}" placeholder="translation"></div></div></div>`)
    .join("");
  $("#tr-save").classList.remove("hidden");
  $("#tr-msg").textContent =
    `${Object.keys(out.values).length} strings translated for "${loc}"`;
};

$("#tr-save").onclick = async () => {
  const entries = {};
  document.querySelectorAll("[data-tr]").forEach((el) =>
    entries[el.dataset.tr] = el.value);
  const out = await api("/api/store/admin/translations", { method: "POST",
    body: JSON.stringify({ locale: $("#tr-locale").value.trim().toLowerCase(),
      entries }) });
  $("#tr-msg").textContent = `saved — ${out.count} strings for ${out.locale}`;
};

// ---------- staff & audit ----------
async function drawStaff() {
  const out = await api("/api/store/admin/staff");
  $("#st-list").innerHTML = out.staff.map((s) =>
    `<div class="adm-item" style="flex-wrap:wrap">
      <b style="flex:0 0 150px">${s.name}</b>
      <span class="dim" style="flex:0 0 110px">${s.role}
        ${s.is_admin ? "· admin" : ""}</span>
      <span style="flex:1;display:flex;gap:8px;flex-wrap:wrap">
      ${Object.keys(out.permissions).map((p) =>
        `<label style="font-size:11.5px;font-weight:600;display:flex;gap:3px">
          <input type="checkbox" style="width:auto" data-perm="${s.id}:${p}"
            ${s.effective.includes(p) || s.effective.includes("*")
              ? "checked" : ""}> ${p}</label>`).join("")}
      </span>
      <button class="btn-pill ghost mini" data-psave="${s.id}">save</button>
    </div>`).join("");
  $("#st-list").querySelectorAll("[data-psave]").forEach((b) => b.onclick =
    async () => {
      const uid = b.dataset.psave;
      const perms = [...document.querySelectorAll(
        `[data-perm^="${uid}:"]:checked`)].map((c) =>
        c.dataset.perm.split(":")[1]);
      try {
        await api(`/api/store/admin/staff/${uid}/permissions`,
          { method: "POST", body: JSON.stringify({ permissions: perms }) });
        drawStaff(); drawAudit();
      } catch (e) { alert(e.message); }
    });
}

async function drawAudit() {
  const rows = await api("/api/store/admin/audit?limit=100");
  $("#au-table").innerHTML =
    "<tr><th>when</th><th>who</th><th>action</th><th>detail</th></tr>" +
    (rows.map((r) => `<tr>
      <td class="dim">${new Date(r.created_at * 1000).toLocaleString()}</td>
      <td>${r.actor}</td><td><code>${r.action}</code></td>
      <td class="dim">${r.detail || r.entity || ""}</td></tr>`).join("") ||
     "<tr><td colspan=4 class=dim>nothing logged yet</td></tr>");
}

// ---------- analytics ----------

// ---------- orders ----------
const STEPS = ["pending", "confirmed", "shipped", "delivered"];
async function drawOrders() {
  const rows = await api("/api/orders?all=1");
  $("#or-list").innerHTML = rows.slice(0, 30).map((o) => {
    const next = STEPS[STEPS.indexOf(o.status) + 1];
    return `<div class="adm-item"><b>#${o.id}</b>
     <span class="dim">${o.status} · ${o.payment_status} ·
     ${money(o.total_cents)}${o.discount_code ? " · " + o.discount_code : ""}
     · ${o.ship_name || ""}</span>
     ${next && o.status !== "cancelled" ? `<button class="btn-pill ghost mini"
       data-adv="${o.id}" data-next="${next}">→ ${next}</button>` : ""}
     ${o.payment_status !== "refunded" ? `<button class="btn-pill ghost mini"
       data-refund="${o.id}">refund</button>` : ""}
    </div>`; }).join("") || '<p class="dim">No orders yet.</p>';
  $("#or-list").querySelectorAll("[data-adv]").forEach((b) => b.onclick =
    async () => { await api(`/api/admin/orders/${b.dataset.adv}/status`,
      { method: "POST", body: JSON.stringify({ status: b.dataset.next }) });
      drawOrders(); });
  $("#or-list").querySelectorAll("[data-refund]").forEach((b) => b.onclick =
    async () => {
      if (!confirm(`Refund order #${b.dataset.refund} in full?` +
        ` (restocks variants)`)) return;
      try { await api(`/api/admin/orders/${b.dataset.refund}/refund`,
        { method: "POST", body: JSON.stringify({ restock: true }) }); }
      catch (e) { alert(e.message); }
      drawOrders(); });
}

// ---------- review moderation ----------
async function drawReviewQueue() {
  const rows = await api("/api/store/admin/reviews");
  $("#rv-queue").innerHTML = rows.map((r) =>
    `<div class="adm-item">
     <b>${"★".repeat(r.rating)}${r.verified ? " ✓" : ""}</b>
     <span class="dim">${r.product_name} · ${r.name}:
     "${(r.body || "").slice(0, 90)}"</span>
     <button class="btn-pill ghost mini" data-ok="${r.id}">approve</button>
     <button class="btn-pill ghost mini" data-del="${r.id}">delete</button>
    </div>`).join("") || '<p class="dim">Queue is clear ✨</p>';
  $("#rv-queue").querySelectorAll("[data-ok]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/reviews/${b.dataset.ok}/approve`,
      { method: "POST" }); drawReviewQueue(); });
  $("#rv-queue").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/reviews/${b.dataset.del}`,
      { method: "DELETE" }); drawReviewQueue(); });
}

// ---------- webhooks ----------
async function drawWebhooks() {
  const out = await api("/api/store/admin/webhooks");
  $("#wh-secret").textContent = out.secret;
  const rows = out.hooks;
  $("#wh-list").innerHTML = rows.map((w) =>
    `<div class="adm-item"><b>${w.event}</b>
     <span class="dim">${w.url}</span>
     <button class="btn-pill ghost mini" data-test="${w.id}">test</button>
     <button class="btn-pill ghost mini" data-del="${w.id}">delete</button>
    </div>`).join("") || '<p class="dim">No webhooks yet.</p>';
  $("#wh-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/webhooks/${b.dataset.del}`,
      { method: "DELETE" }); drawWebhooks(); });
  $("#wh-list").querySelectorAll("[data-test]").forEach((b) => b.onclick =
    async () => { await api(`/api/store/admin/webhooks/${b.dataset.test}/test`,
      { method: "POST" }); b.textContent = "fired ✔"; });
}

$("#wh-add").onclick = async () => {
  await api("/api/store/admin/webhooks", { method: "POST",
    body: JSON.stringify({ event: $("#wh-event").value,
      url: $("#wh-url").value }) });
  drawWebhooks();
};

// ---------- API keys ----------
async function drawKeys() {
  const out = await api("/api/store/admin/keys");
  $("#ak-scopes").innerHTML = Object.entries(out.scopes).map(([k, v]) =>
    `<label style="display:flex;gap:8px;align-items:flex-start;font-weight:500;
      font-size:13px;margin:4px 0">
     <input type="checkbox" style="width:auto" value="${k}" class="ak-scope">
     <span><code>${k}</code> — <span class="dim">${v}</span></span></label>`)
    .join("");
  $("#ak-list").innerHTML = out.keys.map((k) =>
    `<div class="adm-item"><b>${k.name}</b>
     <span class="dim"><code>${k.prefix}</code> · ${k.scopes} ·
     ${k.calls} calls${k.active ? "" : " · REVOKED"}</span>
     ${k.active ? `<button class="btn-pill ghost mini"
       data-revoke="${k.id}">revoke</button>` : ""}
    </div>`).join("") || '<p class="dim">No keys yet.</p>';
  $("#ak-list").querySelectorAll("[data-revoke]").forEach((b) => b.onclick =
    async () => { if (!confirm("Revoke this key? Apps using it stop working."))
      return;
      await api(`/api/store/admin/keys/${b.dataset.revoke}`,
        { method: "DELETE" }); drawKeys(); });
}

$("#ak-create").onclick = async () => {
  const scopes = [...document.querySelectorAll(".ak-scope:checked")]
    .map((c) => c.value);
  try {
    const out = await api("/api/store/admin/keys", { method: "POST",
      body: JSON.stringify({ name: $("#ak-name").value.trim(), scopes }) });
    $("#ak-new").innerHTML =
      `<div class="adm-panel" style="border-color:var(--purple);margin:12px 0">
        <b>Copy this key now — it cannot be shown again</b>
        <p style="user-select:all;word-break:break-all;background:#f2eefa;
          border-radius:10px;padding:10px;margin-top:6px">
          <code>${out.key}</code></p></div>`;
    $("#ak-name").value = "";
    document.querySelectorAll(".ak-scope").forEach((c) => c.checked = false);
    drawKeys();
  } catch (e) { alert(e.message); }
};

// ---------- analytics ----------
async function drawAnalytics() {
  const a = await api("/api/store/admin/page-analytics");
  $("#an-subs").textContent =
    `${a.subscribers} rewards subscribers captured on the storefront`;
  $("#an-pages").innerHTML =
    "<tr><th>page</th><th>hits</th><th>visitors</th></tr>" +
    (a.pages.map((p) => `<tr><td>${p.page}</td><td>${p.hits}</td>
      <td>${p.visitors}</td></tr>`).join("") ||
     "<tr><td colspan=3 class=dim>no pageviews yet</td></tr>");
  $("#an-funnel").innerHTML =
    "<tr><th>step</th><th>hits</th><th>visitors</th></tr>" +
    (a.funnel.map((f) => `<tr><td>${f.step}</td><td>${f.hits}</td>
      <td>${f.visitors}</td></tr>`).join("") ||
     "<tr><td colspan=3 class=dim>no events yet</td></tr>");
}

// ---------- boot ----------
async function boot() {
  $("#login-card").classList.add("hidden");
  $("#adm-app").classList.remove("hidden");
  applyPermissions();
  const can = (p) => !ME || ME.permissions.includes("*") ||
    ME.permissions.includes(p);
  // Load only what this person may see; a refusal must never break the page.
  const run = (perm, fn) => { if (can(perm)) Promise.resolve()
    .then(fn).catch(() => {}); };
  if (can("products")) await drawProducts().catch(() => {});
  run("products", drawCollections); run("products", drawVariants);
  run("products", drawMedia);
  run("customers", drawAffiliates);
  run("content", drawPages); run("content", drawReviewQueue);
  run("content", drawPosts); run("content", drawMenus);
  run("content", drawRedirects);
  run("discounts", drawDiscounts); run("discounts", drawGiftCards);
  run("orders", drawOrders);
  run("settings", drawWebhooks); run("settings", drawKeys);
  run("settings", drawCurrencies); run("settings", drawStaff);
  run("settings", drawAudit); run("settings", drawShipping);
}
tryBoot().then((ok) => { if (ok) boot(); });
