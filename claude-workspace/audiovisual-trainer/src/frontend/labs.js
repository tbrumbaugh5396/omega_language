// Module 3: the effects lab. A live-coding environment over the Part 3 maths
// spine, with four runtimes (glsl, canvas2d, audio graph, sample-level dsp).
//
// The loop this is built for is the one from Part 13: describe the goal
// perceptually, get an implementation, run it, say what is wrong
// perceptually, then ask why the fix worked. The judgement stays with you;
// this is where you run it.

import { el, clear, api, toast, modal, closeModal, knob } from "./ui.js";
import { expandButton } from "./expand.js";
import { LAB_SOURCE } from "./labs-content.js";
import * as A from "./engine-audio.js";
import * as I from "./engine-image.js";

const OUT_W = 480, OUT_H = 300;

export async function labView(ctx) {
  const root = el("div");
  const saves = (await api("/api/labs/saves")).saves;

  root.append(el("div.card", {},
    el("h2", {}, "Effects lab"),
    el("p.dim", {}, "Guided builds of the maths spine. Each one is a working " +
      "thing you can break — the goals are what to aim at once it runs. " +
      "Ask an LLM for the implementation if you want; the part that cannot be " +
      "delegated is deciding whether the result is right.")));

  const groups = [
    ["glsl", "Shader"], ["canvas2d", "Canvas"], ["audio", "Audio graph"],
    ["dsp", "Sample-level DSP"],
  ];
  for (const [runtime, label] of groups) {
    const labs = ctx.state.curriculum.labs.filter(
      (l) => LAB_SOURCE[l.id]?.runtime === runtime);
    if (!labs.length) continue;
    root.append(el("div.card", {},
      el("h2", {}, label),
      el("div.drill-list", {}, ...labs.map((lab) =>
        el("button.drill-card", { onclick: () => openLab(ctx, lab, root, saves) },
          el("b", {}, lab.title),
          el("p", {}, lab.teaches),
          el("div.row.tight", { style: { marginTop: ".4rem" } },
            saves.filter((s) => s.lab === lab.id).length
              ? el("span.tag.good", {}, `${saves.filter((s) => s.lab === lab.id).length} saved`)
              : null,
            el("span.tag", {}, ctx.state.lessonTitles[lab.lesson] || lab.lesson)))))));
  }
  return root;
}

function openLab(ctx, lab, container, saves) {
  const def = LAB_SOURCE[lab.id];
  if (!def) { toast("No source for that lab yet"); return; }

  let source = def.source;
  const knobs = (def.knobs || []).map(([name, min, max, value]) => ({ name, min, max, value }));
  let stop = null;

  const out = el("canvas", { width: OUT_W, height: OUT_H });
  // The lab's picture, filling the window. The editor and the goals stay
  // behind it: what you want larger is the thing the code is making.
  const stage = el("div", { style: { position: "relative", display: "flex",
                                     alignItems: "center", justifyContent: "center" } }, out);
  // …and it renders at the larger size rather than being blown up. Every
  // runtime here reads `canvas.width` on the frame it draws — the GLSL one
  // sets its viewport and u_res from it, the canvas2d one is handed it — so
  // resizing the backing store is enough and nothing has to be re-run.
  //
  // 480×300 is an internal constant rather than something anybody chose, which
  // is why overriding it is fair game. A studio's preview size *is* a choice,
  // and those still scale up.
  const ex = expandButton(stage, {
    onChange: (big) => {
      const box = stage.getBoundingClientRect();
      const w = big ? Math.max(OUT_W, Math.min(1920, Math.round(box.width))) : OUT_W;
      const h = big ? Math.round((w * OUT_H) / OUT_W) : OUT_H;
      if (out.width !== w || out.height !== h) { out.width = w; out.height = h; }
    },
  });
  const log = el("div.lab-log");
  const editor = el("textarea.editor", { spellcheck: false, value: source });
  const scope = el("canvas", { width: OUT_W, height: 110, style: { width: "100%", display: "block" } });

  const knobRow = el("div.knobs", {}, ...knobs.map((kb, i) =>
    kb.name ? knob(kb.name, {
      min: kb.min, max: kb.max, step: (kb.max - kb.min) / 200, value: kb.value,
      format: (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)),
      oninput: (v) => { knobs[i].value = v; if (def.runtime !== "dsp") run(); },
    }) : el("span")));

  const goalList = el("ul.bullets", {}, ...lab.goals.map((g) => el("li", {}, g)));

  const card = el("div.card", {},
    el("div.spread", {},
      el("div", {},
        el("h2", { style: { marginBottom: ".1rem" } }, lab.title),
        el("span.fine", {}, def.runtime, " · ", lab.teaches)),
      el("div.row.tight", {},
        el("button", { onclick: () => run() }, "Run"),
        def.runtime === "dsp" && el("button.primary", { onclick: () => run(true) }, "Render & play"),
        el("button.ghost", { onclick: () => saveDialog() }, "Save"),
        el("button.ghost", { onclick: () => { editor.value = def.source; run(); } }, "Reset"),
        ex.button,
        el("button.ghost", { onclick: () => { teardown(); ctx.go("lab"); } }, "Close"))),
    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, stage, log),
        knobRow,
        (def.runtime === "audio" || def.runtime === "dsp")
          ? el("div.lab-out", {}, scope) : null,
        el("div", {}, el("h4", {}, "Aim at"), goalList),
        savedList()),
      el("div.stack", {}, editor,
        el("p.fine", {}, def.runtime === "glsl"
          ? "Uniforms: u_res, u_time, u_mouse, u_k (the four knobs)."
          : def.runtime === "canvas2d"
          ? "Scope: ctx, w, h, t (seconds), k (knob array), I (image engine)."
          : def.runtime === "audio"
          ? "Scope: ctx, src (looping source), k, A (audio engine). Return the last node."
          : "Scope: input (Float32Array), sr, k, A. Return a Float32Array."))));

  clear(container);
  container.append(card);
  out.style.width = "100%";
  out.style.height = "auto";

  function savedList() {
    const mine = saves.filter((s) => s.lab === lab.id);
    if (!mine.length) return el("span");
    return el("div", {}, el("h4", {}, "Saved"),
      el("div.chips", {}, ...mine.map((s) =>
        el("button.chip", {
          onclick: () => {
            editor.value = s.source || def.source;
            (s.params.knobs || []).forEach((v, i) => {
              if (knobs[i]) knobs[i].value = v;
            });
            knobRow.querySelectorAll("input").forEach((inp, i) => {
              if (knobs[i]) { inp.value = knobs[i].value; inp.dispatchEvent(new Event("input")); }
            });
            run();
          },
        }, s.name))));
  }

  function saveDialog() {
    const name = el("input", { placeholder: "what this one is", value: "" });
    const note = el("textarea", { placeholder: "why it is worth coming back to" });
    modal(el("h2", {}, "Save this state"), name, note,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", {
          onclick: async () => {
            try {
              await api("/api/labs/saves", {
                method: "POST",
                body: {
                  lab: lab.id, name: name.value.trim() || "untitled",
                  params: { knobs: knobs.map((k) => k.value) },
                  source: editor.value, note: note.value,
                },
              });
              closeModal();
              toast("Saved");
              ctx.go("lab");
            } catch (e) { toast(e.message); }
          },
        }, "Save")));
  }

  function teardown() {
    stop?.();
    stop = null;
    A.stopAll();
  }

  function run(playIt = false) {
    teardown();
    clear(log);
    const k = knobs.map((kb) => kb.value);
    try {
      if (def.runtime === "glsl") stop = runGlsl(out, editor.value, k, log);
      else if (def.runtime === "canvas2d") stop = runCanvas(out, editor.value, k, log);
      else if (def.runtime === "audio") stop = runAudio(out, scope, editor.value, k, def, log);
      else stop = runDsp(out, scope, editor.value, k, def, log, playIt);
    } catch (e) {
      log.textContent = String(e.message || e);
    }
  }
  run();
}

// ------------------------------------------------------------------ glsl

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

function runGlsl(canvas, src, k, log) {
  const gl = canvas.getContext("webgl", { antialias: false, preserveDrawingBuffer: true });
  if (!gl) { log.textContent = "WebGL is not available in this browser."; return null; }

  const compile = (type, code) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, code);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(s) || "shader compile failed");
    }
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, src));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(prog) || "link failed");
  }
  gl.useProgram(prog);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "a_pos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  const uRes = gl.getUniformLocation(prog, "u_res");
  const uTime = gl.getUniformLocation(prog, "u_time");
  const uMouse = gl.getUniformLocation(prog, "u_mouse");
  const uK = gl.getUniformLocation(prog, "u_k");
  const mouse = [0.5, 0.5];
  canvas.onmousemove = (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = (e.clientX - r.left) / r.width;
    mouse[1] = 1 - (e.clientY - r.top) / r.height;
  };

  const t0 = performance.now();
  let raf;
  const frame = () => {
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, (performance.now() - t0) / 1000);
    gl.uniform2f(uMouse, mouse[0], mouse[1]);
    gl.uniform4f(uK, k[0] ?? 0, k[1] ?? 0, k[2] ?? 0, k[3] ?? 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = requestAnimationFrame(frame);
  };
  frame();
  return () => { cancelAnimationFrame(raf); canvas.onmousemove = null; };
}

// ------------------------------------------------------------------ canvas

function runCanvas(canvas, src, k, log) {
  const fn = new Function("ctx", "w", "h", "t", "k", "I", src);
  const g = canvas.getContext("2d", { willReadFrequently: true });
  const t0 = performance.now();
  let raf, failed = false;
  const frame = () => {
    if (!failed) {
      try {
        fn(g, canvas.width, canvas.height, (performance.now() - t0) / 1000, k, I);
      } catch (e) {
        failed = true;
        log.textContent = String(e.message || e);
      }
    }
    raf = requestAnimationFrame(frame);
  };
  frame();
  return () => cancelAnimationFrame(raf);
}

// ------------------------------------------------------------------ audio

function labSource(kind, seconds = 4) {
  switch (kind) {
    case "drums": return A.synth.drumLoop(seconds, { seed: 12 });
    case "voice": return A.synth.voice(seconds, { seed: 12 });
    case "pluck": return A.synth.pluck(seconds, 220, { seed: 12 });
    default: return A.synth.pad(seconds, { seed: 12 });
  }
}

function runAudio(canvas, scope, src, k, def, log) {
  const fn = new Function("ctx", "src", "k", "A", src);
  const ctx = A.audioCtx();
  const node = A.liveSource(labSource(def.sourceKind));
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 2048;

  let last;
  try {
    last = fn(ctx, node, k, A) || node;
  } catch (e) {
    log.textContent = String(e.message || e);
    return null;
  }
  const gain = ctx.createGain();
  gain.gain.value = 0.7;
  last.connect(gain);
  gain.connect(analyser);
  gain.connect(ctx.destination);
  node.start();

  const bins = new Uint8Array(analyser.frequencyBinCount);
  const g = canvas.getContext("2d");
  const sg = scope.getContext("2d");
  let raf;
  const frame = () => {
    analyser.getByteFrequencyData(bins);
    drawSpectrum(g, bins, canvas.width, canvas.height, ctx.sampleRate);
    analyser.getByteTimeDomainData(bins);
    drawWave(sg, bins, scope.width, scope.height);
    raf = requestAnimationFrame(frame);
  };
  frame();
  return () => {
    cancelAnimationFrame(raf);
    try { node.stop(); } catch { /* already stopped */ }
    gain.disconnect();
  };
}

// ------------------------------------------------------------------ dsp

function runDsp(canvas, scope, src, k, def, log, playIt) {
  const fn = new Function("input", "sr", "k", "A", src);
  const input = labSource(def.sourceKind, 2);
  let out;
  try {
    out = fn(input, A.SR, k, A);
  } catch (e) {
    log.textContent = String(e.message || e);
    return null;
  }
  if (!(out instanceof Float32Array)) {
    log.textContent = "process() must return a Float32Array.";
    return null;
  }
  const mag = A.fftMag(out.subarray(Math.floor(out.length / 3), Math.floor(out.length / 3) + 4096));
  const bins = new Uint8Array(mag.length);
  const peak = Math.max(A.peakOf(mag), 1e-9);
  for (let i = 0; i < mag.length; i++) {
    // dB scale: linear magnitude hides everything below the fundamental.
    bins[i] = Math.max(0, Math.min(255, (1 + Math.log10(mag[i] / peak + 1e-6) / 3) * 255));
  }
  drawSpectrum(canvas.getContext("2d"), bins, canvas.width, canvas.height, A.SR);

  const sg = scope.getContext("2d");
  const wave = new Uint8Array(600);
  const start = Math.floor(out.length / 3);
  for (let i = 0; i < wave.length; i++) {
    wave[i] = Math.max(0, Math.min(255, (out[start + i] * 0.5 + 0.5) * 255));
  }
  drawWave(sg, wave, scope.width, scope.height);

  let stopFn = null;
  if (playIt) {
    A.fade(out);
    stopFn = A.play(A.toBuffer([out]), { loop: true });
  }
  return () => { stopFn?.(); A.stopAll(); };
}

// ------------------------------------------------------------------ scopes

function drawSpectrum(g, bins, w, h, sr) {
  g.fillStyle = "#06080e";
  g.fillRect(0, 0, w, h);
  // Log frequency axis, because that is how the ear is laid out (tonotopy).
  const nyquist = sr / 2;
  const fmin = 20, fmax = Math.min(20000, nyquist);
  g.strokeStyle = "#1e2438";
  g.fillStyle = "#3a4260";
  g.font = "9px ui-monospace, monospace";
  for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
    if (f > fmax) break;
    const x = (Math.log(f / fmin) / Math.log(fmax / fmin)) * w;
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
    g.fillText(f >= 1000 ? `${f / 1000}k` : f, x + 2, h - 3);
  }
  g.beginPath();
  g.moveTo(0, h);
  for (let x = 0; x < w; x++) {
    const f = fmin * Math.pow(fmax / fmin, x / w);
    const bin = Math.round((f / nyquist) * bins.length);
    const v = bins[Math.min(bins.length - 1, bin)] / 255;
    g.lineTo(x, h - v * (h - 12));
  }
  g.lineTo(w, h);
  g.closePath();
  g.fillStyle = "rgba(124,156,255,.35)";
  g.fill();
  g.strokeStyle = "#7c9cff";
  g.stroke();
}

function drawWave(g, data, w, h) {
  g.fillStyle = "#06080e";
  g.fillRect(0, 0, w, h);
  g.strokeStyle = "#6ee7c8";
  g.beginPath();
  for (let x = 0; x < w; x++) {
    const v = data[Math.floor((x / w) * data.length)] / 128 - 1;
    const y = h / 2 - v * (h / 2 - 4);
    x ? g.lineTo(x, y) : g.moveTo(x, y);
  }
  g.stroke();
}
