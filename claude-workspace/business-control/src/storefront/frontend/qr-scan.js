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

  /* Where the browser has no detector of its own — Safari on every
     iPhone and iPad, Firefox — a software decoder does the reading from
     a canvas. jsQR is loaded on first need, not on every page: 260KB is
     nothing to a phone at the door and something to a page that never
     scans. QR only; the retail symbologies still need a real detector
     or a wedge scanner. */
  let jsqrLoading = null;
  function loadJsQR() {
    if (global.jsQR) return Promise.resolve(global.jsQR);
    if (jsqrLoading) return jsqrLoading;
    jsqrLoading = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = "/vendor/jsqr.js";
      el.onload = () => resolve(global.jsQR);
      el.onerror = () => { jsqrLoading = null; reject(new Error("decoder")); };
      document.head.appendChild(el);
    });
    return jsqrLoading;
  }

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
        <form class="qrs-typed"><input placeholder="or type the code, or use a USB scanner"
          autocomplete="off" spellcheck="false"><button type="submit">Go</button></form>
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
      // The typed road is always open: a USB scanner is a keyboard, and a
      // code read out over the phone is a code. It resolves exactly as a
      // camera read would, so no caller can tell the difference.
      const typed = el.querySelector(".qrs-typed");
      typed.onsubmit = (e) => {
        e.preventDefault();
        const v = typed.querySelector("input").value.trim();
        if (v) finish(v);
      };
      if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
        status.textContent = "No camera here. Type the code in, or use a "
          + "USB scanner.";
        typed.querySelector("input").focus();
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
        const formats = supported() ? await usable(want) : null;
        if (formats) {
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
          return;
        }
        // No detector, or not for these formats: QR by software.
        if (!want.includes("qr_code")) {
          status.textContent = "This browser cannot read that kind of code. "
            + "Type it in, or use a USB scanner.";
          typed.querySelector("input").focus();
          return;
        }
        let decode;
        try { decode = await loadJsQR(); }
        catch (e) { decode = null; }
        if (!decode) {
          status.textContent = "The QR decoder didn't load. Type the code "
            + "in, or use a USB scanner.";
          typed.querySelector("input").focus();
          return;
        }
        if (want.length > 1) {
          status.textContent = "QR only on this browser — barcodes need a "
            + "USB scanner.";
        }
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        const tick = () => {
          if (done) return;
          try {
            const w = video.videoWidth, h = video.videoHeight;
            if (w && h) {
              // Half size is plenty for a QR filling the reticle, and
              // four times cheaper to decode on a phone.
              canvas.width = w >> 1; canvas.height = h >> 1;
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
              const hit = decode(img.data, img.width, img.height,
                                 { inversionAttempts: "dontInvert" });
              if (hit && hit.data) {
                status.textContent = "Got it";
                return finish(hit.data);
              }
            }
          } catch (e) { /* a frame that won't decode is normal */ }
          timer = setTimeout(tick, 250);
        };
        video.onloadedmetadata = () => { clearTimeout(timer); tick(); };
      }).catch((e) => {
        status.textContent = "Camera unavailable (" + e.message + "). "
          + "Check the browser's camera permission, type the code in, or "
          + "use a USB scanner.";
        typed.querySelector("input").focus();
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
