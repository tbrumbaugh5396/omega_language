// The live-figure runtime for the course docs.
//
// A figure is either a WebGL2 fragment shader or a canvas2d draw call, plus
// optional knobs. The docs stay valid markdown — they reference
// `figures/name.svg` as an ordinary image — and this runtime swaps in the live
// version wherever one exists with a matching id. Nothing forks into two
// copies that drift.
//
// Three rules the course's own README argues for, enforced here rather than
// left to the author:
//
//   · Artifact figures render at exactly one canvas pixel per device pixel.
//     A banding or dither demo that gets resampled is a claim about the
//     scaler, not about the signal, and it is worse than no figure at all.
//   · Offscreen figures do not run. Twenty animated canvases on one page
//     will cook a laptop, and a document that heats the reader's machine
//     does not get read.
//   · prefers-reduced-motion renders a single frame and offers a play button.

import { el, clear } from "./ui.js";

// ------------------------------------------------------------------ colour
//
// The CIE tables are not shipped. These are the Wyman–Sloan–Shirley (JCGT
// 2013) multi-lobe piecewise-Gaussian fits to the CIE 1931 2° observer:
// accurate to a fraction of a percent, and enough for every figure here.
// Anything claiming tabulated precision should say so and load the real CSV.

const gauss = (x, mu, s1, s2) => {
  const t = (x - mu) * (x < mu ? 1 / s1 : 1 / s2);
  return Math.exp(-0.5 * t * t);
};

export function cmf(lambda) {
  return [
    1.056 * gauss(lambda, 599.8, 37.9, 31.0)
      + 0.362 * gauss(lambda, 442.0, 16.0, 26.7)
      - 0.065 * gauss(lambda, 501.1, 20.4, 26.2),
    0.821 * gauss(lambda, 568.8, 46.9, 40.5)
      + 0.286 * gauss(lambda, 530.9, 16.3, 31.1),
    1.217 * gauss(lambda, 437.0, 11.8, 36.0)
      + 0.681 * gauss(lambda, 459.0, 26.0, 13.8),
  ];
}

export const LAMBDAS = Array.from({ length: 81 }, (_, i) => 380 + i * 5);
export const CMF_TABLE = LAMBDAS.map(cmf);

/** Integrate an SPD against the CMFs. The inner product Module 1 is about. */
export function spdToXYZ(spd) {
  let X = 0, Y = 0, Z = 0;
  for (let i = 0; i < spd.length; i++) {
    X += spd[i] * CMF_TABLE[i][0];
    Y += spd[i] * CMF_TABLE[i][1];
    Z += spd[i] * CMF_TABLE[i][2];
  }
  const k = 5;                       // 5 nm sample spacing
  return [X * k, Y * k, Z * k];
}

const XYZ_TO_LIN = [
  [3.2404542, -1.5371385, -0.4985314],
  [-0.9692660, 1.8760108, 0.0415560],
  [0.0556434, -0.2040259, 1.0572252],
];

export function xyzToLinear(X, Y, Z) {
  return XYZ_TO_LIN.map((r) => r[0] * X + r[1] * Y + r[2] * Z);
}
export const linToSrgb = (c) =>
  c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(Math.max(0, c), 1 / 2.4) - 0.055;
export const srgbToLin = (c) =>
  c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);

/** Clip to gamut, reporting whether anything had to be clipped. */
export function xyzToSrgb255(X, Y, Z) {
  const lin = xyzToLinear(X, Y, Z);
  const out = [];
  let clipped = false;
  for (const v of lin) {
    if (v < -1e-6 || v > 1 + 1e-6) clipped = true;
    out.push(Math.round(Math.max(0, Math.min(1, linToSrgb(Math.max(0, Math.min(1, v))))) * 255));
  }
  return { rgb: out, clipped };
}

export const LUMA = [0.2126729, 0.7151522, 0.0721750];

const M_LIN_LMS = [[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]];
const M_LMS_LAB = [[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]];

export function linearToOklab(r, g, b) {
  const l = Math.cbrt(M_LIN_LMS[0][0] * r + M_LIN_LMS[0][1] * g + M_LIN_LMS[0][2] * b);
  const m = Math.cbrt(M_LIN_LMS[1][0] * r + M_LIN_LMS[1][1] * g + M_LIN_LMS[1][2] * b);
  const s = Math.cbrt(M_LIN_LMS[2][0] * r + M_LIN_LMS[2][1] * g + M_LIN_LMS[2][2] * b);
  return M_LMS_LAB.map((row) => row[0] * l + row[1] * m + row[2] * s);
}
export function oklabToLinear(L, a, b) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
          -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
          -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s];
}

/** Planck's law, W·m⁻³·sr⁻¹, wavelength in nm. */
export function planck(lambdaNm, T) {
  const h = 6.62607015e-34, c = 2.99792458e8, kB = 1.380649e-23;
  const l = lambdaNm * 1e-9;
  return (2 * h * c * c) / (l ** 5 * (Math.exp((h * c) / (l * kB * T)) - 1));
}

/**
 * A vector in the null space of the CMF matrix — a metameric black.
 * Adding any multiple of it to a spectrum leaves XYZ exactly unchanged, which
 * is Module 1's central claim made constructive rather than asserted.
 */
export function metamericBlack(seedFn) {
  const n = LAMBDAS.length;
  const b = LAMBDAS.map((l, i) => seedFn(l, i));
  // Gram matrix of the three CMF rows, then project b onto their span and
  // subtract: what remains is orthogonal to all three.
  const rows = [0, 1, 2].map((k) => CMF_TABLE.map((c) => c[k]));
  const G = [], rhs = [];
  for (let i = 0; i < 3; i++) {
    G.push([]);
    for (let j = 0; j < 3; j++) {
      let s = 0;
      for (let x = 0; x < n; x++) s += rows[i][x] * rows[j][x];
      G[i].push(s);
    }
    let s = 0;
    for (let x = 0; x < n; x++) s += rows[i][x] * b[x];
    rhs.push(s);
  }
  const coef = solve3(G, rhs);
  const out = new Float64Array(n);
  for (let x = 0; x < n; x++) {
    out[x] = b[x] - (coef[0] * rows[0][x] + coef[1] * rows[1][x] + coef[2] * rows[2][x]);
  }
  return out;
}

function solve3(A, b) {
  const m = [[...A[0], b[0]], [...A[1], b[1]], [...A[2], b[2]]];
  for (let i = 0; i < 3; i++) {
    let p = i;
    for (let r = i + 1; r < 3; r++) if (Math.abs(m[r][i]) > Math.abs(m[p][i])) p = r;
    [m[i], m[p]] = [m[p], m[i]];
    const d = m[i][i] || 1e-12;
    for (let c = i; c < 4; c++) m[i][c] /= d;
    for (let r = 0; r < 3; r++) {
      if (r === i) continue;
      const f = m[r][i];
      for (let c = i; c < 4; c++) m[r][c] -= f * m[i][c];
    }
  }
  return [m[0][3], m[1][3], m[2][3]];
}

// ------------------------------------------------------------------ runtime

const VERT = `#version 300 es
in vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

const PREAMBLE = `#version 300 es
precision highp float;
uniform vec2  u_resolution;
uniform float u_time;
uniform vec2  u_mouse;
uniform vec4  u_k;
out vec4 fragColor;
`;

const reducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Mount one figure into `host`. Returns a teardown function.
 * `fig` comes from figures-content.js.
 */
export function mountFigure(host, fig, { width = 720 } = {}) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const canvas = el("canvas", {
    style: { display: "block", borderRadius: "8px", background: "#0b0e16" },
  });

  const err = el("div.lab-log");
  const knobRow = el("div.knobs");
  const k = (fig.knobs || []).map((kb) => kb[3]);

  const state = { t0: performance.now(), raf: null, visible: false,
                  running: false, mouse: [0.5, 0.5] };

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    state.mouse = [(e.clientX - r.left) / r.width, 1 - (e.clientY - r.top) / r.height];
  });

  let draw = () => {};
  let teardownRuntime = () => {};

  if (fig.runtime === "glsl") {
    const gl = canvas.getContext("webgl2", { antialias: false, preserveDrawingBuffer: true });
    if (!gl) {
      err.textContent = "This figure needs WebGL2, which this browser did not provide.";
      draw = () => {};
    } else {
      let program = null;
      try {
        program = buildProgram(gl, PREAMBLE + fig.source);
      } catch (e) {
        err.textContent = String(e.message).trim();
      }
      if (program) {
        gl.useProgram(program);
        const buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
        const loc = gl.getAttribLocation(program, "a_pos");
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        const u = (n) => gl.getUniformLocation(program, n);
        draw = (t) => {
          gl.viewport(0, 0, canvas.width, canvas.height);
          gl.uniform2f(u("u_resolution"), canvas.width, canvas.height);
          gl.uniform1f(u("u_time"), t);
          gl.uniform2f(u("u_mouse"), state.mouse[0], state.mouse[1]);
          gl.uniform4f(u("u_k"), k[0] ?? 0, k[1] ?? 0, k[2] ?? 0, k[3] ?? 0);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
        };
        teardownRuntime = () => { gl.deleteProgram(program); };
      }
    }
  } else {
    const g = canvas.getContext("2d", { willReadFrequently: !!fig.exact });
    draw = (t) => {
      try {
        // canvas2d figures are handed device pixels and a scale factor, so a
        // plot can stay legible while an artifact demo stays pixel-exact.
        fig.draw(g, canvas.width, canvas.height, t, k, fig.exact ? 1 : dpr);
      } catch (e) {
        err.textContent = String(e.message);
        state.running = false;
      }
    };
  }

  const frame = () => {
    if (!state.running) return;
    draw((performance.now() - state.t0) / 1000);
    if (fig.animated) state.raf = requestAnimationFrame(frame);
    else state.running = false;
  };
  const start = () => {
    if (state.running) return;
    // A still figure draws now rather than waiting a frame. Deferring it to
    // requestAnimationFrame costs a visible flash of empty canvas, and under a
    // throttled rAF it can be a long one.
    if (!fig.animated) { draw((performance.now() - state.t0) / 1000); return; }
    state.running = true;
    state.raf = requestAnimationFrame(frame);
  };
  const pause = () => {
    state.running = false;
    if (state.raf) cancelAnimationFrame(state.raf);
  };
  const redraw = () => { if (!fig.animated) { draw((performance.now() - state.t0) / 1000); } };

  for (let i = 0; i < (fig.knobs || []).length; i++) {
    const [label, min, max, def, fmt] = fig.knobs[i];
    const out = el("b", {}, (fmt || ((v) => v.toFixed(2)))(def));
    knobRow.append(el("label.knob", {}, out, label,
      el("input", {
        type: "range", min, max, step: (max - min) / 200, value: def,
        oninput: (e) => {
          k[i] = parseFloat(e.target.value);
          out.textContent = (fmt || ((v) => v.toFixed(2)))(k[i]);
          redraw();
        },
      })));
  }

  const playBtn = el("button.ghost", {
    onclick: () => {
      if (state.running) { pause(); playBtn.textContent = "Play"; }
      else { start(); playBtn.textContent = "Pause"; }
    },
  }, "Play");

  const wrap = el("figure.course-figure", {},
    canvas,
    err,
    (fig.knobs || []).length ? knobRow : null,
    el("figcaption", {},
      el("span", {}, fig.caption || ""),
      fig.note ? el("span.fine", { style: { display: "block", marginTop: ".3rem" } }, fig.note) : null,
      fig.animated ? el("div.row.tight", { style: { marginTop: ".3rem" } }, playBtn) : null));
  host.append(wrap);

  // Size from the width the figure actually got, not from a guess. An exact
  // figure must never be scaled by CSS afterwards — if the backing store and
  // the layout box disagree, the artifact on screen is the browser's resampler
  // rather than the signal, which is the one thing these figures must not do.
  function fit() {
    const avail = Math.max(200, Math.floor(wrap.clientWidth - 2));
    const cssW = Math.min(avail, fig.maxWidth || avail);
    const cssH = Math.round(cssW * (fig.aspect || 0.42));
    const bw = Math.round(cssW * dpr), bh = Math.round(cssH * dpr);
    if (canvas.width === bw && canvas.height === bh) return false;
    canvas.width = bw;
    canvas.height = bh;
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;
    return true;
  }
  fit();
  // Paint once, now. IntersectionObserver decides whether an *animation* runs;
  // it must not be what decides whether the figure has any content, or a
  // reader whose browser defers the callback sees an empty box.
  draw(0);

  const ro = new ResizeObserver(() => {
    if (!fit()) return;
    state.running = false;
    if (fig.animated && state.visible) start(); else draw((performance.now() - state.t0) / 1000);
  });
  ro.observe(wrap);

  // Only run while on screen. This is the difference between a page with
  // twenty figures and a page that melts a laptop.
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      state.visible = entry.isIntersecting;
      if (!fig.animated) continue;            // stills are already painted
      if (!state.visible) { pause(); playBtn.textContent = "Play"; continue; }
      if (reducedMotion()) { draw(0); continue; }
      start();
      playBtn.textContent = "Pause";
    }
  }, { rootMargin: "120px" });
  io.observe(canvas);

  return () => { io.disconnect(); ro.disconnect(); pause(); teardownRuntime(); };
}

function buildProgram(gl, fragSource) {
  const mk = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error(log || "shader compile failed");
    }
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, mk(gl.VERTEX_SHADER, VERT));
  gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fragSource));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(p) || "link failed");
  }
  return p;
}

// ------------------------------------------------------------------ plotting
//
// Small helpers so the canvas2d figures read as plots rather than as pixel
// bookkeeping. Neutral axes, like the course's own SVGs, so they sit on any
// background.

export const AX = "#808080";
export const PLOT_COLORS = ["#7F77DD", "#D85A30", "#1D9E75", "#EF9F27", "#C05BC0"];

export function plotFrame(g, w, h, opts = {}) {
  const { xLabel = "", yLabel = "", xMin = 0, xMax = 1, yMin = 0, yMax = 1,
          pad = 34, s = 1, logY = false, title = "" } = opts;
  const P = pad * s;
  g.clearRect(0, 0, w, h);
  g.save();
  g.strokeStyle = AX;
  g.fillStyle = AX;
  g.lineWidth = 1 * s;
  g.font = `${10 * s}px ui-monospace, monospace`;
  g.beginPath();
  g.moveTo(P, 6 * s); g.lineTo(P, h - P); g.lineTo(w - 8 * s, h - P);
  g.stroke();
  if (title) { g.fillText(title, P + 4 * s, 14 * s); }
  if (xLabel) g.fillText(xLabel, w / 2 - 12 * s, h - 8 * s);
  if (yLabel) {
    g.save(); g.translate(11 * s, h / 2 + 20 * s); g.rotate(-Math.PI / 2);
    g.fillText(yLabel, 0, 0); g.restore();
  }
  g.restore();
  const X = (v) => P + ((v - xMin) / (xMax - xMin)) * (w - P - 8 * s);
  const Y = logY
    ? (v) => (h - P) - ((Math.log10(Math.max(v, 1e-9)) - Math.log10(Math.max(yMin, 1e-9)))
        / (Math.log10(yMax) - Math.log10(Math.max(yMin, 1e-9)))) * (h - P - 6 * s)
    : (v) => (h - P) - ((v - yMin) / (yMax - yMin)) * (h - P - 6 * s);
  return { X, Y, P };
}

export function plotLine(g, pts, color, { s = 1, dash = null } = {}) {
  g.save();
  g.strokeStyle = color;
  g.lineWidth = 1.6 * s;
  if (dash) g.setLineDash(dash.map((d) => d * s));
  g.beginPath();
  pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.stroke();
  g.restore();
}

export function legend(g, items, x, y, s = 1) {
  g.save();
  g.font = `${10 * s}px system-ui`;
  items.forEach(([label, color], i) => {
    const yy = y + i * 14 * s;
    g.fillStyle = color;
    g.fillRect(x, yy - 6 * s, 12 * s, 3 * s);
    g.fillStyle = AX;
    g.fillText(label, x + 17 * s, yy);
  });
  g.restore();
}
