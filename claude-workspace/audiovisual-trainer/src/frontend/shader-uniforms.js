// Uniform introspection and the sketch shorthand.
//
// Two jobs, both pure — no DOM in here, so the parsing can be checked without
// a browser:
//
//   parseUniforms(src)  ->  control descriptors for every uniform you declared
//   desugar(sketch)     ->  a full GLSL ES 1.00 fragment shader
//
// The rule for uniforms is that ordinary GLSL always works. A bare
// `uniform float k;` gets a 0-1 slider; an annotation comment only refines
// what is already there. Nothing you paste in from The Book of Shaders or
// ShaderToy is ever rejected for want of a comment.

/** Supplied by the runtime, so they are driven rather than dialled. */
export const RESERVED = new Set([
  "u_resolution", "u_mouse", "u_time", "u_seed",
]);

// Scanned over the whole source rather than line by line: `uniform vec2 u_r;
// uniform float u_t;` on one line is ordinary GLSL, and an anchored per-line
// pattern silently finds nothing in it.
const DECL = new RegExp(
  "\\buniform\\s+(?:lowp\\s+|mediump\\s+|highp\\s+)?" +
  "(float|int|bool|vec2|vec3|vec4)\\s+" +
  "([A-Za-z_][A-Za-z0-9_]*)\\s*(?:\\[\\s*\\d+\\s*\\])?\\s*;", "g");

const COLOURISH = /(colou?r|tint|rgb|ink|hue|paint)/i;

/** Widths of the value each GLSL type carries. */
const WIDTH = { float: 1, int: 1, bool: 1, vec2: 2, vec3: 3, vec4: 4 };

/**
 * Read `@` annotations out of a trailing comment. Anything that is not an
 * annotation becomes the label, so `// @range 1 40 — tile count` documents
 * itself in the panel exactly as it reads in the source.
 */
function annotations(comment) {
  const out = { flags: new Set(), label: "" };
  if (!comment) return out;
  const words = comment.trim().split(/\s+/);
  const rest = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (w[0] !== "@") { rest.push(w); continue; }
    const key = w.slice(1).toLowerCase();
    const num = (n) => {
      const v = parseFloat(words[i + n]);
      return Number.isFinite(v) ? v : null;
    };
    if (key === "range") {
      const lo = num(1), hi = num(2);
      if (lo !== null && hi !== null) { out.min = lo; out.max = hi; i += 2; }
      if (String(words[i + 1]).toLowerCase() === "step") {
        const s = parseFloat(words[i + 2]);
        if (Number.isFinite(s)) { out.step = s; i += 2; }
      }
    } else if (key === "step") {
      const s = num(1);
      if (s !== null) { out.step = s; i += 1; }
    } else if (key === "default") {
      const d = [];
      while (Number.isFinite(parseFloat(words[i + 1]))) { d.push(parseFloat(words[++i])); }
      if (d.length) out.default = d;
    } else if (key === "label") {
      out.label = words.slice(i + 1).join(" ");
      i = words.length;
    } else {
      out.flags.add(key);
    }
  }
  if (!out.label) out.label = rest.join(" ").replace(/^[—–\-:,\s]+/, "").trim();
  return out;
}

/**
 * Blank comments out rather than deleting them. Length and line count both
 * have to survive: splitSketch indexes into the original source with offsets
 * found here, and deleting would slide every one of them.
 */
export function stripComments(src) {
  const blank = (m) => m.replace(/[^\n]/g, " ");
  return String(src)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/\/\/[^\n]*/g, blank);
}

/**
 * Every uniform you declared, as a control descriptor. Reserved names are
 * skipped — those are driven by the clock and the pointer.
 */
/** Two colours that default to the same value make `mix(a, b, k)` a flat
    field, which reads as a broken sketch. Hand each one a different start. */
const COLOUR_DEFAULTS = [
  [0.85, 0.45, 0.20], [0.10, 0.17, 0.29],
  [0.35, 0.70, 0.62], [0.93, 0.88, 0.78],
];

export function parseUniforms(src) {
  const text = String(src);
  // Matches are found in the blanked copy so a commented-out declaration is
  // not mistaken for a real one; offsets still index the original, because
  // blanking preserves length.
  const bare = stripComments(text);
  const out = [];
  const seen = new Set();
  let colours = 0;

  DECL.lastIndex = 0;
  let m;
  while ((m = DECL.exec(bare)) !== null) {
    const [, type, name] = m;
    if (RESERVED.has(name) || seen.has(name)) continue;
    seen.add(name);

    // The annotation is whatever comment trails the declaration on its line.
    const eol = bare.indexOf("\n", DECL.lastIndex);
    const rest = text.slice(DECL.lastIndex, eol === -1 ? text.length : eol);
    const c = rest.indexOf("//");
    const a = annotations(c === -1 ? "" : rest.slice(c + 2));
    const width = WIDTH[type];
    let control;
    if (type === "bool" || a.flags.has("toggle")) control = "toggle";
    else if (a.flags.has("color") || a.flags.has("colour")) control = "color";
    else if (a.flags.has("pad")) control = "pad";
    else if (type === "vec2") control = "pad";
    else if ((type === "vec3" || type === "vec4") && COLOURISH.test(name)) control = "color";
    else control = "slider";

    const isInt = type === "int" || a.flags.has("int");
    const min = a.min ?? (control === "color" ? 0 : isInt ? 0 : 0);
    const max = a.max ?? (isInt ? 16 : 1);
    const step = a.step ?? (isInt ? 1 : (max - min) / 200);

    let value = a.default;
    if (!value) {
      if (control === "color") {
        value = COLOUR_DEFAULTS[colours++ % COLOUR_DEFAULTS.length].concat(1).slice(0, width);
      }
      else if (control === "toggle") value = [0];
      else if (control === "pad") value = [0.5, 0.5];
      else value = Array(width).fill(isInt ? Math.round((min + max) / 2)
                                           : min + (max - min) * 0.5);
    }
    while (value.length < width) value.push(value[value.length - 1] ?? 0);

    out.push({
      name, type, control, width, isInt,
      min, max, step,
      label: a.label || name,
      value: value.slice(0, width),
    });
  }
  return out;
}

// ---------------------------------------------------------------- the sketch

/** #1b2b4b and #f80 become vec3 literals. Preprocessor lines cannot collide:
    "define" and "ifdef" are not six hex digits. */
export function expandHex(src) {
  return String(src).replace(/#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g, (_, h) => {
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const v = [0, 2, 4].map((i) => (parseInt(full.slice(i, i + 2), 16) / 255).toFixed(4));
    return `vec3(${v.join(", ")})`;
  });
}

/** Helpers, each guarded so your own definition of the same name wins. */
const HELPERS = [
  ["rot", `mat2 rot(float a){ float c=cos(a), s=sin(a); return mat2(c,-s,s,c); }`],
  ["hash21", `float hash21(vec2 p){ p=fract(p*vec2(123.34,456.21)); p+=dot(p,p+45.32); return fract(p.x*p.y); }`],
  ["random", `float random(vec2 p){ return hash21(p); }`],
  ["noise", `float noise(vec2 p){
  vec2 i=floor(p), f=fract(p);
  float a=hash21(i), b=hash21(i+vec2(1.0,0.0));
  float c=hash21(i+vec2(0.0,1.0)), d=hash21(i+vec2(1.0,1.0));
  vec2 u=f*f*(3.0-2.0*f);
  return mix(a,b,u.x)+(c-a)*u.y*(1.0-u.x)+(d-b)*u.x*u.y;
}`],
  ["fbm", `float fbm(vec2 p){
  float v=0.0, amp=0.5;
  for(int i=0;i<6;i++){ v+=amp*noise(p); p*=2.02; amp*=0.5; }
  return v;
}`],
  ["sdCircle", `float sdCircle(vec2 p, float r){ return length(p)-r; }`],
  ["sdBox", `float sdBox(vec2 p, vec2 b){ vec2 d=abs(p)-b; return length(max(d,0.0))+min(max(d.x,d.y),0.0); }`],
  ["sdSegment", `float sdSegment(vec2 p, vec2 a, vec2 b){
  vec2 pa=p-a, ba=b-a;
  float h=clamp(dot(pa,ba)/dot(ba,ba),0.0,1.0);
  return length(pa-ba*h);
}`],
  // No fwidth: GL_OES_standard_derivatives is an extension, and a sketch that
  // fails to compile on a machine without it is worse than a fixed width.
  ["aa", `float aa(float d, float w){ return smoothstep(w,-w,d); }
float aa(float d){ return aa(d, 1.5/u_resolution.y); }`],
  ["palette", `vec3 palette(float t, vec3 a, vec3 b, vec3 c, vec3 d){ return a+b*cos(6.28318*(c*t+d)); }
vec3 palette(float t){ return palette(t, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0,0.33,0.67)); }`],
  ["srgbToLinear", `vec3 srgbToLinear(vec3 c){ return pow(c, vec3(2.2)); }`],
  ["linearToSrgb", `vec3 linearToSrgb(vec3 c){ return pow(max(c,0.0), vec3(1.0/2.2)); }`],
];

/** Names the sketch is allowed to end with, whatever their type. */
const COERCE = `vec3 _rgb(vec3 c){ return c; }
vec3 _rgb(vec4 c){ return c.rgb; }
vec3 _rgb(vec2 c){ return vec3(c, 0.0); }
vec3 _rgb(float g){ return vec3(g); }`;

const PRELUDE = `#ifdef GL_ES
precision mediump float;
#endif
uniform vec2  u_resolution;
uniform vec2  u_mouse;
uniform float u_time;
uniform float u_seed;`;

/** The variables in scope inside a sketch, documented for the help panel. */
export const SKETCH_VARS = [
  ["uv", "vec2", "0 to 1 across the frame, y up"],
  ["st", "vec2", "aspect-corrected — y is 0 to 1, x is scaled by the aspect"],
  ["p", "vec2", "centred and aspect-corrected, roughly -1 to 1. Radial work wants this"],
  ["t", "float", "seconds since the sketch started"],
  ["m", "vec2", "pointer, 0 to 1"],
  ["seed", "float", "changes when you press Randomise"],
];

/**
 * A sketch is: declarations, then statements, then one colour expression.
 *
 * The three are told apart by what they are, not by where you put them.
 * Declarations (uniforms, functions, const, #define) have to sit at global
 * scope; statements have to sit inside main, or `p` and `t` are not in scope
 * and GLSL would evaluate them once for the whole draw rather than per
 * fragment. Splitting on the last `;` alone got that wrong.
 */
export function splitSketch(sketch) {
  const src = String(sketch);
  const bare = stripComments(src);
  const spans = [];
  let depth = 0, start = 0;

  for (let i = 0; i < bare.length; i++) {
    const ch = bare[i];
    if (ch === "{") depth++;
    else if (ch === "}") { if (--depth === 0) { spans.push([start, i + 1]); start = i + 1; } }
    else if (ch === ";" && depth === 0) { spans.push([start, i + 1]); start = i + 1; }
  }

  const decls = [], stmts = [];
  for (let [s, e] of spans) {
    // Absorb a trailing comment on the same line, so the annotation stays with
    // the declaration it belongs to.
    const nl = bare.indexOf("\n", e);
    const upto = nl === -1 ? bare.length : nl;
    if (!bare.slice(e, upto).trim()) e = upto;

    const text = src.slice(s, e);
    const code = bare.slice(s, e).trim();
    if (!code) continue;
    const isDecl = /^(uniform|attribute|varying|const|struct|precision)\b/.test(code)
      || code.startsWith("#")
      || code.endsWith("}");          // a function definition
    (isDecl ? decls : stmts).push(text);
  }

  return {
    preamble: decls.join("\n"),
    body: stmts.join("\n"),
    expr: src.slice(start).trim(),
  };
}

/** Sketch shorthand to a complete fragment shader. */
export function desugar(sketch) {
  const { preamble, body, expr } = splitSketch(sketch);
  const colour = expr || "vec3(0.0)";
  const declared = stripComments(preamble);
  const defines = (name) =>
    new RegExp(`\\b(?:float|int|bool|vec2|vec3|vec4|mat2)\\s+${name}\\b`).test(declared);

  const helpers = HELPERS
    .filter(([name]) =>
      !new RegExp(`\\b(?:float|int|vec2|vec3|vec4|mat2)\\s+${name}\\s*\\(`).test(declared))
    .map(([, src]) => src)
    .join("\n");

  // The coordinates are file-scope so a function you write in the preamble can
  // read them, the way it reads a uniform. They are assigned once per fragment
  // at the top of main. A name you declared yourself wins, and is left alone.
  const vars = [
    ["vec2", "uv", "gl_FragCoord.xy / u_resolution"],
    ["vec2", "st", "vec2(uv.x * (u_resolution.x / u_resolution.y), uv.y)"],
    ["vec2", "p", "(gl_FragCoord.xy * 2.0 - u_resolution) / u_resolution.y"],
    ["float", "t", "u_time"],
    ["vec2", "m", "u_mouse / u_resolution"],
    ["float", "seed", "u_seed"],
  ].filter(([, name]) => !defines(name));

  return expandHex(`${PRELUDE}
${vars.map(([ty, name]) => `${ty} ${name};`).join("\n")}
${helpers}
${COERCE}
${preamble}
void main() {
${vars.map(([, name, init]) => `  ${name} = ${init};`).join("\n")}
${body}
  gl_FragColor = vec4(_rgb(
${colour}
  ), 1.0);
}
`);
}
