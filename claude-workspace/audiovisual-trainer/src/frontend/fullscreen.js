// One studio's picture, on its own.
//
// Six studios wanted the same button, so it is written once. What varies is
// only *what* goes fullscreen — a WebGL canvas and its overlay in Generate and
// Shader, a bitmap and its selection marquee in Canvas, a video frame in
// Video, an SVG surface in Design, a piano roll in Music — and a studio knows
// that better than this file does, so it hands over the element.
//
// The awkward part of the platform API, handled here rather than six times:
//
//   - **`fullscreenchange` is on the document, not the element.** Every studio
//     that ever opened would otherwise leave a listener behind, so the handler
//     removes itself once its stage is no longer in the page.
//   - **A request can simply be refused.** An embedded frame without the
//     permission is the common case, and the promise rejects with something
//     worth reading. A button that does nothing and says nothing is worse than
//     one that says it was refused, so the caller is told.
//   - **The screen's shape is not the picture's.** A fullscreen stage centres
//     its child and bounds it by both dimensions, so a 16:9 sketch on a 16:10
//     screen gets bars rather than a stretch.
//
// Nothing here decides a *render* size. In Generate a fullscreen render is
// larger, not merely scaled up, and that is Generate's business — it owns the
// budget and the state texture that resizing would reset. This reports the
// change and lets the studio decide what to do about it.

/** Is this element the one currently fullscreen? */
export const isFullscreen = (stage) => !!stage && document.fullscreenElement === stage;

/**
 * A fullscreen button for one element.
 *
 *   const fs = fullscreenButton(stage, { onChange: (full) => …, onRefused: … });
 *   row.append(fs.button);
 *
 * Returns { button, isFull, exit }. The button labels itself, and the stage
 * gets the styles that centre and letterbox its contents while it is up.
 */
export function fullscreenButton(stage, opts = {}) {
  const { label = "Fullscreen", exitLabel = "Exit fullscreen",
          title = "show this on its own", onChange, onRefused, className = "ghost",
          // How the contents want the extra room.
          //   "contain" — a picture with a size of its own. A canvas is 640×360
          //               whatever the screen is, so it is centred and bounded
          //               by both dimensions; stretching it would be a
          //               different picture.
          //   "fill"    — a *viewport* onto something larger, like Design's
          //               surface, which has its own pan and zoom and simply
          //               wants more room.
          //   "none"    — a scrolling editor, like Music's arrangement, whose
          //               contents are already the size the document makes
          //               them. It gets a bigger window onto the same thing,
          //               and nothing is centred or resized.
          fit = "contain",
          // Black is right behind a picture and wrong behind text: a patch on
          // a black field is a different, worse editor. A studio whose stage
          // is an editor asks for the surface it already sits on.
          background = "#000" } = opts;

  const button = document.createElement("button");
  if (className) button.className = className;
  button.textContent = label;
  button.title = title;

  const isFull = () => isFullscreen(stage);

  // What the stage looked like before, so leaving puts it back rather than
  // leaving the fullscreen styles on an element that is now 400 pixels wide.
  const saved = {};
  const KEYS = ["background", "width", "height", "display", "alignItems", "justifyContent"];

  const dress = (full) => {
    if (full) {
      for (const k of KEYS) saved[k] = stage.style[k];
      saved.padding = stage.style.padding;
      saved.overflow = stage.style.overflow;
      if (fit === "none") { stage.style.padding = "1rem"; stage.style.overflow = "auto"; }
      stage.style.background = background;
      stage.style.width = "100%";
      stage.style.height = "100%";
      if (fit === "none") return;                     // a scrolling editor: leave it be
      stage.style.display = "flex";
      stage.style.alignItems = "center";
      stage.style.justifyContent = "center";
      // The picture itself: as large as it can be without leaving the screen
      // or changing shape. `firstElementChild` rather than a query, because a
      // stage's picture is whatever it put first.
      for (const kid of stage.children) {
        if (!kid.style) continue;
        kid.dataset.fsW = kid.style.width;
        kid.dataset.fsH = kid.style.height;
        kid.dataset.fsMax = kid.style.maxWidth;
        kid.dataset.fsMaxH = kid.style.maxHeight;
        if (fit === "fill") {
          kid.style.width = "100%"; kid.style.height = "100%";
          kid.style.maxWidth = ""; kid.style.maxHeight = "";
        } else {
          kid.style.width = "auto"; kid.style.height = "auto";
          kid.style.maxWidth = "100%"; kid.style.maxHeight = "100%";
        }
      }
    } else {
      for (const k of KEYS) stage.style[k] = saved[k] || "";
      stage.style.padding = saved.padding || "";
      stage.style.overflow = saved.overflow || "";
      for (const kid of stage.children) {
        if (!kid.style || kid.dataset.fsW === undefined) continue;
        kid.style.width = kid.dataset.fsW;
        kid.style.height = kid.dataset.fsH;
        kid.style.maxWidth = kid.dataset.fsMax;
        kid.style.maxHeight = kid.dataset.fsMaxH;
        delete kid.dataset.fsW; delete kid.dataset.fsH;
        delete kid.dataset.fsMax; delete kid.dataset.fsMaxH;
      }
    }
  };

  const onChangeEvent = () => {
    // A studio that has been navigated away from is not around to care, and
    // its listener should not outlive it.
    if (!stage.isConnected) {
      document.removeEventListener("fullscreenchange", onChangeEvent);
      return;
    }
    const full = isFull();
    button.textContent = full ? exitLabel : label;
    dress(full);
    if (onChange) onChange(full);
  };
  document.addEventListener("fullscreenchange", onChangeEvent);

  button.onclick = () => {
    if (isFull()) { document.exitFullscreen(); return; }
    if (!stage.requestFullscreen) {
      if (onRefused) onRefused("this browser has no fullscreen for an element");
      return;
    }
    stage.requestFullscreen().catch((e) => {
      if (onRefused) onRefused(`fullscreen was refused: ${String((e && e.message) || e)}`);
    });
  };

  return { button, isFull, exit: () => { if (isFull()) document.exitFullscreen(); } };
}
