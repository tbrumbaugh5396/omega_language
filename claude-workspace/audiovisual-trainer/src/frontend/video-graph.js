// Video on the graph: a clip is a time-varying source, and a frame is a graph.
//
// The timeline used to composite with the 2D canvas and grade with a CSS
// filter string. Both are exact things — the filter functions are specified
// down to the matrix — so they compile rather than get approximated: this
// file turns a frame of the timeline into the same kind of graph a canvas
// document makes, with the same node types and the same fusion.
//
// It also holds the keyframe model, which is the other half of Phase 3. Any
// parameter may carry a track of `{t, v, ease}` in *local clip time*, so a
// keyed grade survives being moved or trimmed. The evaluator is pure and the
// export path calls exactly the same one the preview does — which is what
// makes an export reproducible.

import { createGraph, addNode } from "./render-graph.js";
import { effectNode } from "./canvas-graph.js";
import { BLEND_ORDER } from "./composite-nodes.js";

// ------------------------------------------------------------------ keyframes

export const EASES = ["linear", "hold", "smooth", "in", "out"];

const easeAt = (kind, u) => {
  if (kind === "hold") return 0;
  if (kind === "smooth") return u * u * (3 - 2 * u);
  if (kind === "in") return u * u;
  if (kind === "out") return 1 - (1 - u) * (1 - u);
  return u;
};

/**
 * A track's value at local time t. Before the first key it holds the first
 * value, after the last it holds the last — so a single key is a constant,
 * which is the least surprising thing a single key can mean.
 */
export function evalTrack(track, t) {
  if (!track || !track.length) return null;
  const ks = track;
  if (t <= ks[0].t) return ks[0].v;
  if (t >= ks[ks.length - 1].t) return ks[ks.length - 1].v;
  for (let i = 0; i < ks.length - 1; i++) {
    const a = ks[i], b = ks[i + 1];
    if (t < a.t || t > b.t) continue;
    const span = Math.max(1e-6, b.t - a.t);
    const u = easeAt(a.ease || "linear", (t - a.t) / span);
    return a.v + (b.v - a.v) * u;
  }
  return ks[ks.length - 1].v;
}

/** Keep a track sorted and free of duplicate times. */
export function putKey(track, t, v, ease = "linear") {
  const ks = (track || []).filter((k) => Math.abs(k.t - t) > 1e-4);
  ks.push({ t: +t.toFixed(4), v, ease });
  ks.sort((a, b) => a.t - b.t);
  return ks;
}

export const hasKeys = (clip, path) => !!(clip.keys && clip.keys[path] && clip.keys[path].length);

/** A parameter's value at local time t: the track if it has one, else the stored value. */
export function paramAt(clip, path, stored, t) {
  if (!hasKeys(clip, path)) return stored;
  const v = evalTrack(clip.keys[path], t);
  return v === null ? stored : v;
}

/**
 * The clip as it is at local time t: opacity, grade and every effect
 * parameter resolved through their tracks. Nothing else in the clip moves,
 * so the result is a shallow copy with three fields replaced.
 */
export function clipAt(clip, t) {
  const grade = { ...(clip.grade || {}) };
  for (const k of Object.keys(grade)) grade[k] = paramAt(clip, `grade.${k}`, grade[k], t);
  const effects = (clip.effects || []).map((e) => {
    const params = { ...(e.params || {}) };
    for (const k of Object.keys(params)) {
      const v = params[k];
      if (typeof v === "number") params[k] = paramAt(clip, `fx.${e.id}.${k}`, v, t);
      else if (Array.isArray(v) && typeof v[0] === "number" && v.length === 1) {
        params[k] = [paramAt(clip, `fx.${e.id}.${k}`, v[0], t)];
      }
    }
    // A sketch effect runs at the clip's own time, so it animates with the
    // clip and stays a pure function of the frame — which is what lets an
    // export be repeated.
    return e.kind === "sketch" ? { ...e, params, time: t } : { ...e, params };
  });
  return { ...clip, opacity: paramAt(clip, "opacity", clip.opacity ?? 1, t), grade, effects };
}

/** Every parameter of a clip that can be keyed, as [path, label, get, set]. */
export function keyablePaths(clip) {
  const out = [["opacity", "opacity"]];
  for (const k of Object.keys(clip.grade || {})) out.push([`grade.${k}`, k]);
  for (const e of clip.effects || []) {
    for (const [k, v] of Object.entries(e.params || {})) {
      if (typeof v === "number" || (Array.isArray(v) && v.length === 1)) out.push([`fx.${e.id}.${k}`, k]);
    }
  }
  return out;
}

// ------------------------------------------------------------------ the grade

export const DEFAULT_GRADE = { brightness: 1, contrast: 1, saturate: 1, hue: 0, blur: 0 };

/**
 * The number of taps the filter spec's blur uses for a standard deviation.
 * A CSS blur is three box blurs, not a true Gaussian, and this is the size
 * the spec prescribes — so the graph reproduces what the browser drew rather
 * than something that merely looks similar.
 */
export const boxSizeFor = (sigma) => Math.floor(sigma * 3 * Math.sqrt(2 * Math.PI) / 4 + 0.5);

/**
 * A clip's grade as graph effects: one pass for the colour matrices, then the
 * spec's three box blurs per axis if there is any blur. `scale` maps document
 * pixels to the pixels being drawn, so the preview and the export blur by the
 * same visible amount — which the CSS-filter path never did.
 */
export function gradeEffects(grade, scale = 1) {
  const g = { ...DEFAULT_GRADE, ...(grade || {}) };
  const out = [];
  if (g.brightness !== 1 || g.contrast !== 1 || g.saturate !== 1 || g.hue !== 0) {
    out.push({ kind: "node", ref: "filter.cssGrade", params: {
      brightness: [g.brightness], contrast: [g.contrast], saturation: [g.saturate], hue: [g.hue] } });
  }
  const sigma = (g.blur || 0) * scale;
  if (sigma > 0.05) {
    const d = boxSizeFor(sigma);
    if (d > 0) {
      // Odd: three boxes centred on the pixel. Even: one shifted left, one
      // shifted right, then one of d+1 centred — the spec's own recipe.
      const runs = (d % 2)
        ? [[-(d - 1) / 2, (d - 1) / 2], [-(d - 1) / 2, (d - 1) / 2], [-(d - 1) / 2, (d - 1) / 2]]
        : [[-d / 2, d / 2 - 1], [-d / 2 + 1, d / 2], [-d / 2, d / 2]];
      for (const dir of [[1, 0], [0, 1]]) {
        for (const [lo, hi] of runs) {
          out.push({ kind: "node", ref: "filter.box1d", params: { lo: [lo], hi: [hi], dir } });
        }
      }
    }
  }
  return out;
}

// ------------------------------------------------------------------ the frame

/**
 * One frame of the timeline as a graph. `clips` is [{clip, pixels}] in draw
 * order, already resolved to this instant and rasterised to the target size
 * (media letterboxed, titles drawn); `alphaOf(clip)` is its fade and opacity.
 * Returns { graph, sources } for renderGraph.
 */
export function frameGraph(clips, { width, height, background = "#000000", alphaOf, scale = 1 }) {
  const graph = createGraph(width, height);
  const sources = {};
  const bg = hexToRgb(background);
  let acc = addNode(graph, "source.flat", { colour: bg, alpha: [1] }, []);
  for (const { clip, pixels, transition, preApplied } of clips) {
    if (!pixels) continue;
    const sid = addNode(graph, "source");
    sources[sid] = pixels;
    let out = sid;
    // A chain with a CPU or sketch step in it cannot be expressed as nodes, so
    // the caller ran it and hands over the result; everything else is compiled.
    if (!preApplied) {
      for (const e of gradeEffects(clip.grade, scale)) out = effectNode(graph, out, e);
      for (const e of (clip.effects || []).filter((x) => !x.bypass)) out = effectNode(graph, out, e);
    }
    if (transition) {
      // A cut with an overlap is a two-input node: the outgoing frame is
      // whatever has been composited so far, the incoming one is this clip.
      acc = addNode(graph, "transition.mix", {
        mode: [transition.mode], progress: [transition.progress],
        angle: [transition.angle ?? 0], colour: transition.colour || [0, 0, 0],
        softness: [transition.softness ?? 0.08],
      }, [acc, out]);
      continue;
    }
    const mode = Math.max(0, BLEND_ORDER.indexOf(clip.blend || "source-over"));
    acc = addNode(graph, "composite.layer", { mode: [mode], opacity: [alphaOf(clip)] }, [acc, out]);
  }
  graph.output = acc;
  return { graph, sources };
}

function hexToRgb(hex) {
  const h = String(hex).replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full || "000000", 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
