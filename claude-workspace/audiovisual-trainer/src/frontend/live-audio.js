// The live audio path: an effect becomes a sound.
//
// The DSP graph has bounced offline since Phase D, sample-exact and the same
// file twice. This runs the *same* compiled graph on a live AudioContext and
// feeds it from the effects a render graph describes — `{ kind: "note", hz,
// dur }` when a key goes down, `{ kind: "param", node, param, value }` every
// frame — so an event in the picture makes a sound, and the sound is the same
// instrument the bounce would have used.
//
// One primitive carries both: `installGraph` makes the worklet node on any
// context, live or offline, and `setVoice`/`param` schedule AudioParams at a
// time. So the live player is a thin thing — a voice allocator that works one
// note at a time, and a clock — and the parity claim is direct: the live
// instrument on an OfflineAudioContext, fed the fired list frame by frame, and
// `renderSong` fed the same list as a batch, produce the same samples.

import { installGraph } from "./dsp-runtime.js";
import { createDspGraph, addDspNode } from "./dsp-graph.js";
import { renderSong } from "./dsp-song.js";

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
  static async create({ graph, noteNode, voices = 8, ctx = null, lookahead = 0.03, voiceInit = {} }) {
    const context = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const inst = await installGraph(context, graph, { voices, voiceInit });
    inst.node.connect(context.destination);
    const live = new LiveInstrument();
    Object.assign(live, { ctx: context, inst, noteNode, voices, lookahead,
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
    try { this.inst.stop(); this.inst.node.disconnect(); } catch { /* already gone */ }
    if (this.owned && this.ctx.close) await this.ctx.close();
  }
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
 * The fired list of a whole run, bounced offline as a song — the batch path,
 * for holding the live one against. `frames` says how many frames were run
 * and `fps` how long a frame is; note times are frame / fps.
 */
export async function renderFired(fired, { graph, noteNode, fps = 60, frames, sampleRate = 48000, voices = 8, tail = 0.25 }) {
  const notes = fired.filter((f) => f.kind === "note")
    .map((f) => ({ t: f.frame / fps, dur: Math.max(0.005, +f.dur || 0.2), hz: +f.hz || 440 }));
  const automation = [];
  // Param effects become exact points — a value set at a time and held —
  // which is precisely what the live path does, one per frame it fired on.
  const byParam = new Map();
  for (const f of fired) {
    if (f.kind !== "param") continue;
    const key = `${f.node} ${f.param}`;
    if (!byParam.has(key)) byParam.set(key, { node: String(f.node), param: String(f.param), points: [] });
    byParam.get(key).points.push({ t: f.frame / fps, v: +f.value });
  }
  automation.push(...byParam.values());
  const seconds = frames / fps + tail;
  return renderSong({ graph, noteNode, notes, automation, tail: 0 }, { sampleRate, seconds, voices });
}
