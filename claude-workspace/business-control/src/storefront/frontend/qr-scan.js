/* A camera QR reader, shared by all three sign-in screens.

   One file rather than three copies: it lives under the storefront directory
   because that is mounted at "/", so /qr-scan.js resolves from the shop, the
   store admin and the ops app alike — same origin, one implementation, one
   place to fix.

   The scanned value is untrusted input. A QR code is a string a stranger can
   print and tape to a wall, so this will only ever act on a sign-in link for
   the origin the page is already on; anything else is handed back to the
   caller to reject. Following a scanned URL wherever it points would turn
   every one of these screens into an open redirect with a camera attached.

   The camera is stopped on every exit path — closing, cancelling, a
   successful scan, an error, or the tab being hidden. A getUserMedia stream
   nobody stops keeps the camera light on and the encoder running. */
(function (global) {
  "use strict";

  const supported = () => "BarcodeDetector" in global;

  /* The formats a till needs. QR is the default because that is what every
     existing caller here is scanning; a shop counter asks for the retail
     symbologies as well, and they are requested by name rather than by
     asking for everything — a detector told to look for fourteen formats
     at once is slower at the one that is actually under the beam. */
  const RETAIL = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128",
                  "code_39", "itf", "qr_code"];

  /* Ask the browser which of them it can actually do. Chrome on a phone
     reads all of these; a desktop build may read three. Handing the
     detector a format it does not know makes it refuse the lot, which
     presents as a scanner that never sees anything. */
  async function usable(want) {
    try {
      const have = await global.BarcodeDetector.getSupportedFormats();
      const keep = want.filter((f) => have.includes(f));
      return keep.length ? keep : null;
    } catch (e) {
      return want;            // older builds have no getSupportedFormats
    }
  }

  function overlay(title, hint) {
    const el = document.createElement("div");
    el.className = "qrs-wrap";
    el.innerHTML = `
      <div class="qrs-card">
        <h3 class="qrs-title"></h3>
        <div class="qrs-stage">
          <video class="qrs-video" playsinline muted></video>
          <div class="qrs-reticle"></div>
        </div>
        <p class="qrs-status"></p>
        <button type="button" class="qrs-cancel">Cancel</button>
      </div>`;
    el.querySelector(".qrs-title").textContent = title;
    el.querySelector(".qrs-status").textContent = hint;
    document.body.appendChild(el);
    return el;
  }

  /* Opens the camera and resolves with the decoded string, or null if the
     person cancelled or it couldn't run. Never throws at the caller. */
  function scan(opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      const el = overlay(o.title || "Scan a QR code",
                         "Point the camera at the code");
      const video = el.querySelector(".qrs-video");
      const status = el.querySelector(".qrs-status");
      let stream = null, done = false, timer = 0;

      const finish = (value) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (stream) stream.getTracks().forEach((t) => t.stop());
        video.srcObject = null;
        document.removeEventListener("visibilitychange", onHide);
        document.removeEventListener("keydown", onKey);
        el.remove();
        resolve(value);
      };
      const onHide = () => { if (document.hidden) finish(null); };
      const onKey = (e) => { if (e.key === "Escape") finish(null); };

      el.querySelector(".qrs-cancel").onclick = () => finish(null);
      el.onclick = (e) => { if (e.target === el) finish(null); };
      document.addEventListener("visibilitychange", onHide);
      document.addEventListener("keydown", onKey);

      if (!supported()) {
        status.textContent = "This browser has no built-in QR reader "
          + "(Safari on iPhone is one). Type the code in instead, or open "
          + "this page in Chrome.";
        return;
      }
      navigator.mediaDevices.getUserMedia(
        { video: { facingMode: "environment" } }
      ).then(async (s) => {
        if (done) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        video.srcObject = s;
        video.play().catch(() => {});
        const want = o.formats || ["qr_code"];
        const formats = await usable(want);
        if (!formats) {
          status.textContent = "This browser cannot read that kind of code. "
            + "Type it in instead.";
          return finish(null);
        }
        const det = new global.BarcodeDetector({ formats });
        const tick = async () => {
          if (done) return;
          try {
            const codes = await det.detect(video);
            if (codes.length && codes[0].rawValue) {
              status.textContent = "Got it";
              return finish(codes[0].rawValue);
            }
          } catch (e) { /* a frame that won't decode is normal */ }
          timer = setTimeout(tick, 300);
        };
        video.onloadedmetadata = () => { clearTimeout(timer); tick(); };
      }).catch((e) => {
        status.textContent = "Camera unavailable (" + e.message + "). "
          + "Check the browser's camera permission, or sign in with your "
          + "name and password instead.";
      });
    });
  }

  /* A sign-in QR carries {origin}/qr-login/{token}. Accept only that, and
     only for this origin: a code pointing somewhere else is either a
     mistake or someone's idea of a joke, and neither should navigate. */
  function signInLink(text) {
    let u;
    try { u = new URL(String(text), location.origin); } catch { return null; }
    if (u.origin !== location.origin) return null;
    return /^\/qr-login\/[\w-]+$/.test(u.pathname) ? u.pathname : null;
  }

  async function signIn(title) {
    const text = await scan({ title: title || "Scan your sign-in QR" });
    if (text === null) return { ok: false, cancelled: true };
    const path = signInLink(text);
    if (!path) {
      return { ok: false,
               error: "That isn't a sign-in code for this site." };
    }
    location.assign(path);          // the server sets the session and lands you
    return { ok: true };
  }

  /* ---------- the scanner that is actually on the counter ----------

     Most retail scanners are not cameras. They are USB devices that
     pretend to be a keyboard: they type the digits very fast and press
     Enter. Nothing has to be granted, nothing has to be opened, and the
     page only has to notice that a burst of keystrokes arrived faster
     than fingers can move and ended in a Return.

     Which is also how it stays out of the way: a person typing into a
     search box types at human speed, so the burst never triggers, and
     anything typed into a real input is left alone entirely. */
  function wedge(onCode, opts) {
    const o = opts || {};
    const minLen = o.minLength || 4;
    const gap = o.gapMs || 40;          // a scanner beats this comfortably
    let buf = "", last = 0;
    const onKey = (e) => {
      const now = Date.now();
      const el = document.activeElement;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA"
                            || el.isContentEditable);
      if (typing && !el.dataset.wedge) return;
      if (now - last > gap) buf = "";
      last = now;
      if (e.key === "Enter") {
        const code = buf;
        buf = "";
        if (code.length >= minLen) {
          e.preventDefault();
          onCode(code);
        }
        return;
      }
      if (e.key.length === 1) buf += e.key;
      // A long burst with no Return is a scanner configured without one:
      // flushed on a timer so it still works, just a beat later.
      clearTimeout(wedge._t);
      wedge._t = setTimeout(() => {
        if (buf.length >= minLen) { const c = buf; buf = ""; onCode(c); }
        buf = "";
      }, 120);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }

  global.QRScan = { supported, scan, signIn, signInLink, wedge,
                    RETAIL };
})(window);
