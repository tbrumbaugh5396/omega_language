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
import { expandButton, OVER_MODAL } from "./expand.js";
import { createGraph, addNode, feedback } from "./render-graph.js";
import { renderGraph, resetGraphState } from "./graph-compile.js";
import { graphSummary } from "./graph-view.js";
import { Keyboard } from "./keyboard.js";
import "./field-nodes.js";
import "./sim-nodes.js";
import { shipAsData, menuAsData, pongAsData, pongEffects, PONG_INSTRUMENTS } from "./game-nodes.js";
import { EventQueue, keyboardEvents, pointerEvents } from "./events.js";
import { LiveRig } from "./live-audio.js";
import { instrumentFor } from "./instrument-library.js";

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
    id: "mvu", title: "Ship, as data",
    how: "Arrows or WASD; space sends a pulse. The ship's position is a parameter written as an expression over prev() and key(); the pulse starts on the keydown event, once per press; the shader only draws.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-mvu";
      const ship = shipAsData(g, undefined, { params: {
        // A ring that restarts on the keydown *event* — once per press, however
        // long the key is held — and grows on each frame.
        pulse: { expr: 'on("keydown", 32) ? 0.0 : prev("pulse") + 0.03 * on("frame")', value: [9] },
      } });
      const trail = addNode(g, "feedback.trail", { decay: [0.86] }, [ship, null], { name: "trail" });
      feedback(g, trail, 1, trail);
      const ring = addNode(g, "field.circle",
        { centre: { expr: ['ch("ship.pos", 0)', 'ch("ship.pos", 1)'] }, radius: { expr: 'ch("ship.pulse")' } });
      const shell = addNode(g, "field.shell", { thickness: [0.012] }, [ring]);
      const ink = addNode(g, "field.shade", { fill: [1, 0.5, 0.25], filled: [1], width: [0], glow: [0] }, [shell]);
      g.output = addNode(g, "composite.blend", { mode: [0], opacity: [1] }, [trail, ink]);
      // Sound, as effects the graph describes and the host performs: a note
      // on the keydown that starts a pulse — its pitch following how far the
      // ship has turned — and the hum's level following the thrust.
      // The document names its instrument, and its effects name which.
      // Referenced, not carried: the library ships this one. Its node ids are
      // the library's — an instrument names its own parts, and a reference
      // gets those names, which is why the effect asks the declaration where
      // the hum is rather than assuming.
      const inst = instrumentFor("ship.classic");
      g.instruments = { ship: { ref: "ship.classic" } };
      g.effects = [
        { kind: "note", instrument: "ship", when: 'on("keydown", 32)',
          hz: '330 * 2 ^ (mod(ch("ship.turns"), 12) / 12)', dur: "0.35" },
        { kind: "param", instrument: "ship", node: inst.hum, param: "level",
          value: 'ch("ship.burning") * 0.9' },
      ];
      return { graph: g, sources: {} };
    },
  },
  {
    id: "pong", title: "Pong",
    how: "Up and down (or W and S) move the bat. Turn Sound on: the bat blips at a pitch set by where the ball hit it, the wall rings a bell that rises with your score, and a miss thuds. Every rule is an expression on one node — read them in the graph summary.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-pong";
      const game = pongAsData(g);
      // A short trail, so the ball reads as moving rather than teleporting.
      const trail = addNode(g, "feedback.trail", { decay: [0.72] }, [game, null], { name: "trail" });
      feedback(g, trail, 1, trail);
      g.output = trail;
      g.instruments = PONG_INSTRUMENTS;
      g.effects = pongEffects();
      return { graph: g, sources: {} };
    },
  },
  {
    id: "menu", title: "Menu",
    how: "Up and down move, Enter chooses, Escape clears. Two instruments: a short blip when it moves, a longer tone when it chooses — the document names both and each effect says which.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-menu";
      g.output = menuAsData(g, 4);
      g.instruments = { blip: { ref: "tone.blip" }, tone: { ref: "tone.bell" } };
      g.effects = [
        // Pitch follows which row is highlighted, so moving down sounds lower.
        { kind: "note", instrument: "blip", when: 'on("keydown", 40) + on("keydown", 38)',
          hz: '880 * 2 ^ (-ch("menu.index") / 12)', dur: "0.08" },
        { kind: "note", instrument: "tone", when: 'on("keydown", 13)',
          hz: '440 * 2 ^ (ch("menu.index") / 12)', dur: "0.5" },
      ];
      return { graph: g, sources: {} };
    },
  },
  {
    id: "pointer", title: "Pointer",
    how: "Click to put the dot there; each click also starts a ring. The place arrives in the event, in the sketch's own coordinates.",
    build(W, H) {
      const g = createGraph(W, H); g.stateKey = "play-pointer";
      const dot = addNode(g, "field.circle", {
        centre: { expr: ['on("pointerdown") ? ev("x") : prev("centre", 0)', 'on("pointerdown") ? ev("y") : prev("centre", 1)'], value: [0, 0] },
        radius: [0.05],
      }, [], { name: "dot" });
      const ring = addNode(g, "field.circle", {
        centre: { expr: ['ch("dot.centre", 0)', 'ch("dot.centre", 1)'] },
        radius: { expr: 'on("pointerdown") ? 0.05 : prev("radius") + 0.02 * on("frame")', value: [9] },
      }, [], { name: "ring" });
      const both = addNode(g, "field.union", { k: [0] }, [dot, addNode(g, "field.shell", { thickness: [0.01] }, [ring])]);
      g.output = addNode(g, "field.shade", { fill: [0.43, 0.9, 0.78], filled: [1], width: [0], glow: [0.08], glowColour: [0.43, 0.9, 0.78] }, [both]);
      return { graph: g, sources: {} };
    },
  },
  {
    id: "ship", title: "Ship, in a texel",
    how: "The same ship with its state kept in the texel at (0,0) of its own last frame — Shadertoy's way.",
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
export function playgroundDialog(startId = "pong") {
  const W = 640, H = 360;
  const canvas = el("canvas", { width: W, height: H,
    style: { width: "100%", maxWidth: `${W}px`, aspectRatio: `${W} / ${H}`, background: "#0b0e16",
             borderRadius: "8px", display: "block" } });
  const ctx = canvas.getContext("2d");
  // Opened from a modal, so it has to clear the modal's own layer to be seen.
  // The keyboard follows the canvas rather than the dialog, so a game stays
  // playable at whatever size it is.
  const stage = el("div", { style: { position: "relative", display: "flex",
                                     alignItems: "center", justifyContent: "center" } }, canvas);
  const ex = expandButton(stage, { layer: OVER_MODAL, onChange: () => canvas.focus() });
  const status = el("p.fine", {}, "");
  const how = el("p.fine", {}, "");
  const summary = el("p.fine", { style: { opacity: 0.7 } }, "");
  const keyboard = new Keyboard();
  const queue = new EventQueue();
  let current = null, raf = 0, frames = 0, lastAt = performance.now(), fps = 0, running = true;
  // Sound is off until asked for: an AudioContext needs a gesture, and a page
  // that starts humming on its own is a page you close.
  let live = null, wantSound = false;
  const soundBtn = el("button", {}, "Sound: off");
  const ensureSound = async () => {
    if (!wantSound || !current || !current.graph.instruments) return;
    if (live && live.for === current.graph) { await live.resume(); return; }
    if (live) { await live.close(); live = null; }
    // The host installs what the document names, and nothing else.
    live = await LiveRig.create(current.graph);
    live.for = current.graph;
    await live.resume();
  };
  soundBtn.onclick = async () => {
    wantSound = !wantSound;
    soundBtn.textContent = wantSound ? "Sound: on" : "Sound: off";
    if (wantSound) await ensureSound();
    else if (live) { await live.close(); live = null; }
  };

  const pick = (id) => {
    const demo = PLAY_DEMOS.find((d) => d.id === id) || PLAY_DEMOS[0];
    if (current) resetGraphState(current.graph.stateKey);
    current = { ...demo.build(W, H), demo };
    resetGraphState(current.graph.stateKey);
    how.textContent = demo.how;
    summary.textContent = graphSummary(current.graph);
    ctx.imageSmoothingEnabled = !current.pixelated;
    keyboard.clear(); queue.drain();
    for (const b of tabs.children) b.classList.toggle("primary", b.dataset.id === id);
    soundBtn.hidden = !current.graph.instruments;
    ensureSound();
  };

  const tabs = el("div.row", {}, ...PLAY_DEMOS.map((d) =>
    el("button", { "data-id": d.id, onclick: () => pick(d.id) }, d.title)));

  const frame = () => {
    if (!running) return;
    if (current) {
      const { graph, sources, stepsPerFrame } = current;
      try {
        renderGraph(graph, sources, { keys: keyboard, events: queue, steps: stepsPerFrame || 1,
                                      time: performance.now() / 1000, into: ctx,
                                      onFired: (fired) => { if (live && wantSound) live.perform(fired); } });
      } catch (e) {
        status.textContent = String(e.message).split("\n")[0];
      }
      keyboard.tick();
    }
    frames++;
    const now = performance.now();
    if (now - lastAt > 500) { fps = Math.round((frames * 1000) / (now - lastAt)); frames = 0; lastAt = now; }
    const held = keyboard.held();
    const snd = live && wantSound
      ? ` · ${[...live.players.keys()].join(" + ")} ${live.meter.rms > 0.001 ? "●" : "○"} ${live.notes} note${live.notes === 1 ? "" : "s"}` : "";
    status.textContent = `${fps} fps · ${held.length ? "holding " + held.join(", ") : "no keys held"}${snd}`;
    raf = requestAnimationFrame(frame);
  };

  const stop = () => {
    ex.collapse();
    running = false;
    cancelAnimationFrame(raf);
    stopKeys(); stopPointer();
    if (live) { live.close(); live = null; }
    if (current) resetGraphState(current.graph.stateKey);
  };

  modal(el("h2", {}, "Playground"),
    el("p.fine", {}, "A graph, every frame, with the keyboard fed in as a texture and the memory " +
      "left alone between frames. Click the picture first so it has the keys."),
    tabs, stage, how, summary, status,
    el("div.row", { style: { justifyContent: "flex-end" } },
      soundBtn, ex.button,
      el("button", { onclick: () => { if (current) { resetGraphState(current.graph.stateKey); keyboard.clear(); } } }, "Reset"),
      el("button.primary", { onclick: () => { stop(); closeModal(); } }, "Close")));
  canvas.tabIndex = 0;
  // One listener feeds both the keyboard texture and the queue, so the two
  // cannot disagree about what happened.
  const stopKeys = keyboardEvents(queue, { target: document, keyboard });
  const stopPointer = pointerEvents(queue, canvas);
  canvas.focus();
  pick(startId);
  raf = requestAnimationFrame(frame);
  return stop;
}
