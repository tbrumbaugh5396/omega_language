// Reading a font file, for true glyph outlines.
//
// Tracing a raster recovers an outline to about a pixel; a font file *has* the
// outline, exactly, as the designer drew it. That is the difference between a
// corner reconstructed near where it belongs and one placed exactly, which is
// what the MSDF path wanted all along.
//
// Both outline flavours are read: TrueType's `glyf` (quadratic B-splines, with
// the implied on-curve midpoints between consecutive off-curve points) and
// OpenType's CFF (Type 2 charstrings, cubic Béziers, with the subroutine and
// hint machinery those require). Containers: bare sfnt, TrueType collections,
// and WOFF where the platform can inflate.
//
// A loaded font is also registered with the document, so the browser can lay
// text out with it. That division is deliberate: the file gives the shapes,
// the text engine gives the positions, and neither has to guess at the other.

const registry = new Map();          // family (lowercase) → font

const tag = (v) => String.fromCharCode((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255);

class Reader {
  constructor(view, pos = 0) { this.v = view; this.p = pos; }
  u8() { return this.v.getUint8(this.p++); }
  u16() { const x = this.v.getUint16(this.p); this.p += 2; return x; }
  i16() { const x = this.v.getInt16(this.p); this.p += 2; return x; }
  u32() { const x = this.v.getUint32(this.p); this.p += 4; return x; }
  i32() { const x = this.v.getInt32(this.p); this.p += 4; return x; }
  skip(n) { this.p += n; return this; }
}

async function inflate(bytes) {
  if (typeof DecompressionStream === "undefined") throw new Error("this browser cannot inflate WOFF");
  const ds = new DecompressionStream("deflate");
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Table directory → { tag: DataView }, whatever the container. */
async function readTables(buf) {
  let view = new DataView(buf);
  let sig = view.getUint32(0);

  if (tag(sig) === "wOFF") {
    const num = view.getUint16(12);
    const tables = {};
    let p = 44;
    for (let i = 0; i < num; i++) {
      const t = tag(view.getUint32(p));
      const off = view.getUint32(p + 4), compLen = view.getUint32(p + 8), origLen = view.getUint32(p + 12);
      p += 20;
      const raw = new Uint8Array(buf, off, compLen);
      const data = compLen < origLen ? await inflate(raw) : raw;
      tables[t] = new DataView(data.buffer, data.byteOffset, data.byteLength);
    }
    return tables;
  }
  if (tag(sig) === "wOF2") throw new Error("WOFF2 needs Brotli — convert to .ttf, .otf or .woff");

  let base = 0;
  if (tag(sig) === "ttcf") {           // a collection: take the first face
    base = view.getUint32(12);
    sig = view.getUint32(base);
  }
  if (sig !== 0x00010000 && tag(sig) !== "OTTO" && tag(sig) !== "true" && tag(sig) !== "typ1") {
    throw new Error("not a font file this reads");
  }
  const num = view.getUint16(base + 4);
  const tables = {};
  for (let i = 0; i < num; i++) {
    const p = base + 12 + i * 16;
    const t = tag(view.getUint32(p));
    const off = view.getUint32(p + 8), len = view.getUint32(p + 12);
    if (off + len <= buf.byteLength) tables[t] = new DataView(buf, off, len);
  }
  return tables;
}

// ------------------------------------------------------------------ cmap

function parseCmap(dv) {
  const n = dv.getUint16(2);
  let best = -1, bestScore = -1;
  for (let i = 0; i < n; i++) {
    const pid = dv.getUint16(4 + i * 8), eid = dv.getUint16(6 + i * 8);
    const off = dv.getUint32(8 + i * 8);
    // Prefer full Unicode, then BMP.
    const score = (pid === 3 && eid === 10) ? 5 : (pid === 0 && eid >= 4) ? 4
                : (pid === 3 && eid === 1) ? 3 : (pid === 0) ? 2 : 0;
    if (score > bestScore) { bestScore = score; best = off; }
  }
  if (best < 0) return () => 0;
  const fmt = dv.getUint16(best);
  if (fmt === 4) {
    const segX2 = dv.getUint16(best + 6), seg = segX2 / 2;
    const endP = best + 14, startP = endP + segX2 + 2, deltaP = startP + segX2, rangeP = deltaP + segX2;
    return (cp) => {
      if (cp > 0xffff) return 0;
      for (let i = 0; i < seg; i++) {
        if (dv.getUint16(endP + i * 2) < cp) continue;
        const start = dv.getUint16(startP + i * 2);
        if (start > cp) return 0;
        const delta = dv.getInt16(deltaP + i * 2), ro = dv.getUint16(rangeP + i * 2);
        if (ro === 0) return (cp + delta) & 0xffff;
        const gp = rangeP + i * 2 + ro + (cp - start) * 2;
        if (gp + 1 >= dv.byteLength) return 0;
        const g = dv.getUint16(gp);
        return g === 0 ? 0 : (g + delta) & 0xffff;
      }
      return 0;
    };
  }
  if (fmt === 12) {
    const groups = dv.getUint32(best + 12);
    return (cp) => {
      for (let i = 0; i < groups; i++) {
        const p = best + 16 + i * 12;
        const s = dv.getUint32(p), e = dv.getUint32(p + 4);
        if (cp >= s && cp <= e) return dv.getUint32(p + 8) + (cp - s);
      }
      return 0;
    };
  }
  if (fmt === 6) {
    const first = dv.getUint16(best + 6), count = dv.getUint16(best + 8);
    return (cp) => (cp >= first && cp < first + count ? dv.getUint16(best + 10 + (cp - first) * 2) : 0);
  }
  return () => 0;
}

// ------------------------------------------------------------------ glyf

/** TrueType outlines: quadratics, with midpoints implied between two off-curve
    points, and composite glyphs resolved against their components. */
function glyfOutline(tables, loca, gid, depth = 0) {
  const glyf = tables.glyf;
  if (!glyf || gid + 1 >= loca.length) return [];
  const start = loca[gid], end = loca[gid + 1];
  if (end <= start) return [];                       // blank, e.g. a space
  const r = new Reader(glyf, start);
  const nContours = r.i16();
  r.skip(8);                                          // bbox

  if (nContours < 0) {                                // composite
    if (depth > 4) return [];
    const out = [];
    for (;;) {
      const flags = r.u16(), idx = r.u16();
      let dx, dy;
      if (flags & 1) { dx = r.i16(); dy = r.i16(); }
      else { dx = (r.u8() << 24) >> 24; dy = (r.u8() << 24) >> 24; }
      let a = 1, b = 0, c = 0, d = 1;
      const f2d = () => r.i16() / 16384;
      if (flags & 8) { a = d = f2d(); }
      else if (flags & 0x40) { a = f2d(); d = f2d(); }
      else if (flags & 0x80) { a = f2d(); b = f2d(); c = f2d(); d = f2d(); }
      for (const cont of glyfOutline(tables, loca, idx, depth + 1)) {
        out.push(cont.map(([x, y]) => [a * x + c * y + dx, b * x + d * y + dy]));
      }
      if (!(flags & 0x20)) break;
    }
    return out;
  }

  const ends = [];
  for (let i = 0; i < nContours; i++) ends.push(r.u16());
  const nPts = nContours ? ends[nContours - 1] + 1 : 0;
  r.skip(r.u16());                                    // instructions

  const flags = new Uint8Array(nPts);
  for (let i = 0; i < nPts;) {
    const f = r.u8();
    flags[i++] = f;
    if (f & 8) { let rep = r.u8(); while (rep-- > 0 && i < nPts) flags[i++] = f; }
  }
  const xs = new Int16Array(nPts), ys = new Int16Array(nPts);
  let v = 0;
  for (let i = 0; i < nPts; i++) {
    const f = flags[i];
    if (f & 2) { const d = r.u8(); v += (f & 16) ? d : -d; }
    else if (!(f & 16)) v += r.i16();
    xs[i] = v;
  }
  v = 0;
  for (let i = 0; i < nPts; i++) {
    const f = flags[i];
    if (f & 4) { const d = r.u8(); v += (f & 32) ? d : -d; }
    else if (!(f & 32)) v += r.i16();
    ys[i] = v;
  }

  const contours = [];
  let s = 0;
  for (const e of ends) {
    const pts = [];
    for (let i = s; i <= e; i++) pts.push({ x: xs[i], y: ys[i], on: !!(flags[i] & 1) });
    s = e + 1;
    if (pts.length) contours.push(pts);
  }
  return contours.map(quadContour);
}

/** One TrueType contour → a path of {to, ctrl?} moves in font units. */
function quadContour(pts) {
  const out = [];
  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, on: true });
  // Start on-curve: if the contour begins off-curve, synthesise a start.
  let startIdx = pts.findIndex((p) => p.on);
  let start;
  if (startIdx < 0) { start = mid(pts[0], pts[pts.length - 1]); startIdx = 0; }
  else start = pts[startIdx];
  const seq = [];
  for (let i = 1; i <= pts.length; i++) seq.push(pts[(startIdx + i) % pts.length]);
  out.push({ type: "M", x: start.x, y: start.y });
  let ctrl = null;
  for (const p of seq) {
    if (p.on) {
      if (ctrl) { out.push({ type: "Q", cx: ctrl.x, cy: ctrl.y, x: p.x, y: p.y }); ctrl = null; }
      else out.push({ type: "L", x: p.x, y: p.y });
    } else if (ctrl) {
      const m = mid(ctrl, p);
      out.push({ type: "Q", cx: ctrl.x, cy: ctrl.y, x: m.x, y: m.y });
      ctrl = p;
    } else ctrl = p;
  }
  if (ctrl) out.push({ type: "Q", cx: ctrl.x, cy: ctrl.y, x: start.x, y: start.y });
  out.push({ type: "Z" });
  return out;
}

// ------------------------------------------------------------------ CFF

function cffIndex(dv, pos) {
  const count = dv.getUint16(pos);
  if (count === 0) return { items: [], end: pos + 2 };
  const offSize = dv.getUint8(pos + 2);
  const offAt = (i) => {
    let v = 0, p = pos + 3 + i * offSize;
    for (let k = 0; k < offSize; k++) v = (v << 8) | dv.getUint8(p + k);
    return v;
  };
  const dataStart = pos + 3 + (count + 1) * offSize - 1;
  const items = [];
  for (let i = 0; i < count; i++) {
    items.push({ start: dataStart + offAt(i), end: dataStart + offAt(i + 1) });
  }
  return { items, end: dataStart + offAt(count) };
}

function cffDict(dv, start, end) {
  const out = new Map();
  let operands = [];
  let p = start;
  while (p < end) {
    let b = dv.getUint8(p);
    if (b <= 21) {
      let op = b; p++;
      if (b === 12) { op = 1200 + dv.getUint8(p); p++; }
      out.set(op, operands); operands = [];
    } else if (b === 28) { operands.push(dv.getInt16(p + 1)); p += 3; }
    else if (b === 29) { operands.push(dv.getInt32(p + 1)); p += 5; }
    else if (b === 30) {                              // real
      let str = ""; p++;
      for (;;) {
        const v2 = dv.getUint8(p++); let done = false;
        for (const nib of [v2 >> 4, v2 & 15]) {
          if (nib <= 9) str += nib;
          else if (nib === 10) str += ".";
          else if (nib === 11) str += "E";
          else if (nib === 12) str += "E-";
          else if (nib === 14) str += "-";
          else if (nib === 15) { done = true; break; }
        }
        if (done) break;
      }
      operands.push(parseFloat(str) || 0);
    }
    else if (b >= 32 && b <= 246) { operands.push(b - 139); p++; }
    else if (b >= 247 && b <= 250) { operands.push((b - 247) * 256 + dv.getUint8(p + 1) + 108); p += 2; }
    else if (b >= 251 && b <= 254) { operands.push(-(b - 251) * 256 - dv.getUint8(p + 1) - 108); p += 2; }
    else p++;
  }
  return out;
}

const bias = (n) => (n < 1240 ? 107 : n < 33900 ? 1131 : 32768);

function parseCFF(dv) {
  const hdrSize = dv.getUint8(2);
  const nameIdx = cffIndex(dv, hdrSize);
  const topIdx = cffIndex(dv, nameIdx.end);
  const stringIdx = cffIndex(dv, topIdx.end);
  const gsubrs = cffIndex(dv, stringIdx.end);
  const top = cffDict(dv, topIdx.items[0].start, topIdx.items[0].end);
  const charStringsOff = (top.get(17) || [0])[0];
  if (!charStringsOff) throw new Error("CFF without charstrings");
  const charStrings = cffIndex(dv, charStringsOff);

  let subrs = { items: [] };
  const priv = top.get(18);
  if (priv && priv.length >= 2) {
    const [privLen, privOff] = [priv[0], priv[1]];
    const pd = cffDict(dv, privOff, privOff + privLen);
    const so = (pd.get(19) || [0])[0];
    if (so) subrs = cffIndex(dv, privOff + so);
  }
  // CID fonts keep their private dicts per FD; take the first, which covers
  // the common single-FD case and degrades gracefully otherwise.
  if (!subrs.items.length && top.has(1236)) {
    const fdaOff = top.get(1236)[0];
    const fda = cffIndex(dv, fdaOff);
    if (fda.items.length) {
      const fd = cffDict(dv, fda.items[0].start, fda.items[0].end);
      const p2 = fd.get(18);
      if (p2 && p2.length >= 2) {
        const pd = cffDict(dv, p2[1], p2[1] + p2[0]);
        const so = (pd.get(19) || [0])[0];
        if (so) subrs = cffIndex(dv, p2[1] + so);
      }
    }
  }
  const gBias = bias(gsubrs.items.length), lBias = bias(subrs.items.length);

  /** Type 2 charstring interpreter → a path in font units. */
  function outline(gid) {
    if (gid >= charStrings.items.length) return [];
    const path = [];
    let x = 0, y = 0, stack = [], nStems = 0, haveWidth = false, open = false;
    const moveTo = (nx, ny) => { if (open) path.push({ type: "Z" }); path.push({ type: "M", x: nx, y: ny }); open = true; };
    const stems = () => { if (stack.length % 2) haveWidth = true; nStems += stack.length >> 1; stack.length = 0; };

    const run = (item, depth) => {
      if (depth > 10) return;
      let p = item.start;
      while (p < item.end) {
        const b = dv.getUint8(p++);
        if (b >= 32 || b === 28) {
          if (b === 28) { stack.push(dv.getInt16(p)); p += 2; }
          else if (b <= 246) stack.push(b - 139);
          else if (b <= 250) { stack.push((b - 247) * 256 + dv.getUint8(p++) + 108); }
          else if (b <= 254) { stack.push(-(b - 251) * 256 - dv.getUint8(p++) - 108); }
          else { stack.push(dv.getInt32(p) / 65536); p += 4; }
          continue;
        }
        switch (b) {
          case 1: case 3: case 18: case 23: stems(); break;
          case 19: case 20: stems(); p += (nStems + 7) >> 3; break;
          case 21:
            if (stack.length > 2 && !haveWidth) { stack.shift(); haveWidth = true; }
            x += stack[0] || 0; y += stack[1] || 0; moveTo(x, y); stack.length = 0; break;
          case 22:
            if (stack.length > 1 && !haveWidth) { stack.shift(); haveWidth = true; }
            x += stack[0] || 0; moveTo(x, y); stack.length = 0; break;
          case 4:
            if (stack.length > 1 && !haveWidth) { stack.shift(); haveWidth = true; }
            y += stack[0] || 0; moveTo(x, y); stack.length = 0; break;
          case 5:
            for (let i = 0; i + 1 < stack.length; i += 2) { x += stack[i]; y += stack[i + 1]; path.push({ type: "L", x, y }); }
            stack.length = 0; break;
          case 6: case 7: {
            let horiz = b === 6;
            for (let i = 0; i < stack.length; i++) {
              if (horiz) x += stack[i]; else y += stack[i];
              path.push({ type: "L", x, y });
              horiz = !horiz;
            }
            stack.length = 0; break;
          }
          case 8:
            for (let i = 0; i + 5 < stack.length; i += 6) curve(stack, i);
            stack.length = 0; break;
          case 24: {
            let i = 0;
            for (; i + 7 < stack.length; i += 6) curve(stack, i);
            x += stack[i]; y += stack[i + 1]; path.push({ type: "L", x, y });
            stack.length = 0; break;
          }
          case 25: {
            let i = 0;
            for (; i + 7 < stack.length; i += 2) { x += stack[i]; y += stack[i + 1]; path.push({ type: "L", x, y }); }
            curve(stack, i);
            stack.length = 0; break;
          }
          case 26: case 27: {                          // vvcurveto / hhcurveto
            let i = 0, d = 0;
            if (stack.length % 4) d = stack[i++];
            for (; i + 3 < stack.length; i += 4) {
              let c1x, c1y;
              if (b === 26) { c1x = x + d; c1y = y + stack[i]; } else { c1x = x + stack[i]; c1y = y + d; }
              const c2x = c1x + stack[i + 1], c2y = c1y + stack[i + 2];
              if (b === 26) { x = c2x; y = c2y + stack[i + 3]; } else { x = c2x + stack[i + 3]; y = c2y; }
              path.push({ type: "C", c1x, c1y, c2x, c2y, x, y });
              d = 0;
            }
            stack.length = 0; break;
          }
          case 30: case 31: {                          // vhcurveto / hvcurveto
            let horiz = b === 31, i = 0;
            while (i + 3 < stack.length) {
              const last = stack.length - i === 5;
              let c1x, c1y;
              if (horiz) { c1x = x + stack[i]; c1y = y; } else { c1x = x; c1y = y + stack[i]; }
              const c2x = c1x + stack[i + 1], c2y = c1y + stack[i + 2];
              if (horiz) { y = c2y + stack[i + 3]; x = c2x + (last ? stack[i + 4] : 0); }
              else { x = c2x + stack[i + 3]; y = c2y + (last ? stack[i + 4] : 0); }
              path.push({ type: "C", c1x, c1y, c2x, c2y, x, y });
              i += last ? 5 : 4;
              horiz = !horiz;
            }
            stack.length = 0; break;
          }
          case 10: { const idx = stack.pop() + lBias; const it = subrs.items[idx]; if (it) run(it, depth + 1); break; }
          case 29: { const idx = stack.pop() + gBias; const it = gsubrs.items[idx]; if (it) run(it, depth + 1); break; }
          case 11: return;
          case 14:
            if (open) path.push({ type: "Z" });
            open = false; stack.length = 0; return;
          default: stack.length = 0; break;
        }
      }
    };
    const curve = (s, i) => {
      const c1x = x + s[i], c1y = y + s[i + 1];
      const c2x = c1x + s[i + 2], c2y = c1y + s[i + 3];
      x = c2x + s[i + 4]; y = c2y + s[i + 5];
      path.push({ type: "C", c1x, c1y, c2x, c2y, x, y });
    };
    run(charStrings.items[gid], 0);
    if (open) path.push({ type: "Z" });
    return [path];
  }
  return { outline, numGlyphs: charStrings.items.length };
}

// ------------------------------------------------------------------ flatten

function flattenPath(path, tol, out) {
  let cx = 0, cy = 0, sx = 0, sy = 0, cur = null;
  const push = (x, y) => cur && cur.push([x, y]);
  const cubic = (p0, p1, p2, p3, depth = 0) => {
    const dx = p3[0] - p0[0], dy = p3[1] - p0[1];
    const d1 = Math.abs((p1[0] - p3[0]) * dy - (p1[1] - p3[1]) * dx);
    const d2 = Math.abs((p2[0] - p3[0]) * dy - (p2[1] - p3[1]) * dx);
    if (depth > 14 || (d1 + d2) * (d1 + d2) <= tol * (dx * dx + dy * dy)) { push(p3[0], p3[1]); return; }
    const m = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const p01 = m(p0, p1), p12 = m(p1, p2), p23 = m(p2, p3);
    const p012 = m(p01, p12), p123 = m(p12, p23), c = m(p012, p123);
    cubic(p0, p01, p012, c, depth + 1);
    cubic(c, p123, p23, p3, depth + 1);
  };
  for (const seg of path) {
    if (seg.type === "M") {
      if (cur && cur.length > 2) out.push(cur);
      cur = [[seg.x, seg.y]]; cx = sx = seg.x; cy = sy = seg.y;
    } else if (seg.type === "L") { push(seg.x, seg.y); cx = seg.x; cy = seg.y; }
    else if (seg.type === "Q") {
      const c1 = [cx + (2 / 3) * (seg.cx - cx), cy + (2 / 3) * (seg.cy - cy)];
      const c2 = [seg.x + (2 / 3) * (seg.cx - seg.x), seg.y + (2 / 3) * (seg.cy - seg.y)];
      cubic([cx, cy], c1, c2, [seg.x, seg.y]);
      cx = seg.x; cy = seg.y;
    } else if (seg.type === "C") {
      cubic([cx, cy], [seg.c1x, seg.c1y], [seg.c2x, seg.c2y], [seg.x, seg.y]);
      cx = seg.x; cy = seg.y;
    } else if (seg.type === "Z") {
      if (cur && (cx !== sx || cy !== sy)) push(sx, sy);
      if (cur && cur.length > 2) out.push(cur);
      cur = null; cx = sx; cy = sy;
    }
  }
  if (cur && cur.length > 2) out.push(cur);
  return out;
}

// ------------------------------------------------------------------ public

/**
 * Parse a font file and register it with the document so the browser can lay
 * text out with it too.
 * @returns { family, glyphs, format }
 */
export async function loadFontFile(file) {
  const buf = file instanceof ArrayBuffer ? file : await file.arrayBuffer();
  const tables = await readTables(buf);
  if (!tables.head || !tables.cmap) throw new Error("that font has no head/cmap table");

  const unitsPerEm = tables.head.getUint16(18) || 1000;
  const indexToLoc = tables.head.getInt16(50);
  const numGlyphs = tables.maxp ? tables.maxp.getUint16(4) : 0;
  const glyphIdFor = parseCmap(tables.cmap);

  let outlineOf, format;
  if (tables["CFF "]) {
    const cff = parseCFF(tables["CFF "]);
    outlineOf = (gid) => cff.outline(gid);
    format = "CFF";
  } else if (tables.glyf && tables.loca) {
    const loca = [];
    const l = tables.loca;
    if (indexToLoc === 0) for (let i = 0; i * 2 + 1 < l.byteLength; i++) loca.push(l.getUint16(i * 2) * 2);
    else for (let i = 0; i * 4 + 3 < l.byteLength; i++) loca.push(l.getUint32(i * 4));
    outlineOf = (gid) => glyfOutline(tables, loca, gid);
    format = "glyf";
  } else throw new Error("that font has neither glyf nor CFF outlines");

  // Advances, for callers that would rather not ask the text engine.
  let advanceOf = () => unitsPerEm / 2;
  if (tables.hhea && tables.hmtx) {
    const numH = tables.hhea.getUint16(34), hmtx = tables.hmtx;
    advanceOf = (gid) => {
      const i = Math.min(gid, numH - 1);
      return i * 4 + 1 < hmtx.byteLength ? hmtx.getUint16(i * 4) : unitsPerEm / 2;
    };
  }

  // The family name as the file states it, so text already asking for it is
  // matched rather than renamed.
  let family = readName(tables.name) || (file.name || "font").replace(/\.[^.]+$/, "");
  const font = {
    family, format, unitsPerEm, numGlyphs,
    glyphIdFor,
    advanceEm: (ch) => advanceOf(glyphIdFor(ch.codePointAt(0))) / unitsPerEm,
    /** Contours in em units, y down (the atlas convention), pen at the origin. */
    outlineEm(ch, tol = 0.002) {
      const gid = glyphIdFor(ch.codePointAt(0));
      if (!gid && ch !== " ") { /* .notdef is a legitimate answer */ }
      const paths = outlineOf(gid) || [];
      const flat = [];
      for (const p of paths) flattenPath(p, tol * unitsPerEm * unitsPerEm, flat);
      return flat.map((c) => c.map(([x, y]) => [x / unitsPerEm, -y / unitsPerEm]));
    },
  };

  // Registering the face lets the browser measure and shape with this exact
  // font, which is where the glyph positions come from.
  try {
    const face = new FontFace(family, buf);
    await face.load();
    document.fonts.add(face);
  } catch { /* outlines still work; layout falls back to a substitute */ }

  registry.set(family.toLowerCase(), font);
  return font;
}

function readName(dv) {
  if (!dv) return null;
  const count = dv.getUint16(2), stringOff = dv.getUint16(4);
  let best = null;
  for (let i = 0; i < count; i++) {
    const p = 6 + i * 12;
    const pid = dv.getUint16(p), eid = dv.getUint16(p + 2), nid = dv.getUint16(p + 6);
    const len = dv.getUint16(p + 8), off = dv.getUint16(p + 10);
    if (nid !== 1) continue;                            // family
    let s = "";
    if (pid === 3 && (eid === 1 || eid === 0)) {
      for (let k = 0; k + 1 < len; k += 2) s += String.fromCharCode(dv.getUint16(stringOff + off + k));
    } else {
      for (let k = 0; k < len; k++) s += String.fromCharCode(dv.getUint8(stringOff + off + k));
    }
    if (s && (!best || pid === 3)) best = s;
  }
  return best;
}

/** The first family in a CSS font-family list, unquoted. */
export const primaryFamily = (css) =>
  String(css || "").split(",")[0].trim().replace(/^["']|["']$/g, "");

export const getFont = (family) => registry.get(primaryFamily(family).toLowerCase()) || null;
export const registeredFonts = () => [...registry.values()];
