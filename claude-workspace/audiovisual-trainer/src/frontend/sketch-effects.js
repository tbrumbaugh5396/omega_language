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
// The cost is named rather than hidden: reading pixels back stalls the GPU
// until the frame it is reading has finished. For a handful of texels at 60
// frames a second that is small, and it is the only way for the host to learn
// what a shader decided.

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
export function sketchFrame(gl, doc, target, { stateKey, width, height, time, frame, keys }) {
  const probes = readProbes(gl, target, doc.probes, { height });
  const g = sketchGraph(doc, probes, { stateKey, width, height });
  const r = resolveParams(g, { t: time, frame, keys, commit: true });
  return { fired: r.fired || [], probes, errors: r.paramErrors || [] };
}
