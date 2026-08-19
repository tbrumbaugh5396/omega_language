// The music editor: patterns, an arrangement timeline, a mixer and
// automation, over synths built from the same primitives the ear drills use.
//
// Three views of one document:
//   Arrange  clips on a timeline, plus automation lanes
//   Edit     the piano roll / drum grid for one pattern
//   Mix      channel strips, sends, master
//
// Playback renders the whole arrangement offline into one buffer and loops
// it, rather than running a live scheduler. For a sketching tool that trade is
// worth it: edits re-render in a fraction of a second, the result is
// sample-accurate, automation is real AudioParam automation rather than a
// polling approximation, and export is the same code path as play — so what
// you hear is exactly what lands in the file.

import { el, clear, append, toast, modal, closeModal, knob, confirmDialog, clamp } from "./ui.js";
import * as A from "./engine-audio.js";
import { aiButton } from "./ai.js";

const INSTRUMENTS = [
  ["drums", "Drums"], ["bass", "Bass"], ["synth", "Synth"],
  ["pluck", "Pluck"], ["fm", "FM"], ["sampler", "Sampler"],
];

const DRUMS = [
  [36, "Kick"], [38, "Snare"], [42, "Hat"], [46, "Open hat"], [45, "Tom"],
];

const ROLL_LOW = 36, ROLL_HIGH = 84;
const CELL_W = 22, CELL_H = 13;

// Arrange geometry
const GUTTER = 132, ROW_H = 46, LANE_H = 34, RULER_H = 22;

const AUTO_PARAMS = [
  ["volume", "Volume", (v) => v * 1.2],
  ["cutoff", "Filter", (v) => 80 * Math.pow(200, v)],
];

let uid = Date.now() % 1e5;
const nid = () => ++uid;

export async function musicEditor(host) {
  const doc = host.data;
  migrate(doc);

  let view = "arrange";
  let activeTrack = 0;
  let activePattern = doc.patterns[0]?.id ?? null;
  let selectedClip = null;
  let playing = false, stopFn = null, rendered = null, playStartedAt = 0, playFromSec = 0;
  let trackPeaks = {};

  const stepsPerBar = 16;
  const secPerStep = () => 60 / doc.bpm / 4;
  const secPerBar = () => secPerStep() * stepsPerBar;
  const totalSteps = () => doc.bars * stepsPerBar;
  const totalSecs = () => doc.bars * secPerBar() + 2;   // tail for reverb/decay
  const patternById = (id) => doc.patterns.find((p) => p.id === id);

  // ---------------------------------------------------------------- model

  function migrate(d) {
    d.bpm ||= 120;
    d.swing ||= 0;
    d.tracks ||= [];
    if (!d.patterns) {
      // v1 documents kept one loop of notes per track. Wrap each into a
      // pattern and place a single clip, so nothing a user made is lost.
      d.patterns = [];
      const bars = d.bars || 4;
      for (const t of d.tracks) {
        const pat = { id: nid(), name: t.name || "Pattern", bars,
                      notes: (t.notes || []).map((n) => ({ ...n })) };
        d.patterns.push(pat);
        t.clips = [{ id: nid(), patternId: pat.id, startBar: 0, bars }];
        delete t.notes;
      }
      d.bars = Math.max(bars, 8);
    }
    for (const t of d.tracks) {
      t.clips ||= [];
      t.automation ||= {};
      t.solo = !!t.solo;
      t.cutoff ??= 1;                      // normalised: 1 is fully open
      t.fx ||= defaultFx();
    }
    if (!d.patterns.length) {
      d.patterns.push({ id: nid(), name: "Pattern 1", bars: 4, notes: [] });
    }
  }

  function defaultFx() {
    return { eqFreq: 800, eqGain: 0, eqQ: 1, drive: 0,
             delayMs: 0, delayFb: 0.25, reverb: 0, reverbDecay: 1.6 };
  }

  // ---------------------------------------------------------------- synthesis

  const swingOffset = (step) => (step % 2 === 1 ? (doc.swing || 0) * secPerStep() * 0.5 : 0);

  function voice(track, note, dur) {
    const hz = A.noteHz(note.pitch);
    switch (track.instrument) {
      case "drums": {
        const p = note.pitch;
        if (p === 36) return A.synth.hit(0.4, { attackMs: 0.6, decayMs: 90, hz: 110, noise: 0.05 });
        if (p === 38) return A.synth.hit(0.3, { attackMs: 0.5, decayMs: 60, hz: 190, noise: 0.75 });
        if (p === 42) return A.synth.hit(0.09, { attackMs: 0.2, decayMs: 14, hz: 8000, noise: 1 });
        if (p === 46) return A.synth.hit(0.3, { attackMs: 0.3, decayMs: 70, hz: 7000, noise: 1 });
        return A.synth.hit(0.35, { attackMs: 0.7, decayMs: 110, hz: 160, noise: 0.2 });
      }
      case "pluck":
        return A.synth.pluck(dur + 0.35, hz, { damp: 0.9965, gain: 0.5 });
      case "bass": {
        const n = Math.ceil((dur + 0.12) * A.SR);
        const buf = new Float32Array(n);
        for (let i = 0; i < n; i++) {
          const t = i / A.SR;
          const env = Math.min(1, t * 220) * Math.exp(-t * 2.2);
          let v = 0;
          for (let p = 1; p <= 6; p++) v += Math.sin(2 * Math.PI * hz * p * t) / p;
          buf[i] = v * env * 0.24;
        }
        return A.fade(buf, A.SR, 6);
      }
      case "fm": {
        const n = Math.ceil((dur + 0.2) * A.SR);
        const buf = new Float32Array(n);
        for (let i = 0; i < n; i++) {
          const t = i / A.SR;
          const env = Math.min(1, t * 120) * Math.exp(-t * 3.2);
          const mod = Math.sin(2 * Math.PI * hz * 2 * t) * 4 * Math.exp(-t * 4);
          buf[i] = Math.sin(2 * Math.PI * hz * t + mod) * env * 0.28;
        }
        return A.fade(buf, A.SR, 6);
      }
      case "sampler": {
        const s = track.sample;
        if (!s) return new Float32Array(0);
        const rate = Math.pow(2, (note.pitch - (track.root ?? 60)) / 12);
        const n = Math.min(Math.ceil((dur + 0.3) * A.SR), Math.floor(s.length / rate));
        const buf = new Float32Array(Math.max(0, n));
        for (let i = 0; i < n; i++) buf[i] = s[Math.floor(i * rate)] || 0;
        return A.fade(buf, A.SR, 8);
      }
      default: {
        const n = Math.ceil((dur + 0.3) * A.SR);
        const buf = new Float32Array(n);
        for (let i = 0; i < n; i++) {
          const t = i / A.SR;
          const env = Math.min(1, t * 80) * Math.min(1, Math.max(0, (dur + 0.25 - t) * 6));
          let v = 0;
          for (const d of [-0.004, 0, 0.005]) {
            const f = hz * (1 + d);
            v += Math.sin(2 * Math.PI * f * t) + Math.sin(4 * Math.PI * f * t) * 0.35;
          }
          buf[i] = v * env * 0.09;
        }
        return A.fade(buf, A.SR, 8);
      }
    }
  }

  /** Lay every clip on a track down into one buffer. */
  function synthTrack(track) {
    const out = new Float32Array(Math.ceil(totalSecs() * A.SR));
    const sd = secPerStep();
    for (const clip of track.clips) {
      const pat = patternById(clip.patternId);
      if (!pat || !pat.notes.length) continue;
      // A clip longer than its pattern repeats it — that is what makes a
      // four-bar loop into a sixteen-bar section without copying notes.
      const reps = Math.max(1, Math.round(clip.bars / pat.bars));
      for (let r = 0; r < reps; r++) {
        const base = (clip.startBar + r * pat.bars) * stepsPerBar;
        for (const n of pat.notes) {
          const step = base + n.step;
          if (step >= totalSteps()) continue;
          const at = Math.floor((step * sd + swingOffset(n.step)) * A.SR);
          const dur = Math.max(0.05, (n.len || 1) * sd);
          const part = voice(track, n, dur);
          for (let i = 0; i < part.length && at + i < out.length; i++) {
            if (at + i >= 0) out[at + i] += part[i];
          }
        }
      }
    }
    return out;
  }

  function applyAuto(param, points, fallback, map) {
    if (!points || points.length < 1) { param.value = map ? map(fallback) : fallback; return; }
    const pts = [...points].sort((a, b) => a.bar - b.bar);
    const spb = secPerBar();
    param.setValueAtTime(map ? map(pts[0].value) : pts[0].value, 0);
    for (const p of pts) {
      param.linearRampToValueAtTime(map ? map(p.value) : p.value,
                                    Math.max(0.001, p.bar * spb));
    }
  }

  async function renderMix() {
    const soloed = doc.tracks.some((t) => t.solo);
    const live = doc.tracks.filter((t) =>
      (soloed ? t.solo : !t.mute) && t.clips.length);
    if (!live.length) return null;

    const length = Math.ceil(totalSecs() * A.SR);
    const OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const ctx = new OC(2, length, A.SR);

    const master = ctx.createGain();
    master.gain.value = 0.85;
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -3;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = 0.002;
    limiter.release.value = 0.12;
    master.connect(limiter).connect(ctx.destination);

    trackPeaks = {};
    for (const track of live) {
      const samples = synthTrack(track);
      let peak = 0;
      for (let i = 0; i < samples.length; i++) {
        const v = samples[i] < 0 ? -samples[i] : samples[i];
        if (v > peak) peak = v;
      }
      trackPeaks[track.id] = peak;

      const buf = ctx.createBuffer(1, Math.max(1, samples.length), A.SR);
      buf.copyToChannel(samples.subarray(0, buf.length), 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;

      let node = src;
      const fx = track.fx || {};
      if (fx.eqGain) {
        const f = ctx.createBiquadFilter();
        f.type = "peaking";
        f.frequency.value = fx.eqFreq || 800;
        f.Q.value = fx.eqQ || 1;
        f.gain.value = fx.eqGain;
        node = node.connect(f);
      }
      // The per-track filter is always in the chain so automation has
      // something to move; wide open it is inaudible.
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.Q.value = 0.9;
      applyAuto(lp.frequency, track.automation?.cutoff, track.cutoff ?? 1,
                AUTO_PARAMS[1][2]);
      node = node.connect(lp);

      if (fx.drive) {
        const ws = ctx.createWaveShaper();
        ws.curve = A.shaperCurve("asym", Math.min(0.95, fx.drive));
        ws.oversample = "2x";
        node = node.connect(ws);
      }
      const pan = ctx.createStereoPanner();
      pan.pan.value = clamp(track.pan || 0, -1, 1);
      const gain = ctx.createGain();
      applyAuto(gain.gain, track.automation?.volume, track.vol ?? 0.8,
                AUTO_PARAMS[0][2]);
      node = node.connect(pan).connect(gain);

      if (fx.delayMs > 1) {
        const d = ctx.createDelay(2);
        d.delayTime.value = fx.delayMs / 1000;
        const fb = ctx.createGain();
        fb.gain.value = Math.min(0.85, fx.delayFb ?? 0.25);
        const wet = ctx.createGain();
        wet.gain.value = 0.5;
        node.connect(d);
        d.connect(fb).connect(d);
        d.connect(wet).connect(master);
      }
      if (fx.reverb > 0.01) {
        const conv = ctx.createConvolver();
        conv.buffer = A.makeIR(ctx, { seconds: fx.reverbDecay || 1.6,
                                      preDelayMs: 18, decay: 3, seed: 41 });
        const wet = ctx.createGain();
        wet.gain.value = fx.reverb;
        node.connect(conv).connect(wet).connect(master);
      }
      node.connect(master);
      src.start(0);
    }
    return ctx.startRendering();
  }

  let renderTimer = null;
  function scheduleRender({ restart = false } = {}) {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(async () => {
      rendered = await renderMix();
      renderViews();
      if (restart && playing) startPlayback(playFromSec);
    }, 240);
  }

  function startPlayback(fromSec = 0) {
    stopFn?.();
    if (!rendered) return;
    playFromSec = fromSec;
    playStartedAt = performance.now();
    stopFn = A.play(rendered, { loop: true, offset: fromSec });
    playing = true;
    playBtn.textContent = "Stop";
    requestAnimationFrame(tick);
  }
  function stopPlayback() {
    stopFn?.();
    A.stopAll();
    playing = false;
    playBtn.textContent = "Play";
    drawArrange();
  }
  function tick() {
    if (!playing) return;
    if (view === "arrange") drawArrange(); else if (view === "edit") drawGrid();
    updateScopes();
    requestAnimationFrame(tick);
  }
  const playheadSec = () => {
    if (!playing) return playFromSec;
    const loopLen = rendered ? rendered.duration : totalSecs();
    return (playFromSec + (performance.now() - playStartedAt) / 1000) % loopLen;
  };

  // ---------------------------------------------------------------- arrange

  const arrange = el("canvas", { style: { display: "block", cursor: "default" } });
  const ag = arrange.getContext("2d");
  let barW = 46;

  const laneOpen = new Set();
  const rowTop = (i) => {
    let y = RULER_H;
    for (let k = 0; k < i; k++) {
      y += ROW_H + (laneOpen.has(doc.tracks[k].id) ? LANE_H : 0);
    }
    return y;
  };
  const arrangeHeight = () => rowTop(doc.tracks.length) + 8;

  function drawArrange() {
    const w = Math.max(600, GUTTER + doc.bars * barW + 40);
    const h = arrangeHeight();
    if (arrange.width !== w || arrange.height !== h) { arrange.width = w; arrange.height = h; }
    ag.fillStyle = "#0b0e16";
    ag.fillRect(0, 0, w, h);

    // ruler
    ag.fillStyle = "#141a2a";
    ag.fillRect(GUTTER, 0, doc.bars * barW, RULER_H);
    ag.font = "9px ui-monospace, monospace";
    for (let b = 0; b <= doc.bars; b++) {
      const x = GUTTER + b * barW;
      ag.fillStyle = b % 4 === 0 ? "#3a4260" : "#232a40";
      ag.fillRect(x, 0, 1, h);
      if (b % 4 === 0 && b < doc.bars) {
        ag.fillStyle = "#a8b0c8";
        ag.fillText(String(b + 1), x + 3, 14);
      }
    }

    doc.tracks.forEach((t, i) => {
      const y = rowTop(i);
      const isActive = i === activeTrack;
      ag.fillStyle = isActive ? "#161d30" : "#10141f";
      ag.fillRect(0, y, w, ROW_H - 2);

      ag.fillStyle = isActive ? "#e8ebf5" : "#a8b0c8";
      ag.font = "12px system-ui";
      ag.fillText(t.name.slice(0, 14), 8, y + 18);
      ag.font = "9px system-ui";
      ag.fillStyle = "#6e7794";
      ag.fillText(t.instrument, 8, y + 32);

      // mute / solo pips
      ag.fillStyle = t.mute ? "#f2708a" : "#232a40";
      ag.fillRect(96, y + 8, 14, 12);
      ag.fillStyle = t.solo ? "#f0a35e" : "#232a40";
      ag.fillRect(112, y + 8, 14, 12);
      ag.fillStyle = "#0b0e16";
      ag.font = "8px system-ui";
      ag.fillText("M", 99, y + 17);
      ag.fillText("S", 116, y + 17);

      // a peak bar, computed at render time — honest about how loud the track is
      const pk = trackPeaks[t.id];
      if (pk !== undefined) {
        ag.fillStyle = pk > 0.99 ? "#f2708a" : "#5fd39a";
        ag.fillRect(96, y + 26, Math.min(30, pk * 30), 4);
      }

      for (const clip of t.clips) {
        const pat = patternById(clip.patternId);
        const x = GUTTER + clip.startBar * barW;
        const cw = Math.max(8, clip.bars * barW - 2);
        const selected = selectedClip && selectedClip.id === clip.id;
        ag.fillStyle = selected ? "#3b4a7a" : "#2c3a5e";
        ag.fillRect(x + 1, y + 4, cw, ROW_H - 12);
        ag.strokeStyle = selected ? "#7c9cff" : "#44548a";
        ag.lineWidth = selected ? 2 : 1;
        ag.strokeRect(x + 1.5, y + 4.5, cw - 1, ROW_H - 13);
        ag.fillStyle = "#e8ebf5";
        ag.font = "10px system-ui";
        ag.fillText((pat?.name || "?").slice(0, Math.max(1, Math.floor(cw / 6))), x + 6, y + 18);
        // repeat marks where the pattern loops inside the clip
        if (pat && clip.bars > pat.bars) {
          ag.fillStyle = "rgba(232,235,245,.25)";
          for (let r = pat.bars; r < clip.bars; r += pat.bars) {
            ag.fillRect(x + r * barW, y + 4, 1, ROW_H - 12);
          }
        }
      }

      if (laneOpen.has(t.id)) {
        const ly = y + ROW_H - 2;
        ag.fillStyle = "#0d1119";
        ag.fillRect(GUTTER, ly, doc.bars * barW, LANE_H);
        ag.fillStyle = "#6e7794";
        ag.font = "9px system-ui";
        ag.fillText(laneParam.get(t.id) || "volume", 8, ly + 14);
        const key = laneParam.get(t.id) || "volume";
        const pts = (t.automation[key] || []);
        ag.strokeStyle = "#f0a35e";
        ag.lineWidth = 1.5;
        ag.beginPath();
        const py = (v) => ly + LANE_H - 4 - v * (LANE_H - 8);
        if (!pts.length) {
          const fallback = key === "volume" ? (t.vol ?? 0.8) : (t.cutoff ?? 1);
          ag.moveTo(GUTTER, py(fallback));
          ag.lineTo(GUTTER + doc.bars * barW, py(fallback));
        } else {
          const sorted = [...pts].sort((a, b) => a.bar - b.bar);
          sorted.forEach((p, k) => {
            const x = GUTTER + p.bar * barW;
            k ? ag.lineTo(x, py(p.value)) : ag.moveTo(x, py(p.value));
          });
        }
        ag.stroke();
        for (const p of (t.automation[key] || [])) {
          ag.fillStyle = "#f0a35e";
          ag.beginPath();
          ag.arc(GUTTER + p.bar * barW, py(p.value), 3.5, 0, Math.PI * 2);
          ag.fill();
        }
      }
    });

    // playhead
    const ph = playheadSec() / secPerBar();
    ag.fillStyle = "#6ee7c8";
    ag.fillRect(GUTTER + ph * barW, 0, 2, h);
  }

  const laneParam = new Map();
  let adrag = null;

  arrange.addEventListener("pointerdown", (e) => {
    const r = arrange.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * arrange.width;
    const y = ((e.clientY - r.top) / r.height) * arrange.height;

    if (y < RULER_H) {
      const bar = clamp((x - GUTTER) / barW, 0, doc.bars);
      playFromSec = bar * secPerBar();
      if (playing) startPlayback(playFromSec); else drawArrange();
      return;
    }

    for (let i = 0; i < doc.tracks.length; i++) {
      const t = doc.tracks[i];
      const top = rowTop(i);
      if (y >= top && y < top + ROW_H) {
        activeTrack = i;
        if (x < GUTTER) {
          if (x >= 96 && x < 110 && y >= top + 8 && y < top + 20) {
            t.mute = !t.mute; host.save(); scheduleRender({ restart: true }); return;
          }
          if (x >= 112 && x < 126 && y >= top + 8 && y < top + 20) {
            t.solo = !t.solo; host.save(); scheduleRender({ restart: true }); return;
          }
          renderViews();
          return;
        }
        const bar = (x - GUTTER) / barW;
        // The resize edge is tested first and with a tolerance that straddles
        // the boundary. A hot zone that only reaches inward means grabbing the
        // visible right edge lands in empty space and makes a new clip.
        const tolBars = 8 / barW;
        let clip = t.clips.find((c) => Math.abs(bar - (c.startBar + c.bars)) < tolBars);
        let mode = "resize";
        if (!clip) {
          clip = t.clips.find((c) => bar >= c.startBar && bar < c.startBar + c.bars);
          mode = "move";
        }
        if (clip) {
          selectedClip = clip;
          adrag = { mode, clip, track: t,
                    grabBar: bar, startBar: clip.startBar, startLen: clip.bars };
        } else if (activePattern) {
          // Empty space places the current pattern here, unless it would land
          // on top of a clip that is already there.
          const pat = patternById(activePattern);
          const start = Math.floor(bar);
          const overlaps = t.clips.some((c) =>
            start < c.startBar + c.bars && start + pat.bars > c.startBar);
          if (!overlaps) {
            const c = { id: nid(), patternId: pat.id, startBar: start, bars: pat.bars };
            t.clips.push(c);
            selectedClip = c;
            doc.bars = Math.max(doc.bars, start + pat.bars);
            host.save(); scheduleRender({ restart: true });
          }
        }
        drawArrange(); renderViews();
        return;
      }
      if (laneOpen.has(t.id)) {
        const ly = top + ROW_H - 2;
        if (y >= ly && y < ly + LANE_H) {
          const key = laneParam.get(t.id) || "volume";
          t.automation[key] ||= [];
          const bar = clamp((x - GUTTER) / barW, 0, doc.bars);
          const value = clamp((ly + LANE_H - 4 - y) / (LANE_H - 8), 0, 1);
          const pts = t.automation[key];
          const near = pts.find((p) => Math.abs(p.bar - bar) * barW < 7);
          if (e.altKey && near) {
            pts.splice(pts.indexOf(near), 1);
          } else if (near) {
            adrag = { mode: "auto", point: near, track: t, key };
          } else {
            const p = { bar, value };
            pts.push(p);
            adrag = { mode: "auto", point: p, track: t, key };
          }
          drawArrange();
          host.save(); scheduleRender({ restart: true });
          return;
        }
      }
    }
  });

  arrange.addEventListener("pointermove", (e) => {
    if (!adrag) return;
    const r = arrange.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * arrange.width;
    const y = ((e.clientY - r.top) / r.height) * arrange.height;
    const bar = (x - GUTTER) / barW;

    if (adrag.mode === "move") {
      adrag.clip.startBar = Math.max(0, Math.round(adrag.startBar + (bar - adrag.grabBar)));
    } else if (adrag.mode === "resize") {
      const pat = patternById(adrag.clip.patternId);
      const unit = pat ? pat.bars : 1;
      // Resize in whole pattern lengths: a clip is a number of repeats.
      const want = Math.max(unit, Math.round((bar - adrag.clip.startBar) / unit) * unit);
      adrag.clip.bars = want;
    } else if (adrag.mode === "auto") {
      const i = doc.tracks.indexOf(adrag.track);
      const ly = rowTop(i) + ROW_H - 2;
      adrag.point.bar = clamp(bar, 0, doc.bars);
      adrag.point.value = clamp((ly + LANE_H - 4 - y) / (LANE_H - 8), 0, 1);
    }
    drawArrange();
  });

  arrange.addEventListener("pointerup", () => {
    if (!adrag) return;
    adrag = null;
    host.save();
    scheduleRender({ restart: true });
  });

  arrange.addEventListener("dblclick", (e) => {
    const r = arrange.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * arrange.width;
    const y = ((e.clientY - r.top) / r.height) * arrange.height;
    for (let i = 0; i < doc.tracks.length; i++) {
      const top = rowTop(i);
      if (y >= top && y < top + ROW_H && x > GUTTER) {
        const bar = (x - GUTTER) / barW;
        const clip = doc.tracks[i].clips.find((c) => bar >= c.startBar && bar < c.startBar + c.bars);
        if (clip) { activePattern = clip.patternId; activeTrack = i; setView("edit"); }
        return;
      }
    }
  });

  function onKey(e) {
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (/input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === " ") {
      e.preventDefault();
      playing ? stopPlayback() : (async () => {
        if (!rendered) rendered = await renderMix();
        if (rendered) startPlayback(playFromSec);
      })();
      return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && selectedClip) {
      e.preventDefault();
      for (const t of doc.tracks) {
        const i = t.clips.indexOf(selectedClip);
        if (i >= 0) t.clips.splice(i, 1);
      }
      selectedClip = null;
      drawArrange(); host.save(); scheduleRender({ restart: true });
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "d" && selectedClip) {
      e.preventDefault();
      const t = doc.tracks.find((x) => x.clips.includes(selectedClip));
      if (t) {
        const c = { ...selectedClip, id: nid(), startBar: selectedClip.startBar + selectedClip.bars };
        t.clips.push(c);
        selectedClip = c;
        doc.bars = Math.max(doc.bars, c.startBar + c.bars);
        drawArrange(); host.save(); scheduleRender({ restart: true });
      }
    }
  }
  document.addEventListener("keydown", onKey);

  // ---------------------------------------------------------------- edit

  const grid = el("canvas", { style: { display: "block", cursor: "crosshair" } });
  const gg = grid.getContext("2d");
  let noteLen = 2;

  const rowsFor = (track) => track.instrument === "drums"
    ? DRUMS.map(([p, n]) => ({ pitch: p, label: n }))
    : Array.from({ length: ROLL_HIGH - ROLL_LOW + 1 }, (_, i) => {
        const pitch = ROLL_HIGH - i;
        const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
        return { pitch, label: `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}` };
      });

  function drawGrid() {
    const pat = patternById(activePattern);
    const track = doc.tracks[activeTrack];
    if (!pat || !track) return;
    const rows = rowsFor(track);
    const n = pat.bars * stepsPerBar;
    grid.width = n * CELL_W + 52;
    grid.height = rows.length * CELL_H + 2;
    gg.fillStyle = "#0b0e16";
    gg.fillRect(0, 0, grid.width, grid.height);

    rows.forEach((r, ri) => {
      const black = [1, 3, 6, 8, 10].includes(r.pitch % 12) && track.instrument !== "drums";
      gg.fillStyle = black ? "#0f1320" : "#141a2a";
      gg.fillRect(52, ri * CELL_H, n * CELL_W, CELL_H - 1);
      gg.fillStyle = "#6e7794";
      gg.font = "9px ui-monospace, monospace";
      if (track.instrument === "drums" || r.pitch % 12 === 0) gg.fillText(r.label, 4, ri * CELL_H + CELL_H - 4);
    });
    for (let s = 0; s <= n; s++) {
      gg.fillStyle = s % 16 === 0 ? "#3a4260" : s % 4 === 0 ? "#232a40" : "#191f30";
      gg.fillRect(52 + s * CELL_W, 0, 1, rows.length * CELL_H);
    }
    for (const note of pat.notes) {
      const ri = rows.findIndex((r) => r.pitch === note.pitch);
      if (ri < 0) continue;
      gg.fillStyle = "#7c9cff";
      gg.fillRect(52 + note.step * CELL_W + 1, ri * CELL_H + 1,
                  Math.max(CELL_W - 2, (note.len || 1) * CELL_W - 2), CELL_H - 3);
    }
    // playhead, but only while this pattern is the one sounding
    if (playing) {
      const stepNow = playheadSec() / secPerStep();
      const track = doc.tracks[activeTrack];
      for (const clip of track.clips) {
        if (clip.patternId !== pat.id) continue;
        const s0 = clip.startBar * stepsPerBar;
        if (stepNow >= s0 && stepNow < s0 + clip.bars * stepsPerBar) {
          const local = (stepNow - s0) % (pat.bars * stepsPerBar);
          gg.fillStyle = "#6ee7c8";
          gg.fillRect(52 + local * CELL_W, 0, 2, rows.length * CELL_H);
        }
      }
    }
  }

  grid.addEventListener("pointerdown", (e) => {
    const pat = patternById(activePattern);
    const track = doc.tracks[activeTrack];
    if (!pat || !track) return;
    const r = grid.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * grid.width - 52;
    const y = ((e.clientY - r.top) / r.height) * grid.height;
    if (x < 0) return;
    const step = Math.floor(x / CELL_W);
    const rows = rowsFor(track);
    const row = rows[Math.floor(y / CELL_H)];
    if (!row || step < 0 || step >= pat.bars * stepsPerBar) return;
    const hit = pat.notes.findIndex((nt) =>
      nt.pitch === row.pitch && step >= nt.step && step < nt.step + (nt.len || 1));
    if (hit >= 0) pat.notes.splice(hit, 1);
    else pat.notes.push({ step, pitch: row.pitch,
                          len: track.instrument === "drums" ? 1 : noteLen });
    drawGrid();
    host.save();
    scheduleRender({ restart: true });
  });

  // ---------------------------------------------------------------- mixer

  const mixer = el("div.mixer");
  function drawMixer() {
    clear(mixer);
    for (const t of doc.tracks) {
      const pk = trackPeaks[t.id] ?? 0;
      mixer.append(el("div.strip", {},
        el("input", { value: t.name, style: { fontSize: ".72rem", padding: ".2em" },
          onchange: (e) => { t.name = e.target.value; renderViews(); host.save(); } }),
        el("select", { style: { fontSize: ".7rem", padding: ".15em" },
          onchange: (e) => { t.instrument = e.target.value; renderViews(); host.save(); scheduleRender({ restart: true }); } },
          ...INSTRUMENTS.map(([v, l]) => el("option", { value: v, selected: v === t.instrument }, l))),
        el("div.meter", {}, el("i", { style: { height: `${Math.min(100, pk * 100)}%`,
          background: pk > 0.99 ? "var(--bad)" : "var(--good)" } })),
        el("input", { type: "range", min: 0, max: 1, step: 0.01, value: t.vol ?? 0.8,
          class: "fader", orient: "vertical",
          oninput: (e) => { t.vol = +e.target.value; },
          onchange: () => { host.save(); scheduleRender({ restart: true }); } }),
        el("label.design-num", {}, "pan",
          el("input", { type: "range", min: -1, max: 1, step: 0.05, value: t.pan ?? 0,
            oninput: (e) => { t.pan = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); } })),
        el("label.design-num", {}, "filter",
          el("input", { type: "range", min: 0, max: 1, step: 0.01, value: t.cutoff ?? 1,
            oninput: (e) => { t.cutoff = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); } })),
        el("div.row.tight", {},
          el("button.ghost", { class: t.mute ? "on" : "",
            onclick: () => { t.mute = !t.mute; renderViews(); host.save(); scheduleRender({ restart: true }); } }, "M"),
          el("button.ghost", { class: t.solo ? "on" : "",
            onclick: () => { t.solo = !t.solo; renderViews(); host.save(); scheduleRender({ restart: true }); } }, "S")),
        el("button.ghost", { style: { fontSize: ".7rem" }, onclick: () => fxDialog(t) }, "fx")));
    }
    mixer.append(el("div.strip", { style: { borderColor: "var(--accent)" } },
      el("b", { style: { fontSize: ".75rem" } }, "Master"),
      el("p.fine", {}, "−3 dB limiter"),
      el("p.fine", {}, `${doc.tracks.length} tracks`),
      el("p.fine", {}, `${doc.bars} bars`)));
  }

  function fxDialog(track) {
    track.fx ||= defaultFx();
    const f = track.fx;
    modal(el("h2", {}, `${track.name} — effects`),
      el("p.fine", {}, "The same primitives the ear drills are built on: one " +
        "biquad, one transfer curve, one delay line, one impulse response."),
      el("div.stack", {},
        knob("EQ frequency", { min: 40, max: 12000, step: 10, value: f.eqFreq || 800,
          format: (v) => `${v.toFixed(0)} Hz`, oninput: (v) => { f.eqFreq = v; } }),
        knob("EQ gain", { min: -18, max: 18, step: 0.5, value: f.eqGain || 0,
          format: (v) => `${v.toFixed(1)} dB`, oninput: (v) => { f.eqGain = v; } }),
        knob("Drive", { min: 0, max: 0.95, step: 0.01, value: f.drive || 0,
          format: (v) => v.toFixed(2), oninput: (v) => { f.drive = v; } }),
        knob("Delay", { min: 0, max: 600, step: 1, value: f.delayMs || 0,
          format: (v) => `${v.toFixed(0)} ms`, oninput: (v) => { f.delayMs = v; } }),
        knob("Delay feedback", { min: 0, max: 0.85, step: 0.01, value: f.delayFb ?? 0.25,
          format: (v) => v.toFixed(2), oninput: (v) => { f.delayFb = v; } }),
        knob("Reverb", { min: 0, max: 1, step: 0.01, value: f.reverb || 0,
          format: (v) => v.toFixed(2), oninput: (v) => { f.reverb = v; } }),
        knob("Reverb decay", { min: 0.2, max: 5, step: 0.1, value: f.reverbDecay || 1.6,
          format: (v) => `${v.toFixed(1)}s`, oninput: (v) => { f.reverbDecay = v; } })),
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", { onclick: () => { closeModal(); host.save(); scheduleRender({ restart: true }); } }, "Done")));
  }

  // ---------------------------------------------------------------- panels

  const patternList = el("div.stack");
  function drawPatterns() {
    clear(patternList);
    for (const p of doc.patterns) {
      patternList.append(el("div.card.tight", {
        style: { borderColor: p.id === activePattern ? "var(--accent)" : "" },
      },
        el("div.spread", {},
          el("button.ghost", { style: { padding: ".1em .3em" },
            onclick: () => { activePattern = p.id; renderViews(); } },
            el("b", {}, p.name)),
          el("div.row.tight", {},
            el("span.fine", {}, `${p.bars}b · ${p.notes.length}n`),
            el("button.ghost", { title: "duplicate",
              onclick: () => {
                doc.patterns.push({ id: nid(), name: `${p.name} copy`, bars: p.bars,
                                    notes: p.notes.map((n) => ({ ...n })) });
                activePattern = doc.patterns[doc.patterns.length - 1].id;
                renderViews(); host.save();
              } }, "⧉"),
            el("button.ghost.danger", {
              onclick: async () => {
                if (doc.tracks.some((t) => t.clips.some((c) => c.patternId === p.id))
                    && !(await confirmDialog(`"${p.name}" is used on the timeline. Delete it and its clips?`))) return;
                doc.patterns.splice(doc.patterns.indexOf(p), 1);
                for (const t of doc.tracks) t.clips = t.clips.filter((c) => c.patternId !== p.id);
                if (activePattern === p.id) activePattern = doc.patterns[0]?.id ?? null;
                renderViews(); host.save(); scheduleRender({ restart: true });
              } }, "×")))));
    }
  }

  const trackPanel = el("div.stack");
  function drawTrackPanel() {
    clear(trackPanel);
    doc.tracks.forEach((t, i) => {
      trackPanel.append(el("div.card.tight", {
        style: { borderColor: i === activeTrack ? "var(--accent)" : "" },
      },
        el("div.spread", {},
          el("button.ghost", { style: { padding: ".1em .3em" },
            onclick: () => { activeTrack = i; renderViews(); } }, t.name),
          el("div.row.tight", {},
            el("button.ghost", { class: laneOpen.has(t.id) ? "on" : "", title: "automation",
              onclick: () => {
                laneOpen.has(t.id) ? laneOpen.delete(t.id) : laneOpen.add(t.id);
                drawArrange();
              } }, "auto"),
            el("button.ghost.danger", {
              onclick: async () => {
                if (!(await confirmDialog(`Delete "${t.name}"?`))) return;
                doc.tracks.splice(i, 1);
                activeTrack = Math.max(0, activeTrack - 1);
                renderViews(); host.save(); scheduleRender({ restart: true });
              } }, "×"))),
        laneOpen.has(t.id) ? el("div.row.tight", { style: { marginTop: ".3rem" } },
          ...AUTO_PARAMS.map(([key, label]) => el("button.ghost", {
            class: (laneParam.get(t.id) || "volume") === key ? "on" : "",
            style: { fontSize: ".7rem" },
            onclick: () => { laneParam.set(t.id, key); drawArrange(); drawTrackPanel(); },
          }, label)),
          el("button.ghost", { style: { fontSize: ".7rem" },
            onclick: () => {
              const key = laneParam.get(t.id) || "volume";
              t.automation[key] = [];
              drawArrange(); host.save(); scheduleRender({ restart: true });
            } }, "clear")) : null));
    });
  }

  // ---------------------------------------------------------------- import/export

  const audioInput = el("input", {
    type: "file", accept: "audio/*", hidden: true,
    onchange: async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const buf = await A.audioCtx().decodeAudioData(await file.arrayBuffer());
        const t = { id: nid(), name: file.name.slice(0, 16), instrument: "sampler",
          vol: 0.8, pan: 0, mute: false, solo: false, cutoff: 1, clips: [],
          automation: {}, root: 60, fx: defaultFx() };
        t.sample = buf.getChannelData(0).slice(0, A.SR * 8);
        doc.tracks.push(t);
        const asset = await host.upload(file, { kind: "sample", trackId: t.id });
        t.assetId = asset.id;
        activeTrack = doc.tracks.length - 1;
        renderViews(); host.save();
        toast(`Added "${t.name}" — draw a clip, then play it from the roll (root C4)`);
      } catch (err) { toast(`Could not read that audio: ${err.message}`); }
      e.target.value = "";
    },
  });

  for (const t of doc.tracks) {
    if (t.instrument === "sampler" && t.assetId && !t.sample) {
      const asset = host.assets.find((a) => a.id === t.assetId);
      if (!asset) continue;
      try {
        const res = await fetch(asset.url);
        const buf = await A.audioCtx().decodeAudioData(await res.arrayBuffer());
        t.sample = buf.getChannelData(0).slice(0, A.SR * 8);
      } catch { /* the sample is gone; the track stays silent */ }
    }
  }

  // ---------------------------------------------------------------- scopes

  /**
   * The scopes, reading the audio that is actually playing.
   *
   * The rule from the video scopes, unchanged: measure what will be exported.
   * Here that is literally true — the meters read the rendered mix at the
   * playhead, which is the same buffer the WAV is written from, so a number
   * on screen is a number about the file.
   *
   * The pictures are drawn by the render graph. A spectrum is a picture, and
   * the app has a whole compiler for those.
   */
  const scopeCanvas = {
    spectrum: el("canvas", { width: 480, height: 130, style: { width: "100%", borderRadius: "6px", display: "block" } }),
    spectrogram: el("canvas", { width: 480, height: 150, style: { width: "100%", borderRadius: "6px", display: "block" } }),
    wave: el("canvas", { width: 480, height: 90, style: { width: "100%", borderRadius: "6px", display: "block" } }),
    correlation: el("canvas", { width: 480, height: 34, style: { width: "100%", borderRadius: "6px", display: "block" } }),
  };
  const scopeNumbers = el("p.fine", {}, "Press play.");
  let scopeTools = null, scopesOn = false, scopeDue = 0, spectro = null;
  // Integrated loudness and true peak are measurements of the whole mix, and
  // both cost about a hundred operations a sample. Computing them every frame
  // is what made the first version of this panel hang the page — so they are
  // computed once per render and cached against the buffer they describe.
  let scopeStats = { forBuffer: null, lufs: -Infinity, tp: -Infinity, busy: false };

  async function ensureScopeTools() {
    if (scopeTools) return scopeTools;
    const [AS, RG, GC] = await Promise.all([
      import("./audio-scopes.js"), import("./render-graph.js"), import("./graph-compile.js"),
    ]);
    await import("./scope-nodes.js");
    scopeTools = { AS, RG, GC };
    spectro = AS.spectrogram(256, 192);
    return scopeTools;
  }

  /** One node, one canvas — the shortest path from a measurement to a picture. */
  function drawScope(tools, canvas, type, sourceCanvas, params = {}) {
    const { RG, GC } = tools;
    const g = RG.createGraph(canvas.width, canvas.height);
    let out;
    if (sourceCanvas) {
      const src = RG.addNode(g, "source");
      out = RG.addNode(g, type, params, [src]);
      g.output = out;
      GC.renderGraph(g, { [src]: sourceCanvas }, { into: canvas.getContext("2d") });
    } else {
      g.output = RG.addNode(g, type, params, []);
      GC.renderGraph(g, {}, { into: canvas.getContext("2d") });
    }
  }

  let lastCorrelation = 0;
  function writeScopeNumbers(corr) {
    const lufsText = scopeStats.forBuffer === rendered
      ? `${scopeStats.lufs === -Infinity ? "—" : scopeStats.lufs.toFixed(1)} LUFS integrated · `
        + `${scopeStats.tp.toFixed(1)} dBTP true peak`
      : "measuring loudness…";
    scopeNumbers.textContent = `${lufsText} · correlation ${corr.toFixed(2)} · `
      + "measured on the rendered mix, which is the buffer the WAV is written from";
  }

  async function updateScopes() {
    if (!scopesOn || !rendered) return;
    const now = performance.now();
    if (now < scopeDue) return;
    scopeDue = now + 70;
    const tools = await ensureScopeTools();
    const { AS } = tools;
    const sr = rendered.sampleRate;
    const L = rendered.getChannelData(0);
    const R = rendered.numberOfChannels > 1 ? rendered.getChannelData(1) : L;
    const at = Math.min(L.length - 2048, Math.max(0, Math.floor(playheadSec() * sr)));
    const win = L.subarray(at, at + 2048);
    const mag = A.fftMag(win);

    drawScope(tools, scopeCanvas.spectrum, "scope.spectrum",
      AS.rowTexture(AS.packSpectrum(mag, { width: scopeCanvas.spectrum.width })));
    spectro.push(mag);
    drawScope(tools, scopeCanvas.spectrogram, "scope.spectrogram", spectro.canvas,
      { head: [spectro.head] });
    drawScope(tools, scopeCanvas.wave, "scope.wave",
      AS.rowTexture(AS.packWaveform(L.subarray(at, at + 8192), { width: scopeCanvas.wave.width })));
    const corr = AS.correlation(L.subarray(at, at + 8192), R.subarray(at, at + 8192));
    drawScope(tools, scopeCanvas.correlation, "scope.correlation", null, { value: [corr] });

    // The numbers are about the whole mix, not the window: loudness is
    // integrated by definition, and a peak you have already passed still
    // clipped. So they are measured once for this buffer, not once a frame.
    if (scopeStats.forBuffer !== rendered && !scopeStats.busy) {
      scopeStats.busy = true;
      setTimeout(() => {
        try {
          const loud = AS.loudnessLUFS([L, R], sr);
          scopeStats = { forBuffer: rendered, lufs: loud.lufs, tp: AS.truePeakDb([L, R]), busy: false };
          // Say so at once. Waiting for the next frame means never, when
          // nothing is playing — which is exactly when someone opens the
          // panel to read the numbers.
          writeScopeNumbers(lastCorrelation);
        } catch (e) { scopeStats.busy = false; }
      }, 0);
    }
    lastCorrelation = corr;
    writeScopeNumbers(corr);
  }

  const scopePanel = el("div.card", { style: { display: "none" } },
    el("h3", {}, "Scopes"),
    el("p.fine", {}, "Spectrum and spectrogram are logarithmic in frequency, because hearing is. "
      + "The pictures are render-graph nodes — the same compiler the canvas and video studios draw with."),
    scopeCanvas.spectrum, scopeCanvas.spectrogram, scopeCanvas.wave, scopeCanvas.correlation,
    scopeNumbers);

  /**
   * The pattern, rendered through the compiled DSP graph rather than the
   * built-in synth: notes scheduled onto voices, the whole thing bounced
   * offline. It is the same file every time, which the sampled synth cannot
   * promise, and it is the thread from this sequencer to the audio roadmap's
   * engine.
   */
  async function bounceGraph() {
    const pat = patternById(activePattern);
    if (!pat || !pat.notes.length) { toast("This pattern has no notes yet."); return; }
    try {
      const { createDspGraph, addDspNode } = await import("./dsp-graph.js");
      const { renderSong, noteHz, toWav } = await import("./dsp-song.js");
      const g = createDspGraph();
      const note = addDspNode(g, "voice.note", {});
      const osc = addDspNode(g, "osc.sineHz",
        { inputs: { hz: [note, "hz"], gate: [note, "gate"] }, params: { amp: 0.25 } });
      const lp = addDspNode(g, "filter.svf",
        { inputs: { x: [osc, "y"] }, params: { freq: 4000, q: 0.8 } });
      g.output = lp;
      const sd = secPerStep();
      const notes = pat.notes
        .filter((n) => Number.isFinite(n.step) && Number.isFinite(n.pitch))
        .map((n) => ({ t: n.step * sd, dur: Math.max(0.05, (n.len || 1) * sd),
                       midi: n.pitch, hz: noteHz(n.pitch) }));
      toast(`Rendering ${notes.length} notes…`);
      const r = await renderSong({ graph: g, noteNode: note, notes },
                                 { sampleRate: 48000, voices: 8 });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(toWav(r.buffer));
      a.download = `${host.doc.name || "pattern"}-graph.wav`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`Bounced ${r.seconds.toFixed(1)}s in ${r.ms.toFixed(0)}ms — `
        + `${r.realtimeRatio.toFixed(1)}× faster than real time, and the same file every time.`);
    } catch (e) {
      toast(`The graph bounce failed: ${String(e.message).split("\n")[0]}`);
    }
  }

  function exportWav() {
    if (!rendered) { toast("Nothing rendered yet — press play once"); return; }
    const Lc = rendered.getChannelData(0);
    const Rc = rendered.numberOfChannels > 1 ? rendered.getChannelData(1) : Lc;
    const n = Lc.length;
    const bytes = new ArrayBuffer(44 + n * 4);
    const dv = new DataView(bytes);
    const wr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    wr(0, "RIFF"); dv.setUint32(4, 36 + n * 4, true); wr(8, "WAVEfmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 2, true);
    dv.setUint32(24, A.SR, true); dv.setUint32(28, A.SR * 4, true);
    dv.setUint16(32, 4, true); dv.setUint16(34, 16, true);
    wr(36, "data"); dv.setUint32(40, n * 4, true);
    for (let i = 0; i < n; i++) {
      dv.setInt16(44 + i * 4, clamp(Lc[i], -1, 1) * 32767, true);
      dv.setInt16(46 + i * 4, clamp(Rc[i], -1, 1) * 32767, true);
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    a.download = `${host.doc.name || "track"}.wav`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---------------------------------------------------------------- chrome

  const playBtn = el("button.primary", {
    onclick: async () => {
      if (playing) return stopPlayback();
      if (!rendered) rendered = await renderMix();
      if (!rendered) { toast("No clips yet — click a track lane to place one"); return; }
      startPlayback(playFromSec);
    },
  }, "Play");

  const viewTabs = el("div.lib-nav");
  function setView(v) {
    view = v;
    [...viewTabs.children].forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    renderViews();
  }
  for (const [id, label] of [["arrange", "Arrange"], ["edit", "Edit"], ["mix", "Mix"]]) {
    viewTabs.append(el("button", { "data-view": id, class: id === view ? "on" : "",
      onclick: () => setView(id) }, label));
  }

  const stageWrap = el("div.card.tight", { style: { overflow: "auto" } });
  const sidePanel = el("div.stack");

  function renderViews() {
    clear(stageWrap);
    clear(sidePanel);
    if (view === "arrange") {
      stageWrap.append(arrange);
      drawArrange();
      drawTrackPanel(); drawPatterns();
      append(sidePanel,
        el("div.card.tight", {},
          el("div.spread", {}, el("h4", { style: { margin: 0 } }, "Tracks"),
            el("button.ghost", { onclick: addTrack }, "+")),
          trackPanel),
        el("div.card.tight", {},
          el("div.spread", {}, el("h4", { style: { margin: 0 } }, "Patterns"),
            el("button.ghost", { onclick: addPattern }, "+")),
          patternList,
          el("p.fine", {}, "Click an empty lane to place the selected pattern. " +
            "Drag to move, drag the right edge to repeat it, double-click to " +
            "edit. ⌘D duplicates, ⌫ deletes, space plays.")));
    } else if (view === "edit") {
      stageWrap.append(grid);
      drawGrid();
      drawPatterns();
      const pat = patternById(activePattern);
      append(sidePanel,
        el("div.card.tight", {},
          el("h4", {}, "Pattern"),
          pat ? el("div.stack", {},
            el("label", {}, "Name",
              el("input", { value: pat.name,
                onchange: (e) => { pat.name = e.target.value; renderViews(); host.save(); } })),
            el("label", {}, "Bars",
              el("input", { type: "number", min: 1, max: 16, value: pat.bars,
                onchange: (e) => {
                  pat.bars = clamp(+e.target.value || 1, 1, 16);
                  pat.notes = pat.notes.filter((n) => n.step < pat.bars * stepsPerBar);
                  renderViews(); host.save(); scheduleRender({ restart: true });
                } })),
            el("label", {}, "Note length",
              el("select", { onchange: (e) => { noteLen = +e.target.value; } },
                ...[[1, "16th"], [2, "8th"], [4, "quarter"], [8, "half"], [16, "bar"]]
                  .map(([v, l]) => el("option", { value: v, selected: v === noteLen }, l)))),
            el("button.ghost.danger", {
              onclick: () => { pat.notes = []; renderViews(); host.save(); scheduleRender({ restart: true }); },
            }, "Clear notes")) : el("p.fine", {}, "No pattern selected."),
          el("p.fine", {}, `Editing on the "${doc.tracks[activeTrack]?.name}" track — ` +
            `the instrument decides whether you get a drum grid or a roll.`)),
        el("div.card.tight", {}, el("h4", {}, "Patterns"), patternList));
    } else {
      drawMixer();
      stageWrap.append(mixer);
      append(sidePanel, el("div.card.tight", {},
        el("h4", {}, "Mix"),
        el("p.fine", {}, "Meters show the peak measured at render, before the " +
          "master limiter. Red means that track alone is hitting the ceiling."),
        el("p.fine", {}, "Solo overrides mute. Automation on the Arrange tab " +
          "moves volume and filter over the arrangement.")));
    }
  }

  function addTrack() {
    doc.tracks.push({ id: nid(), name: `Track ${doc.tracks.length + 1}`,
      instrument: "synth", vol: 0.8, pan: 0, mute: false, solo: false,
      cutoff: 1, clips: [], automation: {}, fx: defaultFx() });
    activeTrack = doc.tracks.length - 1;
    renderViews(); host.save();
  }
  function addPattern() {
    const p = { id: nid(), name: `Pattern ${doc.patterns.length + 1}`, bars: 4, notes: [] };
    doc.patterns.push(p);
    activePattern = p.id;
    setView("edit");
    host.save();
  }

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        playBtn,
        el("button", { onclick: () => { playFromSec = 0; if (playing) startPlayback(0); else drawArrange(); } }, "⏮"),
        viewTabs,
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "bpm",
          el("input", { type: "number", value: doc.bpm, min: 40, max: 220, style: { width: "5rem" },
            onchange: (e) => { doc.bpm = +e.target.value || 120; host.save(); renderViews(); scheduleRender({ restart: true }); } })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "bars",
          el("input", { type: "number", value: doc.bars, min: 1, max: 128, style: { width: "5rem" },
            onchange: (e) => { doc.bars = clamp(+e.target.value || 8, 1, 128); host.save(); renderViews(); scheduleRender({ restart: true }); } })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "swing",
          el("input", { type: "range", min: 0, max: 0.6, step: 0.02, value: doc.swing || 0,
            oninput: (e) => { doc.swing = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); } })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "zoom",
          el("input", { type: "range", min: 18, max: 120, step: 2, value: barW,
            oninput: (e) => { barW = +e.target.value; drawArrange(); } })),
        el("button", { onclick: () => audioInput.click() }, "Import audio"),
        el("button", { onclick: exportWav }, "WAV"),
        el("button.ghost", { title: "render this pattern through the compiled DSP graph",
          onclick: bounceGraph }, "Bounce (graph)"),
        el("button.ghost", { title: "spectrum, spectrogram, waveform and correlation",
          onclick: async (e) => {
            scopesOn = !scopesOn;
            scopePanel.style.display = scopesOn ? "" : "none";
            e.target.classList.toggle("on", scopesOn);
            if (scopesOn) {
              if (!rendered) rendered = await renderMix();
              scopeDue = 0;
              await updateScopes();
            }
          } }, "Scopes"),
        audioInput,
        aiButton("Pattern…", {
          task: "music",
          describe: "The model writes notes into new patterns and places them. " +
            "It is drafting material for you to cut, not a finished idea.",
          placeholder: "e.g. dub — offbeat skank, sparse kick, lots of space",
          context: () => `Tempo ${doc.bpm} BPM. Write patterns of 4 bars ` +
            `(64 sixteenth-note steps, step 0-63).`,
          onResult: (res) => {
            const j = res.json;
            if (!j?.tracks?.length) { toast(res.parse_error || "nothing usable came back"); return; }
            if (j.bpm) doc.bpm = Math.round(j.bpm);
            for (const t of j.tracks) {
              const notes = (t.notes || [])
                .filter((n) => Number.isFinite(n.step) && Number.isFinite(n.pitch))
                .map((n) => ({ step: clamp(n.step | 0, 0, 63),
                               pitch: clamp(n.pitch | 0, 12, 108),
                               len: clamp(n.len | 0 || 1, 1, 32) }));
              if (!notes.length) continue;
              const pat = { id: nid(), name: (t.name || "generated").slice(0, 16),
                            bars: 4, notes };
              doc.patterns.push(pat);
              const track = { id: nid(), name: pat.name,
                instrument: INSTRUMENTS.some(([v]) => v === t.instrument) ? t.instrument : "synth",
                vol: 0.8, pan: 0, mute: false, solo: false, cutoff: 1,
                automation: {}, fx: defaultFx(),
                clips: [{ id: nid(), patternId: pat.id, startBar: 0, bars: 4 }] };
              doc.tracks.push(track);
            }
            activeTrack = doc.tracks.length - 1;
            activePattern = doc.patterns[doc.patterns.length - 1].id;
            renderViews(); host.save(); scheduleRender({ restart: true });
            toast(j.note || "Patterns added as new tracks");
          },
        }))),

    el("div.lab-split", { style: { gridTemplateColumns: "minmax(0,1fr) 250px" } },
      el("div.stack", {}, stageWrap, scopePanel), sidePanel));

  root._cleanup = () => document.removeEventListener("keydown", onKey);

  renderViews();
  scheduleRender();
  return root;
}
