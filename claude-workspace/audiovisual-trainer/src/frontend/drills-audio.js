// Ear drills. Every stimulus is synthesised fresh and level-matched before
// playback, and every one of them is processed by the browser's own filters,
// compressors and convolvers rather than an approximation of them.
//
// A generator returns:
//   { prompt, choices[], answer, mount(host)->cleanup, explain(chosenIndex) }

import { el, rng, pick, shuffle, clamp } from "./ui.js";
import * as A from "./engine-audio.js";

// ------------------------------------------------------------------ shared

/** Play buttons for one or more rendered buffers. */
function player(buffers, labels = null, { loop = false } = {}) {
  const names = labels || (buffers.length === 1 ? ["Play"] : buffers.map((_, i) => String.fromCharCode(65 + i)));
  let stop = null;
  const btns = buffers.map((buf, i) =>
    el("button", {
      onclick: () => {
        stop?.();
        stop = A.play(buf, { loop });
        btns.forEach((b) => b.classList.remove("on"));
        btns[i].classList.add("on");
      },
    }, names[i]));
  const wrap = el("div.row", { style: { justifyContent: "center", gap: ".5rem" } },
    ...btns,
    loop && el("button.ghost", { onclick: () => { stop?.(); btns.forEach((b) => b.classList.remove("on")); } }, "Stop"));
  wrap._cleanup = () => { stop?.(); A.stopAll(); };
  return wrap;
}

function mountPlayer(buffers, labels, opts) {
  return (host) => {
    const p = player(buffers, labels, opts);
    host.append(p);
    // Auto-play the first one: the drill should start the moment it opens.
    setTimeout(() => p.querySelector("button")?.click(), 60);
    return () => p._cleanup();
  };
}

const dbToGain = (db) => Math.pow(10, db / 20);

// ------------------------------------------------------------------ drills

/** Which band moved? A single peaking filter, named by frequency. */
async function eqBandId(level, seed) {
  const r = rng(seed);
  const wide = [[80, "80 Hz — sub / weight"], [250, "250 Hz — mud / body"],
                [1000, "1 kHz — nasal / presence"], [4000, "4 kHz — bite / edge"],
                [10000, "10 kHz — air"]];
  const narrow = [[60, "60 Hz"], [120, "120 Hz"], [250, "250 Hz"], [500, "500 Hz"],
                  [1000, "1 kHz"], [2000, "2 kHz"], [4000, "4 kHz"], [8000, "8 kHz"],
                  [12000, "12 kHz"]];
  const set = level <= 2 ? wide : narrow;
  const count = level <= 2 ? 5 : clamp(4 + level, 5, 9);
  const opts = shuffle(r, set).slice(0, count).sort((a, b) => a[0] - b[0]);
  const target = pick(r, opts);
  const gainDb = (r() > 0.5 ? 1 : -1) * (14 - level * 2);   // ±12 dB → ±4 dB
  const q = level <= 2 ? 1.0 : 2.2;

  const src = r() > 0.5
    ? A.synth.pink(2.6, Math.floor(r() * 1e6))
    : A.synth.drumLoop(2.6, { seed: Math.floor(r() * 1e6) });

  const dry = A.matchRms(await A.processOffline(src, (ctx, s) => s));
  const wet = A.matchRms(await A.processOffline(src, (ctx, s) => {
    const f = ctx.createBiquadFilter();
    f.type = "peaking";
    f.frequency.value = target[0];
    f.Q.value = q;
    f.gain.value = gainDb;
    return s.connect(f);
  }));

  return {
    prompt: `B has one band ${gainDb > 0 ? "boosted" : "cut"} by ${Math.abs(gainDb)} dB. Which band?`,
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: mountPlayer([dry, wet], ["A — flat", "B — filtered"], { loop: true }),
    explain: (chosen) => {
      const got = opts[chosen];
      if (!got || got[0] === target[0]) {
        return `${target[1]}, Q ${q}, ${gainDb > 0 ? "+" : ""}${gainDb} dB. ` +
               `Sweeping a narrow boost is how you find this on a real mix.`;
      }
      const oct = Math.log2(target[0] / got[0]);
      return `It was ${target[1]}. You picked ${got[1]} — ` +
             `${Math.abs(oct).toFixed(1)} octaves ${oct > 0 ? "below" : "above"} it. ` +
             (Math.abs(oct) <= 1
               ? "Within an octave: you heard the region, not the band yet."
               : "That is a long way off — go back to the wide set for a while.");
    },
  };
}

/** Masked or not? You are measuring your own critical bands. */
async function maskingThreshold(level, seed) {
  const r = rng(seed);
  const fc = pick(r, [400, 800, 1600, 3200]);
  const present = r() > 0.45;
  // Level 1 leaves the tone well clear of the masker; level 4 buries it.
  const toneDb = [-14, -20, -26, -31][clamp(level - 1, 0, 3)];

  const noise = A.synth.pink(2.0, Math.floor(r() * 1e6));
  const masker = await A.processOffline(noise, (ctx, s) => {
    const f = ctx.createBiquadFilter();
    f.type = "bandpass"; f.frequency.value = fc; f.Q.value = 1.2;
    const g = ctx.createGain(); g.gain.value = 6;
    return s.connect(f).connect(g);
  });
  const mix = A.matchRms(masker, 0.14);
  if (present) {
    const tone = A.synth.tone(2.0, fc, { gain: dbToGain(toneDb) });
    const ch = mix.getChannelData(0);
    const ch2 = mix.numberOfChannels > 1 ? mix.getChannelData(1) : null;
    for (let i = 0; i < ch.length; i++) { ch[i] += tone[i]; if (ch2) ch2[i] += tone[i]; }
  }

  return {
    prompt: `A ${fc} Hz tone may or may not be hiding inside this noise band. Is it there?`,
    choices: ["Yes — I can hear it", "No — nothing there"],
    answer: present ? 0 : 1,
    mount: mountPlayer([mix], ["Play"], { loop: true }),
    explain: () =>
      (present
        ? `The tone was there, ${Math.abs(toneDb)} dB under the masker. `
        : `No tone. `) +
      `The noise is centred on the same critical band as the tone, which is why ` +
      `it takes so little level to hide it — and why two elements in one band ` +
      `fight no matter what you do with the faders.`,
  };
}

/** Which one is compressed? Level-matched, so only the envelope gives it away. */
async function compAb(level, seed) {
  const r = rng(seed);
  const ratio = [12, 8, 6, 4, 3][clamp(level - 1, 0, 4)];
  const thresh = [-30, -28, -26, -24, -22][clamp(level - 1, 0, 4)];
  const src = A.synth.drumLoop(2.8, { seed: Math.floor(r() * 1e6) });

  const dry = A.matchRms(await A.processOffline(src, (ctx, s) => s));
  const wet = A.matchRms(await A.processOffline(src, (ctx, s) => {
    const c = ctx.createDynamicsCompressor();
    c.threshold.value = thresh;
    c.ratio.value = ratio;
    c.attack.value = 0.003;
    c.release.value = 0.12;
    c.knee.value = 6;
    return s.connect(c);
  }));
  const first = r() > 0.5;

  return {
    prompt: "One of these is compressed. Both are level-matched. Which one?",
    choices: ["A", "B"],
    answer: first ? 0 : 1,
    mount: mountPlayer(first ? [wet, dry] : [dry, wet], ["A", "B"], { loop: true }),
    explain: () =>
      `Ratio ${ratio}:1 at ${thresh} dB, 3 ms attack. With the levels matched the ` +
      `only cues left are transient shape and how the room behind the kit comes ` +
      `up between hits. Listen to the tail of the snare, not the front of it.`,
  };
}

/** Attack time. Timbre is the temporal envelope as much as the spectral one. */
async function transientId(level, seed) {
  const r = rng(seed);
  const spread = [1, 0.7, 0.45, 0.3][clamp(level - 1, 0, 3)];
  const base = 1;
  const attacks = [base, base * (1 + 24 * spread), base * (1 + 90 * spread)];
  const order = shuffle(r, [0, 1, 2]);
  const bufs = [];
  for (const idx of order) {
    const hit = A.synth.hit(0.8, {
      attackMs: attacks[idx], decayMs: 300, hz: 150 + r() * 60,
      noise: 0.35, seed: Math.floor(r() * 1e6),
    });
    bufs.push(A.matchRms(await A.processOffline(hit, (ctx, s) => s)));
  }
  const slowest = order.indexOf(2);

  return {
    prompt: "Three hits. Which has the slowest attack?",
    choices: ["A", "B", "C"],
    answer: slowest,
    mount: mountPlayer(bufs, ["A", "B", "C"]),
    explain: () =>
      `Attacks were ${order.map((o) => `${attacks[o].toFixed(1)} ms`).join(", ")} ` +
      `for A, B, C. A slow attack reads as soft or distant even at the same level — ` +
      `it is the same cue a compressor changes when it eats a transient.`,
  };
}

/** Read the room: decay and pre-delay, the two parameters that matter. */
async function reverbId(level, seed) {
  const r = rng(seed);
  const askPreDelay = r() > 0.5;
  const src = r() > 0.5
    ? A.synth.voice(2.2, { seed: Math.floor(r() * 1e6) })
    : A.synth.hit(2.2, { attackMs: 1, decayMs: 90, hz: 200, noise: 0.5 });

  const step = [1.9, 1.6, 1.4, 1.25, 1.15][clamp(level - 1, 0, 4)];
  const a = askPreDelay
    ? { seconds: 1.8, preDelayMs: 8, decay: 2.6 }
    : { seconds: 1.2, preDelayMs: 20, decay: 3.4 };
  const b = askPreDelay
    ? { seconds: 1.8, preDelayMs: Math.round(8 * step * step), decay: 2.6 }
    : { seconds: 1.2 * step * step, preDelayMs: 20, decay: 3.4 / step };

  const render = (p) => A.processOffline(src, (ctx, s) => {
    const conv = ctx.createConvolver();
    conv.buffer = A.makeIR(ctx, { ...p, seed: 31 });
    const wet = ctx.createGain(); wet.gain.value = 0.9;
    const dry = ctx.createGain(); dry.gain.value = 0.8;
    const out = ctx.createGain();
    s.connect(conv).connect(wet).connect(out);
    s.connect(dry).connect(out);
    return out;
  });
  const [ba, bb] = [A.matchRms(await render(a)), A.matchRms(await render(b))];
  const swap = r() > 0.5;

  return {
    prompt: askPreDelay
      ? "Which one has more pre-delay — the gap before the room answers?"
      : "Which one is the larger space?",
    choices: ["A", "B"],
    answer: swap ? 0 : 1,
    mount: mountPlayer(swap ? [bb, ba] : [ba, bb], ["A", "B"]),
    explain: () => askPreDelay
      ? `Pre-delay was ${a.preDelayMs} ms against ${b.preDelayMs} ms. More pre-delay ` +
        `separates the source from the space, which is why it makes a voice sit ` +
        `closer to you while still being in a room.`
      : `Decay was about ${a.seconds.toFixed(1)}s against ${b.seconds.toFixed(1)}s. ` +
        `Size is carried by the tail and by how quickly the top of it goes dark, ` +
        `not by how loud the reverb is.`,
  };
}

/** Precedence: level is matched, so only timing localises it. */
async function haasDirection(level, seed) {
  const r = rng(seed);
  const delayMs = [22, 12, 6, 2.5][clamp(level - 1, 0, 3)];
  const leftFirst = r() > 0.5;
  const src = A.synth.pluck(1.6, 220 + r() * 200, { seed: Math.floor(r() * 1e6) });

  const buf = await A.processOffline(src, (ctx, s) => {
    const merger = ctx.createChannelMerger(2);
    const dL = ctx.createDelay(0.1), dR = ctx.createDelay(0.1);
    dL.delayTime.value = leftFirst ? 0 : delayMs / 1000;
    dR.delayTime.value = leftFirst ? delayMs / 1000 : 0;
    s.connect(dL).connect(merger, 0, 0);
    s.connect(dR).connect(merger, 0, 1);
    return merger;
  }, { channels: 2 });

  return {
    prompt: "Both channels are the same level. Which side arrives first?",
    choices: ["Left", "Right"],
    answer: leftFirst ? 0 : 1,
    mount: mountPlayer([A.matchRms(buf)], ["Play"]),
    explain: () =>
      `${delayMs} ms of delay on the ${leftFirst ? "right" : "left"}. Inside about ` +
      `35 ms the ear fuses the two arrivals and localises to the first one — the ` +
      `precedence effect. That is the whole mechanism behind Haas widening, and ` +
      `also why it collapses in mono.`,
  };
}

/** Mono survival: which widening trick fails hardest when summed? */
async function stereoWidth(level, seed) {
  const r = rng(seed);
  const src = A.synth.pad(2.4, { seed: Math.floor(r() * 1e6) });
  const haasMs = [18, 11, 6][clamp(level - 1, 0, 2)];

  // A: Haas — big width, comb-filters itself in mono.
  const haas = await A.processOffline(src, (ctx, s) => {
    const m = ctx.createChannelMerger(2);
    const d = ctx.createDelay(0.1); d.delayTime.value = haasMs / 1000;
    s.connect(m, 0, 0);
    s.connect(d).connect(m, 0, 1);
    return m;
  }, { channels: 2 });
  // B: mid/side — width from level, survives the sum.
  const ms = await A.processOffline(src, (ctx, s) => {
    const m = ctx.createChannelMerger(2);
    const hi = ctx.createBiquadFilter(); hi.type = "highshelf"; hi.frequency.value = 2000; hi.gain.value = 4;
    const lo = ctx.createBiquadFilter(); lo.type = "highshelf"; lo.frequency.value = 2000; lo.gain.value = -4;
    s.connect(hi).connect(m, 0, 0);
    s.connect(lo).connect(m, 0, 1);
    return m;
  }, { channels: 2 });

  const mono = (buf) => {
    const L = buf.getChannelData(0), R = buf.getChannelData(1);
    const out = new Float32Array(L.length);
    for (let i = 0; i < L.length; i++) out[i] = (L[i] + R[i]) * 0.5;
    return A.toBuffer([out, out]);
  };
  const swap = r() > 0.5;
  const stereo = [A.matchRms(haas), A.matchRms(ms)];
  const monos = [A.matchRms(mono(haas)), A.matchRms(mono(ms))];
  const order = swap ? [1, 0] : [0, 1];

  return {
    prompt: "Two widened versions. Which one loses the most when summed to mono?",
    choices: ["A", "B"],
    answer: order.indexOf(0),
    mount: mountPlayer(
      [stereo[order[0]], stereo[order[1]], monos[order[0]], monos[order[1]]],
      ["A stereo", "B stereo", "A mono", "B mono"], { loop: true }),
    explain: () =>
      `One was a ${haasMs} ms Haas delay, the other a mid/side shelf. The delay ` +
      `comb-filters against itself the moment the channels are summed — regular ` +
      `notches through the top end, and the sound goes hollow. Level-based width ` +
      `just narrows.`,
  };
}

/** Name the distortion. Two of these fold instead of stacking. */
async function distortionId(level, seed) {
  const r = rng(seed);
  const kinds = [
    ["soft", "Soft clip / saturation"],
    ["hard", "Hard clip"],
    ["crush", "Bitcrush"],
    ["decimate", "Sample-rate reduction"],
  ];
  const opts = level <= 2 ? kinds.slice(0, 3) : kinds;
  const target = pick(r, opts);
  const amount = [0.85, 0.7, 0.55, 0.4][clamp(level - 1, 0, 3)];

  let src = r() > 0.5
    ? A.synth.pad(2.2, { seed: Math.floor(r() * 1e6) })
    : A.synth.harmonic(2.2, 160 + r() * 80, { partials: 6 });

  let buf;
  if (target[0] === "decimate") {
    const factor = Math.max(2, Math.round(4 + amount * 10));
    buf = await A.processOffline(A.downsample(src, factor), (ctx, s) => s);
  } else {
    const curve = target[0] === "crush"
      ? A.crushCurve(Math.max(3, Math.round(9 - amount * 6)))
      : A.shaperCurve(target[0], amount);
    buf = await A.processOffline(src, (ctx, s) => {
      const ws = ctx.createWaveShaper();
      ws.curve = curve;
      ws.oversample = target[0] === "crush" ? "none" : "2x";
      return s.connect(ws);
    });
  }
  const clean = A.matchRms(await A.processOffline(src, (ctx, s) => s));

  return {
    prompt: "B is distorted. Which kind?",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: mountPlayer([clean, A.matchRms(buf)], ["A — clean", "B — distorted"], { loop: true }),
    explain: (chosen) => {
      const base = {
        soft: "A gradual transfer curve: harmonics stack in an orderly series and the sound thickens.",
        hard: "A flat ceiling: high odd harmonics appear abruptly and it gets edgy rather than thicker.",
        crush: "Amplitude quantisation. The error correlates with the signal, so it is gritty rather than noisy — and it does not get worse with level.",
        decimate: "Downsampling with no band-limiting. Content above the new Nyquist folds back down as inharmonic metallic tone, which is why it sounds like the pitch is fighting itself.",
      }[target[0]];
      const wrong = opts[chosen] && opts[chosen][0] !== target[0]
        ? ` You picked ${opts[chosen][1].toLowerCase()}. `
        : " ";
      return `It was ${target[1].toLowerCase()}.${wrong}${base}`;
    },
  };
}

/** Chorus, flanger, phaser, tremolo — one delay line at different times. */
async function modId(level, seed) {
  const r = rng(seed);
  const kinds = [
    ["chorus", "Chorus", 0.022, 0.004, 0.8, 0],
    ["flanger", "Flanger", 0.003, 0.0022, 0.35, 0.72],
    ["phaser", "Phaser", 0, 0, 0.45, 0],
    ["tremolo", "Tremolo", 0, 0, 4.5, 0],
  ];
  const opts = level <= 1 ? kinds.slice(0, 3) : kinds;
  const target = pick(r, opts);
  const src = A.synth.pad(3.0, { seed: Math.floor(r() * 1e6) });

  const buf = await A.processOffline(src, (ctx, s) => {
    const [kind, , base, depth, rate, fb] = target;
    const lfo = ctx.createOscillator();
    lfo.frequency.value = rate;
    lfo.start();
    if (kind === "tremolo") {
      const g = ctx.createGain(); g.gain.value = 0.55;
      const amt = ctx.createGain(); amt.gain.value = 0.45;
      lfo.connect(amt).connect(g.gain);
      return s.connect(g);
    }
    if (kind === "phaser") {
      let node = s;
      const amt = ctx.createGain(); amt.gain.value = 900;
      for (let i = 0; i < 6; i++) {
        const ap = ctx.createBiquadFilter();
        ap.type = "allpass";
        ap.frequency.value = 400 + i * 350;
        lfo.connect(amt).connect(ap.frequency);
        node = node.connect(ap);
      }
      const mix = ctx.createGain();
      node.connect(mix); s.connect(mix);
      return mix;
    }
    const d = ctx.createDelay(0.2);
    d.delayTime.value = base;
    const amt = ctx.createGain(); amt.gain.value = depth;
    lfo.connect(amt).connect(d.delayTime);
    const mix = ctx.createGain();
    s.connect(d);
    if (fb) { const f = ctx.createGain(); f.gain.value = fb; d.connect(f).connect(d); }
    d.connect(mix); s.connect(mix);
    return mix;
  });
  const clean = A.matchRms(await A.processOffline(src, (ctx, s) => s));

  return {
    prompt: "B has a modulation effect on it. Which one?",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: mountPlayer([clean, A.matchRms(buf)], ["A — dry", "B — modulated"], { loop: true }),
    explain: () => ({
      chorus: "Chorus: ~20 ms delay, modulated, no feedback. Long enough that you hear detuned copies rather than comb notches — it thickens without a swept character.",
      flanger: "Flanger: ~3 ms delay with feedback. Short enough to comb-filter, and the feedback makes the notches resonant — that is the jet-plane sweep.",
      phaser: "Phaser: allpass stages, not a delay. The notches are not harmonically spaced, which is why it sounds hollow rather than metallic.",
      tremolo: "Tremolo: amplitude only, no delay at all. The control here — if you heard level moving and no pitch or comb character, this is it.",
    }[target[0]]),
  };
}

/** Interval. Harmonic vocabulary, built the boring reliable way. */
async function intervalId(level, seed) {
  const r = rng(seed);
  const all = [[0, "Unison"], [1, "Minor 2nd"], [2, "Major 2nd"], [3, "Minor 3rd"],
               [4, "Major 3rd"], [5, "Perfect 4th"], [6, "Tritone"], [7, "Perfect 5th"],
               [8, "Minor 6th"], [9, "Major 6th"], [10, "Minor 7th"], [11, "Major 7th"],
               [12, "Octave"]];
  const easy = [0, 5, 7, 12, 4, 3];
  const set = level <= 2
    ? all.filter((x) => easy.slice(0, 3 + level).includes(x[0]))
    : level <= 3 ? all.filter((x) => [0, 3, 4, 5, 7, 9, 12].includes(x[0])) : all;
  const target = pick(r, set);
  const root = 55 + Math.floor(r() * 10);
  const together = level >= 4 && r() > 0.5;

  const dur = 1.2;
  const a = A.synth.harmonic(dur, A.noteHz(root), { partials: 7, gain: 0.2 });
  const b = A.synth.harmonic(dur, A.noteHz(root + target[0]), { partials: 7, gain: 0.2 });
  const out = new Float32Array(Math.floor((together ? dur : dur * 2) * A.SR));
  if (together) {
    for (let i = 0; i < out.length; i++) out[i] = (a[i] || 0) + (b[i] || 0);
  } else {
    out.set(a, 0);
    out.set(b, Math.floor(dur * A.SR));
  }

  return {
    prompt: together ? "Two notes together. What is the interval?"
                     : "Two notes in sequence. What is the interval?",
    choices: set.map((s) => s[1]),
    answer: set.findIndex((s) => s[0] === target[0]),
    mount: mountPlayer([A.matchRms(await A.processOffline(A.fade(out), (ctx, s) => s))], ["Play"]),
    explain: (chosen) => {
      const got = set[chosen];
      if (!got || got[0] === target[0]) return `${target[1]} — ${target[0]} semitones.`;
      return `${target[1]} (${target[0]} semitones). You heard ${got[1]} — ` +
             `${Math.abs(got[0] - target[0])} semitone(s) out. Sing the answer back ` +
             `before you replay it; recognising and reproducing train differently.`;
    },
  };
}

/** How flat? Detune discrimination, down to a few cents if you get there. */
async function pitchCents(level, seed) {
  const r = rng(seed);
  const sets = [[0, 40, -40], [0, 25, -25], [0, 14, -14], [0, 8, -8], [0, 4, -4]];
  const cents = sets[clamp(level - 1, 0, 4)];
  const target = pick(r, cents);
  const hz = A.noteHz(57 + Math.floor(r() * 8));
  const ref = A.synth.harmonic(1.0, hz, { partials: 6 });
  const test = A.synth.harmonic(1.0, hz * Math.pow(2, target / 1200), { partials: 6 });
  const out = new Float32Array(ref.length * 2);
  out.set(ref, 0);
  out.set(test, ref.length);

  const labels = ["In tune", `Sharp (${Math.abs(cents[1])}¢)`, `Flat (${Math.abs(cents[1])}¢)`];
  return {
    prompt: "Reference, then test note. Is the second one in tune?",
    choices: labels,
    answer: target === 0 ? 0 : target > 0 ? 1 : 2,
    mount: mountPlayer([A.matchRms(await A.processOffline(A.fade(out), (ctx, s) => s))], ["Play"]),
    explain: () =>
      `It was ${target === 0 ? "in tune" : `${Math.abs(target)} cents ${target > 0 ? "sharp" : "flat"}`}. ` +
      `Beating between partials is the cue, not the pitch itself — listen to the ` +
      `upper harmonics, where the same ratio error is a bigger absolute difference.`,
  };
}

/** Match the loudness. You are drawing your own Fletcher-Munson curve. */
async function loudnessMatch(level, seed) {
  const r = rng(seed);
  const testHz = pick(r, [70, 110, 6000, 9000]);
  // Approximate equal-loudness offsets at a moderate listening level. Coarse
  // on purpose — the drill is about direction and rough magnitude.
  const need = testHz <= 200 ? (testHz <= 80 ? 15 : 10) : (testHz >= 8000 ? 9 : 5);
  const spread = [9, 7, 5, 3.5][clamp(level - 1, 0, 3)];
  const offsets = shuffle(r, [need, need - spread, need + spread]);

  const ref = A.synth.tone(1.1, 1000, { gain: 0.16 });
  const cands = [];
  for (const off of offsets) {
    const t = A.synth.tone(1.1, testHz, { gain: 0.16 * dbToGain(off) });
    const both = new Float32Array(ref.length * 2);
    both.set(ref, 0);
    both.set(t, ref.length);
    // No RMS match here — level is the thing under test.
    cands.push(await A.processOffline(A.fade(both), (ctx, s) => s));
  }

  return {
    prompt: `1 kHz reference, then a ${testHz} Hz tone. Which one sounds equally loud?`,
    choices: ["A", "B", "C"],
    answer: offsets.indexOf(need),
    mount: mountPlayer(cands, ["A", "B", "C"]),
    explain: (chosen) => {
      const got = offsets[chosen];
      return `The match was ${need > 0 ? "+" : ""}${need} dB — a ${testHz} Hz tone needs ` +
             `that much more level than 1 kHz to sound the same, because sensitivity ` +
             `falls away at both ends. ` +
             (got === need
               ? "Now notice: this gap gets bigger the quieter you listen. That is why a mix made loud is bass-heavy played quiet."
               : `You picked ${got > 0 ? "+" : ""}${got} dB. These curves are approximate — what matters is that you heard the direction.`);
    },
  };
}

/** Tempo. Groove work needs this to be free. */
async function tempoId(level, seed) {
  const r = rng(seed);
  const bpm = 70 + Math.floor(r() * 90);
  const spread = [16, 10, 6][clamp(level - 1, 0, 2)];
  const opts = shuffle(r, [bpm, bpm - spread, bpm + spread, bpm + spread * 2]);
  const src = A.synth.drumLoop(4.0, { bpm, seed: Math.floor(r() * 1e6) });

  return {
    prompt: "What tempo is this?",
    choices: opts.map((b) => `${b} BPM`),
    answer: opts.indexOf(bpm),
    mount: mountPlayer([A.matchRms(await A.processOffline(src, (ctx, s) => s))], ["Play"], { loop: true }),
    explain: () =>
      `${bpm} BPM. Count against a known anchor — 120 is two beats a second — ` +
      `rather than trying to name it cold. Half-time and double-time confusions ` +
      `are the usual error, and they are worth checking before you commit.`,
  };
}

export const AUDIO_DRILLS = {
  "eq-band-id": eqBandId,
  "masking-threshold": maskingThreshold,
  "comp-ab": compAb,
  "transient-id": transientId,
  "reverb-id": reverbId,
  "haas-direction": haasDirection,
  "stereo-width": stereoWidth,
  "distortion-id": distortionId,
  "mod-id": modId,
  "interval-id": intervalId,
  "pitch-cents": pitchCents,
  "loudness-match": loudnessMatch,
  "tempo-id": tempoId,
};
