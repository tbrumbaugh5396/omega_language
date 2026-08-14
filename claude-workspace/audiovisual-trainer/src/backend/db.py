"""SQLite storage. Multi-user, WAL mode, schema created on init.

Every content table carries a user_id so accounts are fully isolated.

The curriculum, drills, labs and reference library are *not* in the database —
they ship as data in curriculum.py / library.py so they version with the app.
Rows here reference those items only by stable slug, so a curriculum rewrite
never orphans a user's history: unknown slugs are ignored on read.

Table-to-module map (Part 9 of the roadmap):
    pieces        -> 1. practice loop manager (Track A: MAKE)
    drill_attempts-> 2. discrimination trainer
    vocab_srs     -> 5. vocabulary builder (spaced repetition)
    lab_saves     -> 3. effects lab
    analyses      -> 4. reference analyzer
    selections    -> 6. generator + filter sandbox (taste-training data)
    articulation  -> Part 14, the second network
    practice_log  -> Track B: TOOLS (deliberate practice)
    progress/notes-> Track C: THEORY (pulled, not pushed)
"""
import sqlite3
import time
from contextlib import contextmanager

from . import config

# kv is (user_id, key) so each account keeps its own profile/prefs JSON.
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

-- Track C. One row per theory item the user has touched.
CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    slug TEXT NOT NULL,                       -- curriculum lesson slug
    status TEXT NOT NULL DEFAULT 'reading',   -- reading|applied|done
    confidence INTEGER NOT NULL DEFAULT 0,    -- 0-5 self-rating
    minutes INTEGER NOT NULL DEFAULT 0,
    pulled_by TEXT NOT NULL DEFAULT '',       -- the failure that pulled it in
    started INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    UNIQUE (user_id, slug)
);

-- Free-text notes attached to any curriculum or library item.
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    slug TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    updated INTEGER NOT NULL,
    UNIQUE (user_id, slug)
);

-- Track A. One finished piece per week, with its brief and postmortem.
CREATE TABLE IF NOT EXISTS pieces (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    week TEXT NOT NULL DEFAULT '',            -- YYYY-Www, the week it belongs to
    brief TEXT NOT NULL DEFAULT '{}',         -- JSON: the generated/edited brief
    medium TEXT NOT NULL DEFAULT '',          -- motion|shader|audio|still|edit|web
    constraint_note TEXT NOT NULL DEFAULT '', -- the deliberate limitation
    rubric TEXT NOT NULL DEFAULT '',          -- written BEFORE making it
    status TEXT NOT NULL DEFAULT 'briefed',   -- briefed|making|shipped|abandoned
    deadline TEXT NOT NULL DEFAULT '',        -- YYYY-MM-DD
    shipped TEXT NOT NULL DEFAULT '',         -- YYYY-MM-DD actually finished
    link TEXT NOT NULL DEFAULT '',            -- where the artifact lives
    pm_reads TEXT NOT NULL DEFAULT '',        -- postmortem: what reads wrong
    pm_why TEXT NOT NULL DEFAULT '',          -- postmortem: hypothesised mechanism
    pm_study TEXT NOT NULL DEFAULT '',        -- postmortem: what to pull next
    pm_slug TEXT NOT NULL DEFAULT '',         -- theory item the break pointed at
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL
);

-- Module 2. Every graded discrimination round.
CREATE TABLE IF NOT EXISTS drill_attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    drill TEXT NOT NULL,                      -- drill id from curriculum.DRILLS
    level INTEGER NOT NULL DEFAULT 1,         -- difficulty tier; drills adapt
    correct INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    ms INTEGER NOT NULL DEFAULT 0,            -- round duration
    detail TEXT NOT NULL DEFAULT '',          -- JSON: per-question record
    created INTEGER NOT NULL
);

-- Module 5. Spaced repetition over perceptual vocabulary.
CREATE TABLE IF NOT EXISTS vocab_srs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    term TEXT NOT NULL,                       -- library.TERMS key
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    due INTEGER NOT NULL DEFAULT 0,           -- epoch seconds
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL,
    UNIQUE (user_id, term)
);

-- Track B. Deliberate practice sessions on a tool or sub-skill.
CREATE TABLE IF NOT EXISTS practice_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,                        -- YYYY-MM-DD
    track TEXT NOT NULL DEFAULT 'tools',      -- make|tools|theory|perception
    tool TEXT NOT NULL DEFAULT '',            -- Resolve, Reaper, Shadertoy...
    slug TEXT NOT NULL DEFAULT '',            -- curriculum item worked on
    focus TEXT NOT NULL DEFAULT '',           -- the isolated sub-skill
    minutes INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 0,        -- 1-5 how it went
    notes TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);

-- Module 6. Every selection among candidates is a taste rep.
CREATE TABLE IF NOT EXISTS selections (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    sandbox TEXT NOT NULL,                    -- which generator produced them
    chosen TEXT NOT NULL DEFAULT '{}',        -- JSON params of the pick
    candidates TEXT NOT NULL DEFAULT '[]',    -- JSON params of the field
    rationale TEXT NOT NULL DEFAULT '',       -- optional articulation rep
    created INTEGER NOT NULL
);

-- Module 4. Archived reference decompositions.
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'image',       -- image|audio
    name TEXT NOT NULL DEFAULT '',
    features TEXT NOT NULL DEFAULT '{}',      -- JSON feature bundle
    notes TEXT NOT NULL DEFAULT '',           -- the human read on it
    created INTEGER NOT NULL
);

-- Part 14. Articulation reps, the separately trained network.
CREATE TABLE IF NOT EXISTS articulation (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'teachback',   -- see curriculum.ARTICULATION
    slug TEXT NOT NULL DEFAULT '',            -- what it is about
    prompt TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    predicted TEXT NOT NULL DEFAULT '',       -- calibration: what you expect flagged
    actual TEXT NOT NULL DEFAULT '',          -- calibration: what was flagged
    score INTEGER NOT NULL DEFAULT 0,         -- calibration hit rate, 0-100
    created INTEGER NOT NULL
);

-- Module 3. Saved lab parameter sets and edited source.
CREATE TABLE IF NOT EXISTS lab_saves (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    lab TEXT NOT NULL,                        -- lab id from curriculum.LABS
    name TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',        -- JSON blob, lab-specific
    source TEXT NOT NULL DEFAULT '',          -- edited shader / audio graph source
    note TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
""" + KV_DDL


# Columns added after first release; init() bolts them onto existing DBs.
_MIGRATIONS: dict[str, dict[str, str]] = {}


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
