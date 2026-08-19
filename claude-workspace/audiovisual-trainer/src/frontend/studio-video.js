// The video editor: a multi-track timeline with trimming, and an offline
// export that encodes with WebCodecs and muxes to MP4.
//
// Two things worth knowing about the design:
//
//   · Clips are positioned in absolute time on a track, not queued end to
//     end. That is what makes overlaps, cutaways, titles over footage and
//     separate audio possible at all — a sequential list cannot express any
//     of them.
//   · Export is offline and frame-exact: every frame is produced by seeking
//     the source, compositing, and handing a VideoFrame to the encoder. It is
//     slower than real time, but it cannot drop frames, and backgrounding the
//     tab no longer corrupts the result. The old real-time recorder is kept
//     only as a fallback for browsers without WebCodecs.
//
// Grading uses the canvas `filter` property rather than engine-image. A 30fps
// preview cannot afford a per-frame JS pass over half a million pixels, and a
// grade you cannot scrub against is not a grade you can judge.

import { el, clear, append, toast, modal, closeModal, knob, confirmDialog, clamp, api } from "./ui.js";
import { muxMp4 } from "./video-mux.js";
import { aiButton } from "./ai.js";
import { renderGraph, ejectGraph } from "./graph-compile.js";
import { applyEffects, effectCost, effectLabel, makeEffect, sketchEffect } from "./canvas-graph.js";
import { GRAPH_FILTERS, graphFilter } from "./filter-nodes.js";
import { FILTERS } from "./engine-image.js";
import { nodeType } from "./render-graph.js";
import { buildControls } from "./shader-controls.js";
import { sketchUniforms } from "./shader-run.js";
import { GENERATE_PRESETS } from "./studio-generate.js";
import { clipAt, frameGraph, gradeEffects, hasKeys, keyablePaths, paramAt, putKey,
         sourceTimeAt, sourceSpanOf, EASES, DEFAULT_GRADE } from "./video-graph.js";
import { parseCube } from "./lut-cube.js";
import { titleNode } from "./title-node.js";
import { userNodes } from "./node-library.js";
import { drawWaveform, drawVectorscope, drawHistogram, frameStats } from "./scopes.js";

const PREVIEW_MAX = 900;
const RULER_H = 24, ROW_H = 54, GUTTER = 116;

let uid = Date.now() % 1e5;
const nid = () => ++uid;

export async function videoEditor(host) {
  const doc = host.data;
  migrate(doc);

  const W = doc.width, H = doc.height;
  const pw = Math.min(PREVIEW_MAX, W);
  const ph = Math.round((pw * H) / W);

  const media = new Map();          // clipId -> HTMLVideoElement | HTMLImageElement
  let playing = false, playhead = 0, rafId = null, lastTs = 0;
  let selected = null, drag = null, pxPerSec = 40;

  // ---------------------------------------------------------------- model

  function migrate(d) {
    d.fps ||= 30;
    if (!d.tracks) {
      // v1 was one sequential list. Lay it out in absolute time, honouring the
      // dissolve overlap it implied, so nothing a user cut is lost.
      const vclips = [];
      let t = 0;
      for (const c of (d.clips || [])) {
        const dur = Math.max(0.1, (c.out ?? c.dur ?? 3) - (c.in ?? 0));
        const trans = c.transition === "dissolve" ? Math.min(c.transDur || 0.5, dur / 2) : 0;
        const start = Math.max(0, t - trans);
        vclips.push({ id: nid(), assetId: c.assetId, kind: c.kind, name: c.name,
          start, in: c.in || 0, dur, srcDur: c.dur || dur,
          grade: { ...DEFAULT_GRADE, ...(c.grade || {}) }, opacity: 1,
          fadeIn: trans, fadeOut: 0, audioOn: !!c.audioOn,
          text: c.text, color: c.color, bg: c.bg, size: c.size });
        t = start + dur;
      }
      d.tracks = [{ id: nid(), kind: "video", name: "V1", mute: false, clips: vclips }];
      if ((d.audio || []).length) {
        d.tracks.push({ id: nid(), kind: "audio", name: "A1", mute: false,
          clips: d.audio.map((a) => ({ id: nid(), assetId: a.assetId, kind: "audio",
            name: a.name || "audio", start: a.start || 0, in: 0,
            dur: a.dur || 5, srcDur: a.dur || 5, gain: 1, fadeIn: 0, fadeOut: 0 })) });
      }
      delete d.clips; delete d.audio;
    }
    for (const tr of d.tracks) { tr.clips ||= []; tr.mute = !!tr.mute; }
    if (!d.tracks.some((t) => t.kind === "audio")) {
      d.tracks.push({ id: nid(), kind: "audio", name: "A1", mute: false, clips: [] });
    }
  }

  const allClips = () => doc.tracks.flatMap((t) => t.clips.map((c) => ({ clip: c, track: t })));
  const clipEnd = (c) => c.start + c.dur;
  const duration = () => Math.max(1, ...allClips().map(({ clip }) => clipEnd(clip)));
  const trackOf = (clip) => doc.tracks.find((t) => t.clips.includes(clip));

  // ---------------------------------------------------------------- media

  async function ensureMedia(clip) {
    if (clip.kind === "title") return null;
    if (media.has(clip.id)) return media.get(clip.id);
    const asset = host.assets.find((a) => a.id === clip.assetId);
    if (!asset) return null;
    if (clip.kind === "image") {
      const img = new Image();
      img.src = asset.url;
      await new Promise((r) => { img.onload = r; img.onerror = r; });
      media.set(clip.id, img);
      return img;
    }
    const v = document.createElement("video");
    v.src = asset.url;
    v.preload = "auto";
    v.muted = clip.kind === "audio" ? false : !clip.audioOn;
    v.crossOrigin = "anonymous";
    await new Promise((r) => { v.onloadedmetadata = r; v.onerror = r; });
    media.set(clip.id, v);
    return v;
  }

  // ---------------------------------------------------------------- preview

  const canvas = el("canvas", { width: pw, height: ph,
    style: { width: "100%", height: "auto", background: "#000", borderRadius: "8px", display: "block" } });
  const cg = canvas.getContext("2d");

  const fadeAlpha = (clip, local) => {
    let a = clip.opacity ?? 1;
    if (clip.fadeIn > 0) a *= clamp(local / clip.fadeIn, 0, 1);
    if (clip.fadeOut > 0) a *= clamp((clip.dur - local) / clip.fadeOut, 0, 1);
    return a;
  };

  // One canvas per clip slot, reused: a timeline at 30 fps should not
  // allocate a frame's worth of canvases every frame.
  const slots = [];
  function slot(i, w, h) {
    let c = slots[i];
    if (!c) { c = slots[i] = document.createElement("canvas"); }
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    return c;
  }

  /** A clip's pixels at the target size: the media, letterboxed, or the title. */
  function clipPixels(clip, i, target) {
    const c = slot(i, target.w, target.h);
    const g = c.getContext("2d");
    g.clearRect(0, 0, target.w, target.h);
    paintClip(g, clip, target);
    return c;
  }

  function paintClip(g, clip, target = { w: pw, h: ph }) {
    g.save();
    if (clip.kind === "title") {
      if (clip.bg && clip.bg !== "none") { g.fillStyle = clip.bg; g.fillRect(0, 0, target.w, target.h); }
      g.fillStyle = clip.color || "#ffffff";
      g.textAlign = "center";
      g.textBaseline = "middle";
      const size = Math.round((clip.size || 64) * (target.w / W));
      g.font = `600 ${size}px system-ui, sans-serif`;
      const lines = String(clip.text || "").split("\n");
      lines.forEach((line, i) => {
        g.fillText(line, target.w / 2, target.h / 2 + (i - (lines.length - 1) / 2) * size * 1.2);
      });
    } else {
      const m = media.get(clip.id);
      const mw = m?.videoWidth || m?.width, mh = m?.videoHeight || m?.height;
      if (m && mw && mh) {
        const s = Math.min(target.w / mw, target.h / mh);
        g.drawImage(m, (target.w - mw * s) / 2, (target.h - mh * s) / 2, mw * s, mh * s);
      }
    }
    g.restore();
  }

  /**
   * A frame of the timeline, composited through the graph: every clip on
   * every video track, resolved to this instant, graded by the CSS filter
   * functions written out as nodes, through its own effect chain, and blended
   * by the same compositor the canvas studio uses. The preview and the export
   * call this same function — which is what keeps an export reproducible.
   */
  function renderAt(t, g = cg, target = { w: pw, h: ph }) {
    const { graph, sources } = frameGraph(frameEntries(t, target), {
      width: target.w, height: target.h, background: "#000000", scale: target.w / W,
      alphaOf: (c) => fadeAlpha(c, t - c.start) });
    renderGraph(graph, sources, { into: g });
    if (g === cg) updateScopes();
  }

  /** Every clip on screen at t, resolved and rasterised, in draw order. */
  function frameEntries(t, target = { w: pw, h: ph }) {
    const entries = [];
    let i = 0;
    for (const tr of doc.tracks) {
      if (tr.kind !== "video" || tr.mute) continue;
      const ordered = [...tr.clips].sort((a, b) => a.start - b.start);
      ordered.forEach((clip, idx) => {
        if (t < clip.start || t >= clipEnd(clip)) return;
        const local = t - clip.start;
        const at = clipAt(clip, local);
        // A compiled title goes in as a node; until its atlas is built, the
        // text engine draws it, so nothing ever waits for a frame.
        let node = null;
        if (clip.kind === "title" && clip.compiled) {
          node = titleNode(clip, W, H, () => { renderAt(playhead); });
        }
        let pixels = node ? null : clipPixels(clip, i++, target);
        // A sketch or CPU step cannot be a node, so that chain is run here and
        // the frame graph takes the result as it stands.
        const fx = (at.effects || []).filter((e) => !e.bypass);
        const preApplied = !node && fx.some((e) => e.kind !== "graph" && e.kind !== "node" && e.kind !== "lut");
        if (preApplied) {
          const scale = target.w / W;
          pixels = applyEffects(pixels, [...gradeEffects(at.grade, scale), ...fx]);
        }
        entries.push({ clip: at, pixels, node, preApplied, transition: transitionAt(ordered, idx, t) });
      });
    }
    return entries;
  }

  /**
   * Two clips that overlap on a track are a cut with a transition in it: the
   * outgoing frame is everything composited so far, the incoming one is this
   * clip, and the overlap is the whole of the transition's time.
   */
  function transitionAt(ordered, idx, t) {
    const clip = ordered[idx], prev = ordered[idx - 1];
    if (!prev || !clip.transition) return null;
    const overlap = clipEnd(prev) - clip.start;
    if (!(overlap > 0) || t >= clipEnd(prev)) return null;
    return {
      mode: clip.transition.mode | 0,
      progress: clamp((t - clip.start) / Math.max(1e-3, overlap), 0, 1),
      angle: clip.transition.angle || 0,
      softness: clip.transition.softness ?? 0.08,
      colour: hexToRgb(clip.transition.colour || "#000000"),
    };
  }
  const hexToRgb = (hex) => {
    const h = String(hex).replace("#", "");
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const n = parseInt(full || "000000", 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  };

  async function seekTo(t) {
    playhead = clamp(t, 0, duration());
    for (const { clip } of allClips()) {
      const m = media.get(clip.id);
      if (!m || clip.kind === "image" || clip.kind === "title") continue;
      const inside = playhead >= clip.start && playhead < clipEnd(clip);
      if (inside) {
        const want = sourceTimeAt(clip, playhead - clip.start);
        if (Math.abs(m.currentTime - want) > 0.12) m.currentTime = want;
      } else if (!m.paused) m.pause();
    }
    renderAt(playhead);
    drawTimeline();
  }

  function tick(ts) {
    if (!playing) return;
    const dt = lastTs ? (ts - lastTs) / 1000 : 0;
    lastTs = ts;
    playhead += dt;
    if (playhead >= duration()) { stop(); seekTo(0); return; }
    for (const { clip, track } of allClips()) {
      const m = media.get(clip.id);
      if (!m || clip.kind === "image" || clip.kind === "title") continue;
      const inside = playhead >= clip.start && playhead < clipEnd(clip);
      if (inside && m.paused && !track.mute) {
        m.currentTime = sourceTimeAt(clip, playhead - clip.start);
        m.play().catch(() => {});
      } else if ((!inside || track.mute) && !m.paused) m.pause();
    }
    renderAt(playhead);
    drawTimeline();
    rafId = requestAnimationFrame(tick);
  }
  function play() {
    if (!allClips().length) { toast("Import something first"); return; }
    playing = true; lastTs = 0;
    playBtn.textContent = "Pause";
    rafId = requestAnimationFrame(tick);
  }
  function stop() {
    playing = false;
    cancelAnimationFrame(rafId);
    playBtn.textContent = "Play";
    for (const m of media.values()) m.pause?.();
  }

  // ---------------------------------------------------------------- timeline

  const timeline = el("canvas", { style: { display: "block", cursor: "default" } });
  const tg = timeline.getContext("2d");
  const rowTop = (i) => RULER_H + i * ROW_H;
  const timelineH = () => RULER_H + doc.tracks.length * ROW_H + 6;

  function drawTimeline() {
    const dur = Math.max(duration() + 4, 12);
    const w = Math.max(700, GUTTER + dur * pxPerSec + 40);
    const h = timelineH();
    if (timeline.width !== w || timeline.height !== h) { timeline.width = w; timeline.height = h; }
    tg.fillStyle = "#0b0e16";
    tg.fillRect(0, 0, w, h);

    tg.fillStyle = "#141a2a";
    tg.fillRect(GUTTER, 0, dur * pxPerSec, RULER_H);
    tg.font = "9px ui-monospace, monospace";
    const step = pxPerSec > 60 ? 1 : pxPerSec > 25 ? 2 : 5;
    for (let s = 0; s <= dur; s += step) {
      const x = GUTTER + s * pxPerSec;
      tg.fillStyle = "#2a3350";
      tg.fillRect(x, 0, 1, h);
      tg.fillStyle = "#a8b0c8";
      tg.fillText(`${s}s`, x + 3, 15);
    }

    doc.tracks.forEach((tr, i) => {
      const y = rowTop(i);
      tg.fillStyle = i % 2 ? "#10141f" : "#0e121c";
      tg.fillRect(0, y, w, ROW_H - 2);
      tg.fillStyle = "#e8ebf5";
      tg.font = "12px system-ui";
      tg.fillText(tr.name, 8, y + 18);
      tg.fillStyle = "#6e7794";
      tg.font = "9px system-ui";
      tg.fillText(tr.kind, 8, y + 32);
      tg.fillStyle = tr.mute ? "#f2708a" : "#232a40";
      tg.fillRect(84, y + 10, 16, 13);
      tg.fillStyle = "#0b0e16";
      tg.font = "8px system-ui";
      tg.fillText("M", 88, y + 20);

      for (const clip of tr.clips) {
        const x = GUTTER + clip.start * pxPerSec;
        const cw = Math.max(6, clip.dur * pxPerSec);
        const isSel = selected === clip;
        tg.fillStyle = clip.kind === "title" ? "#3b3560"
          : clip.kind === "audio" ? "#1f4a44"
          : clip.kind === "image" ? "#274d3f" : "#2c4a63";
        tg.fillRect(x, y + 5, cw, ROW_H - 14);
        tg.strokeStyle = isSel ? "#7c9cff" : "#44548a";
        tg.lineWidth = isSel ? 2 : 1;
        tg.strokeRect(x + 0.5, y + 5.5, cw - 1, ROW_H - 15);
        tg.fillStyle = "#e8ebf5";
        tg.font = "10px system-ui";
        tg.save();
        tg.beginPath(); tg.rect(x, y + 5, cw, ROW_H - 14); tg.clip();
        tg.fillText(clip.name || clip.kind, x + 5, y + 20);
        tg.fillStyle = "#a8b0c8";
        tg.fillText(`${clip.dur.toFixed(1)}s`, x + 5, y + 33);
        tg.restore();
        // fade ramps, drawn as the triangles they are
        if (clip.fadeIn > 0) {
          tg.strokeStyle = "rgba(240,163,94,.9)";
          tg.beginPath(); tg.moveTo(x, y + ROW_H - 10);
          tg.lineTo(x + clip.fadeIn * pxPerSec, y + 6); tg.stroke();
        }
        if (clip.fadeOut > 0) {
          tg.strokeStyle = "rgba(240,163,94,.9)";
          tg.beginPath(); tg.moveTo(x + cw - clip.fadeOut * pxPerSec, y + 6);
          tg.lineTo(x + cw, y + ROW_H - 10); tg.stroke();
        }
        // Keys, at the local times they hold. Every track's keys land on the
        // same row: what matters here is when the clip changes, not which
        // parameter did.
        const keyTimes = new Set();
        for (const track of Object.values(clip.keys || {})) for (const k of track) keyTimes.add(k.t);
        for (const kt of keyTimes) {
          const kx = x + kt * pxPerSec;
          if (kx < x || kx > x + cw) continue;
          tg.fillStyle = "#6ee7c8";
          tg.beginPath();
          tg.moveTo(kx, y + ROW_H - 16); tg.lineTo(kx + 3.5, y + ROW_H - 12);
          tg.lineTo(kx, y + ROW_H - 8); tg.lineTo(kx - 3.5, y + ROW_H - 12);
          tg.closePath(); tg.fill();
        }
        // The overlap with the clip before it, when that overlap is a transition.
        if (clip.transition) {
          const before = tr.clips.filter((o) => o !== clip && o.start < clip.start)
            .sort((a2, b2) => a2.start - b2.start).pop();
          const ov = before ? clipEnd(before) - clip.start : 0;
          if (ov > 0) {
            tg.fillStyle = "rgba(124,156,255,.28)";
            tg.fillRect(x, y + 5, ov * pxPerSec, ROW_H - 14);
            tg.strokeStyle = "rgba(124,156,255,.9)";
            tg.beginPath();
            tg.moveTo(x, y + ROW_H - 10); tg.lineTo(x + ov * pxPerSec, y + 6); tg.stroke();
          }
        }
      }
    });

    if (drag?.snapX !== undefined && drag.snapX !== null) {
      tg.fillStyle = "#f0a35e";
      tg.fillRect(GUTTER + drag.snapX * pxPerSec, 0, 1, h);
    }
    tg.fillStyle = "#6ee7c8";
    tg.fillRect(GUTTER + playhead * pxPerSec, 0, 2, h);
  }

  const timeAt = (clientX) => {
    const r = timeline.getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * timeline.width;
    return (x - GUTTER) / pxPerSec;
  };
  const rowAt = (clientY) => {
    const r = timeline.getBoundingClientRect();
    const y = ((clientY - r.top) / r.height) * timeline.height;
    if (y < RULER_H) return -1;
    return Math.floor((y - RULER_H) / ROW_H);
  };

  /** Snap candidates: every other clip edge, the playhead, and zero. */
  function snapTime(t, exclude) {
    const cands = [0, playhead];
    for (const { clip } of allClips()) {
      if (clip === exclude) continue;
      cands.push(clip.start, clipEnd(clip));
    }
    const tol = 7 / pxPerSec;
    let best = null, bestD = tol;
    for (const c of cands) {
      const d = Math.abs(c - t);
      if (d < bestD) { bestD = d; best = c; }
    }
    return best;
  }

  timeline.addEventListener("pointerdown", (e) => {
    const t = timeAt(e.clientX);
    const row = rowAt(e.clientY);
    if (row < 0) { seekTo(Math.max(0, t)); return; }
    const tr = doc.tracks[row];
    if (!tr) return;

    const r = timeline.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * timeline.width;
    if (x < GUTTER) {
      if (x >= 84 && x < 100) { tr.mute = !tr.mute; host.save(); drawTimeline(); }
      return;
    }

    const tol = 7 / pxPerSec;
    let clip = tr.clips.find((c) => Math.abs(t - c.start) < tol);
    let mode = "trimIn";
    if (!clip) { clip = tr.clips.find((c) => Math.abs(t - clipEnd(c)) < tol); mode = "trimOut"; }
    if (!clip) { clip = tr.clips.find((c) => t >= c.start && t < clipEnd(c)); mode = "move"; }
    if (!clip) { selected = null; drawTimeline(); renderInspector(); return; }

    selected = clip;
    drag = { mode, clip, track: tr, grabT: t, start: clip.start, dur: clip.dur,
             inPoint: clip.in || 0, snapX: null };
    drawTimeline(); renderInspector();
  });

  timeline.addEventListener("pointermove", (e) => {
    if (!drag) {
      const t = timeAt(e.clientX), row = rowAt(e.clientY);
      const tr = doc.tracks[row];
      const tol = 7 / pxPerSec;
      const onEdge = tr?.clips.some((c) => Math.abs(t - c.start) < tol || Math.abs(t - clipEnd(c)) < tol);
      timeline.style.cursor = onEdge ? "ew-resize" : "default";
      return;
    }
    const t = timeAt(e.clientX);
    const dt = t - drag.grabT;
    const c = drag.clip;

    if (drag.mode === "move") {
      let want = Math.max(0, drag.start + dt);
      const snapped = snapTime(want, c) ?? snapTime(want + c.dur, c);
      if (snapped !== null && snapped !== undefined) {
        // Snap whichever edge is closer to a candidate.
        const byStart = snapTime(want, c);
        const byEnd = snapTime(want + c.dur, c);
        if (byStart !== null) { want = byStart; drag.snapX = byStart; }
        else if (byEnd !== null) { want = byEnd - c.dur; drag.snapX = byEnd; }
      } else drag.snapX = null;
      c.start = Math.max(0, want);
    } else if (drag.mode === "trimIn") {
      // Trimming the head moves the in-point too, so the frame under the
      // cursor is the frame that stays.
      const maxShift = c.dur - 0.1;
      let shift = clamp(dt, -(drag.inPoint), maxShift);
      const snapped = snapTime(drag.start + shift, c);
      if (snapped !== null) { shift = snapped - drag.start; drag.snapX = snapped; } else drag.snapX = null;
      shift = clamp(shift, -(drag.inPoint), maxShift);
      c.start = Math.max(0, drag.start + shift);
      c.in = Math.max(0, drag.inPoint + shift);
      c.dur = Math.max(0.1, drag.dur - shift);
    } else {
      let end = drag.start + drag.dur + dt;
      const snapped = snapTime(end, c);
      if (snapped !== null) { end = snapped; drag.snapX = snapped; } else drag.snapX = null;
      const maxDur = c.srcDur ? c.srcDur - (c.in || 0) : Infinity;
      c.dur = clamp(end - c.start, 0.1, maxDur);
    }
    drawTimeline();
  });

  timeline.addEventListener("pointerup", () => {
    if (!drag) return;
    drag = null;
    host.save(thumbnail());
    drawTimeline(); renderInspector(); seekTo(playhead);
  });

  function splitAtPlayhead() {
    const c = selected;
    if (!c || playhead <= c.start + 0.05 || playhead >= clipEnd(c) - 0.05) {
      toast("Put the playhead inside the selected clip");
      return;
    }
    const tr = trackOf(c);
    const offset = playhead - c.start;
    const right = { ...c, id: nid(), start: playhead, in: (c.in || 0) + offset,
                    dur: c.dur - offset, fadeIn: 0 };
    c.dur = offset;
    c.fadeOut = Math.min(c.fadeOut || 0, c.dur);
    tr.clips.push(right);
    selected = right;
    host.save(); drawTimeline(); renderInspector();
  }

  function onKey(e) {
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (/input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === " ") { e.preventDefault(); playing ? stop() : play(); return; }
    if (e.key.toLowerCase() === "s" && !e.metaKey && !e.ctrlKey) { e.preventDefault(); splitAtPlayhead(); return; }
    if ((e.key === "Delete" || e.key === "Backspace") && selected) {
      e.preventDefault(); removeClip(); return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "d" && selected) {
      e.preventDefault();
      const tr = trackOf(selected);
      const copy = { ...selected, id: nid(), start: clipEnd(selected) };
      tr.clips.push(copy);
      selected = copy;
      ensureMedia(copy).then(() => { host.save(); drawTimeline(); renderInspector(); });
    }
  }
  document.addEventListener("keydown", onKey);

  async function removeClip() {
    if (!selected) return;
    const tr = trackOf(selected);
    tr.clips.splice(tr.clips.indexOf(selected), 1);
    media.delete(selected.id);
    selected = null;
    host.save(); drawTimeline(); renderInspector(); seekTo(playhead);
  }

  // ---------------------------------------------------------------- inspector

  const inspector = el("div.stack");
  /** The frame at the playhead as GLSL: what the timeline compiles to, now. */
  function frameGlsl() {
    let text;
    try {
      const entries = frameEntries(playhead, { w: pw, h: ph });
      const { graph } = frameGraph(entries, { width: pw, height: ph, background: "#000000",
        scale: pw / W, alphaOf: (c) => fadeAlpha(c, playhead - c.start) });
      text = ejectGraph(graph);
    } catch (e) { text = `// ${String(e.message).split("\n")[0]}`; }
    modal(el("h2", {}, "This frame, as GLSL"),
      el("p.fine", {}, `Every clip on screen at ${playhead.toFixed(2)}s — its grade written out as the ` +
        "CSS filter functions, its effects, and the compositor — fused. Clip pixels arrive as textures; " +
        "everything else is in the text."),
      el("textarea", { rows: 18, readonly: true,
        style: { fontFamily: "ui-monospace, monospace", fontSize: ".72rem" }, value: text }),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => { navigator.clipboard.writeText(text); toast("Copied"); } }, "Copy"),
        el("button.primary", { onclick: closeModal }, "Close")));
  }

  // ---------------------------------------------------------------- scopes

  const scopeWave = el("canvas", { width: 240, height: 110, style: { width: "100%", borderRadius: "6px", display: "block" } });
  const scopeVector = el("canvas", { width: 130, height: 130, style: { width: "48%", borderRadius: "6px" } });
  const scopeHist = el("canvas", { width: 130, height: 130, style: { width: "48%", borderRadius: "6px" } });
  const scopeNote = el("p.fine", {}, "");
  let scopesOn = false, scopeDue = 0;

  /**
   * The instruments, on the frame that was actually composited — so what they
   * measure is what will be exported, not an approximation of it.
   */
  function updateScopes() {
    if (!scopesOn) return;
    const now = performance.now();
    if (now < scopeDue) return;                    // a scope at 10 Hz is still a scope
    scopeDue = now + 100;
    try {
      const img = cg.getImageData(0, 0, canvas.width, canvas.height);
      drawWaveform(img, scopeWave);
      drawVectorscope(img, scopeVector);
      drawHistogram(img, scopeHist);
      const st = frameStats(img);
      scopeNote.textContent = `mean ${(st.mean * 100).toFixed(0)} IRE · `
        + `${(st.crushed * 100).toFixed(1)}% crushed · ${(st.clipped * 100).toFixed(1)}% clipped · `
        + `cast ${(st.cast * 100).toFixed(1)}%`;
    } catch (e) { scopeNote.textContent = String(e.message).split("\n")[0]; }
  }

  const scopePanel = el("div.card", { style: { display: "none" } },
    el("h3", {}, "Scopes"),
    el("p.fine", {}, "Waveform is luma up the vertical, one column per column of the frame. " +
      "The vectorscope is hue as angle and saturation as radius, with the 75% primaries boxed and " +
      "the skin-tone line drawn. Rec. 709 throughout."),
    scopeWave,
    el("div.row.tight", { style: { justifyContent: "space-between" } }, scopeVector, scopeHist),
    scopeNote);

  // ---------------------------------------------------------------- keyframes

  const localOf = (c) => playhead - c.start;
  const insideClip = (c) => playhead >= c.start && playhead < clipEnd(c);

  /** Put a key for `path` at the playhead, holding `v`. */
  function keyHere(c, path, v) {
    if (!insideClip(c)) { toast("Move the playhead inside the clip first"); return; }
    c.keys = c.keys || {};
    c.keys[path] = putKey(c.keys[path], localOf(c), v, (c.keys[path] || []).length ? "linear" : "linear");
    drawTimeline(); renderInspector(); renderAt(playhead); host.save();
  }
  function clearKeys(c, path) {
    if (!c.keys) return;
    delete c.keys[path];
    drawTimeline(); renderInspector(); renderAt(playhead); host.save();
  }

  /**
   * A control with a keyframe diamond beside it. Moving a keyed control writes
   * a key at the playhead rather than a constant — which is what you meant by
   * moving it while it was keyed.
   */
  function keyed(c, path, label, opts, read, write) {
    const on = hasKeys(c, path);
    const shown = on ? paramAt(c, path, read(), localOf(c)) : read();
    const k = knob(label, { ...opts, value: shown,
      oninput: (v) => {
        write(v);
        if (on && insideClip(c)) c.keys[path] = putKey(c.keys[path], localOf(c), v);
        renderAt(playhead); host.save();
      } });
    return el("div.row.tight", { style: { alignItems: "center", gap: ".25rem" } },
      el("div", { style: { flex: 1 } }, k),
      el("button.ghost", {
        title: on ? `keyed (${c.keys[path].length}) — click to set one here, shift-click to clear`
                  : "keyframe this parameter at the playhead",
        style: { padding: ".05em .3em", color: on ? "var(--good, #6ee7c8)" : "var(--dim, #6e7794)" },
        onclick: (e) => (e.shiftKey ? clearKeys(c, path) : keyHere(c, path, shown)),
      }, on ? "◆" : "◇"));
  }

  /** Every key on the clip, so a track can be seen and eased and undone. */
  function keyPanel(c) {
    const paths = Object.keys(c.keys || {}).filter((p2) => (c.keys[p2] || []).length);
    if (!paths.length) return null;
    return el("div.stack", { style: { gap: ".2rem", marginTop: ".4rem" } },
      el("h4", { style: { margin: 0 } }, "Keyframes"),
      ...paths.map((p2) => el("div.spread", {},
        el("span.fine", {}, `${p2} · ${c.keys[p2].length}`),
        el("div.row.tight", {},
          el("select", { style: { width: "auto", fontSize: ".7rem" },
            title: "how this track leaves each key",
            onchange: (e) => { for (const k of c.keys[p2]) k.ease = e.target.value; renderAt(playhead); host.save(); } },
            ...EASES.map((x) => el("option", { value: x, selected: x === (c.keys[p2][0].ease || "linear") }, x))),
          el("button.ghost", { title: "previous key",
            onclick: () => { const ks = c.keys[p2].map((k) => k.t + c.start).filter((t) => t < playhead - 1e-3);
                             if (ks.length) seekTo(Math.max(...ks)); } }, "‹"),
          el("button.ghost", { title: "next key",
            onclick: () => { const ks = c.keys[p2].map((k) => k.t + c.start).filter((t) => t > playhead + 1e-3);
                             if (ks.length) seekTo(Math.min(...ks)); } }, "›"),
          el("button.ghost.danger", { onclick: () => clearKeys(c, p2) }, "×")))));
  }

  /**
   * Speed, and speed ramps. A constant is a multiplication; keyed, the source
   * time is the integral of the track, which is the difference between a ramp
   * that lands where you meant and one that slips.
   */
  function speedPanel(c) {
    if (c.kind !== "video" && c.kind !== "audio") return null;
    const ramped = hasKeys(c, "speed");
    const span = sourceSpanOf(c);
    const over = c.srcDur ? span > (c.srcDur - (c.in || 0)) + 1e-3 : false;
    return el("div.stack", { style: { gap: ".2rem", marginTop: ".4rem" } },
      el("h4", { style: { margin: 0 } }, "Speed"),
      keyed(c, "speed", "speed",
        { min: 0.1, max: 4, step: 0.01, format: (v) => `${v.toFixed(2)}×` },
        () => c.speed ?? 1, (v) => { c.speed = v; }),
      el("p.fine", {}, ramped
        ? `A ramp: it eats ${span.toFixed(2)}s of source over ${c.dur.toFixed(2)}s on the timeline.`
        : `${((c.speed ?? 1)).toFixed(2)}× — ${span.toFixed(2)}s of source over ${c.dur.toFixed(2)}s.`),
      over ? el("p.fine", { style: { color: "var(--warm)" } },
        "That runs past the end of the source; the last frame will hold.") : null);
  }

  /**
   * A transition lives in the overlap between two clips on one track: drag a
   * clip so it starts before the one before it ends, and that overlap is the
   * whole of the transition's time. It is a two-input node, so the outgoing
   * frame is a real input rather than something faded over.
   */
  function transitionPanel(c) {
    const tr = trackOf(c);
    if (!tr) return null;
    const before = tr.clips.filter((o) => o !== c && o.start < c.start)
      .sort((a, b) => a.start - b.start).pop();
    const overlap = before ? clipEnd(before) - c.start : 0;
    if (!(overlap > 0)) {
      return c.transition ? el("p.fine", { style: { color: "var(--warm)" } },
        "This clip has a transition but no overlap — drag it back over the clip before it.") : null;
    }
    const t = c.transition || (c.transition = { mode: 0, angle: 0, softness: 0.08, colour: "#000000" });
    return el("div.stack", { style: { gap: ".2rem", marginTop: ".4rem" } },
      el("h4", { style: { margin: 0 } }, "Transition"),
      el("p.fine", {}, `${overlap.toFixed(2)}s of overlap with ${before.name || before.kind}.`),
      el("select", { onchange: (e) => { t.mode = +e.target.value; renderAt(playhead); drawTimeline(); renderInspector(); host.save(); } },
        ...["dissolve", "wipe", "dip to colour", "push"].map((n, i) =>
          el("option", { value: i, selected: i === (t.mode | 0) }, n))),
      (t.mode === 1 || t.mode === 3) ? knob("angle", { min: 0, max: 360, step: 1, value: t.angle || 0,
        format: (v) => `${v.toFixed(0)}°`, oninput: (v) => { t.angle = v; renderAt(playhead); host.save(); } }) : null,
      t.mode === 1 ? knob("softness", { min: 0, max: 0.5, step: 0.005, value: t.softness ?? 0.08,
        format: (v) => v.toFixed(3), oninput: (v) => { t.softness = v; renderAt(playhead); host.save(); } }) : null,
      t.mode === 2 ? el("label.design-num", {}, "through",
        el("input", { type: "color", value: t.colour || "#000000",
          oninput: (e) => { t.colour = e.target.value; renderAt(playhead); host.save(); } })) : null,
      el("button.ghost", { onclick: () => { c.transition = null; drawTimeline(); renderAt(playhead); renderInspector(); host.save(); } },
        "no transition (fade over instead)"));
  }

  // A .cube goes into the clip as bytes, so the look travels with the file.
  const lutInput = el("input", {
    type: "file", accept: ".cube,text/plain", hidden: true,
    onchange: async (e) => {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file || !selected) return;
      try {
        const lut = parseCube(await file.text());
        selected.effects = selected.effects || [];
        selected.effects.push({ ...makeEffect("lut", "", { amount: 1 }),
                                lut, name: lut.title || file.name.replace(/\.cube$/i, "") });
        toast(`${lut.size}³ LUT loaded${lut.domain ? " (with its own domain)" : ""}`);
        renderInspector(); renderAt(playhead); host.save();
      } catch (err) { toast(`That .cube did not read: ${err.message}`); }
    },
  });

  // ---------------------------------------------------------------- clip effects

  function effectPanel(c) {
    const fx = c.effects || [];
    const cost = (() => { try { return effectCost(fx); } catch (e) { return null; } })();
    const move = (i, d) => {
      const j = i + d;
      if (j < 0 || j >= fx.length) return;
      [fx[i], fx[j]] = [fx[j], fx[i]];
      renderInspector(); renderAt(playhead); host.save();
    };
    return el("div.stack", { style: { gap: ".2rem", marginTop: ".4rem" } },
      el("div.spread", {},
        el("h4", { style: { margin: 0 } }, "Effects"),
        el("div.row.tight", {},
          el("button.ghost", { title: "load a .cube", onclick: () => lutInput.click() }, "+ LUT"),
          el("button.ghost", { onclick: () => effectDialog(c) }, "+ effect"))),
      ...fx.map((e, i) => el("div.spread", {},
        el("div.row.tight", {},
          el("input", { type: "checkbox", checked: !e.bypass, style: { width: "auto" },
            onchange: (ev) => { e.bypass = !ev.target.checked; renderAt(playhead); host.save(); } }),
          el("span.fine", { style: { opacity: e.bypass ? 0.5 : 1 } }, effectLabel(e))),
        el("div.row.tight", {},
          el("button.ghost", { title: "earlier", onclick: () => move(i, -1) }, "↑"),
          el("button.ghost", { title: "later", onclick: () => move(i, 1) }, "↓"),
          el("button.ghost.danger", {
            onclick: () => { fx.splice(i, 1); renderInspector(); renderAt(playhead); host.save(); } }, "×")))),
      ...fx.flatMap((e) => Object.entries(e.params || {})
        .filter(([, v]) => typeof v === "number" || (Array.isArray(v) && v.length === 1))
        .map(([k, v]) => keyed(c, `fx.${e.id}.${k}`, `${effectLabel(e)} · ${k}`,
          { min: paramRange(e, k)[0], max: paramRange(e, k)[1], step: (paramRange(e, k)[1] - paramRange(e, k)[0]) / 100,
            format: (x) => (Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(2)) },
          () => (Array.isArray(v) ? v[0] : v),
          (x) => { e.params[k] = Array.isArray(v) ? [x] : x; }))),
      fx.length && cost ? el("p.fine", {}, `${cost.draws} GPU draw${cost.draws === 1 ? "" : "s"}` +
        `${cost.cpu ? ` · ${cost.cpu} outside the graph` : ""} on top of the grade`) : null);
  }

  /** A parameter's sensible range, from the CPU filter or the node it came from. */
  function paramRange(e, name) {
    if (e.kind === "graph") {
      const gf = GRAPH_FILTERS.find((f) => f.id === e.ref);
      const cpu = gf && FILTERS.find((f) => f.id === gf.cpu);
      const row = cpu && cpu.params.find((p2) => p2[0] === name);
      if (row) return [row[1], row[2]];
    }
    if (e.kind === "node") {
      const t = nodeType(e.ref);
      const u = t && t.params.find((p2) => p2.name === name);
      if (u) return [u.min, u.max];
    }
    return [0, 1];
  }
  async function effectDialog(c) {
    const presets = GENERATE_PRESETS.filter((p2) => /\bsampler2D\b/.test(p2.source));
    const pick = el("select", {},
      el("optgroup", { label: "Catalogue (GPU)" },
        ...GRAPH_FILTERS.filter((f) => !f.cpuOnly).map((f) => el("option", { value: `g:${f.id}` }, f.name))),
      el("optgroup", { label: "Render graph nodes" },
        el("option", { value: "n:adjust.exposure" }, "Exposure"),
        el("option", { value: "n:adjust.curves" }, "Curves"),
        el("option", { value: "n:filter.blur" }, "Gaussian blur")),
      userNodes().length ? el("optgroup", { label: "Your nodes" },
        ...userNodes().map((n) => el("option", { value: `n:${n.id}` }, n.name))) : null,
      el("optgroup", { label: "Shader — Generate presets that take an image" },
        ...presets.map((p2) => el("option", { value: `s:${p2.id}` }, p2.label))));
    modal(el("h2", {}, "Clip effect"),
      el("p.fine", {}, "The same node types the canvas studio uses. A catalogue filter or a " +
        "node fuses into the clip's grade — one draw for the lot. A sketch runs as its own pass, " +
        "and if it keeps state it steps deterministically from the frame's time, so an export repeats."),
      pick,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: closeModal }, "Cancel"),
        el("button.primary", { onclick: () => {
          const v = pick.value, kind = v[0], ref = v.slice(2);
          let e = null;
          if (kind === "g") {
            const gf = graphFilter(ref);
            const params = {};
            const cpu = FILTERS.find((f) => f.id === gf.cpu);
            for (const [n2, , , def] of (cpu ? cpu.params : [])) params[n2] = def;
            for (const [n2, def] of (cpu && cpu.colors) || []) params[n2] = def;
            e = makeEffect("graph", ref, params);
          } else if (kind === "n") {
            const t = nodeType(ref === "filter.blur" ? "filter.blur1d" : ref);
            const params = {};
            for (const u of t.params.filter((u2) => !u2.hidden && u2.control !== "image")) params[u.name] = u.value.slice();
            e = makeEffect("node", ref, params);
          } else {
            const pr = presets.find((x) => x.id === ref);
            const values = {};
            for (const u of sketchUniforms(pr.source)) if (u.control !== "image") values[u.name] = u.value.slice();
            e = sketchEffect(pr.source, values, 0, pr.label, pr.steps);
          }
          c.effects = c.effects || [];
          c.effects.push(e);
          closeModal(); renderInspector(); renderAt(playhead); host.save();
        } }, "Add")));
  }

  function renderInspector() {
    clear(inspector);
    const c = selected;
    if (!c) {
      append(inspector, el("p.fine", {}, "Nothing selected. Import footage, or " +
        "add a title, then click a clip on the timeline."),
        el("p.fine", {}, "Drag a clip to move it, drag its edges to trim, " +
          "S splits at the playhead, ⌘D duplicates, ⌫ deletes. Space plays."));
      return;
    }
    const g = { ...DEFAULT_GRADE, ...(c.grade || {}) };
    c.grade = g;

    append(inspector,
      el("div.spread", {},
        el("input", { value: c.name || c.kind, style: { width: "62%" },
          onchange: (e) => { c.name = e.target.value; drawTimeline(); host.save(); } }),
        el("span.tag", {}, c.kind)),
      el("div.design-grid2", {},
        el("label.design-num", {}, "start", el("input", { type: "number", step: 0.1, value: +c.start.toFixed(2),
          onchange: (e) => { c.start = Math.max(0, +e.target.value); drawTimeline(); host.save(); } })),
        el("label.design-num", {}, "length", el("input", { type: "number", step: 0.1, value: +c.dur.toFixed(2),
          onchange: (e) => { c.dur = Math.max(0.1, +e.target.value); drawTimeline(); host.save(); } })),
        c.kind === "video" || c.kind === "audio"
          ? el("label.design-num", {}, "in", el("input", { type: "number", step: 0.1, value: +(c.in || 0).toFixed(2),
              onchange: (e) => { c.in = Math.max(0, +e.target.value); seekTo(playhead); host.save(); } }))
          : el("span"),
        el("label.design-num", {}, "opacity", el("input", { type: "number", step: 0.05, min: 0, max: 1,
          value: c.opacity ?? 1,
          onchange: (e) => { c.opacity = clamp(+e.target.value, 0, 1); renderAt(playhead); host.save(); } }))),
      el("div.design-grid2", {},
        el("label.design-num", {}, "fade in", el("input", { type: "number", step: 0.1, min: 0, value: c.fadeIn || 0,
          onchange: (e) => { c.fadeIn = Math.max(0, +e.target.value); drawTimeline(); renderAt(playhead); host.save(); } })),
        el("label.design-num", {}, "fade out", el("input", { type: "number", step: 0.1, min: 0, value: c.fadeOut || 0,
          onchange: (e) => { c.fadeOut = Math.max(0, +e.target.value); drawTimeline(); renderAt(playhead); host.save(); } }))),
      c.kind === "video" ? el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
        el("input", { type: "checkbox", checked: !!c.audioOn, style: { width: "auto" },
          onchange: (e) => { c.audioOn = e.target.checked; const m = media.get(c.id); if (m) m.muted = !c.audioOn; host.save(); } }),
        "keep this clip's audio") : null);

    if (c.kind === "title") {
      append(inspector,
        el("label", {}, "Text", el("textarea", { value: c.text || "",
          oninput: (e) => { c.text = e.target.value; renderAt(playhead); host.save(); } })),
        el("div.row.tight", {},
          el("label.design-num", {}, "colour", el("input", { type: "color", value: c.color || "#ffffff",
            oninput: (e) => { c.color = e.target.value; renderAt(playhead); host.save(); } })),
          el("label.design-num", {}, "background", el("input", { type: "color", value: c.bg || "#000000",
            oninput: (e) => { c.bg = e.target.value; renderAt(playhead); host.save(); } })),
          el("button.ghost", { onclick: () => { c.bg = "none"; renderAt(playhead); host.save(); renderInspector(); } }, "no bg")),
        knob("size", { min: 16, max: 240, step: 1, value: c.size || 64,
          format: (v) => v.toFixed(0), oninput: (v) => { c.size = v; renderAt(playhead); host.save(); } }),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
          el("input", { type: "checkbox", checked: !!c.compiled, style: { width: "auto" },
            onchange: (e) => { c.compiled = e.target.checked; renderAt(playhead); renderInspector(); host.save(); } }),
          "compile the type to a distance field"),
        el("p.fine", {}, c.compiled
          ? "The glyphs are a field in the shader now: this title is in the frame's GLSL, it is sharp at any " +
            "export size, and an effect after it reads a shape rather than pixels. The two rasterisers do not " +
            "agree to the pixel, so a title already placed may shift a little."
          : "Drawn by the text engine. Tick the box to compile it instead."));
    }

    append(inspector,
      el("h4", { style: { marginTop: ".5rem" } }, "Grade"),
      el("p.fine", {}, "The CSS filter functions, compiled to nodes — ◇ keyframes one at the playhead."),
      ...[["brightness", 0.2, 2, 0.01], ["contrast", 0.2, 2.5, 0.01],
          ["saturate", 0, 2.5, 0.01], ["hue", -180, 180, 1], ["blur", 0, 20, 0.5]]
        .map(([key, min, max, step]) => keyed(c, `grade.${key}`, key,
          { min, max, step, format: (v) => (key === "hue" ? `${v.toFixed(0)}°` : v.toFixed(2)) },
          () => g[key], (v) => { g[key] = v; })),
      effectPanel(c),
      speedPanel(c),
      transitionPanel(c),
      keyPanel(c),
      lutInput,
      el("div.row.tight", { style: { marginTop: ".4rem" } },
        el("button.ghost", { onclick: () => { c.grade = { ...DEFAULT_GRADE }; renderInspector(); renderAt(playhead); host.save(); } }, "Reset"),
        el("button.ghost", {
          onclick: () => {
            for (const { clip } of allClips()) if (clip.kind !== "audio") clip.grade = { ...c.grade };
            toast("Grade copied to every clip — this is what unifies them");
            renderAt(playhead); host.save();
          },
        }, "Apply to all"),
        el("button.ghost.danger", { onclick: removeClip }, "Delete")));
  }

  // ---------------------------------------------------------------- import

  const fileInput = el("input", {
    type: "file", accept: "video/*,image/*,audio/*", multiple: true, hidden: true,
    onchange: async (e) => {
      for (const file of [...e.target.files]) {
        try {
          const isVideo = file.type.startsWith("video");
          const isAudio = file.type.startsWith("audio");
          const meta = (isVideo || isAudio) ? await probe(file, isVideo) : {};
          toast(`Importing ${file.name}…`);
          const asset = await host.upload(file, meta);
          const kind = isVideo ? "video" : isAudio ? "audio" : "image";
          const track = doc.tracks.find((t) => t.kind === (kind === "audio" ? "audio" : "video"))
            || doc.tracks[0];
          const srcDur = meta.duration || (kind === "image" ? 4 : 5);
          const start = track.clips.length
            ? Math.max(...track.clips.map(clipEnd)) : 0;
          const clip = { id: nid(), assetId: asset.id, kind, name: file.name.slice(0, 22),
            start, in: 0, dur: Math.min(srcDur, kind === "image" ? 4 : srcDur),
            srcDur, opacity: 1, fadeIn: 0, fadeOut: 0, audioOn: isVideo,
            grade: { ...DEFAULT_GRADE } };
          track.clips.push(clip);
          await ensureMedia(clip);
          selected = clip;
        } catch (err) { toast(`${file.name}: ${err.message}`); }
      }
      drawTimeline(); renderInspector(); seekTo(playhead);
      host.save(thumbnail());
      e.target.value = "";
    },
  });

  function probe(file, isVideo) {
    return new Promise((res) => {
      const m = document.createElement(isVideo ? "video" : "audio");
      m.preload = "metadata";
      m.onloadedmetadata = () => {
        res({ duration: m.duration, width: m.videoWidth, height: m.videoHeight });
        URL.revokeObjectURL(m.src);
      };
      m.onerror = () => res({});
      m.src = URL.createObjectURL(file);
    });
  }

  function addTitle() {
    const track = doc.tracks.find((t) => t.kind === "video");
    const clip = { id: nid(), kind: "title", name: "Title", text: "Title",
      start: playhead, in: 0, dur: 3, srcDur: 3, opacity: 1, fadeIn: 0.3, fadeOut: 0.3,
      color: "#ffffff", bg: "#000000", size: 72, grade: { ...DEFAULT_GRADE } };
    track.clips.push(clip);
    selected = clip;
    drawTimeline(); renderInspector(); host.save();
  }

  function addTrack(kind) {
    const n = doc.tracks.filter((t) => t.kind === kind).length + 1;
    doc.tracks.push({ id: nid(), kind, name: `${kind === "video" ? "V" : "A"}${n}`,
      mute: false, clips: [] });
    drawTimeline(); host.save();
  }

  function thumbnail() {
    try {
      const t = document.createElement("canvas");
      t.width = 240; t.height = Math.round((240 * ph) / pw);
      t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
      return t.toDataURL("image/jpeg", 0.7);
    } catch { return ""; }
  }

  // ---------------------------------------------------------------- export

  const seekExact = (v, t) => new Promise((res) => {
    let done = false;
    const finish = () => { if (!done) { done = true; v.onseeked = null; res(); } };
    v.onseeked = finish;
    // A seek to a time the browser considers current fires nothing at all.
    if (Math.abs(v.currentTime - t) < 0.001) return finish();
    v.currentTime = t;
    setTimeout(finish, 900);
  });

  /** Mix every audio-bearing clip offline into one buffer. */
  async function mixAudio(dur) {
    const SR = 48000;
    const OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const ctx = new OC(2, Math.ceil(dur * SR), SR);
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    let any = false;
    for (const { clip, track } of allClips()) {
      if (track.mute) continue;
      const wantsAudio = clip.kind === "audio" || (clip.kind === "video" && clip.audioOn);
      if (!wantsAudio) continue;
      const asset = host.assets.find((a) => a.id === clip.assetId);
      if (!asset) continue;
      try {
        const bytes = await (await fetch(asset.url)).arrayBuffer();
        const buf = await ac.decodeAudioData(bytes);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        const gain = ctx.createGain();
        const g0 = clip.gain ?? 1;
        gain.gain.setValueAtTime(clip.fadeIn > 0 ? 0.0001 : g0, clip.start);
        if (clip.fadeIn > 0) gain.gain.linearRampToValueAtTime(g0, clip.start + clip.fadeIn);
        if (clip.fadeOut > 0) {
          gain.gain.setValueAtTime(g0, Math.max(clip.start, clipEnd(clip) - clip.fadeOut));
          gain.gain.linearRampToValueAtTime(0.0001, clipEnd(clip));
        }
        src.connect(gain).connect(ctx.destination);
        src.start(clip.start, clip.in || 0, clip.dur);
        any = true;
      } catch { /* this source has no decodable audio; carry on */ }
    }
    ac.close();
    if (!any) return null;
    return ctx.startRendering();
  }

  async function exportVideo() {
    if (!allClips().length) { toast("Nothing on the timeline"); return; }
    if (!("VideoEncoder" in window)) return exportRealtime();

    stop();
    const fps = doc.fps || 30;
    const dur = duration();
    const frames = Math.ceil(dur * fps);
    const status = el("p.dim", {}, "Preparing…");
    const bar = el("div.bar", {}, el("i", { style: { width: "0%" } }));
    let cancelled = false;
    modal(el("h2", {}, "Exporting MP4"),
      el("p.fine", {}, `${W}×${H}, ${fps} fps, ${dur.toFixed(1)}s — ${frames} frames. ` +
        `Every frame is composited and encoded in turn rather than recorded as ` +
        `it plays, so it cannot drop a frame and backgrounding the tab is safe. ` +
        `Stills and titles export quickly; video sources have to be seeked ` +
        `frame by frame, which is slower than real time.`),
      status, bar,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button", { onclick: () => { cancelled = true; closeModal(); } }, "Cancel")));

    try {
      const out = document.createElement("canvas");
      out.width = W; out.height = H;
      const og = out.getContext("2d");

      const vsamples = [];
      let vdesc = null;
      const encoder = new VideoEncoder({
        output: (chunk, meta) => {
          if (meta?.decoderConfig?.description && !vdesc) {
            vdesc = new Uint8Array(meta.decoderConfig.description);
          }
          const data = new Uint8Array(chunk.byteLength);
          chunk.copyTo(data);
          vsamples.push({ data, timestamp: chunk.timestamp,
                          duration: chunk.duration || 1e6 / fps, type: chunk.type });
        },
        error: (e) => { throw e; },
      });
      // Level is chosen from the frame size; 4d0028 covers 1080p comfortably.
      const codec = (W * H > 1280 * 720) ? "avc1.4d0028" : "avc1.42001f";
      encoder.configure({ codec, width: W, height: H, framerate: fps,
        bitrate: Math.round(W * H * fps * 0.12), avc: { format: "avc" } });

      for (let f = 0; f < frames; f++) {
        if (cancelled) { encoder.close(); return; }
        const t = f / fps;
        // Seek only the sources actually on screen at this instant.
        for (const { clip } of allClips()) {
          if (clip.kind !== "video") continue;
          if (t < clip.start || t >= clipEnd(clip)) continue;
          const m = media.get(clip.id);
          if (m) { m.pause(); await seekExact(m, sourceTimeAt(clip, t - clip.start)); }
        }
        renderAt(t, og, { w: W, h: H });
        const frame = new VideoFrame(out, { timestamp: Math.round(t * 1e6),
                                            duration: Math.round(1e6 / fps) });
        encoder.encode(frame, { keyFrame: f % (fps * 2) === 0 });
        frame.close();
        if (encoder.encodeQueueSize > 8) {
          await new Promise((r) => setTimeout(r, 8));
        }
        if (f % 3 === 0) {
          bar.firstChild.style.width = `${((f / frames) * 90).toFixed(1)}%`;
          status.textContent = `Frame ${f + 1} of ${frames}`;
          await new Promise((r) => setTimeout(r, 0));
        }
      }
      await encoder.flush();
      encoder.close();

      status.textContent = "Mixing audio…";
      bar.firstChild.style.width = "92%";
      let asamples = [], adesc = null;
      const mixed = await mixAudio(dur);
      if (mixed && "AudioEncoder" in window) {
        const aenc = new AudioEncoder({
          output: (chunk, meta) => {
            if (meta?.decoderConfig?.description && !adesc) {
              adesc = new Uint8Array(meta.decoderConfig.description);
            }
            const data = new Uint8Array(chunk.byteLength);
            chunk.copyTo(data);
            asamples.push({ data, timestamp: chunk.timestamp, duration: chunk.duration || 0, type: chunk.type });
          },
          error: () => {},
        });
        aenc.configure({ codec: "mp4a.40.2", sampleRate: mixed.sampleRate,
                         numberOfChannels: 2, bitrate: 160000 });
        const L = mixed.getChannelData(0);
        const R = mixed.numberOfChannels > 1 ? mixed.getChannelData(1) : L;
        const CH = 1024;
        for (let off = 0; off + CH <= L.length; off += CH) {
          const inter = new Float32Array(CH * 2);
          inter.set(L.subarray(off, off + CH), 0);
          inter.set(R.subarray(off, off + CH), CH);
          const ad = new AudioData({ format: "f32-planar", sampleRate: mixed.sampleRate,
            numberOfFrames: CH, numberOfChannels: 2,
            timestamp: Math.round((off / mixed.sampleRate) * 1e6), data: inter });
          aenc.encode(ad);
          ad.close();
        }
        await aenc.flush();
        aenc.close();
      }

      status.textContent = "Writing the file…";
      bar.firstChild.style.width = "98%";
      const tracks = [{ kind: "video", samples: vsamples, description: vdesc,
                        width: W, height: H, timescale: 1_000_000 }];
      if (asamples.length && adesc) {
        tracks.push({ kind: "audio", samples: asamples, description: adesc,
                      channels: 2, timescale: mixed.sampleRate });
      }
      const blob = muxMp4(tracks);
      closeModal();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${host.doc.name || "cut"}.mp4`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`Exported ${(blob.size / 1e6).toFixed(1)} MB` +
            (asamples.length ? " with audio" : " (no audio track)"));
    } catch (err) {
      closeModal();
      toast(`Export failed: ${err.message}. Falling back to a screen recording.`);
      exportRealtime();
    }
    await seekTo(playhead);
  }

  /** The old path, kept for browsers with no WebCodecs. */
  async function exportRealtime() {
    if (!window.MediaRecorder) { toast("This browser cannot export"); return; }
    const dur = duration();
    const stream = canvas.captureStream(doc.fps || 30);
    const mime = ["video/webm;codecs=vp9", "video/webm"]
      .find((m) => MediaRecorder.isTypeSupported(m)) || "video/webm";
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8e6 });
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const done = new Promise((r) => { rec.onstop = r; });
    await seekTo(0);
    rec.start();
    play();
    await new Promise((r) => {
      const iv = setInterval(() => { if (!playing || playhead >= dur) { clearInterval(iv); r(); } }, 120);
    });
    rec.stop();
    await done;
    stop();
    const blob = new Blob(chunks, { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${host.doc.name || "cut"}.webm`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---------------------------------------------------------------- layout

  const playBtn = el("button.primary", { onclick: () => (playing ? stop() : play()) }, "Play");

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        playBtn,
        el("button", { onclick: () => seekTo(0) }, "⏮"),
        el("button", { onclick: () => fileInput.click() }, "Import"),
        el("button", { onclick: addTitle }, "+ Title"),
        el("button", { onclick: splitAtPlayhead }, "Split (S)"),
        el("button.ghost", { onclick: () => addTrack("video") }, "+ V track"),
        el("button.ghost", { onclick: () => addTrack("audio") }, "+ A track"),
        el("button.primary", { onclick: exportVideo }, "Export MP4"),
        el("button.ghost", { onclick: (e) => {
          scopesOn = !scopesOn;
          scopePanel.style.display = scopesOn ? "" : "none";
          e.target.classList.toggle("on", scopesOn);
          scopeDue = 0; updateScopes();
        } }, "Scopes"),
        el("button.ghost", { title: "the frame at the playhead, as one chain of shaders",
          onclick: frameGlsl }, "GLSL"),
        fileInput,
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "zoom",
          el("input", { type: "range", min: 10, max: 180, step: 2, value: pxPerSec,
            oninput: (e) => { pxPerSec = +e.target.value; drawTimeline(); } })),
        aiButton("Shot list…", {
          task: "brief",
          describe: "Turns an idea into a shot list you can shoot against. It " +
            "writes the plan; the cutting is yours.",
          placeholder: "e.g. 10-second spot, one product, must survive muted playback",
          onResult: (res) => modal(el("h2", {}, "Shot list"),
            el("p.dim", { style: { whiteSpace: "pre-wrap" } }, res.text),
            el("div.row", { style: { justifyContent: "flex-end" } },
              el("button.primary", { onclick: closeModal }, "Close"))),
        }))),

    el("div.lab-split", { style: { gridTemplateColumns: "minmax(0,1fr) 290px" } },
      el("div.stack", {}, canvas, el("div.card.tight", { style: { overflow: "auto" } }, timeline)),
      el("div.stack", {}, el("div.card.tight", {}, el("h4", {}, "Clip"), inspector), scopePanel)));

  root._cleanup = () => { stop(); document.removeEventListener("keydown", onKey); };

  for (const { clip } of allClips()) await ensureMedia(clip);
  renderInspector();
  await seekTo(0);
  drawTimeline();
  setTimeout(drawTimeline, 60);
  return root;
}
