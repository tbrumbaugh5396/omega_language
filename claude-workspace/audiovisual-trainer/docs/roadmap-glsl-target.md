# Roadmap — editing as authoring, GLSL as the target

*Written 2026-08-17, against commit `a20c35b`. This is the plan for turning the
studio from five editors that happen to share a codebase into one system in
which every edit that produces pixels compiles to GLSL.*

*What the system described here actually became — the idea, what is unusual
about it, and what it is not — is in [`what-this-is.md`](what-this-is.md).
This document is the record of how it got there.*

---

## 0. The thesis, and whether it makes sense

**The question:** should the studio move towards GLSL as *the* target — so that
editing in Canvas, Video, Design and Generate all becomes "GLSL updates"?

**The answer: yes — with one reframing that changes what gets built.**

GLSL is the right *compilation target* for everything that ends as pixels. It is
already how the serious tools work underneath: Photoshop's adjustment stack,
Resolve's node graph, Figma's renderer, Nuke, Substance — each keeps a
**document** (a graph of operations with parameters) and **compiles** it to GPU
programs to draw. Nobody edits the GPU code by hand as the primary
representation, because a shader is a lossy projection of the document: it
knows *what to draw this frame* but not *why*, not the history, not which
slider produced which constant.

So the goal is not "the editors edit a GLSL file". The goal is:

> **The document is a graph of operations. Every editor is a view that
> authors that graph. GLSL is what the graph compiles to — always regenerable,
> always visible, and editable in the one way that composes: a hand-written
> shader becomes a node in the graph, with its parameters introspected.**

That last clause is what we already proved in Generate: a sketch's `uniform
float k; // @range 0 40` line *is* a parameter schema. The uniform annotation
grammar is the bridge — it is how a hand-written node declares its controls,
and it is how every built-in node will declare its own. One grammar, both
directions.

Where the thesis stops, said plainly:

| Domain | GLSL as target? | What is the target instead |
|---|---|---|
| Raster pixels (Canvas, filters, grading, compositing) | **Yes** | — |
| Video (compositing, effects, transitions, grading, sims) | **Yes** — per frame | Time → uniform values (keyframes) |
| Generate (sketches, sims, 3D) | Already is | — |
| Design (vector shapes, layout, text) | **Partly** — rasterisation and effects yes; geometry no | Vector geometry stays vector; SDF export where shapes permit |
| Music / audio | **No** | An AudioWorklet DSP graph is the analogue; same graph discipline, different target |
| Document model, history, assets | **No** | Plain data; the graph *is* the document; GLSL is derived from it |

The payoff, once the graph exists:

- **Non-destructive everything.** An adjustment is a node; a filter is a node;
  moving a slider later just recompiles. This is the single biggest gap between
  the Canvas studio and Photoshop today, and it falls out of the architecture
  rather than being bolted on.
- **One effect library for stills, video and generative work.** A grade node is
  the same node whether it sits on a photo layer, a video clip, or after a
  simulation. Today there are three unrelated code paths (engine-image CPU
  filters, video per-clip grading, Generate helpers).
- **Everything ejectable.** Any layer, clip, or whole document can show "the
  GLSL this is", and that GLSL runs.
- **The course becomes live.** Every node links to the module that explains it
  — the blend node to Module 3, the dither node to Module 5, the tone-map to
  Module 5's transfer functions. The tool teaches what it does.

---

## 1. Where we are

Everything below exists and is verified as of `a20c35b`.

**Generate** (`studio-generate.js`, ~1,300 lines) — the prototype of the whole
idea:

- Sketch shorthand → full GLSL (`shader-uniforms.js: desugar`), one file with an
  `#ifdef SIM_PASS` section, editable directly in **GLSL mode**.
- **Uniform introspection**: `float`→slider, `vec2`→pad, colour-named `vec3`→
  swatch, `bool`→toggle, `int`→stepper, `sampler2D`→image/video picker;
  `@range/@step/@default/@color/@pad/@toggle/@label` refine. Reserved:
  `u_resolution u_mouse u_time u_seed u_prev u_state u_frame u_mouseDown`.
- **Feedback buffers** (`feedback.js`): float → half → byte negotiated by trying;
  ping-pong state; `sim()` pass; steps/frame; Restart.
- **Textures**: images and videos as assets with capability URLs; `<name>_size`;
  `coverUV/containUV`; videos seeked frame-exactly for offline render.
- **3D kit** injected when `scene(vec3)` is defined; finishing kit (ACES, sRGB,
  dither, vignette, grain, fresnel, `sky`).
- **Export**: PNG (2× supersampled), **MP4** (WebCodecs + our muxer, frame-exact,
  sims stepped per frame).
- **Bake** (values → `@default`), **Randomise**, presets (22).
- **`shader-run.js`**: render any sketch offscreen to a canvas; one shared
  context; programs cached by source.

**Canvas** (`studio-canvas.js`) — layers, masks, blend modes (browser canvas
compositing), selections, transform, text, brushes, 21 CPU filters
(`engine-image.js`), **shader filters** (any image-taking Generate sketch, via
`shader-run`), undo, grid. Filters **bake** pixels — the destructive gap.

**Video** (`studio-video.js`) — multi-track, trim/split, per-clip grading,
transitions, titles, frame-exact MP4 with mixed audio. Effects are CPU/2D.

**Design** (`studio-design.js`) — SVG vector editor; export SVG/PNG.

**Shader** (`studio-shader.js`) — Book of Shaders sketchpad; introspected
uniforms; images; grid; no feedback.

**Music** — Web Audio; out of scope for this roadmap except where it feeds video.

What is *not* here yet, and matters for the thesis:

- No operation graph. Layers are canvases; filters are functions; the "why" is
  lost the moment Apply is pressed.
- WebGL1. Float rendering, `fwidth`, integer textures, MRT and `texelFetch` are
  all extensions or absent. This is the single most limiting platform decision
  and should be reversed early (§6).
- Three unrelated effect implementations (CPU filters, video grading, Generate
  helpers) that will drift.
- No colour management: the compositor works in encoded sRGB (as browser
  canvas does); Generate scenes work in linear and `finish()`; the two meet
  nowhere.

---

## 2. Target architecture

### 2.1 The render graph

A **document** is a directed acyclic graph:

```
Node {
  id, type,                    // "source.image", "adjust.curves", "filter.blur", "custom.sketch", "sim", "composite.blend", …
  params: { name: value },     // typed by the node's schema
  inputs: [nodeId | null],     // textures in
  keyframes?: { name: [{t, value, ease}] },   // video: params as functions of time
  bypass: bool
}
Graph { nodes, output: nodeId, size, colourSpace, assets }
```

A **node type** is a GLSL template plus a schema. The schema **is the uniform
annotation grammar** — a node type is literally a sketch:

```glsl
// node: adjust.exposure    module: 05-display §5.4
uniform sampler2D in0;
uniform float stops;      // @range -4 4 @default 0 — exposure
uniform float offset;     // @range -0.2 0.2 @default 0

vec4 c = texture2D(in0, uv);
vec4(c.rgb * exp2(stops) + offset, c.a)
```

Built-in nodes ship as such sketches. A user's Generate document that takes an
image is a node with no further ceremony (`custom.sketch`). **There is one
authoring format.**

### 2.2 The compiler

`graph → [passes]`, where a pass is one fragment program drawing into one
target.

- **Fusion.** Consecutive *per-pixel* nodes (adjustments, blends, colour maps)
  fuse into one fragment shader: each node's body becomes a function; the
  chain is inlined. This is the difference between 30 fps and 300 fps on a
  twelve-adjustment layer stack, and it is what makes "GLSL for this layer"
  a single readable file.
- **Pass boundaries** at nodes that read neighbourhoods (blur, sharpen,
  edge, halftone cell), at feedback (`sim`), at resolution changes, and at
  nodes marked `@pass`.
- **Targets** from a pooled FBO allocator (`feedback.js` grows into it):
  half-float intermediates by default, float where a node asks (`@precision
  float`), bytes for the final display.
- **Program cache** keyed by fused source (already the pattern in
  `shader-run.js`).
- **Ejection**: any node, layer or the whole graph → the exact GLSL of its
  passes, with pass boundaries as comments. What Generate's GLSL button does
  today, generalised.

### 2.3 The two directions

- **UI → graph → GLSL.** Every slider, blend menu, mask stroke, keyframe edits
  a node's params; the compiler re-emits; the preview redraws. Immediate.
- **GLSL → graph.** A hand-written shader is a `custom.sketch` node. Its
  uniforms become params by introspection. It composes with every other node.
  It does **not** attempt to round-trip back into built-in nodes — that is the
  boundary, and it is a good one: the text is opaque, the *interface* is not.
- **Bake** is the bridge inside a node (values → `@default`); **Freeze** is the
  bridge across nodes (a fused chain → one custom node you now own the text of).

### 2.4 Where the pixels live

The question that decides whether "GLSL as the target" is honest: a shader
declares `uniform sampler2D mask;`, but the *bytes* of the mask are not in the
text. Can an image, a selection, a painted layer be "in the shader"? Three
ways, in increasing order of how much they change the model:

**(a) The sampler is the variable; the annotation carries the data.**
Already shipped as of this writing. A declaration may say where its pixels
come from:

```glsl
uniform sampler2D mask;   // @data data:image/png;base64,iVBOR…   (the bytes themselves)
uniform sampler2D photo;  // @asset /api/studio/assets/12/blob?k=…  (a pointer)
```

Still valid GLSL — it is a comment — so nothing downstream changes. The
loader (`buildControls`) fills the sampler from the source when nothing has
been chosen. **Embed** writes chosen images into the current source as
`@data`; the GLSL dialog can produce a self-contained eject. Verified: a
document created from embedded text alone, with no assets, renders its
picture. Cost: a PNG in base64 is ~1.37× its size in the text — fine for
masks and layers up to a few MB, wrong for a 4k photo, which should stay an
`@asset`. Inside the studio the doc keeps `@asset`; on export you choose.

**(b) Constant arrays.** GLSL ES 3.00 allows `const` array initialisers; 1.00
does not; both hit implementation limits at a few thousand values and compile
time grows badly. Viable for an 8×8 dither matrix or a 32×32 one-bit mask
packed into ints (ES 3.00 has bit ops), not for layers. A curiosity, not a
plan.

**(c) Compile the structure to math.** Most raster edits are *not* raster in
origin. A rectangle, ellipse or lasso selection is a shape — an SDF. A brush
stroke is a polyline with pressure — a capsule chain (`sdCapsule` per
segment, radius from pressure) or, for a soft brush, a sum of Gaussians along
the path. Feather is `smoothstep` on the distance. These become **code with
no data**, they compose with everything else in the graph, and they are
non-destructive for free — the stroke log the editor already keeps for undo
*is* the source. Limits: a few hundred segments per node before uniform
counts and per-pixel cost bite; beyond that (or once a layer is flattened
into freehand pixels) the node bakes to a texture and becomes case (a).
Text is the same story via an SDF glyph atlas, and is L.

So the rule for the graph:

- shapes, selections, strokes, gradients, text → **structure nodes** (math);
- photographs, videos, flattened paint → **texture nodes** (`@asset`, or
  `@data` when the file must stand alone);
- a structure node **may bake** to a texture node when it grows too large;
  a texture node never un-bakes.

This is what makes the thesis hold. The shader is not a lossy dump of a
bitmap; for everything that had structure, the shader *is* the structure.

### 2.5 Colour

One working space: **linear light, scene-referred**, in half-float
intermediates. Sources decode on entry (sRGB → linear, or the video's transfer
function); the output node applies the display transform (`finish()` today —
tone-map + sRGB encode + dither). Blend modes operate in linear unless a node
opts into encoded space for fidelity with legacy files (`@space encoded`).
This is Module 3 becoming policy.

---

## 3. Phases

Each phase lists deliverables, what "done" means (a test you can run), rough
size (S ≈ a session, M ≈ a few, L ≈ many), and dependencies. Order is by
dependency and by payoff.

### Phase 0 — Harden the foundation *(S–M, now)* — **shipped, `24fc41c`+**

What landed, against the list below: WebGL2 is the context everywhere
(`getGL` tries it first; the Generate, Shader and offscreen renderers share it
and one `linkProgram` that picks the vertex stage by the fragment's version).
A sketch emits GLSL ES 3.00 on WebGL2 — `#version 300 es`, `out fragColor`,
and two `#define`s that keep `gl_FragColor` and `texture2D` working so every
sketch, helper and Book of Shaders paste-in compiles unchanged — and 1.00
elsewhere; `aa()` uses `fwidth` under 3.00. Feedback storage negotiates float
via `EXT_color_buffer_float` with sized formats. `desugarMapped` carries a
line map from generated to sketch lines and `mapErrors` rewrites the driver's
log against it, so an error reads "line 3: … undeclared identifier" with the
offending sketch line under it. Schema v1 adds `@group @help @module` on a
uniform and a header block `sketchMeta` reads (`@node @module @pass
@precision @space`).

The self-test lives in the account menu ("Self-test the shaders"): every
Generate preset compiled for both passes and drawn, controls probed on the
non-feedback ones, every Shader preset compiled, and the two shape compilers
plus the glyph atlas run against the browser's own rasterisation with the
thresholds the commits reported. **Its first run caught a real regression**:
the joins commit had put a mitre wedge at every vertex of a flattened curve,
which took the SVG fixture from 2.33 to 5.70/255, and no hand check had
noticed. Fixed by skipping joins below ~12°; 40/40 now, on WebGL2 with float
state.

Not done from the list, deliberately: nothing.

The Generate stack is the seed of everything; make it load-bearing.

- **WebGL2 as the baseline** with WebGL1 fallback only for display. Float
  render targets become standard, `fwidth` arrives (a real `aa()`), integer
  and `texelFetch`, sRGB textures, MRT. `desugar` emits `#version 300 es` when
  available (`in/out`, `texture()`); a shim keeps `texture2D` and
  `gl_FragColor` working so existing sketches and Book of Shaders paste-ins
  do not break. *Done when:* all 22 presets and 11 shader presets compile
  under both; `aa()` uses `fwidth` on WebGL2.
- **Error line mapping** for sketch mode: subtract the generated preamble so a
  compile error points at the sketch line. *Done when:* an error on sketch
  line 7 reports 7.
- **A regression harness in the app**: the "Verify" tab gains a shader
  self-test that compiles every preset, renders each at 64×36, and checks
  non-flat output and control response — what has been done ad hoc in this
  chat, made permanent. *Done when:* one click reports pass/fail per preset.
- **Node schema v1** = the annotation grammar frozen and documented, plus the
  new keys the graph needs: `@pass`, `@precision`, `@space`, `@module`
  (course link), `@group`, `@help`. `parseUniforms` learns them; nothing else
  changes yet.

### Phase 1 — The render graph and compiler *(L; the keystone)* — **shipped**

`render-graph.js` is the model: `defineNode(sketch)` registers a node type
from sketch text — `sketchMeta` reads `@node/@module/@pass`, `parseUniforms`
gives inputs (`in0`, `in1`, …) and parameters, `@lut` marks a sampler the host
builds from a value, `@options` makes an enum. A graph is nodes with params
and input references and one output; `topo`, `validate`, bypass. Four proving
nodes: `adjust.exposure`, `adjust.curves` (256-entry monotone-cubic LUT from
points), `composite.blend` (eight modes, opacity), `filter.blur1d` (`@pass`;
two make a blur, same σ and kernel as the CPU reference).

`graph-compile.js` is the compiler: one pass per node into a pooled half-float
target on WebGL2, inputs bound as textures with `<in>_size`, LUTs uploaded and
cached by content, sources handed in by the host; `eject` returns every pass
as `{header, glsl}` and `ejectText` joins them. `renderGraph` and `applyNode`
run on a shared context.

**Parity, in the self-test** (Render graph group): exposure vs a JS reference
0.96/255; curves identity 0.00 and a black lift lifts; **blur 0.12/255 against
`engine-image.blurFast` at r=6, the same kernel**; blend multiply 0.02; the
four-pass chain ejects as 22 KB of GLSL and every pass links on its own.
The Canvas filter dialog offers the three single-input nodes as "Render graph
nodes (GPU)" — a first surface, still baking on Apply until Phase 2.

Two things worth remembering: `half` is a reserved word in ES 3.00 and not in
1.00, which the node found on WebGL2 first; and `@hidden` had only been
honoured on samplers.

**1.3, the catalogue** (`filter-nodes.js`): the 21 CPU filters as 20 node
types plus a `GRAPH_FILTERS` table that mirrors `engine-image.FILTERS` id for
id, each entry building its graph (`bloom` = bright-pass → blur → add; the
blur is two `filter.blur1d`). Every node was written from the CPU
implementation, not from memory of what the effect "is": the exact sRGB
transfer for grade, OKLab for hue/duotone, the CPU's Uint8 clamp on the
sobel intermediate, the same Bayer 8×8, the same prng structure for grain,
`round`-sampling in motion blur, the same 14 radial steps. Error-diffusion
dither stays on the CPU and says why (serial dependence). The self-test's
"Catalogue: CPU vs graph node" group runs all 21 at default parameters
against `FILTERS[i].fn` on a 160×100 picture with edges, gradients, saturated
colour and a dark region: **eighteen agree to under 0.1/255, most to 0.00**;
grain compares statistics (mean shift −0.09, spread 8.0 vs 8.1 wanted);
halftone compares tone after a 3 px soften (3.9/255) because the reference is
canvas-drawn and Skia's rasteriser is ±4% on ink at two-pixel discs — the
node's dot is π r² to a tenth of a pixel, so the node is the truer of the two.
The Canvas filter dialog lists all twenty as "… — on the GPU" with the CPU
filter's own parameter ranges and colours, so both paths get identical
controls; `applyFilter(canvas, entry, params)` is the one-call bridge. 66/66.

**1.4, fusion** (`graph-fuse.js`): a run of consecutive nodes without `@pass`
becomes one shader. Each node's sketch is turned into a function — its
declarations renamed `f0_`, `f1_`, … so two nodes may both own an `amount`
and both carry their own OKLab helpers — and the colour is passed from one to
the next in a register instead of a framebuffer. `planPasses` walks the
topological order and extends a run while the next node reads the tail, the
tail is read by nothing else, and the node's other inputs come from outside
the run (those stay real samplers, read at uv, which is how a two-input
composite fuses). Sources and bypasses draw nothing, so they no longer break a
run they merely sit between.

`@pass` is a promise about sampling, and fusion checks it rather than trusting
it: a node is left alone if it samples an input anywhere but `uv`, moves `uv`,
keeps state, or takes a host image. Beyond that, a fused program that fails to
compile falls back to a pass per node and logs why — **fusion can make the
picture faster, never different**. The fused text is itself a sketch, so
ejection shows the one shader the GPU was actually given (`{fuse:false}`
ejects the graph as written, for comparison).

**In the self-test** (Fusion group, 7 checks): five adjustments → 1 draw;
a blur in the middle keeps its two passes and the tail still fuses (5 → 4);
a two-input composite fuses with its second input as a texture; a curve LUT
survives; eight per-pixel filters → 1 draw; the fused shader ejects and links
with all three `apply()` functions in it; the four neighbourhood nodes decline
and say why. Every check compares against the same graph run one pass per
node and asserts on **what actually drew**, not on the plan — which is what
caught the first version: the carrier substitution ran on the first node of a
run too, so every fused program silently failed to link and fell back, and
the parity checks were comparing the fallback with itself. The surviving
differences (0.02–0.76/255) are the half-float intermediates the fused path
skips; it is the more accurate of the two.

Measured, seven adjustment nodes at 1920×1080: **14.4 ms → 1.4 ms, 10.4×**.
The Canvas filter dialog now states the real cost of each catalogue filter —
"1 draw", "4 draws" for bloom — which is the number a stack of them will add
up to when layers become subgraphs in Phase 2.

- `render-graph.js`: node model, schema loading from sketch text, validation.
- `graph-compile.js`: passes, fusion, FBO pool, program cache, ejection.
- Built-in node library v1, each as a sketch with `@module`:
  - **Adjust**: exposure, white balance (temp/tint), curves (RGB + per
    channel, as a 256-sample LUT texture), levels, HSL (hue/sat/lum per
    range), vibrance/saturation, colour balance, black & white mix, tone map,
    LUT (`.cube` → 2D atlas texture; 3D textures on WebGL2 later).
  - **Filter**: the 21 CPU filters re-expressed as GLSL nodes (blur family as
    separable two-pass; halftone/dither exist already as sketches).
  - **Composite**: blend (all 16 browser modes + linear variants, from the W3C
    compositing spec formulas), opacity, mask, clip.
  - **Geometry**: transform (matrix), crop, resample.
- **Parity tests**: for each ported filter, CPU (`engine-image`) vs GPU output
  differ by ≤ 2/255 mean; the CPU code stays as the reference and the drills'
  stimulus generator.
- *Done when:* the Canvas filter dialog runs every filter through the graph,
  and "GLSL for this filter" shows fused source that compiles.

### Phase 2 — Canvas on the graph *(L)* — **the structure shipped; four features left**

- A layer becomes a subgraph: `source → [effects…] → composite`. Adjustment
  layers, clipping masks and group layers become plain nodes. **Filters stop
  baking**: Apply adds a node; the layer panel shows a stack you can reorder,
  bypass, re-open. "Flatten" bakes on request.
- Selections and strokes become **structure nodes** (§2.4c): a selection of
  shapes is an SDF node; a stroke log is a capsule-chain node up to N
  segments, baking to a mask texture beyond that. Freehand pixel painting on
  a flattened layer stays a texture. Undo stays an op log.
- **Shader layer**: a Generate sketch as a live layer (generative fill,
  simulation, 3D) with its controls in the layer panel; time-driven if the
  sketch uses `t`.
- **Curves/Levels/HSL/Colour balance UI** with a histogram (GPU reduction on
  WebGL2; readback fallback).
- **Clone/heal** brushes (CPU; content-aware is out of scope and said so).
- **Eject document**: the whole layer stack as one shader chain; opens in
  Generate as a document with the layer bitmaps as image assets.
- Colour management on: sources decode, blends in linear, output transform.
  A per-document switch keeps old files rendering as before.
- *Done when:* a twelve-layer document with three adjustment layers renders at
  60 fps at 2k, every slider is live, undo/redo crosses node edits, and the
  ejected GLSL reproduces the composite within 2/255.

**Shipped.** `canvas-graph.js` holds a layer's effect stack: catalogue
filters, single nodes, CPU-only filters and Generate sketches, as plain data
that survives a reload. Consecutive graph entries are collected into one
graph before it runs, so fusion works across the boundary between one filter
and the next — duotone + vignette in a stack is a single draw. `surface()`
runs the stack then the mask, cached against the layer's dirty flag; a stroke
in progress goes into the pixels, so it goes in *under* the stack.

**Filters stopped baking.** The filter dialog's four result paths collapsed
into one candidate effect — so the preview is the layer, not the filter — and
Apply became Add effect / Update effect, with Bake alongside for when you
actually want pixels. The layer panel lists the stack with bypass, reorder,
re-open, flatten, and the GLSL it compiles to. Undo carries the stack.
Verified in the browser: after two effects, the *stored* pixels are still the
original while the view shows the filtered result.

**Adjustment layers** are a stack with no pixels under it, applying to
everything composited below, through a mask that a brush on the layer paints.
`render()` only pays for the accumulator when one exists.

**Shader layers**: a Generate preset or one of your own Generate documents as
a layer, its uniforms live in the layer panel, `t` scrubbable, effects and a
mask on top of it like any other layer, "rasterise" when you want to stop
editing it.

**The document compiles.** `composite-nodes.js` puts the browser's sixteen
blend modes in the graph, to the CSS compositing spec: separable modes through
B(Cb,Cs), the four non-separable ones through SetLum/SetSat, and the general
formula carrying straight alpha. That needed alpha to survive a pass, so
`@alpha` joined `@pass` in the header grammar — a sketch is opaque unless it
says otherwise, because the alpha of an expression that happens to end in a
texture read is rarely what the author meant. The graph premultiplies in
`present()`, the one place its convention meets the canvas's.
`documentGraph()` compiles background, layers, stacks, masks and blend modes
into one chain, and the canvas toolbar's **GLSL** button ejects it.

**Against the done-criteria**: all sixteen blend modes within **0.1/255** of
the browser's own composite; a document with a masked layer, a two-effect
stack and an adjustment layer at **0.24/255** (the bar was 2); every slider
live; undo crosses effect edits; twelve layers at 2048² with three adjustment
layers, composited, at **3.9 ms a frame** (the bar was 16.7). 76/76 in the
self-test, including a new "Canvas on the graph" group.

Fusion had been quietly discarding `@alpha` — every fused function forced 1 —
which the masked-layer parity check caught, and its renamer could emit
identifiers with two underscores, which GLSL reserves.

**Left in Phase 2**, four features that are independent of "layers are
subgraphs" rather than parts of it:

- **Selections and strokes as structure nodes** (§2.4c): a selection of shapes
  as an SDF node, a stroke log as a capsule chain. Today a selection is still
  a mask texture and a stroke is still pixels.
- **Curves / Levels / HSL / colour balance UI with a histogram.** The curve
  *node* exists and takes control points; what is missing is the editor for
  them and the GPU reduction behind it.
- **Clone and heal brushes** (CPU).
- **Colour management**: decode on input, blend in linear, an output
  transform, with a per-document switch so existing files keep rendering as
  they do. This one changes how every existing document looks, so it wants to
  be a deliberate piece of work rather than a rider on this one.

Group layers and clipping masks are also still to do; both are small next to
the four above.

### Phase 3 — Video on the graph *(L)* — **shipped**

- A clip is a time-varying source; its effect chain is the same node types.
- **Keyframes**: any param may have a track `[{t, value, ease}]`; the compiler
  evaluates to uniform values per frame. Curve editor in the timeline.
- Transitions as two-input nodes; titles as text-source nodes; **shader clip
  effects** (Generate sketches) — `shader-run.js` was built for this.
- **LUT node**, **scopes** (waveform, vectorscope, histogram — GPU on WebGL2),
  speed ramps (time-remap as a keyframed source parameter).
- Export stays frame-exact and offline; the graph is evaluated per frame;
  audio from Music muxes as today.
- *Done when:* a grade keyframed across a cut exports identically twice, and a
  Generate sim runs as a clip effect.

**Both halves of that pass**, and the group in the self-test says so: seven
frames of a keyed grade across a dissolve, rendered twice, byte for byte; and
the "ink stirred out of the picture" preset — a sim seeded by the clip, so the
same frame always comes out the same way — running as a clip effect.

**The frame is a graph.** The timeline used to composite with the 2D canvas
and grade with a CSS filter string. Both are exact things, so they compile
rather than get approximated: `filter.cssGrade` writes out the Filter Effects
matrices for brightness, contrast, saturate and hue-rotate, and a CSS blur is
three box blurs of the size the spec prescribes, so `filter.box1d` is that.
Against the browser's own filter string, worst **1.18/255**. A side effect
worth knowing: the blur is now in document pixels rather than preview pixels,
so the preview and the export blur by the same visible amount, which the
CSS-filter path never did.

**Keyframes.** Any parameter carries a track of `{t, v, ease}` in *local clip
time*, so a keyed grade survives being moved or trimmed. The evaluator is
pure and both the preview and the export call it, which is what makes an
export repeatable. A diamond beside every control keys it at the playhead;
moving a keyed control writes a key rather than a constant; the keys are
drawn on the clip; effect parameters key the same way. Eases: linear, hold,
smooth, in, out — chosen per track, not dragged on a curve (see below).

**A clip takes the same effect stack a layer does** — catalogue filters,
nodes, Generate sketches — and a **transition is a two-input node** living in
the overlap between two clips, so the outgoing frame is a real input rather
than something faded over: dissolve, wipe, dip to colour, push.

**LUTs**: `filter.lut3d` samples a cube laid out as a tile sheet, half a texel
in from each tile's edge so linear filtering never crosses one. `lut-cube.js`
reads a `.cube` including the two things that get it wrong in practice —
DOMAIN_MIN/MAX, which a log LUT moves, and 1D LUTs, which are widened into a
cube. The bytes travel in the document as base64, so a look is part of the
file. An identity cube changes nothing (0/255); a known channel rotation
matches the same thing done in JS (0/255).

**Scopes**: waveform, vectorscope and histogram, on the frame that was
actually composited, so what they measure is what will be exported. Rec. 709,
75% primaries boxed, the skin-tone line drawn, and a line of numbers for what
is crushed, what is clipped, and how far the channels have drifted apart.

**Speed ramps**: at a constant speed the source time is a multiplication;
keyed, it is the integral of the track, at a fixed step so the preview and the
export agree exactly. A 1×→3× ramp over four seconds covers eight seconds of
source — the mean rate, not either end.

**Titles compile.** `title-node.js` turns a title into a node whose glyphs are
a distance field carried in its own source: in the frame's ejected GLSL, sharp
at any export size, and a *shape* an effect downstream can read. It is opt-in
per clip, because two rasterisers never agree to the pixel — the compiled one
lands on the canvas one to 90.2% of its ink, after the browser was asked where
its "middle" baseline actually is (the middle of the em square, not half the
font's bounding box, which is four pixels at 64px).

To make that work the graph runner learned to bind a sampler a node carries in
its own source (`@data`) — roadmap §2.4's "the pixels live in the shader",
now true for graph nodes and not just sketches.

The video toolbar has a **GLSL** button: the frame at the playhead as one
chain of shaders. Export is unchanged and still frame-exact, because it calls
the same `renderAt` the preview does. 86/86.

**Left in Phase 3:** the keyframe UI is a list of tracks with an ease per
track and prev/next navigation — not the **draggable curve editor in the
timeline** the bullet asks for. The model is ready for it (per-key eases are
already stored per key); it is the editor that is missing.

### Phase 4 — Generate as the node authoring environment *(M)* — **shipped**

- **Save as node**: a sketch with `@node <name>` appears in Canvas and Video
  effect menus with its icon, group and help.
- Node library management (yours, presets, imported), versioning of node text.
- **Freeze**: fused chain → custom node.
- Multi-input sketches (`in0`, `in1` — mixers, transitions) and multi-output
  (MRT on WebGL2: a sim writing velocity and dye to two targets).
- Optional **graph view**: a visual editor of the render graph. Useful, not
  load-bearing; the layer panel is the graph view most people want.

**Save as node.** A node type has never been anything but a sketch with
`@node` in its header, so a user's Generate document with that line in it was
already one — all that was missing was for the app to go and look.
`node-library.js` is that looking: at boot it finds the documents that declare
a node, registers each under a namespaced id (`you.<name>`) so a built-in can
never be quietly shadowed, and proves it by drawing one 16×16 frame. A node
that will not draw stays in the list *with its error*, because "my node
vanished" is worse to debug than "my node says why". The document **is** the
node: editing the sketch changes it everywhere it is used, and the Studio page
lists what you have with its inputs, controls and module.

**Freeze.** A stack that fuses into one pass is one shader, so it can become a
node with a name: the dialled values are baked in as `@default`s, a LUT in the
stack travels with it as `@data`, and the result is saved as a Generate
document — so a frozen look can be opened and edited like anything else.
Verified end to end in the browser: two effects → one node with one input and
seven controls, and the picture byte-identical before and after.

**Versions.** A node other documents depend on is not a thing to edit without
a way back, so the text is versioned in the document — a ring of twelve, with
a diff that names the uniforms that moved — and the dialog says which
documents use the node before you change it.

**Multi-input and multi-output.** A sketch declaring `in0` and `in1` works as
an effect, the second picture chosen in the dialog. And `vec4 sim2(vec2)`
alongside `sim()` asks for a **second render target**: the sim pass writes both
at once and `state2()` reads the second back, so one simulation can keep a
velocity field and the dye being carried through it in four channels each
instead of squeezing both into one RGBA. MRT is core in WebGL2 and absent in
WebGL1, so under 1.00 the second pass is not emitted and `state2()` reads the
first — the sketch still runs, and `describe()` says which it got. Shipped
with a fluid preset that uses it.

**Graph view** — read-only, as the bullet allows. It shows what the passes
are, which of them fused (a dashed surround), where the textures come from and
what the whole thing costs. Building a wire editor for a document that is
nearly always a chain would be a large thing for a small return; this answers
the questions the layer panel cannot.

Three real bugs came out of building it. Fusion left a carried input's
`in0_size` as a uniform — the runner happened to set it, but a node registered
from the fused text got it as a control defaulting to (0.5, 0.5); a carried
input is always the size of the pass, so it is `u_resolution`. Freeze named
the stack's own input `f0_in0`, which is a name only fusion cares about, so
the frozen node declared no input at all — the graph view is what made that
visible. And `TargetPool` judged an allocation by `getError()`, which reports
the *oldest* pending error, so a failure somewhere else read as this
allocation failing; it drains first now.

**Left in Phase 4:** importing a node from a file is "paste it into a Generate
document in GLSL mode, then Save as node" — there is no drop-a-`.glsl`-here.
92/92.

### Phase 5 — Design meets the target *(M)* — **shipped**

SVG is the best case for §2.4c, because it is already structure: nothing has
to be recovered, only translated. Every primitive has a direct SDF —

| SVG | GLSL |
|---|---|
| `rect` (with `rx`) | `sdBox(p, half) - rx` |
| `circle` / `ellipse` | `sdCircle` / `sdEllipse` |
| `line`, `polyline` | capsule chain (`sdSegment`) |
| `polygon`, `path` M/L/H/V/Z | segments + winding sign; Q/C Béziers flattened adaptively (quadratics exact) |
| `stroke-width`, round caps/joins | `abs(d) - w/2`; a capsule chain gives round joins free |
| `fill-rule` | union / crossing-count sign |
| `transform` | inverse `mat3` on `p` before the shape |
| linear / radial gradient | `dot(p, dir)` / `length(p - c)` into a ramp |
| opacity, painter's order | the `mix` chain compositing already is |
| `clipPath` | `max(d, -dClip)` |
| CSS / SMIL animation | `t` |

— and the result is more than parity. SDFs are resolution-independent like
SVG, but they also say what SVG cannot: exact anti-aliasing at any zoom via
`fwidth`, offset by adding to `d`, outline as `abs(d) - w`, glow as
`exp(-k·d)`, morph as `mix(d1, d2, k)`, booleans as `min/max/smin`. A design
compiled this way is editable geometry inside the shader, and every control
Generate already has applies to it.

- **`design-to-sdf` — shipped** (`3e28c79`+): the compiler from the Design
  document model. Frame, rect (radius), ellipse, line, image (as `@asset` /
  `@data` sampler with cover mapping), nested frames, rotation about the
  centre composed through the tree, opacity multiplied down, multiply/screen
  blends, painter's order; each shape a named `s_*` function of `q` in frame
  pixels; three controls (inflate, outline, wobble) at zero for parity.
  Text is greeked as bars, and says so. **Parity: mean error 0.08/255
  against the browser's own SVG rasterisation of the same frame, zero pixels
  off by more than 40**, rotated nested frame and opacity included. The
  Design studio's **Shader** button opens the result as a Generate document at
  the frame's aspect.
- **`svg-to-sdf` — shipped**: an SVG *file* through the same emitter.
  rect/rx, circle, ellipse, line, polyline, polygon, path (M L H V C S Q T A Z,
  cubics and quadratics flattened adaptively by chord flatness, arcs converted
  to centre form and sampled), `g`/`use`/`symbol`/`defs`, the full transform
  list, viewBox with preserveAspectRatio, presentation attributes and inline
  style with inheritance, fill-rule nonzero and even-odd (signed crossings —
  one accumulator, since parity is shared), linear and radial gradients with
  objectBoundingBox and userSpaceOnUse units and href stop inheritance,
  clip-path, opacity/fill-opacity/stroke-opacity, `<image>` as a sampler,
  butt/square/round caps. Circles keep their exact distance rather than being
  polygonised. **Parity: mean 2.33/255 against the browser's own rasterisation
  of a file exercising all of the above, 11 pixels of 240,000 off by more
  than 50.** Generate's **SVG…** button imports one.
- **Dashes and joins — shipped.** `stroke-dasharray` and `stroke-dashoffset`
  are resolved by arc length at compile time, so each dash becomes its own
  polyline with its own caps — which is also why a dashed circle stops being
  a circle and goes through the polyline path. Mitre and bevel joins add the
  wedge on the outside of each turn, bounded by the two segments' own offset
  lines; `stroke-miterlimit` falls back to bevel. A join is a region rather
  than an offset of a line, so those strokes bake the width into the shape and
  paint like a filled outline — inflate and outline still act on them.
  **Parity on a scene of every join type, a mitre-limit fallback, four dash
  patterns and a stroked rect: mean 0.32/255, 132 pixels of 319,200 off by
  more than 60.**
- **stop-opacity — shipped.** A gradient with any translucent stop compiles to
  a vec4 ramp and its alpha joins the coverage rather than the colour; opaque
  gradients stay vec3, so the common case costs nothing. Parity on
  fade-to-transparent, a three-stop varying-alpha ramp, a radial glow and a
  gradient-stroked rectangle: **mean 0.26/255, zero pixels off**.
- **Kerning from the font — shipped.** GPOS's `kern` feature (pair lookups in
  both the specific-pair and class-pair forms, reached through extension
  lookups) and the legacy `kern` table. With a parsed font, advances come from
  `hmtx` and pairs from the font, so layout no longer depends on the browser
  having the family. Verified: Arial reads AV −74/1000 em and P. −129 from
  GPOS, Baskerville (inside a TTC) reads AV −120 from the old table, and a
  monospace correctly reports none.
  - Worth knowing: **that is also more accurate than asking the text engine.**
    Laying the same string out both ways and rendering against the browser's
    own SVG, font metrics scored 1.97/255 and canvas `measureText` 8.39 —
    canvas measurement and SVG shaping do not agree, and the font is the
    better authority.
- **WOFF2 — partial, and labelled as such.** It is Brotli-compressed and
  further transforms `glyf`/`loca`; the platform will not inflate Brotli, and
  carrying a decoder plus that transform is out of proportion here. A WOFF2 is
  therefore registered for *layout*, which browsers support natively, and its
  glyphs fall back to tracing. The loader says so in as many words rather than
  half-claiming support.
- **Known gaps, reported in the import notes rather than hidden**: CSS
  stylesheets and classes, filters, masks and patterns are ignored.
- **MSDF — shipped** (`msdf.js`), and the honest account of it. A single
  channel cannot hold a corner: it stores the distance to the nearest edge, and
  a corner's crease is lost to bilinear filtering. Chlumský's answer needs
  outlines, which no browser will give for a system font — so they are
  recovered: marching squares on the anti-aliased coverage (sub-pixel, and
  already better than the binary threshold), Douglas–Peucker, corners found
  over an arc-length window, edges coloured so neighbours share exactly one
  channel, and each channel storing the pseudo-distance of the edge nearest by
  *true* distance. In GLSL the sample is `med3(r, g, b)`.
  - **At 1:1 it is better**: a design's text region 2.17 vs 2.31/255, and
    pixels off by 60 down from 655 to 487.
  - **At 6× it draws sharp corners where a single channel rounds them** — but
    the reconstructed apex sits up to about one atlas pixel outside the true
    one, because the edges it meets were traced rather than read. Measured on
    one corner at 6.25×: single-channel loses 13 pixels of area to rounding,
    MSDF gains 45 by overshooting. Whole-string mean 5.44 vs 5.27.
  - So it is the default because normal sizes are the common case, and
    `{singleChannel: true}` remains for anyone who prefers the rounder,
    area-truer corner. Build cost roughly doubles (120 ms vs 59 ms for five
    glyphs); the atlas is RGB, so ~58 KB against ~20 KB.
- **True outlines — shipped** (`font-file.js`), which removes the tracing
  error rather than working around it. A font file is parsed directly: sfnt,
  TrueType collections and WOFF containers; `glyf` outlines (quadratic
  B-splines, implied on-curve midpoints, composite glyphs) and CFF (Type 2
  charstrings with local and global subroutines, the hint operators, and the
  four curve families); `cmap` 4/6/12, `hmtx`, `name`. The face is also
  registered with the document, so the browser lays the text out with the same
  font the outlines came from — the file gives the shapes, the text engine
  gives the positions, and neither guesses at the other. Load one with
  **Font…** in Generate; any text asking for that family compiles from it.
  Verified against the browser's own rasterisation of each glyph: the parsed
  outlines agree to within 0.3–0.65% of pixels.
  - **Corner area error at 6.25×: 61 (single-channel) and 66 (traced MSDF) →
    16 with true outlines.** Whole-string mean 3.70 / 4.23 → **3.09**.
  - Two bugs worth remembering. Merging corner detections by index is right
    for a traced outline and wrong for a real one, where consecutive vertices
    are all genuine corners — an 'H' collapsed from twelve to three. And a
    curve has to be flattened finer than the corner window, or its segments
    read as a sequence of sharp turns.
  - The magnitude-based error correction pass (median against the true
    distance, truth winning past a pixel) is what finally cleared the specks
    from serif letterforms. A sign-based version, tried first, never fired.
- **GSUB ligatures — shipped.** The `liga` and `clig` features, ligature
  substitution (type 4) and single substitution (type 1), through extension
  lookups. A **token** is now what one glyph draws — usually a character, but
  `fi` where the font has that ligature — and advances, kerning, outlines and
  the atlas all take tokens, so a ligature needs no special case anywhere
  except where it is resolved. On Avenir Next, "office flag" shapes to
  `o f fi c e / fl a g`, the atlas holds `fi` and `fl` as single glyphs, and
  the shaped line measures 311.68 px against 313.02 laid out per character.
  - Worth knowing for anyone testing this: **on macOS most families keep their
    Latin ligatures in Apple's `morx`, not GSUB.** A scan of every system font
    turns up very few — Arial's `liga` covers Arabic forms only; Georgia and
    Baskerville have none at all. So the self-test reads a GSUB table built by
    hand rather than depending on a font being installed.
  - **Still not applied:** chained contextual lookups (types 5 and 6), which is
    where `calt` lives. Those need a matching engine rather than a table read,
    and the families that depend on them are mostly scripts.
- **The strain case is handled.** Past the edge budget a shape used to be
  *dropped*, which is a visible failure. It bakes to a distance field now —
  rasterised, distance-transformed with the same exact EDT the glyph atlas
  uses, and carried in the source as `@data` — so the picture is always
  produced. It stops being editable geometry, and the import notes say which
  shapes went that way. **A 900-edge polygon at a 400-edge budget reads
  0.67/255 against the browser's own rasterisation**, 10 pixels of 90,000 off
  by more than 60.
- **WOFF2 outlines** stay out, for the reason above: Brotli needs a decoder
  and its static dictionary, which is out of proportion to what it buys here.
- **Effects on design layers through the graph — shipped.** A design node
  carries an effect stack. The geometry stays vector — this is a compile
  target, not a raster tool — but a blur or a grade is not geometry, and the
  graph is where those belong: the node's own subtree is rasterised on its
  own, the stack runs over it, and the result composites back in its place.
  Baking is asynchronous so the plain drawing stands in until it lands, and
  the raster is padded, because a blur does not stay inside the box the shape
  occupies.
  - That found a fault reaching well past Design. **Every node in the
    catalogue already computed a correct alpha** — `c.a`, `o.a`, the source's
    — and `desugar` was overwriting all of them with 1, because none of them
    said `@alpha`. Putting a blur on a design node turned its clear surround
    into an opaque box; the same fault would have eaten the transparency of
    any canvas layer you blurred. They all say `@alpha` now, and the two
    blurs premultiply, because blurring straight alpha drags whatever sits
    under the transparency out into the edge — which, with nothing behind it,
    is black.
- **Generate → Design** is not attempted (the boundary of §2.3 again).
- Effects on design layers through the graph.
- **Text via an SDF glyph atlas — shipped** (`glyph-atlas.js`). No font file is
  parsed: the browser rasterises each glyph at 96 ppem, an exact Euclidean
  distance transform (Felzenszwalb–Huttenlocher, linear time — not the usual
  8SSEDT approximation) turns it into a field, that field is halved to 48 ppem
  (which distance survives and coverage does not), and the glyphs are shelf-
  packed into the smallest power-of-two atlas. The atlas rides in the source
  as an `@hidden @data` sampler, so a compiled design is still one file.
  Positions come from `measureText` on growing prefixes, so kerning is the
  browser's own. Text costs one texture sample per glyph, each behind a tile
  bounds test. **Parity: a design's text region went from 38.2 to 2.31/255
  against the browser's own text rendering; an SVG with three families, three
  weights and all three anchors reads 1.65/255 overall.** And the point of
  doing it as distance rather than coverage: inflate, outline and wobble act
  on letterforms exactly as they act on every other shape.
- Where it strains: paths past a few hundred segments per pixel bake to a
  texture; `feGaussianBlur` and friends are pass boundaries, not per-pixel.
- Geometry stays vector in the Design document; this is a compile target, not
  a replacement for the vector model.

### Phase 6 — Platform and performance *(M, continuous)* — **decided and shipped**

- **WebGPU/WGSL as a second target** only if the node templates are kept
  small enough to translate; otherwise stay GLSL ES 3.00 and use WebGPU's
  compat layer when it lands. Decide at Phase 1 by keeping node bodies free
  of anything WGSL cannot express.
- Tile rendering for exports beyond the max viewport; FBO pool caps; program
  cache eviction; half-float intermediates by default.
- Export: image sequences (zip), WebM (VP9/AV1 via WebCodecs), MP4 with audio
  from the video studio's mixer for Generate too.
- Wide-gamut output (P3 canvas) once colour management exists.

**The WGSL question, answered with evidence.** `wgsl-audit.js` reads every
registered node type and reports what a translation would have to deal with:
no preprocessor, no function overloading, no loose uniforms, and no way to
pass a texture and its sampler as one thing. **37 of 37 node bodies are
clean.** The only obstacles are in the *host's* own text — four preprocessor
sites and four overloaded helpers (`palette`, `aa`, `_rgb`, `_rgba`) — and a
WGSL backend would emit its own versions of those anyway.

So: **stay on GLSL ES 3.00**, and use WebGPU's compat layer when it lands. A
second backend is a real body of work with no user-visible gain today, and
the condition the roadmap set for reconsidering — that the node templates
stay small enough to translate — is now a *checked property* rather than an
intention. One helper took a `sampler2D` as a parameter, the single thing in
the library WGSL has no form of; it reads `in0` directly now.
  - The checker deliberately does not flag mixed int/float arithmetic. Telling
    `float(x) - 1` from `int(x) - 1` needs types, and the first version
    reported five exponents (`1e-6`) as integer literals. A checker that cries
    wolf is worse than one that says what it cannot see.

**Tiling — shipped.** A render past the GPU's maximum is drawn in pieces.
Every tile is given the whole picture's resolution and its own corner, and
`gl_FragCoord` is shifted once in the prelude, so nothing downstream — not a
helper, not a node body, not a preset — has to know it happened. **A tiled
render is byte-identical to an untiled one**: rings, cells and the raymarched
beach, in twelve tiles each, not one pixel different. Generate offers 8192 and
16384 instead of refusing; an 8192 square renders in 64 tiles on a GPU
claiming a 1024px limit. A simulation still cannot be tiled — a sim reads its
neighbours and a tile's neighbours are in the next tile — and says so.
  - That exposed a bug that had been there all along: `usesFeedback` tested
    the *generated* source for `u_prev`, and every prelude declares it — so
    **every Generate PNG export had been falling back to the preview size**,
    whatever size was chosen. It asks the author's own text now.

**Caps — shipped.** The target pool holds eight (141 made and 132 released
over a full self-test, where before it grew without bound); fused programs
evict least-recently-used at 24; embedded textures at 16. Intermediates were
already half-float by default.

**Image sequences — shipped.** `zip-store.js` writes STORED rather than
deflated, because a PNG already is, with a fixed stamp so the same run
produces the same bytes. Verified against the system `unzip`: CRCs, sizes,
nested paths and the DOS timestamp all round-trip.

**What is left here, and why:**
- **WebM (VP9/AV1)** is not written. MP4 already comes out of WebCodecs
  through our own muxer; WebM would need a second muxer (EBML) for a
  container most tools accept less readily. The image sequence covers the
  "give me the frames" case that WebM was there for.
- **MP4 with audio for Generate** waits on Generate having audio to mux.
  The mixer belongs to the video timeline, and a sketch has no track.
- **P3 output** stays gated exactly where the bullet puts it: on colour
  management, which is Phase 2's remaining item.

### Phase 7 — What stays outside *(note)* — **written**

Audio does not compile to GLSL. The analogous move — Music as an AudioWorklet
DSP graph with the same schema discipline (`// @range` on parameters, nodes
authored as text) — is the right one, and it is a separate roadmap.

That roadmap now exists: **[`roadmap-audio-target.md`](roadmap-audio-target.md)**.
It starts by being clear about why it is not this document with different
words — a picture is a pure function of position and a sound is not, so the
target is a graph of stateful nodes rather than one expression — and then
carries over the four things this roadmap actually got its value from: the
schema in a comment, the document-is-the-graph rule, a parity number against
a reference nobody wrote for the occasion, and fusion. Its grammar adds
exactly three ideas to the one here: `state`, named `in`/`out` ports, and
`@rate`.

### Phase 8 — Field wires *(M)* — **shipped**

Until now every wire in the graph carried pixels. That is exact for colour and
lossy for geometry: a shape becomes pixels early, and from then on it is a
photo of a shape. You cannot ask a photo how far its edge is, so you cannot
offset it, round it, hollow it, or smoothly weld it to another one.

A **field wire** carries the distance function itself. A field node does not
draw; it emits

```glsl
float f3_field(vec2 p) { return length(p - f3_centre) - f3_radius; }
```

and the node downstream of it emits a function that calls that one. The wire
becomes a call, and the graph's topology becomes the call graph.

**The port is a prototype.** A field input is declared the way GLSL declares
any function it means to call — `float in0(vec2 p);` — which is both the
honest description and exactly the text that gets satisfied. Ports share one
namespace with image inputs, so `n.inputs[i]` means the same thing whichever
kind it is and nothing downstream had to learn a second convention.

**It has to be a text operation, and that is the whole design.** GLSL ES 3.00
has no function pointers and no first-class functions, so two distance
functions cannot be combined at run time by binding anything — only by being
written into one file together. So a field tree is never several passes:
`compileFields` rewrites the graph before planning, folding each field tree
and the node that shades it into one generated node type. Fusion, ejection,
the target pool and tiling never learn that fields exist.

**Sixteen nodes** (`field-nodes.js`): circle, box, ellipse, segment, polygon;
union, subtract, intersect, each with a smoothing radius; offset, shell,
transform, repeat, mirror, warp; and two ways to look at the result — `shade`
(glow under fill under stroke) and `contours`, which draws the field itself so
that a node returning something that is *not* a distance is visible rather
than merely wrong downstream.

**What it is held to.** The composition is judged by the browser's own
rasteriser, and the claim that the wire carries a *distance* is judged by
identities a raster pipeline cannot satisfy:

| held against | number |
|---|---|
| the browser's two `arc()` fills, hard union | **0.30/255** |
| the browser's `roundRect` | **0.06/255** |
| the same maths written as one sketch by hand | **0.21/255** |
| `offset(0.1)` of r=0.3 vs a circle of r=0.4 | **0 pixels differ at all** |
| `shell(0.1)` of r=0.4 vs (r=0.45) minus (r=0.35) | **0 pixels differ at all** |

Those last two are the ones that matter. Nothing that has become pixels can
pass them.

**Three bugs it turned up, all older than it.** `sketchMeta` gained a `field`
key but the pattern that reads the header was never extended, so `@field`
parsed as nothing. `desugar` read `vec2 p` inside a function's *parameter
list* as the sketch declaring its own `p`, and then neither declared nor
assigned it — every sketch with a helper taking `vec2 p` would have failed to
compile, and the naming conventions elsewhere had been quietly dodging it. And
the renamer that puts two sketches in one file matched on a word boundary
alone, so a node declaring a uniform called `x` would have had `p.x` rewritten
to `p.f3_x`; fusion had the same hole. The renamer is now one shared module
(`sketch-rename.js`) rather than a copy in each compiler.

*Left:* fields are 2-D only — the same machinery in 3-D is a raymarch loop in
the shade node and nothing else changes. There is no click-to-wire editor, so
a field graph is built in code, which is how every other graph in this app is
built (`documentGraph`, `frameGraph`, `graphFilter`); the graph *view* draws
field wires dashed and labels the nodes `@field`, but it still shows rather
than edits.

### Phase 9 — Parameter expressions *(M)* — **shipped**

A parameter was an array of numbers. It can now also be an expression, a list
of expressions one per component, or a keyframe track:

```js
radius: { expr: 'ch("beat.radius") * 1.7' }
size:   { expr: ["0.3", "0.3 / aspect"] }
stops:  { keys: [{ t: 0, v: 0 }, { t: 2, v: 1.5 }] }
```

`ch("node.param")` is Houdini's idea and roughly its spelling: a reference to
another node's parameter, by the name you gave that node or by its id. That is
the part that matters. Without it a graph is a pile of constants; with it a
graph holds a *relationship*, and one number drives ten.

**Not JavaScript, deliberately.** `new Function` on a string out of a saved
document runs whatever the document says, and a document is data. So `expr.js`
is a tokeniser, a precedence-climbing parser and a tree-walking evaluator —
about the size of the thing it refuses to use, and it can report which
parameters an expression depends on, which `new Function` cannot. The
self-test reads the file back and fails if `Function` or `eval` ever appears
in it.

**Resolved on the CPU, before anything is planned.** `resolveParams` runs
first, then `compileFields`, then `planPasses`. Three consequences, all of
them the reason for that order: the shader is untouched, so expressions cost
nothing at draw time and cannot interfere with fusion or field composition; a
parameter is a plain number by the time it reaches a uniform, so it is
inspectable and ejectable; and a field node, a filter and a keyed grade are
all served by one resolution without any of them knowing.

**What it is held to:**

| held against | number |
|---|---|
| the JavaScript engine, 19 expressions | **exact** — worst disagreement 0.0 |
| `ch("lead.radius") * 2` vs 0.4 typed in | **0 pixels differ at all** |
| `0.2 + 0.2 * t` at t=1 vs 0.4 typed in | **0 pixels differ at all** |
| a keyed parameter vs `evalTrack` itself | **exact**, four times |

The first is worth dwelling on: every one of those nineteen expressions means
the same thing in this language and in JavaScript, so the engine is an
independent implementation of precedence, associativity and arity — written by
somebody else, long before this. `2 ^ 3 ^ 2` is 512 and `-2 ^ 2` is −4 in both.

**Failure is not a black frame.** A cycle is detected and named
(`a.stops depends on itself`) rather than run out of stack. A typo falls back
to the value the node would have used and is reported; the check renders a
graph whose radius is the unclosed `wobble(3` and confirms it still draws the
circle.

**Ejection carries the source.** A pass header now says `written as: stops =
sin(t) * 2` beside the number it came out at, so reading the shader still
tells you what the graph meant, not only what it computed.

*Left:* the audio side still automates through `evalTrack` alone —
expressions do not reach a DSP parameter yet, though `expr.js` has no graph
dependency and is ready for it. There is no expression *editor*; a parameter
is written as an expression in the document, and the graph view shows it as
written rather than offering a field to type in.

### Phase 10 — Feedback in the graph *(M)* — **shipped**

The visual graph was a DAG. The audio one has had back edges since its Phase
C, where a wire pointing backwards becomes a state slot read before the
sample is written. This is the same move for pictures: a wire may point
backwards if it is marked as reading **last frame**, and what it reads is a
half-float texture the runner keeps between runs.

```js
const life = addNode(g, "sim.life", {}, [null, seed], { name: "life" });
feedback(g, life, 0, life);          // in0 is this node's own previous frame
```

**One mechanism, no special node.** Any node's input can be a feedback read,
of itself or of anything downstream — it is only a cycle if read *this* frame,
and reading last frame is what breaks the cycle. `topo` refuses a cycle of
this-frame edges by naming it and saying what to mark. A node something reads
back draws into its own memory rather than a pool target; the pair of targets
swap after each frame, and that swap is the whole of what "remember" means. A
graph runs `steps` frames in one call; `reset` forgets; `u_frame` counts.
Memory is keyed by the graph's `stateKey` and the node's name, so a graph
rebuilt from its document every frame still finds its own. Fusion, fields and
expressions never learn any of this: a fused run whose last node is read back
simply draws into memory, and the check that it does is in the test.

**Four nodes** (`sim-nodes.js`): `feedback.trail`, `sim.life`,
`sim.reactionDiffusion`, `sim.view`. The convention they share is that in0 is
last frame and in1 is a seed read on frame 0, so the graph that runs the sim
also starts it, and reset is nothing more than forgetting. The CPU
implementations of Life and Gray–Scott sit in the same file, one screen from
the sketches, so a change to a stencil is seen next to the other one.

**What it is held to:**

| held against | number |
|---|---|
| Life, a glider, 12 generations, vs the CPU rule | **0 cells differ** — and 5 alive |
| 7 steps in one call vs 7 separate renders | **0 cells differ** |
| after reset, vs the seed | **0 cells differ** |
| Gray–Scott, 30 steps, vs the CPU stencil | u **0.62/255**, v **0.24/255**, worst 2 |
| a trail after 20 frames vs 1 − 0.9²⁰ | **0.52/255** |
| a fused, remembered pass vs a pass per node | **0.01/255** |

Life is binary, so the bar is exact and it is met. The two continuous sims run
in half float for thirty nonlinear steps and land under a level.

*Left:* memory is one RGBA texture per node. The Generate sketchpad's `sim2`
has MRT — two targets, velocity and dye — and the graph does not yet; a fluid
wants it. Nothing in a graph reads the keyboard, so a simulation can be
watched but not played; that is the next thing between this and a game.

### Phase 11 — Input: a simulation you can play *(M)* — **shipped**

A shader cannot be handed an event. It can be handed a picture, and a picture
of the keyboard is 256 columns by 3 rows — one column per key code, and a row
each for *held*, *went down this frame* and *toggled*. That is Shadertoy's
`iKeyboard`, copied rather than improved on so that every sketch written
against it reads here unchanged. It arrives as `u_keys`, a reserved uniform
the host binds in every pass that declares it, and three prelude helpers read
it: `keyDown(u_keys, 39.0)`, `keyHit`, `keyToggle`.

`keyboard.js` owns the state and the canvas. A test presses a key by calling
`press(39)` and gets the same frame a person would — which is what makes a
game testable, and a replay exact.

**`game.ship`** is the proof: arrows turn and thrust, it wraps, and its
position, velocity and heading live in the texel at the bottom-left of its
own last frame — every other texel reads that one and draws. One texture
carries the game and the picture of the game, which is how Shadertoy games
have always done it. `input.keys` draws the keyboard texture itself, for
seeing that the host is really feeding keys. Life and reaction–diffusion now
listen too: space holds Life still, R reseeds both.

**The playground** (account menu → *Playground*) is the loop that makes "can
be played" a thing you do: a canvas, a Keyboard on the page, rAF, the graph
every frame with memory left alone between. Four demos, one tab each.

**What it is held to:**

| held against | number |
|---|---|
| a ship flown 80 frames by script, vs the CPU integration of the same equations | **0.72 px** apart |
| the same keys, the same game, twice | **0 bytes differ** |
| the keyboard texture: held / this frame / toggled through press, tick, release | **exact** |
| `input.keys` lit in the pressed column, all three rows, no other | **exact** |
| Life under space, two frames | **0 cells changed**; under R, the seed back **exactly** |
| `u_keys` through a fused program | **still bound by name** |

**Two things it turned up.** The ship's register drifted: 3 px off its own
equations after 80 frames, consistently, in half float. Measured directly,
this GPU's float→half conversion loses about **0.5% over thirty
accumulations** — not rounding noise, a bias — so `@precision float` in a
node's header now asks for a 32-bit memory, `game.ship` says it, and a check
runs the same accumulation in both and reports both numbers (half **0.53%**
off, float **0.012%**). And `codeOf` returned 0 for a real `ArrowLeft` that
arrived with a `key` and no `keyCode` — which is most of them now — so names
map to codes too.

**The trail was wrong.** `mix(fresh, prev, decay)` made this frame only 14%
present at decay 0.86, and a ship drawn through it vanished under its own
threshold. A trail is this frame at full strength *over* last frame faded;
fading is the alpha going down, not the colour darkening. Its check now asks
for exactly that: one frame of ink, twenty of nothing, the ghost's alpha is
0.9²⁰ to **0.00/255** and its red is still the ink's.

*Left:* no mouse in the graph (`u_mouse` is bound, but the playground does not
feed it), no gamepad, no sound on an event — the live audio path is the gap
between "a simulation you can play" and "a game", and it is an audio-roadmap
item.

### Phase 12 — Update as expressions: the model is data *(S)* — **shipped**

Phase 11's ship kept its state in a texel: position, velocity and heading in
the pixel at (0,0) of its own last frame. It worked, and it is how Shadertoy
does it, and it is exactly what makes "you can see what everything means"
false — the model had gone opaque, readable only by running the shader and
decoding a pixel somebody promised to lay out that way.

Two more things an expression can see fix that:

- `prev("pos")` — a parameter as it was resolved **last frame**; before there
  is a last frame, its written `value`, which is therefore the initial state
  and is written down as one.
- `key(38)`, `keyHit`, `keyToggle` — the keyboard, the same three rows the
  texture has.

A parameter that reads its own last value is a state; an expression over that
is a transition; and the shader that reads the result is then purely the
View. That is Model–Update–View with all three readable:

```js
turns:   { expr: 'prev("turns") + key(37) - key(39)', value: [0] },
heading: { expr: 'pi / 2 + ch("turns") * 0.09' },
vel:     { expr: ['(prev("vel", 0) + cos(ch("heading")) * 0.006 * key(38)) * 0.985', …], value: [0, 0] },
pos:     { expr: ['wrap(prev("pos", 0) + ch("vel", 0), aspect)', …], value: [0, 0] },
```

and `game.shipView`, which draws at `pos` facing `heading` and keeps nothing.
A bare `"turns"` means this node's own; a parameter the shader does not read
(`vel`, `turns`) is still a parameter — a model can carry a velocity the view
never draws. Last frame's values are kept per `stateKey` and advance **only
when the runner runs a frame**: a panel, a summary or an ejection that
resolves the graph to look at it does not move time. The runner re-resolves
each step of a multi-step call, and `reset` forgets this memory along with the
texture one.

**What it is held to:**

| held against | number |
|---|---|
| the data ship's state vs the CPU integration, 80 frames, read from the document | **2.0e−15** — exact, same doubles |
| the data ship vs the texel ship, drawn | **0.00 px** apart |
| `prev()` before any frame / after 1 / after 3 more in one call / after reset | 1.5 / 2 / 3.5 / 1.5 — **and looking twice does not advance it** |
| `key()`, `keyHit()`, `keyToggle()` vs the Keyboard | **exact**, all three rows |
| a replay of 50 frames, the model dumped | **183 bytes, identical** |
| the ejected pass header | carries `pos = wrap(prev("pos", 0) + …)` beside the shader |

Two consequences worth writing down. The texel ship needed `@precision float`
memory and drifted 0.72 px in 80 frames from rounding; the data ship is the
same arithmetic in the same doubles as the reference and drifts by nothing.
And the View node has no `@pass` and no memory of its own, so it **fuses** —
ship + trail is one draw where the texel version was two. Moving the state
into data made the view fusible.

*Left:* an expression is a per-frame map; there is no event queue, no
"between frames", no way to say "on the frame this key went down, do this
once and remember that it happened" except by arithmetic on `keyHit`. That
is enough for a ship and not for a menu.

### Phase 13 — Events: every one, exactly once, in order *(M)* — **shipped**

The keyboard texture says what is held *now*. It cannot say that two keys
went down between this frame and the last, or which went first, and at a low
frame rate it forgets a press. `keyHit` is a snapshot; a menu needs a queue.

**`events.js`.** An `EventQueue` of small records — `{ kind, code, x, y, t,
… }` — pushed in the order they happened. `keyboardEvents(queue, {keyboard})`
is one listener feeding both the queue and the keyboard texture, so the two
cannot disagree; `pointerEvents(queue, element)` reports a click in the
sketch's own `p` coordinates, so `field.circle` at `ev("x"), ev("y")` lands
under the finger with no conversion in the expression. A record is data; a
log of them plus the graph is a replay.

**Delivery.** The runner drains the queue once per frame and hands each event
to `resolveParams` on its own, in order, as an *event pass*: only the
parameters that **listen** — whose expression mentions `ev()` or `on()` — are
evaluated; everything else is held at its last value, so physics does not
step on a keypress. Then the frame is delivered as an event too,
`{ kind: "frame", dt }`, and everything is evaluated. That rule is what makes
"do this once when the key goes down, and remember" a line of arithmetic:

```js
index:    { expr: 'clamp(prev("index") + on("keydown", 40) - on("keydown", 38), 0, 3)', value: [0] },
selected: { expr: 'on("keydown", 13) ? ch("index") : prev("selected")', value: [-1] },
pulse:    { expr: 'on("keydown", 32) ? 0.0 : prev("pulse") + 0.03 * on("frame")', value: [9] },
```

`game.menu` is the view for the first two; the ship's pulse ring is the third
— held for thirty frames, it fires once.

**What it is held to:**

| held against | number |
|---|---|
| two keydowns delivered in one frame | the menu moved **2**; the texture's hit row saw **1** |
| Down,Enter vs Enter,Down | chose **1** vs **0** — order is meaning |
| 100 events in one frame vs the same 100 over seven | **100** and **100** |
| ten frames of thrust with 0 events a frame vs 5 | y = **0.371200** both — physics stepped once, not six times |
| `on("frame")` across three renders with a keydown between | **3**; `ev("dt")` **0.050 s** |
| a log of 17 events replayed into a fresh graph | **198 bytes of model, identical** |
| a click at the centre / top-right / bottom-left of a 2:1 canvas | **(0,0) / (2,1) / (−2,−1)** |

*Left:* events are delivered once per frame, in a batch — there is no
"between frames" with a different picture for each; an event's `t` is there
but nothing schedules by it. And nothing yet makes a sound on one: the live
audio path is still the gap.

### Phase 14 — The live audio path: an effect becomes a sound *(M)* — **shipped**

The DSP graph has bounced offline since audio Phase D, sample-exact and the
same file twice. It did not play live, and nothing in a picture could make a
sound. Both are one change, and the change is small because the pieces were
already the right shape.

**Effects.** A graph may carry `effects: [{ kind, when, …args }]`, every field
an expression. Elm calls this a `Cmd`: the model *describes* what it wants
done, as data with its arguments evaluated, and the host performs it. A `note`
whose `when` is `on("keydown", 32)` fires once per press with its pitch
computed from the model; a `param` with no `when` fires every frame and
carries a value. The same listening rule as parameters — in an event pass only
an effect whose `when` listens is considered. What fired comes back from the
runner (`onFired`), in order, and it is data: the same keys give the same
list.

```js
g.effects = [
  { kind: "note",  when: 'on("keydown", 32)', hz: '330 * 2 ^ (mod(ch("ship.turns"), 12) / 12)', dur: "0.35" },
  { kind: "param", node: hum, param: "level", value: 'ch("ship.burning") * 0.9' },
];
```

**The instrument.** `live-audio.js` runs the *same* compiled DSP graph on a
live `AudioContext` — `installGraph` already took any context — and performs
a fired list: a note is a voice's pitch and gate scheduled on and off, a param
is one `setValueAtTime`. The voice allocator takes notes one at a time by the
rule `allocateVoices` applies to a whole list, so for notes in time order it is
the same assignment. `ctx` may be an `OfflineAudioContext`, which is how it is
held to the bounce. The playground's ship has a sound switch; on, a pulse is a
note whose pitch follows how far the ship has turned, and the hum follows the
thrust.

**What it is held to:**

| held against | number |
|---|---|
| the effects a scripted flight describes, twice | **93 effects, identical** — 3 notes, 90 hum levels |
| the live instrument on an offline context, fed frame by frame, vs `renderSong` fed the same list as a batch | **84 000 samples, identical** |
| rms before the first press / in the four frames after it | **0.0** / **0.245** |
| hum during thrust vs idle | **0.725** vs **0.075** |
| three presses, two a frame apart | **3 notes, 0 voices stolen** |
| the live instrument's loop vs the bounce's | the same 93 generated lines |

One thing it found: `schedule()` sampled a *held* automation track on a grid,
and at the exact time of a key returned the previous key's value — one frame
late against a live `setValueAtTime`. Automation can now be `points`, set and
held exactly, which is what a live performance leaves behind; the parity check
went from 4.3e−4 to identical.

And one it found in Phase 11: the texel ship's replay check flickered by two
texels about one run in eight. `aa()` takes `fwidth()`, a derivative computed
across a 2×2 quad; the two register texels skipped the draw, so the two texels
sharing their quad took the derivative of a value their neighbours never
computed. Everything is computed now and the registers merely overwrite; 150
runs of 40 frames hash identically.

*Left:* the instrument is one graph, chosen by the host; a document does not
yet say which instrument its effects want. Events are performed at the frame
they arrived in, quantised to the frame — fine at 60 fps, audible at 10.

### Phase 15 — The document names its instrument *(S)* — **shipped**

Phase 14's effects made a sound, but the host chose what with: the playground
built a DSP graph in JavaScript and handed it to the player. A document that
cannot say what it sounds like is not whole.

A DSP graph is already plain data — nodes, wires, parameters — so it travels
inside the render-graph document the way a `@data` texture or a field tree
does:

```js
g.instruments = {
  blip: toneInstrument({ decayMs: 70 }),
  tone: toneInstrument({ decayMs: 420, gain: 0.9 }),
};
g.effects = [
  { kind: "note", instrument: "blip", when: 'on("keydown", 40) + on("keydown", 38)',
    hz: '880 * 2 ^ (-ch("menu.index") / 12)', dur: "0.08" },
  { kind: "note", instrument: "tone", when: 'on("keydown", 13)', … },
];
```

**Resolved at description time.** An effect that names no instrument is
resolved to the document's first — *in the fired list*, not by the host — so
the list that comes back says which instrument every effect is for and the
player never guesses. A name the document does not carry is reported once, by
name, with what the document does have. `LiveRig` installs what it is handed
and routes by name; it chooses nothing. A per-instrument `gain` lets a
document balance two without editing either one's DSP graph.

**What it is held to:**

| held against | number |
|---|---|
| the effects of a scripted flight, twice | **95, identical** — 3 to "ship", 2 to "bell", 90 hum levels |
| the rig fed frame by frame vs the batch scheduler, per instrument | **ship identical, bell identical** — 84 000 samples each |
| the bell's channel through the ship's first two notes | **0.0** — then 0.139 on its own note |
| the instruments through `JSON.stringify` and back | **identical, sample for sample** |
| an effect naming no instrument | resolved to `"first"` in the description |
| an effect naming `"tuba"` | *there is no instrument called "tuba" — this document has "bell"* |

The JSON row is the one that matters: an instrument that only worked because a
JavaScript object was still in scope would fail it.

**Why per instrument.** The first version of the parity check mixed both
instruments and compared one channel, and it failed by 1.19e−7 — and so did
the JSON check, for the same reason. Each instrument alone rendered
identically; two together did not. Summing two float32 streams is not
bit-stable between renders on this machine: the first disagreement was at the
sample the second instrument starts, at 2⁻²⁴. So each instrument now renders
to its own channel and is compared there. Mixed, the comparison measures the
browser's adder; per channel, there is no adder, and what is left is the two
schedulers — which is the thing the check is about.

*Left:* an instrument is written into the document inline, so two documents
that want the same one carry it twice; there is no library of instruments the
way there is of nodes. And the Music studio's transport still drives the
built-in synth rather than a named instrument.

### Phase 16 — The instrument library *(S)* — **shipped**

Phase 15 made every document carry its instruments, which made every document
whole and made two documents wanting the same sound carry it twice. The node
library solved that by saying *the document is the node* — nothing is copied,
because a node type is only ever a sketch with `@node` in its header.

An instrument has no header to name it with. What it has is its own data, so
**identity here is a hash of the instrument itself** — `inst.1xlq9ni` — and
"the same instrument" becomes provable rather than a naming convention two
people have to keep.

The obstacle is that DSP node ids come from a counter that never resets, so
two identical instruments built a minute apart read as `n32` and `n50` and
hash differently. `normalise` renumbers them `i0, i1, …` in dependency order
and sorts every key first. That is the whole trick, and it is why the id means
what it says. It also carries an instrument's own names for its parts — the
`hum` node a `param` effect writes to — through the renumbering, so a document
that *references* an instrument asks the declaration where the hum is rather
than assuming it knows.

**A reference is an optimisation, never a dependency:**

```js
{ ref: "tone.bell" }                       the library's, by name
{ ref: "inst.1xlq9ni", graph, noteNode }   the library's, or this copy
{ graph, noteNode }                        this copy, nothing else
```

A document that carries both plays on a machine whose library has never heard
of it. `internInstruments` turns copies into references, `inlineInstruments`
turns them back, and a document put through both is the same document.

**What it is held to:**

| held against | number |
|---|---|
| two identical instruments built 5 node-ids apart | graphs differ (`n32` vs `n50`), ids **the same** |
| one millisecond of decay | a **different** id |
| an instrument before and after renumbering | **44 000 samples, identical** |
| a document interned then inlined | **identical**, and **92% smaller** as references (674 → 55 bytes) |
| a carried copy after the library forgets it | **identical**; without the copy, *"which this library does not have and this document does not carry"* |
| two documents interning one sound | the same ref, and **the very same declaration** |

Four instruments ship named — `tone.blip`, `tone.bell`, `tone.pluck`,
`ship.classic` — each registered under its name *and* under what it sounds
like, so a document written elsewhere finds it either way.

The check that a carried copy survives the library forgetting it failed first
time, and it was the test's fault in an instructive way: it built the
reference-only document *after* forgetting, and interning had quietly put the
instrument back. Interning registers; that is what it is for.

*Left:* the library is in memory and rebuilt from the built-ins at load, so an
instrument a document interned is remembered for the session and not past it —
there is no place to keep one the way a Generate document keeps a node. And
nothing shows the library: no browser, no audition button.

### Phase 17 — The instrument document *(M)* — **shipped**

The library was in memory and rebuilt from its built-ins at every load, so an
instrument lasted exactly as long as the tab. The node library has never had
that problem, because *the document is the node* — and an instrument had no
document to be.

**A patch.** One line per node, `name = type key=value …`, where a value is a
number or `other.port`:

```
// A voice over a low saw whose level an effect can move.
// @instrument hum
// @voices 8

note  = voice.note
voice = osc.sineHz  hz=note.hz  gate=note.gate  amp=0.35
low   = osc.saw     hz=55  amp=0.18  blep=1
hum   = gain.smooth x=low.y  level=0  ms=60
out   = mix.add     a=voice.y  b=hum.y  gainA=1  gainB=1
```

`out` is what you hear and the `voice.note` is where notes are written, both
overridable by `@out` and `@note`. **Every other name is a part** the document
can address — `{ kind: "param", node: "hum", … }` — which is what makes a
*reference* usable at all, since the library renumbers what it stores. Parsing
never throws: a patch with a bad line yields the nodes that did parse and a
list of what did not, per line.

**The document type.** `instrument` joins the studio's kinds; the editor is a
text area, the errors, an audition keyboard and the id it registers under.
`ensureUserInstruments` reads those documents at boot and registers each — the
same arrangement, and the same three lines, as the node library's.

**What it is held to:**

| held against | number |
|---|---|
| the four starter patches | **all parse** — 3, 5, 5 and 5 nodes |
| every patch written out and read back | **every id unchanged**; 44 000 samples identical for the first |
| an instrument built in code, written as a patch and read back | **the same id** |
| a patch with three mistakes | **three messages, each with its line**, and the 4 good nodes still made a declaration |
| `{ node: "hum" }` through a reference the library renumbered | patch said `n165`, library says `i3` — **rms 0.410 while up, 0.000 after** |
| a saved document, loaded the way boot loads it | back as `saved.one`, **32 432 samples above silence** |
| a real document through the backend, forgotten and reloaded | back as `you.wobble`, 3 nodes, parts `note, env, out` |

Two things it found, both mine. The starter patches named `cutoff` on
`filter.svf` and `hz`/`feedback` on `filter.comb`; the parser said so before
they ever shipped, which is what a validating parser is for. And more
interestingly: **an instrument built in code and the same instrument written
as a patch had different content ids**, because a patch names every line and
`parts` was in the hash. A name is not a sound. Identity now excludes the
names — and when the same sound arrives better labelled than the one on the
shelf, the labels are kept.

*Left:* the patch has no way to say a per-voice value, so an instrument's
`voiceInit` is code-only. The editor has no waveform and no meter, and its
audition is eight buttons rather than a keyboard you can play. And nothing
lists the library — you reference an instrument by knowing its name.

### Phase 18 — The library, listed; and a game in Generate *(S)* — **shipped**

Two things left over, and a bug found by doing them.

**The library, listed.** A card on the Studio page beside "Your nodes": every
instrument once, whatever it answers to. The map holds each declaration under
its content id *and* under any name, so listing means grouping by the
declaration rather than by the key — otherwise every instrument appears twice
and neither row says the other exists. Each row shows where it came from
(built in, yours, or interned by a document while it ran), what it is made of,
the parts an effect can address, three notes to audition it, and its **patch**,
because an instrument you cannot read or hear is one you will not use. The
patch each row prints is checked to read back as that instrument.

**A game in Generate.** There were simulations to watch — Life, Gray–Scott,
the wave equation — and nothing to play, because `renderSketch` never bound
`u_keys`. It does now, on the one texture unit left between a sketch's own
images and its state, and the Generate editor attaches a keyboard to its
canvas (focused, so typing in the source does not steer the picture). The
`pong` preset keeps its ball, bat and score in three texels of its own state
and reads the arrows — the Shadertoy arrangement, playable here because the
sketch runtime now does what the render graph already did.

**The bug.** Driving the game found that it drew a nearly invisible ball and
the wrong colours, and the reason was old and everywhere: **`@color @default
#f4efe6` had never worked.** `annotations()` reads `@default` by taking
numbers, and a hex literal is not one — so every colour with a hex default
silently fell back to the four-colour palette meant for colours that declare
none. Sixteen declarations across the field, sim and game catalogues were
affected. `@default` now accepts a hex colour, and the game's ink went from
`#6c7348`-ish palette orange to the `#f4efe6` it asked for.

| held against | number |
|---|---|
| the listing, with an instrument under a name and an id | **one row**, every instrument once |
| every row's printed patch, read back | **every id unchanged** |
| the `pong` preset | declares `u_keys`, keeps state, **both passes link** |
| a one-line sketch reading `keyDown(u_keys, 38)` | **0** with the key up, **255** with it down |

*Left:* the game is a bat and a ball, not a demo of what a game *could* be
here — no sound, because a Generate sketch has no effects to describe. The
listing has no search and no way to delete. And the score is a stack of marks
rather than a number, because there is no text in a sketch.

### Phase 19 — Pong, with sound *(S)* — **shipped**

The Generate preset was a game you could play and not hear, because a sketch
has no effects to describe — effects belong to a render graph. So pong is now
a Playground document as well, and there everything the last several phases
built is in one place:

- the **model** is fourteen parameters on one node, written as expressions
  over `prev()` and `key()`;
- the **rules** are those expressions, and the intermediate decisions are
  parameters too — `hitBat`, `hitWall`, `missed` — because naming them makes
  the rules readable *and* gives the effects something to fire on;
- the **view** is `game.pongView`, which keeps nothing;
- the **sound** is three effects naming three library instruments.

```js
hitBat: 'ch("nx") < -aspect + 0.09 && abs(ch("ny") - ch("batY")) < 0.24'
velX:   'ch("missed") ? -0.024 : (ch("hitWall") + ch("hitBat") > 0 ? -prev("velX") : prev("velX"))'

{ kind: "note", instrument: "blip", when: 'ch("game.hitBat")',
  hz: '440 * 2 ^ ((ch("game.ballY") - ch("game.batY")) * 6 / 12)', dur: "0.07" }
```

The sounds are not a second copy of the rules — they fire on the game's own
decisions, so a bat hit cannot make a noise the game did not agree happened.
It is under the account menu → **Playground**, and it is the tab that opens.

| held against | number |
|---|---|
| played well vs not played at all | **3 blips, 3 bells, score 3, no thuds** vs **10 thuds, no blips, score 0** |
| the bell's pitch across a rally | **622, 659, 698 Hz** — one semitone a point |
| the same keys twice, 700 frames | **405 bytes of model identical**, 6 notes at the same frames and pitches |
| the rig fed frame by frame vs the batch bounce, per instrument | **identical** — 584 000 samples on each of 3 channels |

`key()` also stopped throwing when a graph is merely inspected. A panel or a
summary resolves a graph to look at it and has no hands; no keyboard now reads
as no keys held, the same rule `prev()` follows before there is a last frame.

Two failures on the way, both the test's own. The parity check printed
"identical" in its detail unconditionally while asserting on something else —
so it failed silently-looking, and the first fix was to make the sentence
report what was measured. It then said the worst difference was **0.00e+0**
while the samples compared unequal, which is only possible past the end of an
array: the live context had half a second of tail and `renderFired` defaulted
to a quarter, so twelve thousand indices read `undefined`. Same tail on both
sides, and an explicit length check, and it is identical.

*Left:* one bat, no opponent, and the score resets on a miss rather than
ending anything. The Generate preset is still silent — a sketch has no
effects, and giving it any would mean a sketch that is really a graph.

### Phase 20 — A sketch with a voice *(S)* — **shipped**

Last phase said a Generate sketch could not have effects because effects need
parameters and a sketch has none. That was true and not interesting: a sketch
keeps whatever it remembers in its own state texture, and the only thing
missing was a way to look at it.

**Probes.** A sketch document names texels of its own state:

```js
probes: { hitBat: { texel: [2, 0], channel: "r" },
          score:  { texel: [1, 0], channel: "g" } }
```

They are read back once a frame and handed to the ordinary evaluator as the
parameters of one node called `sketch`. From there everything a render graph
can do, a sketch can — `prev()` works because the readings are committed like
any parameter, `key()` works because the runtime binds the keyboard, and
effects fire:

```js
effects: [{ kind: "note", instrument: "blip", when: 'ch("hitBat") > 0.5',
            hz: '440 * 2 ^ ((ch("ballY") - ch("batY")) * 6 / 12)' }]
```

Bare names resolve against that one node — a graph may now say `effectNode`,
and a sketch says `sketch`, because there is only one thing an unqualified
name could mean. A render graph still says nothing, so a bare name there is
still an error that names itself.

**The sketch has to say what happened.** Pong kept its ball, bat and score in
two texels; it now writes a third holding *this frame's events* — hit the bat,
hit the wall, missed. A shader has no other way to tell anyone anything, and
naming those three texels is the whole of what turns a shader's decisions into
a document's sound.

| held against | number |
|---|---|
| a new document from the preset | carries **6 probes, 3 effects, 3 instruments** |
| played well vs not played, read from the probes | **score rose, never missed** vs **never hit the bat, score 0** |
| the effects those probes fired | **2 blips, 1 bell, no thuds** vs **5 thuds, no blips** |
| the rig fed frame by frame vs the batch bounce | **identical**, 579 200 samples × 3 channels |

The cost is named rather than hidden: `readPixels` stalls until the frame it
reads has finished. Six texels at sixty frames a second is small, and it is
the only way for a host to learn what a shader decided.

*Left:* a probe reports 0..1 on a byte target and its raw value on a float
one, so a document that reads a counter wants a float state — true here, and
not enforced. And the editor's sound needs the tab visible, because a paused
`requestAnimationFrame` reads no probes.

### Phase 21 — WebGPU, as a number *(L)* — **first pixels, and the rest named**

`wgsl-audit.js` has said since Phase 6 that the node bodies are clean and the
door is verifiably open. That was a text scan and an argument. This walks
through it: a WGSL emitter, a WebGPU runner, and the same sketch rendered by
both backends and compared pixel for pixel.

**What makes it tractable** is that the input is not arbitrary GLSL. It is the
sketch shorthand, and the prelude, the helpers and the coercions are the
*host's* text — `wgsl-emit.js` simply writes them again in WGSL. Only the
user's part is translated, by a short list of rules: `float x = …` becomes
`var x: f32 = …`, `vec3(…)` becomes `vec3f(…)`, `a ? b : c` becomes
`select(c, b, a)`, `texture2D(s, uv)` becomes `textureSample(s_tex, s_smp, uv)`,
`mod` becomes what GLSL means by it, and `if (c) x;` gains the braces WGSL
requires. Uniforms are packed one to a vec4 so nothing here implements WGSL's
alignment rules.

**What it is held to:**

| held against | number |
|---|---|
| the node catalogue, translated and rendered | **12 of 12 pixel-identical** to the GL path |
| the rest | 12 refused with a reason, 40 not translated yet |
| `p.x`, magnified until they part | identical to **2⁻²²** |

Twelve is not sixty-four, and the remaining forty are a *named* list rather
than a total: fifteen want a value the translator did not declare, eight a
declaration form it does not write, seven a call whose argument types it
cannot see. Each is a rule to add, not a question to answer.

**Two places the backends genuinely differ, and neither is the translator.**
A hash of a *constant* agrees exactly — both compilers fold it — while a hash
of a computed coordinate is 236/255 apart although its inputs are bit-identical:
that is multiply-add fusion, which a driver may do or not. And `p.y` at a
height of 28 differs from the eighth bit while at a height of 32 it is exact,
which places the blame on dividing by 28: one driver multiplies by the
reciprocal, the other divides, and 1/28 is not a binary fraction. Below 1/255
they agree, which is exactly why the catalogue comes out identical.

**The translator refuses rather than guesses.** A field port, a `discard` and
a preprocessor directive are each turned away with a reason. A translator that
quietly emits something plausible is found by a customer; one that says which
line it could not do is found by a test.

**Then the rest of them.** Twelve became **forty translated, thirty-six of
them pixel-identical**, by adding the rules the failures named — one class at
a time, measuring after each:

| what was missing | what it was |
|---|---|
| `<sampler>_size`, `gl_FragCoord` | provided at the entry point, from `textureDimensions` and the builtin |
| `vec3 a = X, b = Y;` | split into one declaration each |
| `step(0.5, a.rgb)` | widen on the *widest* argument, not the first |
| `sdCircle(…)` handed to `_rgb3` | a return-type table, so a distance is known to be a distance |
| `min(hp(a), hp(b))` read as a vector | component-wise builtins take the widest of their arguments, and an unknown call claims nothing |
| `float as = …` | WGSL keywords renamed |
| a sampler inside a loop | `textureSampleLevel`, which has no uniformity rule |
| `int mode` becoming `t mode` | `(?:in\|out\|inout\s+)?` was eating the `in` of `int` |
| a helper reading `uv` or a size | refused with a reason — it would need a signature change, which is a rewrite |

Two of those were found by the numbers going *down*: a refusal that matched a
helper's own parameter called `m`, and a "widen" that did not recognise its
own `vec3f(…)` and wrapped it until the parser gave up. Each was reverted to
the last measured state and redone.

And one wrong claim caught before it shipped: the detail line said the three
nodes that rendered-but-differed "each use a hash", and `game.menu` uses none.
They were `@alpha` nodes, and the GL side had been through `present()`, which
premultiplies. Comparing straight alpha against premultiplied measures the
host's convention rather than the translation — corrected, `game.shipView`
went from 145.8/255 to **1.1/255**.

*Left:* eight nodes still untranslated, in three named classes, and four that
render without matching. And one sketch to one texture: nothing about the
render graph — pooling, fusion, feedback, tiling — has a WebGPU path, and none
of it should until the pixels are known to match.

### Phase 22 — Three games that keep their world somewhere new *(M)* — **shipped**

Pong, breakout and the flyer between them show state in a register, state in a
row of texels and a course generated from a hash. These three each need
somewhere else to put a world.

**Snake — the grid the game walks on.** The snake is not a list: every cell of
the board is one texel holding how many more steps it stays body. Each step
every cell counts down and the head's cell is set to the length, so the tail
disappears by arithmetic and nothing remembers where it was. The fade along
the body is that same countdown, drawn — nothing extra is stored for it.

**A platformer — the level as a texture.** Rows 1 upward hold the world one
tile a texel, red solid and green a coin, generated once from a hash and then
written back unchanged, so it is somewhere the game *looks things up* rather
than something the shader recomputes. Collision is four lookups at the corners
of the player's box, one axis at a time so a wall does not also stop a fall.
A collected coin clears exactly one texel.

**Rover — a raymarched world you drive.** One distance function, a soft shadow
from a real occlusion march, ambient occlusion, a sky the ground picks up, and
the tone-map-and-dither finish. `scene()` is a pure function of a point and the
world is data — the rover's place and which beacons still stand come from the
state texture.

That last one had to be built twice. The first version read the state *inside*
`scene()`, which `march` calls about a hundred and fifty times a pixel: a
thousand texture fetches to draw one dot, and a GPU that stopped answering.
The fix is the rule: **a raymarched `scene()` must be arithmetic**, and
anything it needs is hoisted into globals the display body fills once. There
is a check for it, because the failure mode is a hang rather than a wrong
picture.

Two more things it turned up. The shorthand did not treat `vec4 gRover;` as a
declaration — only `const`, `uniform` and friends counted — so a file-scope
variable landed *after* the function that used it. A declaration with **no
initialiser** is unambiguous (it does nothing inside `main`), so it is one now;
`vec3 col = mix(…)` is still a statement. And the platformer spawned the player
inside a ledge, where the box could not move in any direction and the game was
a still photograph — the first stretch of ground is solid now, and the check
requires the picture to actually change.

| held against | number |
|---|---|
| snake, driven for 240 frames | changed on **14** frames (it steps every seven), **736** lit pixels |
| the platformer, running right and jumping | changed on **221** of 260 frames; reaches x=28 and **4 coins** |
| the rover, driving forward | changed on **89** of 90 frames |
| `scene()`, read for lookups | **0** — it is arithmetic |

*Left:* snake's fruit can land under the snake on the fourth re-roll and sit
there until the body passes; the platformer has no enemies and nothing to
fall into but the void; and the rover's beacons respawn only on R.

### Cross-cutting

- **Course integration — shipped.** Every built-in node carries `@module`,
  and the generated reference groups by lesson and links to it. Building it
  found four nodes tagged with slugs the course does not have
  (`01-light-and-exposure`, `07-motion`), so those links went nowhere; they
  point at real modules now and a check holds every tag to a module the
  course actually has. *Left:* "open in Canvas with this node" buttons on the
  course pages themselves — the link runs the other way so far.
- **Docs — shipped.** `node-docs.js` generates the reference from the
  annotations: the first comment line is what a node is, its uniforms are its
  controls with ranges and help, `@pass` and `@alpha` say how it behaves in a
  chain. Nothing is written twice, so it cannot go stale. Its first useful act
  was reporting its own holes — 10 of 33 nodes fully described — and those are
  filled, with the self-test holding the property rather than trusting it. The
  prose Help stays hand-written on purpose: it explains *concepts*, which no
  annotation carries.
- **Testing — shipped, with one thing deliberately not done.** Parity tests
  (CPU vs GPU, browser vs compiler), the in-app self-test, and the
  ejected-GLSL-reproduces-the-composite check are all in place: **102 checks**.
  *Golden images per node are not attempted*, and that is a decision rather
  than an omission — two GPUs disagree in the last bit, so a stored hash would
  fail on the wrong machine and teach everyone to ignore it. What a golden was
  *for* is checked instead: every single-input node draws, and repeats byte
  for byte. Being an identity at its defaults is reported, not failed, because
  a grade whose defaults did something would be a bad grade.
- **AI — not started.** The agents write briefs, shot lists and critiques
  today; authoring nodes and graph edits is the intended next step and nothing
  has been built for it. Critique stays non-ranking.

---

### Phase 23 — The last of the catalogue *(M)* — **shipped**

The eight became **every node type there is**. Six were compile errors and
five were refusals, and each named a rule:

| what failed | the rule that was missing |
|---|---|
| `for (…) for (…) stmt;` | where a statement *ends*, braces and nesting included, so an outer loop can be braced round an inner one |
| `step(vec3f(cut), lumaOf(c.rgb))` | an expression is as wide as its **widest operand**, and an operand that is a call of known return type says so — rather than being rummaged through for whatever vectors are inside it |
| `clamp(sm * x, 0.0, 1.0)` | a matrix times a vector is the *vector*; the matrix is the operator, not the width |
| `sdBox(…) - corner` given `_rgb3` | the same operand rule: a distance minus a distance is a distance |
| `step(0.5, tex(…).r)` | a swizzle says its own width off **anything**, not only off a bare name |
| a ternary split across lines | a statement ends at `;`, not at a newline — the else-branch was being cut at the line break |
| a helper reading `uv`, a size or a uniform | promoted to a module-scope `var<private>`, assigned once at the top of the fragment |
| `vec4 gState;` at file scope | module scope has no default address space, and *function* scope must not have one — the test is the brace depth, not the indentation, because a frozen node writes its function bodies against the left margin |
| `if (texel == vec2(1.0, 0.0))` | `==` on two vectors is a bool in GLSL and a vector of bools in WGSL; GLSL has `equal()` for the second, so a bare `==` always meant `all()` |
| `_rgb(vec4(c, 1.0))` in a frozen node | the GL prelude's own coercions, which are overloaded — one name per argument type, chosen after translation when the type is readable |
| `keyDown(u_keys, 37.0)` | WGSL cannot pass a sampler; `u_keys` is one reserved binding, so the argument is dropped and every read goes through one helper |
| `texture2D(in0, uv) * k` ending a sketch | a sketch may *compute* a vec4 as well as construct one — it keeps its colour and drops its alpha, as `_rgb(vec4)` does |

**Where it stands:**

| held against | number |
|---|---|
| the node catalogue, translated and rendered | **48 of 53 pixel-identical** to the GL path |
| what is left untranslated | **none** |
| what is refused | 11, every one a field port — which is compiled away into its shade node before a plan exists, so it never runs as a node |
| twelve rules, one small sketch each | all twelve pixel-identical |

**Two corrections worth keeping.** The comparison itself was wrong: it
premultiplied the WebGPU side and not the GL side, which measures the
difference between two storage conventions rather than the translation. Both
composited over black — the picture either backend actually shows —
`game.menu` went from 36.9/255 to **2.8/255** and `game.shipView` from
1.1 to **0.2**. And the keyboard is the one texture the GL path uploads
*without* `UNPACK_FLIP_Y_WEBGL`, so the WebGPU side must not flip it either;
flipping it swapped "held" for "toggled" and read 255/255 apart.

**A third place the backends appeared to differ — and did not.** This phase
reported `fwidth` as a third cause, alongside multiply-add fusion in a hash and
reciprocal-versus-divide in `p.y`: the same distance field 0/255 apart and the
same field through `aa()` 6/255, on edge pixels only. That was wrong, and
Phase 24 found out why — it was the emitter flipping `@builtin(position)`,
which gave the two sides opposite derivative signs. With the flip gone, `aa()`
and `fwidth` are both **0/255**. The reading was real; the explanation was a
guess that fitted it, and the fix for something else disproved it.

*Left:* still one sketch to one texture. Nothing about the render graph —
pooling, fusion, feedback, tiling — has a WebGPU path, and none of it should
until somebody needs it; the translation is now the part that is finished.

### Phase 24 — The render graph on WebGPU *(L)* — **shipped**

`webgpu-graph.js`: a pool of textures, a pipeline per node type, fused runs,
feedback kept between frames, several steps in a row — the same list as the GL
runner, on the second backend.

**The design decision that matters is what is *not* in the file.**
`resolveParams`, `compileFields` and `planPasses` are imported, not written
again. Nothing in the WebGPU runner decides what to draw. That is why the
self-test can assert that both backends produce *the same plan*, and why a
difference between them can only ever be a difference in how a pass is
executed — never a disagreement about which passes there are.

| held against the GL runner | number |
|---|---|
| one node, one draw | **identical** |
| three nodes fused into one draw | **identical** |
| two spatial passes with a buffer between them | **identical** |
| a two-input composite | **identical** |
| a node carrying a lookup table | **identical** |
| Life, twelve generations of ping-pong | **0 cells differ**, and the glider is still a glider |
| a ship flown forty frames, state in `rgba32float` | **identical** |

**Three things the second backend does differently, and why.**

*One submission.* GL issues each draw as it is encoded; here every pass in a
frame goes into one command encoder and is submitted once.

*Bind group layouts written out rather than derived.* `layout: "auto"` builds
the layout from what the shader statically reads, so a binding the module
never touches is absent and a graph that binds it is invalid — the failure that
made forty-eight node types "refuse the draw" at once earlier in this work.
It also cannot express `rgba32float`, which is `unfilterable-float` and is
exactly what a simulation's register needs. Writing the layouts out fixes both,
and the target's format joins the pipeline key, because a module whose fragment
target says `rgba16float` cannot draw into a 32-bit texture.

*Formats instead of extensions.* `rgba16float` is renderable and filterable in
core WebGPU. The GL path negotiates for the same thing through
`EXT_color_buffer_float`, `OES_texture_half_float` and a byte fallback.

**One convention, found the hard way.** The emitter used to flip
`@builtin(position)`, so that a single picture came out the right way up. That
also made every *render target* the opposite way up from a GL framebuffer —
which nothing noticed while the only textures a sketch sampled were ones the
host had uploaded. A render graph samples what the pass before it drew, and the
first two-pass comparison came back 41.3/255 apart and **exactly 0 when
compared upside down**. The flip is gone: a target holds the picture the way a
GL framebuffer does, bottom row first, and the readback turns it up the right
way at the end — which is what `present()` does on the other side. The forty-
eight identical node types stayed identical through the change, and the five
that were not identical each got slightly closer.

**And what the flip was hiding.** With one convention throughout, the five
nodes that "render without matching" mostly stop: on every **opaque** pixel of
`game.menu`, `game.pongView` and `game.shipView` the two backends are exactly
equal. What is left differs only where alpha is partial — and that is the GL
side's round trip, not the picture: `present()` premultiplies into a canvas and
`getImageData` un-premultiplies on the way out, which at low alpha cannot
return the number it started from. The WebGPU readback never takes that trip.

So the honest list of places the two backends actually part is **two**, not
five: a hash amplifying one ulp through multiply-add fusion (`filter.grain`,
8.8/255), and `p.y` at a height that is not a power of two, where one driver
multiplies by the reciprocal and the other divides.

*Left:* a WebGPU path for the studios themselves — this runs the graph and
hands back a texture, and every studio still draws through GL.

### Phase 25 — Tiling on WebGPU, and the terrain as data *(M)* — **shipped**

**Tiling.** `renderTiledGpu` and `maxRenderSizeGpu`. The rule that makes a
tiled render *identical* rather than merely similar is the same one the GL path
uses: a tile draws at its own size while thinking in the whole picture's — the
resolution stays the whole picture's, and the origin says which piece this is.
The emitter now adds `U.origin` to the fragment position, which is the one line
that makes it work, and which only reads cleanly because Phase 24 removed the
flip: the origin is in the fragment's own frame, and both backends now count
that frame up from the bottom.

| held against | number |
|---|---|
| five sketches, nine tiles each, vs the same sketch in one go | **byte-identical** |
| the same, vs the GL path's own tiled render | identical but for the hash the two backends already disagree about |
| 8592×64 on a device whose limit is 8192 | 5 tiles, nothing clamped, `uv.x` sweeping 0→255 across the whole picture |

The GL version has a branch for a sketch that keeps state — a simulation reads
its neighbours and a tile's neighbours are in the next tile. There is no such
branch here, because there is nothing for it to do: this translator refuses a
`sim()` sketch outright, and a stateful sketch belongs to `webgpu-graph.js`,
which does feedback properly and does not tile at all. Refusing with that said
beats a branch that cannot be reached.

**The terrain as data.** The rover was still 16 fps on the user's machine — an
Intel HD 6000 — after the arithmetic pass of Phase 22b. Measured on that class
of GPU at 640×360:

| the ground is… | frame |
|---|---|
| four octaves and two, as arithmetic | 28.7 ms |
| three and two | 24.2 ms |
| two and one | 19.3 ms |
| **one filtered texture fetch** | **11.2 ms** |
| nothing at all — a flat plane | 11.1 ms |

One fetch costs what having no terrain costs. So the dunes are baked once into
the second state target and read back as a single filtered sample: **28.5 ms →
13.5 ms**, and the picture moves by 0.31/255.

This is the sketch's own lesson one step further, not a trick bolted onto it.
`scene()` already asked the state texture where the rover and the beacons were;
now it asks where the ground is, and it is still a pure function of a point.
The one place the map is not good enough is the **normal**: a bilinear map is
flat inside a texel and a flat normal is a facet, so `normal3` switches back to
the analytic sum — six calls a pixel rather than a hundred.

**And a rule this work had wrong.** Phase 22 shipped a check asserting that a
raymarched `scene()` looks *nothing* up. That was the right fix for the bug
that prompted it — reading the register texture nine times per call, a thousand
fetches to draw one dot — but the wrong rule, and it would have forbidden the
change above. A lookup is not the problem; a lookup *per thing in the world*
is. The check now says what it means: `scene()` and everything it calls may
make at most one texture read, and it must be the terrain map rather than the
registers.

**Where the rover ended up**, on an Intel HD 6000 at 640×360, one context, one
compile, the way the Playground runs: **367.6 ms → 13.5 ms**, 2.7 fps → 74 fps,
at full resolution. The render scale from Phase 22b is now headroom rather than
a requirement.

### Phase 26 — Filling the window, and the same care for the other 3D sketches *(S)* — **shipped**

**The button.** It puts the canvas and its overlay — the *stage* — on their
own. Doing so changes what a full-size render is, so the scale is asked again
from scratch rather than carried across: the render aims at the window with the
sketch's own aspect fitted into it, capped at 1920×1080, and the auto scale
then takes it to the budget. `fitAspect` is a pure function checked against
four cases, because "letterbox rather than stretch" is arithmetic and
arithmetic can be held to a number. (This shipped against the browser's
Fullscreen API; Phase 27 replaced that with filling the window, for reasons
recorded there.)

**And the other 3D sketches, measured before touching.** At 640×360: `still`
4.9 ms, `bounce` 9.3 ms, `ocean` 8.0 ms, `cloudscape` 14.3 ms, `beach` 6.8 ms.
None of them was the rover's kind of slow, so this was not another rescue —
but `bounce` had the rover's exact bug:

> `bounceY()` is a `mod`, a `sqrt`, a `log` and two `pow`s, and it depends on
> the time and nothing else. `scene()` called it three times, and `march()`
> calls `scene()` about a hundred and ten times a pixel. Three hundred and
> thirty evaluations a pixel became three.

**9.3 ms → 2.8 ms**, and while it was open the lighting was brought up to what
`still` already had — the sun, sky fill and a warm bounce off the floor,
fresnel with the sky in the surface, and a gloss that falls off at grazing
angles. The framing changed too: the old camera stood five metres back with a
wide lens, which put three small dots on a large floor. Technically the same
scene, and a worse picture.

`still` needed nothing — it was already the richest of them, and is where
`bounce`'s new lighting came from. `ocean`, `cloudscape` and `beach` have no
loop-invariant work in their marchers; a scan for calls inside `scene()` whose
arguments never mention the point found one more thing worth taking, in the
rover: `rot(-gRover.z)`, two sines and two cosines, rebuilt at every march step
for a heading that cannot change during a pixel.

### Phase 27 — The picture, filling the window *(M)* — **shipped**

`expand.js`. One button, ten places — seven studios, the Lab, the Playground
and every course figure — and what varies is only *what* expands and how it
wants the room — which a studio knows better than a shared file
does, so it hands over the element and says which.

| studio | the stage | fit |
|---|---|---|
| Generate | the render and its grid overlay | contain, and the render *grows*: it aims at the window and the scale is re-measured |
| Shader | the same | contain |
| Canvas | the layers composited, with the selection marquee | contain |
| Video | the frame at the playhead | contain |
| Design | the SVG surface | **fill** — a viewport with its own pan and zoom wants more room, not a bigger copy |
| Music | whichever view is up | **none** — a scrolling editor gets a bigger window onto the same thing |
| Instrument | the whole editor — patch, problems, keyboard | **none**, on the app's own surface rather than black, the patch area grown to fill the height |
| Lab | the lab's output canvas | contain, and it **re-renders**: every runtime here reads `canvas.width` on the frame it draws, so resizing the backing store is enough |
| Playground | the game | contain, at **layer 85** — it is opened from a modal and has to clear it |
| Course figures | the figure, caption and knobs | **refit** — a figure draws one canvas pixel per device pixel and must never be CSS-scaled, so it redraws at the new size |

**This was the browser's Fullscreen API for about an hour, and that was the
wrong tool.** What a studio wants is the *canvas* at the size of the window —
the tool bars and the panels out of the way. Taking over the whole screen is a
different thing, and one the browser already offers on a key of its own.

Asking for it the other way cost more than it bought. `requestFullscreen` can
be refused, and is, whenever the page sits in a frame that was not granted the
permission — measured: all seven buttons reported *"Permissions check failed"*
rather than working. It also fires its change event on the **document** rather
than the element, so every studio ever opened leaves a listener behind unless
somebody remembers to take it off.

Filling the window is `position: fixed; inset: 0` and a z-index, which no
permission gates and no listener outlives. It sits at **70** — above the sticky
header at 40 and the menus at 50, below the modals at 80 and the toasts at 90,
so a dialog still opens over the top of it.

**The stage moves into a backdrop rather than becoming one.** That is the
detail worth keeping. A studio's overlays — a selection marquee, a grid, a
crosshair — are positioned absolutely against the stage, so the stage has to go
on being the same box as the picture; make the stage fill the window and every
overlay lands somewhere the picture is not. So a backdrop is created, the stage
moves into it, and the stage is sized to the picture's shape fitted to the
window.

**Four things that only showed up once it could be watched**, which is the
point of the change as much as the permission was.

*A box keeps its margin*, and the margin comes off the size it is given:
Music's stage is a card with a rem underneath and sat a rem short.

*`position: fixed` takes the stage out of the flow*, so the page behind reflows
and puts you somewhere else on the way back — a placeholder holds the slot.

*"Contain" only ever shrank.* A lab canvas is 480×300 and a window is not, so
the first version put a small picture in the middle of a large black field.
Fitting means growing as well.

*A figure lifted its own cap and overflowed.* `fit()` measured `clientWidth`,
which counts padding — invisible while `maxWidth` capped the answer below it,
and the moment an expanded figure was allowed the full width the right-hand end
of every curve went missing.

**What the check is now.** It used to stub `document.fullscreenElement`,
because whether a request is *granted* is not something a test can decide.
There is nothing left to fake: the check expands a real stage, measures that it
fills the window exactly — with a margin of its own, which is the bug above —
confirms the placeholder, confirms there is a way out from inside that does not
depend on the button now underneath the picture, presses Escape, and holds
every style to coming back byte for byte.

### Phase 28 — An open world, and things to stand among *(L)* — **shipped**

A first-person world with no edge: terrain, a sea, four biomes, and a map of
the land that follows you. `world` in Generate.

**The whole design is one idea repeated.** `march()` calls `scene()` about a
hundred times a pixel, and an open world's terrain is a great deal of
arithmetic — so none of it happens there. One pass bakes a hundred and ninety
metres of land into the second state target, centred on wherever the walker is
standing, and `scene()` is a single filtered fetch. That is the rover's lesson
from Phase 25, and it is what makes the world *infinite* rather than large: the
map does not cover the world, it covers what you can see of it, and it is
rebuilt every frame from the world's own functions at your new position. Walk
four kilometres and it has been rebuilt fourteen thousand times. There is no
stored world to run out of.

The biomes are the same trick. Two low-frequency fields — how high the land
wants to be, and how wet — decide which height function shapes the ground,
which surface is on it, and how it takes the light. They are baked into the map
beside the height, so choosing a biome costs a fetch too, and the shading picks
up a *blend* of the ones nearby rather than switching at a line: a shore is sand
becoming grass over a few metres.

**One program, several looks.** A single view sees four biomes at once, so they
cannot be separate shaders — but they are separate functions and they read like
it: wind ripples in the sand, patches at field scale in the grass, strata in the
rock, long shallow drifts in the snow, and a sea with its own normal and its own
fresnel.

| held to | number |
|---|---|
| a frame at 640×360, Intel HD 6000 | **9.1 ms — 109 fps**, with trees, boulders and grass |
| the terrain alone, before any of that | 4.3 ms |
| `scene()`, `ground()` and `thingAt()` together | **two** texture reads, and no noise |
| four square kilometres at the origin | 42% sea, 18% sand, 22% grass, 18% rock, 1% snow |
| the same twenty and two hundred kilometres out | three different places, no two the same picture |

**Four things measured rather than assumed**, each of which had gone wrong
first.

*The origin was a hundred metres of open sea.* The world is a function rather
than a place, so where the land *is* is not known until something asks — the
walker now spirals outward until it finds ground comfortably above the sea.
The first version searched a hundred and twenty metres, which was plenty while
the continents were two hundred across and found nothing at all once they were
six hundred: every view for the first four hundred metres of walking was water.

*The continents were stepping stones.* At a wavelength of two hundred metres a
biome map is an archipelago you cross in ten seconds. Six hundred gives a
landmass that takes a minute, and a coastline you arrive at rather than fall
off.

*The detail was static.* A ripple whose wavelength is a third of a pixel does
not read as sand; it reads as fizz, and it crawls when you walk. One sample
cannot average what it cannot see, so every high-frequency term — normal and
pigment both — is faded toward its own mean with distance. That is what a mip
chain does for a texture and what nothing does for a function unless it is
asked.

*Snow was a sheet of paper.* Its albedo really is near 0.9, and 0.9 under a sun
at 2.35 is three stops over: the tone map hands back white with no shape at
all. It is carried by the specular instead, with drifts for form and the sky's
own colour in its shadows, which is what makes snow look like snow.

**Then things to stand among.** Trees, boulders and grass — and, as promised,
measured before they were written rather than after. Changing only `scene()`,
at 640×360:

| | frame |
|---|---|
| the terrain alone | 4.3 ms |
| + one more map fetch a step | 6.3 ms |
| + a whole tree: fetch, hash, three SDFs | **6.5 ms** |
| the same tree, skipped beyond forty-five metres | **7.4 ms** |

The last row is the one worth keeping. Guarding the scatter with a distance
test made it *slower* than not guarding it: the rays in a warp disagree about
which side of forty-five metres they are on, so the branch is paid for and both
sides run anyway. The fetch is the cost, and it was already the cheapest way to
know where the ground is.

So: **one grid, and the cell decides what grows there.** A tree where the map
says green, a boulder where it says stone, nothing in the sea — and both read
the *same texel*. The height a thing stands on and the climate that put it
there are one fetch, which is why two kinds of thing cost what one kind costs.
The whole scatter comes to 4.3 → 9.1 ms, still 109 fps.

Grass is not geometry and should not be: blades are a few centimetres across,
so they exist only in the shading, under a second and much shorter distance
fade than everything else. They are visible underfoot and gone by sixteen
metres, which is where asking for them would bring back the fizz this phase
already spent a round removing.

**Two more things that had to be measured.** The bark was 0.30 in sRGB, which
is 0.07 in linear, and a trunk lit from one side at 0.07 is a silhouette — the
world opened on what looked like a black wall. And the fix for opening *inside*
a tree overshot twice: checking the walker's own cell was not enough, because a
tree in the next cell can be a metre away; rejecting any candidate with a tree
in any of the nine cells around it walked out of the woods entirely and started
in a desert. What was wanted was three metres of clearance, so the spawn now
asks where the trunks actually are — the same jitter the scatter uses, so the
two cannot disagree.

*Left:* nothing that moves but the sea and the walker. No creatures, no
weather, and nothing to do — this is a world to be in rather than a game.

### Phase 29 — Weather, wildlife, and what an endless world costs to remember *(M)* — **shipped**

**Weather.** Wind and rain, both living in a register and drifting with time,
so the weather is something the world is *doing* rather than a slider you are
holding. The direction turns over minutes, the strength gusts, and a front
comes and goes — standing still for a while is a thing worth doing.

Wind bends the trees, and bends the top more than the bottom, which is the
whole of why a tree in wind reads as alive. Each has its own phase from the
hash that placed it, so a wood does not sway as one object. The same wind runs
through the grass as a wave travelling across the field, which is what a gust
looks like from above.

Rain is not particles and not geometry: four layers of streaks, each on a plane
at a fixed distance, sampled where the ray crosses it. Near layers are large and
sparse, far ones small and dense — that is parallax, and it is what stops rain
reading as a texture stuck to the lens. A whole downpour is four hashes a pixel.
It also takes the sun away, brings the horizon in, darkens the ground and makes
it shine, and most of what makes a wet day look like one follows from those.

*One bug worth keeping.* The first frame built the rain's coordinate frame from
`cross(fall, rd)` — which is perpendicular to `rd` by construction, so
projecting a point along the ray onto it gave **zero everywhere** and the
downpour was invisible. Measured rather than eyeballed: the rain lifted 0 of
275,800 pixels. The frame belongs to the rain, not to the ray. With that fixed
it lifts 17% of them.

**And what it costs to remember — which is nothing.** The worry about an
endless world is that walking through it fills memory with the places you have
been. This one cannot: it stores none of them. The world is a *function* of
position and the map is one fixed texture rebuilt every frame around wherever
you are, so there are no regions to load and none to unload. Four kilometres
costs exactly what standing still costs. The price of that choice is
recomputing the map, and Phase 28 measured that against the alternative.

What *did* scale badly was the state's **size**. It was the size of the
picture, because every sim's state always had been — so a fullscreen render
meant a 1920×1080 float pair with two targets, which is **132 MB** to hold a
dozen registers and a height map of a fixed piece of ground. Neither gets
better by being the size of the window.

So a sketch may now say `@state W H`:

| | state |
|---|---|
| the world at 640×360, before | 14.7 MB |
| the world at 1920×1080, before | **132 MB** |
| the world at any size, with `@state 448 448` | **12.9 MB** |

It is also eight times less to bake at fullscreen. The uniform `u_state_size`
comes with it, and two helpers — `reg(texel)` and `reg2(texel)` — because once
the state and the picture are different sizes, `state(uv)`'s division by
`u_resolution` is the wrong division in the display pass. In the state pass
`u_resolution` *is* the state's, so `gl_FragCoord.xy / u_resolution` still
sweeps 0..1 across it and every existing sim sketch is untouched.

| held to | number |
|---|---|
| a frame at 640×360, with weather | **11.9 ms — 84 fps** |
| the same bytes of state at 96×64 and at 480×270 | yes, and unchanged after walking |
| rain against no rain | 30/255 of a different picture |
| the wind moving things between consecutive frames | several times what still air moves |

**And something alive in it.** A herd on the ground and gulls over it, and the
two cost very different things for a reason worth writing down.

*The grazing herd is almost free* — measured at **0.4 ms** of the frame —
because it lives in the cell the terrain had already been asked about. The
height it walks on and the grass it is eating are the texel that decided
whether a tree grows there. It wanders, and it turns to face where it is going,
because an animal that slides sideways is a prop; its head goes down to the
grass and up to look around on its own clock; and it has four legs made from
one capsule by mirroring the space it stands in.

*The birds cost more* — **1.4 ms** — despite being simpler, and that is the
same fact from the other side. Everything on the ground needs to know where the
ground is, and that is a fetch; a bird does not, because it is at a height it
chose. The whole flock is a hash and two capsules with no lookup at all. It
drifts downwind, which is both free and true, and each circles inside its own
cell so a flock is not a lattice.

**Three things measured.**

*Density is the cost, and it is not linear.* A flock at one bird per 19 m was
2.8 ms; at one per 22 m with two thirds the chance it is under one. Scattered
geometry does not cost what it draws — it costs the **shorter steps the marcher
takes everywhere near it**.

*Correct and pointless is a real failure mode.* At their first size the animals
were forty-odd pixels of a hundred thousand: a true fact about the world that
nobody could see. Deer-sized rather than dog-sized.

*And the birds were unreachable by arithmetic.* At 35 m up they were never in
shot: the camera looks down about seven degrees and its vertical half-angle is
eighteen, so the top of the frame is eleven degrees up, and a bird is only ever
in view if its altitude is under a fifth of its distance. At 35 m that is 180 m
away — past the fog. They are gulls now, not eagles, and the camera's pitch
came up a little to meet them.

| | |
|---|---|
| a frame at 640×360, everything on | **12.8 ms — 78 fps** |
| the herd | +0.4 ms |
| the flock | +1.4 ms |
| walking, sampled six times | grazing in most, birds in most, sometimes one close enough to fill a corner |

*Left:* the map is rebuilt every frame even standing still — a toroidal clipmap
would rebuild only the strip that moved, which is worth doing the day the bake
shows up in a measurement rather than before.

### Phase 30 — A day, and a head that turns *(M)* — **shipped**

**A day.** The time of day lives in a register and advances, so the sun goes
round a tilted circle and the moon goes round the other side of it. Night is
not a switch: it comes on as the sun goes under, and the dusk in between is
where the light is worth looking at.

The prelude's `sky()` is a daytime sky and knows nothing about night, so the
night is written beside it and crossfaded in — a deep blue darkening overhead,
stars, and the moon as a lit disc with a phase, which is the sun's direction
seen from a sphere.

The stars are cells on the *ray's direction* rather than on the screen. That is
the whole of it: a star fixed to the screen is a speck on the lens, and the
same star has to stay where it is when the head turns. Two angles, quantised —
which is what a constellation is.

**A head that turns in three axes.** `lookAt` can say where to point but has no
way to say which way up, so the camera is now a basis built by hand from yaw,
pitch and roll. Pitch stops just short of vertical, because at exactly vertical
the forward vector is parallel to world-up and the frame built from it has no
right-hand side. I/K or PageUp/PageDown pitch, Q/E roll, A/D still yaw, and
dragging the mouse looks around.

| held to | number |
|---|---|
| a frame at 640×360, with everything | **12.2 ms — 82 fps** |
| a whole day, six samples | noon to midnight, a swing of more than 45/255 |
| looking up at night | bright specks where the same view by day finds sky |
| rolling | more than 25/255 of the picture moves |

**Two mistakes, both about names.** `vec3 gSun, gMoon;` declares two globals
and the shorthand's global handling reads a type and *a* name, so the second
was never emitted. And a local called `md` inside the night sky silently
deleted the reserved `md` — the shorthand drops a built-in the moment a sketch
defines that name itself, which is the right rule and a sharp edge: the mouse
look stopped compiling in a function that never mentions the mouse.

**And one of mine, worth recording because it nearly cost the work.** The
scratch file holding this phase was deleted by a `rm` that ran after the script
which should have consumed it had already failed — its guard rejected the file
for containing a backtick, which would have broken the template literal it was
being pasted into. The guard was right; the ordering was mine. It was
recovered from the browser's own memory, where it was still loaded.

*Left:* the moon keeps one face and one phase all night, the sun's circle is
tilted by a constant rather than a latitude, and there is still no dawn chorus.

### Phase 31 — A world you can hear *(M)* — **shipped**

Dawn sounds and ambient noise, through the path that was already there: the
world writes texels, the host reads them back as probes, and the ordinary
effect evaluator turns them into notes and parameter moves. The same route a
game's bounce takes. **The world says *that* a bird sang and how high; whether
anything is listening is not its business.**

**Two kinds of sound, and the difference matters.**

*Beds* — wind, rain and surf — are always sounding, and what changes is how
much. They are **one instrument three times**: filtered noise with a different
corner and a different tap of the same state-variable filter, which is what
those three sounds are. Their level is a `param` effect on a named part, not a
note, because a note has a beginning.

*Pulses* — the dawn chorus and a footfall a stride — last exactly one frame,
and that is a thing a **shader** can say and an expression cannot. So the world
emits them: a hash per eleventh of a second, gated by how much dawn it is, and
the slot index kept in the register beside it so the pulse lasts the one frame
the slot turns over on rather than the five a slot spans. The footfall watches
the walked distance wrap.

Dawn itself is one bump a day, not "the sun is low" — the sun crosses that
height twice, and dusk is the other crossing.

| held to | number |
|---|---|
| two sets of probe readings through the evaluator | 6 continuous levels and 2 notes |
| a bird at dawn, a step in the rain | each fires once, and only its own |
| every probe | names a texel the sketch actually writes |
| every `param` effect | names a part its instrument actually has |

**Four numbers tuned by measuring rather than taste.** The wind level was
scaled at 0.55 and sat clipped at 1 — a level that tells you nothing. The rain
front was a `smoothstep` narrow enough to be a switch, and rain does not arrive
like that. The chorus was 2 chirps in 400 frames. And the stride was 1.75 m,
which at thirteen metres a second is seven footfalls a second — a sewing
machine rather than a walk.

**And two things the system was right to refuse.** The patch parser rejects an
instrument with no `voice.note`: "an instrument with nowhere to write a note
plays nothing". A bed is sent no notes, so it has one and mixes it in at
nothing — which keeps the patch honest rather than special-cased. And the
weather was computed inside the branch that stores it, so the texel that says
how loud it is could not see it; it is worked out before the branches now,
because two texels want it.

*Left:* the beds are mono and the same everywhere; nothing is quieter behind a
hill or louder near the shore you can see.

### Phase 32 — Sound a hill gets in the way of, and a view that stays upright *(M)* — **shipped**

**Positional sound.** `exposure()` — eight fetches of the same baked map the
marcher reads, on the compass at twenty-five metres, asking how much of the
surrounding ground stands above your ear. It runs in *one texel of the state
pass, once a frame*, which is precisely why it can afford eight fetches where
`scene()` could not afford two. That asymmetry is the whole reason this is
cheap.

Wind and surf are scaled by it — in a hollow the wind is not gone, it is
distant, which is the difference between an occluder and a mute — and the dawn
chorus is gated by it, so a bird behind a ridge is not heard.

Measured over a walk it spans **0.69 to 1.00**: a measure of where you are
standing rather than a constant. The first threshold asked for a ridge nine
metres above the ear and sat between 0.96 and 0.99 everywhere, telling you
nothing.

**The chorus is gated rather than faded, and that is a limit worth naming.**
Fading it wants a per-note velocity; `env.ad` triggers on `gate > 0.5`, so a
fractional gate never fires, and `osc.sineHz` takes the envelope as its gate
with no signal-by-signal multiply in the catalogue to put a velocity in
between. That is a new DSP node and a change to every tone instrument — worth
doing, not worth pretending is done.

**A view you can keep your bearings in.** Three things, and the first is the
one that mattered:

*Roll comes back to level on its own.* Free roll is what makes a first-person
view lose its grounding — the horizon stops telling you which way up you are
and nothing puts it back. Roll is now something you *hold*: let go and it
returns over about a third of a second. Measured: 1.65 rad held, 0.014 a second
and a half after letting go.

*The mouse turns by how far it moved*, not by where it is. The first version
steered by the pointer's position — hold it left of centre and the world spins,
which is a joystick. The pointer's previous position now lives in a register
beside everything else the world remembers, and the turn is the delta. It is
also in *picture pixels* rather than a fraction of the window, which is why the
same mouse feels the same in a small window and a large one.

*And a reticle.* Four ticks and a gap, in the picture's own pixels. It is the
cheapest thing in the file and it does more for the feeling of standing
somewhere than anything else in it: without a fixed mark to look through, a
first-person view is a camera being flown rather than a head being turned.

**One more shadowed name**, the third this month: the meta register was called
`m`, which is the reserved mouse, so `m` inside the state pass was a `vec4` and
the mouse was not there at all. The rule — a sketch that declares a name gets
its own — is right, and it is a sharp edge every time.

*Left:* no panning, because a note carries no position and the instrument path
is mono; and the beds are still one sound each rather than a near one and a far
one.

## 4. Decisions and risks

- **WebGL1 → WebGL2 first.** Everything in Phases 1–3 gets simpler and faster
  on 2. Support is effectively universal; keep 1 for *display only* of
  existing sketches.
- **Fuse later, but design for it.** Phase 1 may start with one pass per node;
  the node format (a body that reads `in0` and returns a colour) is what
  makes fusion possible without rewriting nodes.
- **Blend-mode parity with the browser** is a known trap: non-separable modes
  (hue, saturation, colour, luminosity) need the spec's formulas exactly, and
  the browser composites in encoded space. Ship parity tests before the
  Canvas switch-over, and keep the per-document "legacy compositing" switch.
- **The two-way boundary is a feature.** Hand-written GLSL is opaque above the
  uniform line; document that plainly so nobody expects sliders to appear for
  a constant they typed. Bake and Freeze are the sanctioned crossings.
- **Precision and memory.** Half-float intermediates at 4k are 64 MB per
  target; the pool must cap and reuse. Sims stay at their own size.
- **Scope creep in Design.** SDF export of arbitrary paths and text is
  seductive and expensive; the geometry-stays-vector rule holds.
- **Content-aware features** are ML, not craft; out of scope, and said so in
  the UI when asked.

---

## 5. Order, in one table

| # | Milestone | Size | Depends on | You get |
|---|---|---|---|---|
| 0.1 | WebGL2 baseline + shims | M | — | float targets, `fwidth`, MRT |
| 0.2 | Error line mapping, in-app self-test | S | — | trust |
| 0.3 | Schema v1 (`@pass @precision @space @module …`) | S | — | one grammar |
| 1.1 | Render graph model + compiler (per-node passes) | L | 0.1, 0.3 | the keystone |
| 1.2 | Built-in nodes: adjust + composite + geometry | M | 1.1 | non-destructive colour |
| 1.3 | Port 21 filters to nodes, parity tests — **shipped** | M | 1.1 | one effect library |
| 1.4 | Fusion + ejection — **shipped** | M | 1.1 | speed; readable GLSL per layer |
| 2.1 | Canvas layers as subgraphs; adjustment layers | L | 1.x | Photoshop's model |
| 2.2 | Curves/Levels/HSL UI + histogram | M | 2.1 | the colourist's tools |
| 2.3 | Shader layer; eject document; colour management | M | 2.1 | live generative layers |
| 2.4 | Clone/heal | S | — | retouching |
| 3.1 | Video clips on the graph; shader clip effects | M | 1.x | one library for stills and motion |
| 3.2 | Keyframes + curve editor | M | 3.1 | animation |
| 3.3 | LUTs, scopes, speed ramps | M | 3.1 | grading |
| 4.1 | Save-as-node, Freeze, multi-in/out | M | 1.x | authoring |
| 5.1 | Design effects via graph; SDF export | M | 1.x | designs as shaders |
| 6.x | Tiling, WebGPU decision, more exports, P3 | M | 1.x | scale |
| 8.1 | Field wires: a port that carries a function — **shipped** | M | 1.x | geometry that composes |
| 9.1 | Parameter expressions and references — **shipped** | M | 1.x | a graph that holds relationships |
| 10.1 | Feedback: a wire that reads last frame — **shipped** | M | 1.x | simulation in the graph |
| 11.1 | Input: the keyboard as a texture, a ship you fly — **shipped** | M | 10.1 | a simulation you can play |
| 12.1 | `prev()` and `key()` in expressions: the model is data — **shipped** | S | 9.1, 11.1 | Model–Update–View, all three readable |
| 13.1 | Events: a queue, delivered once each, in order — **shipped** | M | 12.1 | a menu; a replay that is a log |
| 14.1 | Effects and the live audio path — **shipped** | M | 13.1, audio D | an event makes a sound; live equals the bounce |
| 15.1 | The document names its instrument — **shipped** | S | 14.1 | a document that is whole, sound included |
| 16.1 | The instrument library, content-addressed — **shipped** | S | 15.1 | one sound, one instrument, provably |
| 17.1 | The instrument document: a patch that persists — **shipped** | M | 16.1 | an instrument that outlives its session |
| 18.1 | The library listed; a playable game in Generate — **shipped** | S | 17.1 | you can see what you have, and play a sketch |
| 19.1 | Pong, with sound, in the Playground — **shipped** | S | 18.1 | model, rules, view and sound in one document |
| 20.1 | Probes: a sketch's own state, read back — **shipped** | S | 19.1 | a Generate sketch that can be heard |
| 21.1 | A WGSL emitter and a WebGPU runner — **40 translated** | L | 0.3 | 36 nodes identical on a second backend |
| 21.2 | Three more games in Generate — **shipped** | S | 20.1 | breakout, a flyer, and pong |
| 22.1 | Snake, a tilemap platformer, a raymarched rover — **shipped** | M | 21.2 | a grid, a tilemap and a lit 3-D world |
| 23.1 | The last of the catalogue — **nothing untranslated** | M | 21.1 | 48 of 53 identical; the 11 refusals are field ports |
| 24.1 | The render graph on WebGPU — **shipped** | L | 23.1 | pool, fusion, feedback and 32-bit registers, identical |
| 25.1 | Tiling on WebGPU; the rover's terrain as data | M | 24.1 | past the device's maximum, byte-identical; 74 fps |
| 26.1 | Fullscreen; the same care for the other 3D sketches | S | 25.1 | bounce 9.3 → 2.8 ms, and lit like the still life |
| 27.1 | The picture filling the window, ten places | S | 26.1 | in-page, no permission to be refused; four fits |
| 28.1 | An open world — infinite, four biomes — **shipped** | L | 25.1 | 4.3 ms; scene() is one fetch of a map that follows you |
| 28.2 | Trees, boulders and grass — **shipped** | M | 28.1 | 9.1 ms; one grid, and the cell decides what grows |
| 29.1 | Weather, and `@state` — **shipped** | M | 28.2 | 11.9 ms; 132 MB of state becomes 12.9 |
| 29.2 | A herd and a flock — **shipped** | S | 29.1 | 12.8 ms; the herd 0.4, the birds 1.4 and no fetch |
| 30.1 | Day and night, a moon and stars, roll/pitch/yaw | M | 29.2 | 12.2 ms; stars on the direction, not the screen |
| 31.1 | Dawn sounds and ambient noise — **shipped** | M | 30.1 | beds by param, pulses by shader; 6 levels, 2 notes |
| 32.1 | Occlusion, and an FPS feel — **shipped** | M | 31.1 | exposure 0.69–1.00 over a walk; roll self-levels |

**First 30 days, concretely:** 0.1, 0.2, 0.3, then 1.1 with exposure, curves,
blend and blur as the four proving nodes — one per-pixel adjustment, one
LUT-based, one two-input composite, one neighbourhood pass. If those four
compile, fuse, eject and pass parity, the rest of Phase 1 is repetition.

---

## 6. A note on the sentence "editing → GLSL updates"

Read literally it suggests the text file is the truth and the UI patches it.
That direction is a dead end within weeks: the first time two sliders share a
constant, or a mask is painted, or an undo has to happen, the text cannot
carry it.

Read as *"every edit lands as a change to the shader that runs"* it is exactly
right, and this roadmap is the way to make it true without lying about where
the truth lives. The truth is the graph. The GLSL is its shadow — but a shadow
you can always look at, always run, and step into whenever you want to write
the next node by hand.
