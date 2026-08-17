// A design frame → a Generate sketch.
//
// The Design studio's document is already structure — rects, ellipses, lines,
// text blocks, images, in a tree with transforms — so nothing has to be
// recovered from pixels; it only has to be translated. Every shape becomes a
// signed-distance function of q (frame pixels, y down, like SVG); fills and
// strokes become coverage; painter's order becomes a mix chain. What comes
// out draws what the design draws, and then does what SVG cannot: three
// controls — inflate, outline, wobble — start at zero and act on every edge.
//
// Text is the honest exception. Glyphs need an SDF atlas (roadmap, Phase 5);
// until then a text block is greeked as bars, one per line, at its own
// colour and metrics, and the source says so where it happens.

const num = (v, d = 1) => {
  const n = Number(v) || 0;
  const s = n.toFixed(d).replace(/\.?0+$/, "");
  return /\./.test(s) ? s : s + ".0";
};
const hex = (c, fallback = "#000000") => {
  const s = String(c || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(s) ? s.toLowerCase()
       : /^#[0-9a-fA-F]{3}$/.test(s) ? "#" + [...s.slice(1)].map((ch) => ch + ch).join("").toLowerCase()
       : fallback;
};
const ident = (s) => String(s || "shape").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24) || "shape";

/** 2D affine as [a, b, c, d, e, f]: x' = a x + c y + e ; y' = b x + d y + f. */
const I = [1, 0, 0, 1, 0, 0];
const mul = (m, n) => [
  m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
];
const translate = (x, y) => [1, 0, 0, 1, x, y];
const rotateAbout = (deg, cx, cy) => {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r);
  return mul(mul(translate(cx, cy), [c, s, -s, c, 0, 0]), translate(-cx, -cy));
};
const invert = (m) => {
  const det = m[0] * m[3] - m[1] * m[2] || 1e-9;
  const a = m[3] / det, b = -m[1] / det, c = -m[2] / det, d = m[0] / det;
  return [a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5])];
};
const isTranslate = (m) => Math.abs(m[0] - 1) < 1e-9 && Math.abs(m[3] - 1) < 1e-9
                        && Math.abs(m[1]) < 1e-9 && Math.abs(m[2]) < 1e-9;

/**
 * Compile one frame (and everything inside it) to a sketch.
 * @returns { source, width, height, shapes, images, notes }
 */
export function compileDesignFrame(frame, opts = {}) {
  const W = Math.max(1, Math.round(frame.w)), H = Math.max(1, Math.round(frame.h));
  const funcs = [];        // GLSL function definitions, one per shape
  const paint = [];        // statements in painter's order
  const uniforms = [];     // image samplers
  const notes = [];
  let count = 0, imgCount = 0;
  const used = new Set();

  // Prefixed, so a node called "frame" or "noise" cannot collide with the
  // sketch's own globals and helpers, or with a GLSL keyword.
  const name = (n) => {
    let base = "s_" + ident(n.name || n.type);
    let s = base, k = 2;
    while (used.has(s)) s = `${base}_${k++}`;
    used.add(s);
    return s;
  };

  /** Emit `vec2 lq = …;` mapping frame pixels to the node's local top-left. */
  const localise = (world) => {
    const inv = invert(world);
    if (isTranslate(inv)) return `  vec2 lq = q - vec2(${num(-inv[4], 2)}, ${num(-inv[5], 2)});`;
    return `  vec2 lq = xf(q, ${inv.map((v) => num(v, 5)).join(", ")});`;
  };

  function visit(node, parentWorld, parentOpacity, depth) {
    if (node.visible === false) return;
    const local = mul(translate(node.x || 0, node.y || 0),
                      node.rotation ? rotateAbout(node.rotation, node.w / 2, node.h / 2) : I);
    // The frame we are compiling is the origin: its own position is ignored,
    // exactly as the SVG export does.
    const world = depth === 0 ? (node.rotation ? rotateAbout(node.rotation, node.w / 2, node.h / 2) : I)
                              : mul(parentWorld, local);
    const opacity = (parentOpacity) * (node.opacity ?? 1);
    const op = num(opacity, 3);
    const w = num(node.w, 2), h = num(node.h, 2);
    const blend = node.blend === "multiply" ? "multiply" : node.blend === "screen" ? "screen" : "normal";
    const put = (colourExpr, covExpr) => {
      if (blend === "normal") return `col = mix(col, ${colourExpr}, ${covExpr});`;
      const fn = blend === "multiply" ? "col * (${c})" : "1.0 - (1.0 - col) * (1.0 - (${c}))";
      return `col = mix(col, ${fn.replace("${c}", colourExpr)}, ${covExpr});`;
    };
    const strokeOf = (n, dflt) => ({ col: hex(n.stroke, dflt), w: Number(n.strokeWidth) || 0 });

    if (node.type === "frame" || node.type === "rect") {
      const id = `${name(node)}`;
      const r = num(node.radius || 0, 2);
      funcs.push(`float ${id}(vec2 q) {   // ${node.type} "${node.name || ""}" ${Math.round(node.w)}×${Math.round(node.h)}
${localise(world)}
  return sdRR(lq, vec2(${w}, ${h}), ${r});
}`);
      count++;
      const fill = node.type === "frame" ? hex(node.fill, "#ffffff") : (node.fill && node.fill !== "none" ? hex(node.fill) : null);
      const st = strokeOf(node, "#202020");
      const lines = [`{ float d = ${id}(q) - inflate;`];
      if (fill) lines.push(`  ${put(fill, `cov(d, px) * ${op}`)}`);
      lines.push(`  float sw = max(${num(st.w, 2)}, outline);`,
                 `  if (sw > 0.0) ${put(st.col, `cov(abs(d) - sw * 0.5, px) * ${op}`)} }`);
      paint.push(lines.join("\n"));
    } else if (node.type === "ellipse") {
      const id = name(node);
      funcs.push(`float ${id}(vec2 q) {   // ellipse "${node.name || ""}"
${localise(world)}
  return sdEllipse(lq - vec2(${w}, ${h}) * 0.5, vec2(${w}, ${h}) * 0.5);
}`);
      count++;
      const fill = node.fill && node.fill !== "none" ? hex(node.fill) : null;
      const st = strokeOf(node, "#202020");
      const lines = [`{ float d = ${id}(q) - inflate;`];
      if (fill) lines.push(`  ${put(fill, `cov(d, px) * ${op}`)}`);
      lines.push(`  float sw = max(${num(st.w, 2)}, outline);`,
                 `  if (sw > 0.0) ${put(st.col, `cov(abs(d) - sw * 0.5, px) * ${op}`)} }`);
      paint.push(lines.join("\n"));
    } else if (node.type === "line") {
      const id = name(node);
      funcs.push(`float ${id}(vec2 q) {   // line "${node.name || ""}"
${localise(world)}
  return sdSegment(lq, vec2(0.0), vec2(${w}, ${h}));
}`);
      count++;
      const st = strokeOf(node, "#000000");
      paint.push(`{ float d = ${id}(q);
  float sw = max(${num(st.w || 2, 2)}, outline) + inflate * 2.0;
  ${put(st.col, `cov(d - sw * 0.5, px) * ${op}`)} }`);
    } else if (node.type === "text") {
      // Greeked: one bar per line at the text's colour and metrics.
      const id = name(node);
      const size = Number(node.fontSize) || 32;
      const lh = (Number(node.lineHeight) || 1.3) * size;
      const lines = String(node.text ?? "Text").split("\n");
      const bars = lines.map((line, i) => {
        const wid = Math.min(node.w, Math.max(size * 0.4, [...line].length * size * 0.52));
        const x0 = node.align === "center" ? (node.w - wid) / 2 : node.align === "right" ? node.w - wid : 0;
        const y0 = i * lh + size * 0.28;
        return `  d = min(d, sdRR(lq - vec2(${num(x0, 2)}, ${num(y0, 2)}), vec2(${num(wid, 2)}, ${num(size * 0.56, 2)}), ${num(size * 0.28, 2)}));`;
      });
      funcs.push(`float ${id}(vec2 q) {   // text "${lines[0].slice(0, 32).replace(/"/g, "'")}" — greeked: glyphs need an SDF atlas
${localise(world)}
  float d = 1e5;
${bars.join("\n")}
  return d;
}`);
      count++;
      notes.push(`text "${lines[0].slice(0, 24)}" is greeked as bars`);
      paint.push(`{ float d = ${id}(q) - inflate;
  ${put(hex(node.fill, "#111111"), `cov(d, px) * ${op}`)} }`);
    } else if (node.type === "image" && node.href) {
      const id = name(node);
      const u = `img_${++imgCount}`;
      const key = /^data:/.test(node.href) ? "data" : "asset";
      uniforms.push(`uniform sampler2D ${u};   // @${key} ${node.href}`,
                    `uniform vec2 ${u}_size;`);
      const r = num(node.radius || 0, 2);
      funcs.push(`float ${id}(vec2 q) {   // image "${node.name || ""}"
${localise(world)}
  return sdRR(lq, vec2(${w}, ${h}), ${r});
}
vec3 ${id}_pix(vec2 q) {   // the picture, covering its box like preserveAspectRatio: slice
${localise(world)}
  vec2 size = vec2(${w}, ${h});
  vec2 iu = lq / size;
  float ra = size.x / size.y, ia = ${u}_size.x / max(${u}_size.y, 1.0);
  vec2 s = ra > ia ? vec2(1.0, ia / ra) : vec2(ra / ia, 1.0);
  iu = (iu - 0.5) * s + 0.5;
  return ${u}_size.x > 0.5 ? texture2D(${u}, vec2(iu.x, 1.0 - iu.y)).rgb : vec3(0.5);
}`);
      count++;
      paint.push(`{ float d = ${id}(q) - inflate;
  ${put(`${id}_pix(q)`, `cov(d, px) * ${op}`)}
  if (outline > 0.0) ${put("vec3(0.12)", `cov(abs(d) - outline * 0.5, px) * ${op}`)} }`);
    }

    if (node.children) {
      for (const c of node.children) visit(c, world, opacity, depth + 1);
    }
  }

  visit(frame, I, 1, 0);

  const bg = hex(frame.fill, "#ffffff");
  const source = `// Compiled from the design "${frame.name || "frame"}" — ${count} shape${count === 1 ? "" : "s"}, ${W}×${H}.
// Every shape is a function of q, in frame pixels with y down like SVG. Edit
// anything: it is yours. inflate, outline and wobble start at zero, so this
// draws what the design draws; move them and it draws what SVG cannot.
uniform float inflate;   // @range -24 24 @default 0 — offset every edge (px)
uniform float outline;   // @range 0 12 @default 0 — stroke every shape (px)
uniform float wobble;    // @range 0 40 @default 0 — displace every edge with noise (px)
${uniforms.length ? uniforms.join("\n") + "\n" : ""}
const vec2 FRAME = vec2(${num(W)}, ${num(H)});

vec2 xf(vec2 q, float a, float b, float c, float d, float e, float f) {
  return vec2(a * q.x + c * q.y + e, b * q.x + d * q.y + f);
}
float sdRR(vec2 q, vec2 size, float r) {           // rect with corner radius, top-left origin
  vec2 h = size * 0.5;
  r = min(r, min(h.x, h.y));
  return sdBox(q - h, h - r) - r;
}
float cov(float d, float px) { return smoothstep(0.75 * px, -0.75 * px, d); }

// ---- shapes, in painter's order
${funcs.join("\n")}

vec2 q = vec2(uv.x, 1.0 - uv.y) * FRAME;            // frame pixels, y down
float px = FRAME.y / u_resolution.y;                 // one screen pixel, in frame units
if (wobble > 0.0) q += (vec2(fbm(q * 0.02 + t * 0.15), fbm(q * 0.02 + 7.3)) - 0.5) * wobble;
vec3 col = ${bg};                                    // the frame's fill
${paint.join("\n")}

clamp(col, 0.0, 1.0)`;

  return { source, width: W, height: H, shapes: count, images: imgCount, notes };
}

/** A preview size that keeps the frame's aspect inside a box. */
export function fitPreview(w, h, box = 960) {
  const s = Math.min(1, box / Math.max(w, h));
  return [Math.max(2, Math.round((w * s) / 2) * 2), Math.max(2, Math.round((h * s) / 2) * 2)];
}
