// The in-app self-test.
//
// Every check here was first done by hand, in a browser console, while the
// thing it checks was being built. That is not a test; it is a memory of one.
// This makes them permanent: one click compiles every preset for both
// passes, renders each and asks whether it drew anything and whether its
// controls do anything, then runs the two shape compilers against the
// browser's own rasterisation and reports the error in the same units used
// in the commit messages — mean absolute error out of 255, and pixels off by
// more than a threshold.
//
// It reports; it does not gate. A number that has drifted is a fact to look
// at, not a reason to block a save.

import { el, clear } from "./ui.js";
import { GENERATE_PRESETS } from "./studio-generate.js";
import { SHADER_PRESETS } from "./studio-shader.js";
import { parseUniforms, desugar, hasSimPass, withDefine, isEs3 } from "./shader-uniforms.js";
import { applyUniforms, randomise } from "./shader-controls.js";
import { getGL, isGL2, linkProgram, renderSketch, loadSketchImages } from "./shader-run.js";
import { compileDesignFrame } from "./design-to-sdf.js";
import { compileSvg } from "./svg-to-sdf.js";
import { Feedback } from "./feedback.js";
import { createGraph, addNode, addBlur, curveLut, NODE_TYPES } from "./render-graph.js";
import { renderGraph, ejectGraph } from "./graph-compile.js";
import { blurFast, getImage } from "./engine-image.js";

// ------------------------------------------------------------------ fixtures

/** The design the seeder installs, kept in step with it by being the same shape. */
const DESIGN_FIXTURE = {
  id: "f", type: "frame", name: "Fixture", x: 0, y: 0, w: 800, h: 500, fill: "#f4efe6",
  children: [
    { id: "a", type: "rect", name: "Card", x: 60, y: 60, w: 300, h: 180, radius: 24, fill: "#1b2b4b" },
    { id: "b", type: "ellipse", name: "Sun", x: 520, y: 80, w: 160, h: 160, fill: "#ff7a3d",
      stroke: "#7a2a10", strokeWidth: 6 },
    { id: "c", type: "line", name: "Rule", x: 60, y: 300, w: 680, h: 0, stroke: "#333333", strokeWidth: 3 },
    { id: "e", type: "frame", name: "Tilted", x: 500, y: 330, w: 240, h: 120, fill: "#ffffff",
      radius: 12, rotation: 8, children: [
        { id: "g", type: "rect", name: "Chip", x: 16, y: 16, w: 60, h: 60, fill: "#6ea8ff", opacity: 0.7 }] },
  ],
};

/** Every SVG feature the compiler claims, in one file. */
const SVG_FIXTURE = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <defs>
    <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1b2b4b"/><stop offset="0.5" stop-color="#4a7fd4"/><stop offset="1" stop-color="#ff7a3d"/>
    </linearGradient>
    <radialGradient id="rg" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#fff3c4"/><stop offset="1" stop-color="#e0532a" stop-opacity="0.2"/>
    </radialGradient>
    <clipPath id="cp"><rect x="380" y="240" width="180" height="120"/></clipPath>
  </defs>
  <rect width="600" height="400" fill="#f4efe6"/>
  <rect x="30" y="30" width="240" height="140" rx="24" fill="url(#lg)"/>
  <circle cx="430" cy="100" r="70" fill="url(#rg)" stroke="#7a2a10" stroke-width="5"/>
  <path d="M 40 220 C 90 160, 170 300, 230 220 S 320 150, 350 230 Z" fill="#2f7d5b"/>
  <path d="M 60 300 q 40 -60 80 0 t 80 0" fill="none" stroke="#333" stroke-width="6"/>
  <path d="M 300 300 A 60 60 0 0 1 400 340 L 300 360 Z" fill="#b03a5b"/>
  <polygon points="480,30 540,150 420,150" fill="#5b3aa0" opacity="0.75"/>
  <g transform="translate(60,330) rotate(-8)"><rect width="150" height="46" rx="10" fill="#111"/></g>
  <rect x="360" y="220" width="220" height="160" fill="#0a7d8c" clip-path="url(#cp)"/>
  <path d="M 470 190 L 530 190 L 530 250 L 470 250 Z M 490 210 L 510 210 L 510 230 L 490 230 Z" fill="#d4a017" fill-rule="evenodd"/>
  <polyline points="40,380 80,360 120,380 160,360" fill="none" stroke="#1b2b4b" stroke-width="8" stroke-linejoin="miter" stroke-dasharray="14 6"/>
</svg>`;

// ------------------------------------------------------------------ helpers

async function rasteriseSvg(text, w, h) {
  const img = new Image();
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
  await img.decode();
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  c.getContext("2d").drawImage(img, 0, 0, w, h);
  return c.getContext("2d").getImageData(0, 0, w, h).data;
}

function compare(a, b, w, h, { skip = null, thresh = 60 } = {}) {
  let sum = 0, n = 0, off = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (skip && skip(x, y)) continue;
      const i = (y * w + x) * 4;
      const e = (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2])) / 3;
      sum += e; n++;
      if (e > thresh) off++;
    }
  }
  return { mean: +(sum / Math.max(1, n)).toFixed(2), off, pct: +((100 * off) / Math.max(1, n)).toFixed(3) };
}

/** The design's SVG, drawn the way the Design studio's export draws it. */
function designToSvg(frame) {
  const NS = "http://www.w3.org/2000/svg";
  const mk = (n) => {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("transform", `translate(${n.x} ${n.y})` +
      (n.rotation ? ` rotate(${n.rotation} ${n.w / 2} ${n.h / 2})` : ""));
    if (n.opacity !== undefined) g.setAttribute("opacity", n.opacity);
    const add = (t, a) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]);
      g.append(e); return e;
    };
    if (n.type === "frame") add("rect", { width: n.w, height: n.h, fill: n.fill || "#fff", rx: n.radius || 0 });
    else if (n.type === "rect") add("rect", { width: n.w, height: n.h, rx: n.radius || 0, fill: n.fill || "none",
      stroke: n.stroke || null, "stroke-width": n.strokeWidth || 0 });
    else if (n.type === "ellipse") add("ellipse", { cx: n.w / 2, cy: n.h / 2, rx: n.w / 2, ry: n.h / 2,
      fill: n.fill || "none", stroke: n.stroke || null, "stroke-width": n.strokeWidth || 0 });
    else if (n.type === "line") add("line", { x1: 0, y1: 0, x2: n.w, y2: n.h, stroke: n.stroke || "#000",
      "stroke-width": n.strokeWidth || 2, "stroke-linecap": "round" });
    for (const c of n.children || []) g.append(mk(c));
    return g;
  };
  const root = document.createElementNS(NS, "svg");
  root.setAttribute("xmlns", NS);
  root.setAttribute("width", frame.w); root.setAttribute("height", frame.h);
  root.setAttribute("viewBox", `0 0 ${frame.w} ${frame.h}`);
  const g = mk(frame); g.setAttribute("transform", "translate(0 0)");
  root.append(g);
  return new XMLSerializer().serializeToString(root);
}

// ------------------------------------------------------------------ the suite

/**
 * Run everything. `report(item)` is called as each result lands, so a dialog
 * can fill in as it goes; the returned array is the whole run.
 * item = { group, name, ok, detail }
 */
export async function runSelfTest(report = () => {}) {
  const results = [];
  const push = (item) => { results.push(item); report(item); };

  // A context of its own, so a failure here cannot disturb an open editor.
  const canvas = document.createElement("canvas");
  canvas.width = 64; canvas.height = 36;
  const gl = getGL(canvas);
  if (!gl) {
    push({ group: "GL", name: "context", ok: false, detail: "WebGL is not available" });
    return results;
  }
  const gl2 = isGL2(gl);
  push({ group: "GL", name: "context", ok: true,
         detail: gl2 ? "WebGL2 — sketches emit GLSL ES 3.00" : "WebGL1 — sketches emit GLSL ES 1.00" });
  const fb = new Feedback(gl);
  fb.resize(8, 8);
  push({ group: "GL", name: "feedback storage", ok: fb.kind === "float" || fb.kind === "half",
         detail: fb.describe() });
  fb.release();

  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);

  const draw = (prog, uniforms, values) => {
    gl.useProgram(prog);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    gl.uniform2f(u("u_resolution"), 64, 36);
    gl.uniform1f(u("u_time"), 1.3);
    gl.uniform1f(u("u_seed"), 2);
    gl.uniform2f(u("u_mouse"), 32, 18);
    applyUniforms(gl, prog, uniforms, values);
    gl.viewport(0, 0, 64, 36);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    const px = new Uint8Array(64 * 36 * 4);
    gl.readPixels(0, 0, 64, 36, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return px;
  };
  const colours = (px) => { const s = new Set(); for (let i = 0; i < px.length; i += 4) s.add((px[i] << 16) | (px[i + 1] << 8) | px[i + 2]); return s.size; };
  const differ = (a, b) => { let n = 0; for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) > 4) n++; return n; };

  // Sims start still or from a seed; what matters at compile time is that
  // both passes link and the picture draws something.
  for (const p of GENERATE_PRESETS) {
    try {
      const src = desugar(p.source, { es3: gl2 });
      const prog = linkProgram(gl, src);
      let simOk = "";
      if (hasSimPass(src)) { const sp = linkProgram(gl, withDefine(src, "SIM_PASS")); gl.deleteProgram(sp); simOk = " · sim pass links"; }
      const us = parseUniforms(p.source);
      const vals = {}; for (const u of us) vals[u.name] = u.value ? u.value.slice() : null;
      const a = draw(prog, us, vals);
      const nc = colours(a);
      let moves = "";
      const movable = us.filter((u) => u.control !== "image" && !u.hidden);
      // A feedback preset — sim or not — draws mostly what the last frame
      // held, and this probe gives it no last frame; its controls are judged
      // by compiling and drawing, not by moving.
      const feedsBack = hasSimPass(src)
        || /\b(?:u_prev|prev|prevAt)\s*\(|\bu_prev\b/.test(p.source.replace(/\/\/[^\n]*/g, ""));
      if (movable.length && !feedsBack) {
        randomise(us, vals);
        const b = draw(prog, us, vals);
        const d = differ(a, b);
        moves = ` · controls move ${d} px`;
        if (d < 20) throw new Error(`controls do nothing (${d} px changed)`);
      }
      gl.deleteProgram(prog);
      const flatOk = nc >= 6 || feedsBack;
      push({ group: "Generate presets", name: p.label, ok: flatOk,
             detail: `${nc} colours${simOk}${moves}${feedsBack && !simOk ? " · feedback" : ""}` + (flatOk ? "" : " — flat") });
    } catch (e) {
      push({ group: "Generate presets", name: p.label, ok: false, detail: String(e.message).split("\n")[0] });
    }
  }
  for (const p of SHADER_PRESETS) {
    try {
      const prog = linkProgram(gl, p.source);
      const us = parseUniforms(p.source);
      const vals = {}; for (const u of us) vals[u.name] = u.value ? u.value.slice() : null;
      const a = draw(prog, us, vals);
      gl.deleteProgram(prog);
      push({ group: "Shader presets (Book of Shaders, ES 1.00)", name: p.label, ok: true,
             detail: `${colours(a)} colours${isEs3(p.source) ? "" : " · 1.00 on " + (gl2 ? "WebGL2" : "WebGL1")}` });
    } catch (e) {
      push({ group: "Shader presets (Book of Shaders, ES 1.00)", name: p.label, ok: false, detail: String(e.message).split("\n")[0] });
    }
  }

  // The shape compilers, against the browser's own rasterisation. Thresholds
  // are the numbers the commits reported, with room.
  try {
    const t0 = performance.now();
    const out = await compileDesignFrame(DESIGN_FIXTURE);
    const truth = await rasteriseSvg(designToSvg(DESIGN_FIXTURE), 800, 500);
    await loadSketchImages(out.source);
    const rc = renderSketch(out.source, 800, 500, { time: 0 });
    const got = rc.getContext("2d").getImageData(0, 0, 800, 500).data;
    const r = compare(got, truth, 800, 500, { thresh: 40 });
    push({ group: "Design → shader", name: `${out.shapes} shapes, ${Math.round(performance.now() - t0)} ms`,
           ok: r.mean < 1.0 && r.pct < 0.05,
           detail: `mean ${r.mean}/255 · ${r.off} px off by >40 (${r.pct}%) · want <1.0 and <0.05%` });
  } catch (e) {
    push({ group: "Design → shader", name: "compile", ok: false, detail: String(e.message).split("\n")[0] });
  }
  try {
    const t0 = performance.now();
    const out = await compileSvg(SVG_FIXTURE, { name: "fixture.svg" });
    const truth = await rasteriseSvg(SVG_FIXTURE, 600, 400);
    await loadSketchImages(out.source);
    const rc = renderSketch(out.source, 600, 400, { time: 0 });
    const got = rc.getContext("2d").getImageData(0, 0, 600, 400).data;
    const r = compare(got, truth, 600, 400, { thresh: 50 });
    push({ group: "SVG → shader", name: `${out.shapes} shapes, ${out.edges} edges, ${Math.round(performance.now() - t0)} ms`,
           ok: r.mean < 4.0 && r.pct < 0.5,
           detail: `mean ${r.mean}/255 · ${r.off} px off by >50 (${r.pct}%) · want <4.0 and <0.5%` +
                   (out.notes.length ? ` · notes: ${out.notes.join("; ")}` : "") });
  } catch (e) {
    push({ group: "SVG → shader", name: "compile", ok: false, detail: String(e.message).split("\n")[0] });
  }
  // Text: the atlas against the browser's own text, at 1:1. Traced outlines,
  // since no font file is loaded here; the bar is set for that path.
  try {
    const W = 600, H = 120;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#f4efe6"/>
      <text x="20" y="80" font-family="system-ui, sans-serif" font-size="56" font-weight="600" fill="#101826">Hello world</text></svg>`;
    const t0 = performance.now();
    const out = await compileSvg(svg, { name: "text.svg" });
    const truth = await rasteriseSvg(svg, W, H);
    await loadSketchImages(out.source);
    const rc = renderSketch(out.source, W, H, { time: 0 });
    const got = rc.getContext("2d").getImageData(0, 0, W, H).data;
    const r = compare(got, truth, W, H, { thresh: 60 });
    push({ group: "Text → glyph atlas", name: `MSDF, traced outlines, ${Math.round(performance.now() - t0)} ms`,
           ok: r.mean < 4.0,
           detail: `mean ${r.mean}/255 · ${r.off} px off by >60 (${r.pct}%) · want <4.0` });
  } catch (e) {
    push({ group: "Text → glyph atlas", name: "compile", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The render graph: each proving node against a CPU reference computed the
  // same way, and the whole chain ejected as text that compiles.
  try {
    const W = 200, H = 120;
    const src = document.createElement("canvas"); src.width = W; src.height = H;
    const g = src.getContext("2d");
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#f4efe6"); gr.addColorStop(1, "#1b2b4b");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = "#ff7a3d"; g.beginPath(); g.arc(70, 60, 32, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#2f7d5b"; g.fillRect(120, 30, 50, 60);
    const srcData = g.getImageData(0, 0, W, H).data;
    const px = (c) => c.getContext("2d").getImageData(0, 0, W, H).data;
    const cmp = (a, b) => compare(a, b, W, H, { thresh: 8 });

    // exposure: +1 stop in linear light, done in JS the same way
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); gph.output = addNode(gph, "adjust.exposure", { stops: [1] }, [s0]);
      const got = px(renderGraph(gph, { [s0]: src }));
      const ref = new Uint8ClampedArray(srcData);
      const dec = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      const enc = (v) => { v = Math.min(1, Math.max(0, v)); return Math.round(255 * (v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055)); };
      for (let i = 0; i < ref.length; i += 4) for (let ch = 0; ch < 3; ch++) ref[i + ch] = enc(Math.pow(dec(srcData[i + ch]) * 2, 1) );
      // the node uses pow(2.2) approximations for speed; allow for that
      const r = cmp(got, ref);
      push({ group: "Render graph", name: "adjust.exposure vs CPU (+1 stop, linear)", ok: r.mean < 3.0,
             detail: `mean ${r.mean}/255 · ${r.off} px off by >8 · want <3.0 (the node uses the 2.2 approximation)` }); }
    // curves: identity LUT must be the identity, and a lift must lift
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); gph.output = addNode(gph, "adjust.curves", { curve: { points: [[0, 0], [1, 1]] } }, [s0]);
      const r = cmp(px(renderGraph(gph, { [s0]: src })), srcData);
      const gph2 = createGraph(W, H); const s1 = addNode(gph2, "source"); gph2.output = addNode(gph2, "adjust.curves", { curve: { points: [[0, 0.2], [1, 1]] } }, [s1]);
      const lifted = px(renderGraph(gph2, { [s1]: src }));
      let darkest = 255; for (let i = 0; i < lifted.length; i += 4) darkest = Math.min(darkest, lifted[i], lifted[i + 1], lifted[i + 2]);
      push({ group: "Render graph", name: "adjust.curves identity, and a black lift", ok: r.mean < 1.0 && darkest >= 45,
             detail: `identity mean ${r.mean}/255 · lifted floor ${darkest} (want ≥ 45 for a 0.2 lift)` }); }
    // blur: the CPU Gaussian is the reference, same sigma and kernel
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); gph.output = addBlur(gph, s0, 6);
      const got = px(renderGraph(gph, { [s0]: src }));
      const ref = blurFast(getImage(src), 6).data;
      const r = cmp(got, ref);
      push({ group: "Render graph", name: "filter.blur (two passes) vs engine-image blurFast, r=6", ok: r.mean < 1.5,
             detail: `mean ${r.mean}/255 · ${r.off} px off by >8 · want <1.5` }); }
    // blend: multiply of the image over itself is the square, in JS
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); const s1 = addNode(gph, "source");
      gph.output = addNode(gph, "composite.blend", { mode: [1], opacity: [1] }, [s0, s1]);
      const got = px(renderGraph(gph, { [s0]: src, [s1]: src }));
      const ref = new Uint8ClampedArray(srcData);
      for (let i = 0; i < ref.length; i += 4) for (let ch = 0; ch < 3; ch++) ref[i + ch] = Math.round(srcData[i + ch] * srcData[i + ch] / 255);
      const r = cmp(got, ref);
      push({ group: "Render graph", name: "composite.blend multiply vs CPU", ok: r.mean < 1.5,
             detail: `mean ${r.mean}/255 · ${r.off} px off by >8 · want <1.5` }); }
    // the chain, ejected: every pass is GLSL that links
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); const s1 = addNode(gph, "source");
      const e = addNode(gph, "adjust.exposure", { stops: [0.5] }, [s0]);
      const b = addBlur(gph, e, 4);
      gph.output = addNode(gph, "composite.blend", { mode: [2], opacity: [0.7] }, [b, s1]);
      renderGraph(gph, { [s0]: src, [s1]: src });
      const parts = ejectGraph(gph, { parts: true }).filter((p2) => p2.glsl);
      const text = ejectGraph(gph);
      let allLink = true, why = "";
      for (const part of parts) {
        try { const p2 = linkProgram(gl, part.glsl); gl.deleteProgram(p2); }
        catch (e) { allLink = false; why = `${part.type}: ${String(e.message).split("\n")[0]}`; }
      }
      push({ group: "Render graph", name: `eject: ${parts.length} passes, ${NODE_TYPES.size} node types registered`, ok: parts.length === 4 && allLink,
             detail: `${Math.round(text.length / 1024)} KB of GLSL${allLink ? ", every pass links on its own" : " — " + why}` }); }
  } catch (e) {
    push({ group: "Render graph", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  gl.deleteBuffer(quad);
  const lose = gl.getExtension("WEBGL_lose_context");
  if (lose) lose.loseContext();
  return results;
}

/** A dialog body that fills in as the run proceeds. */
export function selfTestPanel() {
  const list = el("div.stack", { style: { maxHeight: "60vh", overflow: "auto", gap: ".15rem" } });
  const summary = el("p.fine", {}, "Running…");
  const groups = new Map();
  let pass = 0, fail = 0;
  const report = (r) => {
    if (!groups.has(r.group)) {
      const g = el("div", {}, el("h4", { style: { margin: ".5rem 0 .2rem" } }, r.group));
      groups.set(r.group, g); list.append(g);
    }
    groups.get(r.group).append(el("div.row.tight", { style: { alignItems: "baseline" } },
      el("span", { style: { color: r.ok ? "var(--good, #5fd39a)" : "var(--bad, #f2708a)", minWidth: "1.4rem" } }, r.ok ? "✓" : "✗"),
      el("span", {}, r.name),
      el("span.fine", {}, r.detail)));
    if (r.ok) pass++; else fail++;
    summary.textContent = `${pass} passed, ${fail} failed`;
  };
  runSelfTest(report).then(() => {
    summary.textContent = `${pass} passed, ${fail} failed` + (fail ? " — a number that has drifted is a fact to look at" : "");
  }).catch((e) => { summary.textContent = `The run itself failed: ${e.message}`; });
  return el("div", {}, summary, list);
}
