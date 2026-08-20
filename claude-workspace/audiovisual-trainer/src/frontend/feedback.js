// Feedback buffers: a shader that can read what it drew last frame.
//
// That one capability is what turns a picture into a simulation. Reaction
// diffusion, the wave equation, Life, ink carried in a flow — each is a
// rule from the last frame to the next, and needs somewhere to keep the
// last frame at more precision than eight bits.
//
// Two textures ping-pong: the pass reads one and writes the other, then they
// swap. WebGL1 offers float rendering only through extensions, so the storage
// is negotiated — float, then half float, then plain bytes — and reported,
// because a sim written for float looks wrong in bytes and you should know.

/** One texture of the given kind, filtered and clamped, ready to attach. */
function makeTex(gl, w, h, kind, exts) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  if (exts.gl2) {
    // WebGL2 names its formats: a sized internal format, and HALF_FLOAT is a
    // core constant rather than an extension's. Rendering to either still
    // needs EXT_color_buffer_float, which the constructor asked for.
    const internal = kind === "float" ? gl.RGBA32F : kind === "half" ? gl.RGBA16F : gl.RGBA8;
    const type = kind === "float" ? gl.FLOAT : kind === "half" ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE;
    gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, gl.RGBA, type, null);
  } else {
    const type = kind === "float" ? gl.FLOAT
               : kind === "half" ? exts.half.HALF_FLOAT_OES
               : gl.UNSIGNED_BYTE;
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, type, null);
  }
  // Linear filtering of float textures is its own extension. Without it a
  // sim can still run at NEAREST; only smooth sampling of the state suffers.
  const linear = kind === "byte"
    || (kind === "float" && exts.floatLinear)
    || (kind === "half" && exts.halfLinear);
  const filt = linear ? gl.LINEAR : gl.NEAREST;
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filt);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filt);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return { tex, linear };
}

/**
 * A render target of the given kind, with `channels` colour attachments.
 *
 * Two attachments is what lets one sim keep two fields — velocity and the dye
 * being carried through it — instead of packing both into one RGBA. It needs
 * MRT, which WebGL2 has as standard; asking for two on WebGL1 fails here and
 * the caller falls back to one.
 */
function tryTarget(gl, w, h, kind, exts, channels = 1) {
  if (channels > 1 && !exts.gl2) return null;
  const parts = [];
  for (let i = 0; i < channels; i++) parts.push(makeTex(gl, w, h, kind, exts));
  const fbo = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  parts.forEach((p, i) => gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0 + i, gl.TEXTURE_2D, p.tex, 0));
  if (channels > 1) gl.drawBuffers(parts.map((_, i) => gl.COLOR_ATTACHMENT0 + i));
  const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE
    && gl.getError() === gl.NO_ERROR;
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.bindTexture(gl.TEXTURE_2D, null);
  if (!ok) { for (const p of parts) gl.deleteTexture(p.tex); gl.deleteFramebuffer(fbo); return null; }
  return { tex: parts[0].tex, tex2: parts[1] ? parts[1].tex : null, texes: parts.map((p) => p.tex),
           fbo, kind, linear: parts[0].linear, channels };
}

export class Feedback {
  constructor(gl) {
    this.gl = gl;
    const gl2 = typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext;
    this.exts = gl2 ? {
      gl2: true,
      // Float textures are core in WebGL2; rendering *to* them is not.
      float: gl.getExtension("EXT_color_buffer_float"),
      floatLinear: gl.getExtension("OES_texture_float_linear"),
      half: gl.getExtension("EXT_color_buffer_float") || gl.getExtension("EXT_color_buffer_half_float"),
      halfLinear: true,                       // half-float filtering is core in WebGL2
    } : {
      gl2: false,
      float: gl.getExtension("OES_texture_float"),
      floatLinear: gl.getExtension("OES_texture_float_linear"),
      half: gl.getExtension("OES_texture_half_float"),
      halfLinear: gl.getExtension("OES_texture_half_float_linear"),
    };
    // Some GPUs will render to float; some only to half; some to neither.
    // Decided once by actually trying, not by reading extension names.
    this.kind = null;
    this.channels = 1;
    this.a = null; this.b = null;         // the ping-pong pair (state)
    this.prevTex = null;                  // last displayed frame, for the no-sim path
    this.w = 0; this.h = 0;
    this.frame = 0;
  }

  /**
   * (Re)build storage at a size, with one or two channels. Also resets the
   * simulation — changing what the state *is* invalidates what it held.
   */
  resize(w, h, channels = 1) {
    const want = Math.max(1, Math.min(2, channels | 0));
    if (w === this.w && h === this.h && this.a && this.channels === want) return;
    this.release();
    this.w = w; this.h = h; this.channels = want;
    const gl = this.gl;
    const order = [];
    if (this.exts.float) order.push("float");
    if (this.exts.half) order.push("half");
    order.push("byte");
    for (const kind of order) {
      const a = tryTarget(gl, w, h, kind, this.exts, want);
      if (!a) continue;
      const b = tryTarget(gl, w, h, kind, this.exts, want);
      if (!b) { for (const t of a.texes) gl.deleteTexture(t); gl.deleteFramebuffer(a.fbo); continue; }
      this.a = a; this.b = b; this.kind = kind;
      break;
    }
    // Two channels asked for and refused: run with one and say so.
    if (!this.a && want > 1) {
      this.channels = 1;
      for (const kind of order) {
        const a = tryTarget(gl, w, h, kind, this.exts, 1);
        if (!a) continue;
        const b = tryTarget(gl, w, h, kind, this.exts, 1);
        if (!b) { for (const t of a.texes) gl.deleteTexture(t); gl.deleteFramebuffer(a.fbo); continue; }
        this.a = a; this.b = b; this.kind = kind;
        break;
      }
    }
    // The previous displayed frame is always bytes: it is a copy of the canvas.
    this.prevTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.prevTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindTexture(gl.TEXTURE_2D, null);
    this.reset();
  }

  /** Clear both state buffers and the frame count. */
  reset() {
    const gl = this.gl;
    this.frame = 0;
    for (const t of [this.a, this.b]) {
      if (!t) continue;
      gl.bindFramebuffer(gl.FRAMEBUFFER, t.fbo);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (this.prevTex) {
      gl.bindTexture(gl.TEXTURE_2D, this.prevTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, this.w, this.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.bindTexture(gl.TEXTURE_2D, null);
    }
  }

  /** The state written last: read this. */
  get read() { return this.a; }
  /** The state to write next. */
  get write() { return this.b; }
  swap() { const t = this.a; this.a = this.b; this.b = t; this.frame++; }

  /** After drawing to the canvas: keep a copy as last frame. */
  captureCanvas() {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.prevTex);
    gl.copyTexSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 0, 0, this.w, this.h);
    gl.bindTexture(gl.TEXTURE_2D, null);
  }

  release() {
    const gl = this.gl;
    for (const t of [this.a, this.b]) {
      if (t) { for (const tex of t.texes || [t.tex]) gl.deleteTexture(tex); gl.deleteFramebuffer(t.fbo); }
    }
    if (this.prevTex) gl.deleteTexture(this.prevTex);
    this.a = this.b = this.prevTex = null;
  }

  /** A word for the panel. */
  /**
   * How many bytes of GPU storage this is holding.
   *
   * The ping-pong pair, each with as many targets as the sketch asked for,
   * plus the byte copy of the last displayed frame. Worth being able to state
   * rather than estimate: a float state pair with two targets at 1920×1080 is
   * 132 MB, and the same state at 448 square is 13 MB and holds the same
   * world — which is the whole argument for letting a sketch say `@state`.
   */
  bytes() {
    const per = this.kind === "float" ? 16 : this.kind === "half" ? 8 : 4;
    const state = 2 * this.channels * this.w * this.h * per;
    return state + (this.prevTex ? this.w * this.h * 4 : 0);
  }

  describe() {
    if (!this.kind) return "no feedback storage";
    const api = this.exts.gl2 ? "WebGL2" : "WebGL1";
    const ch = this.channels > 1 ? " · two targets" : "";
    return this.kind === "float" ? `float state · ${api}${ch}`
         : this.kind === "half" ? `half-float state · ${api}${ch}`
         : `8-bit state · ${api}${ch} (this GPU will not render to float; sims will be coarse)`;
  }
}
