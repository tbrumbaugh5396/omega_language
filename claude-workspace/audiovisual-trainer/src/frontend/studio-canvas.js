// The canvas editor: layers with masks, selections, free transform, editable
// text, and the Part 10 effects catalogue as a filter menu.
//
// Layers are real offscreen canvases composited with the browser's own blend
// modes, which are the Porter-Duff operators the compositing lesson is about.
// Filters run through engine-image, so the thing you apply here is the same
// code the drills generate their stimuli with.
//
// Three structural decisions worth knowing:
//
//   · Everything destructive goes through the selection mask. Drawing,
//     filters, delete and transform all clip through one code path, so a
//     selection means the same thing to every tool.
//   · A stroke accumulates into a scratch canvas at full alpha and is
//     composited once on release. That is what makes brush opacity apply to
//     the stroke rather than to every stamp, which is the behaviour anyone
//     coming from a real paint program expects.
//   · Text layers stay text. They re-render from their properties on every
//     edit and only become pixels when you ask them to.

import { el, clear, append, toast, modal, closeModal, knob, confirmDialog, api } from "./ui.js";
import * as I from "./engine-image.js";
import { Selection, wandMask } from "./canvas-selection.js";
import { aiButton } from "./ai.js";
import { gridOverlay } from "./grid-overlay.js";
import { GENERATE_PRESETS } from "./studio-generate.js";
import { renderSketch, sketchUniforms } from "./shader-run.js";
import { buildControls } from "./shader-controls.js";

const BLEND_MODES = ["source-over", "multiply", "screen", "overlay", "darken",
  "lighten", "color-dodge", "color-burn", "hard-light", "soft-light",
  "difference", "exclusion", "hue", "saturation", "color", "luminosity"];

const TOOL_GROUPS = [
  ["Select", [["marquee", "Rect"], ["ellipseSel", "Ellipse"], ["lasso", "Lasso"],
              ["wand", "Wand"], ["move", "Move"]]],
  ["Paint", [["brush", "Brush"], ["eraser", "Eraser"], ["fill", "Fill"],
             ["pick", "Pick"]]],
  ["Shape", [["line", "Line"], ["rect", "Rect"], ["ellipse", "Ellipse"],
             ["text", "Text"]]],
];
const ALL_TOOLS = TOOL_GROUPS.flatMap(([, t]) => t.map(([id]) => id));
const SELECT_TOOLS = ["marquee", "ellipseSel", "lasso", "wand"];

const loadImage = (src) => new Promise((res) => {
  if (!src) return res(null);
  const img = new Image();
  img.onload = () => res(img);
  img.onerror = () => res(null);
  img.src = src;
});

export async function canvasEditor(host) {
  const doc = host.data;
  const W = doc.width, H = doc.height;

  // ------------------------------------------------------------ layer model

  async function hydrate(stored) {
    const c = I.makeCanvas(W, H);
    const img = await loadImage(stored.data);
    if (img) I.ctx2d(c).drawImage(img, 0, 0);
    const layer = {
      id: stored.id, name: stored.name, visible: stored.visible !== false,
      opacity: stored.opacity ?? 1, blend: stored.blend || "source-over",
      type: stored.type || "raster",
      text: stored.text ? { ...stored.text } : null,
      canvas: c, ctx: I.ctx2d(c),
      maskCanvas: null, maskCtx: null,
      cache: I.makeCanvas(W, H), dirty: true,
    };
    if (stored.mask) {
      const m = await loadImage(stored.mask);
      layer.maskCanvas = I.makeCanvas(W, H);
      layer.maskCtx = I.ctx2d(layer.maskCanvas);
      if (m) layer.maskCtx.drawImage(m, 0, 0);
    }
    if (layer.type === "text") renderTextLayer(layer);
    return layer;
  }

  const layers = [];
  for (const l of doc.layers) layers.push(await hydrate(l));
  let active = 0;
  const L = () => layers[active];

  function renderTextLayer(layer) {
    const t = layer.text || {};
    const g = layer.ctx;
    g.clearRect(0, 0, W, H);
    g.save();
    g.fillStyle = t.color || "#111111";
    g.font = `${t.weight || 600} ${t.size || 72}px ${t.family || "system-ui, sans-serif"}`;
    g.textBaseline = "alphabetic";
    g.textAlign = t.align || "left";
    const lh = (t.lineHeight || 1.25) * (t.size || 72);
    const lines = String(t.text ?? "").split("\n");
    lines.forEach((line, i) => {
      if (t.letterSpacing) {
        // Canvas has no letter-spacing, so lay the glyphs out by hand.
        let x = t.x;
        const total = [...line].reduce((s, ch) => s + g.measureText(ch).width + t.letterSpacing, 0);
        if (t.align === "center") x -= total / 2;
        else if (t.align === "right") x -= total;
        const prev = g.textAlign;
        g.textAlign = "left";
        for (const ch of line) {
          g.fillText(ch, x, t.y + i * lh);
          x += g.measureText(ch).width + t.letterSpacing;
        }
        g.textAlign = prev;
      } else {
        g.fillText(line, t.x, t.y + i * lh);
      }
    });
    g.restore();
    layer.dirty = true;
  }

  /** The layer as it participates in the composite: pixels through its mask. */
  function surface(layer) {
    if (!layer.maskCanvas) return layer.canvas;
    if (layer.dirty) {
      const g = I.ctx2d(layer.cache);
      g.clearRect(0, 0, W, H);
      g.drawImage(layer.canvas, 0, 0);
      g.save();
      g.globalCompositeOperation = "destination-in";
      g.drawImage(layer.maskCanvas, 0, 0);
      g.restore();
      layer.dirty = false;
    }
    return layer.cache;
  }

  // ------------------------------------------------------------ state

  const sel = new Selection(W, H);
  const state = {
    tool: "brush", color: "#e8ebf5", size: 18, opacity: 1, hardness: 0.8,
    tolerance: 32, feather: 0, contiguous: true, zoom: 1, editingMask: false,
    fontSize: 72,
  };
  const swatches = ["#e8ebf5", "#0d0f18", "#7c9cff", "#f0a35e", "#6ee7c8",
                    "#f2708a", "#5fd39a"];
  let transform = null;
  let antsOffset = 0;

  // ------------------------------------------------------------ history
  //
  // Snapshots carry whichever surfaces an operation can touch. Pixels are the
  // expensive part, so the stack is short and only stores what changed.

  const undo = [], redo = [];
  function snapshot(kind = "pixels") {
    undo.push(captureState(kind));
    if (undo.length > 18) undo.shift();
    redo.length = 0;
  }
  function captureState(kind) {
    const l = L();
    return {
      kind, index: active,
      pixels: kind === "selection" ? null : I.getImage(l.canvas),
      mask: l.maskCanvas ? I.getImage(l.maskCanvas) : null,
      text: l.text ? { ...l.text } : null,
      selection: sel.active ? I.getImage(sel.canvas) : null,
      selActive: sel.active,
    };
  }
  function applyState(s) {
    const l = layers[s.index] || L();
    if (s.pixels) I.putImage(l.canvas, s.pixels);
    if (s.mask && l.maskCanvas) I.putImage(l.maskCanvas, s.mask);
    if (s.text) l.text = { ...s.text };
    if (s.selActive && s.selection) {
      I.putImage(sel.canvas, s.selection);
      sel.active = true;
      sel.retrace();
    } else {
      sel.clear();
    }
    l.dirty = true;
  }
  function step(from, to) {
    const s = from.pop();
    if (!s) return;
    to.push(captureState(s.kind));
    applyState(s);
    render(); renderPanels(); persist();
  }

  // ------------------------------------------------------------ view

  const view = el("canvas", { width: W, height: H, style: { display: "block" } });
  const overlay = el("canvas", { width: W, height: H,
    style: { display: "block", position: "absolute", inset: 0, pointerEvents: "none" } });
  const vg = view.getContext("2d");
  const og = overlay.getContext("2d");

  const grid = gridOverlay();
  const stage = el("div", { style: { position: "relative", lineHeight: 0 } }, view, overlay, grid.overlay);

  let strokeCanvas = null, strokeCtx = null;

  function render() {
    vg.save();
    vg.globalCompositeOperation = "source-over";
    vg.globalAlpha = 1;
    vg.fillStyle = doc.background || "#ffffff";
    vg.fillRect(0, 0, W, H);
    for (const l of layers) {
      if (!l.visible) continue;
      vg.globalAlpha = l.opacity;
      vg.globalCompositeOperation = l.blend || "source-over";

      if (l === L() && strokeCanvas && !state.editingMask) {
        // Preview the in-progress stroke composited into this layer, so what
        // you see during the stroke is what lands when you let go.
        const tmp = I.makeCanvas(W, H);
        const tg = I.ctx2d(tmp);
        tg.drawImage(surface(l), 0, 0);
        const clipped = sel.clip(copyOf(strokeCanvas));
        tg.globalAlpha = state.opacity;
        tg.globalCompositeOperation = state.tool === "eraser" ? "destination-out" : "source-over";
        tg.drawImage(clipped, 0, 0);
        vg.drawImage(tmp, 0, 0);
      } else if (l === L() && transform) {
        const tmp = I.makeCanvas(W, H);
        const tg = I.ctx2d(tmp);
        tg.drawImage(surface(l), 0, 0);
        drawTransform(tg);
        vg.drawImage(tmp, 0, 0);
      } else {
        vg.drawImage(surface(l), 0, 0);
      }
    }
    vg.restore();
    renderOverlay();
  }

  const copyOf = (c) => {
    const n = I.makeCanvas(c.width, c.height);
    I.ctx2d(n).drawImage(c, 0, 0);
    return n;
  };

  function effZoom() {
    return (view.clientWidth || W) / W;
  }

  function renderOverlay() {
    og.clearRect(0, 0, W, H);
    const z = effZoom();
    sel.drawAnts(og, z, antsOffset);
    if (transform) drawTransformHandles(og, z);
    if (state.editingMask && L().maskCanvas) {
      og.save();
      og.strokeStyle = "#f0a35e";
      og.lineWidth = 3 / z;
      og.strokeRect(0, 0, W, H);
      og.restore();
    }
  }

  // Ants animate only while a selection exists, and stop when it does not.
  let antsTimer = setInterval(() => {
    if (!sel.active) return;
    antsOffset = (antsOffset + 1) % 8;
    renderOverlay();
  }, 90);

  // ------------------------------------------------------------ persistence

  let persistTimer = null;
  function persist() {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
      doc.layers = layers.map((l) => ({
        id: l.id, name: l.name, visible: l.visible, opacity: l.opacity,
        blend: l.blend, type: l.type,
        text: l.text ? { ...l.text } : null,
        data: l.canvas.toDataURL("image/png"),
        mask: l.maskCanvas ? l.maskCanvas.toDataURL("image/png") : null,
      }));
      host.save(thumbnail());
    }, 450);
  }
  function thumbnail() {
    const t = I.makeCanvas(240, Math.max(1, Math.round((240 * H) / W)));
    I.ctx2d(t).drawImage(view, 0, 0, t.width, t.height);
    return t.toDataURL("image/jpeg", 0.7);
  }

  // ------------------------------------------------------------ drawing

  function pos(e) {
    const r = view.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
  }

  /** Where a paint stroke lands: the mask when editing it, else the layer. */
  const paintTarget = () => (state.editingMask && L().maskCanvas)
    ? { canvas: L().maskCanvas, ctx: L().maskCtx } : { canvas: L().canvas, ctx: L().ctx };

  function stamp(g, x, y) {
    const r = state.size / 2;
    const col = state.editingMask
      ? (state.tool === "eraser" ? "#000000" : "#ffffff")
      : state.color;
    if (state.hardness >= 0.99) {
      g.fillStyle = col;
      g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
      return;
    }
    const grad = g.createRadialGradient(x, y, r * state.hardness, x, y, r);
    grad.addColorStop(0, col);
    grad.addColorStop(1, col + "00");
    g.fillStyle = grad;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  }

  let drag = null;

  view.parentElement.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const [x, y] = pos(e);
    const l = L();

    if (transform) {
      const h = transformHandleAt(x, y);
      if (h !== null) {
        drag = { mode: "transform", handle: h, ox: x, oy: y, start: { ...transform } };
        return;
      }
      // Clicking away commits — and consumes the click. Letting it fall
      // through would start a brush stroke or a marquee with the same press,
      // which is never what committing a transform is meant to do.
      commitTransform();
      return;
    }

    if (state.tool === "pick") {
      const d = vg.getImageData(Math.round(x), Math.round(y), 1, 1).data;
      setColor(I.hex(d[0], d[1], d[2]));
      return;
    }
    if (!l.visible) { toast("That layer is hidden"); return; }

    // ---- selection tools
    if (SELECT_TOOLS.includes(state.tool)) {
      const mode = e.altKey ? "subtract" : e.shiftKey ? "add" : "replace";
      if (state.tool === "wand") {
        snapshot("selection");
        const src = state.editingMask && l.maskCanvas ? l.maskCanvas : l.canvas;
        const m = wandMask(src, x, y, state.tolerance, state.contiguous);
        sel.setFrom((g) => g.drawImage(m, 0, 0), mode);
        if (state.feather) sel.feather(state.feather);
        render(); renderPanels(); persist();
        return;
      }
      drag = { mode: "select", kind: state.tool, ox: x, oy: y, points: [[x, y]], selMode: mode };
      return;
    }

    if (l.type === "text" && !state.editingMask) {
      toast("This is a text layer — edit it in the panel, or rasterise it to paint");
      return;
    }

    if (state.tool === "text") { textDialog(x, y); return; }

    if (state.tool === "move") {
      snapshot();
      drag = { mode: "movepixels", ox: x, oy: y,
               lifted: liftSelection(), origin: [x, y] };
      return;
    }

    if (state.tool === "fill") {
      snapshot();
      floodFill(paintTarget(), x, y);
      L().dirty = true;
      render(); persist();
      return;
    }

    snapshot();
    drag = { mode: "paint", ox: x, oy: y, last: [x, y] };
    strokeCanvas = I.makeCanvas(W, H);
    strokeCtx = I.ctx2d(strokeCanvas);
    if (state.tool === "brush" || state.tool === "eraser") stamp(strokeCtx, x, y);
    render();
  });

  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const [x, y] = pos(e);

    if (drag.mode === "paint") {
      if (state.tool === "brush" || state.tool === "eraser") {
        const dist = Math.hypot(x - drag.last[0], y - drag.last[1]);
        const stepPx = Math.max(1, state.size * 0.18);
        for (let d = 0; d <= dist; d += stepPx) {
          const t = dist ? d / dist : 0;
          stamp(strokeCtx, drag.last[0] + (x - drag.last[0]) * t,
                           drag.last[1] + (y - drag.last[1]) * t);
        }
        drag.last = [x, y];
      } else {
        strokeCtx.clearRect(0, 0, W, H);
        strokeCtx.save();
        strokeCtx.fillStyle = state.editingMask ? "#fff" : state.color;
        strokeCtx.strokeStyle = strokeCtx.fillStyle;
        strokeCtx.lineWidth = state.size;
        strokeCtx.lineCap = "round";
        strokeCtx.beginPath();
        if (state.tool === "line") {
          strokeCtx.moveTo(drag.ox, drag.oy); strokeCtx.lineTo(x, y); strokeCtx.stroke();
        } else if (state.tool === "rect") {
          strokeCtx.fillRect(drag.ox, drag.oy, x - drag.ox, y - drag.oy);
        } else {
          strokeCtx.ellipse((drag.ox + x) / 2, (drag.oy + y) / 2,
            Math.abs(x - drag.ox) / 2, Math.abs(y - drag.oy) / 2, 0, 0, Math.PI * 2);
          strokeCtx.fill();
        }
        strokeCtx.restore();
      }
      render();
      return;
    }

    if (drag.mode === "select") {
      const paint = (g) => {
        if (drag.kind === "marquee") {
          g.fillRect(Math.min(drag.ox, x), Math.min(drag.oy, y),
                     Math.abs(x - drag.ox), Math.abs(y - drag.oy));
        } else if (drag.kind === "ellipseSel") {
          g.beginPath();
          g.ellipse((drag.ox + x) / 2, (drag.oy + y) / 2,
                    Math.abs(x - drag.ox) / 2, Math.abs(y - drag.oy) / 2, 0, 0, Math.PI * 2);
          g.fill();
        } else {
          drag.points.push([x, y]);
          g.beginPath();
          g.moveTo(drag.points[0][0], drag.points[0][1]);
          for (const [px, py] of drag.points) g.lineTo(px, py);
          g.closePath();
          g.fill();
        }
      };
      // Live preview replaces each move; the committed mode applies on release.
      sel.setFrom(paint, drag.selMode === "replace" ? "replace" : drag.selMode);
      renderOverlay();
      return;
    }

    if (drag.mode === "movepixels" && drag.lifted) {
      drag.lifted.dx = x - drag.origin[0];
      drag.lifted.dy = y - drag.origin[1];
      render();
      return;
    }

    if (drag.mode === "transform") {
      updateTransform(drag, x, y, e.shiftKey);
      render();
    }
  });

  window.addEventListener("pointerup", () => {
    if (!drag) return;

    if (drag.mode === "paint") {
      const { ctx: tctx } = paintTarget();
      const clipped = sel.clip(strokeCanvas);
      tctx.save();
      tctx.globalAlpha = state.opacity;
      tctx.globalCompositeOperation =
        state.tool === "eraser" && !state.editingMask ? "destination-out" : "source-over";
      if (state.editingMask && state.tool === "eraser") {
        tctx.globalCompositeOperation = "destination-out";
      }
      tctx.drawImage(clipped, 0, 0);
      tctx.restore();
      strokeCanvas = strokeCtx = null;
      L().dirty = true;
      persist();
    } else if (drag.mode === "select") {
      if (state.feather) sel.feather(state.feather);
      sel.retrace();
      persist();
    } else if (drag.mode === "movepixels" && drag.lifted) {
      dropLifted(drag.lifted);
      persist();
    } else if (drag.mode === "transform") {
      persist();
    }
    drag = null;
    render(); renderPanels();
  });

  // ------------------------------------------------------------ move / lift

  /** Cut the selected pixels out of the layer so they can be dragged. */
  function liftSelection() {
    const l = L();
    if (l.type === "text") return null;
    const src = copyOf(l.canvas);
    if (sel.active) sel.clip(src);
    // Remove them from the layer: everything inside the selection goes.
    if (sel.active) {
      l.ctx.save();
      l.ctx.globalCompositeOperation = "destination-out";
      l.ctx.drawImage(sel.canvas, 0, 0);
      l.ctx.restore();
    } else {
      l.ctx.clearRect(0, 0, W, H);
    }
    l.dirty = true;
    return { canvas: src, dx: 0, dy: 0 };
  }

  function dropLifted(lifted) {
    const l = L();
    l.ctx.drawImage(lifted.canvas, lifted.dx, lifted.dy);
    l.dirty = true;
    // The selection travels with the pixels, the way it does everywhere else.
    if (sel.active && (lifted.dx || lifted.dy)) {
      const moved = I.makeCanvas(W, H);
      I.ctx2d(moved).drawImage(sel.canvas, lifted.dx, lifted.dy);
      sel.ctx.clearRect(0, 0, W, H);
      sel.ctx.drawImage(moved, 0, 0);
      sel.retrace();
    }
  }

  // ------------------------------------------------------------ transform

  function beginTransform() {
    if (transform) return;
    const l = L();
    if (l.type === "text") { toast("Rasterise the text layer first"); return; }
    snapshot();
    const src = copyOf(l.canvas);
    if (sel.active) sel.clip(src);
    const b = sel.active ? sel.bounds() : { x: 0, y: 0, w: W, h: H };
    if (!b) { toast("Nothing selected"); return; }
    const cropped = I.makeCanvas(b.w, b.h);
    I.ctx2d(cropped).drawImage(src, -b.x, -b.y);
    if (sel.active) {
      l.ctx.save();
      l.ctx.globalCompositeOperation = "destination-out";
      l.ctx.drawImage(sel.canvas, 0, 0);
      l.ctx.restore();
    } else l.ctx.clearRect(0, 0, W, H);
    l.dirty = true;
    transform = { src: cropped, cx: b.x + b.w / 2, cy: b.y + b.h / 2,
                  w: b.w, h: b.h, angle: 0 };
    render(); renderPanels();
  }

  function drawTransform(g) {
    const t = transform;
    g.save();
    g.translate(t.cx, t.cy);
    g.rotate(t.angle);
    g.drawImage(t.src, -t.w / 2, -t.h / 2, t.w, t.h);
    g.restore();
  }

  const transformCorners = () => {
    const t = transform;
    const c = Math.cos(t.angle), s = Math.sin(t.angle);
    const hw = t.w / 2, hh = t.h / 2;
    return [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]]
      .map(([x, y]) => [t.cx + x * c - y * s, t.cy + x * s + y * c]);
  };

  function drawTransformHandles(g, z) {
    const pts = transformCorners();
    g.save();
    g.strokeStyle = "#7c9cff";
    g.lineWidth = 1.5 / z;
    g.beginPath();
    pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    g.closePath();
    g.stroke();
    const r = 5 / z;
    g.fillStyle = "#0d0f18";
    for (const [x, y] of pts) {
      g.beginPath(); g.rect(x - r, y - r, r * 2, r * 2); g.fill(); g.stroke();
    }
    // rotate handle, off the top edge
    const [tl, tr] = pts;
    const mx = (tl[0] + tr[0]) / 2, my = (tl[1] + tr[1]) / 2;
    const nx = Math.sin(transform.angle), ny = -Math.cos(transform.angle);
    const rx = mx + nx * 28 / z, ry = my + ny * 28 / z;
    g.beginPath(); g.moveTo(mx, my); g.lineTo(rx, ry); g.stroke();
    g.beginPath(); g.arc(rx, ry, r, 0, Math.PI * 2); g.fill(); g.stroke();
    g.restore();
  }

  function transformHandleAt(x, y) {
    if (!transform) return null;
    const z = effZoom();
    const tol = 9 / z;
    const pts = transformCorners();
    for (let i = 0; i < 4; i++) {
      if (Math.hypot(x - pts[i][0], y - pts[i][1]) <= tol) return i;
    }
    const [tl, tr] = pts;
    const mx = (tl[0] + tr[0]) / 2, my = (tl[1] + tr[1]) / 2;
    const nx = Math.sin(transform.angle), ny = -Math.cos(transform.angle);
    if (Math.hypot(x - (mx + nx * 28 / z), y - (my + ny * 28 / z)) <= tol) return "rotate";
    // inside the box: translate
    const c = Math.cos(-transform.angle), s = Math.sin(-transform.angle);
    const lx = (x - transform.cx) * c - (y - transform.cy) * s;
    const ly = (x - transform.cx) * s + (y - transform.cy) * c;
    if (Math.abs(lx) <= transform.w / 2 && Math.abs(ly) <= transform.h / 2) return "move";
    return null;
  }

  function updateTransform(d, x, y, keepRatio) {
    const t = transform, s = d.start;
    if (d.handle === "move") {
      t.cx = s.cx + (x - d.ox); t.cy = s.cy + (y - d.oy);
      return;
    }
    if (d.handle === "rotate") {
      t.angle = Math.atan2(y - s.cy, x - s.cx) + Math.PI / 2;
      return;
    }
    // Corner scale, measured against the opposite corner so it stays anchored.
    const c = Math.cos(-s.angle), sn = Math.sin(-s.angle);
    const lx = (x - s.cx) * c - (y - s.cy) * sn;
    const ly = (x - s.cx) * sn + (y - s.cy) * c;
    let nw = Math.abs(lx) * 2, nh = Math.abs(ly) * 2;
    if (keepRatio && s.w && s.h) {
      const r = s.w / s.h;
      if (nw / nh > r) nh = nw / r; else nw = nh * r;
    }
    t.w = Math.max(2, nw);
    t.h = Math.max(2, nh);
  }

  function commitTransform() {
    if (!transform) return;
    const l = L();
    drawTransform(l.ctx);
    l.dirty = true;
    transform = null;
    render(); renderPanels(); persist();
  }
  function cancelTransform() {
    if (!transform) return;
    const l = L();
    // Put the pixels back where they came from.
    l.ctx.drawImage(transform.src, transform.cx - transform.w / 2,
                    transform.cy - transform.h / 2);
    l.dirty = true;
    transform = null;
    render(); renderPanels();
  }

  // ------------------------------------------------------------ fill / text

  function floodFill(target, x0, y0) {
    const img = I.getImage(target.canvas);
    const d = img.data;
    const x = Math.round(x0), y = Math.round(y0);
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const at = (px, py) => (py * W + px) * 4;
    const s = at(x, y);
    const target4 = [d[s], d[s + 1], d[s + 2], d[s + 3]];
    const col = state.editingMask ? "#ffffff" : state.color;
    const fill = [parseInt(col.slice(1, 3), 16), parseInt(col.slice(3, 5), 16),
                  parseInt(col.slice(5, 7), 16), 255];
    const tol = state.tolerance;
    const close = (i) => Math.abs(d[i] - target4[0]) <= tol &&
      Math.abs(d[i + 1] - target4[1]) <= tol &&
      Math.abs(d[i + 2] - target4[2]) <= tol &&
      Math.abs(d[i + 3] - target4[3]) <= tol;
    if (close(s) && fill.every((v, k) => v === target4[k])) return;

    const seen = new Uint8Array(W * H);
    const stack = [[x, y]];
    while (stack.length) {
      const [sx, sy] = stack.pop();
      let lx = sx;
      while (lx > 0 && close(at(lx - 1, sy))) lx--;
      let rx = sx;
      while (rx < W - 1 && close(at(rx + 1, sy))) rx++;
      for (let px = lx; px <= rx; px++) {
        const i = at(px, sy);
        if (seen[sy * W + px]) continue;
        d[i] = fill[0]; d[i + 1] = fill[1]; d[i + 2] = fill[2]; d[i + 3] = fill[3];
        seen[sy * W + px] = 1;
        for (const ny of [sy - 1, sy + 1]) {
          if (ny < 0 || ny >= H) continue;
          if (!seen[ny * W + px] && close(at(px, ny))) stack.push([px, ny]);
        }
      }
    }
    // The fill honours the selection like everything else.
    const scratch = I.makeCanvas(W, H);
    I.putImage(scratch, img);
    if (sel.active) {
      const before = I.makeCanvas(W, H);
      I.ctx2d(before).drawImage(target.canvas, 0, 0);
      sel.clip(scratch);
      target.ctx.clearRect(0, 0, W, H);
      target.ctx.drawImage(before, 0, 0);
      target.ctx.drawImage(scratch, 0, 0);
    } else {
      I.putImage(target.canvas, img);
    }
  }

  function textDialog(x, y, existing = null) {
    const t = existing || { text: "Text", size: state.fontSize, weight: 600,
      color: state.color, align: "left", lineHeight: 1.25, letterSpacing: 0,
      family: "system-ui, sans-serif", x, y };
    const body = el("textarea", { value: t.text, style: { minHeight: "5em" } });
    const size = el("input", { type: "number", value: t.size, min: 6, max: 800 });
    const weight = el("select", {}, ...[300, 400, 500, 600, 700, 800].map((w) =>
      el("option", { value: w, selected: w === t.weight }, w)));
    const lh = el("input", { type: "number", value: t.lineHeight, step: 0.05 });
    const ls = el("input", { type: "number", value: t.letterSpacing, step: 0.5 });
    const colour = el("input", { type: "color", value: t.color });
    const align = el("select", {}, ...["left", "center", "right"].map((a) =>
      el("option", { value: a, selected: a === t.align }, a)));

    modal(el("h2", {}, existing ? "Edit text" : "Text"),
      el("p.fine", {}, "Text layers stay editable. They only become pixels when " +
        "you rasterise them, and painting on one is what asks you to."),
      body,
      el("div.design-grid2", {},
        el("label.design-num", {}, "Size", size),
        el("label.design-num", {}, "Weight", weight),
        el("label.design-num", {}, "Line height", lh),
        el("label.design-num", {}, "Letter spacing", ls),
        el("label.design-num", {}, "Colour", colour),
        el("label.design-num", {}, "Align", align)),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: () => {
            const next = { ...t, text: body.value, size: +size.value || 72,
              weight: +weight.value, lineHeight: +lh.value || 1.25,
              letterSpacing: +ls.value || 0, color: colour.value, align: align.value };
            if (existing) {
              snapshot("text");
              L().text = next;
              renderTextLayer(L());
            } else {
              snapshot("layer");
              const id = Math.max(0, ...layers.map((l) => l.id)) + 1;
              const c = I.makeCanvas(W, H);
              const layer = { id, name: next.text.slice(0, 18) || "Text",
                visible: true, opacity: 1, blend: "source-over", type: "text",
                text: next, canvas: c, ctx: I.ctx2d(c), maskCanvas: null,
                maskCtx: null, cache: I.makeCanvas(W, H), dirty: true };
              layers.push(layer);
              active = layers.length - 1;
              renderTextLayer(layer);
            }
            state.fontSize = +size.value || 72;
            closeModal();
            render(); renderPanels(); persist();
          },
        }, existing ? "Update" : "Place")));
  }

  function rasterizeText() {
    const l = L();
    if (l.type !== "text") return;
    snapshot("layer");
    l.type = "raster";
    l.text = null;
    renderPanels(); persist();
    toast("Rasterised — it is pixels now");
  }

  // ------------------------------------------------------------ masks

  function addMask(fromSelection = false) {
    const l = L();
    if (l.maskCanvas) { toast("This layer already has a mask"); return; }
    snapshot("layer");
    l.maskCanvas = I.makeCanvas(W, H);
    l.maskCtx = I.ctx2d(l.maskCanvas);
    if (fromSelection && sel.active) {
      l.maskCtx.drawImage(sel.canvas, 0, 0);
    } else {
      l.maskCtx.fillStyle = "#fff";
      l.maskCtx.fillRect(0, 0, W, H);
    }
    l.dirty = true;
    state.editingMask = true;
    render(); renderPanels(); persist();
    toast("Mask added. Paint black to hide, white to reveal.");
  }
  function removeMask(apply) {
    const l = L();
    if (!l.maskCanvas) return;
    snapshot("layer");
    if (apply) {
      const baked = copyOf(surface(l));
      l.ctx.clearRect(0, 0, W, H);
      l.ctx.drawImage(baked, 0, 0);
    }
    l.maskCanvas = l.maskCtx = null;
    l.dirty = true;
    state.editingMask = false;
    render(); renderPanels(); persist();
  }

  // ------------------------------------------------------------ selection ops

  const selOps = {
    all: () => { snapshot("selection"); sel.selectAll(); render(); renderPanels(); },
    none: () => { snapshot("selection"); sel.clear(); render(); renderPanels(); },
    invert: () => { snapshot("selection"); sel.invert(); render(); renderPanels(); },
    deleteInside: () => {
      const l = L();
      if (l.type === "text") { toast("Rasterise the text layer first"); return; }
      snapshot();
      const t = paintTarget();
      t.ctx.save();
      if (sel.active) {
        t.ctx.globalCompositeOperation = "destination-out";
        t.ctx.drawImage(sel.canvas, 0, 0);
      } else t.ctx.clearRect(0, 0, W, H);
      t.ctx.restore();
      l.dirty = true;
      render(); persist();
    },
    fillInside: () => {
      snapshot();
      const t = paintTarget();
      const scratch = I.makeCanvas(W, H);
      const g = I.ctx2d(scratch);
      g.fillStyle = state.editingMask ? "#ffffff" : state.color;
      g.fillRect(0, 0, W, H);
      sel.clip(scratch);
      t.ctx.globalAlpha = state.opacity;
      t.ctx.drawImage(scratch, 0, 0);
      t.ctx.globalAlpha = 1;
      L().dirty = true;
      render(); persist();
    },
  };

  // ------------------------------------------------------------ filters

  async function filterDialog() {
    const l = L();
    if (l.type === "text") { toast("Rasterise the text layer first"); return; }
    // Shader filters: any Generate sketch that takes an image. The layer is
    // handed in as its first sampler, so a photo grade written there applies
    // here, with the same controls.
    const shaderPresets = GENERATE_PRESETS.filter((p) => /\bsampler2D\b/.test(p.source));
    let shaderDocs = [];
    try {
      const { projects } = await api("/api/studio/projects");
      shaderDocs = (projects || []).filter((p) => p.kind === "generate" && p.id !== host.doc.id);
    } catch { /* offline: presets only */ }
    const selBox = el("select", {},
      el("optgroup", { label: "Filters" }, ...I.FILTERS.map((f) =>
        el("option", { value: f.id }, f.name))),
      el("optgroup", { label: "Shader — Generate presets" }, ...shaderPresets.map((p) =>
        el("option", { value: `shader:preset:${p.id}` }, p.label))),
      shaderDocs.length ? el("optgroup", { label: "Shader — your Generate documents" },
        ...shaderDocs.map((d) => el("option", { value: `shader:doc:${d.id}` }, d.name))) : null);
    const controls = el("div.stack");
    const preview = el("canvas", { width: 320, height: Math.round((320 * H) / W),
      style: { width: "100%", borderRadius: "8px", background: "#000" } });
    const source = I.getImage(l.canvas);
    let params = {}, result = null, resultCanvas = null;
    let shader = null;                        // { source, uniforms, values, imageName, time }

    const paintPreview = (tmp) => {
      const pg = preview.getContext("2d");
      pg.fillStyle = doc.background || "#fff";
      pg.fillRect(0, 0, preview.width, preview.height);
      pg.drawImage(tmp, 0, 0, preview.width, preview.height);
    };
    const recompute = () => {
      if (shader) {
        try {
          resultCanvas = renderSketch(shader.source, W, H, {
            images: { [shader.imageName]: l.canvas }, values: shader.values,
            time: shader.time, steps: 8 });
          result = null;
        } catch (e) { toast(`Shader failed: ${String(e.message).split("\n")[0]}`); return; }
        paintPreview(resultCanvas);
        return;
      }
      const f = I.FILTERS.find((x) => x.id === selBox.value);
      try { result = f.fn(source, params); }
      catch (e) { toast(`Filter failed: ${e.message}`); return; }
      resultCanvas = null;
      paintPreview(I.putImage(I.makeCanvas(W, H), result));
    };
    const buildShader = async (src) => {
      const uniforms = sketchUniforms(src);
      const img = uniforms.find((u) => u.control === "image");
      if (!img) { toast("That sketch takes no image, so it cannot filter a layer."); return; }
      shader = { source: src, uniforms, values: {}, imageName: img.name, time: 0 };
      // Seed defaults; images are the layer, so their controls are not shown.
      for (const u of uniforms) if (u.control !== "image") shader.values[u.name] = u.value.slice();
      clear(controls);
      controls.append(el("p.fine", {}, `The layer is passed as \`${img.name}\`.`));
      controls.append(buildControls(uniforms.filter((u) => u.control !== "image"),
        shader.values, recompute));
      controls.append(knob("time", { min: 0, max: 20, step: 0.05, value: 0,
        format: (v) => v.toFixed(2) + " s",
        oninput: (v) => { shader.time = v; recompute(); } }));
      recompute();
    };
    const build = async () => {
      const v = selBox.value;
      if (v.startsWith("shader:preset:")) {
        const p = shaderPresets.find((x) => x.id === v.slice(14));
        return buildShader(p.source);
      }
      if (v.startsWith("shader:doc:")) {
        const d = await api(`/api/studio/projects/${v.slice(11)}`);
        const src = d.data && (d.data.mode === "glsl" ? d.data.glsl : d.data.sketch);
        if (!src) { toast("That document has no source yet."); return; }
        return buildShader(src);
      }
      shader = null;
      const f = I.FILTERS.find((x) => x.id === v);
      params = {};
      clear(controls);
      for (const [name, min, max, def] of f.params) {
        params[name] = def;
        controls.append(knob(name, { min, max, step: (max - min) / 100, value: def,
          format: (v) => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2)),
          oninput: (v) => { params[name] = v; recompute(); } }));
      }
      for (const [name, def] of f.colors || []) {
        params[name] = def;
        controls.append(el("label", {}, name,
          el("input", { type: "color", value: def,
            oninput: (e) => { params[name] = e.target.value; recompute(); } })));
      }
      recompute();
    };
    selBox.onchange = build;

    modal(el("h2", {}, "Filter", el("span.fine", {}, ` — ${l.name}`)),
      sel.active ? el("p.fine", { style: { color: "var(--warm)" } },
        "A selection is active, so this applies inside it only.") : null,
      selBox, preview, controls,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: () => {
            if (!result && !resultCanvas) return;
            snapshot();
            const filtered = resultCanvas || I.putImage(I.makeCanvas(W, H), result);
            if (sel.active) {
              sel.clip(filtered);
              l.ctx.drawImage(filtered, 0, 0);
            } else {
              l.ctx.clearRect(0, 0, W, H);
              l.ctx.drawImage(filtered, 0, 0);
            }
            l.dirty = true;
            closeModal(); render(); persist();
          },
        }, "Apply")));
    build();
  }

  // ------------------------------------------------------------ layers UI

  function addLayer(name = null, drawInto = null) {
    snapshot("layer");
    const c = I.makeCanvas(W, H);
    if (drawInto) I.ctx2d(c).drawImage(drawInto, 0, 0, W, H);
    const id = Math.max(0, ...layers.map((l) => l.id)) + 1;
    layers.push({ id, name: name || `Layer ${id}`, visible: true, opacity: 1,
      blend: "source-over", type: "raster", text: null, canvas: c, ctx: I.ctx2d(c),
      maskCanvas: null, maskCtx: null, cache: I.makeCanvas(W, H), dirty: true });
    active = layers.length - 1;
    render(); renderPanels(); persist();
  }

  const layerList = el("div.stack");
  function renderLayers() {
    clear(layerList);
    [...layers].reverse().forEach((l) => {
      const idx = layers.indexOf(l);
      const isActive = idx === active;
      layerList.append(el("div.card.tight", {
        style: { borderColor: isActive ? "var(--accent)" : "" },
      },
        el("div.spread", {},
          el("div.row.tight", {},
            el("input", { type: "checkbox", checked: l.visible, style: { width: "auto" },
              onchange: (e) => { l.visible = e.target.checked; render(); persist(); } }),
            el("button.ghost", { style: { padding: ".1em .4em" },
              onclick: () => { active = idx; state.editingMask = false; render(); renderPanels(); } },
              l.name),
            l.type === "text" ? el("span.tag", {}, "T") : null,
            l.maskCanvas ? el("span.tag " + (isActive && state.editingMask ? "bad" : ""), {}, "mask") : null),
          el("div.row.tight", {},
            el("button.ghost", { title: "up", onclick: () => moveLayer(idx, 1) }, "↑"),
            el("button.ghost", { title: "down", onclick: () => moveLayer(idx, -1) }, "↓"),
            el("button.ghost.danger", { onclick: () => removeLayer(idx) }, "×"))),
        isActive ? el("div.stack", { style: { marginTop: ".3rem" } },
          el("div.row.tight", {},
            el("select", { style: { width: "auto", fontSize: ".75rem" },
              onchange: (e) => { l.blend = e.target.value; render(); persist(); } },
              ...BLEND_MODES.map((m) => el("option", { value: m, selected: m === l.blend }, m))),
            el("input", { type: "range", min: 0, max: 1, step: 0.01, value: l.opacity,
              style: { flex: 1 },
              oninput: (e) => { l.opacity = +e.target.value; render(); },
              onchange: persist })),
          el("div.row.tight", {},
            l.maskCanvas
              ? el("button.ghost", { class: state.editingMask ? "on" : "",
                  onclick: () => { state.editingMask = !state.editingMask; render(); renderPanels(); } },
                  state.editingMask ? "editing mask" : "edit mask")
              : el("button.ghost", { onclick: () => addMask(sel.active) },
                  sel.active ? "mask from selection" : "add mask"),
            l.maskCanvas ? el("button.ghost", { onclick: () => removeMask(true) }, "apply") : null,
            l.maskCanvas ? el("button.ghost.danger", { onclick: () => removeMask(false) }, "drop") : null),
          l.type === "text" ? el("div.row.tight", {},
            el("button.ghost", { onclick: () => textDialog(0, 0, l.text) }, "edit text"),
            el("button.ghost", { onclick: rasterizeText }, "rasterise")) : null) : null));
    });
  }

  function moveLayer(idx, dir) {
    const j = idx + dir;
    if (j < 0 || j >= layers.length) return;
    snapshot("layer");
    [layers[idx], layers[j]] = [layers[j], layers[idx]];
    active = j;
    render(); renderPanels(); persist();
  }
  async function removeLayer(idx) {
    if (layers.length === 1) { toast("A document needs at least one layer"); return; }
    if (!(await confirmDialog(`Delete "${layers[idx].name}"?`))) return;
    snapshot("layer");
    layers.splice(idx, 1);
    active = Math.max(0, Math.min(active, layers.length - 1));
    render(); renderPanels(); persist();
  }

  // ------------------------------------------------------------ keyboard

  function onKey(e) {
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (/input|textarea|select/i.test(e.target.tagName)) return;
    const meta = e.metaKey || e.ctrlKey;
    if (meta && e.key.toLowerCase() === "z") {
      e.preventDefault(); e.shiftKey ? step(redo, undo) : step(undo, redo); return;
    }
    if (meta && e.key.toLowerCase() === "a") { e.preventDefault(); selOps.all(); return; }
    if (meta && e.key.toLowerCase() === "d") { e.preventDefault(); selOps.none(); return; }
    if (meta && e.key.toLowerCase() === "i") { e.preventDefault(); selOps.invert(); return; }
    if (meta && e.key.toLowerCase() === "t") { e.preventDefault(); beginTransform(); return; }
    if (e.key === "Enter" && transform) { e.preventDefault(); commitTransform(); return; }
    if (e.key === "Escape") {
      if (transform) cancelTransform(); else selOps.none();
      return;
    }
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); selOps.deleteInside(); return; }
  }
  document.addEventListener("keydown", onKey);

  // ------------------------------------------------------------ import/export

  const fileInput = el("input", {
    type: "file", accept: "image/*", hidden: true,
    onchange: async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const bmp = await createImageBitmap(f);
      const scale = Math.min(W / bmp.width, H / bmp.height, 1);
      const c = I.makeCanvas(W, H);
      I.ctx2d(c).drawImage(bmp, (W - bmp.width * scale) / 2, (H - bmp.height * scale) / 2,
        bmp.width * scale, bmp.height * scale);
      addLayer(f.name.slice(0, 24), c);
      e.target.value = "";
    },
  });

  function exportPng() {
    render();
    const a = document.createElement("a");
    a.href = view.toDataURL("image/png");
    a.download = `${host.doc.name || "canvas"}.png`;
    a.click();
  }

  // ------------------------------------------------------------ chrome

  const setColor = (hex) => {
    state.color = hex;
    colorInput.value = hex;
    if (!swatches.includes(hex)) { swatches.unshift(hex); swatches.length = Math.min(14, swatches.length); }
    renderSwatches();
  };
  const colorInput = el("input", { type: "color", value: state.color,
    style: { width: "3rem", padding: 0, height: "2rem" },
    oninput: (e) => setColor(e.target.value) });
  const swatchRow = el("div.swatches");
  function renderSwatches() {
    clear(swatchRow);
    for (const s of swatches) {
      swatchRow.append(el("button", { title: s,
        style: { background: s, width: "22px", height: "22px", padding: 0,
                 borderRadius: "6px", border: "1px solid var(--line)" },
        onclick: () => setColor(s) }));
    }
  }
  renderSwatches();

  const toolBar = el("div.stack");
  function renderTools() {
    clear(toolBar);
    for (const [group, tools] of TOOL_GROUPS) {
      toolBar.append(el("div.row.tight", {},
        el("span.fine", { style: { minWidth: "3.4rem" } }, group),
        ...tools.map(([id, label]) => el("button", {
          class: id === state.tool ? "on" : "", "data-tool": id,
          onclick: () => { state.tool = id; renderTools(); },
        }, label))));
    }
  }
  renderTools();

  const selInfo = el("span.fine");
  function renderPanels() {
    renderLayers();
    renderTools();
    const b = sel.bounds();
    selInfo.textContent = sel.active && b
      ? `selection ${Math.round(b.w)}×${Math.round(b.h)}`
      : "no selection";
  }

  const zoomWrap = el("div", {
    style: { overflow: "auto", background: "#06080e", borderRadius: "10px",
             padding: ".6rem", display: "grid", placeItems: "center" },
  }, stage);
  const applyZoom = () => {
    const w = Math.round(W * state.zoom);
    view.style.width = overlay.style.width = `${w}px`;
    view.style.height = overlay.style.height = "auto";
    view.style.maxWidth = overlay.style.maxWidth = state.zoom === 1 ? "100%" : "none";
    renderOverlay();
  };

  const root = el("div.lab-split", { style: { gridTemplateColumns: "minmax(0,1fr) 290px" } },
    el("div.stack", {},
      el("div.card.tight", {},
        toolBar,
        el("div.row.tight", { style: { marginTop: ".4rem" } }, colorInput, swatchRow),
        el("div.knobs", { style: { marginTop: ".5rem" } },
          knob("size", { min: 1, max: 240, step: 1, value: state.size,
            format: (v) => v.toFixed(0), oninput: (v) => { state.size = v; } }),
          knob("opacity", { min: 0.05, max: 1, step: 0.01, value: state.opacity,
            format: (v) => v.toFixed(2), oninput: (v) => { state.opacity = v; } }),
          knob("hardness", { min: 0, max: 1, step: 0.01, value: state.hardness,
            format: (v) => v.toFixed(2), oninput: (v) => { state.hardness = v; } }),
          knob("tolerance", { min: 0, max: 128, step: 1, value: state.tolerance,
            format: (v) => v.toFixed(0), oninput: (v) => { state.tolerance = v; } }),
          knob("feather", { min: 0, max: 40, step: 0.5, value: state.feather,
            format: (v) => v.toFixed(1), oninput: (v) => { state.feather = v; } }))),
      zoomWrap),

    el("div.stack", {},
      el("div.card.tight", {},
        el("div.row.tight", {},
          el("button", { onclick: () => step(undo, redo) }, "Undo"),
          el("button", { onclick: () => step(redo, undo) }, "Redo"),
          el("button", { onclick: filterDialog }, "Filter…")),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          el("button", { onclick: () => addLayer() }, "+ Layer"),
          el("button", { onclick: () => fileInput.click() }, "Import"),
          el("button", { onclick: exportPng }, "PNG"),
          grid.button,
          fileInput),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          el("span.fine", {}, "zoom"),
          el("input", { type: "range", min: 0.25, max: 4, step: 0.05, value: 1,
            style: { flex: 1 }, oninput: (e) => { state.zoom = +e.target.value; applyZoom(); } }))),

      el("div.card.tight", {},
        el("div.spread", {}, el("h4", { style: { margin: 0 } }, "Selection"), selInfo),
        el("div.row.tight", { style: { marginTop: ".3rem" } },
          el("button.ghost", { onclick: selOps.all }, "All"),
          el("button.ghost", { onclick: selOps.none }, "None"),
          el("button.ghost", { onclick: selOps.invert }, "Invert")),
        el("div.row.tight", { style: { marginTop: ".3rem" } },
          el("button.ghost", { onclick: selOps.fillInside }, "Fill"),
          el("button.ghost", { onclick: selOps.deleteInside }, "Delete"),
          el("button.ghost", { onclick: beginTransform }, "Transform")),
        el("label.row.tight", { style: { marginTop: ".3rem", marginBottom: 0, fontSize: ".75rem" } },
          el("input", { type: "checkbox", checked: state.contiguous, style: { width: "auto" },
            onchange: (e) => { state.contiguous = e.target.checked; } }),
          "wand: contiguous only"),
        el("p.fine", {}, "Shift adds, ⌥ subtracts. ⌘A all · ⌘D none · ⌘I invert · " +
          "⌘T transform · ⌫ delete.")),

      el("div.card.tight", {}, el("h4", {}, "Layers"), layerList),

      el("div.card.tight", {},
        el("h4", {}, "Document"),
        el("p.fine", {}, `${W} × ${H}`),
        el("label", {}, "Background",
          el("input", { type: "color", value: doc.background || "#ffffff",
            oninput: (e) => { doc.background = e.target.value; render(); persist(); } })),
        aiButton("Palette from a description", {
          task: "palette",
          describe: "The model proposes a palette; you decide whether to use it. " +
            "It never sees your canvas.",
          placeholder: "e.g. risograph, two spot colours plus paper, slightly sour",
          onResult: (res) => {
            const cols = res.json?.colors;
            if (!cols?.length) { toast(res.parse_error || "no palette came back"); return; }
            for (const c of [...cols].reverse()) {
              if (/^#[0-9a-f]{6}$/i.test(c.hex)) swatches.unshift(c.hex);
            }
            swatches.length = Math.min(16, swatches.length);
            renderSwatches();
            toast(res.json.note || "Palette added to your swatches");
          },
        }))));

  root._cleanup = () => {
    clearInterval(antsTimer);
    document.removeEventListener("keydown", onKey);
  };

  applyZoom();
  render();
  renderPanels();
  return root;
}
