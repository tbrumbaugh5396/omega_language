// Module 4: the reference analyzer. Decompose a reference into the Part 6
// feature vocabulary — spectral features for audio, palette/edge/frequency
// statistics for image.
//
// Measuring a reference beats remembering it. But the numbers are a handle,
// not a verdict: the notes field is the point of the archive, because what
// you write about five references you love is where the shared features
// actually show up.

import { el, clear, api, toast, confirmDialog, relTime } from "./ui.js";
import * as I from "./engine-image.js";
import * as A from "./engine-audio.js";

export async function analyzeView(ctx) {
  const root = el("div");
  const result = el("div");

  const zone = el("div.dropzone", {}, "Drop an image or an audio file here, or click to choose. " +
    "Nothing leaves this machine.");
  const input = el("input", { type: "file", accept: "image/*,audio/*", hidden: true,
    onchange: (e) => e.target.files[0] && handle(e.target.files[0]) });
  zone.onclick = () => input.click();
  zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    const f = e.dataTransfer.files[0];
    if (f) handle(f);
  };

  root.append(el("div.card", {},
    el("h2", {}, "Reference analyzer"),
    el("p.dim", {}, "Daily analysis of one excellent thing. Decompose it: what " +
      "is the grid, the palette, the rhythm, the mix?"),
    zone, input), result);

  async function handle(file) {
    clear(result);
    result.append(el("div.card", {}, el("p.muted", {}, "Analysing…")));
    try {
      const node = file.type.startsWith("audio")
        ? await analyzeAudio(file, ctx)
        : await analyzeImage(file, ctx);
      clear(result);
      result.append(node);
    } catch (e) {
      clear(result);
      result.append(el("div.card", {}, el("p.err", {}, `Could not read that file: ${e.message}`)));
    }
  }

  root.append(await archivePane(ctx));
  return root;
}

const feat = (label, value, note = "") =>
  el("div.feature", {}, el("b", {}, value), el("span", {}, label), note && el("div.fine", {}, note));

// ------------------------------------------------------------------ image

async function analyzeImage(file, ctx) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 640 / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const c = I.makeCanvas(w, h);
  I.ctx2d(c).drawImage(bitmap, 0, 0, w, h);
  const img = I.getImage(c);

  const f = I.imageFeatures(img);
  const grid = I.detectGrid(img);
  const map = I.saliencyMap(img);
  const peak = I.saliencyPeak(map);

  const salC = I.saliencyToCanvas(map);
  const overlay = I.makeCanvas(w, h);
  const og = I.ctx2d(overlay);
  og.drawImage(c, 0, 0);
  og.globalAlpha = 0.55;
  og.drawImage(salC, 0, 0);
  og.globalAlpha = 1;
  og.strokeStyle = "#5fd39a";
  og.lineWidth = 2;
  og.beginPath();
  og.arc(peak.x, peak.y, Math.max(10, w / 22), 0, Math.PI * 2);
  og.stroke();

  // Grid overlay
  const gridC = I.makeCanvas(w, h);
  const gg = I.ctx2d(gridC);
  gg.drawImage(c, 0, 0);
  gg.strokeStyle = "rgba(124,156,255,.8)";
  gg.lineWidth = 1;
  for (const x of grid.peaks) {
    gg.beginPath(); gg.moveTo(x + 0.5, 0); gg.lineTo(x + 0.5, h); gg.stroke();
  }

  [c, overlay, gridC].forEach((cv) => { cv.style.width = "100%"; cv.style.height = "auto"; cv.style.borderRadius = "8px"; });

  const features = {
    kind: "image", width: f.width, height: f.height,
    meanLum: f.meanLum, contrastSd: f.contrastSd, dynamicRange: f.dynamicRange,
    edgeDensity: f.edgeDensity, edgeStrength: f.edgeStrength,
    paletteEntropy: f.paletteEntropy, freqBands: f.freqBands,
    orientation: f.orientation,
    gridColumns: grid.columns, gridModule: grid.module,
    palette: f.palette.map((p) => ({ hex: p.hex, share: +p.share.toFixed(3),
                                     L: +p.L.toFixed(3), chroma: +p.chroma.toFixed(3) })),
  };

  const notes = el("textarea", {
    placeholder: "Describe before you judge. What is the grid? Where does the " +
      "eye go, and what put it there? What is the palette doing on the " +
      "opponent axes?",
  });

  return el("div", {},
    el("div.card", {},
      el("h2", {}, file.name),
      el("div.g2.grid", {},
        el("div", {}, el("h4", {}, "Reference"), c),
        el("div", {}, el("h4", {}, "Saliency — predicted first fixation"), overlay))),

    el("div.card", {},
      el("h2", {}, "Palette", el("span.fine", {}, "k-means in OKLab")),
      el("div.swatches", { style: { marginBottom: "1.4rem" } },
        ...f.palette.map((p) => el("div.swatch", {
          style: { background: p.hex },
          title: `${p.hex} · ${(p.share * 100).toFixed(1)}% · L ${p.L.toFixed(2)} · C ${p.chroma.toFixed(3)}`,
        }, el("span", {}, `${Math.round(p.share * 100)}%`)))),
      el("p.fine", {}, `Palette entropy ${f.paletteEntropy} — higher means the ` +
        `image is spread evenly across its clusters; a disciplined palette ` +
        `usually sits low with one dominant and one accent.`)),

    el("div.card", {},
      el("h2", {}, "Structure"),
      el("div.feature-list", {},
        feat("mean luminance", f.meanLum, "0-255"),
        feat("contrast (sd)", f.contrastSd, "spread of luminance"),
        feat("dynamic range", f.dynamicRange),
        feat("edge density", f.edgeDensity, "fraction of pixels on an edge"),
        feat("edge strength", f.edgeStrength),
        feat("grid columns", grid.columns || "—", grid.module ? `module ≈ ${grid.module}px` : "no regular grid found")),
      el("h4", { style: { marginTop: ".8rem" } }, "Spatial frequency profile"),
      barRow(f.freqBands, ["fine", "→", "", "", "coarse"]),
      el("p.fine", {}, "Energy at each scale. A design that dies small is one " +
        "carrying its hierarchy in the leftmost bars."),
      el("h4", { style: { marginTop: ".8rem" } }, "Edge orientation"),
      barRow(f.orientation, ["0°", "45°", "90°", "135°", "180°", "225°", "270°", "315°"]),
      el("p.fine", {}, "Flat means organic; two spikes means a grid; a diagonal " +
        "bias is the Constructivist tell."),
      el("h4", { style: { marginTop: ".8rem" } }, "Detected columns"),
      gridC),

    el("div.card", {},
      el("h2", {}, "Your read"),
      notes,
      el("button.primary", {
        onclick: async () => {
          await api("/api/analyses", {
            method: "POST",
            body: { kind: "image", name: file.name, features, notes: notes.value },
          });
          toast("Archived");
          ctx.go("analyze");
        },
      }, "Archive this analysis")));
}

// ------------------------------------------------------------------ audio

async function analyzeAudio(file, ctx) {
  const buf = await file.arrayBuffer();
  const audio = await A.audioCtx().decodeAudioData(buf);
  const data = audio.getChannelData(0);
  // Cap at 60s: enough to characterise, fast enough to stay interactive.
  const slice = data.length > audio.sampleRate * 60
    ? data.subarray(0, audio.sampleRate * 60) : data;

  const f = A.audioFeatures(slice, audio.sampleRate);
  const bpm = A.estimateTempo(slice, audio.sampleRate);

  const wave = I.makeCanvas(700, 90);
  drawWaveform(I.ctx2d(wave), slice, 700, 90);
  const spec = I.makeCanvas(700, 200);
  drawSpectrogram(I.ctx2d(spec), slice, audio.sampleRate, 700, 200);
  [wave, spec].forEach((c) => { c.style.width = "100%"; c.style.height = "auto"; c.style.borderRadius = "8px"; });

  let stop = null;
  const features = {
    kind: "audio", seconds: f.seconds, rms: f.rms, peak: f.peak,
    centroid: f.centroid, rolloff85: f.rolloff85, flux: f.flux,
    onsetDensity: f.onsetDensity, bpm, bands: f.bands,
    channels: audio.numberOfChannels, sampleRate: audio.sampleRate,
  };

  const notes = el("textarea", {
    placeholder: "What is the rhythmic template? Which bands are occupied and " +
      "which are deliberately empty? What is the arrangement arc?",
  });

  return el("div", {},
    el("div.card", {},
      el("div.spread", {},
        el("h2", {}, file.name),
        el("div.row.tight", {},
          el("button", { onclick: () => { stop?.(); stop = A.play(audio); } }, "Play"),
          el("button.ghost", { onclick: () => { stop?.(); A.stopAll(); } }, "Stop"))),
      wave),

    el("div.card", {},
      el("h2", {}, "Feature bundle"),
      el("div.feature-list", {},
        feat("tempo", bpm ? `${bpm}` : "—",
             bpm ? `BPM — ${Math.round(bpm / 2)} and ${bpm * 2} are equally `
                   + `consistent with the signal; autocorrelation cannot tell `
                   + `which metrical level is the beat`
                 : "no stable pulse found"),
        feat("spectral centroid", `${f.centroid} Hz`, "the handle for 'brightness'"),
        feat("rolloff (85%)", `${f.rolloff85} Hz`),
        feat("spectral flux", f.flux, "rate of change"),
        feat("onset density", `${f.onsetDensity}/s`, "a better handle on 'busy' than tempo"),
        feat("length", `${f.seconds}s`),
        feat("RMS", f.rms),
        feat("peak", f.peak, f.peak > 0.99 ? "clipped or limited hard" : "")),
      el("h4", { style: { marginTop: ".8rem" } }, "Average spectrum, 24 log bands"),
      barRow(f.bands, ["20", "", "", "100", "", "", "500", "", "", "2k", "", "", "8k", "", "", "20k"]),
      el("p.fine", {}, "Gaps here are decisions. Two elements sharing one band " +
        "are the thing you cannot fix with a fader.")),

    el("div.card", {},
      el("h2", {}, "Spectrogram"),
      spec,
      el("p.fine", {}, "The window decides what you can see: this one trades " +
        "time resolution for frequency resolution, so transients smear " +
        "slightly and slot boundaries are crisp.")),

    el("div.card", {},
      el("h2", {}, "Your read"),
      notes,
      el("button.primary", {
        onclick: async () => {
          await api("/api/analyses", {
            method: "POST",
            body: { kind: "audio", name: file.name, features, notes: notes.value },
          });
          toast("Archived");
          ctx.go("analyze");
        },
      }, "Archive this analysis")));
}

// ------------------------------------------------------------------ drawing

function barRow(values, labels = []) {
  const max = Math.max(...values, 1e-9);
  return el("div", {},
    el("div.timeline", { style: { height: "60px" } },
      ...values.map((v) => el("i", {
        class: v <= 0 ? "none" : "",
        style: { height: `${Math.max(2, (v / max) * 100)}%` },
        title: v.toFixed(3),
      }))),
    labels.length ? el("div.row", { style: { justifyContent: "space-between" } },
      ...labels.map((l) => el("span.fine", {}, l))) : null);
}

function drawWaveform(g, data, w, h) {
  g.fillStyle = "#06080e";
  g.fillRect(0, 0, w, h);
  g.strokeStyle = "#6ee7c8";
  const step = Math.max(1, Math.floor(data.length / w));
  for (let x = 0; x < w; x++) {
    let lo = 1, hi = -1;
    for (let i = 0; i < step; i++) {
      const v = data[x * step + i] || 0;
      lo = Math.min(lo, v); hi = Math.max(hi, v);
    }
    g.beginPath();
    g.moveTo(x + 0.5, h / 2 - lo * h / 2);
    g.lineTo(x + 0.5, h / 2 - hi * h / 2);
    g.stroke();
  }
}

function drawSpectrogram(g, data, sr, w, h) {
  g.fillStyle = "#06080e";
  g.fillRect(0, 0, w, h);
  const win = 2048;
  const cols = Math.min(w, 400);
  const hop = Math.max(1, Math.floor((data.length - win) / cols));
  const img = g.createImageData(cols, h);
  const fmin = 30, fmax = Math.min(18000, sr / 2);
  for (let x = 0; x < cols; x++) {
    const mag = A.fftMag(data.subarray(x * hop, x * hop + win));
    for (let y = 0; y < h; y++) {
      const f = fmin * Math.pow(fmax / fmin, 1 - y / h);
      const bin = Math.min(mag.length - 1, Math.round((f / (sr / 2)) * mag.length));
      const db = 20 * Math.log10(mag[bin] + 1e-7);
      const v = Math.max(0, Math.min(1, (db + 90) / 80));
      const i = (y * cols + x) * 4;
      img.data[i] = Math.min(255, v * 340);
      img.data[i + 1] = Math.min(255, Math.max(0, v - 0.3) * 320);
      img.data[i + 2] = Math.min(255, Math.max(0, v - 0.65) * 460);
      img.data[i + 3] = 255;
    }
  }
  const tmp = I.makeCanvas(cols, h);
  I.ctx2d(tmp).putImageData(img, 0, 0);
  g.drawImage(tmp, 0, 0, w, h);
}

// ------------------------------------------------------------------ archive

async function archivePane(ctx) {
  const { analyses } = await api("/api/analyses");
  if (!analyses.length) return el("span");
  return el("div.card", {},
    el("h2", {}, "Archive", el("span.fine", {}, `${analyses.length}`)),
    el("p.fine", {}, "Five references you love, side by side, is where the " +
      "shared features start to show."),
    el("div.stack", {}, ...analyses.map((a) => {
      const open = el("div", { hidden: true });
      return el("div.card.tight", {},
        el("div.spread", {},
          el("div", {},
            el("b", {}, a.name || "(unnamed)"),
            el("span.tag " + (a.kind === "audio" ? "audio" : "visual"),
              { style: { marginLeft: ".4rem" } }, a.kind),
            el("span.fine", { style: { marginLeft: ".4rem" } }, relTime(a.created))),
          el("div.row.tight", {},
            el("button.ghost", {
              onclick: (e) => {
                open.hidden = !open.hidden;
                e.target.textContent = open.hidden ? "Open" : "Close";
                if (!open.hidden && !open.childElementCount) {
                  open.append(
                    a.notes && el("p.dim", { style: { whiteSpace: "pre-wrap" } }, a.notes),
                    el("div.feature-list", {}, ...featureChips(a.features)),
                    a.features.palette
                      ? el("div.swatches", { style: { marginTop: ".6rem" } },
                          ...a.features.palette.map((p) =>
                            el("div.swatch", { style: { background: p.hex }, title: p.hex })))
                      : null);
                }
              },
            }, "Open"),
            el("button.ghost.danger", {
              onclick: async () => {
                if (await confirmDialog("Delete this analysis?")) {
                  await api(`/api/analyses/${a.id}`, { method: "DELETE" });
                  ctx.go("analyze");
                }
              },
            }, "×"))),
        open);
    })));
}

function featureChips(f) {
  const keys = f.kind === "audio"
    ? [["bpm", "tempo"], ["centroid", "centroid Hz"], ["onsetDensity", "onsets/s"],
       ["rolloff85", "rolloff Hz"], ["seconds", "length s"]]
    : [["gridColumns", "columns"], ["edgeDensity", "edge density"],
       ["contrastSd", "contrast sd"], ["paletteEntropy", "palette entropy"],
       ["meanLum", "mean luminance"]];
  return keys
    .filter(([k]) => f[k] !== undefined)
    .map(([k, label]) => feat(label, f[k] ?? "—"));
}
