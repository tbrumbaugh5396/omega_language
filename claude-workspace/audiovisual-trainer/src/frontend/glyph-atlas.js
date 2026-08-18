// Text as signed distance fields.
//
// A glyph outline is a path, so text belongs in the shape compiler — but a
// paragraph is thousands of segments, which is why §2.4c of the roadmap sends
// it to an atlas instead. The atlas is a *distance* texture, not a coverage
// one, so it stays crisp at any zoom and every knob that acts on a distance —
// inflate, outline, wobble — acts on letterforms too.
//
// No font file is parsed. The browser already has the fonts and already
// rasterises them, so each glyph is drawn with Canvas at high resolution,
// thresholded, and turned into an exact Euclidean distance field by
// Felzenszwalb and Huttenlocher's transform (linear time, exact — not the
// usual 8SSEDT approximation). The field is then halved to atlas resolution,
// which distance fields survive gracefully and coverage does not.
//
// Positions come from measureText on growing prefixes, so kerning is whatever
// the browser would apply. That is the same text engine the SVG and design
// renderers use, which is the point: the shader agrees with the picture.

import { traceContours, simplify, colorEdges, renderMSDF, makeInsideTest, MEDIAN_GLSL } from "./msdf.js";
import { getFont, primaryFamily } from "./font-file.js";

const PPEM = 48;          // atlas pixels per em, after downsampling
const SUPER = 2;          // rendered at SUPER × PPEM, then halved
const SPREAD = 8;         // distance range in atlas pixels, each way
const MAX_ATLAS = 2048;

/** Exact 1-D squared distance transform of a cost row (Felzenszwalb 2012). */
function edt1d(f, n, d, v, z) {
  let k = 0;
  v[0] = 0; z[0] = -Infinity; z[1] = Infinity;
  for (let q = 1; q < n; q++) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) {
      k--;
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    }
    k++; v[k] = q; z[k] = s; z[k + 1] = Infinity;
  }
  k = 0;
  for (let q = 0; q < n; q++) {
    while (z[k + 1] < q) k++;
    const dq = q - v[k];
    d[q] = dq * dq + f[v[k]];
  }
}

/** Squared distance to the nearest set pixel, over a w×h binary field. */
function edt2d(binary, w, h) {
  const INF = 1e12;
  const f = new Float64Array(Math.max(w, h));
  const d = new Float64Array(Math.max(w, h));
  const v = new Int32Array(Math.max(w, h));
  const z = new Float64Array(Math.max(w, h) + 1);
  const out = new Float64Array(w * h);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) f[y] = binary[y * w + x] ? 0 : INF;
    edt1d(f, h, d, v, z);
    for (let y = 0; y < h; y++) out[y * w + x] = d[y];
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) f[x] = out[y * w + x];
    edt1d(f, w, d, v, z);
    for (let x = 0; x < w; x++) out[y * w + x] = d[x];
  }
  return out;
}

/**
 * A glyph built from real outlines: no raster, no tracing. The contours arrive
 * in em units with y down, are scaled to atlas pixels, and the field is
 * computed against them directly.
 */
function outlineGlyph(parsed, ch) {
  let contours;
  // Flattened finely on purpose: the corner test measures a turn over about a
  // pixel of arc, so segments have to be shorter than that or a smooth curve
  // presents itself as a sequence of sharp turns.
  try { contours = parsed.outlineEm(ch, 0.00002); } catch { return null; }
  const adv = parsed.advanceEm(ch);
  if (!contours.length) return { adv, blank: true };

  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const c of contours) for (const [x, y] of c) {
    if (x < x0) x0 = x; if (y < y0) y0 = y;
    if (x > x1) x1 = x; if (y > y1) y1 = y;
  }
  const padEm = (SPREAD + 1) / PPEM;
  const bx = x0 - padEm, by = y0 - padEm;
  const bw = (x1 - x0) + padEm * 2, bh = (y1 - y0) + padEm * 2;
  const lw = Math.max(2, Math.ceil(bw * PPEM)), lh = Math.max(2, Math.ceil(bh * PPEM));
  // Into tile pixels, with the tile's top-left at the origin.
  const local = contours.map((c) => c.map(([x, y]) => [(x - bx) * PPEM, (y - by) * PPEM]));
  const edges = colorEdges(local);
  const field = renderMSDF(edges, lw, lh, SPREAD, makeInsideTest(local));
  return { adv, bx, by, bw, bh, w: lw, h: lh, field, channels: 3, blank: false };
}

const fontCss = (spec, px) =>
  `${spec.style || "normal"} ${spec.weight || 400} ${px}px ${spec.family || "system-ui, sans-serif"}`;

/**
 * Build one atlas covering every (font, character) pair in `runs`.
 *
 * run = { text, family, weight, style }
 * @returns null when there is nothing to draw, else
 *   { dataUrl, width, height, fonts: Map(key → {glyphs: Map(ch → metrics), ascent}) }
 */
export async function buildAtlas(runs, opts = {}) {
  if (typeof document === "undefined") return null;
  try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch { /* older engine */ }

  // One entry per distinct font, holding the characters it actually needs.
  const fonts = new Map();
  for (const r of runs) {
    const key = fontCss({ family: r.family, weight: r.weight, style: r.style }, 1);
    if (!fonts.has(key)) fonts.set(key, { spec: r, chars: new Set() });
    for (const ch of String(r.text ?? "")) if (ch !== "\n") fonts.get(key).chars.add(ch);
  }
  if (!fonts.size) return null;

  const hi = PPEM * SUPER;
  const pad = Math.ceil((SPREAD + 1) * SUPER);
  const measure = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const cell = document.createElement("canvas");
  const cg = cell.getContext("2d", { willReadFrequently: true });

  // First pass: rasterise each glyph's field and remember its size.
  const tiles = [];
  let trueOutlines = 0;
  for (const [key, f] of fonts) {
    measure.font = fontCss(f.spec, hi);
    f.glyphs = new Map();
    // A parsed font file is the better source by a clear margin: its outlines
    // are what the designer drew, so a corner is placed exactly rather than
    // recovered to within about a pixel.
    const parsed = (opts.singleChannel || opts.trace) ? null : getFont(f.spec.family);
    for (const ch of [...f.chars].sort()) {
      if (parsed) {
        const g = outlineGlyph(parsed, ch);
        if (g) { f.glyphs.set(ch, g); if (!g.blank) { tiles.push(g); trueOutlines++; } continue; }
      }
      const m = measure.measureText(ch);
      const adv = m.width / hi;
      const left = m.actualBoundingBoxLeft, right = m.actualBoundingBoxRight;
      const asc = m.actualBoundingBoxAscent, desc = m.actualBoundingBoxDescent;
      const inkW = (left + right), inkH = (asc + desc);
      if (!(inkW > 0.5 && inkH > 0.5)) {           // space and friends: advance only
        f.glyphs.set(ch, { adv, blank: true });
        continue;
      }
      const w = Math.ceil(inkW) + pad * 2, h = Math.ceil(inkH) + pad * 2;
      cell.width = w; cell.height = h;
      cg.clearRect(0, 0, w, h);
      cg.font = fontCss(f.spec, hi);
      cg.textBaseline = "alphabetic";
      cg.textAlign = "left";
      cg.fillStyle = "#fff";
      cg.fillText(ch, pad + left, pad + asc);

      const img = cg.getImageData(0, 0, w, h).data;
      const alpha = new Uint8Array(w * h);
      for (let i = 0, p = 3; i < w * h; i++, p += 4) alpha[i] = img[p];

      const lw = Math.max(1, Math.round(w / SUPER)), lh = Math.max(1, Math.round(h / SUPER));
      const coveredHi = (x, y) => alpha[Math.min(h - 1, y) * w + Math.min(w - 1, x)] >= 128;
      const covered = (x, y) => coveredHi(Math.floor(x * SUPER + SUPER / 2), Math.floor(y * SUPER + SUPER / 2));

      let field = null, channels = 1;
      if (!opts.singleChannel) {
        // Outlines from the anti-aliased coverage, brought down to atlas
        // scale, cut at their corners and coloured.
        // The tolerance matters more than it looks: too tight and the traced
        // staircase keeps micro-vertices, the corner test fires at each, and
        // every false corner becomes an edge end whose pseudo-distance
        // extends past the outline. An 'H' should come out with twelve
        // corners, not eighteen.
        const contours = traceContours(alpha, w, h)
          .map((c) => simplify(c.map(([x, y]) => [x / SUPER, y / SUPER]), 0.12))
          .filter((c) => c.length > 3);
        if (contours.length) {
          const edges = colorEdges(contours);
          field = renderMSDF(edges, lw, lh, SPREAD, covered);
          channels = 3;
        }
      }
      if (!field) {
        // Single channel: the exact transform on the thresholded bitmap.
        const inside = new Uint8Array(w * h), outside = new Uint8Array(w * h);
        for (let i = 0; i < w * h; i++) { if (alpha[i] >= 128) inside[i] = 1; else outside[i] = 1; }
        const dOut = edt2d(inside, w, h), dIn = edt2d(outside, w, h);
        field = new Uint8ClampedArray(lw * lh * 3);
        for (let y = 0; y < lh; y++) {
          for (let x = 0; x < lw; x++) {
            let acc = 0, n = 0;
            for (let sy = y * SUPER; sy < Math.min(h, (y + 1) * SUPER); sy++) {
              for (let sx = x * SUPER; sx < Math.min(w, (x + 1) * SUPER); sx++) {
                const i = sy * w + sx;
                acc += (Math.sqrt(dOut[i]) - Math.sqrt(dIn[i])) / SUPER;
                n++;
              }
            }
            const v = Math.round(255 * Math.min(1, Math.max(0, 0.5 + (acc / Math.max(1, n)) / (2 * SPREAD))));
            const i3 = (y * lw + x) * 3;
            field[i3] = field[i3 + 1] = field[i3 + 2] = v;
          }
        }
      }
      const g = {
        adv,
        // The tile covers this rectangle, in em, relative to the pen point on
        // the baseline, y down.
        bx: (-left - pad) / hi, by: (-asc - pad) / hi,
        bw: (w / SUPER) / PPEM, bh: (h / SUPER) / PPEM,
        w: lw, h: lh, field, channels, blank: false,
      };
      f.glyphs.set(ch, g);
      tiles.push(g);
    }
  }
  if (!tiles.length) return null;

  // Shelf packing, tallest first, into the smallest power-of-two square.
  tiles.sort((a, b) => b.h - a.h);
  let size = 128;
  const pack = () => {
    let x = 1, y = 1, shelf = 0;
    for (const t of tiles) {
      if (x + t.w + 1 > size) { x = 1; y += shelf + 1; shelf = 0; }
      if (y + t.h + 1 > size) return false;
      t.x = x; t.y = y; x += t.w + 1; shelf = Math.max(shelf, t.h);
    }
    return true;
  };
  while (!pack()) {
    size *= 2;
    if (size > MAX_ATLAS) return null;
  }

  const atlas = document.createElement("canvas");
  atlas.width = size; atlas.height = size;
  const ag = atlas.getContext("2d", { willReadFrequently: true });
  const out = ag.createImageData(size, size);
  // 128 is the zero level: everywhere with no glyph reads as "just outside".
  for (let i = 0; i < size * size; i++) {
    out.data[i * 4] = out.data[i * 4 + 1] = out.data[i * 4 + 2] = 255;
    out.data[i * 4 + 3] = 255;
  }
  for (const t of tiles) {
    for (let y = 0; y < t.h; y++) {
      for (let x = 0; x < t.w; x++) {
        const src = (y * t.w + x) * 3;
        const i = ((t.y + y) * size + (t.x + x)) * 4;
        out.data[i] = t.field[src];
        out.data[i + 1] = t.field[src + 1];
        out.data[i + 2] = t.field[src + 2];
      }
    }
    t.u0 = t.x / size; t.v0 = t.y / size;
    t.u1 = (t.x + t.w) / size; t.v1 = (t.y + t.h) / size;
    delete t.field;
  }
  ag.putImageData(out, 0, 0);

  return {
    dataUrl: atlas.toDataURL("image/png"),
    width: size, height: size, fonts,
    /** Signed distance range the field carries, in em. */
    spreadEm: SPREAD / PPEM,
    multiChannel: tiles.some((t) => t.channels === 3),
    trueOutlines,
  };
}

/**
 * Per-character pen positions.
 *
 * With a parsed font the advances come from `hmtx` and the pairs from GPOS's
 * kern feature (or the old `kern` table), which is the font's own answer and
 * does not depend on the browser having the family installed. Otherwise the
 * text engine is asked, by measuring growing prefixes, which picks up whatever
 * kerning it would apply.
 */
export function layoutLine(text, spec, sizePx, letterSpacing = 0) {
  const font = getFont(spec.family);
  if (font && font.outlines !== false && font.kernEm) {
    const out = [];
    let x = 0;
    for (let i = 0; i < text.length; i++) {
      if (i > 0) x += font.kernEm(text[i - 1], text[i]) * sizePx;
      out.push({ ch: text[i], x });
      x += font.advanceEm(text[i]) * sizePx + letterSpacing;
    }
    return { glyphs: out, width: x };
  }
  const c = document.createElement("canvas").getContext("2d");
  c.font = fontCss(spec, sizePx);
  const out = [];
  let x = 0;
  for (let i = 0; i < text.length; i++) {
    // Prefix widths rather than per-glyph advances, so kerning pairs land
    // where the text engine would put them.
    const before = i === 0 ? 0 : c.measureText(text.slice(0, i)).width + letterSpacing * i;
    out.push({ ch: text[i], x: before });
    x = c.measureText(text.slice(0, i + 1)).width + letterSpacing * (i + 1);
  }
  return { glyphs: out, width: x };
}

/** The GLSL helper every text item shares. Multi-channel fields take the
    median of the three, which is what reconstructs a corner. */
export const GLYPH_HELPER = `${MEDIAN_GLSL}
float glyph(vec2 p, vec2 pos, vec2 size, vec4 uvr, float k) {
  vec2 r = (p - pos) / size;
  // Outside the tile the field is not defined, so say "far" rather than clamp.
  if (r.x < -0.02 || r.x > 1.02 || r.y < -0.02 || r.y > 1.02) return 1e4;
  // Textures are uploaded flipped (uv (0,0) is bottom-left), and the atlas
  // rectangles are in image space, so v comes back the other way up.
  vec2 auv = mix(uvr.xy, uvr.zw, clamp(r, 0.0, 1.0));
  vec3 s = texture2D(u_font, vec2(auv.x, 1.0 - auv.y)).rgb;
  return (med3(s.r, s.g, s.b) - 0.5) * k;
}`;

/**
 * GLSL for one text run: a min() over its glyphs, in the item's local space.
 * `lines` are the text's lines; `origin` places the first baseline.
 */
export function emitTextRun(atlas, run, opts) {
  const key = fontCss({ family: run.family, weight: run.weight, style: run.style }, 1);
  const font = atlas.fonts.get(key);
  if (!font) return null;
  const size = opts.size;
  const lines = String(run.text ?? "").split("\n");
  const lh = opts.lineHeight * size;
  const stmts = [];
  let widest = 0;

  lines.forEach((line, li) => {
    const laid = layoutLine(line, run, size, opts.letterSpacing || 0);
    widest = Math.max(widest, laid.width);
    const dx = opts.align === "center" ? (opts.boxWidth - laid.width) / 2
             : opts.align === "right" ? opts.boxWidth - laid.width : 0;
    const baseY = opts.firstBaseline + li * lh;
    for (const g of laid.glyphs) {
      const m = font.glyphs.get(g.ch);
      if (!m || m.blank) continue;
      const px = dx + g.x + m.bx * size, py = baseY + m.by * size;
      const bw = m.bw * size, bh = m.bh * size;
      // The stored range is spreadEm × 2 of em; at this size that is this many
      // output pixels, which is what turns the sample back into a distance.
      const k = 2 * atlas.spreadEm * size;
      stmts.push(`  d = min(d, glyph(lq, vec2(${f(px)}, ${f(py)}), vec2(${f(bw)}, ${f(bh)}), `
        + `vec4(${f(m.u0, 5)}, ${f(m.v0, 5)}, ${f(m.u1, 5)}, ${f(m.v1, 5)}), ${f(k, 3)}));`);
    }
  });
  if (!stmts.length) return null;
  return { body: `  float d = 1e4;\n${stmts.join("\n")}\n  return d;`, glyphs: stmts.length, width: widest };
}

const f = (v, d = 2) => {
  const n = Number.isFinite(+v) ? +v : 0;
  const s = n.toFixed(d).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return /[.eE]/.test(s) ? s : s + ".0";
};
