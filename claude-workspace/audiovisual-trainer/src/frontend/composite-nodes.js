// Compositing: the browser's sixteen blend modes, as one node.
//
// A canvas document is layers with a blend mode and an opacity, and until now
// that composite only existed in the 2D canvas. These nodes put it in the
// graph, which is what lets a whole document — layers, their effect stacks,
// their masks — compile to one chain of shaders and be ejected as text.
//
// The formulas are the CSS compositing spec, which is what the browser
// implements, so the two can be held against each other pixel for pixel: the
// separable modes through B(Cb, Cs), the four non-separable ones through
// SetLum/SetSat, and the general formula
//
//   Co = (1 - ab)·as·Cs + as·ab·B(Cb, Cs) + (1 - as)·ab·Cb
//   ao = as + ab·(1 - as)
//
// carrying straight (un-premultiplied) alpha, which is why these say @alpha.

import { defineNode } from "./render-graph.js";

/** The order the browser's globalCompositeOperation names appear in `mode`. */
export const BLEND_ORDER = [
  "source-over", "multiply", "screen", "overlay", "darken", "lighten",
  "color-dodge", "color-burn", "hard-light", "soft-light", "difference",
  "exclusion", "hue", "saturation", "color", "luminosity",
];

const BLEND_GLSL = `
float _lum(vec3 c){ return dot(c, vec3(0.3, 0.59, 0.11)); }
vec3 _clipColour(vec3 c){
  float l = _lum(c);
  float n = min(c.r, min(c.g, c.b));
  float x = max(c.r, max(c.g, c.b));
  if (n < 0.0) c = l + (c - l) * l / max(l - n, 1e-6);
  if (x > 1.0) c = l + (c - l) * (1.0 - l) / max(x - l, 1e-6);
  return c;
}
vec3 _setLum(vec3 c, float l){ return _clipColour(c + (l - _lum(c))); }
float _sat(vec3 c){ return max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b)); }
// SetSat: smallest component to 0, largest to s, the middle one in
// proportion — which one affine map does to all three at once.
vec3 _setSat(vec3 c, float s){
  float mn = min(c.r, min(c.g, c.b));
  float mx = max(c.r, max(c.g, c.b));
  return (mx > mn) ? (c - mn) * s / (mx - mn) : vec3(0.0);
}
vec3 _softLight(vec3 cb, vec3 cs){
  vec3 d = mix(sqrt(cb), ((16.0 * cb - 12.0) * cb + 4.0) * cb, step(cb, vec3(0.25)));
  return mix(cb + (2.0 * cs - 1.0) * (d - cb),
             cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb),
             step(cs, vec3(0.5)));
}
vec3 _hardLight(vec3 cb, vec3 cs){
  return mix(1.0 - 2.0 * (1.0 - cb) * (1.0 - cs), 2.0 * cb * cs, step(cs, vec3(0.5)));
}
vec3 _dodge(vec3 cb, vec3 cs){
  return mix(min(vec3(1.0), cb / max(1.0 - cs, 1e-6)), vec3(1.0), step(vec3(1.0), cs))
       * step(vec3(1e-6), cb);
}
vec3 _burn(vec3 cb, vec3 cs){
  vec3 v = 1.0 - min(vec3(1.0), (1.0 - cb) / max(cs, 1e-6));
  return mix(v, vec3(0.0), step(cs, vec3(0.0))) * (1.0 - step(vec3(1.0), cb)) + step(vec3(1.0), cb);
}
vec3 _blend(int mode, vec3 cb, vec3 cs){
  if (mode == 1) return cb * cs;
  if (mode == 2) return cb + cs - cb * cs;
  if (mode == 3) return _hardLight(cs, cb);
  if (mode == 4) return min(cb, cs);
  if (mode == 5) return max(cb, cs);
  if (mode == 6) return _dodge(cb, cs);
  if (mode == 7) return _burn(cb, cs);
  if (mode == 8) return _hardLight(cb, cs);
  if (mode == 9) return _softLight(cb, cs);
  if (mode == 10) return abs(cb - cs);
  if (mode == 11) return cb + cs - 2.0 * cb * cs;
  if (mode == 12) return _setLum(_setSat(cs, _sat(cb)), _lum(cb));
  if (mode == 13) return _setLum(_setSat(cb, _sat(cs)), _lum(cb));
  if (mode == 14) return _setLum(cs, _lum(cb));
  if (mode == 15) return _setLum(cb, _lum(cs));
  return cs;
}`;

defineNode(`// One layer over what is under it: the browser's blend modes, to the spec.
// @node composite.layer
// @module 03-additive-subtractive
// @alpha
uniform sampler2D in0;   // the backdrop
uniform sampler2D in1;   // the layer
uniform int   mode;      // @options source-over,multiply,screen,overlay,darken,lighten,color-dodge,color-burn,hard-light,soft-light,difference,exclusion,hue,saturation,color,luminosity @default 0
uniform float opacity;   // @range 0 1 @default 1
${BLEND_GLSL}
vec4 b = texture2D(in0, uv);
vec4 s = texture2D(in1, uv);
float as = s.a * opacity, ab = b.a;
vec3 mixed = _blend(mode, b.rgb, s.rgb);
float ao = as + ab * (1.0 - as);
vec3 co = (1.0 - ab) * as * s.rgb + as * ab * mixed + (1.0 - as) * ab * b.rgb;
vec4(ao > 0.0 ? co / ao : vec3(0.0), ao)`);

defineNode(`// A layer mask: keep in0 where in1 has alpha. What destination-in does.
// @node composite.mask
// @module 03-additive-subtractive
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;   // the mask; only its alpha is read
vec4 c = texture2D(in0, uv);
vec4(c.rgb, c.a * texture2D(in1, uv).a)`);

defineNode(`// A flat colour, alpha and all: what a document sits on.
// @node source.flat
// @module 01-light-and-exposure
// @alpha
uniform vec3  colour;    // @color @default 1 1 1
uniform float alpha;     // @range 0 1 @default 1
vec4(colour, alpha)`);

// ------------------------------------------------------------------ video
//
// The CSS filter functions, which is what the video studio's grade has always
// been, written out as the matrices the Filter Effects spec gives. The order
// is the order the shorthand applies them in, and each step clamps, because
// each is its own filter primitive.

defineNode(`// brightness, contrast, saturate and hue-rotate — the CSS filter functions, to the spec.
// @node filter.cssGrade
// @module 01-light-and-exposure
// @alpha
uniform sampler2D in0;
uniform float brightness;   // @range 0.2 2 @default 1
uniform float contrast;     // @range 0.2 2.5 @default 1
uniform float saturation;   // @range 0 2.5 @default 1
uniform float hue;          // @range -180 180 @default 0 @help degrees

vec4 c = texture2D(in0, uv);
vec3 x = clamp(c.rgb * brightness, 0.0, 1.0);
x = clamp(x * contrast + (0.5 - 0.5 * contrast), 0.0, 1.0);
float s = saturation;
mat3 sm = mat3(0.213 + 0.787 * s, 0.213 - 0.213 * s, 0.213 - 0.213 * s,
               0.715 - 0.715 * s, 0.715 + 0.285 * s, 0.715 - 0.715 * s,
               0.072 - 0.072 * s, 0.072 - 0.072 * s, 0.072 + 0.928 * s);
x = clamp(sm * x, 0.0, 1.0);
float a = radians(hue), cs = cos(a), sn = sin(a);
mat3 hm = mat3(0.213 + cs * 0.787 - sn * 0.213, 0.213 - cs * 0.213 + sn * 0.143, 0.213 - cs * 0.213 - sn * 0.787,
               0.715 - cs * 0.715 - sn * 0.715, 0.715 + cs * 0.285 + sn * 0.140, 0.715 - cs * 0.715 + sn * 0.715,
               0.072 - cs * 0.072 + sn * 0.928, 0.072 - cs * 0.072 - sn * 0.283, 0.072 + cs * 0.928 + sn * 0.072);
x = clamp(hm * x, 0.0, 1.0);
vec4(x, c.a)`);

defineNode(`// One box blur along one axis, taps lo..hi. Three of these per axis are what a CSS blur is.
// @node filter.box1d
// @module 05-display
// @pass
// @alpha
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float lo;      // @range -64 0 @default -1 @hidden
uniform float hi;      // @range 0 64 @default 1 @hidden
uniform vec2  dir;     // @hidden

vec4 acc = vec4(0.0);
float n = 0.0;
for (int i = -64; i <= 64; i++) {
  float f = float(i);
  if (f < lo || f > hi) continue;
  acc += texture2D(in0, uv + dir * f / in0_size);
  n += 1.0;
}
n > 0.0 ? acc / n : texture2D(in0, uv)`);

defineNode(`// A transition between what is already there (in0) and what is arriving (in1).
// @node transition.mix
// @module 03-additive-subtractive
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;
uniform int   mode;       // @options dissolve,wipe,dip,push @default 0
uniform float progress;   // @range 0 1 @default 0
uniform float angle;      // @range 0 360 @default 0 @help the wipe's direction, degrees
uniform vec3  colour;     // @color @default 0 0 0 @help what a dip passes through
uniform float softness;   // @range 0 0.5 @default 0.08

vec4 a = texture2D(in0, uv);
vec4 b = texture2D(in1, uv);
vec4 outc = mix(a, b, progress);
if (mode == 1) {
  float th = radians(angle);
  float d = dot(uv - 0.5, vec2(cos(th), sin(th))) + 0.5;
  float k = smoothstep(progress - softness, progress + softness, d);
  outc = mix(b, a, k);
} else if (mode == 2) {
  // Through a colour and out the other side: two half-length dissolves.
  vec4 mid = vec4(colour, 1.0);
  outc = progress < 0.5 ? mix(a, mid, progress * 2.0) : mix(mid, b, (progress - 0.5) * 2.0);
} else if (mode == 3) {
  float th = radians(angle);
  vec2 off = vec2(cos(th), sin(th)) * progress;
  vec4 aa = texture2D(in0, uv + off);
  vec4 bb = texture2D(in1, uv + off - vec2(cos(th), sin(th)));
  float d = dot(uv - 0.5, vec2(cos(th), sin(th))) + 0.5;
  outc = d < progress ? bb : aa;
}
outc`);

defineNode(`// A 3D LUT, its slices laid out side by side: n·n across, n down.
// @node filter.lut3d
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;    // @hidden the cube, as a tile sheet
uniform float size;       // @range 2 64 @default 33 @hidden
uniform float amount;     // @range 0 1 @default 1 @help how far towards the look
uniform vec3  dmin;       // @hidden @default 0 0 0 the cube's own input domain, which a log LUT moves
uniform vec3  dmax;       // @hidden @default 1 1 1

vec4 c = texture2D(in0, uv);
float n = max(2.0, size);
vec3 span = max(dmax - dmin, vec3(1e-6));
vec3 q = clamp((c.rgb - dmin) / span, 0.0, 1.0);
float sl = q.b * (n - 1.0);
float s0 = floor(sl), s1 = min(s0 + 1.0, n - 1.0);
// half a texel in from each tile's edge, so linear filtering never crosses one
float su = (q.r * (n - 1.0) + 0.5) / (n * n);
float sv = (q.g * (n - 1.0) + 0.5) / n;
vec3 lo = texture2D(in1, vec2(su + s0 / n, sv)).rgb;
vec3 hi = texture2D(in1, vec2(su + s1 / n, sv)).rgb;
vec4(mix(c.rgb, mix(lo, hi, sl - s0), amount), c.a)`);
