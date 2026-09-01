# Nutrition — the macro-kitchen port

The Nutrition capability ($30, Operations group) is macro-kitchen — the
standalone meal-planning PWA — ported onto this platform the way
lingua-portal became Learning: the pure arithmetic came over whole, the
storage grew a tenant dimension, and checkout became the front desk.

| Layer | macro-kitchen had | on business-control |
| --- | --- | --- |
| The member | a local single-user app | `/nutrition` on the storefront, behind the tenant's Nutrition entitlement — targets, log, plan, shopping, body |
| The math | frontend JS | `erp/backend/nutrition_calc.py` — pure, no database, no clock, unit-tested in the suite |
| The library | one person's pantry | per-tenant: `owner_id NULL` rows are the house library (coach-curated), owned rows are the member's own |
| Coaching | none | the ops **Nutrition** tab: programs, the caseload, per-client adherence — all derived on read |
| Admissions | none | a program names a product (`nutrition_programs.product_id`); buying it opens the client seat, recording which order did |

## What the port keeps

- **Derived, never stored.** BMR (Mifflin–St Jeor), maintenance, the
  daily target, macro grams, streaks and adherence are computed on every
  read. The observed-maintenance estimate — mean logged intake minus the
  calories in the weight slope — refuses thin data (needs a 12-day
  weigh-in span and 10 honestly-logged days) and returns nothing rather
  than a shaky number. A member may adopt it over the formula, and revert.
- **History is immutable.** A food-log entry keeps the macros it had when
  eaten; editing a recipe later never rewrites what was logged.
- **Day-keyed upserts** for weight and water — logging again replaces,
  never duplicates.

## The privacy line

Tracking is open to any signed-in member of the tenant. The coach view
shows only people with a **seat** — bought through checkout or opened by
an admin. A member who tracks for themselves is on nobody's caseload:
oversight follows the seat, the way lessons follow enrolment.

## Layout

- `erp/backend/nutrition_calc.py` — the pure module.
- `erp/backend/nutrition.py` — tables, seats, programs, the coach routes.
- `storefront/backend/nutrition.py` — the member surface + `/nutrition`.
- `storefront/frontend/nutrition.js` — the member app (Today / Plan /
  Foods / Shopping / Body / Targets).

Estimates, not medicine — the page says so, and the numbers recalibrate
against the member's own trend as the data accumulates.
