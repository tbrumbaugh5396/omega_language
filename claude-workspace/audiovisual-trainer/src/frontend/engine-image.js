// Canvas engine: procedural stimuli, convolution, colour science, saliency,
// and the feature extraction the reference analyzer runs on.
//
// Stimuli are generated, never stock. A drill has to produce an unfamiliar
// image every trial or it trains recognition of the picture instead of
// discrimination of the dimension under test.

// ------------------------------------------------------------------ canvas

export function makeCanvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return c;
}

export const ctx2d = (c) => c.getContext("2d", { willReadFrequently: true });

export function cloneImage(img) {
  return new ImageData(new Uint8ClampedArray(img.data), img.width, img.height);
}

export function putImage(canvas, img) {
  ctx2d(canvas).putImageData(img, 0, 0);
  return canvas;
}

export function getImage(canvas) {
  return ctx2d(canvas).getImageData(0, 0, canvas.width, canvas.height);
}

function prng(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
}

// ------------------------------------------------------------------ colour

export const srgbToLinear = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
export const linearToSrgb = (c) => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(Math.max(0, c), 1 / 2.4) - 0.055);

/** Linear sRGB → OKLab. Opponent axes, which is why it behaves. */
export function linearToOklab(r, g, b) {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  ];
}

export function oklabToLinear(L, a, b) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [
    +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ];
}

export const rgbToOklab = (r, g, b) =>
  linearToOklab(srgbToLinear(r / 255), srgbToLinear(g / 255), srgbToLinear(b / 255));

export function oklabToRgb(L, a, b) {
  const [lr, lg, lb] = oklabToLinear(L, a, b);
  return [
    Math.round(Math.max(0, Math.min(1, linearToSrgb(lr))) * 255),
    Math.round(Math.max(0, Math.min(1, linearToSrgb(lg))) * 255),
    Math.round(Math.max(0, Math.min(1, linearToSrgb(lb))) * 255),
  ];
}

export const hex = (r, g, b) =>
  "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");

/** WCAG relative luminance and contrast ratio — the accessibility drill. */
export function relLuminance(r, g, b) {
  const [R, G, B] = [r, g, b].map((v) => srgbToLinear(v / 255));
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}
export function contrastRatio(c1, c2) {
  const a = relLuminance(...c1), b = relLuminance(...c2);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/** Grade: lift/gamma/gain plus saturation, optionally in linear light so the
 *  difference between doing it right and wrong is visible side by side. */
export function grade(img, { lift = 0, gamma = 1, gain = 1, sat = 1, temp = 0,
                             tint = 0, linear = true } = {}) {
  const out = cloneImage(img);
  const d = out.data;
  for (let i = 0; i < d.length; i += 4) {
    let r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
    if (linear) { r = srgbToLinear(r); g = srgbToLinear(g); b = srgbToLinear(b); }
    r = (r + lift) * gain; g = (g + lift) * gain; b = (b + lift) * gain;
    r += temp * 0.08; b -= temp * 0.08;
    g += tint * 0.06;
    r = Math.pow(Math.max(0, r), gamma);
    g = Math.pow(Math.max(0, g), gamma);
    b = Math.pow(Math.max(0, b), gamma);
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    r = lum + (r - lum) * sat; g = lum + (g - lum) * sat; b = lum + (b - lum) * sat;
    if (linear) { r = linearToSrgb(r); g = linearToSrgb(g); b = linearToSrgb(b); }
    d[i] = Math.max(0, Math.min(255, r * 255));
    d[i + 1] = Math.max(0, Math.min(255, g * 255));
    d[i + 2] = Math.max(0, Math.min(255, b * 255));
  }
  return out;
}

// ------------------------------------------------------------------ noise

export function valueNoise2D(seed) {
  const r = prng(seed);
  const perm = new Float32Array(256 * 256);
  for (let i = 0; i < perm.length; i++) perm[i] = r();
  const at = (x, y) => perm[((y & 255) * 256 + (x & 255))];
  const smooth = (t) => t * t * (3 - 2 * t);
  return (x, y) => {
    const xi = Math.floor(x), yi = Math.floor(y);
    const xf = smooth(x - xi), yf = smooth(y - yi);
    const a = at(xi, yi), b = at(xi + 1, yi), c = at(xi, yi + 1), d = at(xi + 1, yi + 1);
    return (a * (1 - xf) + b * xf) * (1 - yf) + (c * (1 - xf) + d * xf) * yf;
  };
}

export function fbm2D(seed, octaves = 5, lacunarity = 2, gainF = 0.5) {
  const n = valueNoise2D(seed);
  return (x, y) => {
    let v = 0, amp = 1, freq = 1, norm = 0;
    for (let o = 0; o < octaves; o++) {
      v += n(x * freq, y * freq) * amp;
      norm += amp;
      amp *= gainF; freq *= lacunarity;
    }
    return v / norm;
  };
}

export function worley2D(seed, cells = 8) {
  const r = prng(seed);
  const pts = [];
  for (let i = 0; i < cells * cells; i++) pts.push([r(), r()]);
  return (x, y) => {
    let best = 1e9;
    for (const [px, py] of pts) {
      const dx = x - px, dy = y - py;
      best = Math.min(best, dx * dx + dy * dy);
    }
    return Math.min(1, Math.sqrt(best) * cells * 0.8);
  };
}

// ------------------------------------------------------------------ scenes

const PALETTES = [
  ["#12202e", "#2c4a63", "#7fa8c9", "#e6cba8", "#f2f0e6"],
  ["#1a1520", "#4a2f3f", "#a8536b", "#e59a6a", "#f4e3c8"],
  ["#0f1f1a", "#274d3f", "#5e9b7d", "#c9d8a5", "#f0f2e4"],
  ["#1d1a2e", "#3b3560", "#6f6bb0", "#c9a8e0", "#efe6f5"],
  ["#241a12", "#4e3620", "#9a6b3c", "#d9ab6b", "#f2e3c8"],
];

const hexToRgb = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

/**
 * A procedural "photograph": graded sky, horizon, a subject with a specular
 * highlight, depth haze and grain. Not art — but it has the statistics a
 * photograph has (low-frequency gradient, a salient subject, fine texture),
 * which is what the grade, blur and saliency drills need.
 */
export function scene(w, h, seed = 1, opts = {}) {
  const c = makeCanvas(w, h);
  const g = ctx2d(c);
  const r = prng(seed);
  const pal = PALETTES[Math.floor(r() * PALETTES.length)].map(hexToRgb);
  const horizon = h * (0.45 + r() * 0.25);

  // sky gradient
  const sky = g.createLinearGradient(0, 0, 0, horizon);
  sky.addColorStop(0, hex(...pal[0]));
  sky.addColorStop(1, hex(...pal[2]));
  g.fillStyle = sky;
  g.fillRect(0, 0, w, horizon);

  // ground
  const ground = g.createLinearGradient(0, horizon, 0, h);
  ground.addColorStop(0, hex(...pal[1]));
  ground.addColorStop(1, hex(...pal[0].map((v) => v * 0.7)));
  g.fillStyle = ground;
  g.fillRect(0, horizon, w, h - horizon);

  // distant shapes, hazed toward the horizon colour
  const layers = 3;
  for (let l = 0; l < layers; l++) {
    const depth = (l + 1) / layers;
    g.globalAlpha = 0.55 + depth * 0.4;
    g.fillStyle = hex(...pal[1].map((v, i) => v * depth + pal[2][i] * (1 - depth)));
    g.beginPath();
    g.moveTo(0, horizon);
    const steps = 6 + Math.floor(r() * 5);
    for (let s = 0; s <= steps; s++) {
      const x = (s / steps) * w;
      const y = horizon - (0.05 + r() * 0.22 * depth) * h;
      g.lineTo(x, y);
    }
    g.lineTo(w, horizon);
    g.closePath();
    g.fill();
  }
  g.globalAlpha = 1;

  // subject: the thing the eye should land on
  if (opts.subject !== false) {
    const sx = w * (0.25 + r() * 0.5), sy = horizon - h * 0.02;
    const sh = h * (0.16 + r() * 0.14);
    g.fillStyle = hex(...pal[0].map((v) => v * 0.5));
    g.beginPath();
    g.ellipse(sx, sy, sh * 0.19, sh * 0.5, 0, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = hex(...pal[4]);
    g.beginPath();
    g.arc(sx - sh * 0.05, sy - sh * 0.28, sh * 0.09, 0, Math.PI * 2);
    g.fill();
  }

  // fine texture — the high band the squint test removes
  const img = getImage(c);
  const d = img.data;
  const grain = opts.grain ?? 10;
  for (let i = 0; i < d.length; i += 4) {
    const n = (r() * 2 - 1) * grain;
    d[i] += n; d[i + 1] += n; d[i + 2] += n;
  }
  putImage(c, img);
  return c;
}

/** A flat layout: grid, rules, blocks. For alignment, gestalt and saliency. */
export function layout(w, h, seed = 1, opts = {}) {
  const c = makeCanvas(w, h);
  const g = ctx2d(c);
  const r = prng(seed);
  g.fillStyle = opts.bg || "#101420";
  g.fillRect(0, 0, w, h);
  const cols = opts.cols || 6;
  const margin = Math.round(w * 0.08);
  const gutter = Math.round(w * 0.02);
  const colW = (w - margin * 2 - gutter * (cols - 1)) / cols;
  const rows = [];
  let y = margin;
  while (y < h - margin) {
    const rh = Math.round(h * (0.04 + r() * 0.09));
    rows.push([y, rh]);
    y += rh + Math.round(h * 0.035);
  }
  const blocks = [];
  for (const [ry, rh] of rows) {
    let cx = margin, c0 = 0;
    while (c0 < cols) {
      const span = 1 + Math.floor(r() * Math.min(3, cols - c0));
      const bw = colW * span + gutter * (span - 1);
      if (r() > 0.25) blocks.push({ x: cx, y: ry, w: bw, h: rh, tone: 0.2 + r() * 0.6 });
      cx += bw + gutter;
      c0 += span;
    }
  }
  return { canvas: c, ctx: g, blocks, margin, colW, gutter, cols };
}

export function drawBlocks(g, blocks, { accent = "#7c9cff" } = {}) {
  for (const b of blocks) {
    g.fillStyle = b.accent ? accent : `rgba(232,235,245,${(0.1 + b.tone * 0.35).toFixed(3)})`;
    g.fillRect(Math.round(b.x), Math.round(b.y), Math.round(b.w), Math.round(b.h));
  }
}

// ------------------------------------------------------------------ filters

/** Direct convolution. Slow and honest — you can watch the kernel work. */
export function convolve(img, kernel, { divisor = null, offset = 0 } = {}) {
  const k = kernel.length;
  const side = Math.round(Math.sqrt(k));
  const half = Math.floor(side / 2);
  const div = divisor ?? (kernel.reduce((a, b) => a + b, 0) || 1);
  const out = cloneImage(img);
  const { width: w, height: h, data: src } = img;
  const dst = out.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let r = 0, g = 0, b = 0;
      for (let ky = 0; ky < side; ky++) {
        for (let kx = 0; kx < side; kx++) {
          const sx = Math.min(w - 1, Math.max(0, x + kx - half));
          const sy = Math.min(h - 1, Math.max(0, y + ky - half));
          const si = (sy * w + sx) * 4;
          const kv = kernel[ky * side + kx];
          r += src[si] * kv; g += src[si + 1] * kv; b += src[si + 2] * kv;
        }
      }
      const di = (y * w + x) * 4;
      dst[di] = r / div + offset;
      dst[di + 1] = g / div + offset;
      dst[di + 2] = b / div + offset;
    }
  }
  return out;
}

export function gaussianKernel(side, sigma) {
  const k = new Array(side * side);
  const half = Math.floor(side / 2);
  let sum = 0;
  for (let y = 0; y < side; y++) {
    for (let x = 0; x < side; x++) {
      const dx = x - half, dy = y - half;
      const v = Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
      k[y * side + x] = v; sum += v;
    }
  }
  return k.map((v) => v / sum);
}

export const KERNELS = {
  identity: [0, 0, 0, 0, 1, 0, 0, 0, 0],
  box: new Array(9).fill(1 / 9),
  gaussian: [1, 2, 1, 2, 4, 2, 1, 2, 1].map((v) => v / 16),
  sharpen: [0, -1, 0, -1, 5, -1, 0, -1, 0],
  edge: [-1, -1, -1, -1, 8, -1, -1, -1, -1],
  emboss: [-2, -1, 0, -1, 1, 1, 0, 1, 2],
  sobelX: [-1, 0, 1, -2, 0, 2, -1, 0, 1],
  sobelY: [-1, -2, -1, 0, 0, 0, 1, 2, 1],
};

/** Separable Gaussian — the reason big blurs are affordable at all. */
export function blurFast(img, radius) {
  if (radius < 1) return cloneImage(img);
  const sigma = radius / 2;
  const size = Math.max(3, Math.ceil(radius) * 2 + 1);
  const half = Math.floor(size / 2);
  const k = new Float32Array(size);
  let sum = 0;
  for (let i = 0; i < size; i++) {
    k[i] = Math.exp(-((i - half) ** 2) / (2 * sigma * sigma));
    sum += k[i];
  }
  for (let i = 0; i < size; i++) k[i] /= sum;

  const { width: w, height: h } = img;
  const pass = (src, horiz) => {
    const dst = new Uint8ClampedArray(src.length);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let r = 0, g = 0, b = 0;
        for (let i = 0; i < size; i++) {
          const o = i - half;
          const sx = horiz ? Math.min(w - 1, Math.max(0, x + o)) : x;
          const sy = horiz ? y : Math.min(h - 1, Math.max(0, y + o));
          const si = (sy * w + sx) * 4;
          r += src[si] * k[i]; g += src[si + 1] * k[i]; b += src[si + 2] * k[i];
        }
        const di = (y * w + x) * 4;
        dst[di] = r; dst[di + 1] = g; dst[di + 2] = b; dst[di + 3] = src[di + 3];
      }
    }
    return dst;
  };
  return new ImageData(pass(pass(img.data, true), false), w, h);
}

/** Directional (motion) blur — a line kernel, and it looks like one. */
export function motionBlur(img, length, angleDeg) {
  const a = (angleDeg * Math.PI) / 180;
  const dx = Math.cos(a), dy = Math.sin(a);
  const out = cloneImage(img);
  const { width: w, height: h, data: src } = img;
  const dst = out.data;
  const n = Math.max(2, Math.round(length));
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let r = 0, g = 0, b = 0;
      for (let i = 0; i < n; i++) {
        const t = i - n / 2;
        const sx = Math.min(w - 1, Math.max(0, Math.round(x + dx * t)));
        const sy = Math.min(h - 1, Math.max(0, Math.round(y + dy * t)));
        const si = (sy * w + sx) * 4;
        r += src[si]; g += src[si + 1]; b += src[si + 2];
      }
      const di = (y * w + x) * 4;
      dst[di] = r / n; dst[di + 1] = g / n; dst[di + 2] = b / n;
    }
  }
  return out;
}

/** Radial/zoom blur — samples along the ray from centre. */
export function radialBlur(img, strength = 0.06, steps = 12) {
  const out = cloneImage(img);
  const { width: w, height: h, data: src } = img;
  const dst = out.data;
  const cx = w / 2, cy = h / 2;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let r = 0, g = 0, b = 0;
      for (let i = 0; i < steps; i++) {
        const s = 1 - (i / steps) * strength;
        const sx = Math.min(w - 1, Math.max(0, Math.round(cx + (x - cx) * s)));
        const sy = Math.min(h - 1, Math.max(0, Math.round(cy + (y - cy) * s)));
        const si = (sy * w + sx) * 4;
        r += src[si]; g += src[si + 1]; b += src[si + 2];
      }
      const di = (y * w + x) * 4;
      dst[di] = r / steps; dst[di + 1] = g / steps; dst[di + 2] = b / steps;
    }
  }
  return out;
}

/** Lens blur: a disc kernel, so highlights bloom into aperture shapes. */
export function lensBlur(img, radius = 4) {
  const side = radius * 2 + 1;
  const k = new Array(side * side).fill(0);
  let count = 0;
  for (let y = 0; y < side; y++) {
    for (let x = 0; x < side; x++) {
      const dx = x - radius, dy = y - radius;
      if (dx * dx + dy * dy <= radius * radius) { k[y * side + x] = 1; count++; }
    }
  }
  return convolve(img, k, { divisor: count });
}

// ------------------------------------------------------------------ analysis

/** Centre-surround saliency, Itti-Koch flavoured: intensity contrast plus
 *  the two opponent colour channels, summed across two scales. */
export function saliencyMap(img) {
  const { width: w, height: h } = img;
  const fine = blurFast(img, 2), coarse = blurFast(img, 12);
  const out = new Float32Array(w * h);
  let max = 0;
  for (let i = 0, p = 0; i < out.length; i++, p += 4) {
    const fi = (fine.data[p] + fine.data[p + 1] + fine.data[p + 2]) / 3;
    const ci = (coarse.data[p] + coarse.data[p + 1] + coarse.data[p + 2]) / 3;
    const intensity = Math.abs(fi - ci);
    const rgF = fine.data[p] - fine.data[p + 1], rgC = coarse.data[p] - coarse.data[p + 1];
    const byF = fine.data[p + 2] - (fine.data[p] + fine.data[p + 1]) / 2;
    const byC = coarse.data[p + 2] - (coarse.data[p] + coarse.data[p + 1]) / 2;
    const v = intensity + Math.abs(rgF - rgC) * 0.7 + Math.abs(byF - byC) * 0.7;
    out[i] = v;
    if (v > max) max = v;
  }
  // Centre bias: gaze starts in the middle and photographers know it.
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const dx = (x / w - 0.5) * 2, dy = (y / h - 0.5) * 2;
      out[y * w + x] *= Math.exp(-(dx * dx + dy * dy) * 0.7);
    }
  }
  max = 0;
  for (const v of out) if (v > max) max = v;
  if (max > 0) for (let i = 0; i < out.length; i++) out[i] /= max;
  return { data: out, width: w, height: h };
}

export function saliencyPeak(map) {
  // Blur the map first: a single hot pixel is not where a fixation lands.
  const { width: w, height: h, data } = map;
  const sm = new Float32Array(data.length);
  const r = Math.max(2, Math.round(Math.min(w, h) / 24));
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0, n = 0;
      for (let dy = -r; dy <= r; dy += 2) {
        for (let dx = -r; dx <= r; dx += 2) {
          const sx = x + dx, sy = y + dy;
          if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
          s += data[sy * w + sx]; n++;
        }
      }
      sm[y * w + x] = s / Math.max(1, n);
    }
  }
  let best = -1, bx = 0, by = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (sm[y * w + x] > best) { best = sm[y * w + x]; bx = x; by = y; }
    }
  }
  return { x: bx, y: by, value: best, smooth: sm };
}

export function saliencyToCanvas(map) {
  const c = makeCanvas(map.width, map.height);
  const img = ctx2d(c).createImageData(map.width, map.height);
  for (let i = 0; i < map.data.length; i++) {
    const v = map.data[i];
    // Warm ramp: dark → amber → white, so peaks read at a glance.
    img.data[i * 4] = Math.min(255, v * 420);
    img.data[i * 4 + 1] = Math.min(255, Math.max(0, v - 0.25) * 340);
    img.data[i * 4 + 2] = Math.min(255, Math.max(0, v - 0.6) * 500);
    img.data[i * 4 + 3] = 255;
  }
  putImage(c, img);
  return c;
}

/** k-means palette extraction in OKLab — perceptual distance, not RGB. */
export function palette(img, k = 6, iterations = 8) {
  const px = [];
  const stride = Math.max(4, Math.floor(Math.sqrt((img.width * img.height) / 4000))) * 4;
  for (let i = 0; i < img.data.length; i += stride) {
    px.push(rgbToOklab(img.data[i], img.data[i + 1], img.data[i + 2]));
  }
  if (!px.length) return [];
  let cents = [];
  for (let i = 0; i < k; i++) cents.push(px[Math.floor((i + 0.5) * px.length / k)]);
  let assign = new Array(px.length).fill(0);
  for (let it = 0; it < iterations; it++) {
    for (let i = 0; i < px.length; i++) {
      let best = 0, bd = 1e9;
      for (let c = 0; c < cents.length; c++) {
        const d = (px[i][0] - cents[c][0]) ** 2 + (px[i][1] - cents[c][1]) ** 2 + (px[i][2] - cents[c][2]) ** 2;
        if (d < bd) { bd = d; best = c; }
      }
      assign[i] = best;
    }
    const sums = cents.map(() => [0, 0, 0, 0]);
    for (let i = 0; i < px.length; i++) {
      const s = sums[assign[i]];
      s[0] += px[i][0]; s[1] += px[i][1]; s[2] += px[i][2]; s[3]++;
    }
    cents = sums.map((s, i) => (s[3] ? [s[0] / s[3], s[1] / s[3], s[2] / s[3]] : cents[i]));
  }
  const counts = cents.map(() => 0);
  for (const a of assign) counts[a]++;
  return cents
    .map((c, i) => ({
      oklab: c,
      rgb: oklabToRgb(c[0], c[1], c[2]),
      share: counts[i] / px.length,
      chroma: Math.hypot(c[1], c[2]),
      L: c[0],
    }))
    .filter((c) => c.share > 0.005)
    .sort((a, b) => b.share - a.share)
    .map((c) => ({ ...c, hex: hex(...c.rgb) }));
}

/** The visual half of the Part 6 feature vocabulary. */
export function imageFeatures(img) {
  const { width: w, height: h, data } = img;
  const lum = new Float32Array(w * h);
  for (let i = 0, p = 0; i < lum.length; i++, p += 4) {
    lum[i] = 0.2126 * data[p] + 0.7152 * data[p + 1] + 0.0722 * data[p + 2];
  }
  // Contrast distribution
  let sum = 0, min = 255, max = 0;
  for (const v of lum) { sum += v; min = Math.min(min, v); max = Math.max(max, v); }
  const mean = sum / lum.length;
  let varr = 0;
  for (const v of lum) varr += (v - mean) ** 2;
  const sd = Math.sqrt(varr / lum.length);

  // Edge statistics (Sobel magnitude)
  let edgeSum = 0, edgeCount = 0;
  const orient = new Array(8).fill(0);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const at = (xx, yy) => lum[yy * w + xx];
      const gx = -at(x - 1, y - 1) + at(x + 1, y - 1) - 2 * at(x - 1, y) + 2 * at(x + 1, y) - at(x - 1, y + 1) + at(x + 1, y + 1);
      const gy = -at(x - 1, y - 1) - 2 * at(x, y - 1) - at(x + 1, y - 1) + at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1);
      const m = Math.hypot(gx, gy);
      edgeSum += m;
      if (m > 60) {
        edgeCount++;
        const a = ((Math.atan2(gy, gx) + Math.PI) / Math.PI) * 4;
        orient[Math.min(7, Math.floor(a))]++;
      }
    }
  }
  const px = (w - 2) * (h - 2);

  // Spatial frequency profile: energy remaining at successive blur radii.
  const bands = [];
  let prev = img;
  for (const radius of [1, 2, 4, 8, 16]) {
    const b = blurFast(img, radius);
    let d = 0;
    for (let i = 0; i < prev.data.length; i += 4) d += Math.abs(prev.data[i] - b.data[i]);
    bands.push(d / (prev.data.length / 4));
    prev = b;
  }
  const bandMax = Math.max(...bands, 1e-9);

  const pal = palette(img, 6);
  // Palette entropy: how spread the image is across its own clusters.
  const entropy = -pal.reduce((a, c) => a + (c.share > 0 ? c.share * Math.log2(c.share) : 0), 0);

  return {
    width: w, height: h,
    meanLum: +mean.toFixed(1),
    contrastSd: +sd.toFixed(1),
    dynamicRange: +(max - min).toFixed(0),
    edgeDensity: +(edgeCount / px).toFixed(4),
    edgeStrength: +(edgeSum / px).toFixed(2),
    orientation: orient.map((o) => +(o / Math.max(1, edgeCount)).toFixed(3)),
    freqBands: bands.map((b) => +(b / bandMax).toFixed(3)),
    paletteEntropy: +entropy.toFixed(2),
    palette: pal,
  };
}

/** Grid detection: column edges show up as peaks in the vertical projection
 *  of edge energy. Crude, but it finds a real grid on a real layout. */
export function detectGrid(img) {
  const { width: w, height: h, data } = img;
  const colEnergy = new Float32Array(w);
  for (let x = 1; x < w; x++) {
    let e = 0;
    for (let y = 0; y < h; y++) {
      const a = (y * w + x) * 4, b = (y * w + x - 1) * 4;
      e += Math.abs(data[a] - data[b]) + Math.abs(data[a + 1] - data[b + 1]) + Math.abs(data[a + 2] - data[b + 2]);
    }
    colEnergy[x] = e / h;
  }
  const mean = colEnergy.reduce((a, b) => a + b, 0) / w;
  const peaks = [];
  for (let x = 2; x < w - 2; x++) {
    if (colEnergy[x] > mean * 2.2 && colEnergy[x] >= colEnergy[x - 1] && colEnergy[x] > colEnergy[x + 1]) {
      if (!peaks.length || x - peaks[peaks.length - 1] > w * 0.02) peaks.push(x);
    }
  }
  // Most common spacing between peaks → candidate column module.
  const gaps = [];
  for (let i = 1; i < peaks.length; i++) gaps.push(peaks[i] - peaks[i - 1]);
  gaps.sort((a, b) => a - b);
  const module = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
  let maxE = 1e-9;
  for (const v of colEnergy) if (v > maxE) maxE = v;
  return {
    peaks,
    module,
    columns: module ? Math.round(w / module) : 0,
    energy: Array.from(colEnergy, (v) => +(v / maxE).toFixed(3)),
  };
}

// ------------------------------------------------------------------ easing

export const EASINGS = {
  linear: (t) => t,
  easeIn: (t) => t * t * t,
  easeOut: (t) => 1 - Math.pow(1 - t, 3),
  easeInOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  back: (t) => { const c = 1.70158 + 1; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
  elastic: (t) => (t === 0 || t === 1 ? t : Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1),
  bounce: (t) => {
    const n = 7.5625, d = 2.75;
    if (t < 1 / d) return n * t * t;
    if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75;
    if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375;
    return n * (t -= 2.625 / d) * t + 0.984375;
  },
};
