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
    `    const P_${p.name} = parameters.${p.name};`).join("\n");
  const bufMake = compiled.buffers.map((b) =>
    `    this.B_${b.name} = new Float32Array(${b.size});`).join("\n");
  const bufBind = compiled.buffers.map((b) =>
    `    const B_${b.name} = this.B_${b.name};`).join("\n");
  const bufClear = compiled.buffers.map((b) => `      this.B_${b.name}.fill(0);`).join("\n");
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
${bufMake}
    this.meter = new Float32Array(2);
    this.blocks = 0;
    this.running = true;
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d && d.reset) {
        this.S.fill(0);
${bufClear}
      }
      if (d && d.stop) this.running = false;
    };
  }
  process(inputs, outputs, parameters) {
    const out = outputs[0];
    if (!out || !out.length) return this.running;
    const L = out[0];
    const R = out.length > 1 ? out[1] : null;
    const S = this.S;
${bufBind}
    const n = L.length;
${math}
    const TAU = 6.283185307179586;
    const PI = 3.141592653589793;
${params}
    // Once a block: coefficients, and anything else that does not change
    // between samples. This is what @control and // @block are for.
${compiled.coefDecls}
${compiled.pre}
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

// ------------------------------------------------------------------ Phase B
//
// The library, and every one of these has a number attached to it in the
// self-test — against the analytic response, against a convolution of its own
// impulse response, or against the alias floor of the naive version. A node
// with no measurement behind it is a claim.

defineDspNode(`// The RBJ cookbook biquad, all seven forms. Coefficients once a block,
// difference equation every sample — which is what @control and // @block are for.
// @node filter.biquad
// @module biquad
in float x;
out float y;
state float x1, x2, y1, y2;
coef float b0, b1, b2, a1, a2;
uniform float type;    // @options lowpass,highpass,bandpass,notch,peaking,lowshelf,highshelf @default 0
uniform float freq;    // @range 20 20000 @default 1000 @log @control @help corner or centre frequency, hertz
uniform float q;       // @range 0.1 20 @default 0.707 @control @help resonance; 0.707 is flat
uniform float gainDb;  // @range -24 24 @default 0 @control @help for peaking and the shelves only

// @block
const w0 = TAU * min(freq, sampleRate * 0.49) / sampleRate;
const cw = cos(w0), sw = sin(w0);
const alpha = sw / (2 * q);
const A = pow(10, gainDb / 40);
const t = floor(type + 0.5);
let B0 = 1, B1 = 0, B2 = 0, A0 = 1, A1 = 0, A2 = 0;
if (t === 0) {
  B0 = (1 - cw) / 2; B1 = 1 - cw; B2 = (1 - cw) / 2;
  A0 = 1 + alpha; A1 = -2 * cw; A2 = 1 - alpha;
} else if (t === 1) {
  B0 = (1 + cw) / 2; B1 = -(1 + cw); B2 = (1 + cw) / 2;
  A0 = 1 + alpha; A1 = -2 * cw; A2 = 1 - alpha;
} else if (t === 2) {
  B0 = alpha; B1 = 0; B2 = -alpha;
  A0 = 1 + alpha; A1 = -2 * cw; A2 = 1 - alpha;
} else if (t === 3) {
  B0 = 1; B1 = -2 * cw; B2 = 1;
  A0 = 1 + alpha; A1 = -2 * cw; A2 = 1 - alpha;
} else if (t === 4) {
  B0 = 1 + alpha * A; B1 = -2 * cw; B2 = 1 - alpha * A;
  A0 = 1 + alpha / A; A1 = -2 * cw; A2 = 1 - alpha / A;
} else if (t === 5) {
  const s2 = 2 * sqrt(A) * alpha;
  B0 = A * ((A + 1) - (A - 1) * cw + s2);
  B1 = 2 * A * ((A - 1) - (A + 1) * cw);
  B2 = A * ((A + 1) - (A - 1) * cw - s2);
  A0 = (A + 1) + (A - 1) * cw + s2;
  A1 = -2 * ((A - 1) + (A + 1) * cw);
  A2 = (A + 1) + (A - 1) * cw - s2;
} else {
  const s2 = 2 * sqrt(A) * alpha;
  B0 = A * ((A + 1) + (A - 1) * cw + s2);
  B1 = -2 * A * ((A - 1) + (A + 1) * cw);
  B2 = A * ((A + 1) + (A - 1) * cw - s2);
  A0 = (A + 1) - (A - 1) * cw + s2;
  A1 = 2 * ((A - 1) - (A + 1) * cw);
  A2 = (A + 1) - (A - 1) * cw - s2;
}
b0 = B0 / A0; b1 = B1 / A0; b2 = B2 / A0; a1 = A1 / A0; a2 = A2 / A0;
// @sample
y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
x2 = x1; x1 = x; y2 = y1; y1 = y;`);

defineDspNode(`// A topology-preserving state-variable filter: three outputs from one
// structure, and stable at resonance where a naive digital ladder is not.
// @node filter.svf
// @module biquad
in float x;
out float lp, bp, hp;
state float ic1eq, ic2eq;
coef float g, k, a1c, a2c, a3c;
uniform float freq;   // @range 20 20000 @default 800 @log @control @help corner frequency, hertz
uniform float q;      // @range 0.5 20 @default 0.707 @control @help resonance

// @block
g = tan(PI * min(freq, sampleRate * 0.49) / sampleRate);
k = 1 / q;
a1c = 1 / (1 + g * (g + k));
a2c = g * a1c;
a3c = g * a2c;
// @sample
const v3 = x - ic2eq;
const v1 = a1c * ic1eq + a2c * v3;
const v2 = ic2eq + a2c * ic1eq + a3c * v3;
ic1eq = 2 * v1 - ic1eq;
ic2eq = 2 * v2 - ic2eq;
lp = v2; bp = v1; hp = x - k * v1 - v2;`);

defineDspNode(`// A delay line with linear interpolation between samples, so a moving
// delay glides rather than steps.
// @node delay.line
// @module delay-lines
// @delay 1
in float x;
out float y;
delay float d;         // @size 96000
coef float coefSamples;
uniform float ms;      // @range 0.1 1000 @default 250 @control @help delay in milliseconds
uniform float feedback; // @range 0 0.98 @default 0 @help how much comes back round

// @block
const samples = max(1, min(ms * 0.001 * sampleRate, 95000));
coefSamples = samples;
// @sample
const fi = floor(coefSamples);
const fr = coefSamples - fi;
const a = dRead(fi), b = dRead(fi + 1);
y = a + (b - a) * fr;
dWrite(x + y * feedback);`);

defineDspNode(`// A feedforward comb: the sound plus a delayed copy. Its response is a
// row of notches, which is exactly what a convolution of its impulse says.
// @node filter.comb
// @module delay-lines
// @delay 1
in float x;
out float y;
delay float d;         // @size 8192
coef float coefSamples;
uniform float ms;      // @range 0.1 100 @default 5 @control @help the spacing of the notches
uniform float mix;     // @range -1 1 @default 1 @help how much of the delayed copy, and its sign

// @block
const samples = max(1, min(ms * 0.001 * sampleRate, 8000));
coefSamples = samples;
// @sample
const fi = floor(coefSamples);
y = x + mix * dRead(fi);
dWrite(x);`);

defineDspNode(`// A tanh saturator. The transfer curve is the whole node; what needs
// measuring is what it does above Nyquist, which is why the test sweeps a sine.
// @node shape.tanh
// @module waveshaping
in float x;
out float y;
uniform float drive;   // @range 1 40 @default 4 @log @help how hard it is pushed in
uniform float level;   // @range 0 1 @default 0.7 @help output level after the curve

const v = x * drive;
// tanh, without calling it: the rational approximation is exact enough here
// and a great deal faster.
const v2 = v * v;
y = level * (v * (27 + v2) / (27 + 9 * v2));`);

defineDspNode(`// A sawtooth with PolyBLEP: the discontinuity is corrected over the two
// samples around it, which is the difference between a saw you can use and a
// spray of aliases.
// @node osc.saw
// @module math-audio
out float y;
state float phase;
uniform float hz;    // @range 1 20000 @default 220 @log @help frequency in hertz
uniform float amp;   // @range 0 1 @default 0.5 @help amplitude
uniform float blep;  // @range 0 1 @default 1 @control @help 1 corrects the step, 0 is the naive ramp

const dt = hz / sampleRate;
phase += dt;
if (phase >= 1) phase -= 1;
let s = 2 * phase - 1;
if (blep > 0.5) {
  if (phase < dt) {
    const t2 = phase / dt;
    s -= t2 + t2 - t2 * t2 - 1;
  } else if (phase > 1 - dt) {
    const t2 = (phase - 1) / dt;
    s -= t2 * t2 + t2 + t2 + 1;
  }
}
y = s * amp;`);

defineDspNode(`// White noise from a 32-bit xorshift — deterministic, so a test can repeat.
// @node noise.white
// @module math-audio
out float y;
state float seed;
uniform float amp;   // @range 0 1 @default 0.5 @help amplitude

let z = seed;
if (z === 0) z = 22222;
z = (z * 1103515245 + 12345) % 2147483648;
seed = z;
y = (z / 1073741824 - 1) * amp;`);

defineDspNode(`// An attack–decay envelope, retriggered by a gate. Control rate: an
// envelope that moves once a block is indistinguishable from one that moves
// every sample, and costs a hundred and twenty-eighth as much.
// @node env.ad
// @module math-audio
in float gate;
out float y;
state float level, armed;
uniform float attackMs;  // @range 0.5 2000 @default 5 @control @help time to full
uniform float decayMs;   // @range 1 5000 @default 200 @control @help time to fall away

const ka = 1 - exp(-1 / (max(attackMs, 0.1) * 0.001 * sampleRate));
const kd = 1 - exp(-1 / (max(decayMs, 0.1) * 0.001 * sampleRate));
if (gate > 0.5) { armed = 1; level += (1.2 - level) * ka; }
else if (armed > 0.5) { level += (0 - level) * kd; if (level < 0.0001) { level = 0; armed = 0; } }
y = min(level, 1);`);
