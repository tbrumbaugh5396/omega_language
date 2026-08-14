"""The reference layer: effects catalogue, genre glossaries, the sensory
systems, the reading list, and the vocabulary set.

Parts 10-12 and Part 8 of the roadmap. This is the material the perceptual
drills name and the briefs draw from — Part 6's point is that a genre is a
feature bundle, so the glossaries are stored as bundles, not prose.

TERMS is the spaced-repetition deck for Part 9 module 5 (vocabulary builder):
naming a discrimination sharpens it, so every term here is meant to be a
perceptual category, not trivia.
"""

# ---------------------------------------------------------------- Part 10

CATALOG = [
    {"slug": "vfx-blur", "part": "10.1", "craft": "visual", "family": "Blur",
     "primitive": "convolution",
     "items": ["Gaussian", "box", "motion blur", "radial / zoom", "directional",
               "tilt-shift", "lens blur / bokeh (aperture-shaped kernels)",
               "surface / bilateral (edge-preserving)"]},
    {"slug": "vfx-sharpen", "part": "10.1", "craft": "visual",
     "family": "Sharpen & edges", "primitive": "convolution",
     "items": ["unsharp mask", "high-pass sharpen", "Sobel / Canny",
               "emboss", "find-edges outlines"]},
    {"slug": "vfx-optics", "part": "10.1", "craft": "visual",
     "family": "Glow & optics", "primitive": "convolution + compositing",
     "items": ["bloom (threshold → blur → additive)", "halation", "lens flare",
               "anamorphic streaks", "chromatic aberration", "vignette",
               "light leaks", "starburst / diffraction"]},
    {"slug": "vfx-grain", "part": "10.1", "craft": "visual",
     "family": "Grain & texture", "primitive": "noise",
     "items": ["film grain", "noise overlay", "dither (Floyd-Steinberg, Bayer)",
               "halftone (dot, line, cross-hatch)", "paper / print texture",
               "risograph misregistration"]},
    {"slug": "vfx-quantize", "part": "10.1", "craft": "visual",
     "family": "Quantization", "primitive": "sampling",
     "items": ["posterize", "threshold", "pixelate / mosaic", "ASCII render",
               "voxelization", "low-bit colour"]},
    {"slug": "vfx-distort", "part": "10.1", "craft": "visual",
     "family": "Distortion", "primitive": "displacement",
     "items": ["wave", "ripple", "twirl", "pinch / bulge",
               "fisheye / barrel / pincushion", "spherize",
               "displacement mapping", "heat shimmer", "refraction / glass"]},
    {"slug": "vfx-glitch", "part": "10.1", "craft": "visual",
     "family": "Glitch", "primitive": "signal corruption",
     "items": ["RGB channel split", "pixel sorting",
               "datamoshing (motion-vector corruption)", "scanlines",
               "VHS (tracking error, chroma bleed, tape noise)",
               "block corruption", "signal interference", "feedback loops"]},
    {"slug": "vfx-stylize", "part": "10.1", "craft": "visual",
     "family": "Stylization", "primitive": "quantization + edges",
     "items": ["cel / toon shading", "outline / ink shaders", "cross-hatching",
               "watercolour / oil simulation", "pointillism", "mosaic / stained glass",
               "kaleidoscope", "mirror / symmetry"]},
    {"slug": "vfx-color", "part": "10.2", "craft": "visual",
     "family": "Colour", "primitive": "transfer functions",
     "items": ["lift / gamma / gain", "curves", "LUT application", "split toning",
               "teal-and-orange", "bleach bypass", "cross-process",
               "day-for-night", "sepia", "cyanotype", "technicolor emulation",
               "duotone / tritone", "gradient mapping", "selective colour",
               "hue rotation", "colour match / transfer", "HDR tone mapping",
               "black / white point", "contrast S-curves", "filmic transfer"]},
    {"slug": "vfx-comp", "part": "10.3", "craft": "visual",
     "family": "Compositing & motion", "primitive": "compositing algebra",
     "items": ["chroma / luma / difference keying", "spill suppression",
               "edge refinement", "masking, roto, garbage mattes",
               "track / alpha / luma mattes",
               "point, planar and 3D-solve tracking", "match-move",
               "screen replacement", "stabilization (and shake simulation)",
               "optical-flow retiming", "speed ramps", "time remapping",
               "freeze frames", "echo / trails", "long-exposure simulation",
               "morphing and warping", "match cut", "whip pan",
               "invisible cuts", "luma-driven transitions", "glitch cuts"]},
    {"slug": "vfx-generative", "part": "10.4", "craft": "visual",
     "family": "Generative & simulation", "primitive": "noise + fields",
     "items": ["particles: fire, smoke, sparks, rain, snow, dust",
               "boids / flocking", "Mandelbrot & Julia", "IFS", "L-systems",
               "flame fractals", "fBm", "flow fields / advection",
               "reaction-diffusion (Turing patterns)", "cellular automata",
               "diffusion-limited aggregation", "physarum / slime mould",
               "cloth, fluid (Navier-Stokes, FLIP)", "rigid / soft body",
               "spring systems", "verlet integration", "Voronoi / Worley",
               "truchet tiles", "wave function collapse", "space colonization",
               "marching squares / cubes", "metaballs"]},
    {"slug": "vfx-3d", "part": "10.5", "craft": "visual",
     "family": "3D & rendering", "primitive": "SDF + shading",
     "items": ["raymarching: soft shadows, AO from distance, domain repetition",
               "smooth boolean blending", "PBR", "subsurface scattering",
               "fresnel / rim light", "matcaps", "iridescence / thin-film",
               "volumetric light / god rays", "caustics", "global illumination",
               "HDRI environment lighting", "depth of field", "motion blur",
               "lens distortion", "SSAO", "screen-space reflections",
               "toon ramps", "hatching shaders", "inverted-hull outlines",
               "depth / normal edge detection", "pixel-art 3D", "dither shading"]},
    {"slug": "afx-eq", "part": "10.6", "craft": "audio",
     "family": "EQ & filters", "primitive": "biquad",
     "items": ["parametric EQ", "shelving", "graphic EQ",
               "low / high / band-pass", "notch", "resonant filters",
               "filter sweeps", "formant filters", "comb filters", "dynamic EQ"]},
    {"slug": "afx-dynamics", "part": "10.6", "craft": "audio",
     "family": "Dynamics", "primitive": "envelope detection",
     "items": ["compression", "limiting", "gating", "expansion",
               "multiband compression", "parallel (NY) compression",
               "sidechain ducking (pumping)", "transient shaping", "de-essing"]},
    {"slug": "afx-saturation", "part": "10.6", "craft": "audio",
     "family": "Saturation & distortion", "primitive": "waveshaping",
     "items": ["overdrive", "fuzz", "tube / tape saturation", "waveshaping",
               "bitcrushing", "sample-rate reduction", "soft / hard clipping"]},
    {"slug": "afx-modulation", "part": "10.6", "craft": "audio",
     "family": "Modulation", "primitive": "delay line + LFO",
     "items": ["chorus", "flanger", "phaser", "tremolo", "vibrato",
               "ring modulation", "auto-pan", "rotary / Leslie"]},
    {"slug": "afx-delay", "part": "10.6", "craft": "audio",
     "family": "Delay", "primitive": "delay line",
     "items": ["slapback", "ping-pong", "tape delay (wow / flutter)",
               "multi-tap", "dub delay", "reverse delay"]},
    {"slug": "afx-reverb", "part": "10.6", "craft": "audio",
     "family": "Reverb", "primitive": "convolution",
     "items": ["room", "hall", "chamber", "plate", "spring",
               "convolution (real IRs)", "shimmer (pitch-shifted feedback)",
               "gated reverb", "reverse reverb", "pre-delay as design parameter"]},
    {"slug": "afx-pitch", "part": "10.6", "craft": "audio",
     "family": "Pitch", "primitive": "phase vocoder",
     "items": ["pitch shifting", "harmonizers", "autotune (corrective and as effect)",
               "formant shifting", "whammy / dive"]},
    {"slug": "afx-time", "part": "10.6", "craft": "audio",
     "family": "Time & texture", "primitive": "granular + spectral",
     "items": ["time-stretching", "reverse", "stutter / glitch edits",
               "tape stop", "granular clouds, freezes, texture beds",
               "spectral freeze / blur / morph", "vocoder", "talk box"]},
    {"slug": "afx-space", "part": "10.6", "craft": "audio",
     "family": "Stereo & space", "primitive": "delay + level",
     "items": ["stereo widening", "panning automation", "Haas effect",
               "mid / side processing", "binaural / HRTF", "ambisonics", "Doppler"]},
    {"slug": "synthesis", "part": "10.7", "craft": "audio",
     "family": "Synthesis techniques", "primitive": "oscillators",
     "items": ["subtractive", "FM", "AM", "additive", "wavetable",
               "physical modelling (Karplus-Strong, modal)", "granular",
               "sample-based", "vector", "west-coast (wavefolding, low-pass gates)"]},
    {"slug": "sound-design-vocab", "part": "10.8", "craft": "audio",
     "family": "Sound-design vocabulary", "primitive": "arrangement",
     "items": ["risers", "downlifters", "impacts / hits", "whooshes", "swells",
               "stingers", "drones", "braams", "sub drops", "tick / UI sounds",
               "foley layers", "room tone", "walla", "ducking under VO",
               "frequency slotting", "LUFS loudness targets"]},
]

# ---------------------------------------------------------------- Part 11

GENRES = [
    # --- 11.1 art movements
    {"slug": "renaissance", "kind": "art", "era": "Pre-modern", "label": "Renaissance",
     "features": "perspective, anatomical accuracy, classical revival"},
    {"slug": "baroque-art", "kind": "art", "era": "Pre-modern", "label": "Baroque",
     "features": "drama, chiaroscuro, diagonal energy"},
    {"slug": "rococo", "kind": "art", "era": "Pre-modern", "label": "Rococo",
     "features": "ornament, pastel, playfulness"},
    {"slug": "neoclassicism", "kind": "art", "era": "Pre-modern", "label": "Neoclassicism",
     "features": "order, line, civic virtue"},
    {"slug": "romanticism", "kind": "art", "era": "Pre-modern", "label": "Romanticism",
     "features": "the sublime, emotion, nature's power"},
    {"slug": "realism", "kind": "art", "era": "Pre-modern", "label": "Realism",
     "features": "unidealized ordinary life"},
    {"slug": "impressionism", "kind": "art", "era": "Modern break", "label": "Impressionism",
     "features": "light, broken colour, momentary perception"},
    {"slug": "post-impressionism", "kind": "art", "era": "Modern break",
     "label": "Post-Impressionism",
     "features": "structure and symbol: Cézanne's geometry, Van Gogh's mark, "
                 "Gauguin's flat colour"},
    {"slug": "pointillism", "kind": "art", "era": "Modern break", "label": "Pointillism",
     "features": "optical mixing"},
    {"slug": "art-nouveau", "kind": "art", "era": "Modern break", "label": "Art Nouveau",
     "features": "organic whiplash line, integrated ornament"},
    {"slug": "fauvism", "kind": "art", "era": "Early avant-garde", "label": "Fauvism",
     "features": "colour liberated from description"},
    {"slug": "expressionism", "kind": "art", "era": "Early avant-garde", "label": "Expressionism",
     "features": "distortion for inner states"},
    {"slug": "cubism", "kind": "art", "era": "Early avant-garde", "label": "Cubism",
     "features": "simultaneous viewpoints, fractured planes"},
    {"slug": "futurism", "kind": "art", "era": "Early avant-garde", "label": "Futurism",
     "features": "speed, machines, motion lines"},
    {"slug": "dada", "kind": "art", "era": "Early avant-garde", "label": "Dada",
     "features": "anti-art, chance, collage, readymades"},
    {"slug": "surrealism", "kind": "art", "era": "Early avant-garde", "label": "Surrealism",
     "features": "dream logic, juxtaposition, automatism"},
    {"slug": "constructivism", "kind": "art", "era": "Design-adjacent", "label": "Constructivism",
     "features": "diagonals, photomontage, agitprop geometry"},
    {"slug": "de-stijl", "kind": "art", "era": "Design-adjacent", "label": "De Stijl",
     "features": "primary colours, orthogonal grid"},
    {"slug": "bauhaus", "kind": "art", "era": "Design-adjacent", "label": "Bauhaus",
     "features": "form follows function, geometric sans, unity of art and craft"},
    {"slug": "art-deco", "kind": "art", "era": "Design-adjacent", "label": "Art Deco",
     "features": "streamlined luxury, symmetry, gold and black"},
    {"slug": "abstract-expressionism", "kind": "art", "era": "Post-war",
     "label": "Abstract Expressionism", "features": "scale, gesture, field"},
    {"slug": "pop-art", "kind": "art", "era": "Post-war", "label": "Pop Art",
     "features": "mass culture, flat commercial colour, repetition"},
    {"slug": "op-art", "kind": "art", "era": "Post-war", "label": "Op Art",
     "features": "perceptual vibration, moiré"},
    {"slug": "minimalism-art", "kind": "art", "era": "Post-war", "label": "Minimalism",
     "features": "reduction, seriality, literal materials"},
    {"slug": "conceptual", "kind": "art", "era": "Post-war", "label": "Conceptual",
     "features": "idea over object"},
    {"slug": "photorealism", "kind": "art", "era": "Post-war", "label": "Photorealism",
     "features": "photographic source rendered by hand"},
    {"slug": "street-art", "kind": "art", "era": "Post-war", "label": "Street Art / Graffiti",
     "features": "letterform, wildstyle, stencil"},
    {"slug": "generative-art", "kind": "art", "era": "Contemporary / digital",
     "label": "Generative Art", "features": "algorithmic, systems-as-medium"},
    {"slug": "glitch-art", "kind": "art", "era": "Contemporary / digital",
     "label": "Glitch Art", "features": "signal corruption as material"},
    {"slug": "post-internet", "kind": "art", "era": "Contemporary / digital",
     "label": "Post-Internet", "features": "network-native imagery and circulation"},

    # --- 11.2 design & illustration
    {"slug": "swiss", "kind": "design", "era": "Commercial backbone",
     "label": "Swiss / International Typographic",
     "features": "grid, Helvetica lineage, objective photography, asymmetric balance"},
    {"slug": "psychedelic", "kind": "design", "era": "Counterculture", "label": "Psychedelic",
     "features": "melting letterforms, vibrating complementaries"},
    {"slug": "punk-grunge", "kind": "design", "era": "Counterculture", "label": "Punk / grunge",
     "features": "xerox texture, ransom type, deliberate damage"},
    {"slug": "memphis", "kind": "design", "era": "Postmodern", "label": "Memphis",
     "features": "squiggles, clashing pastels, playful geometry"},
    {"slug": "vaporwave", "kind": "design", "era": "Digital nostalgia", "label": "Vaporwave",
     "features": "Roman busts, gradients, glitch, 80s-90s consumer nostalgia"},
    {"slug": "y2k", "kind": "design", "era": "Digital nostalgia", "label": "Y2K",
     "features": "chrome, lens flares, tech-optimism blobs"},
    {"slug": "cyberpunk", "kind": "design", "era": "Digital nostalgia", "label": "Cyberpunk",
     "features": "neon on dark, HUD elements, decay plus tech"},
    {"slug": "solarpunk", "kind": "design", "era": "Contemporary", "label": "Solarpunk",
     "features": "organic plus tech, optimist green futurism"},
    {"slug": "ui-pendulum", "kind": "design", "era": "Interface", "label": "The UI style pendulum",
     "features": "flat ↔ skeuomorphism ↔ neumorphism ↔ glassmorphism"},
    {"slug": "web-brutalism", "kind": "design", "era": "Interface", "label": "Web brutalism",
     "features": "raw HTML aesthetics, anti-polish"},
    {"slug": "corporate-flat", "kind": "design", "era": "Interface", "label": "Corporate flat",
     "features": "'Corporate Memphis' figure illustration"},
    {"slug": "pixel-art", "kind": "design", "era": "Technique", "label": "Pixel art",
     "features": "hand-placed pixels, limited palette, dithering"},
    {"slug": "low-poly", "kind": "design", "era": "Technique", "label": "Low-poly / voxel / isometric",
     "features": "visible primitives, flat shading, axonometric projection"},
    {"slug": "riso", "kind": "design", "era": "Technique", "label": "Risograph",
     "features": "limited spot colours, misregistration, paper grain"},
    {"slug": "halftone", "kind": "design", "era": "Technique", "label": "Halftone / print revival",
     "features": "dot screens, registration marks, ink limits"},
    {"slug": "ukiyo-e", "kind": "design", "era": "Non-Western lineage", "label": "Ukiyo-e",
     "features": "flat planes, bold outline, radical cropping — study with attribution"},

    # --- 11.3 music
    {"slug": "baroque", "kind": "music", "era": "Classical lineage", "label": "Baroque",
     "features": "counterpoint, figured bass, terraced dynamics"},
    {"slug": "classical", "kind": "music", "era": "Classical lineage", "label": "Classical",
     "features": "sonata form, balance"},
    {"slug": "romantic", "kind": "music", "era": "Classical lineage", "label": "Romantic",
     "features": "chromaticism, rubato, scale"},
    {"slug": "serialism", "kind": "music", "era": "Classical lineage", "label": "Modern / serial",
     "features": "atonality, serialism"},
    {"slug": "minimalism-music", "kind": "music", "era": "Classical lineage",
     "label": "Minimalism (Reich, Glass)",
     "features": "phasing, process, repetition — hugely relevant to commercial scoring"},
    {"slug": "blues", "kind": "music", "era": "Blues & descendants", "label": "Blues",
     "features": "12-bar, blue notes, call-response"},
    {"slug": "soul", "kind": "music", "era": "Blues & descendants", "label": "Soul",
     "features": "gospel harmony, melisma"},
    {"slug": "funk", "kind": "music", "era": "Blues & descendants", "label": "Funk",
     "features": "the one, syncopated 16ths, interlocking riffs"},
    {"slug": "contemporary-rnb", "kind": "music", "era": "Blues & descendants",
     "label": "Contemporary R&B", "features": "sparse 808s, melisma over space"},
    {"slug": "swing", "kind": "music", "era": "Jazz", "label": "Swing",
     "features": "big band, ride pulse"},
    {"slug": "bebop", "kind": "music", "era": "Jazz", "label": "Bebop",
     "features": "fast changes, virtuosic lines"},
    {"slug": "modal-jazz", "kind": "music", "era": "Jazz", "label": "Modal",
     "features": "static harmony, long forms"},
    {"slug": "fusion", "kind": "music", "era": "Jazz", "label": "Fusion",
     "features": "electric timbres, rock energy"},
    {"slug": "psych-rock", "kind": "music", "era": "Rock", "label": "Psychedelic rock",
     "features": "studio-as-instrument"},
    {"slug": "post-punk", "kind": "music", "era": "Rock", "label": "Post-punk",
     "features": "angular, bass-led"},
    {"slug": "shoegaze", "kind": "music", "era": "Rock", "label": "Shoegaze",
     "features": "wall of texture, buried vocals"},
    {"slug": "post-rock", "kind": "music", "era": "Rock", "label": "Post-rock",
     "features": "crescendo form, instrumental"},
    {"slug": "boom-bap", "kind": "music", "era": "Hip-hop", "label": "Boom bap",
     "features": "swung sampled breaks"},
    {"slug": "trap", "kind": "music", "era": "Hip-hop", "label": "Trap",
     "features": "rolled hi-hats, 808 sub, half-time feel"},
    {"slug": "drill", "kind": "music", "era": "Hip-hop", "label": "Drill",
     "features": "sliding 808s, darker palette"},
    {"slug": "lofi-hiphop", "kind": "music", "era": "Hip-hop", "label": "Lo-fi hip-hop",
     "features": "dusty texture, jazz chords — ubiquitous in web and ad space"},
    {"slug": "house", "kind": "music", "era": "Electronic", "label": "House",
     "features": "4-on-floor ~120-128; deep, tech, progressive variants"},
    {"slug": "techno", "kind": "music", "era": "Electronic", "label": "Techno",
     "features": "machine repetition, timbre-as-melody"},
    {"slug": "trance", "kind": "music", "era": "Electronic", "label": "Trance",
     "features": "supersaw builds, breakdown-drop arcs"},
    {"slug": "dnb", "kind": "music", "era": "Electronic", "label": "Jungle / DnB",
     "features": "chopped breaks ~170"},
    {"slug": "garage", "kind": "music", "era": "Electronic", "label": "UK garage",
     "features": "shuffled 2-step"},
    {"slug": "dubstep", "kind": "music", "era": "Electronic", "label": "Dubstep",
     "features": "140, half-time, bass design"},
    {"slug": "ambient", "kind": "music", "era": "Electronic", "label": "Ambient",
     "features": "beatless, texture-first — core commercial bed music"},
    {"slug": "idm", "kind": "music", "era": "Electronic", "label": "IDM",
     "features": "broken programming, sound design foregrounded"},
    {"slug": "synthwave", "kind": "music", "era": "Electronic", "label": "Synthwave",
     "features": "80s palette nostalgia"},
    {"slug": "dub", "kind": "music", "era": "Roots & regional", "label": "Reggae / dub",
     "features": "offbeat skank; dub is the birthplace of mix-as-instrument"},
    {"slug": "bossa", "kind": "music", "era": "Roots & regional", "label": "Bossa nova",
     "features": "soft syncopation, rich harmony"},
    {"slug": "reggaeton", "kind": "music", "era": "Roots & regional", "label": "Reggaeton",
     "features": "dembow pattern"},
    {"slug": "afrobeat", "kind": "music", "era": "Roots & regional", "label": "Afrobeat",
     "features": "long-form interlock"},
    {"slug": "city-pop", "kind": "music", "era": "Roots & regional", "label": "City pop",
     "features": "lush 80s Japanese production, extended harmony"},
    {"slug": "gamelan", "kind": "music", "era": "Roots & regional", "label": "Gamelan",
     "features": "metallophone cycles, colotomic structure"},
    {"slug": "indian-classical", "kind": "music", "era": "Roots & regional",
     "label": "Indian classical", "features": "raga and tala systems"},
    {"slug": "scoring", "kind": "music", "era": "Functional", "label": "Film / game scoring",
     "features": "leitmotif, underscore, Mickey-Mousing, drone tension, "
                 "hybrid orchestral-electronic, adaptive vertical layering"},
]

# ---------------------------------------------------------------- Part 12

SYSTEMS = [
    {"slug": "visual-pathway", "title": "The visual pathway", "part": "12.1",
     "stages": [
         {"name": "Optics → retina",
          "body": "Rods (~120M) for dim light, achromatic, absent from the "
                  "fovea — which is why faint stars vanish when you look "
                  "straight at them. Cones (~6M) in S/M/L types crowd the "
                  "fovea, the ~2° high-resolution centre. Everything sharp you "
                  "see is foveal; the periphery is low-res and motion-sensitive. "
                  "Vision only feels uniform because of saccades plus memory.",
          "craft": "You are not designing a picture, you are designing a "
                   "sequence of fixations."},
         {"name": "Retinal ganglion cells",
          "body": "Centre-surround receptive fields perform edge detection in "
                  "the eye. The retina outputs contrast, not brightness.",
          "craft": "Perceived lightness is relative, so a grade reads "
                   "differently on a different background. Contrast is the "
                   "currency; absolute values are not."},
         {"name": "Opponent processing",
          "body": "Cone signals are recoded into light/dark, red/green and "
                  "blue/yellow channels.",
          "craft": "No reddish green; afterimages are complementary; OKLab-style "
                   "spaces are built on these axes and therefore behave."},
         {"name": "LGN (thalamus)",
          "body": "Magnocellular (fast, motion and luminance, low detail), "
                  "parvocellular (slow, colour and fine detail), koniocellular.",
          "craft": "Motion and detail travel on different wires: grab attention "
                   "with motion in the periphery, but deliver detail where the "
                   "fovea will land."},
         {"name": "V1",
          "body": "Neurons tuned to oriented edges and spatial frequencies "
                  "(Hubel & Wiesel) — something like a local Gabor basis.",
          "craft": "The biological reason frequency-domain thinking matches "
                   "perception."},
         {"name": "Ventral 'what' stream",
          "body": "V1 → V2 → V4 → inferotemporal. V4 for colour and curvature; "
                  "IT for objects; FFA for faces, PPA for places, VWFA for word "
                  "forms.",
          "craft": "A face dominates any composition it appears in, and a "
                   "literate viewer cannot not read text in frame."},
         {"name": "Dorsal 'where/how' stream",
          "body": "V1 → V5/MT → parietal: motion, spatial relations, action "
                  "guidance.",
          "craft": "Why motion pops in the periphery, and why smooth easing "
                   "reads as intentional where linear reads as mechanical."},
         {"name": "Attention, adaptation, constancy",
          "body": "3-4 saccades a second with vision suppressed mid-flight. "
                  "Salience (contrast, motion, faces) × top-down goals. The "
                  "system normalizes ruthlessly: colour constancy, light/dark "
                  "adaptation, motion aftereffects.",
          "craft": "Sustained effects fatigue into invisibility. Grades are "
                   "judged relative to surround."},
     ]},
    {"slug": "auditory-pathway", "title": "The auditory pathway", "part": "12.2",
     "stages": [
         {"name": "Outer / middle ear",
          "body": "The pinna filters directionally, giving elevation cues; the "
                  "ossicles impedance-match air to cochlear fluid.",
          "craft": "Height cues are spectral, which is why they survive mono."},
         {"name": "Cochlea",
          "body": "The basilar membrane is a mechanical Fourier analyser — high "
                  "frequencies at the base, low at the apex (tonotopy). Outer "
                  "hair cells actively sharpen tuning. Critical bands (~1/3 "
                  "octave) arise here.",
          "craft": "Two sounds in one band fight. Slotting is not a trick, it "
                   "is making room — and it is why MP3 works at all."},
         {"name": "Brainstem / superior olive",
          "body": "Interaural time differences (low frequencies, microsecond "
                  "precision) and interaural level differences (high "
                  "frequencies) compute location. Auditory temporal resolution "
                  "is far finer than visual (~ms vs ~30ms).",
          "craft": "The basis of panning, Haas widening and binaural rendering "
                   "— and the reason sound carries impact sync, not picture."},
         {"name": "IC → MGN → A1",
          "body": "Tonotopic maps persist into cortex; belt and parabelt areas "
                  "extract complex features. Ventral (what) and dorsal "
                  "(where/how) streams again.",
          "craft": "Identity and placement are separable problems — treat them "
                   "separately in a mix."},
         {"name": "Auditory scene analysis",
          "body": "Bregman: the ear receives one summed waveform and must un-mix "
                  "it, grouping by harmonicity, common onset, common modulation "
                  "and continuity. Literally the auditory Gestalt laws.",
          "craft": "A mix is an instruction set for stream segregation. Shared "
                   "onsets fuse layers into one sound; detuning and offsetting "
                   "separate them."},
     ]},
    {"slug": "connected-systems", "title": "Where art actually lands", "part": "12.3",
     "stages": [
         {"name": "Multisensory integration",
          "body": "Superior colliculus and cortical binding integrate sight and "
                  "sound by temporal and spatial coincidence; the McGurk effect "
                  "shows vision rewriting what you hear.",
          "craft": "A/V sync tolerance is asymmetric — audio-late is far more "
                   "forgivable than audio-early. A cut lands as one event only "
                   "if sound and image arrive inside the binding window."},
         {"name": "Reward & emotion",
          "body": "Music-induced chills track dopamine release in nucleus "
                  "accumbens (Salimpoor); anticipation and resolution drive the "
                  "response (Meyer; Huron's ITPRA). The amygdala handles "
                  "salience and threat.",
          "craft": "Build-and-drop, delayed cadence and subverted pattern are "
                   "all engineering of prediction error. Dissonance, sub-bass "
                   "and sudden onsets read as danger."},
         {"name": "Motor coupling & groove",
          "body": "Beat perception recruits basal ganglia and premotor cortex "
                  "even when still. Groove peaks at moderate syncopation — "
                  "predictable enough to entrain, surprising enough to engage.",
          "craft": "Animation that entrains reads as musical. This transfers "
                   "directly to motion design."},
         {"name": "Memory & association",
          "body": "Hippocampus binds episodes; music is a potent retrieval cue.",
          "craft": "Nostalgia genres — synthwave, city pop revival, lo-fi — work "
                   "through this circuit, which is why they are so effective and "
                   "so easy to overuse."},
         {"name": "Default mode network",
          "body": "Vessel: strongly moving artworks engage the DMN "
                  "(self-referential processing).",
          "craft": "Aesthetic impact peaks when the work is processed as "
                   "self-relevant, not merely as pleasant."},
         {"name": "Prediction as the master key",
          "body": "Perception is model plus error; style is a learned prior; "
                  "surprise is attention.",
          "craft": "Effects, edits and drops are all manipulations of the "
                   "audience's generative model."},
     ]},
]

# ---------------------------------------------------------------- Part 8

READING = [
    {"section": "Phenomenology & mastery", "items": [
        ("Varela, Thompson & Rosch", "The Embodied Mind",
         "founding text of neurophenomenology"),
        ("Evan Thompson", "Mind in Life", ""),
        ("Merleau-Ponty", "Phenomenology of Perception",
         "body schema, motor intentionality"),
        ("Hubert Dreyfus", "Skill acquisition papers; the Dreyfus-McDowell exchange",
         "whether expert action is conceptual"),
        ("Andy Clark", "Surfing Uncertainty", "predictive processing"),
        ("Edward Slingerland", "Trying Not to Try; Effortless Action",
         "wu wei × cognitive science; the academic treatment takes the "
         "Laozi/Zhuangzi difference seriously"),
        ("Jean François Billeter", "Lessons on Zhuangzi", ""),
        ("—", "Zhuangzi (Cook Ding, zuowang); Daodejing", ""),
        ("Sian Beilock", "Choking literature", "explicit monitoring"),
        ("K. Anders Ericsson", "Deliberate practice", ""),
    ]},
    {"section": "Design & composition", "items": [
        ("Josef Müller-Brockmann", "Grid Systems in Graphic Design", ""),
        ("Ellen Lupton", "Thinking with Type", ""),
        ("Bruno Munari", "Design as Art; Fantasia", "association-as-method"),
    ]},
    {"section": "Music & signal", "items": [
        ("Meinard Müller", "Fundamentals of Music Processing", "the MIR text"),
        ("Lerdahl & Jackendoff", "A Generative Theory of Tonal Music", ""),
        ("Iannis Xenakis", "Formalized Music", ""),
    ]},
    {"section": "Effects math (practice-first)", "items": [
        ("Inigo Quilez", "Shadertoy articles on SDFs and noise", "canonical"),
        ("Patricio Gonzalez Vivo", "The Book of Shaders", "GLSL fundamentals"),
    ]},
]

TOOLS = [
    {"domain": "Raster / vector", "tools": "Affinity suite or Adobe (Photoshop / "
     "Illustrator); Figma for interface work"},
    {"domain": "Motion graphics", "tools": "After Effects; Blender (3D, free, "
     "industry-real)"},
    {"domain": "Edit / grade", "tools": "DaVinci Resolve — editing is assembly, "
     "timing and rhythm; grading is shaping palette and contrast"},
    {"domain": "Audio", "tools": "Reaper or Ableton Live; a sound-design library "
     "habit; iZotope RX for repair"},
    {"domain": "Creative code", "tools": "p5.js / Processing → GLSL shaders "
     "(Shadertoy) → TouchDesigner"},
    {"domain": "Web-deliverable", "tools": "Three.js / react-three-fiber, GSAP, "
     "Rive / Lottie, Spline"},
    {"domain": "AI — creative code", "tools": "Claude, Cursor, Copilot. Strongest "
     "at GLSL, p5.js, Three.js, r3f, TouchDesigner Python — the highest-leverage "
     "AI use in this curriculum"},
    {"domain": "AI — image", "tools": "Midjourney (aesthetic ceiling); Flux + SD "
     "ecosystem (controllability); ComfyUI (ControlNet, IP-Adapter, LoRA) — where "
     "real production work happens"},
    {"domain": "AI — video", "tools": "Runway, Kling, Veo, Sora, Luma; Wan, "
     "HunyuanVideo, LTX-Video. Weak on precise art direction — use for element "
     "generation, not shot generation"},
    {"domain": "AI — audio", "tools": "Suno / Udio (sketches), ElevenLabs (voice, "
     "SFX), Stable Audio (texture), Demucs (stem separation)"},
    {"domain": "AI — post", "tools": "Resolve Neural Engine (magic mask, depth "
     "maps, voice isolation), Topaz. Least glamorous, most consistently useful"},
    {"domain": "Commercial constraints", "tools": "Provenance and indemnification "
     "(Firefly / Getty / Shutterstock class); performance and accessibility "
     "budgets on web"},
]

# ---------------------------------------------------------------- vocabulary
# Part 9 module 5. Each term is a perceptual category, not trivia — the deck
# exists so that naming and discrimination are trained together.

TERMS = [
    # visual
    ("Premultiplied alpha", "visual", "Colour already multiplied by its alpha, so "
     "filtering and compositing commute. Straight alpha halos on resize because "
     "transparent pixels' colour leaks into the interpolation."),
    ("Porter-Duff over", "visual", "The default composite: result = src + dst·(1−α_src). "
     "The base of every layer stack."),
    ("Linear light", "visual", "Working space where pixel values are proportional to "
     "photons. Blurs, blends and resizes are physically wrong outside it."),
    ("Transfer function", "visual", "The encode/decode curve between light and stored "
     "value — gamma, log, PQ. Not a look, a container."),
    ("OKLab", "visual", "Perceptual colour space built on opponent axes; lightness and "
     "hue behave the way the eye expects."),
    ("Separable kernel", "visual", "A 2D convolution that factors into two 1D passes — "
     "the reason large Gaussian blurs are affordable."),
    ("Unsharp mask", "visual", "image + k·(image − blur(image)). Sharpening is a "
     "high-pass boost, not added detail."),
    ("fBm", "visual", "Fractal Brownian motion: octaves of noise at halving amplitude "
     "and doubling frequency. Most organic texture is this."),
    ("Worley noise", "visual", "Distance to scattered feature points. Cellular, "
     "crystalline, or organic depending on the distance metric."),
    ("Signed distance field", "visual", "A function returning distance to a surface; "
     "shape, outline, glow and shadow all come from the one expression."),
    ("Smooth minimum", "visual", "Blended boolean union in an SDF — makes a join read "
     "as cast rather than cut."),
    ("Domain repetition", "visual", "Modulo the coordinate before evaluating an SDF: "
     "infinite instances at no cost."),
    ("Halation", "visual", "Light bleeding around highlights in film stock; the warm "
     "glow that reads as photographic rather than digital."),
    ("Bloom", "visual", "Threshold, blur, add back. An optical artefact used as a "
     "legibility instrument."),
    ("Chromatic aberration", "visual", "Wavelength-dependent focus; channel-scaled "
     "fringing. Cheap to fake, easy to overdo."),
    ("Bokeh", "visual", "Out-of-focus rendering shaped by the aperture; the kernel is "
     "visible in the highlights."),
    ("Banding", "visual", "Visible steps in a gradient from insufficient bit depth. "
     "Dither is the fix, not more blur."),
    ("Dither", "visual", "Deliberate noise that trades quantisation error for less "
     "visible error. Floyd-Steinberg diffuses it, Bayer orders it."),
    ("Modular scale", "visual", "A ratio-generated size series so type and spacing "
     "share one system."),
    ("Optical alignment", "visual", "Alignment judged by perceived mass rather than "
     "bounding box — round shapes must overshoot to look level."),
    ("Kerning vs tracking", "visual", "Kerning is a pair adjustment; tracking is a "
     "range. Even spacing is a judgement of area, not distance."),
    ("Common fate", "visual", "The Gestalt law that things moving together are one "
     "thing. The strongest grouping cue and the most under-used."),
    ("Closure", "visual", "The eye completes an interrupted contour — why a logo can "
     "lose most of its outline and survive."),
    ("Saliency", "visual", "Bottom-up attention prediction from contrast, motion and "
     "faces. Says where eyes land, not whether the image is worth looking at."),
    ("Change blindness", "visual", "Large changes go unnoticed without a transient to "
     "flag them. The reason a cut can hide almost anything."),
    ("Spatial frequency channel", "visual", "The visual system decomposes into "
     "frequency bands; detail hierarchy is a physiological fact, not a style."),
    ("Contrast sensitivity function", "visual", "Sensitivity peaks at mid spatial "
     "frequencies. Very fine and very coarse detail both need more contrast."),
    ("Simultaneous contrast", "visual", "A patch's lightness depends on its surround, "
     "because the retina encodes contrast."),
    ("Overshoot and settle", "visual", "Passing the target and returning — how motion "
     "communicates mass."),
    ("Ease-out", "visual", "Fast start, slow arrival. Reads as intentional; linear "
     "reads as mechanical because nothing physical starts at full speed."),
    ("Moiré", "visual", "Aliasing between two fine patterns. The visual form of the "
     "same folding that makes distortion metallic."),
    ("Match cut", "visual", "A cut on shared shape, motion or sound so the join "
     "disappears into continuity."),
    ("Teal and orange", "visual", "Skin pushed warm, everything else pushed cool — "
     "maximum separation on the opponent axes."),
    ("Bleach bypass", "visual", "Retained silver look: raised contrast, crushed "
     "saturation, metallic highlights."),

    # audio
    ("Biquad", "audio", "Two-pole two-zero filter; one difference equation gives every "
     "EQ shape via its coefficients."),
    ("Q", "audio", "Filter bandwidth. High enough Q and a peak starts to ring rather "
     "than shape."),
    ("Critical band", "audio", "~1/3-octave cochlear resolution. Two sounds inside one "
     "fight; this is where masking comes from."),
    ("Frequency slotting", "audio", "Giving each element its own band so they stop "
     "competing. Making room, not an EQ trick."),
    ("Masking", "audio", "A louder sound hides a quieter one nearby in frequency or "
     "time. Both spectral and temporal."),
    ("Equal-loudness contour", "audio", "Perceived loudness varies with frequency and "
     "level; bass and top fall away as you turn down."),
    ("LUFS", "audio", "Loudness units relative to full scale — the perceptual loudness "
     "standard delivery is measured against."),
    ("Comb filtering", "audio", "A short delay summed with the dry signal; regularly "
     "spaced notches. Heard as timbre, not repetition, under ~30 ms."),
    ("Haas effect", "audio", "Precedence: within ~35 ms the first arrival localises and "
     "the second becomes width. Mono-fragile."),
    ("Precedence effect", "audio", "The first wavefront wins localisation; later ones "
     "are fused into it."),
    ("ITD / ILD", "audio", "Interaural time difference (low frequencies) and level "
     "difference (high) — the two localisation cues."),
    ("Mid/side", "audio", "Sum and difference encoding of a stereo pair; lets you treat "
     "centre and sides separately."),
    ("Pre-delay", "audio", "Gap before reverb onset. Separates source from space and is "
     "the single most useful reverb parameter."),
    ("Impulse response", "audio", "A space's fingerprint; convolving with it replays "
     "your signal through that space."),
    ("Transient", "audio", "The attack portion. Carries more identity than the steady "
     "state — the main cue left after level-matched compression."),
    ("Attack / release", "audio", "How fast a dynamics processor engages and lets go. "
     "Attack shapes punch; release shapes groove."),
    ("Sidechain ducking", "audio", "One source pushing another down — the pumping that "
     "creates rhythmic space."),
    ("Parallel compression", "audio", "Blending heavily compressed with dry to raise "
     "the floor without flattening the peaks."),
    ("Soft clipping", "audio", "Gradual saturation of the transfer curve; adds "
     "harmonics without the hard edge of clipping."),
    ("Odd vs even harmonics", "audio", "Odd-symmetric curves give hollow, aggressive "
     "tone; asymmetry adds even harmonics and reads as warm."),
    ("Bitcrush", "audio", "Amplitude quantisation. The error is correlated with the "
     "signal, which is why it sounds gritty rather than noisy."),
    ("Sample-rate reduction", "audio", "Downsampling without band-limiting; aliased "
     "content folds down as inharmonic metallic tone."),
    ("Aliasing", "audio", "Content above Nyquist folding back down. It does not "
     "disappear, it relocates."),
    ("Granular synthesis", "audio", "Windowed grains of 5-100 ms scattered in time; "
     "decouples pitch from duration."),
    ("Spectral centroid", "audio", "The spectrum's centre of mass — the measurable "
     "handle for 'brightness'."),
    ("Spectral flux", "audio", "Rate of spectral change; the basis of onset detection."),
    ("Onset density", "audio", "Events per second. A better handle on 'busy' than "
     "tempo."),
    ("Auditory scene analysis", "audio", "Bregman's account of un-mixing one waveform "
     "into streams by harmonicity, common onset, modulation and continuity."),
    ("Common onset", "audio", "Simultaneous starts fuse layers into a single perceived "
     "sound. The whole craft of layering."),
    ("Groove", "audio", "The pleasurable urge to move; maximised at moderate "
     "syncopation — predictable enough to entrain, surprising enough to engage."),

    # cross-craft and meta
    ("Amortized search", "meta", "Expensive deliberation distilled by volume into a "
     "fast learned policy over trained perceptual features."),
    ("Forward model", "meta", "A prediction of your own action's sensory consequences; "
     "correcting against it short-circuits feedback rather than speeding it up."),
    ("Chunking", "meta", "Recoding many elements into one unit, expanding effective "
     "working memory within the trained domain."),
    ("Proceduralization", "meta", "Control migrating from prefrontal areas toward basal "
     "ganglia and cerebellum as a skill consolidates."),
    ("Explicit monitoring", "meta", "Attending to the components of a proceduralized "
     "skill, which degrades it. The mechanism of choking."),
    ("Verbal overshadowing", "meta", "Description impairing novice discrimination but "
     "not experts', whose vocabulary matches perceptual categories."),
    ("Expert blind spot", "meta", "Losing access to what the novice does not yet see, "
     "so your explanation skips the load-bearing step."),
    ("Perceptual learning module", "meta", "Kellman's protocol: high volume, short "
     "trials, immediate feedback, discrimination-focused."),
    ("Attentional weighting", "meta", "Amplifying signal-carrying dimensions and "
     "suppressing the rest — most of expertise is the suppression."),
    ("Family resemblance", "meta", "Category membership by overlapping features rather "
     "than definition. How genre actually works."),
    ("Feature bundle", "meta", "A genre decomposed into palette/timbre, rhythm, "
     "harmony, form and production conventions — the working unit for briefs."),
    ("Generator + filter", "meta", "Formal systems generate a valid candidate space and "
     "filter malformedness; selection stays perceptual."),
    ("Prediction error", "meta", "The gap between model and input. Build-and-drop, "
     "delayed cadence and subverted pattern are all engineering of it."),
    ("McGurk effect", "meta", "Vision rewriting heard speech — evidence that A/V "
     "binding happens below the level of choice."),
    ("Binding window", "meta", "The tolerance inside which sound and image are one "
     "event. Asymmetric: audio-late is far more forgivable than audio-early."),
    ("Deliberate unlearning", "meta", "Suppressing your own trained priors to see "
     "freshly. Available only to the expert; the antidote to the blind spot."),
    ("Wu wei", "meta", "Effortless action — naturalized here as skilled action, one "
     "thread of Daoism rather than the whole of it."),
    ("Transfer test", "meta", "The only real check on an explanation: can someone act "
     "on it and get the result?"),
]

TERM_INDEX = {t[0]: {"term": t[0], "domain": t[1], "definition": t[2]} for t in TERMS}

GLOSSARY = [
    ("Motion", "Animated typography and graphical elements over time."),
    ("Edit", "Video assembly: timing and rhythm."),
    ("Grade", "Shaping the palette and contrast of footage."),
    ("HCC", "Human-centered computing."),
    ("SDF", "Signed distance field."),
    ("LUT", "Lookup table — a sampled colour transform."),
    ("MIR", "Music information retrieval."),
    ("MFCC", "Mel-frequency cepstral coefficients."),
    ("LoRA", "Low-rank adaptation — a lightweight fine-tune for a consistent style."),
    ("Wu wei", "Effortless action."),
    ("Pu", "The uncarved block."),
    ("Shen", "Spirit."),
    ("Zuowang", "Sitting-and-forgetting."),
    ("Ziran", "Self-so-ness."),
]
