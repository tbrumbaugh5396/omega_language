"""The annual report: the year, added up, with the words around it.

Everything here was already in the database as dated rows — orders,
seats, sessions, hours, payslips, expenses, gifts, tickets. What was
missing was the one page a board, a funder, a landlord or the owner's
own family asks for in January: what happened last year, in numbers a
reader can check and in a letter somebody wrote. The numbers are
derived every time from the rows, so the report is never a spreadsheet
that drifted from the books. The words are kept, by year, because they
are the part nobody can regenerate.

It adds up what the install has. A shop with no classroom has a
learning section that says so rather than a row of zeros dressed as a
finding, and a table that does not exist on an older install is a
section that is absent, not an error.
"""
import calendar
import csv
import io
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS annual_reports (
  year INTEGER PRIMARY KEY,
  title TEXT DEFAULT '',
  letter TEXT DEFAULT '',                  -- from the owner / the board
  highlights TEXT DEFAULT '[]',            -- JSON list of lines
  thanks TEXT DEFAULT '',
  published INTEGER DEFAULT 0,
  by_name TEXT DEFAULT '',
  updated_at REAL DEFAULT 0
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "analytics", "settings") or user["role"] in ("director", "board")


def span(year: int) -> tuple:
    return (time.mktime((year, 1, 1, 0, 0, 0, 0, 0, -1)),
            time.mktime((year + 1, 1, 1, 0, 0, 0, 0, 0, -1)))


def _has(con, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone() is not None


def _n(con, sql: str, args=()) -> int:
    r = con.execute(sql, args).fetchone()
    return int(r[0] or 0) if r else 0


def _by_month(con, sql: str, args, year: int) -> list:
    """Twelve buckets from a query returning (month_index_0_11, value)."""
    out = [0] * 12
    for r in con.execute(sql, args).fetchall():
        m = int(r[0])
        if 0 <= m < 12:
            out[m] = int(r[1] or 0)
    return out


def annual(con, year: int) -> dict:
    a, b = span(year)
    w = (a, b)
    month = "CAST(strftime('%m', {col}, 'unixepoch', 'localtime') AS INTEGER)-1"
    out = {"year": year, "from": a, "to": b, "sections": {}}

    # ---- sales ----
    if _has(con, "orders"):
        paid = ("SELECT {agg} FROM orders WHERE created_at>=? AND created_at<?"
                " AND status NOT IN ('cancelled','refunded','void')")
        s = {
            "orders": _n(con, paid.format(agg="COUNT(*)"), w),
            "revenue_cents": _n(con, paid.format(agg="COALESCE(SUM(total_cents),0)"), w),
            "donations_cents": _n(con, paid.format(agg="COALESCE(SUM(donation_cents),0)"), w),
            "by_month_cents": _by_month(con,
                "SELECT " + month.format(col="created_at") + ", SUM(total_cents)"
                " FROM orders WHERE created_at>=? AND created_at<?"
                " AND status NOT IN ('cancelled','refunded','void') GROUP BY 1", w, year),
            "new_customers": _n(con, "SELECT COUNT(*) FROM users WHERE role='customer'"
                                " AND created_at>=? AND created_at<?", w),
            "customers_who_bought": _n(con, "SELECT COUNT(DISTINCT user_id) FROM orders"
                                       " WHERE created_at>=? AND created_at<? AND user_id>0", w),
            "returning": _n(con, "SELECT COUNT(DISTINCT o.user_id) FROM orders o"
                            " WHERE o.created_at>=? AND o.created_at<? AND o.user_id>0"
                            " AND EXISTS (SELECT 1 FROM orders p WHERE p.user_id=o.user_id"
                            " AND p.created_at<?)", (a, b, a)),
            "top_products": [dict(r) for r in con.execute(
                "SELECT p.name, SUM(oi.qty) AS qty, SUM(oi.qty*oi.unit_price_cents) AS cents"
                " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
                " JOIN products p ON p.id=oi.product_id"
                " WHERE o.created_at>=? AND o.created_at<?"
                " GROUP BY p.id ORDER BY cents DESC LIMIT 8", w).fetchall()],
        }
        s["average_order_cents"] = s["revenue_cents"] // s["orders"] if s["orders"] else 0
        out["sections"]["sales"] = s

    # ---- learning ----
    if _has(con, "enrollments"):
        s = {
            "students": _n(con, "SELECT COUNT(DISTINCT user_id) FROM enrollments"
                           " WHERE since<? AND (until IS NULL OR until>=?)", (b, a)),
            "new_seats": _n(con, "SELECT COUNT(*) FROM enrollments WHERE since>=? AND since<?", w),
            "courses": _n(con, "SELECT COUNT(DISTINCT course_id) FROM enrollments"
                          " WHERE since<? AND (until IS NULL OR until>=?)", (b, a)),
        }
        if _has(con, "class_sessions"):
            s["sessions_held"] = _n(con, "SELECT COUNT(*) FROM class_sessions"
                                    " WHERE started_at>=? AND started_at<?", w)
        if _has(con, "checkins"):
            s["attendances"] = _n(con, "SELECT COUNT(*) FROM checkins WHERE at>=? AND at<?"
                                  " AND status IN ('present','late')", w)
        if _has(con, "quiz_attempts"):
            s["quizzes_taken"] = _n(con, "SELECT COUNT(*) FROM quiz_attempts"
                                    " WHERE submitted_at>=? AND submitted_at<?", w)
        if _has(con, "student_applications"):
            s["applications_opened"] = _n(con, "SELECT COUNT(*) FROM student_applications"
                                          " WHERE created_at>=? AND created_at<?", w)
            s["applications_accepted"] = _n(con, "SELECT COUNT(*) FROM student_applications"
                                            " WHERE decided_at>=? AND decided_at<?"
                                            " AND stage IN ('accepted','enrolled')", w)
        out["sections"]["learning"] = s

    # ---- people ----
    staff_roles = "('employee','owner','teacher','volunteer','director','cashier')"
    s = {
        "staff_at_end": _n(con, "SELECT COUNT(*) FROM users WHERE active=1 AND"
                           " erased_at IS NULL AND (is_admin=1 OR role IN " + staff_roles + ")"
                           " AND created_at<?", (b,)),
        "joined": _n(con, "SELECT COUNT(*) FROM users WHERE (is_admin=1 OR role IN "
                     + staff_roles + ") AND created_at>=? AND created_at<?", w),
    }
    if _has(con, "departures"):
        s["left"] = _n(con, "SELECT COUNT(*) FROM departures WHERE last_day>=? AND last_day<?", w)
    if _has(con, "shifts"):
        s["hours_worked"] = round(_n(con, "SELECT COALESCE(SUM(clock_out-clock_in),0)"
                                     " FROM shifts WHERE clock_out>0 AND clock_in>=?"
                                     " AND clock_in<?", w) / 3600, 1)
    if _has(con, "payslips"):
        s["payroll_gross_cents"] = _n(con, "SELECT COALESCE(SUM(gross_cents),0) FROM payslips"
                                      " WHERE created_at>=? AND created_at<?", w)
        s["payroll_net_cents"] = _n(con, "SELECT COALESCE(SUM(net_cents),0) FROM payslips"
                                    " WHERE created_at>=? AND created_at<?", w)
    if _has(con, "applicants"):
        s["applicants"] = _n(con, "SELECT COUNT(*) FROM applicants"
                             " WHERE created_at>=? AND created_at<?", w)
    out["sections"]["people"] = s

    # ---- money out, and money given ----
    s = {}
    if _has(con, "expenses"):
        s["expenses_cents"] = _n(con, "SELECT COALESCE(SUM(amount_cents*business_pct/100.0),0)"
                                 " FROM expenses WHERE spent_at>=? AND spent_at<?"
                                 " AND state IN ('approved','paid')", w)
        s["expenses_by_category"] = [dict(r) for r in con.execute(
            "SELECT category, SUM(amount_cents*business_pct/100.0) AS cents, COUNT(*) AS n"
            " FROM expenses WHERE spent_at>=? AND spent_at<? AND state IN ('approved','paid')"
            " GROUP BY category ORDER BY cents DESC LIMIT 12", w).fetchall()]
        for r in s["expenses_by_category"]:
            r["cents"] = int(r["cents"] or 0)
    if _has(con, "invoices"):
        s["invoices_issued"] = _n(con, "SELECT COUNT(*) FROM invoices WHERE issued_at>=?"
                                  " AND issued_at<? AND state<>'void'", w)
        s["invoiced_cents"] = _n(con, "SELECT COALESCE(SUM(total_cents),0) FROM invoices"
                                 " WHERE issued_at>=? AND issued_at<? AND state<>'void'", w)
        s["invoices_collected_cents"] = _n(con, "SELECT COALESCE(SUM(paid_cents),0) FROM invoices"
                                           " WHERE issued_at>=? AND issued_at<?", w)
    if _has(con, "gifts"):
        s["gifts_cents"] = _n(con, "SELECT COALESCE(SUM(amount_cents),0) FROM gifts"
                              " WHERE at>=? AND at<?", w)
        s["gifts"] = _n(con, "SELECT COUNT(*) FROM gifts WHERE at>=? AND at<?", w)
        s["donors"] = _n(con, "SELECT COUNT(DISTINCT COALESCE(NULLIF(email,''), donor))"
                         " FROM gifts WHERE at>=? AND at<?", w)
    if _has(con, "contributions"):
        s["political_giving_cents"] = _n(con, "SELECT COALESCE(SUM(amount_cents),0)"
                                         " FROM contributions WHERE at>=? AND at<?", w)
    if s:
        out["sections"]["money"] = s

    # ---- the books, when they are kept ----
    if _has(con, "journal_lines") and _n(con, "SELECT COUNT(*) FROM journals"
                                          " WHERE at>=? AND at<? AND reversed_by IS NULL", w):
        def acct(prefix: str, side: str) -> int:
            other = "debit_cents" if side == "credit_cents" else "credit_cents"
            return _n(con, f"SELECT COALESCE(SUM(l.{side}-l.{other}),0) FROM journal_lines l"
                      " JOIN journals j ON j.id=l.journal_id WHERE j.at>=? AND j.at<?"
                      " AND j.reversed_by IS NULL AND l.account LIKE ?",
                      (a, b, prefix + "%"))
        income = acct("4", "credit_cents")
        cogs = acct("5", "debit_cents")
        opex = acct("6", "debit_cents")
        out["sections"]["books"] = {"income_cents": income, "cost_of_sales_cents": cogs,
                                    "operating_cents": opex,
                                    "surplus_cents": income - cogs - opex}

    # ---- service ----
    s = {}
    if _has(con, "tickets"):
        s["tickets_closed"] = _n(con, "SELECT COUNT(*) FROM tickets WHERE closed_at>=?"
                                 " AND closed_at<?", w)
    if _has(con, "store_tickets"):
        s["support_requests"] = _n(con, "SELECT COUNT(*) FROM store_tickets"
                                   " WHERE created_at>=? AND created_at<?", w)
    if _has(con, "appointments"):
        s["appointments"] = _n(con, "SELECT COUNT(*) FROM appointments WHERE starts>=?"
                               " AND starts<? AND state NOT IN ('held','cancelled')", w)
    if _has(con, "store_events"):
        s["events_held"] = _n(con, "SELECT COUNT(*) FROM store_events WHERE starts>=?"
                              " AND starts<?", w)
    if s:
        out["sections"]["service"] = s

    out["months"] = [calendar.month_abbr[m] for m in range(1, 13)]
    r = con.execute("SELECT * FROM annual_reports WHERE year=?", (year,)).fetchone()
    import json
    out["words"] = ({**dict(r), "highlights": json.loads(r["highlights"] or "[]")} if r
                    else {"year": year, "title": "", "letter": "", "highlights": [],
                          "thanks": "", "published": 0, "by_name": "", "updated_at": 0})
    return out


def years_with_data(con) -> list:
    ys = set()
    for table, col in (("orders", "created_at"), ("enrollments", "since"),
                       ("shifts", "clock_in"), ("expenses", "spent_at"),
                       ("gifts", "at")):
        if _has(con, table):
            for r in con.execute(f"SELECT DISTINCT strftime('%Y', {col}, 'unixepoch',"
                                 f" 'localtime') AS y FROM {table} WHERE {col}>0").fetchall():
                if r["y"]:
                    ys.add(int(r["y"]))
    for r in con.execute("SELECT year FROM annual_reports").fetchall():
        ys.add(int(r["year"]))
    ys.add(time.localtime().tm_year)
    return sorted(ys, reverse=True)


def flat(rep: dict) -> list:
    rows = []
    for sec, vals in rep["sections"].items():
        for k, v in vals.items():
            if isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        for kk, vv in item.items():
                            rows.append((sec, f"{k}[{i}].{kk}", vv))
                    else:
                        rows.append((sec, f"{k}[{i}]", item))
            else:
                rows.append((sec, k, v))
    return rows


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _year(y: int) -> int:
    if not y:
        return time.localtime().tm_year
    if y < 2000 or y > 2100:
        raise HTTPException(400, "a year between 2000 and 2100")
    return y


@router.get("/api/reports/annual")
def annual_report(year: int = 0, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "the annual report is the office's and the board's")
    from .main import CFG
    rep = annual(con, _year(year))
    # The year before, flattened, so every number can say how it moved.
    # Derived the same way, so the comparison is between like and like.
    prior = annual(con, rep["year"] - 1)
    rep["prior"] = {sec: {k: v for k, v in vals.items() if not isinstance(v, list)}
                    for sec, vals in prior["sections"].items()}
    rep["prior"]["_months"] = (prior["sections"].get("sales") or {}).get("by_month_cents", [])
    rep["years"] = years_with_data(con)
    rep["brand"] = CFG.get("brand_name") or ""
    return rep


@router.get("/api/reports/annual.csv")
def annual_csv(year: int = 0, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "the annual report is the office's and the board's")
    y = _year(year)
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["year", "section", "measure", "value"])
    for sec, k, v in flat(annual(con, y)):
        wr.writerow([y, sec, k, v])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="annual-{y}.csv"'})


class WordsBody(BaseModel):
    year: int
    title: str = ""
    letter: str = ""
    highlights: list = []
    thanks: str = ""
    published: bool = False


@router.post("/api/reports/annual")
def annual_words(body: WordsBody, user=Depends(current_user), con=Depends(get_con)):
    """The part nobody can regenerate: what the year meant, in the
    owner's or the board's words, kept by year."""
    if not _office(user):
        raise HTTPException(403, "the annual report is the office's and the board's")
    import json
    y = _year(body.year)
    hl = [str(h).strip()[:300] for h in body.highlights if str(h).strip()][:20]
    con.execute(
        "INSERT INTO annual_reports(year,title,letter,highlights,thanks,published,"
        " by_name,updated_at) VALUES(?,?,?,?,?,?,?,?)"
        " ON CONFLICT(year) DO UPDATE SET title=excluded.title, letter=excluded.letter,"
        " highlights=excluded.highlights, thanks=excluded.thanks,"
        " published=excluded.published, by_name=excluded.by_name,"
        " updated_at=excluded.updated_at",
        (y, body.title.strip()[:200], body.letter.strip()[:20000], json.dumps(hl),
         body.thanks.strip()[:4000], int(body.published), user["name"], db.now()))
    con.commit()
    return {"ok": True, "year": y}
