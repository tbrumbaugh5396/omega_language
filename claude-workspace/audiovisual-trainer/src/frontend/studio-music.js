// The music editor: tracks, a piano roll, a drum grid, and a per-track effect
// chain built from the same primitives the ear drills use.
//
// Playback renders the whole arrangement offline into one buffer and loops it,
// rather than running a live scheduler. For a sketching tool that trade is
// worth it: edits re-render in a fraction of a second, the result is
// sample-accurate, and "export" is the same code path as "play" — so what you
// hear is exactly what lands in the file.

import { el, clear, toast, modal, closeModal, knob, confirmDialog } from "./ui.js";
import * as A from "./engine-audio.js";
import { aiButton } from "./ai.js";

const INSTRUMENTS = [
  ["drums", "Drums"], ["bass", "Bass"], ["synth", "Synth"],
  ["pluck", "Pluck"], ["fm", "FM"], ["sampler", "Sampler"],
];

// The drum map is the one the AI task prompt documents, so generated
// patterns land on the right rows without translation.
const DRUMS = [
  [36, "Kick"], [38, "Snare"], [42, "Hat"], [46, "Open hat"], [45, "Tom"],
];

const ROLL_LOW = 36, ROLL_HIGH = 84;     // C2..C6
const CELL_W = 22, CELL_H = 13;

export async function musicEditor(host) {
  const doc = host.data;
  doc.tracks ||= [];
  let active = 0;
  let playing = false, stopFn = null, rendered = null, playStart = 0;
  const steps = () => doc.bars * 16;
  const stepDur = () => 60 / doc.bpm / 4;
  const totalSecs = () => steps() * stepDur() + 1.5;   // tail for reverb/decay

  // ---------------------------------------------------------------- synthesis

  function synthTrack(track) {
    const sr = A.SR;
    const out = new Float32Array(Math.ceil(totalSecs() * sr));
    const sd = stepDur();
    for (const n of track.notes) {
      const at = Math.floor((n.step * sd + swingOffset(n.step)) * sr);
      const dur = Math.max(0.05, (n.len || 1) * sd);
      const part = voice(track, n, dur);
      for (let i = 0; i < part.length && at + i < out.length; i++) {
        if (at + i >= 0) out[at + i] += part[i];
      }
    }
    return out;
  }

  const swingOffset = (step) =>
    (step % 2 === 1 ? (doc.swing || 0) * stepDur() * 0.5 : 0);

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
        // Saw-ish with a fast decay: partials summed, then shaped.
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
        const ratio = 2, index = 4;
        for (let i = 0; i < n; i++) {
          const t = i / A.SR;
          const env = Math.min(1, t * 120) * Math.exp(-t * 3.2);
          const mod = Math.sin(2 * Math.PI * hz * ratio * t) * index * Math.exp(-t * 4);
          buf[i] = Math.sin(2 * Math.PI * hz * t + mod) * env * 0.28;
        }
        return A.fade(buf, A.SR, 6);
      }
      case "sampler": {
        const s = track.sample;
        if (!s) return new Float32Array(0);
        // Resample by pitch relative to the root note.
        const rate = Math.pow(2, (note.pitch - (track.root ?? 60)) / 12);
        const n = Math.min(Math.ceil((dur + 0.3) * A.SR), Math.floor(s.length / rate));
        const buf = new Float32Array(n);
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

  /** One offline render: every track chained through its own effects, mixed. */
  async function renderMix() {
    const live = doc.tracks.filter((t) => !t.mute && t.notes.length);
    if (!live.length) return null;
    const length = Math.ceil(totalSecs() * A.SR);
    const OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const ctx = new OC(2, length, A.SR);
    // Master bus: sum, then limit. Tracks are summed without headroom
    // management, so anything with three or more busy parts hits the ceiling —
    // and an export that clips is not a mix, it is a mistake with a waveform.
    const master = ctx.createGain();
    master.gain.value = 0.85;
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -3;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = 0.002;
    limiter.release.value = 0.12;
    master.connect(limiter).connect(ctx.destination);

    for (const track of live) {
      const samples = synthTrack(track);
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
      if (fx.drive) {
        const ws = ctx.createWaveShaper();
        ws.curve = A.shaperCurve("asym", Math.min(0.95, fx.drive));
        ws.oversample = "2x";
        node = node.connect(ws);
      }
      const pan = ctx.createStereoPanner();
      pan.pan.value = Math.max(-1, Math.min(1, track.pan || 0));
      const gain = ctx.createGain();
      gain.gain.value = track.vol ?? 0.8;
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
      if (restart && playing) startPlayback();
    }, 220);
  }

  function startPlayback() {
    stopFn?.();
    if (!rendered) return;
    playStart = performance.now();
    stopFn = A.play(rendered, { loop: true });
    playing = true;
    playBtn.textContent = "Stop";
    requestAnimationFrame(tickPlayhead);
  }
  function stopPlayback() {
    stopFn?.();
    A.stopAll();
    playing = false;
    playBtn.textContent = "Play";
    drawGrid();
  }

  function tickPlayhead() {
    if (!playing) return;
    drawGrid();
    requestAnimationFrame(tickPlayhead);
  }
  const playheadStep = () => {
    if (!playing) return -1;
    const loopSecs = steps() * stepDur();
    const t = ((performance.now() - playStart) / 1000) % (totalSecs());
    return t < loopSecs ? Math.floor(t / stepDur()) : -1;
  };

  // ---------------------------------------------------------------- grid

  const grid = el("canvas", { style: { display: "block", cursor: "crosshair" } });
  const gg = grid.getContext("2d");
  let noteLen = 2;

  function rowsFor(track) {
    return track.instrument === "drums"
      ? DRUMS.map(([p, n]) => ({ pitch: p, label: n }))
      : Array.from({ length: ROLL_HIGH - ROLL_LOW + 1 }, (_, i) => {
          const pitch = ROLL_HIGH - i;
          const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
          return { pitch, label: `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}` };
        });
  }

  function drawGrid() {
    const track = doc.tracks[active];
    if (!track) return;
    const rows = rowsFor(track);
    const n = steps();
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
      if (track.instrument === "drums" || r.pitch % 12 === 0) {
        gg.fillText(r.label, 4, ri * CELL_H + CELL_H - 4);
      }
    });

    for (let s = 0; s <= n; s++) {
      gg.fillStyle = s % 16 === 0 ? "#3a4260" : s % 4 === 0 ? "#232a40" : "#191f30";
      gg.fillRect(52 + s * CELL_W, 0, 1, rows.length * CELL_H);
    }

    for (const note of track.notes) {
      const ri = rows.findIndex((r) => r.pitch === note.pitch);
      if (ri < 0) continue;
      gg.fillStyle = "#7c9cff";
      gg.fillRect(52 + note.step * CELL_W + 1, ri * CELL_H + 1,
                  Math.max(CELL_W - 2, (note.len || 1) * CELL_W - 2), CELL_H - 3);
    }

    const ph = playheadStep();
    if (ph >= 0) {
      gg.fillStyle = "#6ee7c8";
      gg.fillRect(52 + ph * CELL_W, 0, 2, rows.length * CELL_H);
    }
  }

  grid.addEventListener("pointerdown", (e) => {
    const track = doc.tracks[active];
    const r = grid.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * grid.width - 52;
    const y = ((e.clientY - r.top) / r.height) * grid.height;
    if (x < 0) return;
    const step = Math.floor(x / CELL_W);
    const rows = rowsFor(track);
    const row = rows[Math.floor(y / CELL_H)];
    if (!row || step < 0 || step >= steps()) return;

    const hit = track.notes.findIndex((nt) =>
      nt.pitch === row.pitch && step >= nt.step && step < nt.step + (nt.len || 1));
    if (hit >= 0) track.notes.splice(hit, 1);
    else {
      track.notes.push({ step, pitch: row.pitch,
                         len: track.instrument === "drums" ? 1 : noteLen });
    }
    drawGrid();
    host.save();
    scheduleRender({ restart: true });
  });

  // ---------------------------------------------------------------- tracks

  const trackList = el("div.stack");
  function renderTracks() {
    clear(trackList);
    doc.tracks.forEach((t, i) => {
      trackList.append(el("div.card.tight", {
        style: { borderColor: i === active ? "var(--accent)" : "" },
      },
        el("div.spread", {},
          el("button.ghost", { style: { padding: ".1em .4em" },
            onclick: () => { active = i; renderTracks(); drawGrid(); } },
            el("b", {}, t.name)),
          el("div.row.tight", {},
            el("button.ghost", {
              class: t.mute ? "on" : "",
              onclick: () => { t.mute = !t.mute; renderTracks(); host.save(); scheduleRender({ restart: true }); },
            }, t.mute ? "muted" : "on"),
            el("button.ghost", { onclick: () => fxDialog(t) }, "fx"),
            el("button.ghost.danger", {
              onclick: async () => {
                if (!(await confirmDialog(`Delete "${t.name}"?`))) return;
                doc.tracks.splice(i, 1);
                active = Math.max(0, active - 1);
                renderTracks(); drawGrid(); host.save(); scheduleRender({ restart: true });
              },
            }, "×"))),
        el("div.row.tight", { style: { marginTop: ".3rem" } },
          el("select", {
            style: { width: "auto", fontSize: ".75rem" },
            onchange: (e) => { t.instrument = e.target.value; renderTracks(); drawGrid(); host.save(); scheduleRender({ restart: true }); },
          }, ...INSTRUMENTS.map(([v, l]) => el("option", { value: v, selected: v === t.instrument }, l))),
          el("input", {
            type: "range", min: 0, max: 1, step: 0.01, value: t.vol ?? 0.8,
            title: "level", style: { flex: 1 },
            oninput: (e) => { t.vol = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); },
          }),
          el("input", {
            type: "range", min: -1, max: 1, step: 0.05, value: t.pan ?? 0,
            title: "pan", style: { flex: 1 },
            oninput: (e) => { t.pan = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); },
          }))));
    });
  }

  function fxDialog(track) {
    track.fx ||= {};
    const f = track.fx;
    const box = el("div.stack", {},
      knob("EQ frequency", { min: 40, max: 12000, step: 10, value: f.eqFreq || 800,
        format: (v) => `${v.toFixed(0)} Hz`, oninput: (v) => { f.eqFreq = v; } }),
      knob("EQ gain", { min: -18, max: 18, step: 0.5, value: f.eqGain || 0,
        format: (v) => `${v.toFixed(1)} dB`, oninput: (v) => { f.eqGain = v; } }),
      knob("EQ Q", { min: 0.3, max: 12, step: 0.1, value: f.eqQ || 1,
        format: (v) => v.toFixed(1), oninput: (v) => { f.eqQ = v; } }),
      knob("Drive", { min: 0, max: 0.95, step: 0.01, value: f.drive || 0,
        format: (v) => v.toFixed(2), oninput: (v) => { f.drive = v; } }),
      knob("Delay", { min: 0, max: 600, step: 1, value: f.delayMs || 0,
        format: (v) => `${v.toFixed(0)} ms`, oninput: (v) => { f.delayMs = v; } }),
      knob("Delay feedback", { min: 0, max: 0.85, step: 0.01, value: f.delayFb ?? 0.25,
        format: (v) => v.toFixed(2), oninput: (v) => { f.delayFb = v; } }),
      knob("Reverb", { min: 0, max: 1, step: 0.01, value: f.reverb || 0,
        format: (v) => v.toFixed(2), oninput: (v) => { f.reverb = v; } }),
      knob("Reverb decay", { min: 0.2, max: 5, step: 0.1, value: f.reverbDecay || 1.6,
        format: (v) => `${v.toFixed(1)}s`, oninput: (v) => { f.reverbDecay = v; } }));
    modal(el("h2", {}, `${track.name} — effects`),
      el("p.fine", {}, "The same primitives the ear drills are built on: one " +
        "biquad, one transfer curve, one delay line, one impulse response."),
      box,
      el("div.row", { style: { justifyContent: "flex-end" } },
        el("button.primary", {
          onclick: () => { closeModal(); host.save(); scheduleRender({ restart: true }); },
        }, "Done")));
  }

  // ---------------------------------------------------------------- import/export

  const audioInput = el("input", {
    type: "file", accept: "audio/*", hidden: true,
    onchange: async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const buf = await A.audioCtx().decodeAudioData(await file.arrayBuffer());
        const t = {
          id: Math.max(0, ...doc.tracks.map((x) => x.id)) + 1,
          name: file.name.slice(0, 18), instrument: "sampler",
          vol: 0.8, pan: 0, mute: false, notes: [], root: 60,
          fx: { eqFreq: 800, eqGain: 0, eqQ: 1, drive: 0, delayMs: 0, delayFb: 0.25, reverb: 0, reverbDecay: 1.6 },
        };
        doc.tracks.push(t);
        // The samples stay in memory for this session and the file is stored
        // as an asset, so the project can rebuild it next time.
        t.sample = buf.getChannelData(0).slice(0, A.SR * 8);
        const asset = await host.upload(file, { kind: "sample", trackId: t.id });
        t.assetId = asset.id;
        active = doc.tracks.length - 1;
        renderTracks(); drawGrid(); host.save();
        toast(`Added "${t.name}" — play it from the roll, root note C4`);
      } catch (err) {
        toast(`Could not read that audio: ${err.message}`);
      }
      e.target.value = "";
    },
  });

  // Rehydrate sampler tracks from their stored assets.
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

  function exportWav() {
    if (!rendered) { toast("Nothing rendered yet — press play once"); return; }
    const L = rendered.getChannelData(0);
    const R = rendered.numberOfChannels > 1 ? rendered.getChannelData(1) : L;
    const n = L.length;
    const bytes = new ArrayBuffer(44 + n * 4);
    const dv = new DataView(bytes);
    const wr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    wr(0, "RIFF"); dv.setUint32(4, 36 + n * 4, true); wr(8, "WAVEfmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 2, true);
    dv.setUint32(24, A.SR, true); dv.setUint32(28, A.SR * 4, true);
    dv.setUint16(32, 4, true); dv.setUint16(34, 16, true);
    wr(36, "data"); dv.setUint32(40, n * 4, true);
    for (let i = 0; i < n; i++) {
      dv.setInt16(44 + i * 4, Math.max(-1, Math.min(1, L[i])) * 32767, true);
      dv.setInt16(46 + i * 4, Math.max(-1, Math.min(1, R[i])) * 32767, true);
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    a.download = `${host.doc.name || "track"}.wav`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---------------------------------------------------------------- layout

  const playBtn = el("button.primary", {
    onclick: async () => {
      if (playing) return stopPlayback();
      if (!rendered) rendered = await renderMix();
      if (!rendered) { toast("No notes yet — click into the grid"); return; }
      startPlayback();
    },
  }, "Play");

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        playBtn,
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "bpm",
          el("input", {
            type: "number", value: doc.bpm, min: 40, max: 220,
            style: { width: "5rem" },
            onchange: (e) => { doc.bpm = +e.target.value || 120; host.save(); drawGrid(); scheduleRender({ restart: true }); },
          })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "bars",
          el("input", {
            type: "number", value: doc.bars, min: 1, max: 32,
            style: { width: "4.5rem" },
            onchange: (e) => { doc.bars = Math.max(1, +e.target.value || 4); host.save(); drawGrid(); scheduleRender({ restart: true }); },
          })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "swing",
          el("input", {
            type: "range", min: 0, max: 0.6, step: 0.02, value: doc.swing || 0,
            oninput: (e) => { doc.swing = +e.target.value; },
            onchange: () => { host.save(); scheduleRender({ restart: true }); },
          })),
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } }, "note",
          el("select", { style: { width: "auto" }, onchange: (e) => { noteLen = +e.target.value; } },
            ...[[1, "16th"], [2, "8th"], [4, "quarter"], [8, "half"], [16, "bar"]].map(([v, l]) =>
              el("option", { value: v, selected: v === 2 }, l)))),
        el("button", { onclick: () => audioInput.click() }, "Import audio"),
        el("button", { onclick: exportWav }, "WAV"),
        audioInput,
        aiButton("Pattern…", {
          task: "music",
          describe: "The model writes notes into a new set of tracks. It is " +
            "drafting material for you to cut, not a finished idea.",
          placeholder: "e.g. dub — offbeat skank, sparse kick, lots of space, " +
            "8 bars",
          context: () => `Tempo ${doc.bpm} BPM, ${doc.bars} bars, ` +
            `${doc.bars * 16} sixteenth-note steps available.`,
          onResult: (res) => {
            const j = res.json;
            if (!j?.tracks?.length) { toast(res.parse_error || "nothing usable came back"); return; }
            if (j.bpm) { doc.bpm = Math.round(j.bpm); }
            let nextId = Math.max(0, ...doc.tracks.map((t) => t.id));
            for (const t of j.tracks) {
              const notes = (t.notes || [])
                .filter((n) => Number.isFinite(n.step) && Number.isFinite(n.pitch))
                .map((n) => ({ step: Math.max(0, Math.min(steps() - 1, n.step | 0)),
                               pitch: Math.max(12, Math.min(108, n.pitch | 0)),
                               len: Math.max(1, Math.min(32, n.len | 0 || 1)) }));
              if (!notes.length) continue;
              doc.tracks.push({
                id: ++nextId, name: (t.name || "generated").slice(0, 18),
                instrument: INSTRUMENTS.some(([v]) => v === t.instrument) ? t.instrument : "synth",
                vol: 0.8, pan: 0, mute: false, notes,
                fx: { eqFreq: 800, eqGain: 0, eqQ: 1, drive: 0, delayMs: 0, delayFb: 0.25, reverb: 0, reverbDecay: 1.6 },
              });
            }
            active = doc.tracks.length - 1;
            renderTracks(); drawGrid(); host.save(); scheduleRender({ restart: true });
            toast(j.note || "Pattern added as new tracks");
          },
        }))),

    el("div.lab-split", { style: { gridTemplateColumns: "240px minmax(0,1fr)" } },
      el("div.stack", {},
        el("div.card.tight", {},
          el("div.spread", {}, el("h4", { style: { margin: 0 } }, "Tracks"),
            el("button.ghost", {
              onclick: () => {
                const id = Math.max(0, ...doc.tracks.map((t) => t.id)) + 1;
                doc.tracks.push({ id, name: `Track ${id}`, instrument: "synth",
                  vol: 0.8, pan: 0, mute: false, notes: [],
                  fx: { eqFreq: 800, eqGain: 0, eqQ: 1, drive: 0, delayMs: 0, delayFb: 0.25, reverb: 0, reverbDecay: 1.6 } });
                active = doc.tracks.length - 1;
                renderTracks(); drawGrid(); host.save();
              },
            }, "+")),
          trackList)),
      el("div.card.tight", { style: { overflow: "auto" } }, grid)));

  renderTracks();
  drawGrid();
  scheduleRender();
  return root;
}
