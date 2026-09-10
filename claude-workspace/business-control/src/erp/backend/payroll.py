"""Payroll: turning approved hours into what each person is actually paid.

The install already knows who worked when. The time clock records it, the
logged-hours form catches what the clock never saw, an admin approves it,
and `timesheet.hours_for` turns all of that into regular, overtime and
leave for a period. What has been missing is the step after: a rate, a
gross, whatever comes off it, a net, and a record each person can check.

That last part is the reason this is not a spreadsheet. A payslip is the
document somebody disputes, and a number they cannot see the working of
is a number they cannot dispute — which is not the same as a number
they agree with.

**This does not know your tax rules and does not pretend to.** There are
no tax tables here, no thresholds, no year-to-date bands, and nothing is
filed with anybody. Deductions are rows the operator writes: a name, a
percentage or a fixed amount, and whether it comes off the employee or
sits on top as an employer cost. That is honest for a system sold in one
price book to businesses in many places, and it is the reason the screen
says "estimate" where a payroll bureau would say "return".

What it does do properly:

  **Hours come from one place.** `timesheet.hours_for` is the same
  function the Hours screen uses, so a payslip and the timesheet it came
  from cannot disagree. A second implementation of "how many hours" is
  how a business ends up arguing with itself.

  **A run is built, then approved, then paid, and only then posted.**
  Building is safe and repeatable; a draft can be rebuilt as many times
  as the hours change. Approval freezes the figures. Marking it paid is
  what reaches the ledger, because a wage that has not been paid is a
  liability rather than a payment.

  **Nothing is recomputed after approval.** The payslip stores its own
  numbers. Rates change, hours get corrected, and a payslip from March
  must still say in June what it said in March.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
/* What somebody is paid, and from when. Kept as history rather than a
   column on the user, because a rate that changes in April must not
   silently restate what March cost. */
/* Named payroll_rates, not pay_rates: classroom.py already owns a
   pay_rates, keyed on teacher_id and holding a per-session rate for
   teaching. CREATE TABLE IF NOT EXISTS on a name somebody else has
   taken does nothing at all and says nothing about it, so the two
   would have shared a table and neither would have had its columns. */
CREATE TABLE IF NOT EXISTS payroll_rates (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'hourly',     -- hourly|salary
  rate_cents INTEGER NOT NULL,             -- per hour, or per year for salary
  overtime_bps INTEGER DEFAULT 15000,      -- 15000 = time and a half
  effective_from REAL NOT NULL,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS payroll_rates_user ON payroll_rates(user_id, effective_from);

/* What comes off, or goes on top. The operator writes these because the
   software does not know the jurisdiction. Order matters: a deduction
   can be a percentage of what is left after the ones before it. */
CREATE TABLE IF NOT EXISTS pay_deductions (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'percent',    -- percent|fixed
  rate_bps INTEGER DEFAULT 0,              -- for percent: 1000 = 10%
  amount_cents INTEGER DEFAULT 0,          -- for fixed
  side TEXT NOT NULL DEFAULT 'employee',   -- employee (off the net) | employer (on top)
  of_remaining INTEGER DEFAULT 0,          -- percent of what is left, not of gross
  position INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pay_runs (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,
  period_start REAL NOT NULL,
  period_end REAL NOT NULL,
  pay_date REAL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'draft',     -- draft|approved|paid|cancelled
  gross_cents INTEGER DEFAULT 0,
  deductions_cents INTEGER DEFAULT 0,
  employer_cents INTEGER DEFAULT 0,
  net_cents INTEGER DEFAULT 0,
  built_at REAL DEFAULT 0,
  approved_by TEXT DEFAULT '',
  approved_at REAL DEFAULT 0,
  paid_at REAL DEFAULT 0,
  journal_id INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);

/* One person, one run. The figures are STORED, not derived: a payslip
   from March must still say in June what it said in March, whatever has
   happened to the rate or the hours since. */
CREATE TABLE IF NOT EXISTS payslips (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  name TEXT DEFAULT '',
  kind TEXT DEFAULT 'hourly',
  rate_cents INTEGER DEFAULT 0,
  regular_hours REAL DEFAULT 0,
  overtime_hours REAL DEFAULT 0,
  leave_hours REAL DEFAULT 0,
  gross_cents INTEGER DEFAULT 0,
  lines TEXT DEFAULT '[]',                 -- JSON: how the gross was reached
  deductions TEXT DEFAULT '[]',            -- JSON: what came off, in order
  employer_cents INTEGER DEFAULT 0,
  net_cents INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(run_id, user_id)
);
CREATE INDEX IF NOT EXISTS payslips_user ON payslips(user_id);
"""

KINDS = ("hourly", "salary")
STATES = ("draft", "approved", "paid", "cancelled")
SIDES = ("employee", "employer")
# Staff. A customer does not get a payslip, and neither does a contractor
# paid per route — that is an invoice, and pretending otherwise is how a
# business misclassifies somebody by accident.
PAID_ROLES = ("employee", "teacher", "cashier", "distributor", "admin",
              "owner", "director")
HOURS_A_YEAR = 2080          # 40 a week, for turning a salary into an hour


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings", "finance", "workforce")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "payroll is the office's")


def rate_for(con, uid: int, at: float):
    """The rate in force on a date, not the newest one. A rise in April
    must not restate March."""
    return con.execute(
        "SELECT * FROM payroll_rates WHERE user_id=? AND effective_from<=?"
        " ORDER BY effective_from DESC, id DESC LIMIT 1", (uid, at)).fetchone()


def deductions(con) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM pay_deductions WHERE active=1"
        " ORDER BY position, id").fetchall()]


def _apply(gross: int, rules: list) -> tuple:
    """Returns (lines, off the employee, employer cost on top).

    Percentages of "what is left" compound in the order the operator set,
    which is what makes the order a field rather than an accident of id.
    """
    lines, taken, employer = [], 0, 0
    for d in rules:
        base = (gross - taken) if d["of_remaining"] else gross
        if d["kind"] == "percent":
            amount = base * int(d["rate_bps"] or 0) // 10000
        else:
            amount = int(d["amount_cents"] or 0)
        amount = max(0, min(amount, base if d["side"] == "employee" else amount))
        lines.append({"code": d["code"], "label": d["label"],
                      "side": d["side"], "amount_cents": amount,
                      "basis": "what is left" if d["of_remaining"] else "gross",
                      "rate_bps": d["rate_bps"] if d["kind"] == "percent" else 0})
        if d["side"] == "employee":
            taken += amount
        else:
            employer += amount
    return lines, taken, employer


def build(con, cfg, run_id: int) -> dict:
    """Work out every payslip in a draft run, from the same hours the
    timesheet shows. Safe to repeat: it replaces the run's payslips."""
    from . import timesheet as TS
    run = con.execute("SELECT * FROM pay_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "no such run")
    if run["state"] != "draft":
        raise HTTPException(400, "only a draft is rebuilt — an approved run "
                                 "keeps the figures it was approved on")
    a, b = run["period_start"], run["period_end"]
    rules = deductions(con)
    con.execute("DELETE FROM payslips WHERE run_id=?", (run_id,))
    people = con.execute(
        "SELECT * FROM users WHERE active=1 AND role IN "
        "(" + ",".join("?" * len(PAID_ROLES)) + ")"
        " AND employment='employee' ORDER BY name", PAID_ROLES).fetchall()
    totals = {"gross": 0, "ded": 0, "emp": 0, "net": 0, "n": 0}
    skipped = []
    for u in people:
        rate = rate_for(con, u["id"], b)
        if rate is None:
            skipped.append({"name": u["name"], "why": "no rate set"})
            continue
        h = TS.hours_for(con, u["id"], a, b)
        lines = []
        if rate["kind"] == "salary":
            # A period's share of the year, by its length. Nobody is paid
            # for the leap second, and dividing by twelve when the run is
            # weekly is the bug this avoids.
            share = (b - a) / (365.25 * 86400)
            gross = int(round(int(rate["rate_cents"]) * share))
            lines.append({"what": "Salary for the period",
                          "hours": 0, "rate_cents": rate["rate_cents"],
                          "amount_cents": gross})
        else:
            reg = float(h["regular_hours"] or 0)
            ot = float(h["overtime_hours"] or 0)
            leave = float(h["leave_hours"] or 0)
            r = int(rate["rate_cents"])
            ot_rate = r * int(rate["overtime_bps"] or 10000) // 10000
            gross = 0
            for what, hours, per in (("Regular hours", reg, r),
                                     ("Overtime", ot, ot_rate),
                                     ("Paid leave", leave, r)):
                if hours:
                    amt = int(round(hours * per))
                    gross += amt
                    lines.append({"what": what, "hours": round(hours, 2),
                                  "rate_cents": per, "amount_cents": amt})
        if gross <= 0 and not lines:
            skipped.append({"name": u["name"], "why": "nothing worked"})
            continue
        ded, taken, employer = _apply(gross, rules)
        net = gross - taken
        con.execute(
            "INSERT INTO payslips(run_id,user_id,name,kind,rate_cents,"
            " regular_hours,overtime_hours,leave_hours,gross_cents,lines,"
            " deductions,employer_cents,net_cents,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, u["id"], u["name"], rate["kind"], rate["rate_cents"],
             round(float(h["regular_hours"] or 0), 2),
             round(float(h["overtime_hours"] or 0), 2),
             round(float(h["leave_hours"] or 0), 2),
             gross, json.dumps(lines), json.dumps(ded), employer, net,
             db.now()))
        totals["gross"] += gross
        totals["ded"] += taken
        totals["emp"] += employer
        totals["net"] += net
        totals["n"] += 1
    con.execute(
        "UPDATE pay_runs SET gross_cents=?, deductions_cents=?,"
        " employer_cents=?, net_cents=?, built_at=? WHERE id=?",
        (totals["gross"], totals["ded"], totals["emp"], totals["net"],
         time.time(), run_id))
    con.commit()
    return {"ok": True, "payslips": totals["n"], "skipped": skipped,
            "gross_cents": totals["gross"], "net_cents": totals["net"]}


def post_to_books(con, run) -> int:
    """A paid run in the ledger: the cost, what is held back, and what
    actually left the bank. Posted on payment rather than approval,
    because until it is paid a wage is a liability, not a payment."""
    from . import accounting as ACC
    have = con.execute("SELECT id FROM journals WHERE source='payroll' AND"
                       " source_id=?", (str(run["id"]),)).fetchone()
    if have:
        return have["id"]
    lines = [{"account": "6100", "debit_cents": run["gross_cents"],
              "memo": f"wages — {run['label']}"}]
    if run["employer_cents"]:
        lines.append({"account": "6100", "debit_cents": run["employer_cents"],
                      "memo": "employer costs"})
    if run["deductions_cents"] or run["employer_cents"]:
        lines.append({"account": "2210",
                      "credit_cents": run["deductions_cents"]
                      + run["employer_cents"],
                      "memo": "held back, owed onward"})
    lines.append({"account": "1010", "credit_cents": run["net_cents"],
                  "memo": "paid to staff"})
    return ACC.post(con, at=run["pay_date"] or time.time(), lines=lines,
                    memo=f"Payroll — {run['label']}", ref=f"PAY-{run['id']}",
                    source="payroll", source_id=str(run["id"]),
                    by="posted automatically")


def shape_run(r) -> dict:
    return dict(r)


def shape_slip(r) -> dict:
    d = dict(r)
    d["lines"] = json.loads(d["lines"] or "[]")
    d["deductions"] = json.loads(d["deductions"] or "[]")
    return d


# ---------- routes ----------

router = APIRouter()

from .main import CFG, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/payroll")
def payroll_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    runs = [shape_run(r) for r in con.execute(
        "SELECT * FROM pay_runs ORDER BY period_start DESC, id DESC LIMIT 40"
        ).fetchall()]
    rates = [dict(r) for r in con.execute(
        "SELECT p.*, u.name FROM payroll_rates p JOIN users u ON u.id=p.user_id"
        " ORDER BY u.name, p.effective_from DESC").fetchall()]
    staff = [dict(r) for r in con.execute(
        "SELECT id, name, role, employment FROM users WHERE active=1 AND"
        " role IN (" + ",".join("?" * len(PAID_ROLES)) + ")"
        " ORDER BY name", PAID_ROLES).fetchall()]
    latest = {}
    for r in rates:
        latest.setdefault(r["user_id"], r)
    for s in staff:
        s["rate"] = latest.get(s["id"])
    return {"runs": runs, "rates": rates, "staff": staff,
            "deductions": deductions(con),
            "without_rate": [s["name"] for s in staff
                             if s["employment"] == "employee" and not s["rate"]],
            "kinds": list(KINDS), "sides": list(SIDES),
            "note": "No tax tables live here. Deductions are the rates you "
                    "type, and nothing is filed with anybody."}


@router.get("/api/payroll/runs/{rid}")
def run_detail(rid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM pay_runs WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    return {**shape_run(r), "payslips": [shape_slip(x) for x in con.execute(
        "SELECT * FROM payslips WHERE run_id=? ORDER BY name",
        (rid,)).fetchall()]}


class RunBody(BaseModel):
    label: str
    period_start: float
    period_end: float
    pay_date: float = 0


@router.post("/api/payroll/runs")
def run_add(body: RunBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    if body.period_end <= body.period_start:
        raise HTTPException(400, "a period ends after it starts")
    if not body.label.strip():
        raise HTTPException(400, "name the run — 'March' or 'week 12'")
    clash = con.execute(
        "SELECT label FROM pay_runs WHERE state<>'cancelled'"
        " AND period_start < ? AND period_end > ?",
        (body.period_end, body.period_start)).fetchone()
    if clash:
        raise HTTPException(
            400, f"{clash['label']} already covers part of that period, and "
                 "two runs over the same hours pay them twice")
    cur = con.execute(
        "INSERT INTO pay_runs(label,period_start,period_end,pay_date,created_at)"
        " VALUES(?,?,?,?,?)",
        (body.label.strip()[:60], body.period_start, body.period_end,
         body.pay_date, db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.post("/api/payroll/runs/{rid}/build")
def run_build(rid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return build(con, CFG, rid)


class DecideBody(BaseModel):
    note: str = ""


@router.post("/api/payroll/runs/{rid}/approve")
def run_approve(rid: int, body: DecideBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM pay_runs WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    if r["state"] != "draft":
        raise HTTPException(400, f"that run is already {r['state']}")
    n = con.execute("SELECT COUNT(*) AS n FROM payslips WHERE run_id=?",
                    (rid,)).fetchone()["n"]
    if not n:
        raise HTTPException(400, "build it first — an empty run approves "
                                 "nothing and reads as if it did")
    con.execute("UPDATE pay_runs SET state='approved', approved_by=?,"
                " approved_at=?, note=? WHERE id=?",
                (user["name"], time.time(), body.note.strip()[:400], rid))
    con.commit()
    return {"ok": True}


@router.post("/api/payroll/runs/{rid}/paid")
def run_paid(rid: int, body: DecideBody, user=Depends(current_user),
             con=Depends(get_con)):
    """Mark it paid, and put it in the books. Until this the wage is a
    liability; after it, money has left."""
    _require(user)
    r = con.execute("SELECT * FROM pay_runs WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    if r["state"] != "approved":
        raise HTTPException(400, "approve it first")
    now = time.time()
    con.execute("UPDATE pay_runs SET state='paid', paid_at=?, pay_date=?"
                " WHERE id=?", (now, r["pay_date"] or now, rid))
    con.commit()
    jid = 0
    posted = ""
    try:
        r = con.execute("SELECT * FROM pay_runs WHERE id=?", (rid,)).fetchone()
        jid = post_to_books(con, r)
        con.execute("UPDATE pay_runs SET journal_id=? WHERE id=?", (jid, rid))
        con.commit()
    except HTTPException as e:
        # The run IS paid; the books simply could not take it, most often
        # because the period is closed. Said out loud rather than swallowed.
        posted = str(e.detail)
    return {"ok": True, "journal_id": jid, "posting_problem": posted}


@router.post("/api/payroll/runs/{rid}/cancel")
def run_cancel(rid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM pay_runs WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    if r["state"] == "paid":
        raise HTTPException(400, "a paid run is history — reverse its "
                                 "journal in the books instead")
    con.execute("UPDATE pay_runs SET state='cancelled' WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


class RateBody(BaseModel):
    user_id: int
    kind: str = "hourly"
    rate_cents: int
    overtime_bps: int = 15000
    effective_from: float = 0
    note: str = ""


@router.post("/api/payroll/rates")
def rate_add(body: RateBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    if body.rate_cents <= 0:
        raise HTTPException(400, "a rate above zero")
    if body.overtime_bps < 10000:
        raise HTTPException(400, "overtime cannot be worth less than the "
                                 "hour it was")
    if con.execute("SELECT 1 FROM users WHERE id=? AND active=1",
                   (body.user_id,)).fetchone() is None:
        raise HTTPException(404, "no such person")
    cur = con.execute(
        "INSERT INTO payroll_rates(user_id,kind,rate_cents,overtime_bps,"
        " effective_from,note,created_at) VALUES(?,?,?,?,?,?,?)",
        (body.user_id, body.kind, body.rate_cents, body.overtime_bps,
         body.effective_from or time.time(), body.note.strip()[:200], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class DeductionBody(BaseModel):
    id: int = 0
    code: str
    label: str
    kind: str = "percent"
    rate_bps: int = 0
    amount_cents: int = 0
    side: str = "employee"
    of_remaining: bool = False
    position: int = 0
    active: bool = True
    note: str = ""


@router.post("/api/payroll/deductions")
def deduction_save(body: DeductionBody, user=Depends(current_user),
                   con=Depends(get_con)):
    _require(user)
    if body.kind not in ("percent", "fixed"):
        raise HTTPException(400, "percent or fixed")
    if body.side not in SIDES:
        raise HTTPException(400, f"side is one of {SIDES}")
    if body.kind == "percent" and not 0 <= body.rate_bps <= 10000:
        raise HTTPException(400, "a percentage between 0 and 100")
    if body.kind == "fixed" and body.amount_cents < 0:
        raise HTTPException(400, "an amount at or above zero")
    args = (body.code.strip()[:40], body.label.strip()[:120], body.kind,
            body.rate_bps, body.amount_cents, body.side,
            int(body.of_remaining), body.position, int(body.active),
            body.note.strip()[:200])
    if body.id:
        con.execute(
            "UPDATE pay_deductions SET code=?, label=?, kind=?, rate_bps=?,"
            " amount_cents=?, side=?, of_remaining=?, position=?, active=?,"
            " note=? WHERE id=?", args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO pay_deductions(code,label,kind,rate_bps,amount_cents,"
        " side,of_remaining,position,active,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
        args)
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.get("/api/payroll/mine")
def my_payslips(user=Depends(current_user), con=Depends(get_con)):
    """My own payslips. Everybody sees their own, in full, including how
    the gross was reached — a number somebody cannot see the working of
    is a number they cannot dispute."""
    return {"payslips": [
        {**shape_slip(r), "run_label": r["label"], "state": r["state"],
         "paid_at": r["paid_at"]}
        for r in con.execute(
            "SELECT s.*, p.label, p.state, p.paid_at FROM payslips s"
            " JOIN pay_runs p ON p.id=s.run_id WHERE s.user_id=?"
            " AND p.state IN ('approved','paid')"
            " ORDER BY p.period_start DESC", (user["id"],)).fetchall()]}
