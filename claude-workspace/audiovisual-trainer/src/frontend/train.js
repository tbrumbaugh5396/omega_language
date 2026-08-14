// Module 2 (discrimination trainer), module 5 (vocabulary builder) and
// module 7 (unlearning exercises).
//
// The protocol is Kellman's: short trials, high volume, immediate feedback,
// discrimination-focused, with difficulty that moves. Feedback always names
// the mechanism — a right answer with no mechanism is a lucky guess, and the
// explanation is where the vocabulary gets built.

import { el, clear, api, toast, rng, clamp, pct, relTime } from "./ui.js";
import { AUDIO_DRILLS } from "./drills-audio.js";
import { VISUAL_DRILLS } from "./drills-visual.js";
import * as A from "./engine-audio.js";
import * as I from "./engine-image.js";

const GENERATORS = { ...AUDIO_DRILLS, ...VISUAL_DRILLS };
const TRIALS = 8;

export async function trainView(ctx) {
  const root = el("div");
  const tabs = ["Drills", "Vocabulary", "Unlearn"];
  let active = ctx.sub || "Drills";

  const body = el("div");
  const nav = el("div.lib-nav", {}, ...tabs.map((t) =>
    el("button", {
      class: t === active ? "on" : "",
      onclick: () => {
        active = t;
        [...nav.children].forEach((b) => b.classList.toggle("on", b.textContent === t));
        renderBody();
      },
    }, t)));

  async function renderBody() {
    clear(body);
    body.append(el("p.muted", {}, "Loading…"));
    const node = active === "Drills" ? await drillsPane(ctx)
      : active === "Vocabulary" ? await vocabPane(ctx)
      : unlearnPane(ctx);
    clear(body);
    body.append(node);
  }

  root.append(nav, body);
  await renderBody();
  return root;
}

// ------------------------------------------------------------------ drills

async function drillsPane(ctx) {
  const stats = await api("/api/drills/stats");
  const byId = Object.fromEntries(stats.per_drill.map((d) => [d.drill, d]));
  const wrap = el("div");

  const intro = el("div.card", {},
    el("h2", {}, "Discrimination drills"),
    el("p.dim", {}, "Ten focused minutes a day beats an hour on Sunday. Every " +
      "trial is generated fresh and level-matched, and every answer comes back " +
      "with the mechanism — naming the discrimination is what sharpens it."));

  const craftGroups = [["audio", "Ear"], ["visual", "Eye"]];
  const lists = craftGroups.map(([craft, label]) => {
    const drills = ctx.state.curriculum.drills.filter((d) => d.craft === craft);
    return el("div.card", {},
      el("h2", {}, label, el("span.tag " + craft, {}, `${drills.length} drills`)),
      el("div.drill-list", {}, ...drills.map((d) => {
        const s = byId[d.id];
        return el("button.drill-card", { onclick: () => runDrill(ctx, d, wrap) },
          el("b", {}, d.title),
          el("div.row.tight", {},
            el("span.tag", {}, ctx.state.curriculum.dimensions[d.dim] || d.dim),
            s ? el("span.tag " + (s.pct >= 75 ? "good" : ""), {}, `${s.pct}% · L${s.level}`)
              : el("span.tag", {}, "not started"),
            s && el("span.fine", {}, relTime(s.last))),
          el("p", {}, d.blurb));
      })));
  });

  wrap.append(intro, ...lists);
  return wrap;
}

function runDrill(ctx, drill, container) {
  const gen = GENERATORS[drill.id];
  if (!gen) { toast("That drill isn't wired up yet"); return; }

  const prior = ctx.state.drillLevels?.[drill.id] || 1;
  let level = clamp(prior, 1, drill.levels);
  let trial = 0, correct = 0, cleanup = null, answered = false;
  const detail = [];
  const started = Date.now();
  let articulate = ctx.state.prefs?.articulate ?? false;

  const dots = el("div.progress-dots", {},
    ...Array.from({ length: TRIALS }, () => el("i")));
  const promptEl = el("h2");
  const stage = el("div.stimulus");
  const choicesEl = el("div.choices");
  const feedback = el("div.feedback.dim");
  const callBox = el("input", {
    placeholder: "Call it before you answer — one phrase",
    style: { marginBottom: ".6rem" },
  });
  const callWrap = el("div", { hidden: !articulate }, callBox);

  const levelSel = el("select", {
    onchange: (e) => { level = +e.target.value; next(); },
    style: { width: "auto" },
  }, ...Array.from({ length: drill.levels }, (_, i) =>
    el("option", { value: i + 1, selected: i + 1 === level }, `Level ${i + 1}`)));

  const card = el("div.card", {},
    el("div.spread", {},
      el("div", {},
        el("h2", { style: { marginBottom: 0 } }, drill.title),
        el("span.fine", {}, ctx.state.curriculum.dimensions[drill.dim] || drill.dim)),
      el("div.row.tight", {},
        el("label.row.tight", { style: { marginBottom: 0, fontSize: ".78rem" } },
          el("input", {
            type: "checkbox", checked: articulate, style: { width: "auto" },
            onchange: (e) => { articulate = e.target.checked; callWrap.hidden = !articulate; },
          }), "articulate first"),
        levelSel,
        el("button.ghost", { onclick: () => { cleanup?.(); A.stopAll(); ctx.go("train"); } }, "Done"))),
    el("div.row", { style: { margin: ".6rem 0" } }, dots,
      el("span.fine.right", {}, `${TRIALS} trials`)),
    el("div.drill-stage", {}, promptEl, stage, el("div", { style: { height: ".7rem" } }), callWrap, choicesEl),
    feedback,
    el("p.fine", {}, drill.blurb));

  clear(container);
  container.append(card);

  async function next() {
    cleanup?.();
    A.stopAll();
    if (trial >= TRIALS) return finish();
    answered = false;
    clear(stage); clear(choicesEl); clear(feedback);
    feedback.className = "feedback dim";
    callBox.value = "";
    promptEl.textContent = "Generating…";
    const seed = Math.floor(Math.random() * 1e9);
    let q;
    try {
      q = await gen(level, seed);
    } catch (err) {
      promptEl.textContent = "This stimulus failed to generate.";
      feedback.textContent = String(err.message || err);
      return;
    }
    promptEl.textContent = q.prompt;
    const resolveClick = (ok, text) => grade(ok, text, q, -1);
    cleanup = q.mount(stage, resolveClick) || null;

    if (q.kind === "click") return;   // the stimulus itself takes the answer
    q.choices.forEach((label, i) => {
      choicesEl.append(el("button", {
        onclick: () => {
          if (answered) return;
          const ok = i === q.answer;
          [...choicesEl.children].forEach((b, bi) => {
            if (bi === q.answer) b.classList.add("correct");
            else if (bi === i) b.classList.add("wrong");
            b.disabled = true;
          });
          grade(ok, q.explain ? q.explain(i) : "", q, i);
        },
      }, label));
    });
  }

  function grade(ok, text, q, chosen) {
    if (answered) return;
    answered = true;
    if (ok) correct++;
    dots.children[trial].className = ok ? "hit" : "miss";
    detail.push({
      t: trial, level, ok, chosen,
      called: callBox.value.trim() || undefined,
    });
    trial++;
    feedback.className = "feedback " + (ok ? "right" : "wrong");
    clear(feedback);
    feedback.append(
      el("b", {}, ok ? "Yes. " : "No. "),
      el("span.dim", {}, text || ""),
      el("div.row", { style: { marginTop: ".6rem" } },
        el("button.primary", { onclick: next }, trial >= TRIALS ? "See the round" : "Next")));
  }

  async function finish() {
    clear(stage); clear(choicesEl); clear(feedback);
    callWrap.hidden = true;
    const score = pct(correct, TRIALS);
    // The level moves with you — a fixed difficulty stops training quickly.
    let advice = "";
    if (score >= 85 && level < drill.levels) {
      advice = `That is comfortable. Level ${level + 1} next.`;
      ctx.state.drillLevels[drill.id] = level + 1;
    } else if (score < 50 && level > 1) {
      advice = `Drop to level ${level - 1} and rebuild the discrimination there.`;
      ctx.state.drillLevels[drill.id] = level - 1;
    } else {
      advice = "Stay here until it stops being effortful.";
      ctx.state.drillLevels[drill.id] = level;
    }
    promptEl.textContent = `${correct} of ${TRIALS} — ${score}%`;
    stage.append(el("div.stack", { style: { textAlign: "center" } },
      el("p.dim", {}, advice),
      el("div.row", { style: { justifyContent: "center" } },
        el("button.primary", {
          onclick: () => { trial = 0; correct = 0; detail.length = 0; dots.replaceChildren(...Array.from({ length: TRIALS }, () => el("i"))); levelSel.value = ctx.state.drillLevels[drill.id]; level = ctx.state.drillLevels[drill.id]; next(); },
        }, "Another round"),
        el("button", { onclick: () => ctx.go("train") }, "Back to drills"))));

    try {
      await api("/api/drills/attempt", {
        method: "POST",
        body: { drill: drill.id, level, correct, total: TRIALS,
                ms: Date.now() - started, detail },
      });
      savePrefs(ctx, { articulate, drillLevels: ctx.state.drillLevels });
    } catch (e) { toast(`Could not save: ${e.message}`); }
  }

  next();
}

function savePrefs(ctx, patch) {
  ctx.state.prefs = { ...ctx.state.prefs, ...patch };
  api("/api/kv/prefs", { method: "PUT", body: ctx.state.prefs }).catch(() => {});
}

// ------------------------------------------------------------------ vocabulary

async function vocabPane(ctx) {
  const wrap = el("div");
  const { cards, due, new: fresh, total } = await api("/api/vocab/due?limit=25");
  const stats = await api("/api/vocab/stats");

  wrap.append(el("div.card", {},
    el("h2", {}, "Vocabulary"),
    el("p.dim", {}, "Naming a discrimination sharpens it — but only once the " +
      "discrimination exists. These are perceptual categories, not trivia, so " +
      "answer by trying to hear or see the thing before you read the definition."),
    el("div.kpi", {},
      el("div", {}, el("b", {}, stats.due), el("span", {}, "due now")),
      el("div", {}, el("b", {}, stats.seen), el("span", {}, `seen of ${total}`)),
      el("div", {}, el("b", {}, stats.mature), el("span", {}, "mature (21d+)")),
      el("div", {}, el("b", {}, fresh), el("span", {}, "never seen")))));

  if (!cards.length) {
    wrap.append(el("div.card.empty", {}, "Nothing due. Come back tomorrow — " +
      "spacing is the mechanism, so cramming these does nothing."));
    return wrap;
  }

  let i = 0, revealed = false;
  const deck = el("div.card");
  const render = () => {
    clear(deck);
    if (i >= cards.length) {
      deck.append(el("div.empty", {}, `Done — ${cards.length} reviewed.`),
        el("div.row", { style: { justifyContent: "center" } },
          el("button.primary", { onclick: () => ctx.go("train", "Vocabulary") }, "Reload deck")));
      return;
    }
    const card = cards[i];
    deck.append(
      el("div.spread", {},
        el("span.tag " + card.domain, {}, card.domain),
        el("span.fine", {}, `${i + 1} / ${cards.length}`)),
      el("div.deck-card", {},
        el("div", {},
          el("b", {}, card.term),
          revealed && el("p", {}, card.definition))),
      revealed
        ? el("div.row", { style: { marginTop: ".7rem" } },
            el("button", { onclick: () => review(0) }, "Again"),
            el("button", { onclick: () => review(1) }, "Hard"),
            el("button", { onclick: () => review(2) }, "Good"),
            el("button", { onclick: () => review(3) }, "Easy"))
        : el("div.row", { style: { marginTop: ".7rem" } },
            el("button.primary", { onclick: () => { revealed = true; render(); } },
              "Say it, then reveal")));
  };
  const review = async (grade) => {
    try { await api("/api/vocab/review", { method: "POST", body: { term: cards[i].term, grade } }); }
    catch (e) { toast(e.message); }
    i++; revealed = false; render();
  };
  render();
  wrap.append(deck);
  return wrap;
}

// ------------------------------------------------------------------ unlearn

function unlearnPane(ctx) {
  const wrap = el("div");
  wrap.append(el("div.card", {},
    el("h2", {}, "Unlearning exercises"),
    el("p.dim", {}, "Deliberate prior-suppression. These are only useful once " +
      "you have priors worth suppressing — they are the antidote to the expert " +
      "blind spot, and they treat the failure mode where every piece starts " +
      "coming out the same.")));

  const panels = {
    "upside-down": upsideDown,
    "inverted-playback": invertedPlayback,
    "squint-test": squintTest,
    "constraint-scramble": () => constraintScramble(ctx),
    "mirror-view": mirrorView,
    "describe-only": describeOnly,
  };

  for (const ex of ctx.state.curriculum.unlearning) {
    const holder = el("div", { style: { marginTop: ".7rem" } });
    let open = false;
    wrap.append(el("div.card", {},
      el("div.spread", {},
        el("div", {}, el("h3", { style: { marginBottom: ".2rem" } }, ex.title),
          el("span.tag " + (ex.craft === "both" ? "meta" : ex.craft), {}, ex.craft)),
        el("button", {
          onclick: (e) => {
            open = !open;
            e.target.textContent = open ? "Close" : "Run it";
            clear(holder);
            if (open) holder.append(panels[ex.id]?.() || el("p.dim", {}, ex.how));
          },
        }, "Run it")),
      el("p.dim", {}, ex.blurb),
      el("p.fine", {}, ex.how),
      holder));
  }
  return wrap;
}

function upsideDown() {
  const size = 260;
  const ref = I.scene(size, size, Math.floor(Math.random() * 1e6));
  const shown = I.makeCanvas(size, size);
  const sg = I.ctx2d(shown);
  sg.translate(size, size); sg.rotate(Math.PI); sg.drawImage(ref, 0, 0);

  const pad = I.makeCanvas(size, size);
  const pg = I.ctx2d(pad);
  pg.fillStyle = "#0f1320"; pg.fillRect(0, 0, size, size);
  pg.strokeStyle = "#e8ebf5"; pg.lineWidth = 2; pg.lineCap = "round";
  let drawing = false, last = null;
  const pos = (e) => {
    const r = pad.getBoundingClientRect();
    const p = e.touches ? e.touches[0] : e;
    return [((p.clientX - r.left) / r.width) * size, ((p.clientY - r.top) / r.height) * size];
  };
  const start = (e) => { drawing = true; last = pos(e); e.preventDefault(); };
  const move = (e) => {
    if (!drawing) return;
    const p = pos(e);
    pg.beginPath(); pg.moveTo(...last); pg.lineTo(...p); pg.stroke();
    last = p; e.preventDefault();
  };
  const end = () => { drawing = false; };
  pad.addEventListener("pointerdown", start);
  pad.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
  pad.style.touchAction = "none";
  pad.style.cursor = "crosshair";

  let flipped = false;
  const flip = () => {
    flipped = !flipped;
    const t = flipped ? "rotate(180deg)" : "none";
    shown.style.transform = t; pad.style.transform = t;
  };
  [shown, pad].forEach((c) => { c.style.width = "100%"; c.style.height = "auto"; c.style.borderRadius = "8px"; });

  return el("div.stack", {},
    el("div.ab", {},
      el("div.ab-pane", {}, shown, el("div.dim", {}, "reference, inverted")),
      el("div.ab-pane", {}, pad, el("div.dim", {}, "copy what you see"))),
    el("div.row", {},
      el("button", { onclick: flip }, "Flip both"),
      el("button.ghost", {
        onclick: () => { pg.fillStyle = "#0f1320"; pg.fillRect(0, 0, size, size); },
      }, "Clear"),
      el("span.fine", {}, "Copy shapes and gaps, not objects. Flip when you're done.")));
}

function invertedPlayback() {
  const seed = Math.floor(Math.random() * 1e6);
  const src = A.synth.pluck(0.9, 330, { seed });
  const phrase = new Float32Array(A.SR * 4);
  const notes = [0, 4, 7, 12, 7, 4];
  notes.forEach((n, i) => {
    const p = A.synth.pluck(1.4, A.noteHz(57 + n), { seed: seed + i, damp: 0.9965 });
    const at = Math.floor(i * 0.55 * A.SR);
    for (let j = 0; j < p.length && at + j < phrase.length; j++) phrase[at + j] += p[j] * 0.7;
  });
  const rev = new Float32Array(phrase.length);
  for (let i = 0; i < phrase.length; i++) rev[i] = phrase[phrase.length - 1 - i];

  const play = (data) => A.play(A.toBuffer([A.fade(new Float32Array(data))]));
  return el("div.stack", {},
    el("div.row", {},
      el("button", { onclick: () => play(phrase) }, "Forward"),
      el("button", { onclick: () => play(rev) }, "Reversed"),
      el("button.ghost", { onclick: () => A.stopAll() }, "Stop")),
    el("p.fine", {}, "Reversal destroys the melodic prior and leaves the envelope. " +
      "Attack becomes decay, decay becomes a swell. Write down what you can hear " +
      "backwards that you could not hear forwards — that is usually where the " +
      "sound design actually lives."),
    el("textarea", { placeholder: "What became audible?" }));
}

function squintTest() {
  const size = 300;
  const { canvas, ctx: g, blocks } = I.layout(size, size, Math.floor(Math.random() * 1e6));
  blocks[Math.floor(Math.random() * blocks.length)].accent = true;
  I.drawBlocks(g, blocks);
  const base = I.getImage(canvas);
  const out = I.makeCanvas(size, size);
  out.style.width = "100%"; out.style.height = "auto"; out.style.borderRadius = "8px";
  const apply = (r) => I.putImage(out, r < 0.5 ? base : I.blurFast(base, r));
  apply(0);
  return el("div.stack", {},
    out,
    el("label", {}, "Blur radius",
      el("input", {
        type: "range", min: 0, max: 14, step: 0.5, value: 0,
        oninput: (e) => apply(+e.target.value),
      })),
    el("p.fine", {}, "Whatever survives is what the first fixation gets. If the " +
      "hierarchy changes as you blur, the hierarchy was carried by detail — and " +
      "detail is the first thing lost to small screens, motion and bad displays."),
    el("textarea", { placeholder: "What is still readable at full blur?" }));
}

function constraintScramble(ctx) {
  const list = ctx.state.curriculum.constraints;
  const out = el("div.deck-card", {}, el("b", {}, list[Math.floor(Math.random() * list.length)]));
  return el("div.stack", {},
    out,
    el("div.row", {},
      el("button", {
        onclick: () => { clear(out); out.append(el("b", {}, list[Math.floor(Math.random() * list.length)])); },
      }, "Draw another"),
      el("span.fine", {}, "One hour under it. The constraint is doing the work of " +
        "suppressing your defaults, so do not negotiate with it.")));
}

function mirrorView() {
  const size = 300;
  const c = I.scene(size, size, Math.floor(Math.random() * 1e6));
  c.style.width = "100%"; c.style.height = "auto"; c.style.borderRadius = "8px";
  let m = false;
  return el("div.stack", {},
    c,
    el("div.row", {},
      el("button", {
        onclick: () => { m = !m; c.style.transform = m ? "scaleX(-1)" : "none"; },
      }, "Mirror"),
      el("span.fine", {}, "Reading order habituates you to your own composition. " +
        "Flipped, the balance errors come back.")));
}

function describeOnly() {
  const EVALUATIVE = /\b(good|bad|nice|beautiful|ugly|better|worse|love|hate|great|poor|strong|weak|boring|interesting|should|works|fails)\b/gi;
  const c = I.scene(320, 200, Math.floor(Math.random() * 1e6));
  c.style.width = "100%"; c.style.height = "auto"; c.style.borderRadius = "8px";
  const warn = el("p.fine");
  const ta = el("textarea", {
    placeholder: "Only what is literally there. No judgement.",
    oninput: (e) => {
      const hits = [...new Set(e.target.value.match(EVALUATIVE) || [])];
      warn.textContent = hits.length
        ? `Evaluative words used: ${hits.join(", ")} — that voids the rep.`
        : "";
      warn.style.color = hits.length ? "var(--bad)" : "";
    },
  });
  let left = 300;
  const timer = el("b", {}, "5:00");
  const tick = setInterval(() => {
    left--;
    timer.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left <= 0) clearInterval(tick);
  }, 1000);
  return el("div.stack", {}, c,
    el("div.row", {}, el("span.fine", {}, "Time left:"), timer),
    ta, warn,
    el("p.fine", {}, "Describe is the step everyone skips. Forcing it is what " +
      "builds the link between the vocabulary and the perception."));
}
