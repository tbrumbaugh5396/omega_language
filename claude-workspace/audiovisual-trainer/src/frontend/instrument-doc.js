// An instrument, as text.
//
// Everything else authored here is text with its schema in a comment — a node
// is a sketch with `@node` in its header, a DSP node likewise. An instrument
// is a *graph* of those, and a graph of anything has been a JavaScript call
// until now, which is why instruments could not be saved: there was nothing
// to save.
//
// So: a patch. One line per node, `local = type key=value …`, where a value is
// a number (a parameter) or `other.port` (a wire). The header carries what the
// library needs to know.
//
//     // A plain enveloped tone.
//     // @instrument tone.mine
//     // @voices 4
//
//     note = voice.note
//     env  = env.ad     gate=note.gate  attackMs=3  decayMs=180
//     out  = osc.sineHz hz=note.hz  gate=env.y  amp=0.3
//
// The local names are the point. `out` is what you hear and the `voice.note`
// is where notes are written, both by convention and both overridable; and
// every *other* name — `env`, `hum` — becomes a part of the instrument that a
// document's effects can address by name, so `{ kind: "param", node: "hum" }`
// works whether the instrument was carried or referenced, and keeps working
// when the library renumbers it.
//
// Parsing never throws. A patch with a bad line yields the nodes that did
// parse and a list of what did not, because an editor that goes blank on a
// typo is an editor you fight.

import { createDspGraph, addDspNode, dspNode, DSP_NODES } from "./dsp-graph.js";

const HEADER = /@(instrument|voices|gain|out|note)\b\s*(\S*)/;

/** `local = type k=v …` — the whole grammar, in one expression. */
const LINE = /^([A-Za-z_]\w*)\s*=\s*([A-Za-z_][\w.]*)\s*(.*)$/;
const ARG = /([A-Za-z_]\w*)\s*=\s*(\S+)/g;

/**
 * A patch's text → { decl, errors, parts, meta }.
 *
 * `decl` is an instrument declaration ready for the library — the same shape
 * `toneInstrument()` returns — or null when there is nothing to make one from.
 */
export function parsePatch(text) {
  const src = String(text ?? "");
  const errors = [];
  const meta = { instrument: null, voices: 8, gain: 1, out: null, note: null, title: null };

  const lines = src.split("\n");
  const body = [];
  let inHeader = true;
  lines.forEach((raw, i) => {
    const line = raw.trim();
    const at = i + 1;
    if (!line) return;
    if (line.startsWith("//")) {
      const said = line.replace(/^\/\/\s?/, "");
      if (!inHeader) return;                       // a comment lower down is a note to a reader
      if (meta.title === null && !said.startsWith("@")) meta.title = said;
      const m = HEADER.exec(said);
      if (m) {
        if (m[1] === "voices" || m[1] === "gain") {
          const v = parseFloat(m[2]);
          if (Number.isFinite(v)) meta[m[1]] = v;
          else errors.push(`line ${at}: @${m[1]} wants a number, not "${m[2]}"`);
        } else meta[m[1]] = m[2] || null;
      }
      return;
    }
    inHeader = false;
    body.push({ line, at });
  });

  // Two passes: every local name has to exist before any wire is followed, so
  // a patch may name a node below the one that reads it — which a feedback
  // loop through a delay has to be able to do.
  const decls = [];
  const byName = new Map();
  for (const { line, at } of body) {
    const m = LINE.exec(line);
    if (!m) { errors.push(`line ${at}: expected \`name = type key=value …\``); continue; }
    const [, name, type, rest] = m;
    if (byName.has(name)) { errors.push(`line ${at}: "${name}" is declared twice`); continue; }
    if (!DSP_NODES.has(type)) {
      errors.push(`line ${at}: there is no DSP node called "${type}"`);
      continue;
    }
    const d = { name, type, rest, at };
    decls.push(d);
    byName.set(name, d);
  }

  const graph = createDspGraph();
  for (const d of decls) d.id = addDspNode(graph, d.type, {});

  for (const d of decls) {
    const t = dspNode(d.type);
    const node = graph.nodes.find((n) => n.id === d.id);
    const inNames = new Set(t.ins.map((p) => p.name));
    const paramNames = new Set([...t.uniforms.map((u) => u.name), ...t.perVoice.map((p) => p.name)]);
    ARG.lastIndex = 0;
    let m;
    while ((m = ARG.exec(d.rest))) {
      const [, key, value] = m;
      const num = parseFloat(value);
      const wire = /^([A-Za-z_]\w*)\.([A-Za-z_]\w*)$/.exec(value);
      if (wire) {
        if (!inNames.has(key)) {
          errors.push(`line ${d.at}: ${d.type} has no input called "${key}" (it has ${[...inNames].join(", ") || "none"})`);
          continue;
        }
        const from = byName.get(wire[1]);
        if (!from) { errors.push(`line ${d.at}: there is no node called "${wire[1]}"`); continue; }
        const outs = dspNode(from.type).outs.map((o) => o.name);
        if (!outs.includes(wire[2])) {
          errors.push(`line ${d.at}: ${from.type} has no output called "${wire[2]}" (it has ${outs.join(", ")})`);
          continue;
        }
        node.inputs[key] = [from.id, wire[2]];
      } else if (Number.isFinite(num)) {
        if (inNames.has(key)) node.inputs[key] = num;          // a constant into an input port
        else if (paramNames.has(key)) node.params[key] = num;
        else errors.push(`line ${d.at}: ${d.type} has no parameter called "${key}"`);
      } else {
        errors.push(`line ${d.at}: "${key}=${value}" is neither a number nor a wire`);
      }
    }
  }

  if (!decls.length) return { decl: null, errors, meta, parts: {} };

  // What you hear: `@out`, else a node called `out`, else the last one.
  const outName = meta.out || (byName.has("out") ? "out" : decls[decls.length - 1].name);
  const outDecl = byName.get(outName);
  if (!outDecl) errors.push(`@out names "${outName}", which is not a node here`);
  graph.output = outDecl ? outDecl.id : decls[decls.length - 1].id;

  // Where notes are written: `@note`, else the one `voice.note`.
  let noteDecl = meta.note ? byName.get(meta.note) : decls.find((d) => d.type === "voice.note");
  if (meta.note && !noteDecl) errors.push(`@note names "${meta.note}", which is not a node here`);
  if (!noteDecl) errors.push("no voice.note in this patch — an instrument with nowhere to write a note plays nothing");

  // Every local name is a part the document can address.
  const parts = {};
  for (const d of decls) parts[d.name] = d.id;

  const decl = {
    graph,
    noteNode: noteDecl ? noteDecl.id : null,
    voices: Math.max(1, Math.round(meta.voices)),
    gain: meta.gain,
    parts,
  };
  return { decl, errors, meta, parts };
}

/** A number as short as it can be written and still mean the same. */
const num = (v) => {
  const s = String(+v);
  return s.includes("e") ? String(+v) : s;
};

/**
 * A declaration → its patch text. The other direction, so an instrument built
 * in code — or normalised by the library — can be read, edited and saved.
 */
export function toPatch(decl, { name = null, title = null } = {}) {
  const g = decl.graph;
  const parts = decl.parts || {};
  // Prefer the names the instrument already carries for its own nodes; give
  // anything unnamed a name from its type, so the text never says `n17`.
  const nameOf = new Map();
  for (const [k, id] of Object.entries(parts)) nameOf.set(id, k);
  for (const [k, v] of Object.entries(decl)) {
    if (["graph", "noteNode", "voices", "gain", "voiceInit", "ref", "parts"].includes(k)) continue;
    if (typeof v === "string" && g.nodes.some((n) => n.id === v)) nameOf.set(v, k);
  }
  const used = new Set(nameOf.values());
  const fresh = (base) => {
    let n = base, k = 2;
    while (used.has(n)) n = `${base}${k++}`;
    used.add(n);
    return n;
  };
  for (const n of g.nodes) {
    if (nameOf.has(n.id)) continue;
    nameOf.set(n.id, n.id === g.output ? fresh("out") : fresh(n.type.split(".")[1] || "n"));
  }

  const head = [
    `// ${title || name || "An instrument"}.`,
    name ? `// @instrument ${name}` : null,
    `// @voices ${decl.voices || 8}`,
    (decl.gain ?? 1) !== 1 ? `// @gain ${num(decl.gain)}` : null,
    nameOf.get(g.output) !== "out" ? `// @out ${nameOf.get(g.output)}` : null,
  ].filter(Boolean);

  const width = Math.max(...g.nodes.map((n) => nameOf.get(n.id).length));
  const rows = g.nodes.map((n) => {
    const args = [];
    for (const [k, w] of Object.entries(n.inputs || {})) {
      args.push(`${k}=${Array.isArray(w) ? `${nameOf.get(w[0]) || w[0]}.${w[1]}` : num(w)}`);
    }
    for (const [k, v] of Object.entries(n.params || {})) args.push(`${k}=${num(v)}`);
    return `${nameOf.get(n.id).padEnd(width)} = ${n.type}${args.length ? "  " + args.join("  ") : ""}`;
  });
  return `${head.join("\n")}\n\n${rows.join("\n")}\n`;
}

/** The starting patch a new instrument document gets. */
export const STARTER_PATCH = `// A plain enveloped tone. Change a number and press Audition.
// @instrument mine
// @voices 4

note = voice.note
env  = env.ad      gate=note.gate  attackMs=3  decayMs=180
out  = osc.sineHz  hz=note.hz  gate=env.y  amp=0.3
`;
