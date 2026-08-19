// Run a sketch (or full GLSL) offscreen and hand back pixels.
//
// This is what lets a shader act as a filter in the Canvas studio, and what
// an image-only caller uses when it does not want an editor: give it source,
// a size, images by uniform name (as canvases), values, and a time; get a
// canvas back. Feedback works too — ask for N steps and the sim runs N times
// before the picture is drawn.
//
// One hidden WebGL canvas is shared, because a browser only grants a handful
// of contexts and a filter dialog would otherwise burn one per preview.

import { parseUniforms, desugar, hasSimPass, isEs3, withDefine } from "./shader-uniforms.js";
import { applyUniforms } from "./shader-controls.js";
import { Feedback } from "./feedback.js";

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;
const VERT_300 = `#version 300 es
in vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

/**
 * A GL context for shader work: WebGL2 where the browser has it, WebGL1
 * otherwise. WebGL2 is where float render targets, fwidth, integer textures
 * and MRT are standard rather than extensions, and a 1.00 shader still
 * compiles on it unchanged — so nothing is lost by asking for it first.
 */
export function getGL(canvas, attrs = {}) {
  const a = { preserveDrawingBuffer: true, antialias: false, ...attrs };
  const gl2 = canvas.getContext("webgl2", a);
  if (gl2) return gl2;
  return canvas.getContext("webgl", a);
}
export const isGL2 = (gl) =>
  typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext;

/** Link a fragment shader with the matching vertex shader for its version. */
export function linkProgram(gl, fragSrc) {
  const mk = (type, code) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, code);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const info = gl.getShaderInfoLog(sh) || "compile failed";
      gl.deleteShader(sh);
      throw new Error(info);
    }
    return sh;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, mk(gl.VERTEX_SHADER, isEs3(fragSrc) ? VERT_300 : VERT));
  gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, fragSrc));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(prog) || "link failed");
  }
  return prog;
}

let shared = null;   // { canvas, gl, quad, feedback, programs: Map }

function ctx() {
  if (shared) return shared;
  const canvas = document.createElement("canvas");
  const gl = getGL(canvas);
  if (!gl) throw new Error("WebGL is not available");
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  shared = { canvas, gl, quad, feedback: new Feedback(gl), programs: new Map() };
  return shared;
}

const link = linkProgram;

/** Full GLSL for a source that may be a sketch or may already be a shader.
    A sketch is emitted for the context it will run on. */
export function toGlsl(source, gl = null) {
  if (/\bvoid\s+main\s*\(/.test(source)) return source;
  return desugar(source, { es3: gl ? isGL2(gl) : !!(shared && isGL2(shared.gl)) });
}

/** Compile once per distinct source; a filter dialog re-renders on every
    slider move and must not recompile each time. */
function programsFor(source) {
  const s = ctx();
  const glsl = toGlsl(source, s.gl);
  let entry = s.programs.get(glsl);
  if (entry) return entry;
  const display = link(s.gl, glsl);
  const sim = hasSimPass(glsl) ? link(s.gl, withDefine(glsl, "SIM_PASS")) : null;
  entry = { display, sim, uniforms: parseUniforms(source) };
  // Keep the cache small: a dialog only ever wants the last few.
  if (s.programs.size > 8) {
    const [k, v] = s.programs.entries().next().value;
    s.gl.deleteProgram(v.display);
    if (v.sim) s.gl.deleteProgram(v.sim);
    s.programs.delete(k);
  }
  s.programs.set(glsl, entry);
  return entry;
}

function uploadCanvas(gl, tex, src) {
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
}

/**
 * Render `source` at width×height and return a 2D canvas of the result.
 *
 * @param opts.images   { uniformName: HTMLCanvasElement | HTMLImageElement | ImageBitmap }
 * @param opts.values   uniform values keyed by name (as the editors store them)
 * @param opts.time     seconds for u_time
 * @param opts.steps    sim steps to run before drawing (feedback sketches)
 * @param opts.reset    clear the feedback state first (default true)
 * @param opts.mouse    [x, y] in pixels, y up (default centre)
 * @param opts.seed
 */
export function renderSketch(source, width, height, opts = {}) {
  const s = ctx();
  const { gl, canvas, quad, feedback } = s;
  const { display, sim, uniforms } = programsFor(source);
  const values = opts.values || {};
  const images = opts.images || {};

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width; canvas.height = height;
  }
  // Two targets when the sketch defines sim2(); the buffers decide whether
  // the GPU will actually give two, and say so in describe().
  feedback.resize(width, height, dualTargets(source) ? 2 : 1);
  if (opts.reset !== false) feedback.reset();

  // The keyboard picture, uploaded once per render and kept between them.
  const keysTex = () => {
    if (!s.keys) {
      s.keys = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, s.keys);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    }
    const src = opts.keys && opts.keys.texture ? opts.keys.texture() : opts.keys;
    gl.bindTexture(gl.TEXTURE_2D, s.keys);
    if (src) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    return s.keys;
  };

  // Image uniforms from the caller's canvases.
  const texByName = new Map();
  let unit = 0;
  const bindCommon = (prog, prevTex, stateTex, stateTex2) => {
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    // A tile draws at its own size but must think in the whole picture's, or
    // every scale in the sketch would change with the tiling.
    const res = opts.resolution || [width, height];
    gl.uniform2f(u("u_resolution"), res[0], res[1]);
    gl.uniform2f(u("u_origin"), (opts.origin || [0, 0])[0], (opts.origin || [0, 0])[1]);
    const m = opts.mouse || [res[0] / 2, res[1] / 2];
    gl.uniform2f(u("u_mouse"), m[0], m[1]);
    gl.uniform1f(u("u_time"), opts.time || 0);
    gl.uniform1f(u("u_seed"), opts.seed || 0);
    gl.uniform1i(u("u_frame"), feedback.frame);
    gl.uniform1f(u("u_mouseDown"), opts.mouseDown ? 1 : 0);
    applyUniforms(gl, prog, uniforms, values);
    unit = 0;
    for (const uni of uniforms) {
      if (uni.control !== "image") continue;
      let tex = texByName.get(uni.name);
      // A sampler that carries its own picture in the source resolves from the
      // cache loadSketchImages filled.
      const src = images[uni.name] || (uni.src && imageCache.get(uni.src)) || null;
      if (!tex) {
        tex = gl.createTexture();
        if (src) uploadCanvas(gl, tex, src);
        else {
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
                        new Uint8Array([128, 128, 128, 255]));
        }
        texByName.set(uni.name, tex);
      }
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      if (u(uni.name)) gl.uniform1i(u(uni.name), unit);
      const sz = u(uni.sizeUniform);
      if (sz) gl.uniform2f(sz, src ? (src.width || src.naturalWidth || 0) : 0,
                               src ? (src.height || src.naturalHeight || 0) : 0);
      unit++;
    }
    gl.activeTexture(gl.TEXTURE6);
    gl.bindTexture(gl.TEXTURE_2D, prevTex);
    if (u("u_prev")) gl.uniform1i(u("u_prev"), 6);
    gl.activeTexture(gl.TEXTURE7);
    gl.bindTexture(gl.TEXTURE_2D, stateTex);
    if (u("u_state")) gl.uniform1i(u("u_state"), 7);
    // The second state, where the sketch keeps one. Without it, state2()
    // reads the first — the sketch still runs, it just has one field.
    gl.activeTexture(gl.TEXTURE0 + 5);
    gl.bindTexture(gl.TEXTURE_2D, stateTex2 || stateTex);
    if (u("u_state2")) gl.uniform1i(u("u_state2"), 5);
    // The keyboard, on the one unit left between the images and the state.
    // Absent, a blank: every key reads as up, which is what a sketch that
    // asks about keys in a still export should see.
    if (u("u_keys")) {
      gl.activeTexture(gl.TEXTURE0 + 4);
      gl.bindTexture(gl.TEXTURE_2D, keysTex());
      gl.uniform1i(u("u_keys"), 4);
    }
    gl.activeTexture(gl.TEXTURE0);
  };

  if (sim) {
    const steps = Math.max(1, opts.steps || 1);
    for (let i = 0; i < steps; i++) {
      const w = feedback.write, r = feedback.read;
      gl.bindFramebuffer(gl.FRAMEBUFFER, w.fbo);
      gl.viewport(0, 0, width, height);
      bindCommon(sim, r.tex, r.tex, r.tex2);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      feedback.swap();
    }
  }
  gl.viewport(0, 0, width, height);
  if (sim) bindCommon(display, feedback.write.tex, feedback.read.tex, feedback.read.tex2);
  else bindCommon(display, feedback.prevTex, feedback.prevTex);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  if (!sim) feedback.captureCanvas();

  for (const tex of texByName.values()) gl.deleteTexture(tex);

  const out = document.createElement("canvas");
  out.width = width; out.height = height;
  out.getContext("2d").drawImage(canvas, 0, 0);
  return out;
}

/** The largest square this GPU will render in one go. */
export function maxRenderSize(gl = null) {
  const g = gl || (shared ? shared.gl : ctx().gl);
  return Math.min(g.getParameter(g.MAX_TEXTURE_SIZE), g.getParameter(g.MAX_VIEWPORT_DIMS)[0]);
}

/**
 * Render at any size, in tiles where the GPU will not do it in one go.
 *
 * Each tile draws with the *full* resolution in u_resolution and its own
 * corner in u_origin, so every pixel believes it is where it will end up —
 * which is what makes a tiled render identical to an untiled one rather than
 * merely similar. Returns a 2D canvas.
 *
 * A sketch that keeps state cannot be tiled: a sim reads its neighbours, and
 * a tile's neighbours are in another tile. Those come back untiled, and the
 * caller is told the size it actually got.
 */
export function renderTiled(source, width, height, opts = {}) {
  const s = ctx();
  const max = maxRenderSize(s.gl);
  const bare = String(source);
  const keepsState = /\bvec4\s+sim\s*\(\s*vec2\b/.test(bare) || /\bu_prev\b/.test(bare);
  // `tile` forces a step, which is how the self-test exercises the tiled path
  // at a size the GPU would happily do in one go.
  const forced = opts.tile ? Math.max(8, opts.tile | 0) : 0;
  if (!forced && ((width <= max && height <= max) || keepsState)) {
    const w = Math.min(width, max), h = Math.min(height, max);
    const out = renderSketch(source, w, h, opts);
    return { canvas: out, width: w, height: h, tiles: 1,
             clamped: w !== width || h !== height,
             why: keepsState && (width > max || height > max)
               ? "a sketch that keeps state cannot be tiled — a tile's neighbours are in the next tile"
               : null };
  }
  const out = document.createElement("canvas");
  out.width = width; out.height = height;
  const g = out.getContext("2d");
  const step = forced || Math.min(max, 2048);
  let tiles = 0;
  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      const tw = Math.min(step, width - x), th = Math.min(step, height - y);
      // u_origin is in gl_FragCoord's frame, which counts up from the bottom.
      const originY = height - y - th;
      const tile = renderSketch(source, tw, th, {
        ...opts, tile: 0, resolution: [width, height], origin: [x, originY] });
      g.drawImage(tile, x, y);
      tiles++;
    }
  }
  return { canvas: out, width, height, tiles, clamped: false, why: null };
}

/** Does this sketch keep two fields? `vec4 sim2(vec2)` is how it says so. */
export const dualTargets = (source) =>
  /\bvec4\s+sim2\s*\(\s*vec2\b/.test(String(source)) && /\bvec4\s+sim\s*\(\s*vec2\b/.test(String(source));

/** The controls a source would show, for a host that wants to build them. */
export function sketchUniforms(source) {
  return parseUniforms(source);
}

const imageCache = new Map();      // url → HTMLImageElement, decoded

/** What loadSketchImages has decoded, for anything that binds its own samplers. */
export const cachedImage = (src) => imageCache.get(src) || null;

/**
 * Resolve every sampler the source declares with `@data` or `@asset` into a
 * decoded image, so a later renderSketch can bind it. Sources carry their own
 * pictures — a compiled design carries its glyph atlas this way — and a
 * synchronous render cannot wait for them, so this is the step before.
 */
export async function loadSketchImages(source, into = {}) {
  const jobs = [];
  for (const u of parseUniforms(source)) {
    if (u.control !== "image" || !u.src || into[u.name]) continue;
    if (imageCache.has(u.src)) { into[u.name] = imageCache.get(u.src); continue; }
    jobs.push(new Promise((res) => {
      const im = new Image();
      im.crossOrigin = "anonymous";
      im.onload = () => { imageCache.set(u.src, im); into[u.name] = im; res(); };
      im.onerror = () => res();
      im.src = u.src;
    }));
  }
  await Promise.all(jobs);
  return into;
}
