// Fusion: consecutive per-pixel nodes become one pass.
//
// A node without `@pass` promises to read its input only at `uv` — that is
// the whole meaning of the annotation, and it is what makes the framebuffer
// between two such nodes pointless. Fusion cashes the promise in: each node's
// sketch becomes a function, and the colour is carried from one to the next in
// a register.
//
//   grade → hue → duotone → vignette → invert
//   five draws, four half-float buffers   →   one draw, none
//
// The fused text is itself a sketch: the same shorthand, the same annotation
// grammar, readable and ejectable. Nothing here draws — graph-compile.js runs
// the plan, and falls back to one-pass-per-node if a fused program will not
// compile, so fusion can make the picture faster but never different.
//
// The promise is checked, not trusted. A node is left alone if it samples an
// input anywhere but `uv`, moves `uv`, keeps state, or takes a host image.

import { parseUniforms, splitSketch, stripComments, sketchMeta } from "./shader-uniforms.js";
import { nodeType, topo } from "./render-graph.js";

const IN_RE = /^in(\d+)$/;

/** Why this node cannot be fused, or null if it can. */
export function fusibleReason(node) {
  if (node.type === "source") return "a source texture";
  if (node.bypass) return "bypassed";
  const t = nodeType(node.type);
  if (!t) return "unknown type";
  if (t.pass) return "reads a neighbourhood (@pass)";
  const bare = stripComments(t.source);
  if (/\bvec4\s+sim\s*\(/.test(bare)) return "keeps state";
  if (/\buv\s*=[^=]/.test(bare)) return "moves uv";
  for (const u of t.uniforms) {
    if (u.control === "image" && !IN_RE.test(u.name) && !u.lut) return `takes a host image (${u.name})`;
  }
  // Every mention of an input must be a read at uv, or its size.
  const probe = bare
    .replace(/uniform\s+sampler2D\s+in\d+\s*;/g, " ")
    .replace(/\bin\d+_size\b/g, " ")
    .replace(/texture2D\s*\(\s*in\d+\s*,\s*uv\s*\)/g, " ");
  if (/\bin\d+\b/.test(probe)) return "samples an input somewhere other than uv";
  return null;
}

// ------------------------------------------------------------------ renaming

/**
 * Every name a sketch declares at file scope. Two nodes in one shader would
 * otherwise collide on `amount`, or on a helper they both carry.
 */
function declaredNames(source, parts) {
  const names = new Set();
  const bare = stripComments(source);
  const res = [
    /#\s*define\s+([A-Za-z_]\w*)/g,
    /\buniform\s+(?:lowp|mediump|highp)?\s*\w+\s+([A-Za-z_]\w*)/g,
    /\bconst\s+(?:lowp|mediump|highp)?\s*\w+\s+([A-Za-z_]\w*)/g,
    /\bstruct\s+([A-Za-z_]\w*)/g,
  ];
  for (const re of res) { let m; while ((m = re.exec(bare))) names.add(m[1]); }
  for (const chunk of parts.declTexts) {
    const code = stripComments(chunk).trim();
    let m = /^(?:lowp|mediump|highp)?\s*[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*\(/.exec(code);
    if (m) { names.add(m[1]); continue; }
    m = /^(?:lowp|mediump|highp)?\s*(?:float|int|bool|vec[234]|ivec[234]|bvec[234]|mat[234])\s+([A-Za-z_]\w*)\s*[=;]/.exec(code);
    if (m) names.add(m[1]);
  }
  names.delete("main");
  return names;
}

// ------------------------------------------------------------------ the text

// The sketch for a run depends only on the node types and on which of them
// take the carried colour — not on the graph — so it is worth keeping.
const SKETCH_CACHE = new Map();

/**
 * The fused sketch for a run of nodes, or null if one of them turns out not
 * to be fusable after all (a helper of its own that reads the input).
 * `carried[k]` is true when node k's in0 comes from node k-1.
 */
export function fusedSketch(types, carried) {
  const key = types.join(">") + "|" + carried.map((c) => (c ? 1 : 0)).join("");
  if (SKETCH_CACHE.has(key)) return SKETCH_CACHE.get(key);
  const decls = [], bodies = [], calls = [], roster = [];
  let ok = true;
  types.forEach((typeId, k) => {
    if (!ok) return;
    const t = nodeType(typeId);
    const parts = splitSketch(t.source);
    const pref = `f${k}_`;
    const names = declaredNames(t.source, parts);
    const rename = names.size ? new RegExp(`\\b(${[...names].join("|")})\\b`, "g") : null;
    // GLSL reserves any identifier with two consecutive underscores, so a
    // node's private `_lum` cannot simply be given a prefix.
    const fix = (s) => (rename ? String(s).replace(rename, (m) => pref + m.replace(/^_+/, "u")) : String(s));
    const carrier = new RegExp(`texture2D\\s*\\(\\s*${pref}in0\\s*,\\s*uv\\s*\\)`, "g");
    const dropIn0 = new RegExp(`^uniform\\s+sampler2D\\s+${pref}in0\\s*;`);

    roster.push(`//   f${k} = ${typeId}${carried[k] ? "" : "   (reads its own input)"}`);
    for (const chunk of parts.declTexts) {
      const text = fix(chunk);
      const code = stripComments(text).trim();
      if (carried[k] && dropIn0.test(code)) continue;      // its input is a register now
      // a helper of its own that reads the input has no register to read
      if (carried[k] && new RegExp(carrier.source).test(code)) { ok = false; return; }
      decls.push(text);
    }
    // Only a carried node has a register to read; the first of a run keeps
    // its sampler and reads it as written.
    const take = (s) => (carried[k] ? fix(s).replace(carrier, "_c") : fix(s));
    const stmts = parts.stmtTexts.map(take).join("\n");
    const expr = take(parts.expr || "vec3(0.0)");
    // Each node keeps its own rule about alpha — opaque unless it said
    // `@alpha` — so a mask in the middle of a fused run still masks.
    const ret = sketchMeta(t.source).alpha ? `_rgba(${expr})` : `vec4(_rgb(${expr}), 1.0)`;
    bodies.push(`// ${typeId}, as a function\nvec4 ${pref}apply(${carried[k] ? "vec4 _c" : ""}) {\n` +
                `${stmts ? stmts + "\n" : ""}  return ${ret};\n}`);
    calls.push(`_c = ${pref}apply(${carried[k] ? "_c" : ""});`);
  });
  const sketch = !ok ? null : [
    `// A fused pass — ${types.length} nodes, one draw, no buffers between them.`,
    `// Each node became a function; the colour is carried in a register.`,
    ...roster,
    `// Compiled from the graph. Nothing here was written by hand.`,
    `// @node fused.${types.length}`,
    // The functions decide their own alpha; the pass must not overrule them.
    `// @alpha`,
    "",
    decls.join("\n"),
    "",
    bodies.join("\n\n"),
    "",
    "vec4 _c = vec4(0.0);",
    calls.join("\n"),
    "_c",
  ].join("\n");
  SKETCH_CACHE.set(key, sketch);
  return sketch;
}

// ------------------------------------------------------------------ the plan

/** What the runner needs to draw one fused step. */
function buildFused(graph, run) {
  const inRun = new Set(run.map((n) => n.id));
  const carried = run.map((n) => inRun.has(n.inputs[0]));
  const types = run.map((n) => n.type);
  const sketch = fusedSketch(types, carried);
  if (!sketch) return null;
  const values = {}, samplers = [], sizes = [];
  run.forEach((n, k) => {
    const t = nodeType(n.type);
    const pref = `f${k}_`;
    for (const u of t.uniforms) {
      if (u.control === "image") {
        const m = IN_RE.exec(u.name);
        if (m) {
          const i = +m[1];
          const isCarried = carried[k] && i === 0;
          if (!isCarried) samplers.push({ name: pref + u.name, from: n.inputs[i] });
          if (new RegExp(`\\buniform\\s+vec2\\s+${u.name}_size\\b`).test(t.source)) {
            sizes.push({ name: `${pref}${u.name}_size`, from: isCarried ? null : n.inputs[i] });
          }
        } else if (u.lut) {
          samplers.push({ name: pref + u.name, lut: true, value: n.params[u.name] });
        }
        continue;
      }
      const v = n.params[u.name];
      values[pref + u.name] = Array.isArray(v) ? v : (v !== undefined && v !== null ? [v] : u.value.slice());
    }
  });
  return {
    kind: "fused", key: sketch, sketch, nodes: run.slice(),
    id: run[run.length - 1].id, values, samplers, sizes,
  };
}

/**
 * The graph as a list of draws: `{kind:"node", node}` for anything that keeps
 * its own pass, `{kind:"fused", …}` for a run that collapsed. Order is the
 * topological order, so a step's inputs are always already drawn.
 */
export function planPasses(graph) {
  const order = topo(graph);
  const consumers = new Map();
  for (const n of graph.nodes) for (const i of n.inputs) consumers.set(i, (consumers.get(i) || 0) + 1);
  if (graph.output) consumers.set(graph.output, (consumers.get(graph.output) || 0) + 1);

  const steps = [];
  let run = [];
  const flush = () => {
    if (run.length >= 2) {
      const f = buildFused(graph, run);
      if (f) { steps.push(f); run = []; return; }
    }
    for (const n of run) steps.push({ kind: "node", node: n });
    run = [];
  };
  for (const n of order) {
    const why = fusibleReason(n);
    if (why) {
      // A source or a bypass draws nothing — it hands over a texture that
      // already exists — so it must not break a run it merely sits between.
      if (n.type === "source" || n.bypass) { steps.push({ kind: "node", node: n, why }); continue; }
      flush();
      steps.push({ kind: "node", node: n, why });
      continue;
    }
    const tail = run.length ? run[run.length - 1] : null;
    // A node joins the run when it reads the tail, the tail is read by nothing
    // else (its buffer is about to stop existing), and its other inputs come
    // from outside the run — those stay real samplers, read at uv.
    const extend = tail && n.inputs[0] === tail.id && consumers.get(tail.id) === 1
      && !n.inputs.slice(1).some((id) => run.some((r) => r.id === id));
    if (!extend) flush();
    run.push(n);
  }
  flush();
  return steps;
}

/** Passes before and after, for the panel and the self-test. */
export function fuseStats(graph) {
  const steps = planPasses(graph);
  const drawn = topo(graph).filter((n) => n.type !== "source" && !n.bypass).length;
  const after = steps.filter((s) => s.kind === "fused" || (s.node.type !== "source" && !s.node.bypass)).length;
  const runs = steps.filter((s) => s.kind === "fused");
  return {
    before: drawn, after, saved: drawn - after,
    fused: runs.map((s) => s.nodes.map((n) => n.type)),
    kept: steps.filter((s) => s.kind === "node" && s.why && s.node.type !== "source" && !s.node.bypass)
      .map((s) => `${s.node.type}: ${s.why}`),
  };
}
