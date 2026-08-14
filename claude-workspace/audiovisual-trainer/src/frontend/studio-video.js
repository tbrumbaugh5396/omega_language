// The video editor: a sequential timeline of clips, stills and titles, with
// per-clip grading, dissolves, an audio track, and export by recording the
// composed canvas.
//
// Grading uses the canvas `filter` property rather than engine-image. That is
// a deliberate departure: the pixel-level code elsewhere in this app exists to
// teach the mechanism, but a 30fps preview cannot afford a per-frame JS pass
// over half a million pixels, and a grade you cannot scrub against is not a
// grade you can judge.

import { el, clear, append, toast, modal, closeModal, knob, confirmDialog,
         clamp } from "./ui.js";
import { aiButton } from "./ai.js";

const PREVIEW_MAX = 960;

const DEFAULT_GRADE = { brightness: 1, contrast: 1, saturate: 1, hue: 0, blur: 0 };

export async function videoEditor(host) {
  const doc = host.data;
  doc.clips ||= [];
  doc.audio ||= [];

  const W = doc.width, H = doc.height;
  const pw = Math.min(PREVIEW_MAX, W);
  const ph = Math.round((pw * H) / W);

  const media = new Map();       // clipId -> HTMLVideoElement | HTMLImageElement
  let playing = false, playhead = 0, rafId = null, lastFrameTime = 0;

  const clipDur = (c) => Math.max(0.1, (c.out ?? c.dur) - (c.in ?? 0));
  const timeline = () => {
    let t = 0;
    return doc.clips.map((c) => {
      const entry = { clip: c, start: t, dur: clipDur(c) };
      t += entry.dur - (c.transition === "dissolve" ? Math.min(c.transDur || 0.5, entry.dur / 2) : 0);
      return entry;
    });
  };
  const totalDur = () => {
    const t = timeline();
    if (!t.length) return 0;
    const last = t[t.length - 1];
    return last.start + last.dur;
  };

  // ---------------------------------------------------------------- media

  async function ensureMedia(clip) {
    if (media.has(clip.id)) return media.get(clip.id);
    const asset = host.assets.find((a) => a.id === clip.assetId);
    if (!asset) return null;
    if (clip.kind === "video") {
      const v = document.createElement("video");
      v.src = asset.url;
      v.crossOrigin = "anonymous";
      v.preload = "auto";
      v.muted = !clip.audioOn;
      await new Promise((res) => {
        v.onloadedmetadata = res;
        v.onerror = res;
      });
      media.set(clip.id, v);
      return v;
    }
    const img = new Image();
    img.src = asset.url;
    await new Promise((res) => { img.onload = res; img.onerror = res; });
    media.set(clip.id, img);
    return img;
  }

  // ---------------------------------------------------------------- preview

  const canvas = el("canvas", { width: pw, height: ph,
    style: { width: "100%", height: "auto", background: "#000", borderRadius: "8px", display: "block" } });
  const cg = canvas.getContext("2d");

  function filterFor(clip) {
    const g = { ...DEFAULT_GRADE, ...(clip.grade || {}) };
    return `brightness(${g.brightness}) contrast(${g.contrast}) ` +
           `saturate(${g.saturate}) hue-rotate(${g.hue}deg)` +
           (g.blur ? ` blur(${g.blur}px)` : "");
  }

  function drawSource(entry, localTime, alpha) {
    const clip = entry.clip;
    cg.save();
    cg.globalAlpha = alpha;
    cg.filter = filterFor(clip);
    if (clip.kind === "title") {
      cg.fillStyle = clip.bg || "#000000";
      cg.fillRect(0, 0, pw, ph);
      cg.fillStyle = clip.color || "#ffffff";
      cg.textAlign = "center";
      cg.textBaseline = "middle";
      const size = Math.round((clip.size || 64) * (pw / W));
      cg.font = `600 ${size}px system-ui, sans-serif`;
      const lines = String(clip.text || "").split("\n");
      lines.forEach((line, i) => {
        cg.fillText(line, pw / 2, ph / 2 + (i - (lines.length - 1) / 2) * size * 1.2);
      });
    } else {
      const m = media.get(clip.id);
      if (m) {
        // Fit inside the frame, letterboxed — never silently crop the shot.
        const mw = m.videoWidth || m.width, mh = m.videoHeight || m.height;
        if (mw && mh) {
          const s = Math.min(pw / mw, ph / mh);
          cg.drawImage(m, (pw - mw * s) / 2, (ph - mh * s) / 2, mw * s, mh * s);
        }
      }
    }
    cg.restore();
  }

  function renderAt(t) {
    cg.save();
    cg.filter = "none";
    cg.globalAlpha = 1;
    cg.fillStyle = "#000";
    cg.fillRect(0, 0, pw, ph);
    cg.restore();

    const tl = timeline();
    for (let i = 0; i < tl.length; i++) {
      const e = tl[i];
      if (t < e.start || t > e.start + e.dur) continue;
      const local = t - e.start;
      let alpha = 1;
      // A dissolve is the previous clip still on screen underneath.
      const trans = e.clip.transition === "dissolve"
        ? Math.min(e.clip.transDur || 0.5, e.dur / 2) : 0;
      if (trans && local < trans && i > 0) alpha = local / trans;
      drawSource(e, local, alpha);
    }
  }

  async function seekTo(t) {
    playhead = clamp(t, 0, Math.max(0, totalDur()));
    const tl = timeline();
    for (const e of tl) {
      if (e.clip.kind !== "video") continue;
      const m = media.get(e.clip.id);
      if (!m) continue;
      const inside = playhead >= e.start && playhead <= e.start + e.dur;
      if (inside) {
        const want = (e.clip.in || 0) + (playhead - e.start);
        if (Math.abs(m.currentTime - want) > 0.15) m.currentTime = want;
      } else if (!m.paused) m.pause();
    }
    renderAt(playhead);
    drawRuler();
  }

  function tick(ts) {
    if (!playing) return;
    const dt = lastFrameTime ? (ts - lastFrameTime) / 1000 : 0;
    lastFrameTime = ts;
    playhead += dt;
    const end = totalDur();
    if (playhead >= end) { stop(); seekTo(0); return; }

    const tl = timeline();
    for (const e of tl) {
      if (e.clip.kind !== "video") continue;
      const m = media.get(e.clip.id);
      if (!m) continue;
      const inside = playhead >= e.start && playhead <= e.start + e.dur;
      if (inside && m.paused) {
        m.currentTime = (e.clip.in || 0) + (playhead - e.start);
        m.play().catch(() => {});
      } else if (!inside && !m.paused) m.pause();
    }
    renderAt(playhead);
    drawRuler();
    rafId = requestAnimationFrame(tick);
  }

  async function play() {
    if (!doc.clips.length) { toast("Import something first"); return; }
    playing = true;
    lastFrameTime = 0;
    playBtn.textContent = "Pause";
    rafId = requestAnimationFrame(tick);
  }
  function stop() {
    playing = false;
    cancelAnimationFrame(rafId);
    playBtn.textContent = "Play";
    for (const m of media.values()) if (m.pause) m.pause();
  }

  // ---------------------------------------------------------------- timeline UI

  const ruler = el("canvas", { height: 74, style: { width: "100%", height: "74px", display: "block", cursor: "pointer" } });
  const rg = ruler.getContext("2d");

  function drawRuler() {
    const wCss = ruler.clientWidth || 700;
    if (ruler.width !== wCss) ruler.width = wCss;
    const dur = Math.max(1, totalDur());
    rg.fillStyle = "#0b0e16";
    rg.fillRect(0, 0, ruler.width, ruler.height);

    const tl = timeline();
    tl.forEach((e, i) => {
      const x = (e.start / dur) * ruler.width;
      const w = (e.dur / dur) * ruler.width;
      const selected = doc.clips[selected_i] === e.clip;
      rg.fillStyle = e.clip.kind === "title" ? "#3b3560"
        : e.clip.kind === "image" ? "#274d3f" : "#2c4a63";
      rg.fillRect(x + 1, 16, Math.max(2, w - 2), 40);
      if (selected) {
        rg.strokeStyle = "#7c9cff";
        rg.lineWidth = 2;
        rg.strokeRect(x + 1, 16, Math.max(2, w - 2), 40);
      }
      rg.fillStyle = "#e8ebf5";
      rg.font = "10px system-ui";
      const label = e.clip.name || e.clip.kind;
      rg.fillText(label.slice(0, Math.max(1, Math.floor(w / 6))), x + 5, 34);
      rg.fillStyle = "#a8b0c8";
      rg.fillText(`${e.dur.toFixed(1)}s`, x + 5, 50);
      if (e.clip.transition === "dissolve" && i > 0) {
        rg.fillStyle = "rgba(240,163,94,.8)";
        rg.fillRect(x, 16, 3, 40);
      }
    });

    rg.fillStyle = "#3a4260";
    rg.fillRect(0, 60, ruler.width, 1);
    for (let s = 0; s <= dur; s += Math.max(1, Math.round(dur / 10))) {
      const x = (s / dur) * ruler.width;
      rg.fillStyle = "#6e7794";
      rg.font = "9px ui-monospace, monospace";
      rg.fillText(`${s}s`, x + 2, 70);
      rg.fillRect(x, 60, 1, 6);
    }
    const px = (playhead / dur) * ruler.width;
    rg.fillStyle = "#6ee7c8";
    rg.fillRect(px, 8, 2, 56);
  }

  ruler.addEventListener("pointerdown", (e) => {
    const r = ruler.getBoundingClientRect();
    const frac = (e.clientX - r.left) / r.width;
    const t = frac * Math.max(1, totalDur());
    const tl = timeline();
    const hit = tl.findIndex((x) => t >= x.start && t <= x.start + x.dur);
    if (hit >= 0 && e.clientY - r.top < 60) {
      selected_i = doc.clips.indexOf(tl[hit].clip);
      renderInspector();
    }
    seekTo(t);
  });

  let selected_i = 0;

  // ---------------------------------------------------------------- inspector

  const inspector = el("div.stack");
  function renderInspector() {
    clear(inspector);
    const clip = doc.clips[selected_i];
    if (!clip) {
      inspector.append(el("p.fine", {}, "Import a clip, or add a title."));
      drawRuler();
      return;
    }
    const g = { ...DEFAULT_GRADE, ...(clip.grade || {}) };
    clip.grade = g;

    append(inspector,
      el("div.spread", {},
        el("b", {}, clip.name || clip.kind),
        el("div.row.tight", {},
          el("button.ghost", { onclick: () => moveClip(-1) }, "‹"),
          el("button.ghost", { onclick: () => moveClip(1) }, "›"),
          el("button.ghost.danger", { onclick: removeClip }, "×"))),
      el("div.row.tight", {},
        el("span.tag", {}, clip.kind),
        clip.kind === "video" ? el("label.row.tight", { style: { marginBottom: 0, fontSize: ".75rem" } },
          el("input", { type: "checkbox", checked: !!clip.audioOn, style: { width: "auto" },
            onchange: (e) => { clip.audioOn = e.target.checked;
              const m = media.get(clip.id); if (m) m.muted = !clip.audioOn; host.save(); } }),
          "keep audio") : null));

    if (clip.kind === "title") {
      const text = el("textarea", { value: clip.text || "", placeholder: "title text",
        oninput: (e) => { clip.text = e.target.value; renderAt(playhead); host.save(); } });
      append(inspector, el("label", {}, "Text", text),
        el("div.row.tight", {},
          el("label", {}, "Colour", el("input", { type: "color", value: clip.color || "#ffffff",
            oninput: (e) => { clip.color = e.target.value; renderAt(playhead); host.save(); } })),
          el("label", {}, "Background", el("input", { type: "color", value: clip.bg || "#000000",
            oninput: (e) => { clip.bg = e.target.value; renderAt(playhead); host.save(); } }))),
        knob("size", { min: 16, max: 240, step: 1, value: clip.size || 64,
          format: (v) => v.toFixed(0),
          oninput: (v) => { clip.size = v; renderAt(playhead); host.save(); } }));
    }

    append(inspector,
      knob("duration", { min: 0.2, max: 30, step: 0.1, value: clipDur(clip),
        format: (v) => `${v.toFixed(1)}s`,
        oninput: (v) => { clip.out = (clip.in || 0) + v; drawRuler(); host.save(); } }),
      clip.kind === "video"
        ? knob("in point", { min: 0, max: Math.max(0.1, clip.dur || 10), step: 0.1,
            value: clip.in || 0, format: (v) => `${v.toFixed(1)}s`,
            oninput: (v) => { clip.in = v; seekTo(playhead); host.save(); } })
        : null,
      el("label", {}, "Transition in",
        el("select", {
          onchange: (e) => { clip.transition = e.target.value; drawRuler(); host.save(); },
        }, ...[["none", "Cut"], ["dissolve", "Dissolve"]].map(([v, l]) =>
          el("option", { value: v, selected: v === (clip.transition || "none") }, l)))),
      el("h4", { style: { marginTop: ".5rem" } }, "Grade"),
      knob("brightness", { min: 0.2, max: 2, step: 0.01, value: g.brightness,
        format: (v) => v.toFixed(2), oninput: (v) => { g.brightness = v; renderAt(playhead); host.save(); } }),
      knob("contrast", { min: 0.2, max: 2.5, step: 0.01, value: g.contrast,
        format: (v) => v.toFixed(2), oninput: (v) => { g.contrast = v; renderAt(playhead); host.save(); } }),
      knob("saturation", { min: 0, max: 2.5, step: 0.01, value: g.saturate,
        format: (v) => v.toFixed(2), oninput: (v) => { g.saturate = v; renderAt(playhead); host.save(); } }),
      knob("hue", { min: -180, max: 180, step: 1, value: g.hue,
        format: (v) => `${v.toFixed(0)}°`, oninput: (v) => { g.hue = v; renderAt(playhead); host.save(); } }),
      knob("blur", { min: 0, max: 20, step: 0.5, value: g.blur,
        format: (v) => v.toFixed(1), oninput: (v) => { g.blur = v; renderAt(playhead); host.save(); } }),
      el("div.row.tight", {},
        el("button.ghost", {
          onclick: () => { clip.grade = { ...DEFAULT_GRADE }; renderInspector(); renderAt(playhead); host.save(); },
        }, "Reset grade"),
        el("button.ghost", {
          onclick: () => {
            for (const c of doc.clips) c.grade = { ...clip.grade };
            toast("Grade copied to every clip — this is what unifies them");
            renderAt(playhead); host.save();
          },
        }, "Apply to all")));
    drawRuler();
  }

  function moveClip(dir) {
    const j = selected_i + dir;
    if (j < 0 || j >= doc.clips.length) return;
    [doc.clips[selected_i], doc.clips[j]] = [doc.clips[j], doc.clips[selected_i]];
    selected_i = j;
    renderInspector(); seekTo(playhead); host.save();
  }
  async function removeClip() {
    const clip = doc.clips[selected_i];
    if (!clip) return;
    if (!(await confirmDialog(`Remove "${clip.name || clip.kind}"?`))) return;
    media.delete(clip.id);
    doc.clips.splice(selected_i, 1);
    selected_i = Math.max(0, selected_i - 1);
    renderInspector(); seekTo(0); host.save();
  }

  // ---------------------------------------------------------------- import

  const nextId = () => Math.max(0, ...doc.clips.map((c) => c.id)) + 1;

  const fileInput = el("input", {
    type: "file", accept: "video/*,image/*", multiple: true, hidden: true,
    onchange: async (e) => {
      for (const file of [...e.target.files]) {
        try {
          const isVideo = file.type.startsWith("video");
          let meta = {};
          if (isVideo) {
            meta = await probeVideo(file);
          }
          toast(`Importing ${file.name}…`);
          const asset = await host.upload(file, meta);
          const clip = {
            id: nextId(),
            assetId: asset.id,
            name: file.name.slice(0, 22),
            kind: isVideo ? "video" : "image",
            in: 0,
            out: isVideo ? Math.min(meta.duration || 5, 10) : 4,
            dur: isVideo ? (meta.duration || 5) : 4,
            transition: "none",
            transDur: 0.5,
            audioOn: isVideo,
            grade: { ...DEFAULT_GRADE },
          };
          doc.clips.push(clip);
          await ensureMedia(clip);
          selected_i = doc.clips.length - 1;
        } catch (err) {
          toast(`${file.name}: ${err.message}`);
        }
      }
      renderInspector();
      seekTo(playhead);
      host.save(thumbnail());
      e.target.value = "";
    },
  });

  function probeVideo(file) {
    return new Promise((res) => {
      const v = document.createElement("video");
      v.preload = "metadata";
      v.onloadedmetadata = () => {
        res({ duration: v.duration, width: v.videoWidth, height: v.videoHeight });
        URL.revokeObjectURL(v.src);
      };
      v.onerror = () => res({});
      v.src = URL.createObjectURL(file);
    });
  }

  function addTitle() {
    const clip = {
      id: nextId(), kind: "title", name: "Title", text: "Title",
      in: 0, out: 3, dur: 3, transition: "none", transDur: 0.5,
      color: "#ffffff", bg: "#000000", size: 72, grade: { ...DEFAULT_GRADE },
    };
    doc.clips.push(clip);
    selected_i = doc.clips.length - 1;
    renderInspector(); seekTo(playhead); host.save();
  }

  function thumbnail() {
    const t = document.createElement("canvas");
    t.width = 240; t.height = Math.round((240 * ph) / pw);
    t.getContext("2d").drawImage(canvas, 0, 0, t.width, t.height);
    return t.toDataURL("image/jpeg", 0.7);
  }

  // ---------------------------------------------------------------- export

  async function exportVideo() {
    if (!doc.clips.length) { toast("Nothing on the timeline"); return; }
    if (!window.MediaRecorder) { toast("This browser has no MediaRecorder"); return; }

    const dur = totalDur();
    const stream = canvas.captureStream(doc.fps || 30);

    // Route any clip audio into the recording. Each element can only have one
    // MediaElementSource for the lifetime of the page, so they are cached.
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const dest = ac.createMediaStreamDestination();
      let any = false;
      for (const clip of doc.clips) {
        if (clip.kind !== "video" || !clip.audioOn) continue;
        const m = media.get(clip.id);
        if (!m) continue;
        if (!m._srcNode) m._srcNode = ac.createMediaElementSource(m);
        m._srcNode.connect(dest);
        m._srcNode.connect(ac.destination);
        any = true;
      }
      if (any) for (const tr of dest.stream.getAudioTracks()) stream.addTrack(tr);
    } catch (e) {
      toast(`Audio could not be captured: ${e.message}. Recording picture only.`);
    }

    const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]
      .find((m) => MediaRecorder.isTypeSupported(m)) || "video/webm";
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8_000_000 });
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

    const done = new Promise((res) => { rec.onstop = res; });
    const status = el("p.dim", {}, "Recording in real time…");
    const bar = el("div.bar", {}, el("i", { style: { width: "0%" } }));
    modal(el("h2", {}, "Exporting"),
      el("p.fine", {}, `The timeline is recorded as it plays, so this takes ` +
        `about ${dur.toFixed(0)} seconds. Leave this tab in front — a ` +
        `backgrounded tab throttles animation and drops frames.`),
      status, bar);

    await seekTo(0);
    rec.start();
    await play();
    await new Promise((res) => {
      const check = setInterval(() => {
        bar.firstChild.style.width = `${Math.min(100, (playhead / dur) * 100)}%`;
        if (!playing || playhead >= dur) { clearInterval(check); res(); }
      }, 120);
    });
    rec.stop();
    await done;
    stop();

    const blob = new Blob(chunks, { type: mime });
    closeModal();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${host.doc.name || "cut"}.webm`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Exported ${(blob.size / 1e6).toFixed(1)} MB`);
  }

  // ---------------------------------------------------------------- layout

  const playBtn = el("button.primary", {
    onclick: () => (playing ? stop() : play()),
  }, "Play");

  const root = el("div.stack", {},
    el("div.card.tight", {},
      el("div.row.tight", {},
        playBtn,
        el("button", { onclick: () => seekTo(0) }, "⏮"),
        el("button", { onclick: () => fileInput.click() }, "Import video / stills"),
        el("button", { onclick: addTitle }, "+ Title"),
        el("button", { onclick: exportVideo }, "Export"),
        fileInput,
        aiButton("Shot list…", {
          task: "brief",
          describe: "Turns an idea into a shot list you can shoot against. It " +
            "writes the plan; the cutting is yours.",
          placeholder: "e.g. 10-second spot, one product, gamelan-ish rhythm, " +
            "must survive muted playback",
          onResult: (res) => {
            modal(el("h2", {}, "Shot list"),
              el("p.dim", { style: { whiteSpace: "pre-wrap" } }, res.text),
              el("div.row", { style: { justifyContent: "flex-end" } },
                el("button.primary", { onclick: closeModal }, "Close")));
          },
        }))),

    el("div.lab-split", { style: { gridTemplateColumns: "minmax(0,1fr) 300px" } },
      el("div.stack", {},
        canvas,
        el("div.card.tight", {}, ruler)),
      el("div.card.tight", {},
        el("h4", {}, "Clip"),
        inspector)));

  for (const clip of doc.clips) await ensureMedia(clip);
  renderInspector();
  await seekTo(0);
  setTimeout(drawRuler, 60);
  return root;
}
