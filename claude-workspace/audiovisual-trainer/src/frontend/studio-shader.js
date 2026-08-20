// The shader canvas: a persistent GLSL sketchpad.
//
// Deliberately distinct from the Lab. The Lab has fixed guided builds tied to
// lessons; this is a sketchbook you keep, where a shader is a document you
// come back to.
//
// The uniform names are The Book of Shaders' exactly — u_resolution, u_time,
// u_mouse — so an example from that book pastes in and runs with no edits.
// That compatibility is the whole point of the chapter presets below; getting
// clever with the names would break the one thing this is for.

import { el, clear, toast, modal, closeModal } from "./ui.js";
import { fullscreenButton } from "./fullscreen.js";
import { aiButton } from "./ai.js";
import { parseUniforms } from "./shader-uniforms.js";
import { getGL, linkProgram } from "./shader-run.js";
import { buildControls, applyUniforms, bindTextures, releaseTextures } from "./shader-controls.js";
import { gridOverlay } from "./grid-overlay.js";

const PREAMBLE_HINT = `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform vec2  u_mouse;
uniform float u_time;
uniform vec4  u_k;          // the four sliders, if you want them`;

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

// Chapters follow thebookofshaders.com so the sketchpad tracks the reading.
export const SHADER_PRESETS = [
  { id: "hello", label: "01 · Hello world", source: `#ifdef GL_ES
precision mediump float;
#endif

void main() {
  gl_FragColor = vec4(1.0, 0.0, 1.0, 1.0);
}` },

  { id: "uniforms", label: "02 · Uniforms — time, resolution, mouse", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform vec2  u_mouse;
uniform float u_time;

void main() {
  // Normalised coordinates: 0..1 across the canvas, whatever its size.
  vec2 st = gl_FragCoord.xy / u_resolution;
  gl_FragColor = vec4(st.x, st.y, abs(sin(u_time)), 1.0);
}` },

  { id: "shaping", label: "05 · Shaping functions", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;

// Draw the curve itself, so you can see the function rather than infer it.
float plot(vec2 st, float pct) {
  return smoothstep(pct - 0.02, pct, st.y) - smoothstep(pct, pct + 0.02, st.y);
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;

  // Swap this line. pow, step, smoothstep, sin — each has a character.
  float y = smoothstep(0.1, 0.9, st.x);

  vec3 color = vec3(y);
  float pct = plot(st, y);
  color = (1.0 - pct) * color + pct * vec3(0.0, 1.0, 0.4);
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "colors", label: "06 · Colors", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;

// HSB to RGB — hue as an angle is the useful part.
vec3 hsb2rgb(vec3 c) {
  vec3 rgb = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0,
                   0.0, 1.0);
  rgb = rgb * rgb * (3.0 - 2.0 * rgb);
  return c.z * mix(vec3(1.0), rgb, c.y);
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  vec3 color = hsb2rgb(vec3(st.x + u_time * 0.05, 1.0, st.y));
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "shapes", label: "07 · Shapes and distance fields", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform vec2  u_mouse;
uniform float u_time;

float circle(vec2 st, vec2 c, float r) {
  return 1.0 - smoothstep(r - 0.005, r + 0.005, length(st - c));
}

float box(vec2 st, vec2 c, vec2 b) {
  vec2 d = abs(st - c) - b;
  return 1.0 - smoothstep(0.0, 0.008,
                          length(max(d, 0.0)) + min(max(d.x, d.y), 0.0));
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  st.x *= u_resolution.x / u_resolution.y;      // keep circles round

  vec2 m = u_mouse / u_resolution;
  m.x *= u_resolution.x / u_resolution.y;

  float c = circle(st, m, 0.18);
  float b = box(st, vec2(0.5), vec2(0.12 + 0.04 * sin(u_time)));

  vec3 color = mix(vec3(0.05, 0.06, 0.09), vec3(0.49, 0.61, 1.0), b);
  color = mix(color, vec3(0.43, 0.90, 0.78), c);
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "matrices", label: "08 · Matrices — translate, rotate, scale", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;

mat2 rotate2d(float a) {
  return mat2(cos(a), -sin(a), sin(a), cos(a));
}

float box(vec2 st, vec2 size) {
  size = vec2(0.5) - size * 0.5;
  vec2 uv = smoothstep(size, size + vec2(0.004), st);
  uv *= smoothstep(size, size + vec2(0.004), vec2(1.0) - st);
  return uv.x * uv.y;
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;

  // You do not rotate the shape. You rotate the space it is measured in —
  // which is why the pivot is the centre and not the corner.
  st -= 0.5;
  st = rotate2d(u_time * 0.4) * st;
  st += 0.5;

  vec3 color = vec3(box(st, vec2(0.3)));
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "patterns", label: "09 · Patterns — tiling", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;
uniform vec4  u_k;      // x = tile count

mat2 rotate2d(float a) { return mat2(cos(a), -sin(a), sin(a), cos(a)); }

float box(vec2 st, vec2 size) {
  size = vec2(0.5) - size * 0.5;
  vec2 uv = smoothstep(size, size + vec2(0.02), st);
  uv *= smoothstep(size, size + vec2(0.02), vec2(1.0) - st);
  return uv.x * uv.y;
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  st *= max(1.0, u_k.x * 12.0);

  vec2 ipos = floor(st);      // which tile
  vec2 fpos = fract(st);      // where inside it

  // Per-tile variation is what stops a tiling reading as wallpaper.
  fpos -= 0.5;
  fpos = rotate2d(u_time * 0.5 + ipos.x + ipos.y) * fpos;
  fpos += 0.5;

  vec3 color = vec3(box(fpos, vec2(0.7)));
  color *= mix(vec3(0.49, 0.61, 1.0), vec3(0.94, 0.64, 0.37),
               fract(ipos.x * 0.37 + ipos.y * 0.21));
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "random", label: "10 · Random", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;
uniform vec4  u_k;     // x = grid

// The classic one-liner. It is not random, it is chaotic and repeatable —
// which is exactly what you want, because it is the same every frame.
float random(vec2 st) {
  return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  st *= max(2.0, u_k.x * 40.0);
  float r = random(floor(st));
  gl_FragColor = vec4(vec3(r), 1.0);
}` },

  { id: "noise", label: "11 · Noise", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;
uniform vec4  u_k;      // x = scale

float random(vec2 st) {
  return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
}

float noise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = random(i);
  float b = random(i + vec2(1.0, 0.0));
  float c = random(i + vec2(0.0, 1.0));
  float d = random(i + vec2(1.0, 1.0));
  // Smoothstep, not linear: linear interpolation makes the lattice visible.
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  vec2 pos = st * max(2.0, u_k.x * 20.0) + u_time * 0.3;
  gl_FragColor = vec4(vec3(noise(pos)), 1.0);
}` },

  { id: "cellular", label: "12 · Cellular noise", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;
uniform vec4  u_k;      // x = cell count

vec2 random2(vec2 p) {
  return fract(sin(vec2(dot(p, vec2(127.1, 311.7)),
                        dot(p, vec2(269.5, 183.3)))) * 43758.5453);
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  st.x *= u_resolution.x / u_resolution.y;
  st *= max(2.0, u_k.x * 10.0);

  vec2 i_st = floor(st);
  vec2 f_st = fract(st);
  float m_dist = 1.0;

  // Only the nine neighbouring cells can hold the nearest point.
  for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
      vec2 neighbor = vec2(float(x), float(y));
      vec2 point = random2(i_st + neighbor);
      point = 0.5 + 0.5 * sin(u_time + 6.2831 * point);
      m_dist = min(m_dist, length(neighbor + point - f_st));
    }
  }

  vec3 color = vec3(m_dist);
  color += 1.0 - step(0.03, m_dist);      // the feature points themselves
  gl_FragColor = vec4(color, 1.0);
}` },

  { id: "fbm", label: "13 · Fractal Brownian Motion", source: `#ifdef GL_ES
precision mediump float;
#endif

uniform vec2  u_resolution;
uniform float u_time;
uniform vec4  u_k;      // x = scale, y = octaves, z = warp

float random(vec2 st) {
  return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
}

float noise(vec2 st) {
  vec2 i = floor(st), f = fract(st);
  float a = random(i), b = random(i + vec2(1.0, 0.0));
  float c = random(i + vec2(0.0, 1.0)), d = random(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// Octaves at halving amplitude and doubling frequency. Detail at every scale
// is what reads as organic rather than manufactured.
float fbm(vec2 st, float octaves) {
  float value = 0.0, amplitude = 0.5;
  for (int i = 0; i < 8; i++) {
    if (float(i) >= octaves) break;
    value += amplitude * noise(st);
    st *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}

void main() {
  vec2 st = gl_FragCoord.xy / u_resolution;
  st *= max(1.0, u_k.x * 6.0);
  float oct = max(1.0, u_k.y * 8.0);

  // Domain warp: feed noise its own output. The cheapest way to stop noise
  // looking like noise.
  vec2 q = vec2(fbm(st + u_time * 0.05, oct), fbm(st + vec2(5.2, 1.3), oct));
  float f = fbm(st + q * u_k.z * 4.0, oct);

  vec3 color = mix(vec3(0.05, 0.07, 0.13), vec3(0.95, 0.87, 0.74),
                   clamp(f * 1.6, 0.0, 1.0));
  color = mix(color, vec3(0.43, 0.90, 0.78), clamp(q.x * q.x * 1.2, 0.0, 1.0));
  gl_FragColor = vec4(color, 1.0);
}` },
];

export async function shaderEditor(host) {
  const doc = host.data;
  doc.source ||= SHADER_PRESETS[1].source;
  doc.knobs ||= [0.5, 0.5, 0.5, 0.5];
  doc.paused = false;
  // Documents written before uniforms were introspected stored four bare
  // numbers. They were always u_k, so that is where they land.
  doc.uniforms ||= { u_k: doc.knobs.slice() };

  const canvas = el("canvas", { width: 640, height: 480,
    style: { width: "100%", height: "auto", display: "block", background: "#000",
             borderRadius: "8px", cursor: "crosshair" } });
  const log = el("div.lab-log");
  const editor = el("textarea.editor", { spellcheck: false, value: doc.source,
    style: { minHeight: "460px" } });

  const knobHost = el("div");
  let gl = null, program = null, raf = null, t0 = performance.now();
  let uniforms = [];
  const textures = {};
  const grid = gridOverlay();

  async function onImage(u, file) {
    const asset = await host.upload(file, { role: "texture", uniform: u.name });
    const dims = await new Promise((res) => {
      const im = new Image();
      im.onload = () => res([im.naturalWidth, im.naturalHeight]);
      im.onerror = () => res([0, 0]);
      im.src = asset.url;
    });
    return { url: asset.url, assetId: asset.id, w: dims[0], h: dims[1] };
  }
  const mouse = [0.5, 0.5];
  let fps = 0, frames = 0, lastFpsAt = performance.now();
  const fpsLabel = el("span.fine");

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = ((e.clientX - r.left) / r.width) * canvas.width;
    mouse[1] = (1 - (e.clientY - r.top) / r.height) * canvas.height;
  });

  function compile(src) {
    clear(log);
    if (!gl) {
      gl = getGL(canvas);
      if (!gl) { log.textContent = "WebGL is not available in this browser."; return false; }
    }
    let p;
    try {
      // A Book of Shaders paste-in is 1.00 and compiles unchanged on WebGL2;
      // a shader that opens with `#version 300 es` gets a 300 vertex stage.
      p = linkProgram(gl, src);
    } catch (e) {
      // Keep the last working program on screen: a shader that fails to
      // compile should not blank the thing you were looking at.
      log.textContent = String(e.message).trim();
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

  function frame() {
    if (program && gl) {
      const now = performance.now();
      gl.viewport(0, 0, canvas.width, canvas.height);
      const u = (n) => gl.getUniformLocation(program, n);
      gl.uniform2f(u("u_resolution"), canvas.width, canvas.height);
      gl.uniform2f(u("u_mouse"), mouse[0], mouse[1]);
      gl.uniform1f(u("u_time"), doc.paused ? pausedAt : (now - t0) / 1000);
      gl.uniform1f(u("u_seed"), doc.seed || 0);
      applyUniforms(gl, program, uniforms, doc.uniforms);
      bindTextures(gl, program, uniforms, doc.uniforms, textures);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      frames++;
      if (now - lastFpsAt > 500) {
        fps = Math.round((frames * 1000) / (now - lastFpsAt));
        fpsLabel.textContent = `${fps} fps · ${canvas.width}×${canvas.height}`;
        frames = 0; lastFpsAt = now;
      }
    }
    raf = requestAnimationFrame(frame);
  }
  let pausedAt = 0;

  function run() {
    // Every uniform you declare gets the control its type implies. u_k keeps
    // working — it is just a vec4 like any other now, so the old documents
    // carry their knob values straight over.
    uniforms = parseUniforms(editor.value);
    clear(knobHost);
    knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save(), { onImage }));
    const ok = compile(editor.value);
    if (ok) {
      doc.source = editor.value;
      host.save(thumbnail());
    }
  }

  function thumbnail() {
    try {
      const t = document.createElement("canvas");
      t.width = 240; t.height = Math.round((240 * canvas.height) / canvas.width);
      t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
      return t.toDataURL("image/jpeg", 0.7);
    } catch { return ""; }
  }

  function savePng() {
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${host.doc.name || "shader"}.png`;
    a.click();
  }

  // Ctrl/Cmd+Enter to run — the reflex from every live-coding environment.
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
    typeTimer = setTimeout(run, 700);     // live, but not on every keystroke
  });

  const presetSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      const p = SHADER_PRESETS.find((x) => x.id === e.target.value);
      if (!p) return;
      editor.value = p.source;
      doc.preset = p.id;
      run();
    },
  }, el("option", { value: "" }, "chapter…"),
     ...SHADER_PRESETS.map((p) => el("option", { value: p.id, selected: p.id === doc.preset }, p.label)));

  const sizeSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      const [w, h] = e.target.value.split("x").map(Number);
      canvas.width = w; canvas.height = h;
    },
  }, ...[[640, 480], [512, 512], [800, 450], [1024, 576], [1080, 1080]].map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === 640 }, `${w}×${h}`)));

  const pauseBtn = el("button", {
    onclick: () => {
      doc.paused = !doc.paused;
      if (doc.paused) pausedAt = (performance.now() - t0) / 1000;
      else t0 = performance.now() - pausedAt * 1000;
      pauseBtn.textContent = doc.paused ? "Resume" : "Pause";
    },
  }, "Pause");

  // The picture and its overlay together: the thing that goes fullscreen.
  const stage = el("div", { style: { position: "relative", display: "flex",
                                     alignItems: "center", justifyContent: "center" } },
                   canvas, grid.overlay);
  const fs = fullscreenButton(stage, { className: "", onRefused: (why) => { log.textContent = why; } });

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        el("button.primary", { onclick: run }, "Run"),
        pauseBtn,
        el("button", { onclick: () => { t0 = performance.now(); pausedAt = 0; } }, "Restart time"),
        presetSel, sizeSel,
        el("button", { onclick: savePng }, "PNG"),
        grid.button,
        el("button.ghost", {
          onclick: () => modal(el("h2", {}, "Uniforms available"),
            el("pre.editor", { style: { minHeight: "auto" } }, PREAMBLE_HINT),
            el("p.fine", {}, "These are The Book of Shaders' names, so examples " +
              "from the book paste in and run unchanged. u_mouse is in pixels, " +
              "with y measured from the bottom, as GLSL expects."),
            el("div.row", { style: { justifyContent: "flex-end" } },
              el("button.primary", { onclick: closeModal }, "Close"))),
        }, "Uniforms"),
        aiButton("Implement…", {
          task: "code",
          describe: "Describe the look in perceptual terms. You get a shader " +
            "back; whether it reads right is your call, not the model's.",
          placeholder: "e.g. slow breathing glow with an organic noisy edge, " +
            "warm core, dark ground",
          context: () => "Target: a single WebGL1 GLSL ES 1.00 fragment shader. " +
            "Available uniforms: vec2 u_resolution, vec2 u_mouse, float u_time, " +
            "vec4 u_k. Must set gl_FragColor. Start with the " +
            "'#ifdef GL_ES precision mediump float; #endif' guard.",
          onResult: (res) => { editor.value = res.text; run(); },
        }),
        fs.button, fpsLabel)),

    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, stage, log),
        knobHost,
        el("p.fine", {}, "Ctrl/Cmd+Enter runs. Editing re-runs after a pause. " +
          "A shader that fails to compile leaves the last working one on " +
          "screen and prints the error underneath.")),
      el("div.stack", {}, editor)));

  run();
  frame();

  // Without this the render loop and the GL context outlive the editor. A
  // browser only grants a handful of WebGL contexts before it starts dropping
  // the oldest, so leaking one per visit eventually blanks the canvas.
  root._cleanup = () => {
    cancelAnimationFrame(raf);
    clearTimeout(typeTimer);
    if (gl) releaseTextures(gl, textures);
    if (gl && program) gl.deleteProgram(program);
    const lose = gl && gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  };
  return root;
}
