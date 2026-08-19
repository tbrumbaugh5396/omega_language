// A layer's effect stack, as a graph.
//
// Applying a filter used to mean replacing the layer's pixels. It does not
// any more: a filter is an entry in the layer's stack, and the stack is a
// subgraph run over the layer's pixels every time the layer is drawn. The
// entries stay editable, reorderable and bypassable, and nothing is lost —
// which is the whole difference between an editor that edits a picture and
// one that edits a document.
//
// An entry is one of four kinds:
//
//   graph   a catalogue filter, built as nodes (filter-nodes.js)
//   node    one render-graph node type, with its uniforms as parameters
//   cpu     a filter with no GPU form yet — error diffusion, mostly
//   sketch  a Generate document used as a filter, the layer passed in as its image
//
// Consecutive graph and node entries are collected into ONE graph before it
// runs, so fusion works across filter boundaries: grade + hue + vignette in a
// stack is a single draw, exactly as if they had been written as one shader.

import * as I from "./engine-image.js";
import { createGraph, addNode, addBlur, nodeType } from "./render-graph.js";
import { renderGraph, ejectGraph } from "./graph-compile.js";
import { fuseStats } from "./graph-fuse.js";
import { graphFilter, GRAPH_FILTERS } from "./filter-nodes.js";
import { renderSketch, sketchUniforms } from "./shader-run.js";

const first = (v, d) => (Array.isArray(v) ? v[0] : (v === undefined || v === null ? d : v));

/**
 * Three sliders are friendlier than five control points, so shadows/mids/highs
 * become a curve here rather than in the dialog — the document keeps the
 * sliders, and the node gets what it needs.
 */
export function curveFromSliders(v) {
  const sh = first(v.shadows, 0), mi = first(v.mids, 0), hi = first(v.highs, 0);
  return { points: [[0, 0], [0.25, 0.25 + sh * 0.25], [0.5, 0.5 + mi * 0.25], [0.75, 0.75 + hi * 0.25], [1, 1]] };
}

/** Add one effect to a graph, on top of `input`. Returns the new output id. */
export function effectNode(graph, input, eff) {
  if (eff.kind === "graph") {
    const gf = graphFilter(eff.ref);
    if (!gf || !gf.build) throw new Error(`no graph filter "${eff.ref}"`);
    return gf.build(graph, input, eff.params || {});
  }
  if (eff.kind === "node") {
    const vals = { ...(eff.params || {}) };
    if (eff.ref === "filter.blur") return addBlur(graph, input, first(vals.radius, 4));
    if (eff.ref === "adjust.curves" && vals.shadows) vals.curve = curveFromSliders(vals);
    return addNode(graph, eff.ref, vals, [input]);
  }
  throw new Error(`${eff.kind} is not a graph effect`);
}

const isGraphKind = (e) => e.kind === "graph" || e.kind === "node";

/** One non-graph effect, on the CPU or through a sketch. */
function applyOther(canvas, eff) {
  if (eff.kind === "cpu") {
    const f = I.FILTERS.find((x) => x.id === eff.ref);
    if (!f) throw new Error(`no filter "${eff.ref}"`);
    const flat = {};
    for (const [k, v] of Object.entries(eff.params || {})) flat[k] = Array.isArray(v) ? v[0] : v;
    return I.putImage(I.makeCanvas(canvas.width, canvas.height), f.fn(I.getImage(canvas), flat));
  }
  if (eff.kind === "sketch") {
    return renderSketch(eff.source, canvas.width, canvas.height, {
      images: { [eff.imageName]: canvas }, values: eff.params || {}, time: eff.time || 0, steps: 8 });
  }
  throw new Error(`unknown effect kind "${eff.kind}"`);
}

/**
 * Run a stack over a canvas. Returns a new canvas, or the one it was given
 * when nothing is enabled — the caller must not assume a copy.
 */
export function applyEffects(base, effects) {
  const list = (effects || []).filter((e) => !e.bypass);
  if (!list.length) return base;
  let cur = base, i = 0;
  while (i < list.length) {
    if (!isGraphKind(list[i])) { cur = applyOther(cur, list[i]); i++; continue; }
    // As long a run of graph work as possible, in one graph, so that fusion
    // sees across the boundary between one filter and the next.
    const graph = createGraph(cur.width, cur.height);
    const src = addNode(graph, "source");
    let last = src;
    while (i < list.length && isGraphKind(list[i])) { last = effectNode(graph, last, list[i]); i++; }
    graph.output = last;
    cur = renderGraph(graph, { [src]: cur });
  }
  return cur;
}

/** What a stack costs: draws after fusion, and how many steps stay on the CPU. */
export function effectCost(effects) {
  const list = (effects || []).filter((e) => !e.bypass);
  let draws = 0, cpu = 0, nodes = 0, i = 0;
  while (i < list.length) {
    if (!isGraphKind(list[i])) { cpu++; i++; continue; }
    const graph = createGraph(64, 64);
    const src = addNode(graph, "source");
    let last = src;
    while (i < list.length && isGraphKind(list[i])) { last = effectNode(graph, last, list[i]); i++; }
    graph.output = last;
    const st = fuseStats(graph);
    draws += st.after; nodes += st.before;
  }
  return { draws, cpu, nodes, effects: list.length };
}

/** The GLSL a stack compiles to, fused, with the CPU steps named where they fall. */
export function ejectEffects(effects, w, h) {
  const list = (effects || []).filter((e) => !e.bypass);
  const out = [];
  let i = 0;
  while (i < list.length) {
    if (!isGraphKind(list[i])) {
      out.push(`// ---- ${effectLabel(list[i])}: stays on the CPU (${list[i].kind}); no GLSL for this step`);
      i++; continue;
    }
    const graph = createGraph(w, h);
    const src = addNode(graph, "source");
    let last = src;
    const names = [];
    while (i < list.length && isGraphKind(list[i])) { names.push(effectLabel(list[i])); last = effectNode(graph, last, list[i]); i++; }
    graph.output = last;
    out.push(`// ---- ${names.join(" → ")}\n${ejectGraph(graph)}`);
  }
  return out.join("\n\n");
}

/** The name a stack entry goes by in the panel. */
export function effectLabel(eff) {
  if (!eff) return "";
  if (eff.kind === "graph") {
    const gf = GRAPH_FILTERS.find((f) => f.id === eff.ref);
    return gf ? gf.name : eff.ref;
  }
  if (eff.kind === "node") {
    if (eff.ref === "filter.blur") return "Gaussian blur";
    const t = nodeType(eff.ref);
    return t ? t.title : eff.ref;
  }
  if (eff.kind === "cpu") {
    const f = I.FILTERS.find((x) => x.id === eff.ref);
    return f ? `${f.name} (CPU)` : eff.ref;
  }
  return eff.name || "Shader";
}

/** A stack entry, ready to store: plain data, nothing live in it. */
export function makeEffect(kind, ref, params, extra = {}) {
  return { id: `e${Math.random().toString(36).slice(2, 8)}`, kind, ref,
           params: JSON.parse(JSON.stringify(params || {})), bypass: false, ...extra };
}

/** A sketch used as a filter needs to know which uniform is the layer. */
export function sketchEffect(source, values, time, name) {
  const uniforms = sketchUniforms(source);
  const img = uniforms.find((u) => u.control === "image");
  if (!img) throw new Error("that sketch takes no image, so it cannot filter a layer");
  return makeEffect("sketch", "", values, { source, imageName: img.name, time: time || 0, name: name || "Shader" });
}
