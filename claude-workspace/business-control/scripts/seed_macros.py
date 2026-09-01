#!/usr/bin/env python3
"""Seed the macros tenant with macro-kitchen's own demo world, so the full
Nutrition experience is explorable the moment you open macros.localhost.

This is macro-kitchen's seeder ported onto the platform's tables: the
house food library (the same fifty label-value ingredients, sodium and
sugar included), the meal-prep recipes, and one loaded member — Mia
Tracker — with three weeks of weigh-ins and honest food logs, so the
observed-maintenance trend check has something real to say on first load.
A coach, a program sold as a product (checkout is the coaching desk), and
a second member who just tracks privately round out the model: Mia is on
the caseload because she holds a seat; Leo is not, because oversight
follows the seat.

It also dresses the tenant in macro-kitchen's identity: the dark kitchen
green, the fresh-green accent, and the plate-of-macros voice.

Stand the tenant up first (scripts/standup_macros.py does both), or:
    caps = selling + payments + nutrition — deliberately narrow, so the
    cap wall is part of the demo: macros.localhost has no /learn.

Idempotent: refuses to run over a tenant that already has a food library.
Sign-ins are by NAME (dev mode): Mia Tracker, Leo Lifter, Coach Cora,
Admin Max.
"""

import json
import sys
import time
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DAY = 86400

TENANT = sys.argv[1] if len(sys.argv) > 1 else "macros"
DB = ROOT / "data" / "tenants" / TENANT / "business_control.db"

# macro-kitchen's palette, from its styles.css: deep kitchen green,
# fresh-green accent, amber for the one hot button.
THEME = {
    "brand": "Macros", "dot": ".",
    "title": "Macros — plan, prep, track",
    "description": "Meal planning and honest tracking, with a coach when "
                   "you want one.",
    "purple": "#4ade80",       # the accent: fresh green on the dark ground
    "lavender": "#86efac",     # its lighter step
    "orange": "#f5bb49",       # the hot button: the carbs amber
    "ink": "#f2f8f3", "bg": "#0f1a14",
    "paper": "#182a20",
    "font": "Inter", "display_font": "Inter", "wordmark_font": "Inter",
    "announce": [], "art": "card",
    "footer": "Macros — eat like you mean it",
}

# (name, category, serving_name, cal, protein, carbs, fat, fiber,
#  sodium_mg, sugar_g) — macro-kitchen's starter pantry, label values.
INGREDIENTS = [
    ("Chicken breast (raw)", "protein", "100 g", 120, 22.5, 0, 2.6, 0, 45, 0),
    ("Chicken thigh (raw, skinless)", "protein", "100 g", 144, 19, 0, 7.9, 0, 95, 0),
    ("Ground beef 90/10 (raw)", "protein", "100 g", 176, 20, 0, 10, 0, 66, 0),
    ("Ground turkey 93/7 (raw)", "protein", "100 g", 150, 19, 0, 8, 0, 70, 0),
    ("Salmon fillet (raw)", "protein", "100 g", 208, 20, 0, 13, 0, 59, 0),
    ("Canned tuna in water (drained)", "protein", "1 can (140 g)", 130, 29, 0, 1, 0, 320, 0),
    ("Egg (large)", "protein", "1 egg", 72, 6.3, 0.4, 4.8, 0, 71, 0.2),
    ("Egg whites", "protein", "100 g", 52, 11, 0.7, 0.2, 0, 166, 0.7),
    ("Extra-firm tofu", "protein", "100 g", 94, 10, 2.3, 5.3, 1, 14, 0.7),
    ("Shrimp (raw, peeled)", "protein", "100 g", 85, 20, 0.2, 0.5, 0, 120, 0),
    ("Whey protein powder", "protein", "1 scoop (30 g)", 120, 24, 3, 1.5, 0, 50, 2),
    ("Black beans (cooked)", "protein", "1/2 cup (86 g)", 114, 7.6, 20, 0.5, 7.5, 1, 0.3),
    ("Chickpeas (cooked)", "protein", "1/2 cup (82 g)", 134, 7.3, 22, 2.1, 6.2, 6, 2.4),
    ("Lentils (cooked)", "protein", "1/2 cup (99 g)", 115, 9, 20, 0.4, 7.8, 2, 1.8),
    ("Greek yogurt, nonfat plain", "dairy", "170 g cup", 100, 17, 6, 0.7, 0, 61, 5.5),
    ("Cottage cheese 2%", "dairy", "1/2 cup (113 g)", 90, 12, 5, 2.5, 0, 350, 4),
    ("Cheddar cheese", "dairy", "28 g", 114, 6.5, 0.9, 9.4, 0, 180, 0.1),
    ("Mozzarella, part-skim", "dairy", "28 g", 72, 6.9, 0.8, 4.5, 0, 175, 0.3),
    ("Milk 2%", "dairy", "1 cup (244 g)", 122, 8, 12, 4.8, 0, 115, 12),
    ("Butter", "dairy", "1 tbsp (14 g)", 102, 0.1, 0, 11.5, 0, 91, 0),
    ("White rice (cooked)", "grains", "1 cup (158 g)", 205, 4.3, 45, 0.4, 0.6, 2, 0.1),
    ("Brown rice (cooked)", "grains", "1 cup (195 g)", 216, 5, 45, 1.8, 3.5, 10, 0.7),
    ("Quinoa (cooked)", "grains", "1 cup (185 g)", 222, 8.1, 39, 3.6, 5.2, 13, 1.6),
    ("Rolled oats (dry)", "grains", "1/2 cup (40 g)", 150, 5, 27, 3, 4, 0, 1),
    ("Whole-wheat bread", "grains", "1 slice", 81, 4, 14, 1.1, 1.9, 144, 1.4),
    ("Whole-wheat tortilla", "grains", "1 tortilla (45 g)", 130, 4, 22, 3, 3, 320, 1),
    ("Pasta (cooked)", "grains", "1 cup (140 g)", 220, 8.1, 43, 1.3, 2.5, 1, 0.8),
    ("Sweet potato", "grains", "1 medium (130 g)", 112, 2, 26, 0.1, 3.9, 41, 5.4),
    ("Broccoli", "produce", "1 cup (91 g)", 31, 2.6, 6, 0.3, 2.4, 30, 1.5),
    ("Spinach (raw)", "produce", "2 cups (60 g)", 14, 1.7, 2.2, 0.2, 1.3, 47, 0.3),
    ("Mixed salad greens", "produce", "2 cups (85 g)", 18, 1.5, 3.5, 0.2, 1.8, 15, 1),
    ("Bell pepper", "produce", "1 medium (119 g)", 24, 1, 6, 0.2, 2.1, 5, 4),
    ("Onion", "produce", "1/2 medium (55 g)", 22, 0.6, 5.1, 0.1, 0.9, 2, 2.3),
    ("Tomato", "produce", "1 medium (123 g)", 22, 1.1, 4.8, 0.2, 1.5, 6, 3.2),
    ("Carrot", "produce", "1 medium (61 g)", 25, 0.6, 6, 0.1, 1.7, 42, 2.9),
    ("Banana", "produce", "1 medium (118 g)", 105, 1.3, 27, 0.4, 3.1, 1, 14),
    ("Apple", "produce", "1 medium (182 g)", 95, 0.5, 25, 0.3, 4.4, 2, 19),
    ("Blueberries", "produce", "1 cup (148 g)", 84, 1.1, 21, 0.5, 3.6, 1, 15),
    ("Avocado", "produce", "1/2 fruit (100 g)", 160, 2, 8.5, 14.7, 6.7, 7, 0.7),
    ("Cucumber", "produce", "1/2 cucumber (150 g)", 23, 1, 5.4, 0.2, 0.8, 3, 2.5),
    ("Frozen mixed vegetables", "frozen", "1 cup (91 g)", 60, 2.6, 12, 0.5, 4, 45, 4),
    ("Frozen berries", "frozen", "1 cup (140 g)", 70, 1, 17, 0.5, 4, 2, 10),
    ("Olive oil", "pantry", "1 tbsp (14 g)", 119, 0, 0, 13.5, 0, 0, 0),
    ("Peanut butter", "pantry", "2 tbsp (32 g)", 188, 8, 6.9, 16, 1.9, 140, 3),
    ("Almonds", "pantry", "28 g (23 nuts)", 164, 6, 6.1, 14.2, 3.5, 0, 1.2),
    ("Honey", "pantry", "1 tbsp (21 g)", 64, 0.1, 17.3, 0, 0, 1, 17),
    ("Marinara sauce", "pantry", "1/2 cup (125 g)", 66, 1.8, 10, 2.1, 2, 480, 7),
    ("Salsa", "pantry", "2 tbsp (36 g)", 10, 0.5, 2, 0.1, 0.5, 220, 1),
    ("Soy sauce", "pantry", "1 tbsp (16 g)", 10, 1.3, 0.8, 0, 0.1, 879, 0.1),
    ("Chia seeds", "pantry", "2 tbsp (28 g)", 138, 4.7, 12, 8.7, 9.8, 5, 0),
]

# (name, meal_type, servings, prep_min, instructions, [(ingredient, qty)])
RECIPES = [
    ("Overnight oats with berries", "breakfast", 1, 5,
     "Stir oats, milk, chia and honey in a jar. Refrigerate overnight. "
     "Top with berries in the morning.",
     [("Rolled oats (dry)", 1), ("Milk 2%", 0.75), ("Chia seeds", 0.5),
      ("Honey", 0.5), ("Frozen berries", 0.5)]),
    ("Greek yogurt power bowl", "breakfast", 1, 3,
     "Yogurt in a bowl; top with banana, blueberries, almonds and a "
     "drizzle of honey.",
     [("Greek yogurt, nonfat plain", 1), ("Banana", 0.5),
      ("Blueberries", 0.5), ("Almonds", 0.5), ("Honey", 0.5)]),
    ("Veggie egg scramble", "breakfast", 1, 10,
     "Saute pepper and onion in butter, add eggs and spinach, scramble "
     "until just set.",
     [("Egg (large)", 3), ("Bell pepper", 0.5), ("Onion", 0.5),
      ("Spinach (raw)", 0.5), ("Butter", 0.5)]),
    ("Meal-prep chicken rice bowls", "lunch", 4, 40,
     "Batch for the week: roast chicken (season, 220 C, ~20 min), steam "
     "broccoli, cook rice. Divide into 4 containers; salsa on top.",
     [("Chicken breast (raw)", 6), ("Brown rice (cooked)", 3),
      ("Broccoli", 4), ("Olive oil", 1.5), ("Salsa", 4)]),
    ("Tuna salad wrap", "lunch", 1, 8,
     "Mix tuna with a little yogurt; fold into the tortilla with greens, "
     "tomato and cucumber.",
     [("Canned tuna in water (drained)", 1), ("Whole-wheat tortilla", 1),
      ("Greek yogurt, nonfat plain", 0.25), ("Mixed salad greens", 0.5),
      ("Tomato", 0.5), ("Cucumber", 0.3)]),
    ("Turkey taco skillet", "dinner", 4, 30,
     "Brown turkey with onion and pepper; add beans and salsa; simmer 10 "
     "min. Serve over rice. Freezes well.",
     [("Ground turkey 93/7 (raw)", 5), ("Black beans (cooked)", 2),
      ("White rice (cooked)", 3), ("Onion", 1), ("Bell pepper", 2),
      ("Salsa", 4), ("Olive oil", 1)]),
    ("Sheet-pan salmon & sweet potato", "dinner", 2, 35,
     "Roast sweet potato 15 min at 200 C, add salmon and broccoli, roast "
     "12-15 more. Finish with olive oil.",
     [("Salmon fillet (raw)", 3), ("Sweet potato", 2), ("Broccoli", 2),
      ("Olive oil", 1)]),
    ("Tofu stir-fry", "dinner", 2, 25,
     "Crisp tofu cubes in oil, add frozen vegetables and soy sauce, serve "
     "over quinoa.",
     [("Extra-firm tofu", 3), ("Frozen mixed vegetables", 2),
      ("Quinoa (cooked)", 2), ("Soy sauce", 2), ("Olive oil", 1)]),
    ("Apple & peanut butter snack", "snack", 1, 2,
     "Slice the apple; dip.",
     [("Apple", 1), ("Peanut butter", 0.5)]),
    ("Protein shake", "snack", 1, 2,
     "Shake powder with milk. After workouts or as a dessert stand-in.",
     [("Whey protein powder", 1), ("Milk 2%", 1)]),
]


def main():
    import sqlite3
    if not DB.exists():
        print(f"no tenant database at {DB} — is the tenant stood up?")
        sys.exit(1)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT COUNT(*) AS n FROM nutrition_ingredients"
                   ).fetchone()["n"]:
        print("the kitchen already has a food library — nothing to do "
              "(idempotence, not laziness)")
        sys.exit(0)
    now = time.time()

    def person(name, email, *, role="customer", is_admin=0):
        existing = con.execute("SELECT id FROM users WHERE name=?",
                               (name,)).fetchone()
        if existing:
            return existing["id"]
        cur = con.execute(
            "INSERT INTO users(name,email,role,token,is_admin,"
            " email_verified_at,created_at) VALUES(?,?,?,?,?,?,?)",
            (name, email, role, secrets.token_urlsafe(24), is_admin,
             now, now))
        return cur.lastrowid

    admin = person("Admin Max", "max@macros.test", role="employee",
                   is_admin=1)
    cora = person("Coach Cora", "cora@macros.test", role="employee")
    mia = person("Mia Tracker", "mia@member.test")
    leo = person("Leo Lifter", "leo@member.test")
    person("Prisha Patel", "prisha@member.test")

    # ── the coaching desk: a program, sold as a product ─────────────────
    prod = con.execute(
        "INSERT INTO products(sku,name,description,category,price_cents,"
        " case_price_cents,active) VALUES(?,?,?,?,?,?,1)",
        ("MAC-COACH-1", "Cut & Keep — coaching seat",
         "A month of coaching: your targets checked weekly, your plan "
         "reviewed, your questions answered. Buying it opens your seat.",
         "Coaching", 4900, 4900)).lastrowid
    prog = con.execute(
        "INSERT INTO nutrition_programs(name,blurb,coach_id,product_id,"
        " active,created_at) VALUES(?,?,?,?,1,?)",
        ("Cut & Keep", "Steady fat loss without theatrics: a modest "
         "deficit you can repeat, protein first, and honest logging.",
         cora, prod, now)).lastrowid
    # Mia holds a seat (the caseload shows her); Leo tracks privately
    con.execute(
        "INSERT INTO nutrition_clients(user_id,program_id,since,source)"
        " VALUES(?,?,?,?)", (mia, prog, now - 21 * DAY, "manual:seed"))

    # ── the house food library ──────────────────────────────────────────
    ing_ids = {}
    for (name, cat, serving, cal, protein, carbs, fat, fiber,
         sodium, sugar) in INGREDIENTS:
        ing_ids[name] = con.execute(
            "INSERT INTO nutrition_ingredients(owner_id,name,category,"
            " serving_name,cal,protein,carbs,fat,fiber,sodium,sugar,"
            " created_at) VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)",
            (name, cat, serving, cal, protein, carbs, fat, fiber,
             sodium, sugar, now)).lastrowid
    rec_ids = {}
    for name, meal_type, servings, prep, instructions, items in RECIPES:
        rid = con.execute(
            "INSERT INTO nutrition_recipes(owner_id,name,meal_type,"
            " servings,prep_min,instructions,created_at)"
            " VALUES(NULL,?,?,?,?,?,?)",
            (name, meal_type, servings, prep, instructions, now)).lastrowid
        rec_ids[name] = rid
        for ing_name, qty in items:
            con.execute(
                "INSERT INTO nutrition_recipe_items(recipe_id,ingredient_id,"
                " qty,created_at) VALUES(?,?,?,?)",
                (rid, ing_ids[ing_name], qty, now))

    # ── Mia, loaded: profile, three weeks of weigh-ins and honest logs ──
    # The drift and the intake are chosen so the observed-maintenance
    # trend check has enough honest days to speak on first load.
    con.execute(
        "INSERT INTO nutrition_profiles(user_id,units,sex,birth_year,"
        " height_cm,activity,goal,rate_kg_week,goal_weight_kg,protein_pct,"
        " carbs_pct,fat_pct,water_goal_ml,fiber_goal_g,sodium_limit_mg,"
        " sugar_limit_g,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
        " ?,?)",
        (mia, "metric", "female", 1996, 167, 1.375, "lose", 0.35, 60.0,
         35, 35, 30, 2200, 28, 2300, 45, now))

    def daykey(days_ago):
        return time.strftime("%Y-%m-%d", time.localtime(now - days_ago * DAY))

    for i in range(21, -1, -1):          # 22 weigh-ins, drifting down
        con.execute(
            "INSERT OR IGNORE INTO nutrition_weight_log(user_id,day,kg,"
            " note,created_at) VALUES(?,?,?,'',?)",
            (mia, daykey(i), round(64.3 - (21 - i) * 0.045, 2), now))
    for i in range(18, 0, -1):           # honest logs most days
        if i % 6 == 0:
            continue                     # two unlogged days keep it human
        for slot, name, cal, p_, c_, f_ in (
                ("breakfast", "Overnight oats with berries", 378, 14, 59, 11),
                ("lunch", "Meal-prep chicken rice bowls", 428, 41, 42, 11),
                ("dinner", "Turkey taco skillet", 456, 28, 41, 19),
                ("snack", "Protein shake", 242, 32, 15, 6)):
            con.execute(
                "INSERT INTO nutrition_food_log(user_id,day,slot,name,"
                " servings,cal,protein,carbs,fat,fiber,sodium,sugar,"
                " created_at) VALUES(?,?,?,?,1,?,?,?,?,4,300,6,?)",
                (mia, daykey(i), slot, name, cal, p_, c_, f_, now))
    con.execute(
        "INSERT INTO nutrition_water_log(user_id,day,ml,created_at)"
        " VALUES(?,?,1250,?)", (mia, daykey(0), now))

    # this week's plan, from the house recipes
    for offset, slot, rname in ((0, "breakfast", "Greek yogurt power bowl"),
                                (0, "lunch", "Tuna salad wrap"),
                                (0, "dinner", "Sheet-pan salmon & sweet potato"),
                                (1, "breakfast", "Overnight oats with berries"),
                                (1, "dinner", "Turkey taco skillet"),
                                (2, "dinner", "Tofu stir-fry")):
        con.execute(
            "INSERT INTO nutrition_plan_entries(user_id,day,slot,recipe_id,"
            " servings,created_at) VALUES(?,?,?,?,1,?)",
            (mia, time.strftime("%Y-%m-%d",
                                time.localtime(now + offset * DAY)),
             slot, rec_ids[rname], now))
    # Leo tracks too — privately, so the caseload does NOT show him
    con.execute(
        "INSERT INTO nutrition_weight_log(user_id,day,kg,note,created_at)"
        " VALUES(?,?,82.5,'',?)", (leo, daykey(0), now))

    # ── the look: macro-kitchen's identity, the commerce-shape site ─────
    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES('theme',?)",
                (json.dumps(THEME),))
    con.commit()

    from storefront.backend import layouts
    layouts.apply(con, ["nutrition", "selling", "payments"], "Macros")
    con.execute("UPDATE store_menus SET position=position+1")
    for loc in ("header", "footer"):
        con.execute("INSERT INTO store_menus(location,label,url,position)"
                    " VALUES(?,?,?,0)", (loc, "Nutrition", "/nutrition"))

    def rewrite(heading_like, **changes):
        for r in con.execute(
                "SELECT id, settings FROM page_sections WHERE"
                " page_slug='home'").fetchall():
            s = json.loads(r["settings"])
            if heading_like.lower() in (s.get("heading") or "").lower():
                s.update(changes)
                con.execute("UPDATE page_sections SET settings=? WHERE id=?",
                            (json.dumps(s), r["id"]))

    rewrite("What you sell", heading="Eat like you mean it.",
            sub="Your maintenance calories from your own weigh-ins, a week "
                "of planned meals, the shopping list that falls out of it "
                "— and a coach when you want one.")
    rewrite("The collection", heading="Coaching")
    rewrite("Why buy from us", items=[
        {"icon": "check", "title": "Derived, never guessed",
         "text": "Targets compute from your weigh-ins; after three honest "
                 "weeks the app measures your real maintenance from the "
                 "data itself."},
        {"icon": "sparkle", "title": "History stays honest",
         "text": "A logged meal keeps the macros it had when you ate it. "
                 "Editing a recipe later never rewrites your past."},
        {"icon": "shield", "title": "Private by default",
         "text": "Track for yourself and you are on nobody's caseload. A "
                 "coach sees you only when you take a seat."}])
    con.commit()
    con.close()

    print(f"seeded the {TENANT} kitchen:")
    print("  sign in on the storefront BY NAME (dev mode, no passwords):")
    print("    members: Mia Tracker (the loaded one, on the caseload) ·")
    print("             Leo Lifter (tracks privately) · Prisha Patel")
    print("    coach:   Coach Cora — the ops Nutrition tab (/ops)")
    print("    office:  Admin Max (ops admin)")
    print("  the house library: 50 ingredients · 10 meal-prep recipes")
    print("  Mia: 22 weigh-ins, 15 honest log days (trend check speaks),")
    print("       this week planned, water started today")
    print("  program: Cut & Keep — sold as a product, buying opens a seat")


if __name__ == "__main__":
    main()
