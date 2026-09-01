/* Recording, ported from lingua-portal's lib/recorder.js + lib/compose.js.
 * One file, two layers, exposed as window.LinguaCompose:
 *
 * - createRecorder: voice/video capture on MediaRecorder. Used by a
 *   teacher attaching a drill to a lesson, a student answering a speaking
 *   or video question, and (via `source`) the class recorder.
 * - composeCall: turns a live class — several video tiles and several
 *   microphones — into ONE stream a recorder can take. It records what
 *   THIS browser received: it draws incoming tracks onto a canvas and
 *   mixes incoming audio with WebAudio. Close the tab and it stops; a
 *   participant whose video never arrived is not in it; nothing uploads
 *   until stop. Central SFU-side recording is the alternative that needs
 *   infrastructure — this is the version that works with no server.
 *
 * The container is negotiated, not assumed: Safari cannot write webm and
 * an unsupported mimeType makes the MediaRecorder constructor throw, so
 * pickType asks the browser what it can actually produce.
 */
(function () {
  "use strict";

  const AUDIO_TYPES = ["audio/webm;codecs=opus", "audio/webm",
    "audio/ogg;codecs=opus", "audio/mp4", "audio/aac"];
  const VIDEO_TYPES = ["video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];

  function recSupported() {
    return typeof MediaRecorder !== "undefined" &&
      !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function pickType(kind) {
    const list = kind === "video" ? VIDEO_TYPES : AUDIO_TYPES;
    for (const t of list) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) {
        return t;
      }
    }
    return "";   // let the browser choose rather than forcing one it can't write
  }

  function createRecorder({ kind = "audio", onTick, onState, onError,
                            maxSeconds = 300, source = null }) {
    // `source` lets a caller record a stream it already has — the composed
    // view of a live class — instead of opening a fresh camera.
    let stream = null, rec = null, chunks = [], startedAt = 0, timer = null;
    let ownsStream = true;
    let blob = null, url = null, bytes = 0;

    const state = (s) => { try { onState && onState(s); } catch (e) {} };
    const fail = (e) => {
      try { onError && onError(String((e && e.message) || e)); } catch (x) {}
    };

    function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }

    function release() {
      stopTimer();
      // Only stop tracks we opened: stopping a borrowed stream's tracks
      // would kill the live call the moment the teacher stopped recording.
      if (stream && ownsStream) { for (const t of stream.getTracks()) t.stop(); }
      stream = null;
      rec = null;
    }

    return {
      kind,
      get stream() { return stream; },
      get blob() { return blob; },
      // Bytes that have actually arrived. A recorder producing nothing
      // looks identical to one that works — until you stop, which for a
      // class recording is 45 minutes too late.
      get bytes() { return bytes; },
      get url() { return url; },

      async start() {
        if (!recSupported()) {
          throw new Error("this browser cannot record"
            + " (needs https or localhost)");
        }
        this.discard();
        ownsStream = !source;
        stream = source || await navigator.mediaDevices.getUserMedia(
          kind === "video" ? { video: true, audio: true } : { audio: true });
        const mimeType = pickType(kind);
        rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        chunks = []; bytes = 0;
        rec.ondataavailable = (e) => {
          if (e.data && e.data.size) { chunks.push(e.data); bytes += e.data.size; }
        };
        rec.onerror = (e) => fail(e.error || e);
        rec.onstop = () => {
          blob = new Blob(chunks, { type: rec.mimeType
            || (kind === "video" ? "video/webm" : "audio/webm") });
          if (url) URL.revokeObjectURL(url);
          url = URL.createObjectURL(blob);
          release();
          state("recorded");
        };
        rec.start(250);            // timeslice: data arrives as we go
        startedAt = Date.now();
        state("recording");
        // 1s ticks, not 250ms: the timer only drives an mm:ss display and
        // every tick costs a re-render.
        let lastSecs = -1;
        timer = setInterval(() => {
          const secs = Math.floor((Date.now() - startedAt) / 1000);
          if (secs !== lastSecs) { lastSecs = secs; onTick && onTick(secs); }
          if (secs >= maxSeconds) this.stop();  // a forgotten tab must not fill a disk
        }, 1000);
        return stream;
      },

      // Resolves with the finished blob: MediaRecorder finalises
      // asynchronously, so reading .blob straight after stop() uploads a
      // truncated file. Awaiting the stop event is the only correct moment.
      stop() {
        stopTimer();
        if (!rec || rec.state === "inactive") {
          release(); state("idle"); return Promise.resolve(blob);
        }
        return new Promise((resolve) => {
          const prior = rec.onstop;
          rec.onstop = (e) => {
            try { prior && prior(e); } catch (x) { fail(x); }
            resolve(blob);
          };
          try { rec.stop(); } catch (e) { fail(e); resolve(null); }
        });
      },

      discard() {
        stopTimer();
        if (rec && rec.state !== "inactive") { try { rec.stop(); } catch (e) {} }
        release();
        if (url) { URL.revokeObjectURL(url); url = null; }
        blob = null; chunks = [];
        state("idle");
      },

      filename(stem = "recording") {
        const t = (blob && blob.type) || "";
        const ext = t.includes("mp4") ? (kind === "video" ? ".mp4" : ".m4a")
          : t.includes("ogg") ? ".ogg" : ".webm";
        return stem + ext;
      },

      seconds() {
        return startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0;
      },
    };
  }

  function fmtSecs(n) {
    const s = Math.max(0, Math.floor(n || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  /* ── the compositor ────────────────────────────────────────────────── */

  // Smallest square grid that fits everyone — except two people get 2x1:
  // a 1:1 lesson is the common case, and half a canvas of black is a poor
  // recording of it.
  function gridFor(n) {
    if (n <= 1) return [1, 1];
    if (n === 2) return [2, 1];
    const cols = Math.ceil(Math.sqrt(n));
    return [cols, Math.ceil(n / cols)];
  }

  // Letterbox rather than stretch: a stretched face is the single most
  // obvious sign of a homemade recorder.
  function fitRect(srcW, srcH, cellW, cellH) {
    if (!srcW || !srcH) return { x: 0, y: 0, w: cellW, h: cellH };
    const scale = Math.min(cellW / srcW, cellH / srcH);
    const w = Math.round(srcW * scale);
    const h = Math.round(srcH * scale);
    return { x: Math.round((cellW - w) / 2),
             y: Math.round((cellH - h) / 2), w, h };
  }

  function layout(n, width, height) {
    const [cols, rows] = gridFor(n);
    const cellW = Math.floor(width / cols);
    const cellH = Math.floor(height / rows);
    return Array.from({ length: n }, (_, i) => ({
      x: (i % cols) * cellW, y: Math.floor(i / cols) * cellH,
      w: cellW, h: cellH,
    }));
  }

  function composeSupported() {
    return typeof MediaRecorder !== "undefined" &&
      typeof document !== "undefined" &&
      !!document.createElement("canvas").captureStream;
  }

  // getStreams() is called on EVERY frame rather than captured once, so
  // somebody joining mid-class appears instead of leaving a frozen tile.
  function composeCall({ getStreams, width = 1280, height = 720, fps = 15 }) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");

    const videos = new Map();     // stream id -> detached <video> decoding it
    let raf = null, stopped = false, lastDraw = 0;
    const frameMs = 1000 / fps;

    function videoFor(stream) {
      let v = videos.get(stream.id);
      if (!v) {
        v = document.createElement("video");
        v.autoplay = true; v.muted = true; v.playsInline = true;
        v.srcObject = stream;
        v.play().catch(() => {});   // may reject before data arrives; fine
        videos.set(stream.id, v);
      }
      return v;
    }

    function draw(now) {
      if (stopped) return;
      raf = requestAnimationFrame(draw);
      if (now - lastDraw < frameMs) return;   // cap the work
      lastDraw = now;

      const streams = (getStreams() || [])
        .filter((s) => s && s.getVideoTracks().length);
      ctx.fillStyle = "#0b0e13";
      ctx.fillRect(0, 0, width, height);
      if (!streams.length) return;

      const cells = layout(streams.length, width, height);
      // Drop decoders we no longer need, or a long class accumulates them
      const live = new Set(streams.map((s) => s.id));
      for (const [id, v] of videos) {
        if (!live.has(id)) { v.srcObject = null; videos.delete(id); }
      }
      streams.forEach((stream, i) => {
        const v = videoFor(stream);
        const cell = cells[i];
        if (!v.videoWidth) return;       // not decoding yet: leave it dark
        const r = fitRect(v.videoWidth, v.videoHeight, cell.w, cell.h);
        try {
          ctx.drawImage(v, cell.x + r.x, cell.y + r.y, r.w, r.h);
        } catch (e) { /* not ready */ }
      });
    }

    // Every incoming audio track into one destination — a recording of a
    // conversation with only one side of it is not a recording of a class.
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audio = AudioCtx ? new AudioCtx() : null;
    const dest = audio ? audio.createMediaStreamDestination() : null;
    const wired = new Set();

    function wireAudio() {
      if (!audio) return;
      for (const stream of getStreams() || []) {
        if (!stream || wired.has(stream.id)
            || !stream.getAudioTracks().length) continue;
        try {
          audio.createMediaStreamSource(stream).connect(dest);
          wired.add(stream.id);
        } catch (e) { /* no audio, or already connected */ }
      }
    }

    const audioTimer = setInterval(wireAudio, 1000);  // latecomers mixed in
    wireAudio();
    raf = requestAnimationFrame(draw);

    const out = canvas.captureStream(fps);
    if (dest) for (const t of dest.stream.getAudioTracks()) out.addTrack(t);

    return {
      stream: out,
      get participants() { return (getStreams() || []).length; },
      stop() {
        stopped = true;
        if (raf) cancelAnimationFrame(raf);
        clearInterval(audioTimer);
        for (const [, v] of videos) v.srcObject = null;
        videos.clear();
        for (const t of out.getTracks()) t.stop();
        if (audio && audio.state !== "closed") audio.close().catch(() => {});
      },
    };
  }

  window.LinguaCompose = { createRecorder, pickType, fmtSecs,
                           recSupported, composeCall, composeSupported,
                           fitRect, layout };
})();
