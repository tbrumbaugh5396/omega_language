// Could this run on WebGPU?
//
// The roadmap leaves WGSL as a decision to be made on evidence rather than
// taste: keep the node bodies free of anything WGSL cannot express, and a
// second backend stays cheap; let them drift, and it never happens. So this
// is the check, not an opinion — it reads every node type and every preset
// and reports what a WGSL translation would have to deal with.
//
// The distinction that matters is between the *host's* text and the *node's*.
// The prelude, the helper set and the coercions are ours: a WGSL backend
// would emit its own versions and nothing is lost. A node body is the user's,
// and anything in there that WGSL cannot express is a real obstacle.

import { stripComments, parseUniforms, splitSketch } from "./shader-uniforms.js";
import { NODE_TYPES } from "./render-graph.js";

/**
 * Things WGSL has no form of. Each is a fact about the language, not a
 * limitation of any particular translator:
 *
 *  - no preprocessor at all, so `#ifdef` has to become two compilations
 *  - no function overloading, so two functions of one name must be renamed
 *  - no loose uniforms; they live in a bound uniform buffer
 *  - textures and samplers are separate objects, and cannot be passed to a
 *    plain function the way a sampler2D can
 */
const CHECKS = [
  { id: "preprocessor", why: "WGSL has no preprocessor; #ifdef becomes two compilations",
    find: (src) => (src.match(/^\s*#\s*(ifdef|ifndef|if|else|elif|endif|define|undef)\b/gm) || []).length },
  { id: "sampler-argument", why: "a texture and its sampler are separate objects and cannot be passed as one",
    find: (src) => (src.match(/\(\s*sampler2D\s+\w+|,\s*sampler2D\s+\w+/g) || []).length },
  { id: "gl-builtin", why: "gl_ builtins other than FragCoord/FragColor have no direct WGSL form",
    find: (src) => (src.match(/\bgl_(?!FragCoord\b|FragColor\b)\w+/g) || []).length },
];

// One thing this deliberately does not check: mixed i32/f32 arithmetic, which
// WGSL rejects without a cast. Telling `float(x) - 1` from `int(x) - 1` needs
// types, and a text scan does not have them — an earlier version of this file
// tried and reported five exponents (`1e-6`) as integer literals. A checker
// that cries wolf is worse than one that says what it cannot see, so: mixed
// arithmetic is left to the translator that would have the types.

/** Every function name a source declares, to find overloads. */
function declaredFunctions(src) {
  const out = [];
  const bare = stripComments(src);
  const re = /\b(?:void|float|int|bool|vec[234]|ivec[234]|mat[234])\s+([A-Za-z_]\w*)\s*\(/g;
  let m;
  while ((m = re.exec(bare))) out.push(m[1]);
  return out;
}

/** One source, audited. `bodyOnly` skips what a WGSL backend would re-emit. */
export function auditSource(src, { name = "", bodyOnly = true } = {}) {
  let text = String(src);
  if (bodyOnly) {
    // The declarations and the expression: the part a user writes. The prelude
    // and helpers are the host's problem, and it would emit them differently.
    const parts = splitSketch(text);
    text = [...parts.declTexts, ...parts.stmtTexts, parts.expr].join("\n");
  }
  const bare = stripComments(text);
  const findings = [];
  for (const c of CHECKS) {
    const n = c.find(bare);
    if (n) findings.push({ id: c.id, count: n, why: c.why });
  }
  const fns = declaredFunctions(bare);
  const seen = new Map();
  for (const f of fns) seen.set(f, (seen.get(f) || 0) + 1);
  const overloads = [...seen.entries()].filter(([, n]) => n > 1).map(([f]) => f);
  if (overloads.length) {
    findings.push({ id: "overload", count: overloads.length,
                    why: `WGSL has no function overloading (${overloads.join(", ")})` });
  }
  return { name, findings, clean: findings.length === 0 };
}

/** Every registered node type, audited. */
export function auditNodes() {
  const rows = [];
  for (const [id, t] of NODE_TYPES) rows.push(auditSource(t.source, { name: id }));
  return rows;
}

/**
 * The summary the decision rests on: how much of the library is portable as
 * written, and what the rest would cost.
 */
export function portabilitySummary(rows) {
  const clean = rows.filter((r) => r.clean).length;
  const byKind = new Map();
  for (const r of rows) {
    for (const f of r.findings) {
      const e = byKind.get(f.id) || { nodes: 0, count: 0, why: f.why };
      e.nodes++; e.count += f.count;
      byKind.set(f.id, e);
    }
  }
  return {
    total: rows.length, clean,
    kinds: [...byKind.entries()].map(([id, e]) => ({ id, ...e }))
      .sort((a, b) => b.nodes - a.nodes),
  };
}
