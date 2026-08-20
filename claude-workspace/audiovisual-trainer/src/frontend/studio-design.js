// The design editor: vector shapes, type and layout on an infinite canvas,
// with frames, snapping, auto-layout and a grid overlay.
//
// Rendered as SVG rather than canvas, deliberately. A layout tool needs crisp
// text at any zoom, hit-testing that does not mean re-implementing geometry,
// and an export that is genuinely vector — all three come free from the DOM.
//
// The grid overlay is not decoration: Müller-Brockmann's column grid is the
// thing the composition lesson is about, and a layout tool that cannot show
// you the grid cannot teach you to see it.

import { el, clear, append, toast, modal, closeModal, confirmDialog, api } from "./ui.js";
import { fullscreenButton } from "./fullscreen.js";
import { aiButton } from "./ai.js";
import { compileDesignFrame, fitPreview } from "./design-to-sdf.js";
import { applyEffects, effectCost, effectLabel, makeEffect, prepareEffects } from "./canvas-graph.js";
import { GRAPH_FILTERS, graphFilter } from "./filter-nodes.js";
import { userNodes } from "./node-library.js";
import { nodeType } from "./render-graph.js";
import { buildControls } from "./shader-controls.js";
import { FILTERS } from "./engine-image.js";

const SVGNS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  return n;
};

export const FRAME_PRESETS = [
  ["Desktop", 1440, 900], ["Laptop", 1280, 800], ["Tablet", 768, 1024],
  ["Mobile", 375, 812], ["Square", 1080, 1080], ["Story", 1080, 1920],
  ["Poster A3", 842, 1191],
];

const TOOLS = [
  ["select", "Move", "V"], ["frame", "Frame", "F"], ["rect", "Rect", "R"],
  ["ellipse", "Ellipse", "O"], ["line", "Line", "L"], ["text", "Text", "T"],
];

const SNAP_PX = 6;

let uid = Date.now() % 1e6;
const nextId = () => `n${++uid}`;

export function newDesignDoc(preset = "Desktop") {
  const p = FRAME_PRESETS.find((f) => f[0] === preset) || FRAME_PRESETS[0];
  return {
    nodes: [{
      id: nextId(), type: "frame", name: p[0], x: 0, y: 0, w: p[1], h: p[2],
      fill: "#ffffff", visible: true, children: [],
      grid: { on: false, columns: 12, gutter: 24, margin: 64 },
    }],
    viewport: { x: 80, y: 60, zoom: 0.5 },
  };
}

export async function designEditor(host) {
  const doc = host.data;
  doc.nodes ||= newDesignDoc().nodes;
  const view = doc.viewport || (doc.viewport = { x: 80, y: 60, zoom: 0.5 });

  let tool = "select";
  let selection = [];              // array of node ids
  let clipboard = null;
  const undo = [], redo = [];

  // ---------------------------------------------------------------- model

  /** Walk every node, depth first, with its parent. */
  function* walk(list = doc.nodes, parent = null) {
    for (const n of list) {
      yield [n, parent];
      if (n.children) yield* walk(n.children, n);
    }
  }
  const byId = (id) => {
    for (const [n] of walk()) if (n.id === id) return n;
    return null;
  };
  const parentOf = (id) => {
    for (const [n, p] of walk()) if (n.id === id) return p;
    return null;
  };
  const siblingsOf = (id) => (parentOf(id)?.children) || doc.nodes;
  const selected = () => selection.map(byId).filter(Boolean);

  /** Absolute position: children are stored relative to their frame/group. */
  function absolute(node) {
    let x = node.x, y = node.y, p = parentOf(node.id);
    while (p) { x += p.x; y += p.y; p = parentOf(p.id); }
    return { x, y, w: node.w, h: node.h };
  }

  const snapshot = () => {
    undo.push(JSON.stringify(doc.nodes));
    if (undo.length > 40) undo.shift();
    redo.length = 0;
  };
  const restore = (from, to) => {
    const s = from.pop();
    if (!s) return;
    to.push(JSON.stringify(doc.nodes));
    doc.nodes = JSON.parse(s);
    selection = selection.filter(byId);
    renderAll();
    save();
  };

  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => host.save(thumbnail()), 500);
  }

  // ---------------------------------------------------------------- surface

  const surface = svg("svg", { class: "design-surface" });
  const worldG = svg("g");
  const overlay = svg("g", { class: "design-overlay" });
  surface.append(worldG, overlay);

  const wrap = el("div.design-canvas", {}, surface);
  // The surface is a viewport with its own pan and zoom, so fullscreen fills
  // rather than letterboxes: what it wants is more room, not a bigger copy.
  const fs = fullscreenButton(wrap, { fit: "fill", onRefused: (why) => toast(why) });

  const toWorld = (clientX, clientY) => {
    const r = surface.getBoundingClientRect();
    return {
      x: (clientX - r.left - view.x) / view.zoom,
      y: (clientY - r.top - view.y) / view.zoom,
    };
  };

  function applyViewport() {
    worldG.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.zoom})`);
    overlay.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.zoom})`);
    zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
  }

  // ---------------------------------------------------------------- render

  /**
   * A node with an effect stack is drawn through the graph: its own subtree is
   * rasterised on its own, the stack runs over it, and the result goes back in
   * as an image. Baking is asynchronous, so the plain drawing stands in until
   * it lands and nothing ever waits for a frame.
   *
   * The raster is padded, because a blur or a glow does not stay inside the
   * box the shape occupies.
   */
  const FX_PAD = 40;
  const fxCache = new Map();          // key → { url, w, h, pad }
  const fxPending = new Set();

  const fxKey = (node) => JSON.stringify([nodeShape(node), node.effects]);
  const nodeShape = (n) => ({
    t: n.type, w: n.w, h: n.h, r: n.radius, f: n.fill, s: n.stroke, sw: n.strokeWidth,
    o: n.opacity, b: n.blend, rot: n.rotation, tx: n.text, fs: n.fontSize, ff: n.fontFamily,
    fw: n.fontWeight, al: n.align, lh: n.lineHeight, ls: n.letterSpacing, src: n.src,
    kids: (n.children || []).map(nodeShape),
  });

  async function bakeEffects(node) {
    const key = fxKey(node);
    if (fxPending.has(key)) return;
    fxPending.add(key);
    try {
      const pad = FX_PAD, scale = 2;
      const w = Math.max(1, Math.round(node.w)) + pad * 2;
      const h = Math.max(1, Math.round(node.h)) + pad * 2;
      const holder = svg("svg", { xmlns: SVGNS, width: w, height: h, viewBox: `0 0 ${w} ${h}` });
      const g = paintNode(node, { x: 0, y: 0 }, true);
      if (g) { g.setAttribute("transform", `translate(${pad} ${pad})`
        + (node.rotation ? ` rotate(${node.rotation} ${node.w / 2} ${node.h / 2})` : "")); holder.append(g); }
      const text = new XMLSerializer().serializeToString(holder);
      const img = new Image();
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
      await img.decode();
      const c = document.createElement("canvas");
      c.width = w * scale; c.height = h * scale;
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      const out = applyEffects(c, node.effects || []);
      fxCache.set(key, { url: out.toDataURL("image/png"), w, h, pad });
      if (fxCache.size > 24) fxCache.delete(fxCache.keys().next().value);
      renderWorld();
    } catch (e) {
      fxCache.set(key, { error: String(e.message).split("\n")[0] });
    } finally {
      fxPending.delete(key);
    }
  }

  function paintNode(node, parentAbs = { x: 0, y: 0 }, raw = false) {
    if (node.visible === false) return null;
    if (!raw && (node.effects || []).some((e) => !e.bypass)) {
      const hit = fxCache.get(fxKey(node));
      if (hit && hit.url) {
        const g2 = svg("g", { "data-id": node.id,
          transform: `translate(${node.x} ${node.y})`,
          opacity: node.opacity ?? 1,
          style: node.blend && node.blend !== "normal" ? `mix-blend-mode:${node.blend}` : null });
        const im = svg("image", { x: -hit.pad, y: -hit.pad, width: hit.w, height: hit.h });
        im.setAttributeNS("http://www.w3.org/1999/xlink", "href", hit.url);
        im.setAttribute("href", hit.url);
        g2.append(im);
        return g2;
      }
      if (!hit) bakeEffects(node);
    }
    const g = svg("g", {
      "data-id": node.id,
      transform: `translate(${node.x} ${node.y})` +
        (node.rotation ? ` rotate(${node.rotation} ${node.w / 2} ${node.h / 2})` : ""),
      opacity: node.opacity ?? 1,
      style: node.blend && node.blend !== "normal" ? `mix-blend-mode:${node.blend}` : null,
    });

    if (node.type === "frame") {
      g.append(svg("rect", { width: node.w, height: node.h, fill: node.fill || "#fff",
                             rx: node.radius || 0 }));
      if (node.grid?.on) g.append(gridOverlay(node));
    } else if (node.type === "rect") {
      g.append(svg("rect", { width: node.w, height: node.h, rx: node.radius || 0,
        fill: node.fill || "none", stroke: node.stroke || null,
        "stroke-width": node.strokeWidth || 0 }));
    } else if (node.type === "ellipse") {
      g.append(svg("ellipse", { cx: node.w / 2, cy: node.h / 2, rx: node.w / 2, ry: node.h / 2,
        fill: node.fill || "none", stroke: node.stroke || null,
        "stroke-width": node.strokeWidth || 0 }));
    } else if (node.type === "line") {
      g.append(svg("line", { x1: 0, y1: 0, x2: node.w, y2: node.h,
        stroke: node.stroke || "#000", "stroke-width": node.strokeWidth || 2,
        "stroke-linecap": "round" }));
    } else if (node.type === "text") {
      const size = node.fontSize || 32;
      const lh = (node.lineHeight || 1.3) * size;
      const t = svg("text", {
        fill: node.fill || "#111", "font-size": size,
        "font-weight": node.fontWeight || 500,
        "font-family": node.fontFamily || "system-ui, sans-serif",
        "letter-spacing": node.letterSpacing ?? 0,
        "text-anchor": node.align === "center" ? "middle" : node.align === "right" ? "end" : "start",
      });
      const lines = String(node.text ?? "Text").split("\n");
      const ax = node.align === "center" ? node.w / 2 : node.align === "right" ? node.w : 0;
      lines.forEach((line, i) => {
        t.append(svg("tspan", { x: ax, y: size * 0.92 + i * lh }, ));
        t.lastChild.textContent = line;
      });
      g.append(t);
    } else if (node.type === "image" && node.href) {
      g.append(svg("image", { href: node.href, width: node.w, height: node.h,
        preserveAspectRatio: "xMidYMid slice" }));
    }

    if (node.children) {
      layoutChildren(node);
      for (const c of node.children) {
        const child = paintNode(c);
        if (child) g.append(child);
      }
    }
    return g;
  }

  function gridOverlay(frame) {
    const { columns, gutter, margin } = frame.grid;
    const g = svg("g", { "pointer-events": "none" });
    const usable = frame.w - margin * 2;
    const colW = (usable - gutter * (columns - 1)) / columns;
    for (let i = 0; i < columns; i++) {
      g.append(svg("rect", {
        x: margin + i * (colW + gutter), y: 0, width: Math.max(0, colW), height: frame.h,
        fill: "rgba(124,156,255,.16)",
      }));
    }
    return g;
  }

  /** Auto-layout: a stack with a gap. The single most useful Figma idea. */
  function layoutChildren(node) {
    const L = node.layout;
    if (!L || L.dir === "none") return;
    const pad = L.pad ?? 0, gap = L.gap ?? 0;
    let cursor = pad;
    for (const c of node.children) {
      if (c.visible === false) continue;
      if (L.dir === "horizontal") {
        c.x = cursor; c.y = pad;
        if (L.stretch) c.h = Math.max(1, node.h - pad * 2);
        cursor += c.w + gap;
      } else {
        c.x = pad; c.y = cursor;
        if (L.stretch) c.w = Math.max(1, node.w - pad * 2);
        cursor += c.h + gap;
      }
    }
    if (L.hug) {
      if (L.dir === "horizontal") node.w = Math.max(1, cursor - gap + pad);
      else node.h = Math.max(1, cursor - gap + pad);
    }
  }

  let worldPass = 0;
  function renderWorld() {
    // bakeEffects calls back into here when a raster lands; one level deep is
    // all it ever needs, and the guard keeps a failed bake from looping.
    if (worldPass > 2) return;
    worldPass++;
    clear(worldG);
    for (const n of doc.nodes) {
      const g = paintNode(n);
      if (g) worldG.append(g);
    }
    worldPass--;
  }

  function renderOverlay(extra = null) {
    clear(overlay);
    const inv = 1 / view.zoom;
    for (const n of selected()) {
      const a = absolute(n);
      overlay.append(svg("rect", {
        x: a.x, y: a.y, width: a.w, height: a.h, fill: "none",
        stroke: "#7c9cff", "stroke-width": 1.5 * inv, "pointer-events": "none",
      }));
      if (selection.length === 1) {
        for (const [hx, hy] of handlePoints(a)) {
          overlay.append(svg("rect", {
            x: hx - 4 * inv, y: hy - 4 * inv, width: 8 * inv, height: 8 * inv,
            fill: "#0d0f18", stroke: "#7c9cff", "stroke-width": 1.5 * inv,
            "pointer-events": "none",
          }));
        }
      }
    }
    if (extra) overlay.append(extra);
  }

  const handlePoints = (a) => [
    [a.x, a.y], [a.x + a.w / 2, a.y], [a.x + a.w, a.y],
    [a.x + a.w, a.y + a.h / 2], [a.x + a.w, a.y + a.h],
    [a.x + a.w / 2, a.y + a.h], [a.x, a.y + a.h], [a.x, a.y + a.h / 2],
  ];
  const HANDLE_DIRS = [[-1, -1], [0, -1], [1, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0]];

  function renderAll() {
    renderWorld();
    renderOverlay();
    renderTree();
    renderInspector();
    applyViewport();
  }

  // ---------------------------------------------------------------- snapping

  /** Candidate guides from everything that is not being dragged. */
  function snapTargets(excludeIds) {
    const xs = [], ys = [];
    for (const [n] of walk()) {
      if (excludeIds.includes(n.id) || n.visible === false) continue;
      const a = absolute(n);
      xs.push(a.x, a.x + a.w / 2, a.x + a.w);
      ys.push(a.y, a.y + a.h / 2, a.y + a.h);
    }
    return { xs, ys };
  }

  function applySnap(box, targets) {
    const tol = SNAP_PX / view.zoom;
    const guides = [];
    const edgesX = [[box.x, 0], [box.x + box.w / 2, box.w / 2], [box.x + box.w, box.w]];
    let dx = 0, bestX = tol;
    for (const [edge, off] of edgesX) {
      for (const t of targets.xs) {
        const d = Math.abs(edge - t);
        if (d < bestX) { bestX = d; dx = t - edge; guides.push(["x", t]); }
      }
    }
    const edgesY = [[box.y, 0], [box.y + box.h / 2, box.h / 2], [box.y + box.h, box.h]];
    let dy = 0, bestY = tol;
    for (const [edge, off] of edgesY) {
      for (const t of targets.ys) {
        const d = Math.abs(edge - t);
        if (d < bestY) { bestY = d; dy = t - edge; guides.push(["y", t]); }
      }
    }
    return { dx, dy, guides: guides.slice(-2) };
  }

  function guideMarks(guides) {
    const g = svg("g", { "pointer-events": "none" });
    const inv = 1 / view.zoom;
    const span = 4000;
    for (const [axis, v] of guides) {
      g.append(svg("line", axis === "x"
        ? { x1: v, y1: -span, x2: v, y2: span, stroke: "#f0a35e", "stroke-width": inv }
        : { x1: -span, y1: v, x2: span, y2: v, stroke: "#f0a35e", "stroke-width": inv }));
    }
    return g;
  }

  // ---------------------------------------------------------------- interaction

  let drag = null;

  surface.addEventListener("pointerdown", (e) => {
    if (e.button === 1 || e.altKey || tool === "pan") {          // pan
      drag = { mode: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y };
      surface.setPointerCapture?.(e.pointerId);
      return;
    }
    const p = toWorld(e.clientX, e.clientY);

    if (tool !== "select") {
      snapshot();
      const node = makeNode(tool, p);
      const host_ = tool === "frame" ? null : frameAt(p);
      if (host_) {
        const a = absolute(host_);
        node.x = p.x - a.x; node.y = p.y - a.y;
        host_.children.push(node);
      } else doc.nodes.push(node);
      selection = [node.id];
      drag = { mode: "draw", node, ox: p.x, oy: p.y, parent: host_ };
      renderAll();
      return;
    }

    // select: topmost hit
    const hit = e.target.closest?.("[data-id]");
    const id = hit?.getAttribute("data-id");
    if (!id) {
      if (!e.shiftKey) selection = [];
      drag = { mode: "marquee", ox: p.x, oy: p.y };
      renderOverlay();
      return;
    }

    // A resize handle beats a node hit.
    const handleIdx = handleUnder(p);
    if (handleIdx >= 0 && selection.length === 1) {
      snapshot();
      const n = byId(selection[0]);
      drag = { mode: "resize", idx: handleIdx, node: n, start: { ...absolute(n) }, ox: p.x, oy: p.y };
      return;
    }

    if (e.shiftKey) {
      selection = selection.includes(id) ? selection.filter((s) => s !== id) : [...selection, id];
    } else if (!selection.includes(id)) {
      selection = [id];
    }
    snapshot();
    drag = {
      mode: "move", ox: p.x, oy: p.y,
      starts: selected().map((n) => ({ n, x: n.x, y: n.y })),
      targets: snapTargets(selection),
    };
    renderAll();
  });

  function handleUnder(p) {
    if (selection.length !== 1) return -1;
    const a = absolute(byId(selection[0]));
    const tol = 7 / view.zoom;
    const pts = handlePoints(a);
    for (let i = 0; i < pts.length; i++) {
      if (Math.abs(p.x - pts[i][0]) <= tol && Math.abs(p.y - pts[i][1]) <= tol) return i;
    }
    return -1;
  }

  function frameAt(p) {
    // Innermost frame containing the point, so drawing lands inside it.
    let found = null;
    for (const [n] of walk()) {
      if (n.type !== "frame" || n.visible === false) continue;
      const a = absolute(n);
      if (p.x >= a.x && p.x <= a.x + a.w && p.y >= a.y && p.y <= a.y + a.h) found = n;
    }
    return found;
  }

  surface.addEventListener("pointermove", (e) => {
    if (!drag) {
      if (tool === "select" && selection.length === 1) {
        const idx = handleUnder(toWorld(e.clientX, e.clientY));
        surface.style.cursor = idx >= 0
          ? ["nwse", "ns", "nesw", "ew", "nwse", "ns", "nesw", "ew"][idx] + "-resize"
          : "default";
      }
      return;
    }
    const p = toWorld(e.clientX, e.clientY);

    if (drag.mode === "pan") {
      view.x = drag.ox + (e.clientX - drag.sx);
      view.y = drag.oy + (e.clientY - drag.sy);
      applyViewport();
      return;
    }
    if (drag.mode === "draw") {
      const n = drag.node;
      n.w = Math.max(1, Math.abs(p.x - drag.ox));
      n.h = Math.max(1, Math.abs(p.y - drag.oy));
      const base = drag.parent ? absolute(drag.parent) : { x: 0, y: 0 };
      n.x = Math.min(p.x, drag.ox) - base.x;
      n.y = Math.min(p.y, drag.oy) - base.y;
      renderWorld(); renderOverlay();
      return;
    }
    if (drag.mode === "move") {
      let dx = p.x - drag.ox, dy = p.y - drag.oy;
      for (const s of drag.starts) { s.n.x = s.x + dx; s.n.y = s.y + dy; }
      // Snap the primary node, then carry the correction to the rest.
      const first = drag.starts[0];
      if (first) {
        const a = absolute(first.n);
        const { dx: sx, dy: sy, guides } = applySnap(a, drag.targets);
        if (sx || sy) for (const s of drag.starts) { s.n.x += sx; s.n.y += sy; }
        renderWorld(); renderOverlay(guides.length ? guideMarks(guides) : null);
        return;
      }
      renderWorld(); renderOverlay();
      return;
    }
    if (drag.mode === "resize") {
      const [hx, hy] = HANDLE_DIRS[drag.idx];
      const s = drag.start, n = drag.node;
      let nx = s.x, ny = s.y, nw = s.w, nh = s.h;
      if (hx < 0) { nx = p.x; nw = s.x + s.w - p.x; }
      if (hx > 0) { nw = p.x - s.x; }
      if (hy < 0) { ny = p.y; nh = s.y + s.h - p.y; }
      if (hy > 0) { nh = p.y - s.y; }
      if (e.shiftKey && s.w && s.h) {                    // keep the ratio
        const r = s.w / s.h;
        if (Math.abs(hx)) nh = nw / r; else if (Math.abs(hy)) nw = nh * r;
      }
      const par = parentOf(n.id);
      const base = par ? absolute(par) : { x: 0, y: 0 };
      n.w = Math.max(1, nw); n.h = Math.max(1, nh);
      n.x = nx - base.x; n.y = ny - base.y;
      renderWorld(); renderOverlay();
      return;
    }
    if (drag.mode === "marquee") {
      const x = Math.min(p.x, drag.ox), y = Math.min(p.y, drag.oy);
      const w = Math.abs(p.x - drag.ox), h = Math.abs(p.y - drag.oy);
      const box = svg("rect", { x, y, width: w, height: h, fill: "rgba(124,156,255,.12)",
        stroke: "#7c9cff", "stroke-width": 1 / view.zoom, "pointer-events": "none" });
      selection = [];
      for (const [n, par] of walk()) {
        if (n.visible === false) continue;
        const a = absolute(n);
        if (a.x >= x && a.y >= y && a.x + a.w <= x + w && a.y + a.h <= y + h) {
          if (!par) selection.push(n.id);       // top level only, like Figma
        }
      }
      renderOverlay(box);
    }
  });

  const endDrag = () => {
    if (!drag) return;
    if (drag.mode === "draw" && (drag.node.w < 3 && drag.node.h < 3)) {
      // A click with a shape tool makes a default-sized node, not a speck.
      drag.node.w = drag.node.type === "text" ? 240 : 160;
      drag.node.h = drag.node.type === "text" ? 48 : 120;
    }
    if (drag.mode !== "pan" && drag.mode !== "marquee") save();
    drag = null;
    if (tool !== "select" && tool !== "frame") setTool("select");
    renderAll();
  };
  surface.addEventListener("pointerup", endDrag);
  surface.addEventListener("pointercancel", endDrag);

  surface.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = surface.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    if (e.ctrlKey || e.metaKey || !e.shiftKey) {
      const before = { x: (mx - view.x) / view.zoom, y: (my - view.y) / view.zoom };
      view.zoom = Math.max(0.05, Math.min(8, view.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      view.x = mx - before.x * view.zoom;
      view.y = my - before.y * view.zoom;
    } else {
      view.x -= e.deltaX; view.y -= e.deltaY;
    }
    applyViewport();
    renderOverlay();
  }, { passive: false });

  function makeNode(type, p) {
    const base = { id: nextId(), type, x: p.x, y: p.y, w: 1, h: 1, visible: true,
                   opacity: 1, name: type };
    if (type === "frame") return { ...base, fill: "#ffffff", children: [],
      grid: { on: false, columns: 12, gutter: 24, margin: 64 } };
    if (type === "rect") return { ...base, fill: "#7c9cff", radius: 0 };
    if (type === "ellipse") return { ...base, fill: "#6ee7c8" };
    if (type === "line") return { ...base, stroke: "#111111", strokeWidth: 2 };
    if (type === "text") return { ...base, text: "Text", fill: "#111111",
      fontSize: 32, fontWeight: 500, lineHeight: 1.3, align: "left", w: 240, h: 48 };
    return base;
  }

  // ---------------------------------------------------------------- keyboard

  function onKey(e) {
    // Self-removing: the view can be torn down by any navigation path, and a
    // stray editor shortcut firing on the Library tab is a real bug.
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (/input|textarea|select/i.test(e.target.tagName)) return;
    const meta = e.metaKey || e.ctrlKey;
    if (meta && e.key.toLowerCase() === "z") {
      e.preventDefault();
      e.shiftKey ? restore(redo, undo) : restore(undo, redo);
      return;
    }
    if (meta && e.key.toLowerCase() === "d") { e.preventDefault(); duplicate(); return; }
    if (meta && e.key.toLowerCase() === "c") { clipboard = JSON.stringify(selected()); return; }
    if (meta && e.key.toLowerCase() === "v") { e.preventDefault(); paste(); return; }
    if (meta && e.key.toLowerCase() === "g") { e.preventDefault(); e.shiftKey ? ungroup() : group(); return; }
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeSelected(); return; }
    if (e.key === "Escape") { selection = []; renderAll(); return; }
    const t = TOOLS.find((x) => x[2].toLowerCase() === e.key.toLowerCase());
    if (t && !meta) { setTool(t[0]); return; }
    const step = e.shiftKey ? 10 : 1;
    const nudges = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (nudges[e.key]) {
      e.preventDefault();
      snapshot();
      for (const n of selected()) { n.x += nudges[e.key][0]; n.y += nudges[e.key][1]; }
      renderAll(); save();
    }
  }
  document.addEventListener("keydown", onKey);

  function removeSelected() {
    if (!selection.length) return;
    snapshot();
    for (const id of selection) {
      const list = siblingsOf(id);
      const i = list.findIndex((n) => n.id === id);
      if (i >= 0) list.splice(i, 1);
    }
    selection = [];
    renderAll(); save();
  }
  function duplicate() {
    if (!selection.length) return;
    snapshot();
    const copies = selected().map((n) => reid({ ...JSON.parse(JSON.stringify(n)), x: n.x + 20, y: n.y + 20 }));
    for (const c of copies) siblingsOf(selection[0]).push(c);
    selection = copies.map((c) => c.id);
    renderAll(); save();
  }
  function paste() {
    if (!clipboard) return;
    snapshot();
    const nodes = JSON.parse(clipboard).map((n) => reid({ ...n, x: n.x + 24, y: n.y + 24 }));
    doc.nodes.push(...nodes);
    selection = nodes.map((n) => n.id);
    renderAll(); save();
  }
  const reid = (n) => {
    n.id = nextId();
    if (n.children) n.children = n.children.map(reid);
    return n;
  };
  function group() {
    if (selection.length < 2) return;
    snapshot();
    const nodes = selected();
    const boxes = nodes.map(absolute);
    const x = Math.min(...boxes.map((b) => b.x)), y = Math.min(...boxes.map((b) => b.y));
    const x2 = Math.max(...boxes.map((b) => b.x + b.w)), y2 = Math.max(...boxes.map((b) => b.y + b.h));

    // The group belongs where the nodes already lived. Pushing it to the
    // canvas root would reparent everything out of its frame, and since the
    // box was measured in absolute coordinates the group would also jump by
    // the frame's offset.
    const host_ = parentOf(nodes[0].id);
    const hostAbs = host_ ? absolute(host_) : { x: 0, y: 0 };
    const target = host_ ? host_.children : doc.nodes;

    const g = { id: nextId(), type: "frame", name: "Group",
                x: x - hostAbs.x, y: y - hostAbs.y, w: x2 - x, h: y2 - y,
                fill: "none", visible: true, children: [] };
    for (const n of nodes) {
      const list = siblingsOf(n.id);
      list.splice(list.findIndex((m) => m.id === n.id), 1);
      const a = boxes[nodes.indexOf(n)];
      n.x = a.x - x; n.y = a.y - y;
      g.children.push(n);
    }
    target.push(g);
    selection = [g.id];
    renderAll(); save();
  }
  function ungroup() {
    const g = selected()[0];
    if (!g?.children?.length) return;
    snapshot();
    const a = absolute(g);
    const list = siblingsOf(g.id);
    for (const c of g.children) { c.x += a.x; c.y += a.y; list.push(c); }
    list.splice(list.findIndex((n) => n.id === g.id), 1);
    selection = g.children.map((c) => c.id);
    renderAll(); save();
  }

  // ---------------------------------------------------------------- align

  function align(how) {
    const nodes = selected();
    if (nodes.length < 2) { toast("Select two or more"); return; }
    snapshot();
    const boxes = nodes.map(absolute);
    const minX = Math.min(...boxes.map((b) => b.x)), maxX = Math.max(...boxes.map((b) => b.x + b.w));
    const minY = Math.min(...boxes.map((b) => b.y)), maxY = Math.max(...boxes.map((b) => b.y + b.h));
    nodes.forEach((n, i) => {
      const b = boxes[i];
      if (how === "left") n.x += minX - b.x;
      if (how === "hcenter") n.x += (minX + maxX) / 2 - (b.x + b.w / 2);
      if (how === "right") n.x += maxX - (b.x + b.w);
      if (how === "top") n.y += minY - b.y;
      if (how === "vcenter") n.y += (minY + maxY) / 2 - (b.y + b.h / 2);
      if (how === "bottom") n.y += maxY - (b.y + b.h);
    });
    if (how === "hdist" || how === "vdist") {
      const key = how === "hdist" ? "x" : "y";
      const size = how === "hdist" ? "w" : "h";
      const order = nodes.map((n, i) => ({ n, b: boxes[i] })).sort((a, b) => a.b[key] - b.b[key]);
      const total = order[order.length - 1].b[key] + order[order.length - 1].b[size] - order[0].b[key];
      const used = order.reduce((s, o) => s + o.b[size], 0);
      const gap = (total - used) / (order.length - 1);
      let cur = order[0].b[key];
      for (const o of order) { o.n[key] += cur - o.b[key]; cur += o.b[size] + gap; }
    }
    renderAll(); save();
  }

  // ---------------------------------------------------------------- panels

  const tree = el("div.stack.design-tree");
  function renderTree() {
    clear(tree);
    const row = (n, depth) => {
      const r = el("div.design-row", {
        class: selection.includes(n.id) ? "on" : "",
        style: { paddingLeft: `${depth * 12 + 6}px` },
        onclick: (e) => {
          selection = e.shiftKey ? [...new Set([...selection, n.id])] : [n.id];
          renderAll();
        },
      },
        el("span.design-row-name", {}, n.name || n.type),
        el("span.fine", {}, n.type),
        el("button.ghost", {
          title: "hide",
          onclick: (e) => { e.stopPropagation(); n.visible = n.visible === false; renderAll(); save(); },
        }, n.visible === false ? "○" : "●"));
      tree.append(r);
      if (n.children) for (const c of [...n.children].reverse()) row(c, depth + 1);
    };
    for (const n of [...doc.nodes].reverse()) row(n, 0);
  }

  const inspector = el("div.stack");
  /**
   * A design node's effect stack. The geometry stays vector — this is not a
   * raster tool — but a blur or a grade is not geometry, and the graph is
   * where those belong. The stack runs over the node's own rendering and
   * composites back into the design in its place.
   */
  function effectPanel(n) {
    const fx = n.effects || [];
    const cost = fx.length ? (() => { try { return effectCost(fx); } catch (e) { return null; } })() : null;
    const move = (i, d) => {
      const j = i + d;
      if (j < 0 || j >= fx.length) return;
      snapshot();
      [fx[i], fx[j]] = [fx[j], fx[i]];
      renderWorld(); renderInspector(); save();
    };
    const changed = () => { renderWorld(); save(); };
    return el("div.stack", { style: { gap: ".2rem", marginTop: ".5rem" } },
      el("div.spread", {},
        el("h4", { style: { margin: 0 } }, "Effects"),
        el("button.ghost", { onclick: () => effectDialog(n) }, "+ effect")),
      ...fx.map((e, i) => el("div.spread", {},
        el("div.row.tight", {},
          el("input", { type: "checkbox", checked: !e.bypass, style: { width: "auto" },
            onchange: (ev) => { e.bypass = !ev.target.checked; changed(); } }),
          el("span.fine", { style: { opacity: e.bypass ? 0.5 : 1 } }, effectLabel(e))),
        el("div.row.tight", {},
          el("button.ghost", { title: "earlier", onclick: () => move(i, -1) }, "↑"),
          el("button.ghost", { title: "later", onclick: () => move(i, 1) }, "↓"),
          el("button.ghost.danger", {
            onclick: () => { snapshot(); fx.splice(i, 1); renderWorld(); renderInspector(); save(); } }, "×")))),
      fx.length ? el("p.fine", {}, `${cost ? cost.draws : "?"} GPU draw${cost && cost.draws === 1 ? "" : "s"} · `
        + "the node is rasterised, the stack runs over it, and the result goes back into the design. "
        + "The geometry stays vector.") : null);
  }

  function effectDialog(n) {
    const pick = el("select", {},
      el("optgroup", { label: "Catalogue (GPU)" },
        ...GRAPH_FILTERS.filter((f) => !f.cpuOnly).map((f) => el("option", { value: `g:${f.id}` }, f.name))),
      el("optgroup", { label: "Render graph nodes" },
        el("option", { value: "n:adjust.exposure" }, "Exposure"),
        el("option", { value: "n:adjust.curves" }, "Curves"),
        el("option", { value: "n:filter.blur" }, "Gaussian blur")),
      userNodes().length ? el("optgroup", { label: "Your nodes" },
        ...userNodes().map((u) => el("option", { value: `n:${u.id}` }, u.name))) : null);
    modal(el("h2", {}, "Effect on this node"),
      el("p.fine", {}, "The same nodes the other studios use. It runs over this node's own rendering, " +
        "so a blur or a glow spreads outside its box and still composites correctly."),
      pick,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", { onclick: () => {
          const v = pick.value, kind = v[0], ref = v.slice(2);
          let e;
          if (kind === "g") {
            const gf = graphFilter(ref);
            const cpu = FILTERS.find((f) => f.id === gf.cpu);
            const params = {};
            for (const [name, , , def] of (cpu ? cpu.params : [])) params[name] = def;
            for (const [name, def] of (cpu && cpu.colors) || []) params[name] = def;
            e = makeEffect("graph", ref, params);
          } else {
            const t = nodeType(ref === "filter.blur" ? "filter.blur1d" : ref);
            const params = {};
            for (const u of t.params.filter((x) => !x.hidden && x.control !== "image")) params[u.name] = u.value.slice();
            e = makeEffect("node", ref, params);
          }
          snapshot();
          n.effects = n.effects || [];
          n.effects.push(e);
          closeModal(); renderWorld(); renderInspector(); save();
        } }, "Add")));
  }

  function renderInspector() {
    clear(inspector);
    const nodes = selected();
    if (!nodes.length) {
      append(inspector,
        el("p.fine", {}, "Nothing selected. Draw a frame (F), then put things in it."),
        el("h4", {}, "Canvas"),
        el("button.ghost", { onclick: fitAll }, "Zoom to fit"));
      return;
    }
    const n = nodes[0];
    const num = (label, key, opts = {}) => el("label.design-num", {}, label,
      el("input", { type: "number", value: Math.round((n[key] ?? 0) * 100) / 100, ...opts,
        onchange: (e) => { snapshot(); n[key] = +e.target.value; renderAll(); save(); } }));

    append(inspector,
      el("div.spread", {},
        el("input", { value: n.name || n.type, style: { width: "60%" },
          onchange: (e) => { n.name = e.target.value; renderTree(); save(); } }),
        el("span.tag", {}, nodes.length > 1 ? `${nodes.length} selected` : n.type)),
      el("div.design-grid2", {}, num("X", "x"), num("Y", "y"), num("W", "w"), num("H", "h")),
      el("div.design-grid2", {}, num("Rotate", "rotation"),
        n.type === "rect" || n.type === "frame" ? num("Radius", "radius", { min: 0 }) : el("span")),

      el("h4", {}, "Appearance"),
      el("div.row.tight", {},
        n.type !== "line" ? el("label.design-num", {}, "Fill",
          el("input", { type: "color", value: n.fill && n.fill !== "none" ? n.fill : "#ffffff",
            oninput: (e) => { n.fill = e.target.value; renderWorld(); save(); } })) : null,
        el("label.design-num", {}, "Stroke",
          el("input", { type: "color", value: n.stroke || "#000000",
            oninput: (e) => { n.stroke = e.target.value; renderWorld(); save(); } })),
        num("Width", "strokeWidth", { min: 0, step: 0.5 })),
      el("label", {}, "Opacity",
        el("input", { type: "range", min: 0, max: 1, step: 0.01, value: n.opacity ?? 1,
          oninput: (e) => { n.opacity = +e.target.value; renderWorld(); },
          onchange: save })),
      n.fill && n.fill !== "none"
        ? el("button.ghost", { onclick: () => { n.fill = "none"; renderWorld(); save(); } }, "No fill")
        : null);

    if (n.type === "text") {
      append(inspector,
        el("h4", {}, "Type"),
        el("textarea", { value: n.text || "", style: { minHeight: "4em" },
          oninput: (e) => { n.text = e.target.value; renderWorld(); save(); } }),
        el("div.design-grid2", {},
          num("Size", "fontSize", { min: 4 }),
          num("Line height", "lineHeight", { step: 0.05 }),
          num("Letter sp.", "letterSpacing", { step: 0.5 }),
          el("label.design-num", {}, "Weight",
            el("select", { onchange: (e) => { n.fontWeight = +e.target.value; renderWorld(); save(); } },
              ...[300, 400, 500, 600, 700, 800].map((w) =>
                el("option", { value: w, selected: w === (n.fontWeight || 500) }, w))))),
        el("div.row.tight", {}, ...["left", "center", "right"].map((a) =>
          el("button", { class: (n.align || "left") === a ? "on" : "",
            onclick: () => { n.align = a; renderWorld(); renderInspector(); save(); } }, a))));
    }

    if (n.children) {
      const L = n.layout || (n.layout = { dir: "none", gap: 16, pad: 24, stretch: false, hug: false });
      append(inspector,
        el("h4", {}, "Auto-layout"),
        el("div.row.tight", {}, ...[["none", "Off"], ["vertical", "Stack ↓"], ["horizontal", "Row →"]]
          .map(([v, label]) => el("button", { class: L.dir === v ? "on" : "",
            onclick: () => { snapshot(); L.dir = v; renderAll(); save(); } }, label))),
        L.dir !== "none" ? el("div.design-grid2", {},
          el("label.design-num", {}, "Gap", el("input", { type: "number", value: L.gap,
            onchange: (e) => { L.gap = +e.target.value; renderAll(); save(); } })),
          el("label.design-num", {}, "Padding", el("input", { type: "number", value: L.pad,
            onchange: (e) => { L.pad = +e.target.value; renderAll(); save(); } }))) : null,
        L.dir !== "none" ? el("div.row.tight", {},
          el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
            el("input", { type: "checkbox", checked: !!L.stretch, style: { width: "auto" },
              onchange: (e) => { L.stretch = e.target.checked; renderAll(); save(); } }), "stretch"),
          el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
            el("input", { type: "checkbox", checked: !!L.hug, style: { width: "auto" },
              onchange: (e) => { L.hug = e.target.checked; renderAll(); save(); } }), "hug contents")) : null);
    }

    append(inspector, effectPanel(n));

    if (n.type === "frame" && n.grid) {
      append(inspector,
        el("h4", {}, "Layout grid"),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
          el("input", { type: "checkbox", checked: !!n.grid.on, style: { width: "auto" },
            onchange: (e) => { n.grid.on = e.target.checked; renderWorld(); save(); } }),
          "show columns"),
        el("div.design-grid2", {},
          el("label.design-num", {}, "Columns", el("input", { type: "number", min: 1, max: 24, value: n.grid.columns,
            onchange: (e) => { n.grid.columns = +e.target.value; renderWorld(); save(); } })),
          el("label.design-num", {}, "Gutter", el("input", { type: "number", value: n.grid.gutter,
            onchange: (e) => { n.grid.gutter = +e.target.value; renderWorld(); save(); } })),
          el("label.design-num", {}, "Margin", el("input", { type: "number", value: n.grid.margin,
            onchange: (e) => { n.grid.margin = +e.target.value; renderWorld(); save(); } }))),
        el("p.fine", {}, "A modular grid is the thing the composition lesson is " +
          "about. Turn it on and put every edge on a column."));
    }

    append(inspector,
      el("h4", {}, "Arrange"),
      el("div.row.tight", {},
        el("button.ghost", { onclick: () => reorder(1) }, "Bring forward"),
        el("button.ghost", { onclick: () => reorder(-1) }, "Send back")),
      el("div.row.tight", {},
        el("button.ghost.danger", { onclick: removeSelected }, "Delete")));
  }

  function reorder(dir) {
    const id = selection[0];
    if (!id) return;
    const list = siblingsOf(id);
    const i = list.findIndex((n) => n.id === id);
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    snapshot();
    [list[i], list[j]] = [list[j], list[i]];
    renderAll(); save();
  }

  function fitAll() {
    const boxes = doc.nodes.map(absolute);
    if (!boxes.length) return;
    const x = Math.min(...boxes.map((b) => b.x)), y = Math.min(...boxes.map((b) => b.y));
    const x2 = Math.max(...boxes.map((b) => b.x + b.w)), y2 = Math.max(...boxes.map((b) => b.y + b.h));
    const r = surface.getBoundingClientRect();
    view.zoom = Math.min(8, Math.max(0.05, Math.min(r.width / (x2 - x + 120), r.height / (y2 - y + 120))));
    view.x = -x * view.zoom + (r.width - (x2 - x) * view.zoom) / 2;
    view.y = -y * view.zoom + (r.height - (y2 - y) * view.zoom) / 2;
    applyViewport(); renderOverlay();
  }

  // ---------------------------------------------------------------- export

  function frameSvg(node) {
    const a = absolute(node);
    const out = svg("svg", { xmlns: SVGNS, width: a.w, height: a.h,
                             viewBox: `0 0 ${a.w} ${a.h}` });
    const g = paintNode(node);
    g.setAttribute("transform", "translate(0 0)");
    out.append(g);
    return out;
  }

  function exportSvg() {
    const node = selected().find((n) => n.type === "frame") || doc.nodes.find((n) => n.type === "frame");
    if (!node) { toast("Nothing to export — make a frame first"); return; }
    const text = new XMLSerializer().serializeToString(frameSvg(node));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
    a.download = `${node.name || "frame"}.svg`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /** The frame as a Generate sketch: every shape an SDF, opened as a new
      shader document. One way — the design stays the vector source. */
  async function openAsShader() {
    const node = selected().find((n) => n.type === "frame") || doc.nodes.find((n) => n.type === "frame");
    if (!node) { toast("Nothing to compile — make a frame first"); return; }
    let out;
    toast("Compiling shapes and glyphs…");
    try { out = await compileDesignFrame(node); }
    catch (e) { toast(`Could not compile: ${e.message}`); return; }
    const preview = fitPreview(out.width, out.height);
    const made = await api("/api/studio/projects", { method: "POST",
      body: { kind: "generate", name: `${node.name || "frame"} (shader)`,
              data: { sketch: out.source, preset: "", uniforms: {}, seed: 0, mode: "sketch",
                      preview, exportSize: [out.width - (out.width % 2), out.height - (out.height % 2)],
                      simSteps: 1, from: { design: host.doc.id, frame: node.id } } } });
    toast(`${out.shapes} shape${out.shapes === 1 ? "" : "s"} compiled` +
          (out.notes.length ? ` — ${out.notes[0]}` : "") + ". Opening…");
    location.hash = `#studio/generate/${made.id}`;
  }

  async function exportPng(scale = 2) {
    const node = selected().find((n) => n.type === "frame") || doc.nodes.find((n) => n.type === "frame");
    if (!node) { toast("Nothing to export — make a frame first"); return; }
    const text = new XMLSerializer().serializeToString(frameSvg(node));
    const img = new Image();
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
    const c = document.createElement("canvas");
    c.width = node.w * scale; c.height = node.h * scale;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0, c.width, c.height);
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = `${node.name || "frame"}@${scale}x.png`;
    a.click();
  }

  function thumbnail() {
    try {
      const node = doc.nodes.find((n) => n.type === "frame");
      if (!node) return "";
      const text = new XMLSerializer().serializeToString(frameSvg(node));
      return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
    } catch { return ""; }
  }

  // ---------------------------------------------------------------- chrome

  const zoomLabel = el("span.fine", {}, "50%");
  const toolRow = el("div.row.tight", {}, ...TOOLS.map(([id, label, key]) =>
    el("button", { class: id === tool ? "on" : "", "data-tool": id, title: `${label} (${key})`,
      onclick: () => setTool(id) }, label)));

  function setTool(t) {
    tool = t;
    toolRow.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
    surface.style.cursor = t === "select" ? "default" : "crosshair";
  }

  function addFramePreset() {
    const sel = el("select", {}, ...FRAME_PRESETS.map(([n, w, h]) =>
      el("option", { value: n }, `${n} — ${w}×${h}`)));
    modal(el("h2", {}, "New frame"), el("label", {}, "Preset", sel),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: () => {
            const p = FRAME_PRESETS.find((f) => f[0] === sel.value);
            snapshot();
            const far = doc.nodes.reduce((m, n) => Math.max(m, n.x + n.w), 0);
            doc.nodes.push({ id: nextId(), type: "frame", name: p[0],
              x: far + 80, y: 0, w: p[1], h: p[2], fill: "#ffffff", visible: true,
              children: [], grid: { on: false, columns: 12, gutter: 24, margin: 64 } });
            closeModal(); renderAll(); save(); fitAll();
          },
        }, "Add")));
  }

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        toolRow,
        el("button.ghost", { onclick: addFramePreset }, "+ Frame"),
        el("button.ghost", { onclick: () => restore(undo, redo) }, "Undo"),
        el("button.ghost", { onclick: () => restore(redo, undo) }, "Redo"),
        el("button.ghost", { onclick: fitAll }, "Fit"),
        fs.button,
        zoomLabel,
        el("button.ghost", { onclick: exportSvg }, "SVG"),
        el("button.ghost", { onclick: () => exportPng(2) }, "PNG @2x"),
        el("button.ghost", { onclick: openAsShader,
          title: "Compile this frame to a shader: every shape becomes a signed-distance function" }, "Shader"),
        aiButton("Layout ideas…", {
          task: "brief",
          describe: "The model proposes structure in words — hierarchy, grid, " +
            "what goes where. You build it. It never sees your canvas.",
          placeholder: "e.g. landing page for a modular synth, Swiss grid, one " +
            "hero image, three feature blocks",
          onResult: (res) => modal(el("h2", {}, "Layout notes"),
            el("p.dim", { style: { whiteSpace: "pre-wrap" } }, res.text),
            el("div.row", { style: { justifyContent: "flex-end" } },
              el("button.primary", { onclick: closeModal }, "Close"))),
        })),
      el("div.row.tight", { style: { marginTop: ".4rem" } },
        el("span.fine", {}, "align"),
        ...[["left", "⇤"], ["hcenter", "↔"], ["right", "⇥"], ["top", "⇧"],
            ["vcenter", "↕"], ["bottom", "⇩"], ["hdist", "⇹"], ["vdist", "⇳"]]
          .map(([how, glyph]) => el("button.ghost", { title: how, onclick: () => align(how) }, glyph)),
        el("span.fine", {}, "· ⌘G group · ⌘D duplicate · ⌥drag pan · scroll zoom"))),

    el("div.design-split", {},
      el("div.card.tight.design-panel", {}, el("h4", {}, "Layers"), tree),
      wrap,
      el("div.card.tight.design-panel", {}, inspector)));

  // Tear the key handler down with the view, or it fires on every other tab.
  root._cleanup = () => document.removeEventListener("keydown", onKey);

  setTimeout(() => { applyViewport(); renderAll(); }, 0);
  renderAll();
  return root;
}
