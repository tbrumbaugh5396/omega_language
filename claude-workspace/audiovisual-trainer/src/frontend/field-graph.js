// Field wires: a port that carries a function, not a texture.
//
// Everywhere else in this graph a wire is pixels — one node draws into a
// buffer and the next samples it. That is exact for colour and lossy for
// geometry: a shape becomes pixels early, and from then on it is a photo of a
// shape. You cannot ask a photo what its distance to the nearest edge is, so
// you cannot round its corners, offset it, or smoothly merge it with another.
//
// A field wire carries the distance function itself. `field.circle` does not
// draw a circle; it emits
//
//     float f3_field(vec2 p) { return length(p) - f3_radius; }
//
// and `field.union` emits a function that calls it. The wire becomes a call,
// the graph's topology becomes the call graph, and union, subtract, offset and
// repeat are ordinary nodes rather than things you have to write by hand.
//
// This has to happen in the text generator. GLSL ES 3.00 has no function
// pointers and no first-class functions, so two distance functions cannot be
// combined at run time by binding something — only by being written into one
// file together. So a field tree is never several passes: the whole tree, plus
// the node that shades it, compiles to exactly one program.
//
// The rest of the compiler never learns about any of this. `compileFields`
// rewrites the graph before planning: each field-consuming node becomes an
// ordinary node of a generated type, every field node disappears, and fusion,
// ejection, parameter binding and tiling carry on unchanged.

import { splitSketch, sketchMeta } from "./shader-uniforms.js";
import { prefixer } from "./sketch-rename.js";
import { nodeType, defineDerived, findNode } from "./render-graph.js";

/** A short stable name for a piece of generated text. */
function digest(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

/**
 * The field nodes feeding `id`, in dependency order.
 *
 * A field node reached twice is emitted once — but a field node feeding two
 * different consumers is emitted into both programs, because each program is a
 * separate file and there is nowhere shared to put it.
 */
function fieldTree(graph, id, into, seen) {
  if (seen.has(id)) return;
  seen.add(id);
  const n = findNode(graph, id);
  if (!n) throw new Error(`a field wire refers to missing node ${id}`);
  const t = nodeType(n.type);
  if (!t || !t.field) throw new Error(`${id} (${n.type}) was wired to a field port but is not a field`);
  for (const src of n.inputs) fieldTree(graph, src, into, seen);
  into.push(n);
}

/**
 * One field-consuming node and everything upstream of it, as a single sketch.
 *
 * Returns { sketch, order } where `order` is the consumer followed by its
 * field tree, in the index order their prefixes were assigned — the caller
 * needs it to collect the parameters back out.
 */
export function fieldSketch(graph, consumer) {
  const ct = nodeType(consumer.type);
  const tree = [];
  const seen = new Set();
  ct.inputs.forEach((name, i) => {
    if (ct.fieldInputs.includes(name)) fieldTree(graph, consumer.inputs[i], tree, seen);
  });

  // The consumer is f0; its field tree follows, in dependency order, so a
  // function is always defined before the function that calls it.
  const order = [consumer, ...tree];
  const indexOf = new Map(order.map((n, k) => [n.id, k]));
  const decls = [], funcs = [], roster = [];

  // Image ports are renumbered rather than prefixed: the generated sketch is a
  // node type like any other, and a node type's image inputs are in0, in1, …
  const imageSources = [];

  const emit = (n, k) => {
    const t = nodeType(n.type);
    const parts = splitSketch(t.source);
    const pref = `f${k}_`;
    const fix = prefixer(t.source, parts, pref);

    // Each field port becomes a call to whichever function that wire came from.
    const wires = [];
    t.inputs.forEach((name, i) => {
      if (!t.fieldInputs.includes(name)) return;
      const from = indexOf.get(n.inputs[i]);
      wires.push([new RegExp(`\\b${pref}${name}\\s*\\(`, "g"), `f${from}_field(`]);
    });
    // …and each image port takes the next free slot in the generated node.
    const images = [];
    t.inputs.forEach((name, i) => {
      if (t.fieldInputs.includes(name)) return;
      const slot = imageSources.length;
      imageSources.push(n.inputs[i]);
      images.push([new RegExp(`\\b${pref}${name}\\b`, "g"), `in${slot}`]);
    });
    const wire = (s) => {
      let out = fix(s);
      for (const [re, to] of wires) out = out.replace(re, to);
      for (const [re, to] of images) out = out.replace(re, to);
      return out;
    };

    roster.push(`//   f${k} = ${n.type}`);
    for (const chunk of parts.declTexts) {
      // A field port's prototype is satisfied by a real function now, so the
      // forward declaration would be a second, conflicting one.
      if (t.fieldInputs.some((name) => new RegExp(`\\bfloat\\s+${name}\\s*\\(`).test(chunk))) continue;
      decls.push(wire(chunk));
    }
    const stmts = parts.stmtTexts.map(wire).join("\n");
    return { stmts, expr: wire(parts.expr || "0.0") };
  };

  // The consumer is emitted first so it takes the low image slots and reads
  // first in the roster; the tree follows in dependency order, so a function
  // is always defined before the function that calls it.
  const body = emit(consumer, 0);
  tree.forEach((n, i) => {
    const k = i + 1;
    const { stmts, expr } = emit(n, k);
    // The parameter shadows the file-scope `p` deliberately: that is exactly
    // what lets field.transform call its input at a different place.
    funcs.push(`// ${n.type}\nfloat f${k}_field(vec2 p) {\n${stmts ? stmts + "\n" : ""}  return ${expr};\n}`);
  });

  // Prototypes go above everything. A node's own helper may call the field it
  // was wired to, and that helper is declared among the uniforms — so the
  // names have to exist before the first declaration, not merely before the
  // definitions.
  const protos = tree.map((_, i) => `float f${i + 1}_field(vec2 p);`).join("\n");

  const meta = sketchMeta(ct.source);
  const sketch = [
    `// ${tree.length} field node${tree.length === 1 ? "" : "s"} and the ${consumer.type} that shades them,`,
    `// composed into one program. Each field became a function of p; each wire`,
    `// became a call. GLSL has no function pointers, so this is the only place`,
    `// the composition can happen — and having happened, it is ordinary GLSL.`,
    ...roster,
    `// Compiled from the graph. Nothing here was written by hand.`,
    `// @node field.compiled.PLACEHOLDER`,
    meta.alpha ? "// @alpha" : null,
    meta.pass ? "// @pass" : null,
    meta.module ? `// @module ${meta.module}` : null,
    "",
    protos,
    "",
    decls.join("\n"),
    "",
    funcs.join("\n\n"),
    "",
    body.stmts,
    body.expr,
  ].filter((l) => l !== null).join("\n");

  return { sketch: sketch.replace("PLACEHOLDER", digest(sketch)), order, imageSources };
}

/**
 * Rewrite a graph so nothing in it is a field.
 *
 * Each node with a field port becomes a node of a generated type holding its
 * whole upstream tree; the field nodes themselves are dropped. A graph with no
 * fields in it is returned untouched, so the ordinary path pays nothing.
 */
export function compileFields(graph) {
  const hasField = graph.nodes.some((n) => {
    const t = nodeType(n.type);
    return t && (t.field || t.fieldInputs.length);
  });
  if (!hasField) return graph;

  const nodes = [];
  for (const n of graph.nodes) {
    const t = n.type === "source" ? null : nodeType(n.type);
    if (t && t.field) continue;                       // folded into its consumer
    if (!t || !t.fieldInputs.length) { nodes.push(n); continue; }

    const { sketch, order, imageSources } = fieldSketch(graph, n);
    const type = defineDerived(sketch);
    // Every parameter of every node in the tree, under the prefix its text was
    // written with — so the program is cached by topology and a slider still
    // costs a uniform update rather than a recompile.
    const params = {};
    order.forEach((m, k) => {
      const mt = nodeType(m.type);
      for (const u of mt.params) {
        const v = m.params[u.name];
        params[`f${k}_${u.name}`] = Array.isArray(v) ? v
          : (v !== undefined && v !== null ? [v] : (u.value ? u.value.slice() : null));
      }
    });
    nodes.push({ id: n.id, type: type.id, params, inputs: imageSources, bypass: n.bypass });
  }
  return { ...graph, nodes };
}

/** What compiling the fields did, for the panel and the self-test. */
export function fieldStats(graph) {
  const fields = graph.nodes.filter((n) => {
    const t = nodeType(n.type);
    return t && t.field;
  });
  const consumers = graph.nodes.filter((n) => {
    const t = nodeType(n.type);
    return t && !t.field && t.fieldInputs.length;
  });
  return {
    fields: fields.length,
    consumers: consumers.length,
    // Every field node is one function in somebody's program and never a draw
    // of its own; this is the number of passes that never happened.
    passesSaved: fields.length,
    types: [...new Set(fields.map((n) => n.type))],
  };
}
