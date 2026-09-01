"""Nutrition — meal planning, food logging and body metrics as a tenant
capability. macro-kitchen ported onto the platform, the way lingua-portal
became Learning.

What the port keeps from the source:

- **All arithmetic is pure and derived** — `nutrition_calc.py` computes
  BMR/maintenance/targets and the observed-maintenance estimate from the
  data on every read; nothing stores a computed number.
- Food-log entries are **denormalised at logging time** (the entry keeps
  the macros it had when eaten), so editing a recipe later never rewrites
  history.
- Weight and water are day-keyed upserts; availability-style facts
  (streaks, adherence) are derived, never stored.

What the platform adds that the source never had:

- **Checkout as the coaching desk**: a program can name a product
  (`nutrition_programs.product_id`); buying it opens the client seat and
  records which order opened it — the same admissions rail as Learning.
- Multi-tenancy: the food library is per-tenant. Rows with
  `owner_id NULL` are the tenant's shared library (coach-curated);
  rows with an owner are that member's own additions.
- The coach view: staff see their CLIENTS (seat holders) — a member who
  merely tracks for themselves is not on anyone's caseload. Tracking is
  open to any signed-in member of the tenant; oversight follows the seat.
"""

import datetime
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import notify
from . import nutrition_calc as NC

SLOTS = ("breakfast", "lunch", "dinner", "snack")
CATEGORIES = ("produce", "protein", "dairy", "grains", "pantry", "frozen",
              "beverages", "spices", "other")

TABLES = """
CREATE TABLE IF NOT EXISTS nutrition_programs (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  blurb TEXT DEFAULT '',
  coach_id INTEGER,                    -- users.id; sees this program's clients
  product_id INTEGER,                  -- buying this product opens a seat
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_clients (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  program_id INTEGER,
  since REAL NOT NULL,
  until REAL,                          -- NULL = current
  source TEXT DEFAULT 'manual',        -- manual | order:<id>
  UNIQUE(user_id, program_id)
);

CREATE TABLE IF NOT EXISTS nutrition_profiles (
  user_id INTEGER PRIMARY KEY,
  units TEXT NOT NULL DEFAULT 'metric',
  sex TEXT NOT NULL DEFAULT 'male',
  birth_year INTEGER NOT NULL DEFAULT 1990,
  height_cm REAL NOT NULL DEFAULT 175,
  activity REAL NOT NULL DEFAULT 1.55,
  goal TEXT NOT NULL DEFAULT 'maintain'
    CHECK (goal IN ('lose','maintain','gain')),
  rate_kg_week REAL NOT NULL DEFAULT 0.45,
  goal_weight_kg REAL,
  protein_pct INTEGER NOT NULL DEFAULT 30,
  carbs_pct INTEGER NOT NULL DEFAULT 40,
  fat_pct INTEGER NOT NULL DEFAULT 30,
  water_goal_ml INTEGER NOT NULL DEFAULT 2500,
  fiber_goal_g INTEGER NOT NULL DEFAULT 30,
  sodium_limit_mg INTEGER NOT NULL DEFAULT 2300,
  sugar_limit_g INTEGER NOT NULL DEFAULT 50,
  tdee_override REAL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_ingredients (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER,                    -- NULL = the tenant's shared library
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'pantry',
  serving_name TEXT DEFAULT '',
  cal REAL NOT NULL DEFAULT 0,
  protein REAL NOT NULL DEFAULT 0,
  carbs REAL NOT NULL DEFAULT 0,
  fat REAL NOT NULL DEFAULT 0,
  fiber REAL NOT NULL DEFAULT 0,
  sodium REAL NOT NULL DEFAULT 0,
  sugar REAL NOT NULL DEFAULT 0,
  archived INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_recipes (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER,                    -- NULL = the tenant's shared library
  name TEXT NOT NULL,
  meal_type TEXT NOT NULL DEFAULT 'any',
  servings REAL NOT NULL DEFAULT 1,
  prep_min INTEGER NOT NULL DEFAULT 0,
  instructions TEXT DEFAULT '',
  archived INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_recipe_items (
  id INTEGER PRIMARY KEY,
  recipe_id INTEGER NOT NULL,
  ingredient_id INTEGER NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_plan_entries (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  slot TEXT NOT NULL DEFAULT 'dinner'
    CHECK (slot IN ('breakfast','lunch','dinner','snack')),
  recipe_id INTEGER,
  ingredient_id INTEGER,
  title TEXT DEFAULT '',
  servings REAL NOT NULL DEFAULT 1,
  done INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_food_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  slot TEXT NOT NULL DEFAULT 'snack'
    CHECK (slot IN ('breakfast','lunch','dinner','snack')),
  name TEXT NOT NULL,
  servings REAL NOT NULL DEFAULT 1,
  cal REAL NOT NULL DEFAULT 0,         -- totals for the entry, denormalised
  protein REAL NOT NULL DEFAULT 0,
  carbs REAL NOT NULL DEFAULT 0,
  fat REAL NOT NULL DEFAULT 0,
  fiber REAL NOT NULL DEFAULT 0,
  sodium REAL NOT NULL DEFAULT 0,
  sugar REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_weight_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  kg REAL NOT NULL,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(user_id, day)
);

CREATE TABLE IF NOT EXISTS nutrition_water_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  ml INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(user_id, day)
);

CREATE TABLE IF NOT EXISTS nutrition_shopping_items (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'other',
  qty TEXT DEFAULT '',
  checked INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── seats ────────────────────────────────────────────────────────────────────

def is_client(con, user_id: int) -> bool:
    return con.execute(
        "SELECT 1 FROM nutrition_clients WHERE user_id=?"
        " AND (until IS NULL OR until > ?)",
        (int(user_id), time.time())).fetchone() is not None


def open_seat(con, user_id: int, program_id=None,
              source: str = "manual") -> bool:
    """Idempotent, like enrolment: a lapsed seat revives, an active one is
    a no-op. Returns whether anything changed."""
    cur = con.execute(
        "SELECT id, until FROM nutrition_clients WHERE user_id=?"
        " AND program_id IS ?", (int(user_id), program_id)).fetchone()
    if cur is None:
        con.execute(
            "INSERT INTO nutrition_clients(user_id,program_id,since,source)"
            " VALUES(?,?,?,?)", (int(user_id), program_id, time.time(),
                                 source))
        return True
    if cur["until"] is not None:
        con.execute("UPDATE nutrition_clients SET until=NULL, since=?,"
                    " source=? WHERE id=?", (time.time(), source, cur["id"]))
        return True
    return False


def open_by_order(con, order_id: int, user_id: int) -> list:
    """A placed order opens a coaching seat for every program whose product
    it contains — checkout is the coaching desk, same as admissions."""
    rows = con.execute(
        "SELECT DISTINCT p.id, p.name FROM order_items oi"
        " JOIN nutrition_programs p ON p.product_id = oi.product_id"
        "  AND p.active=1 WHERE oi.order_id=?", (order_id,)).fetchall()
    opened = []
    for r in rows:
        if open_seat(con, user_id, r["id"], source=f"order:{order_id}"):
            opened.append(r["name"])
    return opened


# ── profile & derived numbers ────────────────────────────────────────────────

PROFILE_FIELDS = ("units", "sex", "birth_year", "height_cm", "activity",
                  "goal", "rate_kg_week", "goal_weight_kg", "protein_pct",
                  "carbs_pct", "fat_pct", "water_goal_ml", "fiber_goal_g",
                  "sodium_limit_mg", "sugar_limit_g", "tdee_override")


def profile_of(con, user_id: int) -> dict:
    r = con.execute("SELECT * FROM nutrition_profiles WHERE user_id=?",
                    (int(user_id),)).fetchone()
    if r is None:
        return dict(NC.DEFAULT_PROFILE)
    return {k: r[k] for k in PROFILE_FIELDS}


def save_profile(con, user_id: int, fields: dict) -> dict:
    p = {**profile_of(con, user_id), **{k: v for k, v in fields.items()
                                        if k in PROFILE_FIELDS}}
    if p["goal"] not in ("lose", "maintain", "gain"):
        raise HTTPException(400, "goal must be lose, maintain or gain")
    if p["sex"] not in ("male", "female"):
        raise HTTPException(400, "sex must be male or female (it feeds the"
                                 " BMR formula, nothing else)")
    split = (p["protein_pct"] or 0) + (p["carbs_pct"] or 0) + (p["fat_pct"] or 0)
    if abs(split - 100) > 1:
        raise HTTPException(400, f"macro split adds to {split}%, not 100%")
    cols = ",".join(PROFILE_FIELDS)
    marks = ",".join("?" * len(PROFILE_FIELDS))
    sets = ",".join(f"{k}=excluded.{k}" for k in PROFILE_FIELDS)
    con.execute(
        f"INSERT INTO nutrition_profiles(user_id,{cols},updated_at)"
        f" VALUES(?,{marks},?)"
        f" ON CONFLICT(user_id) DO UPDATE SET {sets},"
        f" updated_at=excluded.updated_at",
        [int(user_id)] + [p[k] for k in PROFILE_FIELDS] + [time.time()])
    return p


def latest_kg(con, user_id: int):
    r = con.execute(
        "SELECT kg FROM nutrition_weight_log WHERE user_id=?"
        " ORDER BY day DESC LIMIT 1", (int(user_id),)).fetchone()
    return r["kg"] if r else None


def intake_by_day(con, user_id: int) -> dict:
    return {r["day"]: r["kcal"] for r in con.execute(
        "SELECT day, SUM(cal) AS kcal FROM nutrition_food_log"
        " WHERE user_id=? GROUP BY day", (int(user_id),)).fetchall()}


def targets_of(con, user_id: int) -> dict:
    today = datetime.date.today()
    t = NC.targets(profile_of(con, user_id), latest_kg(con, user_id), today)
    weighins = [(r["day"], r["kg"]) for r in con.execute(
        "SELECT day, kg FROM nutrition_weight_log WHERE user_id=?"
        " ORDER BY day", (int(user_id),)).fetchall()]
    t["observed"] = NC.observed_tdee(weighins, intake_by_day(con, user_id),
                                     today)
    return t


def adherence_of(con, user_id: int, days: int = 14) -> dict:
    today = datetime.date.today()
    t = NC.targets(profile_of(con, user_id), latest_kg(con, user_id), today)
    intake = intake_by_day(con, user_id)
    goal = profile_of(con, user_id)["goal"]
    window = [(today - datetime.timedelta(days=i)).isoformat()
              for i in range(days - 1, -1, -1)]
    return {
        "days": [{"day": d, "kcal": round(intake.get(d, 0)),
                  "logged": intake.get(d, 0) > 0,
                  "on_target": NC.day_on_target(intake.get(d, 0),
                                                t["target"], goal)}
                 for d in window],
        "streaks": NC.streaks({d for d, k in intake.items() if k > 0}, today),
        "target": t["target"],
    }


# ── the food library ─────────────────────────────────────────────────────────

def visible_ingredients(con, user_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM nutrition_ingredients WHERE archived=0"
        " AND (owner_id IS NULL OR owner_id=?)"
        " ORDER BY category, name COLLATE NOCASE", (int(user_id),)).fetchall()]


def visible_recipes(con, user_id: int) -> list:
    recipes = [dict(r) for r in con.execute(
        "SELECT * FROM nutrition_recipes WHERE archived=0"
        " AND (owner_id IS NULL OR owner_id=?)"
        " ORDER BY name COLLATE NOCASE", (int(user_id),)).fetchall()]
    ids = [r["id"] for r in recipes]
    items = []
    if ids:
        items = [dict(r) for r in con.execute(
            "SELECT * FROM nutrition_recipe_items WHERE recipe_id IN"
            f" ({','.join('?' * len(ids))}) ORDER BY recipe_id, id",
            ids).fetchall()]
    return recipes, items


def may_edit_food(con, user, row) -> bool:
    """Own rows are yours; the shared library (owner NULL) is staff's."""
    if row["owner_id"] == user["id"]:
        return True
    if row["owner_id"] is None:
        return bool(user["is_admin"]) or _is_coach(con, user["id"])
    return False


def _is_coach(con, user_id: int) -> bool:
    return con.execute(
        "SELECT 1 FROM nutrition_programs WHERE coach_id=? AND active=1",
        (int(user_id),)).fetchone() is not None


def coach_or_admin(con, user) -> bool:
    return bool(user["is_admin"]) or _is_coach(con, user["id"])


# ── shopping ─────────────────────────────────────────────────────────────────

def generate_shopping(con, user_id: int, start: str, end: str) -> int:
    """Aggregate the plan between start and end (inclusive) into shopping
    items — recipes expanded to ingredients, quantities summed."""
    if end < start:
        raise HTTPException(400, "end must not be before start")
    entries = [dict(r) for r in con.execute(
        "SELECT * FROM nutrition_plan_entries WHERE user_id=?"
        " AND day>=? AND day<=?", (int(user_id), start, end)).fetchall()]
    if not entries:
        return 0
    recipes, items = visible_recipes(con, user_id)
    recipes = {r["id"]: r for r in recipes}
    by_recipe: dict = {}
    for it in items:
        by_recipe.setdefault(it["recipe_id"], []).append(it)
    ingredients = {i["id"]: i for i in visible_ingredients(con, user_id)}

    need: dict = {}
    loose: list = []
    for e in entries:
        if e["recipe_id"] and e["recipe_id"] in recipes:
            r = recipes[e["recipe_id"]]
            scale = (e["servings"] or 1) / (r["servings"] or 1)
            for it in by_recipe.get(r["id"], []):
                need[it["ingredient_id"]] = (
                    need.get(it["ingredient_id"], 0) + it["qty"] * scale)
        elif e["ingredient_id"] and e["ingredient_id"] in ingredients:
            need[e["ingredient_id"]] = (
                need.get(e["ingredient_id"], 0) + (e["servings"] or 1))
        elif e["title"]:
            loose.append(e["title"])

    ts = time.time()
    added = 0
    for ing_id, qty in sorted(need.items(),
                              key=lambda kv: ingredients[kv[0]]["name"]):
        ing = ingredients.get(ing_id)
        if not ing:
            continue
        amount = round(qty, 1)
        amount_s = str(int(amount)) if amount == int(amount) else str(amount)
        unit = (f" x {ing['serving_name']}" if ing["serving_name"]
                else " servings")
        con.execute(
            "INSERT INTO nutrition_shopping_items(user_id,name,category,qty,"
            " created_at) VALUES(?,?,?,?,?)",
            (int(user_id), ing["name"], ing["category"],
             f"{amount_s}{unit}", ts))
        added += 1
    for title in loose:
        con.execute(
            "INSERT INTO nutrition_shopping_items(user_id,name,category,qty,"
            " created_at) VALUES(?,?,?,?,?)",
            (int(user_id), title, "other", "", ts))
        added += 1
    return added


# ── ops routes: programs, the coach view, the shared library ─────────────────

router = APIRouter()

from .main import admin_user, current_user, get_con  # noqa: E402


class ProgramBody(BaseModel):
    name: str = ""
    blurb: str = ""
    coach_id: int | None = None
    product_id: int | None = None
    active: int = 1


@router.get("/api/nutrition/programs")
def ops_programs(user=Depends(current_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT p.*, u.name AS coach_name,"
        " (SELECT COUNT(*) FROM nutrition_clients c WHERE c.program_id=p.id"
        "  AND (c.until IS NULL OR c.until > ?)) AS clients"
        " FROM nutrition_programs p LEFT JOIN users u ON u.id=p.coach_id"
        " ORDER BY p.active DESC, p.name", (time.time(),)).fetchall()]


@router.post("/api/nutrition/programs")
def ops_program_create(body: ProgramBody, user=Depends(admin_user),
                       con=Depends(get_con)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a program needs a name")
    cur = con.execute(
        "INSERT INTO nutrition_programs(name,blurb,coach_id,product_id,"
        " active,created_at) VALUES(?,?,?,?,?,?)",
        (name[:200], body.blurb.strip()[:2000], body.coach_id,
         body.product_id, 1 if body.active else 0, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/nutrition/programs/{pid}")
def ops_program_update(pid: int, body: ProgramBody, user=Depends(admin_user),
                       con=Depends(get_con)):
    if con.execute("SELECT 1 FROM nutrition_programs WHERE id=?",
                   (pid,)).fetchone() is None:
        raise HTTPException(404, "program not found")
    con.execute(
        "UPDATE nutrition_programs SET name=?, blurb=?, coach_id=?,"
        " product_id=?, active=? WHERE id=?",
        (body.name.strip()[:200] or "Untitled", body.blurb.strip()[:2000],
         body.coach_id, body.product_id, 1 if body.active else 0, pid))
    con.commit()
    return {"ok": True}


class SeatBody(BaseModel):
    user_id: int = 0
    program_id: int | None = None


@router.post("/api/nutrition/clients")
def ops_open_seat(body: SeatBody, user=Depends(admin_user),
                  con=Depends(get_con)):
    if con.execute("SELECT 1 FROM users WHERE id=?",
                   (body.user_id,)).fetchone() is None:
        raise HTTPException(404, "user not found")
    open_seat(con, body.user_id, body.program_id,
              source=f"manual:{user['name']}")
    con.commit()
    return {"ok": True}


@router.post("/api/nutrition/clients/{cid}/end")
def ops_end_seat(cid: int, user=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE nutrition_clients SET until=? WHERE id=?"
                " AND until IS NULL", (time.time(), cid))
    con.commit()
    return {"ok": True}


@router.get("/api/nutrition/clients")
def ops_clients(user=Depends(current_user), con=Depends(get_con)):
    """The caseload. Admins see every seat; a coach sees their programs'.
    Oversight follows the SEAT — a member tracking privately for
    themselves appears on no list."""
    if not coach_or_admin(con, user):
        raise HTTPException(403, "the client list is for coaches")
    rows = [dict(r) for r in con.execute(
        "SELECT c.id, c.user_id, c.program_id, c.since, c.until, c.source,"
        " u.name, p.name AS program, p.coach_id"
        " FROM nutrition_clients c JOIN users u ON u.id=c.user_id"
        " LEFT JOIN nutrition_programs p ON p.id=c.program_id"
        " ORDER BY c.until IS NOT NULL, u.name COLLATE NOCASE").fetchall()]
    if not user["is_admin"]:
        rows = [r for r in rows if r["coach_id"] == user["id"]]
    for r in rows:
        r["adherence"] = adherence_of(con, r["user_id"], days=7)
        r["latest_kg"] = latest_kg(con, r["user_id"])
    return rows


@router.get("/api/nutrition/clients/{uid}/detail")
def ops_client_detail(uid: int, user=Depends(current_user),
                      con=Depends(get_con)):
    if not coach_or_admin(con, user):
        raise HTTPException(403, "the client list is for coaches")
    seat = con.execute(
        "SELECT c.*, p.coach_id FROM nutrition_clients c"
        " LEFT JOIN nutrition_programs p ON p.id=c.program_id"
        " WHERE c.user_id=? AND (c.until IS NULL OR c.until > ?)",
        (uid, time.time())).fetchone()
    if seat is None:
        raise HTTPException(404, "no active seat for that person")
    if not user["is_admin"] and seat["coach_id"] != user["id"]:
        raise HTTPException(403, "not your client")
    person = con.execute("SELECT id, name FROM users WHERE id=?",
                         (uid,)).fetchone()
    return {
        "person": dict(person) if person else None,
        "targets": targets_of(con, uid),
        "adherence": adherence_of(con, uid),
        "weights": [dict(r) for r in con.execute(
            "SELECT day, kg FROM nutrition_weight_log WHERE user_id=?"
            " ORDER BY day", (uid,)).fetchall()],
        "recent_log": [dict(r) for r in con.execute(
            "SELECT day, slot, name, cal, protein FROM nutrition_food_log"
            " WHERE user_id=? ORDER BY day DESC, id DESC LIMIT 40",
            (uid,)).fetchall()],
    }
