// Shared UI plumbing: DOM building, the API client, formatting, toast, modal.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** el("div.card", {onclick}, "text", childNode) — tag supports .class and #id. */
export function el(spec, props = {}, ...kids) {
  const [tag, ...classes] = String(spec).split(".");
  const [name, id] = tag.split("#");
  const node = document.createElement(name || "div");
  if (id) node.id = id;
  if (classes.length) node.className = classes.join(" ");
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = [node.className, v].filter(Boolean).join(" ");
    else if (k === "html") node.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k in node && k !== "list" && typeof v !== "boolean") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  add(node, kids);
  return node;
}

function add(node, kids) {
  for (const k of kids.flat(4)) {
    if (k === null || k === undefined || k === false) continue;
    node.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

export const clear = (node) => { node.replaceChildren(); return node; };

// ------------------------------------------------------------------ api

const TOKEN_KEY = "av-trainer-token";
export const token = {
  get: () => localStorage.getItem(TOKEN_KEY) || "",
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export async function api(path, { method = "GET", body, raw = false } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token.get() ? { Authorization: `Bearer ${token.get()}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { token.clear(); location.reload(); throw new Error("signed out"); }
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* non-JSON error */ }
    throw new Error(msg);
  }
  return raw ? res : res.json();
}

// ------------------------------------------------------------------ chrome

let toastTimer;
export function toast(msg, ms = 2200) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

export function modal(...content) {
  const wrap = $("#modal"), card = $("#modal-card");
  clear(card);
  add(card, content);
  wrap.hidden = false;
  const close = (e) => { if (e.target === wrap) closeModal(); };
  wrap.onclick = close;
  document.addEventListener("keydown", escClose);
  return card;
}
function escClose(e) { if (e.key === "Escape") closeModal(); }
export function closeModal() {
  $("#modal").hidden = true;
  document.removeEventListener("keydown", escClose);
}

export function confirmDialog(question, detail = "") {
  return new Promise((resolve) => {
    modal(
      el("h2", {}, question),
      detail && el("p.dim", {}, detail),
      el("div.row", { style: { justifyContent: "flex-end", marginTop: "1rem" } },
        el("button", { onclick: () => { closeModal(); resolve(false); } }, "Cancel"),
        el("button.primary", { onclick: () => { closeModal(); resolve(true); } }, "Yes")),
    );
  });
}

// ------------------------------------------------------------------ format

export const today = () => new Date().toISOString().slice(0, 10);

export function relDay(iso) {
  if (!iso) return "";
  const d = Math.round((new Date(iso) - new Date(today())) / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "tomorrow";
  if (d === -1) return "yesterday";
  return d < 0 ? `${-d} days ago` : `in ${d} days`;
}

export function relTime(epoch) {
  if (!epoch) return "never";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 90) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return d < 30 ? `${d}d ago` : `${Math.floor(d / 30)}mo ago`;
}

export const hhmm = (min) => (min >= 60 ? `${Math.floor(min / 60)}h ${min % 60 ? `${min % 60}m` : ""}`.trim() : `${min}m`);

export const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);

/** Deterministic small PRNG, so a stimulus can be regenerated from its seed. */
export function rng(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
}

export const pick = (r, arr) => arr[Math.floor(r() * arr.length) % arr.length];
export const shuffle = (r, arr) => {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
};
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** A labelled range control that reports its value live. */
export function knob(label, { min, max, step = 1, value, format = (v) => v, oninput }) {
  const out = el("b", {}, format(value));
  const input = el("input", {
    type: "range", min, max, step, value,
    oninput: (e) => {
      const v = parseFloat(e.target.value);
      out.textContent = format(v);
      oninput(v);
    },
  });
  return el("label.knob", {}, out, label, input);
}

export function field(label, input) {
  return el("label", {}, label, input);
}
