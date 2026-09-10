"""Treasury: where the money actually is, and how long it lasts.

The ledger says the business holds a certain amount of cash. It does not
say that the amount is spread over three bank accounts, one of which is
a deposit that takes a week to reach, or that the card float is nearly
spent, or that at the current rate of burn the whole lot runs out in
March. Those are the treasury questions, and a business answers them on
a Sunday night with a calculator because no screen holds them together.

So: the accounts money sits in, what is in each, transfers between them,
what is set aside and must not be spent, anything held as an investment,
and the runway that falls out of all of it.

**Runway is the number to be careful with.** It is arithmetic on the
past — cash divided by the average net burn over a window — and it is
wrong the moment anything changes. It is offered because a rough number
somebody sanity-checks beats no number at all, and it is labelled as a
projection everywhere it appears. It does not know about the invoice you
are about to send.

Balances are held here rather than derived from the ledger on purpose.
A bank account has a balance whether or not the books are up to date,
and a treasury screen that goes blank because nobody posted last week's
expenses is a treasury screen nobody opens. Where a cash account names a
ledger account, the difference between the two is shown, which is the
beginning of a reconciliation.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS cash_accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'bank',                -- bank|savings|card|cash|merchant|other
  currency TEXT DEFAULT 'USD',
  reference TEXT DEFAULT '',               -- last four, or the sort code
  ledger_account TEXT DEFAULT '',          -- the code in the chart, when linked
  balance_cents INTEGER DEFAULT 0,         -- as last stated
  as_of REAL DEFAULT 0,
  reserved_cents INTEGER DEFAULT 0,        -- set aside: tax, deposits, payroll
  reserved_for TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);

/* Every change to a stated balance, and why. A balance that can be
   overwritten with no trail is a number nobody can argue with, which
   sounds like a virtue and is the opposite. */
CREATE TABLE IF NOT EXISTS cash_movements (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL,
  kind TEXT NOT NULL,                      -- statement|transfer_in|transfer_out|adjustment
  amount_cents INTEGER NOT NULL,           -- signed: what it did to the balance
  balance_after_cents INTEGER DEFAULT 0,
  other_account_id INTEGER DEFAULT 0,      -- the far side of a transfer
  memo TEXT DEFAULT '',
  at REAL NOT NULL,
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS cash_movements_acct ON cash_movements(account_id, at);

CREATE TABLE IF NOT EXISTS holdings (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'fund',                -- fund|share|bond|property|crypto|other
  units REAL DEFAULT 0,
  cost_cents INTEGER DEFAULT 0,            -- what was paid, in total
  value_cents INTEGER DEFAULT 0,           -- what it is worth, as last marked
  valued_at REAL DEFAULT 0,
  account_id INTEGER DEFAULT 0,            -- where it is held
  note TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
"""

KINDS = ("bank", "savings", "card", "cash", "merchant", "other")
HOLDING_KINDS = ("fund", "share", "bond", "property", "crypto", "other")
BURN_DAYS = 90


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings", "finance")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the money is the office's")


def _movement(con, acct_id: int, kind: str, delta: int, memo: str, at: float,
              by: str, other: int = 0) -> None:
    row = con.execute("SELECT balance_cents FROM cash_accounts WHERE id=?",
                      (acct_id,)).fetchone()
    after = int(row["balance_cents"] or 0)
    con.execute(
        "INSERT INTO cash_movements(account_id,kind,amount_cents,"
        " balance_after_cents,other_account_id,memo,at,by_name,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (acct_id, kind, delta, after, other, memo[:200], at, by[:120], db.now()))


def burn(con, days: int = BURN_DAYS) -> dict:
    """Average money in and out per day, from the daybook if it has the
    window and from the orders and expenses tables if it does not."""
    since = time.time() - days * 86400
    inc = con.execute(
        "SELECT COALESCE(SUM(total_cents),0) AS c FROM orders"
        " WHERE payment_status IN ('paid','cod') AND created_at>=?",
        (since,)).fetchone()["c"]
    out = con.execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS c FROM expenses"
        " WHERE state IN ('approved','paid') AND spent_at>=?",
        (since,)).fetchone()["c"]
    net = int(inc) - int(out)
    return {"days": days, "in_cents": int(inc), "out_cents": int(out),
            "net_cents": net, "per_day_cents": net // days if days else 0}


def summary(con) -> dict:
    accts = [dict(r) for r in con.execute(
        "SELECT * FROM cash_accounts WHERE active=1 ORDER BY kind, name"
        ).fetchall()]
    total = sum(a["balance_cents"] for a in accts)
    reserved = sum(a["reserved_cents"] for a in accts)
    b = burn(con)
    # Runway is measured on money that is actually free: reserved cash is
    # somebody else's, it is simply still in your account.
    free = total - reserved
    per_day = b["per_day_cents"]
    days = None
    if per_day < 0:
        days = max(0, free // -per_day)
    holds = [dict(r) for r in con.execute(
        "SELECT h.*, c.name AS account_name FROM holdings h"
        " LEFT JOIN cash_accounts c ON c.id=h.account_id"
        " WHERE h.active=1 ORDER BY h.name").fetchall()]
    for h in holds:
        h["gain_cents"] = h["value_cents"] - h["cost_cents"]
    return {
        "accounts": accts, "total_cents": total, "reserved_cents": reserved,
        "free_cents": free, "burn": b,
        "runway_days": days,
        "runway_note": ("Cash that is free, divided by the average daily "
                        "net over the last quarter. Arithmetic on the past: "
                        "it does not know what you are about to invoice or "
                        "buy."),
        "holdings": holds,
        "holdings_cost_cents": sum(h["cost_cents"] for h in holds),
        "holdings_value_cents": sum(h["value_cents"] for h in holds),
    }


def reconcile(con) -> list:
    """Where a cash account names a ledger account, what the two say.

    A difference is not automatically an error — the books may simply be
    behind — so this reports rather than corrects."""
    out = []
    for a in con.execute("SELECT * FROM cash_accounts WHERE active=1 AND"
                         " ledger_account<>''").fetchall():
        r = con.execute(
            "SELECT COALESCE(SUM(l.debit_cents),0) - COALESCE(SUM(l.credit_cents),0)"
            " AS c FROM journal_lines l WHERE l.account=?",
            (a["ledger_account"],)).fetchone()
        ledger = int(r["c"] or 0)
        out.append({"id": a["id"], "name": a["name"],
                    "ledger_account": a["ledger_account"],
                    "stated_cents": a["balance_cents"],
                    "ledger_cents": ledger,
                    "difference_cents": a["balance_cents"] - ledger})
    return out


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/treasury")
def treasury_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    d = summary(con)
    d["reconciliation"] = reconcile(con)
    d["kinds"] = list(KINDS)
    d["holding_kinds"] = list(HOLDING_KINDS)
    d["movements"] = [dict(r) for r in con.execute(
        "SELECT m.*, c.name AS account_name FROM cash_movements m"
        " JOIN cash_accounts c ON c.id=m.account_id"
        " ORDER BY m.at DESC, m.id DESC LIMIT 60").fetchall()]
    return d


class AccountBody(BaseModel):
    id: int = 0
    name: str
    kind: str = "bank"
    currency: str = "USD"
    reference: str = ""
    ledger_account: str = ""
    balance_cents: int = 0
    reserved_cents: int = 0
    reserved_for: str = ""
    note: str = ""


@router.post("/api/treasury/accounts")
def account_save(body: AccountBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    if not body.name.strip():
        raise HTTPException(400, "an account needs a name")
    if body.reserved_cents < 0:
        raise HTTPException(400, "you cannot set aside a negative amount")
    if body.ledger_account and con.execute(
            "SELECT 1 FROM accounts WHERE code=?",
            (body.ledger_account,)).fetchone() is None:
        raise HTTPException(400, f"no ledger account {body.ledger_account!r}")
    now = time.time()
    if body.id:
        old = con.execute("SELECT * FROM cash_accounts WHERE id=?",
                          (body.id,)).fetchone()
        if old is None:
            raise HTTPException(404, "no such account")
        con.execute(
            "UPDATE cash_accounts SET name=?, kind=?, currency=?, reference=?,"
            " ledger_account=?, balance_cents=?, as_of=?, reserved_cents=?,"
            " reserved_for=?, note=? WHERE id=?",
            (body.name.strip()[:120], body.kind, body.currency[:3].upper(),
             body.reference.strip()[:60], body.ledger_account,
             body.balance_cents, now, body.reserved_cents,
             body.reserved_for.strip()[:120], body.note.strip()[:400], body.id))
        if body.balance_cents != old["balance_cents"]:
            _movement(con, body.id, "statement",
                      body.balance_cents - old["balance_cents"],
                      "balance restated", now, user["name"])
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO cash_accounts(name,kind,currency,reference,ledger_account,"
        " balance_cents,as_of,reserved_cents,reserved_for,note,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (body.name.strip()[:120], body.kind, body.currency[:3].upper(),
         body.reference.strip()[:60], body.ledger_account, body.balance_cents,
         now, body.reserved_cents, body.reserved_for.strip()[:120],
         body.note.strip()[:400], db.now()))
    con.commit()
    if body.balance_cents:
        _movement(con, cur.lastrowid, "statement", body.balance_cents,
                  "opening balance", now, user["name"])
        con.commit()
    return {"ok": True, "id": cur.lastrowid}


class TransferBody(BaseModel):
    from_id: int
    to_id: int
    amount_cents: int
    memo: str = ""
    at: float | None = None


@router.post("/api/treasury/transfer")
def transfer(body: TransferBody, user=Depends(current_user),
             con=Depends(get_con)):
    """Money between two of your own accounts. Not income and not a cost,
    which is exactly why it needs its own verb: recorded as either, it
    inflates both sides of a year that never earned it."""
    _require(user)
    if body.from_id == body.to_id:
        raise HTTPException(400, "those are the same account")
    if body.amount_cents <= 0:
        raise HTTPException(400, "an amount to move")
    a = con.execute("SELECT * FROM cash_accounts WHERE id=?",
                    (body.from_id,)).fetchone()
    b = con.execute("SELECT * FROM cash_accounts WHERE id=?",
                    (body.to_id,)).fetchone()
    if a is None or b is None:
        raise HTTPException(404, "no such account")
    if a["currency"] != b["currency"]:
        raise HTTPException(400, "those accounts are in different currencies "
                                 "— record the exchange as two adjustments, "
                                 "because a rate this screen invented would "
                                 "be wrong")
    at = body.at or time.time()
    con.execute("UPDATE cash_accounts SET balance_cents=balance_cents-?,"
                " as_of=? WHERE id=?", (body.amount_cents, at, body.from_id))
    con.execute("UPDATE cash_accounts SET balance_cents=balance_cents+?,"
                " as_of=? WHERE id=?", (body.amount_cents, at, body.to_id))
    memo = body.memo or f"{a['name']} to {b['name']}"
    _movement(con, body.from_id, "transfer_out", -body.amount_cents, memo, at,
              user["name"], body.to_id)
    _movement(con, body.to_id, "transfer_in", body.amount_cents, memo, at,
              user["name"], body.from_id)
    con.commit()
    return {"ok": True}


class HoldingBody(BaseModel):
    id: int = 0
    name: str
    kind: str = "fund"
    units: float = 0
    cost_cents: int = 0
    value_cents: int = 0
    account_id: int = 0
    note: str = ""


@router.post("/api/treasury/holdings")
def holding_save(body: HoldingBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    if body.kind not in HOLDING_KINDS:
        raise HTTPException(400, f"kind is one of {HOLDING_KINDS}")
    if not body.name.strip():
        raise HTTPException(400, "a holding needs a name")
    now = time.time()
    if body.id:
        con.execute(
            "UPDATE holdings SET name=?, kind=?, units=?, cost_cents=?,"
            " value_cents=?, valued_at=?, account_id=?, note=? WHERE id=?",
            (body.name.strip()[:120], body.kind, body.units, body.cost_cents,
             body.value_cents, now, body.account_id, body.note.strip()[:400],
             body.id))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO holdings(name,kind,units,cost_cents,value_cents,valued_at,"
        " account_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (body.name.strip()[:120], body.kind, body.units, body.cost_cents,
         body.value_cents, now, body.account_id, body.note.strip()[:400],
         db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/treasury/holdings/{hid}")
def holding_close(hid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("UPDATE holdings SET active=0 WHERE id=?", (hid,))
    con.commit()
    return {"ok": True}
