"""Double-entry bookkeeping: the books, as opposed to a view of the money.

The install already knew what it had earned and spent — orders carry
totals, expenses carry amounts, and `/api/analytics/pnl` adds them up.
That answers "how are we doing". It does not answer "what do we file",
and the difference is not presentation. A report derived from operational
tables has no opening balance, cannot be closed, cannot be corrected
without changing history, and has nowhere to put the things that are
neither a sale nor an expense: a loan, an owner's contribution, a
depreciation charge, money owed to a member of staff who paid for the
paper themselves.

So this is a ledger. Accounts with a type, journals with balanced lines,
and a trial balance that must come to zero or something is wrong and says
so.

**Posting is derived, once, and idempotent.** Rather than editing every
place that takes money to also write a journal, `sync()` walks the
business events that have no entry yet and posts them, keyed on
(source, source_id). That choice is worth stating because the obvious
alternative — posting inline at each call site — fails in the way books
must never fail: a payment succeeds, the posting throws, and the ledger
is quietly short one entry that nobody will find until a year end. Here a
failure to post leaves the event unposted and VISIBLE, and running sync
again is safe.

**Nothing here is filed with anybody.** It is a set of books, not an
accountant, and it does not know your jurisdiction's rules. The tax
figure it carries is the one the shop recorded at the till.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS accounts (
  code TEXT PRIMARY KEY,                   -- 4 digits, grouped by type
  name TEXT NOT NULL,
  kind TEXT NOT NULL,                      -- asset|liability|equity|income|expense
  parent TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  system INTEGER DEFAULT 0,                -- seeded; posting rules refer to it
  note TEXT DEFAULT ''
);

/* One journal, many lines, and the lines must balance. The header keeps
   what it was FOR, so a line in the trial balance can be walked back to
   the order or the expense that caused it — a ledger you cannot walk
   back from is a ledger nobody trusts on the day it disagrees. */
CREATE TABLE IF NOT EXISTS journals (
  id INTEGER PRIMARY KEY,
  ref TEXT DEFAULT '',
  memo TEXT DEFAULT '',
  at REAL NOT NULL,                        -- the date it BELONGS to
  source TEXT DEFAULT 'manual',            -- manual|order|expense|opening|depreciation
  source_id TEXT DEFAULT '',
  reversed_by INTEGER DEFAULT 0,           -- corrections reverse, never edit
  reverses INTEGER DEFAULT 0,
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS journals_at ON journals(at);

CREATE TABLE IF NOT EXISTS journal_lines (
  id INTEGER PRIMARY KEY,
  journal_id INTEGER NOT NULL,
  account TEXT NOT NULL,
  debit_cents INTEGER DEFAULT 0,
  credit_cents INTEGER DEFAULT 0,
  memo TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS journal_lines_j ON journal_lines(journal_id);
CREATE INDEX IF NOT EXISTS journal_lines_a ON journal_lines(account);

/* A year, and whether it is shut. Closing stamps a date; posting before
   it is refused. Without this a ledger is a pile of rows that anyone can
   still change after the return has gone in. */
CREATE TABLE IF NOT EXISTS book_periods (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  closed_at REAL DEFAULT 0,
  closed_by TEXT DEFAULT ''
);
"""

KINDS = ("asset", "liability", "equity", "income", "expense")
# Debit increases an asset or an expense; credit increases the rest. This
# one line is the whole of the arithmetic and everything else follows.
DEBIT_POSITIVE = ("asset", "expense")

# A small chart, in the shape a small business actually uses. Seeded
# rather than demanded of the operator: an empty chart of accounts is a
# screen nobody can start from.
CHART = [
    ("1000", "Cash", "asset", 1),
    ("1010", "Bank", "asset", 1),
    ("1200", "Money owed to us", "asset", 1),
    ("1300", "Stock on hand", "asset", 1),
    ("1500", "Equipment", "asset", 1),
    ("1510", "Equipment depreciation", "asset", 1),
    ("2000", "Money we owe", "liability", 1),
    ("2100", "Sales tax owed", "liability", 1),
    ("2200", "Owed to staff", "liability", 1),
    ("2210", "Payroll deductions owed", "liability", 1),
    ("3000", "Owner's capital", "equity", 1),
    ("3100", "Retained earnings", "equity", 1),
    ("4000", "Sales", "income", 1),
    ("4100", "Donations", "income", 1),
    ("4200", "Course fees", "income", 1),
    ("4500", "Discounts given", "income", 1),
    ("4900", "Other income", "income", 1),
    ("5000", "Cost of goods sold", "expense", 1),
    ("6000", "Operating expenses", "expense", 1),
    ("6100", "Wages and salaries", "expense", 1),
    ("6900", "Depreciation", "expense", 1),
]
# Where an expense category lands. Anything unmapped goes to 6000, which
# is correct rather than lazy: a category the bookkeeper has not placed
# is still a business cost, and burying it would lose it.
CATEGORY_ACCOUNT = {
    "equipment": "1500", "advertising": "6000", "marketing": "6000",
}


def init_tables(con):
    con.executescript(TABLES)
    have = {r["code"] for r in con.execute("SELECT code FROM accounts")}
    for code, name, kind, system in CHART:
        if code not in have:
            con.execute(
                "INSERT INTO accounts(code,name,kind,system) VALUES(?,?,?,?)",
                (code, name, kind, system))
    con.commit()


def _office(user) -> bool:
    """The books are the office's, and the grid's finance area is exactly
    what that phrase means."""
    return auth.office(user, "settings", "finance")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the books are the office's")


# ---------- posting ----------

def _closed_before(con, at: float):
    r = con.execute("SELECT label, ends FROM book_periods WHERE closed_at>0"
                    " AND ends>=? ORDER BY ends LIMIT 1", (at,)).fetchone()
    return r


def post(con, *, at: float, lines: list, memo: str = "", ref: str = "",
         source: str = "manual", source_id: str = "", by: str = "") -> int:
    """One balanced journal. Lines are {account, debit_cents, credit_cents}.

    Refuses anything that does not balance, and anything dated into a
    period somebody has closed. Both refusals are the point of a ledger:
    the first is what makes the trial balance mean something, the second
    is what stops last year changing after it was filed.
    """
    clean = []
    dr = cr = 0
    for ln in lines:
        acct = str(ln.get("account", "")).strip()
        d = int(ln.get("debit_cents") or 0)
        c = int(ln.get("credit_cents") or 0)
        if d < 0 or c < 0:
            raise HTTPException(400, "a line is a debit or a credit, not a "
                                     "negative of the other")
        if d and c:
            raise HTTPException(400, f"line on {acct} is both a debit and a "
                                     "credit — split it into two")
        if not d and not c:
            continue
        if con.execute("SELECT 1 FROM accounts WHERE code=? AND active=1",
                       (acct,)).fetchone() is None:
            raise HTTPException(400, f"no account {acct!r}")
        dr += d
        cr += c
        clean.append((acct, d, c, str(ln.get("memo", ""))[:200]))
    if not clean:
        raise HTTPException(400, "a journal needs lines")
    if dr != cr:
        raise HTTPException(
            400, f"this does not balance: debits {dr / 100:.2f}, credits "
                 f"{cr / 100:.2f}. A journal that does not balance is the "
                 "one thing a ledger cannot hold.")
    shut = _closed_before(con, at)
    if shut is not None:
        raise HTTPException(
            400, f"{shut['label']} is closed — post the correction into an "
                 "open period instead of changing a filed one")
    cur = con.execute(
        "INSERT INTO journals(ref,memo,at,source,source_id,by_name,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (ref[:60], memo[:400], at, source, str(source_id), by[:120], db.now()))
    jid = cur.lastrowid
    for acct, d, c, m in clean:
        con.execute(
            "INSERT INTO journal_lines(journal_id,account,debit_cents,"
            " credit_cents,memo) VALUES(?,?,?,?,?)", (jid, acct, d, c, m))
    con.commit()
    return jid


def reverse(con, jid: int, by: str, memo: str = "") -> int:
    """A correction is a new journal that undoes the old one, never an
    edit. An edited journal is a history that changed after somebody
    relied on it."""
    j = con.execute("SELECT * FROM journals WHERE id=?", (jid,)).fetchone()
    if j is None:
        raise HTTPException(404, "no such journal")
    if j["reversed_by"]:
        raise HTTPException(400, "that one has already been reversed")
    lines = [{"account": r["account"], "debit_cents": r["credit_cents"],
              "credit_cents": r["debit_cents"], "memo": r["memo"]}
             for r in con.execute("SELECT * FROM journal_lines WHERE"
                                  " journal_id=?", (jid,)).fetchall()]
    new = post(con, at=time.time(), lines=lines,
               memo=memo or f"Reverses #{jid}: {j['memo']}",
               ref=j["ref"], source="manual",
               source_id=f"reverse:{jid}", by=by)
    con.execute("UPDATE journals SET reversed_by=? WHERE id=?", (new, jid))
    con.execute("UPDATE journals SET reverses=? WHERE id=?", (jid, new))
    con.commit()
    return new


def _posted(con, source: str) -> set:
    return {r["source_id"] for r in con.execute(
        "SELECT source_id FROM journals WHERE source=?", (source,)).fetchall()}


def sync(con, cfg=None) -> dict:
    """Post every business event that has no entry yet.

    Idempotent by construction: (source, source_id) is unique, so running
    this twice posts nothing twice, and running it after a failure picks
    up exactly what was missed.
    """
    made, skipped = 0, []

    # --- paid orders: money in, split between the sale and the tax ---
    done = _posted(con, "order")
    for o in con.execute(
            "SELECT * FROM orders WHERE payment_status IN ('paid','cod')"
            " ORDER BY id").fetchall():
        if str(o["id"]) in done:
            continue
        net = int(o["subtotal_cents"] or 0) + int(o["shipping_cents"] or 0)
        tax = int(o["tax_cents"] or 0)
        gift = int(o["donation_cents"] or 0)
        # A discount is not a smaller sale. It is the full sale and an
        # amount given away, and the two are different questions: "what
        # do we charge" and "what is the discounting costing us". Posted
        # as a debit against an income account, so it reduces revenue
        # where it should while staying visible as its own line.
        disc = int((o["discount_cents"] if "discount_cents" in o.keys()
                    else 0) or 0)
        total = int(o["total_cents"] or 0) or (net + tax + gift - disc)
        lines = [{"account": "1010", "debit_cents": total,
                  "memo": f"order #{o['id']}"}]
        if disc:
            lines.append({"account": "4500", "debit_cents": disc,
                          "memo": (o["discount_code"] or "discount")
                          if "discount_code" in o.keys() else "discount"})
        if net:
            lines.append({"account": "4000", "credit_cents": net})
        if tax:
            lines.append({"account": "2100", "credit_cents": tax})
        if gift:
            lines.append({"account": "4100", "credit_cents": gift})
        # Whatever is still unaccounted for after that. It should be
        # zero; when it is not, it lands somewhere named rather than
        # refusing the run and stranding every later order behind it.
        drift = total + disc - (net + tax + gift)
        if drift:
            lines.append({"account": "4900",
                          "credit_cents": drift} if drift > 0
                         else {"account": "4900", "debit_cents": -drift})
        try:
            post(con, at=o["created_at"], lines=lines, source="order",
                 source_id=str(o["id"]), ref=f"ORD-{o['id']}",
                 memo=f"Order #{o['id']}", by="posted automatically")
            made += 1
        except HTTPException as e:
            skipped.append({"what": f"order #{o['id']}", "why": str(e.detail)})

    # --- approved expenses: a cost, and who is owed for it ---
    done = _posted(con, "expense")
    for e in con.execute(
            "SELECT * FROM expenses WHERE state IN ('approved','paid')"
            " ORDER BY id").fetchall():
        if str(e["id"]) in done:
            continue
        amount = int(e["amount_cents"] or 0)
        tax = int(e["tax_cents"] or 0)
        cap = bool(e["capitalised"])
        acct = "1500" if cap else CATEGORY_ACCOUNT.get(e["category"], "6000")
        # Reclaimable tax is an asset, not a cost — but only where the
        # business reclaims it, which is a setting rather than a fact.
        net = amount - tax if tax else amount
        lines = [{"account": acct, "debit_cents": net,
                  "memo": f"{e['category']} — {e['vendor'] or 'expense'}"}]
        if tax:
            lines.append({"account": "1200", "debit_cents": tax,
                          "memo": "tax to reclaim"})
        lines.append({"account": "2200" if e["paid_by"] == "me" else "1010",
                      "credit_cents": amount})
        try:
            post(con, at=e["spent_at"], lines=lines, source="expense",
                 source_id=str(e["id"]), ref=f"EXP-{e['id']}",
                 memo=f"{e['category']} — {e['vendor'] or ''}".strip(" —"),
                 by="posted automatically")
            made += 1
        except HTTPException as ex:
            skipped.append({"what": f"expense #{e['id']}",
                            "why": str(ex.detail)})
    return {"posted": made, "skipped": skipped}


def unposted(con) -> dict:
    """What the books do not yet know about. A number that should be zero
    and is worth showing when it is not."""
    o = con.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE payment_status IN"
        " ('paid','cod') AND CAST(id AS TEXT) NOT IN"
        " (SELECT source_id FROM journals WHERE source='order')").fetchone()
    e = con.execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE state IN ('approved','paid')"
        " AND CAST(id AS TEXT) NOT IN"
        " (SELECT source_id FROM journals WHERE source='expense')").fetchone()
    return {"orders": o["n"], "expenses": e["n"]}


# ---------- reading the books ----------

def balances(con, upto: float | None = None, since: float | None = None) -> list:
    """Every account with its movement and its sign. `since` bounds a
    period for the income statement; the balance sheet wants everything
    up to a date instead."""
    where, args = [], []
    if upto is not None:
        where.append("j.at <= ?")
        args.append(upto)
    if since is not None:
        where.append("j.at >= ?")
        args.append(since)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = con.execute(
        "SELECT a.code, a.name, a.kind,"
        " COALESCE(SUM(l.debit_cents),0) AS dr,"
        " COALESCE(SUM(l.credit_cents),0) AS cr"
        " FROM accounts a LEFT JOIN journal_lines l ON l.account=a.code"
        " LEFT JOIN journals j ON j.id=l.journal_id" + clause +
        " GROUP BY a.code, a.name, a.kind ORDER BY a.code", args).fetchall()
    out = []
    for r in rows:
        dr, cr = int(r["dr"] or 0), int(r["cr"] or 0)
        sign = 1 if r["kind"] in DEBIT_POSITIVE else -1
        out.append({"code": r["code"], "name": r["name"], "kind": r["kind"],
                    "debit_cents": dr, "credit_cents": cr,
                    "balance_cents": (dr - cr) * sign})
    return out


def trial_balance(con, upto: float | None = None) -> dict:
    rows = [b for b in balances(con, upto=upto)
            if b["debit_cents"] or b["credit_cents"]]
    dr = sum(b["debit_cents"] for b in rows)
    cr = sum(b["credit_cents"] for b in rows)
    return {"rows": rows, "debits_cents": dr, "credits_cents": cr,
            "balanced": dr == cr, "out_by_cents": dr - cr}


def statements(con, since: float, upto: float) -> dict:
    """The income statement for a period, and the balance sheet at its
    end. Both from the ledger, so they agree with each other by
    construction rather than by coincidence."""
    period = balances(con, since=since, upto=upto)
    upto_all = balances(con, upto=upto)
    income = [b for b in period if b["kind"] == "income" and b["balance_cents"]]
    costs = [b for b in period if b["kind"] == "expense" and b["balance_cents"]]
    rev = sum(b["balance_cents"] for b in income)
    exp = sum(b["balance_cents"] for b in costs)
    assets = [b for b in upto_all if b["kind"] == "asset" and b["balance_cents"]]
    liabs = [b for b in upto_all if b["kind"] == "liability" and b["balance_cents"]]
    eq = [b for b in upto_all if b["kind"] == "equity" and b["balance_cents"]]
    a = sum(b["balance_cents"] for b in assets)
    li = sum(b["balance_cents"] for b in liabs)
    e = sum(b["balance_cents"] for b in eq)
    # Profit for the period has not been moved to retained earnings, so it
    # is named separately rather than left as an unexplained gap.
    earned = sum(b["balance_cents"] for b in upto_all
                 if b["kind"] == "income") - sum(
                     b["balance_cents"] for b in upto_all
                     if b["kind"] == "expense")
    return {
        "income": income, "costs": costs,
        "revenue_cents": rev, "expenses_cents": exp, "profit_cents": rev - exp,
        "assets": assets, "liabilities": liabs, "equity": eq,
        "assets_cents": a, "liabilities_cents": li, "equity_cents": e,
        "earnings_cents": earned,
        "sheet_balanced": a == li + e + earned,
        "sheet_out_by_cents": a - (li + e + earned),
        "since": since, "upto": upto,
    }


def year_bounds(cfg) -> tuple:
    from . import expenses as EX
    return EX.year_bounds(cfg, EX.current_year(cfg))


# ---------- routes ----------

router = APIRouter()

from .main import CFG, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/accounting")
def accounting_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    a, b = year_bounds(CFG)
    tb = trial_balance(con)
    st = statements(con, a, b)
    return {
        "accounts": [dict(r) for r in con.execute(
            "SELECT * FROM accounts ORDER BY code").fetchall()],
        "trial_balance": tb, "statements": st, "unposted": unposted(con),
        "periods": [dict(r) for r in con.execute(
            "SELECT * FROM book_periods ORDER BY starts DESC").fetchall()],
        "journals": [dict(r) for r in con.execute(
            "SELECT j.*, COALESCE(SUM(l.debit_cents),0) AS total_cents"
            " FROM journals j LEFT JOIN journal_lines l ON l.journal_id=j.id"
            " GROUP BY j.id ORDER BY j.at DESC, j.id DESC LIMIT 100").fetchall()],
        "kinds": list(KINDS), "year": {"from": a, "to": b},
    }


@router.get("/api/accounting/journals/{jid}")
def journal_detail(jid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    j = con.execute("SELECT * FROM journals WHERE id=?", (jid,)).fetchone()
    if j is None:
        raise HTTPException(404, "no such journal")
    return {**dict(j), "lines": [dict(r) for r in con.execute(
        "SELECT l.*, a.name AS account_name FROM journal_lines l"
        " JOIN accounts a ON a.code=l.account WHERE l.journal_id=?"
        " ORDER BY l.id", (jid,)).fetchall()]}


@router.get("/api/accounting/ledger/{code}")
def ledger(code: str, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    acct = con.execute("SELECT * FROM accounts WHERE code=?", (code,)).fetchone()
    if acct is None:
        raise HTTPException(404, "no such account")
    rows = [dict(r) for r in con.execute(
        "SELECT j.id, j.at, j.memo, j.ref, l.debit_cents, l.credit_cents,"
        " l.memo AS line_memo FROM journal_lines l"
        " JOIN journals j ON j.id=l.journal_id WHERE l.account=?"
        " ORDER BY j.at, j.id", (code,)).fetchall()]
    sign = 1 if acct["kind"] in DEBIT_POSITIVE else -1
    running = 0
    for r in rows:
        running += (r["debit_cents"] - r["credit_cents"]) * sign
        r["running_cents"] = running
    return {"account": dict(acct), "rows": rows, "balance_cents": running}


class LineBody(BaseModel):
    account: str
    debit_cents: int = 0
    credit_cents: int = 0
    memo: str = ""


class JournalBody(BaseModel):
    at: float | None = None
    memo: str = ""
    ref: str = ""
    lines: list[LineBody]


@router.post("/api/accounting/journals")
def journal_add(body: JournalBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    jid = post(con, at=body.at or time.time(),
               lines=[ln.model_dump() for ln in body.lines],
               memo=body.memo, ref=body.ref, source="manual",
               source_id=f"m{int(time.time() * 1000)}", by=user["name"])
    return {"ok": True, "id": jid}


class ReverseBody(BaseModel):
    memo: str = ""


@router.post("/api/accounting/journals/{jid}/reverse")
def journal_reverse(jid: int, body: ReverseBody, user=Depends(current_user),
                    con=Depends(get_con)):
    _require(user)
    return {"ok": True, "id": reverse(con, jid, user["name"], body.memo)}


class AccountBody(BaseModel):
    code: str
    name: str
    kind: str
    note: str = ""


@router.post("/api/accounting/accounts")
def account_add(body: AccountBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    code = body.code.strip()
    if not code.isdigit() or len(code) != 4:
        raise HTTPException(400, "an account code is four digits")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    if con.execute("SELECT 1 FROM accounts WHERE code=?", (code,)).fetchone():
        raise HTTPException(409, f"{code} already exists")
    con.execute("INSERT INTO accounts(code,name,kind,note) VALUES(?,?,?,?)",
                (code, body.name.strip()[:120], body.kind,
                 body.note.strip()[:200]))
    con.commit()
    return {"ok": True}


@router.post("/api/accounting/sync")
def accounting_sync(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return sync(con, CFG)


class PeriodBody(BaseModel):
    label: str
    starts: float
    ends: float


@router.post("/api/accounting/periods")
def period_add(body: PeriodBody, user=Depends(current_user),
               con=Depends(get_con)):
    _require(user)
    if body.ends <= body.starts:
        raise HTTPException(400, "a period ends after it starts")
    cur = con.execute(
        "INSERT INTO book_periods(label,starts,ends) VALUES(?,?,?)",
        (body.label.strip()[:60], body.starts, body.ends))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.post("/api/accounting/periods/{pid}/close")
def period_close(pid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    p = con.execute("SELECT * FROM book_periods WHERE id=?", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such period")
    if p["closed_at"]:
        raise HTTPException(400, "already closed")
    tb = trial_balance(con, upto=p["ends"])
    if not tb["balanced"]:
        raise HTTPException(
            400, f"the trial balance is out by {tb['out_by_cents'] / 100:.2f} "
                 "— a period that does not balance must not be closed")
    con.execute("UPDATE book_periods SET closed_at=?, closed_by=? WHERE id=?",
                (time.time(), user["name"], pid))
    con.commit()
    return {"ok": True}
