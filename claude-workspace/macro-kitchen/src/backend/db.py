"""SQLite storage. Multi-user, WAL mode, schema created on init.

Every content table carries a user_id so accounts are fully isolated.
Canonical units are metric everywhere in storage (kg, ml, cm); the frontend
converts for display when the profile is set to imperial."""
import sqlite3
import time
from contextlib import contextmanager

from . import config

# kv is (user_id, key) so each account keeps its own profile/targets JSON.
KV_DDL = """
CREATE TABLE IF NOT EXISTS kv (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, key)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL DEFAULT '',
    salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'pantry',  -- produce|protein|dairy|grains|pantry|frozen|beverages|spices|other
    serving_name TEXT NOT NULL DEFAULT '',    -- "100 g", "1 cup", "1 egg"
    cal REAL NOT NULL DEFAULT 0,              -- per serving
    protein REAL NOT NULL DEFAULT 0,          -- grams per serving
    carbs REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    fiber REAL NOT NULL DEFAULT 0,
    sodium REAL NOT NULL DEFAULT 0,           -- mg per serving
    sugar REAL NOT NULL DEFAULT 0,            -- g per serving
    in_stock INTEGER NOT NULL DEFAULT 0,      -- pantry flag: shopping can skip it
    archived INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    meal_type TEXT NOT NULL DEFAULT 'any',    -- breakfast|lunch|dinner|snack|any
    servings REAL NOT NULL DEFAULT 1,         -- how many servings the batch makes
    prep_min INTEGER NOT NULL DEFAULT 0,
    instructions TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_items (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    qty REAL NOT NULL DEFAULT 1,              -- in servings of the ingredient
    note TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_entries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,                        -- YYYY-MM-DD
    slot TEXT NOT NULL DEFAULT 'dinner',      -- breakfast|lunch|dinner|snack
    recipe_id INTEGER,                        -- one of recipe_id / ingredient_id / title
    ingredient_id INTEGER,
    title TEXT NOT NULL DEFAULT '',           -- free-text entry when no id
    servings REAL NOT NULL DEFAULT 1,
    done INTEGER NOT NULL DEFAULT 0,          -- prepped / eaten checkmark
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS food_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'snack',
    name TEXT NOT NULL,
    servings REAL NOT NULL DEFAULT 1,
    cal REAL NOT NULL DEFAULT 0,              -- totals for the entry (already × servings)
    protein REAL NOT NULL DEFAULT 0,
    carbs REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    fiber REAL NOT NULL DEFAULT 0,
    sodium REAL NOT NULL DEFAULT 0,           -- mg
    sugar REAL NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS weight_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    kg REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL,
    UNIQUE (user_id, day)
);
CREATE TABLE IF NOT EXISTS water_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    ml INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL,
    UNIQUE (user_id, day)
);
CREATE TABLE IF NOT EXISTS shopping_items (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    qty TEXT NOT NULL DEFAULT '',             -- display amount ("3 servings", "2 lb")
    checked INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
""" + KV_DDL


# Columns added after first release; init() bolts them onto existing DBs.
_MIGRATIONS = {
    "ingredients": {
        "sodium": "REAL NOT NULL DEFAULT 0",
        "sugar": "REAL NOT NULL DEFAULT 0",
        "in_stock": "INTEGER NOT NULL DEFAULT 0",
    },
    "food_log": {
        "fiber": "REAL NOT NULL DEFAULT 0",
        "sodium": "REAL NOT NULL DEFAULT 0",
        "sugar": "REAL NOT NULL DEFAULT 0",
    },
}


def init() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        for table, cols in _MIGRATIONS.items():
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


@contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now() -> int:
    return int(time.time())


def rows(con, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]
