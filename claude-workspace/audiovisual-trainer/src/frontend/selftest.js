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
import { renderGraph, ejectGraph, applyFilter } from "./graph-compile.js";
import { blurFast, getImage, FILTERS } from "./engine-image.js";
import { GRAPH_FILTERS } from "./filter-nodes.js";
import { planPasses, fuseStats, fusibleReason } from "./graph-fuse.js";
import { documentGraph, applyEffects, makeEffect, sketchEffect } from "./canvas-graph.js";
import { BLEND_ORDER } from "./composite-nodes.js";
import { clipAt, evalTrack, frameGraph, gradeEffects, putKey, sourceTimeAt } from "./video-graph.js";
import { parseCube } from "./lut-cube.js";
import { drawWaveform, drawHistogram, frameStats } from "./scopes.js";

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

  // Fusion: the same picture, fewer draws. Every check here compares the
  // fused result against the same graph run one pass per node — the fused
  // one is the more accurate of the two, since its intermediates never land
  // in a half-float buffer, so the bar is "indistinguishable", not "equal".
  try {
    const W = 200, H = 120;
    const src = document.createElement("canvas"); src.width = W; src.height = H;
    const g = src.getContext("2d");
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#f4efe6"); gr.addColorStop(1, "#1b2b4b");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = "#ff7a3d"; g.beginPath(); g.arc(70, 60, 32, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#2f7d5b"; g.fillRect(120, 30, 50, 60);
    const px = (c) => c.getContext("2d").getImageData(0, 0, W, H).data;
    const cmp = (a, b) => compare(a, b, W, H, { thresh: 8 });
    // Both renderings, and what the GPU was actually asked to draw — a fused
    // program that fails to link falls back to a pass per node, and the plan
    // alone would not show it.
    const both = (gph, sources) => {
      let drew = [];
      const fused = px(renderGraph(gph, sources, { onPasses: (ps) => { drew = ps; } }));
      return [fused, px(renderGraph(gph, sources, { fuse: false })), drew];
    };

    // Five adjustments in a row: one draw instead of five.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source");
      let last = addNode(gph, "adjust.grade", { lift: [0.02], gamma: [1.1], gain: [1.05], sat: [1.2] }, [s0]);
      last = addNode(gph, "adjust.hue", { deg: [40] }, [last]);
      last = addNode(gph, "adjust.duotone", { dark: [0.1, 0.05, 0.2], light: [1, 0.9, 0.7], amount: [0.6] }, [last]);
      last = addNode(gph, "filter.vignette", { amount: [0.4], softness: [0.6] }, [last]);
      gph.output = addNode(gph, "adjust.invert", {}, [last]);
      const st = fuseStats(gph);
      const [fused, plain, drew] = both(gph, { [s0]: src });
      const r = cmp(fused, plain);
      push({ group: "Fusion", name: "five adjustments fuse into one draw", ok: st.after === 1 && drew.length === 1 && r.mean < 1.0,
             detail: `${st.before} passes → ${drew.length} drawn · fused vs a pass per node: mean ${r.mean}/255, ${r.off} px off by >8 · want <1.0` }); }

    // A neighbourhood pass in the middle stops the run, and is not swallowed.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source");
      const a = addNode(gph, "adjust.grade", { gain: [1.1] }, [s0]);
      const b = addBlur(gph, a, 5);
      const c = addNode(gph, "adjust.invert", {}, [b]);
      gph.output = addNode(gph, "adjust.posterize", { levels: [6] }, [c]);
      const st = fuseStats(gph);
      const [fused, plain, drew] = both(gph, { [s0]: src });
      const r = cmp(fused, plain);
      const kept = st.kept.filter((k) => k.startsWith("filter.blur1d")).length;
      push({ group: "Fusion", name: "a @pass node breaks the run and keeps its own pass", ok: drew.length === 4 && kept === 2 && r.mean < 1.0,
             detail: `${st.before} → ${drew.length} drawn; the two blur passes stayed (${kept}) and the tail fused · mean ${r.mean}/255` }); }

    // A second input from outside the run stays a sampler, read at uv.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source"); const s1 = addNode(gph, "source");
      const e = addNode(gph, "adjust.exposure", { stops: [0.6] }, [s0]);
      gph.output = addNode(gph, "composite.blend", { mode: [1], opacity: [0.8] }, [e, s1]);
      const st = fuseStats(gph);
      const [fused, plain, drew] = both(gph, { [s0]: src, [s1]: src });
      const r = cmp(fused, plain);
      push({ group: "Fusion", name: "a two-input composite fuses, its other input stays a texture", ok: drew.length === 1 && r.mean < 1.0,
             detail: `${st.before} → ${drew.length} drawn · mean ${r.mean}/255 vs a pass per node` }); }

    // A LUT inside a fused run: the curve texture travels with its node.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source");
      const c = addNode(gph, "adjust.curves", { curve: { points: [[0, 0.1], [0.5, 0.4], [1, 1]] }, amount: [1] }, [s0]);
      gph.output = addNode(gph, "adjust.hue", { deg: [25] }, [c]);
      const st = fuseStats(gph);
      const [fused, plain, drew] = both(gph, { [s0]: src });
      const r = cmp(fused, plain);
      // and the curve is actually applied: a 0.1 lift means nothing stays black
      let darkest = 255;
      for (let i = 0; i < fused.length; i += 4) darkest = Math.min(darkest, fused[i]);
      push({ group: "Fusion", name: "a curve LUT survives fusion", ok: drew.length === 1 && r.mean < 1.0 && darkest >= 15,
             detail: `${st.before} → ${drew.length} drawn · mean ${r.mean}/255 · darkest ${darkest} (the 0.1 lift is there)` }); }

    // A run of every fusible catalogue filter at once — the stress case.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source");
      let last = s0, n = 0;
      for (const gf of GRAPH_FILTERS) {
        if (gf.cpuOnly || gf.id === "grain") continue;
        const probe = { width: W, height: H, nodes: [{ id: "p", type: "source", params: {}, inputs: [], bypass: false }], output: null };
        probe.output = gf.build(probe, "p", {});
        // only the single-node per-pixel ones belong in one chain
        const only = probe.nodes.filter((x) => x.type !== "source");
        if (only.length !== 1 || fusibleReason(only[0])) continue;
        last = addNode(gph, only[0].type, only[0].params, [last]); n++;
      }
      gph.output = last;
      const st = fuseStats(gph);
      const [fused, plain, drew] = both(gph, { [s0]: src });
      const r = cmp(fused, plain);
      push({ group: "Fusion", name: `${n} per-pixel filters chained`, ok: drew.length === 1 && r.mean < 2.0,
             detail: `${st.before} → ${drew.length} drawn · mean ${r.mean}/255 vs a pass per node (the fused one keeps full precision between filters) · want <2.0` }); }

    // The fused shader is what you read, and it links.
    { const gph = createGraph(W, H); const s0 = addNode(gph, "source");
      let last = addNode(gph, "adjust.grade", { sat: [1.3] }, [s0]);
      last = addNode(gph, "adjust.hue", { deg: [30] }, [last]);
      gph.output = addNode(gph, "filter.vignette", { amount: [0.5] }, [last]);
      renderGraph(gph, { [s0]: src });
      const parts = ejectGraph(gph, { parts: true }).filter((p2) => p2.glsl);
      const plain = ejectGraph(gph, { parts: true, fuse: false }).filter((p2) => p2.glsl);
      let ok = parts.length === 1 && plain.length === 3, why = "";
      for (const part of parts) {
        try { const p2 = linkProgram(gl, part.glsl); gl.deleteProgram(p2); }
        catch (e) { ok = false; why = String(e.message).split("\n")[0]; }
      }
      const body = parts[0] ? parts[0].glsl : "";
      const named = /f0_apply/.test(body) && /f1_apply/.test(body) && /f2_apply/.test(body);
      push({ group: "Fusion", name: "eject: one shader for three nodes, and it links", ok: ok && named,
             detail: ok ? `${plain.length} passes as written, 1 fused · ${Math.round(body.length / 1024)} KB, three apply() functions in it` : why || "wrong pass count" }); }

    // Fusion is a promise about sampling, and the promise is checked.
    { const declined = ["filter.blur1d", "filter.motion", "filter.pixelate", "filter.halftone"]
        .map((t) => [t, fusibleReason({ type: t, inputs: ["x"], params: {} })]);
      const allDeclined = declined.every(([, why]) => !!why);
      push({ group: "Fusion", name: "neighbourhood nodes decline to fuse", ok: allDeclined,
             detail: declined.map(([t, w]) => `${t.split(".")[1]}: ${w || "FUSED — should not have"}`).join(" · ") }); }
  } catch (e) {
    push({ group: "Fusion", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The catalogue: every CPU filter against its node, default parameters, on
  // a picture with edges, gradients, saturated colour and a dark region.
  try {
    const W = 160, H = 100;
    const src = document.createElement("canvas"); src.width = W; src.height = H;
    const g = src.getContext("2d");
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#fff8ee"); gr.addColorStop(1, "#0d1220");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = "#e04020"; g.beginPath(); g.arc(50, 50, 26, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#1fa36c"; g.fillRect(95, 20, 40, 60);
    g.fillStyle = "#3355ff"; g.fillRect(20, 78, 120, 8);
    g.fillStyle = "#ffffff"; g.fillRect(140, 8, 12, 12);
    const img = getImage(src);
    for (const gf of GRAPH_FILTERS) {
      const cpu = FILTERS.find((f) => f.id === gf.cpu);
      if (gf.cpuOnly) {
        push({ group: "Catalogue: CPU vs graph node", name: gf.name, ok: true, detail: `stays on the CPU — ${gf.cpuOnly}` });
        continue;
      }
      try {
        const params = {};
        for (const [name, , , def] of cpu.params) params[name] = def;
        for (const [name, def] of cpu.colors || []) params[name] = def;
        const t0 = performance.now();
        const ref = cpu.fn(img, params).data;
        const tc = performance.now() - t0;
        const t1 = performance.now();
        const got = applyFilter(src, gf, { ...params, seed: 3 }).getContext("2d").getImageData(0, 0, W, H).data;
        const tg = performance.now() - t1;
        if (gf.statistical) {
          // Grain: not the same noise, so the same statistics — the mean unmoved,
          // the spread of (got − source) near amount/√3.
          const base = img.data;
          let dm = 0, dv = 0, n = 0;
          for (let i = 0; i < got.length; i += 4) { const d = got[i] - base[i]; dm += d; dv += d * d; n++; }
          const mean = dm / n, sd = Math.sqrt(dv / n - mean * mean);
          const want = params.amount / Math.sqrt(3);
          const ok = Math.abs(mean) < 1.5 && Math.abs(sd - want) < want * 0.35;
          push({ group: "Catalogue: CPU vs graph node", name: gf.name, ok,
                 detail: `statistical: mean shift ${mean.toFixed(2)}, spread ${sd.toFixed(1)} (want ≈ ${want.toFixed(1)}) · cpu ${tc.toFixed(0)} ms, gpu ${tg.toFixed(0)} ms` });
          continue;
        }
        if (gf.id === "halftone") {
          // The CPU draws its dots through the canvas, whose rasteriser is a
          // law unto itself on two-pixel discs; the node's dot is exact area
          // (π r² to a tenth of a pixel). So compare tone — both softened by
          // three pixels — rather than edge pixels.
          const soft = (data) => blurFast(new ImageData(new Uint8ClampedArray(data), W, H), 3).data;
          const r = compare(soft(got), soft(ref), W, H, { thresh: 12 });
          push({ group: "Catalogue: CPU vs graph node", name: gf.name, ok: r.mean < 6,
                 detail: `tone (3 px soft) mean ${r.mean}/255 · want <6 — the canvas dot is the coarser of the two (±4% ink on two-pixel discs) · cpu ${tc.toFixed(0)} ms, gpu ${tg.toFixed(0)} ms` });
          continue;
        }
        const r = compare(got, ref, W, H, { thresh: 12 });
        // Tolerances: per-pixel maths should agree to a fraction of a level;
        // resampling filters differ by their rounding at edges.
        const tol = /motion|radial|lens|chromatic|pixelate/.test(gf.id) ? 2.5
                  : /edges|emboss/.test(gf.id) ? 2.0 : 1.2;
        push({ group: "Catalogue: CPU vs graph node", name: gf.name, ok: r.mean < tol,
               detail: `mean ${r.mean}/255 · ${r.off} px off by >12 (${r.pct}%) · want <${tol} · cpu ${tc.toFixed(0)} ms, gpu ${tg.toFixed(0)} ms` });
      } catch (e) {
        push({ group: "Catalogue: CPU vs graph node", name: gf.name, ok: false, detail: String(e.message).split("\n")[0] });
      }
    }
  } catch (e) {
    push({ group: "Catalogue: CPU vs graph node", name: "setup", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The document on the graph: the browser composites a canvas document, and
  // now so can the graph. The browser is the reference — these are its own
  // blend modes, so anything but agreement is a bug in the node.
  try {
    const W = 120, H = 80;
    const mk = (paint) => {
      const c = document.createElement("canvas"); c.width = W; c.height = H;
      paint(c.getContext("2d"));
      return c;
    };
    // A backdrop with every tone, and a layer with holes and soft edges.
    const back = mk((g) => {
      const gr = g.createLinearGradient(0, 0, W, 0);
      gr.addColorStop(0, "#0b0d12"); gr.addColorStop(0.5, "#8a6b4f"); gr.addColorStop(1, "#f7f2e8");
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
      g.fillStyle = "#2f7d5b"; g.fillRect(0, 50, W, 12);
      g.fillStyle = "#c03a2b"; g.beginPath(); g.arc(30, 25, 16, 0, Math.PI * 2); g.fill();
    });
    const over = mk((g) => {
      const gr = g.createLinearGradient(0, 0, 0, H);
      gr.addColorStop(0, "rgba(255,120,40,1)"); gr.addColorStop(1, "rgba(40,120,255,0.15)");
      g.fillStyle = gr; g.fillRect(10, 5, W - 20, H - 10);
      g.clearRect(45, 20, 22, 22);
      g.fillStyle = "rgba(255,255,255,0.55)"; g.beginPath(); g.arc(90, 55, 18, 0, Math.PI * 2); g.fill();
    });
    const mask = mk((g) => {
      g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
      g.clearRect(0, 0, 26, H);
      g.globalAlpha = 0.4; g.fillStyle = "#fff"; g.fillRect(26, 0, 18, H);
    });

    // The browser's own composite, which is what the graph has to reproduce.
    const composite2d = (layers, pixelsOf, maskOf) => {
      const c = document.createElement("canvas"); c.width = W; c.height = H;
      const g = c.getContext("2d");
      g.fillStyle = "#ffffff"; g.fillRect(0, 0, W, H);
      for (const l of layers) {
        if (!l.visible) continue;
        let px = pixelsOf(l);
        if (l.type === "adjust") {
          const below = document.createElement("canvas"); below.width = W; below.height = H;
          below.getContext("2d").drawImage(c, 0, 0);
          px = applyEffects(below, l.effects || []);
        } else if ((l.effects || []).length) {
          px = applyEffects(px, l.effects);
        }
        const m = maskOf(l);
        if (m) {
          const t = document.createElement("canvas"); t.width = W; t.height = H;
          const tg = t.getContext("2d");
          tg.drawImage(px, 0, 0);
          tg.globalCompositeOperation = "destination-in";
          tg.drawImage(m, 0, 0);
          px = t;
        }
        g.globalAlpha = l.opacity ?? 1;
        g.globalCompositeOperation = l.type === "adjust" ? "source-over" : (l.blend || "source-over");
        g.drawImage(px, 0, 0);
      }
      return c.getContext("2d").getImageData(0, 0, W, H).data;
    };
    const onGraph = (layers, pixelsOf, maskOf) => {
      const { graph, sources } = documentGraph(layers, { width: W, height: H, background: "#ffffff", pixelsOf, maskOf });
      return renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W, H).data;
    };

    // Every blend mode the layer panel offers, at an opacity that is not 1.
    const worst = [];
    for (const mode of BLEND_ORDER) {
      const layers = [
        { name: "back", visible: true, opacity: 1, blend: "source-over", type: "raster", effects: [] },
        { name: "over", visible: true, opacity: 0.8, blend: mode, type: "raster", effects: [] },
      ];
      const pixelsOf = (l) => (l.name === "back" ? back : over);
      const r = compare(onGraph(layers, pixelsOf, () => null), composite2d(layers, pixelsOf, () => null), W, H, { thresh: 6 });
      worst.push([mode, r.mean]);
    }
    worst.sort((a, b) => b[1] - a[1]);
    push({ group: "Canvas on the graph", name: `${BLEND_ORDER.length} blend modes vs the browser's own`,
           ok: worst[0][1] < 2.0,
           detail: `worst ${worst[0][0]} ${worst[0][1]}/255 · then ${worst.slice(1, 4).map(([m, v]) => `${m} ${v}`).join(", ")} · want <2.0` });

    // A mask, an effect stack and an adjustment layer — a document, not a pair.
    { const layers = [
        { name: "back", visible: true, opacity: 1, blend: "source-over", type: "raster", effects: [] },
        { name: "over", visible: true, opacity: 0.75, blend: "multiply", type: "raster",
          effects: [makeEffect("graph", "duotone", { dark: "#10203a", light: "#f2e3c0", amount: 0.7 }),
                    makeEffect("node", "adjust.exposure", { stops: [0.4] })] },
        { name: "adj", visible: true, opacity: 0.9, blend: "source-over", type: "adjust",
          effects: [makeEffect("graph", "vignette", { amount: 0.5, softness: 0.6 })] },
      ];
      const pixelsOf = (l) => (l.name === "back" ? back : over);
      const maskOf = (l) => (l.name === "over" ? mask : null);
      const r = compare(onGraph(layers, pixelsOf, maskOf), composite2d(layers, pixelsOf, maskOf), W, H, { thresh: 6 });
      push({ group: "Canvas on the graph", name: "a masked layer, a two-effect stack and an adjustment layer",
             ok: r.mean < 2.0,
             detail: `mean ${r.mean}/255 · ${r.off} px off by >6 (${r.pct}%) · want <2.0 — the roadmap's own bar for this phase` }); }

    // And the whole thing ejects as GLSL that links.
    { const layers = [
        { name: "back", visible: true, opacity: 1, blend: "source-over", type: "raster", effects: [] },
        { name: "over", visible: true, opacity: 0.8, blend: "soft-light", type: "raster",
          effects: [makeEffect("graph", "grade", { lift: 0.02, gamma: 1.1, gain: 1.05, sat: 1.2 })] },
      ];
      const { graph } = documentGraph(layers, { width: W, height: H, background: "#ffffff",
        pixelsOf: (l) => (l.name === "back" ? back : over), maskOf: () => null });
      const parts = ejectGraph(graph, { parts: true }).filter((p2) => p2.glsl);
      let ok = parts.length > 0, why = "";
      for (const part of parts) {
        try { const p2 = linkProgram(gl, part.glsl); gl.deleteProgram(p2); }
        catch (e) { ok = false; why = String(e.message).split("\n")[0]; }
      }
      const text = ejectGraph(graph);
      push({ group: "Canvas on the graph", name: "the document ejects as GLSL, and every pass links", ok,
             detail: ok ? `${parts.length} passes, ${Math.round(text.length / 1024)} KB — a document, compiled` : why }); }
  } catch (e) {
    push({ group: "Canvas on the graph", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Video on the graph: the grade is the CSS filter functions, so the browser
  // is again the reference; the keyframes are pure; and an export has to be
  // repeatable, which is the phase's own bar.
  try {
    const W = 160, H = 100;
    const paint = (c, a, b) => {
      const g = c.getContext("2d");
      const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, a); gr.addColorStop(1, b);
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
      g.fillStyle = "#e04020"; g.beginPath(); g.arc(50, 50, 26, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#1fa36c"; g.fillRect(95, 20, 40, 60);
      return c;
    };
    const mk = (a, b) => paint(Object.assign(document.createElement("canvas"), { width: W, height: H }), a, b);
    const shotA = mk("#fff2dd", "#101a2e"), shotB = mk("#dfe9ff", "#2e1010");

    // The grade, against the browser's own filter string.
    { const cases = [
        { brightness: 1.25, contrast: 1, saturate: 1, hue: 0, blur: 0 },
        { brightness: 1, contrast: 1.6, saturate: 1, hue: 0, blur: 0 },
        { brightness: 1, contrast: 1, saturate: 1.8, hue: 0, blur: 0 },
        { brightness: 1, contrast: 1, saturate: 1, hue: 75, blur: 0 },
        { brightness: 1.1, contrast: 1.2, saturate: 1.3, hue: -40, blur: 0 },
        { brightness: 1, contrast: 1, saturate: 1, hue: 0, blur: 4 },
        { brightness: 1.1, contrast: 1.15, saturate: 1.2, hue: 20, blur: 6 },
      ];
      let worst = 0, worstName = "";
      for (const g2 of cases) {
        const ref = document.createElement("canvas"); ref.width = W; ref.height = H;
        const rg = ref.getContext("2d");
        rg.filter = `brightness(${g2.brightness}) contrast(${g2.contrast}) saturate(${g2.saturate}) `
                  + `hue-rotate(${g2.hue}deg)` + (g2.blur ? ` blur(${g2.blur}px)` : "");
        rg.drawImage(shotA, 0, 0);
        const got = applyEffects(shotA, gradeEffects(g2, 1)).getContext("2d").getImageData(0, 0, W, H).data;
        // The browser's blur handles the frame edge its own way; judge the middle.
        const r = compare(got, rg.getImageData(0, 0, W, H).data, W, H,
          { thresh: 6, skip: (x, y) => x < 12 || y < 12 || x >= W - 12 || y >= H - 12 });
        if (r.mean > worst) { worst = r.mean; worstName = `b${g2.brightness} c${g2.contrast} s${g2.saturate} h${g2.hue} blur${g2.blur}`; }
      }
      push({ group: "Video on the graph", name: "the grade, against the browser's own CSS filters", ok: worst < 2.0,
             detail: `worst ${worst}/255 on ${worstName} · want <2.0 — a CSS blur is three box blurs, and these are the same three` }); }

    // Keyframes are arithmetic, so they can simply be checked.
    { const tr = putKey(putKey(putKey([], 0, 0), 1, 10), 2, 10, "hold");
      const linear = evalTrack(tr, 0.5) === 5;
      const holdsBefore = evalTrack(tr, -3) === 0, holdsAfter = evalTrack(tr, 9) === 10;
      const smooth = putKey(putKey([], 0, 0, "smooth"), 1, 10);
      const sm = evalTrack(smooth, 0.25);
      const held = putKey(putKey([], 0, 0, "hold"), 1, 10);
      const hd = evalTrack(held, 0.99) === 0 && evalTrack(held, 1) === 10;
      const ok = linear && holdsBefore && holdsAfter && hd && Math.abs(sm - 1.5625) < 1e-6;
      push({ group: "Video on the graph", name: "keyframe tracks: linear, smooth, hold, and holding at the ends", ok,
             detail: `midpoint ${evalTrack(tr, 0.5)} · smooth at ¼ ${sm.toFixed(4)} (want 1.5625) · hold jumps at its next key · ` +
                     `before the first key ${evalTrack(tr, -3)}, after the last ${evalTrack(tr, 9)}` }); }

    // The bar for this phase: a grade keyframed across a cut, exported twice.
    { const clipA = { id: "a", kind: "video", start: 0, dur: 2, opacity: 1, fadeIn: 0, fadeOut: 0.4,
                      grade: { brightness: 1, contrast: 1, saturate: 1, hue: 0, blur: 0 },
                      keys: { "grade.brightness": [{ t: 0, v: 0.7, ease: "linear" }, { t: 2, v: 1.4, ease: "linear" }] },
                      effects: [] };
      const clipB = { id: "b", kind: "video", start: 1.6, dur: 2, opacity: 1, fadeIn: 0, fadeOut: 0,
                      grade: { brightness: 1, contrast: 1, saturate: 1.2, hue: 0, blur: 0 },
                      keys: { "grade.hue": [{ t: 0, v: -30, ease: "smooth" }, { t: 2, v: 60, ease: "smooth" }] },
                      transition: { mode: 0 }, effects: [] };
      const fade = (c, local) => {
        let a = c.opacity ?? 1;
        if (c.fadeIn > 0) a *= Math.min(1, Math.max(0, local / c.fadeIn));
        if (c.fadeOut > 0) a *= Math.min(1, Math.max(0, (c.dur - local) / c.fadeOut));
        return a;
      };
      const frameAt = (t) => {
        const entries = [];
        for (const [clip, pixels] of [[clipA, shotA], [clipB, shotB]]) {
          if (t < clip.start || t >= clip.start + clip.dur) continue;
          const local = t - clip.start;
          const at = clipAt(clip, local);
          const overlap = clip === clipB ? (clipA.start + clipA.dur) - clipB.start : 0;
          const transition = (clip === clipB && overlap > 0 && t < clipA.start + clipA.dur)
            ? { mode: 0, progress: Math.min(1, Math.max(0, (t - clip.start) / overlap)), angle: 0, softness: 0.08, colour: [0, 0, 0] }
            : null;
          entries.push({ clip: at, pixels, transition });
        }
        const { graph, sources } = frameGraph(entries, { width: W, height: H, background: "#000000",
          scale: 1, alphaOf: (c) => fade(c, 0.5) });
        return renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W, H).data;
      };
      const times = [0, 0.5, 1.0, 1.7, 1.9, 2.2, 3.0];
      const pass1 = times.map(frameAt);
      const pass2 = times.map(frameAt);
      let identical = true, moved = 0;
      for (let i = 0; i < times.length; i++) {
        for (let k = 0; k < pass1[i].length; k++) if (pass1[i][k] !== pass2[i][k]) { identical = false; break; }
      }
      for (let k = 0; k < pass1[0].length; k += 4) if (pass1[0][k] !== pass1[2][k]) { moved++; }
      push({ group: "Video on the graph", name: "a grade keyframed across a cut exports identically twice", ok: identical && moved > 1000,
             detail: identical ? `${times.length} frames, byte for byte, twice over — and ${moved} pixels differ between t=0 and t=1, so the key really moved`
                               : "two passes over the same frames disagreed" }); }

    // And a Generate sim as a clip effect.
    { const preset = GENERATE_PRESETS.find((p2) => p2.id === "clipink");
      const values = {};
      for (const u of parseUniforms(preset.source)) if (u.control !== "image") values[u.name] = u.value.slice();
      const eff = sketchEffect(preset.source, values, 0.4, preset.label, preset.steps);
      const once = applyEffects(shotA, [eff]).getContext("2d").getImageData(0, 0, W, H).data;
      const twice = applyEffects(shotA, [eff]).getContext("2d").getImageData(0, 0, W, H).data;
      let same = true, differs = 0;
      const base = shotA.getContext("2d").getImageData(0, 0, W, H).data;
      for (let k = 0; k < once.length; k++) if (once[k] !== twice[k]) { same = false; break; }
      for (let k = 0; k < once.length; k += 4) if (Math.abs(once[k] - base[k]) > 6) differs++;
      push({ group: "Video on the graph", name: "a Generate sim runs as a clip effect, and repeats", ok: same && differs > 500,
             detail: same ? `${preset.steps} steps a frame, seeded from the clip · ${differs} pixels changed by it · identical when run again`
                          : "the same frame came out differently the second time" }); }

    // A LUT: an identity cube must change nothing, and a known one must do
    // exactly what it says.
    { const n = 17;
      const idLines = [`LUT_3D_SIZE ${n}`];
      const swapLines = [`TITLE "swap"`, `LUT_3D_SIZE ${n}`];
      for (let b = 0; b < n; b++) for (let g = 0; g < n; g++) for (let r = 0; r < n; r++) {
        const R = r / (n - 1), G = g / (n - 1), B = b / (n - 1);
        idLines.push(`${R} ${G} ${B}`);
        swapLines.push(`${B} ${R} ${G}`);          // rgb -> bgr rotated, an unmistakable change
      }
      const idc = parseCube(idLines.join("\n"));
      const swap = parseCube(swapLines.join("\n"));
      const lutFx = (lut) => ({ id: "l", kind: "lut", bypass: false, lut, params: { amount: 1 } });
      const base = shotA.getContext("2d").getImageData(0, 0, W, H).data;
      const same = applyEffects(shotA, [lutFx(idc)]).getContext("2d").getImageData(0, 0, W, H).data;
      const rot = applyEffects(shotA, [lutFx(swap)]).getContext("2d").getImageData(0, 0, W, H).data;
      const rIdent = compare(same, base, W, H, { thresh: 6 });
      // the rotation, done in JS on the same pixels
      const want = new Uint8ClampedArray(base);
      for (let i = 0; i < want.length; i += 4) {
        want[i] = base[i + 2]; want[i + 1] = base[i]; want[i + 2] = base[i + 1];
      }
      const rSwap = compare(rot, want, W, H, { thresh: 6 });
      push({ group: "Video on the graph", name: `a ${n}³ .cube: identity changes nothing, a known cube does what it says`,
             ok: rIdent.mean < 1.5 && rSwap.mean < 3.0,
             detail: `identity ${rIdent.mean}/255 · a channel rotation ${rSwap.mean}/255 against the same thing in JS ` +
                     `(a ${n}-cube quantises, so a little is expected) · want <1.5 and <3.0` }); }

    // Speed ramps: a constant multiplies, a ramp integrates.
    { const flat = { in: 2, speed: 2, dur: 4 };
      const constOk = Math.abs(sourceTimeAt(flat, 3) - 8) < 1e-6;
      // 1x to 3x linearly over 4s covers the mean of the ramp, not either end
      const ramp = { in: 0, dur: 4, keys: { speed: [{ t: 0, v: 1, ease: "linear" }, { t: 4, v: 3, ease: "linear" }] } };
      const at4 = sourceTimeAt(ramp, 4);
      const rampOk = Math.abs(at4 - 8) < 0.02;
      const monotone = sourceTimeAt(ramp, 1) < sourceTimeAt(ramp, 2) && sourceTimeAt(ramp, 2) < at4;
      push({ group: "Video on the graph", name: "speed: a constant multiplies, a ramp integrates", ok: constOk && rampOk && monotone,
             detail: `2× from 2s reaches ${sourceTimeAt(flat, 3).toFixed(3)}s (want 8) · a 1×→3× ramp over 4s covers ` +
                     `${at4.toFixed(3)}s of source (want 8, the mean rate — not 4 and not 12)` }); }

    // The scopes read the frame, so they have to agree with what is in it.
    { const flat = document.createElement("canvas"); flat.width = 64; flat.height = 64;
      const fg2 = flat.getContext("2d");
      fg2.fillStyle = "#000"; fg2.fillRect(0, 0, 64, 32);
      fg2.fillStyle = "#fff"; fg2.fillRect(0, 32, 64, 32);
      const img = fg2.getImageData(0, 0, 64, 64);
      const st = frameStats(img);
      const wave = document.createElement("canvas"); wave.width = 120; wave.height = 60;
      const hist = document.createElement("canvas"); hist.width = 120; hist.height = 60;
      drawWaveform(img, wave); drawHistogram(img, hist);
      const wd = wave.getContext("2d").getImageData(0, 0, 120, 60).data;
      // half black and half white: a trace at the very top and the very bottom, nothing between
      let top = 0, mid = 0, bot = 0;
      for (let x = 0; x < 120; x++) {
        if (wd[(0 * 120 + x) * 4 + 1] > 40) top++;
        if (wd[(30 * 120 + x) * 4 + 1] > 40) mid++;
        if (wd[(59 * 120 + x) * 4 + 1] > 40) bot++;
      }
      const ok = Math.abs(st.mean - 0.5) < 0.02 && st.crushed > 0.45 && st.clipped > 0.45 && top > 100 && bot > 100 && mid === 0;
      push({ group: "Video on the graph", name: "the scopes measure the frame they are given", ok,
             detail: `half black, half white: mean ${(st.mean * 100).toFixed(0)} IRE, ${(st.crushed * 100).toFixed(0)}% crushed, ` +
                     `${(st.clipped * 100).toFixed(0)}% clipped · the waveform has ${top} columns at the top, ${bot} at the bottom, ${mid} in the middle` }); }

    // The transition node at its two ends is the two clips, exactly.
    { const two = (progress) => {
        const entries = [
          { clip: { grade: {}, effects: [], opacity: 1, start: 0 }, pixels: shotA },
          { clip: { grade: {}, effects: [], opacity: 1, start: 0 }, pixels: shotB,
            transition: { mode: 0, progress, angle: 0, softness: 0.08, colour: [0, 0, 0] } },
        ];
        const { graph, sources } = frameGraph(entries, { width: W, height: H, background: "#000000",
          scale: 1, alphaOf: () => 1 });
        return renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W, H).data;
      };
      const a0 = compare(two(0), shotA.getContext("2d").getImageData(0, 0, W, H).data, W, H, { thresh: 6 });
      const a1 = compare(two(1), shotB.getContext("2d").getImageData(0, 0, W, H).data, W, H, { thresh: 6 });
      push({ group: "Video on the graph", name: "a dissolve at 0 and 1 is exactly the two clips", ok: a0.mean < 1 && a1.mean < 1,
             detail: `at 0 it is the outgoing frame (${a0.mean}/255), at 1 the incoming one (${a1.mean}/255)` }); }
  } catch (e) {
    push({ group: "Video on the graph", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
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
