"""MacroKitchen — FastAPI backend. Multi-user, JSON API + static PWA.

Meal planning, meal prep, nutrition tracking, shopping lists, plus a diet log
with weight, water, and calorie-target tracking. Every content route is scoped
to the signed-in user, resolved from a bearer token (see current_user)."""
import sqlite3
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, seeder

app = FastAPI(title="MacroKitchen")
db.init()

CATEGORIES = ("produce", "protein", "dairy", "grains", "pantry", "frozen",
              "beverages", "spices", "other")
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack", "any")
SLOTS = ("breakfast", "lunch", "dinner", "snack")
KV_KEYS = ("profile", "prefs")

# Tables carried in a backup, parents before children so restore can remap ids.
BACKUP_TABLES = ["ingredients", "recipes", "recipe_items", "plan_entries",
                 "food_log", "weight_log", "water_log", "shopping_items"]
BACKUP_FORMAT = "macro-kitchen-backup/1"


# ------------------------------------------------------------ auth core

def current_user(authorization: str = Header(None)) -> int:
    """Resolve the signed-in user id from an 'Authorization: Bearer <token>'."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "not signed in")
    with db.connect() as con:
        row = con.execute(
            "SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "session expired")
    return row["user_id"]


def _user_public(con, uid: int) -> dict:
    r = con.execute(
        "SELECT id, username, display_name, created FROM users WHERE id=?",
        (uid,)).fetchone()
    return dict(r) if r else {}


class SignupIn(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/signup")
def signup(body: SignupIn):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(400, "username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "password must be at least 6 characters")
    salt, pw = auth.hash_password(body.password)
    display = body.display_name.strip() or username
    with db.connect() as con:
        exists = con.execute(
            "SELECT 1 FROM users WHERE username=? COLLATE NOCASE",
            (username,)).fetchone()
        if exists:
            raise HTTPException(409, "that username is taken")
        cur = con.execute(
            "INSERT INTO users(username,display_name,salt,pw_hash,created) "
            "VALUES(?,?,?,?,?)", (username, display, salt, pw, db.now()))
        uid = cur.lastrowid
        token = auth.new_token()
        con.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
                    (token, uid, db.now()))
        return {"token": token, "user": _user_public(con, uid)}


@app.post("/api/auth/login")
def login(body: LoginIn):
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (body.username.strip(),)).fetchone()
        if not row or not auth.verify_password(
                body.password, row["salt"], row["pw_hash"]):
            raise HTTPException(401, "wrong username or password")
        token = auth.new_token()
        con.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
                    (token, row["id"], db.now()))
        return {"token": token, "user": _user_public(con, row["id"])}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(None)):
    token = authorization[7:] if authorization and authorization.lower(
    ).startswith("bearer ") else ""
    if token:
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"ok": True}


@app.get("/api/me")
def get_me(uid: int = Depends(current_user)):
    with db.connect() as con:
        return _user_public(con, uid)


class ProfileIn(BaseModel):
    display_name: str


@app.patch("/api/me")
def update_me(body: ProfileIn, uid: int = Depends(current_user)):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(400, "display name cannot be empty")
    with db.connect() as con:
        con.execute("UPDATE users SET display_name=? WHERE id=?", (name, uid))
        return _user_public(con, uid)


class PasswordIn(BaseModel):
    current: str
    new: str


@app.post("/api/me/password")
def change_password(body: PasswordIn, uid: int = Depends(current_user)):
    if len(body.new) < 6:
        raise HTTPException(400, "new password must be at least 6 characters")
    with db.connect() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not auth.verify_password(body.current, row["salt"], row["pw_hash"]):
            raise HTTPException(403, "current password is wrong")
        salt, pw = auth.hash_password(body.new)
        con.execute("UPDATE users SET salt=?, pw_hash=? WHERE id=?",
                    (salt, pw, uid))
        # sign out other sessions after a password change
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        token = auth.new_token()
        con.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
                    (token, uid, db.now()))
    return {"ok": True, "token": token}


# ---------------------------------------------------------------- state

@app.get("/api/state")
def state(uid: int = Depends(current_user)):
    with db.connect() as con:
        kv = {r["key"]: r["value"]
              for r in con.execute("SELECT key,value FROM kv WHERE user_id=?", (uid,))}
        return {
            "user": _user_public(con, uid),
            "kv": kv,
            "ingredients": db.rows(con, "SELECT * FROM ingredients WHERE user_id=? AND archived=0 ORDER BY category, name", (uid,)),
            "recipes": db.rows(con, "SELECT * FROM recipes WHERE user_id=? AND archived=0 ORDER BY favorite DESC, name", (uid,)),
            "recipe_items": db.rows(con, "SELECT * FROM recipe_items WHERE user_id=? ORDER BY recipe_id, id", (uid,)),
            "plan_entries": db.rows(con, "SELECT * FROM plan_entries WHERE user_id=? ORDER BY day, slot, id", (uid,)),
            "food_log": db.rows(con, "SELECT * FROM food_log WHERE user_id=? ORDER BY day DESC, id DESC LIMIT 3000", (uid,)),
            "weight_log": db.rows(con, "SELECT * FROM weight_log WHERE user_id=? ORDER BY day", (uid,)),
            "water_log": db.rows(con, "SELECT * FROM water_log WHERE user_id=? ORDER BY day DESC LIMIT 400", (uid,)),
            "shopping_items": db.rows(con, "SELECT * FROM shopping_items WHERE user_id=? ORDER BY checked, category, id", (uid,)),
        }


class KVIn(BaseModel):
    value: str


@app.put("/api/kv/{key}")
def put_kv(key: str, body: KVIn, uid: int = Depends(current_user)):
    if key not in KV_KEYS:
        raise HTTPException(400, "unknown key")
    with db.connect() as con:
        con.execute(
            "INSERT INTO kv(user_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (uid, key, body.value))
    return {"ok": True}


# --------------------------------------------------- quick daily logging
# NB: declared before the generic /api/{table} routes so they win the match.

class WaterIn(BaseModel):
    day: str
    delta_ml: int


@app.post("/api/water")
def add_water(body: WaterIn, uid: int = Depends(current_user)):
    """One tap: add (or remove) water for a day. Clamped at zero."""
    with db.connect() as con:
        con.execute(
            "INSERT INTO water_log(user_id,day,ml,created) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET "
            "ml=MAX(0, water_log.ml + excluded.ml)",
            (uid, body.day, max(0, body.delta_ml), db.now()))
        # the upsert above can't subtract on first insert; normalize both paths
        if body.delta_ml < 0:
            con.execute(
                "UPDATE water_log SET ml=MAX(0, ml + ?) WHERE user_id=? AND day=? ",
                (body.delta_ml, uid, body.day))
        total = con.execute(
            "SELECT ml FROM water_log WHERE user_id=? AND day=?",
            (uid, body.day)).fetchone()["ml"]
    return {"ok": True, "day": body.day, "ml": total}


class WeightIn(BaseModel):
    day: str
    kg: float
    note: str = ""


@app.post("/api/weight")
def set_weight(body: WeightIn, uid: int = Depends(current_user)):
    """Upsert the weigh-in for a day (stored in kg)."""
    if not (20 <= body.kg <= 400):
        raise HTTPException(400, "weight must be 20-400 kg")
    with db.connect() as con:
        con.execute(
            "INSERT INTO weight_log(user_id,day,kg,note,created) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET "
            "kg=excluded.kg, note=excluded.note",
            (uid, body.day, round(body.kg, 2), body.note.strip(), db.now()))
    return {"ok": True}


# ------------------------------------------------------- shopping list

class GenerateIn(BaseModel):
    start: str
    end: str
    skip_stocked: bool = False


@app.post("/api/shopping/generate")
def shopping_generate(body: GenerateIn, uid: int = Depends(current_user)):
    """Aggregate the plan between start and end (inclusive) into shopping
    items — recipes are expanded to their ingredients, quantities summed.
    With skip_stocked, ingredients flagged in_stock (your pantry) are left
    off the list."""
    if body.end < body.start:
        raise HTTPException(400, "end must not be before start")
    with db.connect() as con:
        entries = db.rows(
            con, "SELECT * FROM plan_entries WHERE user_id=? AND day>=? AND day<=?",
            (uid, body.start, body.end))
        if not entries:
            return {"ok": True, "added": 0, "skipped": 0}
        recipes = {r["id"]: r for r in db.rows(
            con, "SELECT * FROM recipes WHERE user_id=?", (uid,))}
        items = db.rows(
            con, "SELECT * FROM recipe_items WHERE user_id=?", (uid,))
        by_recipe: dict[int, list] = {}
        for it in items:
            by_recipe.setdefault(it["recipe_id"], []).append(it)
        ingredients = {i["id"]: i for i in db.rows(
            con, "SELECT * FROM ingredients WHERE user_id=?", (uid,))}

        need: dict[int, float] = {}      # ingredient_id -> servings
        loose: list[str] = []            # free-text titles
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

        ts = db.now()
        added = 0
        skipped = 0
        for ing_id, qty in sorted(need.items(),
                                  key=lambda kv: ingredients[kv[0]]["name"]):
            ing = ingredients.get(ing_id)
            if not ing:
                continue
            if body.skip_stocked and ing["in_stock"]:
                skipped += 1
                continue
            amount = round(qty, 1)
            amount_s = str(int(amount)) if amount == int(amount) else f"{amount}"
            unit = f" × {ing['serving_name']}" if ing["serving_name"] else " servings"
            con.execute(
                "INSERT INTO shopping_items(user_id,name,category,qty,created) "
                "VALUES(?,?,?,?,?)",
                (uid, ing["name"], ing["category"], f"{amount_s}{unit}", ts))
            added += 1
        for title in loose:
            con.execute(
                "INSERT INTO shopping_items(user_id,name,category,qty,created) "
                "VALUES(?,?,?,?,?)", (uid, title, "other", "", ts))
            added += 1
    return {"ok": True, "added": added, "skipped": skipped}


@app.post("/api/shopping/clear_checked")
def shopping_clear_checked(uid: int = Depends(current_user)):
    with db.connect() as con:
        cur = con.execute(
            "DELETE FROM shopping_items WHERE user_id=? AND checked=1", (uid,))
    return {"ok": True, "removed": cur.rowcount}


# -------------------------------------------------------- starter seed

@app.post("/api/seed")
def seed(uid: int = Depends(current_user)):
    with db.connect() as con:
        if seeder.has_content(con, uid):
            raise HTTPException(409, "this account already has content")
        counts = seeder.seed_user(con, uid)
    return {"ok": True, "seeded": counts}


# ---------------------------------------------------- backup / restore
# A backup is a JSON snapshot of the signed-in user's rows. Restore wipes only
# that user's data and re-inserts with fresh ids (recipe/ingredient refs
# remapped so the restored plan and recipes stay linked).

# column -> default used when a (possibly older) backup lacks the field
_PLAIN_RESTORE_COLS = {
    "food_log": [("day", ""), ("slot", "snack"), ("name", ""),
                 ("servings", 1), ("cal", 0), ("protein", 0), ("carbs", 0),
                 ("fat", 0), ("fiber", 0), ("sodium", 0), ("sugar", 0),
                 ("created", None)],
    "weight_log": [("day", ""), ("kg", 0), ("note", ""), ("created", None)],
    "water_log": [("day", ""), ("ml", 0), ("created", None)],
    "shopping_items": [("name", ""), ("category", "other"), ("qty", ""),
                       ("checked", 0), ("created", None)],
}


@app.get("/api/backup")
def backup(uid: int = Depends(current_user)):
    with db.connect() as con:
        user = _user_public(con, uid)
        kv = {r["key"]: r["value"]
              for r in con.execute("SELECT key,value FROM kv WHERE user_id=?", (uid,))}
        tables = {}
        for t in BACKUP_TABLES:
            rows = db.rows(con, f"SELECT * FROM {t} WHERE user_id=? ORDER BY id", (uid,))
            for r in rows:
                r.pop("user_id", None)
            tables[t] = rows
    payload = {"format": BACKUP_FORMAT, "created": db.now(),
               "account": user.get("username", ""), "kv": kv, "tables": tables}
    stamp = time.strftime("%Y-%m-%d")
    return JSONResponse(payload, headers={
        "Content-Disposition": f'attachment; filename="macro-kitchen-backup-{stamp}.json"'})


@app.post("/api/restore")
def restore(payload: dict, uid: int = Depends(current_user)):
    if not isinstance(payload, dict) or payload.get("format") != BACKUP_FORMAT:
        raise HTTPException(400, "not a MacroKitchen backup file")
    tables = payload.get("tables", {})
    kv = payload.get("kv", {})
    if not isinstance(tables, dict) or not isinstance(kv, dict):
        raise HTTPException(400, "malformed backup file")
    for t in tables:
        if t not in BACKUP_TABLES:
            raise HTTPException(400, f"unknown table in backup: {t}")

    # Safety net: snapshot the whole DB before touching anything.
    if config.DB_PATH.exists():
        backups = config.DATA_DIR / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        aside = backups / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.db"
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(aside)
        src.backup(dst)
        dst.close()
        src.close()

    counts = {}
    with db.connect() as con:
        for t in reversed(BACKUP_TABLES):
            con.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
        con.execute("DELETE FROM kv WHERE user_id=?", (uid,))

        ing_map = {}
        for row in tables.get("ingredients", []):
            cur = con.execute(
                "INSERT INTO ingredients(user_id,name,category,serving_name,"
                "cal,protein,carbs,fat,fiber,sodium,sugar,in_stock,archived,"
                "created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, row.get("name", ""), row.get("category", "other"),
                 row.get("serving_name", ""), row.get("cal", 0),
                 row.get("protein", 0), row.get("carbs", 0), row.get("fat", 0),
                 row.get("fiber", 0), row.get("sodium") or 0,
                 row.get("sugar") or 0, row.get("in_stock") or 0,
                 row.get("archived", 0), row.get("created", db.now())))
            ing_map[row.get("id")] = cur.lastrowid
        counts["ingredients"] = len(tables.get("ingredients", []))

        rec_map = {}
        for row in tables.get("recipes", []):
            cur = con.execute(
                "INSERT INTO recipes(user_id,name,meal_type,servings,prep_min,"
                "instructions,notes,favorite,archived,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, row.get("name", ""), row.get("meal_type", "any"),
                 row.get("servings", 1), row.get("prep_min", 0),
                 row.get("instructions", ""), row.get("notes", ""),
                 row.get("favorite", 0), row.get("archived", 0),
                 row.get("created", db.now())))
            rec_map[row.get("id")] = cur.lastrowid
        counts["recipes"] = len(tables.get("recipes", []))

        kept = 0
        for row in tables.get("recipe_items", []):
            rid = rec_map.get(row.get("recipe_id"))
            iid = ing_map.get(row.get("ingredient_id"))
            if rid is None or iid is None:   # drop items whose parents vanished
                continue
            con.execute(
                "INSERT INTO recipe_items(user_id,recipe_id,ingredient_id,qty,"
                "note,created) VALUES(?,?,?,?,?,?)",
                (uid, rid, iid, row.get("qty", 1), row.get("note", ""),
                 row.get("created", db.now())))
            kept += 1
        counts["recipe_items"] = kept

        for row in tables.get("plan_entries", []):
            con.execute(
                "INSERT INTO plan_entries(user_id,day,slot,recipe_id,"
                "ingredient_id,title,servings,done,created) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, row.get("day", ""), row.get("slot", "dinner"),
                 rec_map.get(row.get("recipe_id")),
                 ing_map.get(row.get("ingredient_id")),
                 row.get("title", ""), row.get("servings", 1),
                 row.get("done", 0), row.get("created", db.now())))
        counts["plan_entries"] = len(tables.get("plan_entries", []))

        for t, cols in _PLAIN_RESTORE_COLS.items():
            rows = tables.get(t, [])
            names = [c for c, _ in cols]
            for row in rows:
                vals = []
                for c, default in cols:
                    v = row.get(c)
                    if v is None:
                        v = db.now() if default is None else default
                    vals.append(v)
                con.execute(
                    f"INSERT INTO {t}(user_id,{','.join(names)}) "
                    f"VALUES(?,{','.join('?' * len(names))})",
                    [uid] + vals)
            counts[t] = len(rows)

        for key, value in kv.items():
            if key in KV_KEYS:
                con.execute("INSERT INTO kv(user_id,key,value) VALUES(?,?,?)",
                            (uid, key, str(value)))
    return {"ok": True, "restored": counts}


# ------------------------------------------------------- generic CRUD
# Each editable table gets POST /api/<table>, PATCH+DELETE /api/<table>/{id},
# all scoped to the signed-in user. weight_log/water_log rows are created
# through their upsert routes above but can be edited/deleted here.

TABLES = {
    "ingredients": {"name", "category", "serving_name", "cal", "protein",
                    "carbs", "fat", "fiber", "sodium", "sugar", "in_stock",
                    "archived"},
    "recipes": {"name", "meal_type", "servings", "prep_min", "instructions",
                "notes", "favorite", "archived"},
    "recipe_items": {"recipe_id", "ingredient_id", "qty", "note"},
    "plan_entries": {"day", "slot", "recipe_id", "ingredient_id", "title",
                     "servings", "done"},
    "food_log": {"day", "slot", "name", "servings", "cal", "protein", "carbs",
                 "fat", "fiber", "sodium", "sugar"},
    "weight_log": {"day", "kg", "note"},
    "water_log": {"day", "ml"},
    "shopping_items": {"name", "category", "qty", "checked"},
}

_NUM_RANGES = {
    "cal": (0, 5000), "protein": (0, 1000), "carbs": (0, 1000),
    "fat": (0, 1000), "fiber": (0, 500), "sodium": (0, 20000),
    "sugar": (0, 1000), "servings": (0.05, 100),
    "qty": (0.01, 500), "prep_min": (0, 1440), "kg": (20, 400),
    "ml": (0, 30000),
}


def _validate(table: str, fields: dict) -> dict:
    allowed = TABLES.get(table)
    if allowed is None:
        raise HTTPException(404, "unknown table")
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise HTTPException(400, "no valid fields")
    if "category" in clean and clean["category"] not in CATEGORIES:
        raise HTTPException(400, f"category must be one of {CATEGORIES}")
    if "meal_type" in clean and clean["meal_type"] not in MEAL_TYPES:
        raise HTTPException(400, f"meal_type must be one of {MEAL_TYPES}")
    if "slot" in clean and clean["slot"] not in SLOTS:
        raise HTTPException(400, f"slot must be one of {SLOTS}")
    for f, (lo, hi) in _NUM_RANGES.items():
        if f in clean and clean[f] is not None:
            if not isinstance(clean[f], (int, float)) or isinstance(clean[f], bool) \
                    or not (lo <= clean[f] <= hi):
                raise HTTPException(400, f"{f} must be a number {lo}-{hi}")
    for f in ("archived", "favorite", "done", "checked", "in_stock"):
        if f in clean and clean[f] not in (0, 1, True, False):
            raise HTTPException(400, f"{f} must be 0 or 1")
    return clean


def _check_refs(table: str, clean: dict, uid: int) -> None:
    """Foreign keys named in the payload must belong to the signed-in user."""
    refs = []
    if table == "recipe_items":
        refs = [("recipes", clean.get("recipe_id")),
                ("ingredients", clean.get("ingredient_id"))]
    elif table == "plan_entries":
        refs = [("recipes", clean.get("recipe_id")),
                ("ingredients", clean.get("ingredient_id"))]
    with db.connect() as con:
        for ref_table, ref_id in refs:
            if ref_id is None:
                continue
            own = con.execute(
                f"SELECT 1 FROM {ref_table} WHERE id=? AND user_id=?",
                (ref_id, uid)).fetchone()
            if not own:
                raise HTTPException(404, f"{ref_table[:-1]} not found")


@app.post("/api/{table}")
def create(table: str, fields: dict, uid: int = Depends(current_user)):
    clean = _validate(table, fields)
    if table == "recipe_items" and (
            clean.get("recipe_id") is None or clean.get("ingredient_id") is None):
        raise HTTPException(400, "recipe_id and ingredient_id are required")
    _check_refs(table, clean, uid)
    cols = list(clean) + ["user_id", "created"]
    vals = list(clean.values()) + [uid, db.now()]
    try:
        with db.connect() as con:
            cur = con.execute(
                f"INSERT INTO {table}({','.join(cols)}) "
                f"VALUES({','.join('?' * len(cols))})", vals)
            return {"id": cur.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "an entry for that day already exists")


@app.patch("/api/{table}/{item_id}")
def update(table: str, item_id: int, fields: dict, uid: int = Depends(current_user)):
    clean = _validate(table, fields)
    _check_refs(table, clean, uid)
    sets = ",".join(f"{k}=?" for k in clean)
    try:
        with db.connect() as con:
            cur = con.execute(
                f"UPDATE {table} SET {sets} WHERE id=? AND user_id=?",
                list(clean.values()) + [item_id, uid])
            if cur.rowcount == 0:
                raise HTTPException(404, "not found")
    except sqlite3.IntegrityError:
        raise HTTPException(409, "an entry for that day already exists")
    return {"ok": True}


@app.delete("/api/{table}/{item_id}")
def delete(table: str, item_id: int, uid: int = Depends(current_user)):
    if table not in TABLES:
        raise HTTPException(404, "unknown table")
    with db.connect() as con:
        con.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (item_id, uid))
    return {"ok": True}


# ------------------------------------------------------------- static

app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.FRONTEND_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(config.FRONTEND_DIR / "sw.js",
                        media_type="application/javascript")


@app.get("/{path:path}")
def index(path: str):
    f = config.FRONTEND_DIR / path
    if path and f.is_file() and config.FRONTEND_DIR in f.resolve().parents:
        return FileResponse(f)
    return FileResponse(config.FRONTEND_DIR / "index.html")
