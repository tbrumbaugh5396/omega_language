// Shell: auth gate, navigation, routing, and the Today dashboard.
//
// Today's job is to make the week's obligation unavoidable and put the next
// drill one click away. Everything else is secondary and lives behind a tab.

import { $, $$, el, clear, api, token, toast, modal, closeModal, relDay, today,
         hhmm, confirmDialog } from "./ui.js";
import { makeView } from "./make.js";
import { studioView } from "./studio.js";
import { trainView } from "./train.js";
import { labView } from "./labs.js";
import { analyzeView } from "./analyze.js";
import { sandboxView } from "./sandbox.js";
import { libraryView } from "./library.js";
import { progressView } from "./progress.js";

const state = {
  user: null,
  curriculum: null,
  library: null,
  prefs: {},
  drillLevels: {},
  lessonTitles: {},
};

const VIEWS = [
  ["today", "Today", todayView],
  ["make", "Make", makeView],
  ["studio", "Studio", studioView],
  ["train", "Train", trainView],
  ["lab", "Lab", labView],
  ["analyze", "Analyze", analyzeView],
  ["sandbox", "Sandbox", sandboxView],
  ["library", "Library", libraryView],
  ["progress", "Progress", progressView],
];

let current = "today";

const ctx = {
  state,
  sub: null,
  arg: null,
  go(view, sub = null, arg = null) {
    current = view;
    ctx.sub = sub;
    ctx.arg = arg;
    // The third segment matters: #studio/canvas/12 has to survive a reload,
    // because an open document is the thing you most want to come back to.
    location.hash = view + (sub ? `/${sub}` : "") + (arg ? `/${arg}` : "");
    renderView();
  },
};

// ------------------------------------------------------------------ boot

async function boot() {
  if (!token.get()) return showGate();
  try {
    const me = await api("/api/auth/me");
    state.user = me.user;
  } catch {
    return showGate();
  }
  await loadContent();
  showApp();
}

async function loadContent() {
  const [cur, lib, prefs] = await Promise.all([
    api("/api/curriculum"),
    api("/api/library"),
    api("/api/kv/prefs").catch(() => ({ value: {} })),
  ]);
  state.curriculum = cur;
  state.library = lib;
  state.prefs = prefs.value || {};
  state.drillLevels = state.prefs.drillLevels || {};
  state.lessonTitles = {};
  for (const mod of cur.modules) {
    for (const les of mod.lessons) state.lessonTitles[les.slug] = les.title;
  }
}

function showGate() {
  $("#gate").hidden = false;
  $("#app").hidden = true;
}

function showApp() {
  $("#gate").hidden = true;
  $("#app").hidden = false;
  $("#who-btn").textContent = state.user.display_name || state.user.username;
  buildNav();
  const [hash, sub, arg] = (location.hash.replace("#", "") || "today").split("/");
  current = VIEWS.some((v) => v[0] === hash) ? hash : "today";
  ctx.sub = sub || null;
  ctx.arg = arg || null;
  renderView();
}

function buildNav() {
  const nav = $("#nav");
  clear(nav);
  for (const [id, label] of VIEWS) {
    nav.append(el("button", {
      class: id === current ? "on" : "",
      "data-view": id,
      onclick: () => ctx.go(id),
    }, label));
  }
}

async function renderView() {
  const view = $("#view");
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === current));
  clear(view);
  view.append(el("p.muted", {}, "Loading…"));
  const fn = VIEWS.find((v) => v[0] === current)?.[2] || todayView;
  try {
    const node = await fn(ctx);
    clear(view);
    view.append(node);
    window.scrollTo(0, 0);
  } catch (e) {
    clear(view);
    view.append(el("div.card", {}, el("h2", {}, "That view failed to load"),
      el("p.err", {}, String(e.message || e)),
      el("button", { onclick: renderView }, "Try again")));
  }
}

// ------------------------------------------------------------------ today

async function todayView(ctx) {
  const t = await api("/api/today");
  const root = el("div");

  // ---- the week
  const piece = t.piece;
  const overdue = t.deadline < today();
  const weekCard = el("div.card", {},
    el("div.spread", {},
      el("h2", {}, "This week", el("span.tag", {}, t.week)),
      el("span.tag " + (overdue ? "bad" : ""), {}, `due ${relDay(t.deadline)}`)));

  if (!piece) {
    weekCard.append(
      el("p.dim", {}, "No brief accepted yet. One finished piece per week, no " +
        "exceptions — the escalation is tied to what you ship, not to how long " +
        "you have been here."),
      el("button.primary", { onclick: () => ctx.go("make", "Pieces") }, "Get this week's brief"));
  } else if (piece.status === "shipped") {
    weekCard.append(
      el("p", {}, el("b", {}, piece.title || "(untitled)"), " — shipped."),
      piece.pm_reads ? el("div.pull", {}, el("b", {}, "Reads wrong: "), piece.pm_reads) : null,
      piece.pm_slug
        ? el("button", { onclick: () => ctx.go("library", "Theory", piece.pm_slug) },
            `Pull the theory: ${state.lessonTitles[piece.pm_slug] || piece.pm_slug}`)
        : null);
  } else {
    weekCard.append(
      el("h3", {}, piece.title || piece.brief?.form || "In flight"),
      piece.brief?.constraint ? el("div.pull", {}, el("b", {}, "Constraint: "), piece.brief.constraint) : null,
      piece.brief?.primitive ? el("div.pull", {}, el("b", {}, "Practising: "), piece.brief.primitive) : null,
      !piece.rubric
        ? el("p.fine", { style: { color: "var(--warm)" } },
            "No rubric yet. Write how you would grade it before you make it.")
        : null,
      el("div.row", { style: { marginTop: ".6rem" } },
        el("button.primary", { onclick: () => ctx.go("make", "Pieces") }, "Open the piece")));
  }
  root.append(weekCard);

  // ---- the daily rep
  root.append(el("div.card", {},
    el("h2", {}, "Today's reps"),
    el("p.fine", {}, "Ten focused minutes beats an hour on Sunday. These are " +
      "the drills you have touched least."),
    el("div.drill-list", {}, ...t.cold_drills.map((d) => {
      const meta = state.curriculum.drills.find((x) => x.id === d.id);
      return el("button.drill-card", { onclick: () => ctx.go("train", "Drills") },
        el("b", {}, d.title),
        el("div.row.tight", { style: { marginTop: ".3rem" } },
          el("span.tag " + d.craft, {}, d.craft === "audio" ? "ear" : "eye"),
          el("span.tag", {}, state.curriculum.dimensions[d.dim] || d.dim),
          d.pct !== null ? el("span.tag " + (d.pct >= 75 ? "good" : ""), {}, `${d.pct}%`)
                         : el("span.tag", {}, "new")),
        meta ? el("p", {}, meta.blurb) : null);
    })),
    t.vocab_due
      ? el("div.row", { style: { marginTop: ".8rem" } },
          el("button", { onclick: () => ctx.go("train", "Vocabulary") },
            `${t.vocab_due} vocabulary cards due`),
          el("span.fine", {}, `${t.vocab_seen} of ${t.vocab_total} terms seen`))
      : el("p.fine", { style: { marginTop: ".8rem" } },
          `Vocabulary: nothing due. ${t.vocab_seen} of ${t.vocab_total} terms started.`)));

  // ---- the week's practice
  const days = new Set(t.practice_days);
  const last14 = Array.from({ length: 14 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (13 - i));
    return d.toISOString().slice(0, 10);
  });
  root.append(el("div.card", {},
    el("div.spread", {},
      el("h2", {}, "Practice"),
      el("span.fine", {}, `${hhmm(t.minutes_week)} in the last 7 days`)),
    el("div.timeline", {}, ...last14.map((d) =>
      el("i", { class: days.has(d) ? "" : "none", title: d,
                style: { height: days.has(d) ? "100%" : "22%" } }))),
    el("div.row", { style: { marginTop: ".7rem" } },
      el("button", { onclick: () => quickLog(ctx) }, "Log a session"),
      el("button.ghost", { onclick: () => ctx.go("make", "Practice") }, "All sessions"),
      el("button.ghost", { onclick: () => ctx.go("analyze") }, "Analyse a reference"))));

  // ---- recent
  if (t.recent_pieces.length) {
    root.append(el("div.card", {},
      el("h2", {}, "Recent pieces"),
      el("div.stack", {}, ...t.recent_pieces.map((p) => el("div.spread", {},
        el("div", {},
          el("b", {}, p.title || "(untitled)"),
          el("div.row.tight", { style: { marginTop: ".2rem" } },
            el("span.tag", {}, p.week),
            el("span.tag " + (p.status === "shipped" ? "good" : ""), {}, p.status))),
        el("button.ghost", { onclick: () => ctx.go("make", "Pieces") }, "Open"))))));
  }

  // ---- the thesis, kept in view
  root.append(el("div.card", {},
    el("p.fine", {}, "Intuition is amortized search over trained perceptual " +
      "features. Perception first, volume second, articulation as its own " +
      "track, theory pulled by friction. LLMs collapse the cost of the " +
      "symbolic half of this work and leave the perceptual half untouched — " +
      "which makes taste more of the bottleneck, not less.")));

  return root;
}

function quickLog(ctx) {
  const focus = el("input", { placeholder: "the isolated sub-skill" });
  const minutes = el("input", { type: "number", value: 30, min: 0 });
  const track = el("select", {}, ...state.curriculum.tracks.map((t) =>
    el("option", { value: t.id, selected: t.id === "tools" }, t.title)));
  const tool = el("input", { placeholder: "tool (optional)" });
  modal(el("h2", {}, "Log a session"),
    el("label", {}, "Focus", focus),
    el("div.row", {},
      el("label", { style: { marginBottom: 0 } }, "Track", track),
      el("label", { style: { marginBottom: 0 } }, "Minutes", minutes),
      el("label", { style: { marginBottom: 0 } }, "Tool", tool)),
    el("div.row", { style: { justifyContent: "flex-end", marginTop: ".7rem" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          if (!focus.value.trim()) { toast("What did you work on?"); return; }
          await api("/api/practice", {
            method: "POST",
            body: { day: today(), track: track.value, tool: tool.value,
                    focus: focus.value, minutes: +minutes.value || 0, rating: 3 },
          });
          closeModal();
          toast("Logged");
          renderView();
        },
      }, "Log it")));
}

// ------------------------------------------------------------------ auth UI

function initGate() {
  const form = $("#auth-form");
  const err = $("#auth-err");
  let mode = "login";

  form.querySelectorAll(".tabs-mini button").forEach((b) => {
    b.onclick = () => {
      mode = b.dataset.mode;
      form.querySelectorAll(".tabs-mini button").forEach((x) => x.classList.toggle("on", x === b));
      form.querySelectorAll(".signup-only").forEach((x) => { x.hidden = mode !== "signup"; });
      $("#auth-go").textContent = mode === "signup" ? "Create account" : "Sign in";
      form.password.autocomplete = mode === "signup" ? "new-password" : "current-password";
      err.hidden = true;
    };
  });

  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hidden = true;
    const body = {
      username: form.username.value.trim(),
      password: form.password.value,
      ...(mode === "signup" ? { display_name: form.display_name.value.trim() } : {}),
    };
    try {
      const res = await api(`/api/auth/${mode}`, { method: "POST", body });
      token.set(res.token);
      state.user = res.user;
      await loadContent();
      showApp();
    } catch (e2) {
      err.textContent = e2.message;
      err.hidden = false;
    }
  };
}

function initMenu() {
  const btn = $("#who-btn"), menu = $("#who-menu");
  btn.onclick = () => { menu.hidden = !menu.hidden; };
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) menu.hidden = true;
  });
  menu.onclick = async (e) => {
    const act = e.target.dataset?.act;
    if (!act) return;
    menu.hidden = true;
    if (act === "logout") {
      await api("/api/auth/logout", { method: "POST" }).catch(() => {});
      token.clear();
      location.reload();
    } else if (act === "profile") {
      profileDialog();
    } else if (act === "backup") {
      const res = await api("/api/backup", { raw: true });
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `av-trainer-${today()}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } else if (act === "restore") {
      const input = el("input", { type: "file", accept: "application/json" });
      input.onchange = async () => {
        const f = input.files[0];
        if (!f) return;
        if (!await confirmDialog("Restore from this file?",
          "It replaces the tables present in the backup.")) return;
        try {
          const payload = JSON.parse(await f.text());
          await api("/api/restore", { method: "POST", body: payload });
          toast("Restored");
          renderView();
        } catch (e2) { toast(e2.message); }
      };
      input.click();
    } else if (act === "seed") {
      const r = await api("/api/seed", { method: "POST" });
      const n = Object.values(r).filter((v) => typeof v === "number").reduce((a, b) => a + b, 0);
      toast(n ? "Starter content loaded" : "You already have content");
      renderView();
    }
  };
}

function profileDialog() {
  const name = el("input", { value: state.user.display_name || "" });
  const cur = el("input", { type: "password", autocomplete: "current-password" });
  const next = el("input", { type: "password", autocomplete: "new-password" });
  modal(el("h2", {}, "Profile"),
    el("label", {}, "Display name", name),
    el("p.fine", {}, "Change password (leave blank to keep it)"),
    el("label", {}, "Current password", cur),
    el("label", {}, "New password", next),
    el("div.row", { style: { justifyContent: "flex-end" } },
      el("button", { onclick: closeModal }, "Cancel"),
      el("button.primary", {
        onclick: async () => {
          try {
            const res = await api("/api/auth/profile", {
              method: "PATCH",
              body: { display_name: name.value,
                      ...(next.value ? { password: next.value, current_password: cur.value } : {}) },
            });
            state.user = res.user;
            $("#who-btn").textContent = res.user.display_name || res.user.username;
            closeModal();
            toast("Saved");
          } catch (e) { toast(e.message); }
        },
      }, "Save")));
}

// ------------------------------------------------------------------ start

window.addEventListener("hashchange", () => {
  const [hash, sub, arg] = (location.hash.replace("#", "") || "today").split("/");
  if (!VIEWS.some((v) => v[0] === hash)) return;
  if (hash === current && (sub || null) === ctx.sub && (arg || null) === ctx.arg) return;
  current = hash;
  ctx.sub = sub || null;
  ctx.arg = arg || null;
  renderView();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

initGate();
initMenu();
boot();
