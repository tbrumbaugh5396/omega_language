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
// Filling the window is `position: fixed; inset: 0` and a z-index, which no
// permission gates and no listener outlives. It sits at 70: above the sticky
// header at 40 and the dropdowns at 50, below the modals at 80 and the toasts
// at 90, so a dialog still opens over the top of it.
//
// What varies between studios is only *what* expands, and how it wants the
// room — which a studio knows better than this file does, so it hands over the
// element and says which.

/** Above the header and the menus, below the modals and the toasts. */
const LAYER = 70;

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
          fit = "contain",
          // Black is right behind a picture and wrong behind text: a patch on
          // a black field is a different, worse editor.
          background = "#000" } = opts;

  const button = document.createElement("button");
  if (className) button.className = className;
  button.textContent = label;
  button.title = title;

  let expanded = false;
  let placeholder = null, exitBtn = null;
  const saved = {};
  const KEYS = ["position", "inset", "zIndex", "background", "width", "height", "margin",
                "display", "alignItems", "justifyContent", "padding", "overflow"];

  const isExpanded = () => expanded;

  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); collapse(); } };

  const dressKids = (big) => {
    for (const kid of stage.children) {
      if (!kid.style || kid.dataset.expandChrome !== undefined) continue;   // not the exit button
      if (big) {
        kid.dataset.exW = kid.style.width;
        kid.dataset.exH = kid.style.height;
        kid.dataset.exMaxW = kid.style.maxWidth;
        kid.dataset.exMaxH = kid.style.maxHeight;
        if (fit === "fill") {
          kid.style.width = "100%"; kid.style.height = "100%";
          kid.style.maxWidth = ""; kid.style.maxHeight = "";
        } else if (fit === "contain") {
          kid.style.width = "auto"; kid.style.height = "auto";
          kid.style.maxWidth = "100%"; kid.style.maxHeight = "100%";
        }
      } else if (kid.dataset.exW !== undefined) {
        kid.style.width = kid.dataset.exW;
        kid.style.height = kid.dataset.exH;
        kid.style.maxWidth = kid.dataset.exMaxW;
        kid.style.maxHeight = kid.dataset.exMaxH;
        delete kid.dataset.exW; delete kid.dataset.exH;
        delete kid.dataset.exMaxW; delete kid.dataset.exMaxH;
      }
    }
  };

  function expand() {
    if (expanded) return;
    // `position: fixed` takes the stage out of the flow, so the page behind
    // would reflow and lose its scroll position while nobody can see it — and
    // put you somewhere else on the way back. A placeholder of the same height
    // holds the slot open.
    const box = stage.getBoundingClientRect();
    placeholder = document.createElement("div");
    placeholder.style.height = `${Math.round(box.height)}px`;
    stage.after(placeholder);

    for (const k of KEYS) saved[k] = stage.style[k];
    stage.style.position = "fixed";
    stage.style.inset = "0";
    stage.style.zIndex = String(LAYER);
    stage.style.background = background;
    stage.style.width = "";               // inset already says how wide
    stage.style.height = "";
    // A margin still applies to a fixed box, and comes off the size `inset`
    // gave it: Music's stage is a card with a rem underneath it, and it filled
    // the window fifteen pixels short until this line.
    stage.style.margin = "0";
    if (fit === "none") {
      stage.style.padding = "1rem";
      stage.style.overflow = "auto";
    } else {
      stage.style.display = "flex";
      stage.style.alignItems = "center";
      stage.style.justifyContent = "center";
    }
    dressKids(true);

    // A way out that does not depend on knowing about Esc, and does not
    // depend on the button that opened it — that one is under the picture now.
    exitBtn = document.createElement("button");
    exitBtn.dataset.expandChrome = "";
    exitBtn.textContent = "Exit (Esc)";
    exitBtn.style.cssText = "position:absolute;top:.6rem;right:.6rem;z-index:1;opacity:.75";
    exitBtn.onclick = collapse;
    stage.append(exitBtn);

    document.addEventListener("keydown", onKey);
    expanded = true;
    button.textContent = exitLabel;
    if (onChange) onChange(true);
  }

  function collapse() {
    if (!expanded) return;
    document.removeEventListener("keydown", onKey);
    dressKids(false);
    for (const k of KEYS) stage.style[k] = saved[k] || "";
    if (exitBtn) { exitBtn.remove(); exitBtn = null; }
    if (placeholder) { placeholder.remove(); placeholder = null; }
    expanded = false;
    button.textContent = label;
    if (onChange) onChange(false);
  }

  button.onclick = () => (expanded ? collapse() : expand());

  return { button, isExpanded, collapse, expand };
}
