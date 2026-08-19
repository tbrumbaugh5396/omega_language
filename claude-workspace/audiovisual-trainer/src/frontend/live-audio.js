// The live audio path: an effect becomes a sound, and the document says which.
//
// The DSP graph has bounced offline since Phase D, sample-exact and the same
// file twice. This runs the *same* compiled graph on a live AudioContext and
// feeds it from the effects a render graph describes — `{ kind: "note", hz,
// dur }` when a key goes down, `{ kind: "param", node, param, value }` every
// frame — so an event in the picture makes a sound.
//
// *Which* sound is the document's business, not the host's. A render graph
// carries its instruments:
//
//   graph.instruments = { lead: { graph: <a DSP graph>, noteNode, voices } }
//   graph.effects     = [{ kind: "note", instrument: "lead", … }]
//
// A DSP graph is already plain data — nodes, wires, parameters — so an
// instrument travels inside the document the way a `@data` texture or a field
// tree does, and a document that names its instrument is whole on its own. The
// host installs what it is handed and routes by name; it chooses nothing.
//
// One primitive carries both paths: `installGraph` makes the worklet node on
// any context, live or offline, and `setVoice`/`param` schedule AudioParams at
// a time. So the live player is thin — a voice allocator working one note at a
// time, and a clock — and the parity claim is direct: the rig on an
// OfflineAudioContext, fed the fired list frame by frame, against the same
// instruments scheduled from the whole list up front.

import { installGraph } from "./dsp-runtime.js";
import { createDspGraph, addDspNode } from "./dsp-graph.js";
import { schedule } from "./dsp-song.js";

/** The instruments a document declares, and which one an unnamed effect means. */
export const instrumentsOf = (graph) => (graph && graph.instruments) || {};
export const defaultInstrument = (graph) => Object.keys(instrumentsOf(graph))[0] || null;

/**
 * A voice allocator that takes notes as they come. The rule is the one
 * `allocateVoices` applies to a whole list — first free voice, else the one
 * that frees soonest — applied one note at a time, which for notes that
 * arrive in time order is the same assignment.
 */
export class VoiceAllocator {
  constructor(count) { this.freeAt = new Array(count).fill(-Infinity); }
  take(t, dur) {
    let pick = -1;
    for (let v = 0; v < this.freeAt.length; v++) if (this.freeAt[v] <= t) { pick = v; break; }
    if (pick < 0) {
      pick = 0;
      for (let v = 1; v < this.freeAt.length; v++) if (this.freeAt[v] < this.freeAt[pick]) pick = v;
    }
    const stolen = this.freeAt[pick] > t;
    this.freeAt[pick] = t + dur;
    return { voice: pick, stolen };
  }
}

/**
 * An instrument you can hand effects to.
 *
 *   const live = await LiveInstrument.create({ graph, noteNode, voices: 8 });
 *   live.perform(fired);              // from renderGraph's onFired
 *
 * `ctx` may be an OfflineAudioContext, in which case `perform` takes an
 * explicit `at` (seconds) and nothing is heard — that is how it is tested.
 */
export class LiveInstrument {
  static async create({ graph, noteNode, voices = 8, gain = 1, ctx = null, lookahead = 0.03,
                        voiceInit = {}, attach = null }) {
    const context = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const inst = await installGraph(context, graph, { voices, voiceInit });
    // A per-instrument gain, so a document can balance two of them without
    // editing either one's DSP graph. Constant, so both paths apply it alike.
    let out = inst.node, gainNode = null;
    if (gain !== 1) {
      gainNode = context.createGain();
      gainNode.gain.value = gain;
      inst.node.connect(gainNode);
      out = gainNode;
    }
    // Where it goes is the caller's business. A rig that wants each
    // instrument on its own channel says so here — which is the only way to
    // measure one of them, since summing two float32 streams is not
    // bit-stable between renders.
    if (attach) attach(out); else out.connect(context.destination);
    const live = new LiveInstrument();
    Object.assign(live, { ctx: context, inst, noteNode, voices, lookahead, gainNode,
                          alloc: new VoiceAllocator(voices), owned: !ctx, notes: 0, stolen: 0 });
    return live;
  }

  /** The clock an effect lands on: a little ahead of now, so it is not late. */
  now() { return this.ctx.currentTime + this.lookahead; }

  /**
   * Perform a list of fired effects at one time. A `note` is a voice's pitch
   * and gate scheduled on and off; a `param` is one AudioParam set. Anything
   * else is ignored — the graph may describe effects this instrument does
   * not know, and that is the graph's business.
   */
  perform(fired, at = this.now()) {
    let did = 0;
    for (const fx of fired || []) {
      if (fx.kind === "note") {
        const hz = +fx.hz || 440, dur = Math.max(0.005, +fx.dur || 0.2);
        const { voice, stolen } = this.alloc.take(at, dur);
        this.inst.setVoice(voice, this.noteNode, "pitch", hz, at);
        this.inst.setVoice(voice, this.noteNode, "on", 1, at);
        this.inst.setVoice(voice, this.noteNode, "on", 0, at + dur);
        this.notes++; if (stolen) this.stolen++;
        did++;
      } else if (fx.kind === "param") {
        const pm = this.inst.param(String(fx.node), String(fx.param));
        if (pm && Number.isFinite(+fx.value)) { pm.setValueAtTime(+fx.value, at); did++; }
      }
    }
    return did;
  }

  get meter() { return this.inst.meter; }
  get tap() { return this.inst.tap; }

  async resume() { if (this.ctx.resume && this.ctx.state !== "running") await this.ctx.resume(); }
  async close() {
    try {
      this.inst.stop();
      this.inst.node.disconnect();
      if (this.gainNode) this.gainNode.disconnect();
    } catch { /* already gone */ }
    if (this.owned && this.ctx.close) await this.ctx.close();
  }
}

/**
 * Every instrument a document names, installed and routed.
 *
 *   const rig = await LiveRig.create(graph);      // reads graph.instruments
 *   rig.perform(fired);                           // from renderGraph's onFired
 *
 * The rig owns the context unless one is handed in; `ctx` may be an
 * OfflineAudioContext, which is how the whole thing is tested without a sound.
 * An effect's `instrument` was already resolved to a real name when it was
 * described — see param-graph.js — so nothing here has to guess.
 */
export class LiveRig {
  static async create(graph, { ctx = null, lookahead = 0.03, split = false } = {}) {
    const decls = instrumentsOf(graph);
    const names = Object.keys(decls);
    if (!names.length) throw new Error("this document names no instruments");
    const context = ctx || new (window.AudioContext || window.webkitAudioContext)();
    // `split` puts instrument k on channel k instead of mixing them, so a
    // test can hold one instrument's stream to another scheduler's without
    // the mixer's rounding in the way.
    const merger = split ? context.createChannelMerger(names.length) : null;
    if (merger) merger.connect(context.destination);
    const players = new Map();
    for (const [i, name] of names.entries()) {
      const d = decls[name];
      players.set(name, await LiveInstrument.create({
        graph: d.graph, noteNode: d.noteNode, voices: d.voices || 8, gain: d.gain ?? 1,
        voiceInit: d.voiceInit || {}, ctx: context, lookahead,
        attach: merger ? (out) => out.connect(merger, 0, i) : null }));
    }
    const rig = new LiveRig();
    Object.assign(rig, { ctx: context, players, merger, owned: !ctx, fallback: names[0], missed: 0 });
    return rig;
  }

  now() { return this.ctx.currentTime + [...this.players.values()][0].lookahead; }

  /** Route a fired list by instrument name and perform each part. */
  perform(fired, at = this.now()) {
    let did = 0;
    for (const fx of fired || []) {
      const who = fx.instrument === undefined ? this.fallback : String(fx.instrument);
      const player = this.players.get(who);
      // A document that names an instrument it does not carry is a document
      // bug, already reported when the effect was described; here it is
      // counted and skipped rather than thrown, because a wrong name in one
      // effect is not a reason for the rest to go silent.
      if (!player) { this.missed++; continue; }
      did += player.perform([fx], at);
    }
    return did;
  }

  get notes() { let n = 0; for (const p of this.players.values()) n += p.notes; return n; }
  get stolen() { let n = 0; for (const p of this.players.values()) n += p.stolen; return n; }
  get meter() {
    let peak = 0, rms = 0;
    for (const p of this.players.values()) { peak = Math.max(peak, p.meter.peak); rms = Math.max(rms, p.meter.rms); }
    return { peak, rms };
  }

  async resume() { if (this.ctx.resume && this.ctx.state !== "running") await this.ctx.resume(); }
  async close() {
    for (const p of this.players.values()) await p.close();
    this.players.clear();
    if (this.merger) { try { this.merger.disconnect(); } catch { /* already gone */ } }
    if (this.owned && this.ctx.close) await this.ctx.close();
  }
}

/**
 * A plain enveloped tone: the smallest instrument worth naming, and the one
 * a second voice in a document usually wants. Returns a declaration ready to
 * put in `graph.instruments`.
 */
export function toneInstrument({ amp = 0.3, attackMs = 3, decayMs = 180, voices = 4, gain = 1 } = {}) {
  const g = createDspGraph();
  const note = addDspNode(g, "voice.note", {});
  // The envelope drives the oscillator's own gate, which is already a
  // multiply — so an AD envelope costs one node and no new DSP.
  const env = addDspNode(g, "env.ad", { inputs: { gate: [note, "gate"] }, params: { attackMs, decayMs } });
  g.output = addDspNode(g, "osc.sineHz", { inputs: { hz: [note, "hz"], gate: [env, "y"] }, params: { amp } });
  return { graph: g, noteNode: note, voices, gain };
}

/**
 * The instrument the playground and the test both use: a polyphonic sine
 * voice summed with a low hum whose level a `param` effect drives.
 * Returns { graph, noteNode, hum } where `hum` is the node id of the hum's
 * gain, so `{ kind: "param", node: hum, param: "level", value: … }` moves it.
 */
export function shipInstrument() {
  const g = createDspGraph();
  const note = addDspNode(g, "voice.note", {});
  const voice = addDspNode(g, "osc.sineHz", { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.35 } });
  const humOsc = addDspNode(g, "osc.saw", { params: { hz: 55, amp: 0.18, blep: 1 } });
  const hum = addDspNode(g, "gain.smooth", { inputs: { x: [humOsc, "y"] }, params: { level: 0, ms: 60 } });
  g.output = addDspNode(g, "mix.add", { inputs: { a: [voice, "y"], b: [hum, "y"] }, params: { gainA: 1, gainB: 1 } });
  return { graph: g, noteNode: note, hum };
}

/**
 * The fired list of a whole run, bounced offline — the batch path, for
 * holding the live one against.
 *
 * Genuinely a different route: the live rig takes one note at a time as it
 * arrives, this hands each instrument its whole list up front and lets
 * `allocateVoices` and `schedule` place them. Two schedulers, one instrument
 * each, and the samples have to agree.
 */
export async function renderFired(fired, { instruments, fps = 60, frames, sampleRate = 48000,
                                           tail = 0.25, split = false }) {
  const names = Object.keys(instruments || {});
  if (!names.length) throw new Error("no instruments to render with");
  const fallback = names[0];
  const seconds = frames / fps + tail;
  const channels = split ? names.length : 1;
  const ctx = new OfflineAudioContext(channels, Math.max(128, Math.round(seconds * sampleRate)), sampleRate);
  const merger = split ? ctx.createChannelMerger(names.length) : null;
  if (merger) merger.connect(ctx.destination);

  for (const [i, name] of names.entries()) {
    const d = instruments[name];
    const mine = (fired || []).filter((f) => (f.instrument === undefined ? fallback : String(f.instrument)) === name);
    const inst = await installGraph(ctx, d.graph, { voices: d.voices || 8, voiceInit: d.voiceInit || {} });
    let out = inst.node;
    if ((d.gain ?? 1) !== 1) { const gn = ctx.createGain(); gn.gain.value = d.gain; inst.node.connect(gn); out = gn; }
    if (merger) out.connect(merger, 0, i); else out.connect(ctx.destination);

    const notes = mine.filter((f) => f.kind === "note")
      .map((f) => ({ t: f.frame / fps, dur: Math.max(0.005, +f.dur || 0.2), hz: +f.hz || 440 }));
    // Param effects become exact points — a value set at a time and held —
    // which is precisely what the live path does, one per frame it fired on.
    const byParam = new Map();
    for (const f of mine) {
      if (f.kind !== "param") continue;
      const key = `${f.node} ${f.param}`;
      if (!byParam.has(key)) byParam.set(key, { node: String(f.node), param: String(f.param), points: [] });
      byParam.get(key).points.push({ t: f.frame / fps, v: +f.value });
    }
    schedule(inst, { noteNode: d.noteNode, notes, automation: [...byParam.values()] });
  }
  const t0 = performance.now();
  const buffer = await ctx.startRendering();
  const ms = performance.now() - t0;
  return { buffer, seconds, ms, realtimeRatio: (seconds * 1000) / Math.max(ms, 0.001) };
}
