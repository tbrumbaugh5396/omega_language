# Audio: the same idea, one octave down

*A companion to `roadmap-glsl-target.md`. That document's Phase 7 says audio
does not compile to GLSL, that the analogous move is Music as an AudioWorklet
DSP graph with the same schema discipline, and that it is a separate roadmap.
This is that roadmap.*

---

## 1. Why this is not the visual roadmap with different words

The GLSL roadmap rests on one fact: a picture is a pure function of position.
Every pixel can be computed independently, at any resolution, in any order, on
a thousand cores at once. That is why a document can compile to a *shader* —
one expression, evaluated everywhere.

A sound is not that. A sample depends on the samples before it. A filter has
state; a delay line *is* state; a reverb is thousands of samples of memory
being read while it is written. There is no `sound(t)` for a lowpass filter
the way there is a `colour(uv)` for a gradient, because the answer at second
three depends on what happened at second two.

So the target is different, and the differences are not cosmetic:

| | Visual | Audio |
|---|---|---|
| the unit | a pixel, independent | a sample, dependent on its past |
| parallelism | embarrassing | essentially none within a voice |
| the deadline | a frame, ~16 ms, a drop is a stutter | a block, ~2.7 ms, a drop is a *click* |
| where it runs | the GPU, off the main thread by nature | an AudioWorklet, one real-time thread |
| the compile target | GLSL, one expression | a processing graph, plus per-node code |
| what "resolution independent" means | any zoom | any sample rate |

What *does* carry over is everything the GLSL roadmap actually got its value
from, and none of it is about pixels:

- **The schema is a comment.** `uniform float cutoff; // @range 20 20000 @log`
  is as good a contract for a filter as for a blur. One grammar, one panel
  builder, one documentation generator.
- **The document is a graph; the text is its shadow.** The truth is nodes and
  connections; the code is generated, always readable, always runnable, and
  hand-editable at a sanctioned boundary.
- **Parity against a reference you did not write.** The visual work is only
  trustworthy because every node is held to a number against the CPU
  implementation or the browser's own rasteriser. Audio has better references
  than that — the analytic response of a biquad is a formula.
- **Fusion.** A chain of per-sample nodes should become one inner loop for the
  same reason a chain of per-pixel nodes becomes one pass.
- **Say what is not done.** WOFF2 outlines, `calt` shaping, WebM — each was
  declined in writing with the reason. That discipline is the whole reason the
  visual roadmap can be trusted; it is worth more here, where "it sounds fine
  to me" is an easier lie to tell.

---

## 2. The target

**An AudioWorklet graph, with the DSP authored as text.**

Not Web Audio's built-in node graph — that is a fixed set of black boxes, and
the whole point of this project is that a student can see and change the thing
that makes the sound. Not WebAssembly either, at least not first: the value is
in *reading* the filter, and a `.wasm` is not reading material.

So: one `AudioWorkletProcessor` that runs a compiled graph, and node bodies
written in a small, checked subset of JavaScript that the compiler inlines
into one `process()` loop.

A node looks like this — and it should look familiar:

```js
// One pole of a state-variable filter. Stable up to Nyquist/2 and cheap.
// @node filter.svf
// @module biquad
// @rate audio
in float x;
out float lp, bp, hp;
state float ic1eq, ic2eq;
uniform float cutoff;      // @range 20 20000 @default 800 @log @help corner frequency, Hz
uniform float q;           // @range 0.5 20 @default 0.7 @help resonance

float g = tan(PI * cutoff / sampleRate);
float k = 1.0 / q;
float a1 = 1.0 / (1.0 + g * (g + k));
float v1 = a1 * (ic1eq + g * (x - ic2eq));
float v2 = ic2eq + g * v1;
ic1eq = 2.0 * v1 - ic1eq;
ic2eq = 2.0 * v2 - ic2eq;
lp = v2; bp = v1; hp = x - k * v1 - v2;
```

Three additions to the grammar the visual side already has, and only three:

- **`state`** — a variable that persists between samples. This is the one
  concept GLSL has no equivalent of, and naming it explicitly is what lets the
  compiler decide what to allocate per voice, what to zero on reset, and what
  can be fused.
- **`in` / `out`** — named signal ports, so a node can have more than one of
  each. A filter with `lp`, `bp` and `hp` outputs is the normal case, not an
  exception.
- **`@rate audio | control | block`** — a cutoff that moves once per block is
  a different thing from one that moves per sample, and the compiler should
  know which so it can hoist the arithmetic.

Everything else is the same grammar: `@range`, `@default`, `@log`, `@help`,
`@module`, `@options`, `@hidden`.

---

## 3. Phases

### Phase A — The worklet baseline *(M)*

- One `AudioWorkletProcessor` that runs a compiled graph; a message port for
  parameter changes; a ring buffer for what the UI needs to draw.
- **The no-allocation rule, enforced.** Nothing in `process()` may allocate:
  no array literals, no closures, no string work. The compiler emits code that
  cannot, and a check reads the emitted text for the constructs that would.
  A garbage collection in the audio thread is a click, and a click is the one
  failure users never forgive.
- Sample-rate independence from the start: every coefficient a function of
  `sampleRate`, and the parity tests run at 44.1 k and 48 k both.
- *Done when:* a sine at 1 kHz measures −0.0 dBFS at 1 kHz and below −90 dB
  everywhere else, at both rates, with no allocation in the audio callback.

### Phase B — The node library, held to the mathematics *(L)*

The visual roadmap's leverage came from parity against a reference. Audio's
references are better, because most of them are closed forms:

- **Biquads** — the RBJ cookbook forms. Parity: the measured magnitude
  response against the analytic |H(e^{jω})|, swept, to a tolerance in dB.
- **State-variable and ladder filters** — parity against an oversampled
  reference implementation, and a stability sweep: no combination of cutoff
  and resonance may produce a sample outside ±10 for a bounded input.
- **Delay, comb, allpass** — parity against a direct convolution of the same
  impulse response.
- **Waveshapers, saturators** — the transfer curve is the reference; what
  needs testing is aliasing, which means measuring energy above Nyquist/2 for
  a swept sine and reporting it in dB rather than hoping.
- **Oscillators** — PolyBLEP against a naive ramp: the point of the node is
  the alias suppression, so the test is the alias floor, not the waveform.
- **Envelopes, LFOs, sample-and-hold** — control rate.
- *Done when:* every node in the library has a number attached to it in the
  self-test, in dB, against something that was not written for the occasion.

### Phase C — The graph, and fusion *(M)*

- The same model: nodes, ports, one output; topological order; bypass.
- **Feedback is legal here and is not in the visual graph.** A cycle through a
  delay of at least one sample is how reverbs and physical models are built.
  So the compiler needs a cycle rule: a cycle is valid if and only if it
  passes through a node that declares `@delay >= 1`, and the error for a
  zero-delay loop must name the nodes in it.
- **Fusion**: a run of per-sample nodes becomes one inner loop with the state
  as locals. The visual fusion's lesson applies directly — the fused code must
  be *ejectable and readable*, and a fused chain that will not compile must
  fall back to node-at-a-time rather than change the sound.
- **Voices**: polyphony is the graph instantiated N times with its own state.
  The compiler emits one loop over voices, not N graphs.

### Phase D — Music on the graph *(L)*

- Instruments become graphs; the step sequencer drives note events into them.
- Per-track effect chains, the same node types.
- **Automation is the visual roadmap's keyframes**, with the same evaluator
  discipline: pure, in local clip time, and shared between the preview and the
  offline render so a bounce is reproducible.
- **Offline render** must be sample-exact and faster than real time, and must
  produce *the same file twice* — the audio equivalent of the frame-exact
  export, and the same test.

### Phase E — What you can see *(M)*

The visual studios earn their trust by showing the numbers. The audio ones
should too, and this is where the two sides finally rejoin:

- **Scopes**: spectrum, spectrogram, oscilloscope, correlation, loudness to
  ITU-R BS.1770 with true-peak. Drawn by the *visual* pipeline — these are
  pictures, and there is a whole render graph for pictures already.
- **The analyser reads the audio graph's own taps**, so what is measured is
  what will be exported, exactly as the video scopes read the composited frame.

---

## 4. Decisions taken in advance

- **Not WebAssembly first.** A student cannot read a `.wasm`. If a node is
  ever too slow as generated JavaScript, that specific node earns a WASM
  implementation *and keeps its readable source as the reference the WASM is
  tested against* — which is the same relationship the GPU nodes have with the
  CPU filters.
- **Not Web Audio's built-in nodes** for anything the library implements, for
  the same reason: `BiquadFilterNode` is a black box, and its coefficients are
  not the lesson. They stay available for output, media elements and analysis.
- **One thread, and respect it.** No `console.log` in `process()`, no
  `postMessage` per sample, no growing arrays. The check for this is
  mechanical and belongs in the self-test from the first commit.
- **Denormals.** Flush them, and say so: a reverb tail decaying into denormal
  numbers is a hundredfold slowdown on some CPUs, and the fix is a tiny DC
  offset or an explicit flush, not hope.
- **Latency is a number the UI states.** Block size, worklet latency and
  output latency, added up and shown, rather than "low latency" as a claim.
- **What stays outside:** score notation, MIDI hardware beyond Web MIDI's own
  surface, and anything that needs a model — stem separation, transcription,
  style transfer. Content-aware is ML, not craft, on this side too.

---

## 5. The one-line version

The visual roadmap's thesis was *the document is a graph and GLSL is its
shadow*. The audio thesis is the same sentence with one word changed and one
word added: **the document is a graph, the DSP is its shadow, and the shadow
has memory.**

Everything hard about audio lives in that last clause. Everything valuable
about the visual roadmap — the schema in a comment, the parity number, the
readable ejection, the honest note about what is not done — carries over
untouched.
