# AV Trainer

A local-first PWA for training the audiovisual crafts — graphics, audio,
video, effects — built to the specification in *Audiovisual Mastery Roadmap*
(Part 9). FastAPI backend, vanilla-ES-module frontend, SQLite, no build step,
no network calls.

Port **8910**. Everything stays on this machine.

## The thesis it is built on

Intuition is amortized search over trained perceptual features. Expensive
deliberate work — analysis, iteration, comparison — is distilled through
volume into a fast learned policy that runs largely feedforward. So:
perception first, volume second, articulation as a separate track, theory
pulled by friction rather than pushed by syllabus.

LLMs collapse the cost of the *symbolic* half of production and leave the
*perceptual* half untouched. Generating a hundred candidates is cheap;
choosing among them is not. Taste becomes more of the bottleneck, not less —
which is why selection is logged here as training data.

## The seven modules

| Module | Where | What it does |
|---|---|---|
| 1. Practice loop manager | **Make** | Weekly brief generator, deadline, archive with postmortems. The postmortem insists on a mechanism and pulls the matching theory item in with the failure attached. |
| 2. Discrimination trainer | **Train → Drills** | 25 drills (13 ear, 12 eye), 8 trials a round, adaptive level, feedback that names the mechanism. |
| 3. Effects lab | **Lab** | 14 guided builds over the Part 3 maths spine, in four live runtimes. |
| 4. Reference analyzer | **Analyze** | Drop an image or audio file; get the Part 6 feature bundle. |
| 5. Vocabulary builder | **Train → Vocabulary** | 82-term spaced-repetition deck of perceptual categories. |
| 6. Generator + filter sandbox | **Sandbox** | Parametric candidate spaces; your picks are logged as taste reps. |
| 7. Unlearning exercises | **Train → Unlearn** | Six prior-suppression drills, including an upside-down drawing pad. |

Plus **Library** (Parts 3–8 and 10–12, searchable by symptom) and
**Progress** (accuracy reported next to the level it was earned at).

### The course

**Library → Course** carries *The Mathematics Behind Graphics*: eight modules
from radiometry to fragment shaders, served straight out of `docs/course` as
ordinary markdown. The files stay the source of truth — edit one, reload, and
the app shows it. They still render on GitHub or in any editor.

What the app adds is that the figures come alive. A document that references
`figures/gradient-triptych.png` gets an interactive canvas computed from the
maths instead of a shipped image, and falls back to the generated file when
there is no live version. The split follows the course's own rule:

- **Plots of data or of a closed-form function** are drawn from the maths, so
  they are reproducible and make no claim about your screen.
- **Display artifacts** — banding, dither, the aliasing zone plate — render at
  one canvas pixel per device pixel and are never CSS-scaled, because a
  resampled artifact figure is a statement about the scaler rather than about
  the signal.

Twelve figures are live, including three the course lists as still to be
generated because they need CIE tables the repo does not ship. Those are
computed instead: the colour-matching functions use the Wyman–Sloan–Shirley
analytic fit to the 1931 2° observer, labelled as a fit, and the **metameric
pair is constructed rather than drawn** — a vector from the null space of the
colour-matching matrix is added to a spectrum, so the two curves differ
visibly while their XYZ agree to about 1e-13. That closes the gap Module 1
admits to when it says a metameric pair is the central idea of the course and
then does not show one.

Maths is transliterated to Unicode rather than typeset — no dependency, and
block equations are shown as source so nothing is mistaken for rendered
output.

## The studio

The trainer builds the eye and ear; the **Studio** tab is where the work
actually gets made. Five document types, one asset store, one AI layer.

| Document | What it is |
|---|---|
| **Canvas** | Layers with real blend modes and non-destructive **layer masks**; **selections** (rectangle, ellipse, lasso, magic wand) with add/subtract, feather and invert; **free transform** with scale and rotate; **editable text layers** that only become pixels when you rasterise them; brush / eraser / shapes / bucket; and the whole Part 10 catalogue as a 21-entry filter menu running through `engine-image`. Imports images, exports PNG. |
| **Music** | Three views of one document: **Arrange** (clips on a timeline with automation lanes), **Edit** (piano roll / drum grid per pattern), **Mix** (channel strips, meters, sends). Patterns are reusable and a clip repeats its pattern to fill its length. Six instruments, per-track EQ / filter / drive / delay / convolution reverb, swing, solo and mute, real AudioParam automation for volume and filter, master limiter. Imports audio, exports WAV. |
| **Video** | A **multi-track timeline** — video tracks composite in order, audio tracks mix — with drag-to-move, edge trimming that carries the in-point, split at the playhead, snapping, per-clip fades, opacity and grading. **Exports MP4 offline** via WebCodecs (H.264 + AAC) through a hand-written muxer, so it cannot drop frames; falls back to a real-time webm recording where WebCodecs is missing. |
| **Design** | Vector shapes, type and layout on an infinite canvas. Frames as artboards, edge/centre snapping with guides, auto-layout stacks, align and distribute, a Müller-Brockmann column grid overlay, grouping, and SVG / PNG@2x export. |
| **Shader** | A GLSL sketchpad using **The Book of Shaders' uniform names** — `u_resolution`, `u_time`, `u_mouse` — so examples from that book paste in and run unchanged. Eleven chapter presets from *Hello world* to *Fractal Brownian Motion*. |

### What this is not

Worth being straight about, because the gap is real. These are sketchpad-tier
tools, not production ones:

- **Canvas is not Photoshop.** It now has selections, transform, masks and
  live text — but no adjustment layers, clipping masks, layer groups, paths
  or pen tool, clone/heal, gradients, guides and snapping, or non-destructive
  filter stacks. Undo is 18 deep and canvas size is fixed at creation.
- **Music is not a DAW.** It has patterns, clips, automation, solo and a
  mixer, but no audio clips on the timeline (samplers are played from the
  roll), no per-note velocity, no time signatures other than 4/4, no
  sidechain routing and no plugin format.
- **Video is not an NLE.** It has multiple tracks, trimming, splitting,
  snapping and a frame-exact MP4 export, but no keyframed effects, no speed
  or time remapping, no transitions beyond fades, no waveform display on
  audio clips, and no nested sequences. Export seeks each source frame by
  frame, so long timelines with video sources take a while.
- **Design is not Figma.** No components or variants, no constraints, no
  prototyping, no shared styles, no pen tool or boolean ops, no multiplayer.
  It has the parts that matter for learning layout — grid, snapping,
  auto-layout, alignment, hierarchy — and stops there.

The design editor renders as SVG rather than canvas on purpose: a layout tool
needs crisp text at any zoom, hit-testing that does not mean re-implementing
geometry, and an export that is genuinely vector. All three come free from the
DOM.

Music playback renders the whole arrangement offline into one buffer and loops
it, rather than running a live scheduler. Edits re-render in a fraction of a
second, the result is sample-accurate, automation is real AudioParam
automation rather than a polled approximation, and export is the same code
path as play — so what you hear is exactly what lands in the file. The cost is
that a parameter cannot be nudged mid-note: it re-renders instead, which at
sketch lengths is imperceptible.

The video grade is the one place that deliberately does *not* use
`engine-image`: it uses the canvas `filter` property, because a 30fps preview
cannot afford a per-frame JS pass over half a million pixels, and a grade you
cannot scrub against is not a grade you can judge.

`video-mux.js` is a minimal MP4 muxer. Browsers will encode H.264 and AAC
through WebCodecs but ship no container writer, so the encoded chunks have to
be written into `ftyp`/`mdat`/`moov` by hand. It writes moov last, which is
legal and avoids patching sample offsets, and gives each track a single chunk
so the sample-to-chunk table stays trivial.

## AI

Optional, off by default, and configured in the studio's AI panel. Three
providers: the Anthropic API, a local Ollama, or any OpenAI-compatible
endpoint. Requests go through the backend so the key never reaches the browser
and there is no CORS to work around.

The roadmap is specific about the limit (Part 13.5), and so is the
implementation: the model drafts, implements and lists things you may have
missed. It never ranks and it is never the selector — the critique prompt
forbids it explicitly, because a critique prompt that does not forbid ranking
will rank. There is no "which of these is best" button anywhere in the app.

When a cloud provider is selected the settings panel says plainly that prompts
leave the machine. With Ollama, or with AI off, nothing does.

## Everything perceptual runs in the browser

The backend is deliberately thin — curriculum, schedule, record. Stimuli have
to be generated fresh every trial and feedback has to be immediate, so all of
it is client-side:

- `engine-audio.js` — sample-level synthesis (pink noise, drum loop, pad,
  formant voice, Karplus-Strong pluck), offline rendering through real Web
  Audio graphs, IR synthesis, waveshaper curves, radix-2 FFT, MIR features,
  tempo estimation with octave correction.
- `engine-image.js` — procedural scenes and layouts, convolution and the blur
  family, sRGB/linear/OKLab conversion, grading, value/fBm/Worley noise,
  centre-surround saliency, k-means palette extraction in OKLab, grid
  detection, easing curves.

Two consequences worth knowing:

- **Every A/B is RMS level-matched.** Louder is heard as better; an unmatched
  comparison tests gain, not discrimination.
- **Nothing is stock.** A fixed stimulus trains recognition of the picture
  instead of discrimination of the dimension.

## The four lab runtimes

| Runtime | Signature | Used by |
|---|---|---|
| `glsl` | fragment shader; `u_res`, `u_time`, `u_mouse`, `u_k` | SDF, noise/fBm |
| `canvas2d` | `draw(ctx, w, h, t, k, I)` | compositing, colour, convolution, easing, saliency, aliasing |
| `audio` | `build(ctx, src, k, A) -> node` | biquad, delay line, convolution reverb |
| `dsp` | `process(input, sr, k, A) -> Float32Array` | waveshaping, granular, additive |

Starter source lives in `labs-content.js`; lab metadata (goals, the lesson it
teaches) lives in the backend registry so the curriculum can link to it.

## Layout

```
src/backend/
  main.py          FastAPI app — all routes, scoped to the signed-in user
  curriculum.py    tracks, 43 theory items, drill + lab registries, brief parts
  library.py       Parts 8/10/11/12 — catalogue, genres, systems, reading, terms
  briefs.py        the weekly brief generator
  db.py            SQLite schema; content tables carry user_id
  auth.py          pbkdf2 + session tokens (stdlib only)
  seeder.py        starter content
src/frontend/      ES modules, no bundler
scripts/           launch.py, seed.py, make_icons.py
command_utilities/ double-clickable .command launchers
tools/             make_launcher.py — builds a Desktop .app on macOS
```

Curriculum and library ship as Python data, not database rows, so they version
with the app. User rows reference them only by stable slug: rewriting the
curriculum never orphans history, because unknown slugs are ignored on read.

## Notes

- Dependencies are `fastapi` and `uvicorn`. Everything else is stdlib —
  including the PNG writer that generates the icons and the password hashing.
- Dark-only by design. This app asks you to judge colour and contrast, so the
  chrome stays low-chroma and no accent sits behind a stimulus.
- `Start AV Trainer (HTTPS).command` serves TLS with a self-signed cert so you
  can install the PWA on a phone on the same network. Worth doing: the drills
  sound different on phone speakers, and checking there is the point.
- The tempo estimate reports one metrical level and says so. Autocorrelation
  cannot tell which level is "the beat" — half and double time are equally
  consistent with the signal.
