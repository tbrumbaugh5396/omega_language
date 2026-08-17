// Generate — a sketchpad for making images fast.
//
// You write one colour expression. The wrapper supplies the coordinates, the
// clock and a small helper library; every uniform you declare turns into the
// control its type implies. Eject prints the real GLSL, so this is a ramp onto
// the Shader editor rather than a separate world.

import { el, clear, api, toast, modal, closeModal } from "./ui.js";
import { aiButton } from "./ai.js";
import { parseUniforms, desugar, SKETCH_VARS } from "./shader-uniforms.js";
import { buildControls, applyUniforms, randomise } from "./shader-controls.js";

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

  const canvas = el("canvas", { width: doc.preview[0], height: doc.preview[1],
    style: { width: "100%", height: "auto", display: "block", background: "#000",
             borderRadius: "8px", cursor: "crosshair" } });
  const log = el("div.lab-log");
  const knobHost = el("div");
  const editor = el("textarea.editor", { spellcheck: false, value: doc.sketch,
    style: { minHeight: "420px" } });

  let gl = null, program = null, raf = null, t0 = performance.now();
  let uniforms = [];
  const mouse = [0.5, 0.5];
  let paused = false, pausedAt = 0;
  const fpsLabel = el("span.fine");
  let frames = 0, lastFpsAt = performance.now();

  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse[0] = ((e.clientX - r.left) / r.width) * canvas.width;
    mouse[1] = (1 - (e.clientY - r.top) / r.height) * canvas.height;
  });

  function compile(fragSrc) {
    clear(log);
    if (!gl) {
      gl = canvas.getContext("webgl", { preserveDrawingBuffer: true, antialias: false });
      if (!gl) { log.textContent = "WebGL is not available in this browser."; return false; }
    }
    const mk = (type, code) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, code);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        const info = gl.getShaderInfoLog(s) || "compile failed";
        gl.deleteShader(s);
        throw new Error(info);
      }
      return s;
    };
    let p;
    try {
      const vs = mk(gl.VERTEX_SHADER, VERT);
      const fs = mk(gl.FRAGMENT_SHADER, fragSrc);
      p = gl.createProgram();
      gl.attachShader(p, vs);
      gl.attachShader(p, fs);
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(p) || "link failed");
      }
    } catch (e) {
      // The generated shader has a preamble you did not type, so a raw line
      // number would point at the wrong place. Say so rather than mislead.
      log.textContent = String(e.message).trim() +
        "\n\n(line numbers are for the generated shader — press Eject to see it)";
      return false;
    }
    if (program) gl.deleteProgram(program);
    program = p;
    gl.useProgram(program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    return true;
  }

  function draw() {
    if (!program || !gl) return;
    gl.viewport(0, 0, canvas.width, canvas.height);
    const u = (n) => gl.getUniformLocation(program, n);
    gl.uniform2f(u("u_resolution"), canvas.width, canvas.height);
    gl.uniform2f(u("u_mouse"), mouse[0], mouse[1]);
    gl.uniform1f(u("u_time"), paused ? pausedAt : (performance.now() - t0) / 1000);
    gl.uniform1f(u("u_seed"), doc.seed);
    applyUniforms(gl, program, uniforms, doc.uniforms);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function frame() {
    draw();
    frames++;
    const now = performance.now();
    if (now - lastFpsAt > 500) {
      fpsLabel.textContent =
        `${Math.round((frames * 1000) / (now - lastFpsAt))} fps · ${canvas.width}×${canvas.height}`;
      frames = 0; lastFpsAt = now;
    }
    raf = requestAnimationFrame(frame);
  }

  /** Re-read the source: rebuild the controls, then recompile. */
  function run(save = true) {
    doc.sketch = editor.value;
    uniforms = parseUniforms(doc.sketch);
    clear(knobHost);
    knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save()));
    const ok = compile(desugar(doc.sketch));
    if (ok && save) host.save(thumbnail());
    return ok;
  }

  function thumbnail() {
    try {
      const t = document.createElement("canvas");
      t.width = 240; t.height = Math.round((240 * canvas.height) / canvas.width);
      t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
      return t.toDataURL("image/jpeg", 0.7);
    } catch { return ""; }
  }

  /** Render once at the export size. The preview canvas is resized rather than
      a second context created, so what you export is what you were looking at. */
  function exportPng() {
    const [w, h] = doc.exportSize;
    const maxDim = gl ? gl.getParameter(gl.MAX_VIEWPORT_DIMS)[0] : 4096;
    if (w > maxDim || h > maxDim) {
      toast(`This GPU caps a render at ${maxDim}px. Pick a smaller size.`);
      return;
    }
    // 2×2 supersampling where the GPU has room: render at double size, then
    // average down. Hard edges — foam lines, grass, board rails — are where a
    // single sample per pixel reads as cheap. Capped so a 4096 export does
    // not ask for a 268 MB drawing buffer.
    const ss = doc.ssaa !== false && w * 2 <= maxDim && h * 2 <= maxDim
             && w * h <= 2048 * 2048 ? 2 : 1;
    const [pw, ph] = [canvas.width, canvas.height];
    canvas.width = w * ss; canvas.height = h * ss;
    draw();
    let url;
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
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${host.doc.name || "generate"}-${w}x${h}.png`;
    a.click();
    toast(`Exported ${w}×${h}${ss > 1 ? ", 2× supersampled" : ""}.`);
  }

  function eject() {
    const src = desugar(doc.sketch);
    const area = el("textarea.editor", { value: src, spellcheck: false,
      style: { minHeight: "340px" } });
    modal(el("h2", {}, "The shader this becomes"),
      el("p.fine", {}, "Plain GLSL ES 1.00 — the same thing the Shader editor " +
        "runs. Open it there to keep working without the shorthand."),
      area,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => {
          navigator.clipboard?.writeText(src);
          toast("Copied.");
        } }, "Copy"),
        el("button.primary", { onclick: async () => {
          const made = await api("/api/studio/projects", { method: "POST",
            body: { kind: "shader", name: `${host.doc.name || "sketch"} (ejected)`,
                    data: { source: src, knobs: [0.5, 0.5, 0.5, 0.5] } } });
          closeModal();
          location.hash = `#studio/shader/${made.id}`;
        } }, "Open as a shader"),
        el("button.ghost", { onclick: closeModal }, "Close")));
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
        "and gets 0 to 1."),
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
      editor.value = p.source;
      doc.preset = p.id;
      doc.uniforms = {};            // a new sketch means new free variables
      if (p.preview) {              // scenes are landscape; patterns are square
        doc.preview = p.preview.slice();
        canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
        sizeSel.value = `${doc.preview[0]}x${doc.preview[1]}`;
      }
      run();
    } }, el("option", { value: "" }, "sketch…"),
    ...GENERATE_PRESETS.map((p) =>
      el("option", { value: p.id, selected: p.id === doc.preset }, p.label)));

  const sizeSel = el("select", { style: { width: "auto" },
    onchange: (e) => {
      doc.preview = e.target.value.split("x").map(Number);
      canvas.width = doc.preview[0]; canvas.height = doc.preview[1];
      host.save();
    } }, ...SIZES.map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.preview[0] && h === doc.preview[1] },
        `preview ${w}×${h}`)));

  const exportSel = el("select", { style: { width: "auto" },
    onchange: (e) => { doc.exportSize = e.target.value.split("x").map(Number); host.save(); },
  }, ...EXPORTS.map(([w, h]) =>
      el("option", { value: `${w}x${h}`, selected: w === doc.exportSize[0] && h === doc.exportSize[1] },
        `export ${w}×${h}`)));

  const pauseBtn = el("button", { onclick: () => {
    paused = !paused;
    if (paused) pausedAt = (performance.now() - t0) / 1000;
    else t0 = performance.now() - pausedAt * 1000;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
  } }, "Pause");

  const seedLabel = el("span.fine", {}, `seed ${doc.seed}`);

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        el("button.primary", { onclick: () => run() }, "Run"),
        pauseBtn,
        el("button", { onclick: () => { t0 = performance.now(); pausedAt = 0; } }, "Restart time"),
        presetSel, sizeSel, exportSel,
        el("button", { onclick: exportPng }, "Export PNG"),
        el("label.fine", { style: { display: "inline-flex", alignItems: "center", gap: ".3rem" } },
          el("input", { type: "checkbox", checked: doc.ssaa !== false, style: { width: "auto" },
            oninput: (e) => { doc.ssaa = e.target.checked; host.save(); } }),
          "2× AA"),
        el("button", { onclick: () => {
          doc.seed = Math.floor(Math.random() * 10000);
          randomise(uniforms, doc.uniforms);
          seedLabel.textContent = `seed ${doc.seed}`;
          clear(knobHost);
          knobHost.append(buildControls(uniforms, doc.uniforms, () => host.save()));
          host.save();
        } }, "Randomise"),
        el("button.ghost", { onclick: eject }, "Eject"),
        el("button.ghost", { onclick: help }, "Help"),
        aiButton("Sketch…", {
          task: "code",
          describe: "Describe the image. You get a sketch back; whether it " +
            "reads right is your call, not the model's.",
          placeholder: "e.g. deep blue ground, warm embers drifting upward, soft",
          context: () =>
            "Target: an expression for this app's shader sketch shorthand. " +
            "Write GLSL ES 1.00. Declare uniforms with annotation comments " +
            "(// @range lo hi, // @color, // @pad, // @toggle) and end with a " +
            "single colour expression — no main(), no gl_FragColor. " +
            "In scope: uv, st, p (vec2), t, seed (float), m (vec2). " +
            "Helpers: random, hash21, noise, fbm, rot, smin, sdCircle, sdBox, " +
            "sdSegment, sdCapsule, sdEllipse, aa, palette, sky(rd,sunDir), " +
            "fresnel, tonemap, srgb, dither, vignette, grain, finish. " +
            "For scenes work in linear light and end with finish(col). " +
            "#rrggbb is a vec3 literal. Loop bounds must be constant; " +
            "statements before the final expression are allowed.",
          onResult: (res) => { editor.value = res.text; doc.uniforms = {}; run(); },
        }),
        seedLabel, fpsLabel)),

    el("div.lab-split", {},
      el("div.stack", {},
        el("div.lab-out", {}, canvas, log),
        knobHost,
        el("p.fine", {}, "Ctrl/Cmd+Enter runs. Editing re-runs after a pause. " +
          "A sketch that fails to compile leaves the last working image on " +
          "screen and prints the error underneath.")),
      el("div.stack", {}, editor)));

  run(false);
  frame();

  root._cleanup = () => {
    cancelAnimationFrame(raf);
    clearTimeout(typeTimer);
    if (gl && program) gl.deleteProgram(program);
    const lose = gl && gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  };
  return root;
}
