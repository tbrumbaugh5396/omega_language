// The shared half of the shape compiler: geometry, and the emitter.
//
// Two front-ends feed this — the Design studio's document model
// (design-to-sdf.js) and an SVG file (svg-to-sdf.js) — and both produce the
// same intermediate: a painter's-order list of items, each a signed-distance
// function of the frame's pixels plus how to paint it. Keeping the emitter in
// one place is the point; two emitters would drift within a month.
//
// Conventions that hold throughout: q is in output pixels with y down, as SVG
// has it. Each item's own function localises q by the inverse of its world
// transform, so shapes are written in their natural coordinates.

export const num = (v, d = 2) => {
  const n = Number.isFinite(+v) ? +v : 0;
  const s = n.toFixed(d).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return /[.eE]/.test(s) ? s : s + ".0";
};

export const hex = (c, fallback = "#000000") => {
  const s = String(c ?? "").trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(s)) return s;
  if (/^#[0-9a-f]{3}$/.test(s)) return "#" + [...s.slice(1)].map((ch) => ch + ch).join("");
  return fallback;
};

export const ident = (s) => String(s || "shape")
  .replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24) || "shape";

// ------------------------------------------------------------------ matrices
// [a, b, c, d, e, f]: x' = a x + c y + e ; y' = b x + d y + f

export const I = [1, 0, 0, 1, 0, 0];
export const mul = (m, n) => [
  m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
];
export const translate = (x, y) => [1, 0, 0, 1, x, y];
export const scaleM = (x, y = x) => [x, 0, 0, y, 0, 0];
export const rotateAbout = (deg, cx = 0, cy = 0) => {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r);
  return mul(mul(translate(cx, cy), [c, s, -s, c, 0, 0]), translate(-cx, -cy));
};
export const invert = (m) => {
  const det = m[0] * m[3] - m[1] * m[2] || 1e-9;
  const a = m[3] / det, b = -m[1] / det, c = -m[2] / det, d = m[0] / det;
  return [a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5])];
};
export const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
const isTranslate = (m) => Math.abs(m[0] - 1) < 1e-9 && Math.abs(m[3] - 1) < 1e-9
                        && Math.abs(m[1]) < 1e-9 && Math.abs(m[2]) < 1e-9;
/** How much this transform scales lengths — for stroke widths and tolerances. */
export const meanScale = (m) => (Math.hypot(m[0], m[1]) + Math.hypot(m[2], m[3])) / 2;

/** `vec2 lq = …;` mapping q into the item's own coordinates. */
export function localise(world, varName = "lq") {
  const inv = invert(world);
  if (isTranslate(inv)) {
    return `  vec2 ${varName} = q - vec2(${num(-inv[4])}, ${num(-inv[5])});`;
  }
  return `  vec2 ${varName} = xf(q, ${inv.map((v) => num(v, 6)).join(", ")});`;
}

// ------------------------------------------------------------------ polygons

/**
 * Unrolled edge list for a set of subpaths. GLSL ES 1.00 has no array
 * constructors and no dynamic indexing worth relying on, so the geometry
 * becomes straight-line code: one statement per edge. `winding` adds the
 * crossing test that gives a closed path its inside.
 */
export function emitEdges(subpaths, { winding }) {
  const out = [];
  let edges = 0;
  for (const sp of subpaths) {
    const pts = sp.pts;
    if (pts.length < 2) continue;
    out.push(`  a = vec2(${num(pts[0][0], 3)}, ${num(pts[0][1], 3)});`);
    const seq = pts.slice(1);
    // A filled path is closed whether or not it said Z; a stroked open path
    // is not, and closing it would draw a line that is not there.
    if ((sp.closed || winding) && (pts[0][0] !== pts[pts.length - 1][0]
                                || pts[0][1] !== pts[pts.length - 1][1])) {
      seq.push(pts[0]);
    }
    for (const p of seq) {
      out.push(`  b = vec2(${num(p[0], 3)}, ${num(p[1], 3)}); d = min(d, sdSegment(lq, a, b));`
             + (winding ? ` w += cr(lq, a, b);` : "") + ` a = b;`);
      edges++;
    }
  }
  return { lines: out.join("\n"), edges };
}

/**
 * An open stroked path. Each subpath is capped on its own, because SVG's
 * default linecap is butt and a capsule chain gives round — a difference of
 * half the stroke width at every free end. The cap is a half-space cut
 * perpendicular to the end tangent; `square` pushes that cut out by half the
 * width, which is why it needs the literal width rather than the live knob.
 */
/**
 * Cut polylines into their dashes, by arc length.
 *
 * A dash pattern is a property of distance along the path, which nothing in a
 * distance field knows about — so it is resolved here, at compile time, and
 * each dash becomes its own open polyline with its own caps. An odd-length
 * pattern repeats to even, as SVG says.
 */
export function dashPolylines(subpaths, pattern, offset = 0, maxPieces = 800) {
  const pat = pattern.filter((v) => Number.isFinite(v) && v >= 0);
  if (!pat.length) return subpaths;
  const dashes = pat.length % 2 ? pat.concat(pat) : pat;
  const period = dashes.reduce((a, b) => a + b, 0);
  if (period <= 0) return subpaths;

  const out = [];
  for (const sp of subpaths) {
    const pts = sp.closed && (sp.pts[0][0] !== sp.pts[sp.pts.length - 1][0]
                           || sp.pts[0][1] !== sp.pts[sp.pts.length - 1][1])
      ? sp.pts.concat([sp.pts[0]]) : sp.pts;
    // Where in the pattern the path starts, and whether that phase is drawn.
    // stroke-dashoffset is the distance *into* the pattern to begin at, so it
    // advances the phase rather than retarding it.
    let rem = ((offset % period) + period) % period;
    let idx = 0;
    while (rem >= dashes[idx]) { rem -= dashes[idx]; idx = (idx + 1) % dashes.length; }
    let left = dashes[idx] - rem;
    let on = idx % 2 === 0;
    let cur = on ? [pts[0]] : null;

    for (let i = 0; i + 1 < pts.length; i++) {
      let [ax, ay] = pts[i];
      const [bx, by] = pts[i + 1];
      let segLeft = Math.hypot(bx - ax, by - ay);
      while (segLeft > 1e-9) {
        const step = Math.min(segLeft, left);
        const t = step / segLeft;
        const nx = ax + (bx - ax) * t, ny = ay + (by - ay) * t;
        if (on) cur.push([nx, ny]);
        segLeft -= step;
        left -= step;
        ax = nx; ay = ny;
        if (left <= 1e-9) {                       // this dash or gap ends here
          if (on && cur && cur.length > 1) out.push({ pts: cur, closed: false });
          idx = (idx + 1) % dashes.length;
          left = dashes[idx];
          on = !on;
          cur = on ? [[ax, ay]] : null;
          if (out.length > maxPieces) return out;
        }
      }
    }
    if (on && cur && cur.length > 1) out.push({ pts: cur, closed: false });
  }
  return out;
}

/** Unit direction from one point to another. */
const unit = (from, to) => {
  const dx = to[0] - from[0], dy = to[1] - from[1];
  const l = Math.hypot(dx, dy) || 1;
  return [dx / l, dy / l];
};

/**
 * The patch that turns a round join into a mitre or a bevel: the wedge on the
 * outside of the turn, bounded by each segment's own offset line. Those two
 * lines meet at the mitre tip, so for a mitre no further limit is needed; a
 * bevel simply cuts the wedge off at the chord.
 *
 * Returned in *outline* terms — the half-width is already in it — because a
 * join has no centreline to be a distance from.
 */
function joinPatch(v, e1, e2, hw, join, miterLimit) {
  const cross = e1[0] * e2[1] - e1[1] * e2[0];
  const dot = e1[0] * e2[0] + e1[1] * e2[1];
  // Below about 12° there is no corner to speak of — the two round caps of the
  // capsules already meet cleanly. This matters most on a flattened curve,
  // where every vertex is a shallow turn: a mitre wedge at each of fifty
  // vertices bulges outward along what should be a smooth line, and the
  // browser draws no such thing.
  if (Math.abs(cross) < 1e-6 || dot > 0.978) return null;
  const s = cross > 0 ? -1 : 1;                        // the outside of the turn
  const perp = (d) => [-d[1] * s, d[0] * s];
  const n1 = perp(e1), n2 = perp(e2);
  let mx = n1[0] + n2[0], my = n1[1] + n2[1];
  const ml = Math.hypot(mx, my);
  if (ml < 1e-6) return null;                          // a full reversal
  mx /= ml; my /= ml;
  const cosHalf = n1[0] * mx + n1[1] * my;
  if (cosHalf < 1e-4) return null;
  const bevel = join === "bevel" || 1 / cosHalf > miterLimit;
  const V = `vec2(${num(v[0], 3)}, ${num(v[1], 3)})`;
  const terms = [
    `dot(jv, vec2(${num(n1[0], 4)}, ${num(n1[1], 4)})) - ${num(hw, 3)}`,
    `dot(jv, vec2(${num(n2[0], 4)}, ${num(n2[1], 4)})) - ${num(hw, 3)}`,
    `-dot(jv, vec2(${num(mx, 4)}, ${num(my, 4)}))`,
  ];
  if (bevel) terms.push(`dot(jv, vec2(${num(mx, 4)}, ${num(my, 4)})) - ${num(hw * cosHalf, 3)}`);
  const expr = terms.reduce((acc, t) => (acc ? `max(${acc}, ${t})` : t), "");
  return `  { vec2 jv = lq - ${V}; ds = min(ds, ${expr}); }`;
}

/** A closed subpath needs its last segment back: the point list names each
    corner once, so the run from the final corner to the first is implied. */
const closeRing = (sp) => {
  const p = sp.pts;
  if (!sp.closed || p.length < 3) return sp;
  const same = Math.abs(p[0][0] - p[p.length - 1][0]) < 1e-9
            && Math.abs(p[0][1] - p[p.length - 1][1]) < 1e-9;
  return same ? sp : { ...sp, pts: p.concat([p[0]]) };
};

export function openStrokeBody(subpaths, { cap = "butt", halfWidth = 0,
                                           join = "round", miterLimit = 4 }) {
  subpaths = subpaths.map(closeRing);
  if (join !== "round") return bakedStrokeBody(subpaths, { cap, halfWidth, join, miterLimit });
  const blocks = [];
  let edges = 0;
  for (const sp of subpaths) {
    const pts = sp.pts;
    if (pts.length < 2) continue;
    const lines = [`  { float ds = 1e5;`, `  a = vec2(${num(pts[0][0], 3)}, ${num(pts[0][1], 3)});`];
    for (const p of pts.slice(1)) {
      lines.push(`  b = vec2(${num(p[0], 3)}, ${num(p[1], 3)}); ds = min(ds, sdSegment(lq, a, b)); a = b;`);
      edges++;
    }
    if (cap !== "round" && !sp.closed) {
      // This function returns a centreline distance; the paint step subtracts
      // half the stroke width from it. So the cut plane is raised by that same
      // half-width, and the subtraction lands it exactly on the end point —
      // which is butt. A square cap wants it half a width further out, so it
      // is raised by nothing at all.
      const lift = cap === "square" ? 0 : halfWidth;
      const dir = (from, to) => {
        const dx = to[0] - from[0], dy = to[1] - from[1];
        const l = Math.hypot(dx, dy) || 1;
        return [dx / l, dy / l];
      };
      const d0 = dir(pts[0], pts[1]);
      const dN = dir(pts[pts.length - 2], pts[pts.length - 1]);
      const add = lift ? ` + ${num(lift, 3)}` : "";
      lines.push(`  ds = max(ds, -dot(lq - vec2(${num(pts[0][0], 3)}, ${num(pts[0][1], 3)}), vec2(${num(d0[0], 4)}, ${num(d0[1], 4)}))${add});`,
                 `  ds = max(ds, dot(lq - vec2(${num(pts[pts.length - 1][0], 3)}, ${num(pts[pts.length - 1][1], 3)}), vec2(${num(dN[0], 4)}, ${num(dN[1], 4)}))${add});`);
    }
    lines.push(`  d = min(d, ds); }`);
    blocks.push(lines.join("\n"));
  }
  return {
    body: `  float d = 1e5;\n  vec2 a = vec2(0.0), b = vec2(0.0);\n${blocks.join("\n")}\n  return d;`,
    edges,
  };
}

/**
 * A stroke whose width is baked in, returning the distance to its outline
 * rather than to its centreline. Mitre and bevel joins need this: the wedge
 * they add is a region, not an offset of a line.
 */
function bakedStrokeBody(subpaths, { cap, halfWidth: hw, join, miterLimit }) {
  subpaths = subpaths.map(closeRing);
  const blocks = [];
  let edges = 0, joins = 0;
  for (const sp of subpaths) {
    const pts = sp.pts;
    if (pts.length < 2) continue;
    const lines = [`  { float ds = 1e5;`, `  a = vec2(${num(pts[0][0], 3)}, ${num(pts[0][1], 3)});`];
    for (const p of pts.slice(1)) {
      lines.push(`  b = vec2(${num(p[0], 3)}, ${num(p[1], 3)}); ds = min(ds, sdSegment(lq, a, b) - ${num(hw, 3)}); a = b;`);
      edges++;
    }
    const closed = sp.closed
      && Math.abs(pts[0][0] - pts[pts.length - 1][0]) < 1e-6
      && Math.abs(pts[0][1] - pts[pts.length - 1][1]) < 1e-6;
    const last = pts.length - 1;
    for (let i = 1; i < last; i++) {
      const patch = joinPatch(pts[i], unit(pts[i - 1], pts[i]), unit(pts[i], pts[i + 1]), hw, join, miterLimit);
      if (patch) { lines.push(patch); joins++; }
    }
    if (closed && pts.length > 2) {
      // The seam is a join like any other.
      const patch = joinPatch(pts[0], unit(pts[last - 1], pts[last]), unit(pts[0], pts[1]), hw, join, miterLimit);
      if (patch) { lines.push(patch); joins++; }
    } else if (cap !== "round") {
      // Baked, so the cut lands on the end point with no half-width to add;
      // a square cap pushes it out by one.
      const push = cap === "square" ? ` - ${num(hw, 3)}` : "";
      const d0 = unit(pts[0], pts[1]), dN = unit(pts[last - 1], pts[last]);
      lines.push(`  ds = max(ds, -dot(lq - vec2(${num(pts[0][0], 3)}, ${num(pts[0][1], 3)}), vec2(${num(d0[0], 4)}, ${num(d0[1], 4)}))${push});`,
                 `  ds = max(ds, dot(lq - vec2(${num(pts[last][0], 3)}, ${num(pts[last][1], 3)}), vec2(${num(dN[0], 4)}, ${num(dN[1], 4)}))${push});`);
    }
    lines.push(`  d = min(d, ds); }`);
    blocks.push(lines.join("\n"));
  }
  return {
    body: `  float d = 1e5;\n  vec2 a = vec2(0.0), b = vec2(0.0);\n${blocks.join("\n")}\n  return d;`,
    edges, joins, baked: true,
  };
}

/** The body of a shape function built from subpaths. */
export function polygonBody(subpaths, { winding, evenOdd }) {
  const { lines, edges } = emitEdges(subpaths, { winding });
  const head = `  float d = 1e5;\n  vec2 a = vec2(0.0), b = vec2(0.0);`
             + (winding ? `\n  float w = 0.0;` : "");
  // Signed crossings and unsigned counts share a parity, so one accumulator
  // serves both rules: nonzero asks whether it is not zero, even-odd asks
  // whether it is odd.
  const tail = winding
    ? `\n  return ${evenOdd ? "mod(abs(w), 2.0) > 0.5" : "abs(w) > 0.5"} ? -d : d;`
    : `\n  return d;`;
  return { body: `${head}\n${lines}${tail}`, edges };
}

// ------------------------------------------------------------------ emitter

const PRELUDE_FUNCS = `vec2 xf(vec2 q, float a, float b, float c, float d, float e, float f) {
  return vec2(a * q.x + c * q.y + e, b * q.x + d * q.y + f);
}
float sdRR(vec2 q, vec2 size, float r) {           // rect with corner radius, top-left origin
  vec2 h = size * 0.5;
  r = min(r, min(h.x, h.y));
  return sdBox(q - h, h - r) - r;
}
float cr(vec2 p, vec2 a, vec2 b) {                 // signed ray crossing, for winding
  if ((a.y > p.y) == (b.y > p.y)) return 0.0;
  float x = a.x + (p.y - a.y) / (b.y - a.y) * (b.x - a.x);
  return x <= p.x ? 0.0 : (b.y > a.y ? 1.0 : -1.0);
}
float cov(float d, float px) { return smoothstep(0.75 * px, -0.75 * px, d); }`;

/**
 * items → a Generate sketch.
 *
 * item = {
 *   name, comment, world,
 *   body,         // GLSL: given `vec2 lq`, returns a float distance
 *   extra,        // functions emitted alongside (gradients, image samplers)
 *   fill,         // null | "#rrggbb" | { expr: "g_1(q)" }
 *   stroke, strokeWidth,
 *   opacity, blend ("normal" | "multiply" | "screen"),
 *   open,         // stroked centreline rather than a closed outline
 *   clip,         // optional name of a clip function: coverage is intersected
 * }
 */
export function emitSketch(items, opts = {}) {
  const W = Math.max(1, Math.round(opts.width || 1));
  const H = Math.max(1, Math.round(opts.height || 1));
  const funcs = [], paint = [];
  const used = new Set();

  for (const it of items) {
    let base = "s_" + ident(it.name);
    let id = base, k = 2;
    while (used.has(id)) id = `${base}_${k++}`;
    used.add(id);
    it.id = id;

    if (it.extra) funcs.push(it.extra.replace(/@ID@/g, id));
    funcs.push(`float ${id}(vec2 q) {${it.comment ? "   // " + it.comment : ""}
${localise(it.world || I)}
${it.body}
}`);

    const op = num(it.opacity ?? 1, 3);
    const sub = (v) => (typeof v === "string" ? v : v && v.expr ? v.expr : v);
    const fillExpr = it.fill ? String(sub(it.fill)).replace(/@ID@/g, id) : null;
    const strokeExpr = it.stroke ? String(sub(it.stroke)).replace(/@ID@/g, id) : null;
    // A translucent gradient answers in vec4; its alpha belongs in the
    // coverage, not the colour, so it is pulled out into a local first.
    const fill4 = !!(it.fill && it.fill.vec4), stroke4 = !!(it.stroke && it.stroke.vec4);
    const put = (colour, cover) => {
      const c = it.blend === "multiply" ? `col * (${colour})`
              : it.blend === "screen" ? `1.0 - (1.0 - col) * (1.0 - (${colour}))`
              : colour;
      return `col = mix(col, ${c}, ${cover});`;
    };
    const clipMul = it.clip ? ` * cov(${it.clip}(q), px)` : "";
    const lines = [];
    if (it.open && it.baked) {
      // The width is already in the distance, so this paints like any filled
      // shape; inflate still offsets the outline and outline still thickens it.
      lines.push(`{ float d = ${id}(q) - inflate - outline * 0.5;`);
      if (stroke4) {
        lines.push(`  vec4 sc = ${strokeExpr};`,
          `  ${put("sc.rgb", `cov(d, px) * ${op} * sc.a${clipMul}`)} }`);
      } else {
        lines.push(`  ${put(strokeExpr || "vec3(0.0)", `cov(d, px) * ${op}${clipMul}`)} }`);
      }
    } else if (it.open) {
      lines.push(`{ float d = ${id}(q);`,
        `  float sw = max(${num(it.strokeWidth || 1)}, outline) + inflate * 2.0;`);
      if (stroke4) {
        lines.push(`  vec4 sc = ${strokeExpr};`,
          `  ${put("sc.rgb", `cov(d - sw * 0.5, px) * ${op} * sc.a${clipMul}`)} }`);
      } else {
        lines.push(`  ${put(strokeExpr || "vec3(0.0)", `cov(d - sw * 0.5, px) * ${op}${clipMul}`)} }`);
      }
    } else {
      lines.push(`{ float d = ${id}(q) - inflate;`);
      if (fillExpr && fill4) {
        lines.push(`  vec4 fc = ${fillExpr};`,
          `  ${put("fc.rgb", `cov(d, px) * ${op} * fc.a${clipMul}`)}`);
      } else if (fillExpr) {
        lines.push(`  ${put(fillExpr, `cov(d, px) * ${op}${clipMul}`)}`);
      }
      const sw = it.strokeWidth || 0;
      if (sw > 0 || strokeExpr) {
        lines.push(`  float sw = max(${num(sw)}, outline);`);
        if (strokeExpr && stroke4) {
          lines.push(`  vec4 sc = ${strokeExpr};`,
            `  if (sw > 0.0) ${put("sc.rgb", `cov(abs(d) - sw * 0.5, px) * ${op} * sc.a${clipMul}`)} }`);
        } else {
          lines.push(`  if (sw > 0.0) ${put(strokeExpr || "vec3(0.0)", `cov(abs(d) - sw * 0.5, px) * ${op}${clipMul}`)} }`);
        }
      } else {
        lines.push(`  if (outline > 0.0) ${put("vec3(0.12)", `cov(abs(d) - outline * 0.5, px) * ${op}${clipMul}`)} }`);
      }
    }
    paint.push(lines.join("\n"));
  }

  const bg = opts.background === null ? null : hex(opts.background, "#ffffff");
  return `// ${opts.title || "Compiled shapes"} — ${items.length} shape${items.length === 1 ? "" : "s"}, ${W}×${H}.
// Every shape is a function of q, in frame pixels with y down like SVG. Edit
// anything: it is yours. inflate, outline and wobble start at zero, so this
// draws what the source draws; move them and it draws what SVG cannot.
uniform float inflate;   // @range -24 24 @default 0 — offset every edge (px)
uniform float outline;   // @range 0 12 @default 0 — stroke every shape (px)
uniform float wobble;    // @range 0 40 @default 0 — displace every edge with noise (px)
${(opts.uniforms || []).join("\n")}${(opts.uniforms || []).length ? "\n" : ""}
const vec2 FRAME = vec2(${num(W)}, ${num(H)});

${PRELUDE_FUNCS}

${(opts.preFuncs || []).join("\n")}${(opts.preFuncs || []).length ? "\n" : ""}
// ---- shapes, in painter's order
${funcs.join("\n")}

vec2 q = vec2(uv.x, 1.0 - uv.y) * FRAME;            // frame pixels, y down
float px = FRAME.y / u_resolution.y;                 // one screen pixel, in frame units
if (wobble > 0.0) q += (vec2(fbm(q * 0.02 + t * 0.15), fbm(q * 0.02 + 7.3)) - 0.5) * wobble;
vec3 col = ${bg || "vec3(1.0)"};
${paint.join("\n")}

clamp(col, 0.0, 1.0)`;
}

/** A preview size that keeps the aspect inside a box, even and at least 2px. */
export function fitPreview(w, h, box = 960) {
  const s = Math.min(1, box / Math.max(w, h));
  return [Math.max(2, Math.round((w * s) / 2) * 2), Math.max(2, Math.round((h * s) / 2) * 2)];
}
