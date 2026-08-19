// The graph compiler: a render graph → passes → pixels.
//
// A node's sketch is compiled once per type (through desugar, like any
// sketch), drawn into a framebuffer from a small pool with its inputs bound as
// textures, and the framebuffer becomes the input of whatever reads it.
// Sources are textures the host hands in. The output node's framebuffer is
// what you get back.
//
// Not one pass per node, though: graph-fuse.js first collapses runs of
// consecutive per-pixel nodes into a single sketch, so a stack of adjustments
// is one draw with no buffers between. If a fused program will not compile,
// the run falls back to a pass per node and says so — fusion may make the
// picture faster, never different.

import { desugar, isEs3, withDefine, parseUniforms } from "./shader-uniforms.js";
import { applyUniforms } from "./shader-controls.js";
import { getGL, isGL2, linkProgram, cachedImage, loadSketchImages } from "./shader-run.js";
import { nodeType, topo, validate, curveLut, resolveBypass } from "./render-graph.js";
import { planPasses } from "./graph-fuse.js";
import { compileFields } from "./field-graph.js";
import { resolveParams } from "./param-graph.js";

// ------------------------------------------------------------------ targets

/** A pool of framebuffers, one size, negotiated to the best precision. */
class TargetPool {
  static CAP = 8;
  constructor(gl) {
    this.gl = gl;
    this.evicted = 0;
    this.made = 0;
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
      // Clear anything an earlier call left behind: getError() reports the
      // oldest error still pending, so without this a failure somewhere else
      // is read as this allocation failing, and a perfectly good target is
      // thrown away.
      while (gl.getError() !== gl.NO_ERROR) { /* drain */ }
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
      if (t) { this.kind = k; this.made++; return t; }
    }
    throw new Error("could not allocate a render target");
  }
  get(w, h) {
    const i = this.free.findIndex((t) => t.w === w && t.h === h);
    if (i >= 0) return this.free.splice(i, 1)[0];
    return this.make(w, h);
  }
  /**
   * Back to the pool, up to a point. A graph that widens and narrows can hand
   * back more targets than it will ever want again, and at 4K each one is 32
   * MB of half float — so past the cap they are released instead of kept.
   */
  put(t) {
    if (!t) return;
    if (this.free.length >= TargetPool.CAP) {
      this.gl.deleteTexture(t.tex);
      this.gl.deleteFramebuffer(t.fbo);
      this.evicted++;
      return;
    }
    this.free.push(t);
  }
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
    this.fused = new Map();         // fused sketch → { prog, uniforms } or { error }
    this.own = new Map();           // @data url → texture the node carries itself
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

  /**
   * The program for a fused step, or null with the reason kept — a fused run
   * that will not compile is a bug in fusion, not in the graph, so the runner
   * draws the nodes one at a time instead and the picture is unaffected.
   */
  fusedProgram(step) {
    let e = this.fused.get(step.key);
    if (e) {
      // Touch it, so the one that goes is the one least recently wanted.
      this.fused.delete(step.key);
      this.fused.set(step.key, e);
      return e;
    }
    if (this.fused.size >= 24) {
      const [oldest, old] = this.fused.entries().next().value;
      if (old && old.prog) this.gl.deleteProgram(old.prog);
      this.fused.delete(oldest);
    }
    try {
      e = { prog: linkProgram(this.gl, desugar(step.sketch, { es3: isGL2(this.gl) })),
            uniforms: parseUniforms(step.sketch) };
    } catch (err) {
      e = { prog: null, error: String(err.message).split("\n")[0] };
    }
    this.fused.set(step.key, e);
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

  /**
   * A texture for a sampler the node carries in its own source. Blank until
   * `prepareNode` has decoded it, so a synchronous render never has to wait.
   */
  ownTexture(src) {
    if (this.own.size > 16 && !this.own.has(src)) {
      const [oldest, t] = this.own.entries().next().value;
      this.gl.deleteTexture(t.tex);
      this.own.delete(oldest);
    }
    let tex = this.own.get(src);
    const im = cachedImage(src);
    if (tex && (tex.filled || !im)) return tex.tex;
    const gl = this.gl;
    if (!tex) { tex = { tex: gl.createTexture(), filled: false }; this.own.set(src, tex); }
    if (im) {
      gl.bindTexture(gl.TEXTURE_2D, tex.tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      tex.filled = true;
    } else {
      gl.bindTexture(gl.TEXTURE_2D, tex.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]));
    }
    return tex.tex;
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
    // Two rewrites before anything is planned, in this order. Expressions
    // become numbers first, because a field tree carries its parameters with
    // it and they have to be values by the time it does. Then fields become
    // one generated node type — so everything from here down (fusion,
    // pooling, tiling) sees an ordinary image graph of plain constants.
    graph = resolveParams(graph, { t: opts.time || 0, frame: opts.frame || 0, seed: opts.seed || 0 });
    graph = compileFields(graph);
    const W = graph.width, H = graph.height;
    // Fusion is on unless a caller wants the passes as written — the self-test
    // wants both, to hold one against the other.
    const steps = opts.fuse === false
      ? topo(graph).map((node) => ({ kind: "node", node }))
      : planPasses(graph);
    const outputs = new Map();        // node id → { tex, w, h, target? }
    const owned = [];
    const passes = [];

    // Common set-up for a draw: the full-screen triangle and the reserved
    // uniforms, which mean the same thing in every pass.
    const begin = (prog, target) => {
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
      gl.uniform1f(u("u_seed"), opts.seed || 0);
      gl.uniform1i(u("u_frame"), 0);
      gl.uniform1f(u("u_mouseDown"), 0);
      return u;
    };
    const lutBytes = (val) => (val && val.points ? curveLut(val.points)
      : (val instanceof Uint8ClampedArray ? val : curveLut(null)));
    const texOf = (id) => outputs.get(id) || { tex: this.blank, w: 1, h: 1 };

    const drawNode = (n) => {
      if (n.type === "source") {
        const s = sources[n.id];
        if (!s) throw new Error(`no source supplied for ${n.id}`);
        const t = s.tex ? { tex: s.tex, w: s.w, h: s.h } : this.textureFrom(s);
        if (t.owned) owned.push(t);
        outputs.set(n.id, t);
        return;
      }
      if (n.bypass) {
        const from = resolveBypass(graph, n.id);
        outputs.set(n.id, outputs.get(from ? from.id : n.inputs[0]) || { tex: this.blank, w: 1, h: 1 });
        return;
      }
      const type = nodeType(n.type);
      const { prog } = this.programFor(n.type);
      const target = this.pool.get(W, H);
      const u = begin(prog, target);
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
        const src = texOf(n.inputs[i]);
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, src.tex);
        if (u(name)) gl.uniform1i(u(name), unit);
        if (u(`${name}_size`)) gl.uniform2f(u(`${name}_size`), src.w, src.h);
        unit++;
      });
      for (const lname of type.luts) {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, this.lutTexture(lutBytes(n.params[lname])));
        if (u(lname)) gl.uniform1i(u(lname), unit);
        unit++;
      }
      // A sampler the node carries itself — `@data`, a glyph atlas in the
      // source. Nothing outside the node knows about it, so nothing outside
      // has to be asked; it just has to have been decoded first.
      for (const own of type.uniforms) {
        if (own.control !== "image" || !own.src) continue;
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, this.ownTexture(own.src));
        if (u(own.name)) gl.uniform1i(u(own.name), unit);
        if (u(`${own.name}_size`)) {
          const im = cachedImage(own.src);
          gl.uniform2f(u(`${own.name}_size`), im ? (im.width || im.naturalWidth || 0) : 0,
                                              im ? (im.height || im.naturalHeight || 0) : 0);
        }
        unit++;
      }
      gl.activeTexture(gl.TEXTURE0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      outputs.set(n.id, { tex: target.tex, w: W, h: H, target });
      passes.push({ node: n.id, type: n.type });
    };

    const drawFused = (step) => {
      const { prog, uniforms, error } = this.fusedProgram(step);
      if (!prog) {                       // the safety net: draw them one by one
        if (!this.warned) { this.warned = new Set(); }
        if (!this.warned.has(step.key)) {
          this.warned.add(step.key);
          console.warn(`fusion fell back to one pass per node: ${error}`);
        }
        for (const n of step.nodes) drawNode(n);
        return;
      }
      const target = this.pool.get(W, H);
      const u = begin(prog, target);
      applyUniforms(gl, prog, uniforms, step.values);
      let unit = 0;
      for (const s of step.samplers) {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, s.lut ? this.lutTexture(lutBytes(s.value)) : texOf(s.from).tex);
        if (u(s.name)) gl.uniform1i(u(s.name), unit);
        unit++;
      }
      for (const s of step.sizes) {
        if (!u(s.name)) continue;
        const src = s.from ? texOf(s.from) : null;
        gl.uniform2f(u(s.name), src ? src.w : W, src ? src.h : H);
      }
      gl.activeTexture(gl.TEXTURE0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      outputs.set(step.id, { tex: target.tex, w: W, h: H, target });
      passes.push({ node: step.id, type: "fused", fused: step.nodes.map((n) => n.type) });
    };

    for (const step of steps) {
      if (step.kind === "fused") drawFused(step);
      else drawNode(step.node);
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

  /** What this runner is holding, for anything that wants to say so. */
  stats() {
    return { programs: this.programs.size, fused: this.fused.size, luts: this.luts.size,
             ownTextures: this.own.size, pooled: this.pool.free.length,
             targetsMade: this.pool.made, targetsEvicted: this.pool.evicted,
             precision: this.pool.kind };
  }

  /**
   * Draw a texture to the context's own canvas, upright. The canvas is
   * premultiplied — that is what the browser assumes when it reads one back —
   * and the graph carries straight alpha, so the multiplication happens here,
   * at the one place the two conventions meet.
   */
  present(texInfo, w, h) {
    const gl = this.gl;
    if (!this.blit) {
      const src = desugar(`uniform sampler2D in0;\nvec4 c = texture2D(in0, uv);\nvec4(c.rgb * c.a, c.a)`,
                          { es3: isGL2(gl), alpha: true });
      this.blit = linkProgram(gl, src);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
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
   * shader" means for a graph. Fused runs eject as the one shader that
   * actually runs, which is the point of fusing: what you read is what the GPU
   * was given. `{fuse:false}` ejects the graph as written instead.
   */
  eject(graph, opts = {}) {
    const { fuse = true } = opts;
    const es3 = isGL2(this.gl);
    const rule = "// ================================================================";
    graph = compileFields(resolveParams(graph, opts.at || {}));
    const steps = fuse ? planPasses(graph) : topo(graph).map((node) => ({ kind: "node", node }));
    const parts = [];
    for (const step of steps) {
      if (step.kind === "fused") {
        const names = step.nodes.map((n) => `${n.id} (${n.type})`).join(" → ");
        const params = step.nodes.map((n, k) => {
          const ps = Object.entries(n.params).map(([k2, v]) => `${k2}=${JSON.stringify(v)}`).join(", ");
          return `//   f${k} = ${n.id}: ${ps || "defaults"}`;
        }).join("\n");
        parts.push({
          node: step.id, type: "fused", fused: step.nodes.map((n) => n.type),
          header: `${rule}\n// pass: ${step.id}  ${step.nodes.length} nodes fused into one draw\n` +
                  `// ${names}\n${params}\n${rule}`,
          glsl: desugar(step.sketch, { es3 }), sketch: step.sketch,
        });
        continue;
      }
      const n = step.node;
      if (n.type === "source") {
        parts.push({ node: n.id, type: "source", header: `// ---- ${n.id}: source (a texture the host supplies)`, glsl: "" });
        continue;
      }
      const t = nodeType(n.type);
      const params = Object.entries(n.params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
      const written = Object.entries(n.exprs || {}).map(([k, v]) => `//   ${k} = ${v}`).join("\n");
      parts.push({
        node: n.id, type: n.type,
        header: `${rule}\n` +
                `// pass: ${n.id}  type: ${n.type}${step.why ? `  (its own pass — ${step.why})` : ""}\n` +
                `// inputs: ${n.inputs.join(", ") || "—"}\n// params: ${params || "defaults"}\n` +
                (written ? `// written as:\n${written}\n` : "") +
                rule,
        glsl: this.sourceFor(n.type),
      });
    }
    return parts;
  }
  ejectText(graph, opts) {
    return this.eject(graph, opts).map((p) => (p.glsl ? `${p.header}\n${p.glsl}` : p.header)).join("\n\n");
  }

  release() {
    const gl = this.gl;
    for (const { prog } of this.programs.values()) gl.deleteProgram(prog);
    for (const { prog } of this.fused.values()) if (prog) gl.deleteProgram(prog);
    for (const t of this.luts.values()) gl.deleteTexture(t);
    for (const t of this.own.values()) gl.deleteTexture(t.tex);
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
  if (opts.onPasses) opts.onPasses(out.passes);
  runner.present(out, graph.width, graph.height);
  // `into` draws straight into a caller's context: a timeline at 60 fps should
  // not allocate a canvas a frame.
  if (opts.into) {
    opts.into.clearRect(0, 0, opts.into.canvas.width, opts.into.canvas.height);
    opts.into.drawImage(canvas, 0, 0, opts.into.canvas.width, opts.into.canvas.height);
    return null;
  }
  const c = document.createElement("canvas");
  c.width = graph.width; c.height = graph.height;
  c.getContext("2d").drawImage(canvas, 0, 0);
  return c;
}

/**
 * Decode whatever a node type carries in its own source, so the next
 * synchronous render can bind it. Call it once, when the type is registered.
 */
export async function prepareNode(typeId) {
  const t = nodeType(typeId);
  if (!t) return;
  await loadSketchImages(t.source);
}

/** What the shared runner is holding: caches, pool, precision. */
export function graphStats() {
  return sharedRunner().runner.stats();
}

/** The ejected GLSL for a graph, on the shared context: text, or parts. */
export function ejectGraph(graph, { parts = false, fuse = true } = {}) {
  const r = sharedRunner().runner;
  return parts ? r.eject(graph, { fuse }) : r.ejectText(graph, { fuse });
}

/**
 * Apply a catalogue filter (filter-nodes.js) to a canvas: build its graph on a
 * source, run, return a canvas. Used by the Canvas filter dialog until layers
 * become subgraphs, and by the self-test for parity.
 */
export function applyFilter(canvasIn, filter, params = {}) {
  const w = canvasIn.width, h = canvasIn.height;
  const graph = { width: w, height: h, nodes: [], output: null };
  graph.nodes.push({ id: "src", type: "source", params: {}, inputs: [], bypass: false });
  graph.output = filter.build(graph, "src", params);
  return renderGraph(graph, { src: canvasIn }, { seed: params.seed || 0, fuse: params.fuse !== false });
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
