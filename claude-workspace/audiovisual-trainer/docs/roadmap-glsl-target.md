# Roadmap — editing as authoring, GLSL as the target

*Written 2026-08-17, against commit `a20c35b`. This is the plan for turning the
studio from five editors that happen to share a codebase into one system in
which every edit that produces pixels compiles to GLSL.*

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

### Phase 0 — Harden the foundation *(S–M, now)*

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

### Phase 1 — The render graph and compiler *(L; the keystone)*

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

### Phase 2 — Canvas on the graph *(L)*

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

### Phase 3 — Video on the graph *(L)*

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

### Phase 4 — Generate as the node authoring environment *(M)*

- **Save as node**: a sketch with `@node <name>` appears in Canvas and Video
  effect menus with its icon, group and help.
- Node library management (yours, presets, imported), versioning of node text.
- **Freeze**: fused chain → custom node.
- Multi-input sketches (`in0`, `in1` — mixers, transitions) and multi-output
  (MRT on WebGL2: a sim writing velocity and dye to two targets).
- Optional **graph view**: a visual editor of the render graph. Useful, not
  load-bearing; the layer panel is the graph view most people want.

### Phase 5 — Design meets the target *(M)*

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
- **Known gaps, reported in the import notes rather than hidden**: miter and
  bevel joins are drawn round; CSS stylesheets and classes, filters, masks
  and patterns are ignored; stop-opacity is dropped; text is greeked.
- **Next in this line**: dashes (arc-length parametrisation), miter joins,
  stop-opacity via vec4 ramps, and text through an SDF glyph atlas.
- **Generate → Design** is not attempted (the boundary of §2.3 again).
- Effects on design layers through the graph.
- Text via an SDF glyph atlas — a texture, but a *distance* texture, so still
  crisp at any scale — is L and last; a paragraph is thousands of segments.
- Where it strains: paths past a few hundred segments per pixel bake to a
  texture; `feGaussianBlur` and friends are pass boundaries, not per-pixel.
- Geometry stays vector in the Design document; this is a compile target, not
  a replacement for the vector model.

### Phase 6 — Platform and performance *(M, continuous)*

- **WebGPU/WGSL as a second target** only if the node templates are kept
  small enough to translate; otherwise stay GLSL ES 3.00 and use WebGPU's
  compat layer when it lands. Decide at Phase 1 by keeping node bodies free
  of anything WGSL cannot express.
- Tile rendering for exports beyond the max viewport; FBO pool caps; program
  cache eviction; half-float intermediates by default.
- Export: image sequences (zip), WebM (VP9/AV1 via WebCodecs), MP4 with audio
  from the video studio's mixer for Generate too.
- Wide-gamut output (P3 canvas) once colour management exists.

### Phase 7 — What stays outside *(note)*

Audio does not compile to GLSL. The analogous move — Music as an AudioWorklet
DSP graph with the same schema discipline (`// @range` on parameters, nodes
authored as text) — is the right one, and it is a separate roadmap.

### Cross-cutting

- **Course integration** — every built-in node carries `@module`; the Help
  panel and layer panel link to it; the course pages gain "open in Canvas
  with this node" buttons.
- **AI** — the agents author nodes (sketches) and graph edits, not pixels.
  Critique stays non-ranking.
- **Docs** — each node is self-documenting from its annotations; the Help
  modal is generated, never hand-maintained.
- **Testing** — parity tests (CPU vs GPU), golden images per node, the
  in-app self-test, and the ejected-GLSL-reproduces-the-composite check.

---

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
| 1.3 | Port 21 filters to nodes, parity tests | M | 1.1 | one effect library |
| 1.4 | Fusion + ejection | M | 1.1 | speed; readable GLSL per layer |
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
