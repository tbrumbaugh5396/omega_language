// A title, compiled: the type becomes a distance field in the shader.
//
// A canvas title is pixels drawn by the text engine — fine, and what the
// video studio has always done. Compiling it instead makes it three things it
// was not: part of the frame's ejected GLSL, resolution-independent at any
// export size, and a *field* rather than a picture, which is what lets an
// effect thicken it, outline it or push it around by its distance.
//
// It is opt-in per clip, because the two rasterisers do not agree to the
// pixel and an existing title should not move because a feature arrived.

import { buildAtlas, emitTextRun, GLYPH_HELPER } from "./glyph-atlas.js";
import { defineNode, nodeType } from "./render-graph.js";
import { prepareNode } from "./graph-compile.js";

const num = (v, d = 2) => {
  const n = Number.isFinite(+v) ? +v : 0;
  const s = n.toFixed(d).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return /[.eE]/.test(s) ? s : s + ".0";
};
const rgb = (hex, fallback = "#ffffff") => {
  const s = /^#[0-9a-fA-F]{6}$/.test(String(hex)) ? String(hex) : fallback;
  return [1, 3, 5].map((k) => (parseInt(s.slice(k, k + 2), 16) / 255).toFixed(4)).join(", ");
};

const hash = (s) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
};

/** What a compiled title depends on: change any of it and it is a new node. */
const keyOf = (clip, W, H) => hash(JSON.stringify([
  clip.text || "", clip.size || 64, clip.color || "#ffffff", clip.bg ?? "#000000",
  clip.family || "system-ui, sans-serif", clip.weight || 600, W, H]));

const pending = new Map();

/**
 * The node type id for this title, or null while it is still being built.
 * Building rasterises and distance-transforms every character it uses, which
 * is asynchronous; `onReady` is called once it can be drawn.
 */
export function titleNode(clip, W, H, onReady) {
  const key = keyOf(clip, W, H);
  const id = `source.title.${key}`;
  if (nodeType(id)) return id;
  if (pending.has(key)) return null;
  pending.set(key, true);
  compile(clip, W, H, id).then((ok) => {
    pending.delete(key);
    if (ok && onReady) onReady(id);
  }).catch(() => pending.delete(key));
  return null;
}

/** The same, awaited: for anything that can wait, such as the self-test. */
export async function compileTitleNode(clip, W, H) {
  const id = `source.title.${keyOf(clip, W, H)}`;
  if (nodeType(id)) return id;
  return (await compile(clip, W, H, id)) ? id : null;
}

async function compile(clip, W, H, id) {
  const family = clip.family || "system-ui, sans-serif";
  const weight = clip.weight || 600;
  const run = { text: String(clip.text ?? ""), family, weight, style: "normal" };
  if (!run.text.trim()) return false;
  const atlas = await buildAtlas([run]);
  if (!atlas) return false;

  const size = clip.size || 64;
  const lines = run.text.split("\n");
  const lh = 1.2;
  // The canvas draws these with textBaseline "middle", which is the middle of
  // the em square and *not* half the font's bounding box — the two differ by
  // several pixels at this size, which is enough to see. Ask the text engine
  // where its alphabetic baseline is instead, and probe it if it will not say.
  const mid = middleToAlphabetic(`${weight} ${size}px ${family}`, size);
  const firstBaseline = H / 2 - ((lines.length - 1) / 2) * lh * size + mid;

  const emitted = emitTextRun(atlas, run, {
    size, lineHeight: lh, align: "center", boxWidth: W, firstBaseline, letterSpacing: 0,
  });
  if (!emitted) return false;

  const bgOn = clip.bg && clip.bg !== "none";
  const source = `// A title, compiled: ${lines.length} line${lines.length === 1 ? "" : "s"}, ` +
`${emitted.glyphs} glyphs, in ${family} at ${size}px.
// The glyphs are a distance field carried in this source, so this is the
// title itself rather than a picture of it — and an effect downstream can
// read the field.
// @node ${id}
// @alpha
uniform sampler2D u_font;   // @hidden the glyph atlas @data ${atlas.dataUrl}
uniform vec3  ink;          // @color @default ${rgb(clip.color, "#ffffff")}
uniform vec3  paper;        // @color @default ${rgb(bgOn ? clip.bg : "#000000")}
uniform float paperAlpha;   // @range 0 1 @default ${bgOn ? "1" : "0"}
uniform float weightPx;     // @range -8 8 @default 0 @help thicken or thin the letterforms, in pixels

${GLYPH_HELPER}
float cov(float d, float px) { return smoothstep(0.75 * px, -0.75 * px, d); }
float titleField(vec2 q) {
  vec2 lq = q;
${emitted.body}
}

vec2 FRAME = vec2(${num(W)}, ${num(H)});
vec2 q = vec2(uv.x, 1.0 - uv.y) * FRAME;
float px = FRAME.y / u_resolution.y;
float d = titleField(q) - weightPx;
float a = cov(d, px);
vec4(mix(paper, ink, a), max(paperAlpha, a))`;

  defineNode(source, { title: `Title — ${lines[0].slice(0, 20)}` });
  await prepareNode(id);
  return true;
}

/**
 * How far below a "middle" baseline the alphabetic one sits, for this font at
 * this size. The engine will usually just say; where it will not, drawing the
 * same glyph on both baselines and subtracting is exact.
 */
function middleToAlphabetic(font, size) {
  const g = document.createElement("canvas").getContext("2d");
  g.font = font;
  g.textBaseline = "middle";
  const t = g.measureText("Hg");
  if (Number.isFinite(t.alphabeticBaseline) && t.alphabeticBaseline !== 0) return -t.alphabeticBaseline;
  const n = Math.ceil(size * 3);
  const c = document.createElement("canvas");
  c.width = n; c.height = n;
  const p = c.getContext("2d");
  const inkTop = (baseline) => {
    p.fillStyle = "#000"; p.fillRect(0, 0, n, n);
    p.fillStyle = "#fff"; p.font = font; p.textAlign = "center"; p.textBaseline = baseline;
    p.fillText("H", n / 2, n / 2);
    const d = p.getImageData(0, 0, n, n).data;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (d[(y * n + x) * 4] > 128) return y;
    return n / 2;
  };
  return inkTop("alphabetic") - inkTop("middle");
}
