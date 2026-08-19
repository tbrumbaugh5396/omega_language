// The node reference, written by the nodes.
//
// The roadmap's rule for documentation is that it is generated and never
// hand-maintained, and the annotation grammar already carries everything a
// reference needs: the first comment line is what the node is, `@module` is
// the lesson it belongs with, `@range`/`@default`/`@help` describe each
// control, `@pass` and `@alpha` say how it behaves in a chain. So there is
// nothing to write down twice — this reads what is there.
//
// The one thing it adds is judgement about *absence*: a node with no
// description, or a control with no help, is reported rather than quietly
// rendered as a blank. Documentation you cannot see the holes in is worse
// than none.

import { parseUniforms, sketchMeta } from "./shader-uniforms.js";
import { NODE_TYPES } from "./render-graph.js";
import { GRAPH_FILTERS } from "./filter-nodes.js";
import { isUserNode } from "./node-library.js";

/** One node, as documentation. */
export function documentNode(id, type) {
  const meta = sketchMeta(type.source);
  const uniforms = parseUniforms(type.source);
  const params = uniforms
    .filter((u) => u.control !== "image" && !u.hidden)
    .map((u) => ({
      name: u.name, control: u.control, type: u.type,
      range: u.control === "slider" || u.control === "select" ? [u.min, u.max] : null,
      options: u.options || null,
      value: u.value, help: u.help || null, label: u.label !== u.name ? u.label : null,
    }));
  const catalogue = GRAPH_FILTERS.find((f) => {
    try { return f.build && String(f.build).includes(`"${id}"`); } catch { return false; }
  });
  return {
    id, module: meta.module || null,
    title: meta.title || type.title || id,
    inputs: type.inputs.slice(),
    pass: !!meta.pass, alpha: !!meta.alpha,
    params, mine: isUserNode(id),
    catalogue: catalogue ? catalogue.name : null,
    // What is missing, said plainly.
    gaps: [
      !meta.title ? "no description — the first comment line is what a node is" : null,
      !meta.module ? "no @module, so it links to no lesson" : null,
      ...params.filter((p) => !p.help && p.control === "slider").map((p) => `${p.name} has no @help`),
    ].filter(Boolean),
  };
}

/** Every registered node, grouped by the course module it belongs with. */
export function nodeReference() {
  const docs = [];
  for (const [id, t] of NODE_TYPES) docs.push(documentNode(id, t));
  docs.sort((a, b) => (a.module || "zz").localeCompare(b.module || "zz") || a.id.localeCompare(b.id));
  const groups = new Map();
  for (const d of docs) {
    const key = d.module || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(d);
  }
  return { docs, groups };
}

/** How complete the reference is — the number that keeps it honest. */
export function referenceGaps() {
  const { docs } = nodeReference();
  const withGaps = docs.filter((d) => d.gaps.length);
  return { total: docs.length, documented: docs.length - withGaps.length, withGaps };
}
