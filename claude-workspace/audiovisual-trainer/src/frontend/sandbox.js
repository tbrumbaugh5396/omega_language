// Module 6: the generator + filter sandbox.
//
// Formal systems generate a large valid candidate space and filter
// malformedness. They do not decide goodness — the grammatical-but-dull space
// vastly exceeds the good space, and no formal measure has closed that gap.
// So the machine generates and you select, and every selection is logged,
// because selection is the training signal.

import { el, clear, api, toast, modal, closeModal, rng, pick, relTime } from "./ui.js";
import * as I from "./engine-image.js";

const CW = 190, CH = 150;

export async function sandboxView(ctx) {
  const root = el("div");
  const generators = {
    layout: { title: "Layout", blurb: "Grid, modular scale, hierarchy. Every candidate is well-formed; none of them is thereby good." },
    palette: { title: "Palette", blurb: "Built on opponent axes at controlled lightness, so the candidates differ on dimensions you can name." },
    motion: { title: "Motion", blurb: "Duration, easing, overshoot. The curve is the grammar; pick the one that has the right mass." },
    bundle: { title: "Bundle cross-breed", blurb: "Two feature bundles spliced. Forced analogy is a reliable ideation method, not a gimmick." },
  };

  let current = "layout";
  const field = el("div");
  const nav = el("div.lib-nav", {}, ...Object.entries(generators).map(([id, g]) =>
    el("button", {
      class: id === current ? "on" : "",
      onclick: () => {
        current = id;
        [...nav.children].forEach((b) => b.classList.toggle("on", b.dataset.id === id));
        generate();
      },
      "data-id": id,
    }, g.title)));

  const blurb = el("p.dim");
  const count = el("select", { style: { width: "auto" } },
    ...[12, 24, 48].map((n) => el("option", { value: n, selected: n === 24 }, `${n} candidates`)));

  function generate() {
    blurb.textContent = generators[current].blurb;
    clear(field);
    const n = +count.value;
    const seed = Math.floor(Math.random() * 1e9);
    const cands = CANDIDATES[current](n, seed, ctx);
    const grid = el("div.candidates");
    cands.forEach((c) => {
      const cell = el("div.candidate", {
        onclick: () => {
          grid.querySelectorAll(".candidate").forEach((x) => x.classList.remove("picked"));
          cell.classList.add("picked");
          pickDialog(ctx, current, c, cands);
        },
      }, c.node);
      grid.append(cell);
    });
    field.append(grid);
  }

  root.append(el("div.card", {},
    el("h2", {}, "Generator + filter"),
    el("p.dim", {}, "Generate wide, select narrow. Choosing among candidates is " +
      "the expensive half and the half that cannot be delegated — so it is " +
      "also the half worth logging."),
    nav,
    blurb,
    el("div.row", {}, count, el("button.primary", { onclick: generate }, "Generate"))),
    field);

  generate();
  root.append(await selectionsPane(ctx));
  return root;
}

function pickDialog(ctx, sandbox, chosen, all) {
  const rationale = el("textarea", {
    placeholder: "One sentence: why this one? Naming the dimension is the " +
      "articulation rep — and it is optional, but the reps are the point.",
  });
  modal(
    el("h2", {}, "Selected"),
    el("div", { style: { maxWidth: "260px", margin: "0 auto 1rem" } }, chosen.preview || chosen.node.cloneNode(true)),
    el("p.fine", {}, chosen.summary || ""),
    rationale,
    el("div.row", { style: { justifyContent: "flex-end" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          await api("/api/selections", {
            method: "POST",
            body: {
              sandbox, chosen: chosen.params,
              candidates: all.map((c) => c.params),
              rationale: rationale.value,
            },
          });
          closeModal();
          toast("Logged as a taste rep");
        },
      }, "Log it")));
}

// ------------------------------------------------------------------ generators

const CANDIDATES = {

  layout(n, seed) {
    const r = rng(seed);
    return Array.from({ length: n }, (_, i) => {
      const cols = pick(r, [2, 3, 4, 5, 6, 8, 12]);
      const ratio = pick(r, [1.125, 1.2, 1.25, 1.333, 1.5, 1.618]);
      const margin = 0.05 + r() * 0.14;
      const density = 0.3 + r() * 0.55;
      const align = pick(r, ["left", "centre", "split"]);
      const params = { cols, ratio: +ratio.toFixed(3), margin: +margin.toFixed(3),
                       density: +density.toFixed(2), align };
      const c = I.makeCanvas(CW, CH);
      const g = I.ctx2d(c);
      drawLayoutCandidate(g, CW, CH, params, seed + i * 7919);
      return { node: c, params,
               summary: `${cols} columns · scale ${ratio} · ${align} · margin ${(margin * 100).toFixed(0)}%` };
    });
  },

  palette(n, seed) {
    const r = rng(seed);
    return Array.from({ length: n }, () => {
      const baseHue = r() * Math.PI * 2;
      const scheme = pick(r, ["complementary", "analogous", "triad", "duotone", "neutral+accent"]);
      const chroma = 0.04 + r() * 0.13;
      const spread = 0.18 + r() * 0.5;
      const params = { scheme, hue: +(baseHue * 57.3).toFixed(0),
                       chroma: +chroma.toFixed(3), spread: +spread.toFixed(2) };
      const cols = paletteColors(baseHue, scheme, chroma, spread);
      params.hexes = cols.map((c) => c.hex);
      const c = I.makeCanvas(CW, CH);
      const g = I.ctx2d(c);
      cols.forEach((col, i) => {
        g.fillStyle = col.hex;
        g.fillRect(0, (i * CH) / cols.length, CW, CH / cols.length + 1);
      });
      return { node: c, params, summary: `${scheme} · chroma ${chroma.toFixed(2)} · L spread ${spread.toFixed(2)}` };
    });
  },

  motion(n, seed) {
    const r = rng(seed);
    const names = Object.keys(I.EASINGS);
    return Array.from({ length: n }, () => {
      const ease = pick(r, names);
      const duration = +(0.15 + r() * 1.1).toFixed(2);
      const stagger = +(r() * 0.12).toFixed(3);
      const params = { ease, duration, stagger };
      const c = I.makeCanvas(CW, CH);
      const g = I.ctx2d(c);
      drawCurve(g, CW, CH, I.EASINGS[ease], `${ease} · ${duration}s`);
      // Live preview in the dialog: the curve is legible, the motion is the truth.
      const preview = I.makeCanvas(240, 90);
      animateCurve(preview, I.EASINGS[ease], duration);
      return { node: c, preview, params,
               summary: `${ease}, ${duration}s, ${stagger}s stagger` };
    });
  },

  bundle(n, seed, ctx) {
    const r = rng(seed);
    const bundles = ctx.state.curriculum.bundles;
    return Array.from({ length: n }, () => {
      const a = pick(r, bundles), b = pick(r, bundles);
      const keep = pick(r, ["palette", "rhythm", "typography", "texture", "form"]);
      const params = { a: a?.label, b: b?.label, keep };
      const node = el("div", { style: { padding: ".5rem", minHeight: `${CH}px` } },
        el("b", {}, a?.label || "—"),
        el("div.fine", {}, a?.features || ""),
        el("div", { style: { margin: ".35rem 0", color: "var(--accent)" } }, "×"),
        el("b", {}, b?.label || "—"),
        el("div.fine", {}, b?.features || ""),
        el("div.tag", { style: { marginTop: ".4rem" } }, `keep the ${keep} of the first`));
      return { node, params, summary: `${a?.label} × ${b?.label}, keeping the ${keep} of the first` };
    });
  },
};

function paletteColors(hue, scheme, chroma, spread) {
  const mk = (L, h, c) => {
    const rgb = I.oklabToRgb(L, Math.cos(h) * c, Math.sin(h) * c);
    return { hex: I.hex(...rgb) };
  };
  const base = 0.5;
  switch (scheme) {
    case "complementary":
      return [mk(base + spread * 0.5, hue, chroma), mk(base, hue, chroma * 0.6),
              mk(base - spread * 0.4, hue + Math.PI, chroma),
              mk(base + spread * 0.3, hue + Math.PI, chroma * 0.4),
              mk(0.95, hue, 0.01)];
    case "analogous":
      return [0, 1, 2, 3, 4].map((i) =>
        mk(base - spread * 0.4 + (i / 4) * spread, hue + (i - 2) * 0.42, chroma));
    case "triad":
      return [mk(base + spread * 0.4, hue, chroma),
              mk(base, hue + 2.094, chroma),
              mk(base - spread * 0.35, hue + 4.188, chroma),
              mk(0.2, hue, 0.02), mk(0.93, hue, 0.01)];
    case "duotone":
      return [0, 1, 2, 3, 4].map((i) =>
        mk(0.15 + (i / 4) * 0.78, i < 2.5 ? hue : hue + Math.PI, chroma * (1 - Math.abs(i - 2) / 3)));
    default:
      return [mk(0.14, hue, 0.008), mk(0.35, hue, 0.012), mk(0.62, hue, 0.016),
              mk(0.9, hue, 0.008), mk(base, hue + Math.PI * 0.9, chroma * 1.6)];
  }
}

function drawLayoutCandidate(g, w, h, p, seed) {
  const r = rng(seed);
  g.fillStyle = "#0f1320";
  g.fillRect(0, 0, w, h);
  const m = w * p.margin;
  const gut = w * 0.012;
  const colW = (w - m * 2 - gut * (p.cols - 1)) / p.cols;
  let y = m;
  const unit = h * 0.035;
  let step = 0;
  while (y < h - m) {
    const size = unit * Math.pow(p.ratio, 3 - Math.min(3, step));
    const span = 1 + Math.floor(r() * Math.min(p.cols, 4));
    const startCol = p.align === "centre"
      ? Math.max(0, Math.floor((p.cols - span) / 2))
      : p.align === "split" ? (step % 2 ? Math.max(0, p.cols - span) : 0)
      : Math.floor(r() * Math.max(1, p.cols - span + 1));
    if (r() < p.density) {
      g.fillStyle = step === 0 ? "#7c9cff" : `rgba(232,235,245,${0.15 + r() * 0.4})`;
      g.fillRect(m + startCol * (colW + gut), y, colW * span + gut * (span - 1), Math.max(2, size));
    }
    y += size + h * 0.03;
    step++;
  }
}

function drawCurve(g, w, h, fn, label) {
  g.fillStyle = "#0f1320";
  g.fillRect(0, 0, w, h);
  g.strokeStyle = "#262c42";
  g.strokeRect(14.5, 14.5, w - 29, h - 44);
  g.strokeStyle = "#7c9cff";
  g.lineWidth = 2;
  g.beginPath();
  for (let x = 0; x <= 60; x++) {
    const t = x / 60;
    const px = 15 + t * (w - 30);
    const py = h - 30 - fn(t) * (h - 44);
    x ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.stroke();
  g.fillStyle = "#a8b0c8";
  g.font = "10px system-ui";
  g.fillText(label, 15, h - 10);
}

function animateCurve(canvas, fn, duration) {
  const g = I.ctx2d(canvas);
  const t0 = performance.now();
  const frame = () => {
    if (!canvas.isConnected && performance.now() - t0 > 500) return;
    const t = (((performance.now() - t0) / 1000) % (duration + 0.5)) / duration;
    const p = t >= 1 ? 1 : fn(Math.max(0, t));
    g.fillStyle = "#0f1320";
    g.fillRect(0, 0, canvas.width, canvas.height);
    g.fillStyle = "#7c9cff";
    g.fillRect(10 + p * (canvas.width - 60), canvas.height / 2 - 14, 40, 28);
    requestAnimationFrame(frame);
  };
  frame();
  canvas.style.width = "100%";
  return canvas;
}

// ------------------------------------------------------------------ history

async function selectionsPane(ctx) {
  const { selections } = await api("/api/selections?limit=60");
  if (!selections.length) {
    return el("div.card", {}, el("p.fine", {}, "Nothing selected yet. Every pick " +
      "you log here is a taste rep, and the pattern in them is readable later."));
  }

  // The emergent summary: what your picks have in common.
  const pal = selections.filter((s) => s.sandbox === "palette");
  const lay = selections.filter((s) => s.sandbox === "layout");
  const mot = selections.filter((s) => s.sandbox === "motion");
  const avg = (arr, f) => (arr.length ? arr.reduce((a, s) => a + (f(s) || 0), 0) / arr.length : 0);
  const modeOf = (arr, f) => {
    const counts = {};
    arr.forEach((s) => { const v = f(s); if (v) counts[v] = (counts[v] || 0) + 1; });
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    return best ? `${best[0]} (${best[1]}×)` : "—";
  };

  return el("div.card", {},
    el("h2", {}, "Your selections", el("span.fine", {}, `${selections.length} reps`)),
    el("div.kpi", {},
      el("div", {}, el("b", {}, pal.length ? avg(pal, (s) => s.chosen.chroma).toFixed(3) : "—"),
        el("span", {}, "mean chroma picked")),
      el("div", {}, el("b", {}, modeOf(pal, (s) => s.chosen.scheme)), el("span", {}, "favoured scheme")),
      el("div", {}, el("b", {}, lay.length ? avg(lay, (s) => s.chosen.cols).toFixed(1) : "—"),
        el("span", {}, "mean columns")),
      el("div", {}, el("b", {}, modeOf(mot, (s) => s.chosen.ease)), el("span", {}, "favoured easing"))),
    el("p.fine", {}, "This is a description of your defaults, which is exactly " +
      "what an unlearning exercise is for when everything starts coming out " +
      "the same."),
    el("div.stack", { style: { marginTop: ".8rem" } },
      ...selections.slice(0, 12).map((s) => el("div.card.tight", {},
        el("div.spread", {},
          el("div.row.tight", {},
            el("span.tag", {}, s.sandbox),
            el("span.fine", {}, summarise(s.chosen)),
            el("span.fine", {}, `1 of ${s.candidates.length}`)),
          el("span.fine", {}, relTime(s.created))),
        s.rationale ? el("p.fine", { style: { margin: ".3rem 0 0" } }, s.rationale) : null))));
}

function summarise(c) {
  if (c.scheme) return `${c.scheme}, chroma ${c.chroma}`;
  if (c.cols) return `${c.cols} cols, scale ${c.ratio}`;
  if (c.ease) return `${c.ease}, ${c.duration}s`;
  if (c.a) return `${c.a} × ${c.b}`;
  return "";
}
