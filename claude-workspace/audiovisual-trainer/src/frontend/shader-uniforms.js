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
  "u_prev", "u_state", "u_frame", "u_mouseDown",
]);

// Scanned over the whole source rather than line by line: `uniform vec2 u_r;
// uniform float u_t;` on one line is ordinary GLSL, and an anchored per-line
// pattern silently finds nothing in it.
const DECL = new RegExp(
  "\\buniform\\s+(?:lowp\\s+|mediump\\s+|highp\\s+)?" +
  "(float|int|bool|vec2|vec3|vec4|sampler2D)\\s+" +
  "([A-Za-z_][A-Za-z0-9_]*)\\s*(?:\\[\\s*\\d+\\s*\\])?\\s*;", "g");

const COLOURISH = /(colou?r|tint|rgb|ink|hue|paint)/i;

/** Widths of the value each GLSL type carries. */
const WIDTH = { float: 1, int: 1, bool: 1, vec2: 2, vec3: 3, vec4: 4, sampler2D: 0 };

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
    } else if (key === "data" || key === "asset") {
      // The pixels themselves (a data: URL) or where to fetch them. One
      // token — URLs have no spaces; a data URL can be very long.
      out.src = words[i + 1] || "";
      i += 1;
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
    if (type === "sampler2D") {
      // An image you choose. Its pixel size is offered as <name>_size if the
      // shader declares that vec2; that uniform is then driven, not dialled.
      out.push({ name, type, control: "image", width: 0, isInt: false,
                 min: 0, max: 0, step: 0, label: a.label || name, value: null,
                 sizeUniform: `${name}_size`, src: a.src || null });
      continue;
    }
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
  // A vec2 named <sampler>_size belongs to the sampler, not the panel.
  const samplers = new Set(out.filter((u) => u.control === "image").map((u) => u.name));
  return out.filter((u) => !(u.type === "vec2" && u.name.endsWith("_size")
                             && samplers.has(u.name.slice(0, -5))));
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
  ["sdCapsule", `float sdCapsule(vec2 p, vec2 a, vec2 b, float r){ return sdSegment(p,a,b)-r; }`],
  ["sdEllipse", `float sdEllipse(vec2 p, vec2 r){ float k0=length(p/r), k1=length(p/(r*r)); return k0*(k0-1.0)/max(k1,1e-4); }`],
  ["smin", `float smin(float a, float b, float k){ float h=clamp(0.5+0.5*(b-a)/k,0.0,1.0); return mix(b,a,h)-k*h*(1.0-h); }`],
  // No fwidth: GL_OES_standard_derivatives is an extension, and a sketch that
  // fails to compile on a machine without it is worse than a fixed width.
  ["aa", `float aa(float d, float w){ return smoothstep(w,-w,d); }
float aa(float d){ return aa(d, 1.5/u_resolution.y); }`],
  ["palette", `vec3 palette(float t, vec3 a, vec3 b, vec3 c, vec3 d){ return a+b*cos(6.28318*(c*t+d)); }
vec3 palette(float t){ return palette(t, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0,0.33,0.67)); }`],
  ["srgbToLinear", `vec3 srgbToLinear(vec3 c){ return pow(max(c,0.0), vec3(2.2)); }`],
  ["linearToSrgb", `vec3 linearToSrgb(vec3 c){ return pow(max(c,0.0), vec3(1.0/2.2)); }`],
  // The finishing kit. Everything below works in linear light and expects you
  // to end with finish(), which tone-maps, encodes to sRGB and dithers.
  ["fresnel", `float fresnel(float cosTheta, float f0){ return f0+(1.0-f0)*pow(clamp(1.0-cosTheta,0.0,1.0),5.0); }`],
  ["sky", `vec3 sky(vec3 rd, vec3 sd){
  float y = clamp(rd.y, 0.0, 1.0);
  vec3 col = mix(vec3(0.42,0.55,0.78), vec3(0.04,0.14,0.48), pow(y,0.55));
  float s = max(dot(rd,sd),0.0);
  col += vec3(1.0,0.90,0.70)*(pow(s,512.0)*6.0 + pow(s,64.0)*0.4 + pow(s,6.0)*0.10);
  return col;
}`],
  ["tonemap", `vec3 tonemap(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14),0.0,1.0); }`],
  ["srgb", `vec3 srgb(vec3 c){ c=max(c,0.0); return mix(c*12.92, 1.055*pow(c,vec3(1.0/2.4))-0.055, step(vec3(0.0031308),c)); }`],
  ["dither", `vec3 dither(vec3 c){ return c + (hash21(gl_FragCoord.xy + fract(u_time)*61.0)-0.5)/255.0; }`],
  ["vignette", `float vignette(vec2 uv, float k){ vec2 q=uv*(1.0-uv); return pow(clamp(q.x*q.y*16.0,0.0,1.0),k); }`],
  ["grain", `float grain(vec2 uv, float t){ return hash21(floor(uv*u_resolution)+fract(t*13.7)*91.0)-0.5; }`],
  ["finish", `vec3 finish(vec3 lin){ return dither(srgb(tonemap(lin))); }`],
  // Fit an image into the frame the way CSS object-fit does. Both take the
  // image size in pixels; the frame is u_resolution.
  ["coverUV", `vec2 coverUV(vec2 uv, vec2 img){
  float fa = u_resolution.x/u_resolution.y, ia = img.x/max(img.y,1.0);
  vec2 s = fa > ia ? vec2(1.0, ia/fa) : vec2(fa/ia, 1.0);
  return (uv - 0.5) * s + 0.5;
}`],
  ["containUV", `vec2 containUV(vec2 uv, vec2 img){
  float fa = u_resolution.x/u_resolution.y, ia = img.x/max(img.y,1.0);
  vec2 s = fa > ia ? vec2(fa/ia, 1.0) : vec2(1.0, ia/fa);
  return (uv - 0.5) * s + 0.5;
}`],
  ["luma", `float luma(vec3 c){ return dot(c, vec3(0.2126, 0.7152, 0.0722)); }`],
  // Feedback. prev/state read a uv; the *At forms read at a pixel offset from
  // this fragment, which is what a stencil wants.
  ["prev", `vec4 prev(vec2 q){ return texture2D(u_prev, q); }`],
  ["prevAt", `vec4 prevAt(vec2 dpx){ return texture2D(u_prev, (gl_FragCoord.xy + dpx) / u_resolution); }`],
  ["state", `vec4 state(vec2 q){ return texture2D(u_state, q); }`],
  ["stateAt", `vec4 stateAt(vec2 dpx){ return texture2D(u_state, (gl_FragCoord.xy + dpx) / u_resolution); }`],
];

/**
 * The 3D kit. Only present when the sketch defines `float scene(vec3 p)`,
 * because GLSL has no function pointers: these call scene() through a
 * forward declaration, and an undefined scene() would fail to link every
 * 2D sketch that never wanted them.
 */
const HELPERS_3D = `float scene(vec3 p);
float sdSphere(vec3 p, float r){ return length(p)-r; }
float sdBox3(vec3 p, vec3 b){ vec3 d=abs(p)-b; return length(max(d,0.0))+min(max(d.x,max(d.y,d.z)),0.0); }
float sdTorus(vec3 p, vec2 t){ vec2 q=vec2(length(p.xz)-t.x,p.y); return length(q)-t.y; }
float sdCapsule3(vec3 p, vec3 a, vec3 b, float r){ vec3 pa=p-a, ba=b-a; float h=clamp(dot(pa,ba)/dot(ba,ba),0.0,1.0); return length(pa-ba*h)-r; }
float sdPlane(vec3 p, float h){ return p.y-h; }
vec3 normal3(vec3 p){
  vec2 e=vec2(0.0008,0.0);
  return normalize(vec3(scene(p+e.xyy)-scene(p-e.xyy), scene(p+e.yxy)-scene(p-e.yxy), scene(p+e.yyx)-scene(p-e.yyx)));
}
float march(vec3 ro, vec3 rd, float maxD){
  float t=0.0;
  for(int i=0;i<96;i++){ float d=scene(ro+rd*t); if(d<0.0006*t+0.0004) return t; t+=d*0.9; if(t>maxD) break; }
  return -1.0;
}
float softShadow(vec3 ro, vec3 rd, float k){
  float res=1.0, t=0.03;
  for(int i=0;i<40;i++){ float h=scene(ro+rd*t); if(h<0.0004) return 0.0; res=min(res,k*h/t); t+=clamp(h,0.01,0.25); if(t>14.0) break; }
  return clamp(res,0.0,1.0);
}
float ao(vec3 p, vec3 n){
  float occ=0.0, sca=1.0;
  for(int i=0;i<5;i++){ float h=0.01+0.14*float(i)/4.0; occ+=(h-scene(p+n*h))*sca; sca*=0.9; }
  return clamp(1.0-2.5*occ,0.0,1.0);
}
mat3 lookAt(vec3 ro, vec3 ta){
  vec3 f=normalize(ta-ro); vec3 r=normalize(cross(f,vec3(0.0,1.0,0.0))); vec3 u=cross(r,f);
  return mat3(r,u,f);
}`;

/** Names the sketch is allowed to end with, whatever their type. */
const COERCE = `vec3 _rgb(vec3 c){ return c; }
vec3 _rgb(vec4 c){ return c.rgb; }
vec3 _rgb(vec2 c){ return vec3(c, 0.0); }
vec3 _rgb(float g){ return vec3(g); }`;

// highp where the GPU offers it: raymarched water and hashes of large
// coordinates fall apart in mediump.
const PRELUDE = `#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#endif
uniform vec2  u_resolution;
uniform vec2  u_mouse;
uniform float u_time;
uniform float u_seed;
uniform sampler2D u_prev;    // last frame — of the state if sim() exists, else of the picture
uniform sampler2D u_state;   // this frame's state, once sim() has run
uniform int   u_frame;       // frames since Restart; 0 on the first
uniform float u_mouseDown;   // 1.0 while the pointer is pressed on the canvas`;

/** The variables in scope inside a sketch, documented for the help panel. */
export const SKETCH_VARS = [
  ["uv", "vec2", "0 to 1 across the frame, y up"],
  ["st", "vec2", "aspect-corrected — y is 0 to 1, x is scaled by the aspect"],
  ["p", "vec2", "centred and aspect-corrected, roughly -1 to 1. Radial work wants this"],
  ["t", "float", "seconds since the sketch started"],
  ["m", "vec2", "pointer, 0 to 1"],
  ["seed", "float", "changes when you press Randomise"],
  ["md", "float", "1.0 while the pointer is pressed on the canvas"],
  ["frame", "int", "frames since Restart — 0 on the first, so a sim can set its initial state"],
  ["<image>_size", "vec2", "pixels of a sampler2D you declared, if you also declare this vec2"],
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
// `type name(args) {` — and not `if (...) {`, which also ends in a brace but
// belongs inside main.
const FUNC_DEF = new RegExp(
  "^\\s*(?!(?:if|for|while|do|else|switch|return)\\b)" +
  "[A-Za-z_]\\w*(?:\\s+[A-Za-z_]\\w*)*\\s+[A-Za-z_]\\w*\\s*\\([^)]*\\)\\s*\\{");
const DECL_START = /^\s*(uniform|attribute|varying|const|struct|precision|invariant)\b/;
// A real directive, not a `#f80` colour literal that happens to start a line.
const DIRECTIVE = /^[ \t]*#\s*(define|undef|if|ifdef|ifndef|else|elif|endif|extension|version|pragma|line|error)\b[^\n]*/gm;

export function splitSketch(sketch) {
  const decls = [], stmts = [];
  // Preprocessor lines end at the newline, not at a semicolon, so they are
  // lifted out first. Blanked to spaces, so every later offset still holds.
  const src = String(sketch).replace(DIRECTIVE, (m) => {
    decls.push(m.trim());
    return " ".repeat(m.length);
  });
  const bare = stripComments(src);
  const spans = [];
  let brace = 0, paren = 0, start = 0;

  for (let i = 0; i < bare.length; i++) {
    const ch = bare[i];
    if (ch === "(") paren++;
    else if (ch === ")") paren = Math.max(0, paren - 1);
    else if (ch === "{") brace++;
    else if (ch === "}") {
      if (--brace <= 0) { brace = 0; spans.push([start, i + 1]); start = i + 1; }
    } else if (ch === ";" && brace === 0 && paren === 0) {
      // paren === 0 keeps the semicolons inside `for (a; b; c)` from splitting it
      spans.push([start, i + 1]); start = i + 1;
    }
  }

  for (let [s, e] of spans) {
    // Absorb a trailing comment on the same line, so the annotation stays with
    // the declaration it belongs to.
    const nl = bare.indexOf("\n", e);
    const upto = nl === -1 ? bare.length : nl;
    if (!bare.slice(e, upto).trim()) e = upto;

    const text = src.slice(s, e);
    const code = bare.slice(s, e).trim();
    if (!code) continue;
    const isDecl = DECL_START.test(code) || FUNC_DEF.test(code);
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

  let helpers = HELPERS
    .filter(([name]) =>
      !new RegExp(`\\b(?:float|int|vec2|vec3|vec4|mat2)\\s+${name}\\s*\\(`).test(declared))
    .map(([, src]) => src)
    .join("\n");
  if (/\bfloat\s+scene\s*\(\s*vec3\b/.test(declared)) helpers += "\n" + HELPERS_3D;

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
    ["float", "md", "u_mouseDown"],
    ["int", "frame", "u_frame"],
  ].filter(([, name]) => !defines(name));

  // Defining `vec4 sim(vec2 uv)` adds a state pass. The same file serves both
  // passes: the runtime prepends `#define SIM_PASS` for the first one.
  const hasSim = /\bvec4\s+sim\s*\(\s*vec2\b/.test(declared);
  const simBlock = hasSim ? `#ifdef SIM_PASS
  gl_FragColor = sim(gl_FragCoord.xy / u_resolution);
#else
` : "";
  const simEnd = hasSim ? "\n#endif" : "";

  return expandHex(`${PRELUDE}
${vars.map(([ty, name]) => `${ty} ${name};`).join("\n")}
${helpers}
${COERCE}
${preamble}
void main() {
${vars.map(([, name, init]) => `  ${name} = ${init};`).join("\n")}
${simBlock}${body}
  gl_FragColor = vec4(_rgb(
${colour}
  ), 1.0);${simEnd}
}
`);
}

/** Does this shader (sketch-generated or hand-written) carry a state pass? */
export function hasSimPass(glsl) {
  return /\bSIM_PASS\b/.test(stripComments(glsl));
}

/**
 * Put images into the source itself. For each sampler with a value, the
 * declaration line gains `@data <dataURL>` (or `@asset <url>` when asked to
 * reference rather than embed). `resolve(name, value)` returns the string to
 * write — a data URL from the caller's fetch, or the asset URL. The result
 * is still valid GLSL; the loader reads the comment and fills the sampler.
 */
export async function embedImages(src, uniforms, values, resolve, key = "data") {
  let out = String(src);
  for (const u of uniforms) {
    if (u.control !== "image") continue;
    const v = values[u.name];
    if (!v || !v.url) continue;
    const url = await resolve(u.name, v);
    if (!url) continue;
    const decl = new RegExp("(\\buniform\\s+sampler2D\\s+" + u.name + "\\s*;)([^\\n]*)");
    out = out.replace(decl, (m, head, rest) => {
      const c = rest.indexOf("//");
      const tag = `@${key} ${url}`;
      if (c === -1) return `${head}  // ${tag}`;
      let body = rest.slice(c + 2).replace(/@(?:data|asset)\s+\S+/, "").replace(/\s+$/, "");
      return `${head}${rest.slice(0, c)}// ${tag}${body ? " " + body.trim() : ""}`;
    });
  }
  return out;
}

/**
 * Write the current control values back into the source as `@default`
 * annotations, so the code carries the state — what you dialled is what a
 * fresh copy opens with. Works on a sketch or on full GLSL alike, because it
 * only touches uniform declaration lines.
 */
export function bakeDefaults(src, uniforms, values) {
  let out = String(src);
  const fmt = (v, u) => {
    if (u.isInt || u.type === "int") return String(Math.round(v));
    if (u.type === "bool") return v > 0.5 ? "1" : "0";
    const s = Math.abs(v) >= 100 ? v.toFixed(1) : Math.abs(v) >= 10 ? v.toFixed(2) : v.toFixed(3);
    return s.replace(/\.?0+$/, "") || "0";
  };
  for (const u of uniforms) {
    if (u.control === "image") continue;
    const v = values[u.name];
    if (!Array.isArray(v)) continue;
    const decl = new RegExp(
      "(\\buniform\\s+(?:lowp\\s+|mediump\\s+|highp\\s+)?" + u.type + "\\s+" + u.name +
      "\\s*;)([^\\n]*)");
    out = out.replace(decl, (m, head, rest) => {
      const val = v.map((x) => fmt(x, u)).join(" ");
      let comment = rest;
      const c = rest.indexOf("//");
      if (c === -1) return `${head}  // @default ${val}`;
      const before = rest.slice(0, c), body = rest.slice(c + 2);
      // Replace an existing @default (with however many numbers) or add one
      // right after the // so it reads first.
      const re = /@default(\s+-?[\d.]+)+/;
      const newBody = re.test(body) ? body.replace(re, `@default ${val}`)
                                    : ` @default ${val}` + body;
      comment = `${before}//${newBody}`;
      return head + comment;
    });
  }
  return out;
}
