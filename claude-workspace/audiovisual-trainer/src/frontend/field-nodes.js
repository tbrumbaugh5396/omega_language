// The field catalogue: shapes, the ways they combine, and the two ways to
// look at the result.
//
// Every node here is a function of `p` — the centred, aspect-corrected
// coordinate the sketch prelude already provides, running about -1 to 1 up the
// short axis. A field answers the signed distance to the nearest edge:
// negative inside, zero on the boundary, positive outside. That number is what
// makes the combinators possible, so any node that returns something else —
// a value that is merely negative in the right places — quietly breaks
// everything downstream of it, and the two that do are marked as such.
//
// The shape primitives are the helpers the sketch prelude already carries, so
// the node bodies are one line each and the geometry is the same code the
// Generate presets and the two SDF compilers have been using all along.

import { defineNode } from "./render-graph.js";

const F = (src) => defineNode(src);

// ------------------------------------------------------------------ shapes

F(`// A circle.
// @node field.circle
// @field
// @module 07-shaders
uniform vec2  centre;   // @pad @range -1.5 1.5 @default 0 0 @help where it sits
uniform float radius;   // @range 0 1.5 @default 0.4 @help in short-axis units

sdCircle(p - centre, radius)`);

F(`// A rectangle with rounded corners. Rounding is free here — it is the
// distance itself, offset — which is the first thing a field gives you that a
// rasteriser does not.
// @node field.box
// @field
// @module 07-shaders
uniform vec2  centre;   // @pad @range -1.5 1.5 @default 0 0
uniform vec2  size;     // @pad @range 0 1.5 @default 0.5 0.35 @help half-extents
uniform float corner;   // @range 0 0.5 @default 0.06 @help corner radius

sdBox(p - centre, max(size - corner, 0.0)) - corner`);

F(`// An ellipse. The distance is approximate — an exact one needs a quartic —
// so it is close near the boundary and drifts far from it. That is fine for
// shading and for small offsets, and it is why a big offset of an ellipse
// bulges.
// @node field.ellipse
// @field
// @module 07-shaders
uniform vec2 centre;    // @pad @range -1.5 1.5 @default 0 0
uniform vec2 radii;     // @pad @range 0.01 1.5 @default 0.5 0.3

sdEllipse(p - centre, max(radii, 0.01))`);

F(`// A thick line with round ends: the capsule, which is a segment offset by
// its own radius.
// @node field.segment
// @field
// @module 07-shaders
uniform vec2  a;          // @pad @range -1.5 1.5 @default -0.4 -0.2
uniform vec2  b;          // @pad @range -1.5 1.5 @default 0.4 0.2
uniform float thickness;  // @range 0 0.4 @default 0.08 @help half the line width

sdCapsule(p, a, b, thickness)`);

F(`// A regular polygon — iq's exact construction: fold the plane into one
// wedge, then measure to that wedge's single edge.
// @node field.polygon
// @field
// @module 07-shaders
uniform vec2  centre;   // @pad @range -1.5 1.5 @default 0 0
uniform float sides;    // @range 3 12 @step 1 @int @default 5 @help how many corners
uniform float radius;   // @range 0.02 1.5 @default 0.45 @help to the vertices
uniform float corner;   // @range 0 0.4 @default 0 @help corner radius

float n  = max(sides, 3.0);
float an = 3.14159265 / n;
float he = radius * tan(an);
vec2  q  = -(p - centre).yx;
float bn = 2.0 * an * floor((atan(q.y, q.x) + an) / (2.0 * an));
vec2  cs = vec2(cos(bn), sin(bn));
q = mat2(cs.x, -cs.y, cs.y, cs.x) * q;
length(q - vec2(radius, clamp(q.y, -he, he))) * sign(q.x - radius) - corner`);

// ------------------------------------------------------------------ combining
//
// The three set operations, each with a smoothing radius. At k = 0 they are
// exactly min, max and their signed variants — the hard boolean — and every
// value above that blends the two surfaces over a band k wide. There is no
// rasterised equivalent of the middle of that range: you can union two masks
// or you can blur the result, and neither one is this.

F(`// Union: both shapes, welded. k rounds the weld.
// @node field.union
// @field
// @module 07-shaders
float in0(vec2 p);
float in1(vec2 p);
uniform float k;   // @range 0 0.4 @default 0 @help blend radius; 0 is a hard union

float a = in0(p), b = in1(p);
smin(a, b, max(k, 1e-5))`);

F(`// Subtract: the second shape cut out of the first.
// @node field.subtract
// @field
// @module 07-shaders
float in0(vec2 p);
float in1(vec2 p);
uniform float k;   // @range 0 0.4 @default 0 @help blend radius; 0 is a hard cut

float a = in0(p), b = in1(p);
float kk = max(k, 1e-5);
float h = clamp(0.5 - 0.5 * (b + a) / kk, 0.0, 1.0);
mix(a, -b, h) + kk * h * (1.0 - h)`);

F(`// Intersect: only where both are inside.
// @node field.intersect
// @field
// @module 07-shaders
float in0(vec2 p);
float in1(vec2 p);
uniform float k;   // @range 0 0.4 @default 0 @help blend radius; 0 is a hard intersection

float a = in0(p), b = in1(p);
float kk = max(k, 1e-5);
float h = clamp(0.5 - 0.5 * (b - a) / kk, 0.0, 1.0);
mix(b, a, h) + kk * h * (1.0 - h)`);

// ------------------------------------------------------------------ modifying

F(`// Grow or shrink every edge by the same distance. On a shape with corners
// this rounds the outside and sharpens the inside, which is what offsetting
// actually means and what a blur-and-threshold only approximates.
// @node field.offset
// @field
// @module 07-shaders
float in0(vec2 p);
uniform float amount;   // @range -0.5 0.5 @default 0.05 @help positive grows

in0(p) - amount`);

F(`// The hollow shell of a shape: everything within half a thickness of its edge,
// inside or out. One line, because the distance was there all along.
// @node field.shell
// @field
// @module 07-shaders
float in0(vec2 p);
uniform float thickness;   // @range 0.001 0.4 @default 0.03 @help how wide the ring is

abs(in0(p)) - thickness * 0.5`);

F(`// Move, turn and scale a field. Rotation and translation leave a distance a
// distance; scaling does not, so the result is multiplied back by the factor —
// without that, everything downstream measures in the wrong units.
// @node field.transform
// @field
// @module 07-shaders
float in0(vec2 p);
uniform vec2  offset;   // @pad @range -1.5 1.5 @default 0 0
uniform float angle;    // @range -180 180 @default 0 @help degrees
uniform float scale;    // @range 0.05 4 @default 1 @help uniform scale factor

float s = max(scale, 0.05);
in0(rot(-radians(angle)) * (p - offset) / s) * s`);

F(`// Repeat a field on a grid, a limited number of times each way. Exact in
// the middle of a cell and approximate near the seams, where the true nearest
// copy may be the neighbour's — visible only at large offsets.
// @node field.repeat
// @field
// @module 07-shaders
float in0(vec2 p);
uniform vec2 cell;    // @pad @range 0.05 2 @default 0.6 0.6 @help spacing
uniform vec2 count;   // @pad @range 0 6 @default 1 1 @help how many each side of centre

vec2 c = max(cell, 0.05);
vec2 id = floor(p / c + 0.5);
in0(p - c * clamp(id, -count, count))`);

F(`// Mirror the plane about the axes, so half a shape becomes a whole
// symmetric one. Cheap symmetry: the fold costs an abs().
// @node field.mirror
// @field
// @module 07-shaders
float in0(vec2 p);
uniform float x;   // @toggle @default 1 @help mirror left/right
uniform float y;   // @toggle @default 0 @help mirror top/bottom

in0(vec2(x > 0.5 ? abs(p.x) : p.x, y > 0.5 ? abs(p.y) : p.y))`);

F(`// Push the plane around with noise before measuring. This displaces the
// domain rather than the value, which keeps the result much closer to a true
// distance than adding noise to it would — but it is no longer exact, so a
// large amount followed by a large offset will misbehave.
// @node field.warp
// @field
// @module 07-shaders
float in0(vec2 p);
uniform float amount;   // @range 0 0.5 @default 0.08 @help how far the plane is pushed
uniform float scale;    // @range 0.5 12 @default 3 @help noise frequency
uniform float drift;    // @range 0 1 @default 0 @help animate with the clock

vec2 w = vec2(fbm(p * scale + drift * t), fbm(p * scale + 7.3 - drift * t)) - 0.5;
in0(p + w * amount)`);

// ------------------------------------------------------------------ shading
//
// Where a field stops being a function and becomes pixels. Everything above
// this line composes; nothing below it does.

F(`// Paint a field: a glow under a fill under a stroke, each antialiased
// against the distance itself rather than against a supersampled guess.
// The glow is the giveaway — it is a falloff in distance, which is something
// you simply do not have once a shape has become pixels.
// @node field.shade
// @module 07-shaders
// @alpha
float in0(vec2 p);
uniform vec3  fill;        // @color @default #f4efe6
uniform float filled;      // @toggle @default 1
uniform vec3  stroke;      // @color @default #1b2b4b
uniform float width;       // @range 0 0.2 @default 0 @help stroke width, 0 for none
uniform vec3  glowColour;  // @color @default #ff7a3d
uniform float glow;        // @range 0 0.6 @default 0 @help falloff distance, 0 for none

float d = in0(p);
float fa = filled > 0.5 ? aa(d) : 0.0;
float sa = width > 0.0 ? aa(abs(d) - width * 0.5) : 0.0;
float ga = glow  > 0.0 ? exp(-max(d, 0.0) / glow) * (1.0 - fa) : 0.0;
// Straight alpha, painted bottom up: glow, then fill, then stroke.
float a1 = ga;
float a2 = fa + a1 * (1.0 - fa);
vec3  c2 = a2 > 0.0 ? (fill * fa + glowColour * a1 * (1.0 - fa)) / a2 : vec3(0.0);
float a3 = sa + a2 * (1.0 - sa);
vec3  c3 = a3 > 0.0 ? (stroke * sa + c2 * a2 * (1.0 - sa)) / a3 : vec3(0.0);
vec4(c3, a3)`);

F(`// Look at the field instead of the shape it describes: bands of constant
// distance, warm outside and cool inside, with the zero contour picked out in
// white. If the bands are not evenly spaced, whatever fed this is not
// returning a distance, and the combinators upstream are lying.
// @node field.contours
// @module 07-shaders
float in0(vec2 p);
uniform float spacing;   // @range 4 200 @default 40 @help bands per unit

float d = in0(p);
vec3 col = d > 0.0 ? vec3(0.92, 0.58, 0.32) : vec3(0.24, 0.48, 0.62);
col *= 1.0 - exp(-6.0 * abs(d));
col *= 0.85 + 0.15 * cos(spacing * 6.28318 * d);
mix(col, vec3(1.0), 1.0 - smoothstep(0.0, 0.008, abs(d)))`);

/** Everything the field catalogue registers, for menus and the reference. */
export const FIELD_NODES = [
  "field.circle", "field.box", "field.ellipse", "field.segment", "field.polygon",
  "field.union", "field.subtract", "field.intersect",
  "field.offset", "field.shell", "field.transform", "field.repeat", "field.mirror", "field.warp",
  "field.shade", "field.contours",
];
