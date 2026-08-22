// Giving a sketch a voice.
//
// A render graph makes sound because it has parameters an expression can read
// and effects that fire on them. A sketch has neither: it is one program with
// uniforms, and whatever it remembers it remembers in its own state texture.
// Saying "a sketch cannot have effects" was true and not interesting — the
// state is right there, and the only thing missing was a way to look at it.
//
// So a sketch document may declare **probes**: named texels of its own state.
//
//   probes: { hitBat: { texel: [2, 0], channel: "r" },
//             score:  { texel: [1, 0], channel: "g" } }
//
// They are read back once a frame — four bytes or four floats, one readPixels
// of a tiny rectangle — and handed to the ordinary expression evaluator as the
// parameters of one node called `sketch`. From there everything a render graph
// can do, a sketch can:
//
//   effects: [{ kind: "note", instrument: "blip",
//               when: 'ch("hitBat") > 0.5', hz: '440 * 2 ^ (ch("score") / 12)' }]
//
// `prev()` works, because the probe values are committed as parameters like
// any others; `key()` works, because the sketch runtime binds the keyboard.
// What a sketch still does not have is a *graph* — one node, no wires — and
// that is the honest shape of the thing rather than a limitation to apologise
// for. A sketch is one program, and this lets that one program be heard.
//
// The cost used to be named rather than hidden: reading pixels back stalls the
// GPU until the frame it is reading has finished. Measured on an Intel HD 6000
// that is 2.675 ms *per call*, and the call was per distinct probe texel — the
// open world has five, so about eleven milliseconds a frame of the main thread
// doing nothing whenever sound was on. Not small. It was the difference
// between an app that runs and one that does not.
//
// Two changes, and the first is the dull one that does most of the work:
//
//   * **One rectangle, not one call a texel.** A sketch's probes live in a
//     handful of texels of one row, so their bounding box is tiny — eleven
//     texels for the open world. One read of the box replaces five reads of
//     one pixel. If the box is not tiny the old way is still there, because
//     probes in opposite corners would make "the box" the whole picture.
//
//   * **The pixels go into a buffer, and a fence says when they arrived.**
//     With a buffer bound to PIXEL_PACK_BUFFER, readPixels stops being a
//     question and becomes a command: it returns at once and the GPU fills
//     the buffer when it gets there. The values are collected a frame or two
//     later. Nothing waits.

import { resolveParams } from "./param-graph.js";

/** The channel index a probe names. */
const CHANNEL = { r: 0, g: 1, b: 2, a: 3, x: 0, y: 1, z: 2, w: 3 };

/** Is there anything here for the host to do? */
export const hasSketchEffects = (doc) =>
  !!(doc && Array.isArray(doc.effects) && doc.effects.length && doc.instruments
     && Object.keys(doc.instruments).length);

/**
 * Read every probe out of a framebuffer, as { name: number }.
 *
 * One readPixels per distinct texel, because probes usually share very few of
 * them and a rectangle covering all of them could be the whole picture. Values
 * come back as bytes for an 8-bit target and as floats otherwise, and are
 * reported in 0..1 either way so a document does not have to know which it got.
 */
export function readProbes(gl, target, probes, { height = 0 } = {}) {
  const out = {};
  if (!probes || !target) return out;
  const byTexel = new Map();
  for (const [name, p] of Object.entries(probes)) {
    const [x, y] = p.texel || [0, 0];
    const key = `${x | 0},${y | 0}`;
    if (!byTexel.has(key)) byTexel.set(key, { x: x | 0, y: y | 0, names: [] });
    byTexel.get(key).names.push([name, CHANNEL[String(p.channel || "r").toLowerCase()] ?? 0]);
  }
  const float = target.kind === "float" || target.kind === "half";
  const buf = float ? new Float32Array(4) : new Uint8Array(4);
  const type = float ? gl.FLOAT : gl.UNSIGNED_BYTE;
  const prev = gl.getParameter(gl.FRAMEBUFFER_BINDING);
  gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
  for (const { x, y, names } of byTexel.values()) {
    try {
      gl.readPixels(x, y, 1, 1, gl.RGBA, type, buf);
    } catch { continue; }
    for (const [name, c] of names) out[name] = float ? buf[c] : buf[c] / 255;
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, prev);
  return out;
}

/**
 * A sketch document as the one-node graph the expression evaluator wants.
 *
 * The probes are this frame's readings, as plain values; anything the document
 * put in `params` is an expression over them. Effects resolve bare names
 * against this node, so a document writes `ch("score")` rather than
 * `ch("sketch.score")` — there is only one node to mean.
 */
export function sketchGraph(doc, probeValues, { stateKey, width, height }) {
  const params = {};
  for (const [name, v] of Object.entries(probeValues || {})) params[name] = [v];
  for (const [name, expr] of Object.entries(doc.params || {})) {
    params[name] = typeof expr === "object" ? expr : { expr: String(expr) };
  }
  return {
    stateKey, width, height,
    nodes: [{ id: "sketch", name: "sketch", type: "source", params, inputs: [] }],
    effects: doc.effects || [],
    instruments: doc.instruments || {},
    effectNode: "sketch",
  };
}

/**
 * One frame of it: read the probes, resolve, and hand back what fired.
 * Performs nothing — the caller owns the rig, as everywhere else.
 */
/**
 * The probes, read without waiting for them.
 *
 * The values are one or two frames old. For sound that is thirty milliseconds
 * on a footstep, which is inaudible; what would not be acceptable is *missing*
 * a pulse, and none are missed while a slot is free — every frame's read is
 * issued, and they are collected strictly in order, one a frame, so no frame's
 * state is stepped over. With the GPU more than three frames behind, a read is
 * skipped rather than letting the lag grow without bound, and a sketch that
 * far behind is not being drawn properly either.
 */
class ProbeReader {
  constructor(gl) {
    this.gl = gl;
    this.slots = []; this.queue = []; this.last = {}; this.key = "";
    this.issued = 0; this.collected = 0; this.skipped = 0;
  }

  /** The smallest rectangle holding every probe, or null if that is silly. */
  static boxOf(probes) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const p of Object.values(probes)) {
      const [x, y] = p.texel || [0, 0];
      x0 = Math.min(x0, x | 0); x1 = Math.max(x1, x | 0);
      y0 = Math.min(y0, y | 0); y1 = Math.max(y1, y | 0);
    }
    if (!Number.isFinite(x0)) return null;
    const w = x1 - x0 + 1, h = y1 - y0 + 1;
    return w * h > 4096 ? null : { x: x0, y: y0, w, h };
  }

  frame(target, probes, float) {
    const gl = this.gl;
    const box = ProbeReader.boxOf(probes);
    if (!box) return null;                    // scattered: the caller does it the old way
    const key = `${box.x},${box.y},${box.w},${box.h},${float ? "f" : "b"}`;
    if (key !== this.key) { this.release(); this.key = key; }
    this.collect(box, probes, float);         // first, so a slot freed now is reusable now

    const slot = this.slots.find((s) => !s.sync)
      || (this.slots.length < 3 ? this.make(box, float) : null);
    if (!slot) { this.skipped++; return this.last; }

    const prevFb = gl.getParameter(gl.FRAMEBUFFER_BINDING);
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, slot.buf);
    gl.readPixels(box.x, box.y, box.w, box.h, gl.RGBA, float ? gl.FLOAT : gl.UNSIGNED_BYTE, 0);
    slot.sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
    if (slot.sync) { this.queue.push(slot); this.issued++; }
    // Unbound before anything else runs. A PIXEL_PACK_BUFFER left bound turns
    // every other readPixels in the app into a write into this buffer, and the
    // caller gets whatever was already in its array — which looks like a
    // frozen picture rather than an error.
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, prevFb);
    return this.last;
  }

  make(box, float) {
    const gl = this.gl;
    const n = box.w * box.h * 4;
    const slot = { buf: gl.createBuffer(), sync: null,
                   view: float ? new Float32Array(n) : new Uint8Array(n) };
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, slot.buf);
    gl.bufferData(gl.PIXEL_PACK_BUFFER, slot.view.byteLength, gl.STREAM_READ);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    this.slots.push(slot);
    return slot;
  }

  /** At most one a frame, oldest first, so no frame's state is stepped over. */
  collect(box, probes, float) {
    const gl = this.gl;
    const slot = this.queue[0];
    if (!slot || !slot.sync) return;
    // SYNC_FLUSH_COMMANDS_BIT, and it is not optional: a fence only advances
    // once the commands behind it have been sent, and nothing here sends them.
    // Without it the fence never signals, the queue never drains, and this
    // hands back the same empty object for ever while looking exactly like it
    // is working — 3 issued, 0 collected, and a saving that was entirely the
    // saving of not doing the work.
    //
    // The timeout is 0: this asks, it does not wait. And what it is waiting on
    // is *elapsed time*, not an event-loop turn — fifty message-channel ticks
    // in a quarter of a millisecond do not move it, and two frames do. Which
    // is the whole design, and worth knowing before writing a test for it.
    const st = gl.clientWaitSync(slot.sync, gl.SYNC_FLUSH_COMMANDS_BIT, 0);
    if (st !== gl.ALREADY_SIGNALED && st !== gl.CONDITION_SATISFIED) return;
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, slot.buf);
    gl.getBufferSubData(gl.PIXEL_PACK_BUFFER, 0, slot.view);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    gl.deleteSync(slot.sync);
    slot.sync = null;
    this.queue.shift();
    this.collected++;
    const out = {};
    for (const [name, p] of Object.entries(probes)) {
      const [px, py] = p.texel || [0, 0];
      const i = (((py | 0) - box.y) * box.w + ((px | 0) - box.x)) * 4
        + (CHANNEL[String(p.channel || "r").toLowerCase()] ?? 0);
      out[name] = float ? slot.view[i] : slot.view[i] / 255;
    }
    this.last = out;
  }

  release() {
    const gl = this.gl;
    for (const s of this.slots) { if (s.sync) gl.deleteSync(s.sync); gl.deleteBuffer(s.buf); }
    this.slots = []; this.queue = []; this.key = "";
  }
}

// One reader a document, because the ring has to live between frames.
const readers = new Map();

/** Let go of a document's read buffers. */
export function releaseProbeReader(stateKey) {
  const r = readers.get(stateKey);
  if (r) { r.release(); readers.delete(stateKey); }
}

/** What the reader is doing, for a check to look at. */
export const probeReaderStats = (stateKey) => {
  const r = readers.get(stateKey);
  return r ? { issued: r.issued, collected: r.collected, skipped: r.skipped, slots: r.slots.length } : null;
};

/**
 * One frame of it: read the probes, resolve, and hand back what fired.
 *
 * `live` decides how the probes are read, and it is not a performance knob —
 * it is a statement about the caller's loop. The buffered read only completes
 * when the caller returns to the event loop and lets some time pass, which a
 * frame loop does by definition and a batch loop never does. A bounce running
 * seven hundred frames back to back would collect nothing and hear silence,
 * so anything not driven by frames keeps the synchronous read.
 *
 * Off by default, because the caller that gets this wrong should get the slow
 * answer rather than no answer.
 */
export function sketchFrame(gl, doc, target, { stateKey, width, height, time, frame, keys, live }) {
  // WebGL2 or nothing: fences and buffer reads are 2.0, and a 1.0 context
  // keeps the synchronous path it always had.
  let probes = null;
  if (live && target && typeof gl.fenceSync === "function"
      && doc.probes && Object.keys(doc.probes).length) {
    let r = readers.get(stateKey);
    if (!r) { r = new ProbeReader(gl); readers.set(stateKey, r); }
    probes = r.frame(target, doc.probes, target.kind === "float" || target.kind === "half");
  }
  if (!probes) probes = readProbes(gl, target, doc.probes, { height });
  const g = sketchGraph(doc, probes, { stateKey, width, height });
  const r = resolveParams(g, { t: time, frame, keys, commit: true });
  return { fired: r.fired || [], probes, errors: r.paramErrors || [] };
}
