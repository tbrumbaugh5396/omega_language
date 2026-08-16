"""SQLite schema and connection helpers."""
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  role TEXT NOT NULL DEFAULT 'customer',   -- customer|distributor|employee|influencer|admin
  token TEXT UNIQUE NOT NULL,
  pin TEXT DEFAULT '',                     -- legacy plaintext; migrated away
  pin_hash TEXT DEFAULT '',                -- time-clock PIN, peppered HMAC
  job TEXT DEFAULT 'general',              -- staff job: driver|dsd|warehouse|sales_rep|ambassador|event_staff|general
  employment TEXT DEFAULT 'employee',      -- employee (hourly) | contractor (per-route)
  password_hash TEXT DEFAULT '',           -- salt$pbkdf2; empty = no password
  region TEXT DEFAULT '',
  is_admin INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  category TEXT DEFAULT '',
  price_cents INTEGER NOT NULL,            -- retail unit price
  case_size INTEGER DEFAULT 12,
  case_price_cents INTEGER NOT NULL,       -- distributor price per case
  image INTEGER DEFAULT 0,                 -- 1 = uploaded photo in data/uploads
  active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'retail',              -- retail|distributor_dc
  region TEXT NOT NULL,
  city TEXT DEFAULT '',
  lat REAL, lng REAL,
  contact TEXT DEFAULT '',
  active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS inventory (
  store_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  qty INTEGER NOT NULL DEFAULT 0,
  par INTEGER NOT NULL DEFAULT 24,         -- restock target; below 25% = low
  updated_at REAL NOT NULL,
  PRIMARY KEY (store_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'customer',   -- customer|distributor
  status TEXT NOT NULL DEFAULT 'pending',  -- pending|confirmed|shipped|delivered|cancelled
  region TEXT DEFAULT '',
  store_id INTEGER,
  subtotal_cents INTEGER NOT NULL,
  tax_cents INTEGER DEFAULT 0,
  shipping_cents INTEGER DEFAULT 0,
  total_cents INTEGER DEFAULT 0,
  payment_status TEXT DEFAULT 'unpaid',    -- unpaid|paid|cod|on_terms|refunded
  payment_ref TEXT DEFAULT '',             -- e.g. Stripe checkout session id
  ship_name TEXT DEFAULT '',
  address TEXT DEFAULT '',
  city TEXT DEFAULT '',
  postal TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  fulfilled_store_id INTEGER,              -- stock source once shipped
  affiliate_code TEXT DEFAULT '',
  visitor_id TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  order_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  clock_in REAL NOT NULL,
  clock_out REAL,
  event_id INTEGER,                        -- promo event worked, if any
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS promos (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'promo',      -- promo (scannable offer) | event (in person)
  name TEXT NOT NULL,
  body TEXT DEFAULT '',
  product_id INTEGER,
  discount_pct INTEGER DEFAULT 0,
  region TEXT DEFAULT '',
  city TEXT DEFAULT '',
  lat REAL, lng REAL,
  starts TEXT DEFAULT '',
  video_url TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS promo_scans (
  promo_id INTEGER NOT NULL,
  visitor_id TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  goal TEXT DEFAULT 'purchase',            -- funnel step counted as conversion
  status TEXT NOT NULL DEFAULT 'running',  -- draft|running|done
  auto_generated INTEGER DEFAULT 0,
  winner_variant_id INTEGER,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS variants (
  id INTEGER PRIMARY KEY,
  experiment_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  headline TEXT DEFAULT '',
  cta TEXT DEFAULT '',
  theme TEXT DEFAULT 'default',
  weight INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS assignments (
  experiment_id INTEGER NOT NULL,
  visitor_id TEXT NOT NULL,
  variant_id INTEGER NOT NULL,
  assigned_at REAL NOT NULL,
  PRIMARY KEY (experiment_id, visitor_id)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  visitor_id TEXT NOT NULL,
  user_id INTEGER,
  step TEXT NOT NULL,                      -- visit|view_product|add_to_cart|checkout|purchase
  region TEXT DEFAULT '',
  product_id INTEGER,
  experiment_id INTEGER,
  variant_id INTEGER,
  value_cents INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_step ON events(step, created_at);
CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id);

CREATE TABLE IF NOT EXISTS affiliates (
  id INTEGER PRIMARY KEY,
  user_id INTEGER UNIQUE NOT NULL,
  code TEXT UNIQUE NOT NULL,
  rate_bps INTEGER NOT NULL,
  clicks INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
  id INTEGER PRIMARY KEY,
  affiliate_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  commission_cents INTEGER NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trucks (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  capacity_cases INTEGER DEFAULT 400,
  home_region TEXT DEFAULT '',
  driver_user_id INTEGER,                  -- set by QR check-in
  active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS routes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  truck_id INTEGER,
  route_date TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planned',  -- planned|active|done
  total_km REAL DEFAULT 0,
  total_min REAL DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS route_stops (
  route_id INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  store_id INTEGER NOT NULL,
  leg_km REAL DEFAULT 0,
  delivered INTEGER DEFAULT 0,
  PRIMARY KEY (route_id, seq)
);

CREATE TABLE IF NOT EXISTS outreach (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,                      -- prospect store / account name
  region TEXT NOT NULL,
  city TEXT DEFAULT '',
  lat REAL, lng REAL,
  stage TEXT NOT NULL DEFAULT 'lead',      -- lead|contacted|sampled|stocked|lost
  owner_user_id INTEGER,
  next_action TEXT DEFAULT '',
  next_action_date TEXT DEFAULT '',
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
  endpoint TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  sub TEXT NOT NULL,                       -- full subscription JSON
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                      -- team | support | dm
  name TEXT DEFAULT '',
  customer_user_id INTEGER,                -- support convs: who it belongs to
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conv_members (
  conv_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY (conv_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  conv_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  body TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);

CREATE TABLE IF NOT EXISTS email_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  kind TEXT,
  dedup_key TEXT UNIQUE,
  subject TEXT,
  status TEXT,                             -- sent | dry | error: ...
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sub_billing (
  id INTEGER PRIMARY KEY,
  contract_id TEXT NOT NULL,
  cycle_month TEXT NOT NULL,
  status TEXT DEFAULT 'pending',           -- pending|success|failed: <code>|error: ...
  created_at REAL NOT NULL,
  UNIQUE (contract_id, cycle_month)        -- one attempt row per contract per cycle
);

CREATE TABLE IF NOT EXISTS box_cycles (
  id INTEGER PRIMARY KEY,
  month TEXT UNIQUE NOT NULL,              -- 'YYYY-MM'
  bill_date TEXT NOT NULL,
  dunning_close TEXT NOT NULL,
  curation_lock TEXT NOT NULL,
  ship_date TEXT NOT NULL,
  billed_count INTEGER DEFAULT 0,          -- from billing provider (manual for now)
  skipped_count INTEGER DEFAULT 0,
  allocated_count INTEGER DEFAULT 0,       -- boxes actually allocated/packed
  closed INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements (
  key TEXT PRIMARY KEY,
  unlocked_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,                         -- NULL = for all admins
  kind TEXT DEFAULT 'info',
  dedup_key TEXT UNIQUE,                   -- NULL allowed; prevents repeats
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_reads (
  notification_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY (notification_id, user_id)
);

CREATE TABLE IF NOT EXISTS login_tokens (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at REAL NOT NULL,
  used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  body TEXT DEFAULT '',
  url TEXT DEFAULT '',
  provider TEXT DEFAULT '',
  title TEXT DEFAULT '',
  image TEXT DEFAULT '',
  description TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_log (
  id INTEGER PRIMARY KEY,
  outreach_id INTEGER NOT NULL,
  user_id INTEGER,
  note TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    # check_same_thread=False: FastAPI enters/exits sync dependencies on
    # different threadpool threads; each request still gets its own connection.
    con = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# Columns added after first release; applied to pre-existing databases.
MIGRATIONS = (
    "ALTER TABLE shifts ADD COLUMN event_id INTEGER",
    "ALTER TABLE trucks ADD COLUMN driver_user_id INTEGER",
    "ALTER TABLE routes ADD COLUMN total_min REAL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN tax_cents INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN shipping_cents INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN total_cents INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT 'unpaid'",
    "ALTER TABLE orders ADD COLUMN payment_ref TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN ship_name TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN address TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN city TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN postal TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN phone TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN fulfilled_store_id INTEGER",
    "ALTER TABLE products ADD COLUMN image INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN job TEXT DEFAULT 'general'",
    "ALTER TABLE users ADD COLUMN employment TEXT DEFAULT 'employee'",
    "ALTER TABLE orders ADD COLUMN discount_cents INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN discount_code TEXT DEFAULT ''",
    "ALTER TABLE order_items ADD COLUMN variant_id INTEGER",
    "ALTER TABLE order_items ADD COLUMN variant_name TEXT DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN gift_cents INTEGER DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN gift_card_code TEXT DEFAULT ''",
)


def init() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        con.commit()
    finally:
        con.close()


def now() -> float:
    return time.time()
