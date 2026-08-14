// Progress. Perceptual learning shows up as accuracy holding steady while the
// difficulty climbs, so accuracy alone would look flat and discouraging —
// every number here is reported next to the level it was earned at.

import { el, api, pct, hhmm, relTime } from "./ui.js";

export async function progressView(ctx) {
  const [stats, vocab, practice, pieces, arts, prog] = await Promise.all([
    api("/api/drills/stats"),
    api("/api/vocab/stats"),
    api("/api/practice"),
    api("/api/pieces"),
    api("/api/articulation"),
    api("/api/progress"),
  ]);
  const root = el("div");

  const shipped = pieces.pieces.filter((p) => p.status === "shipped");
  const totalMin = practice.practice.reduce((a, p) => a + p.minutes, 0);
  const totalTrials = stats.per_drill.reduce((a, d) => a + d.total, 0);
  const lessonCount = Object.keys(ctx.state.lessonTitles).length;

  root.append(el("div.card", {},
    el("h2", {}, "Where you are"),
    el("div.kpi", {},
      el("div", {}, el("b", {}, shipped.length), el("span", {}, "pieces shipped")),
      el("div", {}, el("b", {}, totalTrials), el("span", {}, "drill trials")),
      el("div", {}, el("b", {}, hhmm(totalMin)), el("span", {}, "logged practice")),
      el("div", {}, el("b", {}, `${vocab.mature}/${vocab.total}`), el("span", {}, "vocabulary mature")),
      el("div", {}, el("b", {}, arts.reps.length), el("span", {}, "articulation reps")),
      el("div", {}, el("b", {}, `${prog.progress.length}/${lessonCount}`), el("span", {}, "theory items touched")))));

  // ---------------------------------------------------------- weekly rhythm
  const weeks = weekBuckets(pieces.pieces, practice.practice, stats.series, 16);
  const weekHead = el("thead", {}, el("tr", {},
    el("th", {}, "Week"), el("th", {}, "Shipped"),
    el("th.num", {}, "Practice"), el("th.num", {}, "Trials"), el("th", {}, "")));
  const weekRows = weeks.map((w) => el("tr", {},
    el("td.mono", {}, w.id),
    el("td", {}, w.pieces.length
      ? el("span.tag.good", {}, w.pieces.map((p) => p.title || "(untitled)").join(", "))
      : el("span.tag", {}, "—")),
    el("td.num", {}, w.minutes ? hhmm(w.minutes) : "—"),
    el("td.num", {}, w.trials || "—"),
    el("td", {}, el("div.bar" + (w.pieces.length ? " good" : ""), {},
      el("i", { style: { width: `${Math.min(100, (w.minutes / 300) * 100)}%` } })))));
  root.append(el("div.card", {},
    el("h2", {}, "The last 16 weeks"),
    el("p.fine", {}, "One finished piece per week is the rule the whole thing " +
      "hangs off. Gaps are information, not shame."),
    el("div.wrap-scroll", {},
      el("table", {}, weekHead, el("tbody", {}, ...weekRows)))));

  // ---------------------------------------------------------- discrimination
  const dims = {};
  for (const d of ctx.state.curriculum.drills) {
    const s = stats.per_drill.find((x) => x.drill === d.id);
    (dims[d.dim] ||= { drills: [], correct: 0, total: 0, level: 0, craft: d.craft });
    dims[d.dim].drills.push({ ...d, stat: s });
    if (s) {
      dims[d.dim].correct += s.correct;
      dims[d.dim].total += s.total;
      dims[d.dim].level = Math.max(dims[d.dim].level, s.level);
    }
  }

  root.append(el("div.card", {},
    el("h2", {}, "Discrimination by dimension"),
    el("p.fine", {}, "Accuracy holding steady while the level climbs is the " +
      "shape improvement actually has. A dimension you have never touched is " +
      "not a weakness yet — it is just unmeasured."),
    el("div.g2.grid", {}, ...Object.entries(dims).map(([dim, d]) => {
      const p = pct(d.correct, d.total);
      return el("div.card.tight", {},
        el("div.spread", {},
          el("b", {}, ctx.state.curriculum.dimensions[dim] || dim),
          el("span.tag " + d.craft, {}, d.craft === "audio" ? "ear" : "eye")),
        d.total
          ? el("div", {},
              el("div.spread", { style: { margin: ".3rem 0" } },
                el("span.mono", {}, `${p}% of ${d.total}`),
                el("span.fine", {}, `up to level ${d.level}`)),
              el("div.bar " + (p >= 75 ? "good" : p >= 55 ? "warm" : ""), {},
                el("i", { style: { width: `${p}%` } })))
          : el("p.fine", {}, "not started"),
        el("div.chips", { style: { marginTop: ".4rem" } },
          ...d.drills.map((dr) => el("span.chip", {},
            dr.title, dr.stat ? ` ${dr.stat.pct}%` : ""))));
    }))));

  // ---------------------------------------------------------- per drill trend
  if (stats.per_drill.length) {
    root.append(el("div.card", {},
      el("h2", {}, "Per drill"),
      el("div.wrap-scroll", {}, el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "Drill"), el("th.num", {}, "Rounds"), el("th.num", {}, "All time"),
          el("th.num", {}, "Recent"), el("th.num", {}, "Level"), el("th", {}, "Last"))),
        el("tbody", {}, ...stats.per_drill
          .sort((a, b) => b.rounds - a.rounds)
          .map((d) => {
            const meta = ctx.state.curriculum.drills.find((x) => x.id === d.drill);
            const delta = d.recent_pct === null ? null : d.recent_pct - d.pct;
            return el("tr", {},
              el("td", {}, meta?.title || d.drill),
              el("td.num", {}, d.rounds),
              el("td.num", {}, `${d.pct}%`),
              el("td.num", {}, d.recent_pct === null ? "—"
                : el("span", { class: delta >= 0 ? "tag good" : "tag bad" },
                    `${d.recent_pct}% ${delta > 0 ? "▲" : delta < 0 ? "▼" : ""}`)),
              el("td.num", {}, d.level),
              el("td", {}, el("span.fine", {}, relTime(d.last))));
          }))))));
  }

  // ---------------------------------------------------------- theory pulled
  const pulled = prog.progress.filter((p) => p.pulled_by);
  if (pulled.length) {
    root.append(el("div.card", {},
      el("h2", {}, "Theory you pulled in"),
      el("p.fine", {}, "Each of these arrived because something you made broke " +
        "in a specific way. That is the only order worth reading in."),
      el("div.stack", {}, ...pulled.map((p) => el("div.card.tight", {},
        el("div.spread", {},
          el("b", {}, ctx.state.lessonTitles[p.slug] || p.slug),
          el("div.row.tight", {},
            el("span.tag " + (p.status === "done" ? "good" : ""), {}, p.status),
            p.confidence ? el("span.tag", {}, `${p.confidence}/5`) : null)),
        el("div.pull", { style: { marginTop: ".3rem" } }, p.pulled_by))))));
  }

  return root;
}

function weekBuckets(pieces, practice, series, n) {
  const out = [];
  const now = new Date();
  for (let i = 0; i < n; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() - i * 7);
    out.push({ id: isoWeek(d), pieces: [], minutes: 0, trials: 0, start: startOfWeek(d) });
  }
  const byId = Object.fromEntries(out.map((w) => [w.id, w]));
  for (const p of pieces) {
    if (p.status === "shipped" && byId[p.week]) byId[p.week].pieces.push(p);
  }
  for (const s of practice) {
    const w = byId[isoWeek(new Date(s.day))];
    if (w) w.minutes += s.minutes;
  }
  for (const a of series) {
    const w = byId[isoWeek(new Date(a.created * 1000))];
    if (w) w.trials += a.total;
  }
  return out;
}

function startOfWeek(d) {
  const c = new Date(d);
  const day = (c.getDay() + 6) % 7;
  c.setDate(c.getDate() - day);
  return c;
}

function isoWeek(d) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date - yearStart) / 86400000 + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}
