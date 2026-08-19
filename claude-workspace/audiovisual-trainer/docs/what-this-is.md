# What this is

*The two roadmaps — [`roadmap-glsl-target.md`](roadmap-glsl-target.md) and
[`roadmap-audio-target.md`](roadmap-audio-target.md) — record how the system
got here, phase by phase, with the numbers each phase was held to. This
document says what it **is**: the one idea underneath it, what is genuinely
unusual about it, what it lets you do, and what it is not.*

---

## 1. The idea

**The document is a graph. The text is its shadow — and the shadow can be read,
run, and put back.**

Every studio here edits a document. What runs is compiled from it: GLSL on the
GPU for anything you can see, one `process()` loop on the audio thread for
anything you can hear. The compiled text is never hidden, never a dead end, and
never a second source of truth — you can look at it, edit it, and hand it back
to the system as a new node.

A node is not a class. It is a **sketch**: text, with its contract in its
header.

```glsl
// Exposure, in stops, about linear light.
// @node adjust.exposure
// @module 05-display
uniform sampler2D in0;
uniform float stops;    // @range -4 4 @default 0 @help exposure in stops

vec4 c = texture2D(in0, uv);
vec4(linearToSrgb(clamp(srgbToLinear(c.rgb) * exp2(stops), 0.0, 1.0)), c.a)
```

That header is read by the control-panel builder, the graph compiler, the
fusion pass, the documentation generator and the node library. It is written
once.

---

## 2. What is actually here

Six studios — canvas, design, generate, music, shader, video — over roughly
28,500 lines of frontend JavaScript. No build step, no framework, no network.

Underneath them, **two compilers sharing one discipline**:

| | visual | audio |
|---|---|---|
| target | GLSL ES 3.00, with a 1.00 fallback | one `process()` loop on an AudioWorklet |
| a node is | a sketch with `@node` in its header | a sketch with `@node` in its header |
| node types registered | 41 | 15 |
| fusion | runs of per-pixel nodes → one pass | inlined by construction |
| the hard constraint | a frame, ~16 ms; a miss stutters | a block, ~2.7 ms; a miss *clicks* |

And the machinery that feeds them: SVG → SDF and Design → SDF compilers, a
glyph atlas (exact Euclidean distance transform, MSDF), a font-file parser
(`glyf`, CFF Type 2, `cmap`, GPOS kerning, GSUB ligatures), a `.cube` LUT
reader, a store-only ZIP writer, a WGSL portability auditor, and a **127-check
self-test across 19 groups that runs inside the app**.

---

## 3. What is genuinely unusual

Five claims, each with the evidence that makes it more than a slogan.

### The schema is a comment, and it reaches everywhere

`// @range 0 40 @default 4 @help blur radius in pixels` is the whole contract.
Twenty-five annotations are in active use. The *same grammar*, extended by
exactly three ideas — `state`, named `in`/`out` ports, and `@rate` — drives the
audio compiler, because a parameter with a range and a default is the same
thing whether it is a blur radius or a filter cutoff.

Nothing is declared twice, so nothing can disagree with itself. The node
reference is **generated** from these annotations, and reports its own holes: a
node with no description, or a control with no `@help`, shows up as a gap
rather than as a blank.

### The text is the shadow, and the shadow loops back

Every studio can show the GLSL it compiles to. That much is ordinary.

What is not: **Freeze** takes a fused stack of effects and turns it back into a
*node* — the dialled values baked in as `@default`s, a LUT in the stack carried
along as `@data` — saved as a Generate document, appearing immediately in the
effect menus of two other studios, and editable afterwards. Three effects
become one node that looks identical to 0.08/255.

Ejection is a cycle, not an exit.

### Every claim carries a number, against something nobody wrote for the occasion

This is the discipline the whole thing rests on. A node with no measurement
behind it is a claim.

| held against | number |
|---|---|
| 21 CPU filters vs their GPU nodes | 18 of 19 under **0.1/255**, seven exactly 0 |
| the browser's own compositor, 16 blend modes | **0.1/255** |
| the browser's rasteriser, a whole canvas document | **0.22/255** |
| the browser's rasteriser, a compiled design | **0.07/255** |
| the browser's own CSS filters, the video grade | **1.18/255** |
| the RBJ cookbook, typed out again in the test | **0.000 dB**, five forms |
| an additive band-limited saw | PolyBLEP **7.3–7.6 dB** better than naive |
| BS.1770's own calibration point | **−20.00 LUFS** |
| a delay line vs direct convolution | **2.98e−8**, which is float32 |

Every number above is what the self-test reports on this machine today, not
what it reported when the feature landed — the two differ occasionally, because
a later phase changes something and the check re-measures rather than
remembering. The checks run in the app, not in CI, because the thing being
measured is a GPU and an audio thread on *this* machine.

### One evaluator across media

Audio automation calls `evalTrack` from `video-graph.js` — literally the
function the video timeline uses to evaluate a keyed grade. A parameter moving
over time is one problem, so it gets one answer to "what is it at 1.4 seconds".

### The scopes are render-graph nodes

A spectrum is a picture, and there is a compiler for pictures. So
`scope.spectrum`, `scope.spectrogram`, `scope.wave` and `scope.correlation` are
nodes like any other, taking the packed analysis as a texture.

The audio roadmap's last phase is where the visual roadmap's machinery gets
reused wholesale. That is the strongest evidence the two disciplines really are
one discipline.

---

## 4. What is *not* novel

Worth naming, because the combination is the claim and the parts are not.

- **Node graphs for compositing** — Nuke, Fusion, Substance Designer,
  TouchDesigner, Blender. Decades old.
- **Documents compiling to GPU work** — Skia, and every modern 2D renderer.
- **SDF text and shapes** — Valve's 2007 paper. The multi-channel variant is
  Chlumský's algorithm, reimplemented here (and outlines had to be *recovered*
  by marching squares, because no browser will hand them over for a system
  font).
- **DSP graphs authored as text** — **Faust** has done this since 2002, and
  Gen~, SOUL and Cmajor all do it better and at far greater scale.
  `dsp-graph.js` is 431 lines; Faust is a research language with a decade of
  optimisation behind it. This is a teaching-sized thing that shares the shape.
- **Non-destructive layer effects** — Photoshop smart filters, 2007.

No individual technique here is new. What is unusual is the *combination and
the discipline*: one annotation grammar spanning two compilers and the
documentation; ejection that loops back; a measured number behind every node;
and the whole arrangement built so that a student can read the implementation
of the effect they just used — because the node's source, its documentation and
its course lesson are the same text.

---

## 5. What it allows

- **Filters that never bake.** A canvas layer's effects are a stack you can
  reorder, bypass, re-open and flatten on request. The stored pixels stay the
  original — verified: after two effects, what is saved is still the untouched
  image while the view shows the filtered one.
- **Write a sketch, get an effect.** Any Generate document with `@node` in its
  header appears in the Canvas and Video effect menus, with its controls, its
  help text and a link to the lesson it belongs with.
- **Freeze a look into a thing with a name** — self-contained, carrying its own
  LUT or glyph atlas, editable afterwards.
- **Eject a whole document** — layers, masks, blend modes, adjustment layers —
  as one chain of shaders that reproduces the composite to 0.22/255.
- **Render past the GPU's maximum**, byte-identically, in tiles. An 8192-square
  export runs in 64 tiles on a GPU claiming a 1024-pixel limit.
- **Reproducible exports.** A grade keyframed across a cut exports identically
  twice, frame for frame. A song bounces sample-exact, twice, about 9× faster
  than real time.
- **Teach from the implementation.** 35 nodes link to the course module they
  belong with, and all 41 describe themselves — the reference is generated
  from their annotations and reports its own gaps.

---

## 6. What it is not, yet

Each of these is recorded in its roadmap with the reason, not left as a
surprise:

- **Colour management** — which is what gates wide-gamut P3 output.
- **The live audio path** — the DSP engine bounces *beside* the built-in synth
  rather than being what you hear when you press play.
- **Contextual-alternate shaping** (`calt`) and **WOFF2 outlines** — the second
  needs a Brotli decoder and its static dictionary, which is out of proportion
  to what it buys.
- **AI authoring of nodes** — the agents write briefs and critiques today.
- **A second backend.** The WGSL audit says 41 of 41 node bodies are clean and
  the only obstacles are in the host's own text, so the door is verifiably
  open — but staying on GLSL ES 3.00 is the current decision, and WebGPU's
  compatibility layer is the expected route.

The sketchpad-tier caveats in [`../README.md`](../README.md) still apply to the
studios as tools. This document is about the machinery underneath them.
