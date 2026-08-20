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
| node types registered | 67 | 17 |
| fusion | runs of per-pixel nodes → one pass | inlined by construction |
| what a wire carries | pixels, or a distance function | a sample, or a block |
| a wire pointing backwards | last frame, in a half-float texture | last sample, in a state slot |
| the hard constraint | a frame, ~16 ms; a miss stutters | a block, ~2.7 ms; a miss *clicks* |

And the machinery that feeds them: SVG → SDF and Design → SDF compilers, a
glyph atlas (exact Euclidean distance transform, MSDF), a font-file parser
(`glyf`, CFF Type 2, `cmap`, GPOS kerning, GSUB ligatures), a `.cube` LUT
reader, a store-only ZIP writer, a WGSL portability auditor, a small expression language for parameters, the
keyboard as a texture, an event queue, a content-addressed instrument
library, a WGSL emitter with a WebGPU runner for both a sketch and the whole
graph, and a **246-check self-test across 34 groups that runs inside the app**.

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
| the browser's two `arc()` fills, a field union | **0.30/255** |
| a circle offset by 0.1 vs a circle 0.1 bigger | **0 pixels differ at all** |
| the JavaScript engine, 19 parameter expressions | **exact**, worst disagreement 0.0 |
| Conway's Life, a glider, 12 generations, vs the CPU rule | **0 cells differ** |
| Gray–Scott, 30 steps in half float, vs the CPU stencil | **0.62/255** |
| a ship flown 80 frames by script, vs the CPU integration of its equations | **0.72 px** with its state in a texel; **2.0e−15** with its state in data |

Every number above is what the self-test reports on this machine today, not
what it reported when the feature landed — the two differ occasionally, because
a later phase changes something and the check re-measures rather than
remembering. The checks run in the app, not in CI, because the thing being
measured is a GPU and an audio thread on *this* machine.

### A port can carry a function, not only pixels

Everywhere else a wire is pixels, which is exact for colour and lossy for
geometry — a shape becomes pixels early and is a photo of a shape thereafter.
A **field wire** carries the distance function instead: `field.circle` emits
`float f3_field(vec2 p)`, and `field.union` emits a function that calls it. The
wire is a call; the graph's topology is the call graph.

It cannot work any other way. GLSL has no function pointers, so two distance
functions can only be combined by being written into one file together — which
means a field tree is never several passes, and the composition is a text
operation by necessity rather than by preference. The rest of the compiler
never learns fields exist: they are folded into one generated node type before
anything is planned.

The evidence that the wire really carries a *distance* is an identity nothing
rasterised can satisfy — offsetting a circle by 0.1 gives a circle 0.1 bigger,
to zero pixels of difference.

### A parameter can be a relationship

`radius` can be `ch("beat.radius") * 1.7` — a reference to another node's
parameter — or `0.2 + 0.2 * t`, or a keyframe track. That is the difference
between a document and a system: one number drives ten, and a shape stays
self-similar when you scale it rather than merely getting bigger.

The language is not JavaScript on purpose. `new Function` on a string out of a
saved document runs whatever the document says, and a document is data — so
`expr.js` is a tokeniser, a parser and a tree-walk, and the self-test reads the
file back and fails if `Function` or `eval` ever appears in it.

It resolves on the CPU before anything is planned, which is why it costs
nothing: by the time a value reaches a uniform it is a plain number, and the
shader cannot tell it was computed.

### The same answer to feedback, in both compilers

The audio compiler made a back edge a state slot: read before the sample is
written, written after. The visual graph now does the same with a frame: a
wire marked as reading *last frame* reads a half-float texture the runner
keeps between runs, and the node it points at draws into the other half of
the pair. That single mechanism — no special node — is Life, reaction–diffusion
and a motion trail, each held to a CPU implementation of the same rule written
one screen away from the sketch. Life comes out exact.

### Model, Update and View are all three readable

`prev("pos")` is a parameter as it was last frame; `key(38)` is the keyboard;
`on("keydown", 13)` is the event being delivered, and an expression that
mentions it runs once per event, in order, before the frame. With those, a
parameter that reads its own last value is a state, the expression over it is
the update, and the shader that draws the result is purely the view — and all
three are text in the document. A log of events plus the graph is a replay,
to the byte. And a model can *describe* what it wants the world to do —
`effects`, a note on a keydown, a hum level every frame — as data the host
performs. And the document says *what it sounds like*: a DSP graph is plain
data, so `graph.instruments` carries its own synths and each effect names
which one it is for. Fed frame by frame, the live rig produces the same
84 000 samples per instrument as the batch scheduler given the whole list —
and the instruments survive `JSON.stringify` and back unchanged, which is the
test that an instrument is really in the document rather than in the host.

An instrument's *identity* is a hash of what it sounds like, after its nodes
are renumbered in dependency order — so two built minutes apart are known to
be the same one, and a document may reference `inst.1xlq9ni` instead of
carrying it. A reference is an optimisation and never a dependency: a document
that carries the copy as well plays where the library has never heard of it,
and interning one is 92% smaller with the samples identical either way.

An instrument is authored as a **patch** — one line per DSP node,
`name = type key=value …` — which is a document like any other, so it
persists and every name in it is a part a document's effects can address.
Written out and read back, a patch is the same instrument; so is one built in
code. Identity deliberately excludes those names, because a name is not a
sound. The Studio page lists what the library has — each instrument once,
with its patch and three notes to hear it.

The Playground's pong is all of it in one document: fourteen parameters that
are the game, expressions that are its rules, a view that keeps nothing, and
three effects that make a noise on the game's own decisions — so a bat hit
cannot sound unless the game agreed it happened.

A *sketch* can be heard too, by a smaller route: it names texels of its own
state as **probes**, the host reads them back once a frame, and they become
the parameters of the one node a sketch has. Pong-in-a-sketch writes its
events into a third texel and the document names them — which is the whole of
what turns a shader's decisions into sound. The ship's position
is a number you can read off the graph, not a texel you have to decode; it
equals the CPU integration of its own equations to 2e−15, and the ejected
pass header prints the update beside the shader that draws it.

The dual the user named is then real in both directions: the graph says what
things are and how they change; the shader says how they look; field wires
let a pixel be asked which shape it is in. That is the position this thing
holds — not a more explicit website, but a document where meaning and
appearance are both readable and provably the same.

### One evaluator across media

Audio automation calls `evalTrack` from `video-graph.js` — literally the
function the video timeline uses to evaluate a keyed grade, and now also what
a keyed *parameter* on any node resolves through. A parameter moving
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
- **The keyboard as a texture** — Shadertoy's `iKeyboard`, and the whole
  tradition of games kept in a buffer's pixels. Copied on purpose.
- **Feedback buffers** — Shadertoy's Buffer A reading itself, every
  ping-pong sim since the 1990s. The only claim here is that it is a marked
  edge in a typed graph rather than a convention, and that it is measured.
- **Parameter expressions and channel references** — Houdini's `ch()`, which
  this borrows including roughly the spelling; After Effects expressions;
  Blender drivers.
- **Composing distance fields in a shader** — the whole of Shadertoy, and
  Substance Designer and Houdini's SDF tools at production scale. `smin` is
  iq's, and so is the exact regular polygon. What is unusual here is only that
  the composition is a *typed port in a graph* rather than something you write
  by hand, so a mis-wire is refused by name before any GLSL is generated.

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
- **Simulate, in the graph.** A node reads what it drew last frame; a seed
  field tree starts it; reset is forgetting. One draw per generation, and the
  ejected shader says which input is memory.
- **Play it.** The keyboard arrives as a texture, `u_keys`, and as `key()`
  in an expression. A ship whose state is data flies where its equations say
  to 2e−15; the same keys twice are the same model, byte for byte.
- **Compose geometry, not pictures of geometry.** Union, subtract, offset,
  shell, repeat and a smoothing radius between any two shapes — as wires, at
  full precision, ending in one draw. A glow is a falloff in distance, which
  is simply not available once a shape has become pixels.
- **Teach from the implementation.** 59 nodes link to the course module they
  belong with, and all 61 describe themselves — the reference is generated
  from their annotations and reports its own gaps.

---

## 6. What it is not, yet

Each of these is recorded in its roadmap with the reason, not left as a
surprise:

- **Colour management** — which is what gates wide-gamut P3 output.
- **The live audio path in the Music studio** — the DSP engine now plays live
  and is held sample-for-sample to its own bounce, but the Music studio's
  transport still drives the built-in synth rather than it.
- **Contextual-alternate shaping** (`calt`) and **WOFF2 outlines** — the second
  needs a Brotli decoder and its static dictionary, which is out of proportion
  to what it buys.
- **AI authoring of nodes** — the agents write briefs and critiques today.
- **A second backend, complete for the graph.** There is a WGSL emitter, a
  WebGPU runner and a WebGPU *graph* runner. Every node type in the catalogue
  translates: 53 render, **48 of them pixel-identical** to the GL path on this
  machine. The 11 refused are all field ports, which are compiled away into
  their shade node before a plan exists, so they never run as nodes. The
  render graph itself — a pool, fused runs, feedback kept between frames,
  several steps in a row, registers in 32 bits — is **identical on both
  backends** across seven shapes, including twelve generations of Life cell
  for cell and a ship flown forty frames. It shares the planner rather than
  reimplementing it, so a difference between the two can only ever be a
  difference in how a pass runs, not in which passes there are. The five nodes
  that render without matching agree exactly on every *opaque* pixel; what is
  left differs only where alpha is partial, which is the GL side being read
  back through a premultiplied canvas rather than a difference in the picture.
  Two places the backends genuinely part remain, both named with numbers: a
  hash amplifying one ulp through multiply-add fusion, and `p.y` at a height
  that is not a power of two. What is still GL-only is tiling, which lives at
  the studios, which all still draw through GL. Tiling works on both: a
  picture past what the device will render in one go comes back whole and
  byte-identical to the same sketch drawn in one piece.

The sketchpad-tier caveats in [`../README.md`](../README.md) still apply to the
studios as tools. This document is about the machinery underneath them.
