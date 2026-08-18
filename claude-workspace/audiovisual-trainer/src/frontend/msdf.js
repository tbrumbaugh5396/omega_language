// Multi-channel signed distance fields.
//
// A single-channel field cannot represent a corner: it is the distance to the
// nearest edge, and at a corner the true field has a crease that an 8-bit
// bilinear texture rounds off. Chlumský's answer is to split the outline at
// its corners, give neighbouring pieces different channel pairs, and take the
// **median** of the three at sample time — because at a corner two channels
// disagree and the median follows the one that is right on each side, which
// reconstructs the crease exactly.
//
// That needs outlines, and a browser will not hand over glyph outlines for a
// system font. So they are recovered: marching squares on the *anti-aliased*
// coverage, which interpolates each crossing along its cell edge and so gives
// sub-pixel contours — more accurate than the binary threshold the
// single-channel path used, before MSDF is even considered.
//
// The limit of recovering rather than reading outlines: a corner's apex is
// where two traced edges' lines meet, and those edges carry sub-pixel angular
// error, so the reconstructed apex can sit up to about one atlas pixel outside
// the true one. Corners come out sharp — which is the whole point — but very
// slightly fat. With true font outlines that error would not exist.

const R = 1, G = 2, B = 4;
const YELLOW = R | G, MAGENTA = R | B, CYAN = G | B, WHITE = R | G | B;

/**
 * Contours of the 0.5 coverage isoline, as closed polylines. Marching squares
 * with linear interpolation along each cell edge; segments are then chained by
 * their endpoints.
 */
export function traceContours(alpha, w, h) {
  // Interpolate where the isoline crosses an edge between two samples.
  const at = (x, y) => (x < 0 || y < 0 || x >= w || y >= h ? 0 : alpha[y * w + x] / 255);
  const lerp = (v0, v1) => {
    const d = v1 - v0;
    return Math.abs(d) < 1e-9 ? 0.5 : (0.5 - v0) / d;
  };
  const segs = [];
  for (let y = -1; y < h; y++) {
    for (let x = -1; x < w; x++) {
      const tl = at(x, y), tr = at(x + 1, y), br = at(x + 1, y + 1), bl = at(x, y + 1);
      const idx = (tl >= 0.5 ? 1 : 0) | (tr >= 0.5 ? 2 : 0) | (br >= 0.5 ? 4 : 0) | (bl >= 0.5 ? 8 : 0);
      if (idx === 0 || idx === 15) continue;
      const T = [x + lerp(tl, tr), y];
      const Rr = [x + 1, y + lerp(tr, br)];
      const Bm = [x + lerp(bl, br), y + 1];
      const L = [x, y + lerp(tl, bl)];
      // Directed so the covered side is consistently on one hand of travel.
      const put = (a, b) => segs.push([a, b]);
      switch (idx) {
        case 1: put(T, L); break;
        case 2: put(Rr, T); break;
        case 3: put(Rr, L); break;
        case 4: put(Bm, Rr); break;
        case 5: put(T, L); put(Bm, Rr); break;          // saddle
        case 6: put(Bm, T); break;
        case 7: put(Bm, L); break;
        case 8: put(L, Bm); break;
        case 9: put(T, Bm); break;
        case 10: put(Rr, T); put(L, Bm); break;         // saddle
        case 11: put(Rr, Bm); break;
        case 12: put(L, Rr); break;
        case 13: put(T, Rr); break;
        case 14: put(L, T); break;
      }
    }
  }
  // Chain segments end-to-start into closed loops.
  const key = (p) => `${Math.round(p[0] * 64)},${Math.round(p[1] * 64)}`;
  const from = new Map();
  for (const s of segs) {
    const k = key(s[0]);
    if (!from.has(k)) from.set(k, []);
    from.get(k).push(s);
  }
  const used = new Set();
  const contours = [];
  for (const s of segs) {
    if (used.has(s)) continue;
    const pts = [s[0]];
    let cur = s;
    for (let guard = 0; guard < 100000; guard++) {
      used.add(cur);
      pts.push(cur[1]);
      const next = (from.get(key(cur[1])) || []).find((c) => !used.has(c));
      if (!next) break;
      cur = next;
      if (key(cur[0]) === key(s[0]) && used.has(cur)) break;
    }
    if (pts.length > 3) contours.push(pts);
  }
  return contours;
}

/**
 * Douglas–Peucker, so a traced contour becomes a handful of long segments.
 *
 * A closed contour has to be cut open first: its first and last points are the
 * same, so every perpendicular distance to that degenerate baseline is zero
 * and the whole loop collapses to two points. Cutting at the vertex farthest
 * from the start gives two honest chains.
 */
export function simplify(pts, tol) {
  const closed = pts.length > 3
    && Math.abs(pts[0][0] - pts[pts.length - 1][0]) < 1e-6
    && Math.abs(pts[0][1] - pts[pts.length - 1][1]) < 1e-6;
  if (closed) {
    let far = 1, best = -1;
    for (let i = 1; i < pts.length - 1; i++) {
      const d = Math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]);
      if (d > best) { best = d; far = i; }
    }
    const a = simplifyOpen(pts.slice(0, far + 1), tol);
    const b = simplifyOpen(pts.slice(far), tol);
    return a.concat(b.slice(1));
  }
  return simplifyOpen(pts, tol);
}

function simplifyOpen(pts, tol) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [i, j] = stack.pop();
    let far = -1, best = tol;
    const [ax, ay] = pts[i], [bx, by] = pts[j];
    const dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy) || 1e-9;
    for (let k = i + 1; k < j; k++) {
      const d = Math.abs((pts[k][0] - ax) * dy - (pts[k][1] - ay) * dx) / len;
      if (d > best) { best = d; far = k; }
    }
    if (far > 0) { keep[far] = 1; stack.push([i, far], [far, j]); }
  }
  return pts.filter((_, i) => keep[i]);
}

/**
 * Split each contour at its corners and colour the pieces so that neighbours
 * share exactly one channel. A smooth loop keeps all three, which is what
 * makes a circle behave exactly as it did before.
 */
export function colorEdges(contours, cosLimit = Math.cos((40 * Math.PI) / 180), window = 1.0) {
  const edges = [];
  for (const pts of contours) {
    const n = pts.length - 1;                       // last repeats the first
    if (n < 2) continue;
    // Directions are measured over an arc-length window rather than between
    // neighbouring segments. A traced outline keeps micro-vertices even after
    // simplification, and judging a corner from two one-pixel segments calls
    // half of them corners — which shatters the outline and makes every false
    // end extend its pseudo-distance past the glyph.
    const walk = (i, step) => {
      let x = 0, y = 0, len = 0;
      for (let k = 0; k < n && len < window; k++) {
        const j = ((i + (step < 0 ? -k - 1 : k)) % n + n) % n;
        const a = pts[j], b = pts[(j + 1) % n];
        const dx = b[0] - a[0], dy = b[1] - a[1];
        const l = Math.hypot(dx, dy);
        x += dx; y += dy; len += l;
      }
      const l = Math.hypot(x, y) || 1e-9;
      return [x / l, y / l];
    };
    const corners = [];
    for (let i = 0; i < n; i++) {
      const [px, py] = walk(i, -1), [qx, qy] = walk(i, 1);
      if (px * qx + py * qy < cosLimit) corners.push(i);
    }
    // Several detections can belong to one corner — but only when they are
    // physically close. Merging by index alone is wrong for a true outline,
    // where consecutive vertices are all genuine corners: an 'H' has twelve in
    // a row, and index-merging would leave three.
    const near = 0.6;
    for (let i = corners.length - 1; i > 0; i--) {
      const a = pts[corners[i - 1] % n], b = pts[corners[i] % n];
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) < near) corners.splice(i, 1);
    }
    const pieces = [];
    if (!corners.length) {
      pieces.push(pts.slice(0, n + 1));
    } else if (corners.length === 1) {
      // A teardrop: one corner, so cut it into three to have neighbours at all.
      const s = corners[0], third = Math.max(1, Math.floor(n / 3));
      const idx = [s, s + third, s + 2 * third, s + n];
      for (let k = 0; k < 3; k++) {
        const piece = [];
        for (let i = idx[k]; i <= idx[k + 1]; i++) piece.push(pts[i % n]);
        pieces.push(piece);
      }
    } else {
      for (let c = 0; c < corners.length; c++) {
        const s = corners[c], e = corners[(c + 1) % corners.length] + (c === corners.length - 1 ? n : 0);
        const piece = [];
        for (let i = s; i <= e; i++) piece.push(pts[i % n]);
        if (piece.length > 1) pieces.push(piece);
      }
    }
    const m = pieces.length;
    pieces.forEach((piece, i) => {
      let colour;
      if (m === 1) colour = WHITE;
      else if (m % 2 === 1 && i === m - 1) colour = CYAN;   // breaks the odd wrap
      else colour = i % 2 === 0 ? MAGENTA : YELLOW;
      edges.push({ pts: piece, colour });
    });
  }
  return edges;
}

/** Signed distance from p to one coloured edge, with msdfgen's pseudo-distance
    at the edge's own ends so a corner stays sharp instead of rounding. */
function edgeDistance(edge, px, py, reach = 2) {
  const pts = edge.pts;
  let best = Infinity, bestI = 0, bestT = 0;
  for (let i = 0; i + 1 < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1];
    const ex = bx - ax, ey = by - ay;
    const l2 = ex * ex + ey * ey || 1e-12;
    const traw = ((px - ax) * ex + (py - ay) * ey) / l2;
    const t = traw < 0 ? 0 : traw > 1 ? 1 : traw;
    const qx = ax + ex * t, qy = ay + ey * t;
    const d = Math.hypot(px - qx, py - qy);
    if (d < best) { best = d; bestI = i; bestT = traw; }
  }
  const [ax, ay] = pts[bestI], [bx, by] = pts[bestI + 1];
  const ex = bx - ax, ey = by - ay;
  const l = Math.hypot(ex, ey) || 1e-9;
  const cross = (ex * (py - ay) - ey * (px - ax)) / l;
  let mag = best;
  // Past either free end, measure to the line's continuation — that is what
  // lets one channel keep going straight while its neighbour turns. But only
  // just past: an edge's line has no business speaking about points far beyond
  // where the edge stops, and on a flattened curve, where every short edge has
  // two free ends, letting it do so sprays specks around the letterform.
  const past = bestT < 0 ? -bestT * l : bestT > 1 ? (bestT - 1) * l : 0;
  if (past > 0 && past < reach
      && ((bestI === 0 && bestT < 0) || (bestI === pts.length - 2 && bestT > 1))) {
    mag = Math.abs(cross);
  }
  // Both are returned because they do different jobs: the true distance
  // decides which edge owns this pixel, and only then does the pseudo one
  // give the value. Choosing by the pseudo distance instead lets a distant
  // edge win wherever its extended line happens to pass close, which turns
  // the field into confetti.
  return { d: best, s: cross < 0 ? -mag : mag };
}

const median = (a, b, c) => Math.max(Math.min(a, b), Math.min(Math.max(a, b), c));

/**
 * Render the three channels over a cell.
 *
 * @param edges   coloured edges, in the same space as the cell grid
 * @param inside  (x, y) → is this sample covered, for the far field and for
 *                deciding which way round the traced contours came out
 */
export function renderMSDF(edges, w, h, spread, inside) {
  const out = new Uint8ClampedArray(w * h * 3);
  const reach = spread + 2;
  // Orientation is whatever marching squares produced; rather than reason
  // about it, measure it. One sample is not enough — the first covered pixel
  // is often sitting on an edge, where the sign is a coin toss — so every
  // pixel that is properly inside gets a vote.
  let votes = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!inside(x, y)) continue;
      const px = x + 0.25, py = y + 0.25;
      let m = Infinity, sd = 0;
      for (const e of edges) {
        const r = edgeDistance(e, px, py);
        if (r.d < m) { m = r.d; sd = r.s; }
      }
      if (m > 1.0 && m < Infinity) votes += sd > 0 ? 1 : -1;
    }
  }
  const flip = votes > 0;

  const enc = (v) => Math.round(255 * Math.min(1, Math.max(0, 0.5 + v / (2 * spread))));
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      // An atlas pixel averages SUPER×SUPER samples, so its centre sits a
      // quarter of a pixel in from where a naive +0.5 would put it.
      const px = x + 0.25, py = y + 0.25;
      let bd = [Infinity, Infinity, Infinity];
      let bs = [null, null, null];
      let trueD = Infinity;
      for (const e of edges) {
        const r = edgeDistance(e, px, py);
        if (r.d < trueD) trueD = r.d;
        for (let ch = 0; ch < 3; ch++) {
          if (!(e.colour & (1 << ch))) continue;
          if (r.d < bd[ch]) { bd[ch] = r.d; bs[ch] = r.s; }
        }
      }
      // Beyond the field's reach there is no edge to ask, so the coverage
      // decides — and that value is already the right way round, which is why
      // only the measured ones are flipped.
      // Beyond the field's reach there is no edge to ask, so the coverage
      // decides — and that value is already the right way round, which is why
      // only the measured ones are flipped.
      const covered = inside(x, y);
      const far = (covered ? -1 : 1) * spread;
      const v = [0, 0, 0];
      for (let ch = 0; ch < 3; ch++) {
        const measured = bs[ch] !== null && bd[ch] <= reach;
        v[ch] = measured ? (flip ? -bs[ch] : bs[ch]) : far;
      }
      // Error correction, and the reason msdfgen has one too. Three channels
      // reconstruct a corner by disagreeing, but where several edges meet at a
      // shallow angle the disagreement can outvote the truth and leave a speck
      // floating beside the letterform. The true distance is known here, so
      // where the median wanders more than a pixel from it, the truth wins —
      // which is far enough away never to blunt a corner.
      const med = median(v[0], v[1], v[2]);
      const trueS = (covered ? -1 : 1) * Math.min(trueD, spread);
      if (Math.abs(med - trueS) > 1) { v[0] = v[1] = v[2] = trueS; }
      const i = (y * w + x) * 3;
      for (let ch = 0; ch < 3; ch++) out[i + ch] = enc(v[ch]);
    }
  }
  return out;
}

/**
 * Even-odd point-in-contours test. When the outline comes from a font file
 * there is no raster to consult, so coverage is answered by the geometry.
 */
export function makeInsideTest(contours) {
  return (x, y) => {
    const px = x + 0.5, py = y + 0.5;
    let cross = 0;
    for (const c of contours) {
      for (let i = 0; i + 1 < c.length; i++) {
        const [ax, ay] = c[i], [bx, by] = c[i + 1];
        if ((ay > py) === (by > py)) continue;
        if (px < ax + ((py - ay) / (by - ay)) * (bx - ax)) cross++;
      }
    }
    return (cross & 1) === 1;
  };
}

/** The GLSL side: the median of the three channels is the distance. */
export const MEDIAN_GLSL = `float med3(float a, float b, float c) { return max(min(a, b), min(max(a, b), c)); }`;

export { median };
