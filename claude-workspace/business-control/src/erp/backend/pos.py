"""The counter: cash, a drawer, and a receipt somebody can hold.

An online shop and a shop with a door are the same business and almost
none of the same software. What a till needs that a checkout does not:

  * **A drawer with a float in it.** Cash is the only tender that can go
    missing between the sale and the bank, so a session opens with a
    counted float, records every note that goes in and out, and closes
    against a second count. The difference is stated, never absorbed —
    a till that silently balances is a till nobody can trust.
  * **Tenders, plural.** One sale can be part cash, part card, and cash
    is given back. Recording a total and a payment method loses the
    change, which is the number the drawer is actually counted against.
  * **A receipt that outlives the paper.** Printed with a code on it, so
    the customer's phone can hold the same record we do — and emailed if
    they would rather. A receipt only the shop can find is a returns
    argument waiting to happen.

Sales are ordinary orders with kind 'pos'. Everything downstream — the
day book, the P&L, per-product margin, stock — already reads orders, and
a second sales table would have meant teaching all of it a second answer.
"""
import secrets
import time

from . import db

TENDERS = ("cash", "card", "account", "gift", "other")

TABLES = """
CREATE TABLE IF NOT EXISTS register_sessions (
  id INTEGER PRIMARY KEY,
  register TEXT NOT NULL DEFAULT 'counter',
  store_id INTEGER DEFAULT 0,
  user_id INTEGER NOT NULL,
  opened_at REAL NOT NULL,
  float_cents INTEGER DEFAULT 0,
  closed_at REAL DEFAULT 0,
  counted_cents INTEGER DEFAULT 0,        -- what was in the drawer at close
  expected_cents INTEGER DEFAULT 0,       -- float + cash in - change out
  variance_cents INTEGER DEFAULT 0,       -- counted - expected, signed
  closed_by INTEGER DEFAULT 0,
  note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS register_open
  ON register_sessions(closed_at, register);

/* One row per way the money arrived. Change is a negative cash tender
   rather than a field on the sale: the drawer is counted against the net
   of what went in and out of it, and a column called change_given is a
   number nobody adds up. */
CREATE TABLE IF NOT EXISTS order_tenders (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  session_id INTEGER DEFAULT 0,
  kind TEXT NOT NULL,
  cents INTEGER NOT NULL,
  ref TEXT DEFAULT '',
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tender_order ON order_tenders(order_id);
CREATE INDEX IF NOT EXISTS tender_session ON order_tenders(session_id);

/* The customer's copy. A token rather than the order id, because the
   order id is guessable and a receipt carries an address and a card's
   last four. */
CREATE TABLE IF NOT EXISTS receipts (
  order_id INTEGER PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  created_at REAL NOT NULL,
  emailed_to TEXT DEFAULT '',
  emailed_at REAL DEFAULT 0,
  printed_at REAL DEFAULT 0
);
"""


def init_tables(con):
    con.executescript(TABLES)


def open_session(con, user_id: int, register: str, float_cents: int,
                 store_id: int = 0) -> dict:
    live = con.execute(
        "SELECT id FROM register_sessions WHERE register=? AND closed_at=0",
        (register,)).fetchone()
    if live:
        raise ValueError(f"{register} is already open (session {live['id']})")
    cur = con.execute(
        "INSERT INTO register_sessions(register,store_id,user_id,opened_at,"
        " float_cents) VALUES(?,?,?,?,?)",
        (register[:40], store_id, user_id, db.now(), max(0, float_cents)))
    con.commit()
    return {"id": cur.lastrowid, "register": register,
            "float_cents": float_cents}


def session_of(con, register: str = "counter"):
    return con.execute(
        "SELECT * FROM register_sessions WHERE register=? AND closed_at=0"
        " ORDER BY id DESC LIMIT 1", (register,)).fetchone()


def drawer(con, sid: int) -> dict:
    """What the drawer should hold, and what the session has taken.

    Cash only for the expected figure — a card sale never touched the
    drawer, and counting it into the expectation is how a till reads
    hundreds of dollars short every evening and everybody learns to
    ignore the variance.
    """
    s = con.execute("SELECT * FROM register_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise ValueError("no such session")
    rows = con.execute(
        "SELECT kind, COALESCE(SUM(cents),0) AS cents, COUNT(*) AS n"
        " FROM order_tenders WHERE session_id=? GROUP BY kind", (sid,))
    by = {r["kind"]: {"cents": r["cents"], "n": r["n"]} for r in rows}
    cash = by.get("cash", {}).get("cents", 0)
    taken = sum(v["cents"] for v in by.values())
    sales = con.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total_cents),0) AS cents"
        " FROM orders WHERE id IN (SELECT DISTINCT order_id FROM"
        " order_tenders WHERE session_id=?)", (sid,)).fetchone()
    return {
        "session": dict(s), "by_tender": by,
        "cash_cents": cash,
        "expected_cents": s["float_cents"] + cash,
        "taken_cents": taken,
        "sales": sales["n"], "sales_cents": sales["cents"],
    }


def close_session(con, sid: int, counted_cents: int, by_user: int,
                  note: str = "") -> dict:
    d = drawer(con, sid)
    expected = d["expected_cents"]
    var = counted_cents - expected
    con.execute(
        "UPDATE register_sessions SET closed_at=?, counted_cents=?,"
        " expected_cents=?, variance_cents=?, closed_by=?, note=?"
        " WHERE id=? AND closed_at=0",
        (db.now(), counted_cents, expected, var, by_user, note[:200], sid))
    con.commit()
    return {"expected_cents": expected, "counted_cents": counted_cents,
            "variance_cents": var, "over": var > 0, "short": var < 0,
            **{k: d[k] for k in ("cash_cents", "taken_cents", "sales",
                                 "sales_cents")}}


def receipt_token(con, order_id: int) -> str:
    r = con.execute("SELECT token FROM receipts WHERE order_id=?",
                    (order_id,)).fetchone()
    if r:
        return r["token"]
    tok = secrets.token_urlsafe(16)
    con.execute("INSERT INTO receipts(order_id,token,created_at)"
                " VALUES(?,?,?)", (order_id, tok, db.now()))
    con.commit()
    return tok


def receipt(con, order_id: int) -> dict:
    o = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if o is None:
        raise ValueError("no such order")
    items = [dict(r) for r in con.execute(
        "SELECT oi.qty, oi.unit_price_cents, oi.variant_name,"
        " COALESCE(p.name,'item') AS name, COALESCE(p.sku,'') AS sku"
        " FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id"
        " WHERE oi.order_id=?", (order_id,))]
    tenders = [dict(r) for r in con.execute(
        "SELECT kind, cents, ref FROM order_tenders WHERE order_id=?"
        " ORDER BY id", (order_id,))]
    who = con.execute("SELECT name, email FROM users WHERE id=?",
                      (o["user_id"],)).fetchone()
    store = con.execute("SELECT name, city FROM stores WHERE id=?",
                        (o["store_id"] or 0,)).fetchone()
    # Change is a negative cash tender, so the paid figure is the sum and
    # the change line is read back out of it for the paper.
    change = -sum(t["cents"] for t in tenders if t["cents"] < 0)
    return {
        "order_id": order_id, "at": o["created_at"],
        "kind": o["kind"], "status": o["status"],
        "subtotal_cents": o["subtotal_cents"],
        "tax_cents": o["tax_cents"] or 0,
        "discount_cents": o["discount_cents"] or 0,
        "total_cents": o["total_cents"],
        "items": items, "tenders": tenders, "change_cents": change,
        "customer": dict(who) if who else None,
        "store": dict(store) if store else None,
        "token": receipt_token(con, order_id),
    }
