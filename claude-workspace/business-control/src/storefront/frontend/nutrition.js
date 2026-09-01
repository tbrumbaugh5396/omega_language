/* The member's app at /nutrition: targets, the food log, the week's plan,
 * the shopping list, weight and water. macro-kitchen's frontend, re-homed.
 *
 * The server computes every derived number (targets, observed maintenance,
 * adherence, streaks) through the pure module; this file renders answers
 * and posts intents. The only arithmetic here is presentational: summing a
 * recipe's macros to label a planned meal.
 */
(function () {
  "use strict";
  const root = document.getElementById("nutrition-root");
  if (!root) return;

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const token = () => {
    try { return JSON.parse(localStorage.getItem("sf_support") || "{}").token; }
    catch { return null; }
  };
  async function api(path, body) {
    const r = await fetch(path, {
      method: body !== undefined ? "POST" : "GET",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + token() },
      body: body !== undefined ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch {}
      throw new Error(m);
    }
    return r.json();
  }

  const r0 = (n) => Math.round(n || 0);
  const todayStr = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${
      String(d.getDate()).padStart(2, "0")}`;
  };
  const addDays = (s, n) => {
    const d = new Date(s + "T12:00:00");
    d.setDate(d.getDate() + n);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${
      String(d.getDate()).padStart(2, "0")}`;
  };
  const mondayOf = (s) => {
    const d = new Date(s + "T12:00:00");
    return addDays(s, -((d.getDay() + 6) % 7));
  };
  const niceDay = (s) => new Date(s + "T12:00:00").toLocaleDateString(
    undefined, { weekday: "short", month: "short", day: "numeric" });

  const SLOTS = ["breakfast", "lunch", "dinner", "snack"];
  const SLOT_LABEL = { breakfast: "Breakfast", lunch: "Lunch",
                       dinner: "Dinner", snack: "Snacks" };
  const GLASS_ML = 250;
  const LB = 2.20462;

  let S = null;          // the whole /state payload
  let DAY = todayStr();
  let VIEW = "today";
  let PLAN_START = mondayOf(todayStr());

  const imperial = () => S.profile.units === "imperial";
  const wShow = (kg) => kg == null ? "-" : imperial()
    ? (Math.round(kg * LB * 10) / 10) + " lb"
    : (Math.round(kg * 10) / 10) + " kg";
  const wUnit = () => imperial() ? "lb" : "kg";
  const toKg = (v) => imperial() ? v / LB : v;
  const mlShow = (ml) => imperial() ? r0(ml / 29.5735) + " oz" : r0(ml) + " ml";

  async function reload(view) {
    S = await api("/api/nutrition/me/state?day=" + DAY);
    (view || draw)();
  }

  const ing = (id) => S.ingredients.find((i) => i.id === id);
  const rec = (id) => S.recipes.find((r) => r.id === id);
  function recipeMacros(r) {
    const tot = { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0,
                  sodium: 0, sugar: 0 };
    for (const it of S.recipe_items.filter((x) => x.recipe_id === r.id)) {
      const i = ing(it.ingredient_id);
      if (!i) continue;
      for (const k of Object.keys(tot)) tot[k] += (i[k] || 0) * it.qty;
    }
    for (const k of Object.keys(tot)) tot[k] /= (r.servings || 1);
    return tot;
  }
  function planInfo(e) {
    if (e.recipe_id && rec(e.recipe_id)) {
      const r = rec(e.recipe_id);
      return { name: r.name, per: recipeMacros(r) };
    }
    if (e.ingredient_id && ing(e.ingredient_id)) {
      const i = ing(e.ingredient_id);
      return { name: i.name, per: i };
    }
    return { name: e.title || "(untitled)",
             per: { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0,
                    sodium: 0, sugar: 0 } };
  }
  const entryFrom = (per, s) => ({
    cal: +(per.cal * s).toFixed(1), protein: +(per.protein * s).toFixed(1),
    carbs: +(per.carbs * s).toFixed(1), fat: +(per.fat * s).toFixed(1),
    fiber: +((per.fiber || 0) * s).toFixed(1),
    sodium: +((per.sodium || 0) * s).toFixed(1),
    sugar: +((per.sugar || 0) * s).toFixed(1) });

  /* ── shell ────────────────────────────────────────────────────────────── */
  function tabs() {
    const t = (id, label) => `<span class="ntr-tab ${VIEW === id ? "on" : ""}"
      data-t="${id}">${label}</span>`;
    return `<div class="ntr-tabs">${t("today", "Today")}${t("plan", "Plan")}${
      t("foods", "Foods")}${t("shopping", "Shopping")}${t("body", "Body")}${
      t("targets", "Targets")}</div>`;
  }
  function draw() {
    ({ today, plan, foods, shopping, body, targets }[VIEW] || today)();
    root.querySelectorAll("[data-t]").forEach((el) => el.onclick = () => {
      VIEW = el.dataset.t; draw();
    });
  }

  /* ── Today ────────────────────────────────────────────────────────────── */
  function ring(frac) {
    const size = 150, r = (size - 16) / 2, c = 2 * Math.PI * r;
    const cl = Math.min(1, Math.max(0, frac));
    return `<svg width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
        stroke="rgba(127,127,127,.25)" stroke-width="12"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
        stroke="currentColor" stroke-width="12" stroke-linecap="round"
        opacity="${frac > 1 ? 1 : .8}"
        stroke-dasharray="${c * cl} ${c}"/></svg>`;
  }
  const bar = (label, eaten, goal) => `
    <div class="ntr-bar-head"><span>${label}</span>
      <span class="ntr-meta">${r0(eaten)} / ${r0(goal)} g</span></div>
    <div class="ntr-track"><i class="ntr-fill ${goal && eaten > goal
      ? "over" : ""}" style="width:${Math.min(100,
        goal ? (eaten / goal) * 100 : 0)}%"></i></div>`;

  function today() {
    const t = S.targets;
    const goal = t.target || 2000;
    const tot = { cal: 0, protein: 0, carbs: 0, fat: 0, fiber: 0,
                  sodium: 0, sugar: 0 };
    for (const e of S.log) for (const k of Object.keys(tot)) tot[k] += e[k] || 0;
    const planToday = S.plan.filter((e) => e.day === DAY);
    const glasses = Math.max(8, Math.ceil(S.profile.water_goal_ml / GLASS_ML));
    const full = Math.round(S.water_ml / GLASS_ML);
    root.innerHTML = tabs() + `
      ${!t.has_numbers ? `<div class="ntr-notice">Add a weigh-in and check
        the <b>Targets</b> tab — your calorie target and macros compute from
        your own numbers (using ${r0(goal)} kcal as a placeholder).</div>` : ""}
      <div class="ntr-card"><div class="ntr-row" style="justify-content:space-between">
        <h3 style="margin:0">Today · ${niceDay(DAY)}</h3>
        <span><button class="ntr-btn sm" id="t-weigh">Weigh-in</button>
        <button class="ntr-btn sm primary" id="t-log">Log food</button></span></div>
      <div class="ntr-hero">
        <div class="ntr-ring">${ring(tot.cal / goal)}
          <div class="mid"><b style="font-size:1.6em">${r0(tot.cal)}</b>
            <span class="ntr-meta">of ${r0(goal)} kcal</span>
            <span class="ntr-meta">${tot.cal <= goal
              ? r0(goal - tot.cal) + " left"
              : r0(tot.cal - goal) + " over"}</span></div></div>
        <div class="ntr-bars">
          ${bar("Protein", tot.protein, t.protein_g)}
          ${bar("Carbs", tot.carbs, t.carbs_g)}
          ${bar("Fat", tot.fat, t.fat_g)}
          ${bar("Fiber", tot.fiber, S.profile.fiber_goal_g)}
          <p class="ntr-meta" style="margin:8px 0 0">Sodium ${r0(tot.sodium)}
            / ${S.profile.sodium_limit_mg} mg · Sugar ${r0(tot.sugar)}
            / ${S.profile.sugar_limit_g} g</p>
        </div></div></div>
      <div class="ntr-grid2">
        <div class="ntr-card"><h4 style="margin:0 0 4px">Water</h4>
          <p class="ntr-meta">${mlShow(S.water_ml)} of ${mlShow(
            S.profile.water_goal_ml)} — a glass is ${mlShow(GLASS_ML)}.
            Tap to drink; tap the last full one to undo.</p>
          <div class="ntr-glasses" id="t-glasses">${Array.from(
            { length: glasses }, (_, i) => `<span class="ntr-glass ${
              i < full ? "full" : ""}" data-i="${i}"></span>`).join("")}</div></div>
        <div class="ntr-card"><h4 style="margin:0 0 4px">Body</h4>
          <div class="ntr-stats">
            <div class="ntr-stat"><b>${wShow(t.latest_kg)}</b>
              <div class="ntr-meta">latest weight</div></div>
            <div class="ntr-stat"><b>${t.tdee ?? "-"}</b>
              <div class="ntr-meta">maintenance kcal${t.override
                ? " (observed)" : ""}</div></div></div>
          <p class="ntr-meta" style="margin:8px 0 0">${t.adjust
            ? `Your plan: a ${t.adjust < 0 ? "deficit" : "surplus"} of ${
              Math.abs(t.adjust)} kcal/day.`
            : "Goal: maintain — eat at maintenance."}</p></div>
      </div>
      <div class="ntr-card"><h4 style="margin:0 0 8px">Today's log</h4>
        ${S.log.map((e) => `<div class="ntr-item">
          <span class="grow"><b>${esc(e.name)}</b>
            <span class="ntr-meta">${esc(e.slot)} · ${r0(e.cal)} kcal ·
              P${r0(e.protein)} C${r0(e.carbs)} F${r0(e.fat)}</span></span>
          <button class="ntr-btn sm" data-del="${e.id}">x</button>
        </div>`).join("") || "<p class='ntr-meta'>Nothing logged yet.</p>"}
        ${planToday.length ? `<h4 style="margin:14px 0 4px">Planned today</h4>
          ${planToday.map((e) => {
            const info = planInfo(e);
            return `<div class="ntr-item ${e.done ? "ntr-done" : ""}">
              <span class="grow">${esc(info.name)}
                <span class="ntr-meta">${esc(e.slot)} ·
                  ${r0(info.per.cal * e.servings)} kcal</span></span>
              ${e.done ? "" : `<button class="ntr-btn sm"
                data-logplan="${e.id}">Log it</button>`}</div>`;
          }).join("")}` : ""}</div>`;
    root.querySelector("#t-weigh").onclick = weighForm;
    root.querySelector("#t-log").onclick = () => logForm();
    root.querySelector("#t-glasses").onclick = async (ev) => {
      const g = ev.target.closest(".ntr-glass");
      if (!g) return;
      const delta = +g.dataset.i < full ? -GLASS_ML : GLASS_ML;
      await api("/api/nutrition/me/water", { day: DAY, delta_ml: delta });
      reload();
    };
    root.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      await api(`/api/nutrition/me/log/${b.dataset.del}/delete`, {});
      reload();
    });
    root.querySelectorAll("[data-logplan]").forEach((b) => b.onclick =
      async () => {
        const e = S.plan.find((x) => x.id === +b.dataset.logplan);
        const info = planInfo(e);
        await api("/api/nutrition/me/log", { day: DAY, slot: e.slot,
          name: info.name, servings: e.servings,
          ...entryFrom(info.per, e.servings) });
        await api(`/api/nutrition/me/plan/${e.id}`, { done: 1 });
        reload();
      });
  }

  function weighForm() {
    const v = prompt(`Weight (${wUnit()}) for ${DAY}:`);
    if (!v) return;
    api("/api/nutrition/me/weight", { day: DAY, kg: toKg(parseFloat(v)) })
      .then(() => reload()).catch((e) => alert(e.message));
  }

  function logForm(slot) {
    const hour = new Date().getHours();
    slot = slot || (hour < 10 ? "breakfast" : hour < 14 ? "lunch"
      : hour < 20 ? "dinner" : "snack");
    const box = document.createElement("div");
    box.className = "ntr-card";
    box.id = "ntr-logform";
    box.innerHTML = `<h4 style="margin:0 0 8px">Log food</h4>
      <div class="ntr-row">
        <select id="lf-slot">${SLOTS.map((s) => `<option value="${s}"
          ${s === slot ? "selected" : ""}>${SLOT_LABEL[s]}</option>`).join("")}</select>
        <select id="lf-recipe"><option value="">from a recipe…</option>
          ${S.recipes.map((r) => `<option value="${r.id}">${esc(r.name)}
            (${r0(recipeMacros(r).cal)} kcal/serv)</option>`).join("")}</select>
        <select id="lf-ing"><option value="">a single food…</option>
          ${S.ingredients.map((i) => `<option value="${i.id}">${esc(i.name)}
            (${r0(i.cal)} kcal)</option>`).join("")}</select>
        <input id="lf-serv" type="number" value="1" step="0.25" min="0.25"
          style="width:70px" title="servings">
        <button class="ntr-btn sm primary" id="lf-go">Log</button>
      </div>
      <div class="ntr-row" style="margin-top:8px">
        <input id="lf-name" placeholder="or a quick manual entry…">
        <input id="lf-cal" type="number" placeholder="kcal" style="width:80px">
        <input id="lf-p" type="number" placeholder="P g" style="width:64px">
        <input id="lf-c" type="number" placeholder="C g" style="width:64px">
        <input id="lf-f" type="number" placeholder="F g" style="width:64px">
        <button class="ntr-btn sm" id="lf-manual">Log manual</button>
      </div>`;
    const old = document.getElementById("ntr-logform");
    if (old) return old.scrollIntoView();
    root.prepend(box);
    box.querySelector("#lf-go").onclick = async () => {
      const s = parseFloat(box.querySelector("#lf-serv").value) || 1;
      const rid = +box.querySelector("#lf-recipe").value;
      const iid = +box.querySelector("#lf-ing").value;
      let name, per;
      if (rid && rec(rid)) { name = rec(rid).name; per = recipeMacros(rec(rid)); }
      else if (iid && ing(iid)) { name = ing(iid).name; per = ing(iid); }
      else return alert("pick a recipe or a food");
      await api("/api/nutrition/me/log", {
        day: DAY, slot: box.querySelector("#lf-slot").value, name,
        servings: s, ...entryFrom(per, s) });
      reload();
    };
    box.querySelector("#lf-manual").onclick = async () => {
      const name = box.querySelector("#lf-name").value.trim();
      if (!name) return alert("name what you ate");
      await api("/api/nutrition/me/log", {
        day: DAY, slot: box.querySelector("#lf-slot").value, name,
        servings: 1, cal: +box.querySelector("#lf-cal").value || 0,
        protein: +box.querySelector("#lf-p").value || 0,
        carbs: +box.querySelector("#lf-c").value || 0,
        fat: +box.querySelector("#lf-f").value || 0 });
      reload();
    };
  }

  /* ── Plan ─────────────────────────────────────────────────────────────── */
  function plan() {
    const days = Array.from({ length: 7 }, (_, i) => addDays(PLAN_START, i));
    const goal = S.targets.target || 2000;
    root.innerHTML = tabs() + `
      <div class="ntr-row" style="justify-content:space-between;margin-bottom:10px">
        <span><button class="ntr-btn sm" id="p-prev">&larr;</button>
          <b style="margin:0 8px">${niceDay(days[0])} – ${niceDay(days[6])}</b>
          <button class="ntr-btn sm" id="p-next">&rarr;</button></span>
        <button class="ntr-btn sm" id="p-shop">Shopping list from this week</button>
      </div>
      <div class="ntr-week">
        ${days.map((day) => {
          const entries = S.plan.filter((e) => e.day === day);
          const kcal = entries.reduce((a, e) =>
            a + planInfo(e).per.cal * e.servings, 0);
          return `<div class="ntr-day ${day === todayStr() ? "today" : ""}">
            <h5>${niceDay(day)}</h5>
            <span class="ntr-meta">${r0(kcal)} / ${r0(goal)} kcal</span>
            ${SLOTS.map((slot) => {
              const rows = entries.filter((e) => e.slot === slot);
              return `<div class="ntr-slot">${SLOT_LABEL[slot]}</div>
                ${rows.map((e) => {
                  const info = planInfo(e);
                  return `<div class="ntr-meal ${e.done ? "done" : ""}"
                    data-pdel="${e.id}" title="click to remove">
                    <span>${esc(info.name)}</span>
                    <span class="ntr-meta">${r0(info.per.cal * e.servings)}</span>
                  </div>`;
                }).join("")}
                <div class="ntr-add" data-padd="${day}|${slot}">+ add</div>`;
            }).join("")}
          </div>`;
        }).join("")}
      </div>
      <div id="p-form"></div>`;
    root.querySelector("#p-prev").onclick = () => {
      PLAN_START = addDays(PLAN_START, -7); draw(); };
    root.querySelector("#p-next").onclick = () => {
      PLAN_START = addDays(PLAN_START, 7); draw(); };
    root.querySelector("#p-shop").onclick = async () => {
      const r = await api("/api/nutrition/me/shopping/generate",
        { start: days[0], end: days[6] });
      alert(r.added ? `Added ${r.added} items to the shopping list`
        : "Nothing planned this week");
      VIEW = "shopping"; reload();
    };
    root.querySelectorAll("[data-pdel]").forEach((el) => el.onclick =
      async () => {
        await api(`/api/nutrition/me/plan/${el.dataset.pdel}/delete`, {});
        reload();
      });
    root.querySelectorAll("[data-padd]").forEach((el) => el.onclick = () => {
      const [day, slot] = el.dataset.padd.split("|");
      const f = root.querySelector("#p-form");
      f.innerHTML = `<div class="ntr-card"><h4 style="margin:0 0 8px">
          Plan ${SLOT_LABEL[slot].toLowerCase()} for ${niceDay(day)}</h4>
        <div class="ntr-row">
          <select id="pf-recipe"><option value="">a recipe…</option>
            ${S.recipes.map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select>
          <select id="pf-ing"><option value="">a food…</option>
            ${S.ingredients.map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("")}</select>
          <input id="pf-title" placeholder="or free text (eating out…)">
          <input id="pf-serv" type="number" value="1" step="0.25" min="0.25"
            style="width:70px">
          <button class="ntr-btn sm primary" id="pf-go">Add</button>
        </div></div>`;
      f.querySelector("#pf-go").onclick = async () => {
        const rid = +f.querySelector("#pf-recipe").value || null;
        const iid = rid ? null : +f.querySelector("#pf-ing").value || null;
        const title = rid || iid ? "" : f.querySelector("#pf-title").value;
        try {
          await api("/api/nutrition/me/plan", { day, slot, recipe_id: rid,
            ingredient_id: iid, title,
            servings: parseFloat(f.querySelector("#pf-serv").value) || 1 });
          reload();
        } catch (err) { alert(err.message); }
      };
      f.scrollIntoView();
    });
  }

  /* ── Foods ────────────────────────────────────────────────────────────── */
  function foods() {
    root.innerHTML = tabs() + `
      <div class="ntr-grid2">
        <div class="ntr-card"><h4 style="margin:0 0 4px">Recipes
          (${S.recipes.length})</h4>
          <p class="ntr-meta">Shared ones come from the house library;
            yours are yours alone.</p>
          ${S.recipes.map((r) => {
            const m = recipeMacros(r);
            return `<div class="ntr-item"><span class="grow">
              <b>${esc(r.name)}</b> <span class="ntr-meta">${r0(m.cal)} kcal
              · P${r0(m.protein)} C${r0(m.carbs)} F${r0(m.fat)} per serving${
              r.owner_id ? "" : " · house"}</span></span>
              ${r.owner_id ? `<button class="ntr-btn sm"
                data-rdel="${r.id}">x</button>` : ""}</div>`;
          }).join("") || "<p class='ntr-meta'>None yet.</p>"}
          <div class="ntr-row" style="margin-top:8px">
            <input id="nr-name" placeholder="new recipe name">
            <input id="nr-serv" type="number" value="1" min="0.5" step="0.5"
              style="width:70px" title="servings it makes">
            <button class="ntr-btn sm" id="nr-add">Create</button></div>
          <p class="ntr-meta">Create it empty, then add lines below.</p>
          <div class="ntr-row">
            <select id="nr-pick"><option value="">recipe…</option>
              ${S.recipes.filter((r) => r.owner_id).map((r) =>
                `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select>
            <select id="nr-ing"><option value="">food…</option>
              ${S.ingredients.map((i) =>
                `<option value="${i.id}">${esc(i.name)}</option>`).join("")}</select>
            <input id="nr-qty" type="number" value="1" step="0.25"
              style="width:70px">
            <button class="ntr-btn sm" id="nr-line">Add line</button></div>
        </div>
        <div class="ntr-card"><h4 style="margin:0 0 4px">Foods
          (${S.ingredients.length})</h4>
          <p class="ntr-meta">Per-serving numbers, straight off the label.</p>
          <div style="max-height:340px;overflow-y:auto">
          ${S.ingredients.map((i) => `<div class="ntr-item">
            <span class="grow"><b>${esc(i.name)}</b>
              <span class="ntr-meta">${esc(i.serving_name || "serving")} ·
                ${r0(i.cal)} kcal · P${r0(i.protein)} C${r0(i.carbs)}
                F${r0(i.fat)}${i.owner_id ? "" : " · house"}</span></span>
          </div>`).join("")}</div>
          <div class="ntr-row" style="margin-top:8px">
            <input id="ni-name" placeholder="name" style="width:130px">
            <input id="ni-serving" placeholder="serving" style="width:90px">
            <input id="ni-cal" type="number" placeholder="kcal" style="width:70px">
            <input id="ni-p" type="number" placeholder="P" style="width:56px">
            <input id="ni-c" type="number" placeholder="C" style="width:56px">
            <input id="ni-f" type="number" placeholder="F" style="width:56px">
            <button class="ntr-btn sm" id="ni-add">Add food</button></div>
        </div>
      </div>`;
    root.querySelector("#ni-add").onclick = async () => {
      try {
        await api("/api/nutrition/me/ingredients", {
          name: root.querySelector("#ni-name").value,
          serving_name: root.querySelector("#ni-serving").value,
          cal: +root.querySelector("#ni-cal").value || 0,
          protein: +root.querySelector("#ni-p").value || 0,
          carbs: +root.querySelector("#ni-c").value || 0,
          fat: +root.querySelector("#ni-f").value || 0 });
        reload();
      } catch (err) { alert(err.message); }
    };
    root.querySelector("#nr-add").onclick = async () => {
      try {
        await api("/api/nutrition/me/recipes", {
          name: root.querySelector("#nr-name").value,
          servings: parseFloat(root.querySelector("#nr-serv").value) || 1,
          items: [] });
        reload();
      } catch (err) { alert(err.message); }
    };
    root.querySelector("#nr-line").onclick = async () => {
      const rid = +root.querySelector("#nr-pick").value;
      const iid = +root.querySelector("#nr-ing").value;
      if (!rid || !iid) return alert("pick a recipe and a food");
      const r = rec(rid);
      const items = S.recipe_items.filter((x) => x.recipe_id === rid)
        .map((x) => ({ ingredient_id: x.ingredient_id, qty: x.qty }));
      items.push({ ingredient_id: iid,
        qty: parseFloat(root.querySelector("#nr-qty").value) || 1 });
      try {
        // simplest correct edit: replace the recipe wholesale
        await api(`/api/nutrition/me/recipes/${rid}/delete`, {});
        await api("/api/nutrition/me/recipes", { name: r.name,
          meal_type: r.meal_type, servings: r.servings,
          prep_min: r.prep_min, instructions: r.instructions, items });
        reload();
      } catch (err) { alert(err.message); }
    };
    root.querySelectorAll("[data-rdel]").forEach((b) => b.onclick =
      async () => {
        await api(`/api/nutrition/me/recipes/${b.dataset.rdel}/delete`, {});
        reload();
      });
  }

  /* ── Shopping ─────────────────────────────────────────────────────────── */
  function shopping() {
    const items = S.shopping;
    const cats = [...new Set(items.map((i) => i.category))];
    root.innerHTML = tabs() + `
      <div class="ntr-card">
        <div class="ntr-row" style="justify-content:space-between">
          <h4 style="margin:0">Shopping list</h4>
          ${items.some((i) => i.checked) ? `<button class="ntr-btn sm"
            id="s-clear">Clear checked</button>` : ""}</div>
        <div class="ntr-row" style="margin:8px 0">
          <input id="s-name" placeholder="add an item…">
          <input id="s-qty" placeholder="qty" style="width:70px">
          <button class="ntr-btn sm" id="s-add">Add</button></div>
        ${cats.map((c) => `<div class="ntr-slot">${esc(c)}</div>
          ${items.filter((i) => i.category === c).map((i) => `
            <div class="ntr-item ${i.checked ? "ntr-done" : ""}">
              <input type="checkbox" ${i.checked ? "checked" : ""}
                data-chk="${i.id}">
              <span class="grow">${esc(i.name)}</span>
              <span class="ntr-meta">${esc(i.qty)}</span>
              <button class="ntr-btn sm" data-sdel="${i.id}">x</button>
            </div>`).join("")}`).join("")
          || "<p class='ntr-meta'>Empty — generate one from the Plan tab.</p>"}
      </div>`;
    root.querySelector("#s-add").onclick = async () => {
      const name = root.querySelector("#s-name").value.trim();
      if (!name) return;
      await api("/api/nutrition/me/shopping",
        { name, qty: root.querySelector("#s-qty").value });
      reload();
    };
    const clear = root.querySelector("#s-clear");
    if (clear) clear.onclick = async () => {
      await api("/api/nutrition/me/shopping/clear-checked", {});
      reload();
    };
    root.querySelectorAll("[data-chk]").forEach((c) => c.onchange =
      async () => {
        await api(`/api/nutrition/me/shopping/${c.dataset.chk}`,
          { checked: c.checked ? 1 : 0 });
        reload();
      });
    root.querySelectorAll("[data-sdel]").forEach((b) => b.onclick =
      async () => {
        await api(`/api/nutrition/me/shopping/${b.dataset.sdel}/delete`, {});
        reload();
      });
  }

  /* ── Body ─────────────────────────────────────────────────────────────── */
  function weightChart() {
    const w = S.weights;
    if (w.length < 2) {
      return "<p class='ntr-meta'>Two weigh-ins draw the trend line.</p>";
    }
    const pts = w.map((x, i) => {
      const win = w.slice(Math.max(0, i - 6), i + 1);
      return { ...x, avg: win.reduce((a, y) => a + y.kg, 0) / win.length };
    });
    const goalKg = S.profile.goal_weight_kg;
    const W = Math.max(420, Math.min(900, pts.length * 22)), H = 190;
    const padL = 40, padR = 10, padT = 10, padB = 22;
    const kgs = pts.map((x) => x.kg).concat(goalKg ? [goalKg] : []);
    let lo = Math.min(...kgs), hi = Math.max(...kgs);
    const span = Math.max(1, hi - lo);
    lo -= span * .1; hi += span * .1;
    const X = (i) => padL + (i / (pts.length - 1)) * (W - padL - padR);
    const Y = (kg) => padT + (1 - (kg - lo) / (hi - lo)) * (H - padT - padB);
    const disp = (kg) => imperial() ? r0(kg * LB) : r0(kg);
    return `<div class="ntr-chart"><svg width="${W}" height="${H}">
      ${[1, 2, 3, 4].map((i) => {
        const kg = lo + (i / 5) * (hi - lo);
        return `<line x1="${padL}" y1="${Y(kg)}" x2="${W - padR}"
          y2="${Y(kg)}" stroke="rgba(127,127,127,.25)" stroke-dasharray="2 4"/>
          <text x="4" y="${Y(kg) + 3}" style="font-size:9px"
            fill="currentColor" opacity=".6">${disp(kg)}</text>`;
      }).join("")}
      ${goalKg ? `<line x1="${padL}" y1="${Y(goalKg)}" x2="${W - padR}"
        y2="${Y(goalKg)}" stroke="currentColor" opacity=".5"
        stroke-dasharray="6 4"/>` : ""}
      ${pts.map((x, i) => `<circle cx="${X(i)}" cy="${Y(x.kg)}" r="2.5"
        fill="currentColor" opacity=".45"/>`).join("")}
      <path d="M${pts.map((x, i) => `${X(i)},${Y(x.avg)}`).join(" L")}"
        fill="none" stroke="currentColor" stroke-width="2.5"/>
    </svg></div>
    <p class="ntr-meta">Dots are weigh-ins (${wUnit()}); the line is the
      7-day average — trust the line, not the dots.</p>`;
  }

  function body() {
    const a = S.adherence;
    root.innerHTML = tabs() + `
      <div class="ntr-card">
        <div class="ntr-row" style="justify-content:space-between">
          <h4 style="margin:0">Weight</h4>
          <button class="ntr-btn sm" id="b-weigh">Weigh-in</button></div>
        ${weightChart()}
      </div>
      <div class="ntr-card"><h4 style="margin:0 0 8px">Streaks & adherence</h4>
        <div class="ntr-stats">
          <div class="ntr-stat"><b>${a.streaks.current}</b>
            <div class="ntr-meta">day logging streak</div></div>
          <div class="ntr-stat"><b>${a.streaks.best}</b>
            <div class="ntr-meta">best streak</div></div>
          <div class="ntr-stat"><b>${a.days.filter((d) => d.on_target).length}
            /${a.days.length}</b>
            <div class="ntr-meta">days on target</div></div>
        </div>
        <div class="ntr-cal14" style="margin-top:10px">
          ${a.days.map((d) => `<span class="ntr-daybox ${d.on_target
            ? "hit" : d.logged ? "part" : ""}" title="${d.day}: ${
            d.kcal} kcal">${d.day.slice(8)}</span>`).join("")}
        </div>
        <p class="ntr-meta">Bold green: on target. Amber: logged but off.
          Dim: not logged. Consistency beats perfection.</p>
      </div>`;
    root.querySelector("#b-weigh").onclick = weighForm;
  }

  /* ── Targets ──────────────────────────────────────────────────────────── */
  function targets() {
    const p = S.profile, t = S.targets;
    const opt = (v, cur, label) =>
      `<option value="${v}" ${String(cur) === String(v) ? "selected" : ""}>${
        label}</option>`;
    root.innerHTML = tabs() + `
      <div class="ntr-grid2">
      <div class="ntr-card"><h4 style="margin:0 0 8px">Your profile</h4>
        <div class="ntr-row">
          <select id="tg-units">${opt("metric", p.units, "Metric (kg, cm)")}${
            opt("imperial", p.units, "Imperial (lb, ft)")}</select>
          <select id="tg-sex">${opt("male", p.sex, "Male")}${
            opt("female", p.sex, "Female")}</select>
          <input id="tg-year" type="number" value="${p.birth_year}"
            style="width:80px" title="birth year">
          <input id="tg-height" type="number" value="${p.height_cm}"
            style="width:80px" title="height in cm"> cm
        </div>
        <div class="ntr-row" style="margin-top:8px">
          <select id="tg-act">
            ${opt(1.2, p.activity, "Sedentary")}
            ${opt(1.375, p.activity, "Light activity")}
            ${opt(1.55, p.activity, "Moderate")}
            ${opt(1.725, p.activity, "Active")}
            ${opt(1.9, p.activity, "Athlete")}</select>
          <select id="tg-goal">${opt("lose", p.goal, "Lose fat")}${
            opt("maintain", p.goal, "Maintain")}${
            opt("gain", p.goal, "Build")}</select>
          <input id="tg-rate" type="number" step="0.1" value="${p.rate_kg_week}"
            style="width:70px" title="kg per week"> kg/wk
          <input id="tg-gw" type="number" step="0.1"
            value="${p.goal_weight_kg ?? ""}" placeholder="goal kg"
            style="width:80px">
        </div>
        <div class="ntr-row" style="margin-top:8px">
          P% <input id="tg-p" type="number" value="${p.protein_pct}" style="width:56px">
          C% <input id="tg-c" type="number" value="${p.carbs_pct}" style="width:56px">
          F% <input id="tg-f" type="number" value="${p.fat_pct}" style="width:56px">
          water <input id="tg-water" type="number" value="${p.water_goal_ml}"
            style="width:80px"> ml
        </div>
        <p style="margin-top:12px"><button class="ntr-btn primary"
          id="tg-save">Save profile</button></p>
      </div>
      <div class="ntr-card"><h4 style="margin:0 0 8px">Computed for you</h4>
        ${t.has_numbers ? `<div class="ntr-stats">
          <div class="ntr-stat"><b>${t.bmr ?? "-"}</b>
            <div class="ntr-meta">BMR at rest</div></div>
          <div class="ntr-stat"><b>${t.tdee}</b>
            <div class="ntr-meta">maintenance${t.override ? " (observed)" : ""}</div></div>
          <div class="ntr-stat"><b>${t.target}</b>
            <div class="ntr-meta">daily target</div></div>
          <div class="ntr-stat"><b>${t.adjust > 0 ? "+" : ""}${t.adjust}</b>
            <div class="ntr-meta">daily ${t.adjust < 0 ? "deficit"
              : t.adjust > 0 ? "surplus" : "adjustment"}</div></div>
        </div>
        <p class="ntr-meta" style="margin-top:8px">Daily macros:
          ${t.protein_g}g protein · ${t.carbs_g}g carbs · ${t.fat_g}g fat</p>`
        : "<p class='ntr-meta'>Add a weigh-in — weight is the number the formulas cannot live without.</p>"}
        ${t.override ? `<div class="ntr-notice">Using your observed
          maintenance of <b>${t.override} kcal</b> instead of the formula.
          <button class="ntr-btn sm" id="tg-revert">Revert to formula</button>
          </div>`
        : t.observed ? `<div class="ntr-notice">Trend check: over the last
          ${t.observed.days} days (${t.observed.logged} fully logged), your
          intake and weight change imply a real-world maintenance of
          <b>${t.observed.tdee} kcal/day</b>${t.tdee
            ? ` (formula says ${t.tdee})` : ""}.
          <button class="ntr-btn sm" id="tg-adopt">Use ${t.observed.tdee}
            as my maintenance</button></div>`
        : `<p class="ntr-meta">After ~2-3 weeks of weigh-ins and honest
          logs, your real maintenance is estimated here from the data —
          usually better than any formula.</p>`}
        <p class="ntr-meta">Mifflin-St Jeor estimates, not medicine.</p>
      </div></div>`;
    const saveP = (extra) => api("/api/nutrition/me/profile", {
      units: root.querySelector("#tg-units").value,
      sex: root.querySelector("#tg-sex").value,
      birth_year: +root.querySelector("#tg-year").value || 1990,
      height_cm: +root.querySelector("#tg-height").value || 175,
      activity: +root.querySelector("#tg-act").value || 1.55,
      goal: root.querySelector("#tg-goal").value,
      rate_kg_week: +root.querySelector("#tg-rate").value || 0,
      goal_weight_kg: +root.querySelector("#tg-gw").value || null,
      protein_pct: +root.querySelector("#tg-p").value || 30,
      carbs_pct: +root.querySelector("#tg-c").value || 40,
      fat_pct: +root.querySelector("#tg-f").value || 30,
      water_goal_ml: +root.querySelector("#tg-water").value || 2500,
      fiber_goal_g: p.fiber_goal_g, sodium_limit_mg: p.sodium_limit_mg,
      sugar_limit_g: p.sugar_limit_g,
      tdee_override: p.tdee_override, ...extra });
    root.querySelector("#tg-save").onclick = () =>
      saveP({}).then(() => reload()).catch((e) => alert(e.message));
    const adopt = root.querySelector("#tg-adopt");
    if (adopt) adopt.onclick = () =>
      saveP({ tdee_override: t.observed.tdee }).then(() => reload())
        .catch((e) => alert(e.message));
    const revert = root.querySelector("#tg-revert");
    if (revert) revert.onclick = () =>
      saveP({ tdee_override: null }).then(() => reload())
        .catch((e) => alert(e.message));
  }

  /* ── boot ─────────────────────────────────────────────────────────────── */
  if (!token()) {
    root.innerHTML = `<p>Sign in with the <b>account</b> door on
      <a href="/">the shop</a> (the same sign-in you order with), then come
      back — your tracking is private to your account.</p>`;
    return;
  }
  reload().catch((e) => {
    root.innerHTML = `<p class="ntr-meta">${esc(e.message)}</p>`;
  });
})();
