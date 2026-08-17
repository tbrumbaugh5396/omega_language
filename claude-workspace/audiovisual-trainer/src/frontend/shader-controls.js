// Controls built from the descriptors shader-uniforms.js hands back.
//
// Kept apart from the parsing so the parsing stays testable without a DOM, and
// so both the Shader and Generate editors dress the same descriptors.

import { el } from "./ui.js";

const clamp01 = (v) => Math.min(1, Math.max(0, v));

export const toHex = (rgb) => "#" + rgb.slice(0, 3)
  .map((c) => Math.round(clamp01(c) * 255).toString(16).padStart(2, "0")).join("");

export const fromHex = (hex) => [1, 3, 5]
  .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);

/** A square you drag, for a vec2. Reads far better than two sliders. */
function xyPad(u, value, onChange) {
  const dot = el("div", { style: {
    position: "absolute", width: "12px", height: "12px", borderRadius: "50%",
    background: "var(--accent, #6ea8ff)", border: "2px solid #fff",
    transform: "translate(-50%, 50%)", pointerEvents: "none" } });
  const readout = el("b", {});
  const pad = el("div", {
    style: { position: "relative", width: "100%", aspectRatio: "1 / 1",
             maxWidth: "132px", background: "var(--bg-2, #10141f)",
             border: "1px solid var(--line, #2a3348)", borderRadius: "6px",
             cursor: "crosshair", touchAction: "none" } }, dot);

  const span = u.max - u.min;
  const place = () => {
    // y is measured from the bottom, matching the shader's coordinates rather
    // than the screen's.
    dot.style.left = `${((value[0] - u.min) / span) * 100}%`;
    dot.style.bottom = `${((value[1] - u.min) / span) * 100}%`;
    readout.textContent = `${value[0].toFixed(2)}, ${value[1].toFixed(2)}`;
  };
  const set = (e) => {
    const r = pad.getBoundingClientRect();
    value[0] = u.min + clamp01((e.clientX - r.left) / r.width) * span;
    value[1] = u.min + clamp01(1 - (e.clientY - r.top) / r.height) * span;
    place();
    onChange();
  };
  pad.addEventListener("pointerdown", (e) => {
    pad.setPointerCapture(e.pointerId);
    set(e);
  });
  pad.addEventListener("pointermove", (e) => {
    if (pad.hasPointerCapture(e.pointerId)) set(e);
  });
  place();
  return el("label.knob", {}, readout, u.label, pad);
}

function colourControl(u, value, onChange) {
  const swatch = el("input", {
    type: "color", value: toHex(value),
    style: { width: "100%", height: "30px", padding: "0", cursor: "pointer" },
    oninput: (e) => {
      const rgb = fromHex(e.target.value);
      for (let i = 0; i < 3; i++) value[i] = rgb[i];
      onChange();
    },
  });
  const rows = [el("label.knob", {}, u.label, swatch)];
  if (u.width === 4) {
    const out = el("b", {}, value[3].toFixed(2));
    rows.push(el("label.knob", {}, out, `${u.label} alpha`,
      el("input", { type: "range", min: 0, max: 1, step: 0.01, value: value[3],
        oninput: (e) => {
          value[3] = parseFloat(e.target.value);
          out.textContent = value[3].toFixed(2);
          onChange();
        } })));
  }
  return rows;
}

function toggleControl(u, value, onChange) {
  return el("label.knob", {}, u.label,
    el("input", { type: "checkbox", checked: value[0] > 0.5,
      style: { width: "auto", marginLeft: ".4rem" },
      oninput: (e) => { value[0] = e.target.checked ? 1 : 0; onChange(); } }));
}

function sliders(u, value, onChange) {
  const suffix = u.width === 1 ? [""] : ["x", "y", "z", "w"].slice(0, u.width);
  return suffix.map((s, i) => {
    const fmt = (v) => (u.isInt ? String(Math.round(v)) : v.toFixed(3));
    const out = el("b", {}, fmt(value[i]));
    // A scalar can carry the prose from its comment. Components cannot — four
    // sliders all captioned "x = scale, y = octaves" tells you nothing about
    // which one you are holding, so they get the name and the prose hovers.
    const caption = s ? `${u.name}.${s}` : u.label;
    return el("label.knob", { title: u.label }, out, caption,
      el("input", { type: "range", min: u.min, max: u.max, step: u.step, value: value[i],
        oninput: (e) => {
          value[i] = u.isInt ? Math.round(parseFloat(e.target.value)) : parseFloat(e.target.value);
          out.textContent = fmt(value[i]);
          onChange();
        } }));
  });
}

/** A picture or a video you choose. The value is {url, kind, w, h}; the bytes
    live in the studio's asset store, and the URL carries its own capability
    key. A video plays muted in a loop and is uploaded to the GPU every frame. */
function imageControl(u, values, onChange, onImage) {
  const cur = values[u.name];
  const isVid = cur && cur.kind === "video";
  const thumb = isVid
    ? el("video", { muted: true, loop: true, playsInline: true, autoplay: true,
        style: { width: "100%", maxHeight: "72px", objectFit: "cover", borderRadius: "6px",
                 display: "block", background: "var(--bg-2, #10141f)" }, src: cur.url })
    : el("img", { style: { width: "100%", maxHeight: "72px", objectFit: "cover",
        borderRadius: "6px", display: cur && cur.url ? "block" : "none",
        background: "var(--bg-2, #10141f)" }, src: cur && cur.url ? cur.url : "" });
  const note = el("span.fine", {},
    cur && cur.url ? `${isVid ? "video " : ""}${cur.w || "?"}×${cur.h || "?"}` : "no image yet");
  const file = el("input", { type: "file", accept: "image/*,video/*", style: { display: "none" },
    onchange: async (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f || !onImage) return;
      note.textContent = "uploading…";
      try {
        const v = await onImage(u, f);        // {url, kind, w, h}
        values[u.name] = v;
        note.textContent = `${v.kind === "video" ? "video " : ""}${v.w}×${v.h}`;
        onChange();
        // The thumbnail element's kind may have changed; the panel rebuilds
        // on the next run, so just show what we can now.
        if (thumb.tagName.toLowerCase() === (v.kind === "video" ? "video" : "img")) {
          thumb.src = v.url; thumb.style.display = "block";
        }
      } catch (err) { note.textContent = err.message || "upload failed"; }
      e.target.value = "";
    } });
  return el("label.knob", {}, u.label,
    el("div.row.tight", { style: { marginTop: ".2rem" } },
      el("button", { type: "button", onclick: () => file.click() }, "Choose image…"),
      cur && cur.url ? el("button.ghost", { type: "button", onclick: () => {
        values[u.name] = null; thumb.style.display = "none"; note.textContent = "no image"; onChange();
      } }, "Clear") : null,
      note),
    thumb, file);
}

/** Read the size of a picked file: an image's natural size or a video's frame. */
export function mediaDims(url, kind) {
  return new Promise((res) => {
    if (kind === "video") {
      const v = document.createElement("video");
      v.muted = true; v.preload = "metadata";
      v.onloadedmetadata = () => res([v.videoWidth, v.videoHeight]);
      v.onerror = () => res([0, 0]);
      v.src = url;
    } else {
      const im = new Image();
      im.onload = () => res([im.naturalWidth, im.naturalHeight]);
      im.onerror = () => res([0, 0]);
      im.src = url;
    }
  });
}

/**
 * Build the panel. `values` is the live store, keyed by uniform name — mutated
 * in place so the render loop reads current values without re-binding.
 * `onImage(u, file)` uploads a picked file and resolves to {url, w, h}.
 */
export function buildControls(uniforms, values, onChange, { onImage } = {}) {
  if (!uniforms.length) {
    return el("p.fine", {}, "No adjustable uniforms. Declare one — " +
      "`uniform float scale; // @range 1 40` — and a control appears here.");
  }
  const nodes = [];
  for (const u of uniforms) {
    if (u.control === "image") { nodes.push(imageControl(u, values, onChange, onImage)); continue; }
    // Keep the value across an edit when the shape still fits; a slider that
    // resets every time you touch the source is worse than no slider.
    const prev = values[u.name];
    const v = Array.isArray(prev) && prev.length === u.width
      ? prev.slice() : u.value.slice();
    values[u.name] = v;

    if (u.control === "pad") nodes.push(xyPad(u, v, onChange));
    else if (u.control === "color") nodes.push(...colourControl(u, v, onChange));
    else if (u.control === "toggle") nodes.push(toggleControl(u, v, onChange));
    else nodes.push(...sliders(u, v, onChange));
  }
  return el("div.knobs", {}, ...nodes);
}

/** Push the stored values at the live program. */
export function applyUniforms(gl, program, uniforms, values) {
  for (const u of uniforms) {
    if (u.control === "image") continue;     // bindTextures() owns these
    const loc = gl.getUniformLocation(program, u.name);
    if (!loc) continue;                      // optimised out; nothing to set
    const v = values[u.name] || u.value;
    if (u.type === "bool") gl.uniform1i(loc, v[0] > 0.5 ? 1 : 0);
    else if (u.type === "int") gl.uniform1i(loc, Math.round(v[0]));
    else if (u.type === "float") gl.uniform1f(loc, v[0]);
    else if (u.type === "vec2") gl.uniform2f(loc, v[0], v[1]);
    else if (u.type === "vec3") gl.uniform3f(loc, v[0], v[1], v[2]);
    else if (u.type === "vec4") gl.uniform4f(loc, v[0], v[1], v[2], v[3]);
  }
}

/**
 * Bind every sampler2D to its own texture unit, loading images on demand.
 * `cache` persists across frames and is emptied by releaseTextures(). Until
 * an image arrives, or when none is chosen, a 1×1 mid-grey stands in and the
 * size uniform reads (0, 0) — which is how a sketch tells there is no image.
 */
export function bindTextures(gl, program, uniforms, values, cache) {
  let unit = 0;
  if (!cache.blank) {
    cache.blank = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, cache.blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
                  new Uint8Array([128, 128, 128, 255]));
  }
  for (const u of uniforms) {
    if (u.control !== "image") continue;
    const loc = gl.getUniformLocation(program, u.name);
    const want = values[u.name] && values[u.name].url;
    let entry = cache[u.name];
    const kind = values[u.name] && values[u.name].kind === "video" ? "video" : "image";
    if (want && (!entry || entry.url !== want)) {
      if (entry) dropEntry(gl, entry);
      entry = cache[u.name] = { url: want, tex: null, w: 0, h: 0, kind };
      if (kind === "video") {
        // A video is uploaded every frame it has a new picture. Muted so it
        // may autoplay; looped so a texture never goes black.
        const vid = document.createElement("video");
        vid.muted = true; vid.loop = true; vid.playsInline = true; vid.preload = "auto";
        vid.oncanplay = () => {
          if (cache[u.name] !== entry) return;
          const tex = gl.createTexture();
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          entry.tex = tex; entry.w = vid.videoWidth; entry.h = vid.videoHeight;
          entry.lastTime = -1;
          if (values[u.name]) { values[u.name].w = entry.w; values[u.name].h = entry.h; }
          vid.play().catch(() => {});
        };
        vid.src = want;
        entry.video = vid;
      }
      const img = kind === "video" ? null : new Image();
      if (img) img.onload = () => {
        if (cache[u.name] !== entry) return;           // superseded while loading
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);
        // Flip so uv (0,0) is the bottom-left, matching gl_FragCoord. NPOT
        // images are fine in WebGL1 as long as they clamp and skip mipmaps.
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        entry.tex = tex; entry.w = img.naturalWidth; entry.h = img.naturalHeight;
        // Remember the size on the value, so the panel can show it next time.
        if (values[u.name]) { values[u.name].w = entry.w; values[u.name].h = entry.h; }
      };
      if (img) img.src = want;
    } else if (!want && entry) {
      dropEntry(gl, entry);
      entry = cache[u.name] = null;
    }
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, entry && entry.tex ? entry.tex : cache.blank);
    if (entry && entry.tex && entry.video && entry.video.readyState >= 2
        && entry.video.currentTime !== entry.lastTime) {
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, entry.video);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      entry.lastTime = entry.video.currentTime;
    }
    if (loc) gl.uniform1i(loc, unit);
    const sizeLoc = gl.getUniformLocation(program, u.sizeUniform);
    if (sizeLoc) gl.uniform2f(sizeLoc, entry && entry.tex ? entry.w : 0, entry && entry.tex ? entry.h : 0);
    unit++;
  }
  gl.activeTexture(gl.TEXTURE0);
}

function dropEntry(gl, e) {
  if (e.tex) gl.deleteTexture(e.tex);
  if (e.video) { e.video.pause(); e.video.removeAttribute("src"); e.video.load(); }
}

export function releaseTextures(gl, cache) {
  for (const k of Object.keys(cache)) {
    const e = cache[k];
    if (k === "blank" && e) gl.deleteTexture(e);
    else if (e) dropEntry(gl, e);
    delete cache[k];
  }
}

/** For an offline render: put every video texture at time t (looping) and
    wait until it has that frame, so the export is deterministic. */
export async function seekVideos(cache, t) {
  const waits = [];
  for (const k of Object.keys(cache)) {
    const e = cache[k];
    if (!e || !e.video || !e.video.duration) continue;
    const v = e.video;
    v.pause();
    const target = t % v.duration;
    if (Math.abs(v.currentTime - target) < 0.001) continue;
    waits.push(new Promise((res) => {
      const done = () => { v.removeEventListener("seeked", done); res(); };
      v.addEventListener("seeked", done);
      v.currentTime = target;
      setTimeout(done, 400);                       // never hang an export on a seek
    }));
    e.lastTime = -1;                               // force the upload
  }
  await Promise.all(waits);
}

/** After an offline render: let the videos play again. */
export function resumeVideos(cache) {
  for (const k of Object.keys(cache)) {
    const e = cache[k];
    if (e && e.video) e.video.play().catch(() => {});
  }
}

/** New values for everything the Randomise button should move. Colours stay
    inside a pleasant band rather than going anywhere in the cube. */
export function randomise(uniforms, values) {
  for (const u of uniforms) {
    if (u.control === "image") continue;
    const v = values[u.name] || (values[u.name] = u.value.slice());
    if (u.control === "color") {
      const h = Math.random(), s = 0.35 + Math.random() * 0.45, l = 0.35 + Math.random() * 0.4;
      const rgb = hsl(h, s, l);
      for (let i = 0; i < Math.min(3, u.width); i++) v[i] = rgb[i];
    } else if (u.control === "toggle") {
      v[0] = Math.random() < 0.5 ? 0 : 1;
    } else {
      for (let i = 0; i < u.width; i++) {
        const r = u.min + Math.random() * (u.max - u.min);
        v[i] = u.isInt ? Math.round(r) : r;
      }
    }
  }
}

function hsl(h, s, l) {
  const f = (n) => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    return l - a * Math.max(-1, Math.min(Math.min(k - 3, 9 - k), 1));
  };
  return [f(0), f(8), f(4)];
}
