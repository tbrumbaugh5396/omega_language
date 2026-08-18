// The graph compiler: a render graph → passes → pixels.
//
// One pass per node, for now. Each node's sketch is compiled once per type
// (through desugar, like any sketch), drawn into a framebuffer from a small
// pool with its inputs bound as textures, and the framebuffer becomes the
// input of whatever reads it. Sources are textures the host hands in. The
// output node's framebuffer is what you get back.
//
// Fusing consecutive per-pixel nodes into one shader is the next step
// (roadmap 1.4); nothing here prevents it, because a node body only ever
// reads in0 at uv unless it says @pass. Ejection needs no such step: the
// passes are already text.

import { desugar, isEs3, withDefine } from "./shader-uniforms.js";
import { applyUniforms } from "./shader-controls.js";
import { getGL, isGL2, linkProgram } from "./shader-run.js";
import { nodeType, topo, validate, curveLut, resolveBypass } from "./render-graph.js";

// ------------------------------------------------------------------ targets

/** A pool of framebuffers, one size, negotiated to the best precision. */
class TargetPool {
  constructor(gl) {
    this.gl = gl;
    this.gl2 = isGL2(gl);
    this.free = [];
    this.kind = null;
    if (this.gl2) {
      // Half float is the working precision: intermediates in an adjustment
      // chain do not need 32 bits, and it halves the memory.
      this.ext = gl.getExtension("EXT_color_buffer_float") || gl.getExtension("EXT_color_buffer_half_float");
      this.floatLinear = !!gl.getExtension("OES_texture_float_linear");
    } else {
      this.half = gl.getExtension("OES_texture_half_float");
      this.halfLinear = gl.getExtension("OES_texture_half_float_linear");
    }
  }
  make(w, h) {
    const gl = this.gl;
    const tryKind = (kind) => {
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      if (this.gl2) {
        const internal = kind === "half" ? gl.RGBA16F : gl.RGBA8;
        const type = kind === "half" ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE;
        gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, gl.RGBA, type, null);
      } else {
        const type = kind === "half" ? this.half.HALF_FLOAT_OES : gl.UNSIGNED_BYTE;
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, type, null);
      }
      const linear = kind === "byte" || this.gl2 || this.halfLinear;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, linear ? gl.LINEAR : gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, linear ? gl.LINEAR : gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      const fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE && gl.getError() === gl.NO_ERROR;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      if (!ok) { gl.deleteTexture(tex); gl.deleteFramebuffer(fbo); return null; }
      return { tex, fbo, w, h, kind };
    };
    const order = this.kind ? [this.kind] : ((this.gl2 ? this.ext : this.half) ? ["half", "byte"] : ["byte"]);
    for (const k of order) {
      const t = tryKind(k);
      if (t) { this.kind = k; return t; }
    }
    throw new Error("could not allocate a render target");
  }
  get(w, h) {
    const i = this.free.findIndex((t) => t.w === w && t.h === h);
    if (i >= 0) return this.free.splice(i, 1)[0];
    return this.make(w, h);
  }
  put(t) { if (t) this.free.push(t); }
  release() {
    for (const t of this.free) { this.gl.deleteTexture(t.tex); this.gl.deleteFramebuffer(t.fbo); }
    this.free = [];
  }
}

// ------------------------------------------------------------------ runner

export class GraphRunner {
  constructor(gl) {
    this.gl = gl;
    this.pool = new TargetPool(gl);
    this.programs = new Map();      // type id → { prog }
    this.luts = new Map();          // key → texture
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    this.blank = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]));
  }

  /** The GLSL a node type compiles to on this context. */
  sourceFor(typeId) {
    const t = nodeType(typeId);
    if (!t) throw new Error(`no node type ${typeId}`);
    return desugar(t.source, { es3: isGL2(this.gl) });
  }

  programFor(typeId) {
    let e = this.programs.get(typeId);
    if (e) return e;
    e = { prog: linkProgram(this.gl, this.sourceFor(typeId)) };
    this.programs.set(typeId, e);
    return e;
  }

  /** Upload a caller's image (canvas, image, bitmap) as a texture. */
  textureFrom(src) {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return { tex, w: src.width || src.naturalWidth, h: src.height || src.naturalHeight, owned: true };
  }

  /** A 256×1 lookup texture from a byte array, cached by content. */
  lutTexture(bytes) {
    const key = Array.from(bytes.subarray(0, 64)).join(",") + "|" + bytes.length;
    let tex = this.luts.get(key);
    if (tex) return tex;
    const gl = this.gl;
    tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, bytes.length / 4, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.length));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    if (this.luts.size > 32) { const [k, v] = this.luts.entries().next().value; gl.deleteTexture(v); this.luts.delete(k); }
    this.luts.set(key, tex);
    return tex;
  }

  /**
   * Run the graph. `sources` maps a source node's id to a canvas/image or to
   * a {tex,w,h}. Returns { tex, w, h } — the output's framebuffer texture,
   * valid until the next run — plus a `passes` list for the record.
   */
  run(graph, sources = {}, opts = {}) {
    const gl = this.gl;
    const errs = validate(graph);
    if (errs.length) throw new Error(errs.join("; "));
    const W = graph.width, H = graph.height;
    const order = topo(graph);
    const outputs = new Map();        // node id → { tex, w, h, target? }
    const owned = [];
    const passes = [];

    for (const n of order) {
      if (n.type === "source") {
        const s = sources[n.id];
        if (!s) throw new Error(`no source supplied for ${n.id}`);
        const t = s.tex ? { tex: s.tex, w: s.w, h: s.h } : this.textureFrom(s);
        if (t.owned) owned.push(t);
        outputs.set(n.id, t);
        continue;
      }
      if (n.bypass) {
        const from = resolveBypass(graph, n.id);
        outputs.set(n.id, outputs.get(from ? from.id : n.inputs[0]) || { tex: this.blank, w: 1, h: 1 });
        continue;
      }
      const type = nodeType(n.type);
      const { prog } = this.programFor(n.type);
      const target = this.pool.get(W, H);
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.viewport(0, 0, W, H);
      gl.useProgram(prog);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
      const loc = gl.getAttribLocation(prog, "a_pos");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      const u = (name) => gl.getUniformLocation(prog, name);
      gl.uniform2f(u("u_resolution"), W, H);
      gl.uniform1f(u("u_time"), opts.time || 0);
      gl.uniform2f(u("u_mouse"), W / 2, H / 2);
      gl.uniform1f(u("u_seed"), 0);
      gl.uniform1i(u("u_frame"), 0);
      gl.uniform1f(u("u_mouseDown"), 0);
      // Parameters: the node's values, defaults for anything unset.
      const values = {};
      for (const p of type.params) {
        if (p.control === "image") continue;
        const v = n.params[p.name];
        values[p.name] = Array.isArray(v) ? v : (v !== undefined && v !== null ? [v] : p.value.slice());
      }
      applyUniforms(gl, prog, type.uniforms, values);
      // Inputs on the first units, LUTs after.
      let unit = 0;
      type.inputs.forEach((name, i) => {
        const src = outputs.get(n.inputs[i]) || { tex: this.blank, w: 1, h: 1 };
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, src.tex);
        if (u(name)) gl.uniform1i(u(name), unit);
        if (u(`${name}_size`)) gl.uniform2f(u(`${name}_size`), src.w, src.h);
        unit++;
      });
      for (const lname of type.luts) {
        const val = n.params[lname];
        const bytes = val && val.points ? curveLut(val.points) : (val instanceof Uint8ClampedArray ? val : curveLut(null));
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, this.lutTexture(bytes));
        if (u(lname)) gl.uniform1i(u(lname), unit);
        unit++;
      }
      gl.activeTexture(gl.TEXTURE0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      outputs.set(n.id, { tex: target.tex, w: W, h: H, target });
      passes.push({ node: n.id, type: n.type });
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    // Everything but the output's target goes back to the pool; the output
    // stays alive until the next run, when it is reclaimed.
    const out = outputs.get(graph.output);
    if (this.lastOut) this.pool.put(this.lastOut);
    for (const [id, o] of outputs) if (o.target && id !== graph.output) this.pool.put(o.target);
    this.lastOut = out && out.target ? out.target : null;
    for (const t of owned) gl.deleteTexture(t.tex);
    return { tex: out.tex, w: out.w, h: out.h, passes };
  }

  /** Draw a texture to the context's own canvas, upright. */
  present(texInfo, w, h) {
    const gl = this.gl;
    if (!this.blit) {
      const src = desugar(`uniform sampler2D in0;\ntexture2D(in0, uv)`, { es3: isGL2(gl) });
      this.blit = linkProgram(gl, src);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, w, h);
    gl.useProgram(this.blit);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    const loc = gl.getAttribLocation(this.blit, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(gl.getUniformLocation(this.blit, "u_resolution"), w, h);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texInfo.tex);
    gl.uniform1i(gl.getUniformLocation(this.blit, "in0"), 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  /**
   * Every pass, in order, as { node, type, header, glsl } — what "show me the
   * shader" means for a graph. `ejectText` joins them for reading.
   */
  eject(graph) {
    const order = topo(graph);
    const parts = [];
    for (const n of order) {
      if (n.type === "source") {
        parts.push({ node: n.id, type: "source", header: `// ---- ${n.id}: source (a texture the host supplies)`, glsl: "" });
        continue;
      }
      const t = nodeType(n.type);
      const params = Object.entries(n.params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
      parts.push({
        node: n.id, type: n.type,
        header: `// ================================================================\n` +
                `// pass: ${n.id}  type: ${n.type}${t.pass ? "  (its own pass — reads a neighbourhood)" : ""}\n` +
                `// inputs: ${n.inputs.join(", ") || "—"}\n// params: ${params || "defaults"}\n` +
                `// ================================================================`,
        glsl: this.sourceFor(n.type),
      });
    }
    return parts;
  }
  ejectText(graph) {
    return this.eject(graph).map((p) => (p.glsl ? `${p.header}\n${p.glsl}` : p.header)).join("\n\n");
  }

  release() {
    const gl = this.gl;
    for (const { prog } of this.programs.values()) gl.deleteProgram(prog);
    for (const t of this.luts.values()) gl.deleteTexture(t);
    if (this.lastOut) { gl.deleteTexture(this.lastOut.tex); gl.deleteFramebuffer(this.lastOut.fbo); }
    this.pool.release();
    if (this.blit) gl.deleteProgram(this.blit);
    gl.deleteBuffer(this.quad);
    gl.deleteTexture(this.blank);
  }
}

// ------------------------------------------------------------------ convenience

let shared = null;
function sharedRunner() {
  if (shared) return shared;
  const canvas = document.createElement("canvas");
  const gl = getGL(canvas);
  if (!gl) throw new Error("WebGL is not available");
  shared = { canvas, gl, runner: new GraphRunner(gl) };
  return shared;
}

/**
 * Run a graph on the shared context and return a 2D canvas of the output.
 * `sources` as for GraphRunner.run.
 */
export function renderGraph(graph, sources, opts = {}) {
  const s = sharedRunner();
  const { canvas, gl, runner } = s;
  if (canvas.width !== graph.width || canvas.height !== graph.height) {
    canvas.width = graph.width; canvas.height = graph.height;
  }
  const out = runner.run(graph, sources, opts);
  runner.present(out, graph.width, graph.height);
  const c = document.createElement("canvas");
  c.width = graph.width; c.height = graph.height;
  c.getContext("2d").drawImage(canvas, 0, 0);
  return c;
}

/** The ejected GLSL for a graph, on the shared context: text, or parts. */
export function ejectGraph(graph, { parts = false } = {}) {
  const r = sharedRunner().runner;
  return parts ? r.eject(graph) : r.ejectText(graph);
}

/**
 * Apply one node type to a canvas — the shortest path from "a filter" to
 * "a graph". Used by the Canvas filter dialog until layers become subgraphs.
 */
export function applyNode(canvasIn, typeId, params = {}) {
  const w = canvasIn.width, h = canvasIn.height;
  const graph = { width: w, height: h, nodes: [], output: null };
  const src = { id: "src", type: "source", params: {}, inputs: [], bypass: false };
  graph.nodes.push(src);
  let last = "src";
  if (typeId === "filter.blur") {
    const r = Array.isArray(params.radius) ? params.radius[0] : (params.radius ?? 4);
    graph.nodes.push({ id: "bh", type: "filter.blur1d", params: { radius: [r], dir: [1, 0] }, inputs: ["src"], bypass: false });
    graph.nodes.push({ id: "bv", type: "filter.blur1d", params: { radius: [r], dir: [0, 1] }, inputs: ["bh"], bypass: false });
    last = "bv";
  } else {
    graph.nodes.push({ id: "n", type: typeId, params, inputs: ["src"], bypass: false });
    last = "n";
  }
  graph.output = last;
  return renderGraph(graph, { src: canvasIn });
}
