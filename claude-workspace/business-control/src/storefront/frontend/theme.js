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
    savedTick();
  }, soon);
}
function savedTick() {
  $("#saved").classList.remove("hidden");
  setTimeout(() => $("#saved").classList.add("hidden"), 1400);
}
$("#preview").onload = () => wirePreview();
$("#vp-desktop").onclick = () => { $("#frame-wrap").classList.remove("mobile");
  $("#vp-desktop").classList.add("on"); $("#vp-mobile").classList.remove("on"); };
$("#vp-mobile").onclick = () => { $("#frame-wrap").classList.add("mobile");
  $("#vp-mobile").classList.add("on"); $("#vp-desktop").classList.remove("on"); };
$("#vp-reload").onclick = () => refresh(0);

// ---------- the live loop: the preview is the editor ----------
/* The iframe is same-origin, so the editor works on its DOM directly:
   click a section on the page to select it, type into the marked text
   fields, and saves swap just that section's element. The page never
   reloads under the merchant's cursor — a reload is for structure
   (add / move / delete), not for words. */

const EDIT_CSS = `
  [data-sid] { position: relative; }
  [data-sid]:hover { outline: 2px dashed rgba(108,0,191,.45);
    outline-offset: -2px; cursor: pointer; }
  [data-sid].sfe-sel { outline: 2px solid #6c00bf; outline-offset: -2px;
    cursor: auto; }
  [data-sid].sfe-sel::after, [data-sid]:hover::after {
    content: attr(data-slabel); position: absolute; top: 0; left: 0;
    background: #6c00bf; color: #fff; font: 600 11px/1 Inter, sans-serif;
    padding: 4px 8px; border-bottom-right-radius: 8px; z-index: 60;
    pointer-events: none; }
  .sfe-sel [data-sf] { cursor: text; }
  .sfe-sel [data-sf]:hover { background: rgba(108,0,191,.07);
    border-radius: 4px; }
  .sfe-sel [data-sf]:focus { outline: 1.5px solid rgba(108,0,191,.5);
    outline-offset: 2px; border-radius: 4px; background: #fff3; }
  .sfe-add { position: relative; height: 0; overflow: visible; z-index: 55;
    text-align: center; }
  .sfe-add-pill { position: relative; top: -13px; border: 1.5px solid
    rgba(108,0,191,.35); background: #fff; color: #6c00bf; cursor: pointer;
    font: 600 12px/1 Inter, sans-serif; padding: 6px 12px;
    border-radius: 999px; opacity: 0; transition: opacity .12s; }
  .sfe-add:hover .sfe-add-pill, .sfe-add.sfe-drop .sfe-add-pill {
    opacity: 1; }
  .sfe-add.sfe-drop { outline: 2px solid #6c00bf; outline-offset: -1px; }
  .sfe-add.sfe-drop .sfe-add-pill { background: #6c00bf; color: #fff; }
  .sfe-dragging-page .sfe-add-pill { opacity: .55; }
  .sfe-dragging { opacity: .45; }
  .sfe-handle { position: absolute; top: 6px; right: 8px; z-index: 60;
    cursor: grab; color: #6c00bf; background: #fff; border: 1.5px solid
    rgba(108,0,191,.35); border-radius: 8px; padding: 3px 7px;
    font: 700 13px/1 Inter, sans-serif; letter-spacing: -1px; opacity: 0;
    transition: opacity .12s; user-select: none; }
  [data-sid]:hover .sfe-handle, [data-sid].sfe-sel .sfe-handle {
    opacity: 1; }
  .sfe-handle:active { cursor: grabbing; }
  .sfe-imgbtn { position: absolute; top: 6px; right: 44px; z-index: 60;
    cursor: pointer; background: #fff; border: 1.5px solid
    rgba(108,0,191,.35); border-radius: 8px; padding: 2px 7px;
    font-size: 13px; line-height: 1.4; opacity: 0; transition: opacity .12s;
    user-select: none; }
  [data-sid]:hover .sfe-imgbtn, [data-sid].sfe-sel .sfe-imgbtn {
    opacity: 1; }
  [data-sid].sfe-filedrop { outline: 3px solid #6c00bf;
    outline-offset: -3px; }
  [data-sid].sfe-filedrop::after { content: "Drop to set this image";
    position: absolute; top: 0; left: 0; background: #6c00bf; color: #fff;
    font: 600 11px/1 Inter, sans-serif; padding: 4px 8px;
    border-bottom-right-radius: 8px; z-index: 60; pointer-events: none; }
  .sfe-pick { position: absolute; left: 50%; transform: translateX(-50%);
    top: 14px; z-index: 70; background: #fff; border: 1.5px solid
    rgba(108,0,191,.3); border-radius: 12px; padding: 8px;
    box-shadow: 0 12px 34px rgba(27,24,31,.18); display: grid;
    grid-template-columns: repeat(3, minmax(120px, 1fr)); gap: 4px;
    width: max-content; max-width: 460px; }
  .sfe-pick button { border: none; background: none; cursor: pointer;
    font: 500 12.5px/1.2 Inter, sans-serif; color: #1b181f; padding: 8px;
    border-radius: 8px; text-align: left; }
  .sfe-pick button:hover { background: rgba(108,0,191,.09);
    color: #6c00bf; }
  .sfe-pick .sfe-pick-x { grid-column: 1 / -1; text-align: center;
    color: #8a82a0; border-top: 1px solid #eee; border-radius: 0; }`;

const pdoc = () => $("#preview").contentDocument;

function wirePreview() {
  const doc = pdoc();
  if (!doc || doc.getElementById("sfe-css")) return;
  const st = doc.createElement("style");
  st.id = "sfe-css";
  st.textContent = EDIT_CSS;
  doc.head.appendChild(st);
  // One capture-phase listener owns every click: links must not navigate
  // the page being edited out from under the editor, and any click lands
  // on the section it happened in.
  doc.addEventListener("click", (e) => {
    // the editor's own chrome is the one thing the interceptor lets live
    if (e.target.closest(".sfe-add, .sfe-pick, .sfe-handle")) return;
    const sec = e.target.closest("[data-sid]");
    if (e.target.closest("a") || e.target.closest("button")) {
      // Inert, not interactive: a link would navigate the page being
      // edited out from under the editor, and a live Add-to-cart in a
      // preview quietly builds a real cart.
      e.preventDefault();
      e.stopPropagation();
    }
    if (!sec) return;
    if (+sec.dataset.sid !== SEL) {
      e.preventDefault();
      SEL = +sec.dataset.sid;
      drawSections(); drawForm();
      highlightPreview(SEL, false);
    }
  }, true);
  // An image file dropped on a section that takes one uploads it there.
  // Section drags (DRAG_SID set) keep their own path on the bars.
  doc.addEventListener("dragover", (e) => {
    if (DRAG_SID != null) return;
    if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
    const sec = e.target.closest("[data-sid]");
    doc.querySelectorAll(".sfe-filedrop").forEach((x) =>
      x.classList.remove("sfe-filedrop"));
    if (sec && mediaKeyOf(SECTIONS.find((x) => x.id === +sec.dataset.sid))) {
      e.preventDefault();
      sec.classList.add("sfe-filedrop");
    }
  }, true);
  doc.addEventListener("drop", (e) => {
    if (DRAG_SID != null) return;
    const sec = e.target.closest("[data-sid]");
    doc.querySelectorAll(".sfe-filedrop").forEach((x) =>
      x.classList.remove("sfe-filedrop"));
    if (!sec) return;
    const sRow = SECTIONS.find((x) => x.id === +sec.dataset.sid);
    const mk = mediaKeyOf(sRow);
    const f = e.dataTransfer?.files?.[0];
    if (!mk || !f) return;
    e.preventDefault();
    SEL = sRow.id; drawSections(); drawForm();
    highlightPreview(SEL, false);
    uploadImage(f, { sid: sRow.id, key: mk });
  }, true);
  injectBars(doc);
  highlightPreview(SEL, false);
}

function highlightPreview(sid, scroll = true) {
  const doc = pdoc();
  if (!doc) return;
  doc.querySelectorAll("[data-sid].sfe-sel").forEach((el) => {
    el.classList.remove("sfe-sel");
    el.querySelectorAll("[data-sf]").forEach((t) =>
      t.removeAttribute("contenteditable"));
  });
  const el = doc.querySelector(`[data-sid="${sid}"]`);
  if (!el) return;
  el.classList.add("sfe-sel");
  if (scroll) el.scrollIntoView({ behavior: "smooth", block: "center" });
  armInline(el);
}

/* Typing into the page IS editing the field. data-sf names the settings
   key the element renders; plaintext-only keeps paste from smuggling
   markup into a field the server would escape anyway. */
function armInline(secEl) {
  const s = SECTIONS.find((x) => x.id === SEL);
  if (!s) return;
  secEl.querySelectorAll("[data-sf]").forEach((el) => {
    try { el.contentEditable = "plaintext-only"; }
    catch { el.contentEditable = "true"; }
    el.oninput = () => {
      // <br> is how the renderer writes \n; innerText hands it back.
      const v = el.innerText.replace(/\n+$/, "");
      setPath(s.settings, el.dataset.sf, v);
      mirrorToPanel(el.dataset.sf, v);
      clearTimeout(settingsTimer);
      settingsTimer = setTimeout(() => pushSettings(s, { swap: false }), 400);
    };
  });
}

function mirrorToPanel(path, v) {
  const f = document.querySelector(`#sec-form [data-k="${CSS.escape(path)}"]`);
  if (f && f.type !== "checkbox") f.value = v;
}

/* Swap one section's element for its fresh server render — the save path
   for panel edits. Inline edits skip the swap: the DOM already shows the
   typed text, and replacing the node would eat the caret mid-word. */
async function swapSection(sid) {
  const doc = pdoc();
  const el = doc && doc.querySelector(`[data-sid="${sid}"]`);
  if (!el) { refresh(0); return; }
  const out = await api(`/api/store/admin/sections/${sid}/html`);
  const tpl = doc.createElement("template");
  tpl.innerHTML = out.html;
  const fresh = tpl.content.firstElementChild;
  if (!fresh) { refresh(0); return; }
  el.replaceWith(fresh);
  decorate(doc, fresh);
  if (SEL === sid) {
    fresh.classList.add("sfe-sel");
    armInline(fresh);
  }
}



// ---------- images, without leaving the page ----------
/* A section whose schema has a media field gets an image button beside its
   drag handle, and accepts an image file dropped straight onto it. Either
   way the file uploads as SITE media (product_id 0 — it belongs to the
   storefront, not a product), the section's media field is set, and the
   section re-renders in place. */

const FILE_IN = document.createElement("input");
FILE_IN.type = "file";
FILE_IN.accept = "image/*";
FILE_IN.hidden = true;
document.body.appendChild(FILE_IN);
let UPLOAD_FOR = null;                     // {sid, key} while the picker is up
FILE_IN.onchange = () => {
  const f = FILE_IN.files[0];
  if (f && UPLOAD_FOR) uploadImage(f, UPLOAD_FOR);
  FILE_IN.value = "";
};

const mediaKeyOf = (s) => s &&
  (SCHEMA[s.type].fields.find((f) => f.t === "media") || {}).k;

async function uploadImage(file, { sid, key }) {
  if (!/^image\//.test(file.type)) return;
  if (file.size > 8_000_000) {
    alert("That image is over the 8 MB cap — resize it and try again.");
    return;
  }
  const data_url = await new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.readAsDataURL(file);
  });
  const out = await api("/api/store/admin/media", { method: "POST",
    body: JSON.stringify({ product_id: 0, data_url,
      alt: file.name.replace(/\.[a-z0-9]+$/i, "") }) });
  const s = SECTIONS.find((x) => x.id === sid);
  if (!s) return;
  setPath(s.settings, key, out.id);
  // A hero shows its image only in "image" background mode — uploading one
  // and leaving the gradient up would look like the upload failed.
  if (SCHEMA[s.type].fields.some((f) => f.k === "bg"
      && (f.options || []).includes("image")))
    s.settings.bg = "image";
  await loadSiteMedia();
  if (SEL === sid) drawForm();
  pushSettings(s);
}

/* Site media in the panel's picker, alongside product media. */
let SITE_MEDIA = [];
async function loadSiteMedia() {
  try {
    SITE_MEDIA = (await api("/api/store/admin/media/0")).map((m) =>
      ({ ...m, alt: m.alt || `site image #${m.id}` }));
  } catch { SITE_MEDIA = []; }
  MEDIA = [...SITE_MEDIA, ...PRODUCT_MEDIA];
}

// ---------- add-in-place and drag-to-reorder ----------
/* The insertion points between sections are real elements injected into
   the preview: each bar knows which section it sits before. The same bars
   serve both gestures — click one to add a section there, drop a dragged
   section on one to move it there — because "where between the sections"
   is the only question either gesture asks. */

let DRAG_SID = null;

function decorate(doc, secEl) {
  // the drag handle, top-right so the label pseudo keeps the top-left;
  // idempotent, because it runs again when the section list arrives
  if (secEl.querySelector(".sfe-handle")) { addImgBtn(doc, secEl); return; }
  const h = doc.createElement("span");
  h.className = "sfe-handle";
  h.title = "Drag to move this section";
  h.draggable = true;
  h.textContent = "⋮⋮";
  h.ondragstart = (e) => {
    DRAG_SID = +secEl.dataset.sid;
    secEl.classList.add("sfe-dragging");
    doc.body.classList.add("sfe-dragging-page");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setDragImage(secEl, 24, 24); } catch {}
  };
  h.ondragend = () => {
    DRAG_SID = null;
    secEl.classList.remove("sfe-dragging");
    doc.body.classList.remove("sfe-dragging-page");
  };
  secEl.appendChild(h);
  addImgBtn(doc, secEl);
}

function addImgBtn(doc, secEl) {
  if (secEl.querySelector(".sfe-imgbtn")) return;
  const sRow = SECTIONS.find((x) => x.id === +secEl.dataset.sid);
  const mk = mediaKeyOf(sRow);
  if (!mk) return;
  const ib = doc.createElement("span");
  ib.className = "sfe-imgbtn";
  ib.title = "Upload an image for this section (or drop one onto it)";
  // the storefront page carries the icon sprite, so the button can use
  // the shop's own glyph (and the codebase's no-emoji rule holds)
  ib.innerHTML = '<svg class="ico ico-sm" aria-hidden="true">'
    + '<use href="#i-image"/></svg>';
  ib.onclick = (e) => {
    e.stopPropagation();
    UPLOAD_FOR = { sid: sRow.id, key: mk };
    FILE_IN.click();
  };
  secEl.appendChild(ib);
}

function injectBars(doc) {
  doc.querySelectorAll(".sfe-add").forEach((b) => b.remove());
  const secs = [...doc.querySelectorAll("[data-sid]")];
  if (!secs.length) return;
  const mkBar = (beforeSid) => {
    const bar = doc.createElement("div");
    bar.className = "sfe-add";
    bar.dataset.before = beforeSid;
    bar.innerHTML = `<button class="sfe-add-pill" type="button">＋ Add a
      section here</button>`;
    bar.querySelector("button").onclick = (e) => {
      e.stopPropagation(); openPicker(doc, bar);
    };
    bar.ondragover = (e) => {
      if (DRAG_SID == null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      bar.classList.add("sfe-drop");
    };
    bar.ondragleave = () => bar.classList.remove("sfe-drop");
    bar.ondrop = (e) => {
      e.preventDefault();
      bar.classList.remove("sfe-drop");
      dropAt(DRAG_SID, bar.dataset.before);
    };
    return bar;
  };
  secs.forEach((s2) => {
    s2.parentElement.insertBefore(mkBar(s2.dataset.sid), s2);
    decorate(doc, s2);
  });
  secs[secs.length - 1].after(mkBar("end"));
}

/* The type picker, in place: the bar expands into the same list the
   sidebar's dropdown offers, built from the schema so a new section type
   appears here with no editor changes. */
function openPicker(doc, bar) {
  doc.querySelectorAll(".sfe-pick").forEach((p) => p.remove());
  const pick = doc.createElement("div");
  pick.className = "sfe-pick";
  pick.innerHTML = Object.entries(SCHEMA).map(([k, v]) =>
    `<button type="button" data-t="${k}">${v.label}</button>`).join("") +
    `<button type="button" class="sfe-pick-x">Cancel</button>`;
  pick.querySelectorAll("[data-t]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); addAt(b.dataset.t, bar.dataset.before);
  });
  pick.querySelector(".sfe-pick-x").onclick = (e) => {
    e.stopPropagation(); pick.remove();
  };
  bar.appendChild(pick);
}

/* Both gestures speak in "before this section" and translate to an index
   in the FULL list (the preview hides disabled sections, so its own
   ordinals would be wrong the moment one is hidden). */
const beforeIndex = (beforeSid) =>
  beforeSid === "end" ? SECTIONS.length
    : SECTIONS.findIndex((x) => x.id === +beforeSid);

async function addAt(type, beforeSid) {
  const out = await api("/api/store/admin/sections", { method: "POST",
    body: JSON.stringify({ page_slug: SLUG, type,
                           position: beforeIndex(beforeSid) }) });
  SEL = out.id;
  await loadSections(); refresh(0);
}

async function dropAt(sid, beforeSid) {
  if (sid == null) return;
  const i = SECTIONS.findIndex((x) => x.id === sid);
  let a = beforeIndex(beforeSid);
  if (a === i || a === i + 1) return;       // dropped where it already is
  if (a > i) a -= 1;                        // its own removal shifts the rest
  await api(`/api/store/admin/sections/${sid}`, { method: "POST",
    body: JSON.stringify({ position: a }) });
  SEL = sid;
  await loadSections(); refresh(0);
}

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
  // The preview can wire before the section list arrives at boot — the
  // image buttons need to know each section's schema, so pass again.
  const doc = pdoc();
  if (doc && doc.getElementById("sfe-css"))
    doc.querySelectorAll("[data-sid]").forEach((el) => decorate(doc, el));
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
      highlightPreview(SEL);
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
  if (IS_PROVIDER)
    html += `<button class="btn ghost sm" id="save-design"
      style="margin-bottom:8px">Save to library</button>`;
  if (s.design_sync)
    html += `<p style="font-size:12px;color:#6c00bf;background:
      rgba(108,0,191,.07);border-radius:8px;padding:6px 9px;
      margin-bottom:8px">This section follows a studio design — your
      first edit makes it yours, and it stops updating.</p>`;
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
  const sd = $("#save-design");
  if (sd) sd.onclick = async () => {
    const name = prompt("Name this design (same name updates it):",
      s.label);
    if (!name || !name.trim()) return;
    const out = await api("/api/store/admin/designs", { method: "POST",
      body: JSON.stringify({ name: name.trim(), type: s.type,
        settings: s.settings }) });
    const r = out.refreshed || {};
    const n = Object.values(r).reduce((a, b) => a + b, 0);
    if (n) alert(`Updated — and refreshed ${n} linked placement${
      n === 1 ? "" : "s"} (${Object.keys(r).join(", ")}).`);
    await loadDesigns();
  };
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

/* Sections whose content is wired up by the storefront's own script after
   load — a swapped-in copy would arrive inert (an empty product grid, a
   carousel with dead arrows). Those take the full reload; everything else
   swaps in place. */
const NEEDS_RELOAD = new Set(["custom_html", "product_grid", "showcase",
                             "video"]);

async function pushSettings(s, { swap = true } = {}) {
  await api(`/api/store/admin/sections/${s.id}`, { method: "POST",
    body: JSON.stringify({ settings: s.settings }) });
  savedTick();
  if (!swap) return;
  if (NEEDS_RELOAD.has(s.type)) refresh();
  else swapSection(s.id);
}


// ---------- the design library (provider only) ----------
/* Design once on this storefront, place everywhere: save a section by
   name, insert it on this page, or push it onto client tenants. A push
   ADDS — the placement belongs to the tenant the moment it lands. */
let IS_PROVIDER = false, DESIGNS = [];

async function loadDesigns() {
  if (!IS_PROVIDER) return;
  $("#library-wrap").classList.remove("hidden");
  try { DESIGNS = (await api("/api/store/admin/designs")).designs; }
  catch { DESIGNS = []; }
  drawLibrary();
}

function drawLibrary() {
  const host = $("#library");
  host.innerHTML = DESIGNS.map((d) => {
    const where = Object.entries(d.placements)
      .map(([t, p]) => `${t}${p.n > 1 ? ` ×${p.n}` : ""}`
        + (p.linked ? ` (${p.linked} linked)` : "")).join(", ");
    return `<div class="sec">
      <div class="sec-head">
        <span>${d.name}</span>
        <span style="font-size:11px;color:#8a82a0">${d.label}</span>
        <span class="sp"></span>
        <span class="sec-acts">
          <button data-dins="${d.id}" title="insert on this page">＋</button>
          <button data-dpush="${d.id}" title="push to clients">→</button>
          <button data-ddel="${d.id}" title="delete from library">${icon("trash")}</button>
        </span>
      </div>
      ${where ? `<div style="font-size:11px;color:#8a82a0;
        padding:0 8px 6px">on: ${where}</div>` : ""}
    </div>`;
  }).join("") || `<p style="font-size:13px;color:#8a82a0">Nothing saved
    yet — select a section and use “Save to library”.</p>`;

  host.querySelectorAll("[data-dins]").forEach((b) => b.onclick =
    async () => {
      const d = DESIGNS.find((x) => x.id === +b.dataset.dins);
      const out = await api("/api/store/admin/sections", { method: "POST",
        body: JSON.stringify({ page_slug: SLUG, type: d.type,
          settings: d.settings, design_id: d.id }) });
      SEL = out.id;
      await loadSections(); refresh(0);
    });
  host.querySelectorAll("[data-ddel]").forEach((b) => b.onclick =
    async () => {
      if (!confirm("Remove from the library? Placements already made "
        + "stay — they belong to their tenants.")) return;
      await api(`/api/store/admin/designs/${b.dataset.ddel}`,
        { method: "DELETE" });
      await loadDesigns();
    });
  host.querySelectorAll("[data-dpush]").forEach((b) => b.onclick =
    () => openPush(+b.dataset.dpush));
}

async function openPush(did) {
  const d = DESIGNS.find((x) => x.id === did);
  const fleetBoard = await api("/api/store/admin/fleet");
  const me = tenantsOf(fleetBoard).filter((t) => !t.provider);
  if (!me.length) { alert("No client tenants to push to yet."); return; }
  const host = $("#library");
  host.insertAdjacentHTML("afterbegin", `<div class="sec" id="push-box"
    style="padding:8px">
    <b style="font-size:13px">Push “${d.name}” to:</b>
    ${me.map((t) => `<label style="display:flex;gap:6px;font-size:13px;
      margin-top:4px"><input type="checkbox" value="${t.id}"
      data-pt> ${t.id}</label>`).join("")}
    <label style="display:flex;gap:6px;font-size:12px;margin-top:8px;
      color:#8a82a0;border-top:1px solid #eee;padding-top:8px">
      <input type="checkbox" id="push-linked"> Linked — placements follow
      this design's updates until the client edits them</label>
    <div style="display:flex;gap:6px;margin-top:8px">
      <button class="btn sm" id="push-go">Push</button>
      <button class="btn ghost sm" id="push-x">Cancel</button>
    </div></div>`);
  $("#push-x").onclick = () => $("#push-box").remove();
  $("#push-go").onclick = async () => {
    const tenants = [...document.querySelectorAll("[data-pt]:checked")]
      .map((x) => x.value);
    if (!tenants.length) return;
    const out = await api(`/api/store/admin/designs/${did}/push`,
      { method: "POST", body: JSON.stringify({ tenants,
        linked: $("#push-linked").checked }) });
    $("#push-box").remove();
    const n = Object.keys(out.placed).length;
    const sk = Object.entries(out.skipped)
      .map(([t, r]) => `${t}: ${r}`).join("; ");
    alert(`Placed on ${n} storefront${n === 1 ? "" : "s"}.`
      + (sk ? ` Skipped — ${sk}` : ""));
    await loadDesigns();
  };
}

const tenantsOf = (board) =>
  board.nodes.flatMap((n) => n.tenants);

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
  { k: "wordmark_font", t: "select", label: "Wordmark font (your name)",
    options: ["Quicksand", "Inter", "Fraunces"] },
  // What stands in for a product with no photograph. A shop selling plans
  // or services should not have to explain a drinks can.
  { k: "art", t: "select", label: "Stand-in product art",
    options: ["card", "can"] },
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
let MEDIA = [], PRODUCT_MEDIA = [], COLLECTIONS = [];
async function boot() {
  $("#login").classList.add("hidden");
  $("#topbar").classList.remove("hidden");
  $("#app").classList.remove("hidden");
  SCHEMA = await api("/api/store/admin/section-schema");
  $("#add-type").innerHTML = Object.entries(SCHEMA).map(([k, v]) =>
    `<option value="${k}">${v.label}</option>`).join("");
  const cat = await (await fetch("/api/store/catalog")).json();
  COLLECTIONS = cat.collections;
  PRODUCT_MEDIA = cat.products.flatMap((p) =>
    (p.media || []).map((m) => ({ ...m, alt: m.alt || p.name })));
  await loadSiteMedia();
  try { IS_PROVIDER = !!(await (await fetch("/api/meta")).json())
    .is_provider; } catch { IS_PROVIDER = false; }
  await loadDesigns();
  THEME = await api("/api/store/admin/theme");
  drawTheme();
  await loadPages();
  await loadSections();
}

(async () => {
  if (!TOKEN) return;
  try { await api("/api/store/admin/theme"); boot(); } catch {}
})();
