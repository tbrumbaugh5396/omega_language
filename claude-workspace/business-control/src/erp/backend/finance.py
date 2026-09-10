"""Finance: what is owed each way, what was planned, and what is coming.

Accounting records what happened. Treasury says where the money is right
now. Neither answers the three questions a business actually runs on:

  * **Who owes us, and who do we owe?** Both are sitting in tables
    already — an order on terms that has not been paid is a receivable, an
    approved expense nobody has reimbursed is a payable — and neither had
    a screen. A business that cannot list what it is owed chases nothing.

  * **Are we where we said we would be?** A budget is a line per account
    per period, and the only useful thing to do with one is put the actual
    beside it. Actuals come from the ledger, so budget and books cannot
    drift into two definitions of a cost.

  * **What does the next few weeks look like?** Opening cash, plus what is
    due in, minus what is due out. Arithmetic, and it is labelled as
    arithmetic.

**None of this is a second set of numbers.** Receivables and payables are
derived from the rows that already exist rather than copied into new
tables, so nothing can be paid here and still owed there. Only the budget
is stored, because a plan is the one number in this file that is not a
consequence of something else.

The forecast is the part to be careful with, and it says so on the
screen. Money due on a date is not money arriving on that date, a
recurring expense that has been cancelled still looks recurring until
somebody says so, and nothing here knows about the invoice you are about
to send.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,
  starts REAL NOT NULL,
  ends REAL NOT NULL,
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_lines (
  id INTEGER PRIMARY KEY,
  budget_id INTEGER NOT NULL,
  account TEXT NOT NULL,                   -- a code from the chart
  amount_cents INTEGER NOT NULL,           -- what was planned, for the period
  note TEXT DEFAULT '',
  UNIQUE(budget_id, account)
);
"""

FORECAST_WEEKS = 12
# An order on terms is a receivable; one taken at a till is money already
# in. The difference is the payment status, not the kind of customer.
OWING = ("on_terms", "unpaid")


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings", "finance")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the finances are the office's")


# ---------- what is owed, each way ----------

def receivables(con) -> dict:
    """Orders that have been placed and not paid for. Derived, never
    stored: an order marked paid stops being owed the moment it is
    marked, with nothing to keep in step."""
    rows = [dict(r) for r in con.execute(
        "SELECT o.id, o.total_cents, o.created_at, o.payment_status,"
        " o.kind, u.name AS who, u.email FROM orders o"
        " LEFT JOIN users u ON u.id=o.user_id"
        " WHERE o.payment_status IN ('on_terms','unpaid')"
        " AND o.status <> 'cancelled' ORDER BY o.created_at").fetchall()]
    now = time.time()
    buckets = {"current": 0, "30": 0, "60": 0, "90": 0}
    for r in rows:
        days = int((now - r["created_at"]) // 86400)
        r["days"] = days
        b = "current" if days < 30 else "30" if days < 60 else \
            "60" if days < 90 else "90"
        r["bucket"] = b
        buckets[b] += r["total_cents"]
    return {"rows": rows, "total_cents": sum(r["total_cents"] for r in rows),
            "aged": buckets}


def payables(con) -> dict:
    """What the business owes: approved expenses somebody paid personally
    and has not been reimbursed for, and purchase orders not yet
    received. Both already exist as rows; neither had a list."""
    staff = [dict(r) for r in con.execute(
        "SELECT e.id, e.amount_cents, e.spent_at, e.vendor, e.category,"
        " u.name AS who FROM expenses e JOIN users u ON u.id=e.user_id"
        " WHERE e.state='approved' AND e.paid_by='me'"
        " ORDER BY e.spent_at").fetchall()]
    orders = []
    try:
        # A purchase order has no total of its own; it is the sum of what
        # is still to come on its lines, which is also the only figure
        # that means anything once a delivery has part-arrived.
        orders = [dict(r) for r in con.execute(
            "SELECT p.id, p.created_at, p.status, p.expected,"
            " s.name AS who, COALESCE(SUM("
            "   MAX(l.qty - l.received, 0) * l.unit_cost_cents), 0)"
            "   AS total_cents"
            " FROM purchase_orders p"
            " LEFT JOIN suppliers s ON s.id=p.supplier_id"
            " LEFT JOIN purchase_order_lines l ON l.po_id=p.id"
            " WHERE p.status NOT IN ('received','cancelled')"
            " GROUP BY p.id, p.created_at, p.status, p.expected, s.name"
            " ORDER BY p.created_at").fetchall()]
    except Exception:                                        # noqa: BLE001
        orders = []          # the Sourcing capability may not be installed
    return {"staff": staff, "purchase_orders": orders,
            "staff_cents": sum(r["amount_cents"] for r in staff),
            "po_cents": sum(int(r.get("total_cents") or 0) for r in orders),
            "total_cents": sum(r["amount_cents"] for r in staff)
            + sum(int(r.get("total_cents") or 0) for r in orders)}


# ---------- planned against actual ----------

def budget_view(con, bid: int) -> dict:
    from . import accounting as ACC
    b = con.execute("SELECT * FROM budgets WHERE id=?", (bid,)).fetchone()
    if b is None:
        raise HTTPException(404, "no such budget")
    actual = {x["code"]: x for x in ACC.balances(
        con, since=b["starts"], upto=b["ends"])}
    lines = []
    for ln in con.execute(
            "SELECT l.*, a.name, a.kind FROM budget_lines l"
            " LEFT JOIN accounts a ON a.code=l.account"
            " WHERE l.budget_id=? ORDER BY l.account", (bid,)).fetchall():
        got = actual.get(ln["account"], {}).get("balance_cents", 0)
        planned = int(ln["amount_cents"])
        # For a cost, spending less than planned is good; for income,
        # earning less is bad. One subtraction cannot mean both, so the
        # sign is set by what kind of account it is.
        good = (got <= planned) if ln["kind"] == "expense" else (got >= planned)
        lines.append({"account": ln["account"], "name": ln["name"] or "",
                      "kind": ln["kind"] or "", "planned_cents": planned,
                      "actual_cents": got, "variance_cents": got - planned,
                      "on_track": good})
    return {**dict(b), "lines": lines,
            "planned_cents": sum(x["planned_cents"] for x in lines),
            "actual_cents": sum(x["actual_cents"] for x in lines)}


# ---------- the weeks ahead ----------

def forecast(con, weeks: int = FORECAST_WEEKS) -> dict:
    """Opening cash, then week by week what is expected in and out.

    Every input is something already recorded: cash accounts, unpaid
    orders, unreimbursed expenses, and the recurring expenses that have a
    next date on them. Nothing is invented, which also means nothing is
    predicted — this is what the existing rows imply, not what will
    happen."""
    from . import treasury as TRE
    opening = 0
    try:
        opening = TRE.summary(con)["total_cents"]
    except Exception:                                        # noqa: BLE001
        opening = 0
    now = time.time()
    weeks = max(1, min(int(weeks), 52))
    out = []
    rec = con.execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS c FROM expenses"
        " WHERE recurring<>'' AND state IN ('approved','paid')"
        " AND next_at>0").fetchone()["c"]
    recv = receivables(con)
    pays = payables(con)
    running = opening
    for w in range(weeks):
        a = now + w * 7 * 86400
        b = a + 7 * 86400
        # An unpaid order is assumed to land thirty days after it was
        # placed. An assumption, and named as one on the screen.
        due_in = sum(r["total_cents"] for r in recv["rows"]
                     if a <= r["created_at"] + 30 * 86400 < b)
        due_out = sum(r["amount_cents"] for r in pays["staff"]
                      if a <= r["spent_at"] + 14 * 86400 < b)
        rec_out = con.execute(
            "SELECT COALESCE(SUM(amount_cents),0) AS c FROM expenses"
            " WHERE recurring<>'' AND next_at>=? AND next_at<?",
            (a, b)).fetchone()["c"]
        running += due_in - due_out - int(rec_out)
        out.append({"week": w, "starts": a,
                    "in_cents": int(due_in), "out_cents": int(due_out + rec_out),
                    "closing_cents": running})
    low = min((x["closing_cents"] for x in out), default=opening)
    return {"opening_cents": opening, "weeks": out, "lowest_cents": low,
            "goes_negative": low < 0,
            "recurring_monthly_cents": int(rec),
            "note": "What the rows already here imply, not a prediction. An "
                    "unpaid order is assumed to land thirty days after it "
                    "was placed and a staff reimbursement two weeks after "
                    "the expense; neither is a promise anybody made."}


def working_capital(con) -> dict:
    from . import accounting as ACC
    bs = ACC.balances(con)
    assets = sum(b["balance_cents"] for b in bs if b["kind"] == "asset")
    liabs = sum(b["balance_cents"] for b in bs if b["kind"] == "liability")
    return {"assets_cents": assets, "liabilities_cents": liabs,
            "working_capital_cents": assets - liabs,
            "ratio_bps": (assets * 10000 // liabs) if liabs else 0}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/finance")
def finance_page(weeks: int = FORECAST_WEEKS, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    budgets = [dict(r) for r in con.execute(
        "SELECT * FROM budgets ORDER BY starts DESC").fetchall()]
    current = None
    now = time.time()
    for b in budgets:
        if b["active"] and b["starts"] <= now <= b["ends"]:
            current = budget_view(con, b["id"])
            break
    if current is None and budgets:
        current = budget_view(con, budgets[0]["id"])
    return {"receivables": receivables(con), "payables": payables(con),
            "budgets": budgets, "budget": current,
            "forecast": forecast(con, weeks),
            "working_capital": working_capital(con),
            "accounts": [dict(r) for r in con.execute(
                "SELECT code, name, kind FROM accounts WHERE active=1"
                " AND kind IN ('income','expense') ORDER BY code").fetchall()]}


@router.get("/api/finance/budgets/{bid}")
def budget_detail(bid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return budget_view(con, bid)


class BudgetBody(BaseModel):
    id: int = 0
    label: str
    starts: float
    ends: float
    active: bool = True
    note: str = ""


@router.post("/api/finance/budgets")
def budget_save(body: BudgetBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    if body.ends <= body.starts:
        raise HTTPException(400, "a budget ends after it starts")
    if not body.label.strip():
        raise HTTPException(400, "name the budget")
    args = (body.label.strip()[:60], body.starts, body.ends,
            int(body.active), body.note.strip()[:400])
    if body.id:
        con.execute("UPDATE budgets SET label=?, starts=?, ends=?, active=?,"
                    " note=? WHERE id=?", args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO budgets(label,starts,ends,active,note,created_at)"
        " VALUES(?,?,?,?,?,?)", args + (db.now(),))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class BudgetLineBody(BaseModel):
    account: str
    amount_cents: int
    note: str = ""


@router.post("/api/finance/budgets/{bid}/lines")
def budget_line(bid: int, body: BudgetLineBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    if con.execute("SELECT 1 FROM budgets WHERE id=?", (bid,)).fetchone() is None:
        raise HTTPException(404, "no such budget")
    if con.execute("SELECT 1 FROM accounts WHERE code=? AND active=1",
                   (body.account,)).fetchone() is None:
        raise HTTPException(400, f"no account {body.account!r} — a budget "
                                 "line is planned against the same account "
                                 "the actual lands in, or the two can never "
                                 "be compared")
    con.execute(
        "INSERT INTO budget_lines(budget_id,account,amount_cents,note)"
        " VALUES(?,?,?,?) ON CONFLICT(budget_id, account) DO UPDATE SET"
        " amount_cents=excluded.amount_cents, note=excluded.note",
        (bid, body.account, body.amount_cents, body.note.strip()[:200]))
    con.commit()
    return {"ok": True}


@router.delete("/api/finance/budgets/{bid}/lines/{account}")
def budget_line_delete(bid: int, account: str, user=Depends(current_user),
                       con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM budget_lines WHERE budget_id=? AND account=?",
                (bid, account))
    con.commit()
    return {"ok": True}
