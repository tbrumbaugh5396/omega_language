// The render graph on WebGPU.
//
// `graph-compile.js` is the GL runner: a pool of targets, a program per node
// type, runs of per-pixel nodes fused into one draw, and feedback kept between
// frames. This is the same graph, through the same planner, onto the second
// backend — and *the same planner* is the point. Nothing here decides what to
// draw. `resolveParams`, `compileFields` and `planPasses` are imported, not
// reimplemented, so a difference between the two backends can only be a
// difference in how a pass is executed, never in which passes there are.
//
// What is genuinely different, and worth the file:
//
//   - **One submission.** GL issues each draw as it is encoded. Here every
//     pass in a frame goes into one command encoder and is submitted once.
//   - **Explicit bind group layouts.** `layout: "auto"` leaves a binding the
//     shader never reads out of the layout, so a graph that binds it is
//     invalid — and it cannot express a 32-bit target, which is unfilterable
//     and which a simulation's register needs. The layouts are built here from
//     what the emitter declared, which fixes both.
//   - **Formats rather than extensions.** `rgba16float` is renderable and
//     filterable in core WebGPU; the GL path negotiates for the same thing
//     through two extensions and a fallback.
//
// The output is handed back as a texture. `readback()` runs the same
// premultiply-and-flatten that `present()` does on the GL side, so what comes
// out is comparable to what comes out of there, byte for byte.

import { toWgsl } from "./wgsl-emit.js";
import { gpu } from "./webgpu-run.js";
import { NODE_TYPES, nodeType, topo, validate, curveLut, resolveBypass, isBack, fedBack } from "./render-graph.js";
import { planPasses } from "./graph-fuse.js";
import { compileFields } from "./field-graph.js";
import { resolveParams, resetParamState, hasDynamicParams } from "./param-graph.js";
import { cachedImage } from "./shader-run.js";

/** Working precision, and the one a register asks for. */
const HALF = "rgba16float";
const FLOAT = "rgba32float";
/** What a readback flattens to, which is what a canvas is. */
const BYTE = "rgba8unorm";

const USAGE = GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.TEXTURE_BINDING
            | GPUTextureUsage.COPY_SRC | GPUTextureUsage.COPY_DST;

// ------------------------------------------------------------------ targets

/** A pool of textures, kept by size and format. */
class TexturePool {
  static CAP = 8;
  constructor(device) {
    this.device = device;
    this.free = [];
    this.made = 0;
    this.evicted = 0;
  }
  make(w, h, format = HALF) {
    this.made++;
    const texture = this.device.createTexture({ size: [w, h], format, usage: USAGE });
    return { texture, view: texture.createView(), w, h, format };
  }
  get(w, h, format = HALF) {
    const i = this.free.findIndex((t) => t.w === w && t.h === h && t.format === format);
    if (i >= 0) return this.free.splice(i, 1)[0];
    return this.make(w, h, format);
  }
  put(t) {
    if (!t) return;
    if (this.free.length >= TexturePool.CAP) { t.texture.destroy(); this.evicted++; return; }
    this.free.push(t);
  }
  release() {
    for (const t of this.free) t.texture.destroy();
    this.free = [];
  }
}

// ------------------------------------------------------------------ runner

export class GpuGraphRunner {
  constructor(device) {
    this.device = device;
    this.pool = new TexturePool(device);
    this.pipelines = new Map();     // wgsl + sampler signature → compiled pass
    this.emitted = new Map();       // sketch text → what the emitter said about it
    this.buffers = [];              // uniform buffers, reused between frames
    this.inUse = [];                // …the ones this frame has already claimed
    this.luts = new Map();
    this.own = new Map();
    this.memory = new Map();
    this.frames = new Map();
    this.lastTime = new Map();
    this.uploads = new Map();       // a caller's canvas → its texture, by identity
    this.refused = new Map();       // node type → why it has no WebGPU pass
    this.linear = device.createSampler({ magFilter: "linear", minFilter: "linear",
                                         addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" });
    this.nearest = device.createSampler({ magFilter: "nearest", minFilter: "nearest",
                                          addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" });
    this.blank = this.pool.make(1, 1, BYTE);
    device.queue.writeTexture({ texture: this.blank.texture }, new Uint8Array([0, 0, 0, 0]),
                              { bytesPerRow: 4 }, [1, 1]);
  }

  // ---------------------------------------------------------- compilation

  /** What the emitter says about a sketch, once. */
  emit(sketch) {
    let e = this.emitted.get(sketch);
    if (!e) { e = toWgsl(sketch); this.emitted.set(sketch, e); }
    return e;
  }

  /**
   * A pipeline for this module against these sampler kinds.
   *
   * The kinds are part of the key because they are part of the layout: a
   * 32-bit target is `unfilterable-float` and needs a non-filtering sampler,
   * and a pipeline built for a filterable one will not take it. In practice a
   * node's inputs have the same kind every frame, so this is one entry each.
   */
  pipelineFor(wgsl, samplerNames, kinds, targetFormat = HALF) {
    // The target's format is part of the key because it is part of the
    // pipeline: a module whose fragment target says rgba16float cannot draw
    // into the 32-bit texture a register keeps its state in, and WebGPU
    // refuses that at draw time rather than at creation.
    const key = `${targetFormat} ${kinds.join(",")} ${wgsl}`;
    const hit = this.pipelines.get(key);
    if (hit) { this.pipelines.delete(key); this.pipelines.set(key, hit); return hit; }
    if (this.pipelines.size >= 48) this.pipelines.delete(this.pipelines.keys().next().value);
    const device = this.device;
    const entries = [{ binding: 0, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "uniform" } }];
    let b = 1;
    samplerNames.forEach((_, i) => {
      const unfiltered = kinds[i] === "unfilterable-float";
      entries.push({ binding: b++, visibility: GPUShaderStage.FRAGMENT,
                     texture: { sampleType: unfiltered ? "unfilterable-float" : "float" } });
      entries.push({ binding: b++, visibility: GPUShaderStage.FRAGMENT,
                     sampler: { type: unfiltered ? "non-filtering" : "filtering" } });
    });
    const layout = device.createBindGroupLayout({ entries });
    const module = device.createShaderModule({ code: wgsl });
    const pipeline = device.createRenderPipeline({
      layout: device.createPipelineLayout({ bindGroupLayouts: [layout] }),
      vertex: { module, entryPoint: "vs" },
      fragment: { module, entryPoint: "fs", targets: [{ format: targetFormat }] },
      primitive: { topology: "triangle-list" },
    });
    const made = { pipeline, layout, module };
    this.pipelines.set(key, made);
    return made;
  }

  // ---------------------------------------------------------- resources

  /** A uniform buffer for one pass. Reused across frames, not within one. */
  uniformBuffer() {
    const b = this.buffers.pop()
      || this.device.createBuffer({ size: (12 + 32 * 4) * 4,
                                    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    this.inUse.push(b);
    return b;
  }

  /** A caller's canvas as a texture, uploaded the way the GL path uploads. */
  upload(src, flipY = true) {
    const w = src.width || src.naturalWidth || 1, h = src.height || src.naturalHeight || 1;
    let t = this.uploads.get(src);
    if (!t || t.w !== w || t.h !== h) {
      if (t) t.texture.destroy();
      t = this.pool.make(w, h, BYTE);
      this.uploads.set(src, t);
    }
    this.device.queue.copyExternalImageToTexture({ source: src, flipY }, { texture: t.texture }, [w, h]);
    return t;
  }

  /** A 256×1 lookup texture, cached by content. */
  lutTexture(bytes) {
    const key = Array.from(bytes.subarray(0, 64)).join(",") + "|" + bytes.length;
    let t = this.luts.get(key);
    if (t) return t;
    t = this.pool.make(bytes.length / 4, 1, BYTE);
    this.device.queue.writeTexture({ texture: t.texture },
      new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.length),
      { bytesPerRow: bytes.length }, [bytes.length / 4, 1]);
    if (this.luts.size > 32) {
      const [k, v] = this.luts.entries().next().value;
      v.texture.destroy(); this.luts.delete(k);
    }
    this.luts.set(key, t);
    return t;
  }

  /** A sampler the node carries in its own source — `@data`. Blank until decoded. */
  ownTexture(src) {
    const im = cachedImage(src);
    let t = this.own.get(src);
    if (t && (t.filled || !im)) return t.tex;
    if (!t) { t = { tex: this.blank, filled: false }; this.own.set(src, t); }
    if (im) { t.tex = this.upload(im); t.filled = true; }
    return t.tex;
  }

  // ---------------------------------------------------------- memory

  static MEMORY_CAP = 32;

  memoryKey(graph, node) {
    return `${graph.stateKey || "anonymous"}\u0000${node.name || node.id}`;
  }

  /**
   * The pair of textures a fed-back node persists in — one to read while the
   * other is written. `@precision float` in the header asks for 32 bits: half
   * float is fine for a picture and wrong for a register, which is the same
   * judgement the GL runner makes and for the same measured reason.
   */
  memoryFor(graph, node, W, H) {
    const key = this.memoryKey(graph, node);
    const t = node.type ? nodeType(node.type) : null;
    const format = t && t.precision === "float" ? FLOAT : HALF;
    let m = this.memory.get(key);
    if (m && (m.w !== W || m.h !== H || m.format !== format)) {
      m.read.texture.destroy(); m.write.texture.destroy();
      this.memory.delete(key); m = null;
    }
    if (m) { this.memory.delete(key); this.memory.set(key, m); return m; }
    if (this.memory.size >= GpuGraphRunner.MEMORY_CAP) {
      const [oldest, old] = this.memory.entries().next().value;
      old.read.texture.destroy(); old.write.texture.destroy();
      this.memory.delete(oldest);
    }
    // Cleared, so "nothing yet" reads as nothing rather than as whatever the
    // allocator had. A render pass that loads "clear" and stores is the
    // cheapest way to say that.
    const make = () => {
      const t2 = this.pool.make(W, H, format);
      const enc = this.device.createCommandEncoder();
      enc.beginRenderPass({ colorAttachments: [{ view: t2.view, clearValue: { r: 0, g: 0, b: 0, a: 0 },
                                                 loadOp: "clear", storeOp: "store" }] }).end();
      this.device.queue.submit([enc.finish()]);
      return t2;
    };
    m = { read: make(), write: make(), w: W, h: H, format };
    this.memory.set(key, m);
    return m;
  }

  resetState(stateKey = "anonymous") {
    resetParamState(stateKey);
    this.lastTime.delete(stateKey);
    const prefix = `${stateKey}\u0000`;
    for (const [k, m] of [...this.memory]) {
      if (k.startsWith(prefix)) { m.read.texture.destroy(); m.write.texture.destroy(); this.memory.delete(k); }
    }
    this.frames.delete(stateKey);
  }

  // ---------------------------------------------------------- the run

  /**
   * Run the graph. Same signature as the GL runner's `run`, same return —
   * `{ tex, w, h, passes, frame, fired }` — except that `tex` is a WebGPU
   * texture record and the whole frame is one submission.
   *
   * A node type the translator refuses has no pass here. Rather than draw
   * something else and call it the same picture, the run throws and names it:
   * a second backend that quietly disagrees is worse than one that stops.
   */
  run(graph, sources = {}, opts = {}) {
    const device = this.device;
    const errs = validate(graph);
    if (errs.length) throw new Error(errs.join("; "));
    const stateKey = graph.stateKey || "anonymous";
    if (opts.reset) this.resetState(stateKey);

    const written = graph;
    const remembered = fedBack(graph);
    let frame = opts.frame ?? (this.frames.get(stateKey) || 0);
    const keysObj = opts.keys && opts.keys.down ? opts.keys : null;
    const dynamic = hasDynamicParams(written);
    let pending = [];
    if (opts.events && dynamic) {
      pending = Array.isArray(opts.events) ? opts.events.slice()
        : typeof opts.events.drain === "function" ? opts.events.drain() : [];
    }
    const now = opts.time || 0;
    const lastT = this.lastTime.get(stateKey);
    const dt = lastT === undefined ? 0 : Math.max(0, now - lastT);
    const fired = [];
    const plan = (frameNo) => {
      if (dynamic && pending.length) {
        for (const ev of pending) {
          const r = resolveParams(written, { t: now, frame: frameNo, seed: opts.seed || 0,
                                             keys: keysObj, event: ev, eventPass: true, commit: true });
          if (r.fired) fired.push(...r.fired);
        }
        pending = [];
      }
      let g = resolveParams(written, { t: now, frame: frameNo, seed: opts.seed || 0, keys: keysObj,
                                       event: { kind: "frame", frame: frameNo, t: now, dt }, commit: true });
      if (g.fired) fired.push(...g.fired);
      g = compileFields(g);
      return { graph: g, steps: opts.fuse === false
        ? topo(g).map((node) => ({ kind: "node", node })) : planPasses(g) };
    };
    let planned = plan(frame);
    graph = planned.graph;
    let steps = planned.steps;
    const W = graph.width, H = graph.height;

    const outputs = new Map();
    const passes = [];
    const keysCanvas = opts.keys ? (opts.keys.texture ? opts.keys.texture() : opts.keys) : null;
    // Not flipped, exactly as the GL path uploads it: row 0 is "held".
    const keysTex = keysCanvas && keysCanvas.width ? this.upload(keysCanvas, false) : this.blank;

    const mems = new Map();
    const memOf = (id) => {
      let m = mems.get(id);
      if (!m) { m = this.memoryFor(graph, resolveBypass(graph, id) || { id }, W, H); mems.set(id, m); }
      return m;
    };
    const texOf = (id, back = false) => (back ? memOf(id).read
                                              : outputs.get(id) || this.blank);
    const targetFor = (id) => (remembered.has(id) ? memOf(id).write : this.pool.get(W, H));
    const lutBytes = (val) => (val && val.points ? curveLut(val.points)
      : (val instanceof Uint8ClampedArray ? val : curveLut(null)));

    let enc = device.createCommandEncoder();

    /**
     * One draw. `sketch` is the text, `find` answers what to bind for a named
     * sampler, and `values` are the scalars by name — which is all a plain
     * node and a fused run have in common, and all this needs to know.
     */
    const draw = (sketch, find, values, target, label) => {
      const em = this.emit(sketch);
      if (!em.ok) throw new Error(`${label}: ${em.refused[0]}`);
      const bound = em.samplers.map(find);
      if (em.usesKeys) bound.push(keysTex);
      const names = em.samplers.slice();
      if (em.usesKeys) names.push("KEYS");
      const kinds = bound.map((t) => (t.format === FLOAT ? "unfilterable-float" : "float"));
      const { pipeline, layout } = this.pipelineFor(em.wgsl, names, kinds, target.format);

      const buf = new Float32Array(12 + 32 * 4);
      const iview = new Int32Array(buf.buffer);
      buf[0] = W; buf[1] = H;
      buf[2] = (opts.mouse || [W / 2, H / 2])[0];
      buf[3] = (opts.mouse || [W / 2, H / 2])[1];
      buf[4] = opts.time || 0;
      buf[5] = opts.seed || 0;
      buf[6] = opts.mouseDown ? 1 : 0;
      iview[7] = frame | 0;
      buf[8] = 0; buf[9] = 0;
      em.uniforms.forEach((u, i) => {
        const v = values[u.name];
        const arr = Array.isArray(v) ? v : (v !== undefined && v !== null ? [v] : u.value);
        for (let k = 0; k < 4; k++) buf[12 + i * 4 + k] = Number.isFinite(arr[k]) ? arr[k] : 0;
      });
      const ubo = this.uniformBuffer();
      device.queue.writeBuffer(ubo, 0, buf);

      const entries = [{ binding: 0, resource: { buffer: ubo } }];
      let b = 1;
      for (const t of bound) {
        entries.push({ binding: b++, resource: t.view });
        entries.push({ binding: b++, resource: t.format === FLOAT ? this.nearest : this.linear });
      }
      const group = device.createBindGroup({ layout, entries });
      const pass = enc.beginRenderPass({
        colorAttachments: [{ view: target.view, clearValue: { r: 0, g: 0, b: 0, a: 0 },
                             loadOp: "clear", storeOp: "store" }],
      });
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, group);
      pass.draw(3);
      pass.end();
    };

    const drawNode = (n) => {
      if (n.type === "source") {
        const s = sources[n.id];
        if (!s) throw new Error(`no source supplied for ${n.id}`);
        outputs.set(n.id, s.texture ? s : this.upload(s));
        return;
      }
      if (n.bypass) {
        const from = resolveBypass(graph, n.id);
        outputs.set(n.id, outputs.get(from ? from.id : n.inputs[0]) || this.blank);
        return;
      }
      const type = nodeType(n.type);
      const values = {};
      for (const p of type.params) {
        if (p.control === "image") continue;
        const v = n.params[p.name];
        values[p.name] = Array.isArray(v) ? v : (v !== undefined && v !== null ? [v] : p.value.slice());
      }
      const inputAt = new Map();
      type.inputs.forEach((name, i) => inputAt.set(name, i));
      const find = (name) => {
        if (inputAt.has(name)) {
          const i = inputAt.get(name);
          return texOf(n.inputs[i], isBack(n, i));
        }
        if (type.luts.includes(name)) return this.lutTexture(lutBytes(n.params[name]));
        const own = type.uniforms.find((u) => u.name === name && u.control === "image" && u.src);
        if (own) return this.ownTexture(own.src);
        return this.blank;
      };
      const target = targetFor(n.id);
      draw(type.source, find, values, target, n.type);
      outputs.set(n.id, { ...target, pooled: remembered.has(n.id) ? null : target });
      passes.push({ node: n.id, type: n.type, memory: remembered.has(n.id) || undefined });
    };

    const drawFused = (step) => {
      const byName = new Map(step.samplers.map((s) => [s.name, s]));
      const find = (name) => {
        const s = byName.get(name);
        if (!s) return this.blank;
        return s.lut ? this.lutTexture(lutBytes(s.value)) : texOf(s.from, s.back);
      };
      const target = targetFor(step.id);
      draw(step.sketch, find, step.values, target, `fused ${step.nodes.map((n) => n.type).join("→")}`);
      outputs.set(step.id, { ...target, pooled: remembered.has(step.id) ? null : target });
      passes.push({ node: step.id, type: "fused", fused: step.nodes.map((n) => n.type),
                    memory: remembered.has(step.id) || undefined });
    };

    const steps_ = Math.max(1, opts.steps | 0 || 1);
    let out = null;
    for (let s = 0; s < steps_; s++) {
      if (s > 0 && dynamic) { planned = plan(frame); steps = planned.steps; }
      outputs.clear();
      passes.length = 0;
      for (const step of steps) {
        if (step.kind === "fused") drawFused(step);
        else drawNode(step.node);
      }
      out = outputs.get(graph.output);
      for (const m of mems.values()) { const r = m.read; m.read = m.write; m.write = r; }
      frame++;
      if (s < steps_ - 1) {
        for (const [, o] of outputs) if (o.pooled) this.pool.put(o.pooled);
      }
    }

    // The whole frame, in one submission. This is the difference the second
    // backend actually buys: GL has already issued every draw by now.
    device.queue.submit([enc.finish()]);
    this.buffers.push(...this.inUse.splice(0));

    if (remembered.size || dynamic) { this.frames.set(stateKey, frame); this.lastTime.set(stateKey, now); }
    if (this.lastOut) this.pool.put(this.lastOut);
    for (const [id, o] of outputs) if (o.pooled && id !== graph.output) this.pool.put(o.pooled);
    this.lastOut = out && out.pooled ? out.pooled : null;
    return { tex: out, w: W, h: H, passes, frame, fired };
  }

  /**
   * The output as bytes, premultiplied and flipped the way the GL path's
   * `present()` leaves them — so what comes out of here is comparable to what
   * comes out of there without anybody having to remember a convention.
   */
  async readback(tex, w, h) {
    const device = this.device;
    if (!this.flatten) {
      this.flatten = this.emit(
        "uniform sampler2D in0;\n// @alpha\nvec4 c = texture2D(in0, uv);\nvec4(c.rgb * c.a, c.a)");
      if (!this.flatten.ok) throw new Error(`the flatten pass will not translate: ${this.flatten.refused[0]}`);
    }
    const em = this.flatten;
    const kinds = [tex.format === FLOAT ? "unfilterable-float" : "float"];
    // Its own pipeline: this one ends in bytes, where every graph pass ends in
    // half float.
    const key = `flatten ${kinds[0]}`;
    let p = this.pipelines.get(key);
    if (!p) {
      const layout = device.createBindGroupLayout({ entries: [
        { binding: 0, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "uniform" } },
        { binding: 1, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: kinds[0] } },
        { binding: 2, visibility: GPUShaderStage.FRAGMENT,
          sampler: { type: kinds[0] === "unfilterable-float" ? "non-filtering" : "filtering" } },
      ] });
      const module = device.createShaderModule({ code: em.wgsl });
      p = { layout, pipeline: device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [layout] }),
        vertex: { module, entryPoint: "vs" },
        fragment: { module, entryPoint: "fs", targets: [{ format: BYTE }] },
        primitive: { topology: "triangle-list" },
      }) };
      this.pipelines.set(key, p);
    }
    const flat = this.pool.make(w, h, BYTE);
    const buf = new Float32Array(12 + 32 * 4);
    buf[0] = w; buf[1] = h;
    const ubo = device.createBuffer({ size: buf.byteLength,
                                      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(ubo, 0, buf);
    const group = device.createBindGroup({ layout: p.layout, entries: [
      { binding: 0, resource: { buffer: ubo } },
      { binding: 1, resource: tex.view },
      { binding: 2, resource: tex.format === FLOAT ? this.nearest : this.linear },
    ] });
    const enc = device.createCommandEncoder();
    const pass = enc.beginRenderPass({ colorAttachments: [
      { view: flat.view, clearValue: { r: 0, g: 0, b: 0, a: 0 }, loadOp: "clear", storeOp: "store" }] });
    pass.setPipeline(p.pipeline);
    pass.setBindGroup(0, group);
    pass.draw(3);
    pass.end();
    const bpr = Math.ceil(w * 4 / 256) * 256;
    const read = device.createBuffer({ size: bpr * h,
                                       usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
    enc.copyTextureToBuffer({ texture: flat.texture }, { buffer: read, bytesPerRow: bpr, rowsPerImage: h },
                            [w, h]);
    device.queue.submit([enc.finish()]);
    await read.mapAsync(GPUMapMode.READ);
    const padded = new Uint8Array(read.getMappedRange());
    const data = new Uint8ClampedArray(w * h * 4);
    // Bottom row first, as in GL; a caller wants it the way getImageData does.
    for (let y = 0; y < h; y++) {
      data.set(padded.subarray(y * bpr, y * bpr + w * 4), (h - 1 - y) * w * 4);
    }
    read.unmap(); read.destroy(); ubo.destroy(); flat.texture.destroy();
    return data;
  }

  /** The output as a canvas, for looking at rather than measuring. */
  async toCanvas(tex, w, h) {
    const data = await this.readback(tex, w, h);
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    c.getContext("2d").putImageData(new ImageData(data, w, h), 0, 0);
    return c;
  }

  /** Which node types this backend has no pass for, and why. */
  static refusals() {
    const out = [];
    for (const [id, t] of NODE_TYPES) {
      const em = toWgsl(t.source);
      if (!em.ok) out.push({ id, why: em.refused[0] });
    }
    return out;
  }

  stats() {
    return { pipelines: this.pipelines.size, luts: this.luts.size, ownTextures: this.own.size,
             pooled: this.pool.free.length, memories: this.memory.size,
             floatMemories: [...this.memory.values()].filter((m) => m.format === FLOAT).length,
             uniformBuffers: this.buffers.length, targetsMade: this.pool.made,
             targetsEvicted: this.pool.evicted, precision: "half" };
  }

  release() {
    for (const m of this.memory.values()) { m.read.texture.destroy(); m.write.texture.destroy(); }
    for (const t of this.luts.values()) t.texture.destroy();
    for (const t of this.uploads.values()) t.texture.destroy();
    if (this.lastOut) this.lastOut.texture.destroy();
    this.blank.texture.destroy();
    for (const b of this.buffers) b.destroy();
    this.pool.release();
    this.memory.clear(); this.luts.clear(); this.uploads.clear(); this.pipelines.clear();
  }
}

// ------------------------------------------------------------------ shared

let shared = null;

/**
 * A runner on the shared device, or null where there is no WebGPU. Null is an
 * answer, not a failure: this is a second backend and every caller carries on
 * without it.
 */
export async function gpuGraphRunner() {
  if (shared !== null) return shared;
  const g = await gpu();
  shared = g ? new GpuGraphRunner(g.device) : false;
  return shared || null;
}

/** One graph, one frame, as bytes — the shape the self-test wants. */
export async function renderGraphGpu(graph, sources = {}, opts = {}) {
  const runner = await gpuGraphRunner();
  if (!runner) return null;
  const out = runner.run(graph, sources, opts);
  return { ...out, data: await runner.readback(out.tex, out.w, out.h) };
}
