// Starter source for the guided builds (Part 9, module 3).
//
// Four runtimes, because the maths spine needs four kinds of hands-on:
//   glsl      a fragment shader. Uniforms: u_res, u_time, u_mouse, u_k (vec4).
//   canvas2d  draw(ctx, w, h, t, k, I) — I is the image engine.
//   audio     build(ctx, src, k, A) -> last node. A live Web Audio graph.
//   dsp       process(input, sr, k, A) -> Float32Array. Sample level.
//
// Each build is a working thing you can break, not a blank page. The comments
// in the source are part of the lesson; the goals in the registry are what to
// aim at once it runs.

export const LAB_SOURCE = {

// ------------------------------------------------------------------ glsl

"sdf-shapes": {
  runtime: "glsl",
  knobs: [["blend", 0.0, 0.4, 0.12], ["glow falloff", 2, 60, 18],
          ["glow amount", 0, 1.5, 0.6], ["repeat", 0, 1, 0]],
  source: `precision highp float;
uniform vec2  u_res;
uniform float u_time;
uniform vec4  u_k;      // blend, glow falloff, glow amount, domain repeat

// A distance function returns how far you are from a surface. Everything
// else here — fill, outline, glow, shadow — is read off that one number.
float sdCircle(vec2 p, float r) { return length(p) - r; }

float sdBox(vec2 p, vec2 b) {
  vec2 d = abs(p) - b;
  return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

// Smooth minimum: a union that reads as cast rather than cut.
float smin(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / u_res.y;

  // Domain repetition: modulo the coordinate and you get infinite copies
  // for free. Turn the fourth knob up.
  p = mix(p, mod(p + 0.25, 0.5) - 0.25, step(0.5, u_k.w));

  float d1 = sdCircle(p - vec2(sin(u_time * 0.7) * 0.22, 0.0), 0.16);
  float d2 = sdBox(p + vec2(0.16, 0.0), vec2(0.13, 0.13));
  float d  = smin(d1, d2, u_k.x);

  vec3 col = vec3(0.05, 0.06, 0.09);
  col = mix(col, vec3(0.49, 0.61, 1.0), 1.0 - smoothstep(0.0, 0.006, d));

  // Glow straight off the distance. exp() falloff is physical; linear is not.
  col += vec3(0.43, 0.90, 0.78) * exp(-abs(d) * u_k.y) * u_k.z;

  gl_FragColor = vec4(col, 1.0);
}`,
},

"noise-fbm": {
  runtime: "glsl",
  knobs: [["scale", 1, 14, 4], ["octaves", 1, 8, 5],
          ["warp", 0, 1.5, 0], ["cells", 0, 1, 0]],
  source: `precision highp float;
uniform vec2  u_res;
uniform float u_time;
uniform vec4  u_k;     // scale, octaves, domain warp, worley mix

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// Value noise: random per lattice point, smoothly interpolated between.
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);              // smoothstep, not linear
  return mix(mix(hash(i), hash(i + vec2(1,0)), f.x),
             mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y);
}

// fBm: octaves at halving amplitude and doubling frequency. Detail at every
// scale is what reads as organic.
float fbm(vec2 p, float oct) {
  float v = 0.0, a = 0.5, n = 0.0;
  for (int i = 0; i < 8; i++) {
    if (float(i) >= oct) break;
    v += noise(p) * a; n += a;
    p *= 2.0; a *= 0.5;
  }
  return v / n;
}

// Worley: distance to the nearest scattered feature point. Cells, not blobs.
float worley(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  float d = 1.0;
  for (int y = -1; y <= 1; y++)
    for (int x = -1; x <= 1; x++) {
      vec2 g = vec2(float(x), float(y));
      vec2 o = vec2(hash(i + g), hash(i + g + 17.0));
      d = min(d, length(g + o - f));
    }
  return d;
}

void main() {
  vec2 p = gl_FragCoord.xy / u_res.y * u_k.x;
  p += u_time * 0.05;

  // Domain warp: displace the lookup with more noise. This is the single
  // cheapest way to stop noise looking like noise.
  vec2 q = vec2(fbm(p + 1.7, u_k.y), fbm(p + 9.2, u_k.y));
  p += (q - 0.5) * u_k.z * 2.0;

  float v = mix(fbm(p, u_k.y), worley(p), u_k.w);
  vec3 col = mix(vec3(0.06, 0.07, 0.11), vec3(0.85, 0.88, 0.98), v);
  gl_FragColor = vec4(col, 1.0);
}`,
},

// ------------------------------------------------------------------ canvas2d

"blend-porter-duff": {
  runtime: "canvas2d",
  knobs: [["shrink", 1, 8, 4], ["edge softness", 0, 30, 12], ["", 0, 1, 0], ["", 0, 1, 0]],
  source: `// Why straight alpha halos and premultiplied does not.
// Left: composite the naive way, where fully transparent pixels still carry
// a colour (usually black) that leaks into every filter.
// Right: premultiply first, so invisible pixels contribute nothing.

const shrink = Math.max(1, Math.round(k[0]));
const soft = k[1];

// A soft-edged bright disc on a transparent background.
function layer(sw, sh) {
  const c = I.makeCanvas(sw, sh), g = I.ctx2d(c);
  const grad = g.createRadialGradient(sw/2, sh/2, sw*0.16, sw/2, sh/2, sw*0.16 + soft + 1);
  grad.addColorStop(0, "rgba(250,210,120,1)");
  grad.addColorStop(1, "rgba(250,210,120,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, sw, sh);
  return I.getImage(c);
}

// Downsample by averaging. The only difference between the two paths is
// whether colour is multiplied by alpha BEFORE the average.
function resize(img, factor, premultiply) {
  const w = Math.floor(img.width / factor), h = Math.floor(img.height / factor);
  const out = new ImageData(w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let r = 0, g2 = 0, b = 0, a = 0, n = 0;
    for (let dy = 0; dy < factor; dy++) for (let dx = 0; dx < factor; dx++) {
      const si = ((y*factor+dy) * img.width + (x*factor+dx)) * 4;
      const al = img.data[si+3] / 255;
      const m = premultiply ? al : 1;
      r += img.data[si] * m; g2 += img.data[si+1] * m; b += img.data[si+2] * m;
      a += al; n++;
    }
    a /= n;
    const di = (y * w + x) * 4;
    // Un-premultiply for display; with straight alpha there is nothing to undo.
    const div = premultiply ? (a > 0 ? n * a : 1) : n;
    out.data[di] = r/div; out.data[di+1] = g2/div; out.data[di+2] = b/div;
    out.data[di+3] = a * 255;
  }
  return out;
}

const src = layer(240, 240);
ctx.fillStyle = "#1b2440";
ctx.fillRect(0, 0, w, h);

const half = w / 2;
[false, true].forEach((pm, i) => {
  const small = resize(src, shrink, pm);
  const tmp = I.putImage(I.makeCanvas(small.width, small.height), small);
  ctx.drawImage(tmp, i * half + 20, 30, half - 40, half - 40);
  ctx.fillStyle = "#a8b0c8";
  ctx.font = "13px system-ui";
  ctx.fillText(pm ? "premultiplied" : "straight alpha (halo)", i * half + 20, h - 18);
});`,
},

"color-linear-oklab": {
  runtime: "canvas2d",
  knobs: [["hue A", 0, 360, 25], ["hue B", 0, 360, 210], ["chroma", 0, 0.2, 0.13], ["", 0, 1, 0]],
  source: `// The same two colours ramped three ways. Three different lies.
const a = k[0] * Math.PI / 180, b = k[1] * Math.PI / 180, C = k[2];
const c1 = I.oklabToRgb(0.62, Math.cos(a)*C, Math.sin(a)*C);
const c2 = I.oklabToRgb(0.62, Math.cos(b)*C, Math.sin(b)*C);

const rows = [
  ["sRGB (naive)", (t) => c1.map((v, i) => v*(1-t) + c2[i]*t)],
  ["linear light", (t) => c1.map((v, i) => {
      const l = I.srgbToLinear(v/255)*(1-t) + I.srgbToLinear(c2[i]/255)*t;
      return I.linearToSrgb(l) * 255;
    })],
  ["OKLab", (t) => {
      const A1 = I.rgbToOklab(...c1), A2 = I.rgbToOklab(...c2);
      return I.oklabToRgb(A1[0]*(1-t)+A2[0]*t, A1[1]*(1-t)+A2[1]*t, A1[2]*(1-t)+A2[2]*t);
    }],
];

ctx.fillStyle = "#0d0f18"; ctx.fillRect(0, 0, w, h);
const rh = (h - 30) / rows.length;
rows.forEach(([label, mix], r) => {
  for (let x = 0; x < w; x++) {
    ctx.fillStyle = I.hex(...mix(x / (w - 1)));
    ctx.fillRect(x, r * rh + 20, 1, rh - 26);
  }
  ctx.fillStyle = "#e8ebf5"; ctx.font = "12px system-ui";
  ctx.fillText(label, 8, r * rh + 16);
});
// Watch the midpoint. sRGB goes grey and dark; linear stays bright but the
// hue can swing; OKLab holds both lightness and hue.`,
},

"convolve-kernel": {
  runtime: "canvas2d",
  knobs: [["centre", -8, 12, 5], ["ring", -4, 4, -1], ["corner", -4, 4, 0], ["mix", 0, 1, 1]],
  source: `// Blur, sharpen and edge detection are one operation. Only the weights differ.
// Edit K directly — the knobs drive centre / edge / corner so you can sweep it.
const K = [
  k[2], k[1], k[2],
  k[1], k[0], k[1],
  k[2], k[1], k[2],
];

const src = I.scene(w, h, 12345);
const img = I.getImage(src);
const out = I.convolve(img, K);

// Blend so you can see what the kernel actually changed.
for (let i = 0; i < out.data.length; i += 4) {
  for (let c = 0; c < 3; c++) {
    out.data[i+c] = img.data[i+c] * (1 - k[3]) + out.data[i+c] * k[3];
  }
}
ctx.putImageData(out, 0, 0);

const sum = K.reduce((a, b) => a + b, 0);
ctx.fillStyle = "#e8ebf5"; ctx.font = "12px ui-monospace, monospace";
ctx.fillText("sum " + sum.toFixed(2) + (Math.abs(sum) < 0.01
  ? "  (zero sum = edge detector, output is signed)"
  : sum > 1.01 ? "  (>1 = brightens)" : ""), 10, h - 12);`,
},

"easing-curves": {
  runtime: "canvas2d",
  knobs: [["duration s", 0.2, 3, 1], ["overshoot", 0, 3, 1.7], ["", 0, 1, 0], ["", 0, 1, 0]],
  source: `// Curves are the grammar of motion. Mass is communicated by overshoot.
const back = (t) => { const c = k[1]; return 1 + (c+1)*Math.pow(t-1,3) + c*Math.pow(t-1,2); };
const curves = [
  ["linear", I.EASINGS.linear],
  ["easeOut", I.EASINGS.easeOut],
  ["back", back],
];

ctx.fillStyle = "#0d0f18"; ctx.fillRect(0, 0, w, h);
const dur = k[0];
const phase = (t % (dur + 0.5)) / dur;

curves.forEach(([name, fn], i) => {
  const y = 40 + i * (h - 70) / curves.length;
  // the curve itself
  ctx.strokeStyle = "#262c42"; ctx.beginPath();
  for (let x = 0; x <= 90; x++) {
    const p = fn(x / 90);
    const py = y + 30 - p * 30;
    x ? ctx.lineTo(20 + x, py) : ctx.moveTo(20 + x, py);
  }
  ctx.stroke();
  // the object it drives
  const p = phase >= 1 ? 1 : fn(Math.max(0, phase));
  ctx.fillStyle = "#7c9cff";
  ctx.fillRect(130 + p * (w - 190), y + 6, 34, 24);
  ctx.fillStyle = "#a8b0c8"; ctx.font = "12px system-ui";
  ctx.fillText(name, 20, y - 6);
});`,
},

"saliency-map": {
  runtime: "canvas2d",
  knobs: [["layout / photo", 0, 1, 0], ["overlay", 0, 1, 0.6], ["seed", 1, 200, 42], ["", 0, 1, 0]],
  source: `// Centre-surround contrast across intensity and the two opponent channels.
// Predict the peak before you turn the overlay up.
const seed = Math.round(k[2]);
let base;
if (k[0] < 0.5) {
  const L = I.layout(w, h, seed);
  L.blocks[seed % L.blocks.length].accent = true;
  I.drawBlocks(L.ctx, L.blocks);
  base = L.canvas;
} else {
  base = I.scene(w, h, seed);
}
ctx.drawImage(base, 0, 0);

const map = I.saliencyMap(I.getImage(base));
const peak = I.saliencyPeak(map);
ctx.globalAlpha = k[1];
ctx.drawImage(I.saliencyToCanvas(map), 0, 0);
ctx.globalAlpha = 1;

ctx.strokeStyle = "#5fd39a"; ctx.lineWidth = 2;
ctx.beginPath(); ctx.arc(peak.x, peak.y, 18, 0, Math.PI*2); ctx.stroke();
// Where the model is wrong is the interesting part: it has no face detector,
// no text detector, and no idea what the image is about.`,
},

"aliasing-demo": {
  runtime: "canvas2d",
  knobs: [["frequency", 20, 300, 120], ["supersample", 1, 4, 1], ["speed", 0, 1, 0.25], ["", 0, 1, 0]],
  source: `// Moiré and metallic fizz are the same phenomenon: content above half the
// sampling rate folds back down instead of disappearing.
const freq = k[0], ss = Math.round(k[1]);
const off = t * k[2] * 40;

const img = ctx.createImageData(w, h);
for (let y = 0; y < h; y++) {
  for (let x = 0; x < w; x++) {
    let v = 0;
    // Supersampling: sample more often than the output grid, then average.
    for (let sy = 0; sy < ss; sy++) for (let sx = 0; sx < ss; sx++) {
      const fx = x + (sx + 0.5) / ss, fy = y + (sy + 0.5) / ss;
      const r = Math.hypot(fx - w/2, fy - h/2);
      v += 0.5 + 0.5 * Math.sin((r + off) * freq / 40);
    }
    v /= ss * ss;
    const i = (y * w + x) * 4;
    img.data[i] = img.data[i+1] = img.data[i+2] = v * 255;
    img.data[i+3] = 255;
  }
}
ctx.putImageData(img, 0, 0);
// The rings you see near the centre are real. The ones near the edge, where
// the pattern is finer than the pixel grid, are not.`,
},

// ------------------------------------------------------------------ audio

"biquad-response": {
  runtime: "audio",
  sourceKind: "drums",
  knobs: [["frequency", 40, 12000, 500], ["Q", 0.3, 18, 1], ["gain dB", -18, 18, 0], ["type", 0, 4, 0]],
  source: `// One two-pole two-zero difference equation. Only the coefficients differ.
// Sweep a narrow boost to find what is fighting; then cut instead of boosting.
const types = ["peaking", "lowpass", "highpass", "lowshelf", "highshelf"];

const f = ctx.createBiquadFilter();
f.type = types[Math.min(4, Math.round(k[3]))];
f.frequency.value = k[0];
f.Q.value = k[1];
f.gain.value = k[2];

src.connect(f);
return f;

// Things to hear:
//  · Q above ~8 stops shaping and starts ringing — the filter becomes a voice.
//  · A big boost and an equal cut are not inverses: minimum-phase EQ costs
//    phase, and the phase does not come back.`,
},

"delay-comb": {
  runtime: "audio",
  sourceKind: "pad",
  knobs: [["delay ms", 0.2, 400, 12], ["feedback", 0, 0.85, 0.3],
          ["LFO rate", 0, 6, 0], ["LFO depth ms", 0, 8, 0]],
  source: `// One delay line passes through every regime. Sweep the first knob slowly
// and name each one as you cross it:
//   < 1 ms   comb filtering you hear as tone colour
//   1-10 ms  flanging (with feedback) / phasey doubling
//   10-30 ms chorus, then Haas width
//   30-80 ms slapback
//   > 80 ms  echo, then rhythm

const d = ctx.createDelay(1.0);
d.delayTime.value = k[0] / 1000;

const fb = ctx.createGain();
fb.gain.value = k[1];
d.connect(fb).connect(d);

if (k[2] > 0.01) {
  const lfo = ctx.createOscillator();
  const amt = ctx.createGain();
  lfo.frequency.value = k[2];
  amt.gain.value = k[3] / 1000;
  lfo.connect(amt).connect(d.delayTime);
  lfo.start();
}

const mix = ctx.createGain();
src.connect(d);
src.connect(mix);
d.connect(mix);
return mix;`,
},

"convolution-reverb": {
  runtime: "audio",
  sourceKind: "voice",
  knobs: [["decay s", 0.2, 5, 1.8], ["pre-delay ms", 0, 120, 20],
          ["damping", 0, 0.9, 0.35], ["wet", 0, 1, 0.5]],
  source: `// An impulse response is noise shaped by an envelope. That is genuinely it.
// Pre-delay is the design control: it separates the source from the space,
// which is how you place a voice in a room without pushing it away from you.

const sr = ctx.sampleRate;
const len = Math.floor(k[0] * sr);
const pre = Math.floor(k[1] / 1000 * sr);
const ir = ctx.createBuffer(2, len + pre, sr);

for (let c = 0; c < 2; c++) {
  const d = ir.getChannelData(c);
  let lp = 0;
  for (let i = 0; i < len; i++) {
    const tt = i / len;
    const env = Math.pow(1 - tt, 3.0);          // decay shape
    const white = Math.random() * 2 - 1;
    lp += (white - lp) * (1 - k[2] * tt);       // top goes dark first
    d[pre + i] = lp * env;
  }
}

const conv = ctx.createConvolver();
conv.buffer = ir;
conv.normalize = true;

const wet = ctx.createGain(); wet.gain.value = k[3];
const dry = ctx.createGain(); dry.gain.value = 1 - k[3] * 0.6;
const out = ctx.createGain();
src.connect(conv).connect(wet).connect(out);
src.connect(dry).connect(out);
return out;`,
},

// ------------------------------------------------------------------ dsp

"waveshaper-curve": {
  runtime: "dsp",
  sourceKind: "pad",
  knobs: [["drive", 1, 40, 8], ["asymmetry", 0, 1, 0], ["fold", 0, 1, 0], ["output", 0, 1, 0.6]],
  source: `// A memoryless transfer curve. Its shape decides the harmonic series:
//   odd symmetry  -> odd harmonics only: hollow, aggressive
//   asymmetry     -> even harmonics appear: warm, valve-like
//   folding       -> harmonics that are not a simple series at all
const out = new Float32Array(input.length);
const drive = k[0], asym = k[1], fold = k[2];

function shape(x) {
  const g = x >= 0 ? drive : drive * (1 - asym * 0.7);   // asymmetry
  const s = Math.tanh(x * g) / Math.tanh(g);
  const f = Math.sin(x * (1 + fold * 6) * Math.PI * 0.5);
  return s * (1 - fold) + f * fold;
}

for (let i = 0; i < input.length; i++) out[i] = shape(input[i]) * k[3];
return out;

// Check on the scope: with asymmetry at 0 the even harmonics should be
// missing. Turn it up and watch them fill in.`,
},

"granular-cloud": {
  runtime: "dsp",
  sourceKind: "voice",
  knobs: [["grain ms", 2, 200, 60], ["density /s", 1, 120, 20],
          ["position", 0, 1, 0.3], ["spray", 0, 1, 0.2]],
  source: `// Grains: windowed slices scattered in time. Pitch and duration come apart,
// which is what makes freezes and endless beds possible.
// Push density past ~20 grains/second and the rhythm becomes a pitch — the
// boundary is perceptual, not mathematical.

const out = new Float32Array(sr * 4);
const grainLen = Math.floor(k[0] / 1000 * sr);
const density = k[1];
const step = Math.max(1, Math.floor(sr / density));

for (let start = 0; start < out.length; start += step) {
  const jitter = (Math.random() * 2 - 1) * k[3] * input.length * 0.5;
  let read = Math.floor(k[2] * input.length + jitter);
  read = Math.max(0, Math.min(input.length - grainLen - 1, read));
  for (let i = 0; i < grainLen && start + i < out.length; i++) {
    // Hann window. Without it every grain edge is a click.
    const win = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / grainLen);
    out[start + i] += input[read + i] * win * 0.5;
  }
}
return out;`,
},

"fourier-scope": {
  runtime: "dsp",
  sourceKind: "pad",
  knobs: [["partials", 1, 40, 8], ["odd only", 0, 1, 1],
          ["tilt", 0.2, 3, 1], ["fundamental", 40, 400, 110]],
  source: `// Additive synthesis: build the waveform out of its spectrum and watch the
// scope agree. A square wave is odd harmonics falling as 1/n — nothing else.
const out = new Float32Array(sr * 2);
const f0 = k[3], n = Math.round(k[0]), oddOnly = k[1] > 0.5, tilt = k[2];

for (let p = 1; p <= n; p++) {
  if (oddOnly && p % 2 === 0) continue;
  const f = f0 * p;
  if (f > sr / 2 - 500) break;
  const a = 0.35 / Math.pow(p, tilt);
  for (let i = 0; i < out.length; i++) {
    out[i] += Math.sin(2 * Math.PI * f * i / sr) * a;
  }
}
return out;

// Try: odd only, tilt 1 -> square. Odd only, tilt 2 -> triangle.
// All partials, tilt 1 -> sawtooth. The tilt IS the timbre.`,
},

};
