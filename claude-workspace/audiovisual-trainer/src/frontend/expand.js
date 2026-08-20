// One studio's picture, filling the window.
//
// This was the browser's Fullscreen API for about an hour, and that was the
// wrong tool. What a studio actually wants is the *canvas* at the size of the
// window — the tool bars and the panels out of the way, the picture as large
// as it goes. Taking over the whole screen is a different thing, and one the
// browser already offers on a key of its own.
//
// Asking for it the other way cost more than it bought. `requestFullscreen`
// can be refused, and is, whenever the page is in a frame that was not granted
// the permission — the app embedded anywhere is a button that reports an error
// instead of working. It also fires its change event on the *document* rather
// than the element, so every studio ever opened leaves a listener behind
// unless somebody remembers to take it off.
//
// Filling the window is a backdrop — `position: fixed; inset: 0` and a
// z-index — which no permission gates and no listener outlives. It sits at 70:
// above the sticky header at 40 and the dropdowns at 50, below the modals at
// 80 and the toasts at 90, so a dialog still opens over the top of it.
//
// The stage *moves into* that backdrop rather than becoming one. That is the
// detail worth keeping: a studio's overlays — a selection marquee, a grid, a
// crosshair — are positioned absolutely against the stage, so the stage has to
// go on being the same box as the picture. Make the stage fill the window and
// every overlay ends up somewhere the picture is not.
//
// What varies between studios is only *what* expands, and how it wants the
// room — which a studio knows better than this file does, so it hands over the
// element and says which.

/** Above the header and the menus, below the modals and the toasts. */
const LAYER = 70;
/** …and above a modal, for a picture that was opened from inside one. */
export const OVER_MODAL = 85;

/**
 * An expand button for one element.
 *
 *   const ex = expandButton(stage, { fit: "contain", onChange: (big) => … });
 *   row.append(ex.button);
 *
 * Returns { button, isExpanded, collapse }.
 */
export function expandButton(stage, opts = {}) {
  const { label = "Fullscreen", exitLabel = "Exit fullscreen",
          title = "fill the window with this — Esc to come back", onChange, className = "ghost",
          // How the contents want the extra room.
          //   "contain" — a picture with a size of its own. A canvas is 640×360
          //               whatever the window is, so it is centred and bounded
          //               by both dimensions; stretching it would be a
          //               different picture.
          //   "fill"    — a *viewport* onto something larger, like Design's
          //               surface, which has its own pan and zoom and simply
          //               wants more room.
          //   "none"    — a scrolling editor, like Music's arrangement or a
          //               patch, whose contents are already the size the
          //               document makes them. It gets a bigger window onto
          //               the same thing, and nothing is centred or resized.
          //   "refit"   — contents that resize *themselves*, like a course
          //               figure, which draws one canvas pixel per device
          //               pixel and must never be scaled by CSS afterwards.
          //               Centred like a picture, but its size is left to it.
          fit = "contain",
          // Above what. 70 clears the header and the menus and stays under
          // the modals; something opened *from* a modal has to clear that too,
          // and the toasts at 90 stay on top of everything.
          layer = LAYER,
          // Black is right behind a picture and wrong behind text: a patch on
          // a black field is a different, worse editor.
          background = "#000" } = opts;

  const button = document.createElement("button");
  if (className) button.className = className;
  button.textContent = label;
  button.title = title;

  let expanded = false;
  let placeholder = null, exitBtn = null, backdrop = null;
  const saved = {};
  const KEYS = ["width", "height", "margin", "padding", "overflow", "flex"];

  const isExpanded = () => expanded;

  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); collapse(); } };

  /**
   * The picture's shape. A canvas carries it in its attributes — those are the
   * pixels it actually has — and anything else is measured. Used to size the
   * stage, rather than to letterbox the canvas inside it: an overlay is
   * positioned against the *stage*, so the stage has to stay the same box as
   * the picture or the selection marquee and the grid land somewhere else.
   */
  const aspectOf = () => {
    const pic = stage.firstElementChild;
    if (pic && pic.width > 0 && pic.height > 0) return pic.width / pic.height;
    const box = (pic || stage).getBoundingClientRect();
    return box.height > 0 ? box.width / box.height : 16 / 9;
  };

  const dressKids = (big) => {
    if (fit === "none" || fit === "refit") return;      // they size themselves
    for (const kid of stage.children) {
      if (!kid.style) continue;
      if (big) {
        kid.dataset.exW = kid.style.width;
        kid.dataset.exH = kid.style.height;
        kid.style.width = "100%";
        kid.style.height = "100%";
      } else if (kid.dataset.exW !== undefined) {
        kid.style.width = kid.dataset.exW;
        kid.style.height = kid.dataset.exH;
        delete kid.dataset.exW; delete kid.dataset.exH;
      }
    }
  };

  /** The stage's size inside the backdrop, for whichever fit. */
  const layOut = () => {
    if (fit === "contain") {
      // Grown as well as shrunk. A lab canvas is 480×300 and a window is not;
      // leaving it at its intrinsic size would put a small picture in the
      // middle of a large black field, which is not what asking for this
      // means. The aspect is kept, so the picture is never stretched.
      const a = aspectOf();
      const byWidth = [window.innerWidth, window.innerWidth / a];
      const [w, h] = byWidth[1] <= window.innerHeight
        ? byWidth : [window.innerHeight * a, window.innerHeight];
      stage.style.width = `${Math.round(w)}px`;
      stage.style.height = `${Math.round(h)}px`;
    } else if (fit === "refit") {
      // Full width so the contents have the window to measure themselves
      // against, and auto height so the backdrop can centre what they decide
      // on. Full height would pin a wide figure to the top of the screen.
      stage.style.width = "100%";
      stage.style.height = "auto";
    } else {
      stage.style.width = "100%";
      stage.style.height = "100%";
    }
  };

  const onResize = () => { if (expanded) layOut(); };

  function expand() {
    if (expanded) return;
    // The stage moves into a backdrop rather than becoming one. Keeping the
    // stage the same box as its picture is what lets an absolutely positioned
    // overlay — a selection marquee, a grid — stay where it was drawn.
    const box = stage.getBoundingClientRect();
    placeholder = document.createElement("div");
    placeholder.style.height = `${Math.round(box.height)}px`;
    stage.after(placeholder);

    backdrop = document.createElement("div");
    backdrop.dataset.expandBackdrop = "";
    backdrop.style.cssText = `position:fixed;inset:0;z-index:${layer};background:${background};`
      + "display:flex;align-items:center;justify-content:center;";
    document.body.append(backdrop);

    for (const k of KEYS) saved[k] = stage.style[k];
    // A margin still applies here and would come off the box: Music's stage is
    // a card with a rem underneath, and it sat a rem short until this line.
    stage.style.margin = "0";
    if (fit === "none") { stage.style.padding = "1rem"; stage.style.overflow = "auto"; }
    backdrop.append(stage);
    layOut();
    dressKids(true);

    // A way out that does not depend on knowing about Esc, and does not depend
    // on the button that opened it — that one is behind the backdrop now. It
    // lives on the backdrop rather than the stage, so nothing that dresses the
    // stage's children can reach it.
    exitBtn = document.createElement("button");
    exitBtn.textContent = "Exit (Esc)";
    exitBtn.style.cssText = "position:absolute;top:.6rem;right:.6rem;z-index:1;opacity:.75";
    exitBtn.onclick = collapse;
    backdrop.append(exitBtn);

    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    expanded = true;
    button.textContent = exitLabel;
    if (onChange) onChange(true);
  }

  function collapse() {
    if (!expanded) return;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
    dressKids(false);
    for (const k of KEYS) stage.style[k] = saved[k] || "";
    // Back into the slot the placeholder held open, so the page is where it
    // was rather than wherever the reflow left it.
    if (placeholder) { placeholder.replaceWith(stage); placeholder = null; }
    if (backdrop) { backdrop.remove(); backdrop = null; }
    exitBtn = null;
    expanded = false;
    button.textContent = label;
    if (onChange) onChange(false);
  }

  button.onclick = () => (expanded ? collapse() : expand());

  return { button, isExpanded, collapse, expand };
}
