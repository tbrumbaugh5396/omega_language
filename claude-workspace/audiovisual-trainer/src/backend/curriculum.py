"""The curriculum: theory spine, drill registry, lab registry, brief ingredients.

Ships as data, not database rows, so it versions with the app. Everything the
user does references these items by stable slug/id.

Structure follows the roadmap:
  TRACKS        Part 1 — MAKE / TOOLS / THEORY, run in parallel
  MODULES       Parts 3-7, 13, 14 — theory pulled by friction, not pushed
  DRILLS        Part 9 module 2 — discrimination training (generators live in
                the frontend; this is the registry the backend validates and
                reports against)
  LABS          Part 9 module 3 — guided builds of the Part 3 math spine
                (starter source lives in the frontend, see labs-content.js)
  BRIEF_*       Part 9 module 1 — ingredients for the weekly brief generator
  ARTICULATION  Part 14 — protocols for the second network
  UNLEARNING    Part 9 module 7 — deliberate prior-suppression drills

A lesson's `pulls` list is the point of the whole design: theory is surfaced
when a piece breaks in a way that matches one of those symptoms.
"""

TRACKS = [
    {
        "id": "make",
        "title": "MAKE",
        "sub": "the practice loop",
        "rule": "One finished piece per week, no exceptions.",
        "blurb": "Brief → produce → evaluate → identify what broke → pull theory "
                 "for that break → next piece. Finished beats perfect; the "
                 "archive plus a one-paragraph postmortem is the deliverable.",
    },
    {
        "id": "tools",
        "title": "TOOLS",
        "sub": "deliberate practice",
        "rule": "One tool at a time until it becomes invisible.",
        "blurb": "Isolate a sub-skill, drill it with fast feedback, recombine. "
                 "Invisible means no menu-hunting — the hands know it.",
    },
    {
        "id": "theory",
        "title": "THEORY",
        "sub": "pulled, not pushed",
        "rule": "Read the section that explains this week's failure.",
        "blurb": "The topic map is large on purpose. You are not meant to march "
                 "through it; you are meant to raid it when something breaks.",
    },
    {
        "id": "perception",
        "title": "PERCEPTION",
        "sub": "runs inside all tracks",
        "rule": "High volume, rapid feedback, discrimination-focused.",
        "blurb": "A/B drills, blind identification, reference immersion, and "
                 "vocabulary built alongside the eye and ear — naming a "
                 "discrimination sharpens it.",
    },
]

# ---------------------------------------------------------------- theory map

MODULES = [
    # ---------------------------------------------------- Part 3
    {
        "slug": "math-visual",
        "part": "Part 3",
        "title": "The math of effects — visual",
        "blurb": "Smaller than it looks. Learn these six and you construct "
                 "effects instead of shopping for plugins.",
        "lessons": [
            {
                "slug": "compositing-algebra",
                "title": "Compositing algebra",
                "domain": "visual",
                "key": [
                    "Porter-Duff operators: over, in, out, atop — a small closed "
                    "algebra that every layer stack is written in.",
                    "Blend modes are per-channel functions applied before the "
                    "Porter-Duff composite, not a replacement for it.",
                    "Premultiplied alpha exists so that filtering and compositing "
                    "commute; straight alpha halos on resize because the colour of "
                    "fully transparent pixels leaks into the interpolation.",
                ],
                "pulls": [
                    "dark or bright halo around a keyed/masked edge",
                    "edges fringe when a layer is scaled or blurred",
                    "a composite looks right in one app and wrong in another",
                ],
                "lab": "blend-porter-duff",
                "drills": ["gamma-composite"],
                "practice": "Rebuild 'screen', 'multiply' and 'over' by hand on a "
                            "canvas, with and without premultiplication. Break it "
                            "on purpose, then explain the halo.",
            },
            {
                "slug": "color-spaces",
                "title": "Colour, transfer functions, OKLab",
                "domain": "visual",
                "key": [
                    "Gamma-encoded sRGB is not light. Blurs, blends and resizes are "
                    "physically wrong unless done in linear light.",
                    "OKLab is built on opponent axes (Part 4/12) which is why its "
                    "lightness and hue behave the way your eye expects.",
                    "A LUT is just a sampled function; the interesting question is "
                    "always what space it was authored in.",
                ],
                "pulls": [
                    "gradients go grey/muddy through the midpoint",
                    "a hue shifts as you lighten it",
                    "the grade falls apart on a different display",
                ],
                "lab": "color-linear-oklab",
                "drills": ["grade-ab", "gamma-composite"],
                "practice": "Make the same gradient in sRGB, linear and OKLab. "
                            "Name what each one does wrong.",
            },
            {
                "slug": "convolution",
                "title": "Convolution kernels",
                "domain": "visual",
                "key": [
                    "Blur, sharpen and edge detection are one operation with "
                    "different kernels.",
                    "Separable kernels (Gaussian) turn O(n²) into O(2n) — the "
                    "reason big blurs are affordable at all.",
                    "Unsharp mask is image + k·(image − blur(image)): sharpening is "
                    "a high-pass boost, not added detail.",
                ],
                "pulls": [
                    "blur looks boxy or banded",
                    "sharpening produces halos",
                    "edge detection is noisy",
                ],
                "lab": "convolve-kernel",
                "drills": ["blur-id"],
                "practice": "Build a box blur, then a Gaussian, then design a "
                            "kernel nobody named.",
            },
            {
                "slug": "noise",
                "title": "Noise functions",
                "domain": "visual",
                "key": [
                    "Value/Perlin/simplex are lattice gradient noises: smooth, "
                    "band-limited, cheap. Worley is distance-to-feature-points.",
                    "fBm sums octaves at halving amplitude and doubling frequency "
                    "— the source of almost all organic texture.",
                    "Noise is the standard way to break machine regularity, which "
                    "is what makes motion read as alive (Part 5, prediction).",
                ],
                "pulls": [
                    "texture reads as CG/too clean",
                    "motion is too regular to be believable",
                    "visible tiling or grid artefacts in a procedural texture",
                ],
                "lab": "noise-fbm",
                "drills": ["noise-id"],
                "practice": "fBm a cloud bed, then swap in Worley and watch the "
                            "material change without touching the palette.",
            },
            {
                "slug": "sdf",
                "title": "Signed distance fields",
                "domain": "visual",
                "key": [
                    "An SDF returns distance to a surface, so shape, outline, glow "
                    "and shadow all fall out of one function.",
                    "smin (smooth minimum) gives boolean blending that looks cast, "
                    "not cut.",
                    "Domain repetition is free infinity; raymarching is just "
                    "stepping by the distance you know is safe.",
                ],
                "pulls": [
                    "a logo needs to morph, glow or extrude cleanly",
                    "outlines are inconsistent in weight",
                    "you need resolution-independent shapes",
                ],
                "lab": "sdf-shapes",
                "drills": [],
                "practice": "Raymarch a logo. Add soft shadow from the distance "
                            "field alone.",
            },
            {
                "slug": "motion-grammar",
                "title": "Particles, easing, interpolation",
                "domain": "visual",
                "key": [
                    "Easing curves are the grammar of motion: linear reads "
                    "mechanical because nothing physical starts at full speed.",
                    "Overshoot and settle communicate mass; duration communicates "
                    "size.",
                    "Particles are a system, not an asset — emission, forces, "
                    "lifetime, and death shape the read.",
                ],
                "pulls": [
                    "animation feels robotic or cheap",
                    "objects feel weightless",
                    "timing reads as arbitrary",
                ],
                "lab": "easing-curves",
                "drills": ["easing-id"],
                "practice": "Animate one square four ways so a viewer can name the "
                            "material it's made of.",
            },
        ],
    },
    # ---------------------------------------------------- Part 3 audio
    {
        "slug": "math-audio",
        "part": "Part 3",
        "title": "The math of effects — audio",
        "blurb": "Five primitives underneath the whole effects rack.",
        "lessons": [
            {
                "slug": "biquad",
                "title": "Biquad filters (EQ primitives)",
                "domain": "audio",
                "key": [
                    "One two-pole/two-zero difference equation gives low/high/band "
                    "pass, shelf, peak and notch — only the coefficients differ.",
                    "Q is bandwidth; resonance is Q high enough to ring.",
                    "Every minimum-phase EQ move costs phase. That is why a boost "
                    "here and a cut there are not equivalent.",
                ],
                "pulls": [
                    "two elements fight in the same band",
                    "EQ makes it thinner rather than clearer",
                    "a filter sweep sounds harsh at the top",
                ],
                "lab": "biquad-response",
                "drills": ["eq-band-id"],
                "practice": "Slot a bass and a kick by ear, then look at the "
                            "analyser and see whether your ear or the curve won.",
            },
            {
                "slug": "delay-lines",
                "title": "Delay lines",
                "domain": "audio",
                "key": [
                    "Echo, chorus, flanger and comb filtering are one delay line at "
                    "different times and modulation depths.",
                    "Under ~30 ms you hear timbre (comb), not repetition; above it "
                    "you hear space, then rhythm.",
                    "The Haas window (~1-35 ms) buys width without audible echo — "
                    "the precedence effect doing the work.",
                ],
                "pulls": [
                    "a doubled part sounds hollow or phasey in mono",
                    "the mix collapses on a phone speaker",
                    "widening makes the centre vague",
                ],
                "lab": "delay-comb",
                "drills": ["haas-direction", "mod-id"],
                "practice": "Sweep one delay from 0.2 ms to 400 ms and name every "
                            "regime it passes through.",
            },
            {
                "slug": "waveshaping",
                "title": "Waveshaping and distortion",
                "domain": "audio",
                "key": [
                    "A memoryless transfer curve maps input to output; its shape "
                    "decides which harmonics appear.",
                    "Odd symmetry gives odd harmonics (hollow, aggressive); "
                    "asymmetry adds even harmonics (warm, valve-like).",
                    "Bitcrush and sample-rate reduction are quantisation and "
                    "aliasing, not distortion — the artefacts fold, not stack.",
                ],
                "pulls": [
                    "a part won't cut through without getting louder",
                    "saturation sounds fizzy rather than thick",
                    "distortion turns to mush in the low end",
                ],
                "lab": "waveshaper-curve",
                "drills": ["distortion-id"],
                "practice": "Draw three curves. Predict the harmonic series each "
                            "will produce, then check on the analyser.",
            },
            {
                "slug": "granular",
                "title": "Granular synthesis",
                "domain": "audio",
                "key": [
                    "Chop into grains (5-100 ms), window them, scatter them: "
                    "position, density, size, pitch and spray are the controls.",
                    "Time and pitch become independent, which is what makes "
                    "freezes and texture beds possible.",
                    "Grain rate crossing ~20 Hz turns rhythm into pitch — the "
                    "boundary is perceptual, not mathematical.",
                ],
                "pulls": [
                    "need a bed that never loops audibly",
                    "a sound needs stretching without chipmunking",
                    "transitions need texture rather than a sweep",
                ],
                "lab": "granular-cloud",
                "drills": [],
                "practice": "Build a 30-second bed from a 1-second recording, with "
                            "no audible repeat.",
            },
            {
                "slug": "convolution-audio",
                "title": "Convolution and impulse responses",
                "domain": "audio",
                "key": [
                    "An IR is the room's fingerprint; convolution replays your "
                    "signal through it.",
                    "Pre-delay separates source from space and is the single most "
                    "useful reverb design parameter.",
                    "Anything can be an IR — convolve with a non-room and you get "
                    "a resonator, not a reverb.",
                ],
                "pulls": [
                    "reverb pushes the voice away instead of placing it",
                    "the mix is washed out but still not spacious",
                    "space sounds fake or pasted on",
                ],
                "lab": "convolution-reverb",
                "drills": ["reverb-id"],
                "practice": "Synthesise three IRs (noise burst × decay envelope) "
                            "and match one to a picture of a room.",
            },
        ],
    },
    # ---------------------------------------------------- Part 3 shared
    {
        "slug": "math-shared",
        "part": "Part 3",
        "title": "Shared foundations",
        "blurb": "Where the audio and visual halves turn out to be the same "
                 "subject. Worth real study rather than skimming.",
        "lessons": [
            {
                "slug": "fourier",
                "title": "Fourier analysis",
                "domain": "shared",
                "key": [
                    "Any signal is a sum of sinusoids; the spectrum is a change of "
                    "basis, not an approximation.",
                    "Time-frequency resolution trades off (the window decides what "
                    "you can see) — this is the spectrogram's whole character.",
                    "Image side: frequency-domain filtering, DCT/JPEG, Gaussian "
                    "pyramids, texture synthesis. V1 does something Gabor-like, "
                    "which is why this basis matches perception (Part 12).",
                ],
                "pulls": [
                    "need to time-stretch without artefacts",
                    "need to understand what an EQ move actually does",
                    "compression artefacts you can see or hear but not name",
                ],
                "lab": "fourier-scope",
                "drills": ["eq-band-id", "spatial-freq"],
                "practice": "Additively rebuild a square wave, then a face, and "
                            "watch what the first few coefficients carry.",
            },
            {
                "slug": "sampling",
                "title": "Sampling, aliasing, Nyquist",
                "domain": "shared",
                "key": [
                    "Above half the sample rate, content folds back down — it does "
                    "not disappear.",
                    "Visual aliasing is the same phenomenon: moiré, crawling "
                    "edges, wagon wheels, shimmering fine texture in motion.",
                    "Band-limit before you resample. Supersampling is the visual "
                    "oversampling story.",
                ],
                "pulls": [
                    "fine texture crawls or shimmers when it moves",
                    "moiré on a shirt or a grid",
                    "distortion sounds metallic in the top octave",
                ],
                "lab": "aliasing-demo",
                "drills": [],
                "practice": "Render a fine grid moving slowly, with and without "
                            "supersampling. Same maths as the metallic fizz.",
            },
        ],
    },
    # ---------------------------------------------------- Part 4
    {
        "slug": "perception-vision",
        "part": "Part 4",
        "title": "Perception — vision",
        "blurb": "Why some layouts read instantly and others fight the viewer.",
        "lessons": [
            {
                "slug": "opponent-color",
                "title": "Opponent process colour",
                "domain": "visual",
                "key": [
                    "Cone signals are recoded into light/dark, red/green, "
                    "blue/yellow — there is no reddish green.",
                    "Afterimages take the complementary colour because the "
                    "channel, not the cone, fatigues.",
                    "Perceptual colour spaces are built on these axes; that is why "
                    "they behave.",
                ],
                "pulls": [
                    "a palette feels off but every colour is 'correct'",
                    "complementary pairs vibrate uncomfortably",
                ],
                "lab": "color-linear-oklab",
                "drills": ["color-opponent"],
                "practice": "Build a duotone in opponent axes, then in RGB. Notice "
                            "which one you can control.",
            },
            {
                "slug": "contrast-sensitivity",
                "title": "Contrast sensitivity and spatial frequency",
                "domain": "visual",
                "key": [
                    "Sensitivity peaks at mid spatial frequencies and falls off at "
                    "both ends — detail hierarchy is a physiological fact.",
                    "The retina outputs contrast, not brightness (centre-surround), "
                    "so lightness is always relative to surround.",
                    "Squint or blur your comp: what survives is what the viewer "
                    "gets in the first fixation.",
                ],
                "pulls": [
                    "layout has no hierarchy at a glance",
                    "text disappears against an image",
                    "a design that works big dies small",
                ],
                "lab": "convolve-kernel",
                "drills": ["spatial-freq", "contrast-ratio"],
                "practice": "Blur every comp to 5% size before shipping. If the "
                            "read changes, the hierarchy was decoration.",
            },
            {
                "slug": "gestalt",
                "title": "Gestalt grouping as layout physics",
                "domain": "visual",
                "key": [
                    "Proximity, similarity, continuity, closure and common fate "
                    "are not style advice — they are how grouping happens.",
                    "Common fate is the strongest and the most under-used: things "
                    "that move together are one thing.",
                    "Whitespace is the grouping instrument you already own.",
                ],
                "pulls": [
                    "elements that belong together don't read as a set",
                    "the eye can't find the entry point",
                    "a list reads as noise",
                ],
                "lab": None,
                "drills": ["gestalt-group", "alignment-grid"],
                "practice": "Take one dense layout and fix it using only spacing.",
            },
            {
                "slug": "saliency-attention",
                "title": "Saliency, saccades, change blindness",
                "domain": "visual",
                "key": [
                    "~3-4 saccades a second with vision suppressed in flight; you "
                    "are designing a fixation sequence, not a picture.",
                    "Bottom-up salience is contrast, motion and faces; top-down is "
                    "the viewer's goal. Both are steerable.",
                    "Change blindness is why a cut can hide almost anything, and "
                    "why 'they'll notice' is usually false.",
                ],
                "pulls": [
                    "viewers look at the wrong thing first",
                    "the CTA is invisible in testing",
                    "a face in frame eats the composition",
                ],
                "lab": "saliency-map",
                "drills": ["saliency-predict"],
                "practice": "Predict the first three fixations on your own comp, "
                            "then run the saliency map and score yourself.",
            },
        ],
    },
    {
        "slug": "perception-audition",
        "part": "Part 4",
        "title": "Perception — audition",
        "blurb": "The mix is an instruction set for the listener's scene analysis.",
        "lessons": [
            {
                "slug": "equal-loudness",
                "title": "Equal-loudness contours",
                "domain": "audio",
                "key": [
                    "Perceived loudness depends on frequency and level; bass and "
                    "top fall away as you turn down.",
                    "Mixes made loud are bass-heavy when played quiet, and vice "
                    "versa. Check at the level the audience will use.",
                    "Louder is heard as better — level-match before every A/B or "
                    "you are testing gain, not choice.",
                ],
                "pulls": [
                    "mix falls apart at low volume",
                    "your mix is bass-heavy everywhere but your room",
                ],
                "lab": None,
                "drills": ["loudness-match"],
                "practice": "Mix a bed at conversational level only. Then check "
                            "loud.",
            },
            {
                "slug": "masking",
                "title": "Auditory masking and critical bands",
                "domain": "audio",
                "key": [
                    "The cochlea resolves roughly a third of an octave at a time; "
                    "two sounds in one band fight.",
                    "Masking is both spectral and temporal (a loud transient hides "
                    "what came just before and after it).",
                    "Frequency slotting is not an EQ trick, it is making room.",
                ],
                "pulls": [
                    "the vocal is buried but raising it wrecks the balance",
                    "a busy mix loses its detail",
                    "everything is loud and nothing is clear",
                ],
                "lab": "biquad-response",
                "drills": ["masking-threshold", "eq-band-id"],
                "practice": "Find the exact band where two elements collide by "
                            "ear, then confirm with a narrow boost sweep.",
            },
            {
                "slug": "precedence",
                "title": "The precedence effect",
                "domain": "audio",
                "key": [
                    "The first arrival wins localisation; later arrivals within "
                    "~35 ms are fused into it as width and tone.",
                    "ITD carries low frequencies, ILD carries high — panning by "
                    "level alone is only half the cue.",
                    "Haas width is mono-fragile: always check the collapse.",
                ],
                "pulls": [
                    "the stereo image is vague or unstable",
                    "width disappears in mono",
                ],
                "lab": "delay-comb",
                "drills": ["haas-direction", "stereo-width"],
                "practice": "Place one source three ways: pan, Haas, and mid/side. "
                            "Rank them for mono survival.",
            },
            {
                "slug": "timbre-asa",
                "title": "Timbre and auditory scene analysis",
                "domain": "audio",
                "key": [
                    "Timbre is spectral envelope plus temporal envelope — the "
                    "attack carries more identity than the steady state.",
                    "Bregman's grouping cues (harmonicity, common onset, common "
                    "modulation, continuity) are the auditory Gestalt laws.",
                    "Shared onsets fuse layers into one instrument; offsetting and "
                    "detuning splits them. That is the whole craft of layering.",
                ],
                "pulls": [
                    "layered sounds refuse to become one sound",
                    "a sample sounds fake when pitched",
                    "the arrangement is crowded but thin",
                ],
                "lab": "fourier-scope",
                "drills": ["transient-id", "interval-id"],
                "practice": "Layer three sources into one hit by aligning onsets, "
                            "then split them again by offsetting 12 ms.",
            },
        ],
    },
    {
        "slug": "perceptual-learning",
        "part": "Part 4",
        "title": "Perceptual learning — the science of trainable taste",
        "blurb": "Why this app is built the way it is.",
        "lessons": [
            {
                "slug": "pl-modules",
                "title": "Discrimination training that works",
                "domain": "meta",
                "key": [
                    "Real changes in discriminability, not just faster labelling — "
                    "radiologists, sonar operators, wine tasters.",
                    "Kellman's protocol: high volume, short trials, immediate "
                    "feedback, discrimination-focused, interleaved difficulty.",
                    "Attentional weighting: the signal-carrying dimensions get "
                    "amplified and the rest suppressed. Most of expertise is the "
                    "suppression.",
                ],
                "pulls": [
                    "you can tell something is wrong but not what",
                    "you agree with a critique only after it is pointed out",
                ],
                "lab": None,
                "drills": [],
                "practice": "Short daily drill sets beat long weekly ones. Ten "
                            "minutes, every day, with feedback on every trial.",
            },
            {
                "slug": "verbal-overshadowing",
                "title": "Vocabulary and verbal overshadowing",
                "domain": "meta",
                "key": [
                    "Describing impairs novice discrimination but not experts', "
                    "because expert vocabulary matches perceptual categories.",
                    "So build the words alongside the eye — not before it, and not "
                    "instead of it.",
                    "A named move is a deployable move.",
                ],
                "pulls": [
                    "you can't say why the better option is better",
                    "critique comes out as vibes",
                ],
                "lab": None,
                "drills": [],
                "practice": "After every A/B drill, name the dimension in one "
                            "phrase before you see the answer.",
            },
            {
                "slug": "accessibility",
                "title": "Accessibility as perception",
                "domain": "shared",
                "key": [
                    "Contrast ratios, motion sensitivity, vestibular triggers, "
                    "caption design, audio intelligibility — the same science.",
                    "prefers-reduced-motion is a perceptual constraint, and "
                    "designing for it usually improves the default.",
                    "It makes the work better; it is not a compliance afterthought.",
                ],
                "pulls": [
                    "client accessibility review flagged the piece",
                    "motion makes some viewers unwell",
                    "captions are unreadable over the footage",
                ],
                "lab": None,
                "drills": ["contrast-ratio"],
                "practice": "Ship one piece that is fully legible with motion off "
                            "and sound off.",
            },
        ],
    },
    # ---------------------------------------------------- Part 5
    {
        "slug": "mastery",
        "part": "Part 5",
        "title": "What the practice loop is building",
        "blurb": "Expertise as amortized search. Read this when you want to know "
                 "why the reps are the point.",
        "lessons": [
            {
                "slug": "amortized-search",
                "title": "Amortized search",
                "domain": "meta",
                "key": [
                    "Expensive deliberation distilled into a fast policy over "
                    "trained perceptual features — the loop stops being what does "
                    "the work.",
                    "Anticipation, not reaction (Abernethy's occlusion studies): "
                    "experts read earlier cues, not faster balls.",
                    "Forward models (Kawato): correcting against a prediction "
                    "short-circuits feedback rather than accelerating it.",
                    "Chunking and proceduralization: control migrates from "
                    "prefrontal toward basal ganglia and cerebellum.",
                ],
                "pulls": ["wondering whether the volume is really necessary"],
                "lab": None,
                "drills": [],
                "practice": "Count reps, not hours.",
            },
            {
                "slug": "dont-think-feel",
                "title": "'Don't think, feel' — and when it is wrong",
                "domain": "meta",
                "key": [
                    "Explicit monitoring (Beilock & Carr) and reinvestment "
                    "(Masters): attending to components of a proceduralized skill "
                    "degrades it. Choking is this mechanism.",
                    "It is stage-dependent. Explicit instruction helps novices "
                    "enormously; the maxim is advice for the proficient only.",
                    "Practical: narrate after, never during.",
                ],
                "pulls": [
                    "you get worse when you try harder",
                    "work is stiff when you are being watched",
                ],
                "lab": None,
                "drills": [],
                "practice": "Record commentary on a finished piece, never on a "
                            "piece in progress.",
            },
            {
                "slug": "compression-problem",
                "title": "The compression problem",
                "domain": "meta",
                "key": [
                    "Fast → verbal is lossy: a high-dimensional policy through a "
                    "low-bandwidth channel (Polanyi; Nisbett & Wilson).",
                    "Verbal → fast is lossy differently: instruction specifies a "
                    "target, not a policy. The policy is found by search.",
                    "Explainability is a separately trained network — nothing "
                    "forces it to be faithful (expert blind spot).",
                ],
                "pulls": [
                    "your feedback to someone didn't produce the fix",
                    "a client brief produced the wrong thing",
                ],
                "lab": None,
                "drills": [],
                "practice": "Train articulation as its own track (Part 14).",
            },
            {
                "slug": "three-forgettings",
                "title": "The three forgettings",
                "domain": "meta",
                "key": [
                    "Pruning through training — learning what does not matter. The "
                    "larger half of expertise; a trained eye goes straight to what "
                    "is wrong.",
                    "Laozi's return to the infant — pre-distinction, not "
                    "post-training. Not reachable by the practice route.",
                    "Deliberate unlearning — suppressing your own trained priors to "
                    "catch what does not fit them. Available only to the expert, "
                    "and the antidote to the expert blind spot.",
                ],
                "pulls": [
                    "every piece is coming out the same",
                    "you can no longer see the work freshly",
                ],
                "lab": None,
                "drills": [],
                "practice": "Run an unlearning exercise when your work starts "
                            "converging on itself.",
            },
            {
                "slug": "wu-wei",
                "title": "Cook Ding, held accurately",
                "domain": "meta",
                "key": [
                    "Zhuangzi's butcher: mastery through immense practice, working "
                    "by shen, the blade finding the gaps. Nineteen years in.",
                    "This maps cleanly onto the science; it is the model that "
                    "supports the artistic project.",
                    "It naturalizes wu wei as skilled action — one thread. It does "
                    "not reach Laozi's subtraction ideal or the cosmological Dao.",
                ],
                "pulls": ["wanting the philosophy without the misreading"],
                "lab": None,
                "drills": [],
                "practice": "Nineteen years is the honest number in the story.",
            },
        ],
    },
    # ---------------------------------------------------- Part 6
    {
        "slug": "analysis",
        "part": "Part 6",
        "title": "Analysis frameworks",
        "blurb": "Formal systems generate and filter; selection stays perceptual.",
        "lessons": [
            {
                "slug": "composition-formal",
                "title": "Composition as generator + filter",
                "domain": "visual",
                "key": [
                    "What formalizes: grids and modular scale, typographic "
                    "hierarchy, visual weight, Gestalt grouping, saliency, "
                    "constraint solvers, design tokens.",
                    "What does not: goodness. The grammatical-but-dull space "
                    "vastly exceeds the good space, and no measure has closed it.",
                    "Operational rule: generate a large valid space formally, "
                    "filter malformedness formally, select perceptually.",
                ],
                "pulls": [
                    "layout is technically correct and still dead",
                    "you need many options fast",
                ],
                "lab": None,
                "drills": ["alignment-grid"],
                "practice": "Use the sandbox: generate 24 layouts, pick one, and "
                            "write why in one sentence.",
            },
            {
                "slug": "genre-bundles",
                "title": "Genre as feature bundle",
                "domain": "shared",
                "key": [
                    "Family resemblance, not taxonomy; prototypes beat "
                    "definitions.",
                    "Two layers: an intrinsic feature bundle (timbre, rhythm, "
                    "harmony, palette, mark-making, production conventions) and a "
                    "social-historical lineage. MIR formalizes the first and fails "
                    "at the second.",
                    "'Make it feel like X' → decompose X into the bundle, then "
                    "decide what to keep, exaggerate or swap.",
                ],
                "pulls": [
                    "a reference-led brief you can't reverse-engineer",
                    "the pastiche is recognisable but lifeless",
                ],
                "lab": None,
                "drills": [],
                "practice": "Cross-breed two bundles deliberately. That is a "
                            "reliable ideation method, not a gimmick.",
            },
            {
                "slug": "mir-features",
                "title": "MIR feature vocabulary",
                "domain": "shared",
                "key": [
                    "Spectral centroid (brightness), spectral flux (rate of "
                    "change), MFCCs, onset density, harmonic-to-noise ratio, "
                    "tempo, harmonic density.",
                    "Visual analogues: edge statistics, palette entropy, contrast "
                    "distribution, spatial frequency profile.",
                    "Measuring a reference beats remembering it.",
                ],
                "pulls": [
                    "you want to match a reference objectively",
                    "the client says 'brighter' and you need a handle",
                ],
                "lab": "fourier-scope",
                "drills": [],
                "practice": "Run five references you love through the analyzer. "
                            "Look for what they share.",
            },
            {
                "slug": "ideation",
                "title": "Ideation as association",
                "domain": "meta",
                "key": [
                    "Moodboarding, constraint-setting, systematic variation, "
                    "forced analogy (Munari).",
                    "Constraints generate; freedom paralyses.",
                    "A style bible is the production interface between association "
                    "and generation.",
                ],
                "pulls": ["blank page", "every idea is the obvious idea"],
                "lab": None,
                "drills": [],
                "practice": "Every generated brief carries a constraint. Keep it.",
            },
        ],
    },
    # ---------------------------------------------------- Part 7
    {
        "slug": "history",
        "part": "Part 7",
        "title": "Historical and technical background",
        "blurb": "Orientation. Pulled by curiosity rather than sequenced.",
        "lessons": [
            {
                "slug": "history-graphics",
                "title": "Computer graphics lineage",
                "domain": "visual",
                "key": [
                    "Raster vs vector as two answers to the same question.",
                    "Sutherland → SIGGRAPH → the GPU era → the shader era.",
                    "The rendering pipeline is why certain things are cheap and "
                    "others are not.",
                ],
                "pulls": ["why does this tool work this way"],
                "lab": None, "drills": [],
                "practice": "Read when a tool's constraint feels arbitrary.",
            },
            {
                "slug": "history-audio",
                "title": "Computer audio lineage",
                "domain": "audio",
                "key": [
                    "Synthesis families: subtractive, FM, wavetable, physical "
                    "modelling, granular — each a different theory of sound.",
                    "MIDI and the DAW as the interface that shaped the music.",
                ],
                "pulls": ["choosing a synthesis approach for a sound you hear"],
                "lab": None, "drills": [],
                "practice": "Match the family to the sound before opening a synth.",
            },
            {
                "slug": "history-video",
                "title": "Film grammar to the colour pipeline",
                "domain": "visual",
                "key": [
                    "Montage and continuity as two theories of the cut.",
                    "Digital intermediate; log, LUTs, ACES as one long attempt to "
                    "keep colour meaningful across devices.",
                ],
                "pulls": ["footage looks flat", "grade won't hold across shots"],
                "lab": "color-linear-oklab", "drills": ["grade-ab"],
                "practice": "Grade one shot from log twice: by numbers, by eye.",
            },
        ],
    },
    # ---------------------------------------------------- Part 13
    {
        "slug": "ai-workflows",
        "part": "Part 13",
        "title": "AI workflows",
        "blurb": "LLMs collapse the symbolic half of production and leave the "
                 "perceptual half untouched. Taste becomes more of the "
                 "bottleneck, not less.",
        "lessons": [
            {
                "slug": "llm-creative-code",
                "title": "LLM as creative-code pair",
                "domain": "meta",
                "key": [
                    "Describe the goal perceptually → get an implementation → run "
                    "it → report what is wrong perceptually → ask why the fix "
                    "worked.",
                    "The judgement is yours and cannot be delegated.",
                    "That last step is the curriculum: theory arrives attached to "
                    "a live example.",
                ],
                "pulls": ["you want the effect and the maths at once"],
                "lab": "sdf-shapes", "drills": [],
                "practice": "Run the loop in the lab. Every session teaches the "
                            "primitive it used.",
            },
            {
                "slug": "elements-not-shots",
                "title": "Generate elements, not shots",
                "domain": "meta",
                "key": [
                    "Structure control first (depth/edge/pose), style control "
                    "second, consistency via LoRA and fixed seeds.",
                    "Prefer image-to-video: art-direct a still, then animate.",
                    "The grade is what unifies generated elements into one look.",
                ],
                "pulls": ["generated shots won't hold art direction"],
                "lab": None, "drills": [],
                "practice": "Composite three generated elements into one graded "
                            "frame. Nobody should be able to tell.",
            },
            {
                "slug": "batch-and-select",
                "title": "Batch wide, select narrow",
                "domain": "meta",
                "key": [
                    "Generating a hundred candidates is cheap; choosing among them "
                    "is not.",
                    "Log your selections — they are taste-training data.",
                    "LLM critique for coverage, never for judgement. Model taste "
                    "regresses to the mean; never let it be the selector.",
                ],
                "pulls": ["drowning in options", "output feels generic"],
                "lab": None, "drills": [],
                "practice": "Overnight parameter sweeps; morning job is pure "
                            "selection. Log every pick in the sandbox.",
            },
            {
                "slug": "provenance",
                "title": "Provenance discipline",
                "domain": "meta",
                "key": [
                    "Per-project ledger: which assets are AI-generated, by which "
                    "model, under which licence.",
                    "Indemnification requirements get checked at project start, "
                    "not at delivery.",
                    "Boring, and increasingly the difference between usable and "
                    "unusable work.",
                ],
                "pulls": ["commercial delivery with AI-generated assets"],
                "lab": None, "drills": [],
                "practice": "Keep the ledger in the piece's notes from day one.",
            },
        ],
    },
    # ---------------------------------------------------- Part 14
    {
        "slug": "articulation",
        "part": "Part 14",
        "title": "Articulation — the second network",
        "blurb": "A model of your skill, trained on its own data. It does not "
                 "come free with the skill.",
        "lessons": [
            {
                "slug": "critique-structure",
                "title": "Feldman's four steps",
                "domain": "meta",
                "key": [
                    "Describe (only what is literally there) → analyze (how "
                    "elements relate) → interpret (what it communicates) → judge "
                    "(does it succeed at its aim).",
                    "The describe step is the discipline; most people jump to "
                    "judgement.",
                    "Forced description trains the vocabulary-perception link.",
                ],
                "pulls": ["critique keeps collapsing into taste assertions"],
                "lab": None, "drills": [],
                "practice": "Run the four steps on one reference a day.",
            },
            {
                "slug": "calibration",
                "title": "Calibration against outside readers",
                "domain": "meta",
                "key": [
                    "Before showing work, predict what others will flag, then "
                    "score the prediction.",
                    "This trains away the expert blind spot: you are learning how "
                    "your work reads from outside.",
                    "Client translation is the same compression, aimed at a "
                    "different audience.",
                ],
                "pulls": ["feedback keeps surprising you"],
                "lab": None, "drills": [],
                "practice": "Log a prediction before every share.",
            },
            {
                "slug": "faithfulness",
                "title": "The faithfulness test",
                "domain": "meta",
                "key": [
                    "Introspection does not verify your account of your own skill.",
                    "The only real test is transfer: can someone act on your "
                    "explanation and get the result?",
                    "If they follow your words and produce the wrong thing, the "
                    "explanation is a plausible story, not a faithful model.",
                ],
                "pulls": ["you taught it and it didn't take"],
                "lab": None, "drills": [],
                "practice": "Write a brief, hand it over, compare what came back.",
            },
        ],
    },
]

LESSONS = {les["slug"]: {**les, "module": mod["slug"], "part": mod["part"],
                         "module_title": mod["title"]}
           for mod in MODULES for les in mod["lessons"]}


# ---------------------------------------------------------------- drills
# Generators live in the frontend (train/*.js); this registry is what the
# backend validates attempts against and reports progress over.
# `dims` names the perceptual dimension being trained, for the progress view.

DRILLS = [
    # --- ear
    {"id": "eq-band-id", "title": "Which band moved?", "craft": "audio",
     "dim": "spectrum", "lesson": "biquad", "levels": 5,
     "blurb": "A single parametric band is boosted or cut on pink noise or a "
              "loop. Name the frequency. The whole EQ craft starts here."},
    {"id": "masking-threshold", "title": "Masked or not?", "craft": "audio",
     "dim": "spectrum", "lesson": "masking", "levels": 4,
     "blurb": "A tone sits under a noise band. Say whether you can hear it. "
              "You are measuring your own critical bands."},
    {"id": "comp-ab", "title": "Which one is compressed?", "craft": "audio",
     "dim": "dynamics", "lesson": "timbre-asa", "levels": 5,
     "blurb": "Level-matched A/B. At high levels the only cue left is the "
              "transient shape."},
    {"id": "transient-id", "title": "Attack time", "craft": "audio",
     "dim": "dynamics", "lesson": "timbre-asa", "levels": 4,
     "blurb": "Order three hits by attack time. Timbre is temporal envelope "
              "as much as spectral."},
    {"id": "reverb-id", "title": "Read the room", "craft": "audio",
     "dim": "space", "lesson": "convolution-audio", "levels": 5,
     "blurb": "Identify decay, pre-delay, or which of two spaces is larger."},
    {"id": "haas-direction", "title": "Precedence", "craft": "audio",
     "dim": "space", "lesson": "precedence", "levels": 4,
     "blurb": "Which side arrives first? Level is matched, so only timing "
              "localises it."},
    {"id": "stereo-width", "title": "Mono survival", "craft": "audio",
     "dim": "space", "lesson": "precedence", "levels": 3,
     "blurb": "Which of two widened versions collapses worst in mono?"},
    {"id": "distortion-id", "title": "Name the distortion", "craft": "audio",
     "dim": "timbre", "lesson": "waveshaping", "levels": 4,
     "blurb": "Soft clip, hard clip, bitcrush, sample-rate reduction. Two of "
              "them fold instead of stacking."},
    {"id": "mod-id", "title": "Chorus, flanger, phaser", "craft": "audio",
     "dim": "timbre", "lesson": "delay-lines", "levels": 3,
     "blurb": "All modulation, different delay times. Tremolo is the control."},
    {"id": "interval-id", "title": "Interval", "craft": "audio",
     "dim": "pitch", "lesson": "timbre-asa", "levels": 5,
     "blurb": "Harmonic vocabulary, built the boring reliable way."},
    {"id": "pitch-cents", "title": "How flat?", "craft": "audio",
     "dim": "pitch", "lesson": "timbre-asa", "levels": 5,
     "blurb": "Detune discrimination, down to a few cents if you get there."},
    {"id": "loudness-match", "title": "Match the loudness", "craft": "audio",
     "dim": "loudness", "lesson": "equal-loudness", "levels": 4,
     "blurb": "Match a low or high band to a mid reference. You are drawing "
              "your own Fletcher-Munson curve."},
    {"id": "tempo-id", "title": "Tempo", "craft": "audio",
     "dim": "rhythm", "lesson": "mir-features", "levels": 3,
     "blurb": "Estimate BPM, then check. Groove work needs this to be free."},

    # --- eye
    {"id": "kerning-ab", "title": "Even the spacing", "craft": "visual",
     "dim": "type", "lesson": "gestalt", "levels": 5,
     "blurb": "Two kernings of one word. Spacing is rhythm, judged by area "
              "between letters, not distance."},
    {"id": "alignment-grid", "title": "Spot the break", "craft": "visual",
     "dim": "layout", "lesson": "composition-formal", "levels": 5,
     "blurb": "One element is off the grid. The margin shrinks as you improve."},
    {"id": "gestalt-group", "title": "Which law is doing the work?", "craft": "visual",
     "dim": "layout", "lesson": "gestalt", "levels": 3,
     "blurb": "Proximity, similarity, continuity, closure, common fate."},
    {"id": "contrast-ratio", "title": "Pass or fail?", "craft": "visual",
     "dim": "color", "lesson": "accessibility", "levels": 4,
     "blurb": "Judge WCAG contrast by eye, then see the number. Calibrates a "
              "judgement you will make hundreds of times."},
    {"id": "grade-ab", "title": "Match the grade", "craft": "visual",
     "dim": "color", "lesson": "color-spaces", "levels": 5,
     "blurb": "Which of two grades matches the target look — and on which axis "
              "does the other one miss?"},
    {"id": "color-opponent", "title": "Opponent axes", "craft": "visual",
     "dim": "color", "lesson": "opponent-color", "levels": 4,
     "blurb": "Find the complementary, spot the hue that shifted under a "
              "lightness change."},
    {"id": "gamma-composite", "title": "Spot the gamma error", "craft": "visual",
     "dim": "color", "lesson": "compositing-algebra", "levels": 4,
     "blurb": "One of these composites was done in the wrong space. The "
              "midtones give it away."},
    {"id": "blur-id", "title": "Name the blur", "craft": "visual",
     "dim": "optics", "lesson": "convolution", "levels": 4,
     "blurb": "Gaussian, box, motion, radial, lens. The kernel is visible in "
              "the highlights."},
    {"id": "noise-id", "title": "Name the noise", "craft": "visual",
     "dim": "texture", "lesson": "noise", "levels": 4,
     "blurb": "White, value, fBm, Worley. Each has a signature at the "
              "feature scale."},
    {"id": "spatial-freq", "title": "Detail hierarchy", "craft": "visual",
     "dim": "optics", "lesson": "contrast-sensitivity", "levels": 4,
     "blurb": "Which image survives the squint test? Which carries its "
              "information in the high band?"},
    {"id": "easing-id", "title": "Read the curve", "craft": "visual",
     "dim": "motion", "lesson": "motion-grammar", "levels": 4,
     "blurb": "Identify the easing from motion alone. Linear is always "
              "identifiable; that is the point."},
    {"id": "saliency-predict", "title": "First fixation", "craft": "visual",
     "dim": "attention", "lesson": "saliency-attention", "levels": 3,
     "blurb": "Click where the eye lands first. Scored against a "
              "centre-surround saliency model."},
]

DRILL_IDS = {d["id"] for d in DRILLS}
DIMENSIONS = {
    "spectrum": "Spectrum", "dynamics": "Dynamics", "space": "Space",
    "timbre": "Timbre", "pitch": "Pitch", "loudness": "Loudness",
    "rhythm": "Rhythm", "type": "Type", "layout": "Layout", "color": "Colour",
    "optics": "Optics", "texture": "Texture", "motion": "Motion",
    "attention": "Attention",
}


# ---------------------------------------------------------------- labs
# Starter source lives in the frontend (labs-content.js) keyed by these ids.

LABS = [
    {"id": "sdf-shapes", "title": "SDF shapes, glow, smooth union",
     "runtime": "glsl", "lesson": "sdf",
     "teaches": "Distance functions give shape, outline, glow and shadow from "
                "one expression.",
     "goals": ["Make the glow falloff physical rather than linear",
               "Blend two shapes so the join reads as cast, not cut",
               "Repeat the domain without repeating the maths"]},
    {"id": "noise-fbm", "title": "Value noise, fBm, Worley",
     "runtime": "glsl", "lesson": "noise",
     "teaches": "Octaves at halving amplitude are where organic texture comes "
                "from.",
     "goals": ["Get a cloud that has no visible lattice",
               "Swap to Worley and watch the material change",
               "Warp the domain with noise and stop it looking like noise"]},
    {"id": "blend-porter-duff", "title": "Blend modes and premultiplied alpha",
     "runtime": "canvas2d", "lesson": "compositing-algebra",
     "teaches": "Why straight alpha halos and premultiplied does not.",
     "goals": ["Reproduce the dark fringe on purpose",
               "Fix it with premultiplication only",
               "Show that multiply and over are different operations"]},
    {"id": "color-linear-oklab", "title": "sRGB vs linear vs OKLab",
     "runtime": "canvas2d", "lesson": "color-spaces",
     "teaches": "Three gradients, three different lies.",
     "goals": ["Find the grey midpoint problem",
               "Keep hue constant across a lightness ramp",
               "Build a duotone that stays legible"]},
    {"id": "convolve-kernel", "title": "Convolution kernel bench",
     "runtime": "canvas2d", "lesson": "convolution",
     "teaches": "Blur, sharpen and edges are one operation.",
     "goals": ["Turn a box blur into a Gaussian by weights alone",
               "Build unsharp mask from a blur",
               "Design a kernel that has no name"]},
    {"id": "easing-curves", "title": "Easing and the read of mass",
     "runtime": "canvas2d", "lesson": "motion-grammar",
     "teaches": "Curves are the grammar of motion; mass is communicated by "
                "overshoot and settle.",
     "goals": ["Make one square feel heavy, then light",
               "Match a spring by hand with a cubic",
               "Find the duration where it stops reading as intentional"]},
    {"id": "saliency-map", "title": "Centre-surround saliency",
     "runtime": "canvas2d", "lesson": "saliency-attention",
     "teaches": "An Itti-Koch-flavoured model of where the eye goes first.",
     "goals": ["Predict before you run it",
               "Move one element and move the first fixation",
               "Find a case where the model is wrong and say why"]},
    {"id": "aliasing-demo", "title": "Aliasing, both kinds",
     "runtime": "canvas2d", "lesson": "sampling",
     "teaches": "Moiré and metallic fizz are the same phenomenon.",
     "goals": ["Make a grid crawl, then band-limit it",
               "Show supersampling paying for itself"]},
    {"id": "biquad-response", "title": "Biquad bench",
     "runtime": "audio", "lesson": "biquad",
     "teaches": "One difference equation, every EQ shape.",
     "goals": ["Slot two sources apart by ear, then check the curve",
               "Find the Q where a peak starts to ring",
               "Hear the phase cost of a big boost"]},
    {"id": "delay-comb", "title": "One delay line, every regime",
     "runtime": "audio", "lesson": "delay-lines",
     "teaches": "Comb, chorus, flange, Haas, slapback, echo — one control.",
     "goals": ["Name every regime as you sweep from 0.2 ms to 400 ms",
               "Get width that survives mono",
               "Build a flanger and a chorus from the same graph"]},
    {"id": "waveshaper-curve", "title": "Transfer curve bench",
     "runtime": "audio", "lesson": "waveshaping",
     "teaches": "The curve's symmetry decides the harmonic series.",
     "goals": ["Produce only odd harmonics, then only even",
               "Make saturation thicken without fizzing",
               "Hear quantisation fold instead of stack"]},
    {"id": "granular-cloud", "title": "Granular cloud",
     "runtime": "audio", "lesson": "granular",
     "teaches": "Time and pitch come apart; rhythm becomes pitch at ~20 Hz.",
     "goals": ["Freeze a moment without it buzzing",
               "Cross the 20 Hz boundary and hear it change category",
               "Build a bed with no audible loop"]},
    {"id": "convolution-reverb", "title": "Synthesise an impulse response",
     "runtime": "audio", "lesson": "convolution-audio",
     "teaches": "Noise × envelope is a room; pre-delay is the design control.",
     "goals": ["Place a voice in a room without pushing it away",
               "Build a plate and a hall from the same noise",
               "Convolve with something that is not a room"]},
    {"id": "fourier-scope", "title": "Spectrum, spectrogram, additive",
     "runtime": "audio", "lesson": "fourier",
     "teaches": "The window decides what you can see.",
     "goals": ["Rebuild a square wave additively",
               "Find the window where a transient smears",
               "Read a mix's slotting off the spectrogram"]},
]

LAB_IDS = {l["id"] for l in LABS}


# ---------------------------------------------------------------- briefs
# Module 1: the weekly brief generator. A brief is a cross-product draw:
# form × constraint × feature-bundle × primitive-to-practice, plus a duration.
# Escalating ambition is handled by the `weight` on forms.

BRIEF_FORMS = [
    {"id": "title-card", "label": "A title card", "medium": "motion", "weight": 1,
     "spec": "One line of type, 3 seconds, must read at 25% size."},
    {"id": "ten-second-spot", "label": "A 10-second spot", "medium": "motion", "weight": 3,
     "spec": "Sound and image. One idea. Must survive muted playback."},
    {"id": "sound-loop", "label": "A sound-designed loop", "medium": "audio", "weight": 2,
     "spec": "8-16 bars, seamless, three layers minimum, no stock one-shots "
             "left unprocessed."},
    {"id": "shader-sketch", "label": "A shader sketch", "medium": "shader", "weight": 2,
     "spec": "Single fragment shader, 60fps on a mid-tier mobile GPU."},
    {"id": "animated-poster", "label": "An animated poster", "medium": "motion", "weight": 2,
     "spec": "Static composition that earns its motion; loops under 6 seconds."},
    {"id": "stinger", "label": "A logo stinger", "medium": "motion", "weight": 2,
     "spec": "Under 2 seconds, audio and image locked to the same frame."},
    {"id": "grade-study", "label": "A grade study", "medium": "edit", "weight": 1,
     "spec": "One shot, three grades, one sentence each on what changed."},
    {"id": "texture-bed", "label": "An ambient bed", "medium": "audio", "weight": 1,
     "spec": "90 seconds, no audible repeat, sits under a voice without "
             "masking it."},
    {"id": "web-hero", "label": "A web hero section", "medium": "web", "weight": 3,
     "spec": "Interactive, respects prefers-reduced-motion, under a stated "
             "performance budget."},
    {"id": "cut-study", "label": "A cutting study", "medium": "edit", "weight": 2,
     "spec": "30 seconds from found footage. Rhythm is the subject."},
    {"id": "still-series", "label": "A series of three stills", "medium": "still", "weight": 1,
     "spec": "One system, three outputs. The system must be visible."},
    {"id": "ui-motion", "label": "A UI motion set", "medium": "web", "weight": 2,
     "spec": "Four transitions from one easing language."},
]

BRIEF_CONSTRAINTS = [
    "Two colours only, plus paper.",
    "No cuts.",
    "Everything must be built from one primitive.",
    "Monochrome. Value does all the work.",
    "No easing library — hand-authored curves only.",
    "One typeface, one weight.",
    "Mono audio only.",
    "Nothing above 2 kHz.",
    "No sound design library — synthesise every element.",
    "Must read at 5% size after a heavy blur.",
    "Under 100 KB delivered.",
    "The grid must be visible in the result.",
    "One continuous camera move.",
    "No more than three elements on screen at once.",
    "Silence for at least a third of the runtime.",
    "Must work with motion disabled.",
    "Every asset generated procedurally.",
    "One hour, hard stop.",
    "Reuse last week's piece as the only source material.",
    "No black and no white.",
]

# Feature bundles drawn from the Part 11 glossaries, kept as handles.
BRIEF_BUNDLES = [
    {"label": "Swiss / International Typographic", "features":
     "grid, asymmetric balance, objective photography, Helvetica lineage"},
    {"label": "Vaporwave", "features":
     "gradients, Roman busts, glitch, 80s-90s consumer nostalgia"},
    {"label": "Constructivism", "features":
     "diagonals, photomontage, agitprop geometry, red/black"},
    {"label": "Risograph print", "features":
     "limited spot colours, misregistration, paper texture, halftone"},
    {"label": "Cyberpunk", "features": "neon on dark, HUD elements, decay + tech"},
    {"label": "Memphis", "features": "squiggles, clashing pastels, playful geometry"},
    {"label": "Bauhaus", "features":
     "geometric sans, primary colour, form follows function"},
    {"label": "Ukiyo-e", "features":
     "flat planes, bold outline, radical cropping — study with attribution"},
    {"label": "Op art", "features": "perceptual vibration, moiré, high-frequency pattern"},
    {"label": "Lo-fi hip-hop", "features":
     "dusty texture, jazz chords, swung sampled breaks, tape noise"},
    {"label": "Dub", "features":
     "offbeat skank, drop-outs, delay throws, mix-as-instrument"},
    {"label": "Minimalism (Reich/Glass)", "features":
     "phasing, process, repetition — the commercial scoring workhorse"},
    {"label": "Trap", "features": "rolled hats, 808 sub, half-time feel"},
    {"label": "Ambient (Eno)", "features": "beatless, texture-first, no foreground"},
    {"label": "Jungle / DnB", "features": "chopped breaks ~170, sub weight, space"},
    {"label": "Synthwave", "features": "80s palette nostalgia, supersaws, gated drums"},
    {"label": "Gamelan", "features": "metallophone cycles, colotomic structure"},
    {"label": "Funk", "features": "the one, syncopated 16ths, interlocking riffs"},
    {"label": "Shoegaze", "features": "wall of texture, buried vocal, pitch drift"},
    {"label": "Film scoring idiom", "features":
     "leitmotif, underscore, drone tension, hybrid orchestral-electronic"},
]

# Primitives to practise, pulled from the Part 3 spine and Part 10 catalogue.
BRIEF_PRIMITIVES = [
    {"label": "convolution", "lesson": "convolution"},
    {"label": "signed distance fields", "lesson": "sdf"},
    {"label": "fBm noise", "lesson": "noise"},
    {"label": "premultiplied alpha compositing", "lesson": "compositing-algebra"},
    {"label": "easing and overshoot", "lesson": "motion-grammar"},
    {"label": "linear-light colour work", "lesson": "color-spaces"},
    {"label": "particle systems", "lesson": "motion-grammar"},
    {"label": "biquad filtering", "lesson": "biquad"},
    {"label": "delay lines", "lesson": "delay-lines"},
    {"label": "waveshaping", "lesson": "waveshaping"},
    {"label": "granular processing", "lesson": "granular"},
    {"label": "convolution reverb", "lesson": "convolution-audio"},
    {"label": "sidechain ducking", "lesson": "masking"},
    {"label": "frequency slotting", "lesson": "masking"},
    {"label": "Haas widening", "lesson": "precedence"},
    {"label": "spectral processing", "lesson": "fourier"},
    {"label": "displacement mapping", "lesson": "convolution"},
    {"label": "raymarching", "lesson": "sdf"},
    {"label": "flow fields", "lesson": "noise"},
    {"label": "reaction-diffusion", "lesson": "noise"},
]


# ---------------------------------------------------------------- Part 14

ARTICULATION = [
    {"id": "postmortem", "title": "Postmortem", "social": False,
     "prompt": "What reads wrong? Hypothesise the mechanism — force a "
               "mechanism, not a verdict. What will you pull to fix it?"},
    {"id": "teachback", "title": "Teach-back", "social": False,
     "prompt": "Explain one technique as if to a novice, in writing, no "
               "jargon. Gaps in the explanation are gaps in the model."},
    {"id": "feldman", "title": "Feldman critique", "social": False,
     "prompt": "Describe (only what is literally there) → analyze (how the "
               "elements relate) → interpret → judge. Do not skip describe."},
    {"id": "rubric", "title": "Rubric, written first", "social": False,
     "prompt": "Before making the piece: how would you grade it? Compare "
               "against the actual failure modes afterwards."},
    {"id": "design-language", "title": "Personal design language", "social": False,
     "prompt": "Name a move you keep making. Define it well enough that "
               "someone else could deploy it."},
    {"id": "calibration", "title": "Calibration", "social": True,
     "prompt": "Before showing the work: what will they flag? Score yourself "
               "after."},
    {"id": "pair-critique", "title": "Pair critique, vocabulary-constrained", "social": True,
     "prompt": "Critique using only Part 4/6 vocabulary — masking, hierarchy, "
               "spectral slotting, grouping. Mechanism level only."},
    {"id": "brief-writing", "title": "Brief-writing rep", "social": True,
     "prompt": "Write a brief someone else could produce the right thing "
               "from. Then check whether they did."},
    {"id": "client-translation", "title": "Client translation", "social": True,
     "prompt": "Take one technical decision and re-express it as a client "
               "benefit. Two audiences, two compressions, one policy."},
]

UNLEARNING = [
    {"id": "upside-down", "title": "Upside-down drawing", "craft": "visual",
     "blurb": "Draw a reference rotated 180°. The object-recognition prior "
              "cannot help you, so you draw what is there.",
     "how": "The app rotates a generated reference; you copy it in the pad "
            "beside it, then flip both to compare."},
    {"id": "inverted-playback", "title": "Inverted playback", "craft": "audio",
     "blurb": "Reverse or spectrally invert a piece you know. Envelope and "
              "texture become audible once melody stops carrying attention.",
     "how": "Load or synthesise audio, play reversed, describe what you now "
            "hear that you did not before."},
    {"id": "squint-test", "title": "Squint test", "craft": "visual",
     "blurb": "Heavy blur strips the high band and leaves only the read the "
              "first fixation gets.",
     "how": "Blur a comp to the point of abstraction and write down the "
            "hierarchy you still perceive."},
    {"id": "constraint-scramble", "title": "Constraint scramble", "craft": "both",
     "blurb": "A severe random constraint suppresses the moves you default "
              "to. Convergence on your own style is the failure mode it treats.",
     "how": "Draw a constraint, then make something in one hour under it."},
    {"id": "mirror-view", "title": "Mirror view", "craft": "visual",
     "blurb": "Flipping a composition breaks reading-order habituation and "
              "makes balance errors visible again.",
     "how": "Mirror your comp; note every imbalance that suddenly appears."},
    {"id": "describe-only", "title": "Describe with no judging", "craft": "both",
     "blurb": "Pure description with the judgement step forbidden — the "
              "Feldman discipline used as prior-suppression.",
     "how": "Five minutes of literal description. Any evaluative word voids "
            "the rep."},
]
