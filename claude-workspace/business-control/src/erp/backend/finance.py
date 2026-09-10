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
import html as _html
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
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
    con.executescript(INVOICE_TABLES)
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
    # Issued invoices are owed to us in exactly the same sense, and a
    # receivables figure that counted only orders would understate what
    # the business is owed by the whole of whatever it bills for.
    for i in con.execute(
            "SELECT * FROM invoices WHERE state IN ('issued','part_paid')"
            " AND credits=0 ORDER BY issued_at").fetchall():
        owed = int(i["total_cents"]) - int(i["paid_cents"])
        if owed <= 0:
            continue
        at = i["due_at"] or i["issued_at"] or now
        days = int((now - at) // 86400)
        b = "current" if days < 30 else "30" if days < 60 else \
            "60" if days < 90 else "90"
        buckets[b] += owed
        rows.append({"id": i["id"], "invoice": i["number"],
                     "total_cents": owed, "created_at": i["issued_at"],
                     "payment_status": i["state"], "kind": "invoice",
                     "who": i["bill_to"], "email": i["bill_email"],
                     "days": days, "bucket": b})
    rows.sort(key=lambda r: r["created_at"])
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


# ---------- invoicing ----------
# An unpaid order is a receivable; an invoice is a receivable you can
# SEND. The difference matters for the half of a business that bills
# rather than sells: a school billing a term's fees, a studio billing a
# milestone, anyone on terms. Those had to be typed into a document and
# then remembered somewhere else, which is how a business ends up with a
# spreadsheet of what it is owed beside a system that does not know.
#
# An invoice is issued once and then it is somebody else's copy. So:
# a draft is editable, an issued one is not, and a correction is a credit
# note that reverses it — the same rule the ledger keeps, for the same
# reason. What was sent must still say what it said.

INVOICE_TABLES = """
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY,
  number TEXT DEFAULT '',                  -- sequential, assigned at issue
  token TEXT UNIQUE NOT NULL,              -- the link the customer opens
  user_id INTEGER DEFAULT 0,               -- the account, when there is one
  bill_to TEXT NOT NULL,
  bill_email TEXT DEFAULT '',
  bill_address TEXT DEFAULT '',
  reference TEXT DEFAULT '',               -- their PO number
  issued_at REAL DEFAULT 0,
  due_at REAL DEFAULT 0,
  terms_days INTEGER DEFAULT 30,
  currency TEXT DEFAULT 'USD',
  subtotal_cents INTEGER DEFAULT 0,
  tax_cents INTEGER DEFAULT 0,
  total_cents INTEGER DEFAULT 0,
  paid_cents INTEGER DEFAULT 0,
  state TEXT DEFAULT 'draft',              -- draft|issued|part_paid|paid|void
  note TEXT DEFAULT '',
  terms_text TEXT DEFAULT '',
  credits INTEGER DEFAULT 0,               -- the invoice this one credits
  credited_by INTEGER DEFAULT 0,
  journal_id INTEGER DEFAULT 0,
  sent_at REAL DEFAULT 0,
  viewed_at REAL DEFAULT 0,
  created_by TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS invoices_state ON invoices(state, due_at);

CREATE TABLE IF NOT EXISTS invoice_lines (
  id INTEGER PRIMARY KEY,
  invoice_id INTEGER NOT NULL,
  what TEXT NOT NULL,
  qty REAL DEFAULT 1,
  unit_cents INTEGER DEFAULT 0,
  tax_bps INTEGER DEFAULT 0,
  amount_cents INTEGER DEFAULT 0,
  position INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS invoice_lines_i ON invoice_lines(invoice_id);

/* Money received against an invoice. Kept as its own rows because part
   payment is normal and an invoice that can only be paid in full is one
   somebody settles in a spreadsheet instead. */
CREATE TABLE IF NOT EXISTS invoice_payments (
  id INTEGER PRIMARY KEY,
  invoice_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL,
  at REAL NOT NULL,
  method TEXT DEFAULT '',
  reference TEXT DEFAULT '',
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
"""

INVOICE_STATES = ("draft", "issued", "part_paid", "paid", "void")


def _invoice_number(con) -> str:
    """Sequential within the year. Gaps in an invoice sequence are the
    sort of thing an auditor asks about, so the number is assigned when
    it is ISSUED rather than when the draft is started — a draft that is
    abandoned should not consume one."""
    year = time.strftime("%Y", time.localtime())
    row = con.execute(
        "SELECT number FROM invoices WHERE number LIKE ?"
        " ORDER BY id DESC LIMIT 1", (f"{year}-%",)).fetchone()
    n = int(row["number"].split("-")[1]) + 1 if row and "-" in (
        row["number"] or "") else 1
    return f"{year}-{n:04d}"


def invoice_totals(con, iid: int) -> dict:
    sub = tax = 0
    for ln in con.execute("SELECT * FROM invoice_lines WHERE invoice_id=?",
                          (iid,)).fetchall():
        amount = int(round(float(ln["qty"] or 0) * int(ln["unit_cents"] or 0)))
        con.execute("UPDATE invoice_lines SET amount_cents=? WHERE id=?",
                    (amount, ln["id"]))
        sub += amount
        tax += amount * int(ln["tax_bps"] or 0) // 10000
    con.execute("UPDATE invoices SET subtotal_cents=?, tax_cents=?,"
                " total_cents=? WHERE id=?", (sub, tax, sub + tax, iid))
    con.commit()
    return {"subtotal_cents": sub, "tax_cents": tax, "total_cents": sub + tax}


def invoice_shape(con, r) -> dict:
    d = dict(r)
    d["lines"] = [dict(x) for x in con.execute(
        "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY position, id",
        (r["id"],)).fetchall()]
    d["payments"] = [dict(x) for x in con.execute(
        "SELECT * FROM invoice_payments WHERE invoice_id=? ORDER BY at",
        (r["id"],)).fetchall()]
    d["outstanding_cents"] = int(r["total_cents"]) - int(r["paid_cents"])
    now = time.time()
    d["overdue"] = bool(r["state"] in ("issued", "part_paid")
                        and not r["credits"]
                        and r["due_at"] and r["due_at"] < now)
    d["days_overdue"] = int((now - r["due_at"]) // 86400) if d["overdue"] else 0
    return d


def post_invoice(con, inv) -> int:
    """An issued invoice in the books: they owe us, and we have earned it.

    Posted at ISSUE rather than at payment, which is the opposite of the
    order path and deliberate. An order is recorded when the money
    arrives; an invoice is a claim, and a business that only recognises
    a claim when it is settled cannot tell you what it is owed.
    """
    from . import accounting as ACC
    have = con.execute("SELECT id FROM journals WHERE source='invoice' AND"
                       " source_id=?", (str(inv["id"]),)).fetchone()
    if have:
        return have["id"]
    sign = -1 if inv["credits"] else 1
    lines = [{"account": "1200", "debit_cents": inv["total_cents"] * sign
              if sign > 0 else 0,
              "credit_cents": inv["total_cents"] if sign < 0 else 0,
              "memo": f"invoice {inv['number']}"}]
    body = [{"account": "4000",
             "credit_cents": inv["subtotal_cents"] if sign > 0 else 0,
             "debit_cents": inv["subtotal_cents"] if sign < 0 else 0}]
    if inv["tax_cents"]:
        body.append({"account": "2100",
                     "credit_cents": inv["tax_cents"] if sign > 0 else 0,
                     "debit_cents": inv["tax_cents"] if sign < 0 else 0})
    return ACC.post(con, at=inv["issued_at"] or time.time(),
                    lines=lines + body,
                    memo=("Credit note " if sign < 0 else "Invoice ")
                    + f"{inv['number']} — {inv['bill_to']}",
                    ref=inv["number"], source="invoice",
                    source_id=str(inv["id"]), by="posted automatically")


def invoice_pdf(con, inv, brand: str) -> bytes:
    """The document that gets sent. Plain, because an invoice is read by
    somebody's accounts payable and then filed."""
    from fpdf import FPDF
    money = lambda c: f"{c / 100:,.2f}"                      # noqa: E731
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "Credit note" if inv["credits"] else "Invoice", ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"{brand}", ln=1)
    pdf.cell(0, 6, f"Number: {inv['number']}", ln=1)
    if inv["issued_at"]:
        pdf.cell(0, 6, "Issued: " + time.strftime(
            "%d %b %Y", time.localtime(inv["issued_at"])), ln=1)
    if inv["due_at"]:
        pdf.cell(0, 6, "Due: " + time.strftime(
            "%d %b %Y", time.localtime(inv["due_at"])), ln=1)
    if inv["reference"]:
        pdf.cell(0, 6, f"Your reference: {inv['reference']}", ln=1)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "To", ln=1)
    pdf.set_font("Helvetica", "", 10)
    for line in [inv["bill_to"]] + str(inv["bill_address"] or "").split("\n"):
        if line.strip():
            pdf.cell(0, 5, line.strip()[:90], ln=1)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(96, 7, "What", border="B")
    pdf.cell(18, 7, "Qty", border="B", align="R")
    pdf.cell(28, 7, "Each", border="B", align="R")
    pdf.cell(28, 7, "Amount", border="B", align="R", ln=1)
    pdf.set_font("Helvetica", "", 10)
    for ln_ in con.execute("SELECT * FROM invoice_lines WHERE invoice_id=?"
                           " ORDER BY position, id", (inv["id"],)).fetchall():
        pdf.cell(96, 6, str(ln_["what"])[:60])
        pdf.cell(18, 6, f"{ln_['qty']:g}", align="R")
        pdf.cell(28, 6, money(ln_["unit_cents"]), align="R")
        pdf.cell(28, 6, money(ln_["amount_cents"]), align="R", ln=1)
    pdf.ln(2)
    for label, amount, bold in (("Subtotal", inv["subtotal_cents"], False),
                                ("Tax", inv["tax_cents"], False),
                                ("Total", inv["total_cents"], True),
                                ("Paid", inv["paid_cents"], False),
                                ("Outstanding",
                                 inv["total_cents"] - inv["paid_cents"], True)):
        if not amount and label in ("Tax", "Paid"):
            continue
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.cell(142, 6, label, align="R")
        pdf.cell(28, 6, money(amount), align="R", ln=1)
    if inv["terms_text"] or inv["note"]:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, str(inv["note"] or "")[:600])
        pdf.multi_cell(0, 5, str(inv["terms_text"] or "")[:600])
    out = pdf.output()
    return bytes(out) if not isinstance(out, bytes) else out


# ---------- invoice routes ----------

class InvoiceLineBody(BaseModel):
    what: str
    qty: float = 1
    unit_cents: int = 0
    tax_bps: int = 0


class InvoiceBody(BaseModel):
    id: int = 0
    bill_to: str
    bill_email: str = ""
    bill_address: str = ""
    reference: str = ""
    user_id: int = 0
    terms_days: int = 30
    note: str = ""
    terms_text: str = ""
    lines: list[InvoiceLineBody] = []


@router.get("/api/finance/invoices")
def invoice_list(state: str = "", user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    where, args = "", []
    if state:
        where = " WHERE state=?"
        args = [state]
    rows = [invoice_shape(con, r) for r in con.execute(
        "SELECT * FROM invoices" + where +
        " ORDER BY COALESCE(issued_at, created_at) DESC LIMIT 200",
        args).fetchall()]
    # A credit note is money we owe THEM. Counting it as outstanding
    # would say the business is owed the very amount it just gave back.
    owed = [r for r in rows if not r["credits"]]
    return {"invoices": rows, "states": list(INVOICE_STATES),
            "outstanding_cents": sum(r["outstanding_cents"] for r in owed
                                     if r["state"] in ("issued", "part_paid")),
            "overdue_cents": sum(r["outstanding_cents"] for r in owed
                                 if r["overdue"]),
            "credited_cents": sum(r["total_cents"] for r in rows
                                  if r["credits"])}


@router.get("/api/finance/invoices/{iid}")
def invoice_detail(iid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such invoice")
    from .main import base_url
    return {**invoice_shape(con, r),
            "link": f"{base_url()}/invoice/{r['token']}"}


@router.post("/api/finance/invoices")
def invoice_save(body: InvoiceBody, user=Depends(current_user),
                 con=Depends(get_con)):
    """Create or edit a DRAFT. An issued invoice is somebody else's copy
    and is corrected by a credit note, not by editing."""
    _require(user)
    if not body.bill_to.strip():
        raise HTTPException(400, "who is being billed")
    if body.terms_days < 0 or body.terms_days > 365:
        raise HTTPException(400, "terms are a number of days up to a year")
    args = (body.bill_to.strip()[:160], body.bill_email.strip()[:200],
            body.bill_address.strip()[:400], body.reference.strip()[:80],
            body.user_id, body.terms_days, body.note.strip()[:2000],
            body.terms_text.strip()[:2000])
    if body.id:
        inv = con.execute("SELECT * FROM invoices WHERE id=?",
                          (body.id,)).fetchone()
        if inv is None:
            raise HTTPException(404, "no such invoice")
        if inv["state"] != "draft":
            raise HTTPException(
                400, f"invoice {inv['number']} has been issued — raise a "
                     "credit note against it rather than changing what "
                     "somebody already has a copy of")
        con.execute(
            "UPDATE invoices SET bill_to=?, bill_email=?, bill_address=?,"
            " reference=?, user_id=?, terms_days=?, note=?, terms_text=?"
            " WHERE id=?", args + (body.id,))
        iid = body.id
    else:
        cur = con.execute(
            "INSERT INTO invoices(token,bill_to,bill_email,bill_address,"
            " reference,user_id,terms_days,note,terms_text,created_by,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (secrets.token_urlsafe(20),) + args + (user["name"], db.now()))
        iid = cur.lastrowid
    if body.lines:
        con.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (iid,))
        for i, ln in enumerate(body.lines):
            if not ln.what.strip():
                continue
            con.execute(
                "INSERT INTO invoice_lines(invoice_id,what,qty,unit_cents,"
                " tax_bps,position) VALUES(?,?,?,?,?,?)",
                (iid, ln.what.strip()[:200], ln.qty, ln.unit_cents,
                 ln.tax_bps, i))
    con.commit()
    invoice_totals(con, iid)
    return {"ok": True, "id": iid}


@router.post("/api/finance/invoices/{iid}/issue")
def invoice_issue(iid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None:
        raise HTTPException(404, "no such invoice")
    if inv["state"] != "draft":
        raise HTTPException(400, "that one has already been issued")
    t = invoice_totals(con, iid)
    if t["total_cents"] <= 0:
        raise HTTPException(400, "an invoice for nothing is not an invoice — "
                                 "add a line with an amount")
    now = time.time()
    con.execute(
        "UPDATE invoices SET state='issued', number=?, issued_at=?, due_at=?"
        " WHERE id=?",
        (_invoice_number(con), now, now + int(inv["terms_days"]) * 86400, iid))
    con.commit()
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    jid, problem = 0, ""
    try:
        jid = post_invoice(con, inv)
        con.execute("UPDATE invoices SET journal_id=? WHERE id=?", (jid, iid))
        con.commit()
    except HTTPException as e:
        problem = str(e.detail)
    from .main import base_url
    return {"ok": True, "number": inv["number"], "journal_id": jid,
            "posting_problem": problem,
            "link": f"{base_url()}/invoice/{inv['token']}"}


@router.post("/api/finance/invoices/{iid}/send")
def invoice_send(iid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    from .main import CFG, base_url
    from . import mailer
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None:
        raise HTTPException(404, "no such invoice")
    if inv["state"] == "draft":
        raise HTTPException(400, "issue it first — a draft has no number")
    if "@" not in (inv["bill_email"] or ""):
        raise HTTPException(400, "no email address on this invoice")
    shop = CFG.get("brand_name") or "us"
    link = f"{base_url()}/invoice/{inv['token']}"
    text = (f"Hello,\n\nInvoice {inv['number']} from {shop} is attached at "
            f"the link below.\n\n{link}\n\nAmount: "
            f"{inv['total_cents'] / 100:,.2f}\nDue: "
            + time.strftime("%d %B %Y", time.localtime(inv["due_at"]))
            + f"\n\nThank you,\n{shop}")
    status = mailer.send_logged(con, CFG, inv["bill_email"],
                                f"Invoice {inv['number']} from {shop}",
                                text, "invoice")
    con.execute("UPDATE invoices SET sent_at=? WHERE id=?", (time.time(), iid))
    con.commit()
    return {"ok": True, "status": status, "link": link}


class PaymentBody(BaseModel):
    amount_cents: int
    at: float = 0
    method: str = ""
    reference: str = ""


@router.post("/api/finance/invoices/{iid}/payments")
def invoice_pay(iid: int, body: PaymentBody, user=Depends(current_user),
                con=Depends(get_con)):
    """Money received. Part payment is normal, so this adds a row rather
    than flipping a flag."""
    _require(user)
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None:
        raise HTTPException(404, "no such invoice")
    if inv["state"] in ("draft", "void"):
        raise HTTPException(400, f"a {inv['state']} invoice takes no payment")
    if body.amount_cents <= 0:
        raise HTTPException(400, "an amount received")
    owed = int(inv["total_cents"]) - int(inv["paid_cents"])
    if body.amount_cents > owed:
        raise HTTPException(
            400, f"that is more than the {owed / 100:,.2f} outstanding — "
                 "record an overpayment as a credit note rather than as a "
                 "payment nobody can account for")
    at = body.at or time.time()
    con.execute(
        "INSERT INTO invoice_payments(invoice_id,amount_cents,at,method,"
        " reference,by_name,created_at) VALUES(?,?,?,?,?,?,?)",
        (iid, body.amount_cents, at, body.method.strip()[:40],
         body.reference.strip()[:80], user["name"], db.now()))
    paid = int(inv["paid_cents"]) + body.amount_cents
    con.execute("UPDATE invoices SET paid_cents=?, state=? WHERE id=?",
                (paid, "paid" if paid >= int(inv["total_cents"])
                 else "part_paid", iid))
    con.commit()
    try:
        from . import accounting as ACC
        ACC.post(con, at=at, lines=[
            {"account": "1010", "debit_cents": body.amount_cents,
             "memo": f"paid on {inv['number']}"},
            {"account": "1200", "credit_cents": body.amount_cents}],
            memo=f"Payment on invoice {inv['number']}", ref=inv["number"],
            source="invoice_payment", source_id=str(con.execute(
                "SELECT MAX(id) AS m FROM invoice_payments").fetchone()["m"]),
            by="posted automatically")
    except HTTPException:
        pass          # the payment happened; the books can be caught up
    return {"ok": True, "paid_cents": paid}


class CreditBody(BaseModel):
    reason: str = ""


@router.post("/api/finance/invoices/{iid}/credit")
def invoice_credit(iid: int, body: CreditBody, user=Depends(current_user),
                   con=Depends(get_con)):
    """A credit note reversing an issued invoice. The original stays
    exactly as it was sent, which is the whole point of one."""
    _require(user)
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None:
        raise HTTPException(404, "no such invoice")
    if inv["state"] == "draft":
        raise HTTPException(400, "a draft is edited, not credited")
    if inv["credited_by"]:
        raise HTTPException(400, "that one has already been credited")
    if inv["credits"]:
        raise HTTPException(400, "a credit note is not itself credited")
    now = time.time()
    cur = con.execute(
        "INSERT INTO invoices(token,user_id,bill_to,bill_email,bill_address,"
        " reference,issued_at,due_at,terms_days,subtotal_cents,tax_cents,"
        " total_cents,state,note,credits,created_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'issued',?,?,?,?)",
        (secrets.token_urlsafe(20), inv["user_id"], inv["bill_to"],
         inv["bill_email"], inv["bill_address"], inv["reference"], now, now,
         0, inv["subtotal_cents"], inv["tax_cents"], inv["total_cents"],
         (body.reason.strip() or f"Credits invoice {inv['number']}")[:2000],
         iid, user["name"], db.now()))
    nid = cur.lastrowid
    con.execute("UPDATE invoices SET number=? WHERE id=?",
                (_invoice_number(con) + "-CN", nid))
    for ln in con.execute("SELECT * FROM invoice_lines WHERE invoice_id=?",
                          (iid,)).fetchall():
        con.execute(
            "INSERT INTO invoice_lines(invoice_id,what,qty,unit_cents,tax_bps,"
            " amount_cents,position) VALUES(?,?,?,?,?,?,?)",
            (nid, ln["what"], ln["qty"], ln["unit_cents"], ln["tax_bps"],
             ln["amount_cents"], ln["position"]))
    con.execute("UPDATE invoices SET credited_by=?, state='void' WHERE id=?",
                (nid, iid))
    con.commit()
    note = con.execute("SELECT * FROM invoices WHERE id=?", (nid,)).fetchone()
    try:
        post_invoice(con, note)
    except HTTPException:
        pass
    return {"ok": True, "id": nid, "number": note["number"]}


@router.get("/api/finance/invoices/{iid}/pdf")
def invoice_pdf_route(iid: int, user=Depends(current_user),
                      con=Depends(get_con)):
    _require(user)
    from .main import CFG
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None:
        raise HTTPException(404, "no such invoice")
    from fastapi.responses import Response
    return Response(
        invoice_pdf(con, inv, CFG.get("brand_name") or "Business Control"),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="invoice-{inv["number"] or iid}.pdf"'})


@router.get("/invoice/{token}", response_class=HTMLResponse)
def invoice_page(token: str, con=Depends(get_con)):
    """What the customer opens. No sign-in: the token IS the credential,
    the way every other outward link here works — a customer made to open
    an account to read a bill is a customer who telephones instead.

    Viewing is recorded, which answers the argument that starts "we never
    received it"."""
    from .main import CFG
    e = _html.escape
    r = con.execute("SELECT * FROM invoices WHERE token=?", (token,)).fetchone()
    if r is None or r["state"] == "draft":
        return HTMLResponse("<h3>No invoice at this address.</h3>", 404)
    if not r["viewed_at"]:
        con.execute("UPDATE invoices SET viewed_at=? WHERE id=?",
                    (time.time(), r["id"]))
        con.commit()
    shop = CFG.get("brand_name") or "this business"
    inv = invoice_shape(con, r)
    m = lambda c: f"{c / 100:,.2f}"                          # noqa: E731
    rows = "".join(
        f"<tr><td>{e(str(l['what']))}</td><td class=n>{l['qty']:g}</td>"
        f"<td class=n>{m(l['unit_cents'])}</td>"
        f"<td class=n>{m(l['amount_cents'])}</td></tr>"
        for l in inv["lines"])
    paid = ("".join(
        f"<tr><td>Paid {time.strftime('%d %b %Y', time.localtime(p['at']))}"
        f"{(' · ' + e(p['method'])) if p['method'] else ''}</td>"
        f"<td class=n colspan=3>−{m(p['amount_cents'])}</td></tr>"
        for p in inv["payments"]))
    state = ("This has been credited in full." if r["credits"]
             else "Paid in full — thank you." if r["state"] == "paid"
             else f"{inv['days_overdue']} days overdue."
             if inv["overdue"] else "")
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{'Credit note' if r['credits'] else 'Invoice'} {e(r['number'])} — {e(shop)}</title>
<style>:root{{color-scheme:light}}
body{{font:16px/1.55 system-ui,sans-serif;color:#16202b;background:#f7f6f3;margin:0}}
main{{max-width:720px;margin:0 auto;padding:1.6rem 1.2rem 3rem}}
.card{{background:#fff;border:1px solid #e3e0d9;border-radius:14px;padding:1.4rem}}
h1{{font-size:1.5rem;margin:0 0 .2rem}} .k{{color:#5b6b7c;font-size:.92rem}}
table{{width:100%;border-collapse:collapse;margin:1.2rem 0}}
th,td{{text-align:left;padding:.45rem .3rem;border-bottom:1px solid #eee}}
th.n,td.n{{text-align:right}} tfoot td{{border:0;padding-top:.5rem}}
.tot{{font-weight:700;font-size:1.1rem}}
.due{{display:inline-block;padding:.3rem .7rem;border-radius:1rem;background:#eceaf6;margin-top:.4rem}}
.late{{background:#fdecea}} .ok{{background:#e7f6ec}}
.btn{{display:inline-block;margin-top:1.2rem;padding:.6rem 1.1rem;border-radius:.5rem;
background:#4634d9;color:#fff;text-decoration:none}}
.pre{{white-space:pre-wrap;color:#5b6b7c;font-size:.92rem;margin-top:1rem}}</style>
<main><div class="card">
  <h1>{'Credit note' if r['credits'] else 'Invoice'} {e(r['number'])}</h1>
  <div class="k">From {e(shop)}</div>
  <div class="k">To {e(r['bill_to'])}</div>
  {f'<div class="k">Your reference: {e(r["reference"])}</div>' if r['reference'] else ''}
  <div class="due {'late' if inv['overdue'] else 'ok' if r['state'] == 'paid' else ''}">
    {'Issued ' + time.strftime('%d %B %Y', time.localtime(r['issued_at'])) if r['issued_at'] else ''}
    {' · due ' + time.strftime('%d %B %Y', time.localtime(r['due_at'])) if r['due_at'] and not r['credits'] else ''}
  </div>
  {f'<div class="k">{e(state)}</div>' if state else ''}
  <table>
    <thead><tr><th>What</th><th class=n>Qty</th><th class=n>Each</th>
      <th class=n>Amount</th></tr></thead>
    <tbody>{rows}{paid}</tbody>
    <tfoot>
      <tr><td colspan=3 class=n>Subtotal</td><td class=n>{m(r['subtotal_cents'])}</td></tr>
      {f'<tr><td colspan=3 class=n>Tax</td><td class=n>{m(r["tax_cents"])}</td></tr>' if r['tax_cents'] else ''}
      <tr class="tot"><td colspan=3 class=n>{'Credited' if r['credits'] else 'Outstanding'}</td>
        <td class=n>{m(inv['outstanding_cents'] if not r['credits'] else r['total_cents'])}</td></tr>
    </tfoot>
  </table>
  <div class="pre">{e(str(r['note'] or ''))}</div>
  <div class="pre">{e(str(r['terms_text'] or ''))}</div>
</div></main>""")
