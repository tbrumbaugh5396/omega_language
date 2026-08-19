// Putting two sketches in one shader.
//
// Both compilers that generate GLSL do the same thing first: take several
// sketches that were each written as if they owned the file, and make them
// share one. Fusion does it for a run of per-pixel nodes; field composition
// does it for a tree of distance functions. Neither can afford node A's
// `amount` to be node B's `amount`, so every name a sketch declares gets a
// prefix of its own.
//
// This is the one place that knows what "a name a sketch declares" means.

import { stripComments } from "./shader-uniforms.js";

/**
 * Every name a sketch declares at file scope: uniforms, consts, structs,
 * defines, helper functions and forward declarations. `parts` is the
 * splitSketch of the same source.
 */
export function declaredNames(source, parts) {
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
    // A definition and a prototype declare the same name; both end up here,
    // which is what lets a field port be renamed along with everything else.
    let m = /^(?:lowp|mediump|highp)?\s*[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*\(/.exec(code);
    if (m) { names.add(m[1]); continue; }
    m = /^(?:lowp|mediump|highp)?\s*(?:float|int|bool|vec[234]|ivec[234]|bvec[234]|mat[234])\s+([A-Za-z_]\w*)\s*[=;]/.exec(code);
    if (m) names.add(m[1]);
  }
  names.delete("main");
  return names;
}

/**
 * A function that rewrites one sketch's text into a shared file's namespace.
 *
 * GLSL reserves any identifier containing two consecutive underscores, so a
 * node's private `_lum` cannot simply be handed a prefix — the leading
 * underscores become a `u` first.
 */
export function prefixer(source, parts, prefix) {
  const names = declaredNames(source, parts);
  if (!names.size) return (s) => String(s);
  // The leading group catches a member access, so a node that declares a
  // uniform called `x` does not have `p.x` rewritten to `p.f3_x` underneath
  // it. A word boundary alone matches after the dot, which is a silent way to
  // corrupt a swizzle into a compile error somewhere else entirely.
  const re = new RegExp(`(\\.\\s*)?\\b(${[...names].join("|")})\\b`, "g");
  return (s) => String(s).replace(re, (m, dot, name) =>
    (dot ? m : prefix + name.replace(/^_+/, "u")));
}
