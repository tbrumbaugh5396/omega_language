// Module 1: the practice loop manager (Track A), the deliberate-practice log
// (Track B), and the articulation protocols (Part 14).
//
// The loop is brief → produce → evaluate → identify what broke → pull theory
// for that break → next piece. The postmortem is the hinge: it is the only
// place the app converts a failure into a specific thing to read, and it
// insists on a mechanism rather than a verdict.

import { el, clear, api, toast, modal, closeModal, today, relDay, hhmm, confirmDialog } from "./ui.js";

export async function makeView(ctx) {
  const root = el("div");
  const tabs = ["Pieces", "Practice", "Articulate"];
  let active = ctx.sub || "Pieces";
  const body = el("div");
  const nav = el("div.lib-nav", {}, ...tabs.map((t) =>
    el("button", {
      class: t === active ? "on" : "",
      onclick: () => {
        active = t;
        [...nav.children].forEach((b) => b.classList.toggle("on", b.textContent === t));
        render();
      },
    }, t)));

  async function render() {
    clear(body);
    body.append(el("p.muted", {}, "Loading…"));
    const node = active === "Pieces" ? await piecesPane(ctx, render)
      : active === "Practice" ? await practicePane(ctx, render)
      : await articulatePane(ctx, render);
    clear(body);
    body.append(node);
  }
  root.append(nav, body);
  await render();
  return root;
}

// ------------------------------------------------------------------ pieces

async function piecesPane(ctx, refresh) {
  const wrap = el("div");
  const { pieces } = await api("/api/pieces");
  const { brief, shipped } = await api("/api/brief");
  const thisWeek = pieces.find((p) => p.week === brief.week);

  wrap.append(thisWeek ? currentPiece(ctx, thisWeek, refresh)
                       : newBriefCard(ctx, brief, shipped, refresh));

  const done = pieces.filter((p) => p !== thisWeek);
  if (done.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Archive", el("span.fine", {}, `${shipped} shipped`)),
      el("div.stack", {}, ...done.map((p) => archiveRow(ctx, p, refresh)))));
  }
  return wrap;
}

/** `deadline` falls back to the piece's own, since a brief stored on a piece
 *  (or written by hand) need not carry one. */
function briefBody(brief, fallbackDeadline = "") {
  const due = brief.deadline || fallbackDeadline;
  return el("div.stack", {},
    el("h3", {}, brief.form || "Brief"),
    brief.spec ? el("p.dim", {}, brief.spec) : null,
    el("div.pull-list", {},
      brief.bundle
        ? el("div.pull", {}, el("b", {}, "Bundle: "),
            [brief.bundle, brief.bundle_features].filter(Boolean).join(" — "))
        : null,
      brief.primitive ? el("div.pull", {}, el("b", {}, "Practising: "), brief.primitive) : null,
      brief.constraint ? el("div.pull", {}, el("b", {}, "Constraint: "), brief.constraint) : null),
    el("p.fine", {},
      [brief.budget_minutes ? `Budget ${hhmm(brief.budget_minutes)}` : null,
       due ? `due ${due} (${relDay(due)})` : null].filter(Boolean).join(" · ")));
}

function newBriefCard(ctx, brief, shipped, refresh) {
  const holder = el("div", {}, briefBody(brief));
  let current = brief;

  const reroll = async (craft) => {
    const r = await api(`/api/brief?seed=${Math.floor(Math.random() * 1e9)}&craft=${craft}`);
    current = r.brief;
    clear(holder);
    holder.append(briefBody(current));
  };

  return el("div.card", {},
    el("div.spread", {},
      el("h2", {}, "This week's brief", el("span.tag", {}, brief.week)),
      el("span.fine", {}, `level ${brief.level + 1} of 5 · ${shipped} shipped`)),
    holder,
    el("div.row", { style: { marginTop: ".8rem" } },
      el("button.primary", {
        onclick: async () => {
          await api("/api/pieces", {
            method: "POST",
            body: {
              title: "", week: current.week, brief: current, medium: current.medium,
              constraint_note: current.constraint, status: "briefed",
              deadline: current.deadline,
            },
          });
          toast("Accepted. Write the rubric before you start.");
          refresh();
        },
      }, "Accept this brief"),
      el("button", { onclick: () => reroll("any") }, "Reroll"),
      el("button.ghost", { onclick: () => reroll("audio") }, "Audio"),
      el("button.ghost", { onclick: () => reroll("visual") }, "Visual")),
    el("p.fine", { style: { marginTop: ".7rem" } },
      "Escalating ambition is tied to what you have shipped, not to how long " +
      "you have been here. Finished beats perfect."));
}

function currentPiece(ctx, p, refresh) {
  const title = el("input", { value: p.title, placeholder: "name it" });
  const rubric = el("textarea", {
    value: p.rubric,
    placeholder: "How would you grade this? Write it BEFORE you make it — " +
      "comparing the intended rubric against the actual failure modes is what " +
      "calibrates the explanatory model.",
  });
  const link = el("input", { value: p.link, placeholder: "where the file lives" });
  const overdue = p.deadline && p.deadline < today();

  const save = async (patch = {}) => {
    await api(`/api/pieces/${p.id}`, {
      method: "PATCH",
      body: {
        ...p, brief: p.brief, title: title.value, rubric: rubric.value,
        link: link.value, ...patch,
      },
    });
  };

  return el("div.card", {},
    el("div.spread", {},
      el("h2", {}, "In flight", el("span.tag", {}, p.week)),
      el("span.tag " + (overdue ? "bad" : ""), {},
        overdue ? `overdue — due ${p.deadline}` : `due ${relDay(p.deadline)}`)),
    p.brief?.form ? briefBody(p.brief, p.deadline) : null,
    el("div.stack", { style: { marginTop: ".8rem" } },
      el("label", {}, "Title", title),
      el("label", {}, "Rubric, written first", rubric),
      el("label", {}, "Link", link)),
    el("div.row", {},
      el("button", { onclick: async () => { await save(); toast("Saved"); } }, "Save"),
      p.status === "briefed"
        ? el("button", { onclick: async () => { await save({ status: "making" }); refresh(); } }, "Start making")
        : null,
      el("button.primary", { onclick: () => shipDialog(ctx, p, save, refresh) }, "Ship it"),
      el("button.ghost.danger", {
        onclick: async () => {
          if (await confirmDialog("Abandon this piece?",
            "The week still counts. Abandoning is a data point, not a failure.")) {
            await save({ status: "abandoned" });
            refresh();
          }
        },
      }, "Abandon")));
}

function shipDialog(ctx, p, save, refresh) {
  const reads = el("textarea", { value: p.pm_reads, placeholder: "What reads wrong? Describe it, do not judge it yet." });
  const why = el("textarea", { value: p.pm_why, placeholder: "Hypothesise the mechanism. Force a mechanism, not a verdict — 'the type lands too hard' is a verdict; 'linear-in with no overshoot, so nothing communicates mass' is a mechanism." });
  const study = el("textarea", { value: p.pm_study, placeholder: "What will you pull to fix it?" });

  const lessons = Object.entries(ctx.state.lessonTitles);
  const slug = el("select", {},
    el("option", { value: "" }, "— which theory item does that point at? —"),
    ...lessons.map(([s, t]) => el("option", { value: s, selected: s === p.pm_slug }, t)));

  modal(
    el("h2", {}, "Postmortem"),
    el("p.fine", {}, "One paragraph, honestly. This is the step that turns a " +
      "failure into a specific thing to read — and the archive is worth more " +
      "than the pieces."),
    el("label", {}, "What reads wrong", reads),
    el("label", {}, "Why — the mechanism", why),
    el("label", {}, "What to study", study),
    el("label", {}, "Pulls in", slug),
    el("div.row", { style: { justifyContent: "flex-end", marginTop: ".6rem" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          await save({
            status: "shipped", shipped: today(),
            pm_reads: reads.value, pm_why: why.value, pm_study: study.value,
            pm_slug: slug.value,
          });
          if (slug.value) {
            // The break pulls the theory in, with the failure attached to it.
            await api("/api/progress", {
              method: "POST",
              body: { slug: slug.value, status: "reading",
                      pulled_by: reads.value.slice(0, 240) },
            }).catch(() => {});
          }
          closeModal();
          toast("Shipped. Next brief is waiting.");
          refresh();
        },
      }, "Ship")));
}

function archiveRow(ctx, p, refresh) {
  const open = el("div", { hidden: true });
  return el("div.card.tight", {},
    el("div.spread", {},
      el("div", {},
        el("b", {}, p.title || "(untitled)"),
        el("div.row.tight", { style: { marginTop: ".2rem" } },
          el("span.tag", {}, p.week),
          el("span.tag " + (p.status === "shipped" ? "good" : p.status === "abandoned" ? "bad" : ""), {}, p.status),
          p.medium && el("span.tag", {}, p.medium))),
      el("button.ghost", {
        onclick: (e) => {
          open.hidden = !open.hidden;
          e.target.textContent = open.hidden ? "Open" : "Close";
          if (!open.hidden && !open.childElementCount) {
            open.append(el("div.stack", { style: { marginTop: ".6rem" } },
              p.brief?.form ? el("p.fine", {}, p.brief.form, " · ", p.brief.constraint) : null,
              p.rubric && el("div", {}, el("h4", {}, "Rubric"), el("p.dim", {}, p.rubric)),
              p.pm_reads && el("div", {}, el("h4", {}, "Reads wrong"), el("p.dim", {}, p.pm_reads)),
              p.pm_why && el("div", {}, el("h4", {}, "Mechanism"), el("p.dim", {}, p.pm_why)),
              p.pm_study && el("div", {}, el("h4", {}, "To study"), el("p.dim", {}, p.pm_study)),
              p.pm_slug && el("button.ghost", {
                onclick: () => ctx.go("library", "Theory", p.pm_slug),
              }, `Open: ${ctx.state.lessonTitles[p.pm_slug] || p.pm_slug}`),
              el("button.ghost.danger", {
                onclick: async () => {
                  if (await confirmDialog("Delete this piece?")) {
                    await api(`/api/pieces/${p.id}`, { method: "DELETE" });
                    refresh();
                  }
                },
              }, "Delete")));
          }
        },
      }, "Open")),
    p.pm_reads ? el("p.fine", { style: { margin: ".3rem 0 0" } }, p.pm_reads.slice(0, 120)) : null,
    open);
}

// ------------------------------------------------------------------ practice

async function practicePane(ctx, refresh) {
  const wrap = el("div");
  const { practice } = await api("/api/practice");

  const day = el("input", { type: "date", value: today() });
  const track = el("select", {}, ...ctx.state.curriculum.tracks.map((t) =>
    el("option", { value: t.id, selected: t.id === "tools" }, t.title)));
  const tool = el("input", { placeholder: "Resolve, Reaper, Shadertoy…" });
  const focus = el("input", { placeholder: "the isolated sub-skill" });
  const minutes = el("input", { type: "number", value: 30, min: 0 });
  const rating = el("select", {}, ...[0, 1, 2, 3, 4, 5].map((n) =>
    el("option", { value: n, selected: n === 3 }, n ? `${n}/5` : "—")));
  const notes = el("textarea", { placeholder: "what actually happened" });

  wrap.append(el("div.card", {},
    el("h2", {}, "Log a session"),
    el("p.dim", {}, "One tool at a time until it is invisible. Isolate a " +
      "sub-skill, drill it with fast feedback, recombine."),
    el("div.g3.grid", {},
      el("label", {}, "Day", day),
      el("label", {}, "Track", track),
      el("label", {}, "Tool", tool),
      el("label", {}, "Minutes", minutes),
      el("label", {}, "How it went", rating)),
    el("label", {}, "Focus", focus),
    el("label", {}, "Notes", notes),
    el("button.primary", {
      onclick: async () => {
        if (!focus.value.trim()) { toast("What did you actually work on?"); return; }
        await api("/api/practice", {
          method: "POST",
          body: {
            day: day.value, track: track.value, tool: tool.value,
            focus: focus.value, minutes: +minutes.value || 0,
            rating: +rating.value, notes: notes.value,
          },
        });
        toast("Logged");
        refresh();
      },
    }, "Log it")));

  if (practice.length) {
    const total = practice.reduce((a, p) => a + p.minutes, 0);
    const head = el("thead", {}, el("tr", {},
      el("th", {}, "Day"), el("th", {}, "Track"), el("th", {}, "Tool"),
      el("th", {}, "Focus"), el("th.num", {}, "Min"), el("th.num", {}, "Rating"),
      el("th", {})));
    const rows = practice.map((p) => {
      const del = el("button.ghost.danger", {
        onclick: async () => {
          await api(`/api/practice/${p.id}`, { method: "DELETE" });
          refresh();
        },
      }, "×");
      return el("tr", {},
        el("td", {}, p.day),
        el("td", {}, el("span.tag", {}, p.track)),
        el("td", {}, p.tool || "—"),
        el("td", {}, p.focus, p.notes ? el("div.fine", {}, p.notes) : null),
        el("td.num", {}, p.minutes),
        el("td.num", {}, p.rating || "—"),
        el("td", {}, del));
    });
    wrap.append(el("div.card", {},
      el("h2", {}, "Sessions", el("span.fine", {}, `${hhmm(total)} total`)),
      el("div.wrap-scroll", {},
        el("table", {}, head, el("tbody", {}, ...rows)))));
  }
  return wrap;
}

// ------------------------------------------------------------------ articulate

async function articulatePane(ctx, refresh) {
  const wrap = el("div");
  const { reps } = await api("/api/articulation");

  wrap.append(el("div.card", {},
    el("h2", {}, "Articulation"),
    el("p.dim", {}, "Explaining is a separately trained network — a model of " +
      "your skill, trained on its own data, and nothing forces it to be " +
      "faithful. The only real test is transfer: can someone act on your " +
      "explanation and get the result?")));

  const solo = ctx.state.curriculum.articulation.filter((a) => !a.social);
  const social = ctx.state.curriculum.articulation.filter((a) => a.social);
  for (const [label, list] of [["Solo protocols", solo], ["Social protocols", social]]) {
    wrap.append(el("div.card", {},
      el("h2", {}, label),
      el("div.drill-list", {}, ...list.map((a) =>
        el("button.drill-card", { onclick: () => repDialog(ctx, a, refresh) },
          el("b", {}, a.title),
          el("p", {}, a.prompt))))));
  }

  if (reps.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Your reps", el("span.fine", {}, `${reps.length}`)),
      el("div.stack", {}, ...reps.map((r) => {
        const proto = ctx.state.curriculum.articulation.find((a) => a.id === r.kind);
        const open = el("div", { hidden: true });
        return el("div.card.tight", {},
          el("div.spread", {},
            el("div", {},
              el("b", {}, proto?.title || r.kind),
              r.slug && el("span.tag", { style: { marginLeft: ".4rem" } },
                ctx.state.lessonTitles[r.slug] || r.slug),
              r.kind === "calibration" && r.actual
                ? el("span.tag " + (r.score >= 60 ? "good" : "bad"), { style: { marginLeft: ".4rem" } }, `${r.score}%`)
                : null),
            el("button.ghost", {
              onclick: (e) => {
                open.hidden = !open.hidden;
                e.target.textContent = open.hidden ? "Open" : "Close";
                if (!open.hidden && !open.childElementCount) {
                  open.append(
                    r.predicted && el("div", {}, el("h4", {}, "Predicted"), el("p.dim", {}, r.predicted)),
                    r.actual && el("div", {}, el("h4", {}, "Actually flagged"), el("p.dim", {}, r.actual)),
                    el("p.dim", { style: { whiteSpace: "pre-wrap" } }, r.body),
                    el("button.ghost.danger", {
                      onclick: async () => {
                        await api(`/api/articulation/${r.id}`, { method: "DELETE" });
                        refresh();
                      },
                    }, "Delete"));
                }
              },
            }, "Open")),
          el("p.fine", { style: { margin: ".3rem 0 0" } }, (r.body || "").slice(0, 130)),
          open);
      }))));
  }
  return wrap;
}

function repDialog(ctx, proto, refresh) {
  const body = el("textarea", { placeholder: proto.prompt, style: { minHeight: "9em" } });
  const predicted = el("textarea", { placeholder: "What will they flag? Be specific enough to be scored." });
  const actual = el("textarea", { placeholder: "What did they actually flag?" });
  const score = el("input", { type: "number", min: 0, max: 100, value: 0 });
  const lessons = Object.entries(ctx.state.lessonTitles);
  const slug = el("select", {},
    el("option", { value: "" }, "— about which item? (optional) —"),
    ...lessons.map(([s, t]) => el("option", { value: s }, t)));

  const isCal = proto.id === "calibration";
  modal(
    el("h2", {}, proto.title),
    el("p.dim", {}, proto.prompt),
    isCal ? el("label", {}, "Prediction (write this first)", predicted) : null,
    el("label", {}, isCal ? "Notes" : "Your explanation", body),
    isCal ? el("label", {}, "What was actually flagged", actual) : null,
    isCal ? el("label", {}, "Hit rate %", score) : null,
    el("label", {}, "About", slug),
    el("div.row", { style: { justifyContent: "flex-end", marginTop: ".6rem" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          await api("/api/articulation", {
            method: "POST",
            body: {
              kind: proto.id, slug: slug.value, prompt: proto.prompt,
              body: body.value, predicted: predicted.value,
              actual: actual.value, score: +score.value || 0,
            },
          });
          closeModal();
          toast("Rep logged");
          refresh();
        },
      }, "Save rep")));
}
