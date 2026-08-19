// A song, rendered.
//
// Phase D of the audio roadmap: instruments are graphs, the sequencer drives
// notes into them, tracks have their own effect chains, and a bounce must be
// sample-exact and the same file twice.
//
// Two decisions carry most of the weight:
//
//   - **Notes are scheduled, not messaged.** Every per-voice value is an
//     AudioParam, so a note is `setValueAtTime(hz, t)` — sample-accurate,
//     and identical whether it plays live or renders offline. A port message
//     cannot do that: in an offline render it arrives after the render has
//     finished.
//   - **Automation is the visual roadmap's keyframes.** Literally the same
//     evaluator — `evalTrack` from video-graph.js — because a parameter
//     moving over time is the same problem whether the parameter is a blur
//     radius or a cutoff, and having two of them would mean having two
//     answers to "what is it at 1.4 seconds".

import { installGraph } from "./dsp-runtime.js";
import { evalTrack } from "./video-graph.js";

export const noteHz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

/**
 * Which voice each note gets. Round-robin over the voices that are free,
 * and the oldest sounding one when none is — the ordinary rule, and the
 * ordinary rule is right: a stolen voice should be the one you are least
 * likely to still be listening to.
 */
export function allocateVoices(notes, count) {
  const freeAt = new Array(count).fill(-Infinity);
  const owner = new Array(count).fill(null);
  const out = [];
  for (const n of [...notes].sort((a, b) => a.t - b.t)) {
    let pick = -1;
    for (let v = 0; v < count; v++) if (freeAt[v] <= n.t) { pick = v; break; }
    if (pick < 0) {
      pick = 0;
      for (let v = 1; v < count; v++) if (freeAt[v] < freeAt[pick]) pick = v;
    }
    const stolen = freeAt[pick] > n.t;
    freeAt[pick] = n.t + n.dur;
    owner[pick] = n;
    out.push({ ...n, voice: pick, stolen });
  }
  return out;
}

/**
 * A pattern of steps as notes. `steps` is an array of arrays of MIDI numbers
 * (or null for a rest); `bpm` and `stepsPerBeat` say when they land.
 */
export function patternToNotes(steps, { bpm = 120, stepsPerBeat = 4, gate = 0.8 } = {}) {
  const step = 60 / bpm / stepsPerBeat;
  const notes = [];
  steps.forEach((row, i) => {
    for (const midi of (row || [])) {
      notes.push({ t: i * step, dur: step * gate, midi, hz: noteHz(midi) });
    }
  });
  return notes;
}

/**
 * Schedule everything a render needs: notes onto voices, automation onto
 * parameters. Pure scheduling — it touches AudioParams and nothing else, so
 * the same call produces the same sound offline and live.
 */
export function schedule(inst, song, { at = 0 } = {}) {
  const voices = inst.voices;
  const placed = allocateVoices(song.notes || [], voices);
  const noteNode = song.noteNode;
  for (const n of placed) {
    inst.setVoice(n.voice, noteNode, "pitch", n.hz, at + n.t);
    inst.setVoice(n.voice, noteNode, "on", 1, at + n.t);
    inst.setVoice(n.voice, noteNode, "on", 0, at + n.t + n.dur);
  }
  // Automation: `{ node, param, track }` where track is the same
  // `{t, v, ease}` list the video timeline keys.
  for (const a of song.automation || []) {
    const pm = inst.param(a.node, a.param);
    if (!pm) continue;
    const track = a.track || [];
    if (!track.length) continue;
    // Sampled at a fixed grid rather than handed to the browser's own ramps:
    // the eases are ours, and a hold is not a ramp.
    const step = a.step || 1 / 200;
    const end = track[track.length - 1].t;
    pm.setValueAtTime(evalTrack(track, 0), at);
    for (let t = 0; t <= end + 1e-9; t += step) {
      pm.setValueAtTime(evalTrack(track, t), at + t);
    }
  }
  return placed;
}

/**
 * Render a song offline. Returns `{ buffer, seconds, realtimeRatio }`.
 *
 * Deterministic by construction: every source of variation — note times,
 * automation, voice allocation — is computed here and scheduled, and the
 * graph itself has no clock of its own.
 */
export async function renderSong(song, { sampleRate = 48000, seconds = null, voices = 8 } = {}) {
  const notes = song.notes || [];
  const tail = song.tail ?? 0.5;
  const dur = seconds ?? Math.max(0.25, ...notes.map((n) => n.t + n.dur)) + tail;
  const frames = Math.max(128, Math.round(dur * sampleRate));
  const ctx = new OfflineAudioContext(1, frames, sampleRate);
  const inst = await installGraph(ctx, song.graph, {
    voices, voiceInit: song.voiceInit || {} });
  inst.node.connect(ctx.destination);
  schedule(inst, song);
  const t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
  const buffer = await ctx.startRendering();
  const ms = (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0;
  return { buffer, seconds: dur, ms, realtimeRatio: (dur * 1000) / Math.max(ms, 0.001) };
}

/** A rendered buffer as a 16-bit WAV, for a bounce that leaves the browser. */
export function toWav(buffer) {
  const chans = buffer.numberOfChannels, n = buffer.length, sr = buffer.sampleRate;
  const bytes = new ArrayBuffer(44 + n * chans * 2);
  const dv = new DataView(bytes);
  const tag = (at, s2) => { for (let i = 0; i < s2.length; i++) dv.setUint8(at + i, s2.charCodeAt(i)); };
  tag(0, "RIFF"); dv.setUint32(4, 36 + n * chans * 2, true); tag(8, "WAVE");
  tag(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
  dv.setUint16(22, chans, true); dv.setUint32(24, sr, true);
  dv.setUint32(28, sr * chans * 2, true); dv.setUint16(32, chans * 2, true);
  dv.setUint16(34, 16, true);
  tag(36, "data"); dv.setUint32(40, n * chans * 2, true);
  let at = 44;
  const data = Array.from({ length: chans }, (_, c) => buffer.getChannelData(c));
  for (let i = 0; i < n; i++) {
    for (let c = 0; c < chans; c++) {
      const v = Math.max(-1, Math.min(1, data[c][i]));
      dv.setInt16(at, v < 0 ? v * 0x8000 : v * 0x7fff, true);
      at += 2;
    }
  }
  return new Blob([bytes], { type: "audio/wav" });
}
