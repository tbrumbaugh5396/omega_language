/* Icons come from the shared sprite the storefront uses, so the page
   builder and the store it edits look like one product. */
const icon = (n) =>
  `<svg class="ico-s" aria-hidden="true"><use href="#i-${n}"/></svg>`;

/* Theme & page editor — section list, schema-driven settings form, and a
   live preview iframe. Section types come from the server, so new types
   appear here with no changes to this file. */
"use strict";
const $ = (s) => document.querySelector(s);
let TOKEN = "";
try { TOKEN = JSON.parse(localStorage.getItem("bc_user") || "{}").token || ""; }
catch {}

const H = () => ({ "Content-Type": "application/json",
  Authorization: "Bearer " + TOKEN });
const api = async (url, opts = {}) => {
  const r = await fetch(url, { headers: H(), ...opts });
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).detail) || r.status);
  return r.json();
};

let SCHEMA = {}, SECTIONS = [], SEL = null, SLUG = "home", PAGES = [], THEME = {};

// ---------- auth ----------
$("#li-go").onclick = async () => {
  try {
    const out = await (await fetch("/api/login", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#li-name").value.trim(),
        password: $("#li-pass").value, admin_key: $("#li-key").value.trim() })
    })).json();
    if (!out.token) throw new Error(out.detail || "sign-in failed");
    if (!out.is_admin) throw new Error("that account isn't an admin");
    TOKEN = out.token;
    localStorage.setItem("bc_user", JSON.stringify(out));
    boot();
  } catch (e) { $("#li-msg").textContent = String(e.message || e); }
};

// ---------- preview ----------
let saveTimer;
function refresh(soon = 350) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const f = $("#preview");
    f.src = (SLUG === "home" ? "/" : `/p/${SLUG}`) + "?t=" + Date.now();
    $("#saved").classList.remove("hidden");
    setTimeout(() => $("#saved").classList.add("hidden"), 1400);
  }, soon);
}
$("#vp-desktop").onclick = () => { $("#frame-wrap").classList.remove("mobile");
  $("#vp-desktop").classList.add("on"); $("#vp-mobile").classList.remove("on"); };
$("#vp-mobile").onclick = () => { $("#frame-wrap").classList.add("mobile");
  $("#vp-mobile").classList.add("on"); $("#vp-desktop").classList.remove("on"); };
$("#vp-reload").onclick = () => refresh(0);

// ---------- pages ----------
async function loadPages() {
  PAGES = await api("/api/store/admin/pages");
  $("#page-select").innerHTML =
    `<option value="home">Home page</option>` +
    PAGES.map((p) => `<option value="${p.slug}">${p.title}</option>`).join("");
  $("#page-select").value = SLUG;
  $("#page-url").textContent = SLUG === "home" ? "/" : `/p/${SLUG}`;
}

$("#page-select").onchange = async () => {
  SLUG = $("#page-select").value; SEL = null;
  $("#page-url").textContent = SLUG === "home" ? "/" : `/p/${SLUG}`;
  await loadSections(); refresh(0);
};

$("#new-page").onclick = async () => {
  const title = prompt("Page title (e.g. Our Story)");
  if (!title) return;
  const slug = prompt("URL slug", title.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  if (!slug) return;
  await api("/api/store/admin/pages", { method: "POST",
    body: JSON.stringify({ slug, title, content_html: "" }) });
  SLUG = slug.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  await loadPages(); $("#page-select").value = SLUG;
  // A fresh page starts with something visible to edit.
  await api("/api/store/admin/sections", { method: "POST",
    body: JSON.stringify({ page_slug: SLUG, type: "rich_text" }) });
  await loadSections(); refresh(0);
};

// ---------- sections ----------
async function loadSections() {
  SECTIONS = await api(`/api/store/admin/sections/${SLUG}`);
  drawSections();
  drawForm();
}

function drawSections() {
  $("#sec-list").innerHTML = SECTIONS.map((s, i) => `
    <div class="sec ${SEL === s.id ? "on" : ""} ${s.enabled ? "" : "off"}"
         data-sec="${s.id}">
      <div class="sec-head">
        <span class="ico">${icon(s.icon)}</span>
        <span>${s.label}</span><span class="sp"></span>
        <span class="sec-acts">
          <button data-mv="${s.id}:up" title="move up" ${i === 0 ? "disabled" : ""}>▲</button>
          <button data-mv="${s.id}:down" title="move down" ${i === SECTIONS.length - 1 ? "disabled" : ""}>▼</button>
          <button data-tog="${s.id}" title="${s.enabled ? "hide" : "show"}">${icon(s.enabled ? "eye" : "eye-off")}</button>
          <button data-del="${s.id}" title="delete">${icon("trash")}</button>
        </span>
      </div>
    </div>`).join("") ||
    '<p style="font-size:13px;color:#8a82a0">No sections yet — add one below.</p>';

  $("#sec-list").querySelectorAll("[data-sec]").forEach((el) =>
    el.onclick = (e) => {
      if (e.target.closest(".sec-acts")) return;
      SEL = +el.dataset.sec; drawSections(); drawForm();
    });
  $("#sec-list").querySelectorAll("[data-mv]").forEach((b) => b.onclick =
    async () => { const [id, move] = b.dataset.mv.split(":");
      await api(`/api/store/admin/sections/${id}`, { method: "POST",
        body: JSON.stringify({ move }) });
      await loadSections(); refresh(); });
  $("#sec-list").querySelectorAll("[data-tog]").forEach((b) => b.onclick =
    async () => { const s = SECTIONS.find((x) => x.id === +b.dataset.tog);
      await api(`/api/store/admin/sections/${s.id}`, { method: "POST",
        body: JSON.stringify({ enabled: !s.enabled }) });
      await loadSections(); refresh(); });
  $("#sec-list").querySelectorAll("[data-del]").forEach((b) => b.onclick =
    async () => { if (!confirm("Delete this section?")) return;
      await api(`/api/store/admin/sections/${b.dataset.del}`,
        { method: "DELETE" });
      if (SEL === +b.dataset.del) SEL = null;
      await loadSections(); refresh(); });
}

$("#add-go").onclick = async () => {
  const out = await api("/api/store/admin/sections", { method: "POST",
    body: JSON.stringify({ page_slug: SLUG, type: $("#add-type").value }) });
  SEL = out.id;
  await loadSections(); refresh();
};

// ---------- schema-driven settings form ----------
function field(f, val, path) {
  const id = `f_${path}`;
  const v = val ?? f.default ?? "";
  switch (f.t) {
    case "textarea": case "richtext":
      return `<label>${f.label}</label>
        <textarea id="${id}" data-k="${path}">${String(v)
          .replace(/</g, "&lt;")}</textarea>`;
    case "number":
      return `<label>${f.label}</label>
        <input type="number" id="${id}" data-k="${path}" value="${v}">`;
    case "checkbox":
      return `<div class="chk"><input type="checkbox" id="${id}"
        data-k="${path}" ${v ? "checked" : ""}><label
        style="margin:0">${f.label}</label></div>`;
    case "select":
      return `<label>${f.label}</label><select id="${id}" data-k="${path}">
        ${f.options.map((o) =>
          `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    case "color":
      return `<label>${f.label}</label><div class="swatch">
        <input type="color" id="${id}" data-k="${path}" value="${v}">
        <input type="text" data-mirror="${id}" value="${v}"></div>`;
    case "media":
      return `<label>${f.label}</label>
        <select id="${id}" data-k="${path}">
          <option value="">— none —</option>
          ${MEDIA.map((m) => `<option value="${m.id}"
            ${String(m.id) === String(v) ? "selected" : ""}>
            ${icon(m.kind === "video" ? "video" : "image")} ${m.alt || "media #" + m.id}
            </option>`).join("")}
        </select>`;
    case "collection":
      return `<label>${f.label}</label>
        <select id="${id}" data-k="${path}">
          <option value="">All products</option>
          ${COLLECTIONS.map((c) => `<option value="${c.id}"
            ${String(c.id) === String(v) ? "selected" : ""}>${c.name}</option>`)
            .join("")}
        </select>`;
    default:
      return `<label>${f.label}</label>
        <input type="text" id="${id}" data-k="${path}"
          value="${String(v).replace(/"/g, "&quot;")}">`;
  }
}

function drawForm() {
  const host = $("#sec-form");
  const s = SECTIONS.find((x) => x.id === SEL);
  if (!s) { host.innerHTML =
    '<p style="font-size:13px;color:#8a82a0">Pick a section above to edit it.</p>';
    return; }
  const spec = SCHEMA[s.type];
  let html = `<p style="font-size:12px;color:#8a82a0">${spec.help || ""}</p>`;
  for (const f of spec.fields) {
    if (f.t === "list") {
      const items = s.settings[f.k] || [];
      html += `<label>${f.label}</label><div id="list_${f.k}">` +
        items.map((it, i) => `<div class="list-item">
          <span class="del" data-lrm="${f.k}:${i}">${icon("trash")}</span>` +
          f.item_fields.map((sf) =>
            field(sf, it[sf.k], `${f.k}.${i}.${sf.k}`)).join("") +
          `</div>`).join("") +
        `</div><button class="btn ghost sm" data-ladd="${f.k}"
          style="margin-top:6px">＋ add</button>`;
    } else {
      html += field(f, s.settings[f.k], f.k);
    }
  }
  host.innerHTML = html;

  host.querySelectorAll("[data-k]").forEach((el) => {
    const ev = el.type === "checkbox" || el.tagName === "SELECT"
      ? "change" : "input";
    el.addEventListener(ev, () => saveSection(el.dataset.k, el));
  });
  host.querySelectorAll("[data-mirror]").forEach((el) =>
    el.oninput = () => { const t = document.getElementById(el.dataset.mirror);
      t.value = el.value; t.dispatchEvent(new Event("change")); });
  host.querySelectorAll("[data-ladd]").forEach((b) => b.onclick = () => {
    const f = spec.fields.find((x) => x.k === b.dataset.ladd);
    const items = s.settings[f.k] = (s.settings[f.k] || []).slice();
    items.push(Object.fromEntries(f.item_fields.map((sf) =>
      [sf.k, sf.default ?? ""])));
    pushSettings(s); drawForm();
  });
  host.querySelectorAll("[data-lrm]").forEach((b) => b.onclick = () => {
    const [k, i] = b.dataset.lrm.split(":");
    s.settings[k] = (s.settings[k] || []).filter((_, j) => j !== +i);
    pushSettings(s); drawForm();
  });
}

function setPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = /^\d+$/.test(parts[i]) ? +parts[i] : parts[i];
    cur[key] = cur[key] ?? (/^\d+$/.test(parts[i + 1]) ? [] : {});
    cur = cur[key];
  }
  const last = parts[parts.length - 1];
  cur[/^\d+$/.test(last) ? +last : last] = value;
}

let settingsTimer;
function saveSection(path, el) {
  const s = SECTIONS.find((x) => x.id === SEL);
  const value = el.type === "checkbox" ? el.checked
    : el.type === "number" ? +el.value : el.value;
  setPath(s.settings, path, value);
  clearTimeout(settingsTimer);
  settingsTimer = setTimeout(() => pushSettings(s), 260);
}

async function pushSettings(s) {
  await api(`/api/store/admin/sections/${s.id}`, { method: "POST",
    body: JSON.stringify({ settings: s.settings }) });
  refresh();
}

// ---------- theme ----------
const THEME_FIELDS = [
  { k: "brand", t: "text", label: "Brand name" },
  { k: "title", t: "text", label: "Browser title (SEO)" },
  { k: "description", t: "textarea", label: "Meta description (SEO)" },
  { k: "purple", t: "color", label: "Primary colour" },
  { k: "lavender", t: "color", label: "Secondary colour" },
  { k: "orange", t: "color", label: "Accent colour" },
  { k: "ink", t: "color", label: "Text colour" },
  { k: "bg", t: "color", label: "Background" },
  { k: "font", t: "select", label: "Interface font (buttons, prices, nav)",
    options: ["Inter", "Quicksand", "Fraunces"] },
  { k: "display_font", t: "select", label: "Display font (headlines only)",
    options: ["Fraunces", "Inter", "Quicksand"] },
  { k: "footer", t: "text", label: "Footer note" },
];

function drawTheme() {
  $("#theme-form").innerHTML = THEME_FIELDS.map((f) =>
    field(f, THEME[f.k], "T_" + f.k)).join("") +
    `<label>Announcement bar (one per line)</label>
     <textarea data-announce>${(THEME.announce || []).join("\n")}</textarea>`;
  $("#theme-form").querySelectorAll("[data-k]").forEach((el) => {
    const ev = el.type === "checkbox" || el.tagName === "SELECT"
      ? "change" : "input";
    el.addEventListener(ev, () => {
      THEME[el.dataset.k.slice(2)] = el.value; pushTheme();
    });
  });
  $("#theme-form").querySelectorAll("[data-mirror]").forEach((el) =>
    el.oninput = () => { const t = document.getElementById(el.dataset.mirror);
      t.value = el.value; t.dispatchEvent(new Event("change")); });
  $("#theme-form").querySelector("[data-announce]").oninput = (e) => {
    THEME.announce = e.target.value.split("\n").filter((x) => x.trim());
    pushTheme();
  };
}

let themeTimer;
function pushTheme() {
  clearTimeout(themeTimer);
  themeTimer = setTimeout(async () => {
    await api("/api/store/admin/theme", { method: "POST",
      body: JSON.stringify(THEME) });
    refresh();
  }, 300);
}

// ---------- boot ----------
let MEDIA = [], COLLECTIONS = [];
async function boot() {
  $("#login").classList.add("hidden");
  $("#topbar").classList.remove("hidden");
  $("#app").classList.remove("hidden");
  SCHEMA = await api("/api/store/admin/section-schema");
  $("#add-type").innerHTML = Object.entries(SCHEMA).map(([k, v]) =>
    `<option value="${k}">${v.label}</option>`).join("");
  const cat = await (await fetch("/api/store/catalog")).json();
  COLLECTIONS = cat.collections;
  MEDIA = cat.products.flatMap((p) =>
    (p.media || []).map((m) => ({ ...m, alt: m.alt || p.name })));
  THEME = await api("/api/store/admin/theme");
  drawTheme();
  await loadPages();
  await loadSections();
}

(async () => {
  if (!TOKEN) return;
  try { await api("/api/store/admin/theme"); boot(); } catch {}
})();
