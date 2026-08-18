// An SVG file → a Generate sketch, through the same emitter the Design studio
// uses. SVG is the best possible input for this: it is already structure, so
// nothing is recovered from pixels — rects, ellipses and paths simply become
// signed-distance functions, gradients become ramps, and painter's order
// becomes a mix chain.
//
// Curves are flattened adaptively: a cubic is subdivided until its control
// points lie within a tolerance of the chord, so the segment count follows the
// curvature rather than a fixed guess. Arcs are converted to centre form and
// sampled by angle. Everything is done in the file's own user units and only
// then transformed, which keeps the numbers readable in the output.
//
// What is not attempted, and says so in the notes it returns: CSS stylesheets
// and classes, filters, masks, patterns, and real glyphs (text is greeked, as
// in the Design compiler — a paragraph of outlines needs an SDF atlas).

import {
  num, hex, I, mul, translate, scaleM, rotateAbout, localise,
  polygonBody, openStrokeBody, dashPolylines, emitSketch,
} from "./sdf-core.js";
import { buildAtlas, emitTextRun, GLYPH_HELPER } from "./glyph-atlas.js";

const NAMED = {
  black: "#000000", white: "#ffffff", red: "#ff0000", lime: "#00ff00",
  blue: "#0000ff", yellow: "#ffff00", cyan: "#00ffff", aqua: "#00ffff",
  magenta: "#ff00ff", fuchsia: "#ff00ff", silver: "#c0c0c0", gray: "#808080",
  grey: "#808080", maroon: "#800000", olive: "#808000", green: "#008000",
  purple: "#800080", teal: "#008080", navy: "#000080", orange: "#ffa500",
  pink: "#ffc0cb", brown: "#a52a2a", gold: "#ffd700", indigo: "#4b0082",
  violet: "#ee82ee", tan: "#d2b48c", beige: "#f5f5dc", ivory: "#fffff0",
  crimson: "#dc143c", salmon: "#fa8072", khaki: "#f0e68c", plum: "#dda0dd",
  orchid: "#da70d6", turquoise: "#40e0d0", tomato: "#ff6347", coral: "#ff7f50",
  darkblue: "#00008b", darkgreen: "#006400", darkred: "#8b0000",
  lightblue: "#add8e6", lightgreen: "#90ee90", lightgray: "#d3d3d3",
  lightgrey: "#d3d3d3", transparent: "none", none: "none",
};

/** A paint value: a colour, "none", or a url(#id) reference. */
function paint(v, fallback = null) {
  const s = String(v ?? "").trim();
  if (!s || s === "none" || s === "transparent") return s === "" ? fallback : null;
  const url = /^url\(\s*['"]?#([^)'"]+)['"]?\s*\)/.exec(s);
  if (url) return { ref: url[1] };
  if (s === "currentColor") return "#000000";
  const low = s.toLowerCase();
  if (NAMED[low]) return NAMED[low] === "none" ? null : NAMED[low];
  const rgb = /^rgba?\(\s*([\d.]+%?)\s*[,\s]\s*([\d.]+%?)\s*[,\s]\s*([\d.]+%?)/.exec(s);
  if (rgb) {
    const ch = (t) => {
      const n = parseFloat(t);
      return Math.max(0, Math.min(255, Math.round(t.includes("%") ? (n / 100) * 255 : n)));
    };
    return "#" + [1, 2, 3].map((i) => ch(rgb[i]).toString(16).padStart(2, "0")).join("");
  }
  if (/^#[0-9a-fA-F]{3,8}$/.test(s)) return hex(s.slice(0, 7));
  return fallback;
}

const len = (v, d = 0) => {
  if (v === null || v === undefined || v === "") return d;
  const m = /^\s*(-?[\d.]+(?:e[+-]?\d+)?)\s*(px|pt|mm|cm|in|%)?/i.exec(String(v));
  if (!m) return d;
  const n = parseFloat(m[1]);
  const unit = (m[2] || "").toLowerCase();
  return unit === "pt" ? n * 1.3333 : unit === "mm" ? n * 3.7795
       : unit === "cm" ? n * 37.795 : unit === "in" ? n * 96 : n;
};

function parseTransform(s) {
  let m = I;
  if (!s) return m;
  const re = /(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)/g;
  let t;
  while ((t = re.exec(s))) {
    const a = t[2].trim().split(/[\s,]+/).map(Number).filter((x) => Number.isFinite(x));
    const k = t[1];
    if (k === "matrix" && a.length >= 6) m = mul(m, a.slice(0, 6));
    else if (k === "translate") m = mul(m, translate(a[0] || 0, a[1] || 0));
    else if (k === "scale") m = mul(m, scaleM(a[0] ?? 1, a[1] ?? a[0] ?? 1));
    else if (k === "rotate") m = mul(m, rotateAbout(a[0] || 0, a[1] || 0, a[2] || 0));
    else if (k === "skewX") m = mul(m, [1, 0, Math.tan(((a[0] || 0) * Math.PI) / 180), 1, 0, 0]);
    else if (k === "skewY") m = mul(m, [1, Math.tan(((a[0] || 0) * Math.PI) / 180), 0, 1, 0, 0]);
  }
  return m;
}

/** Presentation attributes plus an inline style attribute; style wins. */
function styleOf(elem) {
  const out = {};
  for (const a of elem.attributes || []) out[a.name] = a.value;
  const st = elem.getAttribute && elem.getAttribute("style");
  if (st) {
    for (const decl of st.split(";")) {
      const i = decl.indexOf(":");
      if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
  }
  return out;
}

// ------------------------------------------------------------------ paths

function tokenisePath(d) {
  const out = [];
  const re = /([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?)/g;
  let m;
  while ((m = re.exec(d))) out.push(m[1] !== undefined ? m[1] : parseFloat(m[2]));
  return out;
}

function flattenCubic(p0, p1, p2, p3, tol, out, depth = 0) {
  const dx = p3[0] - p0[0], dy = p3[1] - p0[1];
  const d1 = Math.abs((p1[0] - p3[0]) * dy - (p1[1] - p3[1]) * dx);
  const d2 = Math.abs((p2[0] - p3[0]) * dy - (p2[1] - p3[1]) * dx);
  if (depth > 16 || (d1 + d2) * (d1 + d2) <= tol * (dx * dx + dy * dy)) { out.push(p3); return; }
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const p01 = mid(p0, p1), p12 = mid(p1, p2), p23 = mid(p2, p3);
  const p012 = mid(p01, p12), p123 = mid(p12, p23), c = mid(p012, p123);
  flattenCubic(p0, p01, p012, c, tol, out, depth + 1);
  flattenCubic(c, p123, p23, p3, tol, out, depth + 1);
}
const quadToCubic = (p0, p1, p2) => [
  [p0[0] + (2 / 3) * (p1[0] - p0[0]), p0[1] + (2 / 3) * (p1[1] - p0[1])],
  [p2[0] + (2 / 3) * (p1[0] - p2[0]), p2[1] + (2 / 3) * (p1[1] - p2[1])],
];

/** Endpoint arc → centre form, then sampled by angle (SVG F.6.5). */
function arcPoints(p0, rx, ry, rot, large, sweep, p1, out) {
  if (rx === 0 || ry === 0) { out.push(p1); return; }
  rx = Math.abs(rx); ry = Math.abs(ry);
  const phi = (rot * Math.PI) / 180, cp = Math.cos(phi), sp = Math.sin(phi);
  const dx2 = (p0[0] - p1[0]) / 2, dy2 = (p0[1] - p1[1]) / 2;
  const x1 = cp * dx2 + sp * dy2, y1 = -sp * dx2 + cp * dy2;
  let l = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry);
  if (l > 1) { const s = Math.sqrt(l); rx *= s; ry *= s; }
  const sign = large === sweep ? -1 : 1;
  const numr = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
  const den = rx * rx * y1 * y1 + ry * ry * x1 * x1;
  const co = sign * Math.sqrt(Math.max(0, numr) / (den || 1e-9));
  const cx1 = (co * rx * y1) / ry, cy1 = (-co * ry * x1) / rx;
  const cx = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2;
  const cy = sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2;
  const ang = (ux, uy, vx, vy) => {
    const d = (Math.sqrt(ux * ux + uy * uy) * Math.sqrt(vx * vx + vy * vy)) || 1e-9;
    let a = Math.acos(Math.max(-1, Math.min(1, (ux * vx + uy * vy) / d)));
    if (ux * vy - uy * vx < 0) a = -a;
    return a;
  };
  const th0 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry);
  let dth = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry);
  if (!sweep && dth > 0) dth -= 2 * Math.PI;
  if (sweep && dth < 0) dth += 2 * Math.PI;
  const steps = Math.max(2, Math.ceil((Math.abs(dth) / (Math.PI / 2)) * 8));
  for (let i = 1; i <= steps; i++) {
    const th = th0 + (dth * i) / steps;
    const ex = rx * Math.cos(th), ey = ry * Math.sin(th);
    out.push([cp * ex - sp * ey + cx, sp * ex + cp * ey + cy]);
  }
}

/** A path's `d` → subpaths of flattened points, in user units. */
export function pathToSubpaths(d, tol = 0.04) {
  const t = tokenisePath(d);
  const subs = [];
  let cur = null, cx = 0, cy = 0, sx = 0, sy = 0;
  let cmd = "", px = 0, py = 0, hadCurve = false;
  let i = 0;
  const start = () => { cur = { pts: [[cx, cy]], closed: false }; subs.push(cur); };
  while (i < t.length) {
    if (typeof t[i] === "string") { cmd = t[i]; i++; if (cmd === "Z" || cmd === "z") {
      if (cur) { cur.closed = true; cx = sx; cy = sy; }
      continue;
    } }
    const rel = cmd === cmd.toLowerCase();
    const n = (k) => t[i + k];
    if (cmd === "M" || cmd === "m") {
      cx = rel ? cx + n(0) : n(0); cy = rel ? cy + n(1) : n(1); i += 2;
      sx = cx; sy = cy; start();
      cmd = rel ? "l" : "L";
    } else if (cmd === "L" || cmd === "l") {
      cx = rel ? cx + n(0) : n(0); cy = rel ? cy + n(1) : n(1); i += 2;
      if (!cur) start(); else cur.pts.push([cx, cy]);
    } else if (cmd === "H" || cmd === "h") {
      cx = rel ? cx + n(0) : n(0); i += 1;
      if (!cur) start(); else cur.pts.push([cx, cy]);
    } else if (cmd === "V" || cmd === "v") {
      cy = rel ? cy + n(0) : n(0); i += 1;
      if (!cur) start(); else cur.pts.push([cx, cy]);
    } else if (cmd === "C" || cmd === "c" || cmd === "S" || cmd === "s") {
      let c1, c2, p3;
      if (cmd === "C" || cmd === "c") {
        c1 = [rel ? cx + n(0) : n(0), rel ? cy + n(1) : n(1)];
        c2 = [rel ? cx + n(2) : n(2), rel ? cy + n(3) : n(3)];
        p3 = [rel ? cx + n(4) : n(4), rel ? cy + n(5) : n(5)];
        i += 6;
      } else {
        c1 = hadCurve ? [2 * cx - px, 2 * cy - py] : [cx, cy];
        c2 = [rel ? cx + n(0) : n(0), rel ? cy + n(1) : n(1)];
        p3 = [rel ? cx + n(2) : n(2), rel ? cy + n(3) : n(3)];
        i += 4;
      }
      if (!cur) start();
      flattenCubic([cx, cy], c1, c2, p3, tol, cur.pts);
      px = c2[0]; py = c2[1]; cx = p3[0]; cy = p3[1]; hadCurve = true;
      continue;
    } else if (cmd === "Q" || cmd === "q" || cmd === "T" || cmd === "t") {
      let c1, p2;
      if (cmd === "Q" || cmd === "q") {
        c1 = [rel ? cx + n(0) : n(0), rel ? cy + n(1) : n(1)];
        p2 = [rel ? cx + n(2) : n(2), rel ? cy + n(3) : n(3)];
        i += 4;
      } else {
        c1 = hadCurve ? [2 * cx - px, 2 * cy - py] : [cx, cy];
        p2 = [rel ? cx + n(0) : n(0), rel ? cy + n(1) : n(1)];
        i += 2;
      }
      if (!cur) start();
      const [a, b] = quadToCubic([cx, cy], c1, p2);
      flattenCubic([cx, cy], a, b, p2, tol, cur.pts);
      px = c1[0]; py = c1[1]; cx = p2[0]; cy = p2[1]; hadCurve = true;
      continue;
    } else if (cmd === "A" || cmd === "a") {
      const rx = n(0), ry = n(1), rot = n(2), large = !!n(3), sweep = !!n(4);
      const ex = rel ? cx + n(5) : n(5), ey = rel ? cy + n(6) : n(6);
      i += 7;
      if (!cur) start();
      arcPoints([cx, cy], rx, ry, rot, large, sweep, [ex, ey], cur.pts);
      cx = ex; cy = ey; hadCurve = false;
      continue;
    } else { i++; continue; }
    hadCurve = false;
  }
  return subs.filter((s) => s.pts.length > 1);
}

// ------------------------------------------------------------------ gradients

function gradientFn(def, world, bbox, idFor, notes) {
  const st = styleOf(def);
  const units = (st.gradientUnits || "objectBoundingBox");
  const gt = parseTransform(st.gradientTransform);
  const stops = [...def.querySelectorAll("stop")].map((s) => {
    const ss = styleOf(s);
    let off = String(ss.offset ?? "0").trim();
    const o = off.endsWith("%") ? parseFloat(off) / 100 : parseFloat(off) || 0;
    const a = Math.max(0, Math.min(1, parseFloat(ss["stop-opacity"] ?? "1")));
    return { o: Math.max(0, Math.min(1, o)), a: Number.isFinite(a) ? a : 1,
             c: paint(ss["stop-color"], "#000000") || "#000000" };
  }).sort((a, b) => a.o - b.o);
  if (!stops.length) return null;

  // objectBoundingBox coordinates are fractions of the shape's own box.
  const ux = (v, d) => units === "objectBoundingBox"
    ? bbox.x + (v === undefined || v === null || v === "" ? d : parseFloat(v) * (String(v).endsWith("%") ? 0.01 : 1)) * bbox.w
    : len(v, d);
  const uy = (v, d) => units === "objectBoundingBox"
    ? bbox.y + (v === undefined || v === null || v === "" ? d : parseFloat(v) * (String(v).endsWith("%") ? 0.01 : 1)) * bbox.h
    : len(v, d);

  let tExpr;
  if (def.tagName.toLowerCase() === "radialgradient") {
    const cx = ux(st.cx, 0.5), cy = uy(st.cy, 0.5);
    const r = units === "objectBoundingBox"
      ? (st.r === undefined ? 0.5 : parseFloat(st.r)) * Math.max(bbox.w, bbox.h)
      : len(st.r, 0);
    tExpr = `clamp(length(gq - vec2(${num(cx, 3)}, ${num(cy, 3)})) / ${num(Math.max(r, 1e-3), 3)}, 0.0, 1.0)`;
  } else {
    const x1 = ux(st.x1, 0), y1 = uy(st.y1, 0), x2 = ux(st.x2, 1), y2 = uy(st.y2, 0);
    const dx = x2 - x1, dy = y2 - y1, l2 = Math.max(dx * dx + dy * dy, 1e-6);
    tExpr = `clamp(dot(gq - vec2(${num(x1, 3)}, ${num(y1, 3)}), vec2(${num(dx, 3)}, ${num(dy, 3)})) / ${num(l2, 4)}, 0.0, 1.0)`;
  }

  // A ramp of colour, and — only when some stop asks for it — a ramp of alpha
  // alongside it. Opaque gradients stay vec3 so the common case costs nothing.
  const translucent = stops.some((st) => st.a < 1);
  const ty = translucent ? "vec4" : "vec3";
  const lit = (st) => (translucent ? `vec4(${st.c}, ${num(st.a, 3)})` : st.c);
  const ramp = [`  ${ty} c = ${lit(stops[0])};`];
  for (let k = 1; k < stops.length; k++) {
    const a = stops[k - 1].o, b = stops[k].o;
    ramp.push(`  c = mix(c, ${lit(stops[k])}, clamp((tg - ${num(a, 4)}) / ${num(Math.max(b - a, 1e-4), 4)}, 0.0, 1.0));`);
  }
  const name = idFor();
  // The gradient lives in the shape's own space, so it localises q the same
  // way the shape does, then undoes any gradientTransform.
  const inner = mul(world, gt);
  return {
    name, vec4: translucent,
    src: `${ty} ${name}(vec2 q) {
${localise(inner)}
  vec2 gq = lq;
  float tg = ${tExpr};
${ramp.join("\n")}
  return c;
}`,
  };
}

// ------------------------------------------------------------------ compile

/**
 * Compile SVG text to a sketch.
 * @returns { source, width, height, shapes, notes }
 */
export async function compileSvg(text, opts = {}) {
  const dom = new DOMParser().parseFromString(text, "image/svg+xml");
  const err = dom.querySelector("parsererror");
  if (err) throw new Error("that file is not valid SVG");
  const root = dom.documentElement;
  if (!root || root.tagName.toLowerCase() !== "svg") throw new Error("no <svg> element");

  const notes = new Set();
  if (dom.querySelector("style")) notes.add("a <style> block was ignored — only presentation attributes and inline style are read");
  if (dom.querySelector("filter")) notes.add("<filter> is ignored — those are pass effects, not per-pixel");
  if (dom.querySelector("mask")) notes.add("<mask> is ignored");
  if (dom.querySelector("pattern")) notes.add("<pattern> is ignored");

  // Size: width/height if given, else the viewBox.
  const vb = (root.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  const hasVB = vb.length === 4 && vb.every(Number.isFinite);
  let W = len(root.getAttribute("width"), 0), H = len(root.getAttribute("height"), 0);
  if ((!W || !H) && hasVB) { W = W || vb[2]; H = H || vb[3]; }
  if (!W || !H) { W = W || 512; H = H || 512; }
  if (opts.maxSize) {
    const s = Math.min(1, opts.maxSize / Math.max(W, H));
    W = Math.round(W * s); H = Math.round(H * s);
  }
  // viewBox → output, preserveAspectRatio: the default meet, centred.
  let rootM = I;
  if (hasVB && vb[2] > 0 && vb[3] > 0) {
    const par = (root.getAttribute("preserveAspectRatio") || "xMidYMid meet").trim();
    const s = par.startsWith("none") ? null : Math.min(W / vb[2], H / vb[3]);
    rootM = s === null
      ? mul(scaleM(W / vb[2], H / vb[3]), translate(-vb[0], -vb[1]))
      : mul(mul(translate((W - vb[2] * s) / 2, (H - vb[3] * s) / 2), scaleM(s)), translate(-vb[0], -vb[1]));
  }

  const items = [];
  const uniforms = [];
  const texts = [];
  const clips = new Map();      // id → emitted clip function name
  let gradN = 0, imgN = 0, edgeTotal = 0, truncated = 0;
  const EDGE_CAP = opts.edgeCap || 9000;

  const bboxOf = (subs) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const s of subs) for (const p of s.pts) {
      x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]);
      x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]);
    }
    return x0 > x1 ? { x: 0, y: 0, w: 1, h: 1 } : { x: x0, y: y0, w: Math.max(x1 - x0, 1e-3), h: Math.max(y1 - y0, 1e-3) };
  };

  /** Resolve a paint into something emitSketch understands. */
  const resolvePaint = (p, world, bbox) => {
    if (!p) return null;
    if (typeof p === "string") return p;
    const def = dom.getElementById(p.ref);
    if (!def) return null;
    const tag = def.tagName.toLowerCase();
    if (tag === "lineargradient" || tag === "radialgradient") {
      // xlink:href chains: inherit stops from the referenced gradient.
      if (!def.querySelector("stop")) {
        const href = def.getAttribute("href") || def.getAttribute("xlink:href");
        const parent = href && dom.getElementById(href.replace("#", ""));
        if (parent) for (const s of parent.querySelectorAll("stop")) def.appendChild(s.cloneNode(true));
      }
      const g = gradientFn(def, world, bbox, () => `grad_${++gradN}`, notes);
      if (!g) return null;
      items.push({ __raw: g.src });
      return { expr: `${g.name}(q)`, vec4: g.vec4 };
    }
    notes.add(`fill url(#${p.ref}) is not a gradient — ignored`);
    return null;
  };

  const clipFor = (ref, world) => {
    if (!ref) return null;
    const id = /^url\(\s*['"]?#([^)'"]+)['"]?\s*\)/.exec(ref);
    const def = id && dom.getElementById(id[1]);
    if (!def) return null;
    if (clips.has(id[1])) return clips.get(id[1]);
    const subs = [];
    for (const ch of def.children) {
      const s = shapeSubpaths(ch, styleOf(ch));
      if (s) subs.push(...s.subs);
    }
    if (!subs.length) return null;
    const name = `clip_${clips.size + 1}`;
    const { body } = polygonBody(subs, { winding: true, evenOdd: false });
    items.push({ __raw: `float ${name}(vec2 q) {\n${localise(mul(world, parseTransform(styleOf(def).transform)))}\n${body}\n}` });
    clips.set(id[1], name);
    return name;
  };

  /** Geometry of a shape element as subpaths in its own user units. */
  function shapeSubpaths(el, st) {
    const tag = el.tagName.toLowerCase();
    const rect = (x, y, w, h, rx, ry) => {
      if (!rx && !ry) return [{ pts: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], closed: true }];
      rx = Math.min(rx || ry, w / 2); ry = Math.min(ry || rx, h / 2);
      const pts = [], N = 8;
      const corner = (cx, cy, a0) => {
        for (let i = 0; i <= N; i++) {
          const a = a0 + (Math.PI / 2) * (i / N);
          pts.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
        }
      };
      corner(x + w - rx, y + ry, -Math.PI / 2);
      corner(x + w - rx, y + h - ry, 0);
      corner(x + rx, y + h - ry, Math.PI / 2);
      corner(x + rx, y + ry, Math.PI);
      return [{ pts, closed: true }];
    };
    if (tag === "rect") {
      return { subs: rect(len(st.x), len(st.y), len(st.width), len(st.height), len(st.rx, 0), len(st.ry, 0)), closed: true };
    }
    if (tag === "circle" || tag === "ellipse") {
      const cx = len(st.cx), cy = len(st.cy);
      const rx = tag === "circle" ? len(st.r) : len(st.rx);
      const ry = tag === "circle" ? len(st.r) : len(st.ry);
      const pts = [], N = Math.max(24, Math.ceil(Math.max(rx, ry)));
      for (let i = 0; i < N; i++) {
        const a = (2 * Math.PI * i) / N;
        pts.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
      }
      return { subs: [{ pts, closed: true }], closed: true, ellipse: { cx, cy, rx, ry } };
    }
    if (tag === "line") {
      return { subs: [{ pts: [[len(st.x1), len(st.y1)], [len(st.x2), len(st.y2)]], closed: false }], closed: false };
    }
    if (tag === "polyline" || tag === "polygon") {
      const nums = String(st.points || "").trim().split(/[\s,]+/).map(Number).filter(Number.isFinite);
      const pts = [];
      for (let i = 0; i + 1 < nums.length; i += 2) pts.push([nums[i], nums[i + 1]]);
      return pts.length > 1 ? { subs: [{ pts, closed: tag === "polygon" }], closed: tag === "polygon" } : null;
    }
    if (tag === "path" && st.d) {
      const subs = pathToSubpaths(st.d, opts.tolerance ?? 0.04);
      return subs.length ? { subs, closed: subs.some((s) => s.closed) } : null;
    }
    return null;
  }

  function visit(el, world, inheritOpacity, inherited) {
    const tag = (el.tagName || "").toLowerCase();
    if (tag === "defs" || tag === "clippath" || tag === "lineargradient"
        || tag === "radialgradient" || tag === "symbol" || tag === "style"
        || tag === "title" || tag === "desc" || tag === "metadata") return;

    const st = styleOf(el);
    if (st.display === "none" || st.visibility === "hidden") return;
    const world2 = mul(world, parseTransform(st.transform));
    const opacity = inheritOpacity * (st.opacity === undefined ? 1 : parseFloat(st.opacity));
    // Presentation attributes inherit; a child's own value wins.
    const inh = {
      fill: st.fill !== undefined ? st.fill : inherited.fill,
      stroke: st.stroke !== undefined ? st.stroke : inherited.stroke,
      "stroke-width": st["stroke-width"] !== undefined ? st["stroke-width"] : inherited["stroke-width"],
      "fill-rule": st["fill-rule"] !== undefined ? st["fill-rule"] : inherited["fill-rule"],
      "fill-opacity": st["fill-opacity"] !== undefined ? st["fill-opacity"] : inherited["fill-opacity"],
      "stroke-opacity": st["stroke-opacity"] !== undefined ? st["stroke-opacity"] : inherited["stroke-opacity"],
      "stroke-linecap": st["stroke-linecap"] !== undefined ? st["stroke-linecap"] : inherited["stroke-linecap"],
      "stroke-linejoin": st["stroke-linejoin"] !== undefined ? st["stroke-linejoin"] : inherited["stroke-linejoin"],
      "stroke-miterlimit": st["stroke-miterlimit"] !== undefined ? st["stroke-miterlimit"] : inherited["stroke-miterlimit"],
      "stroke-dasharray": st["stroke-dasharray"] !== undefined ? st["stroke-dasharray"] : inherited["stroke-dasharray"],
      "stroke-dashoffset": st["stroke-dashoffset"] !== undefined ? st["stroke-dashoffset"] : inherited["stroke-dashoffset"],
    };

    if (tag === "g" || tag === "svg" || tag === "a") {
      for (const ch of el.children) visit(ch, world2, opacity, inh);
      return;
    }
    if (tag === "use") {
      const href = el.getAttribute("href") || el.getAttribute("xlink:href") || "";
      const def = dom.getElementById(href.replace("#", ""));
      if (!def) return;
      const w3 = mul(world2, translate(len(st.x, 0), len(st.y, 0)));
      if (def.tagName.toLowerCase() === "symbol") {
        for (const ch of def.children) visit(ch, w3, opacity, inh);
      } else visit(def, w3, opacity, inh);
      return;
    }
    if (tag === "image") {
      const href = el.getAttribute("href") || el.getAttribute("xlink:href") || "";
      if (!href) return;
      if (!/^data:/.test(href)) notes.add("an <image> points at a file rather than embedding it — it will load only if that URL is reachable");
      const w = len(st.width), h = len(st.height);
      const u = `img_${++imgN}`;
      uniforms.push(`uniform sampler2D ${u};   // @${/^data:/.test(href) ? "data" : "asset"} ${href}`,
                    `uniform vec2 ${u}_size;`);
      const world3 = mul(world2, translate(len(st.x, 0), len(st.y, 0)));
      items.push({
        name: st.id || "image", comment: `<image> ${Math.round(w)}×${Math.round(h)}`,
        world: world3, opacity,
        body: `  return sdRR(lq, vec2(${num(w)}, ${num(h)}), 0.0);`,
        extra: `vec3 @ID@_pix(vec2 q) {
${localise(world3)}
  vec2 iu = lq / vec2(${num(w)}, ${num(h)});
  return ${u}_size.x > 0.5 ? texture2D(${u}, vec2(iu.x, 1.0 - iu.y)).rgb : vec3(0.5);
}`,
        fill: { expr: "@ID@_pix(q)" },
      });
      return;
    }
    if (tag === "text" || tag === "tspan") {
      const size = len(st["font-size"], 16);
      const content = (el.textContent || "").trim();
      if (!content) return;
      const anchor = st["text-anchor"] || "start";
      const x = len(st.x, 0), y = len(st.y, 0);
      const est = Math.max(size * 0.4, [...content].length * size * 0.52);
      const item = {
        name: st.id || "text", comment: `text "${content.slice(0, 28).replace(/"/g, "'")}"`,
        world: world2, opacity,
        fill: resolvePaint(paint(inh.fill, "#000000"), world2, { x, y: y - size, w: est, h: size }) || "#000000",
        __text: {
          run: { text: content, family: st["font-family"] || "system-ui, sans-serif",
                 weight: st["font-weight"] || 400,
                 style: st["font-style"] || "normal" },
          // SVG places text by its baseline, and text-anchor shifts it by the
          // measured width — which the atlas layout knows, so boxWidth is zero
          // and the alignment does the work.
          opts: { size, lineHeight: 1, letterSpacing: len(st["letter-spacing"], 0),
                  align: anchor === "middle" ? "center" : anchor === "end" ? "right" : "left",
                  boxWidth: 0, firstBaseline: 0 },
          anchorAt: [x, y], est,
        },
      };
      items.push(item);
      texts.push(item);
      return;
    }

    const geo = shapeSubpaths(el, st);
    if (!geo) return;

    const fillPaint = paint(inh.fill, "#000000");
    const strokePaint = paint(inh.stroke, null);
    const strokeW = len(inh["stroke-width"], 1) * (strokePaint ? 1 : 0);
    const hasFill = !!fillPaint && geo.closed !== false;
    if (!hasFill && !strokePaint) return;

    const bbox = bboxOf(geo.subs);
    let body, edges = 0, bakedStroke = false, openStroke = false;

    // Dashes are resolved by arc length before anything is emitted, so each
    // dash arrives as its own polyline with its own caps — and a dashed circle
    // stops being a circle, which is why this comes before the shape choice.
    let subs = geo.subs, dashed = false;
    const dashSpec = String(inh["stroke-dasharray"] || "none").trim();
    if (strokePaint && dashSpec && dashSpec !== "none") {
      const pattern = dashSpec.split(/[\s,]+/).map((v) => len(v, 0)).filter((v) => v >= 0);
      if (pattern.some((v) => v > 0)) {
        subs = dashPolylines(subs, pattern, len(inh["stroke-dashoffset"], 0));
        dashed = true;
        if (!subs.length) return;                         // dashed into nothing
        if (subs.length > 700) notes.add("a dash pattern was cut short at 800 pieces");
      }
    }

    // A circle or ellipse has an exact distance; using it instead of a polygon
    // keeps the file small and the edge perfect at any zoom. Its stroke is a
    // band around that distance, so it is never an "open" stroke — treating it
    // as one drew a filled disc, because the inside is where d is most negative.
    if (geo.ellipse && !dashed && Math.abs(geo.ellipse.rx - geo.ellipse.ry) < 1e-6) {
      body = `  return length(lq - vec2(${num(geo.ellipse.cx)}, ${num(geo.ellipse.cy)})) - ${num(geo.ellipse.rx)};`;
    } else if (geo.ellipse && !dashed) {
      body = `  return sdEllipse(lq - vec2(${num(geo.ellipse.cx)}, ${num(geo.ellipse.cy)}), vec2(${num(geo.ellipse.rx)}, ${num(geo.ellipse.ry)}));`;
    } else if (!hasFill && strokePaint) {
      const cap = String(inh["stroke-linecap"] || "butt").toLowerCase();
      const join = String(inh["stroke-linejoin"] || "miter").toLowerCase();
      const miterLimit = parseFloat(inh["stroke-miterlimit"] ?? "4") || 4;
      const r = openStrokeBody(subs, { cap, halfWidth: strokeW / 2, join, miterLimit });
      body = r.body; edges = r.edges; bakedStroke = !!r.baked; openStroke = true;
      edgeTotal += edges;
    } else {
      const r = polygonBody(geo.subs, {
        winding: hasFill,
        evenOdd: (inh["fill-rule"] || "nonzero") === "evenodd",
      });
      body = r.body; edges = r.edges;
      edgeTotal += edges;
      if (edgeTotal > EDGE_CAP) { truncated++; return; }
    }

    const fillOp = parseFloat(inh["fill-opacity"] ?? "1");
    const strokeOp = parseFloat(inh["stroke-opacity"] ?? "1");
    if (fillOp < 1 || strokeOp < 1) notes.add("fill-opacity / stroke-opacity fold into the shape's opacity");

    items.push({
      name: st.id || tag, comment: `<${tag}>${edges ? ` ${edges} edges` : ""}`,
      world: world2,
      opacity: opacity * (hasFill ? fillOp : strokeOp),
      body,
      fill: hasFill ? resolvePaint(fillPaint, world2, bbox) : null,
      stroke: strokePaint ? resolvePaint(strokePaint, world2, bbox) : null,
      strokeWidth: strokeW,
      open: openStroke,
      baked: bakedStroke,
      clip: clipFor(st["clip-path"], world2),
    });
  }

  visit(root, rootM, 1, { fill: undefined, stroke: undefined, "stroke-width": undefined });

  // One atlas for every text element in the file.
  const preFuncs = [];
  if (texts.length) {
    const atlas = opts.text === "greek" ? null : await buildAtlas(texts.map((t) => t.__text.run));
    if (atlas) {
      uniforms.push(`uniform sampler2D u_font;   // @hidden the glyph atlas @data ${atlas.dataUrl}`);
      preFuncs.push(GLYPH_HELPER);
      for (const it of texts) {
        const t = it.__text;
        // Shift the whole run so the pen starts at the SVG anchor point.
        it.world = mul(it.world, translate(t.anchorAt[0], t.anchorAt[1]));
        const r = emitTextRun(atlas, t.run, t.opts);
        if (r) { it.body = r.body; it.comment += ` — ${r.glyphs} glyphs`; }
        else greekSvg(it);
      }
    } else {
      for (const it of texts) greekSvg(it);
      notes.add("no glyph atlas could be built — text is greeked as bars");
    }
    for (const it of texts) delete it.__text;
  }

  function greekSvg(it) {
    const t = it.__text, o = t.opts;
    const wid = t.est;
    const dx = o.align === "center" ? -wid / 2 : o.align === "right" ? -wid : 0;
    it.world = mul(it.world, translate(t.anchorAt[0], t.anchorAt[1]));
    it.body = `  return sdRR(lq - vec2(${num(dx)}, ${num(-o.size * 0.72)}), vec2(${num(wid)}, ${num(o.size * 0.72)}), ${num(o.size * 0.2)});`;
    notes.add(`text "${t.run.text.slice(0, 24)}" is greeked as a bar`);
  }

  if (truncated) notes.add(`${truncated} shape${truncated === 1 ? " was" : "s were"} dropped past the ${EDGE_CAP}-edge budget`);
  if (!items.filter((i) => !i.__raw).length) throw new Error("nothing drawable was found in that file");

  // Raw entries (gradient and clip functions) are emitted verbatim ahead of
  // the shapes that use them.
  const raw = items.filter((i) => i.__raw).map((i) => i.__raw);
  const shapes = items.filter((i) => !i.__raw);
  const source = emitSketch(shapes, {
    width: W, height: H, title: `Compiled from ${opts.name || "an SVG file"}`,
    background: opts.background === undefined ? "#ffffff" : opts.background,
    uniforms,
    preFuncs: [...preFuncs, ...raw],
  });
  return { source, width: W, height: H, shapes: shapes.length, notes: [...notes], edges: edgeTotal };
}
