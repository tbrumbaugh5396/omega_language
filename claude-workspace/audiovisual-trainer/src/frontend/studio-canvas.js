// The canvas editor: layers, brushes, shapes, type, and the Part 10 effects
// catalogue as a filter menu.
//
// Layers are real offscreen canvases composited with the browser's own blend
// modes, which are the Porter-Duff operators the compositing lesson is about.
// Filters run through engine-image, so the thing you apply here is the same
// code the drills generate their stimuli with.

import { el, clear, toast, modal, closeModal, knob, confirmDialog } from "./ui.js";
import * as I from "./engine-image.js";
import { aiButton } from "./ai.js";

const BLEND_MODES = ["source-over", "multiply", "screen", "overlay", "darken",
  "lighten", "color-dodge", "color-burn", "hard-light", "soft-light",
  "difference", "exclusion", "hue", "saturation", "color", "luminosity"];

const TOOLS = [
  ["brush", "Brush"], ["eraser", "Eraser"], ["line", "Line"],
  ["rect", "Rect"], ["ellipse", "Ellipse"], ["fill", "Fill"],
  ["text", "Text"], ["pick", "Pick"],
];

export async function canvasEditor(host) {
  const doc = host.data;
  const W = doc.width, H = doc.height;

  // ---- runtime layer state: an offscreen canvas per stored layer
  const layers = [];
  for (const l of doc.layers) {
    const c = I.makeCanvas(W, H);
    if (l.data) {
      await new Promise((res) => {
        const img = new Image();
        img.onload = () => { I.ctx2d(c).drawImage(img, 0, 0); res(); };
        img.onerror = res;
        img.src = l.data;
      });
    }
    layers.push({ ...l, canvas: c, ctx: I.ctx2d(c) });
  }
  let active = 0;

  // ---- tool state
  const state = {
    tool: "brush", color: "#e8ebf5", size: 18, opacity: 1, hardness: 0.8,
    fontSize: 72, tolerance: 32, zoom: 1,
  };
  const swatches = ["#e8ebf5", "#0d0f18", "#7c9cff", "#f0a35e", "#6ee7c8",
                    "#f2708a", "#5fd39a"];

  // ---- undo, bounded: full-layer snapshots are the honest way to make every
  // operation undoable, but they are not free, so the stack is short.
  const undo = [], redo = [];
  const snapshot = () => {
    undo.push({ index: active, data: I.getImage(layers[active].canvas) });
    if (undo.length > 20) undo.shift();
    redo.length = 0;
  };
  const applySnapshot = (from, to) => {
    const s = from.pop();
    if (!s) return;
    const cur = { index: s.index, data: I.getImage(layers[s.index].canvas) };
    to.push(cur);
    I.putImage(layers[s.index].canvas, s.data);
    render();
    persist();
  };

  // ---- the visible canvas
  const view = el("canvas", { width: W, height: H, style: { cursor: "crosshair" } });
  const vg = view.getContext("2d");

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
      vg.drawImage(l.canvas, 0, 0);
    }
    vg.restore();
  }

  function thumbnail() {
    const t = I.makeCanvas(240, Math.max(1, Math.round((240 * H) / W)));
    I.ctx2d(t).drawImage(view, 0, 0, t.width, t.height);
    return t.toDataURL("image/jpeg", 0.7);
  }

  let persistTimer = null;
  function persist() {
    clearTimeout(persistTimer);
    // Serialising every layer to a PNG data URL is the expensive part, so it
    // waits for a pause rather than running per stroke.
    persistTimer = setTimeout(() => {
      doc.layers = layers.map((l) => ({
        id: l.id, name: l.name, visible: l.visible, opacity: l.opacity,
        blend: l.blend, data: l.canvas.toDataURL("image/png"),
      }));
      host.save(thumbnail());
    }, 400);
  }

  // ---- pointer → document coordinates
  function pos(e) {
    const r = view.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
  }

  function stamp(g, x, y) {
    const r = state.size / 2;
    if (state.hardness >= 0.99) {
      g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
      return;
    }
    // Soft brush: a radial gradient stamp. The falloff is the brush.
    const grad = g.createRadialGradient(x, y, r * state.hardness, x, y, r);
    const col = state.tool === "eraser" ? "#000" : state.color;
    grad.addColorStop(0, col);
    grad.addColorStop(1, col + "00");
    const prev = g.fillStyle;
    g.fillStyle = grad;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
    g.fillStyle = prev;
  }

  let drawing = false, last = null, start = null, preview = null;

  view.addEventListener("pointerdown", (e) => {
    const [x, y] = pos(e);
    const layer = layers[active];
    if (!layer.visible) { toast("That layer is hidden"); return; }

    if (state.tool === "pick") {
      const d = vg.getImageData(Math.round(x), Math.round(y), 1, 1).data;
      setColor(I.hex(d[0], d[1], d[2]));
      return;
    }
    if (state.tool === "text") { textDialog(x, y); return; }
    if (state.tool === "fill") { snapshot(); floodFill(layer, x, y); render(); persist(); return; }

    snapshot();
    drawing = true;
    start = [x, y];
    last = [x, y];
    // Capture is a nicety — it keeps a stroke alive when the pointer leaves
    // the canvas. It must not be able to throw before the context state is
    // set up, or endStroke's restore() would pop a frame that was never
    // pushed and every later stroke would inherit the wrong state.
    try { view.setPointerCapture(e.pointerId); } catch { /* no active pointer */ }

    const g = layer.ctx;
    g.save();
    g.globalAlpha = state.opacity;
    g.globalCompositeOperation = state.tool === "eraser" ? "destination-out" : "source-over";
    g.fillStyle = state.color;
    g.strokeStyle = state.color;
    g.lineWidth = state.size;
    g.lineCap = "round";
    g.lineJoin = "round";

    if (state.tool === "brush" || state.tool === "eraser") stamp(g, x, y);
    else preview = I.getImage(layer.canvas);   // shapes redraw from a snapshot
    render();
  });

  view.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    const [x, y] = pos(e);
    const layer = layers[active], g = layer.ctx;

    if (state.tool === "brush" || state.tool === "eraser") {
      // Interpolate: a fast pointer otherwise leaves a dotted line.
      const dist = Math.hypot(x - last[0], y - last[1]);
      const step = Math.max(1, state.size * 0.18);
      for (let d = 0; d <= dist; d += step) {
        const t = dist ? d / dist : 0;
        stamp(g, last[0] + (x - last[0]) * t, last[1] + (y - last[1]) * t);
      }
      last = [x, y];
    } else {
      I.putImage(layer.canvas, preview);
      g.save();
      g.globalAlpha = state.opacity;
      g.strokeStyle = state.color;
      g.fillStyle = state.color;
      g.lineWidth = state.size;
      g.lineCap = "round";
      g.beginPath();
      if (state.tool === "line") { g.moveTo(start[0], start[1]); g.lineTo(x, y); g.stroke(); }
      else if (state.tool === "rect") g.fillRect(start[0], start[1], x - start[0], y - start[1]);
      else {
        g.ellipse((start[0] + x) / 2, (start[1] + y) / 2,
                  Math.abs(x - start[0]) / 2, Math.abs(y - start[1]) / 2, 0, 0, Math.PI * 2);
        g.fill();
      }
      g.restore();
    }
    render();
  });

  const endStroke = () => {
    if (!drawing) return;
    drawing = false;
    preview = null;
    layers[active].ctx.restore();
    persist();
  };
  view.addEventListener("pointerup", endStroke);
  view.addEventListener("pointercancel", endStroke);

  function floodFill(layer, x0, y0) {
    const img = I.getImage(layer.canvas);
    const d = img.data;
    const x = Math.round(x0), y = Math.round(y0);
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const at = (px, py) => (py * W + px) * 4;
    const s = at(x, y);
    const target = [d[s], d[s + 1], d[s + 2], d[s + 3]];
    const fill = [parseInt(state.color.slice(1, 3), 16),
                  parseInt(state.color.slice(3, 5), 16),
                  parseInt(state.color.slice(5, 7), 16), 255];
    const tol = state.tolerance;
    const close = (i) => Math.abs(d[i] - target[0]) <= tol &&
      Math.abs(d[i + 1] - target[1]) <= tol &&
      Math.abs(d[i + 2] - target[2]) <= tol &&
      Math.abs(d[i + 3] - target[3]) <= tol;
    if (close(at(x, y)) && fill.every((v, k) => v === target[k])) return;

    // Scanline flood: a pixel stack blows up on a large region.
    const stack = [[x, y]];
    const seen = new Uint8Array(W * H);
    while (stack.length) {
      const [sx, sy] = stack.pop();
      let lx = sx;
      while (lx > 0 && close(at(lx - 1, sy))) lx--;
      let rx = sx;
      while (rx < W - 1 && close(at(rx + 1, sy))) rx++;
      for (let px = lx; px <= rx; px++) {
        const i = at(px, sy);
        d[i] = fill[0]; d[i + 1] = fill[1]; d[i + 2] = fill[2]; d[i + 3] = fill[3];
        seen[sy * W + px] = 1;
        for (const ny of [sy - 1, sy + 1]) {
          if (ny < 0 || ny >= H) continue;
          if (!seen[ny * W + px] && close(at(px, ny))) stack.push([px, ny]);
        }
      }
    }
    I.putImage(layer.canvas, img);
  }

  function textDialog(x, y) {
    const text = el("input", { placeholder: "type something" });
    const size = el("input", { type: "number", value: state.fontSize, min: 8, max: 600 });
    const weight = el("select", {}, ...["300", "400", "600", "800"].map((w) =>
      el("option", { value: w, selected: w === "600" }, w)));
    modal(el("h2", {}, "Text"),
      el("label", {}, "Words", text),
      el("div.row", {},
        el("label", { style: { marginBottom: 0 } }, "Size", size),
        el("label", { style: { marginBottom: 0 } }, "Weight", weight)),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: () => {
            if (!text.value) { closeModal(); return; }
            snapshot();
            state.fontSize = +size.value || 72;
            const g = layers[active].ctx;
            g.save();
            g.globalAlpha = state.opacity;
            g.fillStyle = state.color;
            g.font = `${weight.value} ${state.fontSize}px system-ui, sans-serif`;
            g.textBaseline = "middle";
            g.fillText(text.value, x, y);
            g.restore();
            closeModal();
            render();
            persist();
          },
        }, "Place")));
  }

  // ---------------------------------------------------------------- panels

  const setColor = (hex) => {
    state.color = hex;
    colorInput.value = hex;
    if (!swatches.includes(hex)) { swatches.unshift(hex); swatches.length = Math.min(14, swatches.length); }
    renderSwatches();
  };
  const colorInput = el("input", {
    type: "color", value: state.color, style: { width: "3rem", padding: 0, height: "2rem" },
    oninput: (e) => setColor(e.target.value),
  });
  const swatchRow = el("div.swatches");
  function renderSwatches() {
    clear(swatchRow);
    for (const s of swatches) {
      swatchRow.append(el("button", {
        title: s,
        style: { background: s, width: "22px", height: "22px", padding: 0,
                 borderRadius: "6px", border: "1px solid var(--line)" },
        onclick: () => setColor(s),
      }));
    }
  }
  renderSwatches();

  const toolRow = el("div.row.tight", {}, ...TOOLS.map(([id, label]) =>
    el("button", {
      class: id === state.tool ? "on" : "", "data-tool": id,
      onclick: (e) => {
        state.tool = id;
        toolRow.querySelectorAll("button").forEach((b) =>
          b.classList.toggle("on", b.dataset.tool === id));
        view.style.cursor = id === "pick" ? "copy" : "crosshair";
      },
    }, label)));

  const layerList = el("div.stack");
  function renderLayers() {
    clear(layerList);
    [...layers].reverse().forEach((l) => {
      const idx = layers.indexOf(l);
      layerList.append(el("div.card.tight", {
        class: idx === active ? "picked" : "",
        style: { borderColor: idx === active ? "var(--accent)" : "" },
      },
        el("div.spread", {},
          el("div.row.tight", {},
            el("input", {
              type: "checkbox", checked: l.visible, style: { width: "auto" },
              onchange: (e) => { l.visible = e.target.checked; render(); persist(); },
            }),
            el("button.ghost", {
              style: { padding: ".1em .4em" },
              onclick: () => { active = idx; renderLayers(); },
            }, l.name)),
          el("div.row.tight", {},
            el("button.ghost", { title: "up", onclick: () => moveLayer(idx, 1) }, "↑"),
            el("button.ghost", { title: "down", onclick: () => moveLayer(idx, -1) }, "↓"),
            el("button.ghost.danger", { onclick: () => removeLayer(idx) }, "×"))),
        idx === active
          ? el("div.row.tight", { style: { marginTop: ".3rem" } },
              el("select", {
                style: { width: "auto", fontSize: ".75rem" },
                onchange: (e) => { l.blend = e.target.value; render(); persist(); },
              }, ...BLEND_MODES.map((m) => el("option", { value: m, selected: m === l.blend }, m))),
              el("input", {
                type: "range", min: 0, max: 1, step: 0.01, value: l.opacity,
                style: { flex: 1 },
                oninput: (e) => { l.opacity = +e.target.value; render(); },
                onchange: persist,
              }))
          : null));
    });
  }

  function moveLayer(idx, dir) {
    const j = idx + dir;
    if (j < 0 || j >= layers.length) return;
    [layers[idx], layers[j]] = [layers[j], layers[idx]];
    active = j;
    renderLayers(); render(); persist();
  }
  function addLayer(name = null, drawInto = null) {
    const c = I.makeCanvas(W, H);
    if (drawInto) I.ctx2d(c).drawImage(drawInto, 0, 0, W, H);
    const id = Math.max(0, ...layers.map((l) => l.id)) + 1;
    layers.push({ id, name: name || `Layer ${id}`, visible: true, opacity: 1,
                  blend: "source-over", canvas: c, ctx: I.ctx2d(c) });
    active = layers.length - 1;
    renderLayers(); render(); persist();
  }
  async function removeLayer(idx) {
    if (layers.length === 1) { toast("A document needs at least one layer"); return; }
    if (!(await confirmDialog(`Delete "${layers[idx].name}"?`))) return;
    layers.splice(idx, 1);
    active = Math.max(0, Math.min(active, layers.length - 1));
    renderLayers(); render(); persist();
  }
  renderLayers();

  // ---------------------------------------------------------------- filters

  function filterDialog() {
    const sel = el("select", {}, ...I.FILTERS.map((f) =>
      el("option", { value: f.id }, f.name)));
    const controls = el("div.stack");
    const previewCanvas = el("canvas", { width: 320, height: Math.round((320 * H) / W),
      style: { width: "100%", borderRadius: "8px", background: "#000" } });
    const source = I.getImage(layers[active].canvas);
    let params = {};
    let result = null;

    const recompute = () => {
      const f = I.FILTERS.find((x) => x.id === sel.value);
      try {
        result = f.fn(source, params);
      } catch (e) {
        toast(`Filter failed: ${e.message}`);
        return;
      }
      const tmp = I.putImage(I.makeCanvas(W, H), result);
      const pg = previewCanvas.getContext("2d");
      pg.fillStyle = doc.background || "#fff";
      pg.fillRect(0, 0, previewCanvas.width, previewCanvas.height);
      pg.drawImage(tmp, 0, 0, previewCanvas.width, previewCanvas.height);
    };

    const buildControls = () => {
      const f = I.FILTERS.find((x) => x.id === sel.value);
      params = {};
      clear(controls);
      for (const [name, min, max, def] of f.params) {
        params[name] = def;
        controls.append(knob(name, {
          min, max, step: (max - min) / 100, value: def,
          format: (v) => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2)),
          oninput: (v) => { params[name] = v; recompute(); },
        }));
      }
      for (const [name, def] of f.colors || []) {
        params[name] = def;
        controls.append(el("label", {}, name,
          el("input", { type: "color", value: def,
            oninput: (e) => { params[name] = e.target.value; recompute(); } })));
      }
      recompute();
    };
    sel.onchange = buildControls;

    modal(
      el("h2", {}, "Filter", el("span.fine", {}, ` — ${layers[active].name}`)),
      sel, previewCanvas, controls,
      el("p.fine", {}, "Every one of these is an entry from the effects " +
        "catalogue, built from the same primitives as the drills."),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: () => {
            if (!result) return;
            snapshot();
            I.putImage(layers[active].canvas, result);
            closeModal(); render(); persist();
          },
        }, "Apply")));
    buildControls();
  }

  // ---------------------------------------------------------------- import/export

  const fileInput = el("input", {
    type: "file", accept: "image/*", hidden: true,
    onchange: async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const bmp = await createImageBitmap(f);
      // Fit inside the document rather than cropping it.
      const scale = Math.min(W / bmp.width, H / bmp.height, 1);
      const c = I.makeCanvas(W, H);
      const g = I.ctx2d(c);
      g.drawImage(bmp, (W - bmp.width * scale) / 2, (H - bmp.height * scale) / 2,
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

  // ---------------------------------------------------------------- layout

  const zoomWrap = el("div", {
    style: { overflow: "auto", background: "#06080e", borderRadius: "10px",
             padding: ".6rem", display: "grid", placeItems: "center" },
  }, view);
  const applyZoom = () => {
    view.style.width = `${Math.round(W * state.zoom)}px`;
    view.style.height = "auto";
    view.style.maxWidth = state.zoom === 1 ? "100%" : "none";
  };
  applyZoom();

  const root = el("div.lab-split", { style: { gridTemplateColumns: "minmax(0,1fr) 280px" } },
    el("div.stack", {},
      el("div.card.tight", {},
        el("div.row.tight", {}, toolRow),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          colorInput, swatchRow),
        el("div.knobs", { style: { marginTop: ".5rem" } },
          knob("size", { min: 1, max: 200, step: 1, value: state.size,
            format: (v) => v.toFixed(0), oninput: (v) => { state.size = v; } }),
          knob("opacity", { min: 0.05, max: 1, step: 0.01, value: state.opacity,
            format: (v) => v.toFixed(2), oninput: (v) => { state.opacity = v; } }),
          knob("hardness", { min: 0, max: 1, step: 0.01, value: state.hardness,
            format: (v) => v.toFixed(2), oninput: (v) => { state.hardness = v; } }),
          knob("fill tolerance", { min: 0, max: 128, step: 1, value: state.tolerance,
            format: (v) => v.toFixed(0), oninput: (v) => { state.tolerance = v; } }))),
      zoomWrap),

    el("div.stack", {},
      el("div.card.tight", {},
        el("div.row.tight", {},
          el("button", { onclick: () => applySnapshot(undo, redo) }, "Undo"),
          el("button", { onclick: () => applySnapshot(redo, undo) }, "Redo"),
          el("button", { onclick: filterDialog }, "Filter…")),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          el("button", { onclick: () => addLayer() }, "+ Layer"),
          el("button", { onclick: () => fileInput.click() }, "Import"),
          el("button", { onclick: exportPng }, "PNG"),
          fileInput),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          el("span.fine", {}, "zoom"),
          el("input", {
            type: "range", min: 0.25, max: 3, step: 0.05, value: 1,
            style: { flex: 1 },
            oninput: (e) => { state.zoom = +e.target.value; applyZoom(); },
          })),
        el("div.row.tight", { style: { marginTop: ".4rem" } },
          aiButton("Palette from a description", {
            task: "palette",
            describe: "The model proposes a palette; you decide whether to use " +
              "it. It never sees your canvas.",
            placeholder: "e.g. risograph, two spot colours plus paper, " +
              "high-contrast, slightly sour",
            onResult: (res) => {
              const cols = res.json?.colors;
              if (!cols?.length) { toast(res.parse_error || "no palette came back"); return; }
              for (const c of cols.reverse()) {
                if (/^#[0-9a-f]{6}$/i.test(c.hex)) swatches.unshift(c.hex);
              }
              swatches.length = Math.min(16, swatches.length);
              renderSwatches();
              toast(res.json.note || "Palette added to your swatches");
            },
          }))),
      el("div.card.tight", {},
        el("h4", {}, "Layers"),
        layerList),
      el("div.card.tight", {},
        el("h4", {}, "Document"),
        el("p.fine", {}, `${W} × ${H}`),
        el("label", {}, "Background",
          el("input", { type: "color", value: doc.background || "#ffffff",
            oninput: (e) => { doc.background = e.target.value; render(); persist(); } })))));

  render();
  return root;
}
