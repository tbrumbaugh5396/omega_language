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

### Phase A — The worklet baseline *(M)* — **shipped**

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

**Met.** `dsp-graph.js` is the grammar and the compiler; `dsp-runtime.js`
generates the whole `AudioWorkletProcessor` as text and installs it from a
blob, so **nothing is evaluated with `new Function` on the audio thread** and
`sourceFor(graph)` returns exactly what the browser was given.

A node's body goes into the loop **verbatim**, inside a block that declares
its ports, uniforms and state as ordinary locals — the same move the visual
compiler makes with a sketch, and for the same reason: what you read is what
runs. Uniforms become **AudioParams**, not messages, which is sample-accurate,
costs nothing per change, and is already the automation machinery Phase D
will want.

- **The tone.** At 44.1 k, 1001.3 Hz at **0.00 dBFS** with everything else
  below **−95.8 dB**; at 48 k, 996.1 Hz, same numbers. The frequency is nudged
  onto an exact FFT bin — otherwise what gets measured is the window's leakage
  rather than the oscillator, which is the sort of thing that makes a good
  number meaningless.
- **The no-allocation rule is enforced and the enforcement is tested.** The
  emitted loop is clean, and a node written the way a person naturally would —
  with an array literal in it — is caught and named. The rule is scoped to the
  *sample loop*: the constructor is meant to allocate, and the meter goes out
  once every sixteen blocks, outside the loop, which is stated rather than
  pretended away.
- **Sample rate is a variable, and that is measured rather than asserted.**
  The one-pole is held against its own analytic |H(e^{jω})|: **worst 0.02 dB**
  across 500/1000/4000 Hz at both rates, −3.00 dB and −3.02 dB at its corner.
  That is Phase B's method arriving early, on the one node Phase A needed.
- **The cycle rule is in from the start.** A feedback loop with no delay in it
  is refused with the nodes named — `n18 → n17 → n18` — rather than "cyclic
  graph", which tells you nothing you can act on.
- Three nodes ship: `osc.sine`, `gain.smooth` (a one-pole smoother, so a moved
  fader does not step) and `filter.onepole`. Four checks, in the self-test's
  **Audio worklet** group, all rendered offline so it never makes a sound.

**Left for Phase B onward:** everything else. There is no UI for this yet —
no panel, no meter on screen, nothing wired into the Music studio. Phase A is
the floor being solid, not a room.

### Phase B — The node library, held to the mathematics *(L)* — **shipped**

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

**Met.** Nine nodes, six checks, every one a measurement:

| node | held against | number |
|---|---|---|
| `filter.biquad` (7 forms) | the cookbook's response, typed out again in the test | **0.000 dB** worst, five forms × two frequencies |
| `filter.svf` | a stability sweep at full-scale noise | worst sample **5.93**, bar ±10 |
| `filter.comb` / `delay.line` | `x[n] + x[n−240]` computed directly | **2.98e−8**, which is float32 and not the delay |
| `osc.saw` | an additive band-limited saw | **7.6 / 7.3 dB** better than the naive ramp |
| `shape.tanh` | its own non-harmonic energy | **−53.9 dB**, reported rather than hidden |
| `env.ad` | its own shape | reaches 1.000, clamped, never negative |

The compiler grew the two things the library needed, and they are the two the
`@rate` bullet was pointing at:

- **`coef` and `// @block`.** A biquad's `tan`, `cos` and `pow` have no
  business running forty-eight thousand times a second when the cutoff moved
  once. Control-rate uniforms are read before the loop, the block section runs
  there, and the coefficients are plain locals in the sample loop.
- **`delay float d; // @size N`.** A ring buffer, made in the constructor,
  rounded up to a power of two so the wrap is a mask. Its two operations are
  *macros*, not calls — `dRead(n)` and `dWrite(v)` are rewritten by matching
  the closing parenthesis — because a call per sample costs with nothing to
  show for it, and the substitution is small enough to read in the emitted
  source.

Two things worth writing down, because both are the sort of measurement that
looks right and is not:

- **A naive saw measured "clean" at 3 kHz.** At 48 k that is exactly
  `sr/16`, so every alias lands on top of a harmonic and hides. Classifying
  bins as harmonic-or-alias is fragile for anything but an exactly periodic
  signal; comparing against an additive band-limited waveform is not, because
  the reference cannot alias by construction. That is what the test does now.
- **The biquad's first pass read 0.073 dB** because the amplitude was taken
  as a peak, and at 4 kHz a sine has twelve samples a period so the true crest
  falls between two of them. RMS × √2 is exact regardless, and the error went
  to zero.

**Left for later in Phase B:** the ladder filter, granular and convolution
nodes, and oversampling the saturator — its −53.9 dB is what a hard curve
does at 1×, and the fix is 4× oversampling around the curve rather than a
better curve.

### Phase C — The graph, and fusion *(M)* — **shipped**

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

**Shipped**, and one of these turned out to be already true.

**Fusion was never not there.** The audio compiler inlines every node into one
loop by construction — there is no per-node buffer to remove, because there
never was one. So the work in this phase was not fusing; it was the two things
the visual roadmap's fusion lesson actually asks for. The emitted loop is
annotated node by node and readable (`sourceFor(graph)` returns it), and every
node in the library is compiled on its own in the self-test, so a node that
will not build is found when it is written rather than when a graph uses it.
  - **The node-at-a-time fallback is not built, deliberately.** In the visual
    compiler that fallback existed because fusion was an optimisation over a
    working per-node path. Here there is no per-node path to fall back *to*,
    and building one purely as a safety net is a great deal of machinery for a
    case the compile check catches first. Said here rather than left as a gap
    someone finds later.

**Feedback works, and costs one sample.** A back edge — a wire from a node not
yet computed this sample — gets a state slot, is primed from it at the top of
each sample and written back after. A local would have lost it at every block
boundary and clicked 375 times a second. Measured with an impulse into a comb
built out of the graph itself: taps at **1.000, 0.700, 0.490, 0.343** against
g⁰…g³ exactly.
  - The round trip is **N + 1 samples**: the delay line, plus the one sample a
    back edge costs. That is a fact about the compiler, and the test states it
    rather than rounding it away.
  - The cycle rule from Phase A still refuses a loop with no delay, by name.
    It could silently insert the sample of delay a back edge already implies —
    and that would quietly turn the filter you designed into a different one.

**Voices are the graph N times.** `perVoice float` declares a value written
from outside, one per voice; state and delay buffers get a stride so each
voice has its own; the loop runs over voices and sums. Four voices produce
**peaks at 996, 1230, 1465, 1699 Hz**, exactly where each was told to sit, and
gating one off leaves another **bit-for-bit** what it is alone.
  - Initial per-voice values can be baked into the compiled processor, because
    an offline render cannot receive a port message — it would arrive after
    the render had finished. That is how the test sets pitches, and it is also
    what a preset wants.

**One more thing, off to the side.** The visual suite's preset probe randomised
its controls, and it failed once in this phase's runs on a preset where the
draw happened to change almost nothing. A check that fails once in twenty runs
teaches people to ignore failures, which costs more than the check is worth —
so `randomise` now takes a generator and the self-test seeds it. The suite
gives the same answer every time it is run.

### Phase D — Music on the graph *(L)* — **shipped**

- Instruments become graphs; the step sequencer drives note events into them.
- Per-track effect chains, the same node types.
- **Automation is the visual roadmap's keyframes**, with the same evaluator
  discipline: pure, in local clip time, and shared between the preview and the
  offline render so a bounce is reproducible.
- **Offline render** must be sample-exact and faster than real time, and must
  produce *the same file twice* — the audio equivalent of the frame-exact
  export, and the same test.

**Met.** `dsp-song.js` holds the song model and the bounce. The done-when
reads: **0.97 s rendered in 106 ms — 9.2× faster than real time — and the two
renders identical, sample for sample.** Nothing in the graph has a clock of
its own, so there is nothing left to vary.

Two decisions carry it:

- **Notes are scheduled, not messaged.** Every per-voice value became an
  AudioParam, so a note is `setValueAtTime(hz, t)`: sample-accurate, and the
  same whether it plays live or renders offline. A port message cannot do
  that — in an offline render it arrives *after* the render has finished,
  which is how the first version of this rendered silence.
- **Automation is the visual roadmap's keyframes, imported rather than
  reimplemented.** `evalTrack` from `video-graph.js`, the same function the
  video timeline evaluates a keyed grade with. A parameter moving over time is
  the same problem whichever studio asks, and two implementations would mean
  two answers to "what is it at 1.4 seconds". A cutoff keyed 8000 → 300 Hz
  drops the energy above 4 kHz from 1.38 to 0.080 of the energy below it.

Also in: **voice allocation** with the ordinary rule stated plainly — the
oldest sounding voice is stolen, because it is the one you are least likely to
still be listening to — and a **WAV writer**, checked by reading its own header
back. Every step sounds the note it was given, within 7.6 Hz against an FFT
bin of 23.4.

**The thread from the sequencer exists.** The Music studio has a
**Bounce (graph)** button: the active pattern, rendered through a compiled
instrument graph — voice → sine → state-variable filter — and downloaded.
Measured on an eight-note pattern: 2.5 s in 706 ms.

**Left in Phase D:** the studio still plays through its original sampled
synth; the graph engine is a bounce beside it rather than the thing you hear
when you press play. Per-track effect chains and an automation *editor* are
model-level only — the model takes them (a track is a graph, and a track's
automation is a keyframe list), and there is no UI for either yet.

### Phase E — What you can see *(M)* — **shipped**

The visual studios earn their trust by showing the numbers. The audio ones
should too, and this is where the two sides finally rejoin:

- **Scopes**: spectrum, spectrogram, oscilloscope, correlation, loudness to
  ITU-R BS.1770 with true-peak. Drawn by the *visual* pipeline — these are
  pictures, and there is a whole render graph for pictures already.
- **The analyser reads the audio graph's own taps**, so what is measured is
  what will be exported, exactly as the video scopes read the composited frame.

**Shipped, and this is where the two roadmaps meet.** A spectrum is a picture,
and the app has a render graph for pictures — with a schema in a comment,
fusion, ejection, and a self-test that holds every node to a number. So a
scope is not a bespoke canvas routine: `scope.spectrum`, `scope.wave` and
`scope.correlation` are **render-graph nodes** like any other, taking the
packed analysis as a texture. `audio-scopes.js` computes and packs;
`scope-nodes.js` draws; neither does the other's job.

**The measurements, each against the standard rather than against itself:**

- **Loudness reads BS.1770's own calibration point exactly.** 997 Hz at
  −20 dBFS on both channels measures **−20.00 LUFS**, which is what the
  standard says it must be, and halving it moves the meter **6.02 LU** — so it
  is calibrated as well as linear. The K-weighting is re-derived from the
  analogue prototype at whatever rate is in use, rather than reusing the
  48 kHz coefficients the standard prints, which is the usual bug. Both gates
  are in: absolute at −70, then relative at −10 below what survives.
- **True peak catches what a sample peak cannot.** A full-scale sine at a
  quarter of the rate, offset so no sample lands on the crest, reads
  **−3.01 dBFS** on a sample meter — three decibels of headroom, apparently —
  and **+0.10 dBTP** true. It would clip a converter. Four-times oversampled
  with a windowed sinc, as the standard asks.
- **Correlation**: +1.000 identical, −1.000 inverted.

**The tap.** The processor keeps a pool of buffers and hands one over when it
fills, so the scopes read the samples the graph actually produced — the same
rule the video scopes follow with the composited frame. Without
`SharedArrayBuffer`, which needs a cross-origin isolation this app does not
have, a copy per chunk is the best available; it happens outside the sample
loop, and the pool exists so no allocation happens on the audio thread at all.

**One thing the check found**, which is the sort of thing these tests are for:
the spectrum packer took a *point sample* per column, and at the top of a log
axis adjacent columns skip bins — so a narrow peak fell straight through the
gap and vanished. Each column takes the loudest bin it covers now, which is
what every real analyser does and why.

**Left in Phase E:** the spectrogram, which wants a scrolling history and is
therefore a feedback sketch rather than a plain node — the Generate studio has
`prev()` and it would be a good demonstration. And there is no scopes *panel*
in the Music studio yet: the nodes and the measurements exist and are tested,
but nothing on screen shows them.

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
