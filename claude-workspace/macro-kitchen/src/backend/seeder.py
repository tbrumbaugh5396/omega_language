"""Starter content: a pantry of common ingredients (per-serving macros),
a set of meal-prep-friendly recipes, and a sample plan for the coming days.

Numbers are typical label values — close enough for planning; users can edit
anything. Seeding refuses to run on an account that already has content."""
import datetime

from . import db

# (name, category, serving_name, cal, protein, carbs, fat, fiber, sodium_mg, sugar_g)
INGREDIENTS = [
    # protein
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
    # dairy
    ("Greek yogurt, nonfat plain", "dairy", "170 g cup", 100, 17, 6, 0.7, 0, 61, 5.5),
    ("Cottage cheese 2%", "dairy", "1/2 cup (113 g)", 90, 12, 5, 2.5, 0, 350, 4),
    ("Cheddar cheese", "dairy", "28 g", 114, 6.5, 0.9, 9.4, 0, 180, 0.1),
    ("Mozzarella, part-skim", "dairy", "28 g", 72, 6.9, 0.8, 4.5, 0, 175, 0.3),
    ("Milk 2%", "dairy", "1 cup (244 g)", 122, 8, 12, 4.8, 0, 115, 12),
    ("Butter", "dairy", "1 tbsp (14 g)", 102, 0.1, 0, 11.5, 0, 91, 0),
    # grains
    ("White rice (cooked)", "grains", "1 cup (158 g)", 205, 4.3, 45, 0.4, 0.6, 2, 0.1),
    ("Brown rice (cooked)", "grains", "1 cup (195 g)", 216, 5, 45, 1.8, 3.5, 10, 0.7),
    ("Quinoa (cooked)", "grains", "1 cup (185 g)", 222, 8.1, 39, 3.6, 5.2, 13, 1.6),
    ("Rolled oats (dry)", "grains", "1/2 cup (40 g)", 150, 5, 27, 3, 4, 0, 1),
    ("Whole-wheat bread", "grains", "1 slice", 81, 4, 14, 1.1, 1.9, 144, 1.4),
    ("Whole-wheat tortilla", "grains", "1 tortilla (45 g)", 130, 4, 22, 3, 3, 320, 1),
    ("Pasta (cooked)", "grains", "1 cup (140 g)", 220, 8.1, 43, 1.3, 2.5, 1, 0.8),
    ("Sweet potato", "grains", "1 medium (130 g)", 112, 2, 26, 0.1, 3.9, 41, 5.4),
    # produce
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
    # pantry
    ("Olive oil", "pantry", "1 tbsp (14 g)", 119, 0, 0, 13.5, 0, 0, 0),
    ("Peanut butter", "pantry", "2 tbsp (32 g)", 188, 8, 6.9, 16, 1.9, 140, 3),
    ("Almonds", "pantry", "28 g (23 nuts)", 164, 6, 6.1, 14.2, 3.5, 0, 1.2),
    ("Honey", "pantry", "1 tbsp (21 g)", 64, 0.1, 17.3, 0, 0, 1, 17),
    ("Marinara sauce", "pantry", "1/2 cup (125 g)", 66, 1.8, 10, 2.1, 2, 480, 7),
    ("Salsa", "pantry", "2 tbsp (36 g)", 10, 0.5, 2, 0.1, 0.5, 220, 1),
    ("Soy sauce", "pantry", "1 tbsp (16 g)", 10, 1.3, 0.8, 0, 0.1, 879, 0.1),
    ("Chia seeds", "pantry", "2 tbsp (28 g)", 138, 4.7, 12, 8.7, 9.8, 5, 0),
]

# (name, meal_type, servings, prep_min, instructions, [(ingredient, qty)...])
RECIPES = [
    ("Overnight oats with berries", "breakfast", 1, 5,
     "Stir oats, milk, chia and honey in a jar. Refrigerate overnight. "
     "Top with berries in the morning.",
     [("Rolled oats (dry)", 1), ("Milk 2%", 0.75), ("Chia seeds", 0.5),
      ("Honey", 0.5), ("Frozen berries", 0.5)]),
    ("Greek yogurt power bowl", "breakfast", 1, 3,
     "Yogurt in a bowl; top with banana, blueberries, almonds and a drizzle "
     "of honey.",
     [("Greek yogurt, nonfat plain", 1), ("Banana", 0.5), ("Blueberries", 0.5),
      ("Almonds", 0.5), ("Honey", 0.5)]),
    ("Veggie egg scramble", "breakfast", 1, 10,
     "Sauté pepper and onion in butter, add eggs and spinach, scramble until "
     "just set.",
     [("Egg (large)", 3), ("Bell pepper", 0.5), ("Onion", 0.5),
      ("Spinach (raw)", 0.5), ("Butter", 0.5)]),
    ("Meal-prep chicken rice bowls", "lunch", 4, 40,
     "Batch for the week: roast chicken (season, 220°C ~20 min), steam "
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
     "Brown turkey with onion and pepper; add beans and salsa; simmer 10 min. "
     "Serve over rice. Freezes well.",
     [("Ground turkey 93/7 (raw)", 5), ("Black beans (cooked)", 2),
      ("White rice (cooked)", 3), ("Onion", 1), ("Bell pepper", 2),
      ("Salsa", 4), ("Olive oil", 1)]),
    ("Sheet-pan salmon & sweet potato", "dinner", 2, 35,
     "Roast sweet potato 15 min at 200°C, add salmon and broccoli, roast "
     "12–15 more. Finish with olive oil.",
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

# (day_offset, slot, recipe_name, servings)
PLAN = [
    (0, "breakfast", "Overnight oats with berries", 1),
    (0, "lunch", "Meal-prep chicken rice bowls", 1),
    (0, "dinner", "Turkey taco skillet", 1),
    (0, "snack", "Apple & peanut butter snack", 1),
    (1, "breakfast", "Greek yogurt power bowl", 1),
    (1, "lunch", "Meal-prep chicken rice bowls", 1),
    (1, "dinner", "Sheet-pan salmon & sweet potato", 1),
    (1, "snack", "Protein shake", 1),
    (2, "breakfast", "Veggie egg scramble", 1),
    (2, "lunch", "Tuna salad wrap", 1),
    (2, "dinner", "Turkey taco skillet", 1),
    (3, "breakfast", "Overnight oats with berries", 1),
    (3, "lunch", "Meal-prep chicken rice bowls", 1),
    (3, "dinner", "Tofu stir-fry", 1),
]

CONTENT_TABLES = ("ingredients", "recipes", "food_log", "plan_entries",
                  "weight_log", "shopping_items")


def has_content(con, uid: int) -> bool:
    for t in CONTENT_TABLES:
        if con.execute(f"SELECT 1 FROM {t} WHERE user_id=? LIMIT 1",
                       (uid,)).fetchone():
            return True
    return False


def seed_user(con, uid: int) -> dict:
    ts = db.now()
    ing_ids = {}
    for (name, cat, serving, cal, protein, carbs, fat, fiber,
         sodium, sugar) in INGREDIENTS:
        cur = con.execute(
            "INSERT INTO ingredients(user_id,name,category,serving_name,cal,"
            "protein,carbs,fat,fiber,sodium,sugar,created) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, name, cat, serving, cal, protein, carbs, fat, fiber,
             sodium, sugar, ts))
        ing_ids[name] = cur.lastrowid

    recipe_ids = {}
    n_items = 0
    for name, meal_type, servings, prep, instructions, items in RECIPES:
        cur = con.execute(
            "INSERT INTO recipes(user_id,name,meal_type,servings,prep_min,"
            "instructions,created) VALUES(?,?,?,?,?,?,?)",
            (uid, name, meal_type, servings, prep, instructions, ts))
        rid = cur.lastrowid
        recipe_ids[name] = rid
        for ing_name, qty in items:
            con.execute(
                "INSERT INTO recipe_items(user_id,recipe_id,ingredient_id,qty,"
                "created) VALUES(?,?,?,?,?)",
                (uid, rid, ing_ids[ing_name], qty, ts))
            n_items += 1

    today = datetime.date.today()
    for offset, slot, recipe_name, servings in PLAN:
        day = (today + datetime.timedelta(days=offset)).isoformat()
        con.execute(
            "INSERT INTO plan_entries(user_id,day,slot,recipe_id,servings,"
            "created) VALUES(?,?,?,?,?,?)",
            (uid, day, slot, recipe_ids[recipe_name], servings, ts))

    return {"ingredients": len(INGREDIENTS), "recipes": len(RECIPES),
            "recipe_items": n_items, "plan_entries": len(PLAN)}
