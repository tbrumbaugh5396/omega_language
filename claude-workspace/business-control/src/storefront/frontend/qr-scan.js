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
      ).then((s) => {
        if (done) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        video.srcObject = s;
        video.play().catch(() => {});
        const det = new global.BarcodeDetector({ formats: ["qr_code"] });
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

  global.QRScan = { supported, scan, signIn, signInLink };
})(window);
