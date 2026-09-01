# MacroKitchen

A local-first, multi-user PWA for meal planning, meal prep, nutrition
tracking, and body metrics — a visual guide *and* a tracker.

- **Today** — calorie ring vs. your daily target, macro bars, water glasses,
  quick logging, today's planned meals with one-tap "log it".
- **Guide** — visual training: energy balance, BMR/TDEE (computed live from
  *your* profile), deficit math, macros 101, the plate method, hydration, and
  a weekly meal-prep workflow.
- **Log** — the diet diary: log recipes, single ingredients, or quick manual
  entries per meal slot; daily totals vs. target with deficit/surplus.
- **Plan** — weekly planner (days × meal slots) with per-day calorie totals
  against your target; copy days; "repeat last week" for steady-state prep;
  generate a shopping list from any range.
- **Recipes** — recipe builder over your ingredient library; per-serving
  macros computed automatically.
- **Ingredients** — your library with per-serving macros plus fiber, sodium,
  sugar; a "pantry" flag marks what you already have at home.
- **Shopping** — aggregated list grouped by store category, check-off flow;
  generation can skip pantry-flagged ingredients.
- **Body** — weight log with 7-day trend line and goal line, water history,
  logging streaks and a days-on-target adherence calendar.
- **Targets** — profile (units, sex, age, height, activity), goal &
  weekly rate, computed BMR / maintenance / daily target, macro split,
  fiber/sodium/sugar goals, water goal, backup & restore. After 2–3 weeks
  of logs + weigh-ins it also estimates your *observed* maintenance from
  the data (intake vs. weight slope) and can use that instead of the
  formula.

## Stack

FastAPI + SQLite (WAL) backend, vanilla-JS PWA frontend, zero build step.
Multi-user with local accounts (pbkdf2 passwords, bearer-token sessions).
All data stays in `data/kitchen.db` inside this folder.

## Running

Double-click `command_utilities/Install MacroKitchen.command` once, then
`Start MacroKitchen.command` → http://127.0.0.1:8900. See `START HERE.txt`.

Dev loop from a terminal:

```bash
./.venv/bin/python3 scripts/launch.py --port 8900
```

## Layout

```
command_utilities/   double-click installers / start / stop / seed / uninstall
scripts/             launch.py (server), make_icons.py, seed.py
tools/make_launcher.py  Desktop .app builder (macOS)
src/backend/         FastAPI app (main.py), db.py schema, seeder.py
src/frontend/        index.html, app.js, styles.css, sw.js, manifest
data/                kitchen.db, config.json, server.pid (created at runtime)
```

## Notes

- Canonical units are metric in storage (kg / ml / cm); the UI converts when
  the profile is set to imperial.
- Calorie math: Mifflin–St Jeor BMR × activity factor = maintenance (TDEE);
  goal rate maps ±7700 kcal per kg of weekly change. Estimates, not medicine.
- Specific API routes are declared before the generic `/api/{table}` CRUD
  routes so they win the match (same convention as the sibling projects).
