// The node library: where a sketch becomes something the other studios offer.
//
// A node type has never been anything but a sketch with `@node <id>` in its
// header — that is what render-graph.js reads, and it is why the built-in
// catalogue is written as text rather than as code. So a user's own Generate
// document with that one line in it is already a node type; all that was
// missing was for the app to go and look.
//
// This file is that looking: it finds the documents that declare a node,
// registers them, checks each one actually compiles and draws, and hands the
// effect menus a list. Nothing is copied — the document *is* the node, so
// editing the sketch and saving updates the node everywhere it is used.

import { api } from "./ui.js";
import { defineNode, nodeType, NODE_TYPES, createGraph, addNode } from "./render-graph.js";
import { renderGraph, prepareNode } from "./graph-compile.js";
import { sketchMeta, parseUniforms } from "./shader-uniforms.js";

/** id → { id, docId, name, group, help, module, inputs, params, source, error } */
const USER = new Map();

export const userNodes = () => [...USER.values()].filter((n) => !n.error);
export const userNodeProblems = () => [...USER.values()].filter((n) => n.error);
export const isUserNode = (id) => USER.has(id);
export const userNodeFor = (id) => USER.get(id) || null;

/** The source a Generate document actually runs. */
export const sourceOf = (data) => (data && (data.mode === "glsl" ? data.glsl : data.sketch)) || "";

/** Does this document declare a node? The one line that decides it. */
export const declaresNode = (source) => !!sketchMeta(source).node;

/**
 * Namespaced so a user node can never quietly shadow a built-in: a bare name
 * becomes `you.<name>`, a dotted one is taken as written unless the built-in
 * catalogue already owns it.
 */
export function nodeIdFor(source, docId) {
  const raw = String(sketchMeta(source).node || "").trim();
  if (!raw) return null;
  const id = raw.includes(".") ? raw : `you.${raw}`;
  const taken = NODE_TYPES.has(id) && !USER.has(id);
  return taken ? `you.${raw.replace(/\./g, "-")}-${docId}` : id;
}

/**
 * Register one document's sketch as a node type, then prove it: compile it and
 * draw one 16×16 frame. A node that cannot draw is kept in the list with its
 * error rather than dropped, because "my node vanished" is a worse thing to
 * debug than "my node says why".
 */
export async function registerNode(source, { docId, name } = {}) {
  const id = nodeIdFor(source, docId);
  if (!id) return { error: "no `// @node <name>` in the header" };
  const meta = sketchMeta(source);
  // The header says what the author called it; the graph knows it by the
  // namespaced id, so the text it is registered with says the same thing.
  const normalised = String(source).replace(/^(\s*\/\/\s*@node\s+)\S+/m, `$1${id}`);
  let type;
  try {
    type = defineNode(normalised, { title: name || meta.title || id });
  } catch (e) {
    const entry = { id, docId, name, error: String(e.message).split("\n")[0], source };
    USER.set(id, entry);
    return entry;
  }
  const entry = {
    id, docId, name: name || meta.title || id, group: meta.module || null,
    help: meta.title || null, module: meta.module || null,
    inputs: type.inputs.slice(), params: type.params, source: normalised, error: null,
  };
  USER.set(id, entry);
  try {
    await prepareNode(id);
    proveNode(id, type);
  } catch (e) {
    entry.error = String(e.message).split("\n")[0];
  }
  return entry;
}

/** Draw the node once, small, so a broken one is found here and not mid-edit. */
function proveNode(id, type) {
  const graph = createGraph(16, 16);
  const src = document.createElement("canvas");
  src.width = 16; src.height = 16;
  const g = src.getContext("2d");
  g.fillStyle = "#808080"; g.fillRect(0, 0, 16, 16);
  const sources = {};
  const ins = type.inputs.map(() => { const n = addNode(graph, "source"); sources[n] = src; return n; });
  graph.output = addNode(graph, id, {}, ins);
  renderGraph(graph, sources);
}

/**
 * Find every node the signed-in user has written and register it. Called once
 * at boot; failures are reported rather than thrown, because a broken node
 * must not stop the app from starting.
 */
let loading = null;

/**
 * Load the library once, whoever asks first. The boot warms it; anything that
 * needs the list — the Studio page, an effect menu — awaits the same promise
 * rather than racing it.
 */
export function ensureUserNodes() {
  if (!loading) loading = loadUserNodes().catch(() => []);
  return loading;
}

export async function loadUserNodes() {
  let projects = [];
  try {
    const res = await api("/api/studio/projects");
    projects = (res.projects || []).filter((p) => p.kind === "generate");
  } catch { return []; }
  const out = [];
  for (const p of projects) {
    // The listing does not carry the document, so ask for the ones that might
    // be nodes — which is all of them, but each is a few kilobytes of text.
    try {
      const full = await api(`/api/studio/projects/${p.id}`);
      const source = sourceOf(full.data);
      if (!declaresNode(source)) continue;
      out.push(await registerNode(source, { docId: p.id, name: full.name || p.name }));
    } catch { /* one bad document is not the others' problem */ }
  }
  return out;
}

/** Forget a node — used when a document stops declaring one, or is deleted. */
export function unregisterNode(id) {
  USER.delete(id);
  NODE_TYPES.delete(id);
}

// ------------------------------------------------------------------ headers

/**
 * Put a `@node` line into a sketch's header, or change the one that is there.
 * The header is the run of `//` lines at the top; a sketch with none gets one.
 */
export function withNodeHeader(source, { node, module, title }) {
  const lines = String(source).split("\n");
  let end = 0;
  while (end < lines.length && (lines[end].trim().startsWith("//") || !lines[end].trim())) {
    if (lines[end].trim() && !lines[end].trim().startsWith("//")) break;
    if (!lines[end].trim() && end > 0 && !lines[end - 1].trim().startsWith("//")) break;
    end++;
  }
  const head = lines.slice(0, end).filter((l) => l.trim());
  const body = lines.slice(end);
  const kept = head.filter((l) => !/@(node|module)\b/.test(l));
  if (title && !kept.some((l) => !/^\s*\/\/\s*@/.test(l))) kept.unshift(`// ${title}`);
  kept.push(`// @node ${node}`);
  if (module) kept.push(`// @module ${module}`);
  return [...kept, ...body].join("\n");
}

/** The uniforms a sketch offers as inputs, for the "what will this be" note. */
export function nodeShape(source) {
  const us = parseUniforms(source);
  const inputs = us.filter((u) => u.control === "image" && /^in\d+$/.test(u.name)).map((u) => u.name);
  const others = us.filter((u) => u.control === "image" && !/^in\d+$/.test(u.name) && !u.src && !u.lut);
  const params = us.filter((u) => u.control !== "image" && !u.hidden);
  return { inputs, foreignImages: others.map((u) => u.name), params: params.map((u) => u.name) };
}

// ------------------------------------------------------------------ versions
//
// A node other documents depend on is not a thing to edit without a way back.
// Versions live in the document itself — a short ring of previous sources,
// written whenever the text meaningfully changes — so restoring one is a local
// operation and needs no server that knows about nodes.

export const MAX_VERSIONS = 12;

/**
 * Record `source` as a version of this document if it differs from the last
 * one kept. Returns the (possibly unchanged) version list.
 */
export function keepVersion(data, source, note = "") {
  const list = Array.isArray(data.versions) ? data.versions : [];
  const last = list[list.length - 1];
  if (last && last.source === source) return list;
  const next = [...list, { at: new Date().toISOString(), source, note }];
  while (next.length > MAX_VERSIONS) next.shift();
  data.versions = next;
  return next;
}

/** A short description of what changed between two sources, for the list. */
export function versionSummary(prev, next) {
  if (!prev) return "first saved";
  const a = String(prev).split("\n"), b = String(next).split("\n");
  const added = b.filter((l) => !a.includes(l)).length;
  const removed = a.filter((l) => !b.includes(l)).length;
  const ua = new Set(parseUniforms(prev).map((u) => u.name));
  const ub = new Set(parseUniforms(next).map((u) => u.name));
  const gained = [...ub].filter((n) => !ua.has(n));
  const lost = [...ua].filter((n) => !ub.has(n));
  const bits = [];
  if (added || removed) bits.push(`${added} line${added === 1 ? "" : "s"} in, ${removed} out`);
  if (gained.length) bits.push(`+${gained.join(", ")}`);
  if (lost.length) bits.push(`−${lost.join(", ")}`);
  return bits.join(" · ") || "no change to the text";
}

/**
 * Which documents use a node, so an edit can say what it is about to change.
 * Canvas layers and video clips both keep effects as `{kind:"node", ref}`.
 */
export async function usersOfNode(id) {
  let out = [];
  try {
    const { projects } = await api("/api/studio/projects");
    for (const p of projects || []) {
      if (p.kind !== "canvas" && p.kind !== "video") continue;
      const full = await api(`/api/studio/projects/${p.id}`);
      const text = JSON.stringify(full.data || {});
      if (text.includes(`"${id}"`)) out.push({ id: p.id, kind: p.kind, name: full.name || p.name });
    }
  } catch { /* offline: the warning is a courtesy, not a gate */ }
  return out;
}
