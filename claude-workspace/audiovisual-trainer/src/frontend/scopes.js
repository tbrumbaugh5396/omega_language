// Scopes: waveform, vectorscope, histogram.
//
// The three instruments that turn "it looks a bit warm" into a number you can
// point at. They read the frame that was actually composited, so what they
// measure is what will be exported — and they are drawn small and often, so
// they work on the preview rather than the full frame, which is exactly what a
// scope is for.
//
// Rec. 709 throughout, because that is what the footage is and what the grade
// nodes assume.

const R709 = [0.2126, 0.7152, 0.0722];

/** Luma, and the two colour-difference axes a vectorscope plots. */
function ycbcr(r, g, b) {
  const y = R709[0] * r + R709[1] * g + R709[2] * b;
  return [y, (b - y) / 1.8556, (r - y) / 1.5748];
}

/**
 * A waveform: one column per column of the picture, luma up the vertical, and
 * brightness where the samples pile up. Overexposure reads as a line pressed
 * against the top, which is the whole point of looking.
 */
export function drawWaveform(img, canvas, { mode = "luma" } = {}) {
  const W = canvas.width, H = canvas.height;
  const g = canvas.getContext("2d");
  const bins = new Float32Array(W * H);
  const sx = img.width / W, sy = Math.max(1, Math.round(img.height / 220));
  for (let y = 0; y < img.height; y += sy) {
    for (let x = 0; x < img.width; x++) {
      const i = (y * img.width + x) * 4;
      const col = Math.min(W - 1, (x / sx) | 0);
      const v = mode === "luma"
        ? (R709[0] * img.data[i] + R709[1] * img.data[i + 1] + R709[2] * img.data[i + 2]) / 255
        : Math.max(img.data[i], img.data[i + 1], img.data[i + 2]) / 255;
      const row = Math.min(H - 1, Math.max(0, Math.round((1 - v) * (H - 1))));
      bins[row * W + col] += 1;
    }
  }
  let peak = 0;
  for (let i = 0; i < bins.length; i++) if (bins[i] > peak) peak = bins[i];
  const out = g.createImageData(W, H);
  for (let i = 0; i < bins.length; i++) {
    // A square root, so a thin trace is visible next to a thick one.
    const v = peak > 0 ? Math.sqrt(bins[i] / peak) : 0;
    out.data[i * 4] = 90 * v; out.data[i * 4 + 1] = 240 * v; out.data[i * 4 + 2] = 190 * v;
    out.data[i * 4 + 3] = 255;
  }
  g.putImageData(out, 0, 0);
  // 0 and 100 IRE, and the 70 IRE line skin tones sit near
  g.strokeStyle = "rgba(255,255,255,.16)";
  g.lineWidth = 1;
  for (const ire of [0, 0.3, 0.7, 1]) {
    const y = Math.round((1 - ire) * (H - 1)) + 0.5;
    g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
  }
}

/**
 * A vectorscope: hue as angle, saturation as radius. The six boxes are the
 * primaries at 75% bars, so footage can be checked against a known target.
 */
export function drawVectorscope(img, canvas) {
  const W = canvas.width, H = canvas.height;
  const g = canvas.getContext("2d");
  g.fillStyle = "#0b0e16";
  g.fillRect(0, 0, W, H);
  const cx = W / 2, cy = H / 2, rad = Math.min(W, H) / 2 - 6;
  const acc = new Float32Array(W * H);
  const step = Math.max(1, Math.round(Math.sqrt((img.width * img.height) / 40000)));
  for (let y = 0; y < img.height; y += step) {
    for (let x = 0; x < img.width; x += step) {
      const i = (y * img.width + x) * 4;
      const [, cb, cr] = ycbcr(img.data[i] / 255, img.data[i + 1] / 255, img.data[i + 2] / 255);
      const px = Math.round(cx + cb * 2 * rad), py = Math.round(cy - cr * 2 * rad);
      if (px < 0 || py < 0 || px >= W || py >= H) continue;
      acc[py * W + px] += 1;
    }
  }
  let peak = 0;
  for (let i = 0; i < acc.length; i++) if (acc[i] > peak) peak = acc[i];
  const out = g.getImageData(0, 0, W, H);
  for (let i = 0; i < acc.length; i++) {
    if (!acc[i]) continue;
    const v = Math.sqrt(acc[i] / peak);
    out.data[i * 4] = 90 + 165 * v; out.data[i * 4 + 1] = 240 * v; out.data[i * 4 + 2] = 190 * v;
    out.data[i * 4 + 3] = 255;
  }
  g.putImageData(out, 0, 0);
  g.strokeStyle = "rgba(255,255,255,.18)";
  g.beginPath(); g.arc(cx, cy, rad, 0, Math.PI * 2); g.stroke();
  g.beginPath(); g.arc(cx, cy, rad * 0.5, 0, Math.PI * 2); g.stroke();
  // the primaries at 75%, where a colourist expects them
  const bars = [[1, 0, 0, "R"], [1, 1, 0, "Yl"], [0, 1, 0, "G"], [0, 1, 1, "Cy"], [0, 0, 1, "B"], [1, 0, 1, "Mg"]];
  g.font = "8px ui-monospace, monospace";
  for (const [r, gg, b, name] of bars) {
    const [, cb, cr] = ycbcr(r * 0.75, gg * 0.75, b * 0.75);
    const px = cx + cb * 2 * rad, py = cy - cr * 2 * rad;
    g.strokeStyle = "rgba(255,255,255,.35)";
    g.strokeRect(px - 4, py - 4, 8, 8);
    g.fillStyle = "rgba(255,255,255,.5)";
    g.fillText(name, px + 6, py + 3);
  }
  // the skin-tone line, at 123 degrees — the one landmark worth drawing
  g.strokeStyle = "rgba(240,163,94,.5)";
  g.beginPath();
  g.moveTo(cx, cy);
  g.lineTo(cx + Math.cos((-123 * Math.PI) / 180) * rad, cy + Math.sin((-123 * Math.PI) / 180) * rad);
  g.stroke();
}

/** A histogram: how many pixels at each level, per channel, drawn over each other. */
export function drawHistogram(img, canvas) {
  const W = canvas.width, H = canvas.height;
  const g = canvas.getContext("2d");
  g.fillStyle = "#0b0e16";
  g.fillRect(0, 0, W, H);
  const bins = [new Uint32Array(256), new Uint32Array(256), new Uint32Array(256)];
  for (let i = 0; i < img.data.length; i += 4) {
    bins[0][img.data[i]]++; bins[1][img.data[i + 1]]++; bins[2][img.data[i + 2]]++;
  }
  // The extremes are ignored when scaling: a black frame border would
  // otherwise flatten everything else into the floor.
  let peak = 1;
  for (const b of bins) for (let k = 2; k < 254; k++) if (b[k] > peak) peak = b[k];
  const cols = ["rgba(255,90,90,.75)", "rgba(90,240,150,.75)", "rgba(110,150,255,.75)"];
  g.globalCompositeOperation = "lighter";
  bins.forEach((b, ch) => {
    g.fillStyle = cols[ch];
    for (let k = 0; k < 256; k++) {
      const x = (k / 255) * (W - 1);
      const h = Math.min(1, b[k] / peak) * (H - 2);
      g.fillRect(x, H - h, Math.max(1, W / 256), h);
    }
  });
  g.globalCompositeOperation = "source-over";
  g.strokeStyle = "rgba(255,255,255,.14)";
  for (const q of [0.25, 0.5, 0.75]) {
    const x = Math.round(q * (W - 1)) + 0.5;
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke();
  }
}

/** The numbers under the pictures: what is clipped, and where the frame sits. */
export function frameStats(img) {
  let lo = 0, hi = 0, sum = 0, n = 0, rs = 0, gs = 0, bs = 0;
  const step = Math.max(1, Math.round(Math.sqrt((img.width * img.height) / 60000)));
  for (let y = 0; y < img.height; y += step) {
    for (let x = 0; x < img.width; x += step) {
      const i = (y * img.width + x) * 4;
      const r = img.data[i], g = img.data[i + 1], b = img.data[i + 2];
      const l = R709[0] * r + R709[1] * g + R709[2] * b;
      if (r <= 1 && g <= 1 && b <= 1) lo++;
      if (r >= 254 && g >= 254 && b >= 254) hi++;
      sum += l; rs += r; gs += g; bs += b; n++;
    }
  }
  const mean = sum / Math.max(1, n);
  return {
    mean: mean / 255,
    crushed: lo / Math.max(1, n),
    clipped: hi / Math.max(1, n),
    // A rough cast: how far the channel means are from each other.
    cast: (Math.max(rs, gs, bs) - Math.min(rs, gs, bs)) / Math.max(1, n) / 255,
  };
}
