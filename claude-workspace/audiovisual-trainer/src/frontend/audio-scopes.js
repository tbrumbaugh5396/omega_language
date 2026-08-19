// What you can see: the measurements behind the scopes.
//
// Phase E of the audio roadmap, and the half of it that is arithmetic. The
// pictures are drawn by the visual pipeline — they are pictures, and there is
// a render graph for those already — so this file computes and packs, and
// scope-nodes.js draws.
//
// The rule from the video scopes carries over unchanged: **measure what will
// be exported**. The video scopes read the composited frame; these read the
// audio graph's own tap, so what the meter says is what the bounce contains.

/** Rec. ITU-R BS.1770-4 loudness, and the filters it is defined by. */

/**
 * The two K-weighting stages, as the standard gives them: a high-frequency
 * shelf standing for the head's response, then a high-pass ("RLB") that takes
 * out what does not contribute to loudness. The coefficients are specified at
 * 48 kHz; at any other rate they are re-derived from the same analogue
 * prototype rather than reused, because reusing them is the usual bug.
 */
export function kWeightingCoeffs(sampleRate) {
  // Stage 1 — high shelf. The standard's 48 kHz coefficients come from these
  // constants, and the bilinear transform reproduces them exactly there.
  const db = 3.999843853973347, f0 = 1681.974450955533;
  const G = Math.pow(10, db / 20), Q = 0.7071752369554196;
  const K = Math.tan(Math.PI * f0 / sampleRate);
  const vh = G, vb = Math.pow(G, 0.4996667741545416);
  const a0 = 1 + K / Q + K * K;
  const b = [(vh + vb * K / Q + K * K) / a0, 2 * (K * K - vh) / a0, (vh - vb * K / Q + K * K) / a0];
  const a = [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0];

  // Stage 2 — the RLB high-pass.
  const f2 = 38.13547087602444, Q2 = 0.5003270373238773;
  const K2 = Math.tan(Math.PI * f2 / sampleRate);
  const a02 = 1 + K2 / Q2 + K2 * K2;
  const b2 = [1, -2, 1];
  const a2 = [1, 2 * (K2 * K2 - 1) / a02, (1 - K2 / Q2 + K2 * K2) / a02];
  return { shelf: { b, a }, hp: { b: b2, a: a2 } };
}

/** One biquad, direct form I, over a whole buffer. */
function biquad(data, { b, a }) {
  const out = new Float32Array(data.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < data.length; i++) {
    const x = data[i];
    const y = b[0] * x + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    out[i] = y;
  }
  return out;
}

/**
 * Integrated loudness in LUFS, with the standard's two gates: an absolute one
 * at −70 LUFS, then a relative one 10 LU below what survives it. Without the
 * gating a track's silence counts as quiet content and drags the number down,
 * which is the whole reason the gates are in the standard.
 */
export function loudnessLUFS(channels, sampleRate) {
  const chans = Array.isArray(channels) ? channels : [channels];
  const k = kWeightingCoeffs(sampleRate);
  const weighted = chans.map((c) => biquad(biquad(c, k.shelf), k.hp));
  const blockLen = Math.round(0.4 * sampleRate);        // 400 ms
  const hop = Math.round(blockLen / 4);                 // 75% overlap
  const n = weighted[0].length;
  if (n < blockLen) return { lufs: -Infinity, blocks: 0 };

  const loud = [];
  for (let at = 0; at + blockLen <= n; at += hop) {
    let sum = 0;
    for (const w of weighted) {
      let s = 0;
      for (let i = at; i < at + blockLen; i++) s += w[i] * w[i];
      sum += s / blockLen;                              // channel weights are 1 for L/R
    }
    loud.push(-0.691 + 10 * Math.log10(Math.max(sum, 1e-20)));
  }
  const meanOf = (list) => {
    if (!list.length) return -Infinity;
    let s = 0;
    for (const l of list) s += Math.pow(10, (l + 0.691) / 10);
    return -0.691 + 10 * Math.log10(s / list.length);
  };
  const above = loud.filter((l) => l > -70);
  if (!above.length) return { lufs: -Infinity, blocks: loud.length };
  const relative = meanOf(above) - 10;
  const gated = above.filter((l) => l > relative);
  return { lufs: meanOf(gated.length ? gated : above), blocks: loud.length, gate: relative };
}

/**
 * True peak in dBTP: the peak of the signal *between* samples, which is what
 * a converter will actually produce and what a sample peak misses. Four times
 * oversampled with a windowed-sinc, as the standard asks.
 */
export function truePeakDb(channels, { oversample = 4, taps = 33 } = {}) {
  const chans = Array.isArray(channels) ? channels : [channels];
  // One polyphase set of coefficients per sub-sample position.
  const half = (taps - 1) / 2;
  const phases = [];
  for (let p = 0; p < oversample; p++) {
    const h = new Float32Array(taps);
    let sum = 0;
    for (let i = 0; i < taps; i++) {
      const x = i - half - p / oversample;
      const s = Math.abs(x) < 1e-9 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
      const w = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (taps - 1));   // Hamming
      h[i] = s * w;
      sum += h[i];
    }
    for (let i = 0; i < taps; i++) h[i] /= sum;
    phases.push(h);
  }
  let peak = 0;
  for (const c of chans) {
    for (let i = 0; i < c.length; i++) {
      if (Math.abs(c[i]) > peak) peak = Math.abs(c[i]);
      for (let p = 1; p < oversample; p++) {
        let acc = 0;
        const h = phases[p];
        for (let t = 0; t < taps; t++) {
          const j = i + t - half;
          if (j >= 0 && j < c.length) acc += c[j] * h[t];
        }
        if (Math.abs(acc) > peak) peak = Math.abs(acc);
      }
    }
  }
  return 20 * Math.log10(Math.max(peak, 1e-12));
}

/**
 * Correlation between two channels, −1 to 1. The number that says whether a
 * mix will survive being folded to mono: −1 means it will cancel.
 */
export function correlation(left, right) {
  let sl = 0, sr = 0, slr = 0;
  const n = Math.min(left.length, right.length);
  for (let i = 0; i < n; i++) { sl += left[i] * left[i]; sr += right[i] * right[i]; slr += left[i] * right[i]; }
  const d = Math.sqrt(sl * sr);
  return d > 1e-12 ? slr / d : 0;
}

// ------------------------------------------------------------------ packing
//
// The scopes are drawn by the visual pipeline, which means the analysis has
// to arrive as a texture. Everything below turns numbers into pixels; nothing
// below decides what anything looks like.

/** A row of magnitudes as an RGBA row, log-scaled to a decibel floor. */
export function packSpectrum(mag, { floorDb = -96, width = 512 } = {}) {
  const out = new Uint8ClampedArray(width * 4);
  // Logarithmic in frequency, because hearing is: an octave should take the
  // same width wherever it sits. Each column takes the *loudest* bin in the
  // range it covers rather than a sample from the middle of it — at the top
  // of a log axis adjacent columns skip bins, and a point sample drops narrow
  // peaks straight through the gap.
  const binAt = (t) => Math.min(mag.length - 1, Math.max(0, Math.pow(mag.length, t) - 1));
  for (let x = 0; x < width; x++) {
    const t = x / (width - 1);
    const lo = Math.floor(binAt(Math.max(0, (x - 0.5) / (width - 1))));
    const hi = Math.ceil(binAt(Math.min(1, (x + 0.5) / (width - 1))));
    let m = 0;
    for (let b2 = lo; b2 <= hi && b2 < mag.length; b2++) if (mag[b2] > m) m = mag[b2];
    const db = 20 * Math.log10(Math.max(m, 1e-12));
    const v = Math.max(0, Math.min(1, (db - floorDb) / -floorDb));
    out[x * 4] = out[x * 4 + 1] = out[x * 4 + 2] = Math.round(v * 255);
    out[x * 4 + 3] = 255;
  }
  return out;
}

/** A waveform as min/max per column, so a whole buffer fits in one row. */
export function packWaveform(data, { width = 512 } = {}) {
  const out = new Uint8ClampedArray(width * 4);
  const per = Math.max(1, Math.floor(data.length / width));
  for (let x = 0; x < width; x++) {
    let lo = 1, hi = -1;
    const at = x * per;
    for (let i = at; i < at + per && i < data.length; i++) {
      if (data[i] < lo) lo = data[i];
      if (data[i] > hi) hi = data[i];
    }
    out[x * 4] = Math.round((hi * 0.5 + 0.5) * 255);      // r: the top
    out[x * 4 + 1] = Math.round((lo * 0.5 + 0.5) * 255);  // g: the bottom
    out[x * 4 + 2] = 0;
    out[x * 4 + 3] = 255;
  }
  return out;
}

/** A packed row as a canvas the graph can take as a source. */
export function rowTexture(row) {
  const width = row.length / 4;
  const c = document.createElement("canvas");
  c.width = width; c.height = 1;
  c.getContext("2d").putImageData(new ImageData(row, width, 1), 0, 0);
  return c;
}

// ------------------------------------------------------------------ history
//
// A spectrogram wants a scrolling picture. The obvious way is a feedback
// sketch — draw last frame shifted by a column — and the Generate runtime has
// prev() for exactly that. It is the wrong choice here: that runtime's
// context is shared with the canvas filters and the design bakes, and a panel
// that quietly loses its history when someone opens a filter dialog is worse
// than no panel.
//
// So the history is a ring, and nothing is ever copied: the newest column
// simply moves, and the node wraps its lookup by where the head is. Scrolling
// costs one number.

export function spectrogram(width = 256, height = 256) {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, width, height);
  const column = new ImageData(1, height);
  let head = 0;

  return {
    canvas, width, height,
    /** Where the newest column sits, 0 to 1 — the node needs it to unwrap. */
    get head() { return head / width; },
    /**
     * Add one column from a magnitude spectrum. Frequency runs up the
     * picture and is logarithmic, for the same reason the spectrum plot is:
     * an octave should take the same space wherever it sits.
     */
    push(mag, { floorDb = -96 } = {}) {
      const binAt = (t) => Math.min(mag.length - 1, Math.max(0, Math.pow(mag.length, t) - 1));
      for (let y = 0; y < height; y++) {
        const t = 1 - y / (height - 1);                 // top of the picture is high
        const lo = Math.floor(binAt(Math.max(0, t - 0.5 / height)));
        const hi = Math.ceil(binAt(Math.min(1, t + 0.5 / height)));
        let m = 0;
        for (let b = lo; b <= hi && b < mag.length; b++) if (mag[b] > m) m = mag[b];
        const db = 20 * Math.log10(Math.max(m, 1e-12));
        const v = Math.max(0, Math.min(1, (db - floorDb) / -floorDb));
        const i = y * 4;
        column.data[i] = column.data[i + 1] = column.data[i + 2] = Math.round(v * 255);
        column.data[i + 3] = 255;
      }
      ctx.putImageData(column, head, 0);
      head = (head + 1) % width;
    },
    clear() {
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, width, height);
      head = 0;
    },
  };
}
