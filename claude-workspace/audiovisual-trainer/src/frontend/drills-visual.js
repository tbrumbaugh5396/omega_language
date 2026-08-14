// Eye drills. Stimuli are generated per trial, never stock, so the drill
// trains discrimination of the dimension rather than recognition of a picture.
//
// A generator returns:
//   { prompt, kind, choices[], answer, mount(host, resolve)->cleanup, explain() }
// kind "choice" uses choices/answer; kind "click" calls resolve(correct, text).

import { el, rng, pick, shuffle, clamp } from "./ui.js";
import * as I from "./engine-image.js";

const W = 420, H = 260;

function show(canvas, { width = "100%" } = {}) {
  canvas.style.width = width;
  canvas.style.height = "auto";
  return canvas;
}

function abPanes(a, b, labels = ["A", "B"]) {
  return el("div.ab", {},
    el("div.ab-pane", {}, show(a), el("div.dim", { style: { marginTop: ".3rem" } }, labels[0])),
    el("div.ab-pane", {}, show(b), el("div.dim", { style: { marginTop: ".3rem" } }, labels[1])));
}

// ------------------------------------------------------------------ drills

/** Even the spacing. Spacing is judged by area between letters, not distance. */
function kerningAb(level, seed) {
  const r = rng(seed);
  const words = ["HAMBURGER", "AVIATOR", "TYPEFACE", "WATERLOO", "PLAYWRIGHT",
                 "VOLTAGE", "JAWLINE", "RESONANCE"];
  const word = pick(r, words);
  const jitter = [7, 5, 3.5, 2.2, 1.4][clamp(level - 1, 0, 4)];

  const draw = (offsets) => {
    const c = I.makeCanvas(W, 110);
    const g = I.ctx2d(c);
    g.fillStyle = "#0f1320";
    g.fillRect(0, 0, W, 110);
    g.fillStyle = "#e8ebf5";
    g.font = "600 42px system-ui, sans-serif";
    g.textBaseline = "middle";
    const widths = [...word].map((ch) => g.measureText(ch).width);
    const total = widths.reduce((a, b) => a + b, 0) + offsets.reduce((a, b) => a + b, 0);
    let x = (W - total) / 2;
    [...word].forEach((ch, i) => {
      x += offsets[i] || 0;
      g.fillText(ch, x, 55);
      x += widths[i];
    });
    return c;
  };

  const even = new Array(word.length).fill(0);
  const uneven = [...word].map((_, i) => (i === 0 ? 0 : (r() * 2 - 1) * jitter));
  const firstIsEven = r() > 0.5;
  const a = draw(firstIsEven ? even : uneven);
  const b = draw(firstIsEven ? uneven : even);

  return {
    prompt: "Which one is evenly spaced?",
    kind: "choice",
    choices: ["A", "B"],
    answer: firstIsEven ? 0 : 1,
    mount: (host) => { host.append(el("div.stack", {}, abPanes(a, b))); },
    explain: () =>
      `The uneven one was perturbed by up to ${jitter}px per pair. Kerning is not ` +
      `judged as distance between outlines — it is judged as the area of the gap. ` +
      `Round-to-straight and straight-to-diagonal pairs need different distances ` +
      `to read as the same space, which is why letter-spacing alone never fixes it.`,
  };
}

/** Spot the break. The margin shrinks as you improve. */
function alignmentGrid(level, seed) {
  const r = rng(seed);
  const off = [10, 7, 5, 3, 2][clamp(level - 1, 0, 4)];
  const { canvas, ctx: g, blocks } = I.layout(W, H, Math.floor(r() * 1e6));
  const idx = Math.floor(r() * blocks.length);
  const axis = r() > 0.5 ? "x" : "y";
  const dir = r() > 0.5 ? 1 : -1;
  const bad = { ...blocks[idx] };
  bad[axis] += off * dir;
  const shown = blocks.map((b, i) => (i === idx ? bad : b));
  I.drawBlocks(g, shown);

  return {
    prompt: `One block is off the grid by a few pixels. Click it.`,
    kind: "click",
    mount: (host, resolve) => {
      const c = show(canvas);
      c.style.cursor = "crosshair";
      c.onclick = (e) => {
        const rect = c.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * W;
        const y = ((e.clientY - rect.top) / rect.height) * H;
        const hit = x >= bad.x && x <= bad.x + bad.w && y >= bad.y && y <= bad.y + bad.h;
        // Mark the answer so the eye gets the correction immediately.
        g.strokeStyle = hit ? "#5fd39a" : "#f2708a";
        g.lineWidth = 2;
        g.strokeRect(bad.x - 1, bad.y - 1, bad.w + 2, bad.h + 2);
        c.onclick = null;
        resolve(hit,
          `It was ${off}px ${dir > 0 ? (axis === "x" ? "right" : "down") : (axis === "x" ? "left" : "up")} ` +
          `of its column. Misalignment is found by scanning the edges, not the shapes — ` +
          `let your eye run down each margin as a line and the break shows up as a kink.`);
      };
      host.append(c);
    },
  };
}

/** Which grouping law is doing the work? */
function gestaltGroup(level, seed) {
  const r = rng(seed);
  const laws = [
    ["proximity", "Proximity"],
    ["similarity", "Similarity"],
    ["continuity", "Continuity"],
    ["closure", "Closure"],
    ["fate", "Common fate"],
  ];
  const opts = level <= 1 ? laws.slice(0, 3) : laws;
  const target = pick(r, opts);
  const c = I.makeCanvas(W, H);
  const g = I.ctx2d(c);
  let raf = null;

  const paint = (t = 0) => {
    g.fillStyle = "#0f1320";
    g.fillRect(0, 0, W, H);
    g.fillStyle = "#e8ebf5";
    const dot = (x, y, rr = 5, color = "#e8ebf5") => {
      g.fillStyle = color;
      g.beginPath(); g.arc(x, y, rr, 0, Math.PI * 2); g.fill();
    };
    if (target[0] === "proximity") {
      for (let row = 0; row < 5; row++) {
        for (let col = 0; col < 8; col++) {
          const gap = col < 4 ? 0 : 34;   // one gap splits the field in two
          dot(60 + col * 34 + gap, 50 + row * 40);
        }
      }
    } else if (target[0] === "similarity") {
      for (let row = 0; row < 5; row++) {
        for (let col = 0; col < 9; col++) {
          const warm = col % 3 === 0;
          dot(50 + col * 38, 50 + row * 40, 5, warm ? "#f0a35e" : "#e8ebf5");
        }
      }
    } else if (target[0] === "continuity") {
      for (let i = 0; i < 26; i++) {
        const x = 30 + i * 14;
        dot(x, H / 2 + Math.sin(i * 0.34) * 60, 4);
        dot(x, H / 2 + (i - 13) * 3.4, 4, "#7c9cff");
      }
    } else if (target[0] === "closure") {
      g.strokeStyle = "#e8ebf5";
      g.lineWidth = 4;
      for (let k = 0; k < 3; k++) {
        const cx = 110 + k * 100, cy = H / 2;
        for (let s = 0; s < 5; s++) {
          const a0 = (s / 5) * Math.PI * 2 + 0.25;
          g.beginPath();
          g.arc(cx, cy, 44, a0, a0 + 0.85);
          g.stroke();
        }
      }
    } else {
      // common fate: a subset drifts together
      for (let row = 0; row < 5; row++) {
        for (let col = 0; col < 9; col++) {
          const moving = col >= 3 && col <= 5;
          const dx = moving ? Math.sin(t / 620) * 14 : 0;
          dot(50 + col * 38 + dx, 50 + row * 40);
        }
      }
    }
  };

  return {
    prompt: "Which grouping law is organising this field?",
    kind: "choice",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: (host) => {
      host.append(show(c));
      if (target[0] === "fate") {
        const loop = (t) => { paint(t); raf = requestAnimationFrame(loop); };
        raf = requestAnimationFrame(loop);
      } else paint();
      return () => raf && cancelAnimationFrame(raf);
    },
    explain: () => ({
      proximity: "Proximity: identical marks, and the only variable is spacing. Whitespace is the grouping instrument you already own.",
      similarity: "Similarity: identical spacing, and grouping comes entirely from a shared attribute. Weaker than proximity — which is why colour-coding a badly spaced list does not fix it.",
      continuity: "Continuity: the eye prefers a smooth path and will follow one straight through a crossing rather than turning a corner.",
      closure: "Closure: the contour is mostly missing and you see the whole shape anyway. This is how a logo survives being cropped, degraded or partly occluded.",
      fate: "Common fate: things moving together become one thing. The strongest grouping cue there is, and the most under-used — motion can group elements that no amount of spacing will.",
    }[target[0]]),
  };
}

/** Pass or fail? Calibrating a judgement you will make hundreds of times. */
function contrastRatio(level, seed) {
  const r = rng(seed);
  const bands = [["under 3:1", 0, 3], ["3:1 – 4.5:1", 3, 4.5],
                 ["4.5:1 – 7:1", 4.5, 7], ["over 7:1", 7, 99]];
  // Higher levels sit the true value nearer a boundary.
  const nudge = [0.9, 0.6, 0.35, 0.18][clamp(level - 1, 0, 3)];
  const bandIdx = Math.floor(r() * 4);
  const [, lo, hi] = bands[bandIdx];
  const wantLo = Math.max(1.2, lo), wantHi = Math.min(21, hi);
  const target = wantLo + (wantHi - wantLo) * (0.5 + (r() - 0.5) * (1 - nudge));

  // Search a background lightness that hits the target ratio for a fixed fg.
  const hue = r() * Math.PI * 2;
  const fgL = 0.2 + r() * 0.1;
  const fg = I.oklabToRgb(fgL, Math.cos(hue) * 0.05, Math.sin(hue) * 0.05);
  let bg = [255, 255, 255], best = 1e9;
  for (let L = 0.25; L <= 1.0; L += 0.005) {
    const cand = I.oklabToRgb(L, Math.cos(hue + 1.2) * 0.06, Math.sin(hue + 1.2) * 0.06);
    const d = Math.abs(I.contrastRatio(fg, cand) - target);
    if (d < best) { best = d; bg = cand; }
  }
  const actual = I.contrastRatio(fg, bg);
  const answer = bands.findIndex(([, l, h]) => actual >= l && actual < h);

  const c = I.makeCanvas(W, 150);
  const g = I.ctx2d(c);
  g.fillStyle = I.hex(...bg);
  g.fillRect(0, 0, W, 150);
  g.fillStyle = I.hex(...fg);
  g.font = "600 26px system-ui, sans-serif";
  g.fillText("Body copy at this size", 24, 62);
  g.font = "400 15px system-ui, sans-serif";
  g.fillText("and a second line of smaller supporting text", 24, 96);

  return {
    prompt: "Judge the contrast ratio by eye.",
    kind: "choice",
    choices: bands.map((b) => b[0]),
    answer: answer < 0 ? 3 : answer,
    mount: (host) => { host.append(show(c)); },
    explain: () =>
      `It was ${actual.toFixed(2)}:1 — ${actual >= 4.5 ? "passes" : "fails"} WCAG AA for body ` +
      `text (4.5:1), ${actual >= 3 ? "passes" : "fails"} for large text (3:1). Note that ` +
      `the ratio uses relative luminance, so a saturated colour can fail badly ` +
      `while looking vivid: chroma does nothing for legibility.`,
  };
}

/** Match the grade — and name the axis the other one missed on. */
function gradeAb(level, seed) {
  const r = rng(seed);
  const axes = [
    ["temp", "colour temperature", (d) => ({ temp: d * 0.5 })],
    ["sat", "saturation", (d) => ({ sat: 1 + d * 0.9 })],
    ["gamma", "midtone gamma", (d) => ({ gamma: 1 + d * 0.45 })],
    ["lift", "black lift", (d) => ({ lift: d * 0.09 })],
  ];
  const axis = pick(r, axes);
  const delta = (r() > 0.5 ? 1 : -1) * [1, 0.7, 0.5, 0.35, 0.25][clamp(level - 1, 0, 4)];
  const base = { lift: 0.01, gamma: 0.92, gain: 1.05, sat: 1.12, temp: 0.15 };

  const ref = I.scene(W, H, Math.floor(r() * 1e6));
  const other = I.scene(W, H, Math.floor(r() * 1e6));
  const refG = I.grade(I.getImage(ref), base);
  const matchG = I.grade(I.getImage(other), base);
  const missG = I.grade(I.getImage(other), { ...base, ...axis[2](delta) });

  const refC = I.putImage(I.makeCanvas(W, H), refG);
  const first = r() > 0.5;
  const a = I.putImage(I.makeCanvas(W, H), first ? matchG : missG);
  const b = I.putImage(I.makeCanvas(W, H), first ? missG : matchG);

  return {
    prompt: "Which of these two carries the same grade as the reference?",
    kind: "choice",
    choices: ["A", "B"],
    answer: first ? 0 : 1,
    mount: (host) => {
      host.append(el("div.stack", {},
        el("div.ab-pane", {}, show(refC), el("div.dim", { style: { marginTop: ".3rem" } }, "Reference")),
        abPanes(a, b)));
    },
    explain: () =>
      `The other one was off on ${axis[1]}${delta > 0 ? ", pushed up" : ", pulled down"}. ` +
      `Comparing grades works best one axis at a time: check the blacks, then the ` +
      `midtone, then the hue of the highlight — in that order, because a lift error ` +
      `looks like a temperature error until you fix the blacks.`,
  };
}

/** Opponent axes: the complement is a negation, not a rotation. */
function colorOpponent(level, seed) {
  const r = rng(seed);
  const L = 0.55 + r() * 0.2;
  const ang = r() * Math.PI * 2;
  const chroma = 0.11;
  const src = [L, Math.cos(ang) * chroma, Math.sin(ang) * chroma];
  const spread = [1.0, 0.7, 0.5, 0.35][clamp(level - 1, 0, 3)];

  const opp = [L, -src[1], -src[2]];
  const distractors = [
    [L, -src[1] * Math.cos(0.9 * spread) + src[2] * Math.sin(0.9 * spread),
        -src[2] * Math.cos(0.9 * spread) - src[1] * Math.sin(0.9 * spread)],
    [L, -src[1] * Math.cos(-0.9 * spread) + src[2] * Math.sin(-0.9 * spread),
        -src[2] * Math.cos(-0.9 * spread) - src[1] * Math.sin(-0.9 * spread)],
    [L + 0.18 * spread, -src[1] * 0.75, -src[2] * 0.75],
  ];
  const cands = shuffle(r, [opp, ...distractors]);
  const answer = cands.indexOf(opp);

  const swatch = (lab, size = 84) => {
    const c = I.makeCanvas(size, size);
    const g = I.ctx2d(c);
    g.fillStyle = I.hex(...I.oklabToRgb(...lab));
    g.fillRect(0, 0, size, size);
    return c;
  };
  const srcC = swatch(src, 120);

  return {
    prompt: "Which swatch is this colour's opponent complement?",
    kind: "choice",
    choices: ["A", "B", "C", "D"],
    answer,
    mount: (host) => {
      host.append(el("div.stack", { style: { alignItems: "center" } },
        srcC,
        el("div.row", { style: { justifyContent: "center" } },
          ...cands.map((lab, i) => el("div", { style: { textAlign: "center" } },
            swatch(lab),
            el("div.dim", {}, "ABCD"[i]))))));
    },
    explain: () =>
      `The complement is the negation of both opponent axes at the same lightness — ` +
      `red/green flipped and blue/yellow flipped. The near-misses were rotations ` +
      `rather than negations. Stare at the first swatch for fifteen seconds and ` +
      `look at white: the afterimage is the answer, because the channel fatigues.`,
  };
}

/** Spot the gamma error. The midtones give it away. */
function gammaComposite(level, seed) {
  const r = rng(seed);
  const pairs = [
    [[230, 40, 40], [40, 220, 60]],
    [[250, 190, 40], [40, 90, 240]],
    [[240, 60, 180], [60, 230, 200]],
  ];
  const [c1, c2] = pick(r, pairs);
  const mixVis = level >= 3;   // higher levels also blur, a subtler tell

  const make = (linear) => {
    const c = I.makeCanvas(W, 160);
    const g = I.ctx2d(c);
    g.fillStyle = "#0f1320";
    g.fillRect(0, 0, W, 160);
    const blend = (a, b) => {
      if (!linear) return a.map((v, i) => (v + b[i]) / 2);
      return a.map((v, i) => {
        const l = (I.srgbToLinear(v / 255) + I.srgbToLinear(b[i] / 255)) / 2;
        return I.linearToSrgb(l) * 255;
      });
    };
    g.fillStyle = I.hex(...c1); g.fillRect(20, 30, 110, 100);
    g.fillStyle = I.hex(...c2); g.fillRect(W - 130, 30, 110, 100);
    g.fillStyle = I.hex(...blend(c1, c2));
    g.fillRect(W / 2 - 55, 30, 110, 100);
    if (mixVis) {
      // A soft gradient between the two, blended the same way.
      for (let x = 0; x < 60; x++) {
        const t = x / 59;
        const m = c1.map((v, i) => {
          if (!linear) return v * (1 - t) + c2[i] * t;
          const l = I.srgbToLinear(v / 255) * (1 - t) + I.srgbToLinear(c2[i] / 255) * t;
          return I.linearToSrgb(l) * 255;
        });
        g.fillStyle = I.hex(...m);
        g.fillRect(W / 2 - 55 + x * 1.85, 138, 2, 14);
      }
    }
    return c;
  };
  const first = r() > 0.5;
  const a = make(first), b = make(!first);

  return {
    prompt: "One of these blends was done in linear light. Which one?",
    kind: "choice",
    choices: ["A", "B"],
    answer: first ? 0 : 1,
    mount: (host) => { host.append(abPanes(a, b)); },
    explain: () =>
      `The linear one is the brighter, more saturated middle. Averaging ` +
      `gamma-encoded values is averaging the wrong numbers: sRGB code values are ` +
      `roughly perceptual, not proportional to light, so the naive mean lands too ` +
      `dark. Every blur, resize, blend and antialias has this bug unless the tool ` +
      `is working in linear.`,
  };
}

/** Name the blur. The kernel is visible in the highlights. */
function blurId(level, seed) {
  const r = rng(seed);
  const kinds = [
    ["gaussian", "Gaussian"],
    ["box", "Box"],
    ["motion", "Motion"],
    ["radial", "Radial / zoom"],
    ["lens", "Lens / bokeh"],
  ];
  const opts = level <= 2 ? [kinds[0], kinds[2], kinds[3], kinds[4]] : kinds;
  const target = pick(r, opts);
  const strength = [1.3, 1.1, 0.9, 0.75][clamp(level - 1, 0, 3)];

  // Small bright points: the kernel prints itself onto every highlight.
  const sc = I.scene(W, H, Math.floor(r() * 1e6), { grain: 3 });
  const g = I.ctx2d(sc);
  for (let i = 0; i < 9; i++) {
    g.fillStyle = "#fff8e0";
    g.beginPath();
    g.arc(30 + r() * (W - 60), 30 + r() * (H - 60), 1.6, 0, Math.PI * 2);
    g.fill();
  }
  const img = I.getImage(sc);
  let out;
  if (target[0] === "gaussian") out = I.blurFast(img, 5 * strength);
  else if (target[0] === "box") out = I.convolve(img, new Array(81).fill(1), { divisor: 81 });
  else if (target[0] === "motion") out = I.motionBlur(img, 18 * strength, r() * 180);
  else if (target[0] === "radial") out = I.radialBlur(img, 0.09 * strength, 14);
  else out = I.lensBlur(img, Math.round(4 * strength) + 2);

  const c = I.putImage(I.makeCanvas(W, H), out);

  return {
    prompt: "Which blur is this?",
    kind: "choice",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: (host) => { host.append(show(c)); },
    explain: () => ({
      gaussian: "Gaussian: falls off smoothly, no structure in the highlights, no direction. The default, and the one that looks like nothing in particular.",
      box: "Box: a flat kernel, so highlights become squares and you get faint edges where the kernel ends. Cheap, and it shows.",
      motion: "Motion: a line kernel. Every highlight becomes a streak along one axis, and the direction is readable off any bright point.",
      radial: "Radial: samples along the ray from centre, so streaks point outward and the middle stays sharp.",
      lens: "Lens: a disc kernel, so bright points bloom into discs rather than fading. That shaped highlight is the whole reason bokeh reads as photographic.",
    }[target[0]]),
  };
}

/** Name the noise. Each has a signature at the feature scale. */
function noiseId(level, seed) {
  const r = rng(seed);
  const kinds = [["white", "White noise"], ["value", "Value noise"],
                 ["fbm", "fBm (fractal)"], ["worley", "Worley / cellular"]];
  const opts = level <= 1 ? [kinds[0], kinds[2], kinds[3]] : kinds;
  const target = pick(r, opts);
  const s = Math.floor(r() * 1e6);
  const scale = 0.03 + r() * 0.03;

  const c = I.makeCanvas(W, H);
  const g = I.ctx2d(c);
  const img = g.createImageData(W, H);
  const vn = I.valueNoise2D(s);
  const fb = I.fbm2D(s, 5);
  const wo = I.worley2D(s, 7);
  const rr = rng(s);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let v;
      if (target[0] === "white") v = rr();
      else if (target[0] === "value") v = vn(x * scale, y * scale);
      else if (target[0] === "fbm") v = fb(x * scale, y * scale);
      else v = wo(x / W, y / H);
      const i = (y * W + x) * 4;
      const px = Math.round(v * 255);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = px;
      img.data[i + 3] = 255;
    }
  }
  I.putImage(c, img);

  return {
    prompt: "Which noise function made this?",
    kind: "choice",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: (host) => { host.append(show(c)); },
    explain: () => ({
      white: "White: no correlation between neighbours, so there is no feature scale at all. Useless as texture on its own — it is the raw material everything else filters.",
      value: "Value noise: one octave on a lattice. Smooth blobs at a single size, and if you look you can still see the grid it was built on.",
      fbm: "fBm: octaves at halving amplitude and doubling frequency. Detail at every scale, which is what makes it read as organic — clouds, terrain, smoke.",
      worley: "Worley: distance to scattered feature points. Cells with hard ridges between them — stone, cracked earth, scales, water caustics.",
    }[target[0]]),
  };
}

/** Detail hierarchy: which one is carrying its information up high? */
function spatialFreq(level, seed) {
  const r = rng(seed);
  const gap = [3.0, 2.2, 1.7, 1.35][clamp(level - 1, 0, 3)];
  const s = Math.floor(r() * 1e6);
  const base = I.getImage(I.scene(W, H, s, { grain: 2 }));

  // A: fine detail added. B: the same image, softened. Both re-normalised so
  // overall contrast is not the cue.
  const fine = I.cloneImage(base);
  const rr = rng(s + 7);
  for (let i = 0; i < fine.data.length; i += 4) {
    const n = (rr() * 2 - 1) * 26 * gap;
    fine.data[i] += n; fine.data[i + 1] += n; fine.data[i + 2] += n;
  }
  const soft = I.blurFast(base, 1.4);

  const first = r() > 0.5;
  const a = I.putImage(I.makeCanvas(W, H), first ? fine : soft);
  const b = I.putImage(I.makeCanvas(W, H), first ? soft : fine);
  let blurred = false;

  return {
    prompt: "Which one carries more of its information in the high band?",
    kind: "choice",
    choices: ["A", "B"],
    answer: first ? 0 : 1,
    mount: (host) => {
      const panes = abPanes(a, b);
      const btn = el("button.ghost", {
        onclick: () => {
          blurred = !blurred;
          const src = [first ? fine : soft, first ? soft : fine];
          [a, b].forEach((cv, i) => I.putImage(cv, blurred ? I.blurFast(src[i], 5) : src[i]));
          btn.textContent = blurred ? "Un-squint" : "Squint test (blur both)";
        },
      }, "Squint test (blur both)");
      host.append(el("div.stack", {}, panes, el("div.row", { style: { justifyContent: "center" } }, btn)));
    },
    explain: () =>
      `One had fine detail added, the other was softened — and both were left at the ` +
      `same overall contrast so level could not be the cue. Use the squint button: ` +
      `high-band content is exactly the content that disappears under blur. If your ` +
      `composition's hierarchy changes when you squint, the hierarchy was decoration.`,
  };
}

/** Read the curve. Linear is always identifiable; that is the point. */
function easingId(level, seed) {
  const r = rng(seed);
  const all = [["linear", "Linear"], ["easeOut", "Ease out"], ["easeIn", "Ease in"],
               ["easeInOut", "Ease in-out"], ["back", "Back (overshoot)"],
               ["elastic", "Elastic"], ["bounce", "Bounce"]];
  const opts = level <= 1 ? [all[0], all[1], all[4], all[6]]
             : level <= 2 ? [all[0], all[1], all[2], all[3], all[4]]
             : all;
  const target = pick(r, opts);
  const fn = I.EASINGS[target[0]];
  const dur = 1100;
  const c = I.makeCanvas(W, 120);
  const g = I.ctx2d(c);
  let raf = null, t0 = null;

  const frame = (ts) => {
    if (t0 === null) t0 = ts;
    const t = ((ts - t0) % (dur + 700)) / dur;
    const p = t >= 1 ? 1 : fn(Math.max(0, t));
    g.fillStyle = "#0f1320";
    g.fillRect(0, 0, W, 120);
    g.strokeStyle = "#262c42";
    g.beginPath(); g.moveTo(40, 96); g.lineTo(W - 40, 96); g.stroke();
    const x = 40 + p * (W - 120);
    g.fillStyle = "#7c9cff";
    g.fillRect(x, 40, 40, 40);
    raf = requestAnimationFrame(frame);
  };

  return {
    prompt: "Which easing curve is this?",
    kind: "choice",
    choices: opts.map((o) => o[1]),
    answer: opts.findIndex((o) => o[0] === target[0]),
    mount: (host) => {
      host.append(show(c));
      raf = requestAnimationFrame(frame);
      return () => raf && cancelAnimationFrame(raf);
    },
    explain: () => ({
      linear: "Linear: constant velocity, and nothing physical moves that way — no start, no stop, so it reads as a machine changing state rather than an object moving.",
      easeOut: "Ease out: fast start, slow arrival. The default for anything entering, because the eye gets the information immediately and the settle sells the mass.",
      easeIn: "Ease in: slow start, fast exit. Reads as something leaving or falling away; used on entrances it feels sluggish.",
      easeInOut: "Ease in-out: symmetric. Neutral and safe; also the easiest to over-use, because it never quite commits to a direction.",
      back: "Back: overshoots then settles. The overshoot is what communicates mass and elasticity — remove it and the same object reads as weightless.",
      elastic: "Elastic: overshoot with decaying oscillation. Very legible, very loud; it dominates whatever it is applied to.",
      bounce: "Bounce: repeated collisions with decreasing energy. Physical and specific, which is why it reads as cartoon unless the object is actually meant to be hitting something.",
    }[target[0]]),
  };
}

/** First fixation: click where the eye lands, scored against the model. */
function saliencyPredict(level, seed) {
  const r = rng(seed);
  const useLayout = r() > 0.5;
  let canvas;
  if (useLayout) {
    const { canvas: c, ctx: g, blocks } = I.layout(W, H, Math.floor(r() * 1e6));
    // One accented block, so there is something for salience to find.
    blocks[Math.floor(r() * blocks.length)].accent = true;
    I.drawBlocks(g, blocks);
    canvas = c;
  } else {
    canvas = I.scene(W, H, Math.floor(r() * 1e6));
  }
  const map = I.saliencyMap(I.getImage(canvas));
  const peak = I.saliencyPeak(map);
  const tol = [0.22, 0.16, 0.11][clamp(level - 1, 0, 2)] * Math.hypot(W, H);

  return {
    prompt: "Click where you think the eye lands first.",
    kind: "click",
    mount: (host, resolve) => {
      const c = show(canvas);
      c.style.cursor = "crosshair";
      c.onclick = (e) => {
        const rect = c.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * W;
        const y = ((e.clientY - rect.top) / rect.height) * H;
        const dist = Math.hypot(x - peak.x, y - peak.y);
        const hit = dist <= tol;
        c.onclick = null;
        // Overlay the model so the correction is visual, not verbal.
        const g = I.ctx2d(c);
        const sal = I.saliencyToCanvas(map);
        g.globalAlpha = 0.55;
        g.drawImage(sal, 0, 0);
        g.globalAlpha = 1;
        g.strokeStyle = "#5fd39a"; g.lineWidth = 2;
        g.beginPath(); g.arc(peak.x, peak.y, tol, 0, Math.PI * 2); g.stroke();
        g.strokeStyle = hit ? "#5fd39a" : "#f2708a";
        g.beginPath(); g.arc(x, y, 8, 0, Math.PI * 2); g.stroke();
        resolve(hit,
          `You were ${Math.round(dist)}px from the model's peak (tolerance ${Math.round(tol)}px). ` +
          `The overlay is centre-surround contrast in intensity and the two opponent ` +
          `colour channels, with a centre bias. It predicts where gaze goes, not ` +
          `whether the image is worth looking at — and when you disagree with it, ` +
          `work out which cue it is missing. Faces and text beat it constantly.`);
      };
      host.append(c);
    },
  };
}

export const VISUAL_DRILLS = {
  "kerning-ab": kerningAb,
  "alignment-grid": alignmentGrid,
  "gestalt-group": gestaltGroup,
  "contrast-ratio": contrastRatio,
  "grade-ab": gradeAb,
  "color-opponent": colorOpponent,
  "gamma-composite": gammaComposite,
  "blur-id": blurId,
  "noise-id": noiseId,
  "spatial-freq": spatialFreq,
  "easing-id": easingId,
  "saliency-predict": saliencyPredict,
};
