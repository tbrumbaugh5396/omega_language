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

## The studio

The trainer builds the eye and ear; the **Studio** tab is where the work
actually gets made. Four document types, one asset store, one AI layer.

| Document | What it is |
|---|---|
| **Canvas** | Layers with real blend modes, brush / eraser / shapes / type / bucket, and the whole Part 10 catalogue as a 21-entry filter menu running through `engine-image`. Imports images, exports PNG. |
| **Music** | Tracks, piano roll and drum grid over six instruments (subtractive, FM, Karplus-Strong pluck, bass, drum synth, sampler), per-track EQ / drive / delay / convolution reverb, swing, master limiter. Imports audio, exports WAV. |
| **Video** | Sequential timeline of clips, stills and titles with per-clip grading, dissolves and an audio track. Exports by recording the composed canvas. |
| **Design** | Vector shapes, type and layout on an infinite canvas. Frames as artboards, edge/centre snapping with guides, auto-layout stacks, align and distribute, a Müller-Brockmann column grid overlay, grouping, and SVG / PNG@2x export. |
| **Shader** | A GLSL sketchpad using **The Book of Shaders' uniform names** — `u_resolution`, `u_time`, `u_mouse` — so examples from that book paste in and run unchanged. Eleven chapter presets from *Hello world* to *Fractal Brownian Motion*. |

### What this is not

Worth being straight about, because the gap is real. These are sketchpad-tier
tools, not production ones:

- **Canvas is not Photoshop.** No selections, no transform, no layer masks or
  adjustment layers, and text is rasterised the moment it is placed.
- **Video is not an NLE.** One video track, no keyframes, no drag-trimming on
  the timeline, and export is a real-time screen recording to webm rather
  than a proper encode.
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
second, the result is sample-accurate, and export is the same code path as
play — so what you hear is exactly what lands in the file.

The video grade is the one place that deliberately does *not* use
`engine-image`: it uses the canvas `filter` property, because a 30fps preview
cannot afford a per-frame JS pass over half a million pixels, and a grade you
cannot scrub against is not a grade you can judge.

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
