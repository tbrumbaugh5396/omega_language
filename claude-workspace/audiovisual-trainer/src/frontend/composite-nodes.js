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
