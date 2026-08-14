# Audiovisual Mastery Roadmap
### A learning system for graphics, audio, video, effects, and human-centered design

This document compiles a full curriculum, theory base, tool stack, effects catalog, genre glossaries, sensory-system reference, AI workflows, and practice architecture for becoming a designer/artist who can construct custom graphics, audio, and video assets with commercial polish — and who understands the perceptual, mathematical, and cognitive machinery underneath. It doubles as a specification for building a learning tool / development environment around the practice. Parts 0–9 are the plan; Parts 10–14 are the reference library it draws on.

---

## Part 0 — The Central Thesis

**Intuition is amortized search over trained perceptual features.** Expensive deliberate work (analysis, iteration, comparison) gets distilled through volume into a fast learned policy that runs largely feedforward. This is buildable, and it dictates the build order:

1. **Perception first** — taste and discrimination are trainable (perceptual learning is robust science, not folklore).
2. **Volume second** — the policy is found by search under feedback; no amount of reading substitutes for reps.
3. **Articulation as a separate track** — explaining is its own network, trained on its own data. It does not come free with skill.
4. **Theory pulled in by friction** — read in response to problems you actually hit; theory lands when it answers a live question.

Corollary for the AI era: LLMs collapse the cost of the *symbolic* half of production (code, drafts, candidates) while leaving the *perceptual* half untouched. Generating a hundred candidates is cheap; choosing among them is not. **Taste becomes more of the bottleneck, not less.** Leverage moves upstream (problem framing) and downstream (selection).

---

## Part 1 — The Three-Track Structure

Run these in parallel, not in sequence.

### Track A: MAKE (the practice loop)
- **One finished piece per week, no exceptions.** Escalating ambition: a 10-second spot, a title card, a sound-designed loop, an animated poster, a shader sketch.
- Finished > perfect. The loop is: brief → produce → evaluate → identify what broke → pull theory for that break → next piece.
- Keep an archive of every piece with a one-paragraph postmortem: what reads wrong, why (if known), what to study.

### Track B: TOOLS (deliberate practice)
- One tool at a time until it becomes invisible (no menu-hunting, hands know the shortcuts).
- Deliberate practice structure: isolate a sub-skill, drill it with fast feedback, recombine.

### Track C: THEORY (pulled, not pushed)
- The full topic map in Parts 3–8 below. Read the section that explains the current week's failure.

### Perceptual training (runs inside all tracks)
Discrimination-focused, high-volume, rapid-feedback exposure:
- **A/B comparison drills**: two grades of the same footage, two mixes of the same track, two kernings of the same headline — which is better and *why*.
- **Reference immersion**: daily analysis of one excellent commercial/title sequence/track. Decompose: what is the grid, the palette, the rhythm, the mix?
- **Blind tests**: identify effects, filters, fonts, chords, compression artifacts without labels.
- **Vocabulary building alongside perception**: naming discriminations sharpens them (verbal overshadowing hurts novices but not experts — because expert vocabulary matches perceptual categories). Build the words as you build the eye/ear.

---

## Part 2 — Tool Stack

### Core creative tools
| Domain | Tools |
|---|---|
| Raster / vector | Affinity suite or Adobe (Photoshop / Illustrator); **Figma** for interface work |
| Motion graphics | **After Effects**; **Blender** (3D, free, industry-real) |
| Edit / grade | **DaVinci Resolve** (editing = assembly, timing, rhythm; grading = shaping palette/contrast of footage) |
| Audio | **Reaper** or **Ableton Live**; a sound-design library habit; iZotope RX for repair |
| Creative code | **p5.js / Processing** → **GLSL shaders** (Shadertoy) → **TouchDesigner** |
| Web-deliverable | Three.js / react-three-fiber, **GSAP** (timeline control), **Rive** / **Lottie** (vector motion), **Spline** |

The creative-code track is where the mathematics of effects stops being background reading and becomes the thing you type. **Shadertoy + an LLM is an extraordinarily good way to learn effects math**: ask for an implementation, run it, iterate against what you see.

### AI / LLM-empowered tools (verify currency — fastest-moving category)
| Category | Tools | Notes |
|---|---|---|
| LLM + creative code | Claude, Cursor, Copilot | Strong at GLSL, p5.js, Three.js, r3f, TouchDesigner Python. Highest-leverage AI use for this curriculum. |
| Image | Midjourney (aesthetic ceiling); Flux + Stable Diffusion ecosystem (controllability); **ComfyUI** (node pipeline: ControlNet for structure, IP-Adapter for style, LoRA training for consistent house style) | ComfyUI is where real production work happens |
| Video | Runway, Kling, Veo, Sora, Luma (closed); Wan, HunyuanVideo, LTX-Video (open) | Weak on precise art direction; use for **element generation, not shot generation** |
| Audio | Suno / Udio (music sketches), ElevenLabs (voice, SFX), Stable Audio (texture), **Demucs** (stem separation) | |
| Post | Resolve Neural Engine (magic mask, depth maps, voice isolation), Topaz (upscale / interpolation) | Least glamorous, most consistently useful |
| 3D / capture | Meshy, Tripo (text-to-3D); Gaussian splatting (capture) | |

### A working AI production pipeline (web / commercial)
1. Build a **style bible** (references, palette, type, motion language)
2. Train or prompt for a consistent look (LoRA / IP-Adapter / prompt system)
3. **Generate elements, not finished shots**
4. Composite and grade in Resolve / After Effects
5. Hand-authored shaders for anything pixel-exact or interactive
6. Audio generated as stems → arranged and sound-designed in a DAW

### Commercial constraints
- **Provenance / indemnification**: clients increasingly require it. Adobe Firefly, Getty, Shutterstock models offer it; most others don't.
- **Performance & accessibility budgets on web**: `prefers-reduced-motion`, shader cost on mid-tier mobile GPUs, contrast under motion, caption design, audio intelligibility. Accessibility is a perceptual constraint that makes work better, not a compliance afterthought.

---

## Part 3 — The Mathematics of Effects (the small spine)

The mathematical core of effects is smaller than it looks. Learn these and you can *construct* most effects rather than searching for plugins.

### Visual
1. **Compositing algebra** — Porter-Duff operators, blend modes, premultiplied alpha
2. **Color** — color spaces, transfer functions (gamma vs. linear), LUTs, OKLab; opponent-process color
3. **Convolution kernels** — blur, sharpen, edge detection are all one operation with different kernels
4. **Noise functions** — Perlin, simplex, Worley; the source of most organic texture
5. **Signed distance fields (SDFs)** — shapes, glow, morphing, raymarching
6. **Particle systems** and **easing / interpolation curves** — the grammar of motion

### Audio
1. **Biquad filters** (EQ primitives)
2. **Delay lines** (echo, chorus, flange, comb filtering)
3. **Waveshaping / distortion**
4. **Granular synthesis**
5. **Convolution** (reverb, impulse responses)

### Shared foundations
- **Fourier analysis** — spectrograms, EQ, phase vocoder, time-stretching (audio); frequency-domain filtering, DCT/JPEG, Gaussian pyramids, texture synthesis (image). Genuinely foundational — worth real study.
- Linear algebra for transforms; basic signal processing (sampling, aliasing, Nyquist).

### Practice mapping
Each math item pairs with a Shadertoy / p5.js / DAW exercise. Example: SDFs → raymarched logo; convolution → build a blur from scratch, then a custom kernel; granular → texture bed for a spot.

---

## Part 4 — Perception Science (empirical core of "the human body and its encodings")

The trainable-eye/ear curriculum. Directly explains why certain edits read cleanly and others feel wrong.

### Vision
- Opponent-process color; contrast sensitivity functions; critical flicker fusion
- **Gestalt grouping laws** (proximity, similarity, continuity, closure, common fate) — the physics of layout
- Change blindness, inattentional blindness; saliency (Itti–Koch models predicting gaze)
- Spatial frequency channels (why detail hierarchy works)

### Audition
- Equal-loudness contours (Fletcher–Munson); auditory masking (frequency and temporal)
- The precedence effect (spatial hearing, why delays localize)
- Critical bands; timbre as spectral envelope + temporal envelope

### Perceptual learning (the science of trainable taste)
- Genuine changes in discriminability, not just faster labeling — radiologists, sonar operators, wine tasters, chicken sexers
- Attentional weighting: signal-carrying discriminations amplified, noise suppressed
- Kellman's perceptual learning modules — the training protocol template: high volume, rapid feedback, discrimination-focused
- Verbal overshadowing (Schooler): description impairs novice discrimination but not experts' — build vocabulary that matches perceptual categories

### Accessibility as perception
- Contrast ratios, motion sensitivity, vestibular triggers, caption design, audio intelligibility — same science, applied

---

## Part 5 — The Phenomenology & Neuroscience of Mastery

The naturalization of *wu wei* as skilled action; the theory of what the practice loop is building.

### The core account
Expertise = **amortized search**: expensive deliberation distilled into a fast learned policy over trained perceptual features. Not "faster loops" — the loop stops being what does the work:
- **Anticipation, not reaction** (Abernethy's occlusion studies: experts read the bowler's kinematics, not the ball — information extracted earlier, from cues novices can't see)
- **Forward models** (Kawato, cerebellum): the brain predicts sensory consequences of its own commands and corrects against the *prediction* — short-circuiting feedback rather than accelerating it
- **Chunking** (Chase & Simon; Ericsson & Kintsch's long-term working memory)
- **Proceduralization**: control migrating from prefrontal/premotor toward basal ganglia and cerebellum

### Frameworks
- **Predictive processing / active inference** (Friston; Andy Clark, *Surfing Uncertainty*) — expertise as sharpened priors + recalibrated precision-weighting; intuition as perception under strong learned models
- **Skilled intentionality framework** (Rietveld & Kiverstein) — affordance landscapes; the most direct formalization of expert responsiveness; grounded in Gibson's ecological psychology
- **Dreyfus skill model** (novice → advanced beginner → competent → proficient → expert); expert stage = disappearance of rule-following; the Dreyfus–McDowell debate on whether expert action is conceptual
- **Transient hypofrontality** (Dietrich); Limb's jazz-improvisation fMRI (DLPFC deactivation during improvisation) — suggestive, small samples

### "Don't think, feel" — the evidence
- **Explicit monitoring hypothesis** (Beilock & Carr), **reinvestment theory** (Masters): attending to components of a proceduralized skill degrades it; choking is this mechanism
- **Stage-dependent**: explicit instruction helps novices enormously. The maxim is advice for the proficient only.

### The compression problem (fast circuits ↔ conscious explanation)
- **Fast → verbal is lossy**: high-dimensional continuous policy through a low-bandwidth symbolic channel. Polanyi ("we know more than we can tell"); Nisbett & Wilson (introspection is confabulation-prone); Gazzaniga's interpreter module.
- **Verbal → fast is lossy differently**: instruction underdetermines performance; language specifies a target, not a policy — the policy must be found by search under feedback.
- **Explainability is a separately trained network**: a model *of* the skill, trained on different data (teaching attempts, feedback on explanations). Nothing forces it to be faithful — cf. expert blind spot (Nathan & Petrosino), pedagogical content knowledge (Shulman), and the ML interpretability parallel (probes and chain-of-thought faithfulness).
- **Practical upshot**: if you want to direct work, brief clients, or teach — train articulation deliberately as its own track.

### The AlphaZero analogy (held at the right level)
Policy distillation: expensive search at training time → strong single-forward-pass policy. A good formal model of what nineteen years of practice does. Breaks at: embodiment, proprioception, online mid-movement correction, and the nature of the training signal.

### The Daoist frame — used accurately
- **Zhuangzi / Cook Ding**: mastery through immense practice; works by *shen* (spirit), blade finds the gaps; nineteen years in. Maps cleanly onto the science above. **This is the model that supports the artistic project.**
- **Laozi / *Daodejing***: the uncarved block (*pu*), the infant, "abandon learning" — an ideal reached by *subtraction*, prior to expertise, not the refined end of it. In genuine tension with the skill reading (though one scholarly view holds Laozi's target is specifically Confucian social learning, not skill as such).
- **Zuowang** ("sitting and forgetting", *Zhuangzi*): forgetting as advancement.
- **Three distinct "forgettings"** — do not collapse them:
  1. *Pruning through training* — learning what doesn't matter; the larger half of expertise (chess masters search fewer moves; attentional weighting). A trained eye stops seeing most of the image and goes straight to what's wrong.
  2. *Laozi's return to the infant* — pre-distinction, not post-training; not reachable via the practice route.
  3. *Deliberate unlearning to see freshly* — beginner's mind (Suzuki), upside-down drawing; suppressing a trained model's priors to catch what doesn't fit them. Available only to the expert; the antidote to the expert blind spot. **A genuine craft discipline**: the art of removing rather than adding.
- Scope honesty: this naturalizes *wu wei* as skilled action — one thread of Daoism. It does not reach Laozi's subtraction ideal, the cosmological Dao (*ziran* as self-so-ness of rivers and seasons), or religious Daoism (Celestial Masters, internal alchemy).

---

## Part 6 — Analysis Frameworks: Composition, Genre, Features

### Composition — formalizable as generator + filter
**What formalizes well (the grammar of well-formedness):**
- Grid systems and modular scale (Müller-Brockmann)
- Typographic hierarchy (Lupton); visual weight and balance as computable quantities
- Gestalt grouping as layout physics
- Saliency models (Itti–Koch) predicting gaze
- Constraint-based layout (Cassowary solver — underlies auto-layout); design tokens as parametric systems
- Music: species counterpoint; Schenkerian reduction; Lerdahl & Jackendoff's *Generative Theory of Tonal Music*; Xenakis's *Formalized Music*; Tonnetz geometry

**The limit:** these formalize *well-formedness*, not *goodness*. The grammatical-but-dull space vastly exceeds the good space; no formal measure has closed the gap (Birkhoff's M = O/C, 1933, and computational aesthetics since). Saliency says where eyes land, not whether the image is worth looking at.

**Operational rule:** use formal systems to *generate* a large valid candidate space and *filter* malformedness. **Selection remains perceptual** — which is why Parts 1 and 4 are foundational.

### Genre — family resemblance, not taxonomy
- Wittgensteinian family-resemblance category; prototype theory (Rosch) beats definitions
- **Two decomposable layers:**
  1. *Intrinsic feature bundle* — music: timbral palette, rhythmic template, harmonic vocabulary, production conventions; visual: palette, mark-making, compositional habits, historical material constraints
  2. *Social-historical lineage* — scene, label, era, who was in the room
- MIR formalizes layer 1 and fails at layer 2 (genre classification plateaued: partly dataset artifacts, partly genre isn't in the signal)
- For making things, the feature-bundle decomposition is the right working vocabulary — just don't expect orthogonal axes or stable boundaries

### Music Information Retrieval (the field to mine)
- Tasks: beat/tempo tracking, key and chord recognition, source separation, melody extraction, structural segmentation, cover-song ID
- Feature vocabulary worth internalizing: spectral centroid (brightness), spectral flux (rate of change), MFCCs, onset density, harmonic-to-noise ratio, tempo, harmonic density
- Visual analogues: edge statistics, palette entropy, contrast distribution, spatial frequency profile
- Tooling: **librosa** (Python); text: Müller, *Fundamentals of Music Processing*

### Ideation — creating by association (formalizable methods)
- Moodboarding; constraint-setting; systematic variation; forced analogy
- Bruno Munari (*Design as Art*, *Fantasia*) — association-as-method
- Style bibles as the production interface between association and generation

---

## Part 7 — Historical & Technical Background (context layer)

Read for orientation, pulled by curiosity rather than sequenced:
- Computer graphics: raster vs. vector lineage, the rendering pipeline, Sutherland → SIGGRAPH → GPU era → shader era
- Computer audio: synthesis lineages (subtractive, FM, wavetable, physical modeling, granular), MIDI, the DAW
- Video: film grammar → editing theory (montage, continuity) → digital intermediate → color pipeline (log, LUTs, ACES)
- Art & music genre histories — consumed through the feature-bundle lens of Part 6

---

## Part 8 — Reading List

### Phenomenology & mastery
- Varela, Thompson & Rosch — *The Embodied Mind* (founding text of neurophenomenology)
- Thompson — *Mind in Life*
- Merleau-Ponty — *Phenomenology of Perception* (body schema, motor intentionality)
- Dreyfus — skill acquisition papers; the Dreyfus–McDowell exchange
- Clark — *Surfing Uncertainty* (predictive processing)
- Slingerland — *Trying Not to Try* (wu wei × cognitive science) and *Effortless Action* (the academic treatment; takes Laozi/Zhuangzi differences seriously)
- Billeter — *Lessons on Zhuangzi*
- *Zhuangzi* (Cook Ding, zuowang); *Daodejing*
- Beilock — choking literature; Ericsson — deliberate practice

### Design & composition
- Müller-Brockmann — *Grid Systems in Graphic Design*
- Lupton — *Thinking with Type*
- Munari — *Design as Art*; *Fantasia*

### Music & signal
- Müller — *Fundamentals of Music Processing*
- Lerdahl & Jackendoff — *A Generative Theory of Tonal Music*
- Xenakis — *Formalized Music*

### Effects math (practice-first sources)
- Shadertoy (Inigo Quilez's articles on SDFs and noise are canonical)
- The Book of Shaders (GLSL fundamentals)

---

## Part 9 — Specification Sketch: The Learning Tool

If building a development environment around this practice, the architecture falls out of the theory:

### Modules
1. **Practice loop manager** — weekly brief generator, deadline enforcement, archive with postmortems (the MAKE track)
2. **Discrimination trainer** — A/B drills (grades, mixes, kernings, effects), blind identification tests, spaced repetition on perceptual categories; tracks discrimination accuracy over time (perceptual learning module, per Kellman)
3. **Effects lab** — live-coding environment (GLSL / p5.js / Web Audio) with the Part 3 math spine as guided builds; LLM-assisted implementation with the human doing perceptual evaluation
4. **Reference analyzer** — decompose a commercial/track into features (Part 6 vocabulary): grid detection, palette extraction, spectral features via librosa-style analysis
5. **Vocabulary builder** — pairs perceptual drills with naming, building the articulation network alongside the perceptual one
6. **Generator + filter sandbox** — parametric composition systems (grids, scales, tokens, constraint solvers) that generate candidate spaces; the user's job is selection, logged as taste-training data
7. **Unlearning exercises** — upside-down drawing, inverted playback, constraint scrambles: deliberate prior-suppression drills for advanced stages

### Design principles (from the theory)
- Fast feedback everywhere (the policy is found by search under feedback)
- Theory surfaced contextually, at the moment of failure, not front-loaded
- Explicit-instruction density scales *down* with skill stage (Dreyfus; don't give the proficient the novice's rules — and vice versa)
- Selection is the training signal: every choice the user makes among candidates is a taste rep
- Articulation prompts as a separate, optional track (explain your pick — trains the second network)

---

## Part 10 — Effects & Techniques Catalog

A comprehensive working catalog (no catalog is truly complete — new effects are compositions of these primitives). Each maps back to the math spine in Part 3; almost every entry is buildable from convolution, noise, SDFs, delay lines, filters, and modulation.

### 10.1 Visual effects — image processing
| Family | Effects |
|---|---|
| Blur | Gaussian, box, motion blur, radial/zoom blur, directional, tilt-shift, lens blur / bokeh (aperture-shaped kernels), surface/bilateral blur (edge-preserving) |
| Sharpen / edges | Unsharp mask, high-pass sharpen, Sobel/Canny edge detection, emboss, find-edges outlines |
| Glow & optics | Bloom/glow (threshold → blur → additive composite), halation, lens flare, anamorphic streaks, chromatic aberration, vignette, light leaks, starburst/diffraction |
| Grain & texture | Film grain, noise overlay, dither (Floyd–Steinberg, Bayer/ordered), halftone (dot, line, cross-hatch), paper/print texture, risograph misregistration |
| Quantization | Posterize, threshold, pixelate/mosaic, ASCII rendering, voxelization, low-bit color |
| Distortion | Wave, ripple, twirl, pinch/bulge, fisheye/barrel/pincushion, spherize, displacement mapping (drive distortion with any texture/map), heat shimmer, refraction/glass |
| Glitch | RGB channel split, pixel sorting, datamoshing (motion-vector corruption), scanlines, VHS (tracking error, chroma bleed, tape noise), block corruption, signal interference, feedback loops |
| Stylization | Cel/toon shading, outline/ink shaders, cross-hatching, watercolor/oil simulation, pointillism filters, mosaic/stained glass, kaleidoscope, mirror/symmetry |

### 10.2 Visual effects — color
- Color grading: lift/gamma/gain, curves, LUT application, split toning
- Named looks: teal-and-orange, bleach bypass, cross-process, day-for-night, sepia, cyanotype, technicolor two-strip/three-strip emulation
- Duotone/tritone, gradient mapping, selective color/color isolation, hue rotation, color match/transfer between images
- Exposure family: HDR tone mapping, black/white point, contrast S-curves, filmic transfer curves

### 10.3 Visual effects — compositing & motion
- Keying: chroma key, luma key, difference matte; spill suppression; edge refinement
- Masking, rotoscoping, garbage mattes, track mattes, alpha/luma mattes
- Motion tracking: point, planar (mocha-style), 3D camera solve, match-move, screen replacement
- Stabilization (and its inverse: handheld shake simulation)
- Time effects: slow motion / optical-flow interpolation, speed ramps, time remapping, freeze frames, echo/trails, long-exposure simulation, onion skinning, timelapse/hyperlapse
- Morphing and warping (mesh warp, liquify, face morph)
- Transitions: cross-dissolve, dip-to-black/white, wipes, iris, match cut, whip pan, invisible cuts, mask transitions, luma-driven transitions, glitch cuts

### 10.4 Visual effects — generative & simulation
- Particle systems: fire, smoke, sparks, rain, snow, dust, swarms/boids (flocking)
- Fractals: Mandelbrot/Julia sets, iterated function systems (IFS), L-systems (branching/plants), flame fractals, fractal noise (fBm — fractal Brownian motion)
- Fields & automata: flow fields / vector fields (particle advection), reaction-diffusion (Turing patterns), cellular automata (Game of Life and beyond), diffusion-limited aggregation, physarum/slime-mold simulation
- Physics: cloth, fluid (Navier–Stokes solvers, FLIP), rigid/soft body, spring systems, verlet integration
- Procedural: Voronoi/Worley cells, truchet tiles, wave function collapse, space colonization, marching squares/cubes, metaballs

### 10.5 Visual effects — 3D & rendering
- Raymarching (SDF rendering): soft shadows, ambient occlusion from distance fields, infinite repetition (domain repetition), smooth boolean blending
- Shading: PBR (physically based rendering), subsurface scattering, fresnel/rim light, matcaps, iridescence/thin-film
- Light: volumetric light / god rays, caustics, global illumination, HDRI environment lighting
- Camera: depth of field, motion blur, lens distortion, screen-space ambient occlusion (SSAO), screen-space reflections
- Non-photoreal: toon ramps, hatching shaders, outline extraction (inverted hull, depth/normal edge detection), pixel-art 3D, dither shading

### 10.6 Audio effects
| Family | Effects |
|---|---|
| EQ & filters | Parametric EQ, shelving, graphic EQ, low/high/band-pass, notch, resonant filters, filter sweeps, formant filters, comb filters, dynamic EQ |
| Dynamics | Compression, limiting, gating, expansion, multiband compression, parallel (NY) compression, sidechain compression/ducking (the "pumping" effect), transient shaping, de-essing |
| Saturation & distortion | Overdrive, fuzz, tube/tape saturation, waveshaping, bitcrushing, sample-rate reduction, clipping (soft/hard) |
| Modulation | Chorus, flanger, phaser, tremolo, vibrato, ring modulation, auto-pan, rotary/Leslie |
| Delay | Slapback, ping-pong, tape delay (with wow/flutter), multi-tap, dub delay, reverse delay |
| Reverb | Room, hall, chamber, plate, spring, convolution (impulse responses of real spaces), shimmer (pitch-shifted feedback), gated reverb, reverse reverb, pre-delay as a design parameter |
| Pitch | Pitch shifting, harmonizers, autotune (corrective and as an effect), formant shifting, whammy/dive effects |
| Time & texture | Time-stretching, reverse, stutter/glitch edits, tape stop, granular processing (clouds, freezes, texture beds), spectral processing (freeze, blur, morph), vocoder, talk box |
| Stereo & space | Stereo widening, panning automation, Haas effect (precedence-based width), mid/side processing, binaural/HRTF placement, ambisonics, Doppler |

### 10.7 Synthesis techniques (audio)
Subtractive, FM (frequency modulation), AM, additive, wavetable, physical modeling (Karplus–Strong strings, modal synthesis), granular, sample-based, vector synthesis, west-coast (complex oscillators, wavefolding, low-pass gates)

### 10.8 Sound-design vocabulary (commercial/motion work)
Risers, downlifters, impacts/hits, whooshes, swells, stingers, drones, braams, sub drops, tick/UI sounds, foley layers, room tone, walla — and the mix craft that carries them: ducking under VO, frequency slotting, loudness standards (LUFS for broadcast/web)

---

## Part 11 — Genre Glossaries

Organized as **feature bundles** (Part 6): use these as working vocabularies, not true ontologies. Boundaries are fuzzy, axes non-orthogonal, lineage matters.

### 11.1 Art movements (historical spine)
| Era | Movements — defining features |
|---|---|
| Pre-modern | **Renaissance** (perspective, anatomical accuracy, classical revival) → **Baroque** (drama, chiaroscuro, diagonal energy) → **Rococo** (ornament, pastel, playfulness) → **Neoclassicism** (order, line, civic virtue) → **Romanticism** (sublime, emotion, nature's power) → **Realism** (unidealized ordinary life) |
| Modern break | **Impressionism** (light, broken color, momentary perception) → **Post-Impressionism** (structure/symbol: Cézanne's geometry, Van Gogh's expressive mark, Gauguin's flat color) → **Pointillism** (optical mixing) → **Art Nouveau** (organic whiplash line, integrated ornament) |
| Early avant-garde | **Fauvism** (color liberated from description) · **Expressionism** (distortion for inner states) · **Cubism** (simultaneous viewpoints, fractured planes) · **Futurism** (speed, machines, motion lines) · **Dada** (anti-art, chance, collage, readymades) · **Surrealism** (dream logic, juxtaposition, automatism) |
| Design-adjacent | **Constructivism** (diagonals, photomontage, agitprop geometry) · **De Stijl** (primary colors, orthogonal grid) · **Bauhaus** (form follows function, geometric sans, unity of art/craft) · **Art Deco** (streamlined luxury, symmetry, gold/black) |
| Post-war | **Abstract Expressionism** (scale, gesture, field) · **Pop Art** (mass culture, flat commercial color, repetition) · **Op Art** (perceptual vibration, moiré) · **Minimalism** (reduction, seriality, literal materials) · **Conceptual** (idea over object) · **Photorealism** · **Land Art** · **Street Art / Graffiti** (letterform, wildstyle, stencil) |
| Contemporary/digital | **New Media / Digital Art**, **Generative Art** (algorithmic, systems-as-medium), **Glitch Art**, **Net Art**, **Post-Internet**, **AI Art** |

### 11.2 Design & illustration genres (working commercial vocabulary)
- **Swiss / International Typographic Style** — grid, Helvetica lineage, objective photography, asymmetric balance (the backbone of corporate design)
- **Psychedelic** (melting letterforms, vibrating complementaries) · **Punk/grunge** (xerox texture, ransom type, deliberate damage) · **Memphis** (squiggles, clashing pastels, playful geometry) · **Vaporwave** (Roman busts, gradients, glitch, 80s–90s consumer nostalgia) · **Y2K** (chrome, lens flares, tech-optimism blobs) · **Cyberpunk** (neon-on-dark, HUD elements, decay + tech) · **Solarpunk** (organic + tech, optimist green futurism)
- **Flat design** ↔ **skeuomorphism** ↔ **neumorphism** ↔ **glassmorphism** (the UI-style pendulum) · **Web brutalism** (raw HTML aesthetics, anti-polish) · **Corporate flat** ("Corporate Memphis" figure illustration)
- **Pixel art**, **low-poly**, **isometric**, **voxel**, **line art / mono-weight**, **collage/cut-out**, **risograph** (limited spot colors, misregistration), **halftone/print revival**
- Non-Western lineages every commercial artist mines: **ukiyo-e** (flat planes, bold outline, cropping), **anime/manga** style families, **Persian miniature**, **Aboriginal dot painting**, **African textile geometry** — study with attribution and care

### 11.3 Music genres (feature-bundle spine)
| Family | Genres — quick feature handles |
|---|---|
| Classical lineage | Medieval (chant, modal) → Renaissance (polyphony) → **Baroque** (counterpoint, figured bass, terraced dynamics) → **Classical** (sonata form, balance) → **Romantic** (chromaticism, rubato, scale) → **Modern** (atonality, serialism) → **Minimalism** (phasing, process, repetition — Reich, Glass; hugely relevant to commercial scoring) |
| Blues & descendants | **Blues** (12-bar, blue notes, call-response) → **R&B** → **Soul** (gospel harmony, melisma) → **Funk** (the one, syncopated 16ths, interlocking riffs) → contemporary **R&B** (sparse 808s, melisma over space) |
| Jazz | Dixieland → **Swing** (big band, ride pulse) → **Bebop** (fast changes, virtuosic lines) → **Cool** → **Hard bop** → **Modal** (static harmony, So What) → **Free** → **Fusion** (electric, rock energy) |
| Rock | Rock'n'roll → **Psychedelic** (studio-as-instrument) → **Prog** (odd meters, suites) → **Punk** (speed, three chords, DIY) → **Post-punk** (angular, bass-led) → **New wave** (synths, pop economy) → **Metal** family (distortion, riff-centric; doom/thrash/death/black as tempo-timbre variants) → **Grunge** → **Indie** → **Shoegaze** (wall of texture, buried vocals) → **Post-rock** (crescendo form, instrumental) |
| Hip-hop | **Boom bap** (swung sampled breaks) → **G-funk** → **Trap** (rolled hi-hats, 808 sub, half-time feel) → **Drill** (sliding 808s, darker) → **Lo-fi hip-hop** (dusty texture, jazz chords — ubiquitous in web/ad space) |
| Electronic | **House** (4-on-floor ~120–128; deep/tech/progressive variants) · **Techno** (machine repetition, timbre-as-melody) · **Trance** (supersaw builds, breakdown-drop arcs) · **Jungle/DnB** (chopped breaks ~170) · **UK garage** (shuffled 2-step) · **Dubstep** (140, half-time, bass design) · **Ambient** (beatless, texture-first — Eno; core commercial bed music) · **IDM** (broken programming, sound design foregrounded) · **Downtempo/trip-hop** · **Synthwave** (80s palette nostalgia) · **EDM big-room** (festival build-drop grammar) |
| Roots & regional | **Country/folk** (narrative, acoustic timbres) · **Reggae/dub** (offbeat skank; dub = the birthplace of mix-as-instrument: drop-outs, delay throws) · **Ska** · **Salsa** (clave), **Bossa nova** (soft syncopation, rich harmony), **Reggaeton** (dembow pattern), **Cumbia** · **Afrobeat** (Fela: long-form interlock) & **Afrobeats** (contemporary) · **Highlife** · **K-pop** (maximalist genre-splicing production) · **City pop** · **Gamelan** (metallophone cycles, colotomic structure) · **Indian classical** (raga/tala systems) |
| Functional | **Film/game scoring idioms**: leitmotif, underscore, Mickey-Mousing, drone tension, hybrid orchestral-electronic, adaptive/vertical layering (games) — the most directly applicable vocabulary for commercial work |

**How to use these glossaries:** each genre = a bundle of {palette/timbre, rhythmic template, harmonic vocabulary, form, production conventions, historical lineage}. When a brief says "make it feel like X," decompose X into the bundle and decide which features to keep, exaggerate, or swap. Cross-breeding bundles is a reliable ideation method (Part 6, forced analogy).

---

## Part 12 — The Visual System, Auditory System, and Connected Brain Systems

The biological substrate for everything in Part 4. Organized as signal paths.

### 12.1 The visual pathway
**Optics → Retina.** Cornea and lens focus; iris/pupil controls light. The retina is already a computer:
- **Rods** (~120M): dim light, achromatic, absent from the fovea — why faint stars vanish when looked at directly.
- **Cones** (~6M): three types — S, M, L (short/medium/long wavelength) — concentrated in the **fovea**, the tiny high-resolution center (~2° of visual field). Everything sharp you "see" is foveal; the periphery is low-res and motion-sensitive. Vision feels uniform only because of saccades + memory.
- **Retinal ganglion cells** with **center-surround receptive fields** perform edge detection *in the eye* — the retina outputs contrast, not brightness. (Why perceived lightness is relative; why simultaneous contrast illusions work; why your grade reads differently on different backgrounds.)
- **Opponent processing**: cone signals are recoded into three channels — light/dark, red/green, blue/yellow. This is why there is no "reddish green," why afterimages take complementary colors, and why OKLab-style perceptual color spaces are built on opponent axes.

**LGN (thalamus).** Relay with three streams: **magnocellular** (fast, motion/luminance, low detail), **parvocellular** (slow, color/fine detail), koniocellular. Motion and detail travel on different wires — you can capture attention with motion in the low-res periphery, but detail must be delivered where the fovea will land.

**V1 (primary visual cortex).** Neurons tuned to **oriented edges** and **spatial frequencies** at specific locations (Hubel & Wiesel). The image is decomposed into something like a local Fourier/Gabor basis — the biological reason frequency-domain thinking (Part 3) matches perception.

**Two cortical streams:**
- **Ventral "what" stream** (V1 → V2 → V4 → inferotemporal cortex): form and identity. V4 for color/curvature; IT for objects; specialized patches — **FFA** (faces — why faces dominate any composition they appear in), **PPA** (places/scenes), **VWFA** (word forms — literate viewers cannot *not* read text in a frame).
- **Dorsal "where/how" stream** (V1 → **V5/MT** → parietal): motion, spatial relations, action guidance. MT is the motion engine — why motion pops in periphery, why smooth easing reads as intentional and linear interpolation reads as mechanical.

**Attention & eye movements.** ~3–4 **saccades**/sec with vision suppressed mid-flight; perception is fixation samples stitched by prediction. Attention = bottom-up salience (contrast, motion, faces — Itti–Koch) × top-down goals. Composition is choreography of saccades: you are designing a fixation sequence.

**Adaptation & constancy.** The system normalizes ruthlessly — color constancy (discounting the illuminant), light/dark adaptation, motion aftereffects. Consequences: grades are judged relative to surround; sustained effects fatigue into invisibility; contrast is the currency, absolute values are not.

### 12.2 The auditory pathway
**Outer/middle ear.** Pinna filters directionally (elevation cues); ossicles impedance-match air to cochlear fluid.

**Cochlea.** The **basilar membrane** is a mechanical Fourier analyzer: high frequencies peak at the base, low at the apex — **tonotopy** (place code). **Inner hair cells** transduce; **outer hair cells** actively amplify and sharpen tuning. **Critical bands** (~1/3-octave resolution) arise here — the basis of masking, and thus of MP3 and of mix "slotting" (two sounds in one band fight; EQ them apart).

**Brainstem.** The **superior olive** computes location from **interaural time differences** (ITD, low frequencies, microsecond precision) and **interaural level differences** (ILD, high frequencies) — the basis of panning, Haas widening, and binaural rendering. Auditory temporal resolution is far finer than visual (~ms vs ~30ms+): rhythm and transients live in a faster regime than anything visual, which is why sound carries impact sync.

**Inferior colliculus → MGN → A1.** Primary auditory cortex keeps tonotopic maps; surrounding **belt/parabelt** areas extract complex features. Dual streams again: ventral (what — identity, speech comprehension) and dorsal (where/how — location, sensorimotor mapping to speech production).

**Auditory scene analysis** (Bregman). The ear receives one summed waveform and must un-mix it — grouping by harmonicity, common onset, common modulation, continuity. This is *literally the auditory Gestalt laws*, and it's the science of mixing: shared onsets fuse layers into one sound; detuning/offsetting separates them; a mix is an instruction set for stream segregation.

### 12.3 Connected brain systems (where art actually lands)
- **Multisensory integration.** The superior colliculus and cortical binding integrate sight/sound by temporal and spatial coincidence; the **McGurk effect** shows vision rewriting what you hear. Practical: A/V sync tolerance is asymmetric (audio-late is far more forgivable than audio-early); a cut lands as one event only if sound and image arrive within the binding window.
- **Reward & emotion.** Music-induced chills correlate with **dopamine** release in the **nucleus accumbens** (Salimpoor); anticipation and resolution drive the response — the neural basis of **expectation theories** of musical emotion (Meyer; Huron's ITPRA model: tension → prediction → reaction → appraisal). Build-and-drop, delayed cadence, subverted pattern: all engineering of prediction error. The **amygdala** handles salience/threat — why dissonance, sub-bass, and sudden onsets read as danger.
- **Motor coupling & groove.** Beat perception recruits **basal ganglia** and **premotor cortex** even when still — rhythm is heard *with the motor system* (entrainment). "Groove" is the pleasurable urge to move, maximized at moderate syncopation (predictable enough to entrain, surprising enough to engage). Directly applicable to motion design: animation that entrains reads as musical.
- **Memory & association.** **Hippocampus** binds episodes; music and smell are potent retrieval cues. Nostalgia-driven genres (synthwave, city pop revival, lo-fi) work through this circuit.
- **Default mode network & aesthetic experience.** Vessel's work: strongly moving artworks engage the DMN (self-referential processing) — aesthetic impact peaks when the work is processed as *self-relevant*, not just perceptually pleasing.
- **Prediction as the master key.** Predictive processing (Part 5) unifies the above: perception = model + error; style = a learned prior; surprise = attention; beauty (one account) = rate of successful prediction-error reduction. Effects, edits, and drops are all manipulations of the audience's generative model.

---

## Part 13 — AI / LLM Workflows (expanded)

### 13.1 LLM as creative-code pair programmer (the core loop)
1. Describe the visual/sonic goal in perceptual terms ("slow breathing glow with organic edge noise")
2. LLM produces GLSL/p5.js/Three.js/Web Audio implementation
3. Run it. **Evaluate perceptually** — the judgment is yours and cannot be delegated
4. Report what's wrong *perceptually* ("falloff too abrupt, motion too regular"); LLM translates to parameter/math changes
5. Ask *why* the change worked → theory arrives attached to a live example (the pull model, Part 0)

This loop is simultaneously a production method and the effects-math curriculum. Each session teaches the primitive it used.

### 13.2 Image pipeline patterns (ComfyUI grammar)
- **Structure control**: ControlNet (depth / canny edges / pose / normal maps) — compose the frame yourself, let the model render it. Sketch → depth map → styled render is the highest-control path.
- **Style control**: IP-Adapter (reference-image style transfer), style LoRAs, prompt anchors
- **Consistency**: train a **LoRA** on 20–50 curated images of your target look → reusable house style; character/product consistency via LoRA + fixed seeds + inpainting
- **Refinement**: inpainting for local fixes, outpainting for extension, img2img at low denoise for "art direction pass," tiled upscale for print resolution
- **Batch + select**: generate wide (dozens–hundreds), select narrow — and **log your selections**; they're taste-training data (and can fine-tune a personal aesthetic scorer later)

### 13.3 Video patterns
- Prefer **image-to-video** over text-to-video: art-direct a still first (full control), then animate it
- First/last-frame keyframe conditioning where supported; camera-motion presets for coverage
- **Elements, not shots**: generate backgrounds, textures, atmospheric layers, abstract motion — composite and grade yourself (Resolve/AE). The grade is what unifies AI elements into one look.
- AI utilities inside traditional post: optical-flow retiming, depth-map extraction for fake parallax/DOF, magic mask rotoscoping, voice isolation, Topaz upscale/interpolation

### 13.4 Audio patterns
- Suno/Udio for **sketches and temp tracks** → Demucs to split stems → recompose in DAW, replace weak stems with samples/instruments, add human sound design on top
- ElevenLabs SFX/voice for scratch VO and effects beds; Stable Audio for textures/drones
- Structure-first prompting: specify BPM, key, arrangement arc, and reference bundle features (Part 11 vocabulary pays off here)
- Always finish in the DAW: AI output is material, not master. Mix, arrange, and loudness-target (LUFS) manually.

### 13.5 LLM in the ideation/production layer
- **Brief expansion**: rough idea → structured creative brief (audience, tone, references, constraints, deliverables)
- **Style-bible RAG**: keep your style bible / brand guidelines as documents an LLM can reference; every generation prompt gets drafted against it for consistency
- **Storyboards & shot lists**: script → beat sheet → shot list → per-shot prompt sheets
- **Naming, copy, microcopy** for the web deliverable itself
- **LLM as critic — with a caution**: use structured critique prompts ("evaluate against the brief: hierarchy, contrast, rhythm; list what a client would flag") for *coverage* — catching things you missed — not for *judgment*. Model taste is mediocre and regresses to the mean; your trained eye outranks it (Part 0 corollary). Never let it be the selector.
- **Agentic batches**: scripted pipelines that generate variation grids overnight (parameter sweeps of a shader, prompt matrices in ComfyUI) → your morning job is pure selection — the highest-value use of your perceptual training

### 13.6 Web-specific AI workflow
- LLM-scaffolded GSAP timelines, Three.js/r3f scenes, Rive state machines; port Shadertoy shaders to production WebGL/WebGPU with LLM help
- Performance pass as an explicit LLM task: "reduce this shader's cost for mid-tier mobile GPUs," `prefers-reduced-motion` fallbacks, lazy-loading strategies
- Asset pipeline: AI-generated → compressed (WebP/AVIF, basis textures) → measured against a performance budget

### 13.7 Provenance discipline (commercial)
Keep a per-project ledger: which assets are AI-generated, by which model, under which license; client indemnification requirements checked at project start (Firefly/Getty/Shutterstock class vs. others); disclose per client policy. Boring, and increasingly the difference between usable and unusable work.

---

## Part 14 — Explanatory / Articulation Training (expanded)

The second network (Part 5): a model *of* your skill, trained on its own data. Protocols, ordered from solo to social:

### 14.1 Solo protocols
- **Weekly postmortems** (already in Track A): what reads wrong, hypothesis why, what to study. The hypothesis is the articulation rep — force a mechanism, not just a verdict.
- **Commentary tracks**: record yourself explaining decisions on a finished piece. **After, never during** — explicit monitoring degrades proceduralized execution (Beilock, Part 5). Post-hoc narration is safe; concurrent narration is the choking condition.
- **Feynman technique / teach-back**: explain a technique (say, why premultiplied alpha exists) as if to a novice, in writing, no jargon. Gaps in the explanation are gaps in the model.
- **Critique structure — Feldman's four steps**: *describe* (only what is literally there) → *analyze* (how elements relate: hierarchy, rhythm, palette structure) → *interpret* (what it communicates) → *judge* (does it succeed at its aim). The describe step is the discipline: most people jump to judgment; forcing pure description trains the vocabulary-perception link (Schooler, Part 4).
- **Personal design language document**: a living glossary of *your* recurring moves, named. Naming a move makes it deployable on demand and explainable to others.
- **Rubric construction**: before making a piece, write the rubric you'd grade it by. Comparing intended rubric vs. actual failure modes calibrates the explanatory model against the policy.

### 14.2 Social protocols (where the training signal is honest)
- **Calibration exercises**: before showing work, predict what others will flag. Score your predictions. This directly trains the expert-blind-spot away — you're learning a model of *how your work reads from outside*.
- **Pair critique with vocabulary constraint**: critique a partner's piece using only Part 4/Part 6 vocabulary (masking, hierarchy, spectral slotting, grouping). Forces mechanism-level explanation.
- **Brief-writing reps**: write briefs for imaginary (or real) collaborators, then check: could someone produce the right thing from this alone? Language specifies a target, not a policy (Part 5) — brief-writing is learning how much of the target survives the channel.
- **Client translation drills**: take one technical decision ("I used a 2:1 pre-delay on the reverb," "the grid is an 8pt modular scale") and re-express it as a client benefit ("the voice sits closer to you," "everything will feel aligned without you knowing why"). Two audiences, two compressions, same underlying policy.

### 14.3 The faithfulness test
Your explanation of your own skill may be confabulated (Nisbett & Wilson; the interpreter module) — introspection does not verify it. The only real test is **transfer**: *can someone act on your explanation and get the result?* If yes, the articulation network is tracking the policy. If they follow your words and produce the wrong thing, your explanation is a plausible story, not a faithful model — revise it against what they actually did. This is the human version of the ML interpretability problem, and transfer is the only ground truth available.

### 14.4 Why bother (the payoff map)
- **Directing**: AI workflows (Part 13) make you a director of generators — direction *is* articulation
- **Client work**: selling and defending decisions is articulation under adversarial conditions
- **Teaching/leading**: pedagogical content knowledge is a separate competence — start training it before you need it
- **Your own learning**: articulation attempts expose which parts of your skill are load-bearing vs. superstition

---

## Appendix — Glossary of Jargon Used Above
- **Motion (motion design/graphics)**: animated typography and graphical elements over time
- **Edit**: video assembly, timing, rhythm. **Grade**: shaping palette and contrast of footage
- **HCC**: human-centered computing
- **SDF**: signed distance field. **LUT**: lookup table (color transform)
- **MIR**: music information retrieval. **MFCC**: mel-frequency cepstral coefficients
- **LoRA**: low-rank adaptation (lightweight model fine-tune for consistent style)
- ***Wu wei***: effortless action. ***Pu***: the uncarved block. ***Shen***: spirit. ***Zuowang***: sitting-and-forgetting. ***Ziran***: self-so-ness
