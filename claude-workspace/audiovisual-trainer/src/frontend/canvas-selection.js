// Selections, as an 8-bit mask rather than a shape.
//
// A mask is the only representation that covers all four selection tools at
// once, survives feathering, and composites correctly with antialiased edges.
// Everything downstream — drawing, filters, transform, delete — clips through
// the same mask, so there is one code path instead of four.
//
// The marching ants are traced from that mask with marching squares, so a
// wand selection gets the same outline treatment as a rectangle.

import * as I from "./engine-image.js";

export class Selection {
  constructor(w, h) {
    this.w = w;
    this.h = h;
    this.canvas = I.makeCanvas(w, h);   // white where selected, transparent where not
    this.ctx = I.ctx2d(this.canvas);
    this.active = false;
    this.segments = [];                 // contour, for the ants
  }

  clear() {
    this.ctx.clearRect(0, 0, this.w, this.h);
    this.active = false;
    this.segments = [];
  }

  /** Replace the mask from a draw callback that paints white where selected. */
  setFrom(paint, mode = "replace") {
    if (mode === "replace") this.ctx.clearRect(0, 0, this.w, this.h);
    this.ctx.save();
    this.ctx.fillStyle = "#fff";
    this.ctx.strokeStyle = "#fff";
    this.ctx.globalCompositeOperation = mode === "subtract" ? "destination-out" : "source-over";
    paint(this.ctx);
    this.ctx.restore();
    this.active = true;
    this.retrace();
  }

  selectAll() {
    this.setFrom((g) => g.fillRect(0, 0, this.w, this.h));
  }

  invert() {
    if (!this.active) return this.selectAll();
    const inv = I.makeCanvas(this.w, this.h);
    const g = I.ctx2d(inv);
    g.fillStyle = "#fff";
    g.fillRect(0, 0, this.w, this.h);
    g.globalCompositeOperation = "destination-out";
    g.drawImage(this.canvas, 0, 0);
    this.ctx.clearRect(0, 0, this.w, this.h);
    this.ctx.drawImage(inv, 0, 0);
    this.retrace();
  }

  /** Feather by blurring the mask. Cheap, and exactly what feathering is. */
  feather(radius) {
    if (!this.active || radius < 0.5) return;
    const img = I.getImage(this.canvas);
    I.putImage(this.canvas, I.blurFast(img, radius));
    this.retrace();
  }

  /** Bounding box of everything selected, or null. */
  bounds() {
    if (!this.active) return null;
    const d = I.getImage(this.canvas).data;
    let minX = this.w, minY = this.h, maxX = -1, maxY = -1;
    for (let y = 0; y < this.h; y++) {
      for (let x = 0; x < this.w; x++) {
        if (d[(y * this.w + x) * 4 + 3] > 8) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return null;
    return { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 };
  }

  contains(x, y) {
    if (!this.active) return true;          // no selection means "everywhere"
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return false;
    return this.ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data[3] > 8;
  }

  /**
   * Marching squares over the mask, at a stride, producing line segments for
   * the ants. Unordered segments are fine: at one pixel wide with a short
   * dash they read as ants regardless of traversal order.
   */
  retrace(stride = 2) {
    const d = I.getImage(this.canvas).data;
    const at = (x, y) =>
      (x < 0 || y < 0 || x >= this.w || y >= this.h) ? 0
        : (d[(y * this.w + x) * 4 + 3] > 127 ? 1 : 0);
    const segs = [];
    for (let y = 0; y < this.h; y += stride) {
      for (let x = 0; x < this.w; x += stride) {
        const a = at(x, y), b = at(x + stride, y);
        const c = at(x, y + stride);
        if (a !== b) segs.push([x + stride / 2, y, x + stride / 2, y + stride]);
        if (a !== c) segs.push([x, y + stride / 2, x + stride, y + stride / 2]);
      }
    }
    this.segments = segs;
  }

  /** Stroke the ants onto a context already transformed into document space. */
  drawAnts(g, zoom, offset) {
    if (!this.active || !this.segments.length) return;
    const px = 1 / zoom;
    const path = new Path2D();
    for (const [x1, y1, x2, y2] of this.segments) {
      path.moveTo(x1, y1);
      path.lineTo(x2, y2);
    }
    g.save();
    g.lineWidth = px;
    g.strokeStyle = "rgba(0,0,0,.85)";
    g.setLineDash([]);
    g.stroke(path);
    g.strokeStyle = "#fff";
    g.setLineDash([4 * px, 4 * px]);
    g.lineDashOffset = -offset * px;
    g.stroke(path);
    g.restore();
  }

  /** Clip a scratch canvas to the selection, in place. */
  clip(scratchCanvas) {
    if (!this.active) return scratchCanvas;
    const g = I.ctx2d(scratchCanvas);
    g.save();
    g.globalCompositeOperation = "destination-in";
    g.drawImage(this.canvas, 0, 0);
    g.restore();
    return scratchCanvas;
  }
}

/**
 * Magic wand: flood the contiguous region whose colour is within tolerance,
 * or every matching pixel when contiguous is false.
 * Returns a mask canvas.
 */
export function wandMask(sourceCanvas, x0, y0, tolerance, contiguous = true) {
  const w = sourceCanvas.width, h = sourceCanvas.height;
  const img = I.getImage(sourceCanvas);
  const d = img.data;
  const out = I.makeCanvas(w, h);
  const od = new ImageData(w, h);
  const x = Math.floor(x0), y = Math.floor(y0);
  if (x < 0 || y < 0 || x >= w || y >= h) return out;

  const si = (y * w + x) * 4;
  const target = [d[si], d[si + 1], d[si + 2], d[si + 3]];
  // Tolerance is compared in RGB distance rather than per channel: per channel
  // lets a colour differing hugely on one axis still pass on the others.
  const tol = tolerance * tolerance * 3;
  const match = (i) => {
    const dr = d[i] - target[0], dg = d[i + 1] - target[1];
    const db = d[i + 2] - target[2], da = d[i + 3] - target[3];
    return dr * dr + dg * dg + db * db + da * da <= tol;
  };
  const paint = (i) => {
    od.data[i] = od.data[i + 1] = od.data[i + 2] = 255;
    od.data[i + 3] = 255;
  };

  if (!contiguous) {
    for (let i = 0; i < d.length; i += 4) if (match(i)) paint(i);
    I.putImage(out, od);
    return out;
  }

  const seen = new Uint8Array(w * h);
  const stack = [[x, y]];
  while (stack.length) {
    const [sx, sy] = stack.pop();
    let lx = sx;
    while (lx > 0 && !seen[sy * w + lx - 1] && match((sy * w + lx - 1) * 4)) lx--;
    let rx = sx;
    while (rx < w - 1 && !seen[sy * w + rx + 1] && match((sy * w + rx + 1) * 4)) rx++;
    for (let px = lx; px <= rx; px++) {
      const idx = sy * w + px;
      if (seen[idx]) continue;
      seen[idx] = 1;
      paint(idx * 4);
      for (const ny of [sy - 1, sy + 1]) {
        if (ny < 0 || ny >= h) continue;
        const ni = ny * w + px;
        if (!seen[ni] && match(ni * 4)) stack.push([px, ny]);
      }
    }
  }
  I.putImage(out, od);
  return out;
}
