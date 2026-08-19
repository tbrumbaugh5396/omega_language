// A small expression language for parameter values.
//
// `radius` used to be a number. This lets it be `4 + sin(t * 2)`, or
// `ch("blur.radius") * 0.5` — a reference to another node's parameter — so a
// graph can hold a *relationship* rather than a pile of constants. One slider
// then drives ten things, which is the difference between a document and a
// system.
//
// Deliberately not JavaScript. `new Function` on a string out of a saved
// document is a way to run whatever the document says, and a document is data.
// So this is a tokeniser, a precedence-climbing parser and a tree-walking
// evaluator — about the same size as the thing it refuses to use, and it can
// say which parameters an expression depends on, which `new Function` cannot.
//
// Everything is a scalar. A vec2 takes one expression per component, or one
// expression for both. Nothing here touches the graph: `ch` arrives from the
// caller, which is what keeps this file testable on its own.

// ------------------------------------------------------------------ tokens

const NUMBER = /^(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/;
const NAME = /^[A-Za-z_]\w*/;
// Longest first, so `<=` is never read as `<` then `=`.
const PUNCT = ["<=", ">=", "==", "!=", "&&", "||",
               "+", "-", "*", "/", "%", "^", "<", ">", "?", ":", "(", ")", ","];

function tokenise(src) {
  const out = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (/\s/.test(ch)) { i++; continue; }
    if (ch === '"' || ch === "'") {
      const end = src.indexOf(ch, i + 1);
      if (end < 0) throw new Error(`unterminated string at ${i}`);
      out.push({ k: "str", v: src.slice(i + 1, end), at: i });
      i = end + 1;
      continue;
    }
    const rest = src.slice(i);
    let m = NUMBER.exec(rest);
    if (m) { out.push({ k: "num", v: parseFloat(m[0]), at: i }); i += m[0].length; continue; }
    m = NAME.exec(rest);
    if (m) { out.push({ k: "name", v: m[0], at: i }); i += m[0].length; continue; }
    const p = PUNCT.find((q) => rest.startsWith(q));
    if (p) { out.push({ k: p, at: i }); i += p.length; continue; }
    throw new Error(`unexpected "${ch}" at ${i}`);
  }
  return out;
}

// ------------------------------------------------------------------ functions

const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
// A deterministic hash, so `hash(3)` is the same number every run and on every
// machine. Animation that jitters wants to jitter the same way twice.
const hash1 = (x) => {
  const s = Math.sin(x * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
};

/** name → [arity, fn]. Arity -1 means variadic. */
export const FUNCTIONS = {
  sin: [1, Math.sin], cos: [1, Math.cos], tan: [1, Math.tan],
  asin: [1, Math.asin], acos: [1, Math.acos], atan: [1, Math.atan],
  atan2: [2, Math.atan2],
  abs: [1, Math.abs], sign: [1, Math.sign],
  floor: [1, Math.floor], ceil: [1, Math.ceil], round: [1, Math.round],
  sqrt: [1, Math.sqrt], exp: [1, Math.exp],
  log: [1, Math.log], log2: [1, Math.log2],
  pow: [2, Math.pow], hypot: [-1, (...a) => Math.hypot(...a)],
  min: [-1, (...a) => Math.min(...a)], max: [-1, (...a) => Math.max(...a)],
  clamp: [3, clamp],
  mix: [3, (a, b, u) => a + (b - a) * u],
  step: [2, (e, x) => (x < e ? 0 : 1)],
  smoothstep: [3, (e0, e1, x) => {
    const u = clamp((x - e0) / (e1 - e0 || 1e-9), 0, 1);
    return u * u * (3 - 2 * u);
  }],
  // GLSL's mod, not JavaScript's %: the sign follows the divisor, so
  // mod(-1, 4) is 3. A parameter that wraps wants that one.
  mod: [2, (a, b) => a - b * Math.floor(a / (b || 1e-9))],
  fract: [1, (x) => x - Math.floor(x)],
  hash: [1, hash1],
  // Fold a value into -r..r, the way a position wraps at the edge of a
  // screen. mod with the divisor's sign, so it never jumps.
  wrap: [2, (v, r) => { const d = 2 * (r || 1e-9); return v + r - d * Math.floor((v + r) / d) - r; }],
  // Smooth value noise, 0..1, one dimension. For drift that is not a sine.
  noise: [1, (x) => {
    const i = Math.floor(x), f = x - i;
    const u = f * f * (3 - 2 * f);
    return hash1(i) + (hash1(i + 1) - hash1(i)) * u;
  }],
};

export const CONSTANTS = { pi: Math.PI, tau: Math.PI * 2, e: Math.E };

// ------------------------------------------------------------------ parser

/**
 * Precedence-climbing. Each level parses the one above it and then loops on
 * its own operators, so the table is the grammar.
 */
const BINARY = [
  ["||"], ["&&"],
  ["==", "!="], ["<", "<=", ">", ">="],
  ["+", "-"], ["*", "/", "%"],
];

function parse(tokens, src) {
  let i = 0;
  const peek = () => tokens[i];
  const at = () => (tokens[i] ? tokens[i].at : src.length);
  const eat = (k) => {
    if (!tokens[i] || tokens[i].k !== k) throw new Error(`expected ${k} at ${at()}`);
    return tokens[i++];
  };

  const ternary = () => {
    const cond = binary(0);
    if (!peek() || peek().k !== "?") return cond;
    eat("?");
    const a = ternary();
    eat(":");
    const b = ternary();
    return { k: "if", cond, a, b };
  };

  function binary(level) {
    if (level >= BINARY.length) return unary();
    let left = binary(level + 1);
    for (;;) {
      const tk = peek();
      if (!tk || !BINARY[level].includes(tk.k)) return left;
      i++;
      left = { k: "bin", op: tk.k, a: left, b: binary(level + 1) };
    }
  }

  function unary() {
    const tk = peek();
    if (tk && (tk.k === "-" || tk.k === "+")) { i++; return { k: "un", op: tk.k, a: unary() }; }
    return power();
  }

  // Right-associative and tighter than unary minus, so -2^2 is -(2^2).
  function power() {
    const base = primary();
    if (peek() && peek().k === "^") { i++; return { k: "bin", op: "^", a: base, b: unary() }; }
    return base;
  }

  function primary() {
    const tk = peek();
    if (!tk) throw new Error(`the expression ends early, at ${src.length}`);
    if (tk.k === "num") { i++; return { k: "num", v: tk.v }; }
    if (tk.k === "str") { i++; return { k: "str", v: tk.v }; }
    if (tk.k === "(") { i++; const e = ternary(); eat(")"); return e; }
    if (tk.k === "name") {
      i++;
      if (peek() && peek().k === "(") {
        i++;
        const args = [];
        if (peek() && peek().k !== ")") {
          args.push(ternary());
          while (peek() && peek().k === ",") { i++; args.push(ternary()); }
        }
        eat(")");
        return { k: "call", name: tk.v, args, at: tk.at };
      }
      return { k: "var", name: tk.v, at: tk.at };
    }
    throw new Error(`unexpected ${tk.k} at ${tk.at}`);
  }

  const tree = ternary();
  if (i < tokens.length) throw new Error(`unexpected ${tokens[i].k} at ${tokens[i].at}`);
  return tree;
}

// ------------------------------------------------------------------ walking

/** Every `ch("…")` and `prev("…")` with a literal name, so dependencies are known before it runs. */
function referencesOf(node, into = []) {
  if (!node || typeof node !== "object") return into;
  if (node.k === "call" && (node.name === "ch" || node.name === "prev") && node.args[0] && node.args[0].k === "str") {
    into.push({ path: node.args[0].v, last: node.name === "prev",
                comp: node.args[1] && node.args[1].k === "num" ? node.args[1].v : 0 });
  }
  for (const key of ["cond", "a", "b"]) if (node[key]) referencesOf(node[key], into);
  for (const arg of node.args || []) referencesOf(arg, into);
  return into;
}

function walk(node, env) {
  switch (node.k) {
    case "num": return node.v;
    case "str": return node.v;
    case "if": return walk(node.cond, env) ? walk(node.a, env) : walk(node.b, env);
    case "un": return node.op === "-" ? -walk(node.a, env) : +walk(node.a, env);
    case "bin": {
      const a = walk(node.a, env);
      // Short-circuit, so `x != 0 && 1/x > 2` never divides by zero.
      if (node.op === "&&") return a && walk(node.b, env) ? 1 : 0;
      if (node.op === "||") return a || walk(node.b, env) ? 1 : 0;
      const b = walk(node.b, env);
      switch (node.op) {
        case "+": return a + b;
        case "-": return a - b;
        case "*": return a * b;
        case "/": return b === 0 ? 0 : a / b;
        case "%": return b === 0 ? 0 : a % b;
        case "^": return Math.pow(a, b);
        case "<": return a < b ? 1 : 0;
        case ">": return a > b ? 1 : 0;
        case "<=": return a <= b ? 1 : 0;
        case ">=": return a >= b ? 1 : 0;
        case "==": return a === b ? 1 : 0;
        case "!=": return a !== b ? 1 : 0;
        default: throw new Error(`no operator ${node.op}`);
      }
    }
    case "var": {
      if (node.name in CONSTANTS) return CONSTANTS[node.name];
      if (env.vars && node.name in env.vars) return env.vars[node.name];
      throw new Error(`"${node.name}" is not a name this expression can see`);
    }
    case "call": {
      // The three ways an expression reaches outside itself. `ch` is another
      // parameter this frame; `prev` is a parameter as it was *last* frame,
      // which is what makes a parameter a state and an expression an update;
      // `key` is the keyboard. All three arrive from the caller, so this file
      // knows nothing about graphs or keyboards and can be tested without one.
      if (node.name === "ch" || node.name === "prev") {
        const look = env[node.name];
        if (!look) throw new Error(`${node.name}() has nothing to look up here`);
        const path = walk(node.args[0], env);
        const comp = node.args.length > 1 ? walk(node.args[1], env) : 0;
        return look(String(path), Math.round(comp));
      }
      if (node.name === "key" || node.name === "keyHit" || node.name === "keyToggle") {
        if (!env.keys) throw new Error(`${node.name}() — no keyboard reaches this graph`);
        const code = Math.round(walk(node.args[0], env));
        const row = node.name === "key" ? env.keys.down : node.name === "keyHit" ? env.keys.hit : env.keys.toggle;
        return code >= 0 && code < row.length && row[code] ? 1 : 0;
      }
      const f = FUNCTIONS[node.name];
      if (!f) throw new Error(`there is no function called "${node.name}"`);
      const args = node.args.map((a) => walk(a, env));
      if (f[0] >= 0 && args.length !== f[0]) {
        throw new Error(`${node.name}() takes ${f[0]} argument${f[0] === 1 ? "" : "s"}, given ${args.length}`);
      }
      return f[1](...args);
    }
    default: throw new Error(`cannot evaluate ${node.k}`);
  }
}

/**
 * Compile once, evaluate many times.
 *
 * Returns { value(env), refs, error, text }. `value` always answers a finite
 * number and records anything that went wrong in `.runtimeError`, so a caller
 * never has to tell a value from a failure. A bad expression yields an `error`
 * at compile time rather than throwing, because it usually arrives from a
 * saved document and a typo in one parameter must not take the render down.
 */
export function compileExpr(text) {
  const src = String(text ?? "");
  const fail = (msg) => ({
    text: src, refs: [], error: msg, runtimeError: null, value() { return 0; },
  });
  let tree;
  try { tree = parse(tokenise(src), src); } catch (e) { return fail(e.message); }
  const out = {
    text: src, refs: referencesOf(tree), error: null, runtimeError: null,
    value(env = {}) {
      try {
        const v = walk(tree, env);
        out.runtimeError = null;
        return Number.isFinite(v) ? v : 0;
      } catch (e) {
        out.runtimeError = e.message;
        return 0;
      }
    },
  };
  return out;
}

/** Every name an expression may use, for the editor and the error message. */
export const VOCABULARY = {
  functions: Object.keys(FUNCTIONS).sort(),
  constants: Object.keys(CONSTANTS),
  reference: 'ch("node.param") — another node\'s parameter, by name or by id; "param" alone is this node\'s',
  state: 'prev("node.param") — the same, as it was last frame; its stored value before the first',
  input: "key(code), keyHit(code), keyToggle(code) — the keyboard, by key code",
};
