// The render graph: the document that every editor authors and GLSL is
// compiled from.
//
// A node type is a sketch — the same text Generate runs — with a header the
// graph reads: `@node adjust.exposure`, `@module 05-display`, `@pass` when it
// samples a neighbourhood and so cannot be fused with its neighbours. Its
// inputs are samplers named in0, in1, …; its parameters are the uniforms the
// annotation grammar already describes. That is the whole contract, and it is
// what lets a user's own Generate document be a node with no further
// ceremony.
//
// A graph is nodes with parameters and input references, and one output.
// Nothing here draws; graph-compile.js turns a graph into passes.

import { parseUniforms, sketchMeta } from "./shader-uniforms.js";

// ------------------------------------------------------------------ types

export const NODE_TYPES = new Map();

/** Register a node type from its sketch text. Returns the type. */
export function defineNode(source, extra = {}) {
  const meta = sketchMeta(source);
  if (!meta.node) throw new Error("a node type needs `// @node <id>` in its header");
  const uniforms = parseUniforms(source);
  const inputs = uniforms.filter((u) => u.control === "image" && /^in\d+$/.test(u.name))
    .map((u) => u.name).sort();
  const params = uniforms.filter((u) => !(u.control === "image" && /^in\d+$/.test(u.name)));
  const type = {
    id: meta.node, title: extra.title || meta.title || meta.node,
    module: meta.module, pass: meta.pass, precision: meta.precision, space: meta.space,
    source, uniforms, inputs, params,
    // Parameters that are textures the host builds from a value, e.g. a curve
    // LUT from control points. Declared with @lut on the sampler.
    luts: uniforms.filter((u) => u.control === "image" && u.lut).map((u) => u.name),
    ...extra,
  };
  NODE_TYPES.set(type.id, type);
  return type;
}

export const nodeType = (id) => NODE_TYPES.get(id) || null;

// ------------------------------------------------------------------ graph

let nextId = 1;

export function createGraph(width, height) {
  return { width, height, nodes: [], output: null };
}

/**
 * Add a node. `type` is a registered id, or "source" for an external texture
 * (the host supplies it at run time, keyed by this node's id).
 */
export function addNode(graph, type, params = {}, inputs = []) {
  if (type !== "source" && !NODE_TYPES.has(type)) throw new Error(`no node type "${type}"`);
  const id = `n${nextId++}`;
  graph.nodes.push({ id, type, params: { ...params }, inputs: inputs.slice(), bypass: false });
  return id;
}

export const findNode = (graph, id) => graph.nodes.find((n) => n.id === id) || null;

/**
 * Nodes in dependency order, from sources to the output, restricted to what
 * the output actually needs. A bypassed node stands in for its first input.
 */
export function topo(graph) {
  const order = [], seen = new Set();
  const visit = (id) => {
    if (!id || seen.has(id)) return;
    const n = findNode(graph, id);
    if (!n) throw new Error(`graph refers to missing node ${id}`);
    seen.add(id);
    for (const i of n.inputs) visit(i);
    order.push(n);
  };
  visit(graph.output);
  return order;
}

/** Problems a compiler would trip on, said in one place. */
export function validate(graph) {
  const errors = [];
  if (!graph.output) errors.push("no output node");
  for (const n of graph.nodes) {
    if (n.type === "source") continue;
    const t = nodeType(n.type);
    if (!t) { errors.push(`${n.id}: unknown type ${n.type}`); continue; }
    t.inputs.forEach((name, i) => {
      if (!n.inputs[i]) errors.push(`${n.id} (${n.type}): input ${name} is not connected`);
      else if (!findNode(graph, n.inputs[i])) errors.push(`${n.id}: input ${name} refers to a missing node`);
    });
  }
  try { topo(graph); } catch (e) { errors.push(e.message); }
  return errors;
}

/** Effective node for reading: follow bypasses down to something that draws. */
export function resolveBypass(graph, id) {
  let n = findNode(graph, id);
  let guard = 0;
  while (n && n.bypass && n.inputs[0] && guard++ < 64) n = findNode(graph, n.inputs[0]);
  return n;
}

// ------------------------------------------------------------------ built-ins
//
// The four proving nodes: a per-pixel adjustment, a LUT, a two-input
// composite, and a neighbourhood pass. If these compile, run and eject, the
// rest of the library is repetition.

defineNode(`// Exposure, in stops, about linear light.
// @node adjust.exposure
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform float stops;    // @range -4 4 @default 0 @help exposure in stops
uniform float offset;   // @range -0.2 0.2 @default 0 @help added after, in linear light

vec4 c = texture2D(in0, uv);
vec3 lin = srgbToLinear(c.rgb) * exp2(stops) + offset;
vec4(linearToSrgb(clamp(lin, 0.0, 1.0)), c.a)`);

defineNode(`// A tone curve, applied through a 256-entry lookup the host builds from control points.
// @node adjust.curves
// @module 05-display
// @alpha
uniform sampler2D in0;
uniform sampler2D curve;   // @hidden @lut the master curve, 256×1
uniform float amount;      // @range 0 1 @default 1 @help how much of the curve to apply

vec4 c = texture2D(in0, uv);
vec3 mapped = vec3(texture2D(curve, vec2(c.r, 0.5)).r,
                   texture2D(curve, vec2(c.g, 0.5)).g,
                   texture2D(curve, vec2(c.b, 0.5)).b);
vec4(mix(c.rgb, mapped, amount), c.a)`);

defineNode(`// Composite in1 over in0 with a blend mode and an opacity. Encoded space, as the browser does.
// @node composite.blend
// @module 03-additive-subtractive
// @alpha
uniform sampler2D in0;
uniform sampler2D in1;
uniform int   mode;      // @options normal,multiply,screen,overlay,darken,lighten,difference,add @default 0
uniform float opacity;   // @range 0 1 @default 1 @help how much of in1 is let through

vec4 a = texture2D(in0, uv);
vec4 b = texture2D(in1, uv);
vec3 r = b.rgb;
if (mode == 1) r = a.rgb * b.rgb;
else if (mode == 2) r = 1.0 - (1.0 - a.rgb) * (1.0 - b.rgb);
else if (mode == 3) r = mix(2.0 * a.rgb * b.rgb, 1.0 - 2.0 * (1.0 - a.rgb) * (1.0 - b.rgb), step(0.5, a.rgb));
else if (mode == 4) r = min(a.rgb, b.rgb);
else if (mode == 5) r = max(a.rgb, b.rgb);
else if (mode == 6) r = abs(a.rgb - b.rgb);
else if (mode == 7) r = min(a.rgb + b.rgb, 1.0);
float k = b.a * opacity;
vec4(mix(a.rgb, r, k), max(a.a, k))`);

defineNode(`// One direction of a separable Gaussian: sigma = radius / 2, kernel 2·ceil(radius)+1 wide — the same
// kernel engine-image uses, so the CPU path is the reference. Two of these make a blur.
// @node filter.blur1d
// @module 05-display
// @alpha
// @pass
uniform sampler2D in0;
uniform vec2  in0_size;
uniform float radius;   // @range 0 40 @default 4 @help blur radius in pixels
uniform vec2  dir;      // @hidden

vec4 acc = vec4(0.0);
float total = 0.0;
float sigma = max(radius * 0.5, 0.01);
int reach = int(ceil(radius));          // not "half": that is a reserved word in ES 3.00
for (int i = -40; i <= 40; i++) {
  if (i < -reach || i > reach) continue;
  float wgt = exp(-float(i * i) / (2.0 * sigma * sigma));
  // Premultiplied, so a transparent pixel contributes no colour: blurring
  // straight alpha drags whatever happens to be under the transparency out
  // into the edge, which on a layer with nothing behind it is black.
  vec4 s = texture2D(in0, uv + dir * float(i) / in0_size);
  acc += vec4(s.rgb * s.a, s.a) * wgt;
  total += wgt;
}
vec4 r = acc / total;
radius < 1.0 ? texture2D(in0, uv) : (r.a > 0.0 ? vec4(r.rgb / r.a, r.a) : vec4(0.0))`);

/** A blur is two 1-D passes; this adds both and returns the second's id. */
export function addBlur(graph, input, radius) {
  const h = addNode(graph, "filter.blur1d", { radius: [radius], dir: [1, 0] }, [input]);
  return addNode(graph, "filter.blur1d", { radius: [radius], dir: [0, 1] }, [h]);
}

/**
 * A curve LUT from control points, as 256 RGBA bytes: the same monotone
 * interpolation for all three channels. Points are [[x,y]…] in 0..1.
 */
export function curveLut(points) {
  const pts = (points && points.length ? points : [[0, 0], [1, 1]])
    .map(([x, y]) => [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))])
    .sort((a, b) => a[0] - b[0]);
  if (pts[0][0] > 0) pts.unshift([0, pts[0][1]]);
  if (pts[pts.length - 1][0] < 1) pts.push([1, pts[pts.length - 1][1]]);
  // Fritsch–Carlson monotone cubic: no overshoot, so a curve that never
  // decreases produces a lookup that never decreases either.
  const n = pts.length, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const d = [], m = [];
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / Math.max(1e-6, xs[i + 1] - xs[i]));
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], s = a * a + b * b;
    if (s > 9) { const t = 3 / Math.sqrt(s); m[i] = t * a * d[i]; m[i + 1] = t * b * d[i]; }
  }
  const out = new Uint8ClampedArray(256 * 4);
  for (let k = 0; k < 256; k++) {
    const x = k / 255;
    let i = 0;
    while (i < n - 2 && x > xs[i + 1]) i++;
    const h = Math.max(1e-6, xs[i + 1] - xs[i]), t = (x - xs[i]) / h;
    const t2 = t * t, t3 = t2 * t;
    const y = (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h * m[i]
            + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h * m[i + 1];
    const v = Math.round(255 * Math.min(1, Math.max(0, y)));
    out[k * 4] = out[k * 4 + 1] = out[k * 4 + 2] = v; out[k * 4 + 3] = 255;
  }
  return out;
}
