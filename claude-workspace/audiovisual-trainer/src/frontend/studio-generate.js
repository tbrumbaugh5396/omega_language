// Generate — a sketchpad for making images fast.
//
// You write one colour expression. The wrapper supplies the coordinates, the
// clock and a small helper library; every uniform you declare turns into the
// control its type implies. Eject prints the real GLSL, so this is a ramp onto
// the Shader editor rather than a separate world.

import { el, clear, api, toast, modal, closeModal } from "./ui.js";
import { aiButton } from "./ai.js";
import { parseUniforms, desugar, desugarMapped, mapErrors, hasSimPass, isEs3, withDefine,
         bakeDefaults, embedImages, stripComments, SKETCH_VARS } from "./shader-uniforms.js";
import { getGL, isGL2, linkProgram } from "./shader-run.js";
import { Feedback } from "./feedback.js";
import { buildControls, applyUniforms, randomise, bindTextures, releaseTextures,
         mediaDims, seekVideos, resumeVideos } from "./shader-controls.js";
import { muxMp4 } from "./video-mux.js";
import { compileSvg } from "./svg-to-sdf.js";
import { loadFontFile, registeredFonts } from "./font-file.js";
import { fitPreview } from "./sdf-core.js";
import { gridOverlay } from "./grid-overlay.js";

const VERT = `attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

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
float scene(vec3 q) {
  float d = sdPlane(q, 0.0);
  float tt = t * speed;
  d = min(d, sdSphere(q - vec3(-1.2, 0.3 + bounceY(tt, drop, bouncy), 0.0), 0.3));
  d = min(d, sdSphere(q - vec3(0.0, 0.3 + bounceY(tt + 0.7, drop * 0.8, bouncy * 0.9), 0.0), 0.3));
  d = min(d, sdSphere(q - vec3(1.2, 0.3 + bounceY(tt + 1.4, drop * 0.6, min(bouncy * 1.15, 0.95)), 0.0), 0.3));
  return d;
}

vec3 sd = normalize(vec3(-0.5, sunHeight, 0.6));
vec3 ro = vec3(0.4, 1.6, 5.2);
vec3 rd = lookAt(ro, vec3(0.0, 0.8, 0.0)) * normalize(vec3(p, 1.8));
vec3 col = sky(rd, sd);
float tHit = march(ro, rd, 40.0);
if (tHit > 0.0) {
  vec3 pos = ro + rd * tHit;
  vec3 n = normal3(pos);
  bool isFloor = pos.y < 0.02 && abs(n.y) > 0.99;
  vec3 albedo = isFloor
    ? mix(vec3(0.62), vec3(0.78), mod(floor(pos.x) + floor(pos.z), 2.0)) * 0.55
    : (pos.x < -0.6 ? vec3(0.8, 0.2, 0.15) : (pos.x < 0.6 ? vec3(0.15, 0.5, 0.8) : vec3(0.9, 0.7, 0.2)));
  float dif = max(dot(n, sd), 0.0) * softShadow(pos + n * 0.01, sd, 16.0);
  vec3 lig = vec3(1.0, 0.92, 0.80) * 2.6 * dif + vec3(0.35, 0.45, 0.65) * (0.5 + 0.5 * n.y) * ao(pos, n);
  col = albedo * lig;
  vec3 hv = normalize(sd - rd);
  col += pow(max(dot(n, hv), 0.0), 120.0) * dif * (isFloor ? 0.2 : 1.2);
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
});

const SIZES = [[512, 512], [640, 640], [800, 450], [1024, 576], [1080, 1080], [1080, 1920]];
const EXPORTS = [[1024, 1024], [2048, 2048], [4096, 4096], [1920, 1080], [3840, 2160], [1080, 1920]];

export async function generateEditor(host) {
  const doc = host.data;
  doc.sketch ||= GENERATE_PRESETS[0].source;
  doc.uniforms ||= {};
  doc.seed ??= 0;
  doc.preview ||= [640, 640];
  doc.exportSize ||= [2048, 2048];
  doc.mode ||= "sketch";                 // "sketch" | "glsl"
  doc.simSteps ||= 1;

  const canvas = el("canvas", { width: doc.preview[0], height: doc.preview[1],
    style: { width: "100%", height: "auto", display: "block", background: "#000",
             borderRadius: "8px", cursor: "crosshair" } });
  const log = el("div.lab-log");
  const knobHost = el("div");
  const editor = el("textarea.editor", { spellcheck: false,
    value: doc.mode === "glsl" ? (doc.glsl || "") : doc.sketch,
    style: { minHeight: "420px" } });

  let gl = null, raf = null, t0 = performance.now();
  let display = null, sim = null;         // the two programs; sim is null without a state pass
  let quad = null;
  let uniforms = [];
  const textures = {};                    // sampler name -> {url, tex, w, h}
  let feedback = null;                    // Feedback instance, once GL exists
  const grid = gridOverlay();
  const mouse = [0.5, 0.5];
  let mouseDown = 0;
  let paused = false, pausedAt = 0;
  const fpsLabel = el("span.fine");
  const stateLabel = el("span.fine");
  let frames = 0, lastFpsAt = performance.now();

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = ((e.clientX - r.left) / r.width) * canvas.width;
    mouse[1] = (1 - (e.clientY - r.top) / r.height) * canvas.height;
  });
  canvas.addEventListener("pointerdown", (e) => { mouseDown = 1; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointerup", () => { mouseDown = 0; });
  canvas.addEventListener("pointercancel", () => { mouseDown = 0; });

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
    feedback.resize(canvas.width, canvas.height);
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
    stateLabel.textContent = sim ? `sim · ${feedback.describe()}` : (es3() ? "WebGL2 · ES 3.00" : "WebGL1 · ES 1.00");
    return true;
  }

  let forcedTime = null;                  // set during an offline export
  let exporting = false;
  const timeNow = () => forcedTime !== null ? forcedTime
                      : paused ? pausedAt : (performance.now() - t0) / 1000;

  /** Set everything both passes share, then bind the feedback textures on the
      last two units — user images take the first ones. */
  function setCommon(prog, prevTex, stateTex) {
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    gl.uniform2f(u("u_resolution"), canvas.width, canvas.height);
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
    gl.activeTexture(gl.TEXTURE0);
  }

  /** One state step: read a, write b, swap. */
  function stepSim() {
    const w = feedback.write, r = feedback.read;
    gl.bindFramebuffer(gl.FRAMEBUFFER, w.fbo);
    gl.viewport(0, 0, feedback.w, feedback.h);
    setCommon(sim, r.tex, r.tex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    feedback.swap();
  }

  /** The picture. Without a sim, u_prev is last frame's picture and this
      frame's is captured for next time. */
  function draw() {
    if (!display || !gl) return;
    if (feedback.w !== canvas.width || feedback.h !== canvas.height) {
      feedback.resize(canvas.width, canvas.height);
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    if (sim) setCommon(display, feedback.write.tex, feedback.read.tex);
    else setCommon(display, feedback.prevTex, feedback.prevTex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!sim) feedback.captureCanvas();
  }

  function frame() {
    if (exporting) { raf = requestAnimationFrame(frame); return; }
    if (display && gl && !paused) {
      if (sim) for (let i = 0; i < doc.simSteps; i++) stepSim();
      draw();
    } else if (display && gl) {
      draw();
    }
    frames++;
    const now = performance.now();
    if (now - lastFpsAt > 500) {
      fpsLabel.textContent =
        `${Math.round((frames * 1000) / (now - lastFpsAt))} fps · ${canvas.width}×${canvas.height}`;
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
  function exportPng() {
    const usesFeedback = !!sim || /\bu_prev\b/.test(stripComments(source()));
    let [w, h] = doc.exportSize;
    const maxDim = gl ? gl.getParameter(gl.MAX_VIEWPORT_DIMS)[0] : 4096;
    if (usesFeedback) { w = canvas.width; h = canvas.height; }
    if (w > maxDim || h > maxDim) {
      toast(`This GPU caps a render at ${maxDim}px. Pick a smaller size.`);
      return;
    }
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
    const usesFeedback = !!sim || /\bu_prev\b/.test(stripComments(source()));
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
        el("button.primary", { onclick: go }, "Render")));

    async function go() {
      const secs = Math.max(1, Math.min(120, +durIn.value || 6));
      const fps = +fpsSel.value;
      doc.videoSecs = secs; doc.videoFps = fps; host.save();
      const frames = Math.round(secs * fps);
      let W = canvas.width, H = canvas.height;
      if (!usesFeedback) {
        W = Math.min(doc.exportSize[0], 1920); H = Math.min(doc.exportSize[1], 1920);
        W -= W % 2; H -= H % 2;                       // H.264 wants even sizes
      }
      if (!("VideoEncoder" in window)) {
        status.textContent = "This browser has no WebCodecs; a video export needs Chrome, Edge or Safari 17+.";
        return;
      }
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

  /** Current control values → @default annotations in the source. */
  function bake() {
    const baked = bakeDefaults(editor.value, uniforms, doc.uniforms);
    if (baked === editor.value) { toast("Nothing to bake — the defaults already match."); return; }
    editor.value = baked;
    run();
    toast("Baked: the values you dialled are now the source's defaults.");
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
      canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
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
        seedLabel, fpsLabel, stateLabel)),

    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, el("div", { style: { position: "relative" } }, canvas, grid.overlay), log),
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
