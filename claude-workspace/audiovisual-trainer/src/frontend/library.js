// The reference layer: the theory map (Parts 3-8, 13, 14) plus the effects
// catalogue, genre glossaries, sensory systems and reading list.
//
// Theory is meant to be raided, not marched through. Every lesson lists the
// symptoms that pull it in, and a lesson opened from a postmortem arrives with
// the failure that sent you there attached to it.

import { el, clear, api, toast, hhmm, relTime } from "./ui.js";
import { renderMarkdown } from "./markdown.js";
import { mountFigure } from "./figures.js";
import { FIGURE_BY_ID, MODULE_EXTRAS } from "./figures-content.js";

export async function libraryView(ctx) {
  const root = el("div");
  const sections = ["Course", "Theory", "Effects", "Genres", "Systems", "Reading", "Tools", "Glossary"];
  let active = ctx.sub && sections.includes(ctx.sub) ? ctx.sub : "Theory";
  const target = ctx.arg;

  const body = el("div");
  const search = el("input", {
    placeholder: "Search everything — symptoms, effects, genres, terms",
    style: { maxWidth: "340px" },
    oninput: (e) => renderSearch(e.target.value.trim()),
  });
  const nav = el("div.lib-nav", {}, ...sections.map((s) =>
    el("button", {
      class: s === active ? "on" : "",
      onclick: () => {
        active = s;
        search.value = "";
        [...nav.children].forEach((b) => b.classList.toggle("on", b.textContent === s));
        render();
      },
    }, s)));

  const progress = Object.fromEntries(
    (await api("/api/progress")).progress.map((p) => [p.slug, p]));
  const notes = Object.fromEntries(
    (await api("/api/notes")).notes.map((n) => [n.slug, n.body]));

  async function render() {
    clear(body);
    if (active === "Course") { await coursePane(ctx, body); return; }
    body.append(
      active === "Theory" ? theoryPane(ctx, progress, notes, target)
      : active === "Effects" ? catalogPane(ctx)
      : active === "Genres" ? genrePane(ctx)
      : active === "Systems" ? systemsPane(ctx)
      : active === "Reading" ? readingPane(ctx)
      : active === "Tools" ? toolsPane(ctx)
      : glossaryPane(ctx));
  }

  function renderSearch(q) {
    if (!q) return render();
    clear(body);
    body.append(searchResults(ctx, q, progress, notes));
  }

  root.append(el("div.card", {},
    el("div.spread", {}, el("h2", {}, "Library"), search),
    el("p.dim", {}, "The topic map is large on purpose. You are not meant to " +
      "march through it — you are meant to raid it when something breaks."),
    nav), body);
  await render();
  if (target) setTimeout(() => document.getElementById(`lesson-${target}`)?.scrollIntoView({ block: "center" }), 50);
  return root;
}

// ------------------------------------------------------------------ theory

function theoryPane(ctx, progress, notes, target) {
  const wrap = el("div");
  for (const mod of ctx.state.curriculum.modules) {
    wrap.append(el("div.card", {},
      el("div.spread", {},
        el("h2", {}, mod.title),
        el("span.tag", {}, mod.part)),
      el("p.dim", {}, mod.blurb),
      el("div.stack", {}, ...mod.lessons.map((les) =>
        lessonRow(ctx, les, progress, notes, target === les.slug)))));
  }
  return wrap;
}

function lessonRow(ctx, les, progress, notes, openNow) {
  const p = progress[les.slug];
  const detail = el("div", { hidden: !openNow });
  const toggle = el("button.ghost", {
    onclick: (e) => {
      detail.hidden = !detail.hidden;
      e.target.textContent = detail.hidden ? "Open" : "Close";
      if (!detail.hidden && !detail.childElementCount) detail.append(lessonDetail(ctx, les, progress, notes));
    },
  }, openNow ? "Close" : "Open");
  if (openNow) detail.append(lessonDetail(ctx, les, progress, notes));

  return el("div.card.tight", { id: `lesson-${les.slug}` },
    el("div.spread", {},
      el("div", {},
        el("b", {}, les.title),
        el("div.row.tight", { style: { marginTop: ".2rem" } },
          el("span.tag " + les.domain, {}, les.domain),
          p ? el("span.tag " + (p.status === "done" ? "good" : ""), {}, p.status) : null,
          p && p.confidence ? el("span.tag", {}, `confidence ${p.confidence}/5`) : null,
          p && p.minutes ? el("span.fine", {}, hhmm(p.minutes)) : null)),
      toggle),
    p?.pulled_by
      ? el("div.pull", { style: { marginTop: ".4rem" } },
          el("b", {}, "Pulled in by: "), p.pulled_by)
      : null,
    detail);
}

function lessonDetail(ctx, les, progress, notes) {
  const p = progress[les.slug] || {};
  const status = el("select", {}, ...["reading", "applied", "done"].map((s) =>
    el("option", { value: s, selected: s === p.status }, s)));
  const confidence = el("select", {}, ...[0, 1, 2, 3, 4, 5].map((n) =>
    el("option", { value: n, selected: n === (p.confidence || 0) }, n ? `${n}/5` : "—")));
  const minutes = el("input", { type: "number", value: 0, min: 0, style: { width: "6em" } });
  const note = el("textarea", { value: notes[les.slug] || "", placeholder: "Your notes on this." });

  return el("div.stack.lesson-body", { style: { marginTop: ".7rem" } },
    el("div", {},
      el("h4", {}, "The load-bearing ideas"),
      el("ul.bullets", {}, ...les.key.map((k) => el("li", {}, k)))),
    les.pulls?.length
      ? el("div", {},
          el("h4", {}, "Read this when"),
          el("div.pull-list", {}, ...les.pulls.map((s) => el("div.pull", {}, s))))
      : null,
    les.practice ? el("p.dim", {}, el("b", {}, "Practice: "), les.practice) : null,
    el("div.row.tight", {},
      les.lab ? el("button", { onclick: () => ctx.go("lab") }, `Lab: ${labTitle(ctx, les.lab)}`) : null,
      ...(les.drills || []).map((d) => el("button.ghost", { onclick: () => ctx.go("train", "Drills") },
        `Drill: ${drillTitle(ctx, d)}`))),
    el("div.row", {},
      el("label", { style: { marginBottom: 0 } }, "Status", status),
      el("label", { style: { marginBottom: 0 } }, "Confidence", confidence),
      el("label", { style: { marginBottom: 0 } }, "Add minutes", minutes)),
    note,
    el("div.row", {},
      el("button.primary", {
        onclick: async () => {
          await api("/api/progress", {
            method: "POST",
            body: { slug: les.slug, status: status.value,
                    confidence: +confidence.value, add_minutes: +minutes.value || 0 },
          });
          await api("/api/notes", { method: "PUT", body: { slug: les.slug, body: note.value } });
          minutes.value = 0;
          toast("Saved");
        },
      }, "Save")));
}

const labTitle = (ctx, id) => ctx.state.curriculum.labs.find((l) => l.id === id)?.title || id;
const drillTitle = (ctx, id) => ctx.state.curriculum.drills.find((d) => d.id === id)?.title || id;

// ------------------------------------------------------------------ catalog

function catalogPane(ctx) {
  const wrap = el("div");
  for (const craft of ["visual", "audio"]) {
    const fams = ctx.state.library.catalog.filter((c) => c.craft === craft);
    wrap.append(el("div.card", {},
      el("h2", {}, craft === "visual" ? "Visual effects" : "Audio effects",
        el("span.fine", {}, `${fams.reduce((a, f) => a + f.items.length, 0)} entries`)),
      el("p.fine", {}, "Almost every entry is buildable from convolution, noise, " +
        "SDFs, delay lines, filters and modulation. No catalogue is complete — " +
        "new effects are compositions of these primitives."),
      ...fams.map((f) => el("details.acc", {},
        el("summary", {}, f.family, " ",
          el("span.tag", {}, f.primitive), " ",
          el("span.fine", {}, `${f.items.length}`)),
        el("div", {}, el("div.chips", {}, ...f.items.map((i) => el("span.chip", {}, i))),
          el("p.fine", { style: { marginTop: ".5rem" } }, `Part ${f.part}`))))));
  }
  return wrap;
}

// ------------------------------------------------------------------ genres

function genrePane(ctx) {
  const wrap = el("div");
  wrap.append(el("div.card", {},
    el("p.dim", {}, "Feature bundles, not an ontology. Boundaries are fuzzy, " +
      "axes are not orthogonal, lineage matters. When a brief says 'make it " +
      "feel like X', decompose X into the bundle and decide which features to " +
      "keep, exaggerate or swap.")));
  for (const kind of ["art", "design", "music"]) {
    const list = ctx.state.library.genres.filter((g) => g.kind === kind);
    const eras = [...new Set(list.map((g) => g.era))];
    wrap.append(el("div.card", {},
      el("h2", {}, { art: "Art movements", design: "Design & illustration", music: "Music" }[kind]),
      ...eras.map((era) => el("details.acc", {},
        el("summary", {}, era, " ", el("span.fine", {}, `${list.filter((g) => g.era === era).length}`)),
        el("div", {}, el("div.stack", {}, ...list.filter((g) => g.era === era).map((g) =>
          el("div", {}, el("b", {}, g.label), " — ", el("span.dim", {}, g.features)))))))));
  }
  return wrap;
}

// ------------------------------------------------------------------ systems

function systemsPane(ctx) {
  const wrap = el("div");
  for (const sys of ctx.state.library.systems) {
    wrap.append(el("div.card", {},
      el("div.spread", {}, el("h2", {}, sys.title), el("span.tag", {}, `Part ${sys.part}`)),
      el("div.stack", {}, ...sys.stages.map((st) =>
        el("div.card.tight", {},
          el("b", {}, st.name),
          el("p.dim", { style: { margin: ".3rem 0" } }, st.body),
          el("div.pull", {}, el("b", {}, "For the craft: "), st.craft))))));
  }
  return wrap;
}

// ------------------------------------------------------------------ reading

function readingPane(ctx) {
  return el("div", {}, ...ctx.state.library.reading.map((sec) =>
    el("div.card", {},
      el("h2", {}, sec.section),
      el("div.stack", {}, ...sec.items.map((it) =>
        el("div", {},
          el("b", {}, it.work),
          el("span.dim", {}, " — ", it.author),
          it.note ? el("div.fine", {}, it.note) : null))))));
}

function toolsPane(ctx) {
  return el("div.card", {},
    el("h2", {}, "Tool stack"),
    el("p.fine", {}, "The AI rows move fastest — verify currency before you " +
      "commit to any of them."),
    el("div.wrap-scroll", {}, el("table", {},
      el("tbody", {}, ...ctx.state.library.tools.map((t) =>
        el("tr", {}, el("td", { style: { whiteSpace: "nowrap" } }, el("b", {}, t.domain)),
          el("td.dim", {}, t.tools)))))));
}

function glossaryPane(ctx) {
  return el("div", {},
    el("div.card", {},
      el("h2", {}, "Jargon"),
      el("div.stack", {}, ...ctx.state.library.glossary.map((g) =>
        el("div", {}, el("b", {}, g.term), " — ", el("span.dim", {}, g.definition))))),
    el("div.card", {},
      el("h2", {}, "Vocabulary deck", el("span.fine", {}, `${ctx.state.library.terms.length} terms`)),
      el("p.fine", {}, "These are the spaced-repetition cards. Every one is a " +
        "perceptual category rather than trivia."),
      ...["visual", "audio", "meta"].map((d) => el("details.acc", {},
        el("summary", {}, d, " ", el("span.fine", {},
          `${ctx.state.library.terms.filter((t) => t.domain === d).length}`)),
        el("div", {}, el("div.stack", {},
          ...ctx.state.library.terms.filter((t) => t.domain === d).map((t) =>
            el("div", {}, el("b", {}, t.term), " — ", el("span.dim", {}, t.definition)))))))));
}

// ------------------------------------------------------------------ search

function searchResults(ctx, q, progress, notes) {
  const needle = q.toLowerCase();
  const hit = (s) => String(s || "").toLowerCase().includes(needle);
  const wrap = el("div");

  const lessons = [];
  for (const mod of ctx.state.curriculum.modules) {
    for (const les of mod.lessons) {
      if (hit(les.title) || les.key.some(hit) || (les.pulls || []).some(hit) || hit(les.practice)) {
        lessons.push(les);
      }
    }
  }
  if (lessons.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Theory", el("span.fine", {}, `${lessons.length}`)),
      el("div.stack", {}, ...lessons.map((l) => lessonRow(ctx, l, progress, notes, false)))));
  }

  const effects = ctx.state.library.catalog
    .map((f) => ({ f, items: f.items.filter(hit) }))
    .filter((x) => x.items.length || hit(x.f.family));
  if (effects.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Effects"),
      el("div.stack", {}, ...effects.map((x) =>
        el("div", {}, el("b", {}, x.f.family), " ", el("span.tag", {}, x.f.primitive),
          el("div.chips", { style: { marginTop: ".3rem" } },
            ...(x.items.length ? x.items : x.f.items).map((i) => el("span.chip", {}, i))))))));
  }

  const genres = ctx.state.library.genres.filter((g) => hit(g.label) || hit(g.features));
  if (genres.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Genres"),
      el("div.stack", {}, ...genres.map((g) =>
        el("div", {}, el("b", {}, g.label), " — ", el("span.dim", {}, g.features))))));
  }

  const terms = ctx.state.library.terms.filter((t) => hit(t.term) || hit(t.definition));
  if (terms.length) {
    wrap.append(el("div.card", {},
      el("h2", {}, "Vocabulary"),
      el("div.stack", {}, ...terms.map((t) =>
        el("div", {}, el("b", {}, t.term), " — ", el("span.dim", {}, t.definition))))));
  }

  if (!wrap.childElementCount) {
    wrap.append(el("div.card.empty", {}, `Nothing matches "${q}".`));
  }
  return wrap;
}

// ------------------------------------------------------------------ course
//
// The eight modules of "The Mathematics Behind Graphics", served from
// docs/course as plain markdown. Figures the app has a live version of are
// swapped in where the text already references them; anything else falls back
// to the generated file, so the documents read identically outside the app.

let courseTeardowns = [];

/** Swapping the pane's contents leaves the window where it was, which lands you
    in the middle of whatever replaced it. */
function scrollTop() {
  window.scrollTo(0, 0);
}

async function coursePane(ctx, body) {
  for (const t of courseTeardowns) t();
  courseTeardowns = [];
  // Owns its own clearing: the tab switch clears before calling, but "‹ Modules"
  // calls straight back in, and appending there put the list below the still
  // open document — thousands of pixels down, so the button looked dead.
  clear(body);
  scrollTop();

  const index = await api("/api/course");
  if (index.missing || !index.modules.length) {
    body.append(el("div.card.empty", {},
      "No course documents found. Drop the module markdown into " +
      "docs/course/ and reload."));
    return;
  }

  const list = el("div.card", {},
    el("h2", {}, "The Mathematics Behind Graphics"),
    el("p.dim", {}, "From photons to fragment shaders. Almost everything here " +
      "is either an integral of a signal against a basis, or a change of " +
      "basis — if a module feels like arbitrary trivia, ask which of the two " +
      "it is."),
    el("div.stack", {}, ...index.modules.map((m) =>
      el("button.drill-card", { onclick: () => openDoc(m.slug) },
        el("b", {}, m.title),
        el("div.row.tight", { style: { marginTop: ".3rem" } },
          m.maths ? el("span.fine", {}, m.maths) : null,
          el("span.fine", {}, `${m.words} words`),
          liveCount(m.slug) ? el("span.tag.good", {}, `${liveCount(m.slug)} live figures`) : null)))),
    index.readme ? el("button.ghost", { style: { marginTop: ".6rem" },
      onclick: () => openDoc("README") }, "Course README") : null);
  body.append(list);

  function liveCount(slug) {
    return (MODULE_EXTRAS[slug] || []).length;
  }

  async function openDoc(slug) {
    for (const t of courseTeardowns) t();
    courseTeardowns = [];
    clear(body);
    scrollTop();
    body.append(el("p.muted", {}, "Loading…"));

    let text;
    try { text = await api(`/api/course/doc/${slug}`, { raw: true }).then((r) => r.text()); }
    catch (e) { clear(body); body.append(el("div.card", {}, el("p.err", {}, e.message))); return; }

    // Figures are mounted only once the tree is in the document. Mounting
    // into a detached node gives every canvas a width of zero, and an exact
    // figure sized from nothing is not a figure.
    const pending = [];
    const rendered = renderMarkdown(text, {
      onFigure: (path, alt) => {
        // Assets ship as light/dark pairs; the live version is one figure that
        // suits either, so the theme suffix is not part of its identity.
        const file = path.split("/").pop().replace(/\.(svg|png)$/, "");
        const id = file.replace(/-(dark|light)$/, "");
        const fig = FIGURE_BY_ID[id] || FIGURE_BY_ID[file];
        if (!fig) return null;
        const holder = el("div");
        pending.push([holder, fig]);
        return holder;
      },
      onLink: (target) => openDoc(target),
    });

    // Figures the app can draw that this module's prose predates.
    const extras = (MODULE_EXTRAS[slug] || []).filter((id) => !text.includes(id));
    const extraBox = el("div");
    if (extras.length) {
      extraBox.append(el("div.card", {},
        el("h2", {}, "Interactive figures for this module"),
        el("p.fine", {}, "These are not referenced in the text — the documents " +
          "list them as figures still to be generated. They are computed live " +
          "here rather than shipped as images."),
        ...extras.map((id) => {
          const holder = el("div");
          pending.push([holder, FIGURE_BY_ID[id]]);
          return holder;
        })));
    }

    clear(body);
    body.append(
      el("div.card.tight", {},
        el("div.row.tight", {},
          el("button.ghost", { onclick: () => coursePane(ctx, body) }, "‹ Modules"),
          el("span.fine", {}, "maths is transliterated to Unicode, not typeset"))),
      el("div.card", {}, rendered),
      extraBox);
    for (const [holder, fig] of pending) courseTeardowns.push(mountFigure(holder, fig));
    window.scrollTo(0, 0);
  }
}
