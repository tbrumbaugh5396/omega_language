// The keyboard, as a texture.
//
// A shader cannot be handed an event. It can be handed a picture, and a
// picture of the keyboard is 256 columns by 3 rows: one column per key code,
// and a row each for "held down now", "went down this frame" and "toggled by
// its last press". That is Shadertoy's iKeyboard, and the reason to copy it
// rather than improve on it is that every shader ever written against it
// reads here unchanged.
//
// The host owns one of these, feeds it to the graph as `u_keys` each frame,
// and calls `tick()` after the frame so "went down this frame" lasts exactly
// one. Nothing about it is a DOM event by the time a sketch sees it, which is
// why a test can press a key by calling `press(39)` and get the same frame a
// person would.

export const KEYS = 256, ROWS = 3;
export const ROW_DOWN = 0, ROW_HIT = 1, ROW_TOGGLE = 2;

/** The codes a sketch is most likely to want, by the name a person uses. */
export const KEY = {
  left: 37, up: 38, right: 39, down: 40,
  space: 32, enter: 13, escape: 27, shift: 16,
  a: 65, d: 68, s: 83, w: 87, r: 82, p: 80, q: 81, e: 69,
  zero: 48, one: 49, two: 50, three: 51,
};

const BY_NAME = {
  ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40,
  " ": 32, Spacebar: 32, Enter: 13, Escape: 27, Shift: 16, Tab: 9, Backspace: 8,
};

/** The legacy code for an event, which is what the texture is indexed by. */
export function codeOf(e) {
  if (typeof e.keyCode === "number" && e.keyCode) return e.keyCode;
  // keyCode is deprecated and some events arrive without one; the name
  // still says which key it was.
  const k = String(e.key || "");
  if (k in BY_NAME) return BY_NAME[k];
  if (k.length === 1) return k.toUpperCase().charCodeAt(0);
  return 0;
}

export class Keyboard {
  constructor() {
    this.down = new Uint8Array(KEYS);
    this.hit = new Uint8Array(KEYS);
    this.toggle = new Uint8Array(KEYS);
    this.canvas = document.createElement("canvas");
    this.canvas.width = KEYS; this.canvas.height = ROWS;
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: true });
    this.image = this.ctx.createImageData(KEYS, ROWS);
    this.dirty = true;
    this.detach = null;
    this.anyDown = 0;
  }

  press(code) {
    if (code < 0 || code >= KEYS) return;
    if (!this.down[code]) { this.hit[code] = 1; this.toggle[code] ^= 1; }
    this.down[code] = 1;
    this.dirty = true;
  }
  release(code) {
    if (code < 0 || code >= KEYS) return;
    this.down[code] = 0;
    this.dirty = true;
  }
  /** End of frame: "went down this frame" is over. */
  tick() {
    if (this.hit.some((v) => v)) { this.hit.fill(0); this.dirty = true; }
  }
  /** Everything up, as if the hands left the keys. */
  clear() {
    this.down.fill(0); this.hit.fill(0); this.toggle.fill(0);
    this.dirty = true;
  }

  /** Listen on an element (or the document). Returns a function that stops. */
  attach(target = document) {
    this.detach && this.detach();
    const onDown = (e) => {
      const c = codeOf(e);
      if (!c) return;
      // A key a game uses should not also scroll the page or move focus.
      if (c >= 37 && c <= 40 || c === 32) e.preventDefault();
      this.press(c);
    };
    const onUp = (e) => this.release(codeOf(e));
    const onBlur = () => this.clear();
    target.addEventListener("keydown", onDown);
    target.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    this.detach = () => {
      target.removeEventListener("keydown", onDown);
      target.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
      this.detach = null;
    };
    return this.detach;
  }

  /**
   * The picture. Rebuilt only when something changed, so a frame in which
   * nothing was pressed costs a comparison and no upload.
   */
  texture() {
    if (this.dirty) {
      const d = this.image.data;
      for (let i = 0; i < KEYS; i++) {
        const v0 = this.down[i] ? 255 : 0, v1 = this.hit[i] ? 255 : 0, v2 = this.toggle[i] ? 255 : 0;
        const o0 = i * 4, o1 = (KEYS + i) * 4, o2 = (2 * KEYS + i) * 4;
        d[o0] = d[o0 + 1] = d[o0 + 2] = v0; d[o0 + 3] = 255;
        d[o1] = d[o1 + 1] = d[o1 + 2] = v1; d[o1 + 3] = 255;
        d[o2] = d[o2 + 1] = d[o2 + 2] = v2; d[o2 + 3] = 255;
      }
      this.ctx.putImageData(this.image, 0, 0);
      this.dirty = false;
    }
    return this.canvas;
  }

  /** Which keys are held, by name where one is known — for a status line. */
  held() {
    const names = Object.entries(KEY);
    const out = [];
    for (let i = 0; i < KEYS; i++) {
      if (!this.down[i]) continue;
      const n = names.find(([, c]) => c === i);
      out.push(n ? n[0] : String(i));
    }
    return out;
  }
}
