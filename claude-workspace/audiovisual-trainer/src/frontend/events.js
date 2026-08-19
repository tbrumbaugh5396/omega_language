// Events, as data in a queue.
//
// The keyboard texture says what is held *now*. It cannot say that two keys
// went down between this frame and the last, or which went first, and at a
// low frame rate it forgets a press entirely. A queue can: every event the
// host sees is a small record — { kind, code, x, y, t, … } — pushed in the
// order it happened, and the runner drains the queue once per frame and hands
// each record to the graph on its own. Every event, exactly once, in order.
//
// A record is data. A log of them plus the graph is a replay, and the
// self-test holds that to the byte. Nothing here is a DOM event by the time
// the graph sees it, which is why a test can push { kind: "keydown", code: 40 }
// twice and get the same frame a person would by typing fast.

import { codeOf } from "./keyboard.js";

export class EventQueue {
  constructor() { this.items = []; this.log = null; this.t0 = performance.now(); }

  /** Add an event. `t` is filled in (seconds since the queue was made) if absent. */
  push(ev) {
    const e = { ...ev };
    if (e.t === undefined) e.t = (performance.now() - this.t0) / 1000;
    this.items.push(e);
    if (this.log) this.log.push(e);
    return e;
  }

  /** Take everything queued so far, in order, leaving the queue empty. */
  drain() {
    const out = this.items;
    this.items = [];
    return out;
  }

  get length() { return this.items.length; }

  /** Keep a copy of everything pushed from now on — for a replay. */
  record() { this.log = []; return this.log; }
  stopRecording() { const l = this.log; this.log = null; return l; }
}

/**
 * Feed a queue from a keyboard. Returns a function that stops. `keyboard`,
 * if given, is told too, so the held/hit/toggle texture stays in step with
 * the queue — one listener, two consumers, no way for them to disagree.
 */
export function keyboardEvents(queue, { target = document, keyboard = null } = {}) {
  const onDown = (e) => {
    const code = codeOf(e);
    if (!code) return;
    if (code >= 37 && code <= 40 || code === 32) e.preventDefault();
    // Auto-repeat is the OS pressing the key for you; a game wants the press.
    if (e.repeat) return;
    if (keyboard) keyboard.press(code);
    queue.push({ kind: "keydown", code });
  };
  const onUp = (e) => {
    const code = codeOf(e);
    if (!code) return;
    if (keyboard) keyboard.release(code);
    queue.push({ kind: "keyup", code });
  };
  const onBlur = () => { if (keyboard) keyboard.clear(); queue.push({ kind: "blur" }); };
  target.addEventListener("keydown", onDown);
  target.addEventListener("keyup", onUp);
  window.addEventListener("blur", onBlur);
  return () => {
    target.removeEventListener("keydown", onDown);
    target.removeEventListener("keyup", onUp);
    window.removeEventListener("blur", onBlur);
  };
}

/**
 * Feed a queue from a pointer over an element. The place is reported in the
 * sketch's own `p` coordinates — centred, y up, aspect-corrected, −1..1 up
 * the short axis — so `field.circle` at ev("x"), ev("y") lands under the
 * finger with no conversion in the expression.
 */
export function pointerEvents(queue, element) {
  const place = (e) => {
    const r = element.getBoundingClientRect();
    const w = r.width || 1, h = r.height || 1;
    const u = (e.clientX - r.left) / w, v = (e.clientY - r.top) / h;
    return { x: (u * 2 - 1) * (w / h), y: 1 - v * 2 };
  };
  const on = (kind) => (e) => {
    queue.push({ kind, ...place(e), button: e.button || 0 });
  };
  const down = on("pointerdown"), up = on("pointerup"), move = on("pointermove");
  element.addEventListener("pointerdown", down);
  element.addEventListener("pointerup", up);
  element.addEventListener("pointermove", move);
  return () => {
    element.removeEventListener("pointerdown", down);
    element.removeEventListener("pointerup", up);
    element.removeEventListener("pointermove", move);
  };
}
