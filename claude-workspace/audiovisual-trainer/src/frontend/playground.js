// Somewhere to play a graph.
//
// The studios render a graph when a document changes. A simulation wants the
// opposite: the same graph, every frame, with the keyboard fed in and the
// memory left alone between frames. This is that loop and nothing more — a
// canvas, a Keyboard attached to the page, requestAnimationFrame, and a line
// that says what is held and how fast it is going. It exists so the claim
// "a simulation can be played" is something you can do, not something the
// self-test asserts.

import { el, modal, closeModal } from "./ui.js";
import { createGraph, addNode, feedback } from "./render-graph.js";
import { renderGraph, resetGraphState } from "./graph-compile.js";
import { graphSummary } from "./graph-view.js";
import { Keyboard } from "./keyboard.js";
import "./field-nodes.js";
import "./sim-nodes.js";
import "./game-nodes.js";

/** A seed picture, drawn with the 2D canvas. */
function seedCanvas(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const g = c.getContext("2d");
  g.fillStyle = "#000"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#fff"; draw(g, w, h);
  return c;
}

/**
 * The demos. Each builds a graph and says how to play it. A demo is a
 * function so a fresh graph — and fresh memory — is made each time.
 */
export const PLAY_DEMOS = [
  {
    id: "ship", title: "Ship",
    how: "Arrows or WASD: left and right turn, up thrusts. It wraps.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-ship";
      const ship = addNode(g, "game.ship", {}, [null], { name: "ship" });
      feedback(g, ship, 0, ship);
      const trail = addNode(g, "feedback.trail", { decay: [0.86] }, [ship, null], { name: "trail" });
      feedback(g, trail, 1, trail);
      g.output = trail;
      return { graph: g, sources: {} };
    },
  },
  {
    id: "life", title: "Life",
    how: "Space pauses. R starts again from the seed.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-life";
      const w = 160, h = Math.round(160 * H / W);
      const seed = seedCanvas(w, h, (c) => {
        // An R-pentomino and a couple of gliders — enough to run for a while.
        const at = (x, y) => c.fillRect(x, y, 1, 1);
        const cx = (w / 2) | 0, cy = (h / 2) | 0;
        [[1, 0], [2, 0], [0, 1], [1, 1], [1, 2]].forEach(([x, y]) => at(cx + x, cy + y));
        [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]].forEach(([x, y]) => at(6 + x, 6 + y));
        [[1, 0], [0, 1], [0, 2], [1, 2], [2, 2]].forEach(([x, y]) => at(w - 10 + x, 6 + y));
      });
      g.width = w; g.height = h;
      const s0 = addNode(g, "source");
      const life = addNode(g, "sim.life", {}, [null, s0], { name: "life" });
      feedback(g, life, 0, life);
      g.output = life;
      return { graph: g, sources: { [s0]: seed }, pixelated: true };
    },
  },
  {
    id: "rd", title: "Reaction–diffusion",
    how: "Watch. R reseeds. The seed is a field tree, not a picture.",
    build(W, H) {
      const w = 280, h = Math.round(280 * H / W);
      const g = createGraph(w, h); g.stateKey = "play-rd";
      const ring = addNode(g, "field.circle", { radius: [0.45] });
      const hole = addNode(g, "field.circle", { radius: [0.38] });
      const cut = addNode(g, "field.subtract", { k: [0] }, [ring, hole]);
      const bars = addNode(g, "field.repeat", { cell: [0.5, 0.5], count: [2, 1] },
        [addNode(g, "field.box", { size: [0.02, 0.12], corner: [0] })]);
      const seedF = addNode(g, "field.union", { k: [0] }, [cut, bars]);
      const seed = addNode(g, "field.shade", { fill: [1, 1, 1], filled: [1], width: [0], glow: [0] }, [seedF]);
      const rd = addNode(g, "sim.reactionDiffusion",
        { feed: [0.037], kill: [0.06] }, [null, seed], { name: "rd" });
      feedback(g, rd, 0, rd);
      g.output = addNode(g, "sim.view", {}, [rd]);
      return { graph: g, sources: {}, stepsPerFrame: 8 };
    },
  },
  {
    id: "keys", title: "The keyboard itself",
    how: "Press anything. Bottom row: held. Middle: this frame. Top: toggled.",
    build(W, H) {
      const g = createGraph(W, H);
      g.output = addNode(g, "input.keys", {});
      return { graph: g, sources: {} };
    },
  },
];

/** Open the playground on a demo. Returns a function that stops it. */
export function playgroundDialog(startId = "ship") {
  const W = 640, H = 360;
  const canvas = el("canvas", { width: W, height: H,
    style: { width: "100%", maxWidth: `${W}px`, aspectRatio: `${W} / ${H}`, background: "#0b0e16",
             borderRadius: "8px", display: "block" } });
  const ctx = canvas.getContext("2d");
  const status = el("p.fine", {}, "");
  const how = el("p.fine", {}, "");
  const summary = el("p.fine", { style: { opacity: 0.7 } }, "");
  const keyboard = new Keyboard();
  let current = null, raf = 0, frames = 0, lastAt = performance.now(), fps = 0, running = true;

  const pick = (id) => {
    const demo = PLAY_DEMOS.find((d) => d.id === id) || PLAY_DEMOS[0];
    if (current) resetGraphState(current.graph.stateKey);
    current = { ...demo.build(W, H), demo };
    resetGraphState(current.graph.stateKey);
    how.textContent = demo.how;
    summary.textContent = graphSummary(current.graph);
    ctx.imageSmoothingEnabled = !current.pixelated;
    keyboard.clear();
    for (const b of tabs.children) b.classList.toggle("primary", b.dataset.id === id);
  };

  const tabs = el("div.row", {}, ...PLAY_DEMOS.map((d) =>
    el("button", { "data-id": d.id, onclick: () => pick(d.id) }, d.title)));

  const frame = () => {
    if (!running) return;
    if (current) {
      const { graph, sources, stepsPerFrame } = current;
      try {
        renderGraph(graph, sources, { keys: keyboard.texture(), steps: stepsPerFrame || 1,
                                      time: performance.now() / 1000, into: ctx });
      } catch (e) {
        status.textContent = String(e.message).split("\n")[0];
      }
      keyboard.tick();
    }
    frames++;
    const now = performance.now();
    if (now - lastAt > 500) { fps = Math.round((frames * 1000) / (now - lastAt)); frames = 0; lastAt = now; }
    const held = keyboard.held();
    status.textContent = `${fps} fps · ${held.length ? "holding " + held.join(", ") : "no keys held"}`;
    raf = requestAnimationFrame(frame);
  };

  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
    keyboard.detach && keyboard.detach();
    if (current) resetGraphState(current.graph.stateKey);
  };

  modal(el("h2", {}, "Playground"),
    el("p.fine", {}, "A graph, every frame, with the keyboard fed in as a texture and the memory " +
      "left alone between frames. Click the picture first so it has the keys."),
    tabs, canvas, how, summary, status,
    el("div.row", { style: { justifyContent: "flex-end" } },
      el("button", { onclick: () => { if (current) { resetGraphState(current.graph.stateKey); keyboard.clear(); } } }, "Reset"),
      el("button.primary", { onclick: () => { stop(); closeModal(); } }, "Close")));
  canvas.tabIndex = 0;
  keyboard.attach(document);
  canvas.focus();
  pick(startId);
  raf = requestAnimationFrame(frame);
  return stop;
}
