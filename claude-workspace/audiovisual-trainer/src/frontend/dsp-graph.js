// The DSP node grammar, and the compiler that turns a graph of them into one
// inner loop.
//
// This is the audio roadmap's Phase A, and it is deliberately the same shape
// as the visual side: a node is *text*, its declarations are its contract, and
// the schema lives in a comment so one grammar serves the panel, the
// documentation and the compiler. What audio adds is the thing a picture
// never needed —
//
//   in float x;              a signal coming in
//   out float lp, bp, hp;    signals going out; more than one is normal
//   state float ic1eq;       a value that survives to the next sample
//   uniform float cutoff;    // @range 20 20000 @default 800 @log
//
// `state` is the whole difference between this and a shader. Naming it
// explicitly is what lets the compiler decide what to allocate, what to clear
// on reset, and what may be fused — rather than inferring it from a closure
// and hoping.
//
// The body is used *verbatim*, inside a block that declares its inputs,
// outputs, uniforms and state as ordinary locals. So there is no renaming, no
// macro expansion, and what you read in the node is what runs.

const DECL = /^\s*(in|out|state|uniform)\s+(float)\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;/;

/** Read `@` annotations off a trailing comment — the same grammar as sketches. */
function annotations(comment) {
  const out = { flags: new Set() };
  if (!comment) return out;
  const words = comment.trim().split(/\s+/);
  const rest = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (w[0] !== "@") { rest.push(w); continue; }
    const key = w.slice(1).toLowerCase();
    if (key === "range") {
      const lo = parseFloat(words[i + 1]), hi = parseFloat(words[i + 2]);
      if (Number.isFinite(lo) && Number.isFinite(hi)) { out.min = lo; out.max = hi; i += 2; }
    } else if (key === "default") {
      const d = parseFloat(words[i + 1]);
      if (Number.isFinite(d)) { out.default = d; i += 1; }
    } else if (key === "help") {
      let j = i + 1;
      while (j < words.length && words[j][0] !== "@") j++;
      out.help = words.slice(i + 1, j).join(" ");
      i = j - 1;
    } else out.flags.add(key);
  }
  if (!out.help && rest.length) out.help = rest.join(" ");
  return out;
}

/** The header a node carries: what it is, and where it belongs. */
export function dspMeta(src) {
  const meta = { node: null, module: null, rate: "audio", title: null, delay: 0 };
  for (const raw of String(src).split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (!line.startsWith("//")) break;
    const body = line.replace(/^\/\/\s?/, "");
    if (meta.title === null && !body.startsWith("@")) meta.title = body;
    const m = /@(node|module|rate|delay)\b\s*(\S*)/.exec(body);
    if (!m) continue;
    if (m[1] === "delay") meta.delay = parseInt(m[2] || "1", 10) || 1;
    else meta[m[1]] = m[2] || null;
  }
  return meta;
}

/**
 * A node's declarations and its body. Everything before the last declaration
 * is contract; everything after is the code that runs once per sample.
 */
export function parseDspNode(source) {
  const meta = dspMeta(source);
  const lines = String(source).split("\n");
  const ins = [], outs = [], states = [], uniforms = [];
  let lastDecl = -1;
  lines.forEach((line, i) => {
    const m = DECL.exec(line.replace(/\/\/.*$/, ""));
    if (!m) return;
    lastDecl = i;
    const [, kind, , namesRaw] = m;
    const comment = (line.match(/\/\/(.*)$/) || [null, ""])[1];
    const a = annotations(comment);
    for (const name of namesRaw.split(",").map((s) => s.trim())) {
      if (kind === "in") ins.push({ name, help: a.help || null });
      else if (kind === "out") outs.push({ name, help: a.help || null });
      else if (kind === "state") states.push({ name });
      else {
        uniforms.push({
          name,
          min: a.min ?? 0, max: a.max ?? 1,
          value: a.default ?? (a.min !== undefined ? a.min : 0),
          log: a.flags.has("log"), help: a.help || null,
          rate: a.flags.has("control") ? "control" : meta.rate,
        });
      }
    }
  });
  const body = lines.slice(lastDecl + 1).join("\n").trim();
  return { ...meta, source, ins, outs, states, uniforms, body };
}

// ------------------------------------------------------------------ registry

export const DSP_NODES = new Map();

export function defineDspNode(source) {
  const t = parseDspNode(source);
  if (!t.node) throw new Error("a DSP node needs `// @node <id>` in its header");
  if (!t.outs.length) throw new Error(`${t.node}: a node with no out port produces nothing`);
  if (!t.body) throw new Error(`${t.node}: no body — the code after the declarations is what runs`);
  DSP_NODES.set(t.node, t);
  return t;
}

export const dspNode = (id) => DSP_NODES.get(id) || null;

// ------------------------------------------------------------------ graph

let nextId = 1;
export const createDspGraph = () => ({ nodes: [], output: null });

/**
 * Add a node. `inputs` maps this node's in-port names to `[nodeId, outName]`
 * or to a constant number.
 */
export function addDspNode(graph, type, { inputs = {}, params = {} } = {}) {
  if (!DSP_NODES.has(type)) throw new Error(`no DSP node type "${type}"`);
  const id = `n${nextId++}`;
  graph.nodes.push({ id, type, inputs: { ...inputs }, params: { ...params } });
  return id;
}

const findDsp = (graph, id) => graph.nodes.find((n) => n.id === id) || null;

/**
 * Nodes in dependency order.
 *
 * A cycle is legal in audio and is not in a shader — a reverb *is* a loop —
 * but only through a node that declares `@delay`, because a loop with no
 * delay has no first sample to compute. The error names the nodes in it,
 * since "cyclic graph" tells you nothing you can act on.
 */
export function topoDsp(graph) {
  const order = [], state = new Map();
  const path = [];
  const visit = (id) => {
    const n = findDsp(graph, id);
    if (!n) throw new Error(`the graph refers to a missing node ${id}`);
    const st = state.get(id);
    if (st === "done") return;
    if (st === "open") {
      const loop = path.slice(path.indexOf(id)).concat(id);
      const delayed = loop.some((x) => { const t = findDsp(graph, x); return t && dspNode(t.type).delay > 0; });
      if (!delayed) throw new Error(`a feedback loop with no delay in it: ${loop.join(" → ")}`);
      return;                                   // the delay breaks it; stop here
    }
    state.set(id, "open");
    path.push(id);
    for (const wire of Object.values(n.inputs)) {
      if (Array.isArray(wire)) visit(wire[0]);
    }
    path.pop();
    state.set(id, "done");
    order.push(n);
  };
  visit(graph.output);
  return order;
}

// ------------------------------------------------------------------ compiler

const MATH = ["sin", "cos", "tan", "abs", "min", "max", "sqrt", "exp", "log",
              "pow", "floor", "ceil", "round", "atan", "atan2", "sign", "hypot"];

/**
 * A graph as the body of one `process()` loop.
 *
 * Every node's body goes in verbatim, inside a block that declares its ports,
 * uniforms and state as locals — which is the audio equivalent of the visual
 * compiler's fusion, and for the same reason: the buffer between two nodes is
 * pointless when both are per-sample.
 */
export function compileDspGraph(graph) {
  const order = topoDsp(graph);
  const params = [];                 // AudioParam descriptors
  const stateSlots = [];             // one entry per state variable
  const lines = [];
  const notes = [];

  for (const n of order) {
    const t = dspNode(n.type);
    const pre = `${n.id}_`;
    lines.push(`      // ${n.id}: ${t.node}${t.title ? ` — ${t.title}` : ""}`);
    lines.push("      {");
    // Inputs: a wire, a constant, or silence.
    for (const port of t.ins) {
      const wire = n.inputs[port.name];
      const expr = Array.isArray(wire) ? `${wire[0]}_${wire[1]}`
                 : Number.isFinite(wire) ? Number(wire).toFixed(8)
                 : "0";
      lines.push(`        const ${port.name} = ${expr};`);
    }
    // Uniforms become AudioParams: sample-accurate, and no message per change.
    for (const u of t.uniforms) {
      const pname = `${pre}${u.name}`;
      const given = n.params[u.name];
      params.push({
        name: pname,
        defaultValue: Number.isFinite(given) ? given : u.value,
        minValue: u.min, maxValue: u.max,
        automationRate: u.rate === "control" ? "k-rate" : "a-rate",
      });
      lines.push(`        const ${u.name} = P_${pname}.length > 1 ? P_${pname}[i] : P_${pname}[0];`);
    }
    // State: read in, written back, one slot each.
    for (const s of t.states) {
      const slot = stateSlots.length;
      stateSlots.push({ node: n.id, name: s.name, slot });
      lines.push(`        let ${s.name} = S[${slot}];`);
    }
    for (const o of t.outs) lines.push(`        let ${o.name} = 0;`);
    for (const bodyLine of t.body.split("\n")) lines.push(`        ${bodyLine}`);
    for (const s of t.states) {
      const slot = stateSlots.find((x) => x.node === n.id && x.name === s.name).slot;
      lines.push(`        S[${slot}] = ${s.name};`);
    }
    for (const o of t.outs) lines.push(`        ${pre}${o.name} = ${o.name};`);
    lines.push("      }");
  }

  const outNode = findDsp(graph, graph.output);
  const outPort = dspNode(outNode.type).outs[0].name;
  const declares = order.flatMap((n) => dspNode(n.type).outs.map((o) => `${n.id}_${o.name}`));

  return {
    params, states: stateSlots, notes,
    outExpr: `${outNode.id}_${outPort}`,
    declares,
    loop: lines.join("\n"),
    math: MATH,
  };
}

// ------------------------------------------------------------------ the rule

// What must never appear in code that runs on the audio thread. Every one of
// these allocates, and an allocation in the audio callback is a garbage
// collection, and a garbage collection is a click — the one failure nobody
// forgives. The compiler emits code that avoids them; this reads the emitted
// text and says so if it did not.
const FORBIDDEN = [
  [/\bnew\s+[A-Z]/, "constructs an object"],
  [/=>/, "a closure"],
  [/\bfunction\b/, "a function expression"],
  [/\.\s*(push|map|filter|slice|concat|split|join|reduce|forEach|sort)\s*\(/, "an array method that allocates"],
  [/=\s*\[/, "an array literal"],
  [/=\s*\{/, "an object literal"],
  [/["'`]/, "a string"],
  [/\bconsole\s*\./, "console, which formats and allocates"],
  [/\bJSON\s*\./, "JSON"],
  [/\bpostMessage\s*\(/, "postMessage inside the loop"],
];

/** Anything in this code that would allocate on the audio thread. */
export function allocationReport(code) {
  const findings = [];
  String(code).split("\n").forEach((line, i) => {
    const bare = line.replace(/\/\/.*$/, "");
    if (!bare.trim()) return;
    for (const [re, why] of FORBIDDEN) {
      if (re.test(bare)) findings.push({ line: i + 1, why, text: line.trim().slice(0, 70) });
    }
  });
  return findings;
}
