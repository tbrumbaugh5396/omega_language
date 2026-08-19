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

import { parseUniforms, sketchMeta, stripComments } from "./shader-uniforms.js";

// ------------------------------------------------------------------ types

export const NODE_TYPES = new Map();

// Types the compiler writes for itself — one per distinct field topology, from
// field-graph.js. They are node types in every respect the runner cares about,
// and in none that the library cares about: nothing authored them, so they are
// kept out of NODE_TYPES and out of the node reference.
const DERIVED_TYPES = new Map();
const DERIVED_CAP = 64;

const IN_NAME = /^in\d+$/;
// A field port is declared the way GLSL declares any function it intends to
// call: `float in0(vec2 p);`. The graph reads that prototype as a port, and
// the compiler satisfies it with the function its upstream node emitted.
const FIELD_PORT = /\bfloat\s+(in\d+)\s*\(\s*vec2\s*[A-Za-z_]\w*\s*\)\s*;/g;

/** The field ports a sketch declares, in index order. */
export function fieldPorts(source) {
  const bare = stripComments(String(source));
  const found = new Set();
  FIELD_PORT.lastIndex = 0;
  let m;
  while ((m = FIELD_PORT.exec(bare))) found.add(m[1]);
  return [...found].sort((a, b) => +a.slice(2) - +b.slice(2));
}

const byIndex = (a, b) => +a.slice(2) - +b.slice(2);

function makeType(source, extra = {}) {
  const meta = sketchMeta(source);
  if (!meta.node) throw new Error("a node type needs `// @node <id>` in its header");
  const uniforms = parseUniforms(source);
  const images = uniforms.filter((u) => u.control === "image" && IN_NAME.test(u.name)).map((u) => u.name);
  const fields = fieldPorts(source);
  const clash = fields.find((f) => images.includes(f));
  if (clash) throw new Error(`${meta.node}: ${clash} is declared as both an image and a field`);
  // Both kinds of port share one namespace, so `n.inputs[i]` means the same
  // thing whatever the port carries and nothing downstream has to ask.
  const inputs = images.concat(fields).sort(byIndex);
  const params = uniforms.filter((u) => !(u.control === "image" && IN_NAME.test(u.name)));
  return {
    id: meta.node, title: extra.title || meta.title || meta.node,
    module: meta.module, pass: meta.pass, precision: meta.precision, space: meta.space,
    source, uniforms, inputs, params,
    // A field node answers a distance rather than a colour. It is never a pass
    // of its own — GLSL has no function pointers, so a field can only be
    // composed by the text generator, never by binding a buffer at run time.
    field: meta.field, fieldInputs: fields,
    // Parameters that are textures the host builds from a value, e.g. a curve
    // LUT from control points. Declared with @lut on the sampler.
    luts: uniforms.filter((u) => u.control === "image" && u.lut).map((u) => u.name),
    ...extra,
  };
}

/** Register a node type from its sketch text. Returns the type. */
export function defineNode(source, extra = {}) {
  const type = makeType(source, extra);
  NODE_TYPES.set(type.id, type);
  return type;
}

/** Register a type the compiler generated. Same contract, different shelf. */
export function defineDerived(source, extra = {}) {
  const type = makeType(source, { ...extra, derived: true });
  if (DERIVED_TYPES.has(type.id)) return DERIVED_TYPES.get(type.id);
  if (DERIVED_TYPES.size >= DERIVED_CAP) DERIVED_TYPES.delete(DERIVED_TYPES.keys().next().value);
  DERIVED_TYPES.set(type.id, type);
  return type;
}

export const nodeType = (id) => NODE_TYPES.get(id) || DERIVED_TYPES.get(id) || null;

/** Does this node hand on a distance field rather than pixels? */
export function isField(graph, id) {
  const n = findNode(graph, id);
  if (!n || n.type === "source") return false;
  const t = nodeType(n.type);
  return !!(t && t.field);
}

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
  // A field is a function, not a picture. Asking for one as the output is the
  // commonest way to get this wrong, and it is worth saying so in those words
  // rather than failing later inside the compiler.
  else if (isField(graph, graph.output)) {
    errors.push(`${graph.output} answers a distance, not pixels — shade it before it can be the output`);
  }
  for (const n of graph.nodes) {
    if (n.type === "source") continue;
    const t = nodeType(n.type);
    if (!t) { errors.push(`${n.id}: unknown type ${n.type}`); continue; }
    t.inputs.forEach((name, i) => {
      if (!n.inputs[i]) { errors.push(`${n.id} (${n.type}): input ${name} is not connected`); return; }
      if (!findNode(graph, n.inputs[i])) { errors.push(`${n.id}: input ${name} refers to a missing node`); return; }
      // The whole point of typing a port: a wire that carries the wrong thing
      // is caught here, by name, before a line of GLSL is written.
      const wants = t.fieldInputs.includes(name);
      const gives = isField(graph, n.inputs[i]);
      if (wants !== gives) {
        errors.push(`${n.id} (${n.type}): ${name} takes ${wants ? "a field" : "an image"}, `
                  + `but ${n.inputs[i]} gives ${gives ? "a field" : "an image"}`);
      }
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
