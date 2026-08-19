// The instrument library: an instrument is what it sounds like.
//
// A document names its instruments, and carries them, which made every
// document whole and made two documents wanting the same sound carry it
// twice. The node library solved the same problem by saying *the document is
// the node* — nothing is copied, because a node type is only ever a sketch
// with `@node` in its header, and the same text everywhere is the same node.
//
// An instrument has no header to name it with. What it has is its own data: a
// DSP graph is nodes, wires and parameters, so two instruments are the same
// instrument exactly when that data is the same. So identity here is a hash of
// the instrument itself — `inst.k3f91a` — and "the same instrument" becomes
// something provable rather than a naming convention two people have to keep.
//
// The obstacle is that node ids are handed out by a counter that never resets,
// so two identical instruments built a minute apart read as `n47` and `n52`
// and hash differently. `normalise` renumbers them in dependency order first.
// That is the whole trick, and it is why the id means what it says.
//
// A reference is an optimisation, never a dependency:
//
//   { ref: "tone.bell" }                       the library's, by name
//   { ref: "inst.k3f91a", graph, noteNode }    the library's, or this copy
//   { graph, noteNode }                        this copy, nothing else
//
// A document that carries both plays on a machine whose library has never
// heard of it. `intern` turns copies into references and `inline` turns them
// back, and a document put through both is the same document — held to
// identical samples, not to an argument.

import { topoDsp, createDspGraph, addDspNode } from "./dsp-graph.js";
// The DSP catalogue is registered by this module's side effects, and the
// built-in instruments below are built at load — so it has to have run.
import "./dsp-runtime.js";

/** id or name → a normalised declaration. */
const INSTRUMENTS = new Map();

export const instrumentNames = () => [...INSTRUMENTS.keys()].filter((k) => !k.startsWith("inst."));
export const instrumentCount = () => new Set(INSTRUMENTS.values()).size;

/** The same hash the field compiler uses for its generated types. */
function digest(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

const sortedKeys = (o) => Object.keys(o || {}).sort();

/**
 * An instrument in the one form its identity is computed from.
 *
 * Nodes are renumbered `i0, i1, …` in dependency order, so an instrument's id
 * says nothing about when it was built. Parameter and input keys are sorted,
 * so it says nothing about the order somebody wrote them in either. What is
 * left is what it sounds like.
 */
export function normalise(decl) {
  const g = decl.graph;
  if (!g || !Array.isArray(g.nodes)) throw new Error("an instrument needs a DSP graph");
  // Dependency order where it can be had — a cycle through a delay is legal
  // audio, and topoDsp stops at it, so anything it did not reach is added in
  // declaration order afterwards.
  let order = [];
  try { order = topoDsp(g); } catch { order = []; }
  const seen = new Set(order.map((n) => n.id));
  for (const n of g.nodes) if (!seen.has(n.id)) order.push(n);

  const rename = new Map(order.map((n, i) => [n.id, `i${i}`]));
  const nodes = order.map((n) => {
    const inputs = {};
    for (const k of sortedKeys(n.inputs)) {
      const w = n.inputs[k];
      inputs[k] = Array.isArray(w) ? [rename.get(w[0]) || w[0], w[1]] : w;
    }
    const params = {};
    for (const k of sortedKeys(n.params)) params[k] = n.params[k];
    return { id: rename.get(n.id), type: n.type, inputs, params };
  });
  const out = {
    graph: { nodes, output: rename.get(g.output) || g.output },
    noteNode: rename.get(decl.noteNode) || decl.noteNode,
    voices: decl.voices || 8,
    gain: decl.gain ?? 1,
  };
  if (decl.voiceInit && Object.keys(decl.voiceInit).length) out.voiceInit = decl.voiceInit;
  // The names an instrument has for its own nodes. A patch gives every line
  // one; code that builds a graph hangs the odd id on the declaration
  // (`hum`). Either way they are renamed with the nodes, so a document's
  // effect can say `node: "hum"` and mean the same thing before and after the
  // library renumbers — which is the only way a reference can work at all.
  const parts = {};
  for (const k of sortedKeys(decl.parts || {})) {
    const v = decl.parts[k];
    if (rename.has(v)) parts[k] = rename.get(v);
  }
  for (const k of sortedKeys(decl)) {
    if (["graph", "noteNode", "voices", "gain", "voiceInit", "ref", "parts"].includes(k)) continue;
    const v = decl[k];
    if (typeof v === "string" && rename.has(v)) { parts[k] = rename.get(v); continue; }
    out[k] = v;
  }
  if (Object.keys(parts).length) out.parts = parts;
  return out;
}

/**
 * The form identity is computed from: everything `normalise` produces except
 * the names.
 *
 * `parts` is how a document addresses an instrument's insides, and a name is
 * not a sound. An instrument built in code names nothing and the same
 * instrument written as a patch names every line, and those two are the same
 * instrument — so the id cannot see the names, or "an instrument is what it
 * sounds like" is not true.
 */
const identityForm = (norm) => {
  const { parts, ...rest } = norm;
  return rest;
};

/** What this instrument is, as an id: the same sound, the same id. */
export function instrumentId(decl) {
  return `inst.${digest(JSON.stringify(identityForm(normalise(decl))))}`;
}

/**
 * Put an instrument in the library. Registered under its content id always,
 * and under `name` as well when one is given — so a document may say
 * `{ ref: "tone.bell" }` and mean something a person chose, or
 * `{ ref: "inst.k3f91a" }` and mean something nothing can rename out from
 * under it.
 */
export function defineInstrument(name, decl) {
  const norm = normalise(decl);
  const id = `inst.${digest(JSON.stringify(identityForm(norm)))}`;
  let kept = INSTRUMENTS.get(id) || norm;
  // The same sound arriving with names when the one on the shelf has none is
  // worth taking: it is the same instrument, better labelled.
  if (kept !== norm && Object.keys(norm.parts || {}).length > Object.keys(kept.parts || {}).length) kept = norm;
  INSTRUMENTS.set(id, kept);
  if (name) INSTRUMENTS.set(name, kept);
  return { id, name: name || null, decl: kept };
}

export const instrumentFor = (ref) => INSTRUMENTS.get(String(ref)) || null;
export const forgetInstrument = (ref) => INSTRUMENTS.delete(String(ref));

/**
 * The instruments a document actually means, with every reference followed.
 *
 * A reference the library knows wins; a declaration that carries its own graph
 * stands in when it does not; and a reference with neither is named, once,
 * with what the library does have.
 */
export function resolveInstruments(graph) {
  const out = {}, errors = [];
  const decls = (graph && graph.instruments) || {};
  for (const name of Object.keys(decls)) {
    const d = decls[name] || {};
    if (d.ref) {
      const found = instrumentFor(d.ref);
      if (found) { out[name] = found; continue; }
      if (d.graph) { out[name] = normalise(d); continue; }
      errors.push(`instrument "${name}" refers to ${d.ref}, which this library does not have and this document does not carry`);
      continue;
    }
    if (!d.graph) { errors.push(`instrument "${name}" has neither a graph nor a reference`); continue; }
    out[name] = normalise(d);
  }
  return { instruments: out, errors };
}

/**
 * Every instrument this document carries, put in the library and replaced by
 * a reference to it. `carry` keeps the copy alongside the reference, which is
 * what a document meant to travel wants: the reference saves the space when
 * the library has it and the copy saves the day when it does not.
 */
export function internInstruments(graph, { carry = false } = {}) {
  const decls = (graph && graph.instruments) || {};
  const instruments = {};
  for (const name of Object.keys(decls)) {
    const d = decls[name] || {};
    if (d.ref && !d.graph) { instruments[name] = { ref: d.ref }; continue; }
    const norm = normalise(d);
    const { id } = defineInstrument(null, norm);
    instruments[name] = carry ? { ref: id, ...norm } : { ref: id };
  }
  return { ...graph, instruments };
}

/** The other way: every reference followed and written out in full, so the
    document depends on nothing. */
export function inlineInstruments(graph) {
  const { instruments, errors } = resolveInstruments(graph);
  if (errors.length) throw new Error(errors[0]);
  const out = {};
  for (const name of Object.keys(instruments)) out[name] = { ...instruments[name] };
  return { ...graph, instruments: out };
}

/** Roughly how much of a document its instruments are, for the record. */
export const instrumentBytes = (graph) => JSON.stringify((graph && graph.instruments) || {}).length;

// ------------------------------------------------------------------ builders
//
// The instruments the app itself ships. Each is registered under a name, so a
// document may reference it, and under its content id, so a document that was
// written elsewhere finds it anyway.

/**
 * A plain enveloped tone: the smallest instrument worth naming. The envelope
 * drives the oscillator's own gate, which is already a multiply — so an AD
 * envelope costs one node and no new DSP.
 */
export function toneInstrument({ amp = 0.3, attackMs = 3, decayMs = 180, voices = 4, gain = 1 } = {}) {
  const g = createDspGraph();
  const note = addDspNode(g, "voice.note", {});
  const env = addDspNode(g, "env.ad", { inputs: { gate: [note, "gate"] }, params: { attackMs, decayMs } });
  g.output = addDspNode(g, "osc.sineHz", { inputs: { hz: [note, "hz"], gate: [env, "y"] }, params: { amp } });
  return { graph: g, noteNode: note, voices, gain };
}

/**
 * A polyphonic sine voice summed with a low saw hum whose level a `param`
 * effect drives. `hum` is the node id to write that level to.
 */
export function shipInstrument() {
  const g = createDspGraph();
  const note = addDspNode(g, "voice.note", {});
  const voice = addDspNode(g, "osc.sineHz", { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.35 } });
  const humOsc = addDspNode(g, "osc.saw", { params: { hz: 55, amp: 0.18, blep: 1 } });
  const hum = addDspNode(g, "gain.smooth", { inputs: { x: [humOsc, "y"] }, params: { level: 0, ms: 60 } });
  const out = addDspNode(g, "mix.add", { inputs: { a: [voice, "y"], b: [hum, "y"] }, params: { gainA: 1, gainB: 1 } });
  g.output = out;
  return { graph: g, noteNode: note, voices: 8,
           parts: { note, voice, humOsc, hum, out } };
}

// ------------------------------------------------------------------ documents
//
// The library above is rebuilt from the built-ins at every load, which made an
// instrument last exactly as long as the tab. An `instrument` document is
// where one is kept: its patch is the instrument, so loading the documents at
// boot is all the persistence there is — the same arrangement the node library
// has with Generate documents, and for the same reason. Nothing is copied.

let loadingInstruments = null;

/** Load the instrument documents once, whoever asks first. */
export function ensureUserInstruments(deps) {
  if (!loadingInstruments) loadingInstruments = loadUserInstruments(deps).catch(() => []);
  return loadingInstruments;
}

/**
 * Every `instrument` document, parsed and registered. `deps` carries the two
 * things this needs from elsewhere — the API and the patch parser — so the
 * library stays a file with no opinion about either.
 */
export async function loadUserInstruments({ api, parsePatch, nameFor }) {
  let projects = [];
  try {
    const res = await api("/api/studio/projects");
    projects = (res.projects || []).filter((p) => p.kind === "instrument");
  } catch { return []; }
  const out = [];
  for (const p of projects) {
    try {
      const full = await api(`/api/studio/projects/${p.id}`);
      const patch = (full.data && full.data.patch) || "";
      const { decl, errors } = parsePatch(patch);
      const name = nameFor(full.data || {}, full.name || p.name);
      if (!decl || errors.length) { out.push({ name, docId: p.id, error: errors[0] || "nothing to parse" }); continue; }
      const { id } = defineInstrument(name, decl);
      out.push({ name, id, docId: p.id, nodes: decl.graph.nodes.length });
    } catch (e) { out.push({ docId: p.id, error: String(e.message).split("\n")[0] }); }
  }
  return out;
}

/** Forget one, for a document that stopped being an instrument or went away. */
export function unregisterInstrument(name) {
  const decl = INSTRUMENTS.get(name);
  INSTRUMENTS.delete(name);
  if (decl) for (const [k, v] of [...INSTRUMENTS]) if (v === decl && k.startsWith("inst.")) INSTRUMENTS.delete(k);
}

export const BUILT_IN = {
  "tone.blip": toneInstrument({ amp: 0.22, attackMs: 1, decayMs: 70, voices: 4 }),
  "tone.bell": toneInstrument({ amp: 0.3, attackMs: 6, decayMs: 420, voices: 4, gain: 0.9 }),
  "tone.pluck": toneInstrument({ amp: 0.28, attackMs: 2, decayMs: 300, voices: 4, gain: 0.8 }),
  "ship.classic": shipInstrument(),
};
for (const [name, decl] of Object.entries(BUILT_IN)) defineInstrument(name, decl);
