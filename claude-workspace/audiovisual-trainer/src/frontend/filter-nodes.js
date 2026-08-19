// The effects catalogue as render-graph nodes.
//
// Each of engine-image's filters, re-expressed as a sketch with the same
// mathematics — the same kernel, the same transfer function, the same
// colour space — so the CPU implementation is the reference and the
// self-test can hold the two to a number. Where the CPU code rounds a sample
// position or clamps at the border, the node does too, because parity is
// only meaningful if it is parity with what the code actually does.
//
// One filter is not here, on purpose. Error-diffusion dither carries each
// pixel's quantisation error into the pixels after it, in scan order; that
// is a serial dependency, and no per-pixel program can express it. It stays
// on the CPU and the catalogue says so.

import { defineNode, addNode, addBlur } from "./render-graph.js";

// The exact sRGB transfer, as engine-image has it. The sketch helpers'
// srgbToLinear is a 2.2 approximation, fine for a scene and wrong for parity.
const EXACT = `vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
vec3 toSrgb(vec3 c) { c = max(c, 0.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }`;

// OKLab, from the same coefficients. cbrt is a signed cube root.
const OKLAB = `float cbrt_(float x) { return sign(x) * pow(abs(x), 1.0 / 3.0); }
vec3 linToOklab(vec3 c) {
  float l = cbrt_(0.4122214708 * c.r + 0.5363325363 * c.g + 0.0514459929 * c.b);
  float m = cbrt_(0.2119034982 * c.r + 0.6806995451 * c.g + 0.1073969566 * c.b);
  float s = cbrt_(0.0883024619 * c.r + 0.2817188376 * c.g + 0.6299787005 * c.b);
  return vec3(0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
              1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
              0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s);
}
vec3 oklabToLin(vec3 c) {
  float l = c.x + 0.3963377774 * c.y + 0.2158037573 * c.z;
  float m = c.x - 0.1055613458 * c.y - 0.0638541728 * c.z;
  float s = c.x - 0.0894841775 * c.y - 1.2914855480 * c.z;
  l = l * l * l; m = m * m * m; s = s * s * s;
  return vec3( 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
              -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
              -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s);
}`;

// Sample the way the CPU does: round the position to a pixel, clamp to the
// image, read that texel's centre. Bilinear would be smoother and wrong.
const NEAREST = `vec4 texel(sampler2D s, vec2 sz, vec2 px) {
  vec2 p = clamp(floor(px + 0.5), vec2(0.0), sz - 1.0);
  return texture2D(s, (p + 0.5) / sz);
}`;

const LUMA = `float lumaOf(vec3 c) { return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b; }`;

// ------------------------------------------------------------------ nodes

defineNode(`// Motion blur: n taps along a direction, positions rounded to pixels.
// @node filter.motion
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float length_;  // @range 2 60 @default 16 @label length
uniform float angle;    // @range 0 180 @default 0
${NEAREST}
float a = radians(angle);
vec2 dir = vec2(cos(a), sin(a));
int n = int(max(2.0, floor(length_ + 0.5)));
// The CPU's (x, y) with rows counting down; a sample there is read back at
// its texel centre with the row flipped again.
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec4 acc = vec4(0.0);
for (int i = 0; i < 60; i++) {
  if (i >= n) break;
  float t = float(i) - float(n) / 2.0;
  vec2 q = clamp(floor(px + dir * t + 0.5), vec2(0.0), in0_size - 1.0);
  acc += texture2D(in0, vec2(q.x + 0.5, in0_size.y - q.y - 0.5) / in0_size);
}
vec4 c = acc / float(n);
vec4(c.rgb, texture2D(in0, uv).a)`);

defineNode(`// Radial blur: samples toward the centre at shrinking scales, positions rounded.
// @node filter.radial
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float strength; // @range 0.01 0.3 @default 0.08
uniform int   steps;    // @range 4 24 @default 14 @hidden
vec2 c0 = in0_size * 0.5;
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec4 acc = vec4(0.0);
for (int i = 0; i < 24; i++) {
  if (i >= steps) break;
  float s = 1.0 - (float(i) / float(steps)) * strength;
  vec2 q = clamp(floor(c0 + (px - c0) * s + 0.5), vec2(0.0), in0_size - 1.0);
  acc += texture2D(in0, vec2(q.x + 0.5, in0_size.y - q.y - 0.5) / in0_size);
}
vec4 c = acc / float(steps);
vec4(c.rgb, texture2D(in0, uv).a)`);

defineNode(`// Lens blur: a flat disc kernel of radius r, clamped at the border.
// @node filter.lens
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform int   radius;   // @range 1 12 @default 4
vec4 acc = vec4(0.0);
float count = 0.0;
for (int dy = -12; dy <= 12; dy++) {
  for (int dx = -12; dx <= 12; dx++) {
    if (dx * dx + dy * dy > radius * radius) continue;
    vec2 q = clamp(gl_FragCoord.xy - 0.5 + vec2(float(dx), float(dy)), vec2(0.0), in0_size - 1.0);
    acc += texture2D(in0, (q + 0.5) / in0_size);
    count += 1.0;
  }
}
vec4 c = acc / count;
vec4(c.rgb, texture2D(in0, uv).a)`);

defineNode(`// Unsharp mask: the original plus amount × (original − its blur). in1 is the blur.
// @node filter.unsharp
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;
uniform float amount;   // @range 0 3 @default 0.8
vec4 o = texture2D(in0, uv);
vec4 b = texture2D(in1, uv);
vec4(clamp(o.rgb + amount * (o.rgb - b.rgb), 0.0, 1.0), o.a)`);

defineNode(`// Sobel edges: gradient magnitude per channel, from the two 3×3 kernels.
// @node filter.edges
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
vec3 gx = vec3(0.0), gy = vec3(0.0);
for (int ky = -1; ky <= 1; ky++) {
  for (int kx = -1; kx <= 1; kx++) {
    vec2 q = clamp(gl_FragCoord.xy - 0.5 + vec2(float(kx), float(ky)), vec2(0.0), in0_size - 1.0);
    vec3 s = texture2D(in0, (q + 0.5) / in0_size).rgb * 255.0;
    // CPU rows count down, so its ky = −1 is our +1: the sign of gy flips, and
    // a magnitude does not care.
    float wx = float(kx) * (ky == 0 ? 2.0 : 1.0);
    float wy = float(ky) * (kx == 0 ? 2.0 : 1.0);
    gx += s * wx; gy += s * wy;
  }
}
// The CPU stores each gradient plus 128 in an 8-bit array before subtracting
// again, which clamps it to −128..127; parity means doing the same.
gx = clamp(gx, -128.0, 127.0); gy = clamp(gy, -128.0, 127.0);
vec3 mag = min(sqrt(gx * gx + gy * gy), 255.0);
vec4(mag / 255.0, texture2D(in0, uv).a)`);

defineNode(`// Emboss: the 3×3 kernel, offset by mid-grey.
// @node filter.emboss
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
vec3 acc = vec3(0.0);
for (int ky = -1; ky <= 1; ky++) {
  for (int kx = -1; kx <= 1; kx++) {
    // The CPU kernel [-2 -1 0; -1 1 1; 0 1 2] is dx + dy along its rows, which
    // count down; GL's count up, so it is kx − ky here, and 1 at the centre.
    float w = (kx == 0 && ky == 0) ? 1.0 : float(kx) - float(ky);
    vec2 q = clamp(gl_FragCoord.xy - 0.5 + vec2(float(kx), float(ky)), vec2(0.0), in0_size - 1.0);
    acc += texture2D(in0, (q + 0.5) / in0_size).rgb * w;
  }
}
vec4(clamp(acc + 128.0 / 255.0, 0.0, 1.0), texture2D(in0, uv).a)`);

defineNode(`// Grade: lift, gamma, gain, saturation and temperature, in linear light — the exact transfer.
// @node adjust.grade
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform float lift;     // @range -0.15 0.3 @default 0
uniform float gamma;    // @range 0.3 2.5 @default 1
uniform float gain;     // @range 0.3 2.5 @default 1
uniform float sat;      // @range 0 2.5 @default 1
uniform float temp;     // @range -1 1 @default 0
${EXACT}
vec4 c = texture2D(in0, uv);
vec3 l = toLin(c.rgb);
l = (l + lift) * gain;
l.r += temp * 0.08; l.b -= temp * 0.08;
l = pow(max(l, 0.0), vec3(gamma));
float lum = dot(l, vec3(0.2126, 0.7152, 0.0722));
l = lum + (l - lum) * sat;
vec4(clamp(toSrgb(l), 0.0, 1.0), c.a)`);

defineNode(`// Hue rotate, in OKLab so lightness holds still.
// @node adjust.hue
// @module 04-color-organization
// @alpha
uniform sampler2D in0;
uniform float degrees;  // @range -180 180 @default 30
${EXACT}
${OKLAB}
vec4 c = texture2D(in0, uv);
vec3 lab = linToOklab(toLin(c.rgb));
float a = radians(degrees), cs = cos(a), sn = sin(a);
vec3 rot = vec3(lab.x, lab.y * cs - lab.z * sn, lab.y * sn + lab.z * cs);
vec4(clamp(toSrgb(oklabToLin(rot)), 0.0, 1.0), c.a)`);

defineNode(`// Duotone: OKLab lightness maps a line between two colours.
// @node adjust.duotone
// @module 04-color-organization
// @alpha
uniform sampler2D in0;
uniform vec3 dark;      // @color @default 0.078 0.102 0.180
uniform vec3 light;     // @color @default 0.949 0.902 0.800
${EXACT}
${OKLAB}
vec4 c = texture2D(in0, uv);
float L = linToOklab(toLin(c.rgb)).x;
vec3 A = linToOklab(toLin(dark)), B = linToOklab(toLin(light));
vec4(clamp(toSrgb(oklabToLin(A + (B - A) * L)), 0.0, 1.0), c.a)`);

defineNode(`// Posterize: each channel to n levels.
// @node adjust.posterize
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform int levels;     // @range 2 12 @default 5
vec4 c = texture2D(in0, uv);
float n = float(max(2, levels) - 1);
vec4(floor(c.rgb * n + 0.5) / n, c.a)`);

defineNode(`// Threshold on luma, 0..255.
// @node adjust.threshold
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform float level;    // @range 0 255 @default 128
${LUMA}
vec4 c = texture2D(in0, uv);
float v = step(level, lumaOf(c.rgb * 255.0));
vec4(vec3(v), c.a)`);

defineNode(`// Ordered dither with the 8×8 Bayer matrix, computed rather than stored:
// the value at (x, y) is the bit-interleave of x^y and y, reversed.
// @node filter.ditherOrdered
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform int levels;     // @range 2 8 @default 2
float bayer8(vec2 p) {
  float v = 0.0;
  for (int k = 0; k < 3; k++) {
    float xb = mod(floor(p.x / pow(2.0, float(k))), 2.0);
    float yb = mod(floor(p.y / pow(2.0, float(k))), 2.0);
    float xy = mod(xb + yb, 2.0);                       // xb ^ yb
    v += (xy * 2.0 + yb) * pow(4.0, float(2 - k));
  }
  return v;
}
vec4 c = texture2D(in0, uv);
float n = float(max(2, levels) - 1);
vec2 px = vec2(gl_FragCoord.x - 0.5, u_resolution.y - gl_FragCoord.y - 0.5);   // CPU's (x, y)
float t = (bayer8(px) / 64.0 - 0.5) * (255.0 / n);
vec4(floor((c.rgb * 255.0 + t) / 255.0 * n + 0.5) / n, c.a)`);

defineNode(`// Halftone: dots on a rotated grid, radius from the luma at the dot's centre.
// @node filter.halftone
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float cell;     // @range 3 20 @default 6
uniform float angle;    // @range 0 90 @default 15
${LUMA}
float s = max(2.0, cell);
float a = radians(angle), cs = cos(a), sn = sin(a);
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec2 rel = px - in0_size * 0.5;
// into the grid's frame, find the nearest lattice point, and back
vec2 g = vec2(rel.x * cs + rel.y * sn, -rel.x * sn + rel.y * cs) / s;
float cov = 0.0;
for (int dv = -1; dv <= 1; dv++) {
  for (int du = -1; du <= 1; du++) {
    vec2 lat = floor(g + 0.5) + vec2(float(du), float(dv));
    vec2 cw = vec2(lat.x * s * cs - lat.y * s * sn, lat.x * s * sn + lat.y * s * cs) + in0_size * 0.5;
    vec2 cp = floor(cw + 0.5);
    if (cp.x < 0.0 || cp.y < 0.0 || cp.x >= in0_size.x || cp.y >= in0_size.y) continue;
    float lum = lumaOf(texture2D(in0, vec2(cp.x + 0.5, in0_size.y - cp.y - 0.5) / in0_size).rgb);
    float r = (1.0 - lum) * s * 0.72;
    if (r <= 0.2) continue;
    // the canvas anti-aliases by area: how much of the pixel square the disc
    // covers. A 4×4 supersample is that area to a sixteenth, and successive
    // canvas fills composite rather than take the max.
    float c = 0.0;
    for (int sy = 0; sy < 4; sy++)
      for (int sx = 0; sx < 4; sx++)
        c += step(length(px + vec2(float(sx) + 0.5, float(sy) + 0.5) / 4.0 - cw), r);
    c /= 16.0;
    cov = cov + c * (1.0 - cov);
  }
}
vec4(vec3(1.0 - cov), 1.0)`);

defineNode(`// Pixelate: the mean of each s×s cell, cells anchored at the top-left like the CPU.
// @node filter.pixelate
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform int   size;     // @range 2 40 @default 8
float s = float(max(2, size));
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec2 cell = floor(px / s) * s;
vec4 acc = vec4(0.0);
float n = 0.0;
for (int dy = 0; dy < 40; dy++) {
  if (dy >= size) break;
  for (int dx = 0; dx < 40; dx++) {
    if (dx >= size) break;
    vec2 q = cell + vec2(float(dx), float(dy));
    if (q.x >= in0_size.x || q.y >= in0_size.y) continue;
    acc += texture2D(in0, vec2(q.x + 0.5, in0_size.y - q.y - 0.5) / in0_size);
    n += 1.0;
  }
}
acc / max(n, 1.0)`);

defineNode(`// Bloom, first half: keep only what is brighter than the cut.
// @node filter.bright
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform float cut;      // @range 100 250 @default 190
${LUMA}
vec4 c = texture2D(in0, uv);
float k = step(cut, lumaOf(c.rgb * 255.0) + 0.001);
vec4(c.rgb * k, c.a)`);

defineNode(`// Bloom, second half: the original plus amount × the softened bright pass (in1).
// @node filter.bloomAdd
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;
uniform float amount;   // @range 0 2 @default 0.7
vec4 o = texture2D(in0, uv);
vec4 s = texture2D(in1, uv);
vec4(min(o.rgb + s.rgb * amount, 1.0), o.a)`);

defineNode(`// Chromatic aberration: red pushed out from the centre, blue pulled in, positions rounded.
// @node filter.chromatic
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float amount;   // @range 0 20 @default 4
${NEAREST}
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec2 d = (px - in0_size * 0.5) / in0_size;
vec2 pr = clamp(floor(px + d * amount + 0.5), vec2(0.0), in0_size - 1.0);
vec2 pb = clamp(floor(px - d * amount + 0.5), vec2(0.0), in0_size - 1.0);
vec4 c = texture2D(in0, uv);
float r = texture2D(in0, vec2(pr.x + 0.5, in0_size.y - pr.y - 0.5) / in0_size).r;
float b = texture2D(in0, vec2(pb.x + 0.5, in0_size.y - pb.y - 0.5) / in0_size).b;
vec4(r, c.g, b, c.a)`);

defineNode(`// Vignette: a squared falloff from the corner distance.
// @node filter.vignette
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float amount;   // @range 0 1 @default 0.5
uniform float softness; // @range 0.1 1 @default 0.6
vec2 px = vec2(gl_FragCoord.x - 0.5, in0_size.y - gl_FragCoord.y - 0.5);
vec2 c0 = in0_size * 0.5;
float t = length(px - c0) / length(c0);
float f = 1.0 - amount * pow(max(0.0, (t - (1.0 - softness)) / softness), 2.0);
vec4 c = texture2D(in0, uv);
vec4(c.rgb * f, c.a)`);

defineNode(`// Film grain: the same noise on all three channels, ±amount in 8-bit units.
// The CPU draws its noise from a seeded stream in scan order, which no
// per-pixel program can reproduce, so parity here is statistical: the mean
// is unchanged and the spread is amount/√3.
// @node filter.grain
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform float amount;   // @range 0 60 @default 14
vec4 c = texture2D(in0, uv);
float n = (hash21(gl_FragCoord.xy + u_seed * 17.0) * 2.0 - 1.0) * amount / 255.0;
vec4(clamp(c.rgb + n, 0.0, 1.0), c.a)`);

defineNode(`// Invert.
// @node adjust.invert
// @module 05-display
// @alpha
uniform sampler2D in0;
vec4 c = texture2D(in0, uv);
vec4(1.0 - c.rgb, c.a)`);

// ------------------------------------------------------------------ catalogue

/**
 * The catalogue as the filter dialog and the self-test see it: one entry per
 * engine-image filter, with a builder that adds the node or nodes to a graph
 * and returns the output id, and the CPU filter's parameter list so both
 * sides get identical defaults. `cpu` is the engine-image id.
 */
export const GRAPH_FILTERS = [
  { id: "blur", cpu: "blur", name: "Gaussian blur",
    build: (g, i, p) => addBlur(g, i, p.radius ?? 4) },
  { id: "motion", cpu: "motion", name: "Motion blur",
    build: (g, i, p) => addNode(g, "filter.motion", { length_: [p.length ?? 16], angle: [p.angle ?? 0] }, [i]) },
  { id: "radial", cpu: "radial", name: "Radial blur",
    build: (g, i, p) => addNode(g, "filter.radial", { strength: [p.strength ?? 0.08], steps: [14] }, [i]) },
  { id: "lens", cpu: "lens", name: "Lens blur",
    build: (g, i, p) => addNode(g, "filter.lens", { radius: [Math.round(p.radius ?? 4)] }, [i]) },
  { id: "unsharp", cpu: "unsharp", name: "Unsharp mask",
    build: (g, i, p) => addNode(g, "filter.unsharp", { amount: [p.amount ?? 0.8] }, [i, addBlur(g, i, p.radius ?? 2)]) },
  { id: "edges", cpu: "edges", name: "Find edges", build: (g, i) => addNode(g, "filter.edges", {}, [i]) },
  { id: "emboss", cpu: "emboss", name: "Emboss", build: (g, i) => addNode(g, "filter.emboss", {}, [i]) },
  { id: "grade", cpu: "grade", name: "Grade",
    build: (g, i, p) => addNode(g, "adjust.grade", { lift: [p.lift ?? 0], gamma: [p.gamma ?? 1], gain: [p.gain ?? 1], sat: [p.sat ?? 1], temp: [p.temp ?? 0] }, [i]) },
  { id: "hue", cpu: "hue", name: "Hue rotate", build: (g, i, p) => addNode(g, "adjust.hue", { degrees: [p.degrees ?? 30] }, [i]) },
  { id: "duotone", cpu: "duotone", name: "Duotone",
    build: (g, i, p) => addNode(g, "adjust.duotone", { dark: hexToVec(p.dark || "#141a2e"), light: hexToVec(p.light || "#f2e6cc") }, [i]) },
  { id: "posterize", cpu: "posterize", name: "Posterize", build: (g, i, p) => addNode(g, "adjust.posterize", { levels: [Math.round(p.levels ?? 5)] }, [i]) },
  { id: "threshold", cpu: "threshold", name: "Threshold", build: (g, i, p) => addNode(g, "adjust.threshold", { level: [p.level ?? 128] }, [i]) },
  { id: "dither-ordered", cpu: "dither-ordered", name: "Dither — ordered", build: (g, i, p) => addNode(g, "filter.ditherOrdered", { levels: [Math.round(p.levels ?? 2)] }, [i]) },
  { id: "dither-diffuse", cpu: "dither-diffuse", name: "Dither — diffusion", cpuOnly: "error diffusion is serial: each pixel's error feeds the next, which no per-pixel program can express" },
  { id: "halftone", cpu: "halftone", name: "Halftone", build: (g, i, p) => addNode(g, "filter.halftone", { cell: [p.cell ?? 6], angle: [p.angle ?? 15] }, [i]) },
  { id: "pixelate", cpu: "pixelate", name: "Pixelate", build: (g, i, p) => addNode(g, "filter.pixelate", { size: [Math.round(p.size ?? 8)] }, [i]) },
  { id: "bloom", cpu: "bloom", name: "Bloom",
    build: (g, i, p) => {
      const bright = addNode(g, "filter.bright", { cut: [p.cut ?? 190] }, [i]);
      const soft = addBlur(g, bright, p.radius ?? 8);
      return addNode(g, "filter.bloomAdd", { amount: [p.amount ?? 0.7] }, [i, soft]);
    } },
  { id: "chromatic", cpu: "chromatic", name: "Chromatic aberration", build: (g, i, p) => addNode(g, "filter.chromatic", { amount: [p.amount ?? 4] }, [i]) },
  { id: "vignette", cpu: "vignette", name: "Vignette", build: (g, i, p) => addNode(g, "filter.vignette", { amount: [p.amount ?? 0.5], softness: [p.softness ?? 0.6] }, [i]) },
  { id: "grain", cpu: "grain", name: "Film grain", statistical: true, build: (g, i, p) => addNode(g, "filter.grain", { amount: [p.amount ?? 14] }, [i]) },
  { id: "invert", cpu: "invert", name: "Invert", build: (g, i) => addNode(g, "adjust.invert", {}, [i]) },
];

export const hexToVec = (hx) => [1, 3, 5].map((k) => parseInt(String(hx).slice(k, k + 2), 16) / 255);
export const graphFilter = (id) => GRAPH_FILTERS.find((f) => f.id === id) || null;
