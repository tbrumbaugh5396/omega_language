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

const DECL = /^\s*(in|out|state|coef|delay|uniform|perVoice)\s+(float|int)\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;/;

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
    } else if (key === "size") {
      const n = parseInt(words[i + 1], 10);
      if (Number.isFinite(n)) { out.size = n; i += 1; }
    } else if (key === "options") {
      out.options = String(words[i + 1] || "").split(",").map((w2) => w2.trim()).filter(Boolean);
      i += 1;
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
  const ins = [], outs = [], states = [], uniforms = [], coefs = [], delays = [], perVoice = [];
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
      // A coefficient is worked out once a block and read every sample. That
      // is the whole point of @rate: a biquad's tan() and cos() have no
      // business running forty-eight thousand times a second when the cutoff
      // only moved once.
      else if (kind === "coef") coefs.push({ name });
      // A delay line is memory, not a number. Its size is fixed at compile
      // time and rounded up to a power of two, so the wrap is a mask.
      else if (kind === "delay") delays.push({ name, size: Math.max(2, a.size ?? 4096) });
      // A per-voice value: one number per voice, written from outside and
      // read inside the voice loop. This is what makes polyphony the graph
      // instantiated N times rather than N graphs.
      else if (kind === "perVoice") perVoice.push({ name, value: a.default ?? 0, help: a.help || null });
      else {
        const opts = a.options || null;
        uniforms.push({
          name,
          min: a.min ?? 0, max: a.max ?? (opts ? opts.length - 1 : 1),
          value: a.default ?? (a.min !== undefined ? a.min : 0),
          log: a.flags.has("log"), help: a.help || null, options: opts,
          // A choice and a coefficient source are control-rate by nature; a
          // node may say so for anything else.
          rate: (a.flags.has("control") || opts) ? "control" : meta.rate,
        });
      }
    }
  });
  // The body may be in two parts: what runs once a block, and what runs
  // every sample. `// @block` opens the first, `// @sample` the second; a
  // node with neither is all sample, which is what Phase A's nodes are.
  const rest = lines.slice(lastDecl + 1);
  let blockBody = "", sampleBody = "";
  const bStart = rest.findIndex((l) => /^\s*\/\/\s*@block\s*$/.test(l));
  const sStart = rest.findIndex((l) => /^\s*\/\/\s*@sample\s*$/.test(l));
  if (bStart >= 0 && sStart > bStart) {
    blockBody = rest.slice(bStart + 1, sStart).join("\n").trim();
    sampleBody = rest.slice(sStart + 1).join("\n").trim();
  } else {
    sampleBody = rest.join("\n").trim();
  }
  return { ...meta, source, ins, outs, states, coefs, delays, uniforms, perVoice,
           body: sampleBody, blockBody };
}

// ------------------------------------------------------------------ registry

export const DSP_NODES = new Map();

export function defineDspNode(source) {
  const t = parseDspNode(source);
  if (!t.node) throw new Error("a DSP node needs `// @node <id>` in its header");
  if (!t.outs.length) throw new Error(`${t.node}: a node with no out port produces nothing`);
  if (t.coefs.length && !t.blockBody) {
    throw new Error(`${t.node}: it declares coefficients but has no // @block section to work them out in`);
  }
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
export function compileDspGraph(graph, { voices = 1 } = {}) {
  const V = Math.max(1, Math.min(64, voices | 0));
  const order = topoDsp(graph);
  const params = [];                 // AudioParam descriptors
  const stateSlots = [];             // one entry per state variable
  const lines = [];                  // the per-sample loop
  const pre = [];                    // once a block, before the loop
  const coefDecls = [];              // coefficients, alive across the loop
  const buffers = [];                // delay lines, made in the constructor
  const voiceArrays = [];            // one number per voice, written from outside
  const notes = [];

  // A back edge — a wire from a node that has not been computed yet this
  // sample — is a feedback path, and its value has to be *last* sample's.
  // Holding it in a local would lose it at the end of every block and click
  // 375 times a second, so it lives in state like anything else that has to
  // survive.
  const position = new Map(order.map((n, i) => [n.id, i]));
  const feedback = new Map();          // "nX_out" → state slot
  for (const n of order) {
    for (const wire of Object.values(n.inputs)) {
      if (!Array.isArray(wire)) continue;
      if (position.get(wire[0]) < position.get(n.id)) continue;   // ordinary edge
      const key = `${wire[0]}_${wire[1]}`;
      if (feedback.has(key)) continue;
      const slot = stateSlots.length;
      stateSlots.push({ node: wire[0], name: `${wire[1]}__fb`, slot });
      feedback.set(key, slot);
    }
  }

  for (const n of order) {
    const t = dspNode(n.type);
    const px = `${n.id}_`;

    // Control-rate uniforms are read once, before the loop: a k-rate
    // AudioParam hands over one number for the whole block anyway.
    const controls = t.uniforms.filter((u) => u.rate === "control");
    for (const u of controls) {
      const pname = `${px}${u.name}`;
      const given = n.params[u.name];
      params.push({
        name: pname, defaultValue: Number.isFinite(given) ? given : u.value,
        minValue: u.min, maxValue: u.max, automationRate: "k-rate",
      });
      pre.push(`    const ${px}${u.name} = P_${pname}[0];`);
    }
    // Delay lines: a power-of-two ring each, plus its write index in state.
    for (const d of t.delays) {
      let size = 2;
      while (size < d.size) size *= 2;
      const bufName = `${px}${d.name}`;
      const idxSlot = stateSlots.length;
      stateSlots.push({ node: n.id, name: `${d.name}__w`, slot: idxSlot });
      // Each voice gets its own stretch of the ring, so one voice's echoes
      // are not another's.
      buffers.push({ name: bufName, size, mask: size - 1, idxSlot, voices: V });
    }
    for (const pv of t.perVoice) {
      voiceArrays.push({ name: `${px}${pv.name}`, node: n.id, port: pv.name,
                         value: pv.value, voices: V });
    }
    if (t.blockBody) {
      pre.push(`    // ${n.id}: ${t.node} — once a block`);
      pre.push("    {");
      for (const u of controls) pre.push(`      const ${u.name} = ${px}${u.name};`);
      for (const c of t.coefs) coefDecls.push(`    let ${px}${c.name} = 0;`);
      for (const c of t.coefs) pre.push(`      let ${c.name} = 0;`);
      for (const bodyLine of t.blockBody.split("\n")) pre.push(`      ${bodyLine}`);
      for (const c of t.coefs) pre.push(`      ${px}${c.name} = ${c.name};`);
      pre.push("    }");
    }

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
    // Audio-rate uniforms are read per sample; control-rate ones were read
    // before the loop and are simply brought into scope here.
    for (const u of t.uniforms) {
      if (u.rate === "control") { lines.push(`        const ${u.name} = ${px}${u.name};`); continue; }
      const pname = `${px}${u.name}`;
      const given = n.params[u.name];
      params.push({
        name: pname,
        defaultValue: Number.isFinite(given) ? given : u.value,
        minValue: u.min, maxValue: u.max, automationRate: "a-rate",
      });
      lines.push(`        const ${u.name} = P_${pname}.length > 1 ? P_${pname}[i] : P_${pname}[0];`);
    }
    for (const c of t.coefs) lines.push(`        const ${c.name} = ${px}${c.name};`);
    for (const pv of t.perVoice) lines.push(`        const ${pv.name} = VP_${px}${pv.name}[v];`);
    // State: read in, written back, one slot each.
    for (const s of t.states) {
      const slot = stateSlots.length;
      stateSlots.push({ node: n.id, name: s.name, slot });
      lines.push(`        let ${s.name} = S[vBase + ${slot}];`);
    }
    for (const o of t.outs) lines.push(`        let ${o.name} = 0;`);
    // A delay line's two operations are macros rather than calls: a call per
    // sample costs with nothing to show for it. The rewrite matches the
    // closing parenthesis rather than guessing at it, because `dRead(fi + 1)`
    // and `dRead(n)` must both come out right.
    const macro = (text) => {
      let outText = text;
      for (const d of t.delays) {
        const buf = buffers.find((x) => x.name === `${px}${d.name}`);
        const w = `S[vBase + ${buf.idxSlot}]`;
        for (const [call, wrap] of [
          [`${d.name}Read`, (arg) => `B_${buf.name}[bBase_${buf.name} + ((${w} - (${arg})) & ${buf.mask})]`],
          [`${d.name}Write`, (arg) => `B_${buf.name}[bBase_${buf.name} + ${w}] = (${arg})`],
        ]) {
          for (;;) {
            const at = outText.indexOf(`${call}(`);
            if (at < 0) break;
            let depth = 0, k = at + call.length;
            for (; k < outText.length; k++) {
              if (outText[k] === "(") depth++;
              else if (outText[k] === ")" && --depth === 0) break;
            }
            const arg = outText.slice(at + call.length + 1, k);
            outText = outText.slice(0, at) + wrap(arg) + outText.slice(k + 1);
          }
        }
      }
      return outText;
    };
    for (const bodyLine of t.body.split("\n")) lines.push(`        ${macro(bodyLine)}`);
    for (const d of t.delays) {
      const buf = buffers.find((x) => x.name === `${px}${d.name}`);
      lines.push(`        S[vBase + ${buf.idxSlot}] = (S[vBase + ${buf.idxSlot}] + 1) & ${buf.mask};`);
    }
    for (const s of t.states) {
      const slot = stateSlots.find((x) => x.node === n.id && x.name === s.name).slot;
      lines.push(`        S[vBase + ${slot}] = ${s.name};`);
    }
    for (const o of t.outs) {
      lines.push(`        ${px}${o.name} = ${o.name};`);
      const slot = feedback.get(`${px}${o.name}`);
      if (slot !== undefined) lines.push(`        S[vBase + ${slot}] = ${o.name};`);
    }
    lines.push("      }");
  }

  const outNode = findDsp(graph, graph.output);
  const outPort = dspNode(outNode.type).outs[0].name;
  const declares = order.flatMap((n) => dspNode(n.type).outs.map((o) => `${n.id}_${o.name}`));

  return {
    params, states: stateSlots, notes, buffers, voiceArrays, voices: V,
    stateStride: stateSlots.length,
    feedback: [...feedback.entries()],
    outExpr: `${outNode.id}_${outPort}`,
    declares,
    coefDecls: coefDecls.join("\n"),
    pre: pre.join("\n"),
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
