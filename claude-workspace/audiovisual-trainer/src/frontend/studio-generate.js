// Generate — a sketchpad for making images fast.
//
// You write one colour expression. The wrapper supplies the coordinates, the
// clock and a small helper library; every uniform you declare turns into the
// control its type implies. Eject prints the real GLSL, so this is a ramp onto
// the Shader editor rather than a separate world.

import { el, clear, api, toast, modal, closeModal } from "./ui.js";
import { aiButton } from "./ai.js";
import { parseUniforms, desugar, desugarMapped, mapErrors, hasSimPass, isEs3, withDefine,
         bakeDefaults, embedImages, stripComments, sketchMeta, SKETCH_VARS } from "./shader-uniforms.js";
import { getGL, isGL2, linkProgram, dualTargets } from "./shader-run.js";
import { Feedback } from "./feedback.js";
import { buildControls, applyUniforms, randomise, bindTextures, releaseTextures,
         mediaDims, seekVideos, resumeVideos } from "./shader-controls.js";
import { muxMp4 } from "./video-mux.js";
import { zipStore, pngBytes } from "./zip-store.js";
import { compileSvg } from "./svg-to-sdf.js";
import { loadFontFile, registeredFonts } from "./font-file.js";
import { fitPreview } from "./sdf-core.js";
import { nodeReference, referenceGaps } from "./node-docs.js";
import { Keyboard } from "./keyboard.js";
import { hasSketchEffects, sketchFrame } from "./sketch-effects.js";
import { expandButton } from "./expand.js";
import { LiveRig } from "./live-audio.js";
import { parsePatch } from "./instrument-doc.js";
import { registerNode, withNodeHeader, nodeShape, declaresNode, keepVersion,
         versionSummary, usersOfNode, nodeIdFor } from "./node-library.js";
import { gridOverlay } from "./grid-overlay.js";

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

/**
 * The steps the render scale may take. Not a continuum: a picture whose
 * resolution drifts every second reads as a fault, and the difference between
 * 0.78 and 0.75 is not worth seeing it move.
 */
export const SCALE_STEPS = [1, 0.85, 0.75, 0.6, 0.5];

/**
 * The scale a sketch needs to hold a frame budget, given what it measured at
 * the scale it is running now.
 *
 * A fragment shader's cost is very nearly proportional to the pixel count —
 * measured on the rover at 640×360 and 480×270 it was 28.9 ms and 16.5 ms for
 * 0.5625 of the pixels, which is 0.571 of the time — so the scale that fits a
 * budget is `atScale × √(budget / measured)`, snapped down to a step. Never
 * above 1: a sketch is authored at its preview size, and a scale that
 * invented pixels would be inventing detail.
 */
/**
 * The largest w×h with this aspect that fits inside a box — which is what
 * fullscreen needs, because a sketch has an aspect and a screen has a
 * different one, and stretching it would be a different picture.
 */
export function fitAspect(aspect, maxW, maxH) {
  if (!(aspect > 0)) return [Math.round(maxW), Math.round(maxH)];
  const byWidth = [maxW, maxW / aspect];
  return byWidth[1] <= maxH ? [Math.round(byWidth[0]), Math.round(byWidth[1])]
                            : [Math.round(maxH * aspect), Math.round(maxH)];
}

export function scaleForBudget(ms, atScale = 1, budgetMs = 16.7) {
  if (!(ms > 0) || !(atScale > 0)) return 1;
  const want = Math.min(1, atScale * Math.sqrt(budgetMs / ms));
  for (const s of SCALE_STEPS) if (s <= want + 1e-9) return s;
  return SCALE_STEPS[SCALE_STEPS.length - 1];
}

/**
 * A bed: filtered noise whose level something else moves.
 *
 * Wind, rain and surf are the same instrument three times with a different
 * corner and a different tap of the same filter — which is what those three
 * sounds are, and writing it once says so. `level` is the part an effect
 * addresses; a `param` effect on it is how a document says "louder now".
 */
function airInstrument(freq, q, tap) {
  // The voice.note is here because an instrument must have somewhere to write
  // a note, and the parser is right to insist: an instrument without one plays
  // nothing when a document sends it a note. This one is never sent any — a
  // bed is always sounding and what changes is how much — so it is mixed in at
  // nothing, which keeps the patch honest rather than special.
  const { decl, errors } = parsePatch(`// @instrument world.air
// @voices 1
note  = voice.note
n     = noise.white amp=1
tone  = filter.svf  x=n.y  freq=${freq}  q=${q}
bed   = gain.smooth x=tone.${tap}  level=0  ms=220
level = mix.add     a=bed.y  b=note.gate  gainA=1  gainB=0
`);
  if (errors.length) throw new Error(`the air instrument does not parse: ${errors[0]}`);
  return decl;
}

export const GENERATE_PRESETS = [
  { id: "field", label: "Warm noise field", source:
`uniform float scale;   // @range 1 12 step 0.1 @default 3 — how tight the noise is
uniform vec3  deep;    // @color
uniform vec3  glow;    // @color
uniform float drift;   // @range 0 1 @default 0.15 — how fast it moves

mix(deep, glow, fbm(st * scale + t * drift))` },

  { id: "rings", label: "Cosine palette rings", source:
`uniform float rings;   // @range 1 40 @default 5 — ring count
uniform vec2  centre;  // @pad
uniform float warp;    // @range 0 2 @default 0.5
uniform float hue;     // @range 0 1 @default 0.08 — where the ramp starts
uniform float spread;  // @range 0.02 0.6 @default 0.16 — how far it travels

float d = length(p - (centre * 2.0 - 1.0)) * rings + fbm(p * 2.0) * warp - t * 0.1;

palette(d, vec3(0.5), vec3(0.45), vec3(1.0), vec3(hue, hue + spread, hue + spread * 2.0))` },

  { id: "cells", label: "Drifting cells", source:
`uniform float count;   // @range 2 30 step 1 @default 7 — cells across
uniform vec3  ink;     // @color
uniform vec3  ground;  // @color
uniform float falloff; // @range 0.15 1.2 @default 0.5 — how fast a cell fades from its centre

float cells(vec2 q, float n) {
  q *= n;
  vec2 i = floor(q), f = fract(q);
  float d = 1.0;
  for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
      vec2 g = vec2(float(x), float(y));
      vec2 o = vec2(hash21(i + g), hash21(i + g + 17.1));
      o = 0.5 + 0.5 * sin(t * 0.6 + 6.2831 * o);
      d = min(d, length(g + o - f));
    }
  }
  return d;
}

mix(ground, ink, cells(st, count) / falloff)` },

  { id: "badge", label: "Hard-edged badge", source:
`uniform float radius;  // @range 0.1 0.9 @default 0.5
uniform float bar;     // @range 0.0 0.6 @default 0.12
uniform vec3  ground;  // @color
uniform vec3  mark;    // @color

mix(ground, mark, aa(min(sdCircle(p, radius), sdBox(p, vec2(0.8, bar)))))` },

  { id: "moire", label: "Moiré interference", source:
`uniform float freq;    // @range 4 120 @default 26 — line frequency
uniform float turn;    // @range 0 1.57 @default 0.12 — angle between the two grids
uniform vec3  tint;    // @color

float a = sin(p.x * freq);
float b = sin((rot(turn) * p).x * freq);

tint * (0.5 + 0.5 * a * b)` },

  { id: "octaves", label: "Octaves, one at a time", source:
`uniform int   octaves; // @range 1 8 @default 5 — how many layers of detail
uniform float scale;   // @range 1 8 @default 3
uniform vec3  paper;   // @color

float layered(vec2 q) {
  float v = 0.0, amp = 0.5;
  for (int i = 0; i < 8; i++) {
    if (i >= octaves) break;   // the bound must be constant; the break need not be
    v += amp * noise(q);
    q *= 2.03;
    amp *= 0.5;
  }
  return v;
}

paper * layered(st * scale + seed)` },

  // ---- scenes. These work in linear light and end with finish(), which
  // tone-maps, encodes to sRGB and dithers. Colour uniforms are taken as sRGB
  // (what a swatch shows you) and converted on the way in — Module 3.

  { id: "sky", label: "Sky, sun and clouds", preview: [800, 450], source:
`uniform float sunHeight; // @range 0.02 0.9 @default 0.22 — how high the sun sits
uniform float cover;     // @range 0 1 @default 0.5 — cloud cover
uniform float scale;     // @range 1 6 @default 2.5 — cloud size (higher is smaller)
uniform float wind;      // @range 0 1 @default 0.25
uniform float haze;      // @range 0 1 @default 0.5

vec3 sd = normalize(vec3(0.35, sunHeight, -1.0));
vec3 rd = normalize(vec3(p.x, p.y * 0.55 + 0.42, -1.0));
vec3 col = sky(rd, sd);

// A cloud deck at height 1, seen along the ray. Domain-warped fbm for the
// shape; a second sample towards the sun for the shading.
float h = clamp(rd.y, 0.02, 1.0);
float dist = 1.0 / h;
vec2 cp = rd.xz * dist * scale * 0.35 + vec2(t * wind * 0.4, 0.0) + seed;
vec2 warp = vec2(fbm(cp * 0.6), fbm(cp * 0.6 + 3.7)) - 0.5;
float dens = fbm(cp + warp * 1.6);
float thr = 0.66 - cover * 0.30;
float cloud = smoothstep(thr, thr + 0.14, dens);
float toward = fbm(cp + warp * 1.6 + sd.xz * 0.25);
float lit = clamp(1.0 - (toward - dens) * 8.0, 0.0, 1.0);
vec3 cloudCol = mix(vec3(0.18, 0.21, 0.30), vec3(1.05, 1.02, 0.98), lit);
cloudCol += vec3(1.0, 0.85, 0.6) * pow(max(dot(rd, sd), 0.0), 16.0) * 0.6;   // silver lining
float fade = exp(-dist * 0.06);                                              // far decks sink into haze
col = mix(col, cloudCol, cloud * fade * 0.96);
col = mix(col, vec3(0.75, 0.80, 0.90), haze * pow(1.0 - clamp(rd.y, 0.0, 1.0), 10.0) * 0.6);

finish(col)` },

  { id: "cloudscape", label: "Cloudscape, volumetric", preview: [800, 450], source:
`uniform float sunHeight; // @range 0.05 0.9 @default 0.35
uniform float density;   // @range 0.2 4 @default 2.0
uniform float cover;     // @range 0 1 @default 0.5
uniform float scale;     // @range 0.3 3 @default 1.0
uniform float wind;      // @range 0 1 @default 0.2

// Density in a slab between y=0 and y=1. Marched in 24 steps; each step
// takes two more samples towards the sun for self-shadowing.
float cloudDensity(vec3 q) {
  q.xz += t * wind * 0.5;
  float n = fbm(q.xz * 0.5 * scale + q.y * 0.35 + seed);
  n += noise(q.xz * 1.7 * scale + q.y * 0.9) * 0.25;
  n += noise(q.xz * 4.5 * scale + q.y * 2.5) * 0.10;                     // the crisp edge
  float slab = smoothstep(0.0, 0.30, q.y) * smoothstep(1.0, 0.60, q.y);
  return clamp((n - (0.70 - cover * 0.32)) * 8.0, 0.0, 1.0) * slab * density;
}

vec3 sd = normalize(vec3(0.3, sunHeight, -1.0));
vec3 ro = vec3(0.0, -0.5, 0.0);
vec3 rd = normalize(vec3(p.x, p.y * 0.55 + 0.35, -1.0));
vec3 col = sky(rd, sd);
if (rd.y > 0.02) {
  float t0 = (0.0 - ro.y) / rd.y, t1 = (1.0 - ro.y) / rd.y;
  float stepLen = (t1 - t0) / 24.0;
  float jitter = hash21(gl_FragCoord.xy);        // breaks the step banding
  float trans = 1.0;
  vec3 acc = vec3(0.0);
  vec3 lightCol = vec3(1.15, 1.05, 0.92), ambCol = vec3(0.22, 0.27, 0.42);
  float forward = pow(max(dot(rd, sd), 0.0), 6.0);
  for (int i = 0; i < 24; i++) {
    float tt = t0 + stepLen * (float(i) + jitter);
    vec3 q = ro + rd * tt;
    float d = cloudDensity(q);
    if (d > 0.001) {
      float shade = cloudDensity(q + sd * 0.4) * 0.6 + cloudDensity(q + sd * 1.0) * 0.4;
      vec3 c = mix(ambCol, lightCol, exp(-shade * 3.5)) * (1.0 + 0.8 * forward * exp(-shade * 4.0));
      float a = 1.0 - exp(-d * stepLen * 1.5);
      acc += trans * a * c;
      trans *= 1.0 - a;
    }
    if (trans < 0.02) break;
  }
  col = mix(col, col * trans + acc, exp(-t0 * 0.02));
}

finish(col)` },

  { id: "ocean", label: "Ocean, raymarched", preview: [800, 450], source:
`uniform float swell;     // @range 0.1 1.2 @default 0.55 — wave height
uniform float choppy;    // @range 1 5 @default 3.0
uniform float sunHeight; // @range 0.03 0.7 @default 0.18
uniform vec3  deep;      // @color @default 0.02 0.09 0.16
uniform vec3  shallow;   // @color @default 0.10 0.45 0.45
uniform float speed;     // @range 0 2 @default 0.7

// A heightfield ocean, found by bisection along the ray — the approach TDM's
// Seascape made familiar. Four octaves of a sharpened sine, two moving
// against each other.
float waveOctave(vec2 q, float ch) {
  q += noise(q) - 0.5;
  vec2 w = 1.0 - abs(sin(q));
  vec2 s = abs(cos(q));
  w = mix(w, s, w);
  return pow(1.0 - pow(w.x * w.y, 0.65), ch);
}
float seaLevel(vec3 pos) {          // signed: positive above the surface
  float freq = 0.16, amp = swell, ch = choppy, tm = t * speed;
  vec2 q = pos.xz * vec2(0.75, 1.0);
  float h = 0.0;
  mat2 turn = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 4; i++) {
    h += (waveOctave((q + tm) * freq, ch) + waveOctave((q - tm) * freq, ch)) * amp;
    q = turn * q; freq *= 1.9; amp *= 0.22; ch = mix(ch, 1.0, 0.2);
  }
  return pos.y - h;
}
vec3 seaNormal(vec3 pos, float e) {
  float h0 = seaLevel(pos);
  return normalize(vec3(seaLevel(pos + vec3(e, 0.0, 0.0)) - h0, e,
                        seaLevel(pos + vec3(0.0, 0.0, e)) - h0));
}

vec3 sd = normalize(vec3(0.0, sunHeight, -1.0));
vec3 ro = vec3(0.0, 3.2, 0.0);
vec3 rd = normalize(vec3(p.x, p.y * 0.8 - 0.35, -1.6));
vec3 col = sky(rd, sd);
if (rd.y < -0.002) {
  float tn = 0.0, tf = 1000.0, tm = tf;
  vec3 pt = ro + rd * tf;
  float hf = seaLevel(pt), hn = seaLevel(ro);
  if (hf < 0.0) {
    for (int i = 0; i < 10; i++) {
      tm = mix(tn, tf, hn / (hn - hf));
      pt = ro + rd * tm;
      float hm = seaLevel(pt);
      if (hm < 0.0) { tf = tm; hf = hm; } else { tn = tm; hn = hm; }
    }
    vec3 dist = pt - ro;
    vec3 n = seaNormal(pt, max(dot(dist, dist) * 0.0006, 0.002));   // coarser normals far away
    float fr = pow(1.0 - max(dot(n, -rd), 0.0), 3.0) * 0.65;
    vec3 refl = sky(reflect(rd, n), sd);
    vec3 refr = srgbToLinear(deep) + srgbToLinear(shallow) * pow(dot(n, sd) * 0.4 + 0.6, 80.0) * 0.12;
    col = mix(refr, refl, fr);
    float atten = max(1.0 - dot(dist, dist) * 0.001, 0.0);
    col += srgbToLinear(shallow) * (pt.y - swell) * 0.18 * atten;      // light through the crests
    vec3 hv = normalize(sd - rd);
    col += vec3(1.0, 0.9, 0.7) * pow(max(dot(n, hv), 0.0), 220.0) * 2.5;  // glitter
    float crest = smoothstep(0.55, 0.85, pt.y / max(swell * 1.5, 0.05)) * smoothstep(0.98, 0.9, n.y);
    col = mix(col, vec3(0.9), crest * 0.7 * atten);                      // foam
    col = mix(col, sky(vec3(rd.x, 0.0, rd.z), sd), 1.0 - exp(-tm * 0.006));
  }
}

finish(col)` },

  { id: "beach", label: "Beach — palm, boards, grass, shore", preview: [800, 450], source:
`uniform float sunHeight; // @range 0.05 0.6 @default 0.22
uniform float tide;      // @range -0.25 0.25 @default 0 — how far the water comes up
uniform vec3  sand;      // @color @default 0.88 0.78 0.58
uniform vec3  water;     // @color @default 0.05 0.52 0.60
uniform float breeze;    // @range 0 1 @default 0.4
uniform bool  palm;      // @toggle @default 1
uniform bool  boards;    // @toggle @default 1

// A painting in p — y up, x scaled by the aspect. The sun sits low on the
// left, so every shadow falls right and towards you.
const float HORIZON = 0.30;

// Ground point -> the point on an upright object that casts a shadow there.
// The sun is low and to the left, so shadows run long to the right and only a
// little towards you.
vec2 unproject(vec2 g, float yb) {
  float y = yb + (yb - g.y) / 0.18;
  return vec2(g.x - 1.6 * (y - yb), y);
}
float trunk(vec2 q, vec2 base, vec2 top) {
  vec2 ctrl = vec2(base.x + 0.04, base.y + (top.y - base.y) * 0.65);
  float d = 1e3;
  vec2 prev = base;
  for (int i = 1; i <= 6; i++) {
    float s = float(i) / 6.0;
    vec2 pt = mix(mix(base, ctrl, s), mix(ctrl, top, s), s);
    d = min(d, sdCapsule(q, prev, pt, 0.030 - 0.016 * s));
    prev = pt;
  }
  return d;
}
// One frond in its own frame: a spine along +x with leaflets angled forward
// off both sides, repeated by nearest index so it costs three capsules.
float frond(vec2 r) {
  float L = 0.72;
  float d = sdCapsule(r, vec2(0.0), vec2(L, 0.0), 0.006);
  float cell = 0.045;
  float xi = clamp(floor(r.x / cell + 0.5), 1.0, L / cell - 1.0);
  for (int k = -1; k <= 0; k++) {
    float xj = clamp(xi + float(k), 1.0, L / cell - 1.0);
    vec2 o = vec2(xj * cell, 0.0);
    float along = xj * cell / L;
    float len = 0.17 * (1.0 - 0.55 * along) * (0.6 + 0.4 * smoothstep(0.0, 0.15, along));
    vec2 dir = normalize(vec2(0.5, sign(r.y + 1e-4) * 0.87));
    d = min(d, sdCapsule(r, o, o + dir * len, 0.004));
  }
  return d;
}
float fronds(vec2 q, vec2 top) {
  float d = 1e3;
  for (int i = 0; i < 7; i++) {
    float a = -0.5 + float(i) * 0.58 + sin(t * 1.3 + float(i)) * breeze * 0.05;
    vec2 r = rot(a) * (q - top);
    r.y += 0.5 * r.x * r.x;                                   // droop
    d = min(d, frond(r));
  }
  for (int i = 0; i < 3; i++) {
    d = min(d, sdCircle(q - top - vec2(0.035 * float(i) - 0.035, -0.03 - 0.015 * float(i)), 0.028));
  }
  return d;
}
float board(vec2 q, vec2 base, float lean, float w) {
  vec2 r = rot(lean) * (q - base);
  r.y -= 0.36;
  float taper = 1.0 - 0.45 * smoothstep(0.0, 0.42, r.y);
  return max(sdEllipse(r, vec2(w * taper, 0.42)), base.y - q.y);
}
float grass(vec2 q, vec2 base, float k) {
  float d = 1e3;
  for (int j = 0; j < 6; j++) {
    float a = (float(j) - 2.5) * 0.28 + (hash21(vec2(float(j), k)) - 0.5) * 0.25;
    float len = 0.16 + hash21(vec2(k, float(j))) * 0.12;
    float sway = sin(t * 2.0 + k * 3.0 + float(j) * 0.5) * breeze * 0.05 + breeze * 0.03;
    vec2 mid = base + vec2(sin(a) * len * 0.5 + sway * 0.4, cos(a) * len * 0.5);
    vec2 tip = mid + vec2(sin(a) * len * 0.5 + sway, cos(a) * len * 0.42);
    d = min(d, sdCapsule(q, base, mid, 0.005));
    d = min(d, sdCapsule(q, mid, tip, 0.0025));
  }
  return d;
}

vec3 sd = normalize(vec3(-0.30, sunHeight, -1.0));
vec3 rd = normalize(vec3(p.x, (p.y - HORIZON) * 0.7 + 0.001, -1.0));
vec3 skyc = sky(rd, sd);
{
  float hh = max(rd.y, 0.02);
  vec2 cp = rd.xz / hh * 0.6 + vec2(t * breeze * 0.2, 0.0) + seed;
  float c = smoothstep(0.55, 0.8, fbm(cp + fbm(cp * 0.5) * 1.2)) * exp(-0.05 / hh);
  skyc = mix(skyc, vec3(1.0, 0.95, 0.9), c * 0.8);
}

// The water's edge breathes in and out.
float edge = (-0.30 + tide) + sin(p.x * 4.0 + t * 0.6) * 0.015
           + (fbm(vec2(p.x * 2.5 + seed, t * 0.25)) - 0.5) * 0.05 + sin(t * 0.8) * 0.025;

// Sea: swells compress towards the horizon, whitewater on the last few.
float seaT = clamp((HORIZON - p.y) / (HORIZON - edge), 0.0, 1.0);
float phase = pow(seaT, 1.7) * 16.0 - t * 1.4;
float swellF = sin(phase + fbm(vec2(p.x * 2.5 + seed, phase * 0.25)) * 1.6);
vec3 waterL = srgbToLinear(water);
vec3 seac = mix(waterL * 0.35, waterL, seaT * 0.85 + 0.15);
seac = mix(seac, waterL * 1.5 + 0.12, smoothstep(0.55, 1.0, swellF) * 0.35 * seaT);
seac = mix(seac, waterL * 0.55, smoothstep(-0.55, -1.0, swellF) * 0.35 * seaT);
float breakF = smoothstep(0.7, 0.9, seaT) * smoothstep(0.7, 0.98, swellF + fbm(vec2(p.x * 9.0, phase * 0.6)) * 0.5);
seac = mix(seac, vec3(0.92), breakF * 0.9);
float lip = smoothstep(0.06, 0.0, p.y - edge);
seac = mix(seac, vec3(0.95), lip * (0.6 + 0.4 * fbm(vec2(p.x * 20.0, t))));
float glit = step(0.988, hash21(floor(vec2(p.x * 260.0, p.y * 260.0 + t * 6.0))));
seac += vec3(1.0, 0.92, 0.75) * glit * exp(-abs(p.x + 0.30) * 2.5) * (1.0 - seaT) * seaT * 12.0;
seac = mix(seac, skyc, pow(1.0 - seaT, 5.0) * 0.55);

// Sand: mottling, grain, ripples, and a wet band the last wave left.
vec3 sandc = srgbToLinear(sand) * (0.9 + 0.1 * fbm(p * 5.0 + seed));
sandc *= 0.93 + 0.14 * hash21(floor(p * 260.0));
sandc *= 1.0 + 0.05 * sin(p.y * 45.0 + fbm(p * 3.0) * 7.0);
float wet = smoothstep(edge - 0.09 - 0.03 * sin(t * 0.8), edge, p.y);
sandc = mix(sandc, sandc * 0.55 + skyc * 0.10, wet);

vec3 col = p.y > HORIZON ? skyc : (p.y > edge ? seac : sandc);

// Props and their shadows. Bases sit on the sand; shadows are the same SDFs
// read at the unprojected point, softening with distance from the base.
vec2 PB = vec2(-1.30, -0.62), PT = vec2(-0.92, 0.66);
vec2 B1 = vec2(0.85, -0.75), B2 = vec2(1.08, -0.79);
vec2 G1 = vec2(-0.35, -0.86), G2 = vec2(0.30, -0.70), G3 = vec2(1.45, -0.92);
float shadow = 0.0;
if (palm && p.y < PB.y) {
  vec2 o = unproject(p, PB.y);
  float ds = min(trunk(o, PB, PT), fronds(o, PT));
  float soft = 0.01 + 0.06 * (PB.y - p.y);
  shadow = max(shadow, smoothstep(soft, -soft, ds));
}
if (boards) {
  if (p.y < B1.y) shadow = max(shadow, smoothstep(0.02, -0.02, board(unproject(p, B1.y), B1, 0.12, 0.085)));
  if (p.y < B2.y) shadow = max(shadow, smoothstep(0.02, -0.02, board(unproject(p, B2.y), B2, -0.08, 0.075)));
}
if (p.y < G1.y) shadow = max(shadow, smoothstep(0.008, -0.008, grass(unproject(p, G1.y), G1, 1.0)));
if (p.y < G2.y) shadow = max(shadow, smoothstep(0.008, -0.008, grass(unproject(p, G2.y), G2, 2.0)));
if (p.y < G3.y) shadow = max(shadow, smoothstep(0.008, -0.008, grass(unproject(p, G3.y), G3, 3.0)));
col = mix(col, col * vec3(0.50, 0.52, 0.62), shadow * step(p.y, edge));

if (boards) {
  float d1 = board(p, B1, 0.12, 0.085), d2 = board(p, B2, -0.08, 0.075);
  vec3 c1 = mix(vec3(0.85), vec3(0.75, 0.12, 0.10), aa(board(p, B1, 0.12, 0.030)));
  vec3 c2 = mix(vec3(0.55, 0.72, 0.80), vec3(0.03, 0.06, 0.20), aa(board(p, B2, -0.08, 0.026)));
  col = mix(col, c2 * (0.75 + 0.25 * smoothstep(0.0, 0.05, -d2)), aa(d2));
  col = mix(col, c1 * (0.75 + 0.25 * smoothstep(0.0, 0.05, -d1)), aa(d1));
}
if (palm) {
  float dt_ = trunk(p, PB, PT), df = fronds(p, PT);
  float lit = 1.0 - aa(trunk(p + vec2(0.025, 0.0), PB, PT));               // the sunward edge
  col = mix(col, vec3(0.10, 0.06, 0.035) * (0.5 + 1.8 * lit), aa(dt_));
  col = mix(col, vec3(0.035, 0.085, 0.04) * (0.7 + 0.6 * fbm(p * 8.0)), aa(df));   // backlit
}
{
  float dg = min(min(grass(p, G1, 1.0), grass(p, G2, 2.0)), grass(p, G3, 3.0));
  col = mix(col, vec3(0.16, 0.20, 0.08), aa(dg));
}
col *= mix(1.0, vignette(uv, 0.3), 0.35);

finish(col)` },

  { id: "sand", label: "Sand, close — ripples and a shell", preview: [800, 450], source:
`uniform vec3  sand;     // @color @default 0.87 0.76 0.55
uniform float ripple;   // @range 0 1 @default 0.6
uniform float sunAngle; // @range 0 6.28 @default 3.9 — where the light comes from
uniform float sunLow;   // @range 0.1 1 @default 0.3 — lower sun, longer shadows

// A height field: wind ripples, grain, and one shell. Lit from its normal,
// with the shadow found by walking the field towards the sun.
float hgt(vec2 q) {
  float r = sin(q.y * 18.0 + fbm(q * 2.0 + seed) * 5.0 + q.x * 2.0) * 0.5 + 0.5;
  r = pow(r, 1.6) * ripple * 0.06;
  float g = (fbm(q * 40.0) - 0.5) * 0.012;
  vec2 sq = (q - vec2(0.35, -0.2)) * vec2(1.0, 1.4);
  float ang = atan(sq.y, sq.x);
  float shell = smoothstep(0.17, 0.0, length(sq)) * (1.0 + 0.12 * sin(ang * 14.0)) * 0.12;
  return r + g + shell;
}

vec3 sandL = srgbToLinear(sand);
float e = 0.004;
float h0 = hgt(p);
vec3 n = normalize(vec3(-(hgt(p + vec2(e, 0.0)) - h0) / e, 1.0, -(hgt(p + vec2(0.0, e)) - h0) / e));
vec3 l = normalize(vec3(cos(sunAngle), sunLow, sin(sunAngle)));
float diff = max(dot(n, l), 0.0);
float shadow = 1.0;
{
  vec3 pos = vec3(p.x, h0 + 0.002, p.y);
  for (int i = 1; i <= 16; i++) {
    pos += l * 0.02;
    if (hgt(pos.xz) > pos.y) { shadow = 0.0; break; }
  }
}
vec3 col = sandL * (0.22 + 0.9 * diff * shadow) + vec3(0.30, 0.36, 0.5) * sandL * 0.15;
col *= 0.92 + 0.16 * hash21(floor(p * 420.0));                                     // grain
col += vec3(1.0, 0.95, 0.8) * step(0.996, hash21(floor(p * 700.0))) * diff * shadow * 0.8;   // mica
vec2 sq = (p - vec2(0.35, -0.2)) * vec2(1.0, 1.4);
col = mix(col, col * vec3(1.05, 0.98, 0.95) + 0.05, smoothstep(0.17, 0.12, length(sq)) * 0.6);   // the shell is paler
col *= mix(1.0, vignette(uv, 0.3), 0.3);

finish(col)` },

  { id: "dunegrass", label: "Dune grass at sunset", preview: [800, 450], source:
`uniform float sunHeight; // @range 0.0 0.4 @default 0.06
uniform float breeze;    // @range 0 1 @default 0.5
uniform float tufts;     // @range 3 12 step 1 @default 7
uniform vec3  ember;     // @color @default 1.0 0.45 0.15
uniform vec3  dusk;      // @color @default 0.20 0.12 0.32

// A warm sky of its own, a dune silhouette, and grass drawn as capsules
// swaying in the wind, backlit at the edges.
vec3 sd = normalize(vec3(0.15, sunHeight, -1.0));
vec3 rd = normalize(vec3(p.x, p.y * 0.5 + 0.25, -1.0));
float y = clamp(rd.y, 0.0, 1.0);
vec3 col = mix(srgbToLinear(ember), srgbToLinear(dusk), pow(y, 0.5));
float s = max(dot(rd, sd), 0.0);
col += vec3(1.0, 0.8, 0.5) * (pow(s, 600.0) * 8.0 + pow(s, 24.0) * 0.8 + pow(s, 3.0) * 0.35);
col = mix(col, vec3(0.9, 0.5, 0.35), smoothstep(0.55, 0.75, fbm(vec2(p.x * 2.0 + t * 0.05, p.y * 9.0))) * 0.35 * (1.0 - y));

float dune = -0.45 + fbm(vec2(p.x * 0.7 + seed, 0.0)) * 0.25;
float d = 1e3;
for (int i = 0; i < 12; i++) {
  if (float(i) >= tufts) break;
  float fx = -1.7 + 3.4 * (float(i) + 0.5) / tufts + (hash21(vec2(float(i), seed)) - 0.5) * 0.2;
  float fy = -0.45 + fbm(vec2(fx * 0.7 + seed, 0.0)) * 0.25 - 0.02;
  for (int j = 0; j < 7; j++) {
    float a = (float(j) - 3.0) * 0.22 + (hash21(vec2(float(i) * 7.0 + float(j), 1.0)) - 0.5) * 0.2;
    float len = 0.25 + hash21(vec2(float(j), float(i))) * 0.2;
    float sway = sin(t * 1.7 + float(i) * 0.9 + float(j) * 0.4) * breeze * 0.12 + breeze * 0.08;
    vec2 base = vec2(fx, fy);
    vec2 mid = base + vec2(sin(a) * len * 0.5 + sway * 0.4, cos(a) * len * 0.5);
    vec2 tip = mid + vec2(sin(a) * len * 0.5 + sway, cos(a) * len * 0.42);
    d = min(d, sdCapsule(p, base, mid, 0.007));
    d = min(d, sdCapsule(p, mid, tip, 0.0035));
  }
}
vec3 ground = mix(vec3(0.09, 0.055, 0.045), vec3(0.45, 0.22, 0.10), smoothstep(0.04, 0.0, dune - p.y) * 0.7);
col = mix(col, ground, step(p.y, dune));
col += vec3(1.0, 0.6, 0.3) * smoothstep(0.014, 0.0, d) * step(0.0, d) * 0.4;   // rim: just outside the blade
col = mix(col, vec3(0.05, 0.035, 0.025), aa(d));

finish(col)` },

  // ---- images. A sampler2D is a picture you choose; <name>_size reads (0,0)
  // until you do, so these draw a stand-in rather than a grey square.

  { id: "grade", label: "Photo — grade, grain, vignette", preview: [800, 450], source:
`uniform sampler2D photo;  // @image
uniform vec2  photo_size;
uniform float exposure;   // @range -2 2 @default 0.2 — stops
uniform float contrast;   // @range 0.5 2 @default 1.15
uniform float warmth;     // @range -1 1 @default 0.25
uniform float fade;       // @range 0 1 @default 0.25 — lifted blacks
uniform float grainAmt;   // @range 0 1 @default 0.35
uniform float vig;        // @range 0 1 @default 0.5

// A stand-in when there is no image: soft blobs and a horizon.
vec3 standIn(vec2 q) {
  vec3 c = mix(vec3(0.85, 0.55, 0.30), vec3(0.15, 0.30, 0.55), q.y);
  c = mix(c, vec3(1.0, 0.9, 0.7), smoothstep(0.35, 0.0, length(q - vec2(0.65, 0.6))));
  c *= 0.8 + 0.4 * fbm(q * 5.0);
  return srgbToLinear(c);
}

vec3 lin = photo_size.x > 0.5
  ? srgbToLinear(texture2D(photo, coverUV(uv, photo_size)).rgb)
  : standIn(uv);
lin *= exp2(exposure);
float l = luma(lin);
lin = mix(vec3(l), lin, 1.05);                                    // a touch of saturation
lin = pow(max(lin, 0.0), vec3(contrast)) * pow(0.18, 1.0 - contrast);   // contrast about middle grey
lin *= mix(vec3(1.0), vec3(1.08, 1.0, 0.90), warmth);            // warm / cool
lin = lin * (1.0 - fade * 0.15) + fade * 0.03;                   // film fade: black is not zero
lin *= mix(1.0, vignette(uv, 0.4), vig);
lin += grain(uv, t) * grainAmt * 0.06 * (0.3 + l);              // grain rides the midtones

finish(lin)` },

  { id: "halftone", label: "Photo — halftone and dither", preview: [800, 450], source:
`uniform sampler2D photo;  // @image
uniform vec2  photo_size;
uniform float cellPx;     // @range 3 24 step 1 @default 8 — dot cell in pixels
uniform float angle;      // @range 0 1.57 @default 0.4 — screen angle
uniform bool  ordered;    // @toggle — Bayer dither instead of dots
uniform vec3  ink;        // @color @default 0.08 0.06 0.10
uniform vec3  paper;      // @color @default 0.96 0.93 0.86

// The same photo, quantised two ways. Both are Module 5: a threshold with a
// carrier keeps tone as area, where a plain threshold would throw it away.
float bayer(vec2 px) {
  vec2 c = floor(mod(px, 4.0));
  float b = 0.0;
  b += mod(c.x, 2.0) * 8.0 + mod(c.y, 2.0) * 4.0;
  b += mod(floor(c.x / 2.0), 2.0) * 2.0 + mod(floor(c.y / 2.0), 2.0);
  return (b + 0.5) / 16.0;
}
float source(vec2 q) {
  if (photo_size.x > 0.5) return luma(texture2D(photo, coverUV(q, photo_size)).rgb);
  float g = 0.5 + 0.5 * sin(q.x * 6.0) * cos(q.y * 4.0);       // a stand-in gradient
  return mix(g, smoothstep(0.4, 0.0, length(q - vec2(0.5))), 0.5);
}

vec2 px = gl_FragCoord.xy;
float tone;
float v;
if (ordered) {
  tone = source(uv);
  v = step(bayer(px), tone);
} else {
  vec2 r = rot(angle) * px;
  vec2 cell = (floor(r / cellPx) + 0.5) * cellPx;
  vec2 back = rot(-angle) * cell;                                // sample at the cell centre
  tone = source(back / u_resolution);
  float radius = sqrt(1.0 - tone) * cellPx * 0.62;              // area carries the tone
  v = smoothstep(-0.7, 0.7, length(r - cell) - radius);
}

srgbToLinear(mix(ink, paper, v))` },

  // ---- three dimensions and motion. Real ray hits against real surfaces;
  // the ball drops are exact ballistics, solved for time rather than stepped.

  { id: "still", label: "Still life, raymarched (3D)", preview: [800, 450], source:
`uniform float sunHeight; // @range 0.1 1.2 @default 0.6
uniform float orbit;     // @range 0 6.28 @default 0.6 — where the camera stands
uniform vec3  paint;     // @color @default 0.80 0.25 0.18
uniform vec3  metal;     // @color @default 0.90 0.75 0.45
uniform float gloss;     // @range 0 1 @default 0.6

// Defining scene(vec3) brings in the 3D kit: march, normal3, softShadow, ao,
// lookAt and the primitives. Objects are told apart by asking which one is
// nearest at the hit — GLSL has no way to hand a material back from march().
float scene(vec3 q) {
  float floorD = sdPlane(q, 0.0);
  float ball = sdSphere(q - vec3(-0.9, 0.6, 0.2), 0.6);
  float box = sdBox3(q - vec3(0.8, 0.45, -0.3), vec3(0.45)) - 0.04;
  float ring = sdTorus(q - vec3(0.2, 0.22, 0.9), vec2(0.5, 0.12));
  return min(min(floorD, ball), min(box, ring));
}
int nearest(vec3 q) {
  float a = sdPlane(q, 0.0), b = sdSphere(q - vec3(-0.9, 0.6, 0.2), 0.6);
  float c = sdBox3(q - vec3(0.8, 0.45, -0.3), vec3(0.45)) - 0.04;
  float d = sdTorus(q - vec3(0.2, 0.22, 0.9), vec2(0.5, 0.12));
  float m = min(min(a, b), min(c, d));
  return m == a ? 0 : (m == b ? 1 : (m == c ? 2 : 3));
}

vec3 sd = normalize(vec3(-0.6, sunHeight, 0.4));
vec3 ro = vec3(3.6 * sin(orbit), 1.7, 3.6 * cos(orbit));
vec3 rd = lookAt(ro, vec3(0.0, 0.4, 0.0)) * normalize(vec3(p, 1.7));
vec3 col = sky(rd, sd);
float tHit = march(ro, rd, 30.0);
if (tHit > 0.0) {
  vec3 pos = ro + rd * tHit;
  vec3 n = normal3(pos);
  int id = nearest(pos);
  vec3 albedo = id == 0
    ? mix(vec3(0.55), vec3(0.85), mod(floor(pos.x) + floor(pos.z), 2.0)) * 0.6
    : (id == 1 ? srgbToLinear(paint) : (id == 2 ? srgbToLinear(metal) : vec3(0.85, 0.87, 0.9)));
  float dif = max(dot(n, sd), 0.0) * softShadow(pos + n * 0.01, sd, 12.0);
  float occ = ao(pos, n);
  vec3 lig = vec3(1.0, 0.92, 0.80) * 2.6 * dif;
  lig += vec3(0.35, 0.45, 0.65) * (0.5 + 0.5 * n.y) * occ;         // sky fill
  lig += vec3(0.25, 0.20, 0.15) * max(-n.y, 0.0) * occ * 0.4;      // ground bounce
  col = albedo * lig;
  vec3 hv = normalize(sd - rd);
  float fr = fresnel(max(dot(n, -rd), 0.0), 0.04);
  vec3 refl = sky(reflect(rd, n), sd) * softShadow(pos + n * 0.01, reflect(rd, n), 8.0);
  col += pow(max(dot(n, hv), 0.0), mix(12.0, 240.0, gloss)) * dif * gloss * 1.5;
  col = mix(col, refl, fr * gloss * (id == 0 ? 0.3 : 1.0));
  col = mix(col, sky(rd, sd), 1.0 - exp(-tHit * 0.02));           // aerial perspective
}

finish(col)` },

  { id: "bounce", label: "Bouncing balls, exact ballistics (3D)", preview: [800, 450], source:
`uniform float drop;      // @range 0.6 3 @default 1.8 — release height
uniform float bouncy;    // @range 0.3 0.95 @default 0.72 — restitution
uniform float speed;     // @range 0.2 2 @default 1.0
uniform float sunHeight; // @range 0.2 1.2 @default 0.7

// Height of a ball dropped from h0 at time t, restitution e, solved in
// closed form: the n-th flight lasts T0·e^n and the sum is geometric, so n
// falls out of a log rather than a step loop. It settles, pauses, repeats.
float bounceY(float tt, float h0, float e) {
  float g = 9.8;
  float T0 = 2.0 * sqrt(2.0 * h0 / g);          // one full flight from height h0
  float settle = T0 * 0.5 + T0 * e / (1.0 - e); // fall + every bounce
  tt = mod(tt, settle + 1.2);
  if (tt < T0 * 0.5) return h0 - 0.5 * g * tt * tt;
  float u = tt - T0 * 0.5;
  float arg = 1.0 - u * (1.0 - e) / (T0 * e);
  if (arg <= 0.001) return 0.0;
  float n = floor(log(arg) / log(e));
  float Sn = T0 * e * (1.0 - pow(e, n)) / (1.0 - e);
  float Tn = T0 * pow(e, n + 1.0);
  float tau = u - Sn;
  float v0 = 0.5 * g * Tn;
  return max(v0 * tau - 0.5 * g * tau * tau, 0.0);
}
// Where the three balls are *this frame*. bounceY is a mod, a sqrt, a log and
// two pows, and it depends on the time and nothing else — so it is a constant
// for the whole pixel, and computing it inside scene() means paying for it
// once per march step instead of once per frame. Three hundred and thirty
// evaluations a pixel became three.
vec3 gY;
float scene(vec3 q) {
  float d = sdPlane(q, 0.0);
  d = min(d, sdSphere(q - vec3(-0.95, 0.36 + gY.x, 0.0), 0.36));
  d = min(d, sdSphere(q - vec3( 0.00, 0.36 + gY.y, 0.0), 0.36));
  d = min(d, sdSphere(q - vec3( 0.95, 0.36 + gY.z, 0.0), 0.36));
  return d;
}

float tt = t * speed;
gY = vec3(bounceY(tt, drop, bouncy),
          bounceY(tt + 0.7, drop * 0.8, bouncy * 0.9),
          bounceY(tt + 1.4, drop * 0.6, min(bouncy * 1.15, 0.95)));

// Close enough that the balls are the subject. The old camera stood five
// metres back with a wide lens, which put three small dots on a large floor —
// technically the same scene and a worse picture.
vec3 sd = normalize(vec3(-0.5, sunHeight, 0.6));
vec3 ro = vec3(0.35, 1.15, 3.4);
vec3 rd = lookAt(ro, vec3(0.0, 0.62, 0.0)) * normalize(vec3(p, 2.0));
vec3 col = sky(rd, sd);
float tHit = march(ro, rd, 40.0);
if (tHit > 0.0) {
  vec3 pos = ro + rd * tHit;
  vec3 n = normal3(pos);
  bool isFloor = pos.y < 0.02 && abs(n.y) > 0.99;
  vec3 albedo = isFloor
    ? mix(vec3(0.30), vec3(0.42), mod(floor(pos.x) + floor(pos.z), 2.0))
    : (pos.x < -0.6 ? srgbToLinear(vec3(0.85, 0.22, 0.16))
                    : (pos.x < 0.6 ? srgbToLinear(vec3(0.15, 0.52, 0.85))
                                   : srgbToLinear(vec3(0.95, 0.72, 0.20))));
  float sh = softShadow(pos + n * 0.01, sd, 16.0);
  float dif = max(dot(n, sd), 0.0) * sh;
  float occ = ao(pos, n);
  // The same three lights the still life is lit by: sun, sky from above, and
  // a warm bounce off the floor. A ball lit only from the sun is a sticker.
  vec3 lig = vec3(1.0, 0.92, 0.80) * 2.6 * dif;
  lig += vec3(0.35, 0.45, 0.65) * (0.5 + 0.5 * n.y) * occ;
  lig += vec3(0.30, 0.24, 0.18) * max(-n.y, 0.0) * occ * 0.5;
  col = albedo * lig;
  // A gloss, and the sky in the surface — the floor takes a little, the balls
  // take a lot, and both fall off at grazing angles the way a real one does.
  vec3 hv = normalize(sd - rd);
  float fr = fresnel(max(dot(n, -rd), 0.0), 0.04);
  col += pow(max(dot(n, hv), 0.0), isFloor ? 60.0 : 180.0) * dif * (isFloor ? 0.25 : 1.4);
  col = mix(col, sky(reflect(rd, n), sd), fr * (isFloor ? 0.35 : 0.75));
  col = mix(col, sky(rd, sd), 1.0 - exp(-tHit * 0.015));
}

finish(col)` },

  { id: "ripples", label: "Ripple tank — interference and reflection", preview: [800, 450], source:
`uniform int   sources;   // @range 1 4 @default 2
uniform float wavelength;// @range 0.05 0.5 @default 0.16
uniform float speed;     // @range 0 3 @default 1.0
uniform float damping;   // @range 0 3 @default 0.8 — falloff with distance
uniform vec2  s1;        // @pad
uniform vec2  s2;        // @pad @default 0.75 0.6
uniform vec3  water;     // @color @default 0.10 0.40 0.55

// Circular waves from up to four sources in a rectangular tank. The walls
// reflect: each source gets its four mirror images, which is exactly what a
// hard boundary does to a wave. Interference is then just the sum.
float wave(vec2 q, vec2 src, float k, float w) {
  float r = length(q - src);
  return cos(k * r - w * t) * exp(-damping * r) / sqrt(1.0 + r * 4.0);
}
float tank(vec2 q, vec2 src, float k, float w) {
  float A = u_resolution.x / u_resolution.y;                       // tank half-width
  float h = wave(q, src, k, w);
  h += wave(q, vec2(-2.0 * A - src.x, src.y), k, w) + wave(q, vec2(2.0 * A - src.x, src.y), k, w);
  h += wave(q, vec2(src.x, -2.0 - src.y), k, w) + wave(q, vec2(src.x, 2.0 - src.y), k, w);
  return h;
}
float height(vec2 q) {
  float k = 6.2831 / wavelength, w = k * speed * 0.35;
  float A = u_resolution.x / u_resolution.y;
  vec2 c1 = (s1 * 2.0 - 1.0) * vec2(A, 1.0);
  vec2 c2 = (s2 * 2.0 - 1.0) * vec2(A, 1.0);
  float h = tank(q, c1, k, w);
  if (sources > 1) h += tank(q, c2, k, w);
  if (sources > 2) h += tank(q, vec2(-A * 0.6, -0.55), k, w);
  if (sources > 3) h += tank(q, vec2(A * 0.55, -0.6), k, w);
  return h * 0.06;
}

float e = 0.004;
float h0 = height(p);
vec3 n = normalize(vec3(-(height(p + vec2(e, 0.0)) - h0) / e, 1.0, -(height(p + vec2(0.0, e)) - h0) / e));
vec3 sd = normalize(vec3(-0.4, 0.8, 0.5));
vec3 view = vec3(0.0, 1.0, 0.0);
vec3 refl = reflect(-view, n);
vec3 col = srgbToLinear(water) * (0.6 + 0.4 * max(dot(n, sd), 0.0));
col += sky(vec3(refl.x, abs(refl.y), refl.z), sd) * fresnel(max(dot(n, view), 0.0), 0.02) * 2.0;
col += vec3(1.0, 0.95, 0.85) * pow(max(dot(n, normalize(sd + view)), 0.0), 180.0) * 2.0;
col += vec3(0.6, 0.8, 0.9) * max(-h0, 0.0) * 4.0;              // caustic-ish light in the troughs

finish(col)` },

  // ---- simulations. Define vec4 sim(vec2 uv) and a state pass runs before
  // the picture, reading its own last frame. These are real: the rule is
  // applied every step to what the previous step left.

  { id: "reaction", label: "Reaction–diffusion (Gray–Scott)", preview: [640, 640], steps: 8, source:
`uniform float feed;      // @range 0.01 0.08 @default 0.037
uniform float kill;      // @range 0.04 0.07 @default 0.06
uniform vec3  ink;       // @color @default 0.10 0.05 0.20
uniform vec3  paper;     // @color @default 0.95 0.92 0.85
uniform vec3  edge;      // @color @default 0.90 0.45 0.20

// Two chemicals, u (red channel) and v (green). v eats u and makes more v;
// u is fed in and v is removed. Diffusion at different rates does the rest.
// Karl Sims' weights for the Laplacian.
vec4 sim(vec2 q) {
  if (frame < 1) {
    float blob = smoothstep(0.06, 0.02, length(p - vec2(0.0, 0.0)));
    blob += smoothstep(0.03, 0.01, length(p - vec2(0.5, 0.3)));
    return vec4(1.0, blob * 0.9, 0.0, 1.0);
  }
  vec4 c = prevAt(vec2(0.0));
  vec4 lap = -c
    + 0.2  * (prevAt(vec2(1.0, 0.0)) + prevAt(vec2(-1.0, 0.0)) + prevAt(vec2(0.0, 1.0)) + prevAt(vec2(0.0, -1.0)))
    + 0.05 * (prevAt(vec2(1.0, 1.0)) + prevAt(vec2(-1.0, 1.0)) + prevAt(vec2(1.0, -1.0)) + prevAt(vec2(-1.0, -1.0)));
  float u = c.r, v = c.g;
  float uvv = u * v * v;
  u += 1.0 * lap.r - uvv + feed * (1.0 - u);
  v += 0.5 * lap.g + uvv - (feed + kill) * v;
  // press to add v under the pointer
  v += md * smoothstep(0.05, 0.0, length(q - m) * (u_resolution.x / u_resolution.y)) * 0.5;
  return vec4(clamp(u, 0.0, 1.0), clamp(v, 0.0, 1.0), 0.0, 1.0);
}

float v = state(uv).g;
vec3 col = mix(srgbToLinear(paper), srgbToLinear(edge), smoothstep(0.05, 0.25, v));
col = mix(col, srgbToLinear(ink), smoothstep(0.25, 0.5, v));

finish(col)` },

  { id: "waves", label: "Wave equation — tap the water", preview: [800, 450], steps: 2, source:
`uniform float speed;     // @range 0.1 0.5 @default 0.35 — wave speed (keep under 0.5 or it blows up)
uniform float damping;   // @range 0.98 1.0 @default 0.996
uniform float rain;      // @range 0 1 @default 0.15 — random drops
uniform vec3  water;     // @color @default 0.06 0.35 0.50

// Height in red, velocity in green. The discrete wave equation: acceleration
// is the Laplacian of height. Press to make a drop; rain does it for you.
vec4 sim(vec2 q) {
  if (frame < 1) return vec4(0.0, 0.0, 0.0, 1.0);
  vec4 c = prevAt(vec2(0.0));
  float lap = prevAt(vec2(1.0, 0.0)).r + prevAt(vec2(-1.0, 0.0)).r
            + prevAt(vec2(0.0, 1.0)).r + prevAt(vec2(0.0, -1.0)).r - 4.0 * c.r;
  float vel = (c.g + speed * speed * lap) * damping;
  float h = c.r + vel;
  float aspect = u_resolution.x / u_resolution.y;
  h += md * smoothstep(0.02, 0.0, length((q - m) * vec2(aspect, 1.0))) * 0.5;
  // an occasional drop somewhere
  float drop = step(1.0 - rain * 0.02, hash21(vec2(float(frame), seed)));
  vec2 where = vec2(hash21(vec2(float(frame), 1.7)), hash21(vec2(2.3, float(frame))));
  h += drop * smoothstep(0.015, 0.0, length((q - where) * vec2(aspect, 1.0))) * 0.6;
  return vec4(h, vel, 0.0, 1.0);
}

float h0 = state(uv).r;
vec3 n = normalize(vec3(-(stateAt(vec2(1.0, 0.0)).r - stateAt(vec2(-1.0, 0.0)).r) * 40.0, 1.0,
                        -(stateAt(vec2(0.0, 1.0)).r - stateAt(vec2(0.0, -1.0)).r) * 40.0));
vec3 sd = normalize(vec3(-0.4, 0.8, 0.5));
vec3 view = vec3(0.0, 1.0, 0.0);
vec3 refl = reflect(-view, n);
vec3 col = srgbToLinear(water) * (0.6 + 0.4 * max(dot(n, sd), 0.0));
col += sky(vec3(refl.x, abs(refl.y), refl.z), sd) * fresnel(max(dot(n, view), 0.0), 0.02) * 2.0;
col += vec3(1.0, 0.95, 0.85) * pow(max(dot(n, normalize(sd + view)), 0.0), 200.0) * 2.0;
col += vec3(0.5, 0.7, 0.8) * max(-h0, 0.0) * 3.0;

finish(col)` },

  { id: "rover", label: "Rover — a raymarched world you drive, with shadows", preview: [640, 360], steps: 1,
    probes: { got: { texel: [2, 0], channel: "r" }, bump: { texel: [2, 0], channel: "g" },
              score: { texel: [1, 0], channel: "g" }, speed: { texel: [1, 0], channel: "b" } },
    instruments: { chime: { ref: "tone.bell" }, knock: { ref: "tone.pluck" }, motor: { ref: "tone.blip" } },
    effects: [
      { kind: "note", instrument: "chime", when: 'ch("got") > 0.5',
        hz: '659 * 2 ^ (min(ch("score"), 10) / 12)', dur: "0.35" },
      { kind: "note", instrument: "knock", when: 'ch("bump") > 0.5', hz: "110", dur: "0.25" },
    ],
    source:
`// A world you drive around, lit properly: one distance function raymarched,
// a soft shadow from a real occlusion march, ambient occlusion, a sky that
// the ground reflects a little, and the tone-map-and-dither finish. Arrows or
// WASD steer; the eight beacons are the game.
//
// The trick worth reading: scene() is a pure function of a point, and it asks
// the *state texture* where the rover and the beacons are. A shader's world
// can be data without ceasing to be a function.
uniform sampler2D u_keys;
uniform float accel;    // @range 2 20 @default 8 @help how hard it pulls away
uniform float turn;     // @range 0.5 4 @default 1.9 @help radians a second
uniform float drag;     // @range 0.9 0.999 @default 0.965 @help speed kept each frame
uniform float hour;     // @range 0 1 @default 0.28 @help sun height, 0 is dusk
uniform vec3 sand;      // @color @default #9a744a
uniform vec3 shell;     // @color @default #f4efe6

const float BEACONS = 8.0;
vec4 rover() { return state(vec2(0.5, 0.5) / u_resolution); }   // x, z, heading, speed
vec4 meta()  { return state(vec2(1.5, 0.5) / u_resolution); }   // taken, score, speed, alive
// Beacon k is a texel; r is 1 while it still stands.
float standing(float k) { return state(vec2(4.5 + k, 0.5) / u_resolution).r; }
vec2 beaconAt(float k) {
  return (vec2(hash21(vec2(k * 3.1, 1.0)), hash21(vec2(k * 7.7, 2.0))) - 0.5) * 34.0;
}
// The ground: low rolling dunes, so the shadows have something to fall on.
float fbmN(vec2 p, int n) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 6; i++) { if (i >= n) break; v += a * noise(p); p *= 2.02; a *= 0.5; }
  return v;
}
// The terrain, written out: two fbm, six noise, twenty-four hashes a call.
float duneAt(vec2 q) { return -1.0 + 0.55 * fbmN(q * 0.09, 4) + 0.18 * fbmN(q * 0.31, 2); }

// …and the terrain as *data*. The dunes do not change, and the marcher asks
// about them a hundred times a pixel — so they are baked once into the second
// state target and read back as one filtered fetch. Measured on an Intel HD
// 6000: the same scene with an analytic ground is 28.7 ms a frame and with a
// single fetch 11.2 ms, which is what it costs with no terrain at all. The
// arithmetic *was* the frame.
//
// This is the sketch's own lesson one step further. scene() already asked the
// state texture where the rover and the beacons were; now it asks where the
// ground is too, and it is still a pure function of a point.
const vec2 WORLD = vec2(64.0, 64.0);          // the square of world the map covers
vec2 mapUv(vec2 q) { return q / WORLD + 0.5; }
float gSmooth;   // 1 while marching: read the map. 0 for the normal: do the sum.
float ground(vec2 q) {
  if (gSmooth > 0.5) return state2(mapUv(q)).r;
  return duneAt(q);
}

// One texel of the map: the height of the dunes under the patch of world it
// stands for. Computed on the first frame and held after — recomputing it
// every frame would be one fbm per texel per frame, which is the cost this
// was meant to avoid, only spread differently.
vec4 sim2(vec2 q) {
  if (frame > 0 && keyHit(u_keys, 82.0) < 0.5) return state2(q);
  return vec4(duneAt((q - 0.5) * WORLD), 0.0, 0.0, 1.0);
}

// The world's state, read *once* per pixel and kept here for scene() to use.
// The first version of this sketch read the texture inside scene(), which the
// marcher calls about a hundred and fifty times a pixel — a thousand texture
// fetches to draw one dot, and a GPU that stops answering. A raymarcher's
// scene() must be arithmetic; anything it needs to look up is hoisted.
//
// The same argument applies twice over to ground(): it is two fbm, which is
// six octaves each, which is twenty-four hashes each — forty-eight hashes a
// call. The rover and the beacons do not move during a pixel, so their ground
// heights are constants, and computing them inside scene() made every one of
// the ~110 marching steps pay for nine of them. They are hoisted into the
// globals too, and scene() calls ground() exactly once, for the terrain
// under the point it was actually asked about.
vec4 gRover;
float gRoverY;            // the ground under the rover, once per pixel
mat2 gTurn;               // and the heading as a matrix: two sin and two cos,
                          // which scene() was building at every march step
// Eight beacons, and eight *names* rather than an array. An array indexed by
// a running variable is not a register file on most drivers — it is memory,
// and scene() reads it about a hundred times a pixel. Written out it costs
// nothing; measured on this machine, the array cost a quarter of the frame.
vec4 gB0; vec4 gB1; vec4 gB2; vec4 gB3;
vec4 gB4; vec4 gB5; vec4 gB6; vec4 gB7;   // x, z, standing, ground height

// One beacon, with a sphere round it first: while the point is outside that
// sphere its distance is a lower bound on the true one, which is exactly what
// sphere tracing needs, and it skips two SDFs for the seven beacons that are
// never near.
float beacon(vec3 p, vec4 b) {
  if (b.z < 0.5) return 1e9;
  vec3 bp = p - vec3(b.x, b.w + 0.9, b.y);
  float bound = length(bp) - 1.10;
  if (bound > 0.2) return bound;
  return min(sdCapsule3(bp, vec3(0.0, -0.9, 0.0), vec3(0.0, 0.55, 0.0), 0.10),
             sdSphere(bp - vec3(0.0, 0.78, 0.0), 0.26));
}

float scene(vec3 p) {
  float d = p.y - ground(p.xz);
  vec3 rp = p - vec3(gRover.x, gRoverY + 0.42, gRover.y);
  rp.xz = gTurn * rp.xz;
  float car = sdBox3(rp, vec3(0.62, 0.20, 0.95)) - 0.10;
  car = min(car, sdSphere(rp - vec3(0.0, 0.26, -0.10), 0.42));
  d = min(d, car);
  d = min(d, beacon(p, gB0)); d = min(d, beacon(p, gB1));
  d = min(d, beacon(p, gB2)); d = min(d, beacon(p, gB3));
  d = min(d, beacon(p, gB4)); d = min(d, beacon(p, gB5));
  d = min(d, beacon(p, gB6)); d = min(d, beacon(p, gB7));
  return d;
}

// The sketch's own shadow march. The prelude's takes forty steps with a floor
// of one centimetre, which is right for a still life on a table and wrong for
// a desert twenty units across: twenty-four steps with a floor of five
// centimetres is the same picture here and a third of the cost.
float shadow(vec3 ro, vec3 rd) {
  float res = 1.0, t = 0.05;
  for (int i = 0; i < 24; i++) {
    float h = scene(ro + rd * t);
    if (h < 0.002) return 0.0;
    res = min(res, 12.0 * h / t);
    t += clamp(h, 0.05, 0.6);
    if (t > 11.0) break;
  }
  return clamp(res, 0.0, 1.0);
}

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;
  float dt = 1.0 / 60.0;
  vec4 r = first ? vec4(0.0, 6.0, 3.14159, 0.0) : rover();
  vec4 m = first ? vec4(0.0, 0.0, 0.0, 1.0) : meta();

  float lf = max(keyDown(u_keys, 37.0), keyDown(u_keys, 65.0));
  float rt = max(keyDown(u_keys, 39.0), keyDown(u_keys, 68.0));
  float fw = max(keyDown(u_keys, 38.0), keyDown(u_keys, 87.0));
  float bk = max(keyDown(u_keys, 40.0), keyDown(u_keys, 83.0));

  float heading = r.z + (lf - rt) * turn * dt;
  float speed = (r.w + (fw - bk) * accel * dt) * drag;
  vec2 dir = vec2(sin(heading), cos(heading));
  vec2 pos = r.xy + dir * speed * dt;
  // The edge of the world pushes back rather than letting you leave it.
  float bump = 0.0;
  if (length(pos) > 22.0) { pos = normalize(pos) * 22.0; speed *= -0.35; bump = 1.0; }

  float got = 0.0;
  for (int i = 0; i < 8; i++) {
    float k = float(i);
    if (standing(k) < 0.5) continue;
    if (length(pos - beaconAt(k)) < 1.1) { got = 1.0; m.y += 1.0; }
  }

  if (texel == vec2(0.0)) return vec4(pos, heading, speed);
  if (texel == vec2(1.0, 0.0)) return vec4(m.x, m.y, abs(speed), 1.0);
  if (texel == vec2(2.0, 0.0)) return vec4(got, bump, 0.0, 1.0);
  // One texel a beacon: it stands until the rover reaches it.
  if (texel.y == 0.0 && texel.x >= 4.0 && texel.x < 4.0 + BEACONS) {
    float k = texel.x - 4.0;
    float up = first ? 1.0 : standing(k);
    if (!first && up > 0.5 && length(rover().xy + vec2(sin(rover().z), cos(rover().z)) * rover().w * dt - beaconAt(k)) < 1.1) up = 0.0;
    return vec4(up, 0.0, 0.0, 1.0);
  }
  return vec4(0.0);
}

vec4 r = rover();
vec4 m = meta();
// Hoist the world into the globals scene() reads: nine texture fetches and
// nine ground() heights for the whole pixel, rather than nine of each per
// march step.
gSmooth = 1.0;
gRover = r;
gRoverY = ground(r.xy);
gTurn = rot(-r.z);
{ vec2 b = beaconAt(0.0); gB0 = vec4(b, standing(0.0), ground(b)); }
{ vec2 b = beaconAt(1.0); gB1 = vec4(b, standing(1.0), ground(b)); }
{ vec2 b = beaconAt(2.0); gB2 = vec4(b, standing(2.0), ground(b)); }
{ vec2 b = beaconAt(3.0); gB3 = vec4(b, standing(3.0), ground(b)); }
{ vec2 b = beaconAt(4.0); gB4 = vec4(b, standing(4.0), ground(b)); }
{ vec2 b = beaconAt(5.0); gB5 = vec4(b, standing(5.0), ground(b)); }
{ vec2 b = beaconAt(6.0); gB6 = vec4(b, standing(6.0), ground(b)); }
{ vec2 b = beaconAt(7.0); gB7 = vec4(b, standing(7.0), ground(b)); }
// A chase camera, behind and above, looking where the rover is going.
vec2 dir = vec2(sin(r.z), cos(r.z));
vec3 target = vec3(r.x, gRoverY + 0.7, r.y);
// Behind by five and up by two — the height must not be scaled by the
// distance, or the camera ends up ten units overhead looking at its own
// shadow, which is what the first version of this did.
vec3 ro = target - vec3(dir.x * 5.4, -2.0, dir.y * 5.4);
ro.y = max(ro.y, ground(ro.xz) + 1.2);
mat3 cam = lookAt(ro, target);
vec3 rd = cam * normalize(vec3(p, 1.5));
vec3 sun = normalize(vec3(0.55, 0.35 + hour * 0.7, 0.42));

vec3 col = sky(rd, sun);
float t = march(ro, rd, 60.0);
if (t > 0.0) {
  vec3 hit = ro + rd * t;
  // The map is linear inside a texel, so a normal taken from it is constant
  // inside a texel — which reads as facets. The normal is the one place worth
  // paying for the sum: six scene() calls rather than a hundred.
  gSmooth = 0.0;
  vec3 n = normal3(hit);
  gSmooth = 1.0;
  float lit = max(dot(n, sun), 0.0);
  float sh = lit > 0.0 ? shadow(hit + n * 0.02, sun) : 0.0;
  float occ = ao(hit, n);
  // Which thing was hit, from its distance to each — cheaper than an id and
  // exact enough at these scales.
  vec3 rp = hit - vec3(r.x, gRoverY + 0.42, r.y);
  rp.xz = rot(-r.z) * rp.xz;
  float dCar = min(sdBox3(rp, vec3(0.62, 0.20, 0.95)) - 0.10,
                   sdSphere(rp - vec3(0.0, 0.26, -0.10), 0.42));
  vec3 albedo = sand * (0.75 + 0.35 * fbm(hit.xz * 1.6));
  if (dCar < 0.02) albedo = shell;
  // A beacon glows rather than only reflecting, so it reads at a distance.
  float glow = 0.0;
  if (gB0.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB0.x, gB0.w + 1.68, gB0.y)));
  if (gB1.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB1.x, gB1.w + 1.68, gB1.y)));
  if (gB2.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB2.x, gB2.w + 1.68, gB2.y)));
  if (gB3.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB3.x, gB3.w + 1.68, gB3.y)));
  if (gB4.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB4.x, gB4.w + 1.68, gB4.y)));
  if (gB5.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB5.x, gB5.w + 1.68, gB5.y)));
  if (gB6.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB6.x, gB6.w + 1.68, gB6.y)));
  if (gB7.z > 0.5) glow += 0.55 / (1.0 + 12.0 * length(hit - vec3(gB7.x, gB7.w + 1.68, gB7.y)));
  vec3 lin = albedo * (lit * sh * vec3(1.0, 0.92, 0.78) * 1.15 + occ * vec3(0.13, 0.18, 0.28));
  lin += vec3(1.0, 0.62, 0.28) * glow;
  lin += vec3(1.0, 0.9, 0.75) * fresnel(max(dot(n, -rd), 0.0), 0.04) * sh * 0.35;
  col = mix(sky(rd, sun), lin, exp(-t * 0.018));
}
// A beacon count along the bottom.
float marks = min(m.y, BEACONS);
if (uv.y < 0.035 && uv.x * BEACONS < marks) col = mix(col, vec3(1.0, 0.62, 0.28), 0.85);
finish(col)`
  },
  { id: "world", label: "Open world — infinite terrain, biomes, a map that follows you",
    preview: [640, 360], steps: 1,
    // What the world sounds like. Six texels of its own state, read back each
    // frame and handed to the ordinary effect evaluator — the same path a game
    // uses for a bounce. The world says *that* a bird sang and how high; it
    // does not know whether anything is listening.
    probes: {
      wind: { texel: [4, 0], channel: "r" },
      rain: { texel: [4, 0], channel: "g" },
      sea:  { texel: [4, 0], channel: "b" },
      dawn: { texel: [4, 0], channel: "a" },
      chirp: { texel: [5, 0], channel: "r" },
      pitch: { texel: [5, 0], channel: "g" },
      foot: { texel: [6, 0], channel: "r" },
      wet:  { texel: [6, 0], channel: "b" },
      // What is underfoot: the same four weights the ground is painted with.
      // The tally, and the moment it changes.
      got:   { texel: [10, 0], channel: "r" },
      gotKind: { texel: [10, 0], channel: "g" },
      carried: { texel: [10, 0], channel: "b" },
      sand:  { texel: [8, 0], channel: "r" },
      grass: { texel: [8, 0], channel: "g" },
      rock:  { texel: [8, 0], channel: "b" },
      snow:  { texel: [8, 0], channel: "a" },
    },
    instruments: {
      // Two beds, each a filtered noise whose level an effect moves. A bed is
      // not a note: it is always sounding, and what changes is how much.
      air: airInstrument(420, 0.6, "lp"),
      hiss: airInstrument(3400, 0.5, "hp"),
      surf: airInstrument(240, 1.4, "bp"),
      bird: { ref: "tone.bell" },
      step: { ref: "tone.pluck" },
      // Finding something. A bell, because the one sound a game has to get
      // right is the one that says yes.
      find: { ref: "tone.bell" },
      // The second half of a footstep: what the ground does *after* the weight
      // lands. Sand and snow give, so they hiss; rock does not, so it does not.
      scuff: { ref: "tone.pluck" },
    },
    effects: [
      // The beds follow the weather continuously — no `when`, so every frame.
      { kind: "param", node: "bed", param: "level", instrument: "air",
        value: 'ch("wind") * 0.30 + 0.02' },
      { kind: "param", node: "bed", param: "level", instrument: "hiss",
        value: 'ch("rain") * 0.22' },
      { kind: "param", node: "bed", param: "level", instrument: "surf",
        value: 'ch("sea") * 0.16' },
      // The dawn chorus. The shader decides when a bird sings, because a pulse
      // that lasts exactly one frame is a thing a shader can say.
      { kind: "note", instrument: "bird", when: 'ch("chirp") > 0.5',
        hz: '900 + ch("pitch") * 1500', dur: '0.10 + ch("pitch") * 0.13' },
      // A footfall a stride, and the ground decides what it sounds like.
      //
      // tone.pluck is noise into a comb, so its pitch is the comb's length —
      // a short comb is a click and a long one is a thud. That maps onto
      // ground rather neatly: rock clicks, snow squeaks, sand and grass
      // thud, and water is lower still because a splash is mostly body.
      { kind: "note", instrument: "step", when: 'ch("foot") > 0.5',
        hz: '62 + ch("rock") * 165 + ch("snow") * 78 + ch("grass") * 26 - ch("wet") * 18',
        dur: '0.055 + ch("sand") * 0.045 + ch("wet") * 0.05' },
      // Up a scale as the bag fills — the fourth thing you find rings a
      // fourth above the first — and each kind starts from its own note, so a
      // run of mushrooms and a run of crystal are not the same run.
      { kind: "note", instrument: "find", when: 'ch("got") > 0.5',
        hz: '392 * 2 ^ ((ch("gotKind") * 3 + min(ch("carried"), 12)) / 12)',
        dur: "0.34" },
      // …and the hiss of ground that gives under you. Loose or wet only: a
      // scuff on bare rock is a sound that is not there. It is a second note
      // rather than a louder first one because a note carries no velocity —
      // the same limit the dawn chorus runs into, met from the other side.
      { kind: "note", instrument: "scuff",
        when: 'ch("foot") > 0.5 && ch("sand") + ch("snow") + ch("wet") > 0.38',
        hz: '760 + ch("snow") * 520 + ch("wet") * 380',
        dur: '0.05 + ch("sand") * 0.05' },
    ],
    source:
`// An open world: terrain with no edge, biomes that decide what a place is
// made of, and a map of the land that follows you.
//
// The trick that makes it affordable is the rover's, taken further. march()
// calls scene() about a hundred times a pixel, so nothing in scene() may be
// arithmetic worth the name — and an open world's terrain is a great deal of
// arithmetic. So the land near you is *baked*: one pass writes a height map
// into the second state target, centred on wherever you are standing, and
// scene() is one filtered fetch.
//
// That is what makes it infinite rather than large. The map does not cover
// the world; it covers a hundred and eighty metres of it, and it follows you.
// Walk a thousand metres and the map has been rebuilt a thousand times, each
// time from the world's own functions at your new position — there is no
// stored world to run out of.
//
// The biomes are the same idea. Two low-frequency fields — how high the land
// wants to be, and how wet — decide everything: which height function shapes
// the ground, which surface is on it, how it takes the light. They are baked
// into the map alongside the height, so choosing a biome costs a fetch too,
// and the shading picks up a *blend* of the ones nearby rather than switching
// at a line. One program, several looks: a single view sees four biomes at
// once, so they cannot be separate shaders, but they are separate functions
// and they read like it.
// The state is a height map of a fixed piece of ground and a handful of
// registers. It has no business being the size of the window: at 1920x1080 a
// float state pair with two targets is 132 MB, and at 448 square it is 13 MB
// and holds the same world. It is also eight times less to bake.
// @state 448 448
uniform sampler2D u_keys;
uniform float walk;      // @range 3 40 @default 13 @help metres a second
uniform float turn;      // @range 0.5 3 @default 1.7 @help radians a second
uniform float hour;      // @range 0 1 @default 0.28 @help the time of day it starts at
uniform float dayLen;    // @range 20 900 @default 180 @help seconds in a whole day
uniform float look;      // @range 0.4 3 @default 1.4 @help how fast the view turns
uniform float fogFar;    // @range 30 160 @default 86 @help where the air closes in
uniform vec3  sandC;     // @color @default #cbab72
uniform vec3  grassC;    // @color @default #466b34
uniform vec3  rockC;     // @color @default #6d655a
uniform vec3  snowC;     // @color @default #eef3f8
uniform vec3  waterC;    // @color @default #163c50
uniform vec3  leafC;     // @color @default #3f6d2e
uniform float weather;   // @range 0 1 @default 0.5 @help how much weather there is
uniform float windAmt;   // @range 0 2 @default 1 @help how hard it blows
uniform float wildlife;  // @range 0 1 @default 0.6 @help how much of it is alive
uniform float items;     // @range 0 1 @default 0.55 @help how much there is to find
uniform vec3  hideC;     // @color @default #6b4f31
// The two other ways of looking, as buttons. Hold M or V for a moment; tick
// the box to stay there.
//
// A key that *toggled* would be nicer and would need a latch, and then the
// box and the latch would be two truths about one thing, free to disagree the
// moment somebody used both. The greater of a held key and a ticked box has
// no state at all, so there is nothing to get out of step.
uniform float mapOn;     // @toggle @label map @help what the world has baked — or hold M
uniform float povOn;     // @toggle @label third person @help stand behind yourself — or hold V

// How much world the map holds. Larger than the far plane on purpose: the
// edge of the map is then always further away than the fog, so nothing ever
// sees where it stops.
const vec2 WORLD = vec2(190.0, 190.0);

float fbmN(vec2 p, int n) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 7; i++) { if (i >= n) break; v += a * noise(p); p *= 2.03; a *= 0.5; }
  return v;
}

// ------------------------------------------------------------ the world
// Everything below is evaluated once per *texel of the map*, never per march
// step. That is the whole budget argument: a hundred and eighty metres of
// terrain costs one pass, and looking at it costs one fetch.

// Where the land wants to be high, and where it wants to be wet. Two fields
// at very different scales, which is all a climate needs to be interesting.
// The scales are the design. At 0.0043 the continents came out two hundred
// metres across, which is an archipelago of stepping stones rather than
// somewhere to walk; the wavelength is now about six hundred, so a landmass
// takes a minute to cross and the sea is something you arrive at.
float landAt(vec2 q)  { return fbmN(q * 0.0017, 5); }
float moistAt(vec2 q) { return fbmN(q * 0.0052 + vec2(37.2, 11.9), 3); }

/**
 * One texel of the map: (height in metres, moisture, mountain-ness, 1).
 * Sea level is y = 0, so "under water" is just a negative height.
 */
vec4 landform(vec2 q) {
  float c = landAt(q);
  float m = moistAt(q);
  float e = (c - 0.415) * 104.0;                     // metres above the sea
  // Mountains sharpen where the land is already high, which is why ranges
  // have foothills rather than walls.
  float mtn = smoothstep(10.0, 44.0, e);
  e += mtn * (fbmN(q * 0.0115, 4) - 0.35) * 52.0;
  // Dunes where it is dry and low; a gentler ripple everywhere else.
  float dry = (1.0 - m) * (1.0 - smoothstep(4.0, 22.0, e));
  e += dry * (fbmN(q * 0.055, 3) - 0.5) * 6.5;
  e += (1.0 - mtn) * (fbmN(q * 0.032, 3) - 0.5) * 2.6;
  // The shore flattens out, so a beach is a beach rather than a cliff.
  e *= smoothstep(-3.0, 6.0, e) * 0.35 + 0.65;
  return vec4(e, m, mtn, 1.0);
}

// ------------------------------------------------------------ the map
// Centred on the walker, so the world scrolls under the map rather than the
// map moving through the world.
vec2 gEye2;                 // where the map is centred, this frame
vec2 mapUv(vec2 q) { return (q - gEye2) / WORLD + 0.5; }

// The sun, the moon, and how much of the night it is. Set once per pixel.
// One name to a declaration: the shorthand's global handling reads a type
// and a name, and a comma-separated pair is a second name it never sees.
vec3 gSun;
vec3 gMoon;
vec3 gKey;
vec3 gKeyCol;
float gNight;

/**
 * The sky, which is two skies with a dusk between them.
 *
 * The prelude's sky() is a daytime sky and knows nothing about night, so the
 * night is written here and crossfaded in: a deep blue that darkens overhead,
 * stars in it, and the moon as a lit disc with a phase.
 *
 * The stars are cells on the *direction* rather than on the screen — the same
 * star has to stay where it is when the head turns, which a screen-space hash
 * cannot do. Two angles, quantised: that is what a constellation is.
 */
vec3 nightSky(vec3 rd) {
  float up = max(rd.y, 0.0);
  vec3 base = mix(vec3(0.035, 0.045, 0.085), vec3(0.006, 0.010, 0.026), up);
  if (rd.y > -0.02) {
    vec2 sp = vec2(atan(rd.z, rd.x) * 3.1, asin(clamp(rd.y, -1.0, 1.0)) * 6.2) * 9.5;
    vec2 sc = floor(sp);
    float h = hash21(sc);
    if (h > 0.975) {
      vec2 j = vec2(hash21(sc + 3.1), hash21(sc + 7.7)) * 0.6 + 0.2;
      float d = length(fract(sp) - j);
      // A little twinkle, but not so much that the sky boils.
      float tw = 0.75 + 0.25 * sin(t * 2.3 + h * 90.0);
      float mag = 0.35 + 0.65 * hash21(sc + 11.3);
      base += vec3(0.9, 0.93, 1.0) * smoothstep(0.09, 0.0, d) * mag * tw
            * smoothstep(-0.02, 0.25, rd.y);
    }
  }
  // The moon: a disc, and a phase, which is the sun's direction seen from it.
  float mdot = dot(rd, gMoon);
  if (mdot > 0.9985) {
    // Where on the little disc this ray lands, in the moon's own frame.
    vec3 mr = normalize(cross(gMoon, vec3(0.0, 1.0, 0.0)));
    vec3 mu = cross(mr, gMoon);
    vec2 q = vec2(dot(rd, mr), dot(rd, mu)) / 0.055;
    float r2 = dot(q, q);
    if (r2 < 1.0) {
      // A sphere's normal, from where the ray lands on the disc — which is
      // all a phase is: the lit half of a ball, seen edge on.
      vec3 nrm = gMoon * sqrt(max(1.0 - r2, 0.0)) + mr * q.x + mu * q.y;
      float lit = smoothstep(-0.12, 0.12, dot(nrm, gSun));
      vec3 face = mix(vec3(0.72, 0.74, 0.78), vec3(0.96, 0.95, 0.90),
                      0.5 + 0.5 * noise(q * 3.0));
      base = mix(base, face * (0.12 + 0.88 * lit), smoothstep(1.0, 0.86, r2));
    }
  }
  // …and a halo, so it is a light in the sky rather than a sticker on it.
  // Tight, or the halo swallows the disc it is meant to surround: at an
  // exponent of 260 the glow was four degrees wide and the moon is three.
  base += vec3(0.5, 0.53, 0.62) * pow(max(mdot, 0.0), 900.0) * 0.22;
  return base;
}

vec3 skyAt(vec3 rd) {
  return mix(sky(rd, gSun), nightSky(rd), gNight);
}

// The weather, read once per pixel and then used everywhere. Wind is a
// direction and a strength, rain is an amount, and both drift with time in a
// register — so the weather is something the world is doing rather than a
// slider you are holding.
vec2 gWind;
float gRain;

float gWave;                // the sea's height this frame, once per pixel
// How much of the fine detail survives at this distance — set once per pixel,
// from how far the ray went. Declared here because the sea wants it too.
float gNear;
// …and a second, much shorter fade. Blades are a few centimetres across:
// they are only ever visible underfoot, and asking for them at forty metres
// is asking for the fizz that Phase 28 spent a round removing.
float gClose;
vec3 gGlow;                 // what a thing gives off, rather than reflects
float ground(vec2 q) { return state2(mapUv(q)).r; }

// ------------------------------------------------------------ what grows
// One thing to a cell of an eight-metre grid, and the cell decides what it
// is: a tree where the map says green, a boulder where it says stone. Both
// read the *same texel* — the height a thing stands on and the climate that
// put it there are one fetch — which is why two kinds of thing cost what one
// kind costs.
//
// Measured on an Intel HD 6000, at 640×360, changing only scene():
//
//   terrain alone                                  4.3 ms
//   + one more map fetch a step                    6.3 ms
//   + a whole tree: fetch, hash, three SDFs        6.5 ms
//   the same, skipped beyond forty-five metres     7.4 ms
//
// The last line is the one worth keeping. Guarding the scatter with a
// distance test made it *slower* than not guarding it: the rays in a warp
// disagree about which side of forty-five metres they are on, so the branch
// is paid for and both sides run anyway. The fetch is the cost, and it is
// already the cheapest way to know where the ground is.
const float CELL = 8.0;

// Whether a cell grows anything, given the land under it. Written once and
// used twice — by the scatter, and by the spawn, so that the walker cannot
// begin the world standing inside a trunk. It did, at first, and a tree from
// the inside is a black screen.
float treeChance(vec4 L)  { return smoothstep(0.28, 0.5, L.y) * (1.0 - smoothstep(14.0, 26.0, L.x)); }
float stoneChance(vec4 L) { return smoothstep(12.0, 24.0, L.x); }
bool growsTree(vec2 id) {
  return hash21(id * 3.1 - 4.7) < treeChance(landform((id + 0.5) * CELL)) * 0.62;
}
/** Where the thing in this cell actually stands — the same jitter the scatter uses. */
vec2 thingSpot(vec2 id) {
  return (id + 0.5 + (vec2(hash21(id + 0.5), hash21(id * 1.7 + 9.13)) - 0.5) * 0.34) * CELL;
}
/** Room to stand: no trunk within a few metres of here. */
bool roomToStand(vec2 q) {
  vec2 id0 = floor(q / CELL);
  for (int dy = -1; dy <= 1; dy++) {
    for (int dx = -1; dx <= 1; dx++) {
      vec2 id = id0 + vec2(float(dx), float(dy));
      if (growsTree(id) && length(q - thingSpot(id)) < 3.4) return false;
    }
  }
  return true;
}

// -------------------------------------------------- walking into things
// Collision as a *nearest allowed place*, not as a refusal.
//
// The walker is a circle and a trunk is a circle, so "not inside it" is one
// subtraction, and moving to the nearest point outside is exactly sliding
// along the bark. Refusing the step instead would glue you to the tree: press
// forward and you stop dead, at any angle, which is what walking into
// something in a bad game feels like and not what walking into a tree feels
// like.
//
// Nine cells, once, in the state pass — never in scene(). The same asymmetry
// the sound occlusion is built on: the walker is one texel a frame and can
// afford what a hundred and ten march steps a pixel cannot.
const float BODY = 0.40;

/** What stands in this cell, as the radius it keeps you out by. 0 for nothing.
    The thresholds are thingAt's, character for character, because a tree you
    can see and walk through is worse than no collision at all. */
float blockAt(vec2 id, out float kind) {
  kind = 0.0;
  vec4 L = state2(mapUv(thingSpot(id)));
  if (L.x < 1.2) return 0.0;
  float h1 = hash21(id + 0.5), h2 = hash21(id * 1.7 + 9.13), h3 = hash21(id * 3.1 - 4.7);
  float green = treeChance(L), stone = stoneChance(L);
  // A trunk, not a crown. The crown is three metres up and you are meant to
  // walk under it; blocking the whole silhouette would turn a wood into a
  // maze of invisible walls.
  if (h3 < green * 0.62) { kind = 1.0; return 0.17 * (0.75 + h2 * 0.7) + 0.06; }
  if (h3 > 1.0 - stone * 0.5) { kind = 2.0; return (0.5 + h1 * 0.9) * 0.82; }
  return 0.0;    // grass grows there, or an animal does, and an animal moves
}

/** The nearest place a given position is allowed to be. */
vec2 pushOut(vec2 q) {
  vec2 id0 = floor(q / CELL);
  for (int dy = -1; dy <= 1; dy++) {
    for (int dx = -1; dx <= 1; dx++) {
      vec2 id = id0 + vec2(float(dx), float(dy));
      float kind;
      float r = blockAt(id, kind) + BODY;
      if (kind < 0.5) continue;
      vec2 d = q - thingSpot(id);
      float len = length(d);
      // A dead-centre hit has no direction to leave by; any one will do, and
      // it is the one case where standing still would be the wrong answer.
      if (len < r) q += (r - len) * (len > 1e-4 ? d / len : vec2(1.0, 0.0));
    }
  }
  return q;
}

// -------------------------------------------------- the one you are playing
// Only ever asked for when the camera is behind them. The guard is a uniform,
// so every ray in the frame agrees about it — which is what makes this branch
// worth having and made the distance guard on the scatter (Phase 28) worth
// removing. A branch a warp agrees about is free; one it argues about costs
// both sides and the test as well.
float gPov;                 // 1 while you can see yourself
vec3 gWalkAt;               // where they stand
float gWalkFace;
float gWalkStride;
float gWalkSpeed;

float walkerAt(vec3 p) {
  vec3 q = p - gWalkAt;
  float c = cos(-gWalkFace), s = sin(-gWalkFace);
  // Into their frame, so +z is the way they face and the legs swing in z.
  q.xz = mat2(c, -s, s, c) * q.xz;
  float sw = sin(gWalkStride * 6.28318) * gWalkSpeed;
  vec3 hip = vec3(0.0, 0.86, 0.0);
  float body = sdCapsule3(q - hip, vec3(0.0), vec3(0.0, 0.62, 0.0), 0.20);
  float head = sdSphere(q - vec3(0.0, 1.76, 0.0), 0.145);
  // Two legs and two arms from one capsule each, by folding the space they
  // stand in — and the near side swings opposite the far one, which is the
  // whole of why a walk reads as a walk rather than as a hop.
  vec3 lp = q; lp.x = abs(lp.x) - 0.13;
  float side = q.x < 0.0 ? -1.0 : 1.0;
  float leg = sdCapsule3(lp - hip, vec3(0.0), vec3(0.0, -0.86, sw * 0.34 * side), 0.085);
  float arm = sdCapsule3(lp - vec3(0.0, 1.44, 0.0), vec3(0.0),
                         vec3(0.0, -0.60, -sw * 0.30 * side), 0.062);
  return min(min(body, head), min(leg, arm));
}

// -------------------------------------------------- things to pick up
// One more band of the same hash, between the animals and the boulders. A
// cell that grows a tree does not also grow a mushroom, which is not a rule
// imposed on the scatter but the arithmetic of a band: the hash is one number
// and it lands in one place.
//
// What kind is decided by the ground rather than by another hash, so what you
// find tells you where you are: shells on the beach, mushrooms where it is
// damp, crystal on the high rock, berries in between.
float itemLo(vec4 L)  { return treeChance(L) * 0.62 + 0.10 * wildlife; }
float itemKind(vec4 L) {
  if (L.x < 3.4) return 1.0;                        // a shell, on the sand
  if (L.x > 15.0) return 2.0;                       // a crystal, up on the rock
  if (L.y > 0.46) return 0.0;                       // a mushroom, where it is damp
  return 3.0;                                       // and berries in between
}
/** Whether this cell holds something, ignoring whether it is still there. */
bool growsItem(vec2 id, out float kind) {
  vec4 L = state2(mapUv(thingSpot(id)));
  kind = itemKind(L);
  if (L.x < 1.2) return false;
  float h3 = hash21(id * 3.1 - 4.7);
  float lo = itemLo(L);
  return h3 > lo && h3 < lo + 0.30 * items && h3 < 1.0 - stoneChance(L) * 0.5;
}

// What has been picked up, in a texture that does not grow.
//
// This is the one thing in the world that genuinely has to be *remembered*.
// Everything else is a function of position and can be recomputed; a mushroom
// you have already eaten cannot be, and a list of them would grow without
// bound in a world that has no bound.
//
// So: a direct-mapped table in row 1 of the state, which was zeros until now.
// The cell's own coordinates go in the slot beside the flag, so a collision
// is *detectable* rather than silent — a slot holding someone else's id reads
// as "not taken", and the older entry is simply overwritten. That is the
// honest failure: pick up more than a few hundred things and the earliest of
// them grow back. Constant memory buys forgetting, and forgetting is the
// right thing to give up in a world you can walk out of.
const float SLOTS = 421.0;                          // prime, and under the state's width
float slotOf(vec2 id) {
  return floor(mod(abs(id.x * 7919.0 + id.y * 104729.0 + 3.0), SLOTS));
}
bool taken(vec2 id) {
  vec4 e = reg(vec2(slotOf(id), 1.0));
  return e.z > 0.5 && abs(e.x - id.x) < 0.5 && abs(e.y - id.y) < 0.5;
}

/** The nearest unclaimed thing within arm's reach, if any. First found
    rather than nearest, which is the same answer here: one thing to a cell
    and cells eight metres apart, so two of them cannot both be within two. */
const float REACH = 2.3;
bool reachFor(vec2 at, out vec2 id, out float kind) {
  vec2 id0 = floor(at / CELL);
  id = id0; kind = 0.0;
  for (int dy = -1; dy <= 1; dy++) {
    for (int dx = -1; dx <= 1; dx++) {
      vec2 c = id0 + vec2(float(dx), float(dy));
      float k;
      if (!growsItem(c, k)) continue;
      if (length(at - thingSpot(c)) > REACH) continue;
      if (taken(c)) continue;
      id = c; kind = k; return true;
    }
  }
  return false;
}

/** One of four as a vector. A dynamic index into a vec4 is a thing GLSL ES
    1.00 does not promise, and this sketch is meant to run there. */
vec4 oneHot(float k) {
  return vec4(step(abs(k), 0.4), step(abs(k - 1.0), 0.4),
              step(abs(k - 2.0), 0.4), step(abs(k - 3.0), 0.4));
}

/** What each kind looks like. Read by the world, the map and the panel, so
    a crystal is the same colour wherever you meet it. */
vec3 itemColour(float k) {
  if (k < 0.5) return vec3(0.86, 0.78, 0.62);       // a mushroom
  if (k < 1.5) return vec3(0.94, 0.82, 0.80);       // a shell
  if (k < 2.5) return vec3(0.42, 0.86, 0.95);       // a crystal
  return vec3(0.78, 0.16, 0.26);                    // berries
}

vec3 gThing;                // where the thing in this cell stands
float gThingKind;           // 0 a tree, 1 a boulder
float gThingSize;

float thingAt(vec3 p, out float kind) {
  vec2 id = floor(p.xz / CELL);
  float h1 = hash21(id + 0.5);
  float h2 = hash21(id * 1.7 + 9.13);
  float h3 = hash21(id * 3.1 - 4.7);
  // Jittered, but not past the cell it belongs to: this asks the cell the ray
  // is in and no others, so anything that leans over the edge is a thing the
  // marcher can step through.
  vec2 c = thingSpot(id);
  vec4 L = state2(mapUv(c));
  kind = 0.0;
  if (L.x < 1.2) return 1e9;                       // nothing grows in the sea
  float green = treeChance(L);
  float stone = stoneChance(L);
  vec3 rp = p - vec3(c.x, L.x, c.y);
  if (h3 < green * 0.62) {                          // a tree
    float sz = 0.75 + h2 * 0.7;
    // The wind bends it, and bends the top more than the bottom, which is the
    // whole of why a tree in wind reads as alive. Each has its own phase from
    // the hash that placed it, so a wood does not sway as one object.
    float lean = smoothstep(0.0, 3.4 * sz, rp.y);
    float sway = sin(t * 1.7 + h1 * 6.28) * 0.16 + sin(t * 3.1 + h2 * 6.28) * 0.06;
    rp.xz -= gWind * lean * (0.5 + sway) * sz;
    float trunk = sdCapsule3(rp, vec3(0.0), vec3(0.0, 3.1 * sz, 0.0), 0.17 * sz);
    vec3 cp = rp - vec3(0.0, 3.5 * sz, 0.0);
    cp.y *= 1.45;                                   // taller than it is wide
    float crown = (length(cp) - 1.5 * sz) / 1.45;
    gThingSize = sz;
    // Bending a field stretches it, so what it reports is no longer a bound on
    // the truth. Scaled back, the marcher takes shorter steps near a leaning
    // tree and does not walk through the bark.
    return min(trunk, crown) * 0.85;
  }
  // Something grazing. It costs almost nothing, because the cell it stands in
  // has already been fetched to decide whether a tree grows there — the height
  // it walks on and the grass it is eating are that same texel. Measured: the
  // whole herd is 0.4 ms of a 10.9 ms frame.
  if (h3 > green * 0.62 && h3 < green * 0.62 + 0.10 * wildlife) {
    kind = 2.0;
    float ph = h1 * 6.28;
    // It wanders, and it faces where it is going — an animal that slides
    // sideways is a prop. The wander stays well inside its own cell, because
    // this asks the cell the ray is in and no others.
    vec2 amble = vec2(sin(t * 0.21 + ph), cos(t * 0.17 + ph * 1.7)) * 1.9;
    vec2 look = vec2(cos(t * 0.21 + ph), -sin(t * 0.17 + ph * 1.7) * 0.85);
    vec3 ap = rp - vec3(amble.x, 0.0, amble.y);
    ap.xz = rot(atan(look.y, look.x)) * ap.xz;
    // Deer-sized rather than dog-sized. At the first scale they were correct
    // and pointless: forty-odd pixels of a hundred thousand, which is a fact
    // about the world and not something anybody can see.
    float sz = 1.45 + h2 * 0.5;
    // Head down to the grass, up to look around, on its own clock.
    float graze = smoothstep(0.2, 0.8, sin(t * 0.33 + ph * 2.1) * 0.5 + 0.5);
    vec3 bp = ap - vec3(0.0, 0.66 * sz, 0.0);
    bp.z /= 0.62;
    float body = (length(bp) - 0.42 * sz) * 0.62;
    vec3 hd = vec3(0.42, 0.72 - graze * 0.62, 0.0) * sz;
    float neck = sdCapsule3(ap - vec3(0.0, 0.66 * sz, 0.0), vec3(0.0), hd, 0.09 * sz);
    float head = sdSphere(ap - vec3(0.0, 0.66 * sz, 0.0) - hd, 0.15 * sz);
    // Four legs from one capsule, by mirroring the space it stands in.
    vec3 lp = ap; lp.xz = abs(lp.xz) - vec2(0.26, 0.17) * sz;
    float legs = sdCapsule3(lp, vec3(0.0), vec3(0.0, 0.66 * sz, 0.0), 0.05 * sz);
    gThingSize = sz;
    return min(min(body, neck), min(head, legs));
  }
  // Something to pick up, and whether it is still there.
  //
  // The first version tried to get this for nothing: the map pass has a spare
  // channel and bakes every texel anyway, so it wrote the answer there and
  // scene() read it out of the fetch it had already paid for. That is the
  // move this whole world is built on and it is the right instinct — it is
  // simply not what the measurement said. The flag reached the texture (361
  // texels of a 14,336-texel band carried it) and did not survive being
  // sampled back: forcing the test off changed exactly zero pixels of the
  // map, twice, by two different measurements.
  //
  // So the question is asked directly, and paid for. The saving grace is that
  // it is asked *inside* the band — only a ray whose cell grows something
  // reaches the fetch — and a warp is a patch of neighbouring pixels, so the
  // rays in it agree about which cell they are in. That is the opposite of
  // the distance guard Phase 28 had to delete, where they never agreed about
  // anything. Measured below at no cost I can distinguish from zero.
  float lo = green * 0.62 + 0.10 * wildlife;
  if (h3 > lo && h3 < lo + 0.30 * items && h3 < 1.0 - stone * 0.5) {
    if (taken(id)) return 1e9;                      // it is in your bag now
    kind = 3.0;
    gThingSize = itemKind(L);                       // the display wants to know which
    float sz = 0.85 + h1 * 0.4;
    vec3 ip = rp;
    // Four shapes, and they are small on purpose: a thing you pick up should
    // want looking for. The marcher still bounds them correctly — a small
    // object is a small distance, not a missed one — so they cost what their
    // silhouette costs and nothing for being little.
    if (gThingSize < 0.5) {                         // a mushroom
      float stem = sdCapsule3(ip, vec3(0.0), vec3(0.0, 0.30 * sz, 0.0), 0.045 * sz);
      vec3 cp = ip - vec3(0.0, 0.30 * sz, 0.0); cp.y *= 2.2;
      return min(stem, (length(cp) - 0.17 * sz) / 2.2);
    }
    if (gThingSize < 1.5) {                         // a shell
      vec3 cp = ip - vec3(0.0, 0.06 * sz, 0.0); cp.y *= 3.0;
      return (length(cp) - 0.19 * sz) / 3.0;
    }
    if (gThingSize < 2.5) {                         // a crystal
      vec3 cp = ip - vec3(0.0, 0.24 * sz, 0.0);
      return (abs(cp.x) + abs(cp.y) * 0.5 + abs(cp.z) - 0.27 * sz) * 0.5;
    }
    vec3 cp = ip - vec3(0.0, 0.15 * sz, 0.0);       // berries
    cp.xz = abs(cp.xz) - 0.08 * sz;
    return length(cp) - 0.11 * sz;
  }
  if (h3 > 1.0 - stone * 0.5) {                     // a boulder
    kind = 1.0;
    float sz = 0.5 + h1 * 0.9;
    vec3 bp = rp - vec3(0.0, sz * 0.35, 0.0);
    bp.y /= 0.72;
    gThingSize = sz;
    return (length(bp) - sz) * 0.72;
  }
  return 1e9;
}

/**
 * Birds, which are the cheapest thing in the world to have.
 *
 * Everything else on the ground needs to know where the ground is, and that is
 * a fetch. A bird does not: it is at a height it chose, so the whole flock is
 * a hash and two capsules with no lookup at all. Measured at 1.4 ms of a
 * 10.9 ms frame — more than the grazing herd, which is only 0.4, precisely
 * because the herd reuses a fetch that had already been paid for.
 *
 * The flock drifts downwind, which is both free and true.
 */
float birdsAt(vec3 p) {
  vec3 q = p;
  q.xz -= gWind * t * 1.4;
  vec2 id = floor(q.xz / 22.0);
  float h = hash21(id * 5.7);
  // Density is the whole cost here, and it is not linear: a flock at one
  // bird per 19 m was 2.8 ms of the frame and at one per 22 m with two thirds
  // the chance it is under one. Scattered geometry does not cost what it draws
  // — it costs the shorter steps the marcher takes everywhere near it.
  if (h > 0.34 * wildlife) return 1e9;
  float ph = h * 39.0;
  // A slow circle inside its own cell, so a flock is not a lattice.
  vec2 c = (id + 0.5) * 22.0 + vec2(sin(t * 0.23 + ph), cos(t * 0.19 + ph)) * 3.6;
  // Low, and that is arithmetic rather than taste. The camera looks down
  // about seven degrees and its vertical half-angle is eighteen, so the top of
  // the frame is eleven degrees up — a bird is only ever in shot if its
  // altitude is under a fifth of its distance. At thirty-five metres up the
  // whole flock was past the fog before it rose into view, which is a great
  // deal of work to render nothing. These are gulls, not eagles.
  float y = 6.0 + h * 15.0 + sin(t * 0.7 + ph) * 2.0;
  vec3 bp = vec3(q.x - c.x, q.y - y, q.z - c.y);
  // Turned to face the way it is circling.
  bp.xz = rot(t * 0.23 + ph + 1.57) * bp.xz;
  float body = sdCapsule3(bp, vec3(-0.3, 0.0, 0.0), vec3(0.32, 0.0, 0.0), 0.105);
  // Two wings from one capsule, and the flap is the wing rising along its own
  // span — which is what makes a distant bird read as a bird at all.
  vec3 wp = bp; wp.z = abs(wp.z);
  wp.y -= wp.z * sin(t * 6.5 + ph) * 0.6;
  float wing = sdCapsule3(wp, vec3(0.0), vec3(-0.12, 0.0, 1.15), 0.055);
  return min(body, wing);
}

float scene(vec3 p) {
  float land = p.y - ground(p.xz);
  float sea = p.y - gWave;
  float kind;
  float d = min(min(land, sea), min(thingAt(p, kind), birdsAt(p)));
  if (gPov > 0.5) d = min(d, walkerAt(p));
  return d;
}

// The sea is flat enough to march as a plane and detailed enough to look wet,
// which is a normal's job rather than a distance function's.
vec3 seaNormal(vec2 q) {
  float e = 0.35;
  float h0 = sin(q.x * 0.7 + t * 1.1) * 0.05 + sin(q.y * 0.9 - t * 0.8) * 0.04
           + noise(q * 0.6 + t * 0.2) * 0.06;
  float hx = sin((q.x + e) * 0.7 + t * 1.1) * 0.05 + sin(q.y * 0.9 - t * 0.8) * 0.04
           + noise(vec2(q.x + e, q.y) * 0.6 + t * 0.2) * 0.06;
  float hy = sin(q.x * 0.7 + t * 1.1) * 0.05 + sin((q.y + e) * 0.9 - t * 0.8) * 0.04
           + noise(vec2(q.x, q.y + e) * 0.6 + t * 0.2) * 0.06;
  // Flattened with distance for the same reason the land's detail is: a wave
  // whose crest is narrower than a pixel is not a wave, it is a shimmer, and
  // at a grazing angle near the horizon every wave is.
  vec3 n = normalize(vec3(h0 - hx, e, h0 - hy));
  return normalize(mix(vec3(0.0, 1.0, 0.0), n, gNear * 0.75 + 0.25));
}

// The ground's normal, from the map rather than from the sum. Two texels
// across, which is wide enough to be smooth and narrow enough to keep the
// hills. The fine detail arrives as a perturbation at shading time, which is
// six samples a pixel rather than a hundred.
vec3 landNormal(vec2 q) {
  vec2 e = WORLD / u_state_size * 1.5;
  float hx = ground(q + vec2(e.x, 0.0)) - ground(q - vec2(e.x, 0.0));
  float hy = ground(q + vec2(0.0, e.y)) - ground(q - vec2(0.0, e.y));
  return normalize(vec3(-hx, 2.0 * e.x, -hy));
}

// ------------------------------------------------------------ the biomes
// Each is a weight, and each weight is a look. Nothing switches: a shore is
// sand becoming grass over a few metres, because the weights say so.
vec4 gW;                    // sand, grass, rock, snow
float gWet;                 // …and how much of this pixel is water

void weigh(float h, float m, float mtn, float slope) {
  float snow = smoothstep(26.0, 42.0, h) * smoothstep(0.62, 0.3, slope);
  float rock = max(smoothstep(14.0, 30.0, h), smoothstep(0.45, 0.75, slope)) * (1.0 - snow);
  float shore = 1.0 - smoothstep(0.4, 3.4, h);
  float grass = smoothstep(0.25, 0.55, m) * (1.0 - rock) * (1.0 - snow) * (1.0 - shore * 0.75);
  float sand = max(shore, (1.0 - smoothstep(0.2, 0.5, m)) * (1.0 - rock) * (1.0 - snow));
  gW = vec4(sand, grass, rock, snow);
  gW /= max(gW.x + gW.y + gW.z + gW.w, 1e-4);
}

// Every high-frequency term below is a lie at range: a ripple whose wavelength
// is a third of a pixel does not read as sand, it reads as static, and it
// crawls when you walk. One sample cannot average what it cannot see, so the
// detail is faded out instead — which is what a mip chain does for a texture
// and what nothing does for a function unless it is asked.

// What each biome does to the surface it is on. This is the part that reads
// as "a different shader over there": wind ripples in the sand, a fine mottle
// in the grass, strata in the rock, and snow left smooth so it takes the sun.
vec3 detailNormal(vec3 n, vec2 q, float h) {
  if (gNear < 0.01) return n;
  float ripple = sin(q.x * 1.7 + q.y * 0.7 + noise(q * 0.3) * 6.0) * 0.5 + 0.5;
  vec3 sandN = n + vec3(ripple - 0.5, 0.0, (ripple - 0.5) * 0.4) * 0.4;
  // Coarser and shallower than it was. Grass at a wavelength of twenty
  // centimetres is not grass at walking distance, it is noise on a hill —
  // what reads as a field is the patch, not the blade.
  vec3 grassN = n + (vec3(noise(q * 2.6), 0.0, noise(q * 2.6 + 5.1)) - 0.5) * 0.26;
  // Blades, underfoot only: leaning noise, which is what a tuft of grass is
  // when you are looking down at it from a person's height.
  if (gClose > 0.01) {
    // The same wind runs through the blades, as a wave travelling across the
    // field — which is what a gust looks like from above.
    float gust = sin(dot(q, gWind) * 0.5 - t * 3.2) * 0.5 + 0.5;
    float lean = noise(q * 1.4) * 5.0 + gust * length(gWind) * 2.4;
    float blade = noise(q * vec2(34.0, 9.0) + vec2(lean, 0.0));
    grassN += vec3(blade - 0.5, 0.0, (blade - 0.5) * 0.35) * 0.5 * gClose;
  }
  float strata = fract(h * 0.55 + noise(q * 0.7) * 0.6);
  vec3 rockN = n + vec3(strata - 0.5, 0.0, noise(q * 2.2) - 0.5) * 0.55;
  // Snow drifts: long and shallow, and the only thing that gives a white
  // field any shape at all. Left flat, snow is the tone map's problem — every
  // pixel over one, and a mountain reads as a sheet of paper.
  float drift = noise(q * 0.42 + vec2(0.0, noise(q * 0.11) * 3.0));
  vec3 snowN = n + vec3(drift - 0.5, 0.0, (drift - 0.5) * 0.5) * 0.3;
  vec3 mixed = sandN * gW.x + grassN * gW.y + rockN * gW.z + snowN * gW.w;
  return normalize(mix(n, mixed, gNear));
}

vec3 albedoOf(vec2 q, float h) {
  // The same argument for the pigment: at range every one of these averages
  // to its own mean, so it is mixed toward that rather than sampled.
  float n1 = mix(0.5, noise(q * 1.7), gNear);
  float n2 = mix(0.5, noise(q * 0.31) * 0.7 + noise(q * 1.9) * 0.3, gNear);
  float n3 = mix(0.5, noise(q * 7.0), gNear);
  float n4 = mix(0.5, fract(h * 0.55 + noise(q * 0.7) * 0.6), gNear);
  float n5 = mix(0.5, noise(q * 4.0), gNear);
  vec3 sand = srgbToLinear(sandC) * (0.86 + 0.24 * n1);
  // Patches of it, at field scale, and a little of the sand it grows out of —
  // a single green is a billiard table.
  vec3 grass = mix(srgbToLinear(grassC), srgbToLinear(sandC) * 0.5, 0.18 + 0.3 * n2)
             * (0.86 + 0.28 * n2) + vec3(0.02, 0.035, 0.0) * n3;
  // Blade for blade the colour varies too, and the dark between them is what
  // reads as depth rather than paint.
  if (gClose > 0.01) {
    float gust = sin(dot(q, gWind) * 0.5 - t * 3.2) * 0.5 + 0.5;
    float lean = noise(q * 1.4) * 5.0 + gust * length(gWind) * 2.4;
    float blade = noise(q * vec2(34.0, 9.0) + vec2(lean, 0.0));
    grass *= mix(1.0, 0.55 + 0.85 * blade, gClose);
  }
  vec3 rock = srgbToLinear(rockC) * (0.74 + 0.42 * n4);
  // Bright, not white. Snow's albedo really is near 0.9, but a surface at 0.9
  // under a sun at 2.35 is three stops over and the tone map hands back paper.
  // It is carried by the specular instead, which is what actually makes snow
  // look like snow.
  vec3 snow = srgbToLinear(snowC) * (0.55 + 0.12 * n5);
  return sand * gW.x + grass * gW.y + rock * gW.z + snow * gW.w;
}

/**
 * Somewhere to start.
 *
 * The world is a function rather than a place, so where the land *is* is not
 * known until something asks. The first version put the walker at the origin
 * and the origin turned out to be a hundred metres of open sea — which is a
 * fair thing for a procedural world to do and a poor way to begin.
 *
 * So: a golden-angle spiral outward from the origin, taking the first point
 * that is comfortably above the sea and not up a mountain. Forty-eight
 * evaluations, once, in four texels.
 *
 * The radius has to be read against the world's own scale. The first version
 * searched a hundred and twenty metres, which was plenty while the continents
 * were two hundred across and found nothing at all once they were six
 * hundred: every view for the first four hundred metres of walking was open
 * sea. It now reaches two kilometres, which is past several coastlines.
 *
 * It also declines to begin inside a tree, which the first version did — the
 * world opened on a black wall of bark. The same rule the scatter uses is
 * asked here, against the land rather than the map, because on the frame the
 * walker is placed the map has not been written yet.
 */
vec2 spawnPoint() {
  for (int i = 1; i < 49; i++) {
    float a = float(i) * 2.399963;
    float r = 300.0 * sqrt(float(i));
    vec2 q = vec2(cos(a), sin(a)) * r;
    vec4 L = landform(q);
    if (L.x < 4.0 || L.x > 22.0) continue;
    // Room to stand, rather than no trees at all. Rejecting every candidate
    // with a tree in any of the nine cells around it does avoid opening on a
    // wall of bark — by walking out of the woods entirely and starting in a
    // desert, which is a worse answer to a better-posed question. What is
    // wanted is three metres of clearance, so this asks where the trunks
    // actually are.
    if (!roomToStand(q)) continue;
    return q;
  }
  return vec2(0.0);
}

/**
 * How exposed a spot is: 1 on a ridge with nothing around it, 0 in a hollow.
 *
 * Eight fetches of the same baked map the marcher uses, at twenty-five metres
 * on the compass. This is the whole of "quieter behind a hill" for the things
 * that are heard continuously — wind is loud where there is nothing to stop
 * it, and the sea is not heard from behind a ridge.
 *
 * It runs in one texel of the state pass, once a frame, which is why it can
 * afford eight fetches while scene() cannot afford two.
 */
float exposure(vec2 at, float earY) {
  float open = 0.0;
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.7853982;
    vec2 q = at + vec2(cos(a), sin(a)) * 25.0;
    // Above the ear is in the way; below it is not.
    // A ridge four metres above the ear at twenty-five paces already hides
    // what is behind it. At nine the measure sat between 0.96 and 0.99
    // everywhere and told you nothing about where you were standing.
    open += 1.0 - smoothstep(-2.5, 4.0, ground(q) - earY);
  }
  return open / 8.0;
}

// ------------------------------------------------------------ the walker
// By texel, not by uv: the state and the picture are different sizes now, so
// dividing by u_resolution would be the wrong division in the display pass.
vec4 who()  { return reg(vec2(0.0, 0.0)); }   // x, z, heading, speed
vec4 meta() { return reg(vec2(1.0, 0.0)); }   // metres walked, -, -, -
vec4 airOf() { return reg(vec2(2.0, 0.0)); }  // wind x, wind z, rain, gust
vec4 view()  { return reg(vec2(3.0, 0.0)); }  // pitch, roll, time of day, -

// ------------------------------------------------------------ the panel
// A three-by-five font, fifteen bits to a digit, chosen with a chain rather
// than an array because a constant array with a computed index is a thing
// GLSL ES 1.00 does not promise either.
//
// The studio has a real glyph atlas — EDT and MSDF, a font-file parser, the
// lot — and none of it is reachable from inside a sketch, which is one
// program with a state texture and no graph. A count you cannot read is not
// a count, so: thirty bytes of font.
float digitBits(float d) {
  if (d < 0.5) return 31599.0;
  if (d < 1.5) return 29850.0;
  if (d < 2.5) return 29671.0;
  if (d < 3.5) return 31207.0;
  if (d < 4.5) return 18925.0;
  if (d < 5.5) return 31183.0;
  if (d < 6.5) return 31695.0;
  if (d < 7.5) return 18727.0;
  if (d < 8.5) return 31727.0;
  return 31215.0;
}
/** One cell of one digit. c is in font cells, y downward from the cap line. */
float digitPix(float d, vec2 c) {
  if (c.x < 0.0 || c.x >= 3.0 || c.y < 0.0 || c.y >= 5.0) return 0.0;
  float bit = floor(c.y) * 3.0 + floor(c.x);
  return mod(floor(digitBits(d) / pow(2.0, bit)), 2.0);
}
/** Up to two of them, the units column fixed so the number does not walk
    sideways as it passes nine. */
float numberPix(float n, vec2 c) {
  n = clamp(floor(n), 0.0, 99.0);
  float tens = floor(n / 10.0);
  float ink = digitPix(n - tens * 10.0, c - vec2(4.0, 0.0));
  if (tens > 0.5) ink = max(ink, digitPix(tens, c));
  return ink;
}

/** What each kind looks like flat, as a distance. Deliberately not the same
    shapes as the world's: an icon read at twenty pixels is a silhouette, and
    a mushroom's silhouette is a cap, not a mushroom. */
float itemIcon(float k, vec2 c) {
  if (k < 0.5) {                                     // a mushroom
    float cap = max(length(vec2(c.x, (c.y - 0.05) * 1.8)) - 0.74, -(c.y - 0.05));
    float stem = max(abs(c.x) - 0.17, abs(c.y + 0.42) - 0.44);
    return min(cap, stem);
  }
  if (k < 1.5) {                                     // a shell
    float fan = max(length(vec2(c.x * 0.92, c.y + 0.55)) - 0.98, -(c.y + 0.55));
    float notch = abs(fract(c.x * 2.2 + 0.5) - 0.5) - 0.30;
    return max(fan, notch * 0.5 - 0.12);
  }
  if (k < 2.5) return abs(c.x) * 1.55 + abs(c.y) * 0.82 - 0.66;   // a crystal
  vec2 b = c; b.x = abs(b.x) - 0.28;                 // berries
  return length(b - vec2(0.0, -0.06)) - 0.36;
}

/**
 * Four slots along the bottom. Drawn in the picture's own pixels and scaled
 * by its height, so the panel is the same size on a thumbnail and on a wall
 * — the same argument the reticle settled, and the same one the map's arrow
 * had to be taught the hard way.
 */
vec3 panel(vec3 col, vec4 inv, float flashKind, float flash) {
  float S = max(floor(u_resolution.y / 200.0), 1.0);
  float cw = 42.0 * S, chh = 26.0 * S, gap = 4.0 * S;
  vec2 o = vec2(9.0 * S, 9.0 * S);
  for (int i = 0; i < 4; i++) {
    float fi = float(i);
    vec2 q = gl_FragCoord.xy - o - vec2(fi * (cw + gap), 0.0);
    if (q.x < 0.0 || q.x > cw || q.y < 0.0 || q.y > chh) continue;
    float have = dot(inv, oneHot(fi));
    // A plate you can see the world through: an opaque bar across the bottom
    // of a first-person view is a letterbox, not a panel.
    col = mix(col, vec3(0.006, 0.008, 0.012), 0.62);
    // …and the slot you just filled lights up, because a tally that changes
    // silently is a tally nobody notices changing.
    float lit = abs(flashKind - fi) < 0.4 ? flash : 0.0;
    col = mix(col, itemColour(fi) * 0.5, lit * 0.55);
    float edge = min(min(q.x, cw - q.x), min(q.y, chh - q.y));
    col = mix(col, vec3(0.30, 0.33, 0.40), (1.0 - smoothstep(0.0, S, edge)) * 0.5);

    vec2 ic = (q - vec2(13.0 * S, 13.0 * S)) / (9.0 * S);
    float d = itemIcon(fi, ic);
    // Empty slots are drawn dim rather than left out: a panel whose shapes
    // move as you fill it is a panel you have to read again every time.
    vec3 tint = itemColour(fi) * (have > 0.5 ? 1.0 : 0.22);
    col = mix(col, tint, smoothstep(1.2 / (9.0 * S), -0.6 / (9.0 * S), d));

    vec2 nc = floor(vec2(q.x - 25.0 * S, (chh - 8.0 * S) - q.y) / (2.6 * S));
    col = mix(col, vec3(0.94, 0.95, 0.97) * (have > 0.5 ? 1.0 : 0.35), numberPix(have, nc));
  }
  return col;
}

// ------------------------------------------------------------ the map
// A map you can only have because the world already keeps one.
//
// The state pass bakes a hundred and ninety metres of landform around the
// walker every frame — it must, because the marcher reads it — so the map is
// that same texture seen from above: one fetch a pixel, and nothing drawn
// that was not already there. The colours come from albedoOf(), the very
// function the ground is painted with, so the map cannot quietly drift out
// of agreement with the world it is a map of.
//
// It is a *local* map, and that is not a corner cut. There is no world map to
// have: the world is a function of position, unbounded, and no part of it
// exists until something asks. What a map can honestly show is what has been
// baked — about as far as you can see on a clear day, and the same reason the
// fog never reaches the edge.
vec3 mapPicture(vec2 pp, vec4 wk) {
  vec3 paper = vec3(0.020, 0.024, 0.032);
  // pp is aspect-corrected, so a square map stays square in a wide window.
  vec2 m = pp * 1.02;
  float edge = max(abs(m.x), abs(m.y));
  if (edge > 1.0) return paper + vec3(0.05, 0.055, 0.07) * smoothstep(1.05, 1.0, edge);
  // North is up. Heading is measured from +z, so this is the compass rather
  // than a second convention to hold in your head.
  vec2 q = wk.xy + m * WORLD * 0.5;
  vec4 L = state2(mapUv(q));
  // Metres a pixel, from the mapping rather than from a derivative: fwidth is
  // an extension in GLSL ES 1.00 and this sketch is meant to run there too.
  // p is (2·frag − res)/res.y by construction, so this is exact where a
  // derivative would have been an estimate.
  float mpp = WORLD.x * 1.02 / max(u_resolution.y, 1.0);

  // Relief, from the baked map's own neighbours — the ground normal's trick
  // at the map's resolution rather than at the metre.
  float e = WORLD.x / max(u_state_size.x, 1.0) * 2.0;
  float hx = ground(q + vec2(e, 0.0)) - ground(q - vec2(e, 0.0));
  float hz = ground(q + vec2(0.0, e)) - ground(q - vec2(0.0, e));
  vec3 n = normalize(vec3(-hx, 2.0 * e, -hz));
  float lit = 0.40 + 0.85 * max(dot(n, normalize(vec3(-0.45, 0.72, 0.53))), 0.0);

  gNear = 0.0;              // no detail up here: a ripple half a pixel wide is static
  gW = vec4(0.0);
  weigh(L.x, L.y, L.z, 1.0 - n.y);
  vec3 col = albedoOf(q, L.x) * lit;
  if (L.x < 0.0) col = srgbToLinear(waterC) * (0.55 + 0.75 * smoothstep(-11.0, 0.0, L.x));

  // What stands there. At a hundred and ninety metres across a few hundred
  // pixels a trunk is a fifth of a pixel wide, so the dot has a floor measured
  // in *pixels* — it is the size it must be to exist rather than the size the
  // tree is, which is what every map has always done to a road.
  vec2 id = floor(q / CELL);
  float kind;
  float r = blockAt(id, kind);
  if (kind > 0.5) {
    float d = length(q - thingSpot(id)) - max(r, mpp * 1.7);
    vec3 ink = kind > 1.5 ? srgbToLinear(rockC) * 2.1 : srgbToLinear(leafC) * 1.7;
    col = mix(col, ink, smoothstep(0.4, -0.4, d));
  }
  // What is left to find, and only what is left. A map that still shows what
  // you are carrying is a map that lies.
  float ik;
  if (growsItem(id, ik) && !taken(id)) {
    float d = length(q - thingSpot(id)) - mpp * 2.1;
    col = mix(col, itemColour(ik) * 2.4, smoothstep(0.5, -0.5, d) * 0.9);
  }

  // Twenty metres a square: the ruler and the scale bar in one, at a width
  // measured in pixels so it stays a hairline whatever the window does.
  //
  // The metres-a-pixel comes from the mapping rather than from a derivative:
  // fwidth is an extension in GLSL ES 1.00 and this sketch is meant to run
  // there too. Since p is (2·frag − res)/res.y by construction, the scale is
  // exact rather than approximate, which a derivative would not have been.
  vec2 g = abs(fract(q / 20.0 + 0.5) - 0.5) * 20.0 / max(mpp, 1e-4);
  col = mix(col, vec3(0.62, 0.66, 0.74), 0.18 * (1.0 - smoothstep(0.0, 1.0, min(g.x, g.y))));

  // Where you are and which way you point. In *pixels*, not in metres: the
  // arrow is a symbol rather than a thing standing on the ground, and a
  // symbol that shrinks as the map covers more is a symbol nobody can see.
  // Drawn in metres it came out three pixels tall.
  vec2 rel = q - wk.xy;
  float ch = cos(-wk.z), sh = sin(-wk.z);
  vec2 lr = (mat2(ch, -sh, sh, ch) * rel) / max(mpp, 1e-4);   // +y is the way they face
  float arrow = max(-lr.y - 4.0, abs(lr.x) * 2.2 + lr.y - 8.0);
  col = mix(col, vec3(0.02, 0.02, 0.03), smoothstep(2.2, 0.7, arrow));
  col = mix(col, vec3(0.99, 0.93, 0.42), smoothstep(0.8, -0.3, arrow));

  // And a tick at the top, so north is stated rather than assumed.
  vec2 nm = m - vec2(0.0, 0.94);
  col = mix(col, vec3(0.85), step(abs(nm.x), 0.004) * step(abs(nm.y), 0.045));
  return col;
}

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  // Row 0 is the register bank and row 1 is the table of what has been
  // picked up. Everything below them is still the zeros it always was.
  if (texel.y > 1.5 || (texel.y < 0.5 && texel.x > 10.5)) return vec4(0.0);
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;
  float dt = 1.0 / 60.0;
  vec4 w = first ? vec4(spawnPoint(), 0.6, 0.0) : who();
  vec4 mt = first ? vec4(0.0) : meta();
  // The map is baked around where the walker was, so that is what "here"
  // means to every fetch below — and it has to be said before the first of
  // them, because ground() has no other way to know.
  gEye2 = w.xy;

  float lf = max(keyDown(u_keys, 37.0), keyDown(u_keys, 65.0));
  float rt = max(keyDown(u_keys, 39.0), keyDown(u_keys, 68.0));
  float fw = max(keyDown(u_keys, 38.0), keyDown(u_keys, 87.0));
  float bk = max(keyDown(u_keys, 40.0), keyDown(u_keys, 83.0));
  float run = 1.0 + keyDown(u_keys, 16.0) * 1.6;

  float heading = w.z + (lf - rt) * turn * dt;
  // Pitch, roll and the clock. Pitch stops just short of straight up: at
  // exactly vertical the forward vector is parallel to world-up and the frame
  // it is built from has no right-hand side.
  vec4 v = first ? vec4(-0.07, 0.0, hour, 0.0) : view();
  float upK = max(keyDown(u_keys, 73.0), keyDown(u_keys, 33.0));    // I / PageUp
  float dnK = max(keyDown(u_keys, 75.0), keyDown(u_keys, 34.0));    // K / PageDown
  float rlK = keyDown(u_keys, 81.0), rrK = keyDown(u_keys, 69.0);   // Q / E
  float pitch = clamp(v.x + (upK - dnK) * look * dt, -1.45, 1.45);

  // Roll comes back to level on its own.
  //
  // Free roll is what makes a first-person view lose its grounding: the
  // horizon stops telling you which way up you are, and nothing puts it back.
  // A shooter keeps up pointing up, so roll here is something you *hold* — let
  // go and it returns over about a third of a second. It is still there when
  // you want to lean into a turn; it is simply not somewhere you can end up by
  // accident.
  float roll = v.y + (rlK - rrK) * look * dt;
  if (rlK + rrK < 0.5) roll *= exp(-dt * 3.2);

  // Mouse look, by the *delta* rather than the position.
  //
  // The first version steered by where the pointer was — hold it left of
  // centre and the world spins, which is a joystick, not a mouse. A shooter
  // turns by how far the mouse moved since the last frame, so the pointer's
  // previous position is kept in a register beside everything else the world
  // remembers.
  // u_mouse is in the picture's pixels, and in the state pass u_resolution is
  // the *state's* — so there is nothing here to normalise by, and nothing that
  // should be: a shooter turns by an angle per pixel the mouse moved, not per
  // fraction of a window, which is why the same mouse feels the same in a
  // small window and a large one.
  vec2 mouseNow = u_mouse / 600.0;
  vec4 mouseMem = first ? vec4(mouseNow, 0.0, 0.0) : reg(vec2(7.0, 0.0));
  if (md > 0.5 && mouseMem.z > 0.5) {
    vec2 dm = mouseNow - mouseMem.xy;
    heading += dm.x * look * 5.2;
    pitch = clamp(pitch - dm.y * look * 4.0, -1.45, 1.45);
  }
  float clock = fract(v.z + dt / max(dayLen, 1.0));
  float sp = (fw - bk) * walk * run;
  vec2 dir = vec2(sin(heading), cos(heading));
  vec2 pos = w.xy + dir * sp * dt;
  // Where they meant to go, and then the nearest place they are allowed to
  // be. Not on the first frame: the map is baked around the spawn and does
  // not exist yet, so there is nothing there yet to be inside of.
  if (!first) pos = pushOut(pos);
  // Speed as *travelled*, not as asked for. Leaning on a boulder with forward
  // held should stop the footsteps, and this is the one number the gait, the
  // head bob and the metres walked are all made of.
  sp = sign(sp) * length(pos - w.xy) / dt;

  // What is within arm's reach, worked out once and needed by three texels:
  // the table that remembers it, the tally, and the pulse that plays the
  // sound. Each recomputes it rather than reading a neighbour's answer,
  // because a texel that reads its neighbour is reading last frame's.
  vec2 gotId; float gotKind;
  bool got = !first && reachFor(pos, gotId, gotKind);

  if (texel.y > 0.5) {
    // Row 1. A slot keeps what it had unless this is the frame its cell was
    // claimed; the cell's own coordinates go in beside the flag so that a
    // collision reads as "not taken" rather than as somebody else's mushroom.
    if (first) return vec4(0.0);
    if (got && abs(slotOf(gotId) - texel.x) < 0.5) return vec4(gotId, 1.0, gotKind);
    return reg(vec2(texel.x, 1.0));
  }

  if (texel.x < 0.5) return vec4(pos, heading, sp);
  if (texel.x < 1.5) return vec4(mt.x + abs(sp) * dt, 0.0, 0.0, 1.0);
  // The weather, worked out before the branches rather than inside one of
  // them: two texels want it now — the one that stores it and the one that
  // says how loud it is — and a value computed in a branch belongs to that
  // branch alone.
  float turnT = t * 0.037;
  vec2 dirW = vec2(sin(turnT * 1.3 + 0.7), cos(turnT));
  float gust = 0.55 + 0.45 * sin(t * 0.41) * sin(t * 0.17 + 1.1);
  // A wide ramp rather than a narrow one: a front that is 0 or 1 and
  // nothing between is a switch, and rain does not arrive like that.
  float front = smoothstep(0.24, 0.86, fbmN(vec2(t * 0.011, 4.3), 3) + weather - 0.5);
  vec2 windV = dirW * gust * windAmt * (0.6 + front * 0.9);

  if (texel.x > 2.5 && texel.x < 3.5) return vec4(pitch, roll, clock, 1.0);

  // ---- what the world sounds like ------------------------------------
  //
  // Three texels the host reads back and turns into sound. The world decides
  // *that* there is a chirp and how high it is; whether anything is heard is
  // the host's business, which is the same division the effects have always
  // had. It is also why the pulses are made here: a chirp that lasts exactly
  // one frame is something a shader can say and an expression cannot.
  float dayA = clock * 6.28318;
  float sunY = sin(dayA);
  vec4 land = landform(pos);
  float earY = max(land.x, 0.0) + 1.75;
  float open = exposure(pos, earY);
  if (texel.x > 3.5 && texel.x < 4.5) {
    // Levels, for the things that are heard continuously.
    // Scaled so a strong wind is loud and not merely clipped: at 0.55 it
    // reached 1 and stayed there, which is a level that tells you nothing.
    // Wind is loud where there is nothing to stop it. In a hollow it is not
    // gone, it is distant — which is the difference between an occluder and
    // a mute.
    float windL = clamp(length(windV) * 0.30, 0.0, 1.0) * (0.30 + 0.70 * open);
    // Near the water, and with something between you and it: a shore you
    // cannot see is a shore you cannot hear.
    float sea = (1.0 - smoothstep(0.0, 9.0, land.x)) * (0.25 + 0.75 * open);
    // Dawn is the sun coming up, not the sun being low — it has to be one
    // bump a day, and dusk is the other crossing of the same height.
    float dawn = smoothstep(-0.09, 0.14, sunY) * (1.0 - smoothstep(0.16, 0.46, sunY))
               * step(0.0, cos(dayA));
    return vec4(windL, front, sea, dawn);
  }
  if (texel.x > 4.5 && texel.x < 5.5) {
    vec4 mem = reg(vec2(5.0, 0.0));
    // A chirp, at most one a slot, and only in the dawn. The slot index is
    // kept so the pulse lasts the one frame the slot turns over on, rather
    // than the five frames a twelfth of a second spans.
    float dawn = smoothstep(-0.09, 0.14, sunY) * (1.0 - smoothstep(0.16, 0.46, sunY))
               * step(0.0, cos(dayA));
    float slot = floor(t * 11.0);
    float h = hash21(vec2(slot, 3.7));
    // A bird behind a hill is not heard at all. Fading it would be better and
    // needs a per-note velocity, which would mean a signal multiply this DSP
    // catalogue does not have and a change to every tone instrument — so for
    // now the occlusion is a gate rather than a level, and this comment is the
    // honest version of that.
    float sings = step(1.0 - 0.34 * dawn * wildlife, h) * step(0.45, open);
    float fresh = abs(slot - mem.z) > 0.5 ? 1.0 : 0.0;
    return vec4(sings * fresh, hash21(vec2(slot, 8.1)), slot, dawn);
  }
  if (texel.x > 9.5) {
    // The pulse, and how long ago. One frame of "picked", which is a thing a
    // shader can say and an expression cannot, and a fading number beside it
    // that the panel uses to light the slot you just filled.
    vec4 inv = first ? vec4(0.0) : reg(vec2(9.0, 0.0));
    vec4 was = first ? vec4(0.0) : reg(vec2(10.0, 0.0));
    float total = inv.x + inv.y + inv.z + inv.w + (got ? 1.0 : 0.0);
    float flash = got ? 1.0 : max(was.w - dt * 2.6, 0.0);
    return vec4(got ? 1.0 : 0.0, gotKind, total, flash);
  }
  if (texel.x > 8.5) {
    // The tally itself: four kinds, one texel, and nothing that grows.
    vec4 inv = first ? vec4(0.0) : reg(vec2(9.0, 0.0));
    return inv + (got ? oneHot(gotKind) : vec4(0.0));
  }
  if (texel.x > 7.5) {
    // What is underfoot, as the four weights the ground itself is painted
    // with — so a step on rock is the picture's own judgement about that
    // texel rather than a second opinion free to disagree with it.
    vec3 nrm = landNormal(pos);
    weigh(land.x, land.y, land.z, 1.0 - nrm.y);
    return gW;
  }
  if (texel.x > 6.5) {
    // Where the pointer was, and whether it was down — a delta needs a
    // previous, and the frame a drag starts on has none, which is the frame
    // the view would otherwise jump on.
    return vec4(mouseNow, md, 0.0);
  }
  if (texel.x > 5.5) {
    // A footfall each stride, found by watching the walked distance wrap.
    // Its own texel keeps its own memory: reading the chirp's would be a
    // different number that happens to be nearby.
    vec4 mem = reg(vec2(6.0, 0.0));
    // A long stride: at 1.75 m and thirteen metres a second it was seven
    // footfalls a second, which is a sewing machine rather than a walk.
    float phase = fract(meta().x / 2.6);
    float wrapped = (phase < mem.y && abs(sp) > 0.4) ? 1.0 : 0.0;
    return vec4(wrapped, phase, land.x < 0.4 ? 1.0 : 0.0, open);
  }
  if (texel.x < 2.5) {
    // Weather, drifting. The direction turns slowly, the strength gusts, and
    // the rain comes and goes over a couple of minutes — so standing still
    // for a while is a thing worth doing.
    return vec4(windV, front, gust);
  }
  return vec4(0.0);
}

// One texel of the map, baked around where the walker is now. Every texel,
// every frame: the map is a hundred and eighty metres wide and the walker
// moves, so nothing in it can be reused for long — and one fbm per texel is
// a great deal cheaper than a hundred per pixel.
vec4 sim2(vec2 q) {
  vec2 eye = frame == 0 ? spawnPoint() : who().xy;
  return landform(eye + (q - 0.5) * WORLD);
}

// ------------------------------------------------------------ the picture
vec4 w = who();
vec4 air = airOf();
gWind = air.xy;
gRain = air.z;
gEye2 = w.xy;
gWave = 0.0;


// Which way of looking. The greater of a held key and a ticked box — no
// latch, so nothing to fall out of step with the panel.
float mapV = max(mapOn, keyDown(u_keys, 77.0));
float povV = max(povOn, keyDown(u_keys, 86.0));

vec4 ft = reg(vec2(6.0, 0.0));
float standing = ground(w.xy);
vec3 ro = vec3(w.x, max(standing, gWave) + 1.75, w.y);

// A head that goes up and down, because a walk is not a dolly move.
//
// Twice a stride vertically — there are two feet — and once laterally, since
// they are on opposite sides of you. Scaled by how fast you are *actually*
// travelling, so leaning on a boulder is as still as standing still.
//
// Three centimetres, which is smaller than it wants to be. Head bob is the
// effect most often turned up until it makes people ill, and the amount that
// reads as walking is a good deal less than the amount that reads as effort.
float gait = clamp(abs(w.w) / max(walk, 1.0), 0.0, 1.0);
float stridePh = ft.y * 6.28318;
float bobUp = -cos(stridePh * 2.0) * 0.030 * gait;
float bobSide = sin(stridePh) * 0.042 * gait;

// Yaw, pitch and roll, built by hand rather than through lookAt — which can
// say where to point but has no way to say which way up.
vec4 vw = view();
float cp = cos(vw.x), sp2 = sin(vw.x);
vec3 fwd = vec3(sin(w.z) * cp, sp2, cos(w.z) * cp);
vec3 rgt = normalize(cross(fwd, vec3(0.0, 1.0, 0.0)));
vec3 upv = cross(rgt, fwd);
float cr = cos(vw.y), sr = sin(vw.y);
mat3 cam = mat3(rgt * cr + upv * sr, upv * cr - rgt * sr, fwd);
vec3 rd = cam * normalize(vec3(p, 1.55));

// Standing behind yourself.
//
// The walker only exists as a shape while somebody can see them — and the
// guard is a *uniform*, so every ray in the frame agrees about it. That is
// what makes this branch worth having, and it is the same fact that made the
// distance guard on the scatter worth deleting in Phase 28: a branch a warp
// agrees about is free, one it argues about costs both sides and the test.
gPov = povV;
gWalkAt = vec3(w.x, max(standing, gWave), w.y);
gWalkFace = w.z;
gWalkStride = ft.y;
gWalkSpeed = gait;
if (povV > 0.5) {
  // Behind and a little above, and pulled in when the ground gets between:
  // a camera on a rigid boom spends half of every hillside inside the hill.
  // Six tries at sixty centimetres is a coarse search and the right one —
  // it is a camera, not a collision solver, and the failure it has to avoid
  // is being underground rather than being an inch too far out.
  float boom = 4.4;
  for (int i = 0; i < 6; i++) {
    vec3 at = ro - fwd * boom + vec3(0.0, 0.85, 0.0);
    if (at.y > ground(at.xz) + 0.55) break;
    boom -= 0.6;
  }
  ro = ro - fwd * max(boom, 1.3) + vec3(0.0, 0.85, 0.0);
  ro.y = max(ro.y, ground(ro.xz) + 0.55);
} else {
  // The bob belongs to the head, so it is applied in the head's frame: up is
  // the camera's up, not the world's, and it therefore survives being upside
  // down. Adding it to ro.y would make a bob that grows and shrinks with how
  // far you are leaning.
  ro += upv * bobUp + rgt * bobSide;
}
// A day. The sun goes round a tilted circle and the moon goes round the other
// side of it, so when one is up the other is mostly not — which is wrong about
// the actual moon and right about what a sky looks like.
float dayAng = view().z * 6.28318;
gSun = normalize(vec3(cos(dayAng) * 0.85, sin(dayAng), 0.38));
gMoon = normalize(vec3(cos(dayAng + 3.14159) * 0.85, sin(dayAng + 3.14159), -0.42));
// Night is not a switch. It comes on as the sun goes under, and the dusk in
// between is where the light is worth looking at.
gNight = smoothstep(0.10, -0.14, gSun.y);
// Whichever is up is the light. The moon is a hundred thousand times dimmer
// than the sun in life; here it is twenty times, because a scene lit by the
// real ratio is a black rectangle.
gKey = mix(gSun, gMoon, gNight);
gKeyCol = mix(vec3(1.0, 0.94, 0.84) * (0.35 + 0.65 * smoothstep(-0.05, 0.35, gSun.y)),
              vec3(0.42, 0.52, 0.78), gNight);
vec3 sun = gKey;
// Rain takes the sun away and brings the horizon in. Most of what makes a wet
// day look like one follows from those two.
float far = mix(fogFar, fogFar * 0.42, gRain);
vec3 grey = vec3(0.52, 0.55, 0.60);
// Overcast is grey by day and nearly black by night — a rainy night is not a
// grey one, and mixing toward the same grey either way is what makes a cheap
// night look like a photograph of a day.
vec3 skyCol = mapV > 0.5 ? vec3(0.0) : mix(skyAt(rd), grey * (0.55 + 0.45 * smoothstep(-0.1, 0.5, rd.y)) * (1.0 - gNight * 0.88),
                  gRain * 0.8);
float sunDim = 1.0 - gRain * 0.72;

gGlow = vec3(0.0);
vec3 col = skyCol;
// Nothing to march when you are looking at the map, and nothing to pay for
// it either — the ternary is the whole saving, because a frame that marches
// and then throws the result away costs exactly as much as one that keeps it.
float tHit = mapV > 0.5 ? -1.0 : march(ro, rd, far);
if (tHit > 0.0) {
  vec3 hit = ro + rd * tHit;
  gNear = 1.0 - smoothstep(9.0, 52.0, tHit);
  gClose = 1.0 - smoothstep(3.0, 16.0, tHit);
  // What was hit. The marcher does not hand back what it stopped on, so the
  // three candidates are asked again — once, here, rather than a hundred
  // times in scene().
  float kind = 0.0;
  float dThing = thingAt(hit, kind);
  float dBird = birdsAt(hit);
  float dLand = hit.y - ground(hit.xz);
  bool onBird = dBird < min(min(dThing, dLand), hit.y - gWave) + 0.02;
  bool onThing = !onBird && dThing < min(dLand, hit.y - gWave) + 0.02;

  vec4 land = state2(mapUv(hit.xz));
  // Wetness rather than wet. At a hundred metres one pixel covers several
  // metres of shoreline, and a hard test there makes the coast a dotted line
  // — the ray lands on the sea or on the sand depending on nothing. Over a
  // band, the coast is a coast.
  gWet = smoothstep(0.35, -0.15, land.x - gWave);
  vec3 nLand = landNormal(hit.xz);
  float slope = 1.0 - nLand.y;
  weigh(land.x, land.y, land.z, slope);

  vec3 n = normalize(mix(detailNormal(nLand, hit.xz, land.x), seaNormal(hit.xz), gWet));
  vec3 albedo = mix(albedoOf(hit.xz, land.x), srgbToLinear(waterC), gWet);
  if (onThing) {
    // A thing has its own normal, because it is not the ground: normal3 walks
    // the whole field, which is what makes a trunk round.
    n = normal3(hit);
    gWet = 0.0;
    if (kind > 2.5) {
      // Something to pick up. It gets a little light of its own — not because
      // anything here glows, but because a thing the size of a fist in a
      // hundred and ninety metres of grass is otherwise a thing nobody ever
      // finds. The crystal gets most of it, which is at least an excuse.
      albedo = srgbToLinear(itemColour(gThingSize)) * 1.15;
      gGlow = itemColour(gThingSize) * (gThingSize > 1.5 && gThingSize < 2.5 ? 0.55 : 0.16);
    } else if (kind > 1.5) {
      // A hide, and a different one per animal — a herd of the same brown is
      // one animal drawn several times.
      vec2 id = floor(hit.xz / CELL);
      albedo = srgbToLinear(hideC) * (0.7 + 0.85 * hash21(id * 2.3 + 7.7))
             * (0.85 + 0.3 * noise(hit.xz * 14.0 + hit.y * 5.0));
    } else if (kind > 0.5) {
      // Lighter than the ground it sits on, and mottled: a boulder the colour
      // of its own shadow is a hole in the picture.
      albedo = srgbToLinear(rockC) * (2.4 + 1.1 * noise(hit.xz * 2.6 + hit.y));
    } else {
      // Bark below, leaves above — the trunk is the part near the axis.
      vec2 id = floor(hit.xz / CELL);
      float lift = smoothstep(1.6, 2.6, hit.y - ground(hit.xz));
      vec3 bark = srgbToLinear(vec3(0.52, 0.40, 0.30)) * (0.75 + 0.45 * noise(hit.xz * 9.0 + hit.y * 3.0));
      // Every tree its own green, or a wood reads as one object repeated.
      vec3 leaf = srgbToLinear(leafC) * (0.8 + 0.5 * noise(hit.xz * 3.2 + hit.y * 1.4))
                * (0.8 + 0.55 * hash21(id + 0.5));
      albedo = mix(bark, leaf, lift);
    }
  }

  if (onBird) {
    // A bird against the sky is a silhouette: there is nothing behind it to
    // bounce light back, so what you see is its shape and not its colour.
    n = normal3(hit);
    gWet = 0.0;
    gW = vec4(0.0);
    albedo = vec3(0.035, 0.033, 0.030);
    if (gNight > 0.5) albedo = vec3(0.02, 0.022, 0.03);
  }
  float sh = softShadow(hit + n * 0.06, sun, 9.0);
  float lit = max(dot(n, sun), 0.0);
  float occ = mix(ao(hit, n), 1.0, gWet);
  if (onThing) occ = mix(occ, 1.0, 0.45);          // leaves are not a cave
  if (onBird) occ = 1.0;                           // and nothing occludes the sky
  // Wet ground is darker and shinier: the water fills the pores, so less light
  // comes back diffusely and more of it comes back in one direction.
  albedo *= 1.0 - gRain * 0.35 * (1.0 - gWet);
  vec3 lin = albedo * (lit * sh * gKeyCol * mix(2.35, 0.42, gNight) * sunDim
                     // Snow's shadows are the sky's colour, which is why they
                     // are blue and why nothing else on the ground is.
                     // The ambient is the sky, so it goes out with the sky.
                     + occ * mix(mix(vec3(0.13, 0.19, 0.31), vec3(0.20, 0.30, 0.52), gW.w),
                                 vec3(0.030, 0.042, 0.085), gNight)
                       * (0.5 + 0.5 * n.y));
  // What the biome does with the light, rather than only with the pigment:
  // snow and water throw it back, sand and grass do not.
  float gloss = gW.w * 0.75 + gWet * 0.95 + gW.z * 0.12;
  if (onThing) gloss = 0.05;                       // bark, stone and hide are matt
  if (onBird) gloss = 0.0;
  gloss = max(gloss, gRain * 0.55 * (1.0 - gWet));
  vec3 hv = normalize(sun - rd);
  lin += pow(max(dot(n, hv), 0.0), mix(30.0, 260.0, gloss)) * sh * gloss * 1.8 * sunDim;
  lin += gGlow;
  float fr = fresnel(max(dot(n, -rd), 0.0), 0.02);
  lin = mix(lin, skyCol, fr * (gWet * 0.85 + gW.w * 0.25 + gRain * 0.3));
  // Air, not milk: enough to say "far away" and not so much that the middle
  // distance loses its shape.
  col = mix(skyCol, lin, exp(-pow(tHit / far, 1.6) * 2.4));
}

// ------------------------------------------------------------ the rain
//
// Not particles and not geometry: four layers of streaks, each on a plane at
// a fixed distance, sampled where the ray crosses it. A ray is a line, so the
// crossing is one multiply — which makes a whole downpour a handful of hashes
// a pixel rather than anything the marcher has to know about.
//
// Near layers are large and sparse, far ones small and dense. That is
// parallax, and it is what stops rain reading as a texture stuck to the lens.
if (gRain > 0.01 && mapV < 0.5) {
  vec3 fall = normalize(vec3(gWind.x * 0.22, -1.0, gWind.y * 0.22));
  // The frame belongs to the *rain*, not to the ray. The first version built
  // it from cross(fall, rd), which is perpendicular to rd by construction — so
  // projecting a point along the ray onto it gave zero everywhere and the
  // downpour was invisible. Across the fall, and along it:
  vec3 across = normalize(cross(fall, vec3(0.0, 0.0, 1.0)));
  for (int i = 0; i < 4; i++) {
    vec3 at = rd * (2.5 + float(i) * 5.5);
    float k = 11.0 - float(i) * 1.6;
    vec2 sq = vec2(dot(at, across), dot(at, fall)) * k;
    sq.y += t * (34.0 + float(i) * 9.0);           // falling
    float h = hash21(floor(sq) + float(i) * 17.3);
    vec2 f = fract(sq) - 0.5;
    // Narrow across and long along, so a drop is a streak rather than a dot.
    float streak = step(1.0 - gRain * 0.45, h)
                 * smoothstep(0.4, 0.0, abs(f.x) * 4.5 + abs(f.y) * 0.35);
    col += vec3(0.58, 0.63, 0.72) * streak * 0.34 * (1.0 - float(i) * 0.16);
  }
}

// A crosshair. Four ticks and a gap, drawn in the picture's own pixels rather
// than in p — a reticle that changes size with the aspect is not a reticle.
// It is the cheapest thing here and it does more for the feel of standing
// somewhere than anything else in this file: without a fixed mark to look
// through, a first-person view is a camera being flown rather than a head
// being turned.
if (mapV < 0.5) {
  vec2 pix = (gl_FragCoord.xy - u_resolution * 0.5);
  vec2 ap = abs(pix);
  float arm = min(max(ap.x, ap.y), 9.0) - 3.0;          // a gap in the middle
  float tick = step(min(ap.x, ap.y), 0.75) * step(3.0, max(ap.x, ap.y)) * step(max(ap.x, ap.y), 9.0);
  float dot_ = step(length(pix), 1.0);
  float mark = clamp(tick + dot_, 0.0, 1.0);
  col = mix(col, vec3(0.95), mark * 0.55);
}

if (mapV > 0.5) col = mapPicture(p, w);

// What you are carrying, over whichever view you are in — the map included,
// because "what have I got" and "where am I" are the same question asked
// twice, and the answer should not move between them.
{
  vec4 pick = reg(vec2(10.0, 0.0));
  col = panel(col, reg(vec2(9.0, 0.0)), pick.y, pick.w);
}

finish(col)` },

  { id: "snake", label: "Snake — the grid the game writes into itself", preview: [640, 480], steps: 1,
    probes: { ate: { texel: [3, 0], channel: "r" }, died: { texel: [3, 0], channel: "g" },
              turned: { texel: [3, 0], channel: "b" }, score: { texel: [1, 0], channel: "g" } },
    instruments: { pip: { ref: "tone.blip" }, eat: { ref: "tone.bell" }, over: { ref: "tone.pluck" } },
    effects: [
      { kind: "note", instrument: "eat", when: 'ch("ate") > 0.5',
        hz: '523 * 2 ^ (min(ch("score"), 12) / 12)', dur: "0.12" },
      { kind: "note", instrument: "pip", when: 'ch("turned") > 0.5', hz: "294", dur: "0.04" },
      { kind: "note", instrument: "over", when: 'ch("died") > 0.5', hz: "98", dur: "0.7" },
    ],
    source:
`// Snake, and the snake is not a list — it is the grid. Every cell of the
// board is one texel holding how many more steps it stays part of the body;
// each step every cell counts down by one and the head's cell is set to the
// length. A cell is snake while its number is above zero, so the tail
// disappears by arithmetic and nothing has to remember where it was.
//
// That is the thing a texture can do that a variable cannot, and it is why
// this is thirty lines rather than a linked list. Arrows or WASD. R restarts.
uniform sampler2D u_keys;
uniform float cell;    // @range 8 40 @step 1 @int @default 24 @help board width in cells
uniform float every;   // @range 2 20 @step 1 @int @default 7 @help frames between steps
uniform vec3 ink;      // @color @default #f4efe6
uniform vec3 body;     // @color @default #6ee7c8
uniform vec3 fruit;    // @color @default #ff7a3d

float COLS() { return max(4.0, floor(cell)); }
float ROWS() { return max(4.0, floor(COLS() * u_resolution.y / u_resolution.x)); }
// Row 0 of the state is registers; the board starts at row 1.
vec4 head()  { return state(vec2(0.5, 0.5) / u_resolution); }   // x, y, dx, dy
vec4 meta()  { return state(vec2(1.5, 0.5) / u_resolution); }   // length, score, alive, timer
vec4 food()  { return state(vec2(2.5, 0.5) / u_resolution); }   // x, y
float at(vec2 c) { return state((vec2(c.x, c.y + 1.0) + 0.5) / u_resolution).r; }
// Where the fruit goes next: a hash of the step number, re-rolled a few times
// if it lands on the snake. Four tries is enough at these sizes and it can be
// counted, which an unbounded loop cannot.
vec2 place(float n) {
  vec2 f = vec2(0.0);
  for (int i = 0; i < 4; i++) {
    f = floor(vec2(hash21(vec2(n * 3.7 + float(i), 11.0)),
                   hash21(vec2(n * 5.1 + float(i), 23.0))) * vec2(COLS(), ROWS()));
    if (at(f) < 0.5) return f;
  }
  return f;
}

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;
  float C = COLS(), R = ROWS();

  vec4 h = first ? vec4(floor(C * 0.5), floor(R * 0.5), 1.0, 0.0) : head();
  vec4 m = first ? vec4(4.0, 0.0, 1.0, 0.0) : meta();
  vec2 f = first ? vec2(floor(C * 0.75), floor(R * 0.5)) : food().xy;

  // Turning is read every frame, so a press between steps is not lost.
  float lf = max(keyHit(u_keys, 37.0), keyHit(u_keys, 65.0));
  float rt = max(keyHit(u_keys, 39.0), keyHit(u_keys, 68.0));
  float up = max(keyHit(u_keys, 38.0), keyHit(u_keys, 87.0));
  float dn = max(keyHit(u_keys, 40.0), keyHit(u_keys, 83.0));
  vec2 want = h.zw;
  float turned = 0.0;
  if (lf > 0.5 && h.z ==  0.0) { want = vec2(-1.0,  0.0); turned = 1.0; }
  if (rt > 0.5 && h.z ==  0.0) { want = vec2( 1.0,  0.0); turned = 1.0; }
  if (up > 0.5 && h.w ==  0.0) { want = vec2( 0.0,  1.0); turned = 1.0; }
  if (dn > 0.5 && h.w ==  0.0) { want = vec2( 0.0, -1.0); turned = 1.0; }

  float timer = m.w + 1.0;
  bool step_ = timer >= max(2.0, floor(every)) && m.z > 0.5;
  float ate = 0.0, died = 0.0;
  vec2 np = h.xy;
  if (step_) {
    timer = 0.0;
    np = h.xy + want;
    if (np.x < 0.0 || np.y < 0.0 || np.x >= C || np.y >= R) { died = 1.0; }
    else if (at(np) > 0.5) { died = 1.0; }
    else if (np == f) { ate = 1.0; m.x += 1.0; m.y += 1.0; f = place(m.y); }
  }
  if (died > 0.5) { m.z = 0.0; }

  if (texel == vec2(0.0)) return vec4(step_ && died < 0.5 ? np : h.xy, want);
  if (texel == vec2(1.0, 0.0)) return vec4(m.x, m.y, m.z, timer);
  if (texel == vec2(2.0, 0.0)) return vec4(f, 0.0, 1.0);
  if (texel == vec2(3.0, 0.0)) return vec4(ate, died, turned, 1.0);
  // The board. Every cell counts down; the head's cell is refilled.
  if (texel.y >= 1.0 && texel.x < C && texel.y <= R) {
    vec2 c = vec2(texel.x, texel.y - 1.0);
    float life = first ? (c == vec2(floor(C * 0.5), floor(R * 0.5)) ? 4.0 : 0.0) : at(c);
    if (step_ && died < 0.5) {
      life = max(0.0, life - 1.0);
      if (c == np) life = m.x;
    }
    return vec4(life, 0.0, 0.0, 1.0);
  }
  return vec4(0.0);
}

float C = COLS(), R = ROWS();
vec2 cellUV = uv * vec2(C, R);
vec2 c = floor(cellUV);
vec2 inCell = fract(cellUV) - 0.5;
vec4 m = meta();
vec3 col = vec3(0.05, 0.06, 0.11);
// A quiet grid, so the board reads as a board.
col = mix(col, col * 1.5, step(0.46, max(abs(inCell.x), abs(inCell.y))));
float life = at(c);
if (life > 0.5) {
  // The nose is brightest and the tail fades, which the countdown already
  // encodes — nothing extra is stored to draw it.
  float k = life / max(1.0, m.x);
  col = mix(col * 1.2, body, 0.45 + 0.55 * k);
  col = mix(col, ink, smoothstep(0.42, 0.30, max(abs(inCell.x), abs(inCell.y))) * 0.12);
}
if (c == food().xy) col = mix(col, fruit, 1.0 - smoothstep(0.18, 0.34, length(inCell)));
if (m.z < 0.5) col *= 0.45;
// The score along the top edge.
float marks = min(m.y, C);
if (c.y == R - 1.0 && c.x < marks) col = mix(col, fruit, 0.55);
col`
  },
  { id: "platform", label: "Platformer — the level is a texture", preview: [640, 400], steps: 1,
    probes: { coin: { texel: [3, 0], channel: "r" }, land: { texel: [3, 0], channel: "g" },
              jump: { texel: [3, 0], channel: "b" }, score: { texel: [1, 0], channel: "g" } },
    instruments: { hop: { ref: "tone.blip" }, ping: { ref: "tone.bell" }, thud: { ref: "tone.pluck" } },
    effects: [
      { kind: "note", instrument: "ping", when: 'ch("coin") > 0.5',
        hz: '659 * 2 ^ (min(ch("score"), 12) / 12)', dur: "0.14" },
      { kind: "note", instrument: "hop", when: 'ch("jump") > 0.5', hz: "392", dur: "0.06" },
      { kind: "note", instrument: "thud", when: 'ch("land") > 0.5', hz: "147", dur: "0.09" },
    ],
    source:
`// A platformer whose level is a texture. Row 1 upward of the state holds the
// world one tile a texel — red is solid, green is a coin — generated once
// from a hash and then written back unchanged, so the world is somewhere the
// game can *look things up* rather than something the shader recomputes.
// Collision is four lookups at the corners of the player's box.
//
// Left and right walk, space or up jumps. R restarts.
uniform sampler2D u_keys;
uniform float gravity;  // @range 20 90 @default 46 @help tiles per second squared
uniform float runSpd;   // @range 3 14 @default 7.5 @help tiles per second
uniform float jumpSpd;  // @range 6 22 @default 13.5 @help tiles per second
uniform vec3 sky1;      // @color @default #1b2b4b
uniform vec3 rock;      // @color @default #2f7d5b
uniform vec3 ink;       // @color @default #f4efe6
uniform vec3 gold;      // @color @default #ff7a3d

const float MAPW = 64.0;
const float MAPH = 18.0;
const float VIEW = 16.0;      // tiles across the screen
vec4 who()  { return state(vec2(0.5, 0.5) / u_resolution); }   // x, y, vx, vy
vec4 meta() { return state(vec2(1.5, 0.5) / u_resolution); }   // onGround, score, alive, camX
vec4 tile(vec2 t) {
  if (t.x < 0.0 || t.y < 0.0 || t.x >= MAPW || t.y >= MAPH) return vec4(1.0, 0.0, 0.0, 1.0);
  return state((vec2(t.x, t.y + 1.0) + 0.5) / u_resolution);
}
float solid(vec2 t) { return tile(t).r; }
// What is under a tile, which decides where a coin can sit.
float solidBelow(vec2 t) {
  float gap = t.x < 6.0 ? 0.0 : step(0.82, hash21(vec2(floor(t.x / 3.0), 7.0)));
  float ground = (t.y - 1.0) < 2.0 && (t.y - 1.0) >= 0.0 && gap < 0.5 ? 1.0 : 0.0;
  float ledge = 0.0;
  float yy = t.y - 1.0;
  if (yy > 3.0 && mod(yy, 4.0) == 0.0) {
    float h = hash21(vec2(floor(t.x / 5.0), floor(yy / 4.0) * 3.0 + 1.0));
    ledge = h > 0.45 && mod(t.x, 5.0) < 3.0 ? 1.0 : 0.0;
  }
  return max(ground, ledge);
}
// The world, decided once and then stored. Two rows of ground with gaps, and
// ledges above them; a coin sits over most ledges.
vec4 makeTile(vec2 t) {
  // The first stretch is always solid, so wherever the player starts there
  // is something under it — a spawn inside geometry is a game that never
  // moves, which is exactly what the first version of this did.
  float gap = t.x < 6.0 ? 0.0 : step(0.82, hash21(vec2(floor(t.x / 3.0), 7.0)));
  float ground = t.y < 2.0 && gap < 0.5 ? 1.0 : 0.0;
  float ledge = 0.0;
  float band = floor(t.y / 4.0);
  if (t.y > 3.0 && mod(t.y, 4.0) == 0.0) {
    float h = hash21(vec2(floor(t.x / 5.0), band * 3.0 + 1.0));
    ledge = h > 0.45 && mod(t.x, 5.0) < 3.0 ? 1.0 : 0.0;
  }
  float sol = max(ground, ledge);
  float coin = sol < 0.5 && solidBelow(t) > 0.5 && hash21(t + 5.0) > 0.55 ? 1.0 : 0.0;
  return vec4(sol, coin, 0.0, 1.0);
}
// Is the player's box overlapping anything solid at this position?
float hits(vec2 pos) {
  vec2 lo = pos + vec2(-0.32, 0.0), hi = pos + vec2(0.32, 0.9);
  return max(max(solid(floor(vec2(lo.x, lo.y))), solid(floor(vec2(hi.x, lo.y)))),
             max(solid(floor(vec2(lo.x, hi.y))), solid(floor(vec2(hi.x, hi.y)))));
}

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;
  float dt = 1.0 / 60.0;
  vec4 w = first ? vec4(2.0, 2.2, 0.0, 0.0) : who();
  vec4 m = first ? vec4(0.0, 0.0, 1.0, 0.0) : meta();

  float lf = max(keyDown(u_keys, 37.0), keyDown(u_keys, 65.0));
  float rt = max(keyDown(u_keys, 39.0), keyDown(u_keys, 68.0));
  float jp = max(keyHit(u_keys, 32.0), keyHit(u_keys, 38.0));
  float coin = 0.0, land = 0.0, jumped = 0.0;

  float vx = (rt - lf) * runSpd;
  float vy = w.w - gravity * dt;
  if (jp > 0.5 && m.x > 0.5) { vy = jumpSpd; jumped = 1.0; }

  // One axis at a time, so a wall does not also stop a fall.
  vec2 pos = w.xy;
  vec2 tryX = vec2(pos.x + vx * dt, pos.y);
  if (hits(tryX) < 0.5) pos = tryX; else vx = 0.0;
  vec2 tryY = vec2(pos.x, pos.y + vy * dt);
  float onGround = 0.0;
  if (hits(tryY) < 0.5) { pos = tryY; }
  else {
    if (vy < 0.0) { onGround = 1.0; if (m.x < 0.5) land = 1.0; }
    vy = 0.0;
  }
  if (pos.y < -3.0) { pos = vec2(2.0, 2.2); vy = 0.0; }

  vec2 onTile = floor(pos + vec2(0.0, 0.45));
  if (tile(onTile).g > 0.5) { coin = 1.0; m.y += 1.0; }
  float camX = clamp(pos.x - VIEW * 0.5, 0.0, MAPW - VIEW);

  if (texel == vec2(0.0)) return vec4(pos, vx, vy);
  if (texel == vec2(1.0, 0.0)) return vec4(onGround, m.y, 1.0, camX);
  if (texel == vec2(3.0, 0.0)) return vec4(coin, land, jumped, 1.0);
  if (texel.y >= 1.0 && texel.x < MAPW && texel.y <= MAPH) {
    vec2 t = vec2(texel.x, texel.y - 1.0);
    vec4 cur = first ? makeTile(t) : tile(t);
    // A collected coin is cleared, and only that one texel changes.
    if (!first && cur.g > 0.5 && t == onTile && coin > 0.5) cur.g = 0.0;
    return cur;
  }
  return vec4(0.0);
}

vec4 w = who();
vec4 m = meta();
float aspect = u_resolution.x / u_resolution.y;
// World coordinates under this pixel, from the camera.
vec2 wp = vec2(m.w, 0.0) + uv * vec2(VIEW, VIEW / aspect);
vec2 t = floor(wp);
vec2 inT = fract(wp) - 0.5;

vec3 col = mix(sky1 * 0.55, sky1, uv.y);
vec4 tl = tile(t);
if (tl.r > 0.5) {
  // A little shading from the tile's own coordinates, so a wall of one
  // colour still reads as tiles.
  float edge = smoothstep(0.5, 0.42, max(abs(inT.x), abs(inT.y)));
  col = mix(rock * 0.6, rock, edge);
  col *= 0.85 + 0.3 * hash21(t);
}
if (tl.g > 0.5) col = mix(col, gold, 1.0 - smoothstep(0.12, 0.26, length(inT)));
// The player: a rounded box, feet at its position.
vec2 rel = wp - w.xy - vec2(0.0, 0.45);
float d = sdBox(rel, vec2(0.3, 0.45)) - 0.08;
col = mix(col, ink, aa(d));
col = mix(col, sky1 * 0.4, aa(sdCircle(rel - vec2(sign(w.z) * 0.1, 0.2), 0.06)));
// Score along the top.
float marks = min(m.y, 20.0);
if (uv.y > 0.94 && uv.x * 20.0 < marks) col = mix(col, gold, 0.8);
col`
  },
  { id: "breakout", label: "Breakout — a wall of bricks, in the texture", preview: [640, 400], steps: 1,
    // The bricks are not a variable: they are twenty-four texels of the
    // state, one per brick, and the ball reads the one it is over. A shader
    // has no arrays, and it does not need any — the texture is the array.
    probes: {
      hitBrick: { texel: [3, 0], channel: "r" },
      hitWall:  { texel: [3, 0], channel: "g" },
      missed:   { texel: [3, 0], channel: "b" },
      score:    { texel: [1, 0], channel: "g" },
      ballX:    { texel: [0, 0], channel: "r" },
    },
    instruments: { brick: { ref: "tone.blip" }, wall: { ref: "tone.pluck" }, lose: { ref: "tone.bell" } },
    effects: [
      { kind: "note", instrument: "brick", when: 'ch("hitBrick") > 0.5',
        hz: '523 * 2 ^ (min(ch("score"), 12) / 12)', dur: "0.09" },
      { kind: "note", instrument: "wall", when: 'ch("hitWall") > 0.5', hz: "196", dur: "0.06" },
      { kind: "note", instrument: "lose", when: 'ch("missed") > 0.5', hz: "147", dur: "0.6" },
    ],
    source:
`// A wall of bricks, and the wall lives in the texture. Row 1 of the state
// holds twenty-four texels, one a brick, 1 while it stands; the ball reads
// the texel under it and that texel reads whether the ball is over it. No
// arrays, no lists — a shader has neither, and with a texture it needs
// neither. Left and right, or A and D. Click first so it has the keys.
uniform sampler2D u_keys;
uniform float speed;    // @range 0.3 2 @default 0.85 @help ball speed
uniform float batLen;   // @range 0.08 0.4 @default 0.16 @help half the bat's width
uniform vec3 ink;       // @color @default #f4efe6
uniform vec3 hot;       // @color @default #ff7a3d
uniform vec3 brickCol;  // @color @default #6ee7c8

const float COLS = 12.0;
const float ROWS = 2.0;
float A() { return u_resolution.x / u_resolution.y; }
vec4 reg()  { return state(vec2(0.5, 0.5) / u_resolution); }        // ball xy, vel xy
vec4 bat()  { return state(vec2(1.5, 0.5) / u_resolution); }        // bat x, score
// Brick k is texel (k, 1) — a row of the state used as an array.
float brick(float k) { return state(vec2(k + 0.5, 1.5) / u_resolution).r; }
// Which brick a point is over, or -1.
float brickAt(vec2 q) {
  float top = 0.95, h = 0.16, w = 2.0 * A() / COLS;
  if (q.y > top || q.y < top - ROWS * h) return -1.0;
  float col = floor((q.x + A()) / w);
  float row = floor((top - q.y) / h);
  if (col < 0.0 || col >= COLS || row < 0.0 || row >= ROWS) return -1.0;
  return row * COLS + col;
}

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  float left  = max(keyDown(u_keys, 37.0), keyDown(u_keys, 65.0));
  float right = max(keyDown(u_keys, 39.0), keyDown(u_keys, 68.0));
  float aa2 = A();
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;

  vec4 b = first ? vec4(0.0, -0.4, speed * 0.55, speed * 0.6) : reg();
  vec4 s = first ? vec4(0.0, 0.0, 0.0, 1.0) : bat();
  float dt = 1.0 / 60.0;

  float bx = clamp(s.x + (right - left) * 1.6 * dt, -aa2 + batLen, aa2 - batLen);
  vec2 pos = b.xy + b.zw * dt;
  vec2 vel = b.zw;
  float hitBrick = 0.0, hitWall = 0.0, missed = 0.0;

  if (pos.x >  aa2 - 0.02) { pos.x =  aa2 - 0.02; vel.x = -vel.x; hitWall = 1.0; }
  if (pos.x < -aa2 + 0.02) { pos.x = -aa2 + 0.02; vel.x = -vel.x; hitWall = 1.0; }
  if (pos.y >  1.0) { pos.y = 1.0; vel.y = -vel.y; hitWall = 1.0; }
  // The bat.
  if (pos.y < -0.86 && vel.y < 0.0 && abs(pos.x - bx) < batLen) {
    pos.y = -0.86; vel.y = -vel.y;
    vel.x += (pos.x - bx) / batLen * speed * 0.5;
  }
  // A brick, if the ball is over one that still stands.
  float k = brickAt(pos);
  if (k >= 0.0 && brick(k) > 0.5) { vel.y = -vel.y; s.y += 1.0; hitBrick = 1.0; }
  if (pos.y < -1.1) { pos = vec2(0.0, -0.4); vel = vec2(speed * 0.55, speed * 0.6); missed = 1.0; }

  if (texel == vec2(0.0)) return vec4(pos, vel);
  if (texel == vec2(1.0, 0.0)) return vec4(bx, s.y, 0.0, 1.0);
  if (texel == vec2(3.0, 0.0)) return vec4(hitBrick, hitWall, missed, 1.0);
  // The wall itself. A brick stands until the ball is over it.
  if (texel.y == 1.0 && texel.x < COLS * ROWS) {
    float me = first ? 1.0 : brick(texel.x);
    if (hitBrick > 0.5 && abs(texel.x - k) < 0.5) me = 0.0;
    // Every brick gone: put them all back and keep the score.
    return vec4(me, 0.0, 0.0, 1.0);
  }
  return vec4(0.0);
}

float aa2 = A();
vec4 b = reg();
vec4 s = bat();
vec3 col = vec3(0.04, 0.05, 0.09);
// The wall, read back out of the texture one brick at a time.
float k = brickAt(p);
if (k >= 0.0 && brick(k) > 0.5) {
  float w = 2.0 * aa2 / COLS, h = 0.16;
  vec2 c = vec2(-aa2 + (mod(k, COLS) + 0.5) * w, 0.95 - (floor(k / COLS) + 0.5) * h);
  float d = sdBox(p - c, vec2(w * 0.42, h * 0.36));
  col = mix(col, brickCol * (0.7 + 0.3 * (1.0 - floor(k / COLS) / ROWS)), aa(d));
}
col = mix(col, hot, aa(length(p - b.xy) - 0.028));
col = mix(col, ink, aa(sdBox(p - vec2(s.x, -0.93), vec2(batLen, 0.022))));
// The score, as marks along the bottom.
float marks = min(s.y, 24.0);
float m2 = sdBox(vec2(mod(p.x + aa2, 0.09) - 0.045, p.y + 0.99), vec2(0.02, 0.012));
if (p.x < -aa2 + marks * 0.09) col = mix(col, hot * 0.8, aa(m2));
col`
  },
  { id: "flappy", label: "One-key flyer — pipes, and a score you can hear", preview: [640, 400], steps: 1,
    probes: {
      passed: { texel: [2, 0], channel: "r" },
      died:   { texel: [2, 0], channel: "g" },
      flap:   { texel: [2, 0], channel: "b" },
      score:  { texel: [1, 0], channel: "g" },
    },
    instruments: { wing: { ref: "tone.blip" }, point: { ref: "tone.bell" }, crash: { ref: "tone.pluck" } },
    effects: [
      { kind: "note", instrument: "wing", when: 'ch("flap") > 0.5', hz: "330", dur: "0.05" },
      { kind: "note", instrument: "point", when: 'ch("passed") > 0.5',
        hz: '523 * 2 ^ (min(ch("score"), 10) / 12)', dur: "0.18" },
      { kind: "note", instrument: "crash", when: 'ch("died") > 0.5', hz: "110", dur: "0.5" },
    ],
    source:
`// One key. Space or up flaps; everything else is gravity. The pipes are not
// objects — there is one pipe pattern scrolling, and its gap height comes
// from a hash of which pipe it is, so an unbounded course costs two texels.
// Click the picture first so it has the keys.
uniform sampler2D u_keys;
uniform float gravity;  // @range 1 6 @default 3.2 @help how hard it falls
uniform float flapUp;   // @range 0.4 2 @default 1.05 @help how hard a flap pushes
uniform float gap;      // @range 0.2 0.7 @default 0.42 @help half the gap height
uniform float pace;     // @range 0.2 1.5 @default 0.62 @help how fast the course moves
uniform vec3 ink;       // @color @default #f4efe6
uniform vec3 hot;       // @color @default #ff7a3d
uniform vec3 pipeCol;   // @color @default #2f7d5b

float A() { return u_resolution.x / u_resolution.y; }
vec4 reg() { return state(vec2(0.5, 0.5) / u_resolution); }   // y, vy, x travelled, alive
vec4 sc()  { return state(vec2(1.5, 0.5) / u_resolution); }   // last pipe counted, score
// Where the gap sits for pipe number n. A hash, so the course is endless and
// remembers nothing.
float gapAt(float n) { return (hash21(vec2(n * 7.31, 3.0)) - 0.5) * 1.1; }
// Where pipe n is on screen. The sim and the picture must not each have their
// own idea of this, or the bird dies where nothing is drawn — so there is one
// function and both call it.
const float UNIT = 1.1;      // world distance between pipes
const float SCALE = 1.6;     // world units to screen units
const float BIRD_X = -0.55;
float pipeX(float n, float travelled) { return BIRD_X + (n * UNIT - travelled) * SCALE; }
// The pipe the bird is nearest, in pipe numbers.
float nearestPipe(float travelled) { return floor(travelled / UNIT) + 1.0; }

vec4 sim(vec2 uvv) {
  vec2 texel = floor(gl_FragCoord.xy);
  float dt = 1.0 / 60.0;
  float up = max(keyHit(u_keys, 32.0), keyHit(u_keys, 38.0));
  bool first = frame == 0 || keyHit(u_keys, 82.0) > 0.5;

  vec4 b = first ? vec4(0.0, 0.0, 0.0, 1.0) : reg();
  vec4 s = first ? vec4(-1.0, 0.0, 0.0, 1.0) : sc();
  float passed = 0.0, died = 0.0, flapped = 0.0;

  float vy = b.y - gravity * dt;
  if (up > 0.5 && b.w > 0.5) { vy = flapUp; flapped = 1.0; }
  float y = b.x + vy * dt;
  float travelled = b.z + pace * dt;

  // The pipe the bird is nearest, and where it is on screen — the same
  // function the picture uses, so what kills you is what you can see.
  float n = nearestPipe(travelled);
  float g = gapAt(n);
  float dx = abs(pipeX(n, travelled) - BIRD_X);
  if (dx < 0.09 + 0.07 && abs(y - g) > gap && b.w > 0.5) { died = 1.0; }
  // Counted once, when the pipe has gone by.
  if (pipeX(n, travelled) < BIRD_X - 0.16 && n > s.x + 0.5 && b.w > 0.5) { passed = 1.0; s.x = n; s.y += 1.0; }
  if (y < -1.0 || y > 1.0) { died = 1.0; }

  float alive = b.w;
  if (died > 0.5) { alive = 0.0; }
  if (alive < 0.5 && !first) { y = b.x; vy = 0.0; travelled = b.z; }
  if (first) { s = vec4(-1.0, 0.0, 0.0, 1.0); }

  if (texel == vec2(0.0)) return vec4(y, vy, travelled, alive);
  if (texel == vec2(1.0, 0.0)) return vec4(s.x, s.y, 0.0, 1.0);
  if (texel == vec2(2.0, 0.0)) return vec4(passed, died, flapped, 1.0);
  return vec4(0.0);
}

float aa2 = A();
vec4 b = reg();
vec4 s = sc();
vec3 col = mix(vec3(0.06, 0.09, 0.16), vec3(0.10, 0.14, 0.24), uv.y);
// The pipes: one shape repeated, its gap read from the hash, its place from
// the same pipeX() the collision uses.
float travelled = b.z;
float n0 = nearestPipe(travelled);
for (int i = -1; i < 3; i++) {
  float n = n0 + float(i);
  float xAt = pipeX(n, travelled);
  float g = gapAt(n);
  float dTop = sdBox(p - vec2(xAt, g + gap + 1.0), vec2(0.09, 1.0));
  float dBot = sdBox(p - vec2(xAt, g - gap - 1.0), vec2(0.09, 1.0));
  col = mix(col, pipeCol, aa(min(dTop, dBot)));
}
// The bird, tilted by how fast it is falling.
vec2 q = rot(clamp(b.y * 0.5, -0.9, 0.9)) * (p - vec2(BIRD_X, b.x));
float body = sdEllipse(q, vec2(0.075, 0.055));
col = mix(col, b.w > 0.5 ? hot : vec3(0.4, 0.2, 0.2), aa(body));
col = mix(col, ink, aa(sdCircle(q - vec2(0.035, 0.02), 0.012)));
// The score, as marks across the top.
float marks = min(s.y, 20.0);
float m2 = sdBox(vec2(mod(p.x + aa2, 0.1) - 0.05, p.y - 0.93), vec2(0.02, 0.014));
if (p.x < -aa2 + marks * 0.1) col = mix(col, ink, aa(m2));
col`
  },
  { id: "pong", label: "Bat and ball — a game, in one sketch, with sound", preview: [640, 400], steps: 1,
    // What the host reads out of the sketch's own state, once a frame. The
    // sketch writes its three events into one texel; naming them here is all
    // it takes for a shader's decisions to become a document's effects.
    probes: {
      hitBat:  { texel: [2, 0], channel: "r" },
      hitWall: { texel: [2, 0], channel: "g" },
      missed:  { texel: [2, 0], channel: "b" },
      score:   { texel: [1, 0], channel: "g" },
      ballY:   { texel: [0, 0], channel: "g" },
      batY:    { texel: [1, 0], channel: "r" },
    },
    instruments: { blip: { ref: "tone.blip" }, bell: { ref: "tone.bell" }, thud: { ref: "tone.pluck" } },
    effects: [
      { kind: "note", instrument: "blip", when: 'ch("hitBat") > 0.5',
        hz: '440 * 2 ^ ((ch("ballY") - ch("batY")) * 6 / 12)', dur: "0.07" },
      { kind: "note", instrument: "bell", when: 'ch("hitWall") > 0.5',
        hz: '587 * 2 ^ (min(ch("score"), 10) / 12)', dur: "0.22" },
      { kind: "note", instrument: "thud", when: 'ch("missed") > 0.5', hz: "110", dur: "0.45" },
    ],
    source:
`// A game. Up and down (or W and S) move the bat; the ball bounces, and the
// score is the bricks it has taken off the right wall. Everything lives in
// three texels of the state: the ball, the bat, and the score. Every other
// texel reads those three and draws.
//
// That is the whole Shadertoy trick — state in pixels, keys in a texture —
// and it is playable here because the sketch runtime binds u_keys the way
// the render graph does. Click the picture first so it has the keys.
//
// It also makes a sound, which a sketch has no way to do by itself: the
// third register holds what happened this frame, the document names those
// texels as probes, and the host reads them back and fires the notes. Turn
// Sound on.
uniform sampler2D u_keys;
uniform float speed;     // @range 0.2 2 @default 0.9 @help how fast the ball travels
uniform float batSpeed;  // @range 0.5 4 @default 2.2 @help how fast the bat moves
uniform float batLen;    // @range 0.1 0.5 @default 0.22 @help half the bat's height
uniform vec3 ink;        // @color @default #f4efe6
uniform vec3 hot;        // @color @default #ff7a3d

// The three registers, at the bottom-left corner of the state.
vec4 ball() { return state(vec2(0.5, 0.5) / u_resolution); }   // xy = position, zw = velocity
vec4 bat()  { return state(vec2(1.5, 0.5) / u_resolution); }   // x = height, y = score
float ar() { return u_resolution.x / u_resolution.y; }

vec4 sim(vec2 uv) {
  vec2 texel = floor(gl_FragCoord.xy);
  float up   = max(keyDown(u_keys, 38.0), keyDown(u_keys, 87.0));
  float down = max(keyDown(u_keys, 40.0), keyDown(u_keys, 83.0));
  float A = ar();

  vec4 b = frame == 0 ? vec4(0.0, 0.0, -speed, speed * 0.55) : ball();
  vec4 s = frame == 0 ? vec4(0.0, 0.0, 0.0, 0.0) : bat();
  float dt = 1.0 / 60.0;

  // The bat, clamped to the court.
  float h = clamp(s.x + (up - down) * batSpeed * dt, -1.0 + batLen, 1.0 - batLen);

  vec2 pos = b.xy + b.zw * dt;
  vec2 vel = b.zw;
  float hitBat = 0.0, hitWall = 0.0, missed = 0.0;
  if (pos.y >  1.0) { pos.y =  1.0; vel.y = -vel.y; }          // ceiling
  if (pos.y < -1.0) { pos.y = -1.0; vel.y = -vel.y; }          // floor
  if (pos.x >  A - 0.04) { pos.x = A - 0.04; vel.x = -vel.x; s.y += 1.0; hitWall = 1.0; }
  // The bat: a hit takes the angle from where on the bat it landed.
  float batX = -A + 0.09;
  if (pos.x < batX && vel.x < 0.0) {
    if (abs(pos.y - h) < batLen) {
      pos.x = batX; vel.x = -vel.x;
      vel.y += (pos.y - h) / batLen * speed * 0.6;
      vel = normalize(vel) * length(vec2(speed, speed * 0.55));
      hitBat = 1.0;
    } else if (pos.x < -A - 0.2) {                              // missed: serve again
      pos = vec2(0.0); vel = vec2(-speed, speed * 0.55); s.y = 0.0;
      missed = 1.0;
    }
  }
  if (texel == vec2(0.0)) return vec4(pos, vel);
  if (texel == vec2(1.0, 0.0)) return vec4(h, s.y, 0.0, 1.0);
  // The third register is what *happened* this frame, for whoever is
  // listening: hit the bat, hit the wall, missed. A shader has no other way
  // to tell anyone, and the host reads exactly these three numbers back.
  if (texel == vec2(2.0, 0.0)) return vec4(hitBat, hitWall, missed, 1.0);
  return vec4(0.0);
}

float A = ar();
vec2 q = p;
vec4 b = ball();
vec4 s = bat();

float d = length(q - b.xy) - 0.035;                              // the ball
float dbat = sdBox(q - vec2(-A + 0.06, s.x), vec2(0.02, batLen)); // the bat
float dwall = sdBox(q - vec2(A - 0.03, 0.0), vec2(0.03, 1.0));    // the wall it scores off

vec3 col = vec3(0.04, 0.05, 0.09);
col = mix(col, hot, aa(d));
col = mix(col, ink, aa(dbat));
col = mix(col, ink * 0.35, aa(dwall));
// The score, as a stack of marks up the right-hand side.
float rows = min(s.y, 24.0);
float mark = sdBox(vec2(abs(q.x - (A - 0.1)), mod(q.y + 1.0, 0.16) - 0.08), vec2(0.03, 0.03));
if (q.y < -1.0 + rows * 0.16) col = mix(col, hot, aa(mark));
col`
  },
  { id: "life", label: "Life, with a trail", preview: [640, 640], steps: 1, source:
`uniform float pace;      // @range 1 12 step 1 @default 4 — frames per generation
uniform vec3  alive;     // @color @default 0.95 0.90 0.60
uniform vec3  trail;     // @color @default 0.30 0.10 0.40

// Conway's rule on the red channel; the green channel remembers how long a
// cell has been dead, which is the trail. Press to paint cells alive.
vec4 sim(vec2 q) {
  vec4 c = prevAt(vec2(0.0));
  if (frame < 1) return vec4(step(0.72, hash21(floor(gl_FragCoord.xy) + seed)), 0.0, 0.0, 1.0);
  float paint = md * step(length((q - m) * vec2(u_resolution.x / u_resolution.y, 1.0)), 0.03)
              * step(0.5, hash21(gl_FragCoord.xy + float(frame)));
  if (mod(float(frame), pace) > 0.5) return vec4(max(c.r, paint), c.g, 0.0, 1.0);
  float n = 0.0;
  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
    if (x == 0 && y == 0) continue;
    n += step(0.5, prevAt(vec2(float(x), float(y))).r);
  }
  float was = step(0.5, c.r);
  float now = (was > 0.5 && (n == 2.0 || n == 3.0)) || (was < 0.5 && n == 3.0) ? 1.0 : 0.0;
  now = max(now, paint);
  float age = now > 0.5 ? 0.0 : min(c.g + 1.0 / 60.0, 1.0);
  return vec4(now, age, 0.0, 1.0);
}

vec4 sv = state(uv);
vec3 col = mix(srgbToLinear(trail) * (1.0 - sv.g), vec3(0.02), smoothstep(0.0, 1.0, sv.g));
col = mix(col, srgbToLinear(alive), sv.r);

finish(col)` },

  { id: "ink", label: "Ink carried in a flow", preview: [800, 450], steps: 1, source:
`uniform float swirl;     // @range 0.2 3 @default 1.2 — how tight the eddies are
uniform float flow;      // @range 0 2 @default 0.8 — how fast it moves
uniform float fade;      // @range 0.9 1.0 @default 0.995
uniform vec3  ink1;      // @color @default 0.90 0.30 0.10
uniform vec3  ink2;      // @color @default 0.10 0.40 0.90

// Dye advected by a divergence-free field — the curl of a noise potential —
// so it swirls without piling up. Back-trace one step and read what was there.
// This is advection done honestly; it is not a pressure solve.
vec2 velocity(vec2 q) {
  float e = 0.01;
  vec2 s = q * swirl + vec2(0.0, t * 0.05);
  float dx = fbm(s + vec2(e, 0.0)) - fbm(s - vec2(e, 0.0));
  float dy = fbm(s + vec2(0.0, e)) - fbm(s - vec2(0.0, e));
  vec2 v = vec2(dy, -dx) / (2.0 * e) * 0.15;                       // curl
  vec2 toMouse = q - (m * 2.0 - 1.0) * vec2(u_resolution.x / u_resolution.y, 1.0);
  v += md * normalize(toMouse + 1e-4) * exp(-dot(toMouse, toMouse) * 30.0) * 0.6;
  return v * flow;
}
vec4 sim(vec2 q) {
  if (frame < 1) return vec4(0.0, 0.0, 0.0, 1.0);
  vec2 aspect = vec2(u_resolution.x / u_resolution.y, 1.0);
  vec2 pos = (q * 2.0 - 1.0) * aspect;
  vec2 back = pos - velocity(pos) * (1.0 / 60.0) * 8.0;
  vec4 c = prev((back / aspect) * 0.5 + 0.5) * fade;
  // two sources breathe ink in on the left and right
  float a = smoothstep(0.08, 0.0, length(pos - vec2(-aspect.x * 0.6, 0.35 * sin(t * 0.7))));
  float b = smoothstep(0.08, 0.0, length(pos - vec2( aspect.x * 0.6, -0.35 * sin(t * 0.9))));
  c.rgb += srgbToLinear(ink1) * a * 0.08 + srgbToLinear(ink2) * b * 0.08;
  c.rgb += md * srgbToLinear(mix(ink1, ink2, 0.5)) * exp(-length(pos - (m * 2.0 - 1.0) * aspect) * 40.0) * 0.1;
  return vec4(min(c.rgb, 4.0), 1.0);
}

vec3 col = state(uv).rgb + vec3(0.02, 0.02, 0.03);

finish(col)` },

  { id: "fluid", label: "Fluid — velocity and dye, on two targets", preview: [640, 640], steps: 2, source:
`// Two fields, two targets. The first state holds a velocity field; the
// second holds the dye being carried through it. Packing both into one RGBA
// is the usual trick and it always hurts — four channels between a vector
// and a colour. Defining sim2() as well as sim() asks for a second target,
// which WebGL2 gives as standard, and then each field has its own four.
//
// sim()  -> the velocity, read back with state()
// sim2() -> the dye, read back with state2()
// @module 07-shaders
uniform float swirl;     // @range 0 3 @default 1.4 @help how hard the curl of the noise pushes
uniform float damp;      // @range 0.9 1 @default 0.985 @help how fast the motion dies away
uniform float inject;    // @range 0 1 @default 0.55 @help dye put in at the pointer, and at the start
uniform float fade;      // @range 0.9 1 @default 0.994 @help how long the dye lasts

// The curl of a noise field: divergence-free, so it stirs without pumping.
vec2 curlNoise(vec2 p) {
  float e = 0.06;
  float n1 = fbm(p + vec2(0.0, e)), n2 = fbm(p - vec2(0.0, e));
  float n3 = fbm(p + vec2(e, 0.0)), n4 = fbm(p - vec2(e, 0.0));
  return vec2(n1 - n2, n4 - n3) / (2.0 * e);
}

vec4 sim(vec2 q) {
  if (frame == 0) return vec4(0.0);
  // Semi-Lagrangian advection: look back along the velocity and take what
  // was there.
  vec2 v = state(q).xy;
  vec2 back = q - v / u_resolution;
  vec2 carried = texture2D(u_state, back).xy;
  vec2 force = curlNoise(q * 3.0 + vec2(t * 0.05, 0.0)) * swirl;
  vec2 push = (m - q) * md * 40.0;
  return vec4((carried + force * 0.02 + push) * damp, 0.0, 1.0);
}

vec4 sim2(vec2 q) {
  vec2 v = state(q).xy;
  vec4 dye = texture2D(u_state2, q - v / u_resolution);
  if (frame == 0) {
    float ring = smoothstep(0.34, 0.3, length(q - 0.5));
    return vec4(palette(q.x + q.y, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67)) * ring, 1.0);
  }
  // A standing source, so it keeps going without anyone touching it, and
  // the pointer as a second one for when they do.
  vec2 spout = 0.5 + 0.3 * vec2(cos(t * 0.61), sin(t * 0.83));
  float at = smoothstep(0.055, 0.0, length(q - spout)) * inject
           + smoothstep(0.09, 0.0, length(q - m)) * md * inject;
  vec3 ink = palette(t * 0.2, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
  return vec4(mix(dye.rgb * fade, ink, clamp(at, 0.0, 1.0)), 1.0);
}

vec3 dye = state2(uv).rgb;
vec2 v = state(uv).xy;
// A little of the motion in the shading, so the field is visible as well as
// its effect: bright where it is moving fast.
finish(srgbToLinear(dye) * (1.0 + length(v) * 0.05))` },

  { id: "clipink", label: "Video — ink stirred out of the picture", preview: [640, 360], steps: 6, source:
`// Ink stirred out of what the picture is showing: the frame seeds a flow,
// the flow carries it, and the result is mixed back over the frame. Written
// to be a clip effect — the layer or clip arrives as \`src\`, and because the
// state is rebuilt from that seed every frame, the same frame always comes
// out the same way, which is what an export needs.
// @module 07-shaders
uniform sampler2D src;     // the clip, or the layer
uniform float stir;        // @range 0 4 @default 1.6 @help how far the flow carries the ink each step
uniform float spread;      // @range 0 2 @default 0.9 @help how much it diffuses as it goes
uniform float amount;      // @range 0 1 @default 0.6 @help how much of it you see over the picture

vec2 flow(vec2 q) {
  float a = fbm(q * 2.5 + vec2(t * 0.07, -t * 0.05)) * 6.28318;
  return vec2(cos(a), sin(a)) * stir;
}

vec4 sim(vec2 q) {
  vec4 seed = texture2D(src, q);
  if (frame == 0) return seed;
  vec4 carried = texture2D(u_state, q - flow(q) / u_resolution);
  vec4 spread4 = (stateAt(vec2(1.0, 0.0)) + stateAt(vec2(-1.0, 0.0))
                + stateAt(vec2(0.0, 1.0)) + stateAt(vec2(0.0, -1.0))) * 0.25;
  return mix(carried, spread4, spread * 0.3) * 0.995 + seed * 0.02;
}

vec3 c = texture2D(src, uv).rgb;
vec3 ink = state(uv).rgb;
mix(c, max(c * 0.6, ink), amount)` },

  { id: "trails", label: "Trails — feedback without a sim", preview: [640, 640], source:
`uniform float persist;   // @range 0.8 0.995 @default 0.96 — how long a trail lasts
uniform float zoom;      // @range 0.98 1.02 @default 1.004 — feedback zoom per frame
uniform float turn;      // @range -0.05 0.05 @default 0.008 — feedback rotation per frame
uniform vec3  ink;       // @color @default 1.0 0.7 0.3

// No sim(): u_prev is simply the last picture. Read it slightly zoomed and
// turned, fade it, and draw this frame's orb on top. The classic feedback.
vec2 c = (rot(turn) * (uv - 0.5)) / zoom + 0.5;
vec3 last = prev(c).rgb * persist;
vec2 orb = vec2(0.5) + 0.32 * vec2(cos(t * 1.3), sin(t * 2.1)) * vec2(1.0, u_resolution.x / u_resolution.y);
float d = length((uv - orb) * vec2(u_resolution.x / u_resolution.y, 1.0));
vec3 col = last + ink * smoothstep(0.03, 0.0, d) * 1.5;
col += md * ink.bgr * smoothstep(0.05, 0.0, length((uv - m) * vec2(u_resolution.x / u_resolution.y, 1.0)));

clamp(col, 0.0, 1.0)` },

  // ---- the shape compiler's own idiom, written by hand. This is what a
  // design or an SVG turns into, so it is the thing to read when you want to
  // edit one — and the three knobs at the top are the ones every compile emits.

  { id: "mark", label: "Logo mark — booleans and offsets", preview: [800, 450], source:
`uniform float inflate;  // @range -20 20 @default 0 — offset every edge (px)
uniform float outline;  // @range 0 14 @default 0 — stroke every shape (px)
uniform float round;    // @range 0 40 @default 18 — how softly the parts merge
uniform float gap;      // @range 0 40 @default 14 — counter-space
uniform vec3  ink;      // @color @default 0.10 0.17 0.29
uniform vec3  accent;   // @color @default 1.0 0.48 0.24
uniform vec3  paper;    // @color @default 0.96 0.93 0.86

// A mark built the way a distance field wants: union with smin so parts fuse,
// subtraction with max(-d) to cut a counter, abs(d) - w for an outline. Every
// one of these is a thing SVG cannot say, which is the argument for compiling
// to this rather than exporting from it.
const vec2 FRAME = vec2(800.0, 450.0);
float cov(float d, float px) { return smoothstep(0.75 * px, -0.75 * px, d); }

float body(vec2 q) {
  float stem = sdBox(q - vec2(-70.0, 0.0), vec2(26.0, 110.0));
  float bowl = sdCircle(q - vec2(30.0, -34.0), 78.0);
  float foot = sdCapsule(q, vec2(-70.0, 96.0), vec2(96.0, 96.0), 24.0);
  float d = smin(stem, bowl, round);
  d = smin(d, foot, round * 0.6);
  return max(d, -(sdCircle(q - vec2(34.0, -38.0), 34.0) - gap * 0.25));   // the counter
}
float spark(vec2 q) {
  vec2 r = rot(0.785) * (q - vec2(112.0, -104.0));
  return min(sdBox(r, vec2(5.0, 30.0)), sdBox(r, vec2(30.0, 5.0)));
}

vec2 q = (vec2(uv.x, 1.0 - uv.y) - 0.5) * FRAME;
float px = FRAME.y / u_resolution.y;

float d = body(q) - inflate;
float s = spark(q) - inflate;
vec3 col = paper;
col = mix(col, ink, cov(d, px));
col = mix(col, accent, cov(s, px));
if (outline > 0.0) {
  col = mix(col, ink, cov(abs(d) - outline * 0.5, px));
  col = mix(col, accent, cov(abs(s) - outline * 0.5, px));
}

col` },

  { id: "poster", label: "Poster in code — dashes and joins", preview: [800, 500], source:
`uniform float dashLen;  // @range 4 60 @default 26 — dash length (px)
uniform float dashGap;  // @range 2 40 @default 14
uniform float phase;    // @range 0 1 @default 0 — where the pattern starts
uniform float weight;   // @range 2 20 @default 7 — rule weight (px)
uniform vec3  ink;      // @color @default 0.10 0.17 0.29
uniform vec3  accent;   // @color @default 0.69 0.23 0.36
uniform vec3  paper;    // @color @default 0.96 0.94 0.90

// Dashes along a line, done the way a field can: measure arc length, then use
// mod() to decide whether this point is in a dash or a gap. The SVG compiler
// does the same by cutting the polyline at compile time — this is the same
// idea in one expression, and it animates for free.
const vec2 FRAME = vec2(800.0, 500.0);
float cov(float d, float px) { return smoothstep(0.75 * px, -0.75 * px, d); }

// A dashed segment: distance to the line, cut into dashes by position along it.
float dashedSeg(vec2 q, vec2 a, vec2 b, float w) {
  vec2 ab = b - a;
  float len = length(ab);
  vec2 dir = ab / len;
  float t = clamp(dot(q - a, dir), 0.0, len);
  float dLine = length(q - (a + dir * t)) - w * 0.5;
  float period = dashLen + dashGap;
  float on = step(mod(t + phase * period, period), dashLen);
  return mix(1e5, dLine, on);
}
// A mitred corner: the two arms, plus the wedge that fills the outside.
float elbow(vec2 q, vec2 a, vec2 v, vec2 b, float w) {
  float d = min(sdSegment(q, a, v), sdSegment(q, v, b)) - w * 0.5;
  vec2 e1 = normalize(v - a), e2 = normalize(b - v);
  vec2 n1 = vec2(-e1.y, e1.x), n2 = vec2(-e2.y, e2.x);
  float s = (e1.x * e2.y - e1.y * e2.x) > 0.0 ? -1.0 : 1.0;
  n1 *= s; n2 *= s;
  vec2 m = normalize(n1 + n2);
  float wedge = max(max(dot(q - v, n1) - w * 0.5, dot(q - v, n2) - w * 0.5), -dot(q - v, m));
  return min(d, wedge);
}

vec2 q = vec2(uv.x, 1.0 - uv.y) * FRAME;
float px = FRAME.y / u_resolution.y;
vec3 col = paper;

col = mix(col, ink, cov(sdBox(q - vec2(400.0, 96.0), vec2(300.0, 2.0)), px));
col = mix(col, accent, cov(dashedSeg(q, vec2(100.0, 150.0), vec2(700.0, 150.0), weight), px));
col = mix(col, ink,    cov(dashedSeg(q, vec2(100.0, 190.0), vec2(700.0, 190.0), weight * 0.5), px));
col = mix(col, ink,    cov(elbow(q, vec2(120.0, 380.0), vec2(300.0, 250.0), vec2(480.0, 380.0), weight * 2.0), px));
col = mix(col, accent, cov(elbow(q, vec2(520.0, 380.0), vec2(640.0, 260.0), vec2(700.0, 380.0), weight * 2.0), px));
col = mix(col, ink, cov(sdBox(q - vec2(400.0, 440.0), vec2(300.0, 1.0)), px));

col` },
];

export const newGenerateDoc = (preset = GENERATE_PRESETS[0]) => ({
  sketch: preset.source, preset: preset.id, uniforms: {}, seed: 0,
  preview: (preset.preview || [640, 640]).slice(), exportSize: [2048, 2048],
  simSteps: preset.steps || 1,
  // A sketch that wants to be heard says what to read out of its own state
  // and what to do about it. Absent, nothing is read and nothing sounds.
  ...(preset.probes ? { probes: preset.probes } : {}),
  ...(preset.effects ? { effects: preset.effects } : {}),
  ...(preset.instruments ? { instruments: preset.instruments } : {}),
});

const SIZES = [[512, 512], [640, 640], [800, 450], [1024, 576], [1080, 1080], [1080, 1920]];
// Sizes past a GPU's maximum are drawn in tiles, so the list is not bounded
// by what fits in one render any more.
const EXPORTS = [[1024, 1024], [2048, 2048], [4096, 4096], [8192, 8192], [16384, 16384],
                 [1920, 1080], [3840, 2160], [7680, 4320], [1080, 1920]];

export async function generateEditor(host) {
  const doc = host.data;
  doc.sketch ||= GENERATE_PRESETS[0].source;
  doc.uniforms ||= {};
  doc.seed ??= 0;
  doc.preview ||= [640, 640];
  doc.exportSize ||= [2048, 2048];
  doc.mode ||= "sketch";                 // "sketch" | "glsl"
  doc.simSteps ||= 1;

  // A sketch that declares `uniform sampler2D u_keys;` is played, not merely
  // watched. Attached to the canvas rather than the document, so typing in
  // the source does not also steer whatever is on screen.
  const keyboard = new Keyboard();
  const canvas = el("canvas", { width: doc.preview[0], height: doc.preview[1],
    style: { width: "100%", height: "auto", display: "block", background: "#000",
             borderRadius: "8px", cursor: "crosshair" } });
  const log = el("div.lab-log");
  const knobHost = el("div");
  const editor = el("textarea.editor", { spellcheck: false,
    value: doc.mode === "glsl" ? (doc.glsl || "") : doc.sketch,
    style: { minHeight: "420px" } });

  let gl = null, raf = null, t0 = performance.now();
  let lastFrameAt = 0;
  let display = null, sim = null;         // the two programs; sim is null without a state pass
  let quad = null;
  let uniforms = [];
  const textures = {};                    // sampler name -> {url, tex, w, h}
  let feedback = null;                    // Feedback instance, once GL exists
  const grid = gridOverlay();
  const mouse = [0.5, 0.5];
  let mouseDown = 0;
  let paused = false, pausedAt = 0;
  // The stage: the canvas and its overlay together, and the element that goes
  // fullscreen. Centred and letterboxed there, because a sketch has an aspect
  // and a screen has a different one.
  const stage = el("div", { style: { position: "relative", display: "flex",
                                     alignItems: "center", justifyContent: "center" } },
                   canvas, grid.overlay);
  const fpsLabel = el("span.fine");
  const stateLabel = el("span.fine");
  let frames = 0, lastFpsAt = performance.now();
  // The render scale. The canvas is styled `width: 100%`, so its backing store
  // and the size it is seen at are already two different things — rendering
  // fewer pixels and letting the browser scale them up costs one line here and
  // is the only lever that works on a sketch whose cost is the shader itself.
  const scaleSel = el("select", { style: { width: "auto" },
    title: "how many pixels the sketch actually renders; the canvas is shown at its full size either way" });
  let deltas = [];              // recent frame-to-frame times, for the auto scale
  let settled = false;          // auto has chosen, and stops choosing
  const wantScale = () => (doc.renderScale === undefined ? "auto" : doc.renderScale);
  const isFull = () => fs.isExpanded();
  /**
   * The size a render aims at before the scale is applied: the authored
   * preview normally, and the screen with the sketch's own aspect fitted into
   * it when fullscreen. Capped at 1920×1080 — past that the scale would just
   * take it back down again, and a 4K backing store for a raymarcher is
   * several seconds a frame rather than a nicer picture.
   */
  const baseSize = () => {
    if (!isFull()) return doc.preview;
    return fitAspect(doc.preview[0] / doc.preview[1],
                     Math.min(stage.clientWidth || screen.width, 1920),
                     Math.min(stage.clientHeight || screen.height, 1080));
  };
  // Entering or leaving changes what a full-size render *is* — the render aims
  // at the screen rather than the authored preview — so the scale is asked
  // again from scratch rather than carried across.
  const fs = expandButton(stage, {
    className: "",
    title: "show the render on its own. The state is the size of the picture, so this restarts a simulation",
    onRefused: (why) => { log.textContent = why; },
    onChange: () => rescale(),
  });
  const fsBtn = fs.button;
  const applyScale = (scale) => {
    const base = baseSize();
    const w = Math.max(16, Math.round(base[0] * scale));
    const h = Math.max(16, Math.round(base[1] * scale));
    if (canvas.width === w && canvas.height === h) return false;
    canvas.width = w; canvas.height = h;
    // The state is the size of the picture, so changing the size is the end of
    // this run of the simulation. Said plainly rather than left to look like a
    // glitch: the sketch restarts, once, at the start.
    if (feedback) { const [sw, sh] = stateSize(w, h); feedback.resize(sw, sh, feedback.channels || 1); }
    restart();
    return true;
  };
  const rescale = () => {
    deltas = []; settled = false;
    const s = wantScale();
    applyScale(s === "auto" ? 1 : s);
  };
  for (const [value, label] of [["auto", "scale: auto (60 fps)"],
                                ...SCALE_STEPS.map((v) => [String(v), `scale: ${Math.round(v * 100)}%`])]) {
    scaleSel.append(el("option", { value, selected: String(wantScale()) === value }, label));
  }
  // Coming back to the foreground throws the samples away and asks again —
  // the ones taken on the way out are the browser's rate, not the sketch's.
  const onVisible = () => { if (!document.hidden && wantScale() === "auto") { deltas = []; lastFrameAt = 0; } };
  document.addEventListener("visibilitychange", onVisible);
  scaleSel.onchange = (e) => {
    doc.renderScale = e.target.value === "auto" ? "auto" : Number(e.target.value);
    rescale();
    host.save();
  };

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = ((e.clientX - r.left) / r.width) * canvas.width;
    mouse[1] = (1 - (e.clientY - r.top) / r.height) * canvas.height;
  });
  canvas.addEventListener("pointerdown", (e) => { mouseDown = 1; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointerup", () => { mouseDown = 0; });
  canvas.addEventListener("pointercancel", () => { mouseDown = 0; });
  // Keys go to the canvas, and only while it has focus — clicking it is how
  // you pick the sketch up, and clicking away is how you put it down.
  canvas.tabIndex = 0;
  canvas.style.outline = "none";
  canvas.addEventListener("pointerdown", () => canvas.focus());
  keyboard.attach(canvas);
  canvas.addEventListener("blur", () => keyboard.clear());

  /** The full GLSL that runs — generated from the sketch, or yours. A sketch is
      emitted for the context: ES 3.00 on WebGL2, 1.00 otherwise. */
  let lastMapped = null;                     // the last sketch → GLSL map, for errors
  const es3 = () => !!(gl && isGL2(gl));
  const source = () => {
    if (doc.mode === "glsl") return doc.glsl || "";
    lastMapped = desugarMapped(doc.sketch, { es3: es3() });
    return lastMapped.source;
  };

  function ensureGL() {
    if (gl) return true;
    gl = getGL(canvas);
    if (!gl) { log.textContent = "WebGL is not available in this browser."; return false; }
    quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    feedback = new Feedback(gl);
    { const [sw, sh] = stateSize(); feedback.resize(sw, sh); }
    return true;
  }

  const link = (fragSrc) => linkProgram(gl, fragSrc);

  /** Compile the display program and, if the source has a state pass, the sim
      program too — from the same file, with SIM_PASS defined for the second. */
  function compile(src) {
    clear(log);
    if (!ensureGL()) return false;
    let d = null, s2 = null;
    let inSim = false;
    try {
      d = link(src);
      if (hasSimPass(src)) { inSim = true; s2 = link(withDefine(src, "SIM_PASS")); }
    } catch (e) {
      // Keep the last working programs: a shader that fails to compile should
      // not blank the thing you were looking at.
      if (d) gl.deleteProgram(d);
      let msg = String(e.message).trim();
      if (doc.mode === "sketch" && lastMapped) {
        // Errors arrive against the generated file; say them in sketch lines.
        // The sim program has one extra line (the define) after any #version.
        if (inSim) msg = msg.replace(/(ERROR|WARNING):\s*(\d+):(\d+):/g,
          (m, k, a, b) => `${k}: ${a}:${Math.max(1, +b - 1)}:`);
        msg = mapErrors(msg, lastMapped, doc.sketch);
      } else if (inSim) {
        msg = msg.replace(/(ERROR|WARNING):\s*(\d+):(\d+):/g,
          (m, k, a, b) => `${k}: ${a}:${Math.max(1, +b - 1)}:`);
      }
      log.textContent = msg;
      return false;
    }
    if (display) gl.deleteProgram(display);
    if (sim) gl.deleteProgram(sim);
    display = d; sim = s2;
    // Two fields if the sketch defines sim2(); the buffers are rebuilt on the
    // next draw, and describe() then says whether the GPU actually gave two.
    wantChannels = s2 && dualTargets(src) ? 2 : 1;
    const [sw, sh] = stateSize();
    if (feedback.channels !== wantChannels) feedback.resize(sw, sh, wantChannels);
    stateLabel.textContent = sim ? `sim · ${feedback.describe()}` : (es3() ? "WebGL2 · ES 3.00" : "WebGL1 · ES 1.00");
    return true;
  }

  /**
   * How big the state is. A sketch may say with `@state W H`; otherwise it is
   * the size of the picture, as it always was.
   *
   * This is the whole of the memory answer. A float state pair with two
   * targets is w×h×16 bytes four times over: at 1920×1080 that is 132 MB for
   * what is usually a dozen registers and a height map of a fixed piece of
   * ground. Neither gets better by being the size of the window.
   */
  const stateSize = (w, h) => {
    const said = doc.mode === "glsl" ? null : sketchMeta(doc.sketch || "").state;
    return said ? [Math.max(1, said[0]), Math.max(1, said[1])]
                : [w || canvas.width, h || canvas.height];
  };

  let forcedTime = null;                  // set during an offline export
  let exporting = false;
  const timeNow = () => forcedTime !== null ? forcedTime
                      : paused ? pausedAt : (performance.now() - t0) / 1000;

  /** Set everything both passes share, then bind the feedback textures on the
      last two units — user images take the first ones. */
  function setCommon(prog, prevTex, stateTex, stateTex2, asState = false) {
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    // A tile draws at its own size and thinks in the whole picture's, so a
    // render past the GPU's maximum comes out identical to one that fitted.
    // In the state pass the resolution *is* the state's, so a sketch's
    // `gl_FragCoord.xy / u_resolution` still sweeps 0..1 across it however big
    // the picture happens to be.
    const res = asState ? [feedback.w, feedback.h] : (tileRes || [canvas.width, canvas.height]);
    gl.uniform2f(u("u_resolution"), res[0], res[1]);
    gl.uniform2f(u("u_state_size"), feedback.w, feedback.h);
    gl.uniform2f(u("u_origin"), tileOrigin[0], tileOrigin[1]);
    gl.uniform2f(u("u_mouse"), mouse[0], mouse[1]);
    gl.uniform1f(u("u_time"), timeNow());
    gl.uniform1f(u("u_seed"), doc.seed);
    gl.uniform1i(u("u_frame"), feedback.frame);
    gl.uniform1f(u("u_mouseDown"), mouseDown);
    applyUniforms(gl, prog, uniforms, doc.uniforms);
    bindTextures(gl, prog, uniforms, doc.uniforms, textures);
    gl.activeTexture(gl.TEXTURE6);
    gl.bindTexture(gl.TEXTURE_2D, prevTex);
    if (u("u_prev")) gl.uniform1i(u("u_prev"), 6);
    gl.activeTexture(gl.TEXTURE7);
    gl.bindTexture(gl.TEXTURE_2D, stateTex);
    if (u("u_state")) gl.uniform1i(u("u_state"), 7);
    // The second field, for a sim that keeps two. Where there is none it
    // reads the first, so a sketch written for two still draws something.
    gl.activeTexture(gl.TEXTURE5);
    gl.bindTexture(gl.TEXTURE_2D, stateTex2 || stateTex);
    if (u("u_state2")) gl.uniform1i(u("u_state2"), 5);
    // The keyboard, so a sketch here can be played rather than only watched.
    // Unit 4 is the one left between the sketch's own images and the state.
    if (u("u_keys")) {
      gl.activeTexture(gl.TEXTURE4);
      gl.bindTexture(gl.TEXTURE_2D, keysTexture());
      gl.uniform1i(u("u_keys"), 4);
    }
    gl.activeTexture(gl.TEXTURE0);
  }

  // ---------------------------------------------------------------- sound
  //
  // Off until asked for, like the playground's: an AudioContext needs a
  // gesture, and a page that starts humming on its own is one you close.
  let rig = null, wantSound = false, soundNotes = 0, soundSaid = "";
  const soundBtn = el("button", { hidden: !hasSketchEffects(doc) }, "Sound: off");
  soundBtn.onclick = async () => {
    wantSound = !wantSound;
    soundBtn.textContent = wantSound ? "Sound: on" : "Sound: off";
    if (!wantSound) { if (rig) { await rig.close(); rig = null; } return; }
    try {
      rig = await LiveRig.create({ instruments: doc.instruments });
      await rig.resume();
    } catch (e) { soundSaid = String(e.message).split("\n")[0]; wantSound = false; soundBtn.textContent = "Sound: off"; }
  };

  function soundFrame() {
    if (!wantSound || !rig || !sim || !hasSketchEffects(doc)) return;
    try {
      // The state the sim just wrote is the one to look at.
      const { fired, errors } = sketchFrame(gl, doc, feedback.read, {
        stateKey: `generate-${host.doc.id || "doc"}`,
        width: canvas.width, height: canvas.height,
        time: timeNow(), frame: feedback.frame, keys: keyboard,
      });
      soundSaid = errors[0] || "";
      if (fired.length) soundNotes += rig.perform(fired);
    } catch (e) { soundSaid = String(e.message).split("\n")[0]; }
  }

  let keysTex = null;
  function keysTexture() {
    if (!keysTex) {
      keysTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, keysTex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    }
    gl.bindTexture(gl.TEXTURE_2D, keysTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, keyboard.texture());
    return keysTex;
  }

  // Decided when the program is compiled, not per frame: desugaring the
  // sketch to ask is not something to do sixty times a second.
  let wantChannels = 1;
  let tileOrigin = [0, 0], tileRes = null;

  /** One state step: read a, write b, swap. */
  function stepSim() {
    const w = feedback.write, r = feedback.read;
    gl.bindFramebuffer(gl.FRAMEBUFFER, w.fbo);
    gl.viewport(0, 0, feedback.w, feedback.h);
    setCommon(sim, r.tex, r.tex, r.tex2, true);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    feedback.swap();
  }

  /** The picture. Without a sim, u_prev is last frame's picture and this
      frame's is captured for next time. */
  function draw() {
    if (!display || !gl) return;
    // The channel count matters as much as the size: a sketch that grew a
    // sim2() needs a second target, and a resize that only checks dimensions
    // would leave state2() reading the first field.
    const [sw, sh] = stateSize();
    if (feedback.w !== sw || feedback.h !== sh || feedback.channels !== wantChannels) {
      feedback.resize(sw, sh, wantChannels);
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    if (sim) setCommon(display, feedback.write.tex, feedback.read.tex, feedback.read.tex2);
    else setCommon(display, feedback.prevTex, feedback.prevTex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!sim) feedback.captureCanvas();
  }

  function frame() {
    if (exporting) { raf = requestAnimationFrame(frame); return; }
    if (display && gl && !paused) {
      if (sim) for (let i = 0; i < doc.simSteps; i++) stepSim();
      draw();
      soundFrame();
      // "Went down this frame" lasts exactly one frame, whatever the sim
      // step count is — so it is cleared here rather than inside stepSim.
      keyboard.tick();
    } else if (display && gl) {
      draw();
    }
    frames++;
    const now = performance.now();
    // Auto: watch a couple of dozen frames at full size, then pick the scale
    // that fits the budget and stop. Adapting continuously would resize the
    // state texture — which is the simulation — every time the view got busy.
    // Not while the tab is in the background: a hidden document's animation
    // frames arrive at whatever rate the browser feels like — five a second
    // here — and a scale chosen from that is a measurement of the browser.
    if (!settled && wantScale() === "auto" && display && gl && !paused && !document.hidden) {
      if (lastFrameAt) deltas.push(now - lastFrameAt);
      if (deltas.length >= 24) {
        const sorted = deltas.slice(4).sort((a, b) => a - b);
        const median = sorted[sorted.length >> 1];
        const scale = scaleForBudget(median, canvas.width / baseSize()[0]);
        settled = true;
        applyScale(scale);
      }
    }
    lastFrameAt = now;
    if (now - lastFpsAt > 500) {
      if (hasSketchEffects(doc)) {
        soundBtn.hidden = false;
        soundBtn.title = soundSaid || (wantSound ? `${soundNotes} notes so far` : "");
      }
      const base = baseSize();
      const scale = canvas.width / base[0];
      fpsLabel.textContent =
        `${Math.round((frames * 1000) / (now - lastFpsAt))} fps · ${canvas.width}×${canvas.height}`
        + (scale < 0.999 ? ` · ${Math.round(scale * 100)}% of ${base[0]}×${base[1]}` : "");
      frames = 0; lastFpsAt = now;
    }
    raf = requestAnimationFrame(frame);
  }

  /** A picked file — image or video — becomes a studio asset; the value is
      its capability URL. */
  async function onImage(u, file) {
    const kind = (file.type || "").startsWith("video/") ? "video" : "image";
    const asset = await host.upload(file, { role: "texture", uniform: u.name, kind });
    const dims = await mediaDims(asset.url, kind);
    return { url: asset.url, assetId: asset.id, kind, w: dims[0], h: dims[1] };
  }

  function rebuildControls() {
    clear(knobHost);
    knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save(), { onImage }));
  }

  /** Re-read the source: rebuild the controls, then recompile. The sim keeps
      its state across a recompile, so you can tune a rule while it runs. */
  function run(save = true) {
    if (doc.mode === "glsl") doc.glsl = editor.value; else doc.sketch = editor.value;
    uniforms = parseUniforms(editor.value);
    rebuildControls();
    const ok = compile(source());
    if (ok && save) host.save(thumbnail());
    return ok;
  }

  function restart() {
    t0 = performance.now(); pausedAt = 0;
    if (feedback) feedback.reset();
  }

  function thumbnail() {
    try {
      const t = document.createElement("canvas");
      t.width = 240; t.height = Math.round((240 * canvas.height) / canvas.width);
      t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
      return t.toDataURL("image/jpeg", 0.7);
    } catch { return ""; }
  }

  /** Render once at the export size. A simulation is its state, and its state
      is the preview's size — so with feedback in play the export is that size,
      not resampled to something the sim never ran at. */
  /**
   * Does this sketch read the last frame?
   *
   * Not a question to ask of the generated source: every prelude declares
   * u_prev and every helper set defines prev(), so testing that says yes to
   * everything — which is why an export has been quietly falling back to the
   * preview size for every document, whatever size was chosen. Ask the text
   * the author actually wrote, with the two helpers' own definitions taken
   * out first so their bodies do not answer for them.
   */
  function readsPrevFrame() {
    const src = stripComments(doc.mode === "glsl" ? (doc.glsl || "") : (doc.sketch || ""));
    const withoutHelpers = src
      .replace(/vec4\s+prev\s*\(\s*vec2[^)]*\)\s*\{[^}]*\}/g, " ")
      .replace(/vec4\s+prevAt\s*\(\s*vec2[^)]*\)\s*\{[^}]*\}/g, " ");
    return /\btexture2?D?\s*\(\s*u_prev\b|\bprev\s*\(|\bprevAt\s*\(/.test(withoutHelpers);
  }

  function exportPng() {
    const usesFeedback = !!sim || readsPrevFrame();
    let [w, h] = doc.exportSize;
    const maxDim = gl ? Math.min(gl.getParameter(gl.MAX_TEXTURE_SIZE),
                                 gl.getParameter(gl.MAX_VIEWPORT_DIMS)[0]) : 4096;
    if (usesFeedback) { w = canvas.width; h = canvas.height; }
    // Past the GPU's maximum the picture is drawn in tiles. A simulation
    // cannot be: a sim reads its neighbours, and a tile's neighbours are in
    // the next tile — so those still export at the size their state is.
    if (!usesFeedback && (w > maxDim || h > maxDim)) return exportTiled(w, h, maxDim);
    // 2×2 supersampling where the GPU has room: render at double size, then
    // average down. Hard edges — foam lines, grass, board rails — are where a
    // single sample per pixel reads as cheap. Capped so a 4096 export does
    // not ask for a 268 MB drawing buffer.
    const ss = !usesFeedback && doc.ssaa !== false && w * 2 <= maxDim && h * 2 <= maxDim
             && w * h <= 2048 * 2048 ? 2 : 1;
    const [pw, ph] = [canvas.width, canvas.height];
    let url;
    if (usesFeedback) {
      // Draw the current state once more (no step) and read it back.
      draw();
      try { url = canvas.toDataURL("image/png"); } catch { toast("Could not read the canvas back."); }
    } else {
      canvas.width = w * ss; canvas.height = h * ss;
      // The feedback storage tracks the canvas; a plain picture never reads it,
      // so a temporary resize costs a reallocation and nothing else.
      draw();
      try {
        if (ss === 1) url = canvas.toDataURL("image/png");
        else {
          const out = document.createElement("canvas");
          out.width = w; out.height = h;
          const cx = out.getContext("2d");
          cx.imageSmoothingEnabled = true;
          cx.imageSmoothingQuality = "high";
          cx.drawImage(canvas, 0, 0, w, h);
          url = out.toDataURL("image/png");
        }
      } catch { toast("Could not read the canvas back."); }
      canvas.width = pw; canvas.height = ph;
      draw();
    }
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${host.doc.name || "generate"}-${w}x${h}.png`;
    a.click();
    toast(`Exported ${w}×${h}${ss > 1 ? ", 2× supersampled" : ""}${usesFeedback ? " (a simulation exports at its own size)" : ""}.`);
  }

  /**
   * Every frame as a PNG, in a zip. Stored rather than deflated, because a
   * PNG is already compressed and running it through deflate again costs
   * time for nothing. The archive is stamped with a fixed date so the same
   * run produces the same bytes.
   */
  async function frameSequence(frames, fps, W, H, ui) {
    exporting = true;
    const [pw, ph] = [canvas.width, canvas.height];
    if (W !== pw || H !== ph) { canvas.width = W; canvas.height = H; }
    const files = [];
    const pad = String(frames - 1).length;
    try {
      for (let f = 0; f < frames; f++) {
        if (ui.cancelled()) break;
        forcedTime = f / fps;
        await seekVideos(textures, forcedTime);
        if (sim) for (let i = 0; i < doc.simSteps; i++) stepSim();
        draw();
        files.push({ name: `frame_${String(f).padStart(pad, "0")}.png`, bytes: await pngBytes(canvas) });
        if (f % 4 === 0) {
          ui.status.textContent = `Frame ${f + 1} of ${frames}…`;
          ui.bar.firstChild.style.width = `${Math.round((100 * f) / frames)}%`;
          await new Promise((r) => setTimeout(r, 0));
        }
      }
      if (ui.cancelled()) return;
      ui.status.textContent = "Writing the archive…";
      await new Promise((r) => setTimeout(r, 0));
      const blob = zipStore(files);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${host.doc.name || "generate"}-${W}x${H}-${fps}fps.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
      closeModal();
      toast(`Exported ${files.length} frames, ${(blob.size / 1e6).toFixed(1)} MB.`);
    } catch (e) {
      ui.status.textContent = `Frames failed: ${String(e.message).split("\n")[0]}`;
    } finally {
      exporting = false; forcedTime = null;
      canvas.width = pw; canvas.height = ph;
      draw();
    }
  }

  /**
   * A render larger than the GPU will do in one go: draw it in pieces, each
   * one told where it sits, and put them together on a 2D canvas. Identical
   * to an untiled render rather than merely close, because every tile is
   * given the whole picture's resolution and its own corner.
   */
  function exportTiled(w, h, maxDim) {
    const step = Math.min(maxDim, 2048);
    const out = document.createElement("canvas");
    out.width = w; out.height = h;
    const cx = out.getContext("2d");
    const [pw, ph] = [canvas.width, canvas.height];
    const tiles = Math.ceil(w / step) * Math.ceil(h / step);
    toast(`Rendering ${w}×${h} in ${tiles} tiles…`);
    try {
      tileRes = [w, h];
      for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
          const tw = Math.min(step, w - x), th = Math.min(step, h - y);
          if (canvas.width !== tw || canvas.height !== th) { canvas.width = tw; canvas.height = th; }
          // u_origin counts from the bottom, as gl_FragCoord does.
          tileOrigin = [x, h - y - th];
          draw();
          cx.drawImage(canvas, x, y);
        }
      }
    } catch (e) {
      toast(`Tiled export failed: ${String(e.message).split("\n")[0]}`);
      return;
    } finally {
      tileRes = null; tileOrigin = [0, 0];
      canvas.width = pw; canvas.height = ph;
      draw();
    }
    const a = document.createElement("a");
    a.href = out.toDataURL("image/png");
    a.download = `${host.doc.name || "generate"}-${w}x${h}.png`;
    a.click();
    toast(`Exported ${w}×${h} in ${tiles} tiles — past this GPU's ${maxDim}px limit.`);
  }

  /**
   * Render a run of frames at a fixed clock and write an MP4. Nothing is
   * recorded off the screen: each frame is drawn for exactly t = i/fps, a
   * sim is stepped once per frame (times steps/frame), and video textures
   * are seeked to that instant — so the file is the same every time.
   */
  function exportVideo() {
    if (!display || !gl) { toast("Nothing compiled to export."); return; }
    const durIn = el("input", { type: "number", min: 1, max: 120, step: 1, value: doc.videoSecs || 6,
      style: { width: "5rem" } });
    const fpsSel = el("select", {}, ...[24, 30, 60].map((f) =>
      el("option", { value: f, selected: f === (doc.videoFps || 30) }, `${f} fps`)));
    const usesFeedback = !!sim || readsPrevFrame();
    const sizeNote = usesFeedback
      ? `at the preview size, ${canvas.width}×${canvas.height} — a simulation is its state`
      : `at ${Math.min(doc.exportSize[0], 1920)}×${Math.min(doc.exportSize[1], 1920)}`;
    const restartBox = el("input", { type: "checkbox", checked: false, style: { width: "auto" } });
    const status = el("p.fine", {}, `Renders ${sizeNote}. Frame-exact; not a screen recording.`);
    const bar = el("div", { style: { height: "6px", background: "var(--line)", borderRadius: "3px" } },
      el("div", { style: { height: "100%", width: "0%", background: "var(--accent, #6ea8ff)", borderRadius: "3px" } }));
    let cancelled = false;

    modal(el("h2", {}, "Export video"),
      el("div.row.tight", {}, el("label", {}, "seconds ", durIn), fpsSel,
        el("label.fine", { style: { display: "inline-flex", gap: ".3rem", alignItems: "center" } },
          restartBox, "restart the sim first")),
      status, bar,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => { cancelled = true; closeModal(); } }, "Cancel"),
        el("button", { onclick: () => go({ frames: true }),
          title: "every frame as a PNG, in a zip" }, "Frames (zip)"),
        el("button.primary", { onclick: () => go({}) }, "Render")));

    async function go({ frames: asFrames = false } = {}) {
      const secs = Math.max(1, Math.min(120, +durIn.value || 6));
      const fps = +fpsSel.value;
      doc.videoSecs = secs; doc.videoFps = fps; host.save();
      const frames = Math.round(secs * fps);
      let W = canvas.width, H = canvas.height;
      if (!usesFeedback) {
        W = Math.min(doc.exportSize[0], 1920); H = Math.min(doc.exportSize[1], 1920);
        W -= W % 2; H -= H % 2;                       // H.264 wants even sizes
      }
      if (!asFrames && !("VideoEncoder" in window)) {
        status.textContent = "This browser has no WebCodecs; a video export needs Chrome, Edge or Safari 17+.";
        return;
      }
      // An image sequence needs no encoder at all, which is the point of
      // having it: whatever this browser will not encode, another tool can.
      if (asFrames) return frameSequence(frames, fps, W, H, { status, bar, cancelled: () => cancelled });
      exporting = true;
      const [pw, ph] = [canvas.width, canvas.height];
      if (W !== pw || H !== ph) { canvas.width = W; canvas.height = H; }
      if (restartBox.checked && feedback) feedback.reset();
      const vsamples = [];
      let vdesc = null;
      const encoder = new VideoEncoder({
        output: (chunk, meta) => {
          if (meta?.decoderConfig?.description && !vdesc) {
            vdesc = new Uint8Array(meta.decoderConfig.description);
          }
          const data = new Uint8Array(chunk.byteLength);
          chunk.copyTo(data);
          vsamples.push({ data, timestamp: chunk.timestamp,
                          duration: chunk.duration || 1e6 / fps, type: chunk.type });
        },
        error: (e) => { status.textContent = `Encoder: ${e.message}`; cancelled = true; },
      });
      const codec = (W * H > 1280 * 720) ? "avc1.4d0028" : "avc1.42001f";
      try {
        encoder.configure({ codec, width: W, height: H, framerate: fps,
          bitrate: Math.round(W * H * fps * 0.12), avc: { format: "avc" } });
        for (let f = 0; f < frames; f++) {
          if (cancelled) break;
          forcedTime = f / fps;
          await seekVideos(textures, forcedTime);
          if (sim) for (let i = 0; i < doc.simSteps; i++) stepSim();
          draw();
          const vf = new VideoFrame(canvas, { timestamp: Math.round(forcedTime * 1e6),
                                              duration: Math.round(1e6 / fps) });
          encoder.encode(vf, { keyFrame: f % (fps * 2) === 0 });
          vf.close();
          if (encoder.encodeQueueSize > 8) await new Promise((r) => setTimeout(r, 8));
          if (f % 5 === 0) {
            status.textContent = `Frame ${f + 1} of ${frames}…`;
            bar.firstChild.style.width = `${Math.round((100 * f) / frames)}%`;
            await new Promise((r) => setTimeout(r, 0));
          }
        }
        if (!cancelled) {
          await encoder.flush();
          encoder.close();
          status.textContent = "Writing the file…";
          const blob = muxMp4([{ kind: "video", samples: vsamples, description: vdesc,
                                 width: W, height: H, timescale: 1_000_000 }]);
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `${host.doc.name || "generate"}-${W}x${H}.mp4`;
          a.click();
          URL.revokeObjectURL(a.href);
          closeModal();
          toast(`Exported ${secs}s at ${fps} fps, ${(blob.size / 1e6).toFixed(1)} MB (no audio).`);
        } else { try { encoder.close(); } catch { /* already */ } }
      } catch (err) {
        status.textContent = `Export failed: ${err.message}`;
      } finally {
        forcedTime = null;
        exporting = false;
        if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
        resumeVideos(textures);
      }
    }
  }

  // ------------------------------------------------------------ modes

  const modeLabel = el("span.tag", {}, doc.mode === "glsl" ? "GLSL" : "sketch");
  const modeBtn = el("button.ghost", { onclick: () => (doc.mode === "glsl" ? backToSketch() : showGlsl()) },
    doc.mode === "glsl" ? "‹ Sketch" : "GLSL");

  /** Sketch → GLSL. The generated file becomes the thing you edit; it is what
      runs, so a change there is a change to the shader. One way — the sketch
      is kept, but edits made here do not fold back into it. */
  function editAsGlsl(text) {
    const fresh = typeof text === "string" ? text : desugar(doc.sketch, { es3: es3() });
    if (doc.glsl && doc.glsl !== fresh) {
      if (!confirm("You have GLSL edits from before. Replace them with a fresh conversion of the sketch?")) {
        // keep the old edits
      } else doc.glsl = fresh;
    } else doc.glsl = fresh;
    doc.mode = "glsl";
    editor.value = doc.glsl;
    modeLabel.textContent = "GLSL"; modeBtn.textContent = "‹ Sketch";
    closeModal();
    run();
    toast("Editing the shader directly. Uniforms, images and feedback all still work.");
  }

  function backToSketch() {
    doc.mode = "sketch";
    editor.value = doc.sketch;
    modeLabel.textContent = "sketch"; modeBtn.textContent = "GLSL";
    run();
    toast("Back to the sketch. Your GLSL edits are kept and come back with GLSL → Edit.");
  }

  /** Fetch an image value's bytes as a data URL, so the source can carry them. */
  async function toDataUrl(v) {
    const res = await fetch(v.url);
    const blob = await res.blob();
    if (blob.size > 12e6) throw new Error(`${(blob.size / 1e6).toFixed(0)} MB is too much to embed`);
    return new Promise((ok, no) => {
      const r = new FileReader();
      r.onload = () => ok(r.result);
      r.onerror = () => no(new Error("could not read"));
      r.readAsDataURL(blob);
    });
  }

  /** The current source with every chosen image embedded as `@data`, so the
      file stands alone. Also usable in place: Embed writes it into the editor. */
  async function selfContained(src) {
    const imgs = uniforms.filter((u) => u.control === "image" && doc.uniforms[u.name] && doc.uniforms[u.name].url);
    if (!imgs.length) return src;
    return embedImages(src, uniforms, doc.uniforms, async (name, v) => {
      if (v.url.startsWith("data:")) return v.url;
      try { return await toDataUrl(v); }
      catch (e) { toast(`${name}: ${e.message}`); return null; }
    });
  }

  function showGlsl() {
    // The version that actually runs here — 3.00 on WebGL2 — not a generic one.
    const src = desugar(doc.sketch, { es3: es3() });
    const area = el("textarea.editor", { value: src, spellcheck: false, readOnly: true,
      style: { minHeight: "340px" } });
    const embedBox = el("input", { type: "checkbox", checked: false, style: { width: "auto" },
      onchange: async (e) => {
        area.value = e.target.checked ? await selfContained(src) : src;
      } });
    const nImg = uniforms.filter((u) => u.control === "image" && doc.uniforms[u.name] && doc.uniforms[u.name].url).length;
    modal(el("h2", {}, "The shader this becomes"),
      el("p.fine", {}, "Plain GLSL ES 1.00. Edit it here and it becomes the " +
        "shader you are working on — the sketch shorthand steps aside, and " +
        "every line is yours. Or open it in the Shader editor, which has The " +
        "Book of Shaders presets but no feedback buffers."),
      nImg ? el("label.fine", { style: { display: "inline-flex", gap: ".4rem", alignItems: "center" } },
        embedBox, `Embed the ${nImg} image${nImg > 1 ? "s" : ""} in the source (@data), so the file stands alone`) : null,
      area,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => { navigator.clipboard?.writeText(area.value); toast("Copied."); } }, "Copy"),
        el("button.primary", { onclick: () => editAsGlsl(area.value) }, "Edit this GLSL here"),
        el("button", { onclick: async () => {
          const made = await api("/api/studio/projects", { method: "POST",
            body: { kind: "shader", name: `${host.doc.name || "sketch"} (ejected)`,
                    data: { source: area.value, knobs: [0.5, 0.5, 0.5, 0.5] } } });
          closeModal();
          location.hash = `#studio/shader/${made.id}`;
        } }, "Open as a shader"),
        el("button.ghost", { onclick: closeModal }, "Close")));
  }

  /**
   * Save this sketch as a node: put `@node` in its header if it is not there,
   * register it, and it appears in the Canvas and Video effect menus. The
   * document *is* the node — editing this sketch later changes the node
   * everywhere it is used, which is the point of not copying it.
   */
  async function saveAsNode() {
    const src = source();
    const shape = nodeShape(src);
    const suggested = String(sketchMeta(src).node || "")
      || (host.doc.name || "my node").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
      || "my-node";
    const nameIn = el("input", { value: suggested, placeholder: "a name for the node" });
    // The course modules, if the app has them loaded; a node that names one
    // gets a link back to the lesson it belongs with.
    let modules = [];
    try { modules = (await api("/api/curriculum")).modules || []; } catch { /* offline */ }
    const modIn = el("select", {},
      el("option", { value: "" }, "— no course module —"),
      ...modules.map((m) => el("option", { value: m.slug }, m.title)));
    const already = declaresNode(src);
    modal(el("h2", {}, "Save as a node"),
      el("p.fine", {}, shape.inputs.length
        ? `This sketch reads ${shape.inputs.join(", ")}, so it takes ${shape.inputs.length} input`
          + `${shape.inputs.length > 1 ? "s" : ""}: the layer or clip it runs on`
          + (shape.inputs.length > 1 ? ", and one more you choose when you use it." : ".")
        : "This sketch reads no input, so it will be offered as something that draws rather than " +
          "something that filters. Declare `uniform sampler2D in0;` and read it at `uv` to make it a filter."),
      shape.foreignImages.length ? el("p.fine", { style: { color: "var(--warm)" } },
        `Its image uniform${shape.foreignImages.length > 1 ? "s" : ""} ${shape.foreignImages.join(", ")} `
        + "will not be filled by the graph — rename one to in0 for the layer, or embed a picture with @data.") : null,
      shape.params.length ? el("p.fine", {}, `${shape.params.length} control${shape.params.length === 1 ? "" : "s"} `
        + `come with it: ${shape.params.join(", ")}.`) : null,
      el("label", {}, "Name", nameIn),
      el("label", {}, "Course module it belongs to", modIn),
      already ? el("p.fine", {}, "This sketch already declares a node; saving updates it.") : null,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", { onclick: async () => {
          const slug = nameIn.value.trim().toLowerCase().replace(/[^a-z0-9.-]+/g, "-").replace(/^-|-$/g, "");
          if (!slug) { toast("It needs a name."); return; }
          const next = withNodeHeader(src, { node: slug, module: modIn.value || null,
                                             title: host.doc.name || null });
          if (doc.mode === "glsl") doc.glsl = next; else doc.sketch = next;
          editor.value = next;
          keepVersion(doc, next, already ? "updated" : "saved as a node");
          await host.save(thumbnail());
          const entry = await registerNode(next, { docId: host.doc.id, name: host.doc.name });
          closeModal();
          run(false);
          if (entry.error) toast(`Saved, but it will not draw: ${entry.error}`);
          else toast(`"${entry.name}" is now an effect in Canvas and Video.`);
        } }, already ? "Update the node" : "Save as node")));
  }

  /**
   * The versions of this node's text, and a way back to one. A node other
   * documents depend on is not a thing to edit without that.
   */
  async function versionsDialog() {
    const list = Array.isArray(doc.versions) ? doc.versions : [];
    const src = source();
    let used = [];
    if (declaresNode(src)) used = await usersOfNode(nodeIdFor(src, host.doc.id));
    modal(el("h2", {}, "Versions"),
      el("p.fine", {}, list.length
        ? `${list.length} kept, newest last. Restoring one puts it in the editor; it becomes the node when you save.`
        : "Nothing kept yet — versions are recorded when you save this sketch as a node."),
      used.length ? el("p.fine", { style: { color: "var(--warm)" } },
        `${used.length} document${used.length === 1 ? " uses" : "s use"} this node: `
        + used.map((u) => u.name).join(", ") + ". Editing it changes them.") : null,
      el("div.stack", { style: { gap: ".25rem" } },
        ...list.map((v, i) => el("div.spread", {},
          el("span.fine", {}, `${new Date(v.at).toLocaleString()} · ${v.note || ""} · `
            + versionSummary(i ? list[i - 1].source : null, v.source)),
          el("button.ghost", { onclick: () => {
            if (doc.mode === "glsl") doc.glsl = v.source; else doc.sketch = v.source;
            editor.value = v.source;
            closeModal();
            run(true);
            toast("Restored into the editor — save it to make it the node.");
          } }, "restore"))).reverse()),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", { onclick: closeModal }, "Close")));
  }

  /** Current control values → @default annotations in the source. */
  function bake() {
    const baked = bakeDefaults(editor.value, uniforms, doc.uniforms);
    if (baked === editor.value) { toast("Nothing to bake — the defaults already match."); return; }
    editor.value = baked;
    run();
    toast("Baked: the values you dialled are now the source's defaults.");
  }

  /**
   * The node reference. Nothing here is written down twice: the description
   * is the sketch's first comment line, the controls are its uniforms, and
   * the lesson is its @module — so a node that changes documents itself.
   */
  async function nodeReferenceDialog() {
    let modules = [];
    try { modules = (await api("/api/course")).modules || []; } catch { /* offline */ }
    const titleOf = (slug) => (modules.find((m) => m.slug === slug) || {}).title || slug;
    const { groups } = nodeReference();
    const gaps = referenceGaps();
    const section = (slug, list) => el("div.stack", { style: { gap: ".3rem", marginTop: ".6rem" } },
      el("h3", { style: { margin: 0 } },
        slug ? el("a", { href: `#library/course/${slug}`, onclick: closeModal }, titleOf(slug))
             : "Not tied to a lesson"),
      ...list.map((d) => el("div", { style: { borderLeft: "2px solid var(--line)", paddingLeft: ".6rem" } },
        el("div.row.tight", { style: { alignItems: "baseline" } },
          el("code", {}, d.id),
          d.mine ? el("span.tag", {}, "yours") : null,
          d.pass ? el("span.tag", { title: "reads a neighbourhood, so it is its own pass" }, "@pass") : null,
          d.alpha ? el("span.tag", { title: "carries transparency through" }, "@alpha") : null,
          el("span.fine", {}, `${d.inputs.length} input${d.inputs.length === 1 ? "" : "s"}`)),
        el("p.fine", { style: { margin: ".1rem 0" } }, d.title),
        d.params.length ? el("table", {}, el("tbody", {}, ...d.params.map((pm) =>
          el("tr", {},
            el("td", {}, el("code", {}, pm.name)),
            el("td", {}, el("span.fine", {},
              pm.options ? pm.options.join(" · ")
                : pm.range ? `${pm.range[0]} … ${pm.range[1]}`
                : pm.control)),
            el("td", {}, el("span.fine", {}, pm.help || pm.label || "")))))) : null)));
    modal(el("h2", {}, "Nodes", el("span.fine", {}, ` ${gaps.total}`)),
      el("p.fine", {}, "Every node the effect menus offer, described by itself: the first line of " +
        "its sketch is what it is, its uniforms are its controls, and @module is the lesson it " +
        "belongs with. Nothing here is written down a second time, so it cannot go stale."),
      gaps.withGaps.length
        ? el("p.fine", { style: { color: "var(--warm)" } },
            `${gaps.documented} of ${gaps.total} are fully described. Missing: `
            + gaps.withGaps.slice(0, 3).map((d) => `${d.id} (${d.gaps[0]})`).join("; ")
            + (gaps.withGaps.length > 3 ? `, and ${gaps.withGaps.length - 3} more` : ""))
        : el("p.fine", {}, `All ${gaps.total} are fully described.`),
      el("div", { style: { maxHeight: "56vh", overflow: "auto" } },
        ...[...groups.entries()].map(([slug, list]) => section(slug, list))),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", { onclick: closeModal }, "Close")));
  }

  function help() {
    modal(el("h2", {}, "How a sketch works"),
      el("p.fine", {}, "Write one colour expression. Anything above the last " +
        "`;` or `}` is preamble — uniforms and helper functions go there."),
      el("h3", {}, "In scope"),
      el("table", {}, el("tbody", {}, ...SKETCH_VARS.map(([n, ty, what]) =>
        el("tr", {}, el("td", {}, el("code", {}, n)), el("td", {}, el("span.fine", {}, ty)),
          el("td", {}, el("span.fine", {}, what)))))),
      el("h3", {}, "Controls from uniforms"),
      el("pre.editor", { style: { minHeight: "auto" } },
`uniform float scale;   // @range 1 40 step 0.5
uniform vec3  tint;    // @color
uniform vec2  centre;  // @pad
uniform int   octaves; // @range 1 8
uniform bool  mirror;  // @toggle`),
      el("p.fine", {}, "The type picks the control — float gives a slider, vec2 " +
        "an XY pad, vec3 named like a colour a swatch, bool a toggle. The " +
        "annotation only refines it, so a bare `uniform float k;` still works " +
        "and gets 0 to 1. Bake writes what you dialled back in as @default."),
      el("h3", {}, "Simulation — feedback"),
      el("p.fine", {}, "Define `vec4 sim(vec2 uv)` and a state pass runs before the " +
        "picture, ping-ponging between two float buffers. In it, prev(uv) / " +
        "prevAt(pixelOffset) read last frame's state; frame is 0 on the first " +
        "pass, so set your initial state there. The picture then reads " +
        "state(uv). Without sim(), prev(uv) is simply the last picture — " +
        "trails and echoes. md is 1.0 while the pointer is down. Steps per " +
        "frame runs the rule several times per drawn frame; Restart clears."),
      el("h3", {}, "Which GLSL"),
      el("p.fine", {}, "On WebGL2 a sketch is emitted as GLSL ES 3.00 — texture2D " +
        "and gl_FragColor still work, by #define — and aa() uses fwidth, so an " +
        "edge is one pixel soft at any zoom. On WebGL1 it is 1.00 with a fixed " +
        "width. A hand-written shader picks its own version by its first line: " +
        "`#version 300 es`, or nothing for 1.00; both run on either context."),
      el("h3", {}, "Editing the GLSL"),
      el("p.fine", {}, "GLSL shows the file the sketch becomes. Edit this GLSL " +
        "here makes that file the thing you edit and run — every line yours, " +
        "line numbers in errors exact. Controls, images and feedback keep " +
        "working because they only need the uniform declarations."),
      el("h3", {}, "Type"),
      el("p.fine", {}, "Text compiles to a distance-field atlas. Load a font " +
        "file with Font… and any text asking for that family is built from the " +
        "outlines in the file — TrueType's quadratics or CFF's cubics — which " +
        "places a corner exactly. Without one, the glyph is rasterised and its " +
        "outline traced back, which is close but about a pixel loose at corners."),
      el("h3", {}, "From vectors"),
      el("p.fine", {}, "SVG… compiles a file into this sketch: rects, circles, " +
        "ellipses, lines, polygons and paths (Béziers flattened adaptively, " +
        "arcs converted) become signed-distance functions; linear and radial " +
        "gradients become ramps; transforms, groups, use, clip-path and " +
        "fill-rule are honoured. The Design studio's Shader button does the " +
        "same for a frame. Text is greeked — real glyphs need an SDF atlas."),
      el("h3", {}, "Images and video"),
      el("p.fine", {}, "A picture can live in the text: `uniform sampler2D mask; " +
        "// @data data:image/png;base64,…` fills the sampler from the source " +
        "itself, and `@asset <url>` points at one. Embed writes the chosen " +
        "images in as @data; the GLSL dialog can do the same for an ejected " +
        "file, so a shader stands alone with its pictures."),
      el("p.fine", {}, "Declare `uniform sampler2D photo;` and a Choose image… " +
        "button appears; the file — a picture or a video — becomes an asset " +
        "of this document. A video plays muted in a loop and is uploaded every " +
        "frame; on export it is seeked frame-exactly. Export video writes an " +
        "MP4 rendered at a fixed clock, so a sim advances one frame per frame " +
        "and the file is the same every time. Declare " +
        "`uniform vec2 photo_size;` too and it is filled with the pixel size — " +
        "(0, 0) until an image is chosen, so a sketch can draw a stand-in. " +
        "coverUV / containUV fit it to the frame like CSS object-fit."),
      el("h3", {}, "Three dimensions"),
      el("p.fine", {}, "Define `float scene(vec3 p)` and the 3D kit comes in: " +
        "march(ro, rd, maxD), normal3, softShadow(ro, rd, k), ao(p, n), " +
        "lookAt(ro, target), and sdSphere, sdBox3, sdTorus, sdCapsule3, sdPlane. " +
        "It is only added when scene() exists, because the kit calls it."),
      el("h3", {}, "Helpers"),
      el("p.fine", {}, "Shape and noise: random, hash21, noise, fbm, rot, smin, " +
        "sdCircle, sdBox, sdSegment, sdCapsule, sdEllipse, aa, palette. " +
        "Define your own with the same name and yours wins."),
      el("p.fine", {}, "Light: sky(rd, sunDir) is a linear-light sky with a sun; " +
        "fresnel(cosθ, f0); tonemap (ACES); srgb (exact encode); dither; " +
        "vignette(uv, k); grain(uv, t). finish(col) = dither(srgb(tonemap(col))) " +
        "— the scene presets work in linear light and end with it. That is " +
        "why their colour uniforms pass through srgbToLinear on the way in: " +
        "a swatch shows you an encoded value."),
      el("p.fine", {}, "#1b2b4b is a colour literal. Note it is an encoded " +
        "sRGB value, so mixing two of them mixes in the encoded space — wrap " +
        "in srgbToLinear if you want the mix to be physically right, which " +
        "Module 3 is the argument for."),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", { onclick: closeModal }, "Close")));
  }

  editor.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); run(); }
    if (e.key === "Tab") {
      e.preventDefault();
      const s = editor.selectionStart;
      editor.setRangeText("  ", s, editor.selectionEnd, "end");
    }
  });
  let typeTimer = null;
  editor.addEventListener("input", () => {
    clearTimeout(typeTimer);
    typeTimer = setTimeout(run, 700);
  });

  const presetSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      const p = GENERATE_PRESETS.find((x) => x.id === e.target.value);
      if (!p) return;
      doc.mode = "sketch"; doc.glsl = "";
      modeLabel.textContent = "sketch"; modeBtn.textContent = "GLSL";
      editor.value = p.source;
      doc.preset = p.id;
      doc.uniforms = {};            // a new sketch means new free variables
      if (p.preview) {              // scenes are landscape; patterns are square
        doc.preview = p.preview.slice();
        queueMicrotask(rescale);
        canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
        sizeSel.value = `${doc.preview[0]}x${doc.preview[1]}`;
      }
      if (p.steps) { doc.simSteps = p.steps; stepsSel.value = String(p.steps); }
      run();
      restart();
    } }, el("option", { value: "" }, "sketch…"),
    ...GENERATE_PRESETS.map((p) =>
      el("option", { value: p.id, selected: p.id === doc.preset }, p.label)));

  const sizeSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      doc.preview = e.target.value.split("x").map(Number);
      rescale();
      host.save();
    } }, ...SIZES.concat(SIZES.some(([w, h]) => w === doc.preview[0] && h === doc.preview[1])
                          ? [] : [doc.preview.slice()])            // a compiled design keeps its aspect
      .map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.preview[0] && h === doc.preview[1] },
        `preview ${w}×${h}`)));

  const exportSel = el("select", { style: { width: "auto" },
    onchange: (e) => { doc.exportSize = e.target.value.split("x").map(Number); host.save(); },
  }, ...EXPORTS.map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.exportSize[0] && h === doc.exportSize[1] },
        `export ${w}×${h}`)));

  const stepsSel = el("select", { style: { width: "auto" }, title: "Simulation steps per drawn frame",
    onchange: (e) => { doc.simSteps = +e.target.value; host.save(); },
  }, ...[1, 2, 4, 8, 16].map((n) =>
      el("option", { value: String(n), selected: n === doc.simSteps }, `${n} step${n > 1 ? "s" : ""}/frame`)));

  const pauseBtn = el("button", { onclick: () => {
    paused = !paused;
    if (paused) pausedAt = (performance.now() - t0) / 1000;
    else t0 = performance.now() - pausedAt * 1000;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
  } }, "Pause");

  const seedLabel = el("span.fine", {}, `seed ${doc.seed}`);

  /** A font file gives true outlines, so text compiles from the shapes the
      designer drew rather than from a traced raster. */
  const fontInput = el("input", { type: "file", accept: ".ttf,.otf,.woff,.ttc,font/*",
    style: { display: "none" },
    onchange: async (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!f) return;
      toast("Reading the font…");
      try {
        const font = await loadFontFile(f);
        if (font.outlines === false) { toast(`${font.family}: ${font.note}`, 7000); return; }
        toast(`${font.family} — ${font.format} outlines, ${font.numGlyphs} glyphs, ` +
              `kerning from ${font.kerningSource === "none" ? "advances only" : font.kerningSource}. ` +
              `Text asking for that family now compiles from them.`, 5000);
      } catch (err) { toast(`Could not read that font: ${err.message}`); }
    } });

  /** An SVG file compiles to a sketch: every shape a signed-distance function. */
  const svgInput = el("input", { type: "file", accept: ".svg,image/svg+xml",
    style: { display: "none" },
    onchange: async (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!f) return;
      let out;
      toast("Compiling shapes and glyphs…");
      try { out = await compileSvg(await f.text(), { name: f.name }); }
      catch (err) { toast(`Could not compile: ${err.message}`); return; }
      doc.mode = "sketch"; doc.glsl = ""; doc.uniforms = {}; doc.preset = "";
      modeLabel.textContent = "sketch"; modeBtn.textContent = "GLSL";
      editor.value = out.source;
      doc.preview = fitPreview(out.width, out.height);
      canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
      sizeSel.value = `${doc.preview[0]}x${doc.preview[1]}`;
      doc.exportSize = [out.width - (out.width % 2), out.height - (out.height % 2)];
      run(); restart();
      toast(`${out.shapes} shape${out.shapes === 1 ? "" : "s"}, ${out.edges} edges` +
            (out.notes.length ? ` — ${out.notes[0]}` : ""));
      if (out.notes.length > 1) {
        modal(el("h2", {}, "Imported, with notes"),
          el("ul", {}, ...out.notes.map((n) => el("li", {}, el("span.fine", {}, n)))),
          el("div.row", { style: { justifyContent: "flex-end" } },
            el("button.primary", { onclick: closeModal }, "Close")));
      }
    } });

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        el("button.primary", { onclick: () => run() }, "Run"),
        pauseBtn,
        el("button", { onclick: restart }, "Restart"),
        presetSel, sizeSel, exportSel, stepsSel,
        el("button", { onclick: exportPng }, "Export PNG"),
        el("button", { onclick: exportVideo }, "Export video"),
        el("label.fine", { style: { display: "inline-flex", alignItems: "center", gap: ".3rem" } },
          el("input", { type: "checkbox", checked: doc.ssaa !== false, style: { width: "auto" },
            oninput: (e) => { doc.ssaa = e.target.checked; host.save(); } }),
          "2× AA"),
        el("button", { onclick: () => {
          doc.seed = Math.floor(Math.random() * 10000);
          randomise(uniforms, doc.uniforms);
          seedLabel.textContent = `seed ${doc.seed}`;
          rebuildControls();
          host.save();
        } }, "Randomise"),
        el("button", { onclick: bake, title: "Write the current control values into the source as @default" }, "Bake"),
        el("button", { onclick: saveAsNode,
          title: "Offer this sketch as an effect in Canvas and Video" }, "Save as node"),
        el("button.ghost", { onclick: versionsDialog,
          title: "Earlier versions of this node's text" }, "Versions"),
        el("button", { title: "Write the chosen images into the source as @data, so the text carries its pictures",
          onclick: async () => {
            const out = await selfContained(editor.value);
            if (out === editor.value) { toast("No images to embed."); return; }
            editor.value = out; run();
            toast("Embedded: the source now carries its images.");
          } }, "Embed"),
        modeBtn, modeLabel,
        grid.button,
        el("button", { onclick: () => svgInput.click(),
          title: "Compile an SVG file: paths, gradients and all, into this sketch" }, "SVG…"),
        svgInput,
        el("button", { onclick: () => fontInput.click(),
          title: "Load a .ttf/.otf/.woff so text compiles from true outlines" }, "Font…"),
        fontInput,
        el("button.ghost", { onclick: help }, "Help"),
        el("button.ghost", { onclick: nodeReferenceDialog,
          title: "every node, written by the nodes" }, "Nodes…"),
        aiButton("Sketch…", {
          task: "code",
          describe: "Describe the image. You get a sketch back; whether it " +
            "reads right is your call, not the model's.",
          placeholder: "e.g. deep blue ground, warm embers drifting upward, soft",
          context: () => doc.mode === "glsl"
            ? "Target: a complete WebGL1 GLSL ES 1.00 fragment shader for this app. " +
              "Keep the existing uniforms u_resolution, u_mouse, u_time, u_seed, u_prev, " +
              "u_state, u_frame, u_mouseDown; declare your own with annotation comments " +
              "(// @range lo hi, // @color, // @pad, // @toggle). If you use a state pass, " +
              "guard it with #ifdef SIM_PASS inside main and read u_prev there. Must set gl_FragColor."
            : "Target: an expression for this app's shader sketch shorthand. " +
              "Write GLSL ES 1.00. Declare uniforms with annotation comments " +
              "(// @range lo hi, // @color, // @pad, // @toggle) and end with a " +
              "single colour expression — no main(), no gl_FragColor. " +
              "In scope: uv, st, p (vec2), t, seed, md (float), m (vec2), frame (int). " +
              "Helpers: random, hash21, noise, fbm, rot, smin, sdCircle, sdBox, " +
              "sdSegment, sdCapsule, sdEllipse, aa, palette, sky(rd,sunDir), " +
              "fresnel, tonemap, srgb, dither, vignette, grain, luma, finish, " +
              "coverUV(uv, imgSize), containUV. `uniform sampler2D name;` is an image " +
              "the user picks; `uniform vec2 name_size;` is its size, (0,0) if none. " +
              "Defining `float scene(vec3 p)` enables march, normal3, softShadow, ao, " +
              "lookAt, sdSphere, sdBox3, sdTorus, sdCapsule3, sdPlane. " +
              "Defining `vec4 sim(vec2 uv)` adds a feedback state pass: inside it " +
              "prev(uv)/prevAt(pixelOffset) read last frame's state and frame==0 is the " +
              "first pass; the picture reads state(uv). " +
              "For scenes work in linear light and end with finish(col). " +
              "#rrggbb is a vec3 literal. Loop bounds must be constant; " +
              "statements before the final expression are allowed.",
          onResult: (res) => { editor.value = res.text; doc.uniforms = {}; run(); restart(); },
        }),
        fsBtn, scaleSel, seedLabel, fpsLabel, stateLabel, soundBtn)),

    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, stage, log),
        knobHost,
        el("p.fine", {}, "Ctrl/Cmd+Enter runs. Editing re-runs after a pause. " +
          "A sketch that fails to compile leaves the last working image on " +
          "screen and prints the error underneath. Press on the canvas to " +
          "drive md and u_mouse in a simulation.")),
      el("div.stack", {}, editor)));

  run(false);
  frame();

  root._cleanup = () => {
    cancelAnimationFrame(raf);
    clearTimeout(typeTimer);
    if (gl) releaseTextures(gl, textures);
    if (feedback) feedback.release();
    if (gl && display) gl.deleteProgram(display);
    if (gl && sim) gl.deleteProgram(sim);
    const lose = gl && gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  };
  return root;
}
