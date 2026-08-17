// Controls built from the descriptors shader-uniforms.js hands back.
//
// Kept apart from the parsing so the parsing stays testable without a DOM, and
// so both the Shader and Generate editors dress the same descriptors.

import { el } from "./ui.js";

const clamp01 = (v) => Math.min(1, Math.max(0, v));

export const toHex = (rgb) => "#" + rgb.slice(0, 3)
  .map((c) => Math.round(clamp01(c) * 255).toString(16).padStart(2, "0")).join("");

export const fromHex = (hex) => [1, 3, 5]
  .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);

/** A square you drag, for a vec2. Reads far better than two sliders. */
function xyPad(u, value, onChange) {
  const dot = el("div", { style: {
    position: "absolute", width: "12px", height: "12px", borderRadius: "50%",
    background: "var(--accent, #6ea8ff)", border: "2px solid #fff",
    transform: "translate(-50%, 50%)", pointerEvents: "none" } });
  const readout = el("b", {});
  const pad = el("div", {
    style: { position: "relative", width: "100%", aspectRatio: "1 / 1",
             maxWidth: "132px", background: "var(--bg-2, #10141f)",
             border: "1px solid var(--line, #2a3348)", borderRadius: "6px",
             cursor: "crosshair", touchAction: "none" } }, dot);

  const span = u.max - u.min;
  const place = () => {
    // y is measured from the bottom, matching the shader's coordinates rather
    // than the screen's.
    dot.style.left = `${((value[0] - u.min) / span) * 100}%`;
    dot.style.bottom = `${((value[1] - u.min) / span) * 100}%`;
    readout.textContent = `${value[0].toFixed(2)}, ${value[1].toFixed(2)}`;
  };
  const set = (e) => {
    const r = pad.getBoundingClientRect();
    value[0] = u.min + clamp01((e.clientX - r.left) / r.width) * span;
    value[1] = u.min + clamp01(1 - (e.clientY - r.top) / r.height) * span;
    place();
    onChange();
  };
  pad.addEventListener("pointerdown", (e) => {
    pad.setPointerCapture(e.pointerId);
    set(e);
  });
  pad.addEventListener("pointermove", (e) => {
    if (pad.hasPointerCapture(e.pointerId)) set(e);
  });
  place();
  return el("label.knob", {}, readout, u.label, pad);
}

function colourControl(u, value, onChange) {
  const swatch = el("input", {
    type: "color", value: toHex(value),
    style: { width: "100%", height: "30px", padding: "0", cursor: "pointer" },
    oninput: (e) => {
      const rgb = fromHex(e.target.value);
      for (let i = 0; i < 3; i++) value[i] = rgb[i];
      onChange();
    },
  });
  const rows = [el("label.knob", {}, u.label, swatch)];
  if (u.width === 4) {
    const out = el("b", {}, value[3].toFixed(2));
    rows.push(el("label.knob", {}, out, `${u.label} alpha`,
      el("input", { type: "range", min: 0, max: 1, step: 0.01, value: value[3],
        oninput: (e) => {
          value[3] = parseFloat(e.target.value);
          out.textContent = value[3].toFixed(2);
          onChange();
        } })));
  }
  return rows;
}

function toggleControl(u, value, onChange) {
  return el("label.knob", {}, u.label,
    el("input", { type: "checkbox", checked: value[0] > 0.5,
      style: { width: "auto", marginLeft: ".4rem" },
      oninput: (e) => { value[0] = e.target.checked ? 1 : 0; onChange(); } }));
}

function sliders(u, value, onChange) {
  const suffix = u.width === 1 ? [""] : ["x", "y", "z", "w"].slice(0, u.width);
  return suffix.map((s, i) => {
    const fmt = (v) => (u.isInt ? String(Math.round(v)) : v.toFixed(3));
    const out = el("b", {}, fmt(value[i]));
    // A scalar can carry the prose from its comment. Components cannot — four
    // sliders all captioned "x = scale, y = octaves" tells you nothing about
    // which one you are holding, so they get the name and the prose hovers.
    const caption = s ? `${u.name}.${s}` : u.label;
    return el("label.knob", { title: u.label }, out, caption,
      el("input", { type: "range", min: u.min, max: u.max, step: u.step, value: value[i],
        oninput: (e) => {
          value[i] = u.isInt ? Math.round(parseFloat(e.target.value)) : parseFloat(e.target.value);
          out.textContent = fmt(value[i]);
          onChange();
        } }));
  });
}

/**
 * Build the panel. `values` is the live store, keyed by uniform name — mutated
 * in place so the render loop reads current values without re-binding.
 */
export function buildControls(uniforms, values, onChange) {
  if (!uniforms.length) {
    return el("p.fine", {}, "No adjustable uniforms. Declare one — " +
      "`uniform float scale; // @range 1 40` — and a control appears here.");
  }
  const nodes = [];
  for (const u of uniforms) {
    // Keep the value across an edit when the shape still fits; a slider that
    // resets every time you touch the source is worse than no slider.
    const prev = values[u.name];
    const v = Array.isArray(prev) && prev.length === u.width
      ? prev.slice() : u.value.slice();
    values[u.name] = v;

    if (u.control === "pad") nodes.push(xyPad(u, v, onChange));
    else if (u.control === "color") nodes.push(...colourControl(u, v, onChange));
    else if (u.control === "toggle") nodes.push(toggleControl(u, v, onChange));
    else nodes.push(...sliders(u, v, onChange));
  }
  return el("div.knobs", {}, ...nodes);
}

/** Push the stored values at the live program. */
export function applyUniforms(gl, program, uniforms, values) {
  for (const u of uniforms) {
    const loc = gl.getUniformLocation(program, u.name);
    if (!loc) continue;                      // optimised out; nothing to set
    const v = values[u.name] || u.value;
    if (u.type === "bool") gl.uniform1i(loc, v[0] > 0.5 ? 1 : 0);
    else if (u.type === "int") gl.uniform1i(loc, Math.round(v[0]));
    else if (u.type === "float") gl.uniform1f(loc, v[0]);
    else if (u.type === "vec2") gl.uniform2f(loc, v[0], v[1]);
    else if (u.type === "vec3") gl.uniform3f(loc, v[0], v[1], v[2]);
    else if (u.type === "vec4") gl.uniform4f(loc, v[0], v[1], v[2], v[3]);
  }
}

/** New values for everything the Randomise button should move. Colours stay
    inside a pleasant band rather than going anywhere in the cube. */
export function randomise(uniforms, values) {
  for (const u of uniforms) {
    const v = values[u.name] || (values[u.name] = u.value.slice());
    if (u.control === "color") {
      const h = Math.random(), s = 0.35 + Math.random() * 0.45, l = 0.35 + Math.random() * 0.4;
      const rgb = hsl(h, s, l);
      for (let i = 0; i < Math.min(3, u.width); i++) v[i] = rgb[i];
    } else if (u.control === "toggle") {
      v[0] = Math.random() < 0.5 ? 0 : 1;
    } else {
      for (let i = 0; i < u.width; i++) {
        const r = u.min + Math.random() * (u.max - u.min);
        v[i] = u.isInt ? Math.round(r) : r;
      }
    }
  }
}

function hsl(h, s, l) {
  const f = (n) => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    return l - a * Math.max(-1, Math.min(Math.min(k - 3, 9 - k), 1));
  };
  return [f(0), f(8), f(4)];
}
