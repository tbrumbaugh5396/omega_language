// Web Audio engine: sources, offline processing, analysis.
//
// Two layers, deliberately:
//   synth.*        writes samples directly into Float32Arrays. Fully
//                  deterministic from a seed, which matters because a drill
//                  has to be able to regenerate the exact stimulus it graded.
//   processOffline renders those samples through a real Web Audio graph, so
//                  the filters, compressors and convolvers under test are the
//                  browser's own, not an approximation.
//
// Everything is level-matched before playback (see matchRms). Louder is heard
// as better; an unmatched A/B tests gain, not discrimination.

let _ctx = null;

export function audioCtx() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (_ctx.state === "suspended") _ctx.resume();
  return _ctx;
}

export const SR = 44100;

// ------------------------------------------------------------------ helpers

const TAU = Math.PI * 2;
export const noteHz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

function prng(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
}

export function rms(data) {
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
  return Math.sqrt(sum / Math.max(1, data.length));
}

/** Peak by loop. Math.max(...array) overflows the stack past ~100k samples,
 *  and a minute of audio is millions. */
export function peakOf(data) {
  let p = 0;
  for (let i = 0; i < data.length; i++) {
    const v = data[i] < 0 ? -data[i] : data[i];
    if (v > p) p = v;
  }
  return p;
}

/** Scale a buffer to a target RMS. The level-match that makes A/B honest. */
export function matchRms(buffer, target = 0.12) {
  const chans = [];
  for (let c = 0; c < buffer.numberOfChannels; c++) chans.push(buffer.getChannelData(c));
  let sum = 0, n = 0;
  for (const ch of chans) { for (let i = 0; i < ch.length; i++) { sum += ch[i] * ch[i]; n++; } }
  const cur = Math.sqrt(sum / Math.max(1, n));
  if (cur < 1e-9) return buffer;
  let g = target / cur;
  // Never let the match itself clip; back off if it would.
  let peak = 0;
  for (const ch of chans) for (let i = 0; i < ch.length; i++) peak = Math.max(peak, Math.abs(ch[i]));
  if (peak * g > 0.98) g = 0.98 / peak;
  for (const ch of chans) for (let i = 0; i < ch.length; i++) ch[i] *= g;
  return buffer;
}

/** Short raised-cosine fades, so a stimulus never starts with a click. */
export function fade(data, sr = SR, ms = 8) {
  const n = Math.min(Math.floor((ms / 1000) * sr), Math.floor(data.length / 2));
  for (let i = 0; i < n; i++) {
    const w = 0.5 - 0.5 * Math.cos((Math.PI * i) / n);
    data[i] *= w;
    data[data.length - 1 - i] *= w;
  }
  return data;
}

export function toBuffer(chans, sr = SR) {
  const arr = Array.isArray(chans) ? chans : [chans];
  const ctx = audioCtx();
  const buf = ctx.createBuffer(arr.length, arr[0].length, sr);
  arr.forEach((c, i) => buf.copyToChannel(c, i));
  return buf;
}

// ------------------------------------------------------------------ sources

export const synth = {
  /** Pink-ish noise (Voss-McCartney style filtering of white). */
  pink(seconds, seed = 1, sr = SR) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    for (let i = 0; i < n; i++) {
      const w = r() * 2 - 1;
      b0 = 0.99886 * b0 + w * 0.0555179;
      b1 = 0.99332 * b1 + w * 0.0750759;
      b2 = 0.96900 * b2 + w * 0.1538520;
      b3 = 0.86650 * b3 + w * 0.3104856;
      b4 = 0.55000 * b4 + w * 0.5329522;
      b5 = -0.7616 * b5 - w * 0.0168980;
      out[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
      b6 = w * 0.115926;
    }
    return out;
  },

  white(seconds, seed = 1, sr = SR) {
    const r = prng(seed);
    const out = new Float32Array(Math.floor(seconds * sr));
    for (let i = 0; i < out.length; i++) out[i] = r() * 2 - 1;
    return out;
  },

  tone(seconds, hz, { sr = SR, gain = 0.3, phase = 0 } = {}) {
    const out = new Float32Array(Math.floor(seconds * sr));
    for (let i = 0; i < out.length; i++) out[i] = Math.sin(phase + (TAU * hz * i) / sr) * gain;
    return fade(out, sr, 12);
  },

  /** Harmonic-rich tone: the spectral envelope is what makes timbre. */
  harmonic(seconds, hz, { sr = SR, partials = 8, tilt = 1.0, gain = 0.22 } = {}) {
    const out = new Float32Array(Math.floor(seconds * sr));
    for (let p = 1; p <= partials; p++) {
      const a = gain / Math.pow(p, tilt);
      const f = hz * p;
      if (f > sr / 2 - 200) break;
      for (let i = 0; i < out.length; i++) out[i] += Math.sin((TAU * f * i) / sr) * a;
    }
    return fade(out, sr, 15);
  },

  /** Karplus-Strong pluck — a physical model in eight lines. */
  pluck(seconds, hz, { sr = SR, damp = 0.996, seed = 7, gain = 0.5 } = {}) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    const len = Math.max(2, Math.round(sr / hz));
    const buf = new Float32Array(len);
    for (let i = 0; i < len; i++) buf[i] = r() * 2 - 1;
    let idx = 0;
    for (let i = 0; i < n; i++) {
      const nxt = (idx + 1) % len;
      const v = (buf[idx] + buf[nxt]) * 0.5 * damp;
      out[i] = buf[idx] * gain;
      buf[idx] = v;
      idx = nxt;
    }
    return fade(out, sr, 5);
  },

  /** A hit with a controllable attack — the drill stimulus for transients. */
  hit(seconds, { sr = SR, attackMs = 1, decayMs = 220, hz = 180, noise = 0.5, seed = 3 } = {}) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    const a = Math.max(1, (attackMs / 1000) * sr);
    const d = (decayMs / 1000) * sr;
    for (let i = 0; i < n; i++) {
      const env = i < a ? i / a : Math.exp(-(i - a) / d);
      const tone = Math.sin((TAU * hz * i) / sr);
      out[i] = env * (tone * (1 - noise) + (r() * 2 - 1) * noise) * 0.7;
    }
    return fade(out, sr, 4);
  },

  /** A two-bar drum pattern. Transients, sub, and a busy top — enough to
   *  make compression, EQ and reverb audible on something musical. */
  drumLoop(seconds, { sr = SR, bpm = 96, seed = 11 } = {}) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    const beat = (60 / bpm) * sr;
    const step = beat / 4;

    const kickAt = [0, 6, 8, 14];
    const snareAt = [4, 12];
    const hatAt = [0, 2, 4, 6, 8, 10, 12, 14, 1, 5, 9, 13];

    const place = (start, len, fn) => {
      for (let i = 0; i < len && start + i < n; i++) out[start + i] += fn(i);
    };
    const steps = Math.ceil(n / step);
    for (let s = 0; s < steps; s++) {
      const at = Math.floor(s * step);
      const m = s % 16;
      if (kickAt.includes(m)) {
        place(at, Math.floor(0.35 * sr), (i) => {
          const t = i / sr;
          const f = 120 * Math.exp(-t * 28) + 46;
          return Math.sin(TAU * f * t) * Math.exp(-t * 9) * 0.9;
        });
      }
      if (snareAt.includes(m)) {
        place(at, Math.floor(0.2 * sr), (i) => {
          const t = i / sr;
          const env = Math.exp(-t * 24);
          return ((r() * 2 - 1) * 0.6 + Math.sin(TAU * 190 * t) * 0.4) * env * 0.7;
        });
      }
      if (hatAt.includes(m)) {
        place(at, Math.floor(0.06 * sr), (i) => {
          const t = i / sr;
          return (r() * 2 - 1) * Math.exp(-t * 130) * 0.28;
        });
      }
    }
    // A held sub so masking and slotting have something to fight over.
    for (let i = 0; i < n; i++) {
      out[i] += Math.sin((TAU * 55 * i) / sr) * 0.12;
      out[i] = Math.tanh(out[i] * 1.1) * 0.85;
    }
    return fade(out, sr, 10);
  },

  /** A sustained pad — steady state, for filter and modulation work. */
  pad(seconds, { sr = SR, root = 48, seed = 5, gain = 0.16 } = {}) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    const chord = [0, 7, 12, 15, 19];
    for (const iv of chord) {
      const base = noteHz(root + iv);
      for (let d = 0; d < 3; d++) {
        const det = base * (1 + (d - 1) * 0.004 * (0.5 + r()));
        const ph = r() * TAU;
        for (let i = 0; i < n; i++) {
          // Saw via summed partials, cheap and band-limited enough here.
          const t = (TAU * det * i) / sr + ph;
          out[i] += (Math.sin(t) + Math.sin(2 * t) * 0.4 + Math.sin(3 * t) * 0.22) * gain * 0.2;
        }
      }
    }
    return fade(out, sr, 60);
  },

  /** Formant-ish "voice" — for masking, ducking and intelligibility work. */
  voice(seconds, { sr = SR, seed = 9, hz = 130 } = {}) {
    const r = prng(seed);
    const n = Math.floor(seconds * sr);
    const out = new Float32Array(n);
    const formants = [[700, 1.0], [1220, 0.5], [2600, 0.25]];
    let phase = 0;
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      // Syllabic envelope around 4 Hz — speech rhythm is the important cue.
      const syl = Math.max(0, Math.sin(TAU * 3.6 * t + Math.sin(t * 1.7) * 2));
      const f0 = hz * (1 + 0.06 * Math.sin(TAU * 1.3 * t));
      phase += (TAU * f0) / sr;
      let v = 0;
      for (const [f, a] of formants) {
        v += Math.sin(phase * Math.round(f / f0)) * a;
      }
      out[i] = (v * 0.25 + (r() * 2 - 1) * 0.02) * syl * 0.5;
    }
    return fade(out, sr, 20);
  },
};

// ------------------------------------------------------------------ offline

/**
 * Render source samples through a Web Audio graph offline.
 * build(ctx, source) must return the last node in the chain.
 */
export async function processOffline(chans, build, { sr = SR, channels = null } = {}) {
  const arr = Array.isArray(chans) ? chans : [chans];
  const outCh = channels || Math.max(2, arr.length);
  const OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const ctx = new OC(outCh, arr[0].length, sr);
  const buf = ctx.createBuffer(arr.length, arr[0].length, sr);
  arr.forEach((c, i) => buf.copyToChannel(c, i));
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const last = build(ctx, src) || src;
  last.connect(ctx.destination);
  src.start();
  return ctx.startRendering();
}

/** Synthesised impulse response: noise through a decay envelope, plus a
 *  pre-delay gap. That is genuinely all a basic reverb IR is. */
export function makeIR(ctx, { seconds = 1.8, preDelayMs = 20, decay = 3.0,
                              damp = 0.35, seed = 21, stereo = true } = {}) {
  const sr = ctx.sampleRate;
  const n = Math.floor(seconds * sr);
  const pre = Math.floor((preDelayMs / 1000) * sr);
  const ir = ctx.createBuffer(stereo ? 2 : 1, n + pre, sr);
  for (let c = 0; c < ir.numberOfChannels; c++) {
    const r = prng(seed + c * 977);
    const d = ir.getChannelData(c);
    let lp = 0;
    for (let i = 0; i < n; i++) {
      const t = i / n;
      const env = Math.pow(1 - t, decay);
      const w = r() * 2 - 1;
      lp += (w - lp) * (1 - damp * t);   // high end decays first, as rooms do
      d[pre + i] = lp * env;
    }
  }
  return ir;
}

/** Waveshaper curves — the transfer function is the whole effect. */
export function shaperCurve(kind, amount = 0.5, n = 2048) {
  const c = new Float32Array(n);
  const k = 1 + amount * 40;
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    switch (kind) {
      case "soft": c[i] = Math.tanh(x * k) / Math.tanh(k); break;
      case "hard": c[i] = Math.max(-1, Math.min(1, x * k)); break;
      case "asym": c[i] = x >= 0 ? Math.tanh(x * k) / Math.tanh(k)
                                 : Math.tanh(x * k * 0.45) / Math.tanh(k); break;
      case "fold": c[i] = Math.sin(x * (1 + amount * 6) * Math.PI * 0.5); break;
      default: c[i] = x;
    }
  }
  return c;
}

/** Bit-depth quantisation as a transfer curve — error correlates with the
 *  signal, which is why it sounds gritty rather than like added noise. */
export function crushCurve(bits = 6, n = 4096) {
  const c = new Float32Array(n);
  const levels = Math.pow(2, bits);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    c[i] = Math.round(x * levels) / levels;
  }
  return c;
}

/** Sample-rate reduction, done by hand: no band-limiting, so it aliases —
 *  which is the point of the sound. */
export function downsample(data, factor) {
  const out = new Float32Array(data.length);
  let held = 0;
  for (let i = 0; i < data.length; i++) {
    if (i % factor === 0) held = data[i];
    out[i] = held;
  }
  return out;
}

// ------------------------------------------------------------------ playback

let liveNodes = [];

export function stopAll() {
  for (const n of liveNodes) { try { n.stop(); } catch { /* already stopped */ } }
  liveNodes = [];
}

/** Play an AudioBuffer. Returns a stop function; stops anything already going. */
export function play(buffer, { loop = false, gain = 1, onended } = {}) {
  stopAll();
  const ctx = audioCtx();
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.loop = loop;
  const g = ctx.createGain();
  g.gain.value = gain;
  src.connect(g).connect(ctx.destination);
  src.onended = () => { liveNodes = liveNodes.filter((n) => n !== src); onended?.(); };
  src.start();
  liveNodes.push(src);
  return () => { try { src.stop(); } catch { /* already stopped */ } };
}

/** Live graph for the labs: a looping source you can rewire while it runs. */
export function liveSource(samples, { loop = true, sr = SR } = {}) {
  const ctx = audioCtx();
  const buf = ctx.createBuffer(1, samples.length, sr);
  buf.copyToChannel(samples, 0);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.loop = loop;
  return src;
}

// ------------------------------------------------------------------ analysis

/** Iterative radix-2 FFT, in place. Returns magnitudes for the lower half. */
export function fftMag(input) {
  let n = 1;
  while (n * 2 <= input.length) n *= 2;
  const re = new Float32Array(n), im = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    // Hann window: the window is what decides what you can see.
    re[i] = input[i] * (0.5 - 0.5 * Math.cos((TAU * i) / (n - 1)));
  }
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -TAU / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k], ui = im[i + k];
        const vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k] = ur + vr; im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        const ncr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
  const mag = new Float32Array(n / 2);
  for (let i = 0; i < n / 2; i++) mag[i] = Math.hypot(re[i], im[i]) / (n / 2);
  return mag;
}

/** MIR-flavoured feature bundle (Part 6). Deliberately the vocabulary from
 *  the roadmap: centroid is 'brightness', flux is 'rate of change'. */
export function audioFeatures(channelData, sr) {
  const hop = 1024, win = 2048;
  const frames = Math.max(1, Math.floor((channelData.length - win) / hop));
  const step = Math.max(1, Math.floor(frames / 240));   // cap the work
  const centroids = [], fluxes = [], rolloffs = [], energies = [];
  let prev = null;
  const spectra = [];
  for (let f = 0; f < frames; f += step) {
    const seg = channelData.subarray(f * hop, f * hop + win);
    const mag = fftMag(seg);
    spectra.push(mag);
    let sum = 0, wsum = 0, tot = 0;
    for (let i = 0; i < mag.length; i++) { sum += mag[i]; wsum += mag[i] * i; }
    const hz = (i) => (i * sr) / (2 * mag.length);
    centroids.push(sum > 1e-9 ? hz(wsum / sum) : 0);
    let acc = 0, roll = 0;
    for (let i = 0; i < mag.length; i++) { acc += mag[i]; if (acc >= sum * 0.85) { roll = hz(i); break; } }
    rolloffs.push(roll);
    if (prev) {
      let d = 0;
      for (let i = 0; i < mag.length; i++) { const x = mag[i] - prev[i]; if (x > 0) d += x; }
      fluxes.push(d);
    }
    for (let i = 0; i < mag.length; i++) tot += mag[i] * mag[i];
    energies.push(Math.sqrt(tot));
    prev = mag;
  }
  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
  // Onset count: flux peaks above a running threshold.
  const fluxMean = mean(fluxes), fluxSd = Math.sqrt(mean(fluxes.map((x) => (x - fluxMean) ** 2)));
  let onsets = 0;
  for (let i = 1; i < fluxes.length - 1; i++) {
    if (fluxes[i] > fluxMean + fluxSd && fluxes[i] > fluxes[i - 1] && fluxes[i] >= fluxes[i + 1]) onsets++;
  }
  const seconds = channelData.length / sr;
  const frameSec = (hop * step) / sr;

  // Average spectrum, in 24 log bands — the shape you actually mix against.
  const bands = new Array(24).fill(0);
  if (spectra.length) {
    const bins = spectra[0].length;
    for (const m of spectra) {
      for (let i = 1; i < bins; i++) {
        const hz = (i * sr) / (2 * bins);
        const b = Math.floor((Math.log2(Math.max(20, hz) / 20) / Math.log2(20000 / 20)) * 24);
        if (b >= 0 && b < 24) bands[b] += m[i];
      }
    }
    for (let b = 0; b < 24; b++) bands[b] /= spectra.length;
  }
  const peakBand = Math.max(...bands, 1e-9);

  return {
    seconds: +seconds.toFixed(2),
    rms: +rms(channelData).toFixed(4),
    peak: +peakOf(channelData).toFixed(3),
    centroid: Math.round(mean(centroids)),
    centroidSd: Math.round(Math.sqrt(mean(centroids.map((x) => (x - mean(centroids)) ** 2)))),
    rolloff85: Math.round(mean(rolloffs)),
    flux: +mean(fluxes).toFixed(4),
    onsetDensity: +(onsets / Math.max(0.001, frames * frameSec)).toFixed(2),
    bands: bands.map((b) => +(b / peakBand).toFixed(3)),
    frameSec,
  };
}

/** Autocorrelation tempo estimate over the energy envelope. Rough by design —
 *  it exists so the drill can tell you whether your guess was in the ballpark. */
export function estimateTempo(channelData, sr) {
  const hop = 512;
  const n = Math.floor(channelData.length / hop);
  const env = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let e = 0;
    for (let j = 0; j < hop; j++) e += Math.abs(channelData[i * hop + j] || 0);
    env[i] = e / hop;
  }
  // Difference-rectify: onsets, not level.
  for (let i = n - 1; i > 0; i--) env[i] = Math.max(0, env[i] - env[i - 1]);
  const fps = sr / hop;
  // Every lag is scored over the same number of terms. Summing raw products
  // favours short lags (more terms); dividing by the term count favours long
  // ones (fewer, noisier terms). A common window is the only fair comparison.
  const maxLag = Math.min(n - 4, Math.ceil((60 / 45) * fps));
  const terms = n - maxLag;
  const score = (bpm) => {
    const lag = Math.round((60 / bpm) * fps);
    if (lag < 2 || lag > maxLag || terms < 8) return 0;
    let acc = 0;
    for (let i = 0; i < terms; i++) acc += env[i] * env[i + lag];
    return acc / terms;
  };

  // Stage 1: strongest periodicity anywhere in a wide range.
  let raw = 0, rawScore = 0;
  for (let bpm = 45; bpm <= 240; bpm++) {
    const s = score(bpm);
    if (s > rawScore) { rawScore = s; raw = bpm; }
  }
  if (!raw) return 0;

  // Stage 2: octave correction. Autocorrelation cannot tell which metrical
  // level is "the beat" — the half-time and double-time answers are equally
  // consistent with the signal — so break the tie with a mild preference for
  // the range humans actually tap in.
  const prefer = (bpm) => Math.exp(-0.5 * Math.pow(Math.log2(bpm / 115) / 0.9, 2));
  let best = 0, bestBpm = raw;
  for (const cand of [raw / 2, raw, raw * 2]) {
    if (cand < 50 || cand > 210) continue;
    const s = score(Math.round(cand)) * prefer(cand);
    if (s > best) { best = s; bestBpm = Math.round(cand); }
  }
  return bestBpm;
}
