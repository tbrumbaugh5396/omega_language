/* MacroKitchen — frontend. Vanilla JS, no dependencies.
   Meal planning, meal prep, nutrition tracking, shopping lists, and a diet
   log with weight, water and calorie targets. All data lives on the local
   server; the frontend computes all calorie math from your profile. */
"use strict";

// ============================================================ helpers

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let TOKEN = localStorage.getItem("kitchen_token") || "";
let STATE = null;

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (TOKEN) opts.headers["Authorization"] = "Bearer " + TOKEN;
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) { signOutLocal(); throw new Error("signed out"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function toast(msg) {
  let t = $("#toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}

function openModal(html) {
  closeModal();
  const back = document.createElement("div");
  back.id = "modal-back";
  back.innerHTML = `<div id="modal" class="card">${html}</div>`;
  back.addEventListener("click", (e) => { if (e.target === back) closeModal(); });
  document.body.appendChild(back);
  return back;
}
function closeModal() { $("#modal-back")?.remove(); }

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function addDays(dayStr, n) {
  const d = new Date(dayStr + "T12:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function mondayOf(dayStr) {
  const d = new Date(dayStr + "T12:00:00");
  return addDays(dayStr, -((d.getDay() + 6) % 7));
}
function niceDay(dayStr, withYear = false) {
  const d = new Date(dayStr + "T12:00:00");
  const o = { weekday: "short", month: "short", day: "numeric" };
  if (withYear) o.year = "numeric";
  return d.toLocaleDateString(undefined, o);
}
const r0 = (n) => Math.round(n || 0);
const r1 = (n) => Math.round((n || 0) * 10) / 10;
const fmt1 = (n) => { const v = r1(n); return v === Math.round(v) ? String(Math.round(v)) : v.toFixed(1); };

async function reload(renderOnly = null) {
  STATE = await api("/api/state");
  if (renderOnly) renderOnly();
  else renderAll();
}

// ============================================================ constants

const SLOTS = ["breakfast", "lunch", "dinner", "snack"];
const SLOT_LABEL = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snacks" };
const CATEGORIES = ["produce", "protein", "dairy", "grains", "pantry", "frozen", "beverages", "spices", "other"];
const CAT_LABEL = {
  produce: "Produce", protein: "Protein", dairy: "Dairy", grains: "Grains & starches",
  pantry: "Pantry", frozen: "Frozen", beverages: "Beverages", spices: "Spices", other: "Other",
};
const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack", "any"];
const ACTIVITY = [
  ["1.2", "Sedentary — desk job, little exercise"],
  ["1.375", "Light — exercise 1–3 days/week"],
  ["1.55", "Moderate — exercise 3–5 days/week"],
  ["1.725", "Active — hard exercise 6–7 days/week"],
  ["1.9", "Athlete — physical job + training"],
];
const GLASS_ML = 250;   // one glass on the water tracker
const KCAL_PER_KG = 7700;
const LB_PER_KG = 2.20462;

// ============================================================ profile & math

const DEFAULT_PROFILE = {
  units: "imperial", sex: "male", birth_year: 1990, height_cm: 175,
  activity: 1.55, goal: "maintain", rate_kg_week: 0.45, goal_weight_kg: null,
  protein_pct: 30, carbs_pct: 40, fat_pct: 30, water_goal_ml: 2500,
  fiber_goal_g: 30, sodium_limit_mg: 2300, sugar_limit_g: 50,
  tdee_override: null,   // observed maintenance, when the user adopts it
};

function getProfile() {
  let p = {};
  try { p = JSON.parse(STATE.kv?.profile || "{}"); } catch { p = {}; }
  return { ...DEFAULT_PROFILE, ...p };
}
async function saveProfile(patch) {
  const p = { ...getProfile(), ...patch };
  await api("/api/kv/profile", "PUT", { value: JSON.stringify(p) });
  STATE.kv.profile = JSON.stringify(p);
}

function latestWeightKg() {
  const w = STATE.weight_log;
  return w.length ? w[w.length - 1].kg : null;
}

// Everything the app derives from the profile, in one place.
function calcTargets() {
  const p = getProfile();
  const kg = latestWeightKg();
  const age = Math.max(10, new Date().getFullYear() - (p.birth_year || 1990));
  let bmr = null, tdee = null, target = null, adjust = 0;
  const override = p.tdee_override && p.tdee_override > 500 ? p.tdee_override : null;
  if (kg) {
    bmr = 10 * kg + 6.25 * (p.height_cm || 175) - 5 * age + (p.sex === "female" ? -161 : 5);
    tdee = bmr * (parseFloat(p.activity) || 1.55);
  }
  if (override) tdee = override;   // observed maintenance beats the formula
  if (tdee) {
    adjust = p.goal === "maintain" ? 0 :
      (p.goal === "lose" ? -1 : 1) * (p.rate_kg_week || 0) * KCAL_PER_KG / 7;
    target = Math.max(1000, tdee + adjust);
  }
  const t = target || 2000;
  return {
    profile: p, kg, age, bmr, tdee, target, adjust, override,
    protein_g: t * (p.protein_pct / 100) / 4,
    carbs_g: t * (p.carbs_pct / 100) / 4,
    fat_g: t * (p.fat_pct / 100) / 9,
    hasProfile: !!kg || !!override,
  };
}

// Observed maintenance: mean logged intake minus the calories represented by
// the weight slope over the same window. Needs honest logging + weigh-ins.
function observedTDEE() {
  const w = STATE.weight_log;                      // sorted by day asc
  if (w.length < 4) return null;
  const dayN = (s) => Math.floor(Date.parse(s + "T12:00:00") / 86400000);
  const cutoff = addDays(todayStr(), -35);
  const win = w.filter((x) => x.day >= cutoff);
  if (win.length < 4) return null;
  const head = win.slice(0, 3), tail = win.slice(-3);
  const avg = (xs, f) => xs.reduce((a, x) => a + f(x), 0) / xs.length;
  const d0 = avg(head, (x) => dayN(x.day)), d1 = avg(tail, (x) => dayN(x.day));
  const span = d1 - d0;
  if (span < 12) return null;                      // need a real stretch of time
  const slope = (avg(tail, (x) => x.kg) - avg(head, (x) => x.kg)) / span; // kg/day
  const byDay = {};
  for (const e of STATE.food_log) byDay[e.day] = (byDay[e.day] || 0) + e.cal;
  const cals = Object.entries(byDay)
    .filter(([d, c]) => dayN(d) >= d0 && dayN(d) <= d1 && c >= 800)
    .map(([, c]) => c);                            // <800 kcal ≈ partial log; skip
  if (cals.length < 10) return null;
  const intake = cals.reduce((a, c) => a + c, 0) / cals.length;
  const tdee = intake - slope * KCAL_PER_KG;
  if (tdee < 800 || tdee > 6000) return null;
  return { tdee, days: Math.round(span), logged: cals.length };
}

// unit display helpers
const isImperial = () => getProfile().units === "imperial";
const wShow = (kg) => kg == null ? "—" : (isImperial() ? `${fmt1(kg * LB_PER_KG)} lb` : `${fmt1(kg)} kg`);
const wToKg = (v) => isImperial() ? v / LB_PER_KG : v;
const wUnit = () => isImperial() ? "lb" : "kg";
const mlShow = (ml) => isImperial() ? `${r0(ml / 29.5735)} oz` : `${r0(ml)} ml`;

function ingredientById(id) { return STATE.ingredients.find((i) => i.id === id); }
function recipeById(id) { return STATE.recipes.find((r) => r.id === id); }
function itemsOf(recipeId) { return STATE.recipe_items.filter((i) => i.recipe_id === recipeId); }

// per-ONE-serving macros of a recipe, from its ingredient lines
function recipeMacros(recipe) {
  const tot = { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sodium: 0, sugar: 0 };
  for (const it of itemsOf(recipe.id)) {
    const ing = ingredientById(it.ingredient_id);
    if (!ing) continue;
    for (const k of Object.keys(tot)) tot[k] += (ing[k] || 0) * it.qty;
  }
  const s = recipe.servings || 1;
  for (const k of Object.keys(tot)) tot[k] /= s;
  return tot;
}

function planEntryInfo(e) {
  // -> {name, perServing:{cal,protein,carbs,fat}} for a plan entry
  if (e.recipe_id) {
    const r = recipeById(e.recipe_id);
    if (r) return { name: r.name, per: recipeMacros(r) };
  }
  if (e.ingredient_id) {
    const ing = ingredientById(e.ingredient_id);
    if (ing) return { name: ing.name, per: { cal: ing.cal, protein: ing.protein,
      carbs: ing.carbs, fat: ing.fat, fiber: ing.fiber || 0,
      sodium: ing.sodium || 0, sugar: ing.sugar || 0 } };
  }
  return { name: e.title || "(untitled)",
    per: { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sodium: 0, sugar: 0 } };
}

function logTotals(day) {
  const tot = { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sodium: 0, sugar: 0 };
  for (const e of STATE.food_log) {
    if (e.day !== day) continue;
    tot.cal += e.cal; tot.protein += e.protein; tot.carbs += e.carbs; tot.fat += e.fat;
    tot.fiber += e.fiber || 0; tot.sodium += e.sodium || 0; tot.sugar += e.sugar || 0;
  }
  return tot;
}

// entry payload for a source with per-serving macros `per` at `s` servings
function entryFrom(per, s) {
  return { cal: r1(per.cal * s), protein: r1(per.protein * s),
    carbs: r1(per.carbs * s), fat: r1(per.fat * s),
    fiber: r1((per.fiber || 0) * s), sodium: r1((per.sodium || 0) * s),
    sugar: r1((per.sugar || 0) * s) };
}

// ---- streaks & adherence (Body tab) ----

function loggedDaySet() {
  const s = new Set();
  for (const e of STATE.food_log) if (e.cal > 0) s.add(e.day);
  return s;
}

function dayOnTarget(day, t) {
  const cal = logTotals(day).cal;
  if (cal <= 0 || !t.target) return false;
  const g = getProfile().goal;
  if (g === "lose") return cal <= t.target * 1.05;
  if (g === "gain") return cal >= t.target * 0.95;
  return Math.abs(cal - t.target) <= t.target * 0.10;
}

function streaks() {
  const logged = loggedDaySet();
  // current: count back from today (an unlogged today doesn't break it yet)
  let cur = 0, d = todayStr();
  if (!logged.has(d)) d = addDays(d, -1);
  while (logged.has(d)) { cur++; d = addDays(d, -1); }
  // best: walk the sorted distinct days
  const days = [...logged].sort();
  let best = 0, run = 0, prev = null;
  for (const x of days) {
    run = (prev && addDays(prev, 1) === x) ? run + 1 : 1;
    if (run > best) best = run;
    prev = x;
  }
  return { cur, best };
}

function waterFor(day) {
  const row = STATE.water_log.find((w) => w.day === day);
  return row ? row.ml : 0;
}

// ============================================================ auth

function signOutLocal() {
  TOKEN = "";
  localStorage.removeItem("kitchen_token");
  STATE = null;
  $("#app").hidden = true;
  $("#auth-screen").hidden = false;
}

function bindAuth() {
  let mode = "login";
  const setMode = (m) => {
    mode = m;
    $("#tab-login").classList.toggle("active", m === "login");
    $("#tab-signup").classList.toggle("active", m === "signup");
    $("#row-display").hidden = m === "login";
    $("#au-submit").textContent = m === "login" ? "Log in" : "Create account";
    $("#au-password").autocomplete = m === "login" ? "current-password" : "new-password";
    $("#auth-msg").textContent = "";
  };
  $("#tab-login").onclick = () => setMode("login");
  $("#tab-signup").onclick = () => setMode("signup");
  $("#auth-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const username = $("#au-username").value.trim();
    const password = $("#au-password").value;
    try {
      const data = mode === "login"
        ? await api("/api/auth/login", "POST", { username, password })
        : await api("/api/auth/signup", "POST",
            { username, password, display_name: $("#au-display").value.trim() });
      TOKEN = data.token;
      localStorage.setItem("kitchen_token", TOKEN);
      await enterApp();
    } catch (e) {
      $("#auth-msg").textContent = e.message;
    }
  };
}

function bindUserChip() {
  $("#user-chip").onclick = () => {
    const u = STATE.user;
    openModal(`
      <h2>${esc(u.display_name)}</h2>
      <p class="hint">@${esc(u.username)}</p>
      <label class="small muted">Display name
        <input id="pm-name" value="${esc(u.display_name)}"></label>
      <div class="row" style="margin-top:8px">
        <button class="btn small" id="pm-save">Save name</button>
      </div>
      <h3>Change password</h3>
      <input id="pm-cur" type="password" placeholder="current password" style="margin-bottom:6px">
      <input id="pm-new" type="password" placeholder="new password (6+ chars)">
      <div class="row" style="margin-top:8px">
        <button class="btn small ghost" id="pm-pass">Change password</button>
        <span class="grow"></span>
        <button class="btn small danger" id="pm-out">Log out</button>
      </div>`);
    $("#pm-save").onclick = async () => {
      try {
        await api("/api/me", "PATCH", { display_name: $("#pm-name").value });
        toast("Saved"); closeModal(); await reload();
      } catch (e) { toast(e.message); }
    };
    $("#pm-pass").onclick = async () => {
      try {
        const d = await api("/api/me/password", "POST",
          { current: $("#pm-cur").value, new: $("#pm-new").value });
        TOKEN = d.token; localStorage.setItem("kitchen_token", TOKEN);
        toast("Password changed"); closeModal();
      } catch (e) { toast(e.message); }
    };
    $("#pm-out").onclick = async () => {
      try { await api("/api/auth/logout", "POST", {}); } catch {}
      signOutLocal();
    };
  };
}

// ============================================================ shared UI bits

function macroPills(m, servings = 1) {
  return `<span class="pill">${r0(m.cal * servings)} kcal</span>
    <span class="pill p">P ${r0(m.protein * servings)}g</span>
    <span class="pill c">C ${r0(m.carbs * servings)}g</span>
    <span class="pill f">F ${r0(m.fat * servings)}g</span>`;
}

function ringSVG(frac, size = 170, color = "var(--accent)") {
  const r = (size - 18) / 2, c = 2 * Math.PI * r;
  const cl = Math.min(1, Math.max(0, frac));
  const over = frac > 1;
  return `<svg width="${size}" height="${size}">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
      stroke="var(--bg2)" stroke-width="14"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
      stroke="${over ? "var(--protein)" : color}" stroke-width="14"
      stroke-linecap="round"
      stroke-dasharray="${c * cl} ${c}" />
  </svg>`;
}

function macroBar(label, cls, eaten, goal) {
  const pct = Math.min(100, goal ? (eaten / goal) * 100 : 0);
  const over = goal && eaten > goal;
  return `<div class="mb-row">
    <div class="mb-head"><span>${label}</span>
      <span class="muted">${r0(eaten)} / ${r0(goal)} g</span></div>
    <div class="mb-track"><div class="mb-fill ${cls}${over ? " over" : ""}"
      style="width:${pct}%"></div></div>
  </div>`;
}

function accountIsEmpty() {
  return !STATE.ingredients.length && !STATE.recipes.length &&
    !STATE.food_log.length && !STATE.plan_entries.length;
}

// ============================================================ Today

function renderToday() {
  const el = $("#tab-today");
  const day = todayStr();
  const t = calcTargets();
  const eaten = logTotals(day);
  const water = waterFor(day);
  const goal = t.target || 2000;
  const remaining = goal - eaten.cal;
  const planToday = STATE.plan_entries.filter((e) => e.day === day);

  const seedCard = accountIsEmpty() ? `
    <div class="card">
      <h2>Welcome to MacroKitchen 🌱</h2>
      <p class="hint">Your account is empty. Load a starter pantry, meal-prep
        recipes and a few planned days to explore — or start from scratch on
        the Ingredients tab.</p>
      <button class="btn" id="seed-btn">Load starter content</button>
    </div>` : "";

  const profileNudge = !t.hasProfile ? `
    <div class="card notice">Add a weigh-in and check your profile on the
      <b>Targets</b> tab — then your calorie target, deficit and macro goals
      are computed for you (using ${r0(goal)} kcal as a placeholder for now).
    </div>` : "";

  const glasses = Array.from({ length: Math.max(8, Math.ceil((t.profile.water_goal_ml || 2000) / GLASS_ML)) },
    (_, i) => `<div class="glass${i < Math.round(water / GLASS_ML) ? " full" : ""}" data-i="${i}"></div>`).join("");

  el.innerHTML = `
    ${seedCard}${profileNudge}
    <div class="card">
      <div class="row spread"><h2>Today · ${niceDay(day)}</h2>
        <div class="row">
          <button class="btn small ghost" id="t-weigh">＋ Weigh-in</button>
          <button class="btn small" id="t-quicklog">＋ Log food</button>
        </div></div>
      <div class="today-hero">
        <div class="ring-wrap">${ringSVG(eaten.cal / goal)}
          <div class="ring-center">
            <div class="big">${r0(eaten.cal)}</div>
            <div class="lbl">of ${r0(goal)} kcal</div>
            <div class="lbl ${remaining < 0 ? "danger-text" : ""}">
              ${remaining >= 0 ? r0(remaining) + " left" : r0(-remaining) + " over"}</div>
          </div>
        </div>
        <div class="macro-bars">
          ${macroBar("Protein", "p", eaten.protein, t.protein_g)}
          ${macroBar("Carbs", "c", eaten.carbs, t.carbs_g)}
          ${macroBar("Fat", "f", eaten.fat, t.fat_g)}
          ${macroBar("Fiber", "fb", eaten.fiber, t.profile.fiber_goal_g)}
          <p class="small muted" style="margin:8px 0 0">
            Sodium <b class="${eaten.sodium > t.profile.sodium_limit_mg ? "danger-text" : ""}">${r0(eaten.sodium)}</b> / ${r0(t.profile.sodium_limit_mg)} mg
            &nbsp;·&nbsp; Sugar <b class="${eaten.sugar > t.profile.sugar_limit_g ? "danger-text" : ""}">${r0(eaten.sugar)}</b> / ${r0(t.profile.sugar_limit_g)} g</p>
        </div>
      </div>
    </div>

    <div class="grid2">
      <div class="card">
        <h2>Water</h2>
        <p class="hint">${mlShow(water)} of ${mlShow(t.profile.water_goal_ml)} —
          each glass is ${mlShow(GLASS_ML)}. Tap to drink, tap the last full
          one to undo.</p>
        <div class="glasses" id="t-glasses">${glasses}</div>
      </div>
      <div class="card">
        <h2>Body</h2>
        <div class="stat-row" style="grid-template-columns:1fr 1fr">
          <div class="stat"><div class="n">${wShow(t.kg)}</div>
            <div class="lbl">latest weight</div></div>
          <div class="stat"><div class="n">${t.tdee ? r0(t.tdee) : "—"}</div>
            <div class="lbl">maintenance kcal/day</div></div>
        </div>
        <p class="hint" style="margin-top:8px">
          ${t.adjust ? `Your plan: ${t.adjust < 0 ? "a deficit" : "a surplus"} of
            ${r0(Math.abs(t.adjust))} kcal/day ≈
            ${fmt1(t.profile.rate_kg_week * (isImperial() ? LB_PER_KG : 1))}
            ${wUnit()}/week ${t.adjust < 0 ? "down" : "up"}.`
          : "Goal: maintain — eat at maintenance."}</p>
      </div>
    </div>

    <div class="card">
      <h2>Today's plan</h2>
      ${planToday.length ? SLOTS.map((slot) => {
        const rows = planToday.filter((e) => e.slot === slot);
        if (!rows.length) return "";
        return `<div class="plan-slot">${SLOT_LABEL[slot]}</div>` + rows.map((e) => {
          const info = planEntryInfo(e);
          return `<div class="item row spread ${e.done ? "done" : ""}">
            <div><span class="title">${esc(info.name)}</span>
              <span class="meta"> · ${fmt1(e.servings)} serving${e.servings === 1 ? "" : "s"}
                · ${r0(info.per.cal * e.servings)} kcal</span></div>
            <div class="row">
              ${e.done ? "" : `<button class="btn small" data-logplan="${e.id}">Log it</button>`}
            </div></div>`;
        }).join("");
      }).join("") || "" : `<p class="hint">Nothing planned for today —
        build your week on the <b>Plan</b> tab.</p>`}
    </div>`;

  $("#seed-btn")?.addEventListener("click", async () => {
    try { await api("/api/seed", "POST", {}); toast("Starter content loaded"); await reload(); }
    catch (e) { toast(e.message); }
  });
  $("#t-weigh").onclick = () => weighInModal();
  $("#t-quicklog").onclick = () => addLogModal(day);
  $("#t-glasses").onclick = async (ev) => {
    const g = ev.target.closest(".glass");
    if (!g) return;
    const full = Math.round(waterFor(day) / GLASS_ML);
    const i = +g.dataset.i;
    const delta = i < full ? -GLASS_ML : GLASS_ML;
    await api("/api/water", "POST", { day, delta_ml: delta });
    await reload(renderToday);
  };
  $$("[data-logplan]", el).forEach((b) => b.onclick = async () => {
    const e = STATE.plan_entries.find((x) => x.id === +b.dataset.logplan);
    const info = planEntryInfo(e);
    await api("/api/food_log", "POST", {
      day, slot: e.slot, name: info.name, servings: e.servings,
      ...entryFrom(info.per, e.servings),
    });
    await api("/api/plan_entries/" + e.id, "PATCH", { done: 1 });
    toast("Logged");
    await reload(renderToday);
  });
}

function weighInModal() {
  const day = todayStr();
  openModal(`
    <h2>Weigh-in</h2>
    <p class="hint">One entry per day — logging again replaces it.</p>
    <div class="row">
      <input id="w-day" type="date" value="${day}" style="flex:1">
      <input id="w-val" type="number" step="0.1" min="1"
        placeholder="weight (${wUnit()})" style="flex:1">
    </div>
    <input id="w-note" placeholder="note (optional)" style="margin-top:8px">
    <div class="row" style="margin-top:12px">
      <button class="btn" id="w-save">Save</button>
    </div>`);
  $("#w-val").focus();
  $("#w-save").onclick = async () => {
    const v = parseFloat($("#w-val").value);
    if (!v) { toast("Enter a weight"); return; }
    try {
      await api("/api/weight", "POST",
        { day: $("#w-day").value, kg: wToKg(v), note: $("#w-note").value });
      toast("Weigh-in saved"); closeModal(); await reload();
    } catch (e) { toast(e.message); }
  };
}

// ============================================================ Guide

function renderGuide() {
  const el = $("#tab-guide");
  const t = calcTargets();
  const kg = t.kg || 75;
  const you = t.hasProfile;
  const bmr = t.bmr || (10 * kg + 6.25 * 175 - 5 * 35 + 5);
  const tdee = t.tdee || bmr * 1.55;
  const target = t.target || tdee;
  const scale = 130 / Math.max(tdee, target, 1);
  const rateLb = [0.25, 0.5, 0.75, 1.0];

  el.innerHTML = `
    <div class="card">
      <h2>1 · Energy balance — the whole game</h2>
      <p class="hint">Everything in nutrition sits on one relationship:
        calories in vs. calories out. Eat under what you burn and weight goes
        down; over it, up. The bars below use
        ${you ? "<b>your numbers</b> from the Targets tab" : "example numbers — fill in the Targets tab to see yours"}.</p>
      <div class="energy-scale">
        <div class="energy-col">
          <div class="energy-bar" style="height:${r0(bmr * scale)}px"></div>
          <div class="val">${r0(bmr)} kcal</div>
          <div class="lbl"><b>BMR</b> — what your body burns at complete rest
            (breathing, brain, temperature)</div>
        </div>
        <div class="energy-col">
          <div class="energy-bar" style="height:${r0(tdee * scale)}px"></div>
          <div class="val">${r0(tdee)} kcal</div>
          <div class="lbl"><b>Maintenance (TDEE)</b> —
            ${t.override ? "your observed maintenance, measured from your own logs and weigh-ins"
              : "BMR × your activity; eat this and weight holds steady"}</div>
        </div>
        <div class="energy-col">
          <div class="energy-bar ${target < tdee ? "out" : ""}" style="height:${r0(target * scale)}px"></div>
          <div class="val">${r0(target)} kcal</div>
          <div class="lbl"><b>Your daily target</b> —
            ${target === tdee ? "maintenance (goal: maintain)"
              : `${r0(Math.abs(tdee - target))} kcal ${target < tdee ? "deficit" : "surplus"} for your goal`}</div>
        </div>
      </div>
      <div class="formula">BMR (Mifflin–St Jeor) =
        10 × <b>weight kg</b> + 6.25 × <b>height cm</b> − 5 × <b>age</b> ±
        (men +5 / women −161)</div>
      <div class="formula">Maintenance = BMR × activity (1.2 – 1.9) &nbsp;·&nbsp;
        Target = maintenance ± your rate</div>
    </div>

    <div class="card">
      <h2>2 · Deficits, in real units</h2>
      <p class="hint">A kilogram of body fat stores ≈ 7 700 kcal (a pound ≈
        3 500). A steady daily deficit maps directly to a weekly rate —
        modest and repeatable beats aggressive and abandoned. Sustainable
        range: 0.25–1 % of body weight per week.</p>
      <div class="stat-row">
        ${rateLb.map((lb) => {
          const kcal = r0(lb * 3500 / 7);
          return `<div class="stat"><div class="n">−${kcal}</div>
            <div class="lbl">kcal/day ≈ ${isImperial() ? lb + " lb" : fmt1(lb / LB_PER_KG) + " kg"}/week</div></div>`;
        }).join("")}
      </div>
      <p class="hint" style="margin-top:8px">Flip the signs to bulk: the same
        arithmetic, upward. A gentle surplus (200–300 kcal) limits fat gain.</p>
    </div>

    <div class="card">
      <h2>3 · Macros 101 — where the calories live</h2>
      <div class="macro-cards">
        <div class="macro-card p"><b>Protein</b>
          <div class="kcal-g">4 kcal per gram</div>
          <p class="small">Builds and keeps muscle, and it's the most filling
            macro. In a deficit it protects lean mass. Aim roughly
            1.6–2.2 g per kg of body weight
            (${you ? `≈ <b>${r0(kg * 1.6)}–${r0(kg * 2.2)} g</b> for you` : "e.g. 120–165 g at 75 kg"}).</p></div>
        <div class="macro-card c"><b>Carbs</b>
          <div class="kcal-g">4 kcal per gram</div>
          <p class="small">The body's preferred fuel, especially for training.
            Favor slow sources — oats, rice, potatoes, fruit, beans — and
            fiber (25–38 g/day) for fullness and gut health.</p></div>
        <div class="macro-card f"><b>Fat</b>
          <div class="kcal-g">9 kcal per gram — densest</div>
          <p class="small">Hormones, vitamin absorption, satiety. Keep at
            least ~0.6 g/kg; oils and nuts are healthy but calorie-dense,
            so measure, don't pour.</p></div>
      </div>
      <p class="hint" style="margin-top:10px">Your current split
        (${t.profile.protein_pct}/${t.profile.carbs_pct}/${t.profile.fat_pct})
        at ${r0(target)} kcal = <b>${r0(t.protein_g)} g protein ·
        ${r0(t.carbs_g)} g carbs · ${r0(t.fat_g)} g fat</b>. Change it on the
        Targets tab.</p>
    </div>

    <div class="grid2">
      <div class="card">
        <h2>4 · The plate method</h2>
        <p class="hint">No scale handy? Build every plate like this and the
          macros roughly take care of themselves.</p>
        <div class="plate"></div>
        <div class="legend">
          <span><i style="background:var(--accent)"></i>½ vegetables & fruit</span>
          <span><i style="background:var(--protein)"></i>¼ lean protein</span>
          <span><i style="background:var(--carbs)"></i>¼ whole-grain carbs</span>
        </div>
        <p class="hint" style="margin-top:8px">Plus a thumb of fat for
          cooking, and water as the default drink.</p>
      </div>
      <div class="card">
        <h2>5 · Hydration</h2>
        <p class="hint">A practical baseline is ~30–35 ml per kg of body
          weight (${you ? `≈ <b>${mlShow(kg * 33)}</b> for you` : "≈ 2–3 L for most people"}) —
          more on training or hot days. Thirst lags; urine color is the
          honest signal (pale straw = good).</p>
        <p class="hint">The Today tab's glasses are ${mlShow(GLASS_ML)} each.
          Set your goal on the Targets tab. Hunger and mild dehydration are
          easy to confuse — when a craving hits, drink a glass first and
          give it ten minutes.</p>
      </div>
    </div>

    <div class="card">
      <h2>6 · The weekly meal-prep workflow</h2>
      <p class="hint">One relaxed hour of planning saves five stressful
        decisions a day. The tabs of this app are laid out to follow it.</p>
      <div class="steps">
        <div class="step"><div><b>Set the target (Targets)</b>
          <div class="small">Weigh in, check your maintenance and daily
            target. This number drives everything downstream.</div></div></div>
        <div class="step"><div><b>Pick 3–5 recipes (Recipes)</b>
          <div class="small">Batch-friendly dinners + one breakfast you love.
            Repeats are a feature — decision fatigue is the enemy.</div></div></div>
        <div class="step"><div><b>Lay out the week (Plan)</b>
          <div class="small">Fill the grid; watch each day's total against
            your target as you go. Leave slack for a social meal.</div></div></div>
        <div class="step"><div><b>Generate the shopping list (Plan → Shopping)</b>
          <div class="small">One tap aggregates every ingredient in the date
            range, grouped by store section.</div></div></div>
        <div class="step"><div><b>Batch cook once</b>
          <div class="small">Cook grains and proteins in parallel, roast a
            tray of vegetables, portion into containers. Fridge: 3–4 days;
            freeze the rest.</div></div></div>
        <div class="step"><div><b>Log as you eat (Log / Today)</b>
          <div class="small">Planned meals log with one tap. Weigh in most
            mornings, watch the 7-day trend on Body — not any single day.</div></div></div>
      </div>
    </div>

    <div class="card notice">These are planning estimates, not medical
      advice. Formulas are population averages — your real maintenance
      shows up in the Body tab's trend line after 2–3 honest weeks. Adjust
      calories to the trend you observe, and talk to a professional for
      medical conditions, pregnancy, or a history of disordered eating.</div>`;
}

// ============================================================ Log (diary)

let LOG_DAY = todayStr();

function renderLog() {
  const el = $("#tab-log");
  const day = LOG_DAY;
  const t = calcTargets();
  const goal = t.target || 2000;
  const tot = logTotals(day);
  const entries = STATE.food_log.filter((e) => e.day === day);

  el.innerHTML = `
    <div class="card">
      <div class="row spread">
        <div class="row">
          <button class="btn small ghost" id="l-prev">‹</button>
          <input type="date" id="l-day" value="${day}" style="width:160px">
          <button class="btn small ghost" id="l-next">›</button>
          ${day !== todayStr() ? `<button class="btn small ghost" id="l-today">today</button>` : ""}
        </div>
        <button class="btn small" id="l-add">＋ Log food</button>
      </div>
      <div class="stat-row" style="margin-top:12px">
        <div class="stat"><div class="n ${tot.cal > goal ? "danger-text" : ""}">${r0(tot.cal)}</div>
          <div class="lbl">kcal of ${r0(goal)} target</div></div>
        <div class="stat"><div class="n" style="color:var(--protein)">${r0(tot.protein)}g</div>
          <div class="lbl">protein / ${r0(t.protein_g)}g</div></div>
        <div class="stat"><div class="n" style="color:var(--carbs)">${r0(tot.carbs)}g</div>
          <div class="lbl">carbs / ${r0(t.carbs_g)}g</div></div>
        <div class="stat"><div class="n" style="color:var(--fat)">${r0(tot.fat)}g</div>
          <div class="lbl">fat / ${r0(t.fat_g)}g</div></div>
      </div>
      <p class="small muted" style="margin:10px 0 0">
        Fiber <b class="${tot.fiber >= t.profile.fiber_goal_g ? "" : ""}">${r0(tot.fiber)}</b> / ${r0(t.profile.fiber_goal_g)} g
        &nbsp;·&nbsp; Sodium <b class="${tot.sodium > t.profile.sodium_limit_mg ? "danger-text" : ""}">${r0(tot.sodium)}</b> / ${r0(t.profile.sodium_limit_mg)} mg
        &nbsp;·&nbsp; Sugar <b class="${tot.sugar > t.profile.sugar_limit_g ? "danger-text" : ""}">${r0(tot.sugar)}</b> / ${r0(t.profile.sugar_limit_g)} g</p>
      <p class="hint" style="margin-top:10px">
        ${tot.cal <= goal
          ? `${r0(goal - tot.cal)} kcal remaining${t.adjust < 0 ? ` — on plan you'd bank a ${r0(Math.abs(t.adjust))} kcal deficit today` : ""}.`
          : `${r0(tot.cal - goal)} kcal over target — one day never decides the week; tomorrow is a clean slate.`}
      </p>
    </div>

    ${SLOTS.map((slot) => {
      const rows = entries.filter((e) => e.slot === slot);
      const slotCal = rows.reduce((a, e) => a + e.cal, 0);
      return `<div class="card">
        <div class="row spread"><h2>${SLOT_LABEL[slot]}</h2>
          <span class="muted small">${rows.length ? r0(slotCal) + " kcal" : ""}</span></div>
        ${rows.map((e) => `<div class="item row spread">
          <div><span class="title">${esc(e.name)}</span>
            <span class="meta"> · ${fmt1(e.servings)}× · ${r0(e.cal)} kcal ·
              P${r0(e.protein)} C${r0(e.carbs)} F${r0(e.fat)}</span></div>
          <button class="btn small danger" data-del="${e.id}">✕</button>
        </div>`).join("") || `<p class="hint">Nothing logged.
          <span class="clickable" style="color:var(--accent2);cursor:pointer"
            data-addslot="${slot}">Add ${slot} →</span></p>`}
      </div>`;
    }).join("")}`;

  const setDay = (d) => { LOG_DAY = d; renderLog(); };
  $("#l-prev").onclick = () => setDay(addDays(day, -1));
  $("#l-next").onclick = () => setDay(addDays(day, 1));
  $("#l-today")?.addEventListener("click", () => setDay(todayStr()));
  $("#l-day").onchange = (e) => setDay(e.target.value);
  $("#l-add").onclick = () => addLogModal(day);
  $$("[data-addslot]", el).forEach((s) => s.onclick = () => addLogModal(day, s.dataset.addslot));
  $$("[data-del]", el).forEach((b) => b.onclick = async () => {
    await api("/api/food_log/" + b.dataset.del, "DELETE");
    await reload(renderLog);
  });
}

function addLogModal(day, slot = null) {
  const hour = new Date().getHours();
  slot = slot || (hour < 10 ? "breakfast" : hour < 14 ? "lunch" : hour < 20 ? "dinner" : "snack");
  const recipes = STATE.recipes;
  const ings = STATE.ingredients;
  openModal(`
    <h2>Log food</h2>
    <div class="row">
      <input type="date" id="al-day" value="${day}" style="flex:1">
      <select id="al-slot" style="flex:1">${SLOTS.map((s) =>
        `<option value="${s}"${s === slot ? " selected" : ""}>${SLOT_LABEL[s]}</option>`).join("")}</select>
    </div>
    <h3>From a recipe</h3>
    <div class="row">
      <select id="al-recipe" style="flex:2">
        <option value="">— choose a recipe —</option>
        ${recipes.map((r) => `<option value="${r.id}">${esc(r.name)} (${r0(recipeMacros(r).cal)} kcal/serv)</option>`).join("")}
      </select>
      <input id="al-rserv" type="number" value="1" step="0.25" min="0.25" style="width:80px" title="servings">
      <button class="btn small" id="al-logr">Log</button>
    </div>
    <h3>A single ingredient</h3>
    <div class="row">
      <select id="al-ing" style="flex:2">
        <option value="">— choose an ingredient —</option>
        ${ings.map((i) => `<option value="${i.id}">${esc(i.name)} (${esc(i.serving_name || "serving")}, ${r0(i.cal)} kcal)</option>`).join("")}
      </select>
      <input id="al-iserv" type="number" value="1" step="0.25" min="0.25" style="width:80px" title="servings">
      <button class="btn small" id="al-logi">Log</button>
    </div>
    <h3>Quick manual entry</h3>
    <input id="al-name" placeholder="what was it? (e.g. restaurant burrito)">
    <div class="row" style="margin-top:6px">
      <input id="al-cal" type="number" placeholder="kcal" min="0">
      <input id="al-p" type="number" placeholder="protein g" min="0">
      <input id="al-c" type="number" placeholder="carbs g" min="0">
      <input id="al-f" type="number" placeholder="fat g" min="0">
    </div>
    <div class="row" style="margin-top:6px">
      <input id="al-fb" type="number" placeholder="fiber g (opt)" min="0">
      <input id="al-na" type="number" placeholder="sodium mg (opt)" min="0">
      <input id="al-su" type="number" placeholder="sugar g (opt)" min="0">
    </div>
    <div class="row" style="margin-top:10px">
      <button class="btn" id="al-logm">Log manual entry</button>
    </div>`);

  const dayVal = () => $("#al-day").value;
  const slotVal = () => $("#al-slot").value;
  const post = async (payload) => {
    await api("/api/food_log", "POST", { day: dayVal(), slot: slotVal(), ...payload });
    toast("Logged"); closeModal(); await reload();
  };
  $("#al-logr").onclick = async () => {
    const r = recipeById(+$("#al-recipe").value);
    if (!r) { toast("Pick a recipe"); return; }
    const s = parseFloat($("#al-rserv").value) || 1;
    await post({ name: r.name, servings: s, ...entryFrom(recipeMacros(r), s) });
  };
  $("#al-logi").onclick = async () => {
    const ing = ingredientById(+$("#al-ing").value);
    if (!ing) { toast("Pick an ingredient"); return; }
    const s = parseFloat($("#al-iserv").value) || 1;
    await post({ name: ing.name, servings: s, ...entryFrom(ing, s) });
  };
  $("#al-logm").onclick = async () => {
    const name = $("#al-name").value.trim();
    if (!name) { toast("Give it a name"); return; }
    await post({ name, servings: 1, cal: +$("#al-cal").value || 0,
      protein: +$("#al-p").value || 0, carbs: +$("#al-c").value || 0,
      fat: +$("#al-f").value || 0, fiber: +$("#al-fb").value || 0,
      sodium: +$("#al-na").value || 0, sugar: +$("#al-su").value || 0 });
  };
}

// ============================================================ Plan

let PLAN_START = mondayOf(todayStr());

function renderPlan() {
  const el = $("#tab-plan");
  const t = calcTargets();
  const goal = t.target || 2000;
  const days = Array.from({ length: 7 }, (_, i) => addDays(PLAN_START, i));

  el.innerHTML = `
    <div class="card">
      <div class="row spread">
        <div class="row">
          <button class="btn small ghost" id="p-prev">‹ prev</button>
          <b>${niceDay(days[0])} – ${niceDay(days[6], true)}</b>
          <button class="btn small ghost" id="p-next">next ›</button>
          <button class="btn small ghost" id="p-this">this week</button>
        </div>
        <div class="row">
          <button class="btn small ghost" id="p-repeat">⟳ Repeat last week</button>
          <button class="btn small" id="p-shop">🛒 Shopping list from this week</button>
        </div>
      </div>
      <p class="hint">Tap a meal to edit or remove it; ＋ adds to a slot. The
        per-day total compares against your ${r0(goal)} kcal target.</p>
      <div class="plan-week">
        ${days.map((day) => {
          const entries = STATE.plan_entries.filter((e) => e.day === day);
          const dayCal = entries.reduce((a, e) => a + planEntryInfo(e).per.cal * e.servings, 0);
          return `<div class="plan-day${day === todayStr() ? " today" : ""}">
            <h4>${niceDay(day)}</h4>
            <div class="day-kcal ${dayCal > goal ? "over" : ""}">${r0(dayCal)} / ${r0(goal)} kcal</div>
            ${SLOTS.map((slot) => {
              const rows = entries.filter((e) => e.slot === slot);
              return `<div class="plan-slot">${SLOT_LABEL[slot]}</div>
                ${rows.map((e) => {
                  const info = planEntryInfo(e);
                  return `<div class="plan-meal${e.done ? " done-meal" : ""}" data-edit="${e.id}">
                    <span>${esc(info.name)}${e.servings !== 1 ? ` ×${fmt1(e.servings)}` : ""}</span>
                    <span class="kcal">${r0(info.per.cal * e.servings)}</span></div>`;
                }).join("")}
                <div class="plan-add" data-add="${day}|${slot}">＋ add</div>`;
            }).join("")}
            ${entries.length ? `<div class="plan-add" data-copy="${day}">⧉ copy day…</div>` : ""}
          </div>`;
        }).join("")}
      </div>
    </div>`;

  $("#p-prev").onclick = () => { PLAN_START = addDays(PLAN_START, -7); renderPlan(); };
  $("#p-next").onclick = () => { PLAN_START = addDays(PLAN_START, 7); renderPlan(); };
  $("#p-this").onclick = () => { PLAN_START = mondayOf(todayStr()); renderPlan(); };
  $("#p-shop").onclick = () => generateShoppingModal(days[0], days[6]);
  $("#p-repeat").onclick = async () => {
    const prevStart = addDays(PLAN_START, -7), prevEnd = addDays(PLAN_START, -1);
    const src = STATE.plan_entries.filter((e) => e.day >= prevStart && e.day <= prevEnd);
    if (!src.length) { toast("Nothing planned last week"); return; }
    const existing = STATE.plan_entries.filter((e) => e.day >= days[0] && e.day <= days[6]);
    if (existing.length && !confirm(
      `This week already has ${existing.length} planned meal${existing.length === 1 ? "" : "s"} — add last week's ${src.length} on top?`)) return;
    for (const e of src) {
      await api("/api/plan_entries", "POST", {
        day: addDays(e.day, 7), slot: e.slot, recipe_id: e.recipe_id,
        ingredient_id: e.ingredient_id, title: e.title, servings: e.servings,
      });
    }
    toast(`Repeated ${src.length} meals into this week`);
    await reload(renderPlan);
  };
  $$("[data-add]", el).forEach((b) => b.onclick = () => {
    const [day, slot] = b.dataset.add.split("|");
    planEntryModal(null, day, slot);
  });
  $$("[data-edit]", el).forEach((b) => b.onclick = () => {
    const e = STATE.plan_entries.find((x) => x.id === +b.dataset.edit);
    planEntryModal(e, e.day, e.slot);
  });
  $$("[data-copy]", el).forEach((b) => b.onclick = () => {
    const src = b.dataset.copy;
    openModal(`
      <h2>Copy ${niceDay(src)}</h2>
      <p class="hint">Copies every planned meal of that day onto another day.</p>
      <input type="date" id="cp-day" value="${addDays(src, 1)}">
      <div class="row" style="margin-top:10px">
        <button class="btn" id="cp-go">Copy</button></div>`);
    $("#cp-go").onclick = async () => {
      const dst = $("#cp-day").value;
      const rows = STATE.plan_entries.filter((e) => e.day === src);
      for (const e of rows) {
        await api("/api/plan_entries", "POST", {
          day: dst, slot: e.slot, recipe_id: e.recipe_id,
          ingredient_id: e.ingredient_id, title: e.title, servings: e.servings,
        });
      }
      toast(`Copied ${rows.length} meals`); closeModal(); await reload(renderPlan);
    };
  });
}

function planEntryModal(entry, day, slot) {
  const isEdit = !!entry;
  const kind = entry ? (entry.recipe_id ? "recipe" : entry.ingredient_id ? "ingredient" : "custom") : "recipe";
  openModal(`
    <h2>${isEdit ? "Edit planned meal" : "Plan a meal"}</h2>
    <div class="row">
      <input type="date" id="pe-day" value="${day}" style="flex:1">
      <select id="pe-slot" style="flex:1">${SLOTS.map((s) =>
        `<option value="${s}"${s === slot ? " selected" : ""}>${SLOT_LABEL[s]}</option>`).join("")}</select>
    </div>
    <h3>What</h3>
    <select id="pe-kind" style="margin-bottom:6px">
      <option value="recipe"${kind === "recipe" ? " selected" : ""}>A recipe</option>
      <option value="ingredient"${kind === "ingredient" ? " selected" : ""}>A single ingredient</option>
      <option value="custom"${kind === "custom" ? " selected" : ""}>Free text (eating out, leftovers…)</option>
    </select>
    <select id="pe-recipe" ${kind !== "recipe" ? "hidden" : ""}>
      ${STATE.recipes.map((r) => `<option value="${r.id}"${entry?.recipe_id === r.id ? " selected" : ""}>
        ${esc(r.name)} (${r0(recipeMacros(r).cal)} kcal/serv)</option>`).join("")}
    </select>
    <select id="pe-ing" ${kind !== "ingredient" ? "hidden" : ""}>
      ${STATE.ingredients.map((i) => `<option value="${i.id}"${entry?.ingredient_id === i.id ? " selected" : ""}>
        ${esc(i.name)} (${r0(i.cal)} kcal)</option>`).join("")}
    </select>
    <input id="pe-title" placeholder="describe it" value="${esc(entry?.title || "")}"
      ${kind !== "custom" ? "hidden" : ""}>
    <div class="row" style="margin-top:8px">
      <label class="small muted">Servings
        <input id="pe-serv" type="number" step="0.25" min="0.25"
          value="${entry?.servings ?? 1}" style="width:90px"></label>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="pe-save">${isEdit ? "Save" : "Add to plan"}</button>
      ${isEdit ? `<button class="btn small ghost" id="pe-toggle">${entry.done ? "Mark not done" : "Mark done"}</button>
        <span class="grow"></span>
        <button class="btn small danger" id="pe-del">Remove</button>` : ""}
    </div>`);

  $("#pe-kind").onchange = () => {
    const k = $("#pe-kind").value;
    $("#pe-recipe").hidden = k !== "recipe";
    $("#pe-ing").hidden = k !== "ingredient";
    $("#pe-title").hidden = k !== "custom";
  };
  $("#pe-save").onclick = async () => {
    const k = $("#pe-kind").value;
    const payload = {
      day: $("#pe-day").value, slot: $("#pe-slot").value,
      servings: parseFloat($("#pe-serv").value) || 1,
      recipe_id: k === "recipe" ? +$("#pe-recipe").value || null : null,
      ingredient_id: k === "ingredient" ? +$("#pe-ing").value || null : null,
      title: k === "custom" ? $("#pe-title").value.trim() : "",
    };
    if (k === "recipe" && !payload.recipe_id) { toast("Pick a recipe — or add one on the Recipes tab"); return; }
    if (k === "ingredient" && !payload.ingredient_id) { toast("Pick an ingredient"); return; }
    if (k === "custom" && !payload.title) { toast("Describe the meal"); return; }
    try {
      if (isEdit) await api("/api/plan_entries/" + entry.id, "PATCH", payload);
      else await api("/api/plan_entries", "POST", payload);
      toast("Saved"); closeModal(); await reload(renderPlan);
    } catch (e) { toast(e.message); }
  };
  $("#pe-toggle")?.addEventListener("click", async () => {
    await api("/api/plan_entries/" + entry.id, "PATCH", { done: entry.done ? 0 : 1 });
    closeModal(); await reload(renderPlan);
  });
  $("#pe-del")?.addEventListener("click", async () => {
    await api("/api/plan_entries/" + entry.id, "DELETE");
    toast("Removed"); closeModal(); await reload(renderPlan);
  });
}

function generateShoppingModal(start, end) {
  openModal(`
    <h2>Generate shopping list</h2>
    <p class="hint">Aggregates every ingredient of every planned meal in the
      range (recipes expanded and scaled), grouped by store section, and adds
      the items to the Shopping tab.</p>
    <div class="row">
      <input type="date" id="gs-start" value="${start}" style="flex:1">
      <input type="date" id="gs-end" value="${end}" style="flex:1">
    </div>
    <label class="row small" style="margin-top:10px;cursor:pointer">
      <input type="checkbox" id="gs-pantry" checked style="width:16px;height:16px">
      <span>Skip what I already have (ingredients marked “pantry” on the
        Ingredients tab)</span>
    </label>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="gs-go">Generate</button>
    </div>`);
  $("#gs-go").onclick = async () => {
    try {
      const d = await api("/api/shopping/generate", "POST",
        { start: $("#gs-start").value, end: $("#gs-end").value,
          skip_stocked: $("#gs-pantry").checked });
      toast(d.added
        ? `Added ${d.added} items${d.skipped ? `, skipped ${d.skipped} in your pantry` : ""}`
        : d.skipped ? `Everything's already in your pantry (${d.skipped} skipped)`
        : "Nothing planned in that range");
      closeModal(); await reload(() => { renderPlan(); renderShopping(); });
      if (d.added) switchTab("shopping");
    } catch (e) { toast(e.message); }
  };
}

// ============================================================ Recipes

function renderRecipes() {
  const el = $("#tab-recipes");
  const rs = STATE.recipes;
  el.innerHTML = `
    <div class="card">
      <div class="row spread"><h2>Recipes</h2>
        <button class="btn small" id="r-add">＋ New recipe</button></div>
      <p class="hint">Built from your ingredient library, so macros per
        serving are computed automatically. ★ favorites float to the top.</p>
      ${rs.length ? rs.map((r) => {
        const m = recipeMacros(r);
        const nItems = itemsOf(r.id).length;
        return `<div class="item clickable" data-open="${r.id}">
          <div class="row spread">
            <span class="title">${r.favorite ? "★ " : ""}${esc(r.name)}</span>
            <span class="row">${macroPills(m)}</span>
          </div>
          <div class="meta">${r.meal_type !== "any" ? SLOT_LABEL[r.meal_type] || r.meal_type : "Any meal"}
            · makes ${fmt1(r.servings)} serving${r.servings === 1 ? "" : "s"}
            · ${nItems} ingredient${nItems === 1 ? "" : "s"}
            ${r.prep_min ? ` · ${r.prep_min} min` : ""}</div>
        </div>`;
      }).join("") : `<p class="hint">No recipes yet — create one, or load
        starter content from the Today tab.</p>`}
    </div>`;
  $("#r-add").onclick = () => recipeModal(null);
  $$("[data-open]", el).forEach((b) => b.onclick = () => recipeModal(recipeById(+b.dataset.open)));
}

function recipeModal(recipe) {
  const isEdit = !!recipe;
  // local working copy of ingredient lines (saved on submit)
  const lines = isEdit ? itemsOf(recipe.id).map((i) => ({ ingredient_id: i.ingredient_id, qty: i.qty })) : [];
  const ings = STATE.ingredients;

  const linesHtml = () => lines.map((ln, idx) => {
    const ing = ingredientById(ln.ingredient_id);
    return `<div class="row" style="margin:4px 0">
      <span class="grow small">${esc(ing?.name || "?")}
        <span class="muted">(${esc(ing?.serving_name || "serving")})</span></span>
      <input type="number" step="0.25" min="0.05" value="${ln.qty}" data-qty="${idx}" style="width:80px">
      <button class="btn small danger" data-rm="${idx}">✕</button>
    </div>`;
  }).join("") || `<p class="hint">No ingredients yet.</p>`;

  const totalsHtml = () => {
    const servings = parseFloat($("#rc-serv")?.value) || recipe?.servings || 1;
    const tot = { cal: 0, protein: 0, carbs: 0, fat: 0 };
    for (const ln of lines) {
      const ing = ingredientById(ln.ingredient_id);
      if (!ing) continue;
      tot.cal += ing.cal * ln.qty; tot.protein += ing.protein * ln.qty;
      tot.carbs += ing.carbs * ln.qty; tot.fat += ing.fat * ln.qty;
    }
    return `Per serving (of ${fmt1(servings)}): ` + macroPills({
      cal: tot.cal / servings, protein: tot.protein / servings,
      carbs: tot.carbs / servings, fat: tot.fat / servings });
  };

  openModal(`
    <h2>${isEdit ? "Edit recipe" : "New recipe"}</h2>
    <input id="rc-name" placeholder="recipe name" value="${esc(recipe?.name || "")}">
    <div class="row" style="margin-top:6px">
      <select id="rc-type" style="flex:1">${MEAL_TYPES.map((m) =>
        `<option value="${m}"${(recipe?.meal_type || "any") === m ? " selected" : ""}>
          ${m === "any" ? "Any meal" : SLOT_LABEL[m] || m}</option>`).join("")}</select>
      <label class="small muted">Makes
        <input id="rc-serv" type="number" step="0.5" min="0.5" value="${recipe?.servings ?? 1}" style="width:70px"></label>
      <label class="small muted">Min
        <input id="rc-prep" type="number" min="0" value="${recipe?.prep_min ?? 0}" style="width:70px"></label>
    </div>
    <h3>Ingredients</h3>
    <div id="rc-lines">${linesHtml()}</div>
    <div class="row" style="margin-top:6px">
      <select id="rc-newing" style="flex:2">
        <option value="">— add ingredient —</option>
        ${ings.map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("")}
      </select>
      <input id="rc-newqty" type="number" step="0.25" min="0.05" value="1" style="width:80px">
      <button class="btn small" id="rc-addline">Add</button>
    </div>
    <p class="small muted" id="rc-totals" style="margin-top:8px"></p>
    <h3>Instructions</h3>
    <textarea id="rc-instr" placeholder="how to make it…">${esc(recipe?.instructions || "")}</textarea>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="rc-save">${isEdit ? "Save changes" : "Create recipe"}</button>
      ${isEdit ? `<button class="btn small ghost" id="rc-fav">${recipe.favorite ? "Unfavorite" : "★ Favorite"}</button>
        <span class="grow"></span>
        <button class="btn small danger" id="rc-del">Delete</button>` : ""}
    </div>`);

  const refresh = () => {
    $("#rc-lines").innerHTML = linesHtml();
    $("#rc-totals").innerHTML = totalsHtml();
    bindLines();
  };
  const bindLines = () => {
    $$("[data-rm]", $("#rc-lines")).forEach((b) => b.onclick = () => {
      lines.splice(+b.dataset.rm, 1); refresh();
    });
    $$("[data-qty]", $("#rc-lines")).forEach((inp) => inp.onchange = () => {
      lines[+inp.dataset.qty].qty = parseFloat(inp.value) || 1;
      $("#rc-totals").innerHTML = totalsHtml();
    });
  };
  $("#rc-totals").innerHTML = totalsHtml();
  bindLines();
  $("#rc-serv").onchange = () => { $("#rc-totals").innerHTML = totalsHtml(); };
  $("#rc-addline").onclick = () => {
    const id = +$("#rc-newing").value;
    if (!id) { toast("Pick an ingredient"); return; }
    lines.push({ ingredient_id: id, qty: parseFloat($("#rc-newqty").value) || 1 });
    $("#rc-newing").value = "";
    refresh();
  };

  $("#rc-save").onclick = async () => {
    const name = $("#rc-name").value.trim();
    if (!name) { toast("Name the recipe"); return; }
    const payload = {
      name, meal_type: $("#rc-type").value,
      servings: parseFloat($("#rc-serv").value) || 1,
      prep_min: parseInt($("#rc-prep").value) || 0,
      instructions: $("#rc-instr").value,
    };
    try {
      let rid = recipe?.id;
      if (isEdit) await api("/api/recipes/" + rid, "PATCH", payload);
      else rid = (await api("/api/recipes", "POST", payload)).id;
      // reconcile ingredient lines: simplest correct approach — replace all
      if (isEdit) {
        for (const it of itemsOf(rid)) await api("/api/recipe_items/" + it.id, "DELETE");
      }
      for (const ln of lines) {
        await api("/api/recipe_items", "POST",
          { recipe_id: rid, ingredient_id: ln.ingredient_id, qty: ln.qty });
      }
      toast("Saved"); closeModal(); await reload(renderRecipes);
    } catch (e) { toast(e.message); }
  };
  $("#rc-fav")?.addEventListener("click", async () => {
    await api("/api/recipes/" + recipe.id, "PATCH", { favorite: recipe.favorite ? 0 : 1 });
    closeModal(); await reload(renderRecipes);
  });
  $("#rc-del")?.addEventListener("click", async () => {
    if (!confirm(`Delete "${recipe.name}"? Planned meals using it become empty.`)) return;
    await api("/api/recipes/" + recipe.id, "DELETE");
    toast("Deleted"); closeModal(); await reload(renderRecipes);
  });
}

// ============================================================ Ingredients

let ING_FILTER = { q: "", cat: "" };

function renderIngredients() {
  const el = $("#tab-ingredients");
  const { q, cat } = ING_FILTER;
  const list = STATE.ingredients.filter((i) =>
    (!cat || i.category === cat) &&
    (!q || i.name.toLowerCase().includes(q.toLowerCase())));

  el.innerHTML = `
    <div class="card">
      <div class="row spread"><h2>Ingredient library</h2>
        <button class="btn small" id="i-add">＋ New ingredient</button></div>
      <p class="hint">Per-serving nutrition — recipes and logs pull from
        here. Values straight off the package label work great.</p>
      <div class="row" style="margin-bottom:8px">
        <input id="i-q" placeholder="search…" value="${esc(q)}" style="flex:2;min-width:140px">
        <select id="i-cat" style="flex:1">
          <option value="">All categories</option>
          ${CATEGORIES.map((c) => `<option value="${c}"${cat === c ? " selected" : ""}>${CAT_LABEL[c]}</option>`).join("")}
        </select>
      </div>
      ${list.map((i) => `<div class="item clickable" data-open="${i.id}">
        <div class="row spread">
          <span class="title">${esc(i.name)}</span>
          <span class="row">${macroPills(i)}</span>
        </div>
        <div class="meta row spread">
          <span>${CAT_LABEL[i.category] || i.category} ·
            per ${esc(i.serving_name || "serving")}${i.fiber ? ` · fiber ${fmt1(i.fiber)}g` : ""}${i.sodium ? ` · Na ${r0(i.sodium)}mg` : ""}${i.sugar ? ` · sugar ${fmt1(i.sugar)}g` : ""}</span>
          <label class="row small" style="cursor:pointer" data-stopclick>
            <input type="checkbox" data-stock="${i.id}" ${i.in_stock ? "checked" : ""}
              style="width:15px;height:15px;accent-color:var(--accent)">
            <span class="${i.in_stock ? "" : "muted"}">pantry</span>
          </label>
        </div>
      </div>`).join("") || `<p class="hint">${STATE.ingredients.length
        ? "No matches." : "Empty — add ingredients or load starter content from the Today tab."}</p>`}
    </div>`;

  $("#i-q").oninput = (e) => { ING_FILTER.q = e.target.value; renderIngredients(); $("#i-q").focus(); $("#i-q").setSelectionRange(99, 99); };
  $("#i-cat").onchange = (e) => { ING_FILTER.cat = e.target.value; renderIngredients(); };
  $("#i-add").onclick = () => ingredientModal(null);
  $$("[data-open]", el).forEach((b) => b.onclick = (ev) => {
    if (ev.target.closest("[data-stopclick]")) return;  // pantry toggle, not open
    ingredientModal(ingredientById(+b.dataset.open));
  });
  $$("[data-stock]", el).forEach((c) => c.onchange = async () => {
    await api("/api/ingredients/" + c.dataset.stock, "PATCH",
      { in_stock: c.checked ? 1 : 0 });
    await reload(renderIngredients);
  });
}

function ingredientModal(ing) {
  const isEdit = !!ing;
  openModal(`
    <h2>${isEdit ? "Edit ingredient" : "New ingredient"}</h2>
    <input id="ig-name" placeholder="name (e.g. Chicken breast)" value="${esc(ing?.name || "")}">
    <div class="row" style="margin-top:6px">
      <select id="ig-cat" style="flex:1">${CATEGORIES.map((c) =>
        `<option value="${c}"${(ing?.category || "pantry") === c ? " selected" : ""}>${CAT_LABEL[c]}</option>`).join("")}</select>
      <input id="ig-serving" placeholder='serving (e.g. "100 g", "1 cup")'
        value="${esc(ing?.serving_name || "")}" style="flex:1">
    </div>
    <h3>Per serving</h3>
    <div class="row">
      <label class="small muted">kcal<input id="ig-cal" type="number" min="0" value="${ing?.cal ?? ""}" style="width:80px"></label>
      <label class="small muted">protein g<input id="ig-p" type="number" min="0" step="0.1" value="${ing?.protein ?? ""}" style="width:80px"></label>
      <label class="small muted">carbs g<input id="ig-c" type="number" min="0" step="0.1" value="${ing?.carbs ?? ""}" style="width:80px"></label>
      <label class="small muted">fat g<input id="ig-f" type="number" min="0" step="0.1" value="${ing?.fat ?? ""}" style="width:80px"></label>
      <label class="small muted">fiber g<input id="ig-fb" type="number" min="0" step="0.1" value="${ing?.fiber ?? ""}" style="width:80px"></label>
      <label class="small muted">sodium mg<input id="ig-na" type="number" min="0" value="${ing?.sodium ?? ""}" style="width:80px"></label>
      <label class="small muted">sugar g<input id="ig-su" type="number" min="0" step="0.1" value="${ing?.sugar ?? ""}" style="width:80px"></label>
    </div>
    <label class="row small" style="margin-top:10px;cursor:pointer">
      <input type="checkbox" id="ig-stock" ${ing?.in_stock ? "checked" : ""}
        style="width:16px;height:16px;accent-color:var(--accent)">
      <span>In my pantry (shopping lists can skip it)</span>
    </label>
    <div class="row" style="margin-top:12px">
      <button class="btn" id="ig-save">${isEdit ? "Save" : "Add ingredient"}</button>
      ${isEdit ? `<span class="grow"></span>
        <button class="btn small danger" id="ig-del">Delete</button>` : ""}
    </div>`);
  $("#ig-save").onclick = async () => {
    const name = $("#ig-name").value.trim();
    if (!name) { toast("Name it"); return; }
    const payload = {
      name, category: $("#ig-cat").value, serving_name: $("#ig-serving").value.trim(),
      cal: +$("#ig-cal").value || 0, protein: +$("#ig-p").value || 0,
      carbs: +$("#ig-c").value || 0, fat: +$("#ig-f").value || 0,
      fiber: +$("#ig-fb").value || 0, sodium: +$("#ig-na").value || 0,
      sugar: +$("#ig-su").value || 0, in_stock: $("#ig-stock").checked ? 1 : 0,
    };
    try {
      if (isEdit) await api("/api/ingredients/" + ing.id, "PATCH", payload);
      else await api("/api/ingredients", "POST", payload);
      toast("Saved"); closeModal(); await reload(renderIngredients);
    } catch (e) { toast(e.message); }
  };
  $("#ig-del")?.addEventListener("click", async () => {
    if (!confirm(`Delete "${ing.name}"? Recipe lines using it are removed too.`)) return;
    await api("/api/ingredients/" + ing.id, "DELETE");
    toast("Deleted"); closeModal(); await reload(renderIngredients);
  });
}

// ============================================================ Shopping

function renderShopping() {
  const el = $("#tab-shopping");
  const items = STATE.shopping_items;
  const unchecked = items.filter((i) => !i.checked);
  const checked = items.filter((i) => i.checked);

  const group = (rows) => {
    const by = {};
    for (const i of rows) (by[i.category] ||= []).push(i);
    return CATEGORIES.filter((c) => by[c]).map((c) => `
      <div class="shop-cat">${CAT_LABEL[c]}</div>
      ${by[c].map((i) => `<div class="shop-item ${i.checked ? "done" : ""}">
        <input type="checkbox" ${i.checked ? "checked" : ""} data-check="${i.id}">
        <span class="grow">${esc(i.name)}</span>
        <span class="qty">${esc(i.qty)}</span>
        <button class="btn small danger" data-del="${i.id}">✕</button>
      </div>`).join("")}`).join("");
  };

  el.innerHTML = `
    <div class="card">
      <div class="row spread"><h2>Shopping list</h2>
        <div class="row">
          <button class="btn small ghost" id="s-gen">From plan…</button>
          ${checked.length ? `<button class="btn small ghost" id="s-clear">Clear ${checked.length} checked</button>` : ""}
        </div></div>
      <div class="row" style="margin:8px 0">
        <input id="s-name" placeholder="add item… (e.g. paper towels)" style="flex:2;min-width:140px">
        <select id="s-cat" style="flex:1">${CATEGORIES.map((c) =>
          `<option value="${c}">${CAT_LABEL[c]}</option>`).join("")}</select>
        <input id="s-qty" placeholder="qty" style="width:80px">
        <button class="btn small" id="s-add">Add</button>
      </div>
      ${unchecked.length || checked.length
        ? group(unchecked) + (checked.length ? `<h3>In the cart</h3>` + group(checked) : "")
        : `<p class="hint">Empty. Add items above, or generate a list from
           your meal plan (Plan tab → "Shopping list from this week").</p>`}
    </div>`;

  $("#s-add").onclick = async () => {
    const name = $("#s-name").value.trim();
    if (!name) return;
    await api("/api/shopping_items", "POST",
      { name, category: $("#s-cat").value, qty: $("#s-qty").value.trim() });
    await reload(renderShopping);
  };
  $("#s-name").onkeydown = (e) => { if (e.key === "Enter") $("#s-add").click(); };
  $("#s-gen").onclick = () => {
    const mon = mondayOf(todayStr());
    generateShoppingModal(mon, addDays(mon, 6));
  };
  $("#s-clear")?.addEventListener("click", async () => {
    await api("/api/shopping/clear_checked", "POST", {});
    await reload(renderShopping);
  });
  $$("[data-check]", el).forEach((c) => c.onchange = async () => {
    await api("/api/shopping_items/" + c.dataset.check, "PATCH",
      { checked: c.checked ? 1 : 0 });
    await reload(renderShopping);
  });
  $$("[data-del]", el).forEach((b) => b.onclick = async () => {
    await api("/api/shopping_items/" + b.dataset.del, "DELETE");
    await reload(renderShopping);
  });
}

// ============================================================ Body

function movingAvg(points, n = 7) {
  return points.map((p, i) => {
    const win = points.slice(Math.max(0, i - n + 1), i + 1);
    return { ...p, avg: win.reduce((a, x) => a + x.kg, 0) / win.length };
  });
}

function weightChartSVG() {
  const raw = STATE.weight_log;
  if (raw.length < 2) return `<p class="hint">Log at least two weigh-ins to see the trend.</p>`;
  const pts = movingAvg(raw.map((w) => ({ day: w.day, kg: w.kg })));
  const p = getProfile();
  const goalKg = p.goal_weight_kg;
  const W = Math.max(560, Math.min(960, pts.length * 24)), H = 220, padL = 46, padR = 12, padT = 12, padB = 26;
  const kgs = pts.map((x) => x.kg).concat(goalKg ? [goalKg] : []);
  let lo = Math.min(...kgs), hi = Math.max(...kgs);
  const span = Math.max(1, hi - lo); lo -= span * 0.1; hi += span * 0.1;
  const X = (i) => padL + (i / (pts.length - 1)) * (W - padL - padR);
  const Y = (kg) => padT + (1 - (kg - lo) / (hi - lo)) * (H - padT - padB);
  const disp = (kg) => isImperial() ? kg * LB_PER_KG : kg;

  const dots = pts.map((x, i) =>
    `<circle cx="${X(i)}" cy="${Y(x.kg)}" r="3" fill="var(--dim)" opacity=".55">
       <title>${x.day}: ${wShow(x.kg)}</title></circle>`).join("");
  const trend = "M" + pts.map((x, i) => `${X(i)},${Y(x.avg)}`).join(" L");
  const gridLines = Array.from({ length: 4 }, (_, i) => {
    const kg = lo + ((i + 1) / 5) * (hi - lo);
    return `<line x1="${padL}" y1="${Y(kg)}" x2="${W - padR}" y2="${Y(kg)}"
        stroke="var(--line)" stroke-dasharray="2 4"/>
      <text x="4" y="${Y(kg) + 3}" class="axis-lbl">${r0(disp(kg))}</text>`;
  }).join("");
  const goalLine = goalKg ? `<line x1="${padL}" y1="${Y(goalKg)}" x2="${W - padR}" y2="${Y(goalKg)}"
      stroke="var(--carbs)" stroke-dasharray="6 4"/>
    <text x="${W - padR - 4}" y="${Y(goalKg) - 5}" text-anchor="end" class="axis-lbl"
      fill="var(--carbs)">goal ${wShow(goalKg)}</text>` : "";
  const xlabels = [0, Math.floor((pts.length - 1) / 2), pts.length - 1].map((i) =>
    `<text x="${X(i)}" y="${H - 8}" text-anchor="middle" class="axis-lbl">${pts[i].day.slice(5)}</text>`).join("");

  return `<div class="chart-wrap"><svg width="${W}" height="${H}">
    ${gridLines}${goalLine}${dots}
    <path d="${trend}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>
    ${xlabels}
  </svg></div>
  <p class="hint">Dots are daily weigh-ins (${wUnit()}); the green line is the
    7-day average — trust the line, not the dots. Day-to-day water swings of
    ±1–2&nbsp;${wUnit()} are normal and meaningless.</p>`;
}

function renderBody() {
  const el = $("#tab-body");
  const t = calcTargets();
  const w = STATE.weight_log;
  const latest = latestWeightKg();
  const first = w.length ? w[0].kg : null;
  const days30 = addDays(todayStr(), -30);
  const monthAgo = [...w].reverse().find((x) => x.day <= days30);
  const change30 = latest != null && monthAgo ? latest - monthAgo.kg : null;
  const toGoal = latest != null && t.profile.goal_weight_kg != null
    ? latest - t.profile.goal_weight_kg : null;

  // last 14 days of water
  const waterDays = Array.from({ length: 14 }, (_, i) => addDays(todayStr(), i - 13));
  const waterGoal = t.profile.water_goal_ml || 2500;
  const maxMl = Math.max(waterGoal, ...waterDays.map(waterFor), 1);

  el.innerHTML = `
    <div class="card">
      <div class="row spread"><h2>Weight</h2>
        <button class="btn small" id="b-weigh">＋ Weigh-in</button></div>
      <div class="stat-row">
        <div class="stat"><div class="n">${wShow(latest)}</div><div class="lbl">latest</div></div>
        <div class="stat"><div class="n">${change30 == null ? "—"
          : (change30 <= 0 ? "" : "+") + fmt1(change30 * (isImperial() ? LB_PER_KG : 1)) + " " + wUnit()}</div>
          <div class="lbl">last 30 days</div></div>
        <div class="stat"><div class="n">${first == null || latest == null ? "—"
          : (latest - first <= 0 ? "" : "+") + fmt1((latest - first) * (isImperial() ? LB_PER_KG : 1)) + " " + wUnit()}</div>
          <div class="lbl">since first entry</div></div>
        <div class="stat"><div class="n">${toGoal == null ? "—"
          : fmt1(Math.abs(toGoal) * (isImperial() ? LB_PER_KG : 1)) + " " + wUnit()}</div>
          <div class="lbl">${toGoal == null ? "no goal set" : toGoal > 0 ? "to goal (down)" : "to goal (up)"}</div></div>
      </div>
      <div style="margin-top:14px">${weightChartSVG()}</div>
      ${w.length ? `<details><summary>All weigh-ins</summary>
        ${[...w].reverse().map((x) => `<div class="item row spread">
          <span>${niceDay(x.day, true)} — <b>${wShow(x.kg)}</b>
            ${x.note ? `<span class="muted small"> · ${esc(x.note)}</span>` : ""}</span>
          <button class="btn small danger" data-delw="${x.id}">✕</button>
        </div>`).join("")}</details>` : ""}
    </div>

    ${(() => {
      const s = streaks();
      const logged = loggedDaySet();
      const last7 = Array.from({ length: 7 }, (_, i) => addDays(todayStr(), i - 6));
      const onTarget7 = last7.filter((d) => dayOnTarget(d, t)).length;
      const cal14 = Array.from({ length: 14 }, (_, i) => addDays(todayStr(), i - 13));
      const rule = { lose: "you logged and finished at or under target (+5% grace)",
        maintain: "you logged and landed within ±10% of target",
        gain: "you logged and reached at least 95% of target" }[t.profile.goal];
      return `<div class="card">
        <h2>Streaks & adherence</h2>
        <div class="stat-row">
          <div class="stat"><div class="n">${s.cur}${s.cur >= 3 ? " 🔥" : ""}</div>
            <div class="lbl">day logging streak</div></div>
          <div class="stat"><div class="n">${s.best}</div>
            <div class="lbl">best streak</div></div>
          <div class="stat"><div class="n">${onTarget7}/7</div>
            <div class="lbl">days on target this week</div></div>
          <div class="stat"><div class="n">${logged.size}</div>
            <div class="lbl">days logged all-time</div></div>
        </div>
        <div class="streak-cal">
          ${cal14.map((d) => {
            const cls = dayOnTarget(d, t) ? "hit" : logged.has(d) ? "part" : "";
            return `<div class="streak-day ${cls}" title="${d}">
              <span>${d.slice(8)}</span></div>`;
          }).join("")}
        </div>
        <p class="hint">Last 14 days — green: on target (${rule}); amber:
          logged but off target; dim: not logged. Consistency beats
          perfection: an 80% week you repeat wins against a 100% week you
          abandon.</p>
      </div>`;
    })()}

    <div class="card">
      <h2>Water — last 14 days</h2>
      <div class="barchart">
        ${waterDays.map((d) => {
          const ml = waterFor(d);
          return `<div class="bar" style="height:${Math.max(2, (ml / maxMl) * 100)}%;
            background:linear-gradient(180deg,#7dd3fc,var(--water));
            ${ml >= waterGoal ? "" : "opacity:.45"}">
            <div class="v">${ml ? r0(ml / 1000 * 10) / 10 + "L" : ""}</div></div>`;
        }).join("")}
      </div>
      <div class="bar-lbls">${waterDays.map((d) => `<span>${d.slice(8)}</span>`).join("")}</div>
      <p class="hint">Solid bars hit your ${mlShow(waterGoal)} goal.</p>
    </div>`;

  $("#b-weigh").onclick = () => weighInModal();
  $$("[data-delw]", el).forEach((b) => b.onclick = async () => {
    await api("/api/weight_log/" + b.dataset.delw, "DELETE");
    await reload(renderBody);
  });
}

// ============================================================ Targets

function renderTargets() {
  const el = $("#tab-targets");
  const t = calcTargets();
  const p = t.profile;
  const imp = p.units === "imperial";
  const heightVal = imp ? "" : (p.height_cm || "");
  const ftIn = imp ? [Math.floor((p.height_cm || 175) / 2.54 / 12), Math.round((p.height_cm || 175) / 2.54 % 12)] : [5, 9];
  const gw = p.goal_weight_kg;

  el.innerHTML = `
    <div class="grid2">
      <div class="card">
        <h2>Your profile</h2>
        <p class="hint">Drives every computed number in the app. Stored only
          on this machine.</p>
        <div class="row">
          <label class="small muted" style="flex:1">Units
            <select id="tg-units">
              <option value="imperial"${imp ? " selected" : ""}>Imperial (lb, ft)</option>
              <option value="metric"${!imp ? " selected" : ""}>Metric (kg, cm)</option>
            </select></label>
          <label class="small muted" style="flex:1">Sex (for BMR)
            <select id="tg-sex">
              <option value="male"${p.sex === "male" ? " selected" : ""}>Male</option>
              <option value="female"${p.sex === "female" ? " selected" : ""}>Female</option>
            </select></label>
          <label class="small muted" style="flex:1">Birth year
            <input id="tg-year" type="number" min="1920" max="2020" value="${p.birth_year}"></label>
        </div>
        <div class="row" style="margin-top:6px">
          ${imp ? `<label class="small muted">Height
              <span class="row"><input id="tg-ft" type="number" min="3" max="8" value="${ftIn[0]}" style="width:64px"> ft
              <input id="tg-in" type="number" min="0" max="11" value="${ftIn[1]}" style="width:64px"> in</span></label>`
            : `<label class="small muted">Height (cm)
              <input id="tg-cm" type="number" min="100" max="250" value="${heightVal}" style="width:100px"></label>`}
          <label class="small muted">Activity
            <select id="tg-act" style="min-width:220px">${ACTIVITY.map(([v, l]) =>
              `<option value="${v}"${String(p.activity) === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
        </div>
        <h3>Goal</h3>
        <div class="row">
          <select id="tg-goal" style="flex:1">
            <option value="lose"${p.goal === "lose" ? " selected" : ""}>Lose fat (deficit)</option>
            <option value="maintain"${p.goal === "maintain" ? " selected" : ""}>Maintain</option>
            <option value="gain"${p.goal === "gain" ? " selected" : ""}>Build (surplus)</option>
          </select>
          <label class="small muted" id="tg-rate-wrap"${p.goal === "maintain" ? " hidden" : ""}>
            ${wUnit()}/week
            <input id="tg-rate" type="number" step="0.1" min="0.1" max="2"
              value="${fmt1((p.rate_kg_week || 0.45) * (imp ? LB_PER_KG : 1))}" style="width:80px"></label>
          <label class="small muted">Goal weight (${wUnit()}, optional)
            <input id="tg-gw" type="number" step="0.1"
              value="${gw ? fmt1(gw * (imp ? LB_PER_KG : 1)) : ""}" style="width:90px"></label>
        </div>
        <h3>Macro split & water</h3>
        <div class="row">
          <select id="tg-preset" style="flex:1">
            <option value="">— preset —</option>
            <option value="30,40,30">Balanced 30P / 40C / 30F</option>
            <option value="40,30,30">High protein 40P / 30C / 30F</option>
            <option value="30,50,20">Endurance 30P / 50C / 20F</option>
            <option value="25,15,60">Low carb 25P / 15C / 60F</option>
          </select>
          <label class="small muted">P%<input id="tg-p" type="number" min="5" max="70" value="${p.protein_pct}" style="width:64px"></label>
          <label class="small muted">C%<input id="tg-c" type="number" min="5" max="70" value="${p.carbs_pct}" style="width:64px"></label>
          <label class="small muted">F%<input id="tg-f" type="number" min="5" max="70" value="${p.fat_pct}" style="width:64px"></label>
        </div>
        <div class="row" style="margin-top:6px">
          <label class="small muted">Water goal (${imp ? "oz" : "ml"}/day)
            <input id="tg-water" type="number" min="0"
              value="${imp ? r0(p.water_goal_ml / 29.5735) : p.water_goal_ml}" style="width:100px"></label>
          <label class="small muted">Fiber goal (g)
            <input id="tg-fiber" type="number" min="0" value="${p.fiber_goal_g}" style="width:80px"></label>
          <label class="small muted">Sodium limit (mg)
            <input id="tg-sodium" type="number" min="0" value="${p.sodium_limit_mg}" style="width:90px"></label>
          <label class="small muted">Sugar limit (g)
            <input id="tg-sugar" type="number" min="0" value="${p.sugar_limit_g}" style="width:80px"></label>
        </div>
        <div class="row" style="margin-top:12px">
          <button class="btn" id="tg-save">Save profile</button>
          <span class="small muted" id="tg-msg"></span>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Computed for you</h2>
          ${t.kg == null ? `<p class="hint">Add a weigh-in (Body tab or the
            button on Today) — weight is the one number the formulas can't
            live without.</p>` : `
          <div class="stat-row" style="grid-template-columns:1fr 1fr">
            <div class="stat"><div class="n">${r0(t.bmr)}</div>
              <div class="lbl">BMR — burned at rest</div></div>
            <div class="stat"><div class="n">${r0(t.tdee)}</div>
              <div class="lbl">maintenance (TDEE)</div></div>
            <div class="stat"><div class="n" style="color:var(--accent2)">${r0(t.target)}</div>
              <div class="lbl">your daily target</div></div>
            <div class="stat"><div class="n">${t.adjust ? (t.adjust < 0 ? "−" : "+") + r0(Math.abs(t.adjust)) : "±0"}</div>
              <div class="lbl">daily ${t.adjust < 0 ? "deficit" : t.adjust > 0 ? "surplus" : "adjustment"}</div></div>
          </div>
          <p class="hint" style="margin-top:10px">Daily macro goals:
            <b style="color:var(--protein)">${r0(t.protein_g)}g protein</b> ·
            <b style="color:var(--carbs)">${r0(t.carbs_g)}g carbs</b> ·
            <b style="color:var(--fat)">${r0(t.fat_g)}g fat</b></p>
          ${t.adjust && t.profile.goal_weight_kg && t.kg ? (() => {
            const deltaKg = Math.abs(t.kg - t.profile.goal_weight_kg);
            const weeks = t.profile.rate_kg_week ? deltaKg / t.profile.rate_kg_week : 0;
            return weeks > 0 && weeks < 500 ? `<p class="hint">At this rate,
              your goal weight is ≈ <b>${Math.ceil(weeks)} weeks</b> out
              (${niceDay(addDays(todayStr(), Math.ceil(weeks * 7)), true)}).</p>` : "";
          })() : ""}`}
          ${(() => {
            const est = observedTDEE();
            if (t.override) {
              return `<div class="notice" style="margin-top:10px">Using your
                <b>observed maintenance of ${r0(t.override)} kcal</b> (measured
                from your own logs and weigh-ins) instead of the formula.
                ${est && Math.abs(est.tdee - t.override) > 75
                  ? `Latest data now suggests ≈ ${r0(est.tdee)} kcal —
                     <button class="btn small ghost" id="tg-adopt">update to ${r0(est.tdee)}</button>` : ""}
                <button class="btn small ghost" id="tg-revert">Revert to formula</button></div>`;
            }
            if (est) {
              return `<div class="notice" style="margin-top:10px">
                📈 <b>Trend check:</b> over the last ${est.days} days
                (${est.logged} fully-logged), your intake and weight change
                imply a real-world maintenance of
                ≈ <b>${r0(est.tdee)} kcal/day</b>
                ${t.tdee ? `(formula says ${r0(t.tdee)})` : ""}.
                <button class="btn small" id="tg-adopt">Use ${r0(est.tdee)} as my maintenance</button></div>`;
            }
            return `<p class="hint">After ~2–3 weeks of weigh-ins and honest
              food logs, MacroKitchen estimates your <i>real</i> maintenance
              from the data (intake vs. weight slope) right here — usually
              more accurate than any formula.</p>`;
          })()}
          <p class="hint">Estimates from population formulas (Mifflin–St
            Jeor) — see the Guide tab for how each number is derived, and
            recalibrate against your real trend after a few weeks.</p>
        </div>

        <div class="card">
          <h2>Data & backup</h2>
          <p class="hint">Everything lives in <code>data/kitchen.db</code>
            inside the app folder. Backups are plain JSON.</p>
          <div class="row">
            <a class="btn small ghost" href="/api/backup" id="tg-backup">Download backup</a>
            <button class="btn small ghost" id="tg-restore">Restore from file…</button>
          </div>
        </div>
      </div>
    </div>`;

  $("#tg-goal").onchange = () => {
    $("#tg-rate-wrap").hidden = $("#tg-goal").value === "maintain";
  };
  $("#tg-adopt")?.addEventListener("click", async () => {
    const est = observedTDEE();
    if (!est) return;
    await saveProfile({ tdee_override: r0(est.tdee) });
    toast(`Maintenance set to ${r0(est.tdee)} kcal (observed)`);
    renderAll();
  });
  $("#tg-revert")?.addEventListener("click", async () => {
    await saveProfile({ tdee_override: null });
    toast("Back to the formula estimate");
    renderAll();
  });
  $("#tg-preset").onchange = () => {
    const v = $("#tg-preset").value;
    if (!v) return;
    const [pp, cc, ff] = v.split(",");
    $("#tg-p").value = pp; $("#tg-c").value = cc; $("#tg-f").value = ff;
  };
  $("#tg-backup").addEventListener("click", async (ev) => {
    ev.preventDefault();
    try {
      const data = await api("/api/backup");
      const blob = new Blob([JSON.stringify(data, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `macro-kitchen-backup-${todayStr()}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { toast(e.message); }
  });
  $("#tg-restore").onclick = () => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = "application/json";
    inp.onchange = async () => {
      const f = inp.files[0];
      if (!f) return;
      if (!confirm("Restoring replaces ALL of this account's current data " +
        "with the backup. A safety snapshot of the database is kept in " +
        "data/backups/. Continue?")) return;
      try {
        const payload = JSON.parse(await f.text());
        const d = await api("/api/restore", "POST", payload);
        toast("Restored: " + Object.entries(d.restored).map(([k, v]) => `${v} ${k}`).join(", "));
        await reload();
      } catch (e) { toast("Restore failed: " + e.message); }
    };
    inp.click();
  };
  $("#tg-save").onclick = async () => {
    const imp2 = $("#tg-units").value === "imperial";
    const pp = +$("#tg-p").value || 30, cc = +$("#tg-c").value || 40, ff = +$("#tg-f").value || 30;
    if (Math.abs(pp + cc + ff - 100) > 1) {
      $("#tg-msg").textContent = `macros add to ${pp + cc + ff}% — should be 100%`;
      return;
    }
    const height_cm = imp2
      ? ((+$("#tg-ft")?.value || 5) * 12 + (+$("#tg-in")?.value || 9)) * 2.54
      : +$("#tg-cm")?.value || 175;
    const rate = parseFloat($("#tg-rate").value) || 0.45;
    const gwv = parseFloat($("#tg-gw").value);
    const water = +$("#tg-water").value || 0;
    await saveProfile({
      units: $("#tg-units").value, sex: $("#tg-sex").value,
      birth_year: +$("#tg-year").value || 1990,
      height_cm: Math.round(height_cm * 10) / 10,
      activity: parseFloat($("#tg-act").value),
      goal: $("#tg-goal").value,
      rate_kg_week: imp2 ? rate / LB_PER_KG : rate,
      goal_weight_kg: gwv ? (imp2 ? gwv / LB_PER_KG : gwv) : null,
      protein_pct: pp, carbs_pct: cc, fat_pct: ff,
      water_goal_ml: imp2 ? Math.round(water * 29.5735) : water,
      fiber_goal_g: +$("#tg-fiber").value || 30,
      sodium_limit_mg: +$("#tg-sodium").value || 2300,
      sugar_limit_g: +$("#tg-sugar").value || 50,
    });
    toast("Profile saved");
    renderAll();
  };
}

// ============================================================ shell

function switchTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
}

const RENDERERS = {
  today: renderToday, guide: renderGuide, log: renderLog, plan: renderPlan,
  recipes: renderRecipes, ingredients: renderIngredients,
  shopping: renderShopping, body: renderBody, targets: renderTargets,
};

function renderAll() {
  $("#greeting").textContent = `plan · prep · track — hi, ${STATE.user.display_name}`;
  $("#user-chip").textContent = "@" + STATE.user.username;
  for (const fn of Object.values(RENDERERS)) fn();
}

async function enterApp() {
  await reload();
  $("#auth-screen").hidden = true;
  $("#app").hidden = false;
}

function init() {
  bindAuth();
  bindUserChip();
  $$("#tabs button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (TOKEN) {
    enterApp().catch(() => { /* token expired — auth screen already shown */ });
  } else {
    $("#auth-screen").hidden = false;
  }
}

init();
