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
  clock_token TEXT DEFAULT '',             -- badge QR; identifies, never logs in
  email_verified_at REAL DEFAULT 0,        -- proved they own the address
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

/* An invitation is authority in link form: the office mints it carrying a
   role, and whoever opens the link signs up straight into that role — or
   into a premade account the invite was bound to. Single-use, so a
   forwarded link is worth nothing once its person arrived. */
CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  name TEXT DEFAULT '',
  email TEXT DEFAULT '',
  person_id INTEGER,                       -- NULL = the sign-up creates one
  created_by INTEGER NOT NULL,
  created_at REAL NOT NULL,
  used_at REAL
);

/* A pay-on-delivery order waiting on its email confirmation.

   Deliberately not a row in `orders` with a different status: thirteen
   queries across analytics, the P&L and the supply forecast count anything
   that isn't 'cancelled', so an unconfirmed order stored there would show up
   as revenue the moment it was created. Keeping it outside means it cannot
   be counted by construction, rather than by remembering to exclude it in
   every one of those places. */
CREATE TABLE IF NOT EXISTS pending_orders (
  id INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  payload TEXT NOT NULL,                   -- the OrderBody, as JSON
  as_guest INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  placed_order_id INTEGER DEFAULT 0
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
    # Resolved per call, not at import: the path is the tenant. In legacy
    # single-tenant mode tenancy.db_path() is exactly the old DB_PATH.
    from . import tenancy
    con = sqlite3.connect(tenancy.db_path(), timeout=10,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# Columns added after first release; applied to pre-existing databases.
STOCK_LEDGER = """
/* How a shelf got to the number it says.

   Materials have had this since the beginning — every movement with a
   reason and an actor, so the running total and the record cannot
   disagree. Store stock did not: it was a bare integer that four
   different places overwrote, and "how did this store come to have two
   cases" had no answer at all. Worse, the column could not tell a count
   from an assumption, so a shelf topped up to par on somebody's say-so
   read exactly like a shelf somebody had walked and counted.

   Signed quantities, like the materials ledger, because a delivery and a
   sale are the same event with opposite signs and giving them separate
   columns means adding them up wrongly somewhere. */
CREATE TABLE IF NOT EXISTS inventory_moves (
  id INTEGER PRIMARY KEY,
  store_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  qty REAL NOT NULL,                       -- signed: + in, - out
  balance REAL NOT NULL DEFAULT 0,         -- what it read afterwards
  unit_cost_cents REAL DEFAULT 0,          -- what these units cost to make
  cost_cents INTEGER DEFAULT 0,            -- value moved, signed like qty
  unknown_qty REAL DEFAULT 0,              -- of it, what nobody ever priced
  reason TEXT NOT NULL,                    -- order:12, visit:4, par, count
  counted INTEGER DEFAULT 0,               -- 1 = somebody actually looked
  actor TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS inventory_moves_line
  ON inventory_moves(store_id, product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS inventory_moves_when
  ON inventory_moves(created_at DESC);

/* What each parcel of stock on a shelf cost, oldest first.

   Materials are averaged: litres of concentrate poured into the same
   tank are fungible, nobody tracks which drum went into which batch, and
   a business that pretended to would produce a precise number it could
   not check against a real drum.

   Finished goods are not that. A case has a date code, a shop sells the
   oldest first because that is what the code is for, and two cases of
   the same product made three months apart genuinely cost different
   amounts. So they are layers, consumed in the order they arrived, and a
   sale takes its cost from the parcel it actually shipped rather than
   from an average of everything that ever existed.

   The two methods differ because the two things differ. Using one method
   everywhere would be tidier and wrong in one of the two places. */
CREATE TABLE IF NOT EXISTS stock_layers (
  id INTEGER PRIMARY KEY,
  store_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  qty REAL NOT NULL,                       -- what is left of this parcel
  qty_in REAL NOT NULL,                    -- what it was when it arrived
  unit_cost_cents REAL DEFAULT 0,
  known INTEGER DEFAULT 1,                 -- 0 = it arrived before we asked
  source TEXT DEFAULT '',                  -- run:4, po:12, count, opening
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS stock_layers_line
  ON stock_layers(store_id, product_id, created_at);
"""

KIOSK_TABLE = """
/* A tablet by the door, registered once. For staff who clock in on it,
   the tablet IS the location — and a better one than a browser's guess,
   because it cannot be changed by a setting and it is bolted to a wall. */
CREATE TABLE IF NOT EXISTS kiosks (
  kiosk_id TEXT PRIMARY KEY,
  label TEXT DEFAULT '',
  store_id INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL,
  last_seen REAL DEFAULT 0
);
"""

def stock_move(con, store_id: int, product_id: int, delta: float,
               reason: str, actor: str = "", note: str = "",
               counted: bool = False,
               unit_cost_cents: float = 0.0) -> float:
    """The only way a store's stock changes.

    Writes the movement and applies it in one place, so the ledger and
    the running total cannot disagree — the same rule the materials
    ledger has always had, arriving late for the shelves.

    `counted` marks the movements where somebody actually looked. A
    stocktake and an assumed par-fill both land as a positive number, and
    a business that cannot tell them apart cannot tell which of its
    figures it is entitled to trust.
    """
    if not delta:
        return current_qty(con, store_id, product_id)
    con.execute(
        "INSERT INTO inventory(store_id,product_id,qty,updated_at)"
        " VALUES(?,?,0,?) ON CONFLICT(store_id,product_id) DO NOTHING",
        (store_id, product_id, now()))
    con.execute(
        "UPDATE inventory SET qty=MAX(0, qty + ?), updated_at=?"
        " WHERE store_id=? AND product_id=?",
        (delta, now(), store_id, product_id))
    after = current_qty(con, store_id, product_id)
    # The parcels. Stock arriving is a layer; stock leaving eats the
    # oldest layers first and takes their cost with it, which is the whole
    # point — a sale should be costed at what the units on that pallet
    # cost, not at an average of everything the product has ever cost.
    cost, unknown = _layer(con, store_id, product_id, delta,
                           float(unit_cost_cents or 0), reason, counted)
    con.execute(
        "INSERT INTO inventory_moves(store_id,product_id,qty,balance,"
        " unit_cost_cents,cost_cents,unknown_qty,reason,counted,actor,note,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (store_id, product_id, delta, after, float(unit_cost_cents or 0),
         cost, unknown, reason[:60], 1 if counted else 0, actor[:80],
         note[:200], now()))
    return after


def _layer(con, store_id: int, product_id: int, delta: float,
           unit_cost_cents: float, source: str, counted: bool):
    """Push a parcel on, or eat parcels off. Returns (cost, unknown qty).

    `unknown` is the part that came off stock nobody ever priced —
    inherited from before any of this existed, or added by a stocktake
    that found more than the paperwork said. It is reported rather than
    valued at zero: a cost of nothing flatters a margin exactly the way an
    assumed one does, and the whole reason for layers is to stop that.
    """
    if delta > 0:
        con.execute(
            "INSERT INTO stock_layers(store_id,product_id,qty,qty_in,"
            " unit_cost_cents,known,source,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (store_id, product_id, delta, delta, unit_cost_cents,
             1 if unit_cost_cents > 0 else 0, source[:40], now()))
        return int(round(delta * unit_cost_cents)), 0.0

    want = -delta
    cost, unknown = 0.0, 0.0
    for lay in con.execute(
            "SELECT * FROM stock_layers WHERE store_id=? AND product_id=?"
            " AND qty > 0 ORDER BY created_at, id", (store_id, product_id)):
        if want <= 1e-9:
            break
        take = min(want, float(lay["qty"]))
        con.execute("UPDATE stock_layers SET qty=qty-? WHERE id=?",
                    (take, lay["id"]))
        if lay["known"]:
            cost += take * float(lay["unit_cost_cents"] or 0)
        else:
            unknown += take
        want -= take
    # More went out than any parcel accounts for: stock that was on the
    # shelf before anybody was writing parcels down, or a count that was
    # wrong. Either way it left, and saying how much of it we cannot cost
    # is the honest answer.
    if want > 1e-9:
        unknown += want
    # Signed the same way the quantity is: value leaving is negative, the
    # way value arriving is positive. A ledger where one column is signed
    # and the one beside it is not is a ledger that gets summed wrongly
    # by whoever reads it next.
    return -int(round(cost)), round(unknown, 3)


def current_qty(con, store_id: int, product_id: int) -> float:
    r = con.execute("SELECT qty FROM inventory WHERE store_id=?"
                    " AND product_id=?", (store_id, product_id)).fetchone()
    return float(r["qty"]) if r else 0.0


def stock_set(con, store_id: int, product_id: int, qty: float, reason: str,
              actor: str = "", note: str = "", counted: bool = False) -> float:
    """Set a line to a number, recorded as the movement it implies.

    Somebody typing 18 into a stock box has not made 18 appear — they
    have moved it by the difference, and the difference is what a ledger
    can be read down. A screen that writes the absolute number leaves a
    hole exactly where the question gets asked.
    """
    delta = qty - current_qty(con, store_id, product_id)
    return stock_move(con, store_id, product_id, delta, reason, actor, note,
                      counted)


MIGRATIONS = (
    # Who an email actually went to. The log joined users for the address,
    # which is fine for a customer and useless for a client's point of
    # contact — they are not a user of this system and never will be.
    "ALTER TABLE email_log ADD COLUMN to_addr TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN email_verified_at REAL DEFAULT 0",
    "ALTER TABLE shifts ADD COLUMN event_id INTEGER",
    # Where a punch happened. Recorded on the shift rather than checked and
    # thrown away: "the fence said yes" is not evidence six weeks later
    # when somebody disputes an hour, and the coordinates are.
    "ALTER TABLE shifts ADD COLUMN in_lat REAL",
    "ALTER TABLE shifts ADD COLUMN in_lng REAL",
    "ALTER TABLE shifts ADD COLUMN in_accuracy_m REAL",
    "ALTER TABLE shifts ADD COLUMN in_kiosk TEXT DEFAULT ''",
    "ALTER TABLE shifts ADD COLUMN in_store_id INTEGER DEFAULT 0",
    # Who is bound to where. Empty means what it has always meant: punch
    # from wherever you are.
    "ALTER TABLE users ADD COLUMN clock_store_id INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN clock_kiosk_only INTEGER DEFAULT 0",
    "ALTER TABLE inventory_moves ADD COLUMN unit_cost_cents REAL DEFAULT 0",
    "ALTER TABLE inventory_moves ADD COLUMN cost_cents INTEGER DEFAULT 0",
    "ALTER TABLE inventory_moves ADD COLUMN unknown_qty REAL DEFAULT 0",
    # The number printed on the thing itself. Separate from the SKU: a SKU
    # is what WE call it and we chose it, a barcode is what the
    # manufacturer stamped on the tin and the scanner reads. For own-brand
    # goods they are often the same string, and for everything bought in
    # they are never the same string.
    "ALTER TABLE products ADD COLUMN barcode TEXT DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS products_barcode ON products(barcode)",
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
    # QR identity: an unguessable public identifier, separate from the row
    # id on purpose (the id leaks how many people exist and is guessable).
    "ALTER TABLE users ADD COLUMN uid TEXT",
    # Data rights: erasure tombstones the row instead of deleting it.
    "ALTER TABLE users ADD COLUMN erased_at REAL",
    # Role claims: what somebody asked to be at sign-up. The account works
    # as what it IS meanwhile; approval (roles.py rules) is the promotion.
    "ALTER TABLE users ADD COLUMN requested_role TEXT DEFAULT ''",
    # Sessions age: the token's last use, for the sliding expiry window.
    # 0 = never seen under this scheme; first use stamps it, so a deploy
    # never signs anybody out.
    "ALTER TABLE users ADD COLUMN token_seen_at REAL DEFAULT 0",
    # A person's photo: SELF-uploaded only (uploading is the consent), a
    # token-named path in the sharded media store, shared by their own
    # privacy_photo preference, gone with erasure.
    "ALTER TABLE users ADD COLUMN photo TEXT DEFAULT ''",
)


def init() -> None:
    from . import tenancy
    tenancy.data_dir().mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(SCHEMA)
        con.executescript(KIOSK_TABLE)
        con.executescript(STOCK_LEDGER)
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
