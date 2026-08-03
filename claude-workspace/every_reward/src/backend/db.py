"""SQLite access + schema. One connection per call site via connect()."""
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    address TEXT UNIQUE,            -- 0x wallet address (lowercase), NULL for dev users
    nickname TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS nonces (
    address TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
-- Zero-sum ledger: every txn's entries sum to 0. Accounts:
--   user:<id>, market:<id> (escrow), house
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    txn TEXT NOT NULL,
    account TEXT NOT NULL,
    delta INTEGER NOT NULL,         -- credits, signed
    kind TEXT NOT NULL,             -- deposit|bet|payout|rake|refund|redeem|grant
    ref TEXT,                       -- e.g. market:3, item:2, tx:0xabc
    memo TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_account ON ledger(account);
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tx_hash TEXT UNIQUE NOT NULL,
    asset TEXT NOT NULL DEFAULT 'ETH',
    amount_wei TEXT NOT NULL,       -- raw units of the asset (wei / token base units)
    credits INTEGER NOT NULL,
    status TEXT NOT NULL,           -- confirmed|rejected
    detail TEXT,
    created_at INTEGER NOT NULL
);
-- Pack-opening events: betting seals BEFORE the video is uploadable, so the
-- opener can never take bets on a result they already know.
CREATE TABLE IF NOT EXISTS openings (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    game TEXT NOT NULL DEFAULT 'pokemon',   -- pokemon|yugioh|baseball|other
    status TEXT NOT NULL DEFAULT 'open',    -- open (betting) -> sealed -> revealed
    video_path TEXT,
    video_uploaded_at INTEGER,
    creator_id INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    mechanism TEXT NOT NULL,        -- parimutuel|fixed|lmsr
    status TEXT NOT NULL DEFAULT 'open',  -- open|closed|resolved|void
    close_at INTEGER,               -- unix seconds; NULL = manual close
    resolver TEXT NOT NULL DEFAULT 'manual',  -- manual|chainlink_price|http_json
    resolver_config TEXT NOT NULL DEFAULT '{}',
    winner_outcome_id INTEGER,
    rake_bps INTEGER NOT NULL DEFAULT 0,
    lmsr_b REAL NOT NULL DEFAULT 500.0,
    opening_id INTEGER REFERENCES openings(id),
    creator_id INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES markets(id),
    label TEXT NOT NULL,
    fixed_odds REAL,                -- decimal odds (fixed mechanism only)
    pool INTEGER NOT NULL DEFAULT 0,        -- parimutuel: total staked
    shares REAL NOT NULL DEFAULT 0.0        -- lmsr: outstanding shares q_i
);
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES markets(id),
    outcome_id INTEGER NOT NULL REFERENCES outcomes(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    stake INTEGER NOT NULL,
    odds_at_bet REAL,               -- fixed: locked decimal odds
    shares REAL,                    -- lmsr: shares bought
    payout INTEGER,                 -- set at settlement
    settled INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS store_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,       -- -1 = unlimited
    emoji TEXT NOT NULL DEFAULT '🎁',
    active INTEGER NOT NULL DEFAULT 1,
    -- catalog-sourced items (source != 'manual') are auto-priced and synced
    source TEXT NOT NULL DEFAULT 'manual',
    source_id TEXT,
    base_price_cents INTEGER,               -- source price at last sync
    markup_bps INTEGER,
    last_synced INTEGER,
    suspend_reason TEXT,                    -- set when auto-suspended
    image_url TEXT                          -- card/product image from the source
);
CREATE TABLE IF NOT EXISTS redemptions (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES store_items(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    price_paid INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending|fulfilled|cancelled
    created_at INTEGER NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init() -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
        cols = [r["name"] for r in con.execute("PRAGMA table_info(deposits)")]
        if "asset" not in cols:  # migration for databases created before ERC-20 support
            con.execute("ALTER TABLE deposits ADD COLUMN asset TEXT NOT NULL DEFAULT 'ETH'")
        cols = [r["name"] for r in con.execute("PRAGMA table_info(store_items)")]
        for name, decl in [("source", "TEXT NOT NULL DEFAULT 'manual'"),
                           ("source_id", "TEXT"), ("base_price_cents", "INTEGER"),
                           ("markup_bps", "INTEGER"), ("last_synced", "INTEGER"),
                           ("suspend_reason", "TEXT"), ("image_url", "TEXT")]:
            if name not in cols:  # migration for pre-catalog databases
                con.execute(f"ALTER TABLE store_items ADD COLUMN {name} {decl}")
        cols = [r["name"] for r in con.execute("PRAGMA table_info(markets)")]
        if "opening_id" not in cols:  # migration for pre-openings databases
            con.execute("ALTER TABLE markets ADD COLUMN opening_id INTEGER "
                        "REFERENCES openings(id)")
    con.close()


def now() -> int:
    return int(time.time())
