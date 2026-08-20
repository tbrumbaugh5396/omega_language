// Running a sketch on WebGPU.
//
// Small on purpose. Everything the GL runner does about pooling, fusion,
// tiling and feedback stays where it is; this renders one sketch to one
// texture and reads it back, which is exactly enough to hold the two backends
// against each other. A second full compiler earns nothing until the first
// pixel is known to match.
//
// The device is asked for once and kept. A machine without WebGPU gets null
// from `gpu()` and every caller is expected to carry on — this is a second
// backend, not a requirement.

import { toWgsl } from "./wgsl-emit.js";

let devicePromise = null;

/** The device, or null. Asked for once; the answer is remembered either way. */
export function gpu() {
  if (devicePromise) return devicePromise;
  devicePromise = (async () => {
    if (!globalThis.navigator || !navigator.gpu) return null;
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) return null;
      const device = await adapter.requestDevice();
      // A lost device is not an exception anywhere else in this file; it is
      // simply the end of the second backend for this session.
      device.lost.then(() => { devicePromise = Promise.resolve(null); });
      return { device, adapter, info: adapter.info || null };
    } catch { return null; }
  })();
  return devicePromise;
}

/** What the GPU says about itself, for the record. */
export async function gpuDescribe() {
  const g = await gpu();
  if (!g) return { available: false };
  const i = g.info || {};
  return { available: true, vendor: i.vendor || "?", architecture: i.architecture || "?",
           maxTexture: g.adapter.limits.maxTextureDimension2D };
}

const pipelines = new Map();     // wgsl → { pipeline, layout }

/** A pipeline for this module, compiled once. Throws with the shader log. */
async function pipelineFor(device, wgsl, bindCount) {
  const key = wgsl;
  if (pipelines.has(key)) return pipelines.get(key);
  device.pushErrorScope("validation");
  const module = device.createShaderModule({ code: wgsl });
  const info = await module.getCompilationInfo();
  const errors = info.messages.filter((m) => m.type === "error");
  if (errors.length) {
    await device.popErrorScope();
    const first = errors[0];
    throw new Error(`WGSL line ${first.lineNum}: ${first.message}`);
  }
  const pipeline = device.createRenderPipeline({
    layout: "auto",
    vertex: { module, entryPoint: "vs" },
    fragment: { module, entryPoint: "fs", targets: [{ format: "rgba8unorm" }] },
    primitive: { topology: "triangle-list" },
  });
  const err = await device.popErrorScope();
  if (err) throw new Error(err.message);
  const made = { pipeline, module };
  if (pipelines.size > 32) pipelines.delete(pipelines.keys().next().value);
  pipelines.set(key, made);
  return made;
}

/** A texture from a canvas or image, oriented the way the GL path uploads. */
function uploadTexture(device, src, flipY = true) {
  const w = src.width || src.naturalWidth || 1, h = src.height || src.naturalHeight || 1;
  const tex = device.createTexture({
    size: [w, h], format: "rgba8unorm",
    usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
  });
  // flipY, because the GL path uploads with UNPACK_FLIP_Y_WEBGL — the two
  // backends have to agree about which way up a texture is.
  device.queue.copyExternalImageToTexture({ source: src, flipY }, { texture: tex }, [w, h]);
  return tex;
}

/**
 * Render a sketch and hand back its pixels.
 *
 *   const out = await renderSketchGpu(sketch, 160, 100, { values, images });
 *
 * Returns { data: Uint8ClampedArray, wgsl, refused } — or throws with the
 * WGSL compiler's own message, which is the useful one.
 */
export async function renderSketchGpu(sketch, width, height, opts = {}) {
  const g = await gpu();
  if (!g) throw new Error("this machine has no WebGPU");
  const { device } = g;
  // The sketch says whether it reads the keyboard; the caller only says
  // whether it has one to offer. Binding one that the module never reads is
  // not harmless — `layout: "auto"` leaves a statically-unused binding out of
  // the layout, and an entry for it makes the whole bind group invalid.
  const emitted = toWgsl(sketch);
  const keys = emitted.usesKeys;
  if (!emitted.ok) throw new Error(`not translated: ${emitted.refused[0]}`);

  const { pipeline } = await pipelineFor(device, emitted.wgsl);

  // The uniform block. `array<vec4f, N>` aligns to 16, so the reserved header
  // occupies 48 bytes whatever it contains and the array starts there — a
  // buffer any smaller is refused, and a refusal here is silent unless
  // somebody is listening, which is what the error scope below is for.
  const buf = new Float32Array(12 + 32 * 4);
  const iview = new Int32Array(buf.buffer);
  buf[0] = width; buf[1] = height;
  buf[2] = (opts.mouse || [width / 2, height / 2])[0];
  buf[3] = (opts.mouse || [width / 2, height / 2])[1];
  buf[4] = opts.time || 0;
  buf[5] = opts.seed || 0;
  buf[6] = opts.mouseDown ? 1 : 0;
  iview[7] = opts.frame | 0;
  buf[8] = (opts.origin || [0, 0])[0]; buf[9] = (opts.origin || [0, 0])[1];
  const values = opts.values || {};
  emitted.uniforms.forEach((u, i) => {
    const v = values[u.name] || u.value || [0];
    const at = 12 + i * 4;
    for (let k = 0; k < 4; k++) buf[at + k] = Number.isFinite(v[k]) ? v[k] : 0;
  });
  const ubo = device.createBuffer({ size: buf.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(ubo, 0, buf);

  // Bindings, in the order the emitter declared them.
  const owned = [];
  const entries = [{ binding: 0, resource: { buffer: ubo } }];
  let binding = 1;
  const blank = () => {
    const t = device.createTexture({ size: [1, 1], format: "rgba8unorm",
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST });
    device.queue.writeTexture({ texture: t }, new Uint8Array([0, 0, 0, 0]), { bytesPerRow: 4 }, [1, 1]);
    return t;
  };
  const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear",
                                         addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" });
  const nearest = device.createSampler({ magFilter: "nearest", minFilter: "nearest",
                                         addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" });
  for (const name of emitted.samplers) {
    const src = (opts.images || {})[name];
    const tex = src ? uploadTexture(device, src) : blank();
    owned.push(tex);
    entries.push({ binding: binding++, resource: tex.createView() });
    entries.push({ binding: binding++, resource: sampler });
  }
  if (keys) {
    const src = opts.keys && opts.keys.texture ? opts.keys.texture() : opts.keys;
    // Not flipped: the GL path uploads its images with UNPACK_FLIP_Y_WEBGL
    // and the keyboard without it, so row 0 is "held" at both ends.
    const tex = src && src.width ? uploadTexture(device, src, false) : blank();
    owned.push(tex);
    entries.push({ binding: binding++, resource: tex.createView() });
    entries.push({ binding: binding++, resource: nearest });
  }

  const target = device.createTexture({
    size: [width, height], format: "rgba8unorm",
    usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
  });
  const group = device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries });

  // Everything from here is validated. WebGPU reports a bad bind group by
  // dropping the draw and saying nothing, which reads exactly like a shader
  // that decided to output the clear colour — an hour of looking at the wrong
  // thing, once.
  device.pushErrorScope("validation");
  const enc = device.createCommandEncoder();
  const pass = enc.beginRenderPass({
    colorAttachments: [{ view: target.createView(), clearValue: { r: 0, g: 0, b: 0, a: 0 },
                         loadOp: "clear", storeOp: "store" }],
  });
  pass.setPipeline(pipeline);
  pass.setBindGroup(0, group);
  pass.draw(3);
  pass.end();

  // Readback. A copy's bytes-per-row must be a multiple of 256, so the rows
  // are padded and unpicked here rather than the caller having to know.
  const bpr = Math.ceil(width * 4 / 256) * 256;
  const read = device.createBuffer({ size: bpr * height, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  enc.copyTextureToBuffer({ texture: target }, { buffer: read, bytesPerRow: bpr, rowsPerImage: height },
                          [width, height]);
  device.queue.submit([enc.finish()]);
  const bad = await device.popErrorScope();
  if (bad) {
    read.destroy(); target.destroy(); ubo.destroy();
    for (const t of owned) t.destroy();
    throw new Error(`WebGPU refused the draw: ${bad.message.split("\n")[0]}`);
  }
  await read.mapAsync(GPUMapMode.READ);
  const padded = new Uint8Array(read.getMappedRange());
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) data.set(padded.subarray(y * bpr, y * bpr + width * 4), y * width * 4);
  read.unmap();
  read.destroy();
  target.destroy();
  ubo.destroy();
  for (const t of owned) t.destroy();
  return { data, wgsl: emitted.wgsl, refused: emitted.refused };
}

/** The same, as a canvas — for looking at rather than measuring. */
export async function renderSketchGpuCanvas(sketch, width, height, opts = {}) {
  const { data } = await renderSketchGpu(sketch, width, height, opts);
  const c = document.createElement("canvas");
  c.width = width; c.height = height;
  c.getContext("2d").putImageData(new ImageData(data, width, height), 0, 0);
  return c;
}
