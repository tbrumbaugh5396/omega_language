"""The member's door — /nutrition on the storefront.

The coach side lives in the ops app (erp/backend/nutrition.py); this is
the side a member sees: targets computed from their own profile and
weigh-ins, the food log, the week's plan, the shopping list, and the
tenant's food library with their own additions on top.

Rules enforced here at the server:

- The whole surface sits behind the tenant's Nutrition entitlement —
  revoked = 404 and pruned nav, like every capability.
- Tracking is open to ANY signed-in member of the tenant. A coach sees
  only people with a SEAT (a bought or granted coaching place) — privacy
  follows the seat, so self-trackers stay their own business.
- Numbers the app derives (targets, observed maintenance, streaks,
  adherence) are computed on read by the pure module, never stored.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from erp.backend import nutrition as N
from .api import current_customer, get_con, render_shell
from .partners import _require_cap, brand_name

router = APIRouter()


def _clamp(v, lo, hi, name):
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number")
    if not (lo <= v <= hi):
        raise HTTPException(400, f"{name} must be between {lo} and {hi}")
    return v


# ── state: one call, everything the app draws ────────────────────────────────

@router.get("/api/nutrition/me/state")
def my_state(day: str = "", user=Depends(current_customer),
             con=Depends(get_con)):
    _require_cap("nutrition")
    import datetime
    day = (day or datetime.date.today().isoformat())[:10]
    uid = user["id"]
    recipes, items = N.visible_recipes(con, uid)
    water = con.execute(
        "SELECT ml FROM nutrition_water_log WHERE user_id=? AND day=?",
        (uid, day)).fetchone()
    return {
        "me": {"id": uid, "name": user["name"]},
        "day": day,
        "profile": N.profile_of(con, uid),
        "targets": N.targets_of(con, uid),
        "adherence": N.adherence_of(con, uid),
        "client": N.is_client(con, uid),
        "log": [dict(r) for r in con.execute(
            "SELECT * FROM nutrition_food_log WHERE user_id=? AND day=?"
            " ORDER BY slot, id", (uid, day)).fetchall()],
        "water_ml": water["ml"] if water else 0,
        "weights": [dict(r) for r in con.execute(
            "SELECT id, day, kg, note FROM nutrition_weight_log"
            " WHERE user_id=? ORDER BY day", (uid,)).fetchall()],
        "plan": [dict(r) for r in con.execute(
            "SELECT * FROM nutrition_plan_entries WHERE user_id=?"
            " AND day >= date(?, '-14 days') AND day <= date(?, '+14 days')"
            " ORDER BY day, slot, id", (uid, day, day)).fetchall()],
        "shopping": [dict(r) for r in con.execute(
            "SELECT * FROM nutrition_shopping_items WHERE user_id=?"
            " ORDER BY checked, category, id", (uid,)).fetchall()],
        "ingredients": N.visible_ingredients(con, uid),
        "recipes": recipes,
        "recipe_items": items,
    }


# ── profile ──────────────────────────────────────────────────────────────────

class ProfileBody(BaseModel):
    units: str = "metric"
    sex: str = "male"
    birth_year: int = 1990
    height_cm: float = 175
    activity: float = 1.55
    goal: str = "maintain"
    rate_kg_week: float = 0.45
    goal_weight_kg: float | None = None
    protein_pct: int = 30
    carbs_pct: int = 40
    fat_pct: int = 30
    water_goal_ml: int = 2500
    fiber_goal_g: int = 30
    sodium_limit_mg: int = 2300
    sugar_limit_g: int = 50
    tdee_override: float | None = None


@router.post("/api/nutrition/me/profile")
def my_profile(body: ProfileBody, user=Depends(current_customer),
               con=Depends(get_con)):
    _require_cap("nutrition")
    fields = body.dict()
    _clamp(fields["height_cm"], 100, 250, "height_cm")
    _clamp(fields["activity"], 1.0, 2.5, "activity")
    _clamp(fields["rate_kg_week"], 0, 2, "rate_kg_week")
    if fields["goal_weight_kg"] is not None:
        _clamp(fields["goal_weight_kg"], 20, 400, "goal_weight_kg")
    if fields["tdee_override"] is not None and fields["tdee_override"]:
        _clamp(fields["tdee_override"], 800, 6000, "tdee_override")
    out = N.save_profile(con, user["id"], fields)
    con.commit()
    return out


# ── daily logging ────────────────────────────────────────────────────────────

class LogBody(BaseModel):
    day: str = ""
    slot: str = "snack"
    name: str = ""
    servings: float = 1
    cal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    fiber: float = 0
    sodium: float = 0
    sugar: float = 0


@router.post("/api/nutrition/me/log")
def my_log(body: LogBody, user=Depends(current_customer),
           con=Depends(get_con)):
    _require_cap("nutrition")
    if body.slot not in N.SLOTS:
        raise HTTPException(400, "unknown meal slot")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name what you ate")
    _clamp(body.cal, 0, 10000, "cal")
    for f in ("protein", "carbs", "fat", "fiber", "sugar"):
        _clamp(getattr(body, f), 0, 1000, f)
    _clamp(body.sodium, 0, 30000, "sodium")
    cur = con.execute(
        "INSERT INTO nutrition_food_log(user_id,day,slot,name,servings,cal,"
        " protein,carbs,fat,fiber,sodium,sugar,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], body.day[:10], body.slot, name[:200],
         max(0.05, body.servings), body.cal, body.protein, body.carbs,
         body.fat, body.fiber, body.sodium, body.sugar, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/nutrition/me/log/{lid}/delete")
def my_log_delete(lid: int, user=Depends(current_customer),
                  con=Depends(get_con)):
    _require_cap("nutrition")
    con.execute("DELETE FROM nutrition_food_log WHERE id=? AND user_id=?",
                (lid, user["id"]))
    con.commit()
    return {"ok": True}


class WeightBody(BaseModel):
    day: str = ""
    kg: float = 0
    note: str = ""


@router.post("/api/nutrition/me/weight")
def my_weight(body: WeightBody, user=Depends(current_customer),
              con=Depends(get_con)):
    _require_cap("nutrition")
    _clamp(body.kg, 20, 400, "kg")
    con.execute(
        "INSERT INTO nutrition_weight_log(user_id,day,kg,note,created_at)"
        " VALUES(?,?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET"
        " kg=excluded.kg, note=excluded.note",
        (user["id"], body.day[:10], round(body.kg, 2),
         body.note.strip()[:200], time.time()))
    con.commit()
    return {"ok": True}


@router.post("/api/nutrition/me/weight/{wid}/delete")
def my_weight_delete(wid: int, user=Depends(current_customer),
                     con=Depends(get_con)):
    _require_cap("nutrition")
    con.execute("DELETE FROM nutrition_weight_log WHERE id=? AND user_id=?",
                (wid, user["id"]))
    con.commit()
    return {"ok": True}


class WaterBody(BaseModel):
    day: str = ""
    delta_ml: int = 0


@router.post("/api/nutrition/me/water")
def my_water(body: WaterBody, user=Depends(current_customer),
             con=Depends(get_con)):
    _require_cap("nutrition")
    day = body.day[:10]
    con.execute(
        "INSERT INTO nutrition_water_log(user_id,day,ml,created_at)"
        " VALUES(?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET"
        " ml=MAX(0, nutrition_water_log.ml + excluded.ml)",
        (user["id"], day, max(0, body.delta_ml), time.time()))
    if body.delta_ml < 0:
        con.execute(
            "UPDATE nutrition_water_log SET ml=MAX(0, ml + ?)"
            " WHERE user_id=? AND day=?", (body.delta_ml, user["id"], day))
    total = con.execute(
        "SELECT ml FROM nutrition_water_log WHERE user_id=? AND day=?",
        (user["id"], day)).fetchone()["ml"]
    con.commit()
    return {"ok": True, "day": day, "ml": total}


# ── the plan ─────────────────────────────────────────────────────────────────

class PlanBody(BaseModel):
    day: str = ""
    slot: str = "dinner"
    recipe_id: int | None = None
    ingredient_id: int | None = None
    title: str = ""
    servings: float = 1
    done: int | None = None


@router.post("/api/nutrition/me/plan")
def my_plan_add(body: PlanBody, user=Depends(current_customer),
                con=Depends(get_con)):
    _require_cap("nutrition")
    if body.slot not in N.SLOTS:
        raise HTTPException(400, "unknown meal slot")
    if not (body.recipe_id or body.ingredient_id or body.title.strip()):
        raise HTTPException(400, "plan a recipe, a food, or a description")
    cur = con.execute(
        "INSERT INTO nutrition_plan_entries(user_id,day,slot,recipe_id,"
        " ingredient_id,title,servings,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], body.day[:10], body.slot, body.recipe_id,
         body.ingredient_id, body.title.strip()[:200],
         max(0.05, body.servings), time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/nutrition/me/plan/{pid}")
def my_plan_update(pid: int, body: PlanBody, user=Depends(current_customer),
                   con=Depends(get_con)):
    _require_cap("nutrition")
    cur = con.execute(
        "UPDATE nutrition_plan_entries SET done=? WHERE id=? AND user_id=?",
        (1 if body.done else 0, pid, user["id"]))
    if cur.rowcount == 0:
        raise HTTPException(404, "not found")
    con.commit()
    return {"ok": True}


@router.post("/api/nutrition/me/plan/{pid}/delete")
def my_plan_delete(pid: int, user=Depends(current_customer),
                   con=Depends(get_con)):
    _require_cap("nutrition")
    con.execute("DELETE FROM nutrition_plan_entries WHERE id=? AND user_id=?",
                (pid, user["id"]))
    con.commit()
    return {"ok": True}


# ── shopping ─────────────────────────────────────────────────────────────────

class GenerateBody(BaseModel):
    start: str = ""
    end: str = ""


@router.post("/api/nutrition/me/shopping/generate")
def my_shopping_generate(body: GenerateBody, user=Depends(current_customer),
                         con=Depends(get_con)):
    _require_cap("nutrition")
    added = N.generate_shopping(con, user["id"], body.start[:10],
                                body.end[:10])
    con.commit()
    return {"ok": True, "added": added}


class ShopBody(BaseModel):
    name: str = ""
    category: str = "other"
    qty: str = ""
    checked: int | None = None


@router.post("/api/nutrition/me/shopping")
def my_shopping_add(body: ShopBody, user=Depends(current_customer),
                    con=Depends(get_con)):
    _require_cap("nutrition")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name the item")
    if body.category not in N.CATEGORIES:
        raise HTTPException(400, "unknown category")
    cur = con.execute(
        "INSERT INTO nutrition_shopping_items(user_id,name,category,qty,"
        " created_at) VALUES(?,?,?,?,?)",
        (user["id"], name[:200], body.category, body.qty.strip()[:60],
         time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/nutrition/me/shopping/clear-checked")
def my_shopping_clear(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("nutrition")
    cur = con.execute(
        "DELETE FROM nutrition_shopping_items WHERE user_id=? AND checked=1",
        (user["id"],))
    con.commit()
    return {"ok": True, "removed": cur.rowcount}


@router.post("/api/nutrition/me/shopping/{sid}")
def my_shopping_check(sid: int, body: ShopBody,
                      user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("nutrition")
    cur = con.execute(
        "UPDATE nutrition_shopping_items SET checked=? WHERE id=?"
        " AND user_id=?", (1 if body.checked else 0, sid, user["id"]))
    if cur.rowcount == 0:
        raise HTTPException(404, "not found")
    con.commit()
    return {"ok": True}


@router.post("/api/nutrition/me/shopping/{sid}/delete")
def my_shopping_delete(sid: int, user=Depends(current_customer),
                       con=Depends(get_con)):
    _require_cap("nutrition")
    con.execute(
        "DELETE FROM nutrition_shopping_items WHERE id=? AND user_id=?",
        (sid, user["id"]))
    con.commit()
    return {"ok": True}


# ── my own foods & recipes ───────────────────────────────────────────────────

class IngredientBody(BaseModel):
    name: str = ""
    category: str = "pantry"
    serving_name: str = ""
    cal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    fiber: float = 0
    sodium: float = 0
    sugar: float = 0


@router.post("/api/nutrition/me/ingredients")
def my_ingredient_add(body: IngredientBody, user=Depends(current_customer),
                      con=Depends(get_con)):
    _require_cap("nutrition")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name the food")
    if body.category not in N.CATEGORIES:
        raise HTTPException(400, "unknown category")
    _clamp(body.cal, 0, 10000, "cal")
    cur = con.execute(
        "INSERT INTO nutrition_ingredients(owner_id,name,category,"
        " serving_name,cal,protein,carbs,fat,fiber,sodium,sugar,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], name[:200], body.category, body.serving_name.strip()[:60],
         body.cal, body.protein, body.carbs, body.fat, body.fiber,
         body.sodium, body.sugar, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


class RecipeItemBody(BaseModel):
    ingredient_id: int = 0
    qty: float = 1


class RecipeBody(BaseModel):
    name: str = ""
    meal_type: str = "any"
    servings: float = 1
    prep_min: int = 0
    instructions: str = ""
    items: list[RecipeItemBody] = []


@router.post("/api/nutrition/me/recipes")
def my_recipe_add(body: RecipeBody, user=Depends(current_customer),
                  con=Depends(get_con)):
    _require_cap("nutrition")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name the recipe")
    visible = {i["id"] for i in N.visible_ingredients(con, user["id"])}
    for it in body.items:
        if it.ingredient_id not in visible:
            raise HTTPException(404, "ingredient not found")
    cur = con.execute(
        "INSERT INTO nutrition_recipes(owner_id,name,meal_type,servings,"
        " prep_min,instructions,created_at) VALUES(?,?,?,?,?,?,?)",
        (user["id"], name[:200],
         body.meal_type if body.meal_type in N.SLOTS + ("any",) else "any",
         max(0.5, body.servings), max(0, body.prep_min),
         body.instructions[:5000], time.time()))
    rid = cur.lastrowid
    for it in body.items:
        con.execute(
            "INSERT INTO nutrition_recipe_items(recipe_id,ingredient_id,qty,"
            " created_at) VALUES(?,?,?,?)",
            (rid, it.ingredient_id, max(0.01, it.qty), time.time()))
    con.commit()
    return {"id": rid}


@router.post("/api/nutrition/me/recipes/{rid}/delete")
def my_recipe_delete(rid: int, user=Depends(current_customer),
                     con=Depends(get_con)):
    _require_cap("nutrition")
    cur = con.execute(
        "DELETE FROM nutrition_recipes WHERE id=? AND owner_id=?",
        (rid, user["id"]))
    if cur.rowcount:
        con.execute("DELETE FROM nutrition_recipe_items WHERE recipe_id=?",
                    (rid,))
    con.commit()
    return {"ok": True}


# ── the page ─────────────────────────────────────────────────────────────────

@router.get("/nutrition")
def nutrition_page(con=Depends(get_con)):
    _require_cap("nutrition")
    from .api import asset_version
    _brand = brand_name(con)
    v = asset_version()
    body = f"""
<section class="section partner-head">
 <span class="eyebrow">Nutrition</span>
 <h1>Plan, prep, track</h1>
 <p class="lede">Your maintenance calories and daily target, computed from
  your own weigh-ins; a week of planned meals; the shopping list that falls
  out of it; and an honest log. Estimates, not medicine.</p>
</section>
<section class="section"><div id="nutrition-root">
 <p class="dim">Loading…</p>
</div></section>
<style>
 .ntr-tabs{{display:flex;gap:4px;margin-bottom:18px;border-bottom:1px solid rgba(127,127,127,.25);flex-wrap:wrap}}
 .ntr-tab{{padding:8px 16px;cursor:pointer;border-radius:8px 8px 0 0}}
 .ntr-tab.on{{font-weight:700;border:1px solid rgba(127,127,127,.25);border-bottom-color:transparent}}
 .ntr-btn{{padding:8px 16px;border-radius:8px;border:1px solid currentColor;background:none;color:inherit;cursor:pointer}}
 .ntr-btn.primary{{font-weight:700}}
 .ntr-btn.sm{{padding:4px 10px;font-size:.85em}}
 .ntr-meta{{opacity:.7;font-size:.9em}}
 .ntr-card{{border:1px solid rgba(127,127,127,.25);border-radius:12px;padding:16px;margin:10px 0}}
 .ntr-grid2{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}}
 .ntr-hero{{display:flex;gap:22px;align-items:center;flex-wrap:wrap}}
 .ntr-ring{{position:relative;width:150px;height:150px;flex:none}}
 .ntr-ring svg{{transform:rotate(-90deg)}}
 .ntr-ring .mid{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}}
 .ntr-bars{{flex:1;min-width:220px}}
 .ntr-bar-head{{display:flex;justify-content:space-between;font-size:.85em;margin:8px 0 3px}}
 .ntr-track{{height:10px;border-radius:5px;background:rgba(127,127,127,.2);overflow:hidden}}
 .ntr-fill{{display:block;height:100%;border-radius:5px;background:currentColor;opacity:.8}}
 .ntr-fill.over{{opacity:1}}
 .ntr-glasses{{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}}
 .ntr-glass{{width:30px;height:40px;border:2px solid rgba(127,127,127,.5);border-top-width:1px;border-radius:4px 4px 8px 8px;cursor:pointer;position:relative;overflow:hidden}}
 .ntr-glass.full::after{{content:"";position:absolute;left:0;right:0;bottom:0;height:85%;background:currentColor;opacity:.5}}
 .ntr-row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
 .ntr-row input,.ntr-row select{{padding:6px 8px;border-radius:8px;border:1px solid rgba(127,127,127,.4);background:none;color:inherit}}
 .ntr-item{{display:flex;gap:8px;align-items:center;padding:8px 2px;border-bottom:1px solid rgba(127,127,127,.15)}}
 .ntr-item .grow{{flex:1}}
 .ntr-done{{opacity:.55;text-decoration:line-through}}
 .ntr-week{{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(130px,1fr))}}
 .ntr-day{{border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:8px}}
 .ntr-day.today{{border-color:currentColor}}
 .ntr-day h5{{margin:0 0 4px;font-size:.85em}}
 .ntr-slot{{font-size:.65em;text-transform:uppercase;letter-spacing:1px;opacity:.6;margin-top:6px}}
 .ntr-meal{{font-size:.8em;border:1px solid rgba(127,127,127,.3);border-radius:6px;padding:3px 6px;margin:3px 0;cursor:pointer;display:flex;justify-content:space-between;gap:4px}}
 .ntr-meal.done{{opacity:.5}}
 .ntr-add{{font-size:.75em;opacity:.6;cursor:pointer}}
 .ntr-add:hover{{opacity:1}}
 .ntr-cal14{{display:flex;gap:4px;flex-wrap:wrap}}
 .ntr-daybox{{width:30px;height:30px;border-radius:7px;border:1px solid rgba(127,127,127,.3);display:flex;align-items:center;justify-content:center;font-size:.7em;opacity:.5}}
 .ntr-daybox.part{{opacity:1;border-color:#ca4}}
 .ntr-daybox.hit{{opacity:1;border-color:#3c9;font-weight:700}}
 .ntr-chart{{overflow-x:auto}}
 .ntr-stat{{border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:10px 14px}}
 .ntr-stat b{{font-size:1.4em}}
 .ntr-stats{{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}}
 .ntr-notice{{border-left:3px solid rgba(127,127,127,.5);padding:8px 12px;font-size:.9em;opacity:.85;margin:10px 0}}
</style>
<script src="/nutrition.js?v={v}"></script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"Nutrition — {_brand}",
        description=f"{_brand}: meal planning, food logging and body"
                    " metrics."))
