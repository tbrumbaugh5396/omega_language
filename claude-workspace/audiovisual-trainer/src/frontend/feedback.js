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

/** Try to build a render target of the given kind; null if the GPU refuses. */
function tryTarget(gl, w, h, kind, exts) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  const type = kind === "float" ? gl.FLOAT
             : kind === "half" ? exts.half.HALF_FLOAT_OES
             : gl.UNSIGNED_BYTE;
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, type, null);
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
  const fbo = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE
    && gl.getError() === gl.NO_ERROR;
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.bindTexture(gl.TEXTURE_2D, null);
  if (!ok) { gl.deleteTexture(tex); gl.deleteFramebuffer(fbo); return null; }
  return { tex, fbo, kind, linear };
}

export class Feedback {
  constructor(gl) {
    this.gl = gl;
    this.exts = {
      float: gl.getExtension("OES_texture_float"),
      floatLinear: gl.getExtension("OES_texture_float_linear"),
      half: gl.getExtension("OES_texture_half_float"),
      halfLinear: gl.getExtension("OES_texture_half_float_linear"),
    };
    // Some GPUs will render to float; some only to half; some to neither.
    // Decided once by actually trying, not by reading extension names.
    this.kind = null;
    this.a = null; this.b = null;         // the ping-pong pair (state)
    this.prevTex = null;                  // last displayed frame, for the no-sim path
    this.w = 0; this.h = 0;
    this.frame = 0;
  }

  /** (Re)build storage at a size. Also resets the simulation. */
  resize(w, h) {
    if (w === this.w && h === this.h && this.a) return;
    this.release();
    this.w = w; this.h = h;
    const gl = this.gl;
    const order = [];
    if (this.exts.float) order.push("float");
    if (this.exts.half) order.push("half");
    order.push("byte");
    for (const kind of order) {
      const a = tryTarget(gl, w, h, kind, this.exts);
      if (!a) continue;
      const b = tryTarget(gl, w, h, kind, this.exts);
      if (!b) { gl.deleteTexture(a.tex); gl.deleteFramebuffer(a.fbo); continue; }
      this.a = a; this.b = b; this.kind = kind;
      break;
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
      if (t) { gl.deleteTexture(t.tex); gl.deleteFramebuffer(t.fbo); }
    }
    if (this.prevTex) gl.deleteTexture(this.prevTex);
    this.a = this.b = this.prevTex = null;
  }

  /** A word for the panel. */
  describe() {
    if (!this.kind) return "no feedback storage";
    return this.kind === "float" ? "float state"
         : this.kind === "half" ? "half-float state"
         : "8-bit state (this GPU will not render to float; sims will be coarse)";
  }
}
