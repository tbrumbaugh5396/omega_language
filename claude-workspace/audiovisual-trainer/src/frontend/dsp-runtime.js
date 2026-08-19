// The worklet host: a compiled graph, running on the audio thread.
//
// The processor's source is *generated* — the whole module, including the
// inner loop — and handed to addModule as a blob. Nothing is evaluated with
// new Function, so there is no dynamic code on the audio thread, and what
// runs can be read: `sourceFor(graph)` returns exactly the text the browser
// was given.
//
// Parameters are AudioParams rather than messages. That is sample-accurate,
// costs no message per change, and is the same automation machinery the
// timeline will want later.

import { compileDspGraph, allocationReport, defineDspNode } from "./dsp-graph.js";

const registered = new WeakMap();     // AudioContext → Set of processor names

/** A stable name for a compiled graph, so the same graph registers once. */
function nameFor(code) {
  let h = 2166136261;
  for (let i = 0; i < code.length; i++) { h ^= code.charCodeAt(i); h = Math.imul(h, 16777619); }
  return `dsp-${(h >>> 0).toString(36)}`;
}

/**
 * The whole AudioWorkletProcessor, as text. Two rules shape it:
 *
 *   - nothing inside process() may allocate, so every array it touches is
 *     made in the constructor and every helper is aliased outside the loop;
 *   - the meter goes out on the port at a low rate rather than per block,
 *     because the UI needs a number, not every number.
 */
export function processorSource(compiled, name) {
  const decls = compiled.declares.map((d) => `      let ${d} = 0;`).join("\n");
  const params = compiled.params.map((p) =>
    `      const P_${p.name} = parameters.${p.name};`).join("\n");
  const math = compiled.math.map((m) => `    const ${m} = Math.${m};`).join("\n");
  const descriptors = compiled.params.map((p) =>
    `      { name: ${JSON.stringify(p.name)}, defaultValue: ${p.defaultValue}, ` +
    `minValue: ${p.minValue}, maxValue: ${p.maxValue}, automationRate: ${JSON.stringify(p.automationRate)} }`
  ).join(",\n");

  return `// Generated from a DSP graph. Read it: this is what runs.
class DspProcessor extends AudioWorkletProcessor {
  static get parameterDescriptors() {
    return [
${descriptors}
    ];
  }
  constructor() {
    super();
    // Everything the loop touches is made here, once.
    this.S = new Float64Array(${Math.max(1, compiled.states.length)});
    this.meter = new Float32Array(2);
    this.blocks = 0;
    this.running = true;
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d && d.reset) this.S.fill(0);
      if (d && d.stop) this.running = false;
    };
  }
  process(inputs, outputs, parameters) {
    const out = outputs[0];
    if (!out || !out.length) return this.running;
    const L = out[0];
    const R = out.length > 1 ? out[1] : null;
    const S = this.S;
    const n = L.length;
${math}
    const TAU = 6.283185307179586;
    const PI = 3.141592653589793;
${params}
    let peak = 0, sum = 0;
    for (let i = 0; i < n; i++) {
${decls}
${compiled.loop}
      const y = ${compiled.outExpr};
      L[i] = y;
      if (R !== null) R[i] = y;
      const a = y < 0 ? -y : y;
      if (a > peak) peak = a;
      sum += y * y;
    }
    // A meter every 16 blocks: often enough to look live, rare enough that
    // the message channel is not part of the hot path.
    this.blocks++;
    if ((this.blocks & 15) === 0) {
      this.meter[0] = peak;
      this.meter[1] = sqrt(sum / n);
      this.port.postMessage(this.meter);
    }
    return this.running;
  }
}
registerProcessor(${JSON.stringify(name)}, DspProcessor);
`;
}

/**
 * The per-sample loop, cut out of the emitted source by matching its braces.
 * That is the region the no-allocation rule is about: the constructor is
 * meant to allocate, and the meter goes out once every sixteen blocks, which
 * is not the hot path and is not pretended to be.
 */
export function innerLoopOf(code) {
  const at = code.indexOf("for (let i = 0; i < n; i++) {");
  if (at < 0) return "";
  let depth = 0, i = code.indexOf("{", at);
  for (let k = i; k < code.length; k++) {
    if (code[k] === "{") depth++;
    else if (code[k] === "}" && --depth === 0) return code.slice(i + 1, k);
  }
  return code.slice(i + 1);
}

/** The compiled source for a graph, plus what the allocation rule found. */
export function sourceFor(graph) {
  const compiled = compileDspGraph(graph);
  const name = nameFor(compiled.loop + compiled.outExpr);
  const code = processorSource(compiled, name);
  const findings = allocationReport(innerLoopOf(code));
  return { compiled, name, code, findings, loop: innerLoopOf(code) };
}

/**
 * Install a graph on a context and return a node you can connect.
 * `ctx` may be an OfflineAudioContext, which is how this is tested without
 * making a sound.
 */
export async function installGraph(ctx, graph) {
  const { compiled, name, code, findings } = sourceFor(graph);
  if (findings.length) {
    throw new Error(`the emitted loop would allocate: ${findings[0].why} (line ${findings[0].line})`);
  }
  let names = registered.get(ctx);
  if (!names) { names = new Set(); registered.set(ctx, names); }
  if (!names.has(name)) {
    const url = URL.createObjectURL(new Blob([code], { type: "text/javascript" }));
    try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    names.add(name);
  }
  const node = new AudioWorkletNode(ctx, name, { numberOfInputs: 0, numberOfOutputs: 1,
                                                 outputChannelCount: [2] });
  const meter = { peak: 0, rms: 0 };
  node.port.onmessage = (e) => { meter.peak = e.data[0]; meter.rms = e.data[1]; };
  return {
    node, name, code, meter, compiled,
    param: (nodeId, uniform) => node.parameters.get(`${nodeId}_${uniform}`),
    reset: () => node.port.postMessage({ reset: true }),
    stop: () => node.port.postMessage({ stop: true }),
  };
}

// ------------------------------------------------------------------ Phase A nodes
//
// Three, chosen to prove the three things Phase A is about: that a node can
// hold state, that its coefficients come from the sample rate rather than a
// number someone measured at 44.1 k, and that the whole thing runs without
// allocating.

defineDspNode(`// A sine, from a phase accumulator — the reference tone everything else is measured against.
// @node osc.sine
// @module math-audio
out float y;
state float phase;
uniform float hz;    // @range 1 20000 @default 440 @log @help frequency in hertz
uniform float amp;   // @range 0 1 @default 0.5 @help amplitude, 1 is full scale

phase += hz / sampleRate;
if (phase >= 1) phase -= floor(phase);
y = sin(TAU * phase) * amp;`);

defineDspNode(`// A gain with a one-pole smoother, so a moved fader does not step.
// @node gain.smooth
// @module math-audio
in float x;
out float y;
state float g;
uniform float level;   // @range 0 2 @default 1 @help the gain being approached
uniform float ms;      // @range 0.1 500 @default 20 @control @help how long it takes to get there

const k = 1 - exp(-1 / (ms * 0.001 * sampleRate));
g += (level - g) * k;
y = x * g;`);

defineDspNode(`// A one-pole lowpass. The simplest filter with memory, and the first thing
// that proves state and sample rate are handled properly.
// @node filter.onepole
// @module biquad
in float x;
out float y;
state float z;
uniform float cutoff;   // @range 20 20000 @default 1000 @log @help corner frequency, hertz

const c = exp(-TAU * cutoff / sampleRate);
z = x * (1 - c) + z * c;
y = z;`);
