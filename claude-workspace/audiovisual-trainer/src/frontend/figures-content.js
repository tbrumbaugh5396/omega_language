// The live figures for the course docs.
//
// Keyed by the filename the markdown already references, so a doc that says
// `![...](figures/srgb-transfer.svg)` gets the interactive version here and
// still renders as ordinary markdown anywhere else.
//
// The split follows the course README's own rule. Plots of data or of a
// closed-form function are drawn from the maths, so they are reproducible and
// carry no claim about your screen. Display artifacts — banding, dither,
// aliasing — are rendered at one canvas pixel per device pixel, because a
// resampled artifact figure is a statement about the scaler rather than about
// the signal, and is worse than no figure at all.

import * as F from "./figures.js";

const SRGB = F.srgbToLin, TOSRGB = F.linToSrgb;

// ------------------------------------------------------------------ Module 3

const gradientBars = (t) => {
  // Endpoints are encoded sRGB red and green, exactly as the module states.
  const aE = [1, 0, 0], bE = [0, 1, 0];
  const encoded = aE.map((v, i) => v * (1 - t) + bE[i] * t);

  const aL = aE.map(SRGB), bL = bE.map(SRGB);
  const linear = aL.map((v, i) => TOSRGB(v * (1 - t) + bL[i] * t));

  const aO = F.linearToOklab(...aL), bO = F.linearToOklab(...bL);
  const mixed = aO.map((v, i) => v * (1 - t) + bO[i] * t);
  const okl = F.oklabToLinear(...mixed).map((v) => TOSRGB(Math.max(0, Math.min(1, v))));

  return [encoded, linear, okl];
};

const gradientTriptych = {
  id: "gradient-triptych",
  caption: "Red to green interpolated three ways: encoded sRGB (top), linear light (middle), Oklab (bottom).",
  note: "Rendered at one canvas pixel per device pixel, so the sag in the top " +
        "bar is the signal and not a resampling artifact. Same two endpoints in all three.",
  runtime: "canvas2d",
  exact: true,
  aspect: 0.30,
  draw(g, w, h) {
    const gap = Math.max(6, Math.round(h * 0.05));
    const barH = Math.floor((h - gap * 2) / 3);
    g.clearRect(0, 0, w, h);
    for (let x = 0; x < w; x++) {
      const bars = gradientBars(x / (w - 1));
      bars.forEach((c, i) => {
        g.fillStyle = `rgb(${c.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255)).join(",")})`;
        g.fillRect(x, i * (barH + gap), 1, barH);
      });
    }
  },
};

const gradientLuminance = {
  id: "gradient-luminance",
  caption: "Relative luminance Y along each interpolation.",
  note: "The encoded-sRGB curve dips below both endpoints — no physical mixture " +
        "of two lights can do that. That trough is the brown sag you can see in " +
        "the bar above it.",
  runtime: "canvas2d",
  aspect: 0.42,
  draw(g, w, h, t, k, s) {
    const { X, Y } = F.plotFrame(g, w, h, { xLabel: "t", yLabel: "Y", s,
      xMin: 0, xMax: 1, yMin: 0, yMax: 0.8 });
    const names = ["encoded sRGB", "linear light", "Oklab"];
    const cols = ["#D85A30", "#EF9F27", "#7F77DD"];
    for (let bar = 0; bar < 3; bar++) {
      const pts = [];
      for (let i = 0; i <= 200; i++) {
        const tt = i / 200;
        const c = gradientBars(tt)[bar];
        const lum = c.reduce((acc, v, ch) => acc + SRGB(Math.max(0, Math.min(1, v))) * F.LUMA[ch], 0);
        pts.push([X(tt), Y(lum)]);
      }
      F.plotLine(g, pts, cols[bar], { s });
    }
    F.legend(g, names.map((n, i) => [n, cols[i]]), w - 120 * s, 26 * s, s);
  },
};

// ------------------------------------------------------------------ Module 5

const srgbTransfer = {
  id: "srgb-transfer",
  caption: "Left: the sRGB decoding curve against a pure 2.2 power law. Right: the Weber ratio ΔL/L per code step.",
  note: "The right panel is the whole argument for gamma encoding. A linear " +
        "8-bit encoding's relative step explodes toward black; sRGB flattens it " +
        "to roughly 1% across most of the range. The spike at the very bottom " +
        "is the linear toe.",
  runtime: "canvas2d",
  aspect: 0.40,
  draw(g, w, h, t, k, s) {
    const half = w / 2;
    g.clearRect(0, 0, w, h);

    g.save();
    g.beginPath(); g.rect(0, 0, half, h); g.clip();
    const a = F.plotFrame(g, half, h, { xLabel: "code value", yLabel: "linear light",
      s, xMin: 0, xMax: 1, yMin: 0, yMax: 1, title: "Decoding curve" });
    const curve = (fn) => Array.from({ length: 200 }, (_, i) => {
      const v = i / 199; return [a.X(v), a.Y(fn(v))];
    });
    F.plotLine(g, curve((v) => v), F.AX, { s, dash: [2, 3] });
    F.plotLine(g, curve((v) => Math.pow(v, 2.2)), "#D85A30", { s, dash: [5, 4] });
    F.plotLine(g, curve(SRGB), "#7F77DD", { s });
    F.legend(g, [["sRGB EOTF", "#7F77DD"], ["x^2.2", "#D85A30"], ["identity", F.AX]],
      42 * s, 30 * s, s);
    g.restore();

    g.save();
    g.translate(half, 0);
    g.beginPath(); g.rect(0, 0, half, h); g.clip();
    const b = F.plotFrame(g, half, h, { xLabel: "code value", yLabel: "ΔL / L",
      s, xMin: 1, xMax: 255, yMin: 0.002, yMax: 2, logY: true,
      title: "Weber ratio per step" });
    const linPts = [], srgbPts = [];
    for (let c = 1; c < 256; c++) {
      const linL = c / 255, linPrev = (c - 1) / 255;
      linPts.push([b.X(c), b.Y((linL - linPrev) / Math.max(linL, 1e-9))]);
      const gL = SRGB(c / 255), gPrev = SRGB((c - 1) / 255);
      srgbPts.push([b.X(c), b.Y((gL - gPrev) / Math.max(gL, 1e-9))]);
    }
    F.plotLine(g, linPts, "#D85A30", { s });
    F.plotLine(g, srgbPts, "#7F77DD", { s });
    // 1% is roughly the Weber fraction for luminance
    g.save(); g.strokeStyle = F.AX; g.setLineDash([3 * s, 3 * s]); g.lineWidth = 1 * s;
    g.beginPath(); g.moveTo(b.X(1), b.Y(0.01)); g.lineTo(b.X(255), b.Y(0.01)); g.stroke();
    g.restore();
    F.legend(g, [["linear 8-bit", "#D85A30"], ["sRGB 8-bit", "#7F77DD"]], half - 108 * s, 30 * s, s);
    g.restore();
  },
};

const bandingDither = {
  id: "banding-dither",
  caption: "A near-black ramp quantised to a few bits: no dither, ordered (Bayer), and error-diffusion-style noise.",
  note: "One canvas pixel per device pixel. Lower the bit depth until you see " +
        "the steps, then compare the three strips — dither does not add " +
        "information, it trades a visible edge for invisible noise.",
  runtime: "canvas2d",
  exact: true,
  aspect: 0.34,
  knobs: [["bits", 2, 8, 4, (v) => v.toFixed(0)],
          ["max level", 0.05, 1, 0.25, (v) => v.toFixed(2)]],
  draw(g, w, h, t, k) {
    const bits = Math.max(1, Math.round(k[0]));
    const levels = Math.pow(2, bits) - 1;
    const top = k[1];
    const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
    const gap = Math.max(4, Math.round(h * 0.04));
    const barH = Math.floor((h - gap * 2) / 3);
    const img = g.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      const band = Math.floor(y / (barH + gap));
      if (band > 2 || y % (barH + gap) >= barH) continue;
      for (let x = 0; x < w; x++) {
        const lin = (x / (w - 1)) * top;
        let v = TOSRGB(lin);
        if (band === 1) v += (BAYER[y & 3][x & 3] / 16 - 0.5) / levels;
        if (band === 2) v += (Math.random() - 0.5) / levels;
        const q = Math.round(Math.max(0, Math.min(1, v)) * levels) / levels;
        const px = Math.round(q * 255);
        const i = (y * w + x) * 4;
        img.data[i] = img.data[i + 1] = img.data[i + 2] = px;
        img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  },
};

const zonePlate = {
  id: "zone-plate",
  caption: "A zone plate: frequency rises with radius until it passes what the grid can carry.",
  note: "Sample count 1 is point sampling — the rings you see beyond the " +
        "Nyquist limit are aliases, not signal. Raise it and they resolve into " +
        "grey, which is the honest answer. Rendered at device resolution.",
  runtime: "glsl",
  exact: true,
  animated: false,
  aspect: 0.45,
  knobs: [["frequency", 20, 400, 140, (v) => v.toFixed(0)],
          ["samples per axis", 1, 4, 1, (v) => v.toFixed(0)]],
  source: `
float plate(vec2 p, float k) {
  float r = length(p);
  return 0.5 + 0.5 * cos(k * r * r);
}
void main() {
  vec2 c = (gl_FragCoord.xy - 0.5 * u_resolution) / u_resolution.y;
  float k = u_k.x;
  int n = int(max(1.0, floor(u_k.y + 0.5)));
  float acc = 0.0;
  for (int j = 0; j < 4; j++) {
    for (int i = 0; i < 4; i++) {
      if (i >= n || j >= n) continue;
      // Supersample on a regular sub-grid: averaging before quantising is
      // the whole of antialiasing.
      vec2 off = (vec2(float(i), float(j)) + 0.5) / float(n) - 0.5;
      vec2 q = (gl_FragCoord.xy + off - 0.5 * u_resolution) / u_resolution.y;
      acc += plate(q, k);
    }
  }
  acc /= float(n * n);
  fragColor = vec4(vec3(acc), 1.0);
}`,
};

// ------------------------------------------------------------------ Module 7

const smoothstepContinuity = {
  id: "smoothstep-continuity",
  caption: "Value, first derivative and second derivative of the linear, cubic and quintic interpolants.",
  note: "The middle panel is why smoothstep beats linear: the derivative " +
        "reaches zero at both ends, so there is no kink where the ramp meets " +
        "the flat region. The right panel is why Perlin moved to the quintic — " +
        "the cubic's second derivative is nonzero at t=0 and t=1, which is " +
        "exactly the lattice boundary.",
  runtime: "canvas2d",
  aspect: 0.34,
  draw(g, w, h, t, k, s) {
    g.clearRect(0, 0, w, h);
    const third = w / 3;
    const curves = [
      ["linear", "#888888", (x) => x, () => 1, () => 0],
      ["cubic", "#7F77DD", (x) => 3 * x * x - 2 * x ** 3, (x) => 6 * x - 6 * x * x, (x) => 6 - 12 * x],
      ["quintic", "#1D9E75",
        (x) => 6 * x ** 5 - 15 * x ** 4 + 10 * x ** 3,
        (x) => 30 * x ** 4 - 60 * x ** 3 + 30 * x * x,
        (x) => 120 * x ** 3 - 180 * x * x + 60 * x],
    ];
    const panels = [["S(t)", 2, 0, 1], ["S'(t)", 3, 0, 2], ["S''(t)", 4, -8, 8]];
    panels.forEach(([title, idx, yMin, yMax], p) => {
      g.save();
      g.translate(p * third, 0);
      g.beginPath(); g.rect(0, 0, third, h); g.clip();
      const ax = F.plotFrame(g, third, h, { xLabel: "t", s, xMin: 0, xMax: 1,
        yMin, yMax, title });
      if (yMin < 0) {
        g.save(); g.strokeStyle = F.AX; g.lineWidth = 0.6 * s;
        g.beginPath(); g.moveTo(ax.X(0), ax.Y(0)); g.lineTo(ax.X(1), ax.Y(0)); g.stroke();
        g.restore();
      }
      for (const c of curves) {
        const fn = c[idx];
        const pts = Array.from({ length: 200 }, (_, i) => {
          const x = i / 199; return [ax.X(x), ax.Y(fn(x))];
        });
        F.plotLine(g, pts, c[1], { s, dash: c[0] === "linear" ? [4, 3] : null });
      }
      if (p === 0) F.legend(g, curves.map((c) => [c[0], c[1]]), 44 * s, 30 * s, s);
      g.restore();
    });
  },
};

const sdfAntialias = {
  id: "sdf-antialias",
  caption: "The same circle with a hard step, a fixed-width smoothstep, and fwidth-based antialiasing.",
  note: "Zoom your browser and watch the middle band: a fixed edge width is " +
        "correct at exactly one scale. fwidth measures the screen-space " +
        "derivative, so the edge stays one pixel wide at any scale — this is " +
        "where Module 5's sampling argument pays off in Module 7.",
  runtime: "glsl",
  animated: false,
  aspect: 0.34,
  knobs: [["radius", 0.1, 0.42, 0.3, (v) => v.toFixed(2)],
          ["fixed width", 0.001, 0.08, 0.02, (v) => v.toFixed(3)]],
  source: `
float sdCircle(vec2 p, float r) { return length(p) - r; }
void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float band = floor(uv.x * 3.0);
  vec2 p = (gl_FragCoord.xy - 0.5 * u_resolution) / u_resolution.y;
  p.x = mod(p.x + 0.5 * u_resolution.x / u_resolution.y, u_resolution.x / u_resolution.y / 3.0)
        - 0.5 * u_resolution.x / u_resolution.y / 3.0;
  float d = sdCircle(p, u_k.x);
  float a;
  if (band < 1.0)      a = 1.0 - step(0.0, d);          // hard
  else if (band < 2.0) a = 1.0 - smoothstep(0.0, u_k.y, d);
  else {
    // One pixel, whatever a pixel currently is.
    float px = fwidth(d);
    a = 1.0 - smoothstep(-px, px, d);
  }
  vec3 col = mix(vec3(0.043, 0.055, 0.086), vec3(0.49, 0.61, 1.0), a);
  fragColor = vec4(col, 1.0);
}`,
};

// ------------------------------------------------------------------ Module 1

const metamericPair = {
  id: "metameric-pair",
  caption: "Two different spectra with identical XYZ, built by adding a metameric black.",
  note: "The dashed curve is the first spectrum plus a vector from the null " +
        "space of the colour-matching matrix. Their tristimulus values agree to " +
        "the printed precision because the difference is orthogonal to all three " +
        "matching functions — that is metamerism, constructed rather than asserted. " +
        "Colour-matching functions here are the Wyman–Sloan–Shirley analytic fit " +
        "to the CIE 1931 2° observer, not the tabulated data.",
  runtime: "canvas2d",
  aspect: 0.44,
  knobs: [["metameric black amount", 0, 1, 0.6, (v) => v.toFixed(2)],
          ["black shape", 1, 6, 3, (v) => v.toFixed(0)]],
  draw(g, w, h, t, k, s) {
    const lam = F.LAMBDAS;
    // A smooth, plausible reflected spectrum to start from.
    const bell = (l, mu, w) => Math.exp(-(((l - mu) / w) ** 2));
    const base = lam.map((l) => 0.35 + 0.3 * bell(l, 560, 90) + 0.18 * bell(l, 460, 45));
    const cycles = Math.round(k[1]);
    const black = F.metamericBlack((l) => Math.sin((cycles * Math.PI * (l - 380)) / 400));

    // Scale so the second spectrum stays non-negative and on-scale.
    let maxNeg = 0;
    for (let i = 0; i < base.length; i++) {
      if (black[i] < 0) maxNeg = Math.max(maxNeg, -black[i] / Math.max(base[i], 1e-6));
    }
    const alpha = (k[0] * 0.98) / Math.max(maxNeg, 1e-6);
    const other = base.map((v, i) => v + alpha * black[i]);

    const xyz1 = F.spdToXYZ(base), xyz2 = F.spdToXYZ(other);
    const top = Math.max(...base, ...other, 0.9);

    const { X, Y } = F.plotFrame(g, w, h, { xLabel: "wavelength (nm)",
      yLabel: "reflectance", s, xMin: 380, xMax: 780, yMin: 0, yMax: top * 1.08 });
    F.plotLine(g, lam.map((l, i) => [X(l), Y(base[i])]), "#7F77DD", { s });
    F.plotLine(g, lam.map((l, i) => [X(l), Y(other[i])]), "#EF9F27", { s, dash: [5, 4] });

    // The colour both spectra produce, shown as a patch.
    const c = F.xyzToSrgb255(xyz1[0] / 100, xyz1[1] / 100, xyz1[2] / 100);
    g.save();
    g.fillStyle = `rgb(${c.rgb.join(",")})`;
    g.fillRect(w - 62 * s, 20 * s, 44 * s, 24 * s);
    g.strokeStyle = F.AX; g.lineWidth = 1 * s;
    g.strokeRect(w - 62 * s, 20 * s, 44 * s, 24 * s);
    g.fillStyle = F.AX;
    g.font = `${9 * s}px ui-monospace, monospace`;
    const fmt = (v) => v.toFixed(2);
    g.fillText(`XYZ  ${fmt(xyz1[0])} ${fmt(xyz1[1])} ${fmt(xyz1[2])}`, 44 * s, 20 * s);
    g.fillText(`XYZ  ${fmt(xyz2[0])} ${fmt(xyz2[1])} ${fmt(xyz2[2])}`, 44 * s, 33 * s);
    g.restore();
    F.legend(g, [["spectrum A", "#7F77DD"], ["A + metameric black", "#EF9F27"]],
      44 * s, 52 * s, s);
  },
};

const coneOverlap = {
  id: "colour-matching-functions",
  caption: "The CIE 1931 2° colour-matching functions.",
  note: "x̄ has two lobes because the matching experiment allowed negative " +
        "primaries and XYZ was constructed to avoid them. These are the " +
        "Wyman–Sloan–Shirley analytic fit, accurate to a fraction of a percent; " +
        "swap in the CVRL tables when precision matters.",
  runtime: "canvas2d",
  aspect: 0.42,
  draw(g, w, h, t, k, s) {
    const { X, Y } = F.plotFrame(g, w, h, { xLabel: "wavelength (nm)",
      yLabel: "response", s, xMin: 380, xMax: 780, yMin: 0, yMax: 2.0 });
    const cols = ["#D85A30", "#1D9E75", "#7F77DD"];
    for (let ch = 0; ch < 3; ch++) {
      const pts = [];
      for (let l = 380; l <= 780; l += 2) pts.push([X(l), Y(F.cmf(l)[ch])]);
      F.plotLine(g, pts, cols[ch], { s });
    }
    F.legend(g, [["x̄", cols[0]], ["ȳ", cols[1]], ["z̄", cols[2]]], w - 70 * s, 30 * s, s);
  },
};

// ------------------------------------------------------------------ Module 2

const chromaticity = {
  id: "chromaticity-diagram",
  caption: "The CIE 1931 chromaticity diagram with the sRGB, Display P3 and Rec.2020 primaries.",
  note: "This figure cannot be correct, and neither can any version you have " +
        "seen. Most of the horseshoe lies outside sRGB, so drawing it on an " +
        "sRGB screen means depicting unreachable colours with reachable ones. " +
        "Everything outside the sRGB triangle is clipped, and the further out " +
        "it is the more of a lie it becomes. Read the shape, not the colours.",
  runtime: "canvas2d",
  aspect: 0.78,
  maxWidth: 460,
  draw(g, w, h, t, k, s) {
    const pad = 34 * s;
    const X = (x) => pad + x * (w - pad - 10 * s) / 0.8;
    const Y = (y) => (h - pad) - y * (h - pad - 10 * s) / 0.9;
    g.clearRect(0, 0, w, h);

    // spectral locus
    const locus = [];
    for (let l = 380; l <= 700; l += 2) {
      const [cx, cy, cz] = F.cmf(l);
      const sum = cx + cy + cz;
      if (sum > 1e-6) locus.push([cx / sum, cy / sum]);
    }

    // Fill by testing membership in the locus polygon. Out-of-gamut points are
    // clipped, which is exactly the dishonesty the caption admits to.
    const img = g.createImageData(w, h);
    const inside = (px, py) => {
      let hit = false;
      for (let i = 0, j = locus.length - 1; i < locus.length; j = i++) {
        const [xi, yi] = locus[i], [xj, yj] = locus[j];
        if ((yi > py) !== (yj > py) &&
            px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    };
    for (let py = 0; py < h; py++) {
      for (let px = 0; px < w; px++) {
        const cx = ((px - pad) / (w - pad - 10 * s)) * 0.8;
        const cy = ((h - pad - py) / (h - pad - 10 * s)) * 0.9;
        const i = (py * w + px) * 4;
        if (cx <= 0 || cy <= 0 || !inside(cx, cy)) { img.data[i + 3] = 0; continue; }
        const Yv = 1, Xv = (cx / cy) * Yv, Zv = ((1 - cx - cy) / cy) * Yv;
        const { rgb } = F.xyzToSrgb255(Xv * 0.35, Yv * 0.35, Zv * 0.35);
        img.data[i] = rgb[0]; img.data[i + 1] = rgb[1]; img.data[i + 2] = rgb[2];
        img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);

    g.save();
    g.strokeStyle = F.AX; g.lineWidth = 1 * s;
    g.beginPath(); g.moveTo(pad, 6 * s); g.lineTo(pad, h - pad); g.lineTo(w - 8 * s, h - pad); g.stroke();
    g.font = `${10 * s}px ui-monospace, monospace`;
    g.fillStyle = F.AX;
    g.fillText("x", w / 2, h - 10 * s);
    g.fillText("y", 10 * s, h / 2);

    const gamuts = [
      ["sRGB", "#e8ebf5", [[0.64, 0.33], [0.30, 0.60], [0.15, 0.06]]],
      ["P3", "#EF9F27", [[0.680, 0.320], [0.265, 0.690], [0.150, 0.060]]],
      ["Rec.2020", "#1D9E75", [[0.708, 0.292], [0.170, 0.797], [0.131, 0.046]]],
    ];
    gamuts.forEach(([name, col, tri], i) => {
      g.strokeStyle = col;
      g.lineWidth = 1.4 * s;
      g.beginPath();
      tri.forEach(([x, y], j) => (j ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))));
      g.closePath();
      g.stroke();
      g.fillStyle = col;
      g.fillText(name, w - 92 * s, 22 * s + i * 13 * s);
    });
    g.restore();
  },
};

// ------------------------------------------------------------------ Module 0

const wienPeaks = {
  id: "planck-peaks",
  caption: "Planck's law at three temperatures, each normalised, with Wien's peak marked.",
  note: "The peak moves as 1/T — that is Wien's displacement law, and it is why " +
        "a tungsten bulb is orange and daylight is not. Normalised per curve, " +
        "because the absolute radiance at 6500 K dwarfs the others.",
  runtime: "canvas2d",
  aspect: 0.42,
  knobs: [["temperature K", 1500, 9000, 6500, (v) => v.toFixed(0)]],
  draw(g, w, h, t, k, s) {
    const { X, Y } = F.plotFrame(g, w, h, { xLabel: "wavelength (nm)",
      yLabel: "normalised radiance", s, xMin: 300, xMax: 1200, yMin: 0, yMax: 1.1 });
    const temps = [2700, 4500, Math.round(k[0])];
    const cols = ["#D85A30", "#EF9F27", "#7F77DD"];
    temps.forEach((T, i) => {
      let peak = 0;
      for (let l = 300; l <= 1200; l += 2) peak = Math.max(peak, F.planck(l, T));
      const pts = [];
      for (let l = 300; l <= 1200; l += 2) pts.push([X(l), Y(F.planck(l, T) / peak)]);
      F.plotLine(g, pts, cols[i], { s });
      const wien = 2.897771955e6 / T;      // nm
      g.save();
      g.strokeStyle = cols[i]; g.setLineDash([2 * s, 3 * s]); g.lineWidth = 1 * s;
      g.beginPath(); g.moveTo(X(wien), Y(0)); g.lineTo(X(wien), Y(1)); g.stroke();
      g.restore();
    });
    F.legend(g, temps.map((T, i) => [`${T} K`, cols[i]]), w - 88 * s, 30 * s, s);
  },
};

// ------------------------------------------------------------------ Module 4

const hsvLuminance = {
  id: "hsv-luminance",
  caption: "A full sweep of hue at constant HSV value and saturation, with its actual luminance underneath.",
  note: "HSV's 'value' is max(R,G,B), which has almost nothing to do with " +
        "luminance. Yellow lands near Y=0.93, blue near Y=0.07 — a factor of " +
        "thirteen at the same nominal 'value'. The Oklch strip below holds " +
        "lightness genuinely constant.",
  runtime: "canvas2d",
  exact: true,
  aspect: 0.36,
  knobs: [["value / lightness", 0.35, 1, 1, (v) => v.toFixed(2)]],
  draw(g, w, h, t, k) {
    const gap = Math.max(4, Math.round(h * 0.04));
    const barH = Math.floor((h - gap * 2) / 3);
    const V = k[0];
    const hsv2rgb = (hh, s2, v) => {
      const f = (n) => {
        const kk = (n + hh * 6) % 6;
        return v - v * s2 * Math.max(0, Math.min(Math.min(kk, 4 - kk), 1));
      };
      return [f(5), f(3), f(1)];
    };
    const img = g.createImageData(w, h);
    for (let x = 0; x < w; x++) {
      const hh = x / (w - 1);
      const rgb = hsv2rgb(hh, 1, V);
      const Yv = rgb.reduce((a, v, i) => a + F.srgbToLin(v) * F.LUMA[i], 0);

      // Oklch at constant L, chroma reduced until it fits the gamut.
      const L = 0.55 + (V - 0.6) * 0.35;
      let rgb2 = [0, 0, 0];
      for (let C = 0.26; C >= 0; C -= 0.005) {
        const a = Math.cos(hh * Math.PI * 2) * C, b = Math.sin(hh * Math.PI * 2) * C;
        const lin = F.oklabToLinear(L, a, b);
        if (lin.every((v) => v >= -0.001 && v <= 1.001)) {
          rgb2 = lin.map((v) => F.linToSrgb(Math.max(0, Math.min(1, v))));
          break;
        }
      }
      for (let y = 0; y < h; y++) {
        const band = Math.floor(y / (barH + gap));
        if (band > 2 || y % (barH + gap) >= barH) continue;
        let c;
        if (band === 0) c = rgb;
        else if (band === 1) c = [Yv, Yv, Yv].map(F.linToSrgb);
        else c = rgb2;
        const i = (y * w + x) * 4;
        c.forEach((v, ch) => { img.data[i + ch] = Math.round(Math.max(0, Math.min(1, v)) * 255); });
        img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  },
};

// ------------------------------------------------------------------ registry

export const FIGURES = [
  gradientTriptych, gradientLuminance, srgbTransfer, bandingDither, zonePlate,
  smoothstepContinuity, sdfAntialias, metamericPair, coneOverlap, chromaticity,
  wienPeaks, hsvLuminance,
];

export const FIGURE_BY_ID = Object.fromEntries(FIGURES.map((f) => [f.id, f]));

/** Extra figures a module should offer even though its prose predates them. */
export const MODULE_EXTRAS = {
  "00-radiometry": ["planck-peaks"],
  "01-the-eye": ["metameric-pair", "colour-matching-functions"],
  "02-colorimetry": ["chromaticity-diagram"],
  "04-color-organization": ["hsv-luminance"],
  "05-display": ["banding-dither", "zone-plate"],
  "07-shaders": ["sdf-antialias"],
  "08-web-deliverable": ["banding-dither", "hsv-luminance"],
};
