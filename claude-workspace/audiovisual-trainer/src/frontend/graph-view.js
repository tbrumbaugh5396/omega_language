// A picture of the graph.
//
// The roadmap calls this optional, and it is: the layer panel is the graph
// view most people want, and a node editor with wires is a large thing to
// build for a document whose shape is nearly always a chain. So this shows
// rather than edits — what the passes are, which of them fused, where the
// textures come from, and how many draws it all costs. That is the part that
// answers questions.

import { el } from "./ui.js";
import { nodeType, topo } from "./render-graph.js";
import { planPasses, fuseStats } from "./graph-fuse.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (name, attrs = {}, ...kids) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  for (const k of kids) if (k) n.append(k);
  return n;
};

const BOX_W = 168, BOX_H = 46, GAP_X = 54, GAP_Y = 18;

/**
 * The graph as an SVG: one column per dependency depth, a box per node, a
 * dashed surround for each run that fused into a single draw.
 */
export function graphSvg(graph, opts = {}) {
  const order = topo(graph);
  const depth = new Map();
  for (const n of order) {
    const d = n.inputs.length ? Math.max(...n.inputs.map((i) => (depth.get(i) ?? 0) + 1)) : 0;
    depth.set(n.id, d);
  }
  const cols = new Map();
  for (const n of order) {
    const d = depth.get(n.id);
    if (!cols.has(d)) cols.set(d, []);
    cols.get(d).push(n);
  }
  const at = new Map();
  let maxRow = 0;
  for (const [d, list] of cols) {
    list.forEach((n, i) => {
      at.set(n.id, { x: d * (BOX_W + GAP_X) + 12, y: i * (BOX_H + GAP_Y) + 12 });
      maxRow = Math.max(maxRow, i);
    });
  }
  const width = (Math.max(...cols.keys()) + 1) * (BOX_W + GAP_X) + 24;
  const height = (maxRow + 1) * (BOX_H + GAP_Y) + 24;

  // Which nodes ended up in the same draw.
  const fusedOf = new Map();
  let runs = 0;
  for (const step of planPasses(graph)) {
    if (step.kind !== "fused") continue;
    const tag = runs++;
    for (const n of step.nodes) fusedOf.set(n.id, tag);
  }

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%",
    style: "max-height:56vh", role: "img" });

  // The fused surrounds first, so the boxes sit on top of them.
  for (let tag = 0; tag < runs; tag++) {
    const ids = [...fusedOf.entries()].filter(([, t]) => t === tag).map(([id]) => id);
    const ps = ids.map((id) => at.get(id)).filter(Boolean);
    if (ps.length < 2) continue;
    const x0 = Math.min(...ps.map((p) => p.x)) - 8, y0 = Math.min(...ps.map((p) => p.y)) - 8;
    const x1 = Math.max(...ps.map((p) => p.x)) + BOX_W + 8, y1 = Math.max(...ps.map((p) => p.y)) + BOX_H + 8;
    svg.append(svgEl("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 10,
      fill: "rgba(110,231,200,.07)", stroke: "rgba(110,231,200,.5)", "stroke-dasharray": "5 4" }));
    svg.append(svgEl("text", { x: x0 + 8, y: y0 - 4, fill: "rgba(110,231,200,.9)",
      "font-size": 10, "font-family": "ui-monospace, monospace" },
      document.createTextNode(`fused — ${ps.length} nodes, one draw`)));
  }

  for (const n of order) {
    const p = at.get(n.id);
    for (const inId of n.inputs) {
      const q = at.get(inId);
      if (!q) continue;
      const x1 = q.x + BOX_W, y1 = q.y + BOX_H / 2, x2 = p.x, y2 = p.y + BOX_H / 2;
      const mid = (x1 + x2) / 2;
      svg.append(svgEl("path", { d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`,
        fill: "none", stroke: "rgba(168,176,200,.55)", "stroke-width": 1.4 }));
    }
  }

  for (const n of order) {
    const p = at.get(n.id);
    const isSource = n.type === "source" || n.type === "source.flat";
    const t = nodeType(n.type);
    const g = svgEl("g", { transform: `translate(${p.x},${p.y})` });
    g.append(svgEl("rect", { width: BOX_W, height: BOX_H, rx: 8,
      fill: isSource ? "rgba(124,156,255,.14)" : "rgba(255,255,255,.05)",
      stroke: n.id === graph.output ? "rgba(240,163,94,.9)"
            : isSource ? "rgba(124,156,255,.6)" : "rgba(255,255,255,.18)",
      "stroke-width": n.id === graph.output ? 2 : 1 }));
    const label = isSource ? (n.type === "source.flat" ? "background" : "a texture") : n.type;
    g.append(svgEl("text", { x: 10, y: 19, fill: "#e8ebf5", "font-size": 11,
      "font-family": "system-ui" }, document.createTextNode(label.slice(0, 24))));
    const params = Object.entries(n.params || {})
      .filter(([, v]) => Array.isArray(v) && v.length <= 3)
      .map(([k, v]) => `${k} ${v.map((x) => (+x).toFixed(2).replace(/\.00$/, "")).join(",")}`)
      .join("  ");
    const sub = isSource ? (opts.sourceNames && opts.sourceNames[n.id]) || "" : (params || (t ? `${t.inputs.length} in` : ""));
    g.append(svgEl("text", { x: 10, y: 34, fill: "#8b93ad", "font-size": 9,
      "font-family": "ui-monospace, monospace" }, document.createTextNode(String(sub).slice(0, 30))));
    if (t && t.pass) {
      g.append(svgEl("text", { x: BOX_W - 10, y: 19, fill: "rgba(240,163,94,.9)", "font-size": 9,
        "text-anchor": "end", "font-family": "ui-monospace, monospace" }, document.createTextNode("@pass")));
    }
    svg.append(g);
  }
  return svg;
}

/** The one-line summary that goes under the picture. */
export function graphSummary(graph) {
  const st = fuseStats(graph);
  const bits = [`${st.before} node${st.before === 1 ? "" : "s"}`, `${st.after} draw${st.after === 1 ? "" : "s"}`];
  if (st.saved > 0) bits.push(`${st.saved} saved by fusing`);
  if (st.kept.length) bits.push(`kept apart: ${st.kept.join("; ")}`);
  return bits.join(" · ");
}
