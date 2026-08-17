// A composition grid over a preview — the thirds an artist lays over a canvas
// to place a horizon or a subject, with a golden-section and a diagonals
// variant. It is drawn on top of the picture and is never part of an export.
//
// The choice is a working preference, not a property of one document, so it
// lives in localStorage and every editor that shows a grid shares it.

import { el } from "./ui.js";

const KEY = "av-trainer-grid";
const MODES = ["off", "thirds", "golden", "diagonals"];
const LABEL = { off: "Grid", thirds: "Grid ⅓", golden: "Grid φ", diagonals: "Grid ✕" };

const read = () => {
  const v = localStorage.getItem(KEY);
  return MODES.includes(v) ? v : "off";
};

/** Lines as CSS gradients: two verticals and two horizontals at the given
    fractions, plus optional diagonals. Crisp at any size, no canvas needed. */
function paint(node, mode) {
  const line = "rgba(255,255,255,0.55)";
  const shadow = "rgba(0,0,0,0.45)";
  const at = (f) => [
    `linear-gradient(to right, transparent calc(${f * 100}% - 1px), ${shadow} calc(${f * 100}% - 1px), ${line} ${f * 100}%, ${shadow} calc(${f * 100}% + 1px), transparent calc(${f * 100}% + 1px))`,
    `linear-gradient(to bottom, transparent calc(${f * 100}% - 1px), ${shadow} calc(${f * 100}% - 1px), ${line} ${f * 100}%, ${shadow} calc(${f * 100}% + 1px), transparent calc(${f * 100}% + 1px))`,
  ];
  let layers = [];
  if (mode === "thirds") layers = [...at(1 / 3), ...at(2 / 3)];
  else if (mode === "golden") layers = [...at(0.382), ...at(0.618)];
  else if (mode === "diagonals") {
    layers = [
      `linear-gradient(to top right, transparent calc(50% - 1px), ${line} 50%, transparent calc(50% + 1px))`,
      `linear-gradient(to top left, transparent calc(50% - 1px), ${line} 50%, transparent calc(50% + 1px))`,
      ...at(0.5),
    ];
  }
  node.style.backgroundImage = layers.join(",");
  node.style.display = mode === "off" ? "none" : "block";
}

/**
 * Returns { overlay, button }. Put `overlay` inside a position:relative box
 * that wraps the picture; put `button` in the toolbar. Cycling the button
 * moves through off → thirds → golden → diagonals.
 */
export function gridOverlay() {
  const overlay = el("div", { style: {
    position: "absolute", inset: 0, pointerEvents: "none",
    backgroundRepeat: "no-repeat", backgroundSize: "100% 100%",
  } });
  let mode = read();
  const button = el("button.ghost", { title: "Composition grid: thirds, golden section, diagonals",
    onclick: () => {
      mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
      localStorage.setItem(KEY, mode);
      apply();
    } });
  function apply() {
    paint(overlay, mode);
    button.textContent = LABEL[mode];
    button.classList.toggle("on", mode !== "off");
  }
  apply();
  return { overlay, button };
}
