// Generate — a sketchpad for making images fast.
//
// You write one colour expression. The wrapper supplies the coordinates, the
// clock and a small helper library; every uniform you declare turns into the
// control its type implies. Eject prints the real GLSL, so this is a ramp onto
// the Shader editor rather than a separate world.

import { el, clear, api, toast, modal, closeModal } from "./ui.js";
import { aiButton } from "./ai.js";
import { parseUniforms, desugar, SKETCH_VARS } from "./shader-uniforms.js";
import { buildControls, applyUniforms, randomise } from "./shader-controls.js";

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

export const GENERATE_PRESETS = [
  { id: "field", label: "Warm noise field", source:
`uniform float scale;   // @range 1 12 step 0.1 @default 3 — how tight the noise is
uniform vec3  deep;    // @color
uniform vec3  glow;    // @color
uniform float drift;   // @range 0 1 @default 0.15 — how fast it moves

mix(deep, glow, fbm(st * scale + t * drift))` },

  { id: "rings", label: "Cosine palette rings", source:
`uniform float rings;   // @range 1 40 @default 5 — ring count
uniform vec2  centre;  // @pad
uniform float warp;    // @range 0 2 @default 0.5
uniform float hue;     // @range 0 1 @default 0.08 — where the ramp starts
uniform float spread;  // @range 0.02 0.6 @default 0.16 — how far it travels

float d = length(p - (centre * 2.0 - 1.0)) * rings + fbm(p * 2.0) * warp - t * 0.1;

palette(d, vec3(0.5), vec3(0.45), vec3(1.0), vec3(hue, hue + spread, hue + spread * 2.0))` },

  { id: "cells", label: "Drifting cells", source:
`uniform float count;   // @range 2 30 step 1 @default 7 — cells across
uniform vec3  ink;     // @color
uniform vec3  ground;  // @color
uniform float falloff; // @range 0.15 1.2 @default 0.5 — how fast a cell fades from its centre

float cells(vec2 q, float n) {
  q *= n;
  vec2 i = floor(q), f = fract(q);
  float d = 1.0;
  for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
      vec2 g = vec2(float(x), float(y));
      vec2 o = vec2(hash21(i + g), hash21(i + g + 17.1));
      o = 0.5 + 0.5 * sin(t * 0.6 + 6.2831 * o);
      d = min(d, length(g + o - f));
    }
  }
  return d;
}

mix(ground, ink, cells(st, count) / falloff)` },

  { id: "badge", label: "Hard-edged badge", source:
`uniform float radius;  // @range 0.1 0.9 @default 0.5
uniform float bar;     // @range 0.0 0.6 @default 0.12
uniform vec3  ground;  // @color
uniform vec3  mark;    // @color

mix(ground, mark, aa(min(sdCircle(p, radius), sdBox(p, vec2(0.8, bar)))))` },

  { id: "moire", label: "Moiré interference", source:
`uniform float freq;    // @range 4 120 @default 26 — line frequency
uniform float turn;    // @range 0 1.57 @default 0.12 — angle between the two grids
uniform vec3  tint;    // @color

float a = sin(p.x * freq);
float b = sin((rot(turn) * p).x * freq);

tint * (0.5 + 0.5 * a * b)` },

  { id: "octaves", label: "Octaves, one at a time", source:
`uniform int   octaves; // @range 1 8 @default 5 — how many layers of detail
uniform float scale;   // @range 1 8 @default 3
uniform vec3  paper;   // @color

float layered(vec2 q) {
  float v = 0.0, amp = 0.5;
  for (int i = 0; i < 8; i++) {
    if (i >= octaves) break;   // the bound must be constant; the break need not be
    v += amp * noise(q);
    q *= 2.03;
    amp *= 0.5;
  }
  return v;
}

paper * layered(st * scale + seed)` },
];

export const newGenerateDoc = (preset = GENERATE_PRESETS[0]) => ({
  sketch: preset.source, preset: preset.id, uniforms: {}, seed: 0,
  preview: [640, 640], exportSize: [2048, 2048],
});

const SIZES = [[512, 512], [640, 640], [800, 450], [1024, 576], [1080, 1080], [1080, 1920]];
const EXPORTS = [[1024, 1024], [2048, 2048], [4096, 4096], [1920, 1080], [3840, 2160], [1080, 1920]];

export async function generateEditor(host) {
  const doc = host.data;
  doc.sketch ||= GENERATE_PRESETS[0].source;
  doc.uniforms ||= {};
  doc.seed ??= 0;
  doc.preview ||= [640, 640];
  doc.exportSize ||= [2048, 2048];

  const canvas = el("canvas", { width: doc.preview[0], height: doc.preview[1],
    style: { width: "100%", height: "auto", display: "block", background: "#000",
             borderRadius: "8px", cursor: "crosshair" } });
  const log = el("div.lab-log");
  const knobHost = el("div");
  const editor = el("textarea.editor", { spellcheck: false, value: doc.sketch,
    style: { minHeight: "420px" } });

  let gl = null, program = null, raf = null, t0 = performance.now();
  let uniforms = [];
  const mouse = [0.5, 0.5];
  let paused = false, pausedAt = 0;
  const fpsLabel = el("span.fine");
  let frames = 0, lastFpsAt = performance.now();

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = ((e.clientX - r.left) / r.width) * canvas.width;
    mouse[1] = (1 - (e.clientY - r.top) / r.height) * canvas.height;
  });

  function compile(fragSrc) {
    clear(log);
    if (!gl) {
      gl = canvas.getContext("webgl", { preserveDrawingBuffer: true, antialias: false });
      if (!gl) { log.textContent = "WebGL is not available in this browser."; return false; }
    }
    const mk = (type, code) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, code);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        const info = gl.getShaderInfoLog(s) || "compile failed";
        gl.deleteShader(s);
        throw new Error(info);
      }
      return s;
    };
    let p;
    try {
      const vs = mk(gl.VERTEX_SHADER, VERT);
      const fs = mk(gl.FRAGMENT_SHADER, fragSrc);
      p = gl.createProgram();
      gl.attachShader(p, vs);
      gl.attachShader(p, fs);
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(p) || "link failed");
      }
    } catch (e) {
      // The generated shader has a preamble you did not type, so a raw line
      // number would point at the wrong place. Say so rather than mislead.
      log.textContent = String(e.message).trim() +
        "\n\n(line numbers are for the generated shader — press Eject to see it)";
      return false;
    }
    if (program) gl.deleteProgram(program);
    program = p;
    gl.useProgram(program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    return true;
  }

  function draw() {
    if (!program || !gl) return;
    gl.viewport(0, 0, canvas.width, canvas.height);
    const u = (n) => gl.getUniformLocation(program, n);
    gl.uniform2f(u("u_resolution"), canvas.width, canvas.height);
    gl.uniform2f(u("u_mouse"), mouse[0], mouse[1]);
    gl.uniform1f(u("u_time"), paused ? pausedAt : (performance.now() - t0) / 1000);
    gl.uniform1f(u("u_seed"), doc.seed);
    applyUniforms(gl, program, uniforms, doc.uniforms);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function frame() {
    draw();
    frames++;
    const now = performance.now();
    if (now - lastFpsAt > 500) {
      fpsLabel.textContent =
        `${Math.round((frames * 1000) / (now - lastFpsAt))} fps · ${canvas.width}×${canvas.height}`;
      frames = 0; lastFpsAt = now;
    }
    raf = requestAnimationFrame(frame);
  }

  /** Re-read the source: rebuild the controls, then recompile. */
  function run(save = true) {
    doc.sketch = editor.value;
    uniforms = parseUniforms(doc.sketch);
    clear(knobHost);
    knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save()));
    const ok = compile(desugar(doc.sketch));
    if (ok && save) host.save(thumbnail());
    return ok;
  }

  function thumbnail() {
    try {
      const t = document.createElement("canvas");
      t.width = 240; t.height = Math.round((240 * canvas.height) / canvas.width);
      t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
      return t.toDataURL("image/jpeg", 0.7);
    } catch { return ""; }
  }

  /** Render once at the export size. The preview canvas is resized rather than
      a second context created, so what you export is what you were looking at. */
  function exportPng() {
    const [w, h] = doc.exportSize;
    const maxDim = gl ? gl.getParameter(gl.MAX_VIEWPORT_DIMS)[0] : 4096;
    if (w > maxDim || h > maxDim) {
      toast(`This GPU caps a render at ${maxDim}px. Pick a smaller size.`);
      return;
    }
    const [pw, ph] = [canvas.width, canvas.height];
    canvas.width = w; canvas.height = h;
    draw();
    let url;
    try { url = canvas.toDataURL("image/png"); }
    catch { toast("Could not read the canvas back."); }
    canvas.width = pw; canvas.height = ph;
    draw();
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${host.doc.name || "generate"}-${w}x${h}.png`;
    a.click();
    toast(`Exported ${w}×${h}.`);
  }

  function eject() {
    const src = desugar(doc.sketch);
    const area = el("textarea.editor", { value: src, spellcheck: false,
      style: { minHeight: "340px" } });
    modal(el("h2", {}, "The shader this becomes"),
      el("p.fine", {}, "Plain GLSL ES 1.00 — the same thing the Shader editor " +
        "runs. Open it there to keep working without the shorthand."),
      area,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => {
          navigator.clipboard?.writeText(src);
          toast("Copied.");
        } }, "Copy"),
        el("button.primary", { onclick: async () => {
          const made = await api("/api/studio/projects", { method: "POST",
            body: { kind: "shader", name: `${host.doc.name || "sketch"} (ejected)`,
                    data: { source: src, knobs: [0.5, 0.5, 0.5, 0.5] } } });
          closeModal();
          location.hash = `#studio/shader/${made.id}`;
        } }, "Open as a shader"),
        el("button.ghost", { onclick: closeModal }, "Close")));
  }

  function help() {
    modal(el("h2", {}, "How a sketch works"),
      el("p.fine", {}, "Write one colour expression. Anything above the last " +
        "`;` or `}` is preamble — uniforms and helper functions go there."),
      el("h3", {}, "In scope"),
      el("table", {}, el("tbody", {}, ...SKETCH_VARS.map(([n, ty, what]) =>
        el("tr", {}, el("td", {}, el("code", {}, n)), el("td", {}, el("span.fine", {}, ty)),
          el("td", {}, el("span.fine", {}, what)))))),
      el("h3", {}, "Controls from uniforms"),
      el("pre.editor", { style: { minHeight: "auto" } },
`uniform float scale;   // @range 1 40 step 0.5
uniform vec3  tint;    // @color
uniform vec2  centre;  // @pad
uniform int   octaves; // @range 1 8
uniform bool  mirror;  // @toggle`),
      el("p.fine", {}, "The type picks the control — float gives a slider, vec2 " +
        "an XY pad, vec3 named like a colour a swatch, bool a toggle. The " +
        "annotation only refines it, so a bare `uniform float k;` still works " +
        "and gets 0 to 1."),
      el("h3", {}, "Helpers"),
      el("p.fine", {}, "random, hash21, noise, fbm, rot, sdCircle, sdBox, " +
        "sdSegment, aa, palette, srgbToLinear, linearToSrgb. Define your own " +
        "with the same name and yours wins."),
      el("p.fine", {}, "#1b2b4b is a colour literal. Note it is an encoded " +
        "sRGB value, so mixing two of them mixes in the encoded space — wrap " +
        "in srgbToLinear if you want the mix to be physically right, which " +
        "Module 3 is the argument for."),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", { onclick: closeModal }, "Close")));
  }

  editor.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); run(); }
    if (e.key === "Tab") {
      e.preventDefault();
      const s = editor.selectionStart;
      editor.setRangeText("  ", s, editor.selectionEnd, "end");
    }
  });
  let typeTimer = null;
  editor.addEventListener("input", () => {
    clearTimeout(typeTimer);
    typeTimer = setTimeout(run, 700);
  });

  const presetSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      const p = GENERATE_PRESETS.find((x) => x.id === e.target.value);
      if (!p) return;
      editor.value = p.source;
      doc.preset = p.id;
      doc.uniforms = {};            // a new sketch means new free variables
      run();
    } }, el("option", { value: "" }, "sketch…"),
    ...GENERATE_PRESETS.map((p) =>
      el("option", { value: p.id, selected: p.id === doc.preset }, p.label)));

  const sizeSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      doc.preview = e.target.value.split("x").map(Number);
      canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
      host.save();
    } }, ...SIZES.map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.preview[0] && h === doc.preview[1] },
        `preview ${w}×${h}`)));

  const exportSel = el("select", { style: { width: "auto" },
    onchange: (e) => { doc.exportSize = e.target.value.split("x").map(Number); host.save(); },
  }, ...EXPORTS.map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.exportSize[0] && h === doc.exportSize[1] },
        `export ${w}×${h}`)));

  const pauseBtn = el("button", { onclick: () => {
    paused = !paused;
    if (paused) pausedAt = (performance.now() - t0) / 1000;
    else t0 = performance.now() - pausedAt * 1000;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
  } }, "Pause");

  const seedLabel = el("span.fine", {}, `seed ${doc.seed}`);

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        el("button.primary", { onclick: () => run() }, "Run"),
        pauseBtn,
        el("button", { onclick: () => { t0 = performance.now(); pausedAt = 0; } }, "Restart time"),
        presetSel, sizeSel, exportSel,
        el("button", { onclick: exportPng }, "Export PNG"),
        el("button", { onclick: () => {
          doc.seed = Math.floor(Math.random() * 10000);
          randomise(uniforms, doc.uniforms);
          seedLabel.textContent = `seed ${doc.seed}`;
          clear(knobHost);
          knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save()));
          host.save();
        } }, "Randomise"),
        el("button.ghost", { onclick: eject }, "Eject"),
        el("button.ghost", { onclick: help }, "Help"),
        aiButton("Sketch…", {
          task: "code",
          describe: "Describe the image. You get a sketch back; whether it " +
            "reads right is your call, not the model's.",
          placeholder: "e.g. deep blue ground, warm embers drifting upward, soft",
          context: () =>
            "Target: an expression for this app's shader sketch shorthand. " +
            "Write GLSL ES 1.00. Declare uniforms with annotation comments " +
            "(// @range lo hi, // @color, // @pad, // @toggle) and end with a " +
            "single colour expression — no main(), no gl_FragColor. " +
            "In scope: uv, st, p (vec2), t, seed (float), m (vec2). " +
            "Helpers: random, hash21, noise, fbm, rot, sdCircle, sdBox, " +
            "sdSegment, aa, palette. #rrggbb is a vec3 literal. " +
            "Loop bounds must be constant.",
          onResult: (res) => { editor.value = res.text; doc.uniforms = {}; run(); },
        }),
        seedLabel, fpsLabel)),

    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, canvas, log),
        knobHost,
        el("p.fine", {}, "Ctrl/Cmd+Enter runs. Editing re-runs after a pause. " +
          "A sketch that fails to compile leaves the last working image on " +
          "screen and prints the error underneath.")),
      el("div.stack", {}, editor)));

  run(false);
  frame();

  root._cleanup = () => {
    cancelAnimationFrame(raf);
    clearTimeout(typeTimer);
    if (gl && program) gl.deleteProgram(program);
    const lose = gl && gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  };
  return root;
}
