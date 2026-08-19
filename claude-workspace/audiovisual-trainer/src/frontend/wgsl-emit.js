// The second backend: a sketch, as WGSL.
//
// `wgsl-audit.js` has said for several phases that the node bodies are clean —
// that nothing in them is a thing WGSL cannot express. That was a text scan
// and an argument. This is the translator, so the claim becomes a number: the
// same sketch, rendered by WebGL and by WebGPU, compared pixel for pixel.
//
// What makes it tractable is that the input is not arbitrary GLSL. It is the
// sketch shorthand — `splitSketch` gives declarations, statements and one
// final expression — and the prelude, the helpers and the coercions are the
// host's own text, which this file simply writes again in WGSL. Only the
// user's part is translated, and the translation is a short list of rules:
//
//   float x = …;        var x: f32 = …;
//   vec3(…)             vec3f(…)
//   a ? b : c           select(c, b, a)
//   texture2D(s, uv)    textureSample(s_tex, s_smp, uv)
//   mod(a, b)           a - b * floor(a / b)
//   atan(y, x)          atan2(y, x)
//
// Anything it meets that is not on the list is *reported*, not guessed at.
// A translator that quietly emits something plausible is worse than one that
// says which line it could not do, because the first kind is found by a
// customer and the second by a test.
//
// Uniforms are packed one to a vec4. That wastes three floats on every scalar
// and it means nothing here has to implement WGSL's alignment rules, which is
// the right trade for a second backend whose job is to prove a point.

import { splitSketch, stripComments, parseUniforms, sketchMeta } from "./shader-uniforms.js";

// ------------------------------------------------------------------ types

const TYPE = {
  float: "f32", int: "i32", bool: "bool", void: "void",
  vec2: "vec2f", vec3: "vec3f", vec4: "vec4f",
  ivec2: "vec2i", ivec3: "vec3i", ivec4: "vec4i",
  bvec2: "vec2<bool>", bvec3: "vec3<bool>", bvec4: "vec4<bool>",
  mat2: "mat2x2f", mat3: "mat3x3f", mat4: "mat4x4f",
};
const TYPES = Object.keys(TYPE);
const TYPE_RE = new RegExp(`\\b(${TYPES.join("|")})\\b`, "g");

/** Things GLSL has and WGSL does not, that this translator does not attempt. */
const REFUSED = [
  [/\bdFdx\b|\bdFdy\b/, "dFdx/dFdy — WGSL has dpdx/dpdy but only in a fragment stage helper"],
  [/\btexture2DLod\b|\btextureLod\b/, "explicit LOD sampling is not translated"],
  [/\bdiscard\b/, "discard is expressible but changes the pipeline, so it is not attempted"],
  [/\bstruct\b/, "user structs are not translated"],
  [/\bwhile\b|\bdo\b/, "only for-loops are translated"],
  [/#\s*(ifdef|ifndef|if|else|elif|endif|define)/, "WGSL has no preprocessor"],
];

// ------------------------------------------------------------------ scanning
//
// Two small parsers, because the two rules that matter — calls and ternaries —
// cannot be done with a regular expression and must not be done wrong.

/** The balanced argument list of `name(` starting at `open`, split at commas. */
function argsAt(src, open) {
  let depth = 0, start = open + 1, i = open;
  const args = [];
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") {
      depth--;
      if (depth === 0) { args.push(src.slice(start, i)); return { args, end: i }; }
    } else if (c === "," && depth === 1) { args.push(src.slice(start, i)); start = i + 1; }
  }
  return null;
}

/** Rewrite every call to `name` with a function of its arguments. */
function rewriteCalls(src, name, make) {
  const re = new RegExp(`\\b${name}\\s*\\(`, "g");
  let out = src, guard = 0;
  for (;;) {
    re.lastIndex = 0;
    const m = re.exec(out);
    if (!m || guard++ > 400) break;
    const open = m.index + m[0].length - 1;
    const got = argsAt(out, open);
    if (!got) break;
    const made = make(got.args.map((a) => a.trim()));
    if (made === null) {
      // Left alone on purpose — step past it so the loop makes progress.
      const skip = out.slice(0, got.end + 1);
      const rest = rewriteCalls(out.slice(got.end + 1), name, make);
      return skip + rest;
    }
    out = out.slice(0, m.index) + made + out.slice(got.end + 1);
  }
  return out;
}

// Where an expression begins, scanning left from `at`: back past balanced
// brackets to the first thing that cannot be part of one.
const STOPS = new Set(["(", ")", ",", ";", "{", "}", "=", "?", ":"]);
function exprStart(src, at) {
  let depth = 0;
  for (let i = at - 1; i >= 0; i--) {
    const c = src[i];
    if (c === ")" || c === "]") depth++;
    else if (c === "(" || c === "[") { if (depth === 0) return i + 1; depth--; }
    else if (depth === 0 && (STOPS.has(c) || c === "\n")) return i + 1;
  }
  return 0;
}
/** Where an expression ends, scanning right from `at`. */
function exprEnd(src, at, extra = "") {
  let depth = 0;
  for (let i = at; i < src.length; i++) {
    const c = src[i];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") { if (depth === 0) return i; depth--; }
    else if (depth === 0 && (c === ";" || c === "," || c === "\n" || extra.includes(c))) return i;
  }
  return src.length;
}

/** `a ? b : c` → `select(c, b, a)`, innermost first so nesting works. */
function ternaries(src) {
  let out = src;
  for (let guard = 0; guard < 60; guard++) {
    // The last `?` is innermost-rightmost, so resolving it never disturbs an
    // outer one whose branches contain it.
    const q = out.lastIndexOf("?");
    if (q < 0) return out;
    // A `?` inside a string or a swizzle is not a thing the shorthand has, so
    // any `?` here is a conditional.
    const colon = (() => {
      let depth = 0;
      for (let i = q + 1; i < out.length; i++) {
        const c = out[i];
        if (c === "(" || c === "[") depth++;
        else if (c === ")" || c === "]") depth--;
        else if (c === ":" && depth === 0) return i;
      }
      return -1;
    })();
    if (colon < 0) return out;
    const s = exprStart(out, q);
    const e = exprEnd(out, colon + 1);
    const cond = out.slice(s, q).trim();
    const a = out.slice(q + 1, colon).trim();
    const b = out.slice(colon + 1, e).trim();
    out = `${out.slice(0, s)}select(${b}, ${a}, ${cond})${out.slice(e)}`;
  }
  return out;
}

/** Braces round every branch: WGSL has no single-statement if. */
function braces(src) {
  let out = src;
  for (const kw of ["if", "else if", "else"]) {
    let from = 0;
    for (let guard = 0; guard < 200; guard++) {
      const re = new RegExp(`\\b${kw.replace(" ", "\\s+")}\\b`, "g");
      re.lastIndex = from;
      const m = re.exec(out);
      if (!m) break;
      let i = m.index + m[0].length;
      if (kw !== "else") {                       // step over the condition
        while (i < out.length && out[i] !== "(") i++;
        const got = argsAt(out, i);
        if (!got) { from = m.index + 1; continue; }
        i = got.end + 1;
      }
      while (i < out.length && /\s/.test(out[i])) i++;
      if (out[i] === "{" || out.startsWith("if", i)) { from = i; continue; }
      const end = exprEnd(out, i, ";");
      const stop = out[end] === ";" ? end + 1 : end;
      out = `${out.slice(0, i)}{ ${out.slice(i, stop)} }${out.slice(stop)}`;
      from = i + 1;
    }
  }
  return out;
}

/**
 * What type an expression is, where that can be known without a type checker:
 * a constructor says so, a name declared in this chunk says so, and a swizzle
 * says so. Anything else is null, and a caller that needs a type refuses
 * rather than assuming one.
 */
function typeOf(expr, env) {
  const e = String(expr).trim();
  let m = /^(vec[234]f|vec[234]i|f32|i32)\s*\(/.exec(e);
  if (m) return m[1];
  m = /^([A-Za-z_]\w*)\.([xyzwrgba]+)$/.exec(e);
  if (m) return ["", "f32", "vec2f", "vec3f", "vec4f"][m[2].length] || null;
  m = /^([A-Za-z_]\w*)$/.exec(e);
  if (m) return env.get(m[1]) || null;
  return null;
}

/** GLSL lets a scalar stand in for a vector; WGSL does not. */
function widen(args, env) {
  const t = typeOf(args[0], env);
  if (!t || !/^vec[234]f$/.test(t)) return null;
  return args.map((a, i) => (i === 0 || typeOf(a, env) === t ? a : `${t}(${a})`));
}

// ------------------------------------------------------------------ the body

// `gm`, not `^`: splitSketch hands over a chunk that begins with the *previous*
// line's trailing comment, so a declaration is almost never at the start of
// its chunk — and a function body chunk holds many declarations, each of which
// needs translating too.
const DECL_LINE = new RegExp(`^([ \\t]*)(${TYPES.join("|")})\\s+([A-Za-z_]\\w*)\\s*(=|;)`, "gm");
const CONST_LINE = new RegExp(`^([ \\t]*)const\\s+(${TYPES.join("|")})\\s+([A-Za-z_]\\w*)\\s*=`, "gm");
const FUNC_LINE = new RegExp(`^([ \\t]*)(${TYPES.join("|")})\\s+([A-Za-z_]\\w*)\\s*\\(([^)]*)\\)\\s*\\{`, "gm");
const FOR_DECL = new RegExp(`\\bfor\\s*\\(\\s*(${TYPES.join("|")})\\s+([A-Za-z_]\\w*)\\s*=`, "g");

/** One statement or declaration, translated. `samplers` names the textures. */
function translateChunk(text, ctx) {
  let s = text;
  // Every `T name` this chunk declares, so the widening below knows a vector
  // when it sees one. Read before translating, from the GLSL spelling.
  for (const m of s.matchAll(new RegExp(`\\b(${TYPES.join("|")})\\s+([A-Za-z_]\\w*)\\s*[=;,)]`, "g"))) {
    ctx.env.set(m[2], TYPE[m[1]]);
  }

  // Function heads first, because their parameter lists are `T name` pairs
  // that the declaration rule would otherwise mangle.
  s = s.replace(FUNC_LINE, (all, pad, ret, name, params) => {
    const ps = params.trim() ? params.split(",").map((prm) => {
      const m = /^\s*(?:in|out|inout\s+)?\s*(\w+)\s+([A-Za-z_]\w*)\s*$/.exec(prm);
      if (!m) { ctx.refused.push(`a parameter this translator cannot read: "${prm.trim()}"`); return prm; }
      return `${m[2]}: ${TYPE[m[1]] || m[1]}`;
    }).join(", ") : "";
    const r = ret === "void" ? "" : ` -> ${TYPE[ret] || ret}`;
    return `${pad}fn ${name}(${ps})${r} {`;
  });

  // `const T x = …;` is a compile-time value in both languages.
  s = s.replace(CONST_LINE, (all, pad, ty, name) => `${pad}let ${name}: ${TYPE[ty]} =`);
  // `T x = …;` and `T x;` are mutable locals.
  s = s.replace(DECL_LINE, (all, pad, ty, name, tail) =>
    `${pad}var ${name}: ${TYPE[ty]}${tail === "=" ? " =" : ";"}`);
  // `for (int i = …` likewise.
  s = s.replace(FOR_DECL, (all, ty, name) => `for (var ${name}: ${TYPE[ty]} =`);

  // texture2D(s, uv) → textureSample(s_tex, s_smp, uv)
  s = rewriteCalls(s, "texture2D", (args) => {
    if (args.length !== 2) return null;
    const name = args[0].trim();
    if (!ctx.samplers.has(name)) { ctx.refused.push(`texture2D on "${name}", which is not a declared sampler`); return null; }
    return `textureSample(${name}_tex, ${name}_smp, ${args[1]})`;
  });
  // GLSL's mod, which is not WGSL's `%`.
  s = rewriteCalls(s, "mod", (args) =>
    (args.length === 2 ? `((${args[0]}) - (${args[1]}) * floor((${args[0]}) / (${args[1]})))` : null));
  // Two-argument atan is atan2.
  s = rewriteCalls(s, "atan", (args) => (args.length === 2 ? `atan2(${args[0]}, ${args[1]})` : null));
  // The overloads the prelude carries. WGSL has none, so each arity gets a
  // name of its own and the call is sent to the right one — the very thing
  // `wgsl-audit.js` has been reporting as an obstacle since it was written.
  s = rewriteCalls(s, "palette", (args) => (args.length === 1 ? `palette1(${args[0]})` : null));
  s = rewriteCalls(s, "aa", (args) => (args.length === 2 ? `aaw(${args[0]}, ${args[1]})` : null));

  // A scalar where WGSL wants a vector — GLSL's clamp(v, 0.0, 1.0) and its
  // relatives. Only rewritten when the first argument's type is known.
  for (const fn of ["clamp", "min", "max", "mix", "smoothstep", "step"]) {
    s = rewriteCalls(s, fn, (args) => {
      if (args.length < 2) return null;
      const wide = widen(args, ctx.env);
      if (!wide) return null;
      if (wide.every((a, i) => a === args[i])) return null;
      return `${fn}(${wide.join(", ")})`;
    });
  }

  s = braces(s);
  s = ternaries(s);

  // Constructors and casts: every remaining bare type name is one.
  s = s.replace(TYPE_RE, (t) => TYPE[t]);
  // …except in the declarations just written, where `f32` is already right.
  s = s.replace(/: (f32|i32|bool|vec[234]f|vec[234]i|mat[234]x[234]f)f\b/g, ": $1");
  return s;
}

// ------------------------------------------------------------------ prelude

const PRELUDE = `struct Uniforms {
  resolution: vec2f,
  mouse: vec2f,
  time: f32,
  seed: f32,
  mouseDown: f32,
  frame: i32,
  origin: vec2f,
  pad: vec2f,
  vals: array<vec4f, 32>,
};
@group(0) @binding(0) var<uniform> U: Uniforms;

fn rot(a: f32) -> mat2x2f { let c = cos(a); let s = sin(a); return mat2x2f(c, -s, s, c); }
fn hash21(q: vec2f) -> f32 {
  var p = fract(q * vec2f(123.34, 456.21));
  p += vec2f(dot(p, p + 45.32));
  return fract(p.x * p.y);
}
fn random(p: vec2f) -> f32 { return hash21(p); }
fn noise(p: vec2f) -> f32 {
  let i = floor(p); let f = fract(p);
  let a = hash21(i); let b = hash21(i + vec2f(1.0, 0.0));
  let c = hash21(i + vec2f(0.0, 1.0)); let d = hash21(i + vec2f(1.0, 1.0));
  let u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}
fn fbm(q: vec2f) -> f32 {
  var v = 0.0; var amp = 0.5; var p = q;
  for (var i = 0; i < 6; i++) { v += amp * noise(p); p *= 2.02; amp *= 0.5; }
  return v;
}
fn sdCircle(p: vec2f, r: f32) -> f32 { return length(p) - r; }
fn sdBox(p: vec2f, b: vec2f) -> f32 { let d = abs(p) - b; return length(max(d, vec2f(0.0))) + min(max(d.x, d.y), 0.0); }
fn sdSegment(p: vec2f, a: vec2f, b: vec2f) -> f32 {
  let pa = p - a; let ba = b - a;
  let h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}
fn sdCapsule(p: vec2f, a: vec2f, b: vec2f, r: f32) -> f32 { return sdSegment(p, a, b) - r; }
fn sdEllipse(p: vec2f, r: vec2f) -> f32 { let k0 = length(p / r); let k1 = length(p / (r * r)); return k0 * (k0 - 1.0) / max(k1, 1e-4); }
fn smin(a: f32, b: f32, k: f32) -> f32 { let h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }
fn aa(d: f32) -> f32 { let w = fwidth(d) * 0.75 + 1e-6; return smoothstep(w, -w, d); }
fn aaw(d: f32, w: f32) -> f32 { return smoothstep(w, -w, d); }
fn palette(t: f32, a: vec3f, b: vec3f, c: vec3f, d: vec3f) -> vec3f { return a + b * cos(6.28318 * (c * t + d)); }
fn palette1(t: f32) -> vec3f { return palette(t, vec3f(0.5), vec3f(0.5), vec3f(1.0), vec3f(0.0, 0.33, 0.67)); }
fn srgbToLinear(c: vec3f) -> vec3f { return pow(max(c, vec3f(0.0)), vec3f(2.2)); }
fn linearToSrgb(c: vec3f) -> vec3f { return pow(max(c, vec3f(0.0)), vec3f(1.0 / 2.2)); }
fn tonemap(x: vec3f) -> vec3f { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), vec3f(0.0), vec3f(1.0)); }
fn srgb(c0: vec3f) -> vec3f {
  let c = max(c0, vec3f(0.0));
  return mix(c * 12.92, 1.055 * pow(c, vec3f(1.0 / 2.4)) - vec3f(0.055), step(vec3f(0.0031308), c));
}
fn vignette(uv: vec2f, k: f32) -> f32 { let q = uv * (1.0 - uv); return pow(clamp(q.x * q.y * 16.0, 0.0, 1.0), k); }
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
  // The same full-screen triangle the GL path draws.
  var p = array<vec2f, 3>(vec2f(-1.0, -1.0), vec2f(3.0, -1.0), vec2f(-1.0, 3.0));
  return vec4f(p[i], 0.0, 1.0);
}`;

// Only emitted when a keyboard is bound: WGSL has no preprocessor, so a
// helper naming a binding that is not there is a shader that will not compile.
const KEY_HELPERS = `fn keyDown(code: f32) -> f32 { return textureSample(KEYS_tex, KEYS_smp, vec2f((code + 0.5) / 256.0, 0.5 / 3.0)).r; }
fn keyHit(code: f32) -> f32 { return textureSample(KEYS_tex, KEYS_smp, vec2f((code + 0.5) / 256.0, 1.5 / 3.0)).r; }
fn keyToggle(code: f32) -> f32 { return textureSample(KEYS_tex, KEYS_smp, vec2f((code + 0.5) / 256.0, 2.5 / 3.0)).r; }`;

// The coercions, which exist so a sketch may end in a float, a vec3 or a vec4.
// WGSL has no overloading, so instead of one name three times the emitter
// picks which to call from the expression's type — which it cannot know — so
// it wraps by *arity of the constructor it can see*, and otherwise assumes a
// vec3. That is the one place this translator guesses, and it is why the
// self-test renders the whole catalogue rather than trusting it.
const COERCE = `fn _rgb3(c: vec3f) -> vec3f { return clamp(c, vec3f(0.0), vec3f(1.0)); }
fn _rgb1(c: f32) -> vec3f { return clamp(vec3f(c), vec3f(0.0), vec3f(1.0)); }
fn _rgba4(c: vec4f) -> vec4f { return vec4f(clamp(c.rgb, vec3f(0.0), vec3f(1.0)), clamp(c.a, 0.0, 1.0)); }`;

// ------------------------------------------------------------------ emit

/**
 * A sketch → a WGSL module, or a report of why not.
 *
 * Returns { wgsl, uniforms, samplers, refused, ok }. `refused` is a list of
 * the reasons this sketch was not translated; `ok` is that list being empty.
 */
export function toWgsl(sketch, { keys = false } = {}) {
  const src = String(sketch);
  const refused = [];
  const bare = stripComments(src);
  for (const [re, why] of REFUSED) if (re.test(bare)) refused.push(why);

  const parts = splitSketch(src);
  const uniforms = parseUniforms(src);
  const samplerNames = uniforms.filter((u) => u.control === "image").map((u) => u.name);
  const scalars = uniforms.filter((u) => u.control !== "image");
  if (scalars.length > 32) refused.push(`${scalars.length} uniforms; this translator packs 32`);

  const ctx = { refused, samplers: new Set(samplerNames), env: new Map() };
  // The reserved coordinates and every uniform, so widening knows their types.
  for (const [n, t] of [["uv", "vec2f"], ["st", "vec2f"], ["p", "vec2f"], ["m", "vec2f"],
                        ["t", "f32"], ["seed", "f32"], ["md", "f32"], ["frame", "i32"]]) ctx.env.set(n, t);
  for (const u of uniforms) if (u.control !== "image") ctx.env.set(u.name, TYPE[u.type] || "f32");

  // The sketch's own declarations, minus the ones the host re-declares.
  const decls = parts.declTexts.filter((t) => {
    const code = stripComments(t).trim();
    if (/^\s*uniform\b/.test(code)) return false;          // become the uniform block
    if (/^\s*(precision|attribute|varying|invariant)\b/.test(code)) return false;
    if (/^\s*float\s+in\d+\s*\(/.test(code)) { refused.push("a field port; field composition is a GLSL-side concern"); return false; }
    return true;
  });

  // Uniform accessors: one vec4 slot each, so nothing here implements
  // WGSL's alignment rules.
  const slot = new Map();
  scalars.forEach((u, i) => slot.set(u.name, i));
  const access = (u) => {
    const i = slot.get(u.name);
    if (u.type === "float") return `U.vals[${i}].x`;
    if (u.type === "int") return `i32(U.vals[${i}].x)`;
    if (u.type === "bool") return `(U.vals[${i}].x > 0.5)`;
    if (u.type === "vec2") return `U.vals[${i}].xy`;
    if (u.type === "vec3") return `U.vals[${i}].xyz`;
    return `U.vals[${i}]`;
  };
  const aliases = scalars.map((u) => `  let ${u.name} = ${access(u)};`).join("\n");

  // Bindings: a texture and a sampler each, plus the keyboard when asked for.
  let binding = 1;
  const bindings = [];
  for (const name of samplerNames) {
    bindings.push(`@group(0) @binding(${binding++}) var ${name}_tex: texture_2d<f32>;`);
    bindings.push(`@group(0) @binding(${binding++}) var ${name}_smp: sampler;`);
  }
  if (keys) {
    bindings.push(`@group(0) @binding(${binding++}) var KEYS_tex: texture_2d<f32>;`);
    bindings.push(`@group(0) @binding(${binding++}) var KEYS_smp: sampler;`);
  }

  const body = decls.map((t) => translateChunk(t, ctx)).join("\n");
  const stmts = parts.stmtTexts.map((t) => translateChunk(t, ctx)).join("\n");
  const expr = translateChunk(parts.expr || "vec3(0.0)", ctx).trim();

  // Which coercion: the shape of the final expression is usually visible.
  const alpha = sketchMeta(src).alpha;
  const wrap = alpha ? `_rgba4(${expr})`
    : /^vec3f\s*\(/.test(expr) || /\.rgb\b|\.xyz\b/.test(expr) ? `vec4f(_rgb3(${expr}), 1.0)`
    : /^vec4f\s*\(/.test(expr) ? `vec4f(_rgb3((${expr}).rgb), 1.0)`
    : `vec4f(_rgb3(${expr}), 1.0)`;

  const wgsl = `${PRELUDE}
${COERCE}
${bindings.join("\n")}
${keys ? KEY_HELPERS : ""}

${body}

@fragment fn fs(@builtin(position) FC: vec4f) -> @location(0) vec4f {
  // WebGPU's position is top-down and GL's is bottom-up; flipping here is the
  // one place the two conventions meet, exactly as present() is in the GL path.
  let fc = vec2f(FC.x, U.resolution.y - FC.y);
  let uv = fc / U.resolution;
  let st = vec2f(uv.x * (U.resolution.x / U.resolution.y), uv.y);
  let p = (fc * 2.0 - U.resolution) / U.resolution.y;
  let t = U.time;
  let m = U.mouse / U.resolution;
  let seed = U.seed;
  let md = U.mouseDown;
  let frame = U.frame;
${aliases}
${stmts}
  return ${wrap};
}`;

  return { wgsl, uniforms: scalars, samplers: samplerNames, refused, ok: refused.length === 0, slot };
}
