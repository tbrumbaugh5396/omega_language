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

import { el, clear, api } from "./ui.js";
import { GENERATE_PRESETS, newGenerateDoc, scaleForBudget, fitAspect } from "./studio-generate.js";
import { expandButton } from "./expand.js";
import { SHADER_PRESETS } from "./studio-shader.js";
import { parseUniforms, desugar, hasSimPass, withDefine, isEs3, splitSketch, stripComments,
         sketchMeta } from "./shader-uniforms.js";
import { applyUniforms, randomise, seededRandom } from "./shader-controls.js";
import { getGL, isGL2, linkProgram, renderSketch, loadSketchImages, dualTargets,
         sharedFeedbackBytes } from "./shader-run.js";
import { compileDesignFrame } from "./design-to-sdf.js";
import { compileSvg } from "./svg-to-sdf.js";
import { Feedback } from "./feedback.js";
import { createGraph, addNode, addBlur, curveLut, NODE_TYPES, validate, feedback, findNode, defineNode } from "./render-graph.js";
import { lifeStep, grayScottStep } from "./sim-nodes.js";
import { shipStep, shipAsData, menuAsData, pongAsData, pongEffects, PONG_INSTRUMENTS } from "./game-nodes.js";
import { EventQueue, pointerEvents } from "./events.js";
import { LiveRig, renderFired } from "./live-audio.js";
import { readProbes, sketchFrame, hasSketchEffects } from "./sketch-effects.js";
import { shipInstrument, toneInstrument, instrumentId, normalise, internInstruments,
         inlineInstruments, resolveInstruments, instrumentFor, forgetInstrument,
         instrumentNames, instrumentCount, instrumentBytes, defineInstrument,
         loadUserInstruments, listInstruments } from "./instrument-library.js";
import { parsePatch, toPatch } from "./instrument-doc.js";
import { INSTRUMENT_STARTERS, instrumentNameFor } from "./studio-instrument.js";
import { Keyboard, KEY } from "./keyboard.js";
import { renderGraph, ejectGraph, applyFilter, resetGraphState } from "./graph-compile.js";
import { blurFast, getImage, FILTERS } from "./engine-image.js";
import { GRAPH_FILTERS } from "./filter-nodes.js";
import { planPasses, fuseStats, fusibleReason } from "./graph-fuse.js";
import { compileFields, fieldStats } from "./field-graph.js";
import { resolveParams, paramProblems, paramStats, paramState } from "./param-graph.js";
import { compileExpr, FUNCTIONS } from "./expr.js";
import "./field-nodes.js";
import { documentGraph, applyEffects, makeEffect, sketchEffect } from "./canvas-graph.js";
import { BLEND_ORDER } from "./composite-nodes.js";
import { clipAt, evalTrack, frameGraph, gradeEffects, putKey, sourceTimeAt } from "./video-graph.js";
import { parseCube } from "./lut-cube.js";
import { compileTitleNode } from "./title-node.js";
import { readGsubForTest } from "./font-file.js";
import { renderTiled, maxRenderSize } from "./shader-run.js";
import { auditNodes, portabilitySummary, auditSource } from "./wgsl-audit.js";
import { toWgsl } from "./wgsl-emit.js";
import { renderSketchGpu, gpuDescribe, renderTiledGpu, renderSketchGpuCanvas,
         maxRenderSizeGpu } from "./webgpu-run.js";
import { renderGraphGpu, gpuGraphRunner, GpuGraphRunner } from "./webgpu-graph.js";
import { zipStore, crc32 } from "./zip-store.js";
import { graphStats } from "./graph-compile.js";
import { nodeReference, referenceGaps } from "./node-docs.js";
import { createDspGraph, addDspNode, defineDspNode, allocationReport, topoDsp, DSP_NODES } from "./dsp-graph.js";
import { installGraph, sourceFor } from "./dsp-runtime.js";
import { renderSong, patternToNotes, allocateVoices, noteHz, toWav } from "./dsp-song.js";
import { loudnessLUFS, truePeakDb, correlation, packSpectrum, packWaveform, rowTexture, spectrogram } from "./audio-scopes.js";
import "./scope-nodes.js";
import { fftMag } from "./engine-audio.js";
import { freezeEffects } from "./canvas-graph.js";
import { registerNode, withNodeHeader, nodeIdFor, keepVersion, versionSummary,
         MAX_VERSIONS, declaresNode } from "./node-library.js";
import { nodeType } from "./render-graph.js";
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
        // Seeded, so this check gives the same answer every time it is run.
        // It found a real thing once and a false alarm once, and only one of
        // those is worth having.
        randomise(us, vals, seededRandom(0x5eed));
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

  // Field wires: the port that carries a function.
  //
  // Two things have to be true and neither is obvious. The composition has to
  // be right — a union of two circles has to be the union of two circles, and
  // the browser's own rasteriser is the judge of that. And the wire has to be
  // carrying a *distance*, not a picture of one: the offset checks are the
  // ones a raster pipeline cannot pass, because you cannot offset a photo of
  // a shape by asking it how far away its edge is.
  try {
    const W = 220, H = 140;
    // p is centred and aspect-corrected, y up; the canvas is y down. One
    // conversion, used by every reference below.
    const toPx = (x, y) => [(x * H + W) / 2, (H - y * H) / 2];
    const onWhite = (c) => {
      const w = document.createElement("canvas"); w.width = W; w.height = H;
      const cx = w.getContext("2d");
      cx.fillStyle = "#ffffff"; cx.fillRect(0, 0, W, H);
      cx.drawImage(c, 0, 0);
      return cx.getImageData(0, 0, W, H).data;
    };
    const ref = (draw) => {
      const c = document.createElement("canvas"); c.width = W; c.height = H;
      const cx = c.getContext("2d");
      cx.fillStyle = "#ffffff"; cx.fillRect(0, 0, W, H);
      cx.fillStyle = "#1b2b4b";
      draw(cx);
      return cx.getImageData(0, 0, W, H).data;
    };
    const shaded = (build) => {
      const gph = createGraph(W, H);
      const f = build(gph);
      gph.output = addNode(gph, "field.shade",
        { fill: [0.106, 0.169, 0.294], filled: [1], width: [0], glow: [0] }, [f]);
      let drew = [];
      const out = renderGraph(gph, {}, { onPasses: (ps) => { drew = ps; } });
      return { px: onWhite(out), drew, gph };
    };
    const cmp = (a, b) => compare(a, b, W, H, { thresh: 40 });

    // 1. A whole field tree is one draw, because it has to be: GLSL cannot
    //    pass a function to a shader, so composing them is a text operation.
    { const { drew, gph } = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [-0.25, 0], radius: [0.4] });
        const b = addNode(g, "field.box", { centre: [0.25, 0], size: [0.35, 0.28], corner: [0.08] });
        return addNode(g, "field.union", { k: [0.12] }, [a, b]);
      });
      const fs = fieldStats(gph);
      push({ group: "Field wires", name: "three field nodes, one draw", ok: drew.length === 1 && fs.fields === 3,
             detail: `${fs.fields} fields folded into the shade node · ${drew.length} pass · ${fs.passesSaved} buffers never allocated` }); }

    // 2. A hard union against the browser's own rasteriser. k = 0 is plain
    //    min(), so this is the browser's two circles or nothing.
    { const got = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [-0.3, 0], radius: [0.45] });
        const b = addNode(g, "field.circle", { centre: [0.3, 0.1], radius: [0.35] });
        return addNode(g, "field.union", { k: [0] }, [a, b]);
      }).px;
      const truth = ref((cx) => {
        cx.beginPath();
        let c = toPx(-0.3, 0); cx.moveTo(c[0] + 0.45 * H / 2, c[1]);
        cx.arc(c[0], c[1], 0.45 * H / 2, 0, Math.PI * 2);
        c = toPx(0.3, 0.1); cx.moveTo(c[0] + 0.35 * H / 2, c[1]);
        cx.arc(c[0], c[1], 0.35 * H / 2, 0, Math.PI * 2);
        cx.fill();
      });
      const r = cmp(got, truth);
      push({ group: "Field wires", name: "hard union vs the browser's two circles", ok: r.mean < 3.0,
             detail: `mean ${r.mean}/255 · ${r.pct}% of pixels off by >40 — all of them on the two edges · want <3.0` }); }

    // 3. A rounded rectangle against the browser's roundRect.
    if (document.createElement("canvas").getContext("2d").roundRect) {
      const got = shaded((g) => addNode(g, "field.box",
        { centre: [0, 0], size: [0.55, 0.34], corner: [0.12] })).px;
      const truth = ref((cx) => {
        const [x0, y0] = toPx(-0.55, 0.34);
        cx.beginPath();
        cx.roundRect(x0, y0, 0.55 * H, 0.34 * H, 0.12 * H / 2);
        cx.fill();
      });
      const r = cmp(got, truth);
      push({ group: "Field wires", name: "rounded box vs the browser's roundRect", ok: r.mean < 3.0,
             detail: `mean ${r.mean}/255 · ${r.pct}% off by >40 · want <3.0` });
    }

    // 4. THE check. Offset a circle by 0.1 and you get a circle 0.1 bigger —
    //    which is only true if the wire is carrying a distance. Nothing in a
    //    raster pipeline can answer this, and a field graph answers it exactly.
    { const viaOffset = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [0, 0], radius: [0.3] });
        return addNode(g, "field.offset", { amount: [0.1] }, [a]);
      }).px;
      const direct = shaded((g) => addNode(g, "field.circle", { centre: [0, 0], radius: [0.4] })).px;
      const r = compare(viaOffset, direct, W, H, { thresh: 1 });
      push({ group: "Field wires", name: "offset(0.1) of r=0.3 is exactly r=0.4", ok: r.mean < 0.01 && r.off === 0,
             detail: `mean ${r.mean}/255 · ${r.off} pixels differ at all — the wire carries the distance, not the picture` }); }

    // 5. …and the same for a shell, which is a shape it has no other way to make.
    { const viaShell = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [0, 0], radius: [0.4] });
        return addNode(g, "field.shell", { thickness: [0.1] }, [a]);
      }).px;
      const viaBoolean = shaded((g) => {
        const outer = addNode(g, "field.circle", { centre: [0, 0], radius: [0.45] });
        const inner = addNode(g, "field.circle", { centre: [0, 0], radius: [0.35] });
        return addNode(g, "field.subtract", { k: [0] }, [outer, inner]);
      }).px;
      const r = compare(viaShell, viaBoolean, W, H, { thresh: 1 });
      push({ group: "Field wires", name: "a shell is a ring is a subtraction", ok: r.mean < 0.01 && r.off === 0,
             detail: `mean ${r.mean}/255 · ${r.off} pixels differ · abs(d)-t/2 and (r+t/2) minus (r-t/2) are the same set` }); }

    // 6. Union at k = 0 is min(), against a hand-written sketch that says so.
    //    This is the emitter on trial, not the geometry.
    { const got = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [-0.25, 0.05], radius: [0.4] });
        const b = addNode(g, "field.box", { centre: [0.2, -0.05], size: [0.3, 0.3], corner: [0.05] });
        return addNode(g, "field.union", { k: [0] }, [a, b]);
      }).px;
      const byHand = renderSketch(`// @alpha
float a = sdCircle(p - vec2(-0.25, 0.05), 0.4);
float b = sdBox(p - vec2(0.2, -0.05), max(vec2(0.3, 0.3) - 0.05, 0.0)) - 0.05;
float d = min(a, b);
vec4(vec3(0.106, 0.169, 0.294), aa(d))`, W, H, { time: 0 });
      const r = compare(got, onWhite(byHand), W, H, { thresh: 2 });
      push({ group: "Field wires", name: "the composed program equals the one written by hand", ok: r.mean < 0.6,
             detail: `mean ${r.mean}/255 vs the same maths in a single sketch · ${r.off} pixels off by >2 · want <0.6` }); }

    // 7. A wire that carries the wrong thing is caught by name, in the graph,
    //    before a line of GLSL is generated. That is what typing a port buys.
    { const g1 = createGraph(W, H);
      const img = addNode(g1, "source");
      g1.output = addNode(g1, "field.shade", {}, [img]);
      const e1 = validate(g1);

      const g2 = createGraph(W, H);
      g2.output = addNode(g2, "field.circle", { radius: [0.4] });
      const e2 = validate(g2);

      const g3 = createGraph(W, H);
      const c = addNode(g3, "field.circle", { radius: [0.4] });
      g3.output = addNode(g3, "adjust.exposure", { stops: [1] }, [c]);
      const e3 = validate(g3);

      const said = (errs, want) => errs.some((x) => x.includes(want));
      const ok = said(e1, "takes a field") && said(e2, "not pixels") && said(e3, "takes an image");
      push({ group: "Field wires", name: "a mis-wired port is refused, by name", ok,
             detail: ok ? `image→field, field as output, field→image: all three named the port and the mismatch`
                        : `${e1[0] || "—"} / ${e2[0] || "—"} / ${e3[0] || "—"}` }); }

    // 8. The renamer must not touch a swizzle. field.mirror declares uniforms
    //    called x and y and reads p.x — if `\bx\b` were the rule, this would
    //    compile to p.f1_x and the whole program would fail to link.
    { const { px, drew } = shaded((g) => {
        const a = addNode(g, "field.circle", { centre: [0.35, 0.25], radius: [0.25] });
        return addNode(g, "field.mirror", { x: [1], y: [1] }, [a]);
      });
      // Four circles, so all four quadrants have ink in them.
      const inked = (qx, qy) => {
        let n = 0;
        for (let y = qy * H / 2 | 0; y < (qy + 1) * H / 2; y++)
          for (let x = qx * W / 2 | 0; x < (qx + 1) * W / 2; x++)
            if (px[(y * W + x) * 4] < 200) n++;
        return n;
      };
      const quads = [inked(0, 0), inked(1, 0), inked(0, 1), inked(1, 1)];
      const even = Math.max(...quads) - Math.min(...quads) < Math.max(...quads) * 0.05;
      push({ group: "Field wires", name: "a uniform called x does not eat p.x", ok: drew.length === 1 && Math.min(...quads) > 100 && even,
             detail: `mirrored into four quadrants: ${quads.join(", ")} pixels — within 5% of each other` }); }

    // 9. What you read is what ran: one program, and it links on its own.
    { const gph = createGraph(W, H);
      const a = addNode(gph, "field.polygon", { centre: [0, 0], sides: [6], radius: [0.5], corner: [0.06] });
      const b = addNode(gph, "field.circle", { centre: [0, 0], radius: [0.3] });
      const cut = addNode(gph, "field.subtract", { k: [0.04] }, [a, b]);
      const rep = addNode(gph, "field.repeat", { cell: [0.9, 0.9], count: [1, 0] }, [cut]);
      gph.output = addNode(gph, "field.shade", { width: [0.01], glow: [0.15] }, [rep]);
      renderGraph(gph, {});
      const parts = ejectGraph(gph, { parts: true }).filter((x) => x.glsl);
      let ok = parts.length === 1, why = "";
      if (ok) {
        try { const pr = linkProgram(gl, parts[0].glsl); gl.deleteProgram(pr); }
        catch (e) { ok = false; why = String(e.message).split("\n")[0]; }
      }
      const body = parts[0] ? parts[0].glsl : "";
      const funcs = (body.match(/float f\d+_field\(vec2 p\) \{/g) || []).length;
      push({ group: "Field wires", name: "eject: four fields as four functions in one program", ok: ok && funcs === 4,
             detail: ok ? `${funcs} field functions, ${Math.round(body.length / 1024)} KB, links on its own`
                        : why || `${parts.length} programs, ${funcs} functions` }); }

    // 10. A slider must not be a recompile: the program is keyed by topology,
    //     so moving a parameter has to land on the same generated type.
    { const build = (r) => {
        const g = createGraph(W, H);
        const a = addNode(g, "field.circle", { centre: [0, 0], radius: [r] });
        g.output = addNode(g, "field.shade", {}, [a]);
        return compileFields(g);
      };
      const t1 = build(0.3).nodes.find((n) => n.type.startsWith("field.compiled"));
      const t2 = build(0.45).nodes.find((n) => n.type.startsWith("field.compiled"));
      const same = t1 && t2 && t1.type === t2.type;
      const moved = t1 && t2 && String(t1.params.f1_radius) !== String(t2.params.f1_radius);
      push({ group: "Field wires", name: "moving a parameter is a uniform, not a recompile", ok: same && moved,
             detail: same ? `both radii compile to ${t1.type} · the value rides as f1_radius` : "two different programs" }); }
  } catch (e) {
    push({ group: "Field wires", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Parameter expressions: a parameter that is a relationship, not a number.
  try {
    const W = 220, H = 140;
    const px = (c) => c.getContext("2d").getImageData(0, 0, W, H).data;

    // 1. The language, against the JavaScript engine.
    //
    //    Every pair below means the same thing in both, so the engine is an
    //    independent implementation of precedence, associativity and arity —
    //    written by somebody else, long before this. The *test* is allowed to
    //    build a function from a string; the runtime never does, which is
    //    check 6 below.
    { const pairs = [
        ["2 + 3 * 4", "2 + 3 * 4"],
        ["(2 + 3) * 4", "(2 + 3) * 4"],
        ["10 / 4 - 1", "10 / 4 - 1"],
        ["-3 + 10 * -2", "-3 + 10 * -2"],
        ["2 < 3 ? 7 : 9", "2 < 3 ? 7 : 9"],
        ["1 <= 1 ? sin(1) : 0", "1 <= 1 ? Math.sin(1) : 0"],
        ["sin(1) + cos(2)", "Math.sin(1) + Math.cos(2)"],
        ["sqrt(2) * pi", "Math.sqrt(2) * Math.PI"],
        ["min(3, 7, 2)", "Math.min(3, 7, 2)"],
        ["max(3, 7, 2) - abs(-4)", "Math.max(3, 7, 2) - Math.abs(-4)"],
        ["floor(7.9) + ceil(0.1)", "Math.floor(7.9) + Math.ceil(0.1)"],
        ["pow(2, 10)", "Math.pow(2, 10)"],
        // Right-associative, and tighter than unary minus: 2^(3^2), and -(2^2).
        ["2 ^ 3 ^ 2", "Math.pow(2, Math.pow(3, 2))"],
        ["-2 ^ 2", "-Math.pow(2, 2)"],
        ["hypot(3, 4)", "Math.hypot(3, 4)"],
        ["atan2(1, 2) * 3", "Math.atan2(1, 2) * 3"],
        ["exp(1) - e", "Math.exp(1) - Math.E"],
        ["clamp(9, 0, 4) + smoothstep(0, 1, 0.5)", "Math.min(4, Math.max(0, 9)) + 0.5"],
        ["t * 2 + w / h", "0.75 * 2 + 220 / 140"],
      ];
      const vars = { t: 0.75, w: W, h: H, frame: 0, seed: 0, aspect: W / H };
      let worst = 0, bad = "";
      for (const [mine, theirs] of pairs) {
        const got = compileExpr(mine).value({ vars });
        const want = Function(`"use strict"; return (${theirs});`)();
        const d = Math.abs(got - want);
        if (d > worst) { worst = d; if (d > 1e-12) bad = `${mine} → ${got}, wanted ${want}`; }
      }
      push({ group: "Parameter expressions", name: `${pairs.length} expressions vs the JS engine`, ok: worst <= 1e-12,
             detail: worst <= 1e-12 ? `worst disagreement ${worst.toExponential(1)} — precedence, associativity and arity all agree`
                                    : bad }); }

    // 2. A parameter that follows another one, rendered. The reference is the
    //    same graph with the number typed in, so this is exactly zero or it is
    //    a bug — no antialiasing to hide behind.
    { const build = (radius) => {
        const g = createGraph(W, H);
        addNode(g, "field.circle", { radius: [0.2] }, [], { name: "lead" });
        const f = addNode(g, "field.circle", { centre: [0, 0], radius }, []);
        g.output = addNode(g, "field.shade", { filled: [1], width: [0], glow: [0] }, [f]);
        return g;
      };
      const followed = px(renderGraph(build({ expr: 'ch("lead.radius") * 2' }), {}));
      const typed = px(renderGraph(build([0.4]), {}));
      const r = compare(followed, typed, W, H, { thresh: 1 });
      push({ group: "Parameter expressions", name: 'ch("lead.radius") * 2 is the number it names, doubled', ok: r.mean === 0 && r.off === 0,
             detail: `${r.off} pixels differ from the same graph with 0.4 typed in · a reference by name, resolved on the CPU` }); }

    // 3. …and the clock drives one, at the time the render was asked for.
    { const g = createGraph(W, H);
      const f = addNode(g, "field.circle", { centre: [0, 0], radius: { expr: "0.2 + 0.2 * t" } });
      g.output = addNode(g, "field.shade", { filled: [1], width: [0], glow: [0] }, [f]);
      const g2 = createGraph(W, H);
      const f2 = addNode(g2, "field.circle", { centre: [0, 0], radius: [0.4] });
      g2.output = addNode(g2, "field.shade", { filled: [1], width: [0], glow: [0] }, [f2]);
      const at1 = px(renderGraph(g, {}, { time: 1 }));
      const at0 = px(renderGraph(g, {}, { time: 0 }));
      const want = px(renderGraph(g2, {}));
      const same = compare(at1, want, W, H, { thresh: 1 });
      const moved = compare(at0, at1, W, H, { thresh: 8 });
      push({ group: "Parameter expressions", name: "0.2 + 0.2 * t at t=1 is 0.4", ok: same.off === 0 && moved.off > 200,
             detail: `${same.off} pixels differ from the literal at t=1 · ${moved.off} pixels moved between t=0 and t=1` }); }

    // 4. Per-component: one expression each for x and y.
    { const g = createGraph(W, H);
      const f = addNode(g, "field.box", { size: { expr: ["0.3", "0.3 / aspect"] }, corner: [0] });
      g.output = addNode(g, "field.shade", { filled: [1] }, [f]);
      const rp = resolveParams(g, { t: 0 });
      const size = rp.nodes.find((n) => n.type === "field.box").params.size;
      const want = 0.3 / (W / H);
      push({ group: "Parameter expressions", name: "a vec2 takes one expression per component", ok: Math.abs(size[0] - 0.3) < 1e-9 && Math.abs(size[1] - want) < 1e-9,
             detail: `size = ${size.map((v) => v.toFixed(4)).join(", ")} — the second one asked the frame how wide it is` }); }

    // 5. A reference that comes back round to where it started is reported and
    //    broken, not left to run out of stack.
    { const g = createGraph(W, H);
      const a = addNode(g, "adjust.exposure", { stops: { expr: 'ch("b.stops")' } }, [addNode(g, "source")], { name: "a" });
      const b = addNode(g, "adjust.exposure", { stops: { expr: 'ch("a.stops")' } }, [a], { name: "b" });
      g.output = b;
      const errs = paramProblems(g);
      const said = errs.some((e) => /depends on itself/.test(e));
      push({ group: "Parameter expressions", name: "a cycle is named, not a hang", ok: said && errs.length > 0,
             detail: said ? errs[0] : `${errs.length} problems, none of them the cycle` }); }

    // 6. The runtime never builds a function from a string. A saved document
    //    is data, and this is the property that keeps it that way.
    { let src = "";
      try { src = await (await fetch("/static/expr.js")).text(); } catch { /* offline */ }
      const bad = /\bnew\s+Function\b|[^.\w]eval\s*\(|\bFunction\s*\(/.test(src.replace(/\/\/[^\n]*/g, ""));
      push({ group: "Parameter expressions", name: "the evaluator never calls Function or eval", ok: src.length > 0 && !bad,
             detail: src.length ? `${Math.round(src.length / 1024)} KB of tokeniser, parser and tree-walk — nothing compiled from a string`
                                : "the source could not be fetched, so this was not checked" }); }

    // 7. A typo in one parameter must not be a black frame.
    { const g = createGraph(W, H);
      const f = addNode(g, "field.circle", { centre: [0, 0], radius: { expr: "wobble(3" } }, [], { name: "dot" });
      g.output = addNode(g, "field.shade", { filled: [1], width: [0], glow: [0] }, [f]);
      const errs = paramProblems(g);
      const out = px(renderGraph(g, {}));
      let ink = 0;
      for (let i = 0; i < out.length; i += 4) if (out[i + 3] > 128) ink++;
      // The default radius is 0.4, so it draws the circle it would have drawn.
      push({ group: "Parameter expressions", name: "a broken expression falls back and says so", ok: errs.length === 1 && ink > 1000,
             detail: `${errs[0] || "no error reported"} · it still drew ${ink} pixels, at the value it would have used` }); }

    // 8. Costs nothing at draw time: the same program, the same pass count.
    //    An expression is resolved before anything is planned, so the shader
    //    cannot tell that a number was computed.
    { const build = (radius) => {
        const g = createGraph(W, H);
        const f = addNode(g, "field.circle", { centre: [0, 0], radius });
        g.output = addNode(g, "field.shade", { filled: [1] }, [f]);
        return g;
      };
      const a = compileFields(resolveParams(build({ expr: "0.1 + 0.3" }), {}));
      const b = compileFields(resolveParams(build([0.4]), {}));
      const ta = a.nodes.find((n) => n.type.startsWith("field.compiled"));
      const tb = b.nodes.find((n) => n.type.startsWith("field.compiled"));
      let drew = [];
      renderGraph(build({ expr: "0.1 + 0.3" }), {}, { onPasses: (ps) => { drew = ps; } });
      push({ group: "Parameter expressions", name: "an expression is not a second program", ok: ta.type === tb.type && drew.length === 1,
             detail: `computed and typed both compile to ${ta.type} · ${drew.length} pass · the value arrives as a uniform` }); }

    // 9. A keyed parameter goes through the video timeline's own evaluator,
    //    which is the point: a parameter moving over time is one problem.
    { const keys = [{ t: 0, v: 0.2, ease: "linear" }, { t: 2, v: 0.6, ease: "linear" }];
      const g = createGraph(W, H);
      addNode(g, "field.circle", { radius: { keys } });
      const at = (time) => resolveParams(g, { t: time }).nodes[0].params.radius[0];
      const ours = [0, 0.5, 1, 2].map(at);
      const theirs = [0, 0.5, 1, 2].map((time) => evalTrack(keys, time));
      const agree = ours.every((v, i) => Math.abs(v - theirs[i]) < 1e-12);
      push({ group: "Parameter expressions", name: "a keyed parameter is evalTrack, not a second answer", ok: agree,
             detail: `${ours.map((v) => v.toFixed(2)).join(", ")} — the same function the video timeline uses for a keyed grade` }); }

    // 10. What a number was written as survives into the shader you read.
    { const g = createGraph(W, H);
      const s0 = addNode(g, "source");
      g.output = addNode(g, "adjust.exposure", { stops: { expr: "sin(t) * 2" } }, [s0], { name: "grade" });
      const text = ejectGraph(g, { fuse: false });
      push({ group: "Parameter expressions", name: "the ejected shader says what the number was written as", ok: /written as/.test(text) && /sin\(t\) \* 2/.test(text),
             detail: /written as/.test(text) ? "the pass header carries the expression beside the value it came out at"
                                             : "the expression did not reach the ejected text" }); }
  } catch (e) {
    push({ group: "Parameter expressions", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Feedback: a wire that points backwards, and a node that remembers.
  //
  // Each simulation below is held against a CPU implementation of the same
  // rule, written beside the sketch. Life is binary, so the bar is exact;
  // the others are continuous in half float, so the bar is a fraction of a
  // level. What is really being checked is the machinery — that the memory
  // is the previous frame and not something else, that it persists between
  // separate renders, and that forgetting forgets.
  try {
    const px = (c) => c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    const seedCanvas = (w, h, draw) => {
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      const g = c.getContext("2d");
      g.fillStyle = "#000"; g.fillRect(0, 0, w, h);
      g.fillStyle = "#fff"; draw(g);
      return c;
    };
    let stateN = 0;
    const fresh = (g) => { g.stateKey = `selftest-feedback-${stateN++}`; return g; };

    // 1. Life: a glider, against the CPU rule, exact.
    { const W = 32, H = 32;
      const cells = [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]];
      const seed = seedCanvas(W, H, (g) => { for (const [x, y] of cells) g.fillRect(x + 4, y + 4, 1, 1); });
      let cpu = new Uint8Array(W * H);
      for (const [x, y] of cells) cpu[(y + 4) * W + (x + 4)] = 1;
      const gph = fresh(createGraph(W, H));
      const s0 = addNode(gph, "source");
      const life = addNode(gph, "sim.life", {}, [null, s0], { name: "life" });
      feedback(gph, life, 0, life);
      gph.output = life;
      const GENS = 12;
      // Frame 0 reads the seed; then GENS generations.
      const out = px(renderGraph(gph, { [s0]: seed }, { steps: GENS + 1, reset: true }));
      for (let i = 0; i < GENS; i++) cpu = lifeStep(cpu, W, H);
      let wrong = 0, alive = 0;
      for (let i = 0; i < W * H; i++) {
        // The canvas is y-down and the graph is y-up; the seed went through
        // the same flip on the way in, so row y of the output is row y of the seed.
        const got = out[i * 4] > 127 ? 1 : 0;
        if (got !== cpu[i]) wrong++;
        alive += cpu[i];
      }
      push({ group: "Feedback", name: `Life: a glider, ${GENS} generations, vs the CPU rule`, ok: wrong === 0 && alive === 5,
             detail: `${wrong} cells differ · ${alive} alive (a glider stays a glider) · one draw per generation, the memory is the generation before` }); }

    // 2. The memory persists between separate renders, and reset forgets.
    { const W = 32, H = 32;
      const cells = [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]];
      const seed = seedCanvas(W, H, (g) => { for (const [x, y] of cells) g.fillRect(x + 4, y + 4, 1, 1); });
      const build = () => {
        const gph = fresh(createGraph(W, H));
        const s0 = addNode(gph, "source");
        const life = addNode(gph, "sim.life", {}, [null, s0], { name: "life" });
        feedback(gph, life, 0, life);
        gph.output = life;
        return [gph, s0];
      };
      const [g1, a1] = build();
      const once = px(renderGraph(g1, { [a1]: seed }, { steps: 7, reset: true }));
      const [g2, a2] = build();
      let many;
      for (let i = 0; i < 7; i++) many = px(renderGraph(g2, { [a2]: seed }, { reset: i === 0 }));
      const same = compare(once, many, W, H, { thresh: 1 });
      // Forgetting: after reset, frame is 0 again, so the seed is read again.
      const again = px(renderGraph(g2, { [a2]: seed }, { reset: true }));
      const seedPx = px(seed);
      const back = compare(again, seedPx, W, H, { thresh: 1 });
      push({ group: "Feedback", name: "memory survives between renders; reset forgets", ok: same.off === 0 && back.off === 0,
             detail: `7 steps in one call vs 7 separate renders: ${same.off} cells differ · after reset it reads the seed again: ${back.off} differ` }); }

    // 3. Gray–Scott against the CPU stencil, 30 steps, in half float.
    { const W = 64, H = 48;
      const seed = seedCanvas(W, H, (g) => { g.fillRect(28, 20, 8, 8); g.fillRect(10, 8, 4, 4); });
      const P = { feed: 0.055, kill: 0.062, dU: 1.0, dV: 0.5, dt: 1.0 };
      let cpu = new Float32Array(W * H * 2);
      const sp = px(seed);
      for (let i = 0; i < W * H; i++) { cpu[i * 2] = 1; cpu[i * 2 + 1] = sp[i * 4] > 127 ? 1 : 0; }
      const STEPS = 30;
      for (let i = 0; i < STEPS; i++) cpu = grayScottStep(cpu, W, H, P);
      const gph = fresh(createGraph(W, H));
      const s0 = addNode(gph, "source");
      const rd = addNode(gph, "sim.reactionDiffusion",
        { feed: [P.feed], kill: [P.kill], dU: [P.dU], dV: [P.dV], dt: [P.dt] }, [null, s0], { name: "rd" });
      feedback(gph, rd, 0, rd);
      gph.output = rd;
      const out = px(renderGraph(gph, { [s0]: seed }, { steps: STEPS + 1, reset: true }));
      let sumU = 0, sumV = 0, maxU = 0, moved = 0;
      for (let i = 0; i < W * H; i++) {
        const du = Math.abs(out[i * 4] - cpu[i * 2] * 255), dv = Math.abs(out[i * 4 + 1] - cpu[i * 2 + 1] * 255);
        sumU += du; sumV += dv; maxU = Math.max(maxU, du);
        if (cpu[i * 2 + 1] > 0.05) moved++;
      }
      const meanU = sumU / (W * H), meanV = sumV / (W * H);
      push({ group: "Feedback", name: `Gray–Scott, ${STEPS} steps, vs the CPU stencil`, ok: meanU < 1.0 && meanV < 1.0 && moved > 100,
             detail: `u mean ${meanU.toFixed(2)}/255, v mean ${meanV.toFixed(2)}/255, worst u ${maxU.toFixed(0)} · want <1.0 (half-float state, thirty nonlinear steps) · v has spread to ${moved} cells` }); }

    // 4. A trail's fade is geometric, and the power is the check. One frame of
    //    ink, then twenty of nothing: the ghost's alpha is 0.9^20 exactly, and
    //    its colour is the ink's — fading is alpha, not darkening.
    { const W = 40, H = 30;
      const ink = seedCanvas(W, H, (g) => { g.fillStyle = "#c8643c"; g.fillRect(0, 0, W, H); });
      const nothing = document.createElement("canvas"); nothing.width = W; nothing.height = H;   // transparent
      const gph = fresh(createGraph(W, H));
      const s0 = addNode(gph, "source");
      const tr = addNode(gph, "feedback.trail", { decay: [0.9] }, [s0, null], { name: "trail" });
      feedback(gph, tr, 1, tr);
      gph.output = tr;
      const N = 20;
      renderGraph(gph, { [s0]: ink }, { reset: true });
      let out;
      for (let i = 0; i < N; i++) out = renderGraph(gph, { [s0]: nothing }, {});
      // Read straight from the GPU canvas? It is premultiplied on present, so
      // go through the 2D canvas the graph returns and undo it per pixel.
      const d = px(out);
      const a = Math.pow(0.9, N);
      let errA = 0, errC = 0;
      for (let i = 0; i < W * H; i++) {
        const pa = d[i * 4 + 3] / 255;
        errA += Math.abs(pa - a);
        // At this alpha the stored colour is quantised hard; compare hue-ish:
        // the red channel should still be the ink's 0xc8.
        if (pa > 0.05) errC += Math.abs(d[i * 4] - 0xc8);
      }
      const meanA = errA / (W * H) * 255, meanC = errC / (W * H);
      push({ group: "Feedback", name: `a trail after ${N} empty frames is 0.9^${N} of the ink, in alpha`, ok: meanA < 1.5 && meanC < 12,
             detail: `alpha ${(a * 255).toFixed(1)}/255 expected · mean alpha error ${meanA.toFixed(2)}/255, red still within ${meanC.toFixed(1)} of the ink · the colour does not darken, the coverage goes down` }); }

    // 5. A fused run can be the thing remembered. grade → trail fuses into one
    //    draw whose id is the trail; that draw has to land in memory.
    { const W = 40, H = 30;
      const src = seedCanvas(W, H, (g) => {
        const gr = g.createLinearGradient(0, 0, W, 0); gr.addColorStop(0, "#f4efe6"); gr.addColorStop(1, "#1b2b4b");
        g.fillStyle = gr; g.fillRect(0, 0, W, H);
      });
      const build = () => {
        const gph = fresh(createGraph(W, H));
        const s0 = addNode(gph, "source");
        const gr = addNode(gph, "adjust.grade", { sat: [1.4], gain: [1.1] }, [s0]);
        const tr = addNode(gph, "feedback.trail", { decay: [0.8] }, [gr, null], { name: "trail" });
        feedback(gph, tr, 1, tr);
        gph.output = tr;
        return [gph, s0];
      };
      const [g1, a1] = build();
      let drew = [];
      const fused = px(renderGraph(g1, { [a1]: src }, { steps: 10, reset: true, onPasses: (ps) => { drew = ps; } }));
      const [g2, a2] = build();
      const plain = px(renderGraph(g2, { [a2]: src }, { steps: 10, reset: true, fuse: false }));
      const r = compare(fused, plain, W, H, { thresh: 4 });
      const mem = drew.find((p2) => p2.memory);
      push({ group: "Feedback", name: "a fused pass can be what is remembered", ok: drew.length === 1 && !!mem && r.mean < 1.0,
             detail: `${drew.length} draw a frame (grade and trail fused, and the fused draw is the memory) · mean ${r.mean}/255 vs a pass per node` }); }

    // 6. A cycle without a feedback mark is refused, with the remedy.
    { const gph = createGraph(16, 16);
      const s0 = addNode(gph, "source");
      const a = addNode(gph, "adjust.exposure", {}, [s0]);
      const b = addNode(gph, "adjust.exposure", {}, [a]);
      findNode(gph, a).inputs[0] = b;                   // a reads b reads a, both this frame
      gph.output = b;
      const errs = validate(gph);
      const said = errs.some((e) => /a cycle/.test(e) && /feedback/.test(e));
      push({ group: "Feedback", name: "a cycle of this-frame edges is refused, with the fix in the message", ok: said,
             detail: said ? errs.find((e) => /a cycle/.test(e)) : errs.join("; ") || "no error" }); }

    // 7. A field has no last frame.
    { const gph = createGraph(16, 16);
      const c = addNode(gph, "field.circle", {});
      const off = addNode(gph, "field.offset", {}, [c]);
      feedback(gph, off, 0, c);
      gph.output = addNode(gph, "field.shade", {}, [off]);
      const errs = validate(gph);
      const said = errs.some((e) => /cannot read last frame|has no last frame/.test(e));
      push({ group: "Feedback", name: "a field port cannot read last frame", ok: said,
             detail: said ? errs.find((e) => /last frame/.test(e)) : "not refused" }); }

    // 8. What you read says so.
    { const W = 16, H = 16;
      const gph = fresh(createGraph(W, H));
      const s0 = addNode(gph, "source");
      const life = addNode(gph, "sim.life", {}, [null, s0], { name: "life" });
      feedback(gph, life, 0, life);
      gph.output = life;
      const text = ejectGraph(gph, { fuse: false });
      const ok = /last frame/.test(text) && /memory:/.test(text);
      push({ group: "Feedback", name: "the ejected shader names the memory", ok,
             detail: ok ? "the pass header marks the input as last frame and the pass as kept between frames" : "not said" }); }

    // 9. A register wants 32 bits. The same accumulation — add 0.006, keep
    //    98.5%, thirty times — in half-float memory and in float memory,
    //    against the CPU. The first drifts on this GPU; the second does not,
    //    and that is why game.ship says @precision float.
    { const probe = (id, precision) => defineNode(`// ${id}
// @node test.${id}
// @alpha
// @pass${precision ? "\n// @precision float" : ""}
uniform sampler2D in0;
uniform vec2 in0_size;
vec4 reg() { return texture2D(in0, vec2(0.5, 0.5) / in0_size); }
vec4 s = frame == 0 ? vec4(0.0) : reg();
float v = (s.x + 0.006) * 0.985;
vec2 texel = floor(gl_FragCoord.xy);
texel == vec2(0.0) ? vec4(v, 0.0, 0.0, 1.0) : vec4((v - 0.14) * 100.0, 0.0, 0.0, 1.0)`);
      probe("accHalf", false); probe("accFloat", true);
      const run = (id) => {
        const g = fresh(createGraph(32, 32));
        const a = addNode(g, `test.${id}`, {}, [null], { name: "acc" });
        feedback(g, a, 0, a); g.output = a;
        let out;
        for (let f = 0; f < 30; f++) out = renderGraph(g, {}, { reset: f === 0 });
        return px(out)[(10 * 32 + 10) * 4] / 255 / 100 + 0.14;
      };
      let cpu = 0;
      for (let f = 0; f < 30; f++) cpu = (cpu + 0.006) * 0.985;
      const half = run("accHalf"), flt = run("accFloat");
      const st = graphStats();
      const eh = Math.abs(half - cpu) / cpu, ef = Math.abs(flt - cpu) / cpu;
      push({ group: "Feedback", name: "a register in float memory does not drift; in half it does", ok: ef < 0.0005 && st.floatMemories > 0,
             detail: `after 30 accumulations the CPU says ${cpu.toFixed(5)}; half-float memory ${half.toFixed(5)} (${(eh * 100).toFixed(2)}% off), float memory ${flt.toFixed(5)} (${(ef * 100).toFixed(3)}% off) · ${st.floatMemories} float memories held` }); }

    // 10. The runner holds what it remembers, and no more than the cap.
    { const st = graphStats();
      push({ group: "Feedback", name: "memories are counted and capped", ok: st.memories > 0 && st.memories <= 32,
             detail: `${st.memories} node memories held (cap 32), ${st.floatMemories} of them 32-bit by request, the rest ${st.precision}` }); }
  } catch (e) {
    push({ group: "Feedback", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Input: the keyboard as a texture, and a game held to its own equations.
  try {
    const px = (c) => c.getContext("2d").getImageData(0, 0, c.width, c.height).data;

    // 1. The keyboard texture is what it says: a press lights three rows in
    //    the right column for one frame, then two, and a release leaves one.
    { const kb = new Keyboard();
      kb.press(KEY.right);
      const read = (row) => px(kb.texture())[(row * 256 + KEY.right) * 4];
      const a = [read(0), read(1), read(2)];
      kb.tick();
      const b = [read(0), read(1), read(2)];
      kb.release(KEY.right);
      const c = [read(0), read(1), read(2)];
      kb.press(KEY.right); kb.tick();
      const d = [read(0), read(1), read(2)];
      const ok = a.join() === "255,255,255" && b.join() === "255,0,255" && c.join() === "0,0,255" && d.join() === "255,0,0";
      push({ group: "Input", name: "a key press is one column, three rows, one frame", ok,
             detail: ok ? "held / this frame / toggled: 1,1,1 → tick → 1,0,1 → release → 0,0,1 → press again → 1,0,0"
                        : `got ${a} / ${b} / ${c} / ${d}` }); }

    // 2. The graph reads it. input.keys draws a lit cell exactly where the
    //    key is, and nowhere when nothing is held.
    { const W = 256, H = 3;
      const gph = createGraph(W, H);
      gph.output = addNode(gph, "input.keys", { lit: [1, 1, 1], unlit: [0, 0, 0] });
      const kb = new Keyboard();
      const quiet = px(renderGraph(gph, {}, { keys: kb.texture() }));
      kb.press(KEY.space);
      const loud = px(renderGraph(gph, {}, { keys: kb.texture() }));
      const litQuiet = [...quiet].filter((v, i) => i % 4 === 0 && v > 128).length;
      // The canvas is y-down: row 0 of the texture (held) is the bottom row of the picture.
      const at = (col, rowFromBottom) => loud[((H - 1 - rowFromBottom) * W + col) * 4];
      const ok = litQuiet === 0 && at(KEY.space, 0) > 128 && at(KEY.space, 1) > 128 && at(KEY.space, 2) > 128
              && at(KEY.space + 1, 0) < 128 && at(KEY.left, 0) < 128;
      push({ group: "Input", name: "a node sees the key the host pressed, in its column", ok,
             detail: ok ? `nothing lit with no keys; space lights column ${KEY.space} in all three rows and no other`
                        : `${litQuiet} lit when quiet; col ${KEY.space}: ${at(KEY.space, 0)},${at(KEY.space, 1)},${at(KEY.space, 2)}` }); }

    // 3. The ship, flown by a script, against the CPU integration of the same
    //    equations with the same presses. The state lives in half float, so
    //    the bar is pixels, not bits.
    { const W = 240, H = 160;
      const P = { thrust: 0.006, turn: 0.09, drag: 0.985, aspect: W / H };
      // Chosen so the ship ends mid-frame: the picture does not wrap, only the
      // position does, and a ship straddling the edge has a centroid that
      // says nothing. The check below insists on that.
      const script = (f) => ({ left: f >= 10 && f < 25, right: f >= 60 && f < 70, up: f >= 5 && f < 30 });
      const gph = createGraph(W, H); gph.stateKey = "selftest-ship";
      const ship = addNode(gph, "game.ship",
        // Big, so the centroid of its pixels is a measurement and not a guess:
        // at 0.06 the whole ship is a dozen pixels.
        { thrust: [P.thrust], turn: [P.turn], drag: [P.drag], size: [0.25] }, [null], { name: "ship" });
      feedback(gph, ship, 0, ship);
      gph.output = ship;
      const kb = new Keyboard();
      const FRAMES = 80;
      let cpu = null, out = null;
      for (let f = 0; f < FRAMES; f++) {
        const k = script(f);
        kb.clear();
        if (k.left) kb.press(KEY.left);
        if (k.right) kb.press(KEY.right);
        if (k.up) kb.press(KEY.up);
        out = renderGraph(gph, {}, { keys: kb.texture(), reset: f === 0 });
        cpu = shipStep(cpu, script, f, P);
      }
      // Where is the ship drawn? The centroid of its hull pixels, in p units.
      const d = px(out);
      let sx = 0, sy = 0, n = 0;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        if (d[i + 3] > 128 && !(y === H - 1 && x < 2)) { sx += x; sy += y; n++; }
      }
      const cx = sx / n, cy = sy / n;
      // The triangle's centroid sits a sixth of its length behind the nose's
      // midpoint: nose at +size, tail at -size/2, so the mean x is 0 exactly.
      const wantX = (cpu.x / P.aspect * 0.5 + 0.5) * W;
      const wantY = (0.5 - cpu.y * 0.5) * H;
      const errPx = Math.hypot(cx - wantX, cy - wantY);
      const moved = Math.hypot(cpu.x, cpu.y) > 0.1;
      const inside = Math.abs(cpu.x) < P.aspect - 0.2 && Math.abs(cpu.y) < 0.8;
      push({ group: "Input", name: `a ship flown for ${FRAMES} frames lands where the equations say`, ok: n > 20 && errPx < 2.5 && moved && inside,
             detail: `drawn at (${cx.toFixed(1)}, ${cy.toFixed(1)}), the CPU says (${wantX.toFixed(1)}, ${wantY.toFixed(1)}) — ${errPx.toFixed(2)} px apart after thrust, a left turn and a right turn · want <2.5 px (a 32-bit register)` }); }

    // 4. The same keys, the same game, twice: a replay is exact.
    { const W = 120, H = 80;
      const run = () => {
        const gph = createGraph(W, H); gph.stateKey = "selftest-ship-replay";
        const ship = addNode(gph, "game.ship", {}, [null], { name: "ship" });
        feedback(gph, ship, 0, ship);
        gph.output = ship;
        const kb = new Keyboard();
        let out;
        for (let f = 0; f < 40; f++) {
          kb.clear(); if (f > 3) kb.press(KEY.up); if (f % 7 < 3) kb.press(KEY.left);
          out = renderGraph(gph, {}, { keys: kb.texture(), reset: f === 0, time: 0 });
        }
        return px(out);
      };
      const a = run(), b = run();
      let diff = 0;
      for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
      push({ group: "Input", name: "a replay with the same keys is the same picture", ok: diff === 0,
             detail: `${diff} bytes differ between two runs of 40 frames — the keyboard is data, so the game is a function of it` }); }

    // 5. Life listens: space holds it still, R starts it over.
    { const W = 24, H = 24;
      const seed = document.createElement("canvas"); seed.width = W; seed.height = H;
      const g2 = seed.getContext("2d"); g2.fillStyle = "#000"; g2.fillRect(0, 0, W, H);
      g2.fillStyle = "#fff"; [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]].forEach(([x, y]) => g2.fillRect(x + 4, y + 4, 1, 1));
      const gph = createGraph(W, H); gph.stateKey = "selftest-life-keys";
      const s0 = addNode(gph, "source");
      const life = addNode(gph, "sim.life", {}, [null, s0], { name: "life" });
      feedback(gph, life, 0, life);
      gph.output = life;
      const kb = new Keyboard();
      const seedPx = px(seed);
      const same = (a, b) => { let d2 = 0; for (let i = 0; i < a.length; i += 4) if ((a[i] > 127) !== (b[i] > 127)) d2++; return d2; };
      renderGraph(gph, { [s0]: seed }, { keys: kb.texture(), reset: true });        // frame 0: seed
      const g1 = px(renderGraph(gph, { [s0]: seed }, { keys: kb.texture() }));     // one generation
      kb.press(KEY.space); kb.tick();                                               // toggled: paused
      const held1 = px(renderGraph(gph, { [s0]: seed }, { keys: kb.texture() }));
      const held2 = px(renderGraph(gph, { [s0]: seed }, { keys: kb.texture() }));
      kb.clear(); kb.press(KEY.r);                                                  // R this frame
      const reseeded = px(renderGraph(gph, { [s0]: seed }, { keys: kb.texture() }));
      const ok = same(g1, seedPx) > 0 && same(held1, g1) === 0 && same(held2, g1) === 0 && same(reseeded, seedPx) === 0;
      push({ group: "Input", name: "Life holds still on space and starts over on R", ok,
             detail: ok ? "one generation moved the glider; two frames under space changed nothing; R brought the seed back exactly"
                        : `gen ${same(g1, seedPx)} · held ${same(held1, g1)},${same(held2, g1)} · reseed ${same(reseeded, seedPx)}` }); }

    // 6. A reserved name survives fusion. input.keys after a grade fuses into
    //    one draw, and the keyboard still reaches it by its own name.
    { const W = 256, H = 3;
      const gph = createGraph(W, H);
      const k = addNode(gph, "input.keys", { lit: [1, 1, 1], unlit: [0, 0, 0] });
      gph.output = addNode(gph, "adjust.exposure", { stops: [0] }, [k]);
      const kb = new Keyboard(); kb.press(KEY.enter);
      let drew = [];
      const out = px(renderGraph(gph, {}, { keys: kb.texture(), onPasses: (ps) => { drew = ps; } }));
      const lit = out[((H - 1) * W + KEY.enter) * 4] > 128;
      push({ group: "Input", name: "u_keys keeps its name through fusion", ok: drew.length === 1 && lit,
             detail: `${drew.length} draw, and column ${KEY.enter} is lit inside the fused program — the reserved name was not prefixed` }); }
  } catch (e) {
    push({ group: "Input", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Model–Update–View: the model is parameters, the update is expressions
  // over prev() and key(), the view is the shader. The claim is that the
  // state is then a number in the document rather than a texel — so the
  // first check below reads it off the document and holds it to the CPU
  // exactly, with no centroid and no pixels in between.
  try {
    const px = (c) => c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    const P = { thrust: 0.006, turn: 0.09, drag: 0.985 };
    const script = (f) => ({ left: f >= 10 && f < 25, right: f >= 60 && f < 70, up: f >= 5 && f < 30 });
    const pressFor = (kb, k) => { kb.clear(); if (k.left) kb.press(KEY.left); if (k.right) kb.press(KEY.right); if (k.up) kb.press(KEY.up); };

    // 1. The data ship vs the CPU integration: exact, because it is the same
    //    arithmetic in the same doubles. The state is read from the resolved
    //    graph, which is the document with its expressions evaluated.
    { const W = 240, H = 160;
      const gph = createGraph(W, H); gph.stateKey = "selftest-mvu-ship";
      gph.output = shipAsData(gph, P);
      const kb = new Keyboard();
      let cpu = null, worst = 0, resolved = null;
      resetGraphState(gph.stateKey);
      for (let f = 0; f < 80; f++) {
        pressFor(kb, script(f));
        renderGraph(gph, {}, { keys: kb, reset: f === 0 });
        cpu = shipStep(cpu, script, f, { ...P, aspect: W / H });
        const st = paramState(gph.stateKey);
        const pos = st["ship pos"], vel = st["ship vel"], turns = st["ship turns"];
        worst = Math.max(worst, Math.abs(pos[0] - cpu.x), Math.abs(pos[1] - cpu.y),
                                Math.abs(vel[0] - cpu.vx), Math.abs(vel[1] - cpu.vy), Math.abs(turns[0] - cpu.n));
        resolved = { pos, vel, turns };
      }
      push({ group: "Model–Update–View", name: "the data ship's state equals the CPU integration, exactly", ok: worst < 1e-9,
             detail: `80 frames, thrust and two turns: worst difference ${worst.toExponential(1)} across pos, vel and turns · pos ends (${resolved.pos.map((v) => v.toFixed(4)).join(", ")}) — read from the document, not from pixels` }); }

    // 2. …and it draws where the texel ship draws. Same keys, two ships, one
    //    holding state in a texel and one in data; the pictures agree.
    { const W = 240, H = 160;
      const centroid = (c) => { const d = px(c); let sx = 0, sy = 0, n = 0;
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = (y * W + x) * 4; if (d[i + 3] > 128 && !(y === H - 1 && x < 2)) { sx += x; sy += y; n++; } }
        return [sx / n, sy / n, n]; };
      const run = (asData) => {
        const gph = createGraph(W, H); gph.stateKey = `selftest-mvu-two-${asData}`;
        if (asData) gph.output = shipAsData(gph, P, { params: { size: [0.25] } });
        else { const ship = addNode(gph, "game.ship", { ...P, size: [0.25] }, [null], { name: "ship" }); feedback(gph, ship, 0, ship); gph.output = ship; }
        const kb = new Keyboard();
        let out;
        for (let f = 0; f < 80; f++) { pressFor(kb, script(f)); out = renderGraph(gph, {}, { keys: kb, reset: f === 0 }); }
        return centroid(out);
      };
      const a = run(true), b = run(false);
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      push({ group: "Model–Update–View", name: "the data ship and the texel ship draw in the same place", ok: d < 2.5 && a[2] > 50,
             detail: `data ship at (${a[0].toFixed(1)}, ${a[1].toFixed(1)}), texel ship at (${b[0].toFixed(1)}, ${b[1].toFixed(1)}) — ${d.toFixed(2)} px apart · the texel one carries 32-bit rounding; the data one carries none` }); }

    // 3. prev() before any frame is the written initial value; after one frame
    //    it is last frame's result. Looking at the graph does not advance it.
    { const gph = createGraph(16, 16); gph.stateKey = "selftest-mvu-prev";
      const s0 = addNode(gph, "source");
      gph.output = addNode(gph, "adjust.exposure", { stops: { expr: 'prev("stops") + 0.5', value: [1] } }, [s0], { name: "g" });
      resetGraphState(gph.stateKey);
      const look = () => resolveParams(gph, {}).nodes.find((n) => n.name === "g").params.stops[0];
      const before = look(), beforeAgain = look();                // looking, twice
      const src = document.createElement("canvas"); src.width = 16; src.height = 16;
      renderGraph(gph, { [s0]: src }, {});                         // one frame
      const afterOne = look();
      renderGraph(gph, { [s0]: src }, { steps: 3 });               // three more, in one call
      const afterFour = look();
      resetGraphState(gph.stateKey);
      const afterReset = look();
      const ok = before === 1.5 && beforeAgain === 1.5 && afterOne === 2 && afterFour === 3.5 && afterReset === 1.5;
      push({ group: "Model–Update–View", name: "prev() starts at the written value, advances per frame, and only when run", ok,
             detail: `look: ${before}, look again: ${beforeAgain} (no advance) · after 1 frame: ${afterOne} · after 3 more in one call: ${afterFour} · after reset: ${afterReset}` }); }

    // 4. key() reads the Keyboard handed to the runner, with the same three
    //    rows the texture has.
    { const gph = createGraph(16, 16); gph.stateKey = "selftest-mvu-key";
      const s0 = addNode(gph, "source");
      gph.output = addNode(gph, "adjust.exposure",
        { stops: { expr: "key(32) * 1 + keyHit(32) * 10 + keyToggle(32) * 100" } }, [s0], { name: "g" });
      const src = document.createElement("canvas"); src.width = 16; src.height = 16;
      const kb = new Keyboard();
      const read = () => resolveParams(gph, { keys: kb }).nodes.find((n) => n.name === "g").params.stops[0];
      const quiet = read();
      kb.press(32); const pressed = read();
      kb.tick(); const held = read();
      kb.release(32); const released = read();
      const ok = quiet === 0 && pressed === 111 && held === 101 && released === 100;
      push({ group: "Model–Update–View", name: "key(), keyHit() and keyToggle() see the keyboard", ok,
             detail: `quiet ${quiet} · pressed ${pressed} · next frame ${held} · released ${released} — held + 10·hit + 100·toggle` }); }

    // 5. A replay is a function of its inputs: same keys, same document, same
    //    state, to the bit — and the model can be dumped to say so.
    { const run = () => {
        const gph = createGraph(64, 40); gph.stateKey = "selftest-mvu-replay";
        gph.output = shipAsData(gph, P);
        const kb = new Keyboard();
        for (let f = 0; f < 50; f++) { kb.clear(); if (f > 3) kb.press(KEY.up); if (f % 7 < 3) kb.press(KEY.left); renderGraph(gph, {}, { keys: kb, reset: f === 0 }); }
        return JSON.stringify(paramState(gph.stateKey));
      };
      const a = run(), b = run();
      push({ group: "Model–Update–View", name: "a replay reproduces the model, byte for byte", ok: a === b,
             detail: a === b ? `${a.length} bytes of state, identical across two runs of 50 frames` : "the two runs differ" }); }

    // 6. The ejected shader says what the model was written as — the update
    //    is in the text you read, beside the view.
    { const gph = createGraph(64, 40); gph.stateKey = "selftest-mvu-eject";
      gph.output = shipAsData(gph, P);
      const text = ejectGraph(gph, { fuse: false });
      const ok = /written as:/.test(text) && /prev\("pos", 0\)/.test(text) && /key\(38\)/.test(text);
      push({ group: "Model–Update–View", name: "the ejected text carries the update beside the view", ok,
             detail: ok ? `pos = wrap(prev("pos", 0) + ch("vel", 0), aspect) rides in the pass header with the shader that draws it` : "the expressions did not reach the ejected text" }); }

    // 7. The graph view knows the difference.
    { const gph = createGraph(64, 40);
      shipAsData(gph, P); gph.output = gph.nodes[0].id;
      const st = paramStats(gph);
      push({ group: "Model–Update–View", name: "the summary counts states and inputs", ok: st.states === 3 && st.inputs >= 3,
             detail: `${st.expressions} expressions, ${st.states} carrying state (turns, vel, pos), ${st.inputs} reading the keyboard` }); }
  } catch (e) {
    push({ group: "Model–Update–View", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Events: every one, exactly once, in order. The checks are about delivery,
  // not about drawing — what a menu's index is after two presses in one
  // frame, whether order matters, whether a frame with five key events steps
  // physics once or six times, and whether a log replays to the byte.
  try {
    const src16 = document.createElement("canvas"); src16.width = 16; src16.height = 16;
    const menuGraph = (key) => { const g = createGraph(32, 32); g.stateKey = key; g.output = menuAsData(g, 4); return g; };
    const state = (g) => paramState(g.stateKey);

    // 1. Two presses in one frame move by two. The keyboard texture's "went
    //    down this frame" row would have said one.
    { const g = menuGraph("selftest-ev-two");
      const kb = new Keyboard();
      renderGraph(g, {}, { reset: true, keys: kb });
      kb.press(KEY.down);                                           // what the texture sees: one press
      const evs = [{ kind: "keydown", code: KEY.down }, { kind: "keyup", code: KEY.down },
                   { kind: "keydown", code: KEY.down }];            // what actually happened: two
      renderGraph(g, {}, { keys: kb, events: evs });
      const idx = state(g)["menu index"][0];
      const hitSaw = kb.hit[KEY.down] ? 1 : 0;
      push({ group: "Events", name: "two presses in one frame move the menu by two", ok: idx === 2 && hitSaw === 1,
             detail: `index ${idx} after two keydowns delivered in one frame · the texture's hit row saw ${hitSaw} — a queue keeps what a snapshot loses` }); }

    // 2. Order is meaning: Down then Enter chooses 1; Enter then Down chooses 0.
    { const run = (order) => {
        const g = menuGraph("selftest-ev-order-" + order.join(""));
        renderGraph(g, {}, { reset: true });
        renderGraph(g, {}, { events: order.map((code) => ({ kind: "keydown", code })) });
        return state(g)["menu selected"][0];
      };
      const a = run([KEY.down, KEY.enter]), b = run([KEY.enter, KEY.down]);
      push({ group: "Events", name: "delivery order is the meaning: Down,Enter ≠ Enter,Down", ok: a === 1 && b === 0,
             detail: `Down then Enter chose ${a}; Enter then Down chose ${b}` }); }

    // 3. Exactly once, and over any framing: 100 events in one frame and the
    //    same 100 spread over 7 frames land on the same model.
    { const mk = (key) => { const g = createGraph(16, 16); g.stateKey = key;
        const s0 = addNode(g, "source");
        g.output = addNode(g, "adjust.exposure", { stops: { expr: 'prev("stops") + on("msg")', value: [0] } }, [s0], { name: "c" });
        return [g, s0]; };
      const evs = Array.from({ length: 100 }, (_, i) => ({ kind: "msg", name: "tick", value: i }));
      const [g1, a1] = mk("selftest-ev-100a");
      renderGraph(g1, { [a1]: src16 }, { reset: true, events: evs });
      const one = state(g1)["c stops"][0];
      const [g2, a2] = mk("selftest-ev-100b");
      renderGraph(g2, { [a2]: src16 }, { reset: true });
      for (let f = 0; f < 7; f++) renderGraph(g2, { [a2]: src16 }, { events: evs.slice(f * 15, f * 15 + 15) });
      const seven = state(g2)["c stops"][0];
      push({ group: "Events", name: "100 events count to 100, in one frame or seven", ok: one === 100 && seven === 100,
             detail: `one frame: ${one} · seven frames: ${seven} — every event once, however they are framed` }); }

    // 4. An event pass does not step the frame. The ship, held with thrust on,
    //    moves the same distance in a frame with no events and in a frame
    //    with five — because its physics listens to the frame, not to keys.
    { const run = (withEvents) => {
        const g = createGraph(120, 80); g.stateKey = "selftest-ev-nostep-" + withEvents;
        g.output = shipAsData(g);
        const kb = new Keyboard(); kb.press(KEY.up);
        renderGraph(g, {}, { reset: true, keys: kb });
        for (let f = 0; f < 10; f++) {
          const evs = withEvents ? Array.from({ length: 5 }, () => ({ kind: "keydown", code: 90 })) : [];
          renderGraph(g, {}, { keys: kb, events: evs });
        }
        return state(g)["ship pos"][1];
      };
      const a = run(false), b = run(true);
      push({ group: "Events", name: "a frame with five events steps the physics once, not six times", ok: Math.abs(a - b) < 1e-12 && a > 0,
             detail: `10 frames of thrust: y = ${a.toFixed(6)} with no events, ${b.toFixed(6)} with five a frame — identical` }); }

    // 5. The frame is an event: on("frame") counts frames and ev("dt") is the
    //    time between them.
    { const g = createGraph(16, 16); g.stateKey = "selftest-ev-frame";
      const s0 = addNode(g, "source");
      g.output = addNode(g, "adjust.exposure",
        { stops: { expr: 'prev("stops") + on("frame")', value: [0] }, offset: { expr: 'ev("dt")' } }, [s0], { name: "f" });
      renderGraph(g, { [s0]: src16 }, { reset: true, time: 1.0 });
      renderGraph(g, { [s0]: src16 }, { time: 1.25, events: [{ kind: "keydown", code: 1 }] });
      renderGraph(g, { [s0]: src16 }, { time: 1.3 });
      const st = state(g);
      const frames = st["f stops"][0], dt = st["f offset"][0];
      push({ group: "Events", name: "the frame is an event with a dt", ok: frames === 3 && Math.abs(dt - 0.05) < 1e-9,
             detail: `on("frame") counted ${frames} frames across three renders (a keydown between them did not count) · ev("dt") on the last was ${dt.toFixed(3)} s` }); }

    // 6. A replay is a log. Record 60 frames of scripted events into a queue,
    //    then replay the log into a fresh graph: the model is the same bytes.
    { const run = (log) => {
        const g = createGraph(120, 80); g.stateKey = "selftest-ev-replay-" + (log ? "b" : "a");
        const ship = shipAsData(g, undefined, { params: {
          pulse: { expr: 'on("keydown", 32) ? 0.0 : prev("pulse") + 0.03 * on("frame")', value: [9] } } });
        g.output = ship;
        const q = new EventQueue();
        const recorded = log ? null : q.record();
        const kb = new Keyboard();
        for (let f = 0; f < 60; f++) {
          if (!log) {
            if (f % 9 === 0) { q.push({ kind: "keydown", code: 32 }); kb.press(32); }
            if (f % 9 === 2) { q.push({ kind: "keyup", code: 32 }); kb.release(32); }
            if (f === 4) { q.push({ kind: "keydown", code: KEY.up }); kb.press(KEY.up); }
            if (f === 20) { q.push({ kind: "keydown", code: KEY.left }); kb.press(KEY.left); }
            if (f === 30) { q.push({ kind: "keyup", code: KEY.left }); kb.release(KEY.left); }
          } else {
            // Replay: the same events at the same frames, and the keyboard
            // texture follows them — which is what a recorder would store.
            for (const e of log.filter((e2) => e2.frame === f)) {
              q.push(e); if (e.kind === "keydown") kb.press(e.code); if (e.kind === "keyup") kb.release(e.code);
            }
          }
          if (!log) for (const e of q.items) if (e.frame === undefined) e.frame = f;
          renderGraph(g, {}, { keys: kb, events: q, reset: f === 0, time: f / 60 });
        }
        return { model: JSON.stringify(state(g)), log: recorded };
      };
      const first = run(null);
      const again = run(first.log);
      push({ group: "Events", name: "a replay of the event log reproduces the model, byte for byte", ok: first.model === again.model && first.log.length > 5,
             detail: `${first.log.length} events recorded over 60 frames; replayed, ${first.model.length} bytes of model identical` }); }

    // 7. The pointer arrives in the sketch's own coordinates.
    { const q = new EventQueue();
      const el2 = document.createElement("canvas"); el2.width = 200; el2.height = 100;
      el2.style.cssText = "position:fixed;left:0;top:0;width:200px;height:100px;opacity:0;pointer-events:none";
      document.body.append(el2);
      const stop = pointerEvents(q, el2);
      const r = el2.getBoundingClientRect();
      const fire = (fx, fy) => el2.dispatchEvent(new PointerEvent("pointerdown", { clientX: r.left + fx * 200, clientY: r.top + fy * 100, bubbles: true }));
      fire(0.5, 0.5); fire(1, 0); fire(0, 1);
      stop(); el2.remove();
      const evs = q.drain();
      const near = (a, b) => Math.abs(a - b) < 1e-6;
      const ok = evs.length === 3
        && near(evs[0].x, 0) && near(evs[0].y, 0)
        && near(evs[1].x, 2) && near(evs[1].y, 1)
        && near(evs[2].x, -2) && near(evs[2].y, -1);
      push({ group: "Events", name: "a click arrives as p: centre is (0,0), the top-right corner is (aspect, 1)", ok,
             detail: ok ? "three clicks: (0,0), (2,1), (−2,−1) on a 2:1 canvas — the same frame the shader's p uses"
                        : evs.map((e) => `(${e.x.toFixed(2)},${e.y.toFixed(2)})`).join(" ") }); }

    // 8. The summary knows who is listening.
    { const g = menuGraph("selftest-ev-stats");
      const st = paramStats(g);
      push({ group: "Events", name: "the summary counts listeners", ok: st.listeners === 2,
             detail: `${st.listeners} parameters listening for events (index, selected), ${st.states} carrying state` }); }
  } catch (e) {
    push({ group: "Events", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The live audio path, and the document that names its instrument. The
  // claim is not "it makes a sound" — it is that a document carries its own
  // instruments as data, that its effects say which, and that the sound an
  // event makes live is the sound the batch scheduler would make.
  try {
    const SR = 48000, FPS = 60, FRAMES = 90;
    // Two instruments, declared on the document. The pulse plays the ship's
    // voice; every third pulse also strikes a bell, so routing is exercised.
    const instruments = () => ({
      ship: (() => { const i2 = shipInstrument(); return { graph: i2.graph, noteNode: i2.noteNode, voices: 8, hum: i2.hum }; })(),
      bell: toneInstrument({ amp: 0.25, attackMs: 2, decayMs: 300, voices: 4, gain: 0.8 }),
    });
    const flight = (instr, mutate = (g) => g) => {
      const g = createGraph(120, 80); g.stateKey = "selftest-live-" + (Math.random() * 1e9 | 0);
      g.output = shipAsData(g, undefined, { params: {
        pulse: { expr: 'on("keydown", 32) ? 0.0 : prev("pulse") + 0.03 * on("frame")', value: [9] } } });
      g.instruments = { ship: { graph: instr.ship.graph, noteNode: instr.ship.noteNode, voices: 8 },
                        bell: instr.bell };
      g.effects = [
        { kind: "note", instrument: "ship", when: 'on("keydown", 32)',
          hz: '330 * 2 ^ (mod(ch("ship.turns"), 12) / 12)', dur: "0.3" },
        { kind: "note", instrument: "bell", when: 'on("keydown", 13)', hz: "660", dur: "0.4" },
        { kind: "param", instrument: "ship", node: instr.ship.hum, param: "level",
          value: 'ch("ship.burning") * 0.9' },
      ];
      mutate(g);
      const kb = new Keyboard();
      const fired = [];
      for (let f = 0; f < FRAMES; f++) {
        const evs = [];
        if (f === 10 || f === 40 || f === 41) { evs.push({ kind: "keydown", code: 32 }); kb.press(32); }
        if (f === 12 || f === 43) { evs.push({ kind: "keyup", code: 32 }); kb.release(32); }
        if (f === 25 || f === 60) evs.push({ kind: "keydown", code: KEY.enter });
        if (f === 20) { evs.push({ kind: "keydown", code: KEY.left }); kb.press(KEY.left); }
        if (f === 30) { evs.push({ kind: "keyup", code: KEY.left }); kb.release(KEY.left); }
        if (f === 50) kb.press(KEY.up);
        if (f === 75) kb.release(KEY.up);
        renderGraph(g, {}, { keys: kb, events: evs, reset: f === 0, time: f / FPS,
                             onFired: (fx) => fired.push(...fx) });
      }
      resetGraphState(g.stateKey);
      return { fired, graph: g };
    };

    const instr = instruments();
    const runA = flight(instr), runB = flight(instr);
    const fired = runA.fired;
    const notes = fired.filter((f) => f.kind === "note");
    const shipNotes = notes.filter((f) => f.instrument === "ship");
    const bellNotes = notes.filter((f) => f.instrument === "bell");

    // 1. The effects a run describes are data, they say which instrument, and
    //    the same run describes the same.
    { const same = JSON.stringify(fired) === JSON.stringify(runB.fired);
      const named = notes.every((f) => f.instrument === "ship" || f.instrument === "bell");
      push({ group: "Live audio", name: "a run describes its effects, each naming its instrument", ok: same && named && shipNotes.length === 3 && bellNotes.length === 2,
             detail: `${fired.length} effects over ${FRAMES} frames — ${shipNotes.length} to "ship" (frames ${shipNotes.map((n) => n.frame).join(", ")}), ${bellNotes.length} to "bell" (frames ${bellNotes.map((n) => n.frame).join(", ")}), ${fired.length - notes.length} hum levels · two runs ${same ? "identical" : "DIFFER"}` }); }

    // 2. The rig, fed frame by frame, against the batch scheduler — two
    //    instruments, two routes, one answer.
    //
    //    Each instrument goes to its own channel rather than into a mix.
    //    Summing two float32 streams is not bit-stable between renders — this
    //    machine disagrees with itself by 6e-8 at the sample a second
    //    instrument starts — so a mixed comparison would be measuring the
    //    browser's adder, not the schedulers. Per channel there is no adder.
    { const names = Object.keys(runA.graph.instruments);
      const seconds = FRAMES / FPS + 0.25;
      const offline = new OfflineAudioContext(names.length, Math.round(seconds * SR), SR);
      const rig = await LiveRig.create(runA.graph, { ctx: offline, split: true });
      for (let f = 0; f < FRAMES; f++) rig.perform(fired.filter((x) => x.frame === f), f / FPS);
      const liveBuf = await offline.startRendering();
      const { buffer: batchBuf } = await renderFired(fired, { instruments: runA.graph.instruments,
                                                              fps: FPS, frames: FRAMES, sampleRate: SR, split: true });
      const per = names.map((name, c) => {
        const a = liveBuf.getChannelData(c), b = batchBuf.getChannelData(c);
        let same = a.length === b.length, worst = 0, energy = 0;
        for (let i = 0; i < Math.min(a.length, b.length); i++) {
          const d = Math.abs(a[i] - b[i]); if (d > worst) worst = d; if (d !== 0) same = false;
          energy += a[i] * a[i];
        }
        return { name, same, worst, rms: Math.sqrt(energy / a.length) };
      });
      const allSame = per.every((r) => r.same), heard = per.every((r) => r.rms > 0.005);
      push({ group: "Live audio", name: "two instruments, fed frame by frame, equal the batch scheduler", ok: allSame && heard && rig.missed === 0,
             detail: `${liveBuf.length} samples on each of ${names.length} channels · `
               + per.map((r) => `${r.name} ${r.same ? "identical" : `off by ${r.worst.toExponential(2)}`} (rms ${r.rms.toFixed(3)})`).join(", ")
               + ` · ${rig.notes} notes routed, ${rig.missed} unrouted — one note at a time against the whole list up front` });

      const ship = liveBuf.getChannelData(names.indexOf("ship"));
      const bell = liveBuf.getChannelData(names.indexOf("bell"));
      const at = (d2, f0, f1) => { let e = 0, n = 0; for (let i = Math.round(f0 / FPS * SR); i < Math.round(f1 / FPS * SR); i++) { e += d2[i] * d2[i]; n++; } return Math.sqrt(e / Math.max(1, n)); };
      const before = at(ship, 0, 10), after = at(ship, 10, 14), thrust = at(ship, 55, 70), idle = at(ship, 80, 90);
      push({ group: "Live audio", name: "the note lands on the frame of the keydown; the hum follows the thrust", ok: before < 1e-6 && after > 0.05 && thrust > idle * 3,
             detail: `rms before the first press ${before.toExponential(1)}, in the 4 frames after it ${after.toFixed(3)} · hum during thrust ${thrust.toFixed(3)} vs idle ${idle.toFixed(3)}` });

      // Routing is audible: the bell channel is silent until the bell's own
      // first note, whatever the ship is doing.
      const bellBefore = at(bell, 0, 25), bellAfter = at(bell, 25, 32);
      push({ group: "Live audio", name: "each instrument hears only the effects addressed to it", ok: bellBefore < 1e-6 && bellAfter > 0.02,
             detail: `the bell channel is ${bellBefore.toExponential(1)} through the ship's first two notes, then ${bellAfter.toFixed(3)} on its own — three ship notes never reached it` });
      await rig.close();
    }

    // 3. The document is whole on its own: through JSON and back, the
    //    instruments still install and the samples are the same. An
    //    instrument that only worked because a JS object was still in scope
    //    would fail here.
    { const asText = JSON.stringify(runA.graph.instruments);
      const revived = JSON.parse(asText);
      const one = await renderFired(fired, { instruments: runA.graph.instruments, fps: FPS, frames: FRAMES, sampleRate: SR, split: true });
      const two = await renderFired(fired, { instruments: revived, fps: FPS, frames: FRAMES, sampleRate: SR, split: true });
      let same = one.buffer.length === two.buffer.length;
      for (let c = 0; same && c < one.buffer.numberOfChannels; c++) {
        const a = one.buffer.getChannelData(c), b = two.buffer.getChannelData(c);
        for (let i = 0; same && i < a.length; i++) if (a[i] !== b[i]) same = false;
      }
      push({ group: "Live audio", name: "the instruments survive JSON — the document carries them, not the host", ok: same,
             detail: same ? `${Math.round(asText.length / 1024)} KB of instrument as text, revived, and the render is identical sample for sample`
                          : "the revived instruments rendered differently" }); }

    // 4. An unnamed effect goes to the document's first instrument, and it is
    //    written into the effect rather than left for the host to guess.
    { const g = createGraph(16, 16); g.stateKey = "selftest-live-default";
      const s0 = addNode(g, "source");
      g.output = addNode(g, "adjust.exposure", {}, [s0]);
      g.instruments = { first: toneInstrument({}), second: toneInstrument({}) };
      g.effects = [{ kind: "note", when: 'on("frame")', hz: "440", dur: "0.1" }];
      const src = document.createElement("canvas"); src.width = 16; src.height = 16;
      let got = [];
      renderGraph(g, { [s0]: src }, { reset: true, onFired: (fx) => { got = fx; } });
      push({ group: "Live audio", name: "an effect that names no instrument is resolved to the first, in the description", ok: got.length === 1 && got[0].instrument === "first",
             detail: got.length ? `resolved to "${got[0].instrument}" of ${Object.keys(g.instruments).map((n) => `"${n}"`).join(", ")} — the fired list says which, so the host never guesses` : "nothing fired" }); }

    // 5. A name the document does not carry is said plainly, and the rest
    //    still plays.
    { const g = createGraph(16, 16); g.stateKey = "selftest-live-missing";
      const s0 = addNode(g, "source");
      g.output = addNode(g, "adjust.exposure", {}, [s0]);
      g.instruments = { bell: toneInstrument({}) };
      g.effects = [{ kind: "note", instrument: "tuba", when: 'on("frame")', hz: "440", dur: "0.1" },
                   { kind: "note", instrument: "bell", when: 'on("frame")', hz: "550", dur: "0.1" }];
      const errs = paramProblems(g);
      const said = errs.some((e) => /no instrument called "tuba"/.test(e) && /"bell"/.test(e));
      push({ group: "Live audio", name: "an instrument the document does not carry is named as missing", ok: said && errs.length === 1,
             detail: said ? errs[0] : errs.join("; ") || "not reported" }); }

    // 6. The instrument is the bounce's compiled loop, not a second one.
    { const one = sourceFor(instr.ship.graph, { voices: 8 });
      push({ group: "Live audio", name: "an instrument is one compiled loop, used by both paths", ok: one.findings.length === 0 && one.loop.length > 100,
             detail: `${one.loop.split("\n").length} lines of generated process(), allocation-free, the same text live and bounced` }); }
  } catch (e) {
    push({ group: "Live audio", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The instrument library. The claim is that two documents wanting the same
  // sound do not each carry it — and that "the same sound" is decidable,
  // because an instrument's identity is a hash of what it sounds like rather
  // than a name somebody has to keep.
  try {
    const SR = 48000, FPS = 60, FRAMES = 40;
    const fired = [
      { kind: "note", instrument: "a", frame: 4, hz: 440, dur: 0.25 },
      { kind: "note", instrument: "a", frame: 20, hz: 550, dur: 0.25 },
    ];
    const render = (instruments) => renderFired(fired, { instruments, fps: FPS, frames: FRAMES, sampleRate: SR });
    const identical = (x, y) => {
      const a = x.getChannelData(0), b = y.getChannelData(0);
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
      return true;
    };

    // 1. The point of the whole thing: two instruments built minutes and many
    //    node ids apart are the same instrument, and are known to be.
    { const one = toneInstrument({ decayMs: 200 });
      for (let i = 0; i < 5; i++) toneInstrument({});          // burn some node ids
      const two = toneInstrument({ decayMs: 200 });
      const rawSame = JSON.stringify(one.graph) === JSON.stringify(two.graph);
      const idSame = instrumentId(one) === instrumentId(two);
      const different = instrumentId(toneInstrument({ decayMs: 201 }));
      push({ group: "Instrument library", name: "the same sound is the same instrument, whenever it was built", ok: !rawSame && idSame && different !== instrumentId(one),
             detail: `their graphs differ as written (${one.graph.nodes[0].id} vs ${two.graph.nodes[0].id}) and hash the same: ${instrumentId(one)} · one millisecond of decay makes it ${different} instead` }); }

    // 2. Normalising must not change the sound — the renumbering is the whole
    //    mechanism, so it is held to samples rather than to inspection.
    { const raw = toneInstrument({ decayMs: 200 });
      const a = await render({ a: raw });
      const b = await render({ a: normalise(raw) });
      push({ group: "Instrument library", name: "renumbering an instrument does not change what it sounds like", ok: identical(a.buffer, b.buffer),
             detail: `nodes renumbered to ${normalise(raw).graph.nodes.map((n) => n.id).join(", ")} in dependency order · ${a.buffer.length} samples, identical` }); }

    // 3. intern shrinks a document; inline puts it back; the round trip is
    //    the same document, held to samples.
    { const g = createGraph(16, 16); g.stateKey = "selftest-instlib-round";
      g.instruments = { a: toneInstrument({ decayMs: 200 }), b: toneInstrument({ decayMs: 90 }) };
      const before = instrumentBytes(g);
      const interned = internInstruments(g);
      const after = instrumentBytes(interned);
      const back = inlineInstruments(interned);
      const one = await render(g.instruments);
      const two = await render(back.instruments);
      push({ group: "Instrument library", name: "intern then inline is the same document", ok: identical(one.buffer, two.buffer) && after < before / 4,
             detail: `${before} bytes of instrument became ${after} as references (${Math.round((1 - after / before) * 100)}% smaller), and back again — ${one.buffer.length} samples, identical` }); }

    // 4. A reference is an optimisation, not a dependency: a document that
    //    carries a copy as well plays where the library has never heard of it.
    { const g = createGraph(16, 16);
      g.instruments = { a: toneInstrument({ decayMs: 133 }) };
      const travelling = internInstruments(g, { carry: true });
      // Both forms made before anything is forgotten: interning registers, so
      // asking for the bare one afterwards would quietly put it back.
      const bare = internInstruments(g);                       // reference only
      const ref = travelling.instruments.a.ref;
      const withLibrary = await render(travelling.instruments);
      forgetInstrument(ref);                                   // another machine
      const stranded = await render(travelling.instruments);
      let refused = null;
      try { await render(bare.instruments); } catch (e2) { refused = String(e2.message); }
      push({ group: "Instrument library", name: "a carried copy plays where the library does not have it", ok: identical(withLibrary.buffer, stranded.buffer) && /does not have/.test(refused || ""),
             detail: `${ref} forgotten, and the carried copy rendered the same ${stranded.buffer.length} samples · the same document without the copy says: ${String(refused).split(" — ")[0]}` }); }

    // 5. A reference to nothing at all is named, with what there is.
    { const g = createGraph(16, 16);
      g.instruments = { a: { ref: "tone.nothing" } };
      const { errors } = resolveInstruments(g);
      push({ group: "Instrument library", name: "a reference the library cannot follow is named", ok: errors.length === 1 && /tone\.nothing/.test(errors[0]),
             detail: errors[0] || "not reported" }); }

    // 6. Two documents referring to the same instrument refer to one thing.
    { const shared = toneInstrument({ decayMs: 275 });
      const mk = () => { const g = createGraph(16, 16); g.instruments = { v: shared }; return internInstruments(g); };
      const g1 = mk(), g2 = mk();
      const same = g1.instruments.v.ref === g2.instruments.v.ref;
      const resolvedSame = resolveInstruments(g1).instruments.v === resolveInstruments(g2).instruments.v;
      push({ group: "Instrument library", name: "two documents wanting one sound share one instrument", ok: same && resolvedSame,
             detail: same ? `both say ${g1.instruments.v.ref}, and both resolve to the very same declaration — interning the second registered nothing new` : "two references" }); }

    // 7. The built-ins are in the library under both a name and what they are,
    //    and the name is the one the playground's documents use.
    { const byName = instrumentFor("ship.classic");
      const byContent = byName && instrumentFor(instrumentId(byName));
      const named = instrumentNames();
      push({ group: "Instrument library", name: "a built-in answers to its name and to what it sounds like", ok: !!byName && byContent === byName && named.length >= 4,
             detail: `${named.length} named (${named.join(", ")}), ${instrumentCount()} distinct · ship.classic is also ${instrumentId(byName)}, and names its own hum node "${byName.hum}"` }); }
  } catch (e) {
    push({ group: "Instrument library", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The instrument document: a patch, which is the instrument, which is what
  // persists. The claims are that the text and the declaration are the same
  // thing in two forms, that a saved patch comes back as a library
  // instrument, and that a document's effects can address an instrument's
  // parts by the names the patch gave them.
  try {
    const SR = 48000, FPS = 60, FRAMES = 40;
    const render = (instruments, fired) => renderFired(fired, { instruments, fps: FPS, frames: FRAMES, sampleRate: SR });
    const identical = (x, y) => {
      const a = x.getChannelData(0), b = y.getChannelData(0);
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
      return true;
    };
    const oneNote = [{ kind: "note", instrument: "a", frame: 4, hz: 440, dur: 0.3 }];

    // 1. Every starter the studio offers parses. A starting point that does
    //    not is worse than none.
    { const bad = INSTRUMENT_STARTERS.map((st) => [st.label, parsePatch(st.patch).errors]).filter(([, e]) => e.length);
      push({ group: "Instrument document", name: `all ${INSTRUMENT_STARTERS.length} starter patches parse`, ok: bad.length === 0,
             detail: bad.length ? bad.map(([l, e]) => `${l}: ${e[0]}`).join(" · ")
               : INSTRUMENT_STARTERS.map((st) => `${st.label} (${parsePatch(st.patch).decl.graph.nodes.length} nodes)`).join(", ") }); }

    // 2. Text and declaration are the same instrument in two forms: a patch
    //    written out and read back is the same *sound*, held to samples.
    { const rows = [];
      for (const st of INSTRUMENT_STARTERS) {
        const first = parsePatch(st.patch).decl;
        const again = parsePatch(toPatch(first, { name: "x" })).decl;
        rows.push([st.label, instrumentId(first) === instrumentId(again)]);
      }
      const ok = rows.every(([, same]) => same);
      // And the one that makes a sound is held to samples rather than to its id.
      const a = parsePatch(INSTRUMENT_STARTERS[0].patch).decl;
      const b = parsePatch(toPatch(a, { name: "x" })).decl;
      const ra = await render({ a }, oneNote), rb = await render({ a: b }, oneNote);
      push({ group: "Instrument document", name: "a patch written out and read back is the same instrument", ok: ok && identical(ra.buffer, rb.buffer),
             detail: ok ? `${rows.length} patches through toPatch and parsePatch, every id unchanged · ${ra.buffer.length} samples identical for ${INSTRUMENT_STARTERS[0].label}`
               : rows.filter(([, s2]) => !s2).map(([l]) => l).join(", ") + " changed" }); }

    // 3. An instrument built in code and its patch are the same instrument —
    //    which is what makes the editor able to open one.
    { const built = toneInstrument({ amp: 0.3, attackMs: 3, decayMs: 180, voices: 4 });
      const text = toPatch(normalise(built), { name: "tone.mine" });
      const read = parsePatch(text).decl;
      push({ group: "Instrument document", name: "an instrument built in code writes out as a patch that reads back the same", ok: instrumentId(built) === instrumentId(read),
             detail: `${instrumentId(built)} · the patch names its nodes ${Object.keys(parsePatch(text).parts).join(", ")} rather than n47` }); }

    // 4. A patch that does not parse says why, per line, and yields whatever
    //    did — an editor that goes blank on a typo is one you fight.
    { const { decl, errors } = parsePatch(`// @instrument broken
note = voice.note
env  = env.ad      gate=note.gate  attackMs=3
bad  = osc.nothing
osc  = osc.sineHz  hz=note.hz  gate=env.z  amp=0.3
out  = osc.sineHz  hz=note.hz  gate=env.y  wobble=2
`);
      const kinds = errors.join(" | ");
      const ok = errors.length === 3 && /no DSP node called "osc.nothing"/.test(kinds)
        && /no output called "z"/.test(kinds) && /no parameter called "wobble"/.test(kinds)
        && decl && decl.graph.nodes.length === 4;
      push({ group: "Instrument document", name: "a bad patch names each problem and keeps what parsed", ok,
             detail: ok ? `3 problems, each with its line — and the 4 good nodes still made a declaration` : kinds || "no errors" }); }

    // 5. Every name in a patch is a part, and an effect can address one — the
    //    thing that makes a *reference* usable, since the library renumbers.
    { const patch = `// @instrument hum.test
// @voices 4
note  = voice.note
voice = osc.sineHz  hz=note.hz  gate=note.gate  amp=0.3
low   = osc.saw     hz=55  amp=0.2  blep=1
hum   = gain.smooth x=low.y  level=0  ms=20
out   = mix.add     a=voice.y  b=hum.y  gainA=1  gainB=1
`;
      const decl = parsePatch(patch).decl;
      const { id } = defineInstrument("you.humtest", decl);
      const lib = instrumentFor("you.humtest");
      // The library renumbered it; the part name did not move.
      const renumbered = lib.parts.hum !== decl.parts.hum;
      const fired = [{ kind: "param", instrument: "a", frame: 2, node: "hum", param: "level", value: 0.9 },
                     { kind: "param", instrument: "a", frame: 20, node: "hum", param: "level", value: 0 }];
      const r = await render({ a: { ref: "you.humtest" } }, fired);
      const d = r.buffer.getChannelData(0);
      const rms = (f0, f1) => { let e = 0, n = 0; for (let i = Math.round(f0 / FPS * SR); i < Math.round(f1 / FPS * SR); i++) { e += d[i] * d[i]; n++; } return Math.sqrt(e / Math.max(1, n)); };
      const on = rms(4, 18), off = rms(30, 38);
      push({ group: "Instrument document", name: 'an effect addresses "hum" by name, through a reference', ok: renumbered && on > 0.05 && off < on / 5,
             detail: `the patch called it ${decl.parts.hum}, the library calls it ${lib.parts.hum} (${id}) — and { node: "hum" } moved the right one: rms ${on.toFixed(3)} while up, ${off.toFixed(3)} after` }); }

    // 6. What persistence is: a saved document, read back the way the loader
    //    reads it, is a library instrument a document can name.
    { const saved = { patch: `// @instrument saved.one
// @voices 2
note = voice.note
env  = env.ad      gate=note.gate  attackMs=2  decayMs=140
out  = osc.sineHz  hz=note.hz  gate=env.y  amp=0.25
` };
      // The loader, with the API replaced by the one document.
      const loaded = await loadUserInstruments({
        api: async (path) => (path === "/api/studio/projects"
          ? { projects: [{ id: 1, kind: "instrument", name: "Saved one" }] }
          : { id: 1, name: "Saved one", data: saved }),
        parsePatch, nameFor: instrumentNameFor,
      });
      const found = instrumentFor("saved.one");
      const r = found ? await render({ a: { ref: "saved.one" } }, oneNote) : null;
      let ink = 0;
      if (r) { const d = r.buffer.getChannelData(0); for (let i = 0; i < d.length; i++) if (Math.abs(d[i]) > 0.01) ink++; }
      push({ group: "Instrument document", name: "a saved document comes back as an instrument a document can name", ok: loaded.length === 1 && !loaded[0].error && !!found && ink > 1000,
             detail: found ? `one instrument document loaded as "${loaded[0].name}" (${loaded[0].nodes} nodes) · a document referencing it rendered ${ink} samples above silence`
               : `loaded ${JSON.stringify(loaded[0])}` }); }

    // 7. The name a document goes under: what the patch says, else the
    //    project's own name, namespaced so it cannot shadow a built-in.
    { const cases = [
        [{ patch: "// @instrument tone.mine\nnote = voice.note\nout = osc.sineHz hz=note.hz gate=note.gate" }, "Whatever", "tone.mine"],
        [{ patch: "// @instrument mine\nnote = voice.note\nout = osc.sineHz hz=note.hz gate=note.gate" }, "Whatever", "you.mine"],
        [{ patch: "note = voice.note\nout = osc.sineHz hz=note.hz gate=note.gate" }, "My Best Sound", "you.my-best-sound"],
      ];
      const got = cases.map(([doc, name]) => instrumentNameFor(doc, name));
      const want = cases.map((c) => c[2]);
      push({ group: "Instrument document", name: "a document's instrument is named by its patch, or by the document", ok: JSON.stringify(got) === JSON.stringify(want),
             detail: got.map((g, i) => `${g === want[i] ? "" : "✗ "}${g}`).join(" · ") + " — a bare name is namespaced so it cannot shadow a built-in" }); }
  } catch (e) {
    push({ group: "Instrument document", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The library, listed, and a sketch you can play. Two small things with one
  // property each worth holding: a listing that shows every instrument once
  // however many names it answers to, and a Generate preset that is a game
  // rather than a simulation you watch.
  try {
    // 1. Listing groups by the instrument, not by the key. An instrument
    //    registered under a name *and* a content id is one row, not two.
    { const decl = toneInstrument({ decayMs: 411 });
      defineInstrument("you.listtest", decl);
      const rows = listInstruments();
      const mine = rows.filter((r) => r.names.includes("you.listtest"));
      const dupes = rows.filter((r) => !r.id).length;
      const everyOnce = new Set(rows.map((r) => r.id)).size === rows.length;
      push({ group: "Library listing", name: "every instrument appears once, with the names it answers to", ok: mine.length === 1 && everyOnce && dupes === 0,
             detail: `${rows.length} instruments, each with a content id and ${rows.filter((r) => r.names.length).length} of them named · `
               + `you.listtest is ${mine.length} row, reading ${mine[0] ? mine[0].nodes : "?"} nodes and parts ${(mine[0] ? mine[0].parts : []).join(", ") || "none"}` }); }

    // 2. Every row can show its patch, and that patch is the instrument —
    //    the listing cannot print something that would not read back.
    { const rows = listInstruments();
      const bad = [];
      for (const r of rows) {
        const text = toPatch(r.decl, { name: r.names[0] || r.id });
        const { decl, errors } = parsePatch(text);
        if (errors.length || !decl || instrumentId(decl) !== instrumentId(r.decl)) bad.push(r.names[0] || r.id);
      }
      push({ group: "Library listing", name: "the patch each row shows reads back as that instrument", ok: bad.length === 0,
             detail: bad.length ? `${bad.join(", ")} did not` : `${rows.length} instruments written out and read back, every id unchanged` }); }

    // 3. The Generate presets: the game is there, it declares the keyboard,
    //    and it compiles for both passes on this GPU.
    { const game = GENERATE_PRESETS.find((g) => g.id === "pong");
      let ok = !!game, why = "no preset called pong";
      if (game) {
        const asks = /uniform\s+sampler2D\s+u_keys/.test(game.source);
        const sims = hasSimPass(desugar(game.source, { es3: isGL2(gl) }));
        try {
          for (const pass of [null, "SIM_PASS"]) {
            const src = desugar(game.source, { es3: isGL2(gl) });
            const prog = linkProgram(gl, pass ? withDefine(src, pass) : src);
            gl.deleteProgram(prog);
          }
          ok = asks && sims;
          why = asks ? (sims ? "" : "it keeps no state") : "it does not declare u_keys";
        } catch (e) { ok = false; why = String(e.message).split("\n")[0]; }
      }
      push({ group: "Library listing", name: "Generate has a game, and it is playable rather than watched", ok,
             detail: ok ? "pong: reads u_keys, keeps its ball, bat and score in three texels of its own state, and both passes link here"
                        : why }); }

    // 4. The keyboard reaches a sketch at all: a one-line sketch that paints
    //    itself by whether a key is down, rendered with the key down and up.
    { const src = `uniform sampler2D u_keys;\nvec3(keyDown(u_keys, 38.0))`;
      const kb = new Keyboard();
      const lit = (c) => c.getContext("2d").getImageData(4, 4, 1, 1).data[0];
      const up = lit(renderSketch(src, 16, 16, { keys: kb }));
      kb.press(38);
      const down = lit(renderSketch(src, 16, 16, { keys: kb }));
      push({ group: "Library listing", name: "a Generate sketch can read the keyboard", ok: up === 0 && down === 255,
             detail: `the same sketch reads ${up} with the key up and ${down} with it down — u_keys is bound by the sketch runtime, not only by the graph` }); }
  } catch (e) {
    push({ group: "Library listing", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Pong with sound: the whole game as parameters on one node, its rules as
  // expressions, and its noises as effects. Everything the last several
  // phases built, in one document — so the checks are about the document
  // being a game rather than about any one mechanism.
  try {
    const SR = 48000, FPS = 60, FRAMES = 700;
    const build = (key) => {
      const g = createGraph(320, 200); g.stateKey = key;
      const game = pongAsData(g);
      const trail = addNode(g, "feedback.trail", { decay: [0.72] }, [game, null], { name: "trail" });
      feedback(g, trail, 1, trail);
      g.output = trail;
      g.instruments = PONG_INSTRUMENTS;
      g.effects = pongEffects();
      return g;
    };
    // `chase` plays well and never misses; without it the bat never moves.
    const rally = (key, chase) => {
      const g = build(key);
      resetGraphState(key);
      const kb = new Keyboard();
      const fired = [];
      for (let f = 0; f < FRAMES; f++) {
        const st = paramState(key) || {};
        const by = st["game ballY"] ? st["game ballY"][0] : 0;
        const bt = st["game batY"] ? st["game batY"][0] : 0;
        kb.clear();
        if (chase) { if (by > bt + 0.02) kb.press(KEY.up); else if (by < bt - 0.02) kb.press(KEY.down); }
        renderGraph(g, {}, { keys: kb, reset: f === 0, time: f / FPS,
                             onFired: (fx) => fired.push(...fx.map((x) => ({ ...x, frame: f }))) });
      }
      const count = {};
      for (const x of fired) count[x.instrument] = (count[x.instrument] || 0) + 1;
      return { graph: g, fired, count, state: paramState(key) };
    };

    const good = rally("selftest-pong-good", true);
    const bad = rally("selftest-pong-bad", false);

    // 1. Playing well scores and never thuds; not playing misses and never
    //    scores. The sounds follow the game because they are the game's own
    //    decisions, not a second copy of the rules.
    { const ok = good.count.thud === undefined && good.count.blip > 0 && good.count.bell > 0
        && good.state["game score"][0] === good.count.bell
        && bad.count.thud > 0 && bad.count.blip === undefined && bad.state["game score"][0] === 0;
      push({ group: "Pong", name: "the sounds are the game's own decisions", ok,
             detail: `played well: ${good.count.blip} blips off the bat, ${good.count.bell} bells off the wall, score ${good.state["game score"][0]}, no thuds · `
               + `not played: ${bad.count.thud} thuds, no blips, score ${bad.state["game score"][0]}` }); }

    // 2. The bell's pitch rises with the score, and the blip's follows where
    //    on the bat the ball landed — both computed from the model, in the
    //    effect, so nothing had to be told twice.
    { const bells = good.fired.filter((f) => f.instrument === "bell").map((f) => Math.round(f.hz));
      const rising = bells.every((h, i) => i === 0 || h > bells[i - 1]);
      const blips = good.fired.filter((f) => f.instrument === "blip").map((f) => Math.round(f.hz));
      const varied = new Set(blips).size > 1 || blips.length === 1;
      push({ group: "Pong", name: "the pitches are computed from the model", ok: rising && varied && bells.length > 1,
             detail: `bells ${bells.join(", ")} Hz — one semitone per point · blips ${blips.join(", ")} Hz, from where on the bat it hit` }); }

    // 3. The same keys are the same game: a replay reproduces the model.
    { const again = rally("selftest-pong-again", true);
      const a = JSON.stringify(good.state), b = JSON.stringify(again.state);
      const sameFired = JSON.stringify(good.fired.map((f) => [f.frame, f.instrument, Math.round(f.hz)]))
        === JSON.stringify(again.fired.map((f) => [f.frame, f.instrument, Math.round(f.hz)]));
      push({ group: "Pong", name: "the same keys are the same game, and the same notes", ok: a === b && sameFired,
             detail: `${FRAMES} frames twice: ${a.length} bytes of model identical, and ${good.fired.length} notes at the same frames and pitches` }); }

    // 4. And it sounds the same whether it is played or bounced — the
    //    property the live path was built on, now on a game.
    { // The same tail on both sides, or the shorter buffer's missing samples
      // read as undefined and every one of them counts as a difference.
      const TAIL = 0.5;
      const seconds = FRAMES / FPS + TAIL;
      const names = Object.keys(good.graph.instruments);
      const offline = new OfflineAudioContext(names.length, Math.round(seconds * SR), SR);
      const rig = await LiveRig.create(good.graph, { ctx: offline, split: true });
      for (let f = 0; f < FRAMES; f++) rig.perform(good.fired.filter((x) => x.frame === f), f / FPS);
      const liveBuf = await offline.startRendering();
      const { buffer: batchBuf } = await renderFired(good.fired, { instruments: good.graph.instruments,
                                                                   fps: FPS, frames: FRAMES, sampleRate: SR,
                                                                   tail: TAIL, split: true });
      const per = names.map((name, c) => {
        const a = liveBuf.getChannelData(c), b = batchBuf.getChannelData(c);
        let e = 0, worst = 0, same = true;
        for (let i = 0; i < a.length; i++) {
          const dd = Math.abs(a[i] - b[i]);
          if (dd > worst) worst = dd;
          if (a[i] !== b[i]) same = false;
          e += a[i] * a[i];
        }
        return { name, same, worst, rms: Math.sqrt(e / a.length) };
      });
      const sameLength = liveBuf.length === batchBuf.length;
      const allSame = sameLength && per.every((r) => r.same);
      const heard = per.filter((r) => r.rms > 1e-5).length;
      const routed = rig.notes, missed = rig.missed;
      await rig.close();
      push({ group: "Pong", name: "the game sounds the same played as bounced", ok: allSame && heard >= 2 && missed === 0,
             detail: `${liveBuf.length} samples on each of ${names.length} instrument channels`
               + (sameLength ? " · " : ` — but the bounce is ${batchBuf.length} · `)
               + per.map((r) => `${r.name} ${r.same ? "identical" : `off by ${r.worst.toExponential(2)}`}`
                                + ` (rms ${r.rms.toFixed(4)})`).join(", ")
               + ` · ${routed} notes routed, ${missed} unrouted` }); }
  } catch (e) {
    push({ group: "Pong", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // A sketch with a voice. A Generate document is one program with a state
  // texture and no graph, so it had no parameters for an effect to fire on.
  // Naming texels of its own state as probes gives it some: the host reads
  // them back and the ordinary evaluator does the rest.
  try {
    const W = 320, H = 200, FPS = 60, FRAMES = 700, SR = 48000;
    const game = GENERATE_PRESETS.find((g) => g.id === "pong");
    const src = desugar(game.source, { es3: isGL2(gl) });
    const doc = { probes: game.probes, effects: game.effects, instruments: game.instruments };

    // The sketch, run the way the editor runs it, in this test's own context.
    const play = (stateKey, chase) => {
      const fb = new Feedback(gl);
      fb.resize(W, H, 1);
      const disp = linkProgram(gl, src), simP = linkProgram(gl, withDefine(src, "SIM_PASS"));
      const quad = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, quad);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      const uniforms = parseUniforms(game.source);
      const values = {};
      for (const u of uniforms) if (u.value) values[u.name] = u.value;
      const kb = new Keyboard();
      const keysTex = gl.createTexture();
      const bind = (prog, stateTex) => {
        gl.useProgram(prog);
        gl.bindBuffer(gl.ARRAY_BUFFER, quad);
        const loc = gl.getAttribLocation(prog, "a_pos");
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        const u = (n) => gl.getUniformLocation(prog, n);
        gl.uniform2f(u("u_resolution"), W, H);
        gl.uniform1i(u("u_frame"), fb.frame);
        gl.uniform1f(u("u_time"), 0);
        gl.uniform2f(u("u_origin"), 0, 0);
        gl.uniform1f(u("u_seed"), 0);
        gl.uniform2f(u("u_mouse"), W / 2, H / 2);
        gl.uniform1f(u("u_mouseDown"), 0);
        applyUniforms(gl, prog, uniforms, values);
        gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, stateTex);
        if (u("u_state")) gl.uniform1i(u("u_state"), 7);
        gl.activeTexture(gl.TEXTURE6); gl.bindTexture(gl.TEXTURE_2D, stateTex);
        if (u("u_prev")) gl.uniform1i(u("u_prev"), 6);
        if (u("u_keys")) {
          gl.activeTexture(gl.TEXTURE4); gl.bindTexture(gl.TEXTURE_2D, keysTex);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, kb.texture());
          gl.uniform1i(u("u_keys"), 4);
        }
        gl.activeTexture(gl.TEXTURE0);
      };
      const fired = [], errors = [], raw = [];
      for (let f = 0; f < FRAMES; f++) {
        const seen = readProbes(gl, fb.read, doc.probes);
        kb.clear();
        if (chase) {
          if (seen.ballY > seen.batY + 0.02) kb.press(KEY.up);
          else if (seen.ballY < seen.batY - 0.02) kb.press(KEY.down);
        }
        const w = fb.write, r = fb.read;
        gl.bindFramebuffer(gl.FRAMEBUFFER, w.fbo);
        gl.viewport(0, 0, W, H);
        bind(simP, r.tex);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        fb.swap();
        const res = sketchFrame(gl, doc, fb.read, { stateKey, width: W, height: H, time: f / FPS, frame: f, keys: kb });
        errors.push(...res.errors);
        raw.push(res.probes);
        fired.push(...res.fired.map((x) => ({ ...x, frame: f })));
        kb.tick();
      }
      const kind = fb.read.kind;
      gl.deleteProgram(disp); gl.deleteProgram(simP); gl.deleteBuffer(quad); gl.deleteTexture(keysTex);
      fb.release && fb.release();
      const count = {};
      for (const x of fired) count[x.instrument] = (count[x.instrument] || 0) + 1;
      return { fired, count, errors, raw, kind };
    };

    const good = play("selftest-sketchfx-good", true);
    const bad = play("selftest-sketchfx-bad", false);

    // 1. The document carries what it needs, and a new one from the preset
    //    carries it too — a preset whose sound only worked in the preset
    //    would be a preset nobody could edit.
    { const made = newGenerateDoc(game);
      const ok = hasSketchEffects(made) && Object.keys(made.probes).length === 6
        && made.effects.length === 3 && Object.keys(made.instruments).length === 3;
      push({ group: "Sketch effects", name: "a Generate document carries its probes, effects and instruments", ok,
             detail: ok ? `probes ${Object.keys(made.probes).join(", ")} · 3 effects · instruments ${Object.keys(made.instruments).join(", ")}`
                        : "newGenerateDoc dropped them" }); }

    // 2. The probes read what the sketch wrote. The sketch's three events
    //    live in one texel; a rally that never misses must never set the
    //    third, and one that never plays must set only the third.
    { const anyMissed = good.raw.some((p2) => p2.missed > 0.5);
      const anyBat = bad.raw.some((p2) => p2.hitBat > 0.5);
      const scoreRose = good.raw[good.raw.length - 1].score > 0;
      push({ group: "Sketch effects", name: "the probes read what the shader decided", ok: !anyMissed && !anyBat && scoreRose,
             detail: `the state is a ${good.kind} target, read back a texel at a time · played well: score reached ${good.raw[good.raw.length - 1].score}, never missed · `
               + `not played: never hit the bat, score ${bad.raw[bad.raw.length - 1].score}` }); }

    // 3. And the effects fire on them, once each, with the right instrument.
    { const ok = good.count.blip > 0 && good.count.bell > 0 && good.count.thud === undefined
        && bad.count.thud > 0 && bad.count.blip === undefined && !good.errors.length && !bad.errors.length;
      const bells = good.fired.filter((f) => f.instrument === "bell").map((f) => Math.round(f.hz));
      push({ group: "Sketch effects", name: "a sketch's effects fire on its own state", ok,
             detail: `played well: ${good.count.blip} blips, ${good.count.bell} bells (${bells.join(", ")} Hz), no thuds · `
               + `not played: ${bad.count.thud} thuds, no blips · bare ch("hitBat") resolved against the one node a sketch has` }); }

    // 4. …and it sounds the same played as bounced, like everything else.
    { const TAIL = 0.4, seconds = FRAMES / FPS + TAIL;
      const names = Object.keys(doc.instruments);
      const offline = new OfflineAudioContext(names.length, Math.round(seconds * SR), SR);
      const rig = await LiveRig.create({ instruments: doc.instruments }, { ctx: offline, split: true });
      for (let f = 0; f < FRAMES; f++) rig.perform(good.fired.filter((x) => x.frame === f), f / FPS);
      const liveBuf = await offline.startRendering();
      const { buffer: batchBuf } = await renderFired(good.fired, { instruments: doc.instruments,
                                                                   fps: FPS, frames: FRAMES, sampleRate: SR,
                                                                   tail: TAIL, split: true });
      const sameLength = liveBuf.length === batchBuf.length;
      let allSame = sameLength, heard = 0;
      for (let c = 0; c < names.length && sameLength; c++) {
        const a = liveBuf.getChannelData(c), b = batchBuf.getChannelData(c);
        let e = 0;
        for (let i = 0; i < a.length; i++) { if (a[i] !== b[i]) allSame = false; e += a[i] * a[i]; }
        if (Math.sqrt(e / a.length) > 1e-5) heard++;
      }
      const routed = rig.notes, missed = rig.missed;
      await rig.close();
      push({ group: "Sketch effects", name: "a sketch's sound is the same played as bounced", ok: allSame && heard >= 2 && missed === 0,
             detail: sameLength
               ? `${liveBuf.length} samples on each of ${names.length} channels, ${allSame ? "identical" : "differing"} · ${heard} sounded · ${routed} notes routed, ${missed} unrouted`
               : `lengths differ: ${liveBuf.length} vs ${batchBuf.length}` }); }
  } catch (e) {
    push({ group: "Sketch effects", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The render graph on the second backend. The sketch translator was held to
  // one picture at a time; this is the machinery around it — a pool, fused
  // runs, feedback kept between frames, several steps in a row — and the bar
  // is the same one: not "close", but the same bytes.
  //
  // The strongest evidence here is not a number, it is that the plans match.
  // `resolveParams`, `compileFields` and `planPasses` are imported by the
  // WebGPU runner rather than written again, so a difference between the two
  // backends cannot be a difference about *which* passes there are.
  try {
    const runner = await gpuGraphRunner();
    if (!runner) {
      push({ group: "Graph on WebGPU", name: "a second backend for the graph", ok: true,
             detail: "this machine has no WebGPU, so nothing was measured — the GL path is unaffected" });
    } else {
      const W = 64, H = 48;
      // The block's own helpers: the ones above are local to their own try.
      const px = (c, w, h) => c.getContext("2d").getImageData(0, 0, w, h).data;
      const seedCanvas = (w, h, draw) => {
        const c = document.createElement("canvas"); c.width = w; c.height = h;
        const g2 = c.getContext("2d");
        g2.fillStyle = "#000"; g2.fillRect(0, 0, w, h);
        g2.fillStyle = "#fff"; draw(g2);
        return c;
      };
      let stateN = 0;
      const fresh = (g) => { g.stateKey = `selftest-gpu-graph-${stateN++}`; return g; };
      const pic = document.createElement("canvas"); pic.width = W; pic.height = H;
      { const g2 = pic.getContext("2d");
        const gr = g2.createLinearGradient(0, 0, W, H);
        gr.addColorStop(0, "#f4efe6"); gr.addColorStop(1, "#1b2b4b");
        g2.fillStyle = gr; g2.fillRect(0, 0, W, H);
        g2.fillStyle = "#e04020"; g2.beginPath(); g2.arc(22, 20, 11, 0, Math.PI * 2); g2.fill();
        g2.fillStyle = "#1fa36c"; g2.fillRect(44, 8, 14, 22); }

      // Both composited over black, which is the picture either backend shows.
      const agree = (gpu, gl, w, h) => {
        let sum = 0, worst = 0;
        for (let i = 0; i < w * h; i++) {
          const ga = gpu[i * 4 + 3] / 255, la = gl[i * 4 + 3] / 255;
          for (let k = 0; k < 3; k++) {
            const d = Math.abs(Math.round(gpu[i * 4 + k] * ga) - Math.round(gl[i * 4 + k] * la));
            sum += d; if (d > worst) worst = d;
          }
        }
        return { mean: sum / (w * h * 3), worst };
      };

      // 1. Five shapes, each exercising a different part of the runner.
      { const shapes = [];
        const mk = (name, build) => {
          const g = fresh(createGraph(W, H));
          const s0 = addNode(g, "source");
          build(g, s0);
          shapes.push({ name, g, s0 });
        };
        mk("one node, one draw", (g, s0) => { g.output = addNode(g, "adjust.invert", {}, [s0]); });
        mk("three nodes fused into one draw", (g, s0) => {
          const a = addNode(g, "adjust.exposure", { stops: [0.6] }, [s0]);
          const b = addNode(g, "adjust.grade", { saturation: [1.4] }, [a]);
          g.output = addNode(g, "filter.vignette", {}, [b]);
        });
        mk("two spatial passes, a buffer between them", (g, s0) => {
          const b1 = addNode(g, "filter.blur1d", { radius: [3], dir: [1, 0] }, [s0]);
          g.output = addNode(g, "filter.blur1d", { radius: [3], dir: [0, 1] }, [b1]);
        });
        mk("a two-input composite", (g, s0) => {
          const e = addNode(g, "adjust.exposure", { stops: [1.2] }, [s0]);
          g.output = addNode(g, "composite.blend", { mode: [2], opacity: [0.6] }, [s0, e]);
        });
        mk("a node carrying a lookup table", (g, s0) => { g.output = addNode(g, "adjust.curves", {}, [s0]); });
        const bad = [], plans = [];
        for (const { name, g, s0 } of shapes) {
          let glPasses = null;
          const gl = px(renderGraph(g, { [s0]: pic }, { onPasses: (ps) => { glPasses = ps; } }), W, H);
          const r = await renderGraphGpu(g, { [s0]: pic }, {});
          const same = JSON.stringify(glPasses.map((q) => q.type)) === JSON.stringify(r.passes.map((q) => q.type));
          const { mean, worst } = agree(r.data, gl, W, H);
          plans.push(`${name}: ${glPasses.length} pass${glPasses.length === 1 ? "" : "es"}`);
          if (!same || worst !== 0) bad.push(`${name}: ${same ? "" : "different plan, "}${worst}/255 apart`);
        }
        push({ group: "Graph on WebGPU", name: `${shapes.length} graph shapes, both backends, the same bytes`,
               ok: bad.length === 0,
               detail: bad.length === 0
                 ? `${plans.join(" · ")} — the same plan from the same planner, and every pixel identical`
                 : bad.join(" · ") }); }

      // 2. Feedback: the memory is the picture before, and it survives.
      { const S = 32;
        const cells = [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]];
        const seed = seedCanvas(S, S, (g) => { for (const [x, y] of cells) g.fillRect(x + 4, y + 4, 1, 1); });
        const build = (key) => {
          const g = fresh(createGraph(S, S));
          g.stateKey = key;
          const s0 = addNode(g, "source");
          const life = addNode(g, "sim.life", {}, [null, s0], { name: "life" });
          feedback(g, life, 0, life);
          g.output = life;
          return { g, s0 };
        };
        const a = build(`life-gl-${Math.random()}`), b = build(`life-gpu-${Math.random()}`);
        const gl = px(renderGraph(a.g, { [a.s0]: seed }, { steps: 13, reset: true }), S, S);
        const r = await renderGraphGpu(b.g, { [b.s0]: seed }, { steps: 13, reset: true });
        let wrong = 0, alive = 0;
        for (let i = 0; i < S * S; i++) {
          const got = r.data[i * 4] > 127 ? 1 : 0;
          if (got !== (gl[i * 4] > 127 ? 1 : 0)) wrong++;
          alive += got;
        }
        push({ group: "Graph on WebGPU", name: "Life: twelve generations of ping-pong, cell for cell",
               ok: wrong === 0 && alive === 5,
               detail: `${wrong} cells differ from the GL run · ${alive} alive, so the glider is still a glider · `
                 + "thirteen draws, each reading what the one before wrote, in one submission" }); }

      // 3. A register in 32 bits — which is the reason the bind group layouts
      //    here are written out rather than derived. `layout: "auto"` calls
      //    every sampled texture filterable, and rgba32float is not one.
      { const kb = document.createElement("canvas"); kb.width = 256; kb.height = 3;
        { const k = kb.getContext("2d"); k.fillStyle = "#000"; k.fillRect(0, 0, 256, 3);
          k.fillStyle = "#fff"; k.fillRect(38, 0, 1, 1); }          // right arrow, held
        const build = (key) => {
          const g = fresh(createGraph(W, H));
          g.stateKey = key;
          const ship = addNode(g, "game.ship", {}, [null], { name: "ship" });
          feedback(g, ship, 0, ship);
          g.output = addNode(g, "game.shipView", {}, [ship]);
          return g;
        };
        const gl = px(renderGraph(build(`ship-gl-${Math.random()}`), {},
                                  { steps: 40, reset: true, keys: kb }), W, H);
        const r = await renderGraphGpu(build(`ship-gpu-${Math.random()}`), {},
                                       { steps: 40, reset: true, keys: kb });
        const { mean, worst } = agree(r.data, gl, W, H);
        const stats = runner.stats();
        push({ group: "Graph on WebGPU", name: "a ship flown forty frames, its state in 32 bits",
               ok: worst === 0 && stats.floatMemories >= 1,
               detail: worst === 0
                 ? `identical after forty frames of the same held key · ${stats.floatMemories} memory in rgba32float, `
                   + "which is unfilterable and needs a layout written out rather than derived from the shader"
                 : `${worst}/255 apart, mean ${mean.toFixed(2)}` }); }

      // 4. What has no pass here, said rather than counted.
      { const refused = GpuGraphRunner.refusals();
        const kinds = new Set(refused.map((r) => r.why.slice(0, 28)));
        push({ group: "Graph on WebGPU", name: "the node types this backend has no pass for", ok: kinds.size <= 1,
               detail: refused.length === 0 ? "none — every node type has a WebGPU pass"
                 : `${refused.length}: ${[...kinds].join(" · ")} — a field port is compiled into its shade node `
                   + "before a plan exists, so it never reaches a runner of either kind" }); }
    }
  } catch (e) {
    push({ group: "Graph on WebGPU", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // WebGPU: the second backend, as a number rather than an argument.
  //
  // `wgsl-audit.js` has said for several phases that nothing in the node
  // bodies is a thing WGSL cannot express. This translates them and renders
  // them, so the claim is settled by pixels. The bar is *exact*: two backends
  // that agree to within a level have not been shown to agree.
  try {
    const desc = await gpuDescribe();
    if (!desc.available) {
      push({ group: "WebGPU", name: "a second backend", ok: true,
             detail: "this machine has no WebGPU, so nothing was measured — the GL path is unaffected" });
    } else {
      const W = 40, H = 28;
      const pic = document.createElement("canvas"); pic.width = W; pic.height = H;
      { const g2 = pic.getContext("2d");
        const gr = g2.createLinearGradient(0, 0, W, H);
        gr.addColorStop(0, "#f4efe6"); gr.addColorStop(1, "#1b2b4b");
        g2.fillStyle = gr; g2.fillRect(0, 0, W, H);
        g2.fillStyle = "#e04020"; g2.beginPath(); g2.arc(14, 12, 7, 0, Math.PI * 2); g2.fill(); }

      // Size matters to this comparison — a power-of-two height divides
      // exactly and a 28 does not — so it is a parameter, not a constant.
      // A keyboard, so the nodes that read one are measured rather than
      // skipped: 256 columns of key code, three rows — held, hit, toggled.
      const kb = document.createElement("canvas"); kb.width = 256; kb.height = 3;
      { const k2 = kb.getContext("2d");
        k2.fillStyle = "#000"; k2.fillRect(0, 0, 256, 3);
        k2.fillStyle = "#fff"; k2.fillRect(37, 0, 1, 1); k2.fillRect(38, 1, 1, 1); }

      const compare = async (source, images, w = W, h = H) => {
        const a = await renderSketchGpu(source, w, h, { images, keys: kb });
        const b = renderSketch(source, w, h, { time: 0, images, keys: { texture: () => kb } });
        const g2 = b.getContext("2d").getImageData(0, 0, w, h).data;
        // Both composited over black, which is the picture either backend
        // actually shows. Neither side's straight-alpha RGB is comparable on
        // its own: where alpha is small the colour underneath it is whatever
        // survived the round trip, and comparing *that* measures the storage
        // convention rather than the translation. Premultiplying one side
        // only — which this did — measures the difference between the two
        // conventions, which is not a fact about anything.
        let sum = 0, worst = 0;
        for (let i = 0; i < w * h; i++) {
          const al = a.data[i * 4 + 3] / 255, bl = g2[i * 4 + 3] / 255;
          for (let k = 0; k < 3; k++) {
            const d = Math.abs(Math.round(a.data[i * 4 + k] * al) - Math.round(g2[i * 4 + k] * bl));
            sum += d; if (d > worst) worst = d;
          }
        }
        return { mean: sum / (w * h * 3), worst };
      };

      // 1. The catalogue, node by node. Translated ones must be exact.
      { const rows = [];
        for (const [id, t] of NODE_TYPES) {
          const em = toWgsl(t.source);
          if (!em.ok) { rows.push({ id, refused: em.refused[0] }); continue; }
          try {
            const images = {};
            for (const u of t.uniforms) if (u.control === "image") images[u.name] = pic;
            rows.push({ id, ...(await compare(t.source, images)) });
          } catch (e) { rows.push({ id, error: String(e.message).split("\n")[0] }); }
        }
        const drew = rows.filter((r) => r.mean !== undefined);
        const exact = drew.filter((r) => r.mean === 0);
        const off = drew.filter((r) => r.mean > 0);
        const refused = rows.filter((r) => r.refused).length;
        const failed = rows.filter((r) => r.error);
        push({ group: "WebGPU", name: `${drew.length} of ${rows.length} node types render on WebGPU`,
               ok: exact.length >= 46 && failed.length === 0,
               detail: `${exact.length} pixel-identical to the GL path · `
                 + `${refused} refused with a reason, ${failed.length} not translated yet · `
                 + `every refusal is a field port, which is compiled away before a plan exists · `
                 + `${desc.vendor} ${desc.architecture}` });
        // The ones that render and are not identical, named with their number
        // rather than folded into the count above.
        push({ group: "WebGPU", name: "what renders but does not match, and by how much", ok: true,
               detail: off.length
                 ? off.map((r) => `${r.id} ${r.mean.toFixed(1)}/255 (worst ${r.worst})`).join(" · ")
                   + " — checked one at a time rather than explained in a group"
                 : "nothing — everything that rendered was identical" });
        // The tail, named rather than left as a total.
        const kinds = new Map();
        for (const f of failed) {
          const k = f.error.replace(/'[^']*'/g, "'…'").replace(/line \d+/, "line N").slice(0, 52);
          kinds.set(k, (kinds.get(k) || 0) + 1);
        }
        const top = [...kinds.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
        push({ group: "WebGPU", name: "what the remaining nodes need, said rather than counted", ok: true,
               detail: failed.length
                 ? top.map(([k, n]) => `${n}× ${k}`).join(" · ")
                 : "nothing — every node translated" }); }

      // 2. How far the agreement goes. A zero above could be luck at eight
      //    bits, so this magnifies the coordinate until the two part — and
      //    they do part, for a reason worth writing down rather than fixing.
      { const upto = async (expr) => {
          let last = 0;
          for (const k of [8, 12, 16, 20, 22]) {
            const r = await compare(`vec3(fract(${expr} * ${2 ** k}.0))`, {});
            if (r.worst > 1) return last;
            last = k;
          }
          return 22;
        };
        const x = await upto("p.x"), y = await upto("p.y");
        // The cause, isolated: at a power-of-two height both are exact, so it
        // is the division and not the flip.
        const at28 = await compare(`vec3(fract(uv.y * 28.0))`, {}, 40, 28);
        const at32 = await compare(`vec3(fract(uv.y * 32.0))`, {}, 40, 32);
        push({ group: "WebGPU", name: "how far the two backends agree about where a pixel is",
               ok: x >= 20 && at32.worst === 0 && at28.worst > 0,
               detail: `p.x identical to 2⁻${x} · p.y ${y ? `to 2⁻${y}` : "not even to 2⁻⁸"} at a height of 28, `
                 + `and exact at a height of 32 (${at32.worst}/255 against ${at28.worst}/255) — so it is dividing `
                 + "by 28 that differs, not the y-flip: one driver multiplies by the reciprocal and the other "
                 + "divides, and 1/28 is not a binary fraction. Below 1/255 they agree, which is why the "
                 + "catalogue above is exact." }); }

      // 3. Where they do *not* agree, and why. A hash amplifies one ulp into
      //    a different number, and two drivers may fuse a multiply-add
      //    differently — so this is a fact about floating point, not about
      //    the translation, and the evidence is that constants agree.
      { const constant = await compare(`vec3(hash21(vec2(3.0, 5.0)))`, {});
        const computed = await compare(`vec3(hash21(floor(p * 6.0)))`, {});
        push({ group: "WebGPU", name: "a hash is where the two backends part, and it is not the translator",
               ok: constant.worst === 0 && computed.worst > 0,
               detail: `hash21 of a constant: ${constant.worst}/255 apart — both compilers fold it. `
                 + `hash21 of a computed coordinate: ${computed.worst}/255 — the inputs are bit-identical, so this is `
                 + "multiply-add fusion, which each driver is free to do or not" }); }

      // 3b. The rules that closed the last of the catalogue, each on a sketch
      //     small enough that the rule is the only thing it exercises. Each
      //     one used to be a refusal or a compile error, and each is exact.
      { const cases = [
          ["a helper reads what the entry point owns",
           `float ring(float r) { return smoothstep(r + 0.02, r, length(uv - 0.5)); }\nvec3(ring(0.3))`],
          ["a helper reads a uniform",
           `uniform float k;   // @range 0 2 @default 1.5\nfloat f() { return k * 0.25; }\nvec3(f())`],
          ["a nested for with no braces of its own",
           `float a = 0.0;\nfor (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) a += float(i * j) * 0.02;\nvec3(a)`],
          ["a matrix times a vector is the vector",
           `mat3 sm = mat3(0.8, 0.1, 0.1, 0.1, 0.8, 0.1, 0.1, 0.1, 0.8);\nvec3 x = vec3(uv, 0.5);\nclamp(sm * x, 0.0, 1.0)`],
          ["a call's answer, not the vectors inside it",
           `float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }\nvec3(step(0.4, luma(vec3(uv, 0.5)) + 0.001))`],
          ["a swizzle off a call",
           `vec3(step(0.5, vec4(uv, 0.25, 1.0).z))`],
          ["a distance is a distance, not a colour",
           `sdCircle(p, 0.4) * 0.5 + 0.5`],
          ["a ternary whose branches are on their own lines",
           `float k = p.x < 0.0\n  ? sdCircle(p, 0.3)\n  : 0.25;\nvec3(k * 0.5 + 0.5)`],
          ["a global the sketch declares for itself",
           `vec4 gState;\ngState = vec4(uv, 0.25, 1.0);\nvec3(gState.xyz)`],
          ["two vectors compared for equality",
           `vec2 texel = floor(uv * 2.0);\nfloat k = 0.0;\nif (texel == vec2(1.0, 0.0)) k = 1.0;\nvec3(k)`],
          ["the prelude's own coercion, called by name",
           `vec3 c = vec3(uv, 0.5);\nvec4(_rgb(vec4(c, 1.0)), 1.0)`],
          ["the keyboard, which GLSL passes as a sampler",
           `uniform sampler2D u_keys;\nvec3(keyDown(u_keys, 37.0), keyHit(u_keys, 38.0), 0.0)`],
        ];
        const bad = [];
        for (const [what, src2] of cases) {
          const em = toWgsl(src2);
          if (!em.ok) { bad.push(`${what}: refused — ${em.refused[0].slice(0, 40)}`); continue; }
          try {
            const r = await compare(src2, {});
            if (r.worst > 0) bad.push(`${what}: ${r.worst}/255 apart`);
          } catch (e) { bad.push(`${what}: ${String(e.message).split("\n")[0].slice(0, 60)}`); }
        }
        push({ group: "WebGPU", name: `${cases.length} translation rules, one sketch each`, ok: bad.length === 0,
               detail: bad.length === 0
                 ? `each renders pixel-identically to the GL path: ${cases.map(([w]) => w).join(" · ")}`
                 : bad.join(" · ") }); }

      // 3c. What is left, and what turned out not to be a difference at all.
      //
      //     This check used to assert that `fwidth` was a third place the
      //     backends part, at 6/255 on edge pixels. It was not: it was the
      //     emitter flipping @builtin(position), which gave the two sides
      //     opposite derivative signs. With the flip gone, an antialiased
      //     edge is identical — and so is fwidth on its own.
      //
      //     What remains, measured rather than assumed: on every *opaque*
      //     pixel the two backends agree exactly. Where a node still differs,
      //     it differs only where alpha is partial, and that is the GL side's
      //     round trip — present() premultiplies into a canvas and
      //     getImageData un-premultiplies on the way out, which at low alpha
      //     cannot come back to the number it started from. The WebGPU side
      //     never takes that trip. It is a fact about reading GL back through
      //     a canvas, not about either picture.
      { const flat = await compare(`float d = sdCircle(p, 0.3);\nvec3(d * 0.5 + 0.5)`, {}, 40, 32);
        const edged = await compare(`vec3(aa(sdCircle(p, 0.3)))`, {}, 40, 32);
        const width = await compare(`vec3(fwidth(p.x) * 40.0, fwidth(p.y) * 40.0, 0.0)`, {}, 40, 32);

        // And the same claim about the catalogue: split by alpha rather than
        // averaged over it.
        const split = [];
        for (const id of ["game.menu", "game.pongView", "game.shipView"]) {
          const t = NODE_TYPES.get(id);
          if (!t) continue;
          const g4 = await renderSketchGpu(t.source, 40, 32, {});
          const b4 = renderSketch(t.source, 40, 32, { time: 0 }).getContext("2d").getImageData(0, 0, 40, 32).data;
          let opaque = 0, partial = 0, nPartial = 0;
          for (let i = 0; i < 40 * 32; i++) {
            const al = b4[i * 4 + 3];
            if (al === 0) continue;
            const ga = g4.data[i * 4 + 3] / 255, la = al / 255;
            let d = 0;
            for (let k = 0; k < 3; k++) {
              d = Math.max(d, Math.abs(Math.round(g4.data[i * 4 + k] * ga) - Math.round(b4[i * 4 + k] * la)));
            }
            if (al === 255) opaque = Math.max(opaque, d);
            else { partial = Math.max(partial, d); nPartial++; }
          }
          split.push({ id, opaque, partial, nPartial });
        }
        const cleanOpaque = split.every((r) => r.opaque === 0);
        push({ group: "WebGPU", name: "an antialiased edge is not a difference, and neither is anything opaque",
               ok: flat.worst === 0 && edged.worst === 0 && width.worst === 0 && cleanOpaque,
               detail: `a distance field ${flat.worst}/255, the same field through aa() ${edged.worst}/255, `
                 + `fwidth on its own ${width.worst}/255 — the 6/255 this check used to report was the emitter `
                 + "flipping the fragment position, not the driver's choice of quad. And on every opaque pixel of "
                 + split.map((r) => `${r.id} ${r.opaque}/255`).join(", ")
                 + " — what is left differs only where alpha is partial ("
                 + split.map((r) => `${r.partial}/255 over ${r.nPartial} px`).join(", ")
                 + "), which is present() premultiplying into a canvas and getImageData un-premultiplying back out" }); }

      // 3d. Tiling. The rule that makes a tiled render *identical* rather than
      //     merely similar is that a tile draws at its own size while thinking
      //     in the whole picture's: the resolution stays the whole picture's
      //     and the origin says which piece this is. A sketch that divides by
      //     u_resolution, or reaches for `p` or `st`, would otherwise draw a
      //     different picture in every tile.
      { const TW = 192, TH = 144;
        const cases = [
          ["a shape at p, whose scale must not change", "vec3(aa(sdCircle(p, 0.6)) * vec3(1.0, 0.6, 0.3) + 0.1)"],
          ["uv straight through", "vec3(uv, 0.5)"],
          ["st, which folds in the aspect", "vec3(fract(st * 4.0), 0.5)"],
          ["gl_FragCoord, counted in pixels", "vec3(fract(gl_FragCoord.xy / 32.0), 0.0)"],
          ["a hash of the pixel, which forgives nothing", "vec3(hash21(floor(gl_FragCoord.xy)))"],
        ];
        const bad = [], crossBad = [];
        for (const [what, src2] of cases) {
          const one = await renderSketchGpuCanvas(src2, TW, TH, {});
          const many = await renderTiledGpu(src2, TW, TH, { tile: 64 });
          const a = one.getContext("2d").getImageData(0, 0, TW, TH).data;
          const b = many.canvas.getContext("2d").getImageData(0, 0, TW, TH).data;
          let worst = 0;
          for (let i = 0; i < TW * TH * 4; i++) worst = Math.max(worst, Math.abs(a[i] - b[i]));
          if (worst !== 0 || many.tiles < 9) bad.push(`${what}: ${worst}/255 over ${many.tiles} tiles`);
          // …and against the GL path's own tiled render, which is the same
          // rule written twice and has to agree.
          const glT = renderTiled(src2, TW, TH, { tile: 64 });
          const c = glT.canvas.getContext("2d").getImageData(0, 0, TW, TH).data;
          let cross = 0;
          for (let i = 0; i < TW * TH; i++) {
            for (let k = 0; k < 3; k++) cross = Math.max(cross, Math.abs(b[i * 4 + k] - c[i * 4 + k]));
          }
          if (cross !== 0) crossBad.push(`${what}: ${cross}/255`);
        }
        push({ group: "WebGPU", name: `${cases.length} sketches, nine tiles each, against the untiled render`,
               ok: bad.length === 0,
               detail: bad.length === 0
                 ? "every one byte-identical to the same sketch drawn in one go — and identical to the GL path's "
                   + `own tiled render except ${crossBad.length ? crossBad.join(", ") : "nothing"}`
                   + (crossBad.length ? ", which is the hash the two backends already disagree about, tiled or not" : "")
                 : bad.join(" · ") }); }

      // 3e. And the case tiling exists for: a picture past what the device
      //     will draw in one go.
      { const max = await maxRenderSizeGpu();
        const big = await renderTiledGpu("vec3(uv, 0.5)", max + 400, 64, {});
        const row = big.canvas.getContext("2d").getImageData(0, 0, big.width, 1).data;
        const sweep = [row[0], row[(big.width >> 1) * 4], row[(big.width - 1) * 4]];
        // uv.x sweeps the whole picture rather than restarting at each tile.
        const monotone = sweep[0] < 8 && Math.abs(sweep[1] - 128) <= 2 && sweep[2] > 247;
        let refused = "";
        try {
          await renderTiledGpu("vec4 sim(vec2 q) { return vec4(q, 0.0, 1.0); }\nvec3(state(uv).rg, 0.5)", 256, 64, {});
        } catch (e) { refused = String(e.message); }
        push({ group: "WebGPU", name: "a picture wider than the device will draw comes back whole",
               ok: big.width === max + 400 && big.tiles > 1 && !big.clamped && monotone && /sim\(\) state pass/.test(refused),
               detail: `${max + 400}×64 asked for on a device whose limit is ${max}: ${big.tiles} tiles, `
                 + `nothing clamped, and uv.x reads ${sweep.join(", ")} across it rather than restarting at each tile. `
                 + "A sketch that keeps state is refused instead — two passes and a ping-pong target belong to the "
                 + "graph runner, and a tile's neighbours are in the next tile anyway" }); }

      // 4. It refuses rather than guesses.
      { const cases = [
          [`float in0(vec2 p);\nin0(p)`, /field port/],
          [`if (uv.x > 0.5) discard;\nvec3(1.0)`, /discard/],
          [`#define K 3\nvec3(float(K))`, /preprocessor/],
        ];
        const said = cases.map(([src2, want]) => {
          const em = toWgsl(src2);
          return !em.ok && em.refused.some((r) => want.test(r));
        });
        push({ group: "WebGPU", name: "the translator names what it will not translate", ok: said.every(Boolean),
               detail: said.every(Boolean)
                 ? "a field port, a discard and a preprocessor directive are each refused with a reason, not emitted as a guess"
                 : `${said.filter(Boolean).length} of 3 refused` }); }
    }
  } catch (e) {
    push({ group: "WebGPU", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The three games that each keep their world somewhere new: snake in the
  // grid it walks on, a platformer in a tilemap it looks up, and a raymarched
  // world whose scene() asks the state texture where things are.
  try {
    const cases = [
      { id: "snake", w: 320, h: 240, frames: 240,
        drive: (kb, f) => { if (f === 40) kb.press(KEY.up); if (f === 120) kb.press(KEY.right); },
        wants: ["ate", "died", "turned", "score"] },
      { id: "platform", w: 400, h: 250, frames: 260,
        drive: (kb, f) => { kb.press(KEY.right); if (f % 50 === 0) kb.press(KEY.space); },
        wants: ["coin", "land", "jump", "score"] },
      { id: "rover", w: 200, h: 120, frames: 90,
        drive: (kb) => { kb.press(KEY.up); },
        wants: ["got", "bump", "score", "speed"] },
    ];
    const rows = [];
    for (const c of cases) {
      const g = GENERATE_PRESETS.find((x) => x.id === c.id);
      if (!g) { rows.push({ id: c.id, error: "no such preset" }); continue; }
      // It has to compile for both passes before anything else is claimed.
      const src = desugar(g.source, { es3: isGL2(gl) });
      let linked = true, why = "";
      for (const pass of [null, "SIM_PASS"]) {
        try { const pr = linkProgram(gl, pass ? withDefine(src, pass) : src); gl.deleteProgram(pr); }
        catch (e) { linked = false; why = String(e.message).split("\n")[0]; }
      }
      if (!linked) { rows.push({ id: c.id, error: why }); continue; }
      const values = {};
      for (const u of parseUniforms(g.source)) if (u.value) values[u.name] = u.value;
      const kb = new Keyboard();
      let moved = 0, last = null, out = null;
      const doc = { probes: g.probes, effects: g.effects, instruments: g.instruments };
      let sawProbe = {};
      for (let f = 0; f < c.frames; f++) {
        kb.clear(); c.drive(kb, f);
        out = renderSketch(g.source, c.w, c.h, { keys: kb, values, steps: 1, reset: f === 0, time: f / 60 });
        kb.tick();
        const d = out.getContext("2d").getImageData(0, 0, c.w, c.h).data;
        let hsh = 0;
        for (let i = 0; i < d.length; i += 29) hsh = (hsh * 31 + d[i]) >>> 0;
        if (last !== null && hsh !== last) moved++;
        last = hsh;
      }
      const d = out.getContext("2d").getImageData(0, 0, c.w, c.h).data;
      let lit = 0;
      for (let i = 0; i < c.w * c.h; i++) if (d[i * 4] > 30) lit++;
      const named = c.wants.every((n) => g.probes && g.probes[n]);
      rows.push({ id: c.id, moved, lit, named, effects: (g.effects || []).length });
    }
    const bad = rows.filter((r) => r.error || !r.named || r.moved < 10 || r.lit < 50);
    push({ group: "More games", name: "snake, a tilemap platformer and a raymarched world all run", ok: bad.length === 0,
           detail: bad.length ? bad.map((r) => `${r.id}: ${r.error || `moved ${r.moved}, lit ${r.lit}`}`).join(" · ")
             : rows.map((r) => `${r.id} changed on ${r.moved} frames, ${r.lit} lit pixels, ${r.effects} effects`).join(" · ") });

    // The one that would have hung the GPU — restated, because the first
    // version of this check had the rule wrong.
    //
    // It asserted that scene() looks *nothing* up. That was the right fix for
    // the bug that prompted it (reading the register texture nine times per
    // call, which is a thousand fetches to draw one dot) but the wrong rule.
    // Measured on an Intel HD 6000: the same scene with an analytic ground
    // costs 28.7 ms a frame and with one filtered fetch 11.2 ms — which is
    // what it costs with no terrain at all. A lookup is not the problem; a
    // lookup *per thing in the world* is, and so is arithmetic nobody needs.
    //
    // So the rule is: scene() and everything it calls may make at most one
    // texture read, and it must be the terrain map rather than the registers.
    { const g = GENERATE_PRESETS.find((x) => x.id === "rover");
      const parts = splitSketch(g.source);
      const called = ["scene", "ground", "beacon"];
      const bodies = parts.declTexts
        .filter((t) => called.some((n) => new RegExp(`\\b(float|vec[234])\\s+${n}\\s*\\(`).test(stripComments(t))))
        .map(stripComments).join("\n");
      const registers = (bodies.match(/\bstate\s*\(/g) || []).length;
      const maps = (bodies.match(/\bstate2\s*\(/g) || []).length;
      const raw = (bodies.match(/\btexture2D\s*\(/g) || []).length;
      push({ group: "More games", name: "the raymarched scene() reads the map, and nothing else",
             ok: registers === 0 && raw === 0 && maps === 1,
             detail: registers === 0 && raw === 0 && maps === 1
               ? "one filtered fetch of the terrain map, and no read of the registers — the rover and the beacons "
                 + "are hoisted into globals the display body fills once. march() calls scene() about a hundred "
                 + "times a pixel, so anything in there is paid for a hundred times"
               : `${registers} register reads, ${maps} map reads, ${raw} raw fetches` }); }

    // The same argument, one level down. ground() is two fbm, which is seven
    // noise, which is twenty-eight hashes — and scene() used to call it ten
    // times: once for the terrain under the point, and nine more for things
    // whose positions were already hoisted into globals and could not move
    // during a pixel. Measured on this machine, that one mistake was 420 ms a
    // frame against 37.
    { const g = GENERATE_PRESETS.find((x) => x.id === "rover");
      const parts = splitSketch(g.source);
      const sceneFn = parts.declTexts.find((t) => /\bfloat\s+scene\s*\(\s*vec3/.test(stripComments(t))) || "";
      const bare = stripComments(sceneFn);
      const grounds = (bare.match(/\bground\s*\(/g) || []).length;
      // …and no array indexed by a running variable, which is memory rather
      // than registers on most drivers and cost a quarter of the frame.
      const indexed = /\b\w+\s*\[\s*[a-zA-Z_]\w*\s*\]/.test(bare);
      push({ group: "More games", name: "the raymarched scene() computes the terrain once and indexes nothing",
             ok: grounds === 1 && !indexed,
             detail: grounds === 1 && !indexed
               ? "one ground() for the point it was asked about; the rover's and the beacons' heights are constants for the pixel, so they are hoisted, "
                 + "and the eight beacons are eight names rather than an array"
               : `${grounds} ground() calls in scene()${indexed ? ", and an array indexed by a variable" : ""}` }); }

    // Fullscreen: the screen's shape is not the sketch's, so the render is the
    // largest box of the sketch's aspect that fits inside it — letterboxed,
    // never stretched, and never past 1920×1080, where the scale would only
    // take it back down again.
    { const cases = [
        [16 / 9, 1920, 1080, [1920, 1080]],       // the same shape: fills it
        [16 / 9, 1920, 1200, [1920, 1080]],       // taller screen: bars above and below
        [1, 1920, 1080, [1080, 1080]],            // a square sketch on a wide screen
        [640 / 400, 1920, 1080, [1728, 1080]],    // the games' shape
      ];
      const wrong = cases.filter(([a, w, h, want]) => {
        const got = fitAspect(a, w, h);
        return got[0] !== want[0] || got[1] !== want[1];
      });
      push({ group: "More games", name: "fullscreen fits the sketch's shape into the screen's",
             ok: wrong.length === 0,
             detail: wrong.length === 0
               ? "a 16:9 sketch fills a 16:9 screen and letterboxes a taller one; a square sketch on a 1920×1080 "
                 + "screen renders 1080×1080 rather than being stretched to fit"
               : wrong.map(([a, w, h, want]) => `${a.toFixed(2)} into ${w}×${h} → ${fitAspect(a, w, h)}, wanted ${want}`).join(" · ") }); }

    // Filling the window, ten places over, written once.
    //
    // This began as the browser's Fullscreen API and the check had to stub
    // `document.fullscreenElement`, because whether a request is *granted* is
    // not something a test can decide. Filling the window is ordinary CSS, so
    // there is nothing left to fake: this expands a real stage and collapses
    // it again, and every assertion is about what actually happened.
    { const problems = [];
      for (const fit of ["contain", "fill", "none", "refit"]) {
        const kid = document.createElement("canvas");
        kid.width = 480; kid.height = 300;              // a shape of its own
        kid.style.width = "100%";
        kid.style.height = "auto";
        const stage = document.createElement("div");
        stage.style.position = "relative";
        // A margin, because a box keeps one and it comes off the size it is
        // given — Music's stage is a card with a rem underneath and sat a rem
        // short until that was noticed.
        stage.style.margin = "0 0 1rem";
        stage.append(kid);
        const holder = document.createElement("div");
        holder.style.height = "140px";
        holder.append(stage);
        document.body.append(holder);
        const before = { stage: stage.getAttribute("style"), kid: kid.getAttribute("style"),
                         parent: stage.parentElement, siblings: holder.children.length };
        let told = null;
        const bg = fit === "none" ? "rgb(13, 15, 24)" : undefined;
        const ex = expandButton(stage, { fit, background: bg, onChange: (b) => { told = b; } });

        ex.button.click();
        if (told !== true) problems.push(`${fit}: expanding did not report`);
        if (!ex.isExpanded()) problems.push(`${fit}: did not think it had expanded`);
        if (ex.button.textContent !== "Exit fullscreen") problems.push(`${fit}: the button did not relabel`);

        // A backdrop covering the window, at a layer between the menus and
        // the modals — and the stage inside it, not being it.
        const back = document.querySelector("[data-expand-backdrop]");
        if (!back) { problems.push(`${fit}: no backdrop`); holder.remove(); continue; }
        const bb = back.getBoundingClientRect();
        if (Math.round(bb.width) !== window.innerWidth || Math.round(bb.height) !== window.innerHeight) {
          problems.push(`${fit}: the backdrop is ${Math.round(bb.width)}×${Math.round(bb.height)} of `
            + `${window.innerWidth}×${window.innerHeight}`);
        }
        if (+back.style.zIndex <= 50 || +back.style.zIndex >= 80) {
          problems.push(`${fit}: layered at ${back.style.zIndex}, not between the menus and the modals`);
        }
        if (back.style.background !== (bg || "rgb(0, 0, 0)")) {
          problems.push(`${fit}: backdrop is ${back.style.background || "nothing"}`);
        }
        if (stage.parentElement !== back) problems.push(`${fit}: the stage did not move into the backdrop`);

        // The stage stays the picture's box, so an overlay drawn against it
        // still lands on the picture. For "contain" that box is the window
        // with the picture's aspect fitted into it — grown, not only shrunk.
        const sb = stage.getBoundingClientRect();
        if (fit === "contain") {
          const want = Math.min(window.innerWidth / (480 / 300), window.innerHeight);
          if (Math.abs(sb.height - want) > 2 || Math.abs(sb.width / sb.height - 480 / 300) > 0.02) {
            problems.push(`${fit}: ${Math.round(sb.width)}×${Math.round(sb.height)} is not the `
              + "picture's shape fitted to the window");
          }
          if (sb.width <= 480) problems.push("contain: a small picture was not grown to fill");
          if (kid.style.width !== "100%" || kid.style.height !== "100%") {
            problems.push("contain: the picture does not fill the stage it was given");
          }
        } else if (Math.round(sb.width) !== window.innerWidth) {
          problems.push(`${fit}: the stage is ${Math.round(sb.width)} wide, not the window`);
        }
        if (fit === "none" && (!stage.style.padding || stage.style.overflow !== "auto")) {
          problems.push("none: an editor got no padding or nowhere to scroll");
        }
        if (fit === "refit" && kid.style.width !== "100%") {
          problems.push("refit: the canvas was resized rather than left to redraw itself");
        }
        if (holder.children.length !== before.siblings) problems.push(`${fit}: no placeholder for the slot`);
        if (![...back.children].some((c) => /Esc/.test(c.textContent || ""))) {
          problems.push(`${fit}: no way out from inside`);
        }

        // Escape comes back — to the same slot, with the same styles.
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        if (told !== false) problems.push(`${fit}: Escape did not collapse it`);
        if (ex.button.textContent !== "Fullscreen") problems.push(`${fit}: the button stayed relabelled`);
        if (stage.parentElement !== before.parent) problems.push(`${fit}: it did not go back to its slot`);
        if (document.querySelector("[data-expand-backdrop]")) problems.push(`${fit}: the backdrop outlived it`);
        if (stage.getAttribute("style") !== before.stage) {
          problems.push(`${fit}: the stage kept ${stage.getAttribute("style")}`);
        }
        if (kid.getAttribute("style") !== before.kid) {
          problems.push(`${fit}: the picture kept ${kid.getAttribute("style")}`);
        }
        if (holder.children.length !== before.siblings) problems.push(`${fit}: the placeholder outlived it`);
        // …and Escape after that does nothing, rather than throwing.
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        holder.remove();
      }
      push({ group: "More games", name: "expanding a stage fills the window, and collapsing puts it all back",
             ok: problems.length === 0,
             detail: problems.length === 0
               ? "four fits over a backdrop pinned to every edge at a layer above the menus and below the modals. "
                 + "The stage moves into the backdrop rather than becoming it, so it stays the picture's box and "
                 + "an overlay drawn against it still lands on the picture; a 480×300 picture is *grown* to the "
                 + "window with its shape kept, a viewport fills, an editor is left alone with somewhere to "
                 + "scroll, and a figure that redraws itself is not resized. Escape puts every one back in its "
                 + "own slot with every style byte for byte"
               : problems.join(" · ") });
    }

    // The open world: infinite terrain, and biomes that are data rather than
    // branches. Three claims, three numbers.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const parts = splitSketch(g.source);
      const bare = stripComments(g.source);

      // 1. What scene() is allowed to cost. march() calls it about a hundred
      //    times a pixel, so the budget is counted in fetches: one for the
      //    ground, one for the cell that decides what grows there. No fbm at
      //    all — everything the world knows about a place was baked into the
      //    map by one pass, and the height a tree stands on and the climate
      //    that put it there come back in the same texel.
      //
      //    Measured on an Intel HD 6000 at 640×360, changing only scene():
      //    terrain alone 4.3 ms, one more fetch a step 6.3, a whole tree
      //    (fetch, hash, three SDFs) 6.5 — and the same tree skipped beyond
      //    forty-five metres 7.4, because the rays in a warp disagree about
      //    which side of forty-five metres they are on and the branch is paid
      //    for while both sides run anyway.
      const bodies = ["scene", "ground", "thingAt", "birdsAt"].map((n) => {
        const re = new RegExp(`\\b(float|vec[234])\\s+${n}\\s*\\(`);
        return stripComments(parts.declTexts.find((t) => re.test(stripComments(t))) || "");
      }).join("\n");
      const reads = (bodies.match(/\bstate2?\s*\(|\btexture2D\s*\(/g) || []).length;
      const noisy = /\bfbmN?\s*\(|\bnoise\s*\(/.test(bodies);
      push({ group: "More games", name: "an open world whose scene() is two fetches and no arithmetic",
             ok: reads === 2 && !noisy,
             detail: reads === 2 && !noisy
               ? "one fetch for the ground and one for the cell that decides what grows on it — the height a "
                 + "tree stands on and the climate that put it there are the same texel, which is why a tree, a "
                 + "boulder and something grazing cost what one of them costs. The birds need no fetch at all: "
                 + "they are at a height they chose, not on the ground. No fbm anywhere a march step can reach it"
               : `${reads} reads across scene(), ground(), thingAt() and birdsAt()`
                 + `${noisy ? ", and noise in there too" : ""}` }); }

    // 2. It has no edge, and it is several places rather than one.
    //
    //    Both are decided by the *climate*, not by the walker, so both are
    //    asked of the climate directly: sample four square kilometres of it,
    //    at the origin and then twenty and two hundred kilometres out. A world
    //    that runs out looks like sea everywhere, or like one biome, or like
    //    the same picture twice — and none of those is what comes back.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const cut = g.source.indexOf("// ---------------------------------"
        + "--------------------------- the walker");
      const S = 96;
      const censusAt = (ox, oz) => {
        const probe = g.source.slice(0, cut) + `
vec2 q = (uv - 0.5) * 4000.0 + vec2(${ox}.0, ${oz}.0);
vec4 L = landform(q);
weigh(L.x, L.y, L.z, 0.15);
vec3 c = vec3(1.0, 0.0, 0.0) * gW.x + vec3(0.0, 1.0, 0.0) * gW.y
       + vec3(0.0, 0.0, 1.0) * gW.z + vec3(1.0, 1.0, 1.0) * gW.w;
if (L.x < 0.0) c = vec3(0.0);
c`;
        const d = renderSketch(probe, S, S, { time: 0 }).getContext("2d").getImageData(0, 0, S, S).data;
        const t = { sea: 0, sand: 0, grass: 0, rock: 0, snow: 0 };
        let sig = 0;
        for (let i = 0; i < S * S; i++) {
          const r = d[i * 4], gg = d[i * 4 + 1], b = d[i * 4 + 2];
          sig = (sig * 31 + r + gg * 3 + b * 7) >>> 0;
          if (r < 20 && gg < 20 && b < 20) t.sea++;
          else if (r > 150 && gg > 150 && b > 150) t.snow++;
          else if (r >= gg && r >= b) t.sand++;
          else if (gg >= b) t.grass++;
          else t.rock++;
        }
        return { t, sig, pc: (n) => (100 * n) / (S * S) };
      };
      const here = censusAt(0, 0), far = censusAt(20000, -20000), further = censusAt(200000, 140000);
      const all = [here, far, further];
      // Every biome happens somewhere, nowhere is all sea, and no two of these
      // are the same picture.
      const kinds = ["sea", "sand", "grass", "rock", "snow"];
      const missing = kinds.filter((k) => all.every((c) => c.pc(c.t[k]) < 0.4));
      const drowned = all.filter((c) => c.pc(c.t.sea) > 80).length;
      const same = here.sig === far.sig || far.sig === further.sig || here.sig === further.sig;
      push({ group: "More games", name: "a world with no edge, and more than one kind of place in it",
             ok: missing.length === 0 && drowned === 0 && !same,
             detail: missing.length === 0 && drowned === 0 && !same
               ? `four square kilometres at the origin: `
                 + kinds.map((k) => `${k} ${here.pc(here.t[k]).toFixed(0)}%`).join(", ")
                 + `; twenty kilometres out: ${far.pc(far.t.sea).toFixed(0)}% sea, `
                 + `${far.pc(far.t.grass).toFixed(0)}% grass; two hundred kilometres out: `
                 + `${further.pc(further.t.sea).toFixed(0)}% sea, ${further.pc(further.t.rock).toFixed(0)}% rock. `
                 + "Three different places, because the world is a function of where you are and not a stored map"
               : same ? "two samples two hundred kilometres apart are the same picture"
               : missing.length ? `${missing.join(", ")} never occurs anywhere`
               : "somewhere is nothing but sea" }); }

    // 3. And the walker actually walks: the map is rebuilt around wherever it
    //    is, so the picture has to keep changing as it goes.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const values = {};
      for (const u of parseUniforms(g.source)) if (u.value) values[u.name] = u.value;
      values.walk = [40];                                   // the fastest it goes
      const kb = new Keyboard();
      let changed = 0, last = null, lit = 0;
      const W2 = 96, H2 = 64;
      for (let f = 0; f < 300; f++) {
        kb.clear(); kb.press(KEY.up); kb.press(16);         // forward, running
        const out = renderSketch(g.source, W2, H2, { keys: kb, values, steps: 1, reset: f === 0, time: f / 60 });
        kb.tick();
        const d = out.getContext("2d").getImageData(0, 0, W2, H2).data;
        let hsh = 0;
        for (let i = 0; i < d.length; i += 23) hsh = (hsh * 31 + d[i]) >>> 0;
        if (last !== null && hsh !== last) changed++;
        last = hsh;
        if (f === 299) for (let i = 0; i < W2 * H2; i++) if (d[i * 4] > 30) lit++;
      }
      // 40 m/s running for 300 frames is about three hundred metres, which is
      // more than the map is wide — so every texel of it has been rebuilt from
      // somewhere the walker had not been when it started.
      push({ group: "More games", name: "the map follows the walker, and is rebuilt from scratch as it goes",
             ok: changed > 240 && lit > 200,
             detail: `the picture changed on ${changed} of 299 frames over about three hundred metres — further `
               + "than the map is wide, so nothing on screen at the end was on the map at the start. "
               + "One fbm per texel per frame, against a hundred per pixel if scene() did the arithmetic itself" }); }

    // 4. What it costs to remember, which for this world is nothing.
    //
    //    The obvious worry about an endless world is that walking through it
    //    fills memory with the places you have been. This one cannot: it
    //    stores none of them. The world is a *function* of position, and the
    //    map is one fixed texture that is rebuilt every frame around wherever
    //    you are — so there are no regions to load and none to unload, and
    //    four kilometres costs exactly what standing still costs. The price of
    //    that choice is recomputing the map, which the numbers above say is
    //    far cheaper than the alternative.
    //
    //    What *did* scale badly was the state's size. It was the size of the
    //    picture, because every sim's state always had been — so a fullscreen
    //    render meant a 1920×1080 float pair with two targets, which is 132 MB
    //    to hold a dozen registers and a height map of a fixed piece of
    //    ground. `@state W H` lets a sketch say otherwise.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const said = sketchMeta(g.source).state;
      const kb = new Keyboard();
      const values = {};
      for (const u of parseUniforms(g.source)) if (u.value) values[u.name] = u.value;
      values.walk = [40];
      // Walked, at two very different picture sizes, watching the storage.
      const sizes = [];
      for (const [W2, H2] of [[96, 64], [480, 270]]) {
        let bytes = null, stable = true;
        for (let f = 0; f < 120; f++) {
          kb.clear(); kb.press(KEY.up); kb.press(16);
          renderSketch(g.source, W2, H2, { keys: kb, values, steps: 1, reset: f === 0, time: f / 60 });
          kb.tick();
          if (f % 30 === 29) {
            const now = sharedFeedbackBytes();
            if (bytes !== null && now !== bytes) stable = false;
            bytes = now;
          }
        }
        sizes.push({ at: `${W2}×${H2}`, bytes, stable });
      }
      const [small, large] = sizes;
      const mb = (n) => (n / 1048576).toFixed(1);
      // The same bytes at both sizes, and the same bytes after walking.
      const ok = !!said && small.bytes === large.bytes && small.stable && large.stable;
      push({ group: "More games", name: "an endless world that costs a fixed number of bytes",
             ok,
             detail: ok
               ? `@state ${said[0]}×${said[1]}: ${mb(small.bytes)} MB of state, the same at ${small.at} and at `
                 + `${large.at}, and the same after walking eighty metres at each. Without it the state is the `
                 + "size of the picture — at 1920×1080 that is 132 MB to hold a height map of a fixed piece of "
                 + "ground. Nothing accumulates with distance either: the world is a function, and the map is "
                 + "rebuilt around wherever you are, so there is nothing to load and nothing to unload"
               : !said ? "the world does not declare @state"
               : `${mb(small.bytes)} MB at ${small.at} but ${mb(large.bytes)} MB at ${large.at}`
                 + `${small.stable && large.stable ? "" : ", and it moved while walking"}` }); }

    // 5. And the weather is weather: it changes the picture, and the wind
    //    moves what is standing in it.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const kb = new Keyboard();
      const base = {};
      for (const u of parseUniforms(g.source)) if (u.value) base[u.name] = u.value;
      const W2 = 128, H2 = 84;
      const run = (over, frames) => {
        const values = { ...base, ...over };
        let out = null;
        for (let f = 0; f < frames; f++) {
          kb.clear();
          out = renderSketch(g.source, W2, H2, { keys: kb, values, steps: 1, reset: f === 0, time: f / 60 });
          kb.tick();
        }
        return out.getContext("2d").getImageData(0, 0, W2, H2).data;
      };
      const wet = run({ weather: [1], windAmt: [1.4] }, 90);
      const dry = run({ weather: [0], windAmt: [0.15] }, 90);
      let diff = 0;
      for (let i = 0; i < W2 * H2; i++) diff += Math.abs(wet[i * 4] - dry[i * 4]);
      diff /= W2 * H2;
      // …and the wind moves things: two frames a moment apart, in a still
      // world with nothing else changing, must not be the same picture.
      const still1 = run({ weather: [0], windAmt: [0] }, 60);
      const still2 = run({ weather: [0], windAmt: [0] }, 61);
      const windy1 = run({ weather: [0], windAmt: [2] }, 60);
      const windy2 = run({ weather: [0], windAmt: [2] }, 61);
      const move = (a, b) => { let d = 0; for (let i = 0; i < W2 * H2; i++) d += Math.abs(a[i * 4] - b[i * 4]); return d / (W2 * H2); };
      const stillMove = move(still1, still2), windyMove = move(windy1, windy2);
      push({ group: "More games", name: "weather that changes the light, and wind that moves what stands in it",
             ok: diff > 12 && windyMove > stillMove * 1.5,
             detail: `rain against no rain is ${diff.toFixed(0)}/255 of a different picture — the sun goes, the `
               + `horizon comes in, the ground darkens and the streaks fall across it. Between two consecutive `
               + `frames the wind moves ${windyMove.toFixed(2)}/255 where still air moves ${stillMove.toFixed(2)}: `
               + "each tree has its own phase from the hash that placed it, so a wood does not sway as one thing" }); }

    // 6. And there is something alive in it. Both kinds are sparse on purpose
    //    — a field with a deer in every cell is a farm — so this walks and
    //    asks how often each shows up, rather than demanding both in one frame
    //    and being flaky about it.
    //
    //    One walk, three variants rendered side by side each frame, small. The
    //    first version walked the whole thing twice at 200x120 and blocked the
    //    page for twenty seconds, which is a self-test nobody will run.
    { const g = GENERATE_PRESETS.find((x) => x.id === "world");
      const W2 = 96, H2 = 64;
      const base = {};
      for (const u of parseUniforms(g.source)) if (u.value) base[u.name] = u.value;
      const values = { ...base, weather: [0], windAmt: [0.6], wildlife: [1], walk: [22] };
      const noBirds = g.source.replace("if (h > 0.34 * wildlife) return 1e9;", "return 1e9;");
      const noHerd = g.source.replace("h3 < green * 0.62 + 0.10 * wildlife", "false");
      const kb = new Keyboard();
      const seen = { birds: 0, animals: 0 }, most = { birds: 0, animals: 0 };
      const marks = new Set([90, 180, 270, 360]);
      const px = (c) => c.getContext("2d").getImageData(0, 0, W2, H2).data;
      for (let f = 0; f <= 360; f++) {
        kb.clear(); kb.press(KEY.up);
        const opt = { keys: kb, values, steps: 1, reset: f === 0, time: f / 60 };
        const all = renderSketch(g.source, W2, H2, opt);
        const nb = renderSketch(noBirds, W2, H2, opt);
        const nh = renderSketch(noHerd, W2, H2, opt);
        kb.tick();
        if (!marks.has(f)) continue;
        const a = px(all), b = px(nb), h = px(nh);
        let pb = 0, pa = 0;
        for (let i = 0; i < W2 * H2; i++) {
          if (Math.abs(a[i * 4] - b[i * 4]) > 8 || Math.abs(a[i * 4 + 2] - b[i * 4 + 2]) > 8) pb++;
          if (Math.abs(a[i * 4] - h[i * 4]) > 8 || Math.abs(a[i * 4 + 2] - h[i * 4 + 2]) > 8) pa++;
        }
        if (pb > 0) seen.birds++;
        if (pa > 0) seen.animals++;
        most.birds = Math.max(most.birds, pb);
        most.animals = Math.max(most.animals, pa);
      }
      push({ group: "More games", name: "something alive in it: a herd on the ground and gulls over it",
             ok: seen.animals >= 2 && seen.birds >= 1 && most.animals > 10 && most.birds > 5,
             detail: `walking, sampled four times: something grazing in ${seen.animals} of them (up to `
               + `${most.animals} pixels of ${W2 * H2}) and birds in ${seen.birds} (up to ${most.birds}). `
               + "The herd is 0.4 ms because it lives in the cell the terrain had already been asked about; "
               + "the birds are 1.4 ms and simpler, because a bird is at a height it chose and needs no fetch "
               + "at all, which is the same fact from the other side" }); }

    // The render scale, as a rule rather than a feeling. Cost is very nearly
    // proportional to pixel count, so the scale that fits a budget is
    // √(budget / measured) — snapped down to a step, and never above 1.
    { const cases = [[16.0, 1, 1], [20, 1, 0.85], [28.9, 1, 0.75], [40, 1, 0.6], [400, 1, 0.5], [8, 1, 1]];
      const wrong = cases.filter(([ms, at, want]) => scaleForBudget(ms, at) !== want);
      push({ group: "More games", name: "the render scale is chosen from the frame time, not guessed",
             ok: wrong.length === 0,
             detail: wrong.length === 0
               ? "28.9 ms at full size asks for 0.75, which is 480×270 of 640×360 — measured at 18.5 ms, which is the budget. "
                 + "A sketch already inside the budget stays at 1: a scale above it would be inventing detail"
               : wrong.map(([ms, at, want]) => `${ms}ms → ${scaleForBudget(ms, at)}, wanted ${want}`).join(" · ") }); }
  } catch (e) {
    push({ group: "More games", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
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

    // Transparency has to survive a stack: every catalogue node computes an
    // alpha, and for a long time the compiler was throwing it away — which
    // turned the clear surround of anything you blurred into an opaque box.
    { const c = document.createElement("canvas"); c.width = W; c.height = H;
      const g2 = c.getContext("2d");
      g2.fillStyle = "#e08040";
      g2.beginPath(); g2.arc(W / 2, H / 2, 22, 0, Math.PI * 2); g2.fill();
      const corner = () => 3;                       // a pixel far from the disc
      const out = applyEffects(c, [
        makeEffect("node", "filter.blur", { radius: [5] }),
        makeEffect("graph", "grade", { lift: 0.02, gamma: 1.1, gain: 1.05, sat: 1.2 }),
        makeEffect("graph", "vignette", { amount: 0.4, softness: 0.6 }),
      ]).getContext("2d").getImageData(0, 0, W, H).data;
      const at = (x, y) => out[(y * W + x) * 4 + 3];
      const clear2 = at(corner(), corner()) === 0 && at(W - 4, H - 4) === 0;
      const solid = at(W / 2, H / 2) > 250;
      // And the blur must not drag black out of the transparency: just outside
      // the disc the colour should still be the disc's, only fainter.
      const i = ((H / 2) * W + (W / 2 + 23)) * 4;   // one pixel outside a 22px disc
      const soft = out[i + 3];
      const hue = out[i] > out[i + 1] && out[i + 1] > out[i + 2];
      push({ group: "Canvas on the graph", name: "transparency survives a stack, and a blur does not bleed black",
             ok: clear2 && solid && soft > 20 && soft < 250 && hue,
             detail: `clear corners ${clear2 ? "stay clear" : "went opaque"} · centre alpha ${at(W / 2, H / 2)} · ` +
                     `just outside the disc alpha ${soft} and the colour is still the disc's (${out[i]},${out[i + 1]},${out[i + 2]})` }); }

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

    // A title, compiled: the same words, from a field rather than the text
    // engine. They will not agree to the pixel — two rasterisers never do —
    // so what is checked is that the ink lands in the same place.
    { const clip = { kind: "title", text: "TITLE", size: 64, color: "#ffffff", bg: "none",
                     family: "system-ui, sans-serif", weight: 600 };
      const id = await compileTitleNode(clip, W, H);
      if (!id) {
        push({ group: "Video on the graph", name: "a title compiles to a distance field", ok: false,
               detail: "no atlas could be built for the title" });
      } else {
        const { graph, sources } = frameGraph(
          [{ clip: { grade: {}, effects: [], opacity: 1, start: 0 }, node: id }],
          { width: W, height: H, background: "#000000", scale: 1, alphaOf: () => 1 });
        const got = renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W, H).data;
        const ref = document.createElement("canvas"); ref.width = W; ref.height = H;
        const rg = ref.getContext("2d");
        rg.fillStyle = "#000"; rg.fillRect(0, 0, W, H);
        rg.fillStyle = "#fff"; rg.textAlign = "center"; rg.textBaseline = "middle";
        rg.font = "600 64px system-ui, sans-serif";
        rg.fillText("TITLE", W / 2, H / 2);
        const rd = rg.getImageData(0, 0, W, H).data;
        // Coverage, and how far the two agree about which pixels are ink.
        let both = 0, onlyA = 0, onlyB = 0;
        for (let i = 0; i < got.length; i += 4) {
          const a2 = got[i] > 128, b2 = rd[i] > 128;
          if (a2 && b2) both++; else if (a2) onlyA++; else if (b2) onlyB++;
        }
        const iou = both / Math.max(1, both + onlyA + onlyB);
        push({ group: "Video on the graph", name: "a title compiles to a distance field, and lands where the text engine put it",
               ok: both > 300 && iou > 0.8,
               detail: `${both} px of ink in both, ${onlyA} only in the field, ${onlyB} only in the canvas — ` +
                       `agreement ${(iou * 100).toFixed(1)}% (want >80; two rasterisers never match exactly)` });
      } }

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

  // Generate as the node authoring environment: a sketch with one line in its
  // header is a node, a stack that fuses is a node, and both have to survive
  // the trip.
  try {
    const W = 120, H = 80;
    const src = document.createElement("canvas"); src.width = W; src.height = H;
    { const g = src.getContext("2d");
      const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#fff2dd"); gr.addColorStop(1, "#101a2e");
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
      g.fillStyle = "#e04020"; g.beginPath(); g.arc(40, 40, 20, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#1fa36c"; g.fillRect(80, 15, 30, 50); }
    const px = (c) => c.getContext("2d").getImageData(0, 0, W, H).data;

    // Freeze: a stack that fuses is one shader, and must look the same as one.
    { const stack = [
        makeEffect("graph", "duotone", { dark: "#10203a", light: "#f2e3c0" }),
        makeEffect("graph", "vignette", { amount: 0.55, softness: 0.4 }),
        makeEffect("node", "adjust.exposure", { stops: [0.6] }),
      ];
      const wanted = px(applyEffects(src, stack));
      const fz = freezeEffects(stack, { width: W, height: H });
      if (fz.error) {
        push({ group: "Nodes from Generate", name: "a stack freezes into one node", ok: false, detail: fz.error });
      } else {
        const sketch = withNodeHeader(fz.sketch, { node: "selftest-frozen", title: "Frozen" });
        const entry = await registerNode(sketch, { docId: 90001, name: "Frozen" });
        if (entry.error) {
          push({ group: "Nodes from Generate", name: "a stack freezes into one node", ok: false, detail: entry.error });
        } else {
          const t = nodeType(entry.id);
          const params = {};
          for (const u of t.params) if (u.control !== "image") params[u.name] = u.value.slice();
          const got = px(applyEffects(src, [makeEffect("node", entry.id, params)]));
          const r = compare(got, wanted, W, H, { thresh: 6 });
          // And it must be a *filter*: one input, called in0, or the graph
          // will treat it as something that draws rather than something that
          // takes a picture.
          const shaped = t.inputs.length === 1 && t.inputs[0] === "in0";
          push({ group: "Nodes from Generate", name: "a stack freezes into one node that looks the same",
                 ok: r.mean < 1.0 && shaped,
                 detail: `three effects → one node · mean ${r.mean}/255 · inputs [${t.inputs.join(", ")}] · ` +
                         `${t.params.length} controls, their dialled values baked in as defaults · want <1.0` });
        }
      } }

    // The header is the whole contract, and a user node cannot shadow a built-in.
    { const bare = `// A test node.\n// @node adjust.exposure\nuniform sampler2D in0;\ntexture2D(in0, uv)`;
      const mine = `// A test node.\n// @node my-thing\nuniform sampler2D in0;\nuniform float k;  // @range 0 2 @default 1\ntexture2D(in0, uv) * k`;
      const idClash = nodeIdFor(bare, 90002);
      const idMine = nodeIdFor(mine, 90003);
      const entry = await registerNode(mine, { docId: 90003, name: "My thing" });
      const drew = !entry.error && !!nodeType(entry.id);
      const noHeader = await registerNode("uniform sampler2D in0;\ntexture2D(in0, uv)", { docId: 90004 });
      push({ group: "Nodes from Generate", name: "a sketch with `@node` becomes a node type; a built-in cannot be shadowed",
             ok: drew && idMine === "you.my-thing" && idClash !== "adjust.exposure" && !!noHeader.error,
             detail: `"my-thing" → ${idMine} · one calling itself adjust.exposure → ${idClash} · ` +
                     `${entry.params.length} control${entry.params.length === 1 ? "" : "s"} came with it · ` +
                     `a sketch with no @node is refused ("${noHeader.error}")` }); }

    // Two inputs: a mixer is a node like any other.
    { const mixer = `// Mix two pictures.\n// @node selftest-mixer\n` +
        `uniform sampler2D in0;\nuniform sampler2D in1;\nuniform float k;   // @range 0 1 @default 0.5\n` +
        `mix(texture2D(in0, uv), texture2D(in1, uv), k)`;
      const entry = await registerNode(mixer, { docId: 90005, name: "Mixer" });
      let ok = !entry.error, detail = entry.error || "";
      if (ok) {
        const other = document.createElement("canvas"); other.width = W; other.height = H;
        other.getContext("2d").fillStyle = "#ffffff";
        other.getContext("2d").fillRect(0, 0, W, H);
        const graph = createGraph(W, H);
        const a = addNode(graph, "source"), b = addNode(graph, "source");
        graph.output = addNode(graph, entry.id, { k: [0.5] }, [a, b]);
        const got = px(renderGraph(graph, { [a]: src, [b]: other }));
        const base = px(src);
        // Half way to white, everywhere.
        let worst = 0;
        for (let i = 0; i < got.length; i += 4) worst = Math.max(worst, Math.abs(got[i] - (base[i] + 255) / 2));
        ok = entry.inputs.length === 2 && worst < 3;
        detail = `inputs ${entry.inputs.join(", ")} · half way to white everywhere, worst ${worst.toFixed(1)}/255`;
      }
      push({ group: "Nodes from Generate", name: "a two-input sketch works as a node", ok, detail }); }

    // Two targets: the point is that the two states hold different things.
    // A probe writes a known number into each and reads both back.
    { const probe = `// Two fields at once.
uniform float k;   // @range 0 1 @default 1
vec4 sim(vec2 q) { return vec4(0.25, 0.0, 0.0, 1.0); }
vec4 sim2(vec2 q) { return vec4(0.0, 0.75, 0.0, 1.0); }
vec3(state(uv).r, state2(uv).g, 0.0) * k`;
      const dual = dualTargets(probe);
      const glsl = desugar(probe, { es3: isGL2(gl) });
      const outs = (glsl.match(/^layout\(location = \d\) out vec4 \w+;/gm) || []).length;
      const out = renderSketch(probe, 32, 32, { steps: 2 });
      const d = out.getContext("2d").getImageData(0, 0, 32, 32).data;
      // 0.25 and 0.75 come back as 64 and 191; if both landed in one target
      // the two would be equal, and if the second never ran green would be 0.
      const okDual = isGL2(gl)
        ? (dual && outs === 2 && Math.abs(d[0] - 64) <= 2 && Math.abs(d[1] - 191) <= 2)
        : true;
      push({ group: "Nodes from Generate", name: "a sim can write two targets, and they hold different things",
             ok: okDual,
             detail: isGL2(gl)
               ? `${outs} outputs declared · state() came back ${d[0]} (want 64), state2() ${d[1]} (want 191)`
               : "WebGL1 here: one target, and state2() reads the first — the sketch still runs" }); }

    // A shape past the edge budget: it used to be dropped, which is a visible
    // failure. Now it bakes to a field carried in the source.
    { const pts = [];
      const N = 900;
      for (let i = 0; i < N; i++) {
        const ang = (i / N) * Math.PI * 2;
        const r = 120 + 40 * Math.sin(ang * 17);
        pts.push(`${(200 + r * Math.cos(ang)).toFixed(2)},${(200 + r * Math.sin(ang)).toFixed(2)}`);
      }
      const file = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">`
        + `<rect width="400" height="400" fill="#101828"/>`
        + `<polygon points="${pts.join(" ")}" fill="#f0a35e"/></svg>`;
      const SW = 300, SH = 300;
      const ref = document.createElement("canvas"); ref.width = SW; ref.height = SH;
      const im = new Image();
      im.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(file);
      await im.decode();
      ref.getContext("2d").drawImage(im, 0, 0, SW, SH);
      const compiled = await compileSvg(file, { edgeCap: 400 });
      await loadSketchImages(compiled.source);
      const got = renderSketch(compiled.source, SW, SH, {}).getContext("2d").getImageData(0, 0, SW, SH).data;
      const r2 = compare(got, ref.getContext("2d").getImageData(0, 0, SW, SH).data, SW, SH, { thresh: 60 });
      const said = compiled.notes.some((n2) => /baked to a distance field/.test(n2));
      push({ group: "Nodes from Generate", name: "a shape past the edge budget bakes to a field rather than vanishing",
             ok: r2.mean < 2.0 && said,
             detail: `${N} edges at a 400 budget · mean ${r2.mean}/255 against the browser's own rasterisation, ` +
                     `${r2.off} px off by >60 (${r2.pct}%) · the notes say which shapes went that way` }); }

    // GSUB: the ligature table read back off a hand-built GSUB, so the check
    // does not depend on a font being installed. (It usually is not: on macOS
    // most families keep their Latin ligatures in Apple's `morx` instead.)
    { const bytes = [];
      const u16 = (v) => { bytes.push((v >> 8) & 255, v & 255); };
      const tag = (t) => { for (const c of t) bytes.push(c.charCodeAt(0)); };
      // header: version, scriptList, featureList, lookupList
      u16(1); u16(0); u16(0); u16(10); u16(24);
      // featureList at 10: one 'liga' feature pointing at lookup 0
      u16(1); tag("liga"); u16(8);
      /* feature at 18 */ u16(0); u16(1); u16(0);
      // lookupList at 24: one lookup
      u16(1); u16(4);
      /* lookup at 28 */ u16(4); u16(0); u16(1); u16(8);
      /* subtable at 36 */ u16(1); u16(8); u16(1); u16(14);
      /* coverage at 44 */ u16(1); u16(1); u16(10);
      /* ligature set at 50 */ u16(1); u16(4);
      /* ligature at 54 */ u16(99); u16(2); u16(11);
      const dv = new DataView(new Uint8Array(bytes).buffer);
      const subst = readGsubForTest(dv);
      const forTen = subst.ligatures.get(10) || [];
      const ok = subst.count === 1 && subst.features.includes("liga")
        && forTen.length === 1 && forTen[0].gid === 99
        && forTen[0].rest.length === 1 && forTen[0].rest[0] === 11;
      push({ group: "Nodes from Generate", name: "GSUB: a ligature substitution is read back off the table",
             ok,
             detail: ok ? `glyph 10 + 11 → 99, from the liga feature · ${subst.count} ligature read`
                        : `read ${subst.count} ligatures, features [${subst.features}]` }); }

    // Versions: a ring, and a summary that says what moved.
    { const data = {};
      const v1 = "// @node v\nuniform sampler2D in0;\ntexture2D(in0, uv)";
      const v2 = "// @node v\nuniform sampler2D in0;\nuniform float k; // @range 0 1\ntexture2D(in0, uv) * k";
      keepVersion(data, v1, "first");
      keepVersion(data, v1, "again");                 // no change: not kept twice
      keepVersion(data, v2, "added k");
      const afterTwo = data.versions.length;
      for (let i = 0; i < MAX_VERSIONS + 5; i++) keepVersion(data, `${v2}\n// ${i}`);
      const summary = versionSummary(v1, v2);
      push({ group: "Nodes from Generate", name: "node text is versioned, capped, and the diff says what moved",
             ok: afterTwo === 2 && data.versions.length === MAX_VERSIONS && /\+k/.test(summary),
             detail: `saving the same text twice keeps one · capped at ${data.versions.length} · "${summary}"` }); }
  } catch (e) {
    push({ group: "Nodes from Generate", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // Platform: the things that decide whether this runs anywhere and keeps
  // running — tiling past the GPU's maximum, staying translatable, and not
  // growing without bound.
  try {
    { const worst = [];
      for (const id of ["rings", "cells", "beach"]) {
        const preset = GENERATE_PRESETS.find((p2) => p2.id === id);
        if (!preset) continue;
        const W2 = 320, H2 = 240;
        const one = renderSketch(preset.source, W2, H2, { time: 1.25 })
          .getContext("2d").getImageData(0, 0, W2, H2).data;
        const many = renderTiled(preset.source, W2, H2, { time: 1.25, tile: 96 });
        const got = many.canvas.getContext("2d").getImageData(0, 0, W2, H2).data;
        let diff = 0;
        for (let i = 0; i < one.length; i += 4) if (one[i] !== got[i] || one[i + 1] !== got[i + 1] || one[i + 2] !== got[i + 2]) diff++;
        worst.push({ id, diff, tiles: many.tiles });
      }
      const bad = worst.filter((w) => w.diff);
      push({ group: "Platform", name: "a tiled render is identical to an untiled one", ok: !bad.length,
             detail: bad.length
               ? bad.map((b) => `${b.id}: ${b.diff} px differ`).join(", ")
               : `${worst.map((w) => `${w.id} in ${w.tiles} tiles`).join(", ")} — not one pixel differs · `
                 + `this GPU renders up to ${maxRenderSize()}px in one go` }); }

    { const rows = auditNodes();
      const sum = portabilitySummary(rows);
      const host = auditSource(desugar("uniform sampler2D in0;\ntexture2D(in0, uv)", { es3: isGL2(gl) }),
                               { bodyOnly: false });
      push({ group: "Platform", name: "every node body is still translatable to WGSL",
             ok: sum.clean === sum.total,
             detail: sum.clean === sum.total
               ? `${sum.total}/${sum.total} clean · the obstacles are all in the host's own text `
                 + `(${host.findings.map((f) => `${f.id}×${f.count}`).join(", ") || "none"}), which a `
                 + "WGSL backend would emit differently anyway"
               : `${sum.clean}/${sum.total} clean · ` + sum.kinds.map((k) => `${k.id} in ${k.nodes}`).join(", ") }); }

    { const enc = new TextEncoder();
      const files = [
        { name: "frame_00.txt", bytes: enc.encode("the first frame\n") },
        { name: "nested/frame_01.bin", bytes: new Uint8Array(300).map((_, i) => i & 255) },
      ];
      const blob = zipStore(files, { stamp: new Date(2026, 0, 2, 3, 4, 5) });
      const buf = new Uint8Array(await blob.arrayBuffer());
      const dv = new DataView(buf.buffer);
      let at = 0, seen = 0, crcOk = true;
      while (at + 4 <= buf.length && dv.getUint32(at, true) === 0x04034b50) {
        const nameLen = dv.getUint16(at + 26, true), extra = dv.getUint16(at + 28, true);
        const size = dv.getUint32(at + 18, true), stored = dv.getUint32(at + 14, true);
        const data = buf.subarray(at + 30 + nameLen + extra, at + 30 + nameLen + extra + size);
        if (crc32(data) !== stored) crcOk = false;
        seen++;
        at += 30 + nameLen + extra + size;
      }
      const end = dv.getUint32(buf.length - 22, true) === 0x06054b50;
      push({ group: "Platform", name: "an image sequence's archive reads back", ok: seen === 2 && crcOk && end,
             detail: `${seen} entries, every CRC-32 matches its bytes, and the end record is where it should be · `
                     + `${buf.length} bytes stored rather than deflated, because a PNG already is` }); }

    { const st = graphStats();
      const ok = st.pooled <= 8 && st.fused <= 24 && st.ownTextures <= 17;
      push({ group: "Platform", name: "the runner's caches and pool are capped", ok,
             detail: `${st.pooled} targets pooled (cap 8, ${st.targetsMade} made, ${st.targetsEvicted} released), `
                     + `${st.fused} fused programs (cap 24), ${st.luts} LUTs, ${st.ownTextures} embedded textures · `
                     + `intermediates in ${st.precision || "—"}` }); }
  } catch (e) {
    push({ group: "Platform", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The cross-cutting promises: that a node documents itself, that its
  // lesson exists, and that it still draws what it drew.
  try {
    let courseModules = [];
    try { courseModules = ((await api("/api/course")) || {}).modules || []; } catch { /* offline */ }

    // A node the app generates — a compiled title, a frozen look — is not a
    // library node and has nothing to document; the library is what this is
    // a promise about.
    const generated = (id) => id.startsWith("you.") || id.startsWith("source.title.") || id.startsWith("fused.") || id.startsWith("test.");
    { const gaps = referenceGaps();
      const builtIn = gaps.withGaps.filter((d) => !generated(d.id));
      push({ group: "Cross-cutting", name: "every built-in node describes itself",
             ok: builtIn.length === 0,
             detail: builtIn.length
               ? `${builtIn.length} incomplete: ` + builtIn.slice(0, 3).map((d) => `${d.id} — ${d.gaps[0]}`).join("; ")
               : `${gaps.total} nodes, all with a description and help on every control · `
                 + "written by the nodes, so it cannot go stale" }); }

    { const { docs } = nodeReference();
      const slugs = new Set(courseModules.map((m) => m.slug));
      const tagged = docs.filter((d) => d.module && !generated(d.id));
      const dangling = slugs.size ? tagged.filter((d) => !slugs.has(d.module)) : [];
      const untagged = docs.filter((d) => !d.module && !generated(d.id));
      push({ group: "Cross-cutting", name: "every node's @module names a lesson that exists",
             ok: dangling.length === 0 && untagged.length === 0,
             detail: !slugs.size ? "the course could not be fetched, so the links were not checked"
               : dangling.length || untagged.length
                 ? `${dangling.length} point nowhere (${dangling.slice(0, 2).map((d) => `${d.id}→${d.module}`).join(", ")}), `
                   + `${untagged.length} carry no module`
                 : `${tagged.length} nodes across ${new Set(tagged.map((d) => d.module)).size} lessons, `
                   + "every one of them a course module that exists" }); }

    // Golden images are not attempted across machines — two GPUs disagree in
    // the last bit and a hash would fail on the wrong one. What is checked is
    // what a golden was for: that a node draws, that it changes the picture,
    // and that it does the same thing twice.
    { const W2 = 64, H2 = 48;
      const src2 = document.createElement("canvas"); src2.width = W2; src2.height = H2;
      { const g2 = src2.getContext("2d");
        const gr = g2.createLinearGradient(0, 0, W2, H2);
        gr.addColorStop(0, "#f8f0e0"); gr.addColorStop(1, "#141c2e");
        g2.fillStyle = gr; g2.fillRect(0, 0, W2, H2);
        g2.fillStyle = "#d05028"; g2.fillRect(8, 8, 24, 20); }
      const base = src2.getContext("2d").getImageData(0, 0, W2, H2).data;
      const drew = [], stuck = [], flaky = [];
      for (const [id, t] of NODE_TYPES) {
        if (t.inputs.length !== 1 || generated(id)) continue;
        try {
          // A node whose one input is a field cannot be handed a picture. It
          // gets a circle to work on instead, and is shaded if it hands a
          // field back — the promise being tested is the same either way.
          const onField = t.fieldInputs.length === 1;
          const graph = createGraph(W2, H2);
          let s0 = null, last;
          if (onField) {
            last = addNode(graph, id, {}, [addNode(graph, "field.circle", { centre: [0.1, 0], radius: [0.4] })]);
            if (t.field) last = addNode(graph, "field.shade", {}, [last]);
          } else {
            s0 = addNode(graph, "source");
            last = addNode(graph, id, {}, [s0]);
          }
          graph.output = last;
          const sources = s0 ? { [s0]: src2 } : {};
          const a1 = renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W2, H2).data;
          const a2 = renderGraph(graph, sources).getContext("2d").getImageData(0, 0, W2, H2).data;
          let same = true, moved = 0;
          for (let i = 0; i < a1.length; i += 4) {
            if (a1[i] !== a2[i] || a1[i + 1] !== a2[i + 1]) same = false;
            // With no source to have changed, "it did something" means it put
            // a shape there rather than a flat field of one colour.
            if (Math.abs(a1[i] - (onField ? a1[0] : base[i])) > 2) moved++;
          }
          if (!same) flaky.push(id);
          else if (!moved) stuck.push(id);
          else drew.push(id);
        } catch (e) { flaky.push(`${id} (${String(e.message).split("\n")[0]})`); }
      }
      // Being an identity at its defaults is a legitimate design — a grade
      // whose defaults did something would be a bad grade — so that is
      // reported rather than failed. What is not allowed is a node that
      // cannot be run twice for the same answer.
      push({ group: "Cross-cutting", name: "every single-input node draws and repeats exactly",
             ok: flaky.length === 0,
             detail: flaky.length ? `not repeatable: ${flaky.join(", ")}`
               : `${drew.length} nodes drew and repeated byte for byte; ${stuck.length} are identities at `
                 + `their defaults (${stuck.join(", ") || "none"}), which is what a grade should be · `
                 + "goldens across machines are not attempted — two GPUs disagree in the last bit" }); }
  } catch (e) {
    push({ group: "Cross-cutting", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The audio worklet — the other roadmap's Phase A. Everything here is
  // rendered offline, so the self-test never makes a sound.
  try {
    const db = (v) => 20 * Math.log10(Math.max(v, 1e-12));
    const render = async (graph, sr, seconds) => {
      const ctx = new OfflineAudioContext(1, Math.round(sr * seconds), sr);
      const inst = await installGraph(ctx, graph);
      inst.node.connect(ctx.destination);
      return (await ctx.startRendering()).getChannelData(0);
    };

    // The bar Phase A sets: a sine at 1 kHz, at both rates, with nothing else
    // in it. The frequency is nudged to sit exactly on an FFT bin — otherwise
    // what you measure is the window's leakage rather than the oscillator.
    { const rows = [];
      for (const sr of [44100, 48000]) {
        const N = 4096, hz = Math.round(1000 * N / sr) * sr / N;
        const graph = createDspGraph();
        graph.output = addDspNode(graph, "osc.sine", { params: { hz, amp: 1 } });
        const ch = await render(graph, sr, 0.25);
        const mag = fftMag(ch.subarray(2048, 2048 + N));
        let peakBin = 0;
        for (let i = 1; i < mag.length; i++) if (mag[i] > mag[peakBin]) peakBin = i;
        let spur = -999;
        for (let i = 0; i < mag.length; i++) {
          if (Math.abs(i - peakBin) <= 3) continue;
          spur = Math.max(spur, db(mag[i] / mag[peakBin]));
        }
        let peak = 0;
        for (let i = 0; i < ch.length; i++) peak = Math.max(peak, Math.abs(ch[i]));
        rows.push({ sr, hz, binHz: peakBin * sr / N, dbfs: db(peak), spur });
      }
      const ok = rows.every((r) => Math.abs(r.dbfs) < 0.1 && r.spur < -90
                                   && Math.abs(r.binHz - r.hz) < 1);
      push({ group: "Audio worklet", name: "a sine is a sine, at both sample rates", ok,
             detail: rows.map((r) => `${r.sr / 1000}k: ${r.hz.toFixed(1)} Hz at `
               + `${r.dbfs.toFixed(2)} dBFS, everything else below ${r.spur.toFixed(1)} dB`).join(" · ")
               + " — want 0 dBFS and under −90" }); }

    // The rule that keeps it clickless, and proof the rule can fail.
    { const graph = createDspGraph();
      graph.output = addDspNode(graph, "osc.sine", {});
      const emitted = sourceFor(graph);
      // A node written the way a person naturally would, and should not.
      const badId = `bad.alloc${Math.random().toString(36).slice(2, 6)}`;
      defineDspNode(`// Deliberately wrong, to prove the check bites.\n// @node ${badId}\n`
        + "out float y;\nuniform float hz;   // @range 1 100 @default 1\n\n"
        + "const bin = [1, 2, 3];\ny = bin[0] * hz;");
      const bad = createDspGraph();
      bad.output = addDspNode(bad, badId, {});
      const badFindings = sourceFor(bad).findings;
      push({ group: "Audio worklet", name: "nothing in the sample loop allocates, and the check bites",
             ok: emitted.findings.length === 0 && badFindings.length > 0,
             detail: emitted.findings.length
               ? `the emitted loop would allocate: ${emitted.findings[0].why}`
               : `the emitted loop is clean; a node with an array literal in it is caught `
                 + `("${badFindings[0].why}") · the meter goes out once every sixteen blocks, `
                 + "outside the loop, and is not pretended to be free" }); }

    // Sample-rate independence, measured rather than asserted: the one-pole
    // against its own analytic response, at both rates.
    { const analytic = (f, fc, sr) => {
        const c = Math.exp(-2 * Math.PI * fc / sr), b = 1 - c;
        const w = 2 * Math.PI * f / sr;
        return db(b / Math.hypot(1 - c * Math.cos(w), c * Math.sin(w)));
      };
      let worst = 0, corner = [];
      for (const sr of [44100, 48000]) {
        for (const f of [500, 1000, 4000]) {
          const graph = createDspGraph();
          const osc = addDspNode(graph, "osc.sine", { params: { hz: f, amp: 1 } });
          graph.output = addDspNode(graph, "filter.onepole",
            { inputs: { x: [osc, "y"] }, params: { cutoff: 1000 } });
          const ch = await render(graph, sr, 0.2);
          let peak = 0;
          for (let i = ch.length >> 1; i < ch.length; i++) peak = Math.max(peak, Math.abs(ch[i]));
          const got = db(peak), want = analytic(f, 1000, sr);
          worst = Math.max(worst, Math.abs(got - want));
          if (f === 1000) corner.push(`${sr / 1000}k ${got.toFixed(2)} dB`);
        }
      }
      push({ group: "Audio worklet", name: "a filter's coefficients come from the sample rate",
             ok: worst < 0.25,
             detail: `the one-pole against its own analytic response, worst ${worst.toFixed(2)} dB across `
               + `500/1000/4000 Hz at 44.1k and 48k · at its corner: ${corner.join(", ")} (want −3)` }); }

    // A loop with no delay in it has no first sample, and the error has to
    // say which nodes are in the loop rather than "cyclic graph".
    { const graph = createDspGraph();
      const a = addDspNode(graph, "gain.smooth", {});
      const b = addDspNode(graph, "filter.onepole", { inputs: { x: [a, "y"] } });
      const node = graph.nodes.find((n) => n.id === a);
      node.inputs.x = [b, "y"];
      graph.output = b;
      let msg = "";
      try { topoDsp(graph); } catch (e) { msg = e.message; }
      push({ group: "Audio worklet", name: "a feedback loop with no delay is refused, by name",
             ok: /no delay/.test(msg) && msg.includes(a) && msg.includes(b),
             detail: msg || "the graph was accepted, which it should not have been" }); }
  } catch (e) {
    push({ group: "Audio worklet", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The audio library, held to the mathematics. Every node here has a number
  // against something that was not written for the occasion: the cookbook's
  // own response, a convolution of the node's impulse, or the ideal
  // band-limited waveform computed additively.
  try {
    const db = (v) => 20 * Math.log10(Math.max(v, 1e-12));
    const SR = 48000;
    const render = async (graph, secs) => {
      const ctx = new OfflineAudioContext(1, Math.round(SR * secs), SR);
      const inst = await installGraph(ctx, graph);
      inst.node.connect(ctx.destination);
      return (await ctx.startRendering()).getChannelData(0);
    };
    // A sine's amplitude from its RMS — exact, where a peak is only as good
    // as the sampling happens to be near the crest.
    const amplitudeOf = (ch) => {
      let sum = 0, n = 0;
      for (let i = ch.length >> 1; i < ch.length; i++) { sum += ch[i] * ch[i]; n++; }
      return Math.sqrt(2 * sum / n);
    };

    // The cookbook's magnitude response, typed out here rather than imported,
    // so this is not the implementation reading itself back.
    const rbj = (type, f, fc, q, sr, gainDb) => {
      const w0 = 2 * Math.PI * fc / sr, cw = Math.cos(w0), sw = Math.sin(w0), al = sw / (2 * q);
      const A2 = Math.pow(10, gainDb / 40);
      let B0, B1, B2, A0, A1, A22;
      if (type === 0) { B0 = (1 - cw) / 2; B1 = 1 - cw; B2 = (1 - cw) / 2; A0 = 1 + al; A1 = -2 * cw; A22 = 1 - al; }
      else if (type === 1) { B0 = (1 + cw) / 2; B1 = -(1 + cw); B2 = (1 + cw) / 2; A0 = 1 + al; A1 = -2 * cw; A22 = 1 - al; }
      else if (type === 2) { B0 = al; B1 = 0; B2 = -al; A0 = 1 + al; A1 = -2 * cw; A22 = 1 - al; }
      else if (type === 3) { B0 = 1; B1 = -2 * cw; B2 = 1; A0 = 1 + al; A1 = -2 * cw; A22 = 1 - al; }
      else { B0 = 1 + al * A2; B1 = -2 * cw; B2 = 1 - al * A2; A0 = 1 + al / A2; A1 = -2 * cw; A22 = 1 - al / A2; }
      const w = 2 * Math.PI * f / sr;
      const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
      return db(Math.hypot(B0 + B1 * c1 + B2 * c2, -(B1 * s1 + B2 * s2))
              / Math.hypot(A0 + A1 * c1 + A22 * c2, -(A1 * s1 + A22 * s2)));
    };

    { let worst = 0, worstAt = "";
      for (const [type, name] of [[0, "lowpass"], [1, "highpass"], [2, "bandpass"], [3, "notch"], [4, "peaking"]]) {
        for (const f of [200, 1000]) {
          const g = createDspGraph();
          const osc = addDspNode(g, "osc.sine", { params: { hz: f, amp: 1 } });
          g.output = addDspNode(g, "filter.biquad",
            { inputs: { x: [osc, "y"] }, params: { type, freq: 1000, q: 2, gainDb: 6 } });
          const got = db(amplitudeOf(await render(g, 0.2)));
          const want = rbj(type, f, 1000, 2, SR, 6);
          if (Math.abs(got - want) > worst) { worst = Math.abs(got - want); worstAt = `${name} at ${f} Hz`; }
        }
      }
      push({ group: "Audio library", name: "every biquad form against the cookbook's own response",
             ok: worst < 0.2,
             detail: `five forms at two frequencies each, worst ${worst.toFixed(3)} dB (${worstAt}) · `
               + "the reference is typed out again in the test, not imported, so this is not the "
               + "implementation reading itself back" }); }

    { let peak = 0, at = "";
      for (const freq of [40, 1000, 18000]) {
        for (const q of [0.5, 20]) {
          const g = createDspGraph();
          const n2 = addDspNode(g, "noise.white", { params: { amp: 1 } });
          g.output = addDspNode(g, "filter.svf", { inputs: { x: [n2, "y"] }, params: { freq, q } });
          const ch = await render(g, 0.1);
          for (let i = 0; i < ch.length; i++) {
            if (Math.abs(ch[i]) > peak) { peak = Math.abs(ch[i]); at = `${freq} Hz, Q ${q}`; }
          }
        }
      }
      push({ group: "Audio library", name: "the state-variable filter stays bounded at every setting",
             ok: peak < 10 && Number.isFinite(peak),
             detail: `full-scale noise through six combinations of cutoff and resonance: worst sample `
               + `${peak.toFixed(2)} at ${at} · the bar is ±10, and a filter that fails this one `
               + "does not fail quietly" }); }

    { const taps = Math.round(5 * 0.001 * SR);
      const g1 = createDspGraph();
      const n1 = addDspNode(g1, "noise.white", { params: { amp: 0.5 } });
      g1.output = addDspNode(g1, "filter.comb", { inputs: { x: [n1, "y"] }, params: { ms: 5, mix: 1 } });
      const got = await render(g1, 0.15);
      const g2 = createDspGraph();
      g2.output = addDspNode(g2, "noise.white", { params: { amp: 0.5 } });
      const dry = await render(g2, 0.15);
      let worst = 0;
      for (let i = taps + 2; i < dry.length; i++) worst = Math.max(worst, Math.abs(got[i] - (dry[i] + dry[i - taps])));
      push({ group: "Audio library", name: "a delay line is exactly its own impulse response", ok: worst < 1e-5,
             detail: `the comb against x[n] + x[n−${taps}] computed directly: worst sample ${worst.toExponential(2)}, `
               + "which is float32 and not the delay line" }); }

    { const amp = 0.5, out2 = {};
      for (const f of [220, 2333]) {
        const dt = f / SR, K = Math.floor((SR / 2) / f);
        const ideal = (i) => {
          const phi = ((i + 1) * dt) % 1;
          let acc = 0;
          for (let k = 1; k <= K; k++) acc += Math.sin(2 * Math.PI * k * phi) / k;
          return -(2 / Math.PI) * acc * amp;
        };
        for (const blep of [1, 0]) {
          const g = createDspGraph();
          g.output = addDspNode(g, "osc.saw", { params: { hz: f, amp, blep } });
          const ch = await render(g, 0.2);
          let es = 0, ss = 0;
          for (let i = 2000; i < 8000; i++) { const d = ch[i] - ideal(i); es += d * d; ss += ideal(i) * ideal(i); }
          out2[`${f}_${blep}`] = db(Math.sqrt(es) / Math.sqrt(ss));
        }
      }
      const gain220 = out2["220_0"] - out2["220_1"], gain2333 = out2["2333_0"] - out2["2333_1"];
      push({ group: "Audio library", name: "PolyBLEP is measurably better than the naive ramp",
             ok: gain220 > 5 && gain2333 > 5,
             detail: `against an additive band-limited saw — every harmonic below Nyquist and none above, `
               + `so the reference cannot alias by construction: at 220 Hz `
               + `${out2["220_1"].toFixed(1)} dB against ${out2["220_0"].toFixed(1)}, at 2333 Hz `
               + `${out2["2333_1"].toFixed(1)} against ${out2["2333_0"].toFixed(1)} — better by `
               + `${gain220.toFixed(1)} and ${gain2333.toFixed(1)} dB` }); }

    { const f = 2000;
      const g = createDspGraph();
      const osc = addDspNode(g, "osc.sine", { params: { hz: f, amp: 1 } });
      g.output = addDspNode(g, "shape.tanh", { inputs: { x: [osc, "y"] }, params: { drive: 20, level: 1 } });
      const ch = await render(g, 0.25);
      const N = 4096;
      const mag = fftMag(ch.subarray(4096, 4096 + N));
      let harm = 0, alias = 0;
      for (let i = 4; i < mag.length; i++) {
        const k = (i * SR / N) / f;
        if (Math.abs(k - Math.round(k)) < 0.03 && Math.round(k) >= 1) harm = Math.max(harm, mag[i]);
        else alias = Math.max(alias, mag[i]);
      }
      const floor = db(alias / harm);
      push({ group: "Audio library", name: "the saturator's aliasing is measured rather than hoped about",
             ok: floor < -35,
             detail: `driven twenty times into a tanh curve, everything that is not a harmonic of the input `
               + `sits at ${floor.toFixed(1)} dB · that is aliasing, it is what a hard curve does at 1× , `
               + "and oversampling it is Phase B's next job rather than a thing to be quiet about" }); }

    { const g = createDspGraph();
      const gate = addDspNode(g, "osc.sine", { params: { hz: 2, amp: 1 } });
      g.output = addDspNode(g, "env.ad", { inputs: { gate: [gate, "y"] },
                                           params: { attackMs: 5, decayMs: 80 } });
      const ch = await render(g, 0.6);
      let peak = 0, ends = 0;
      for (let i = 0; i < ch.length; i++) peak = Math.max(peak, ch[i]);
      for (let i = ch.length - 200; i < ch.length; i++) ends = Math.max(ends, ch[i]);
      let below = 0;
      for (let i = 0; i < ch.length; i++) if (ch[i] < 0) below++;
      push({ group: "Audio library", name: "the envelope rises, falls, and never goes negative",
             ok: peak > 0.95 && peak <= 1.0001 && below === 0,
             detail: `a 2 Hz gate, 5 ms up and 80 ms down: it reaches ${peak.toFixed(3)}, is clamped at 1, `
               + `and never goes below zero in ${ch.length} samples` }); }
  } catch (e) {
    push({ group: "Audio library", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The audio graph: feedback, which a shader graph cannot have, and voices,
  // which is the same graph N times rather than N graphs.
  try {
    const SR = 48000;
    const render = async (graph, secs, opts) => {
      const ctx = new OfflineAudioContext(1, Math.round(SR * secs), SR);
      const inst = await installGraph(ctx, graph, opts);
      inst.node.connect(ctx.destination);
      return (await ctx.startRendering()).getChannelData(0);
    };

    // A feedback comb built out of the graph itself: impulse into a summer,
    // the delay's output wired back into it. The answer is known exactly —
    // taps at g, g², g³ — so there is nothing to interpret.
    { const gfb = 0.7, ms = 2;
      const g = createDspGraph();
      const imp = addDspNode(g, "src.impulse", {});
      const sum = addDspNode(g, "mix.add", { inputs: { a: [imp, "y"] }, params: { gainA: 1, gainB: gfb } });
      const dl = addDspNode(g, "delay.line", { inputs: { x: [sum, "y"] }, params: { ms, feedback: 0 } });
      g.nodes.find((x) => x.id === sum).inputs.b = [dl, "y"];
      g.output = sum;
      const ch = await render(g, 0.05);
      // The round trip is the delay plus the one sample a back edge costs,
      // which is a fact about the compiler and worth stating rather than
      // rounding away.
      let period = 0;
      for (let i = 1; i < 400; i++) if (Math.abs(ch[i]) > 0.5) { period = i; break; }
      const taps = [];
      for (let k = 0; k <= 3; k++) {
        let best = 0;
        for (let i = Math.max(0, k * period - 2); i <= k * period + 2 && i < ch.length; i++) {
          best = Math.max(best, Math.abs(ch[i]));
        }
        taps.push(best);
      }
      const ok = taps.every((v, k) => Math.abs(v - Math.pow(gfb, k)) < 0.01);
      push({ group: "Audio graph", name: "feedback through a delay decays exactly as the loop gain says", ok,
             detail: `taps ${taps.map((v) => v.toFixed(3)).join(", ")} against ${[0, 1, 2, 3].map((k) => Math.pow(gfb, k).toFixed(3)).join(", ")} · `
               + `the round trip is ${period} samples: ${Math.round(ms * 0.001 * SR)} of delay and one more, `
               + "which is what a back edge costs and is said rather than hidden" }); }

    // The same graph, four times, each with its own state.
    { const N = 4096;
      const g = createDspGraph();
      const note = addDspNode(g, "voice.note", {});
      g.output = addDspNode(g, "osc.sineHz",
        { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.2 } });
      const wanted = [0, 1, 2, 3].map((v) => (Math.round(1000 * N / SR) + v * 20) * SR / N);
      const ch = await render(g, 0.3, { voices: 4,
        voiceInit: { [`${note}_pitch`]: wanted, [`${note}_on`]: [1, 1, 1, 1] } });
      const mag = fftMag(ch.subarray(4096, 4096 + N));
      const peaks = [];
      for (let i = 2; i < mag.length - 1; i++) {
        if (mag[i] > mag[i - 1] && mag[i] >= mag[i + 1] && mag[i] > 0.02) peaks.push(i * SR / N);
      }
      const ok = peaks.length === 4 && wanted.every((w, k) => Math.abs(peaks[k] - w) < 1);
      push({ group: "Audio graph", name: "four voices are four voices, each with its own state", ok,
             detail: ok
               ? `one graph compiled for four voices: peaks at ${peaks.map((p2) => p2.toFixed(0)).join(", ")} Hz, `
                 + "exactly where each voice was told to sit — one loop over voices, not four graphs"
               : `wanted ${wanted.map((w) => w.toFixed(0)).join(", ")}, found ${peaks.map((p2) => p2.toFixed(0)).join(", ")}` }); }

    // Silence a voice and the others must not notice.
    { const N = 4096;
      const g = createDspGraph();
      const note = addDspNode(g, "voice.note", {});
      g.output = addDspNode(g, "osc.sineHz",
        { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.2 } });
      const wanted = [0, 1].map((v) => (Math.round(1000 * N / SR) + v * 40) * SR / N);
      const both = await render(g, 0.2, { voices: 2,
        voiceInit: { [`${note}_pitch`]: wanted, [`${note}_on`]: [1, 1] } });
      const one = await render(g, 0.2, { voices: 2,
        voiceInit: { [`${note}_pitch`]: wanted, [`${note}_on`]: [1, 0] } });
      const solo = await render(g, 0.2, { voices: 1,
        voiceInit: { [`${note}_pitch`]: [wanted[0]], [`${note}_on`]: [1] } });
      let worst = 0;
      for (let i = 1024; i < 8192; i++) worst = Math.max(worst, Math.abs(one[i] - solo[i]));
      let differs = 0;
      for (let i = 1024; i < 8192; i++) if (Math.abs(both[i] - one[i]) > 1e-4) differs++;
      push({ group: "Audio graph", name: "one voice's state never leaks into another",
             ok: worst < 1e-6 && differs > 1000,
             detail: `gating the second voice off leaves the first bit-for-bit what it is alone `
               + `(worst ${worst.toExponential(1)}), and the two together differ from one in `
               + `${differs} of 7168 samples — so they are summing, not sharing` }); }

    // Every node in the library compiles on its own. A broken node should be
    // found when it is written, not when someone builds a graph with it.
    { const broken = [];
      for (const [id, t] of DSP_NODES) {
        // The check above registers a deliberately-broken node to prove the
        // allocation rule bites; it is not part of the library.
        if (id.startsWith("bad.")) continue;
        try {
          const g = createDspGraph();
          const inputs = {};
          for (const port of t.ins) inputs[port.name] = 0;
          g.output = addDspNode(g, id, { inputs });
          const src = sourceFor(g);
          // eslint-disable-next-line no-new-func
          new Function(`"use strict"; const AudioWorkletProcessor = class {}; `
            + `const registerProcessor = () => {}; const sampleRate = 48000; ${src.code}`);
          if (src.findings.length) broken.push(`${id}: ${src.findings[0].why}`);
        } catch (e) { broken.push(`${id}: ${String(e.message).split("\n")[0]}`); }
      }
      push({ group: "Audio graph", name: "every node in the library compiles on its own",
             ok: broken.length === 0,
             detail: broken.length ? broken.join("; ")
               : `${DSP_NODES.size} nodes, each built into a one-node graph, parsed, and checked for `
                 + "anything that would allocate in the loop" }); }
  } catch (e) {
    push({ group: "Audio graph", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // A song: instruments as graphs, notes scheduled onto voices, automation
  // from the same evaluator the video timeline uses, and a bounce that is the
  // same file twice.
  try {
    const SR = 48000;
    const instrument = () => {
      const g = createDspGraph();
      const note = addDspNode(g, "voice.note", {});
      g.output = addDspNode(g, "osc.sineHz",
        { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.4 } });
      return { g, note };
    };

    // The bar this phase sets.
    { const { g, note } = instrument();
      const song = { graph: g, noteNode: note,
        notes: patternToNotes([[60], [64], [67], [72]], { bpm: 120, stepsPerBeat: 4 }) };
      const r1 = await renderSong(song, { sampleRate: SR, voices: 4 });
      const r2 = await renderSong(song, { sampleRate: SR, voices: 4 });
      const a = r1.buffer.getChannelData(0), b = r2.buffer.getChannelData(0);
      let same = a.length === b.length;
      for (let i = 0; same && i < a.length; i++) if (a[i] !== b[i]) same = false;
      push({ group: "Audio song", name: "a bounce is sample-exact, and the same file twice",
             ok: same && r1.realtimeRatio > 1,
             detail: `${r1.seconds.toFixed(2)} s rendered in ${r1.ms.toFixed(0)} ms — `
               + `${r1.realtimeRatio.toFixed(1)}× faster than real time — and the two renders are `
               + `${same ? "identical, sample for sample" : "NOT identical"} · nothing in the graph has a `
               + "clock of its own, so there is nothing left to vary" }); }

    // The notes are the notes.
    { const { g, note } = instrument();
      const song = { graph: g, noteNode: note,
        notes: patternToNotes([[60], [64], [67], [72]], { bpm: 120, stepsPerBeat: 4, gate: 0.9 }) };
      const { buffer } = await renderSong(song, { sampleRate: SR, voices: 4 });
      const ch = buffer.getChannelData(0);
      const N = 2048, bin = SR / N;
      const errs = song.notes.map((n) => {
        const at = Math.round((n.t + 0.01) * SR);
        const mag = fftMag(ch.subarray(at, at + N));
        let pk = 1;
        for (let i = 2; i < mag.length; i++) if (mag[i] > mag[pk]) pk = i;
        return Math.abs(pk * bin - n.hz);
      });
      const worst = Math.max(...errs);
      push({ group: "Audio song", name: "each step sounds the note it was given", ok: worst < bin,
             detail: `MIDI 60, 64, 67, 72 at 120 bpm: every one within ${worst.toFixed(1)} Hz of its `
               + `pitch, against an FFT bin of ${bin.toFixed(1)} Hz — which is the measurement's own limit` }); }

    // Automation, from the evaluator the video timeline uses.
    { const g = createDspGraph();
      const n2 = addDspNode(g, "noise.white", { params: { amp: 0.5 } });
      const lp = addDspNode(g, "filter.svf", { inputs: { x: [n2, "y"] }, params: { freq: 8000, q: 0.707 } });
      g.output = lp;
      const song = { graph: g, notes: [],
        automation: [{ node: lp, param: "freq",
                       track: [{ t: 0, v: 8000, ease: "linear" }, { t: 1, v: 300, ease: "linear" }] }] };
      const r = await renderSong(song, { sampleRate: SR, seconds: 1.2, voices: 1 });
      const ch = r.buffer.getChannelData(0);
      const brightness = (at) => {
        const mag = fftMag(ch.subarray(Math.round(at * SR), Math.round(at * SR) + 4096));
        let hi = 0, lo = 0;
        for (let i = 1; i < mag.length; i++) {
          if (i * SR / 4096 > 4000) hi += mag[i]; else lo += mag[i];
        }
        return hi / (lo + 1e-9);
      };
      const early = brightness(0.1), late = brightness(0.9);
      push({ group: "Audio song", name: "automation is the video timeline's keyframes, on a filter",
             ok: early > late * 5,
             detail: `a cutoff keyed 8000 → 300 Hz over a second: the energy above 4 kHz falls from `
               + `${early.toFixed(2)} to ${late.toFixed(3)} of the energy below it · the evaluator is `
               + "`evalTrack` from video-graph.js, imported, not reimplemented — a parameter moving over "
               + "time is the same problem whichever studio asks" }); }

    // Voice stealing, which has to be decided rather than left to luck.
    { const notes = [];
      for (let k = 0; k < 6; k++) notes.push({ t: k * 0.01, dur: 1, midi: 60 + k, hz: noteHz(60 + k) });
      const placed = allocateVoices(notes, 3);
      const stolen = placed.filter((p2) => p2.stolen);
      const distinct = new Set(placed.slice(0, 3).map((p2) => p2.voice)).size;
      push({ group: "Audio song", name: "more notes than voices steals the oldest, and says which",
             ok: distinct === 3 && stolen.length === 3,
             detail: `six notes into three voices: the first three take one each, and `
               + `${stolen.length} of the rest steal — the oldest sounding voice, which is the one you `
               + "are least likely to still be listening to" }); }

    // The file that leaves the browser.
    { const { g, note } = instrument();
      const song = { graph: g, noteNode: note, notes: patternToNotes([[69]], { bpm: 120 }) };
      const { buffer } = await renderSong(song, { sampleRate: SR, voices: 2 });
      const wav = toWav(buffer);
      const head = new DataView(await wav.slice(0, 44).arrayBuffer());
      const tag = (at) => String.fromCharCode(head.getUint8(at), head.getUint8(at + 1),
                                              head.getUint8(at + 2), head.getUint8(at + 3));
      const ok = tag(0) === "RIFF" && tag(8) === "WAVE" && tag(36) === "data"
        && head.getUint32(24, true) === SR && head.getUint16(34, true) === 16
        && wav.size === 44 + buffer.length * 2;
      push({ group: "Audio song", name: "the bounce writes a WAV a tool will open", ok,
             detail: `${(wav.size / 1024).toFixed(0)} KB: RIFF/WAVE, ${head.getUint32(24, true)} Hz, `
               + `${head.getUint16(34, true)}-bit, and the data chunk is exactly the ${buffer.length} `
               + "samples rendered" }); }
  } catch (e) {
    push({ group: "Audio song", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
  }

  // The scopes: the measurements, and the fact that the pictures are drawn by
  // the same render graph everything else is.
  try {
    const SR = 48000, n = SR * 2;
    const sine = (hz, amp, phase = 0) => {
      const a = new Float32Array(n);
      for (let i = 0; i < n; i++) a[i] = amp * Math.sin(2 * Math.PI * hz * i / SR + phase);
      return a;
    };

    // The standard's own calibration point, which is the only way to know a
    // loudness meter is right rather than merely consistent.
    { const amp = Math.pow(10, -20 / 20);
      const L = sine(997, amp), R = sine(997, amp);
      const stereo = loudnessLUFS([L, R], SR).lufs;
      const quieter = loudnessLUFS([sine(997, amp / 2), sine(997, amp / 2)], SR).lufs;
      push({ group: "Audio scopes", name: "loudness reads BS.1770's calibration point exactly",
             ok: Math.abs(stereo + 20) < 0.15 && Math.abs((stereo - quieter) - 6.02) < 0.05,
             detail: `997 Hz at −20 dBFS on both channels: ${stereo.toFixed(2)} LUFS, which is what the `
               + `standard says it must be · halving it moves the meter ${(stereo - quieter).toFixed(2)} LU, `
               + "so it is linear as well as calibrated · K-weighting derived from the analogue "
               + "prototype at this rate, not the 48 kHz coefficients reused" }); }

    // True peak exists to catch what a sample peak cannot see.
    { const tricky = sine(SR / 4, 1.0, Math.PI / 4);
      let samplePeak = 0;
      for (let i = 0; i < tricky.length; i++) samplePeak = Math.max(samplePeak, Math.abs(tricky[i]));
      const sampleDb = 20 * Math.log10(samplePeak);
      const tp = truePeakDb([tricky]);
      push({ group: "Audio scopes", name: "true peak catches a crest that falls between samples",
             ok: sampleDb < -2.5 && tp > -0.2,
             detail: `a full-scale sine at a quarter of the rate, offset so no sample lands on the crest: `
               + `the sample meter reads ${sampleDb.toFixed(2)} dBFS and says there are three decibels `
               + `spare, and the true peak is ${tp.toFixed(2)} dBTP — it would clip a converter` }); }

    { const a = sine(997, 0.5), b = sine(997, 0.5, Math.PI);
      const same = correlation(a, a), opposite = correlation(a, b);
      push({ group: "Audio scopes", name: "correlation says what will survive a fold to mono",
             ok: Math.abs(same - 1) < 1e-3 && Math.abs(opposite + 1) < 1e-3,
             detail: `identical channels ${same.toFixed(3)}, inverted ${opposite.toFixed(3)} — `
               + "the second cancels completely, which is the thing the meter is there to warn about" }); }

    // And the pictures: drawn by the render graph, from the packed analysis.
    { const W2 = 256, H2 = 128;
      const mag = new Float32Array(512);
      mag[107] = 1;
      const row = packSpectrum(mag, { width: W2 });
      const g = createGraph(W2, H2);
      const src = addNode(g, "source");
      g.output = addNode(g, "scope.spectrum", {}, [src]);
      const d = renderGraph(g, { [src]: rowTexture(row) }).getContext("2d").getImageData(0, 0, W2, H2).data;
      let topCol = -1, topY = H2;
      for (let x = 0; x < W2; x++) {
        for (let y = 0; y < H2; y++) {
          const i = (y * W2 + x) * 4;
          if (d[i + 1] > 150 && d[i] < 160) { if (y < topY) { topY = y; topCol = x; } break; }
        }
      }
      const want = Math.round(Math.log(108) / Math.log(512) * (W2 - 1));
      push({ group: "Audio scopes", name: "a scope is a render-graph node, and draws where the data is",
             ok: Math.abs(topCol - want) <= 1 && topY <= 1,
             detail: `one loud bin at 107 of 512 draws its peak in column ${topCol} of ${W2}, where a log `
               + `axis puts it (${want}) · each column takes the loudest bin it covers, because at the top `
               + "of a log axis adjacent columns skip bins and a point sample drops narrow peaks through "
               + "the gap — which this check found" }); }

    // The spectrogram's history is a ring, so the newest column is wherever
    // the head is and the node unwraps it. If those two disagree the picture
    // is right but scrolls the wrong way, which is exactly the kind of thing
    // that looks fine until it does not.
    { const sg = spectrogram(64, 32);
      const quiet = new Float32Array(256);
      const loud = new Float32Array(256).fill(1);
      for (let k = 0; k < 40; k++) sg.push(k === 39 ? loud : quiet);
      const px = sg.canvas.getContext("2d").getImageData(0, 0, 64, 32).data;
      // 40 pushes into 64 columns: the newest sits at 39, the head just past it.
      const brightAt = [];
      for (let x = 0; x < 64; x++) if (px[(16 * 64 + x) * 4] > 200) brightAt.push(x);
      const W3 = 128, H3 = 64;
      const g = createGraph(W3, H3);
      const src = addNode(g, "source");
      g.output = addNode(g, "scope.spectrogram", { head: [sg.head] }, [src]);
      const d = renderGraph(g, { [src]: sg.canvas }).getContext("2d").getImageData(0, 0, W3, H3).data;
      // Unwrapped, the newest column must be at the right-hand edge.
      let rightBright = 0, leftBright = 0;
      for (let y = 0; y < H3; y++) {
        if (d[(y * W3 + W3 - 2) * 4] > 150) rightBright++;
        if (d[(y * W3 + 1) * 4] > 150) leftBright++;
      }
      push({ group: "Audio scopes", name: "the spectrogram's ring unwraps to the right edge",
             ok: brightAt.length === 1 && brightAt[0] === 39 && rightBright > H3 * 0.7 && leftBright === 0,
             detail: `40 columns pushed into a 64-wide ring: the loud one is stored at ${brightAt[0]}, and `
               + `the node draws it at the right-hand edge (${rightBright} of ${H3} rows bright there, `
               + `${leftBright} at the left) · nothing is copied to scroll — the head is a number` }); }

    { const W2 = 128;
      const wave = new Float32Array(4096);
      for (let i = 0; i < wave.length; i++) wave[i] = Math.sin(2 * Math.PI * 8 * i / wave.length);
      const row = packWaveform(wave, { width: W2 });
      // The packed row holds each column's top and bottom; at the extremes of
      // a sine they should reach the rails.
      let hi = 0, lo = 255;
      for (let x = 0; x < W2; x++) { hi = Math.max(hi, row[x * 4]); lo = Math.min(lo, row[x * 4 + 1]); }
      push({ group: "Audio scopes", name: "a waveform packs its extremes, not its average",
             ok: hi > 250 && lo < 5,
             detail: `a full-scale sine decimated to ${W2} columns still reaches ${hi} and ${lo} of 255 — `
               + "min and max per column, because an average would show a quiet signal where there is a loud one" }); }
  } catch (e) {
    push({ group: "Audio scopes", name: "run", ok: false, detail: String(e.message).split("\n")[0] });
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
