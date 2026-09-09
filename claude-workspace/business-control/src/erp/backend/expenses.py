"""Money out, and what the tax return will want to know about it.

The books already knew what came in: every order, every donation, the
sales tax charged on each. They knew nothing about what went out except
what the system itself caused — shifts, routes, contractor pay. The
phone bill, the web hosting, the fuel, the miles somebody drove in their
own car to a client: all of that lived in a shoebox until April.

Three things live here.

  * **Expenses.** One row per thing paid for, in a category the return
    recognises, with the business share of it (a phone used half for
    work is half a deduction), the receipt, and who paid — the company,
    or a person who wants the money back.
  * **Trips.** Miles driven for the business, at the rate the tax
    authority allows, which is how a driver in their own car gets
    reimbursed and how the business deducts the wear it never invoiced.
    A finished route imports as one trip, so a driver does not type the
    odometer twice.
  * **The year.** Income, sales tax collected, deductible expenses,
    mileage, what is owed to people, and a rough estimate of the tax on
    what is left — one page, and a CSV for whoever files the return.

Claims wait for the office, like time off and logged hours do: a
reimbursement is a payment, and a payment somebody approved to
themselves is the first thing an auditor looks for.
"""
import csv
import io
import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from . import db

TABLES = """
CREATE TABLE IF NOT EXISTS expense_categories (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  deductible INTEGER NOT NULL DEFAULT 1,
  default_pct INTEGER NOT NULL DEFAULT 100,   -- business share, by default
  hint TEXT DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,                  -- who filed it
  category TEXT NOT NULL,
  vendor TEXT DEFAULT '',
  amount_cents INTEGER NOT NULL,
  spent_at REAL NOT NULL,
  note TEXT DEFAULT '',
  business_pct INTEGER NOT NULL DEFAULT 100,
  paid_by TEXT NOT NULL DEFAULT 'company',   -- company | me (a claim)
  recurring TEXT DEFAULT '',                 -- '' | monthly | yearly
  receipt_path TEXT DEFAULT '',
  receipt_name TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',     -- see STATES
  decided_by TEXT DEFAULT '',
  decided_at REAL DEFAULT 0,
  decided_note TEXT DEFAULT '',
  paid_at REAL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS expenses_when ON expenses(spent_at);
CREATE INDEX IF NOT EXISTS expenses_who ON expenses(user_id, state);

CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  driven_at REAL NOT NULL,
  from_place TEXT DEFAULT '',
  to_place TEXT DEFAULT '',
  purpose TEXT DEFAULT '',
  distance REAL NOT NULL,                    -- in `unit`
  unit TEXT NOT NULL DEFAULT 'mi',
  start_odo REAL,
  end_odo REAL,
  vehicle TEXT NOT NULL DEFAULT 'own',       -- own | company
  truck_id INTEGER DEFAULT 0,
  route_id INTEGER DEFAULT 0,
  rate_cents INTEGER NOT NULL DEFAULT 0,     -- per unit, at the time
  amount_cents INTEGER NOT NULL DEFAULT 0,
  note TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT DEFAULT '',
  decided_at REAL DEFAULT 0,
  decided_note TEXT DEFAULT '',
  paid_at REAL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS trips_when ON trips(driven_at);
CREATE INDEX IF NOT EXISTS trips_who ON trips(user_id, state);
"""

STATES = ("pending", "approved", "declined", "paid", "withdrawn")
PAID_BY = ("company", "me")
RECURRING = ("", "monthly", "yearly")
VEHICLES = ("own", "company")
UNITS = ("mi", "km")
MAX_DISTANCE = 2000

# The categories a small business's return actually has lines for. A
# school or a shop will not use all of them; nobody should have to invent
# the ones they do use.
DEFAULT_CATEGORIES = (
    ("phone", "Phone", 1, 50, "the business share of a personal line"),
    ("internet", "Internet", 1, 50, ""),
    ("hosting", "Web hosting & domains", 1, 100, ""),
    ("software", "Software & subscriptions", 1, 100, ""),
    ("office", "Office & supplies", 1, 100, ""),
    ("equipment", "Equipment", 1, 100, "computers, tools, furniture"),
    ("rent", "Rent & utilities", 1, 100, ""),
    ("fuel", "Fuel", 1, 100, "for a company vehicle — own-car miles go under trips"),
    ("vehicle", "Vehicle wear & repairs", 1, 100, "tyres, servicing, insurance on a work vehicle"),
    ("parking", "Parking & tolls", 1, 100, ""),
    ("travel", "Travel & lodging", 1, 100, ""),
    ("meals", "Meals", 1, 50, "often only half is allowed — check your rules"),
    ("insurance", "Insurance", 1, 100, ""),
    ("fees", "Professional fees", 1, 100, "accountant, lawyer, licences"),
    ("marketing", "Marketing", 1, 100, ""),
    ("training", "Training & books", 1, 100, ""),
    ("bank", "Bank & payment fees", 1, 100, ""),
    ("materials", "Teaching materials", 1, 100, ""),
    ("gifts", "Gifts & entertainment", 1, 25, "rarely fully deductible"),
    ("personal", "Personal (not deductible)", 0, 0, "kept for the record, counted nowhere"),
    ("other", "Other", 1, 100, ""),
)


def init_tables(con):
    con.executescript(TABLES)
    have = {r["code"] for r in con.execute("SELECT code FROM expense_categories")}
    for i, (code, label, ded, pct, hint) in enumerate(DEFAULT_CATEGORIES):
        if code not in have:
            con.execute(
                "INSERT INTO expense_categories(code,label,deductible,"
                " default_pct,hint,position) VALUES(?,?,?,?,?,?)",
                (code, label, ded, pct, hint, i))
    con.commit()


# ── settings ─────────────────────────────────────────────────────────────────

def settings(cfg) -> dict:
    """The knobs the return depends on, with honest defaults: the unit
    and rate are whatever the local tax authority publishes, and the
    income-tax percentage is an estimate for a page, not advice."""
    unit = cfg.get("distance_unit", "mi")
    return {
        "distance_unit": unit if unit in UNITS else "mi",
        "mileage_rate_cents": int(cfg.get("mileage_rate_cents", 70)),
        "income_tax_pct": float(cfg.get("income_tax_pct", 25)),
        "tax_year_start_month": int(cfg.get("tax_year_start_month", 1)),
        "sales_tax_bps": int(cfg.get("tax_bps", 0)),
        "currency": cfg.get("currency", "USD"),
    }


def year_bounds(cfg, year: int) -> tuple:
    """A tax year that starts in April is a thing; `year` names the year
    it starts in."""
    m = int(cfg.get("tax_year_start_month", 1))
    m = m if 1 <= m <= 12 else 1
    a = datetime(year, m, 1).timestamp()
    b = datetime(year + 1, m, 1).timestamp()
    return a, b


def current_year(cfg) -> int:
    m = int(cfg.get("tax_year_start_month", 1))
    t = date.today()
    return t.year if t.month >= m else t.year - 1


# ── who ──────────────────────────────────────────────────────────────────────

def _office(user) -> bool:
    if user["is_admin"] or user["role"] == "owner":
        return True
    perms = (user["permissions"] or "").split(",")
    return any(p.strip() in ("*", "settings", "finance") for p in perms)


def _require_office(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the books are the office's")


def _may_file(user) -> bool:
    return bool(user["is_admin"] or user["role"] in (
        "employee", "teacher", "volunteer", "director", "owner",
        "cashier", "distributor"))


# ── shapes ───────────────────────────────────────────────────────────────────

def categories(con) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM expense_categories WHERE active=1"
        " ORDER BY position, label")]


def _cat_map(con) -> dict:
    return {c["code"]: c for c in con.execute("SELECT * FROM expense_categories")}


def deductible_cents(row: dict, cat: dict | None) -> int:
    if cat is not None and not cat["deductible"]:
        return 0
    pct = max(0, min(100, int(row.get("business_pct") or 0)))
    return int(round(row["amount_cents"] * pct / 100))


def _expense_row(r, cats: dict) -> dict:
    d = dict(r)
    c = cats.get(d["category"])
    d["category_label"] = c["label"] if c else d["category"]
    d["deductible_cents"] = deductible_cents(d, c)
    d["receipt_url"] = f"/media/{d['receipt_path']}" if d["receipt_path"] else ""
    return d


# ── the year ─────────────────────────────────────────────────────────────────

COUNTED = ("approved", "paid")


def summary(con, cfg, year: int) -> dict:
    a, b = year_bounds(cfg, year)
    cats = _cat_map(con)
    income = con.execute(
        "SELECT COALESCE(SUM(subtotal_cents),0) AS s,"
        " COALESCE(SUM(tax_cents),0) AS t, COUNT(*) AS n FROM orders"
        " WHERE created_at>=? AND created_at<? AND status!='cancelled'",
        (a, b)).fetchone()
    by_cat: dict = {}
    total = deductible = 0
    for r in con.execute(
            "SELECT * FROM expenses WHERE spent_at>=? AND spent_at<?"
            " AND state IN ('approved','paid')", (a, b)):
        d = _expense_row(r, cats)
        k = by_cat.setdefault(d["category"], {
            "code": d["category"], "label": d["category_label"],
            "total_cents": 0, "deductible_cents": 0, "count": 0})
        k["total_cents"] += d["amount_cents"]
        k["deductible_cents"] += d["deductible_cents"]
        k["count"] += 1
        total += d["amount_cents"]
        deductible += d["deductible_cents"]
    trips = con.execute(
        "SELECT COALESCE(SUM(distance),0) AS d, COALESCE(SUM(amount_cents),0)"
        " AS c, COUNT(*) AS n FROM trips WHERE driven_at>=? AND driven_at<?"
        " AND state IN ('approved','paid')", (a, b)).fetchone()
    owed_e = con.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM expenses WHERE state="
        "'approved' AND paid_by='me'").fetchone()[0]
    owed_t = con.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM trips WHERE state="
        "'approved' AND vehicle='own'").fetchone()[0]
    pending_e = con.execute(
        "SELECT COUNT(*) FROM expenses WHERE state='pending'").fetchone()[0]
    pending_t = con.execute(
        "SELECT COUNT(*) FROM trips WHERE state='pending'").fetchone()[0]
    s = settings(cfg)
    net = income["s"] - deductible - trips["c"]
    est = int(round(max(0, net) * s["income_tax_pct"] / 100))
    return {
        "year": year, "from": a, "to": b,
        "income_cents": income["s"], "orders": income["n"],
        "sales_tax_collected_cents": income["t"],
        "expenses_total_cents": total, "deductible_cents": deductible,
        "by_category": sorted(by_cat.values(),
                              key=lambda k: -k["deductible_cents"]),
        "mileage": {"distance": round(trips["d"], 1), "unit": s["distance_unit"],
                    "amount_cents": trips["c"], "trips": trips["n"]},
        "net_before_tax_cents": net,
        "estimated_tax_cents": est,
        "estimate_note": (
            f"{s['income_tax_pct']:g}% of what is left after deductible "
            f"expenses and mileage. A page's estimate, not a return: your "
            f"accountant's rules on depreciation, home office and what "
            f"counts will move it."),
        "owed_cents": owed_e + owed_t,
        "pending": pending_e + pending_t,
        "settings": s,
    }


def owed_by_person(con) -> list:
    rows: dict = {}
    for r in con.execute(
            "SELECT e.user_id, u.name, e.amount_cents FROM expenses e"
            " JOIN users u ON u.id=e.user_id WHERE e.state='approved'"
            " AND e.paid_by='me'"):
        k = rows.setdefault(r["user_id"], {"user_id": r["user_id"],
                                           "name": r["name"], "cents": 0,
                                           "items": 0})
        k["cents"] += r["amount_cents"]; k["items"] += 1
    for r in con.execute(
            "SELECT t.user_id, u.name, t.amount_cents FROM trips t"
            " JOIN users u ON u.id=t.user_id WHERE t.state='approved'"
            " AND t.vehicle='own'"):
        k = rows.setdefault(r["user_id"], {"user_id": r["user_id"],
                                           "name": r["name"], "cents": 0,
                                           "items": 0})
        k["cents"] += r["amount_cents"]; k["items"] += 1
    return sorted(rows.values(), key=lambda k: -k["cents"])


# ── routes ───────────────────────────────────────────────────────────────────

router = APIRouter()

from .main import CFG, current_user, get_con  # noqa: E402  (safe: included late)
from . import config as _config  # noqa: E402


@router.get("/api/expenses/meta")
def meta(user=Depends(current_user), con=Depends(get_con)):
    trucks = [dict(r) for r in con.execute(
        "SELECT id, name FROM trucks WHERE active=1 ORDER BY name")]
    return {"categories": categories(con), "settings": settings(CFG),
            "office": _office(user), "may_file": _may_file(user),
            "trucks": trucks, "year": current_year(CFG), "me": user["id"],
            "states": list(STATES)}


class SettingsBody(BaseModel):
    distance_unit: str | None = None
    mileage_rate_cents: int | None = None
    income_tax_pct: float | None = None
    tax_year_start_month: int | None = None


@router.post("/api/expenses/settings")
def set_settings(body: SettingsBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require_office(user)
    if body.distance_unit is not None:
        if body.distance_unit not in UNITS:
            raise HTTPException(400, "unit is mi or km")
        CFG["distance_unit"] = body.distance_unit
    if body.mileage_rate_cents is not None:
        if not 0 <= body.mileage_rate_cents <= 1000:
            raise HTTPException(400, "a rate is cents per mile or km")
        CFG["mileage_rate_cents"] = int(body.mileage_rate_cents)
    if body.income_tax_pct is not None:
        if not 0 <= body.income_tax_pct <= 100:
            raise HTTPException(400, "a percentage")
        CFG["income_tax_pct"] = float(body.income_tax_pct)
    if body.tax_year_start_month is not None:
        if not 1 <= body.tax_year_start_month <= 12:
            raise HTTPException(400, "a month, 1-12")
        CFG["tax_year_start_month"] = int(body.tax_year_start_month)
    _config.save(CFG)
    return {"ok": True, "settings": settings(CFG)}


class CategoryBody(BaseModel):
    code: str
    label: str
    deductible: bool = True
    default_pct: int = 100
    hint: str = ""
    active: bool = True


@router.post("/api/expenses/categories")
def save_category(body: CategoryBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require_office(user)
    code = "".join(ch for ch in body.code.strip().lower()
                   if ch.isalnum() or ch in "-_")[:40]
    if not code or not body.label.strip():
        raise HTTPException(400, "a code and a label")
    n = con.execute("SELECT COUNT(*) FROM expense_categories").fetchone()[0]
    con.execute(
        "INSERT INTO expense_categories(code,label,deductible,default_pct,"
        " hint,position,active) VALUES(?,?,?,?,?,?,?)"
        " ON CONFLICT(code) DO UPDATE SET label=excluded.label,"
        " deductible=excluded.deductible, default_pct=excluded.default_pct,"
        " hint=excluded.hint, active=excluded.active",
        (code, body.label.strip()[:80], int(body.deductible),
         max(0, min(100, body.default_pct)), body.hint.strip()[:200], n,
         int(body.active)))
    con.commit()
    return {"ok": True, "categories": categories(con)}


# ---- expenses ----

@router.get("/api/expenses")
def list_expenses(mine: int = 0, state: str = "", year: int = 0,
                  category: str = "", user=Depends(current_user),
                  con=Depends(get_con)):
    cats = _cat_map(con)
    q = ("SELECT e.*, u.name AS who FROM expenses e"
         " JOIN users u ON u.id=e.user_id")
    where, args = [], []
    if mine or not _office(user):
        where.append("e.user_id=?"); args.append(user["id"])
    if state in STATES:
        where.append("e.state=?"); args.append(state)
    if year:
        a, b = year_bounds(CFG, year)
        where.append("e.spent_at>=? AND e.spent_at<?"); args += [a, b]
    if category:
        where.append("e.category=?"); args.append(category)
    if where:
        q += " WHERE " + " AND ".join(where)
    rows = con.execute(
        q + " ORDER BY e.state='pending' DESC, e.spent_at DESC LIMIT 500",
        tuple(args)).fetchall()
    return {"expenses": [_expense_row(r, cats) for r in rows],
            "office": _office(user), "me": user["id"]}


class ExpenseBody(BaseModel):
    category: str
    amount_cents: int
    spent_at: float = 0
    vendor: str = ""
    note: str = ""
    business_pct: int | None = None
    paid_by: str = "company"
    recurring: str = ""
    user_id: int = 0


@router.post("/api/expenses")
def add_expense(body: ExpenseBody, user=Depends(current_user),
                con=Depends(get_con)):
    if not _may_file(user):
        raise HTTPException(403, "staff file expenses")
    cats = _cat_map(con)
    cat = cats.get(body.category)
    if cat is None or not cat["active"]:
        raise HTTPException(400, "pick a category")
    if body.amount_cents <= 0:
        raise HTTPException(400, "an amount")
    if body.amount_cents > 100_000_00:
        raise HTTPException(400, "that is a very large expense — file it"
                                 " with the office directly")
    if body.paid_by not in PAID_BY:
        raise HTTPException(400, "paid by the company, or by you")
    if body.recurring not in RECURRING:
        raise HTTPException(400, "recurring is monthly, yearly or blank")
    at = body.spent_at or time.time()
    if at > time.time() + 86400:
        raise HTTPException(400, "an expense is logged after it is paid")
    uid = user["id"]
    if body.user_id and body.user_id != user["id"]:
        _require_office(user)
        uid = body.user_id
    pct = cat["default_pct"] if body.business_pct is None else body.business_pct
    pct = max(0, min(100, int(pct)))
    # The office's own company-paid expense is a fact, not a claim — it
    # needs no second signature. Everything else waits.
    state = "approved" if (_office(user) and body.paid_by == "company"
                           and uid == user["id"]) else "pending"
    cur = con.execute(
        "INSERT INTO expenses(user_id,category,vendor,amount_cents,spent_at,"
        " note,business_pct,paid_by,recurring,state,decided_by,decided_at,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, body.category, body.vendor.strip()[:120], int(body.amount_cents),
         at, body.note.strip()[:400], pct, body.paid_by, body.recurring,
         state, user["name"] if state == "approved" else "",
         db.now() if state == "approved" else 0, db.now()))
    con.commit()
    row = con.execute("SELECT e.*, u.name AS who FROM expenses e JOIN users u"
                      " ON u.id=e.user_id WHERE e.id=?",
                      (cur.lastrowid,)).fetchone()
    return {"ok": True, **_expense_row(row, cats)}


@router.post("/api/expenses/{eid}/receipt")
async def expense_receipt(eid: int, request: Request,
                          user=Depends(current_user), con=Depends(get_con)):
    """The receipt, as a photo or a PDF. Kept with the expense, because
    a deduction without one is a story."""
    r = con.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such expense")
    if r["user_id"] != user["id"] and not _office(user):
        raise HTTPException(403, "not your expense")
    from . import materials as MAT
    data = await request.body()
    if not data:
        raise HTTPException(400, "an empty file")
    saved = MAT.save(data, allow=("image", "document"))
    if r["receipt_path"]:
        MAT.unlink(r["receipt_path"])
    name = request.headers.get("x-filename", "")[:120]
    con.execute("UPDATE expenses SET receipt_path=?, receipt_name=? WHERE id=?",
                (saved["path"], name, eid))
    con.commit()
    return {"ok": True, "receipt_url": f"/media/{saved['path']}",
            "receipt_name": name}


class DecideBody(BaseModel):
    state: str
    note: str = ""


def _decide(con, table: str, rid: int, body: DecideBody, user,
            owner_field: str = "user_id") -> dict:
    r = con.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such entry")
    if body.state not in ("approved", "declined", "paid", "withdrawn"):
        raise HTTPException(400, "approved, declined, paid or withdrawn")
    if body.state == "withdrawn":
        if r[owner_field] != user["id"] and not _office(user):
            raise HTTPException(403, "only the person who filed it withdraws it")
        if r["state"] not in ("pending",):
            raise HTTPException(409, f"it is already {r['state']}")
    else:
        _require_office(user)
        if r["state"] == body.state:
            raise HTTPException(409, f"it is already {r['state']}")
        if body.state == "paid" and r["state"] not in ("approved",):
            raise HTTPException(409, "approve it before paying it")
        if r[owner_field] == user["id"] and not user["is_admin"] \
                and body.state == "approved":
            raise HTTPException(400, "somebody else approves your own claim")
    paid_at = db.now() if body.state == "paid" else r["paid_at"]
    con.execute(
        f"UPDATE {table} SET state=?, decided_by=?, decided_at=?,"
        f" decided_note=?, paid_at=? WHERE id=?",
        (body.state, user["name"], db.now(), body.note.strip()[:300],
         paid_at, rid))
    con.commit()
    if body.state in ("approved", "declined", "paid") \
            and r[owner_field] != user["id"]:
        from . import notify
        try:
            what = ("trip" if table == "trips" else "expense")
            notify.push(con, f"{what.capitalize()} {body.state}",
                        f"{user['name']} marked your {what} of"
                        f" {r['amount_cents'] / 100:,.2f} {body.state}"
                        + (f": {body.note.strip()[:200]}"
                           if body.note.strip() else "."),
                        kind="info", user_id=r[owner_field])
        except Exception:                                    # noqa: BLE001
            pass
    return {"ok": True, "state": body.state}


@router.post("/api/expenses/{eid}/decide")
def decide_expense(eid: int, body: DecideBody, user=Depends(current_user),
                   con=Depends(get_con)):
    return _decide(con, "expenses", eid, body, user)


# ---- trips ----

def _trip_row(r) -> dict:
    d = dict(r)
    d["km"] = round(d["distance"] * (1.609344 if d["unit"] == "mi" else 1), 1)
    return d


@router.get("/api/trips")
def list_trips(mine: int = 0, state: str = "", year: int = 0,
               user=Depends(current_user), con=Depends(get_con)):
    q = ("SELECT t.*, u.name AS who, k.name AS truck FROM trips t"
         " JOIN users u ON u.id=t.user_id"
         " LEFT JOIN trucks k ON k.id=t.truck_id")
    where, args = [], []
    if mine or not _office(user):
        where.append("t.user_id=?"); args.append(user["id"])
    if state in STATES:
        where.append("t.state=?"); args.append(state)
    if year:
        a, b = year_bounds(CFG, year)
        where.append("t.driven_at>=? AND t.driven_at<?"); args += [a, b]
    if where:
        q += " WHERE " + " AND ".join(where)
    rows = con.execute(
        q + " ORDER BY t.state='pending' DESC, t.driven_at DESC LIMIT 500",
        tuple(args)).fetchall()
    # Finished routes this driver has not claimed yet — one tap each.
    unclaimed = []
    if _may_file(user):
        for r in con.execute(
                "SELECT r.id, r.name, r.route_date, r.total_km, r.created_at,"
                " k.name AS truck FROM routes r JOIN trucks k ON k.id=r.truck_id"
                " WHERE r.status='done' AND k.driver_user_id=?"
                " AND r.total_km>0 AND r.id NOT IN"
                "  (SELECT route_id FROM trips WHERE route_id>0"
                "   AND state!='withdrawn')"
                " ORDER BY r.created_at DESC LIMIT 20", (user["id"],)):
            unclaimed.append(dict(r))
    return {"trips": [_trip_row(r) for r in rows], "office": _office(user),
            "me": user["id"], "unclaimed_routes": unclaimed,
            "settings": settings(CFG)}


class TripBody(BaseModel):
    driven_at: float = 0
    from_place: str = ""
    to_place: str = ""
    purpose: str = ""
    distance: float = 0
    start_odo: float | None = None
    end_odo: float | None = None
    vehicle: str = "own"
    truck_id: int = 0
    note: str = ""
    user_id: int = 0


def _file_trip(con, uid: int, user, *, driven_at: float, from_place: str,
               to_place: str, purpose: str, distance: float,
               start_odo, end_odo, vehicle: str, truck_id: int,
               route_id: int, note: str) -> dict:
    s = settings(CFG)
    if start_odo is not None and end_odo is not None:
        if end_odo < start_odo:
            raise HTTPException(400, "the odometer does not go backwards")
        distance = round(end_odo - start_odo, 1)
    if distance <= 0:
        raise HTTPException(400, "a distance, or both odometer readings")
    if distance > MAX_DISTANCE:
        raise HTTPException(400, f"{distance:g} {s['distance_unit']} in one"
                                 f" trip — file a day at a time")
    if vehicle not in VEHICLES:
        raise HTTPException(400, "your own vehicle, or the company's")
    if driven_at > time.time() + 86400:
        raise HTTPException(400, "a trip is logged after it is driven")
    # Own car: the rate is the reimbursement and the deduction. Company
    # vehicle: the fuel and wear are expenses of their own, so the trip
    # is a record of distance and nothing is owed to the driver.
    rate = s["mileage_rate_cents"] if vehicle == "own" else 0
    amount = int(round(distance * rate))
    cur = con.execute(
        "INSERT INTO trips(user_id,driven_at,from_place,to_place,purpose,"
        " distance,unit,start_odo,end_odo,vehicle,truck_id,route_id,"
        " rate_cents,amount_cents,note,state,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)",
        (uid, driven_at, from_place.strip()[:120], to_place.strip()[:120],
         purpose.strip()[:200], round(distance, 1), s["distance_unit"],
         start_odo, end_odo, vehicle, truck_id or 0, route_id or 0, rate,
         amount, note.strip()[:400], db.now()))
    con.commit()
    row = con.execute("SELECT t.*, u.name AS who, k.name AS truck FROM trips t"
                      " JOIN users u ON u.id=t.user_id"
                      " LEFT JOIN trucks k ON k.id=t.truck_id WHERE t.id=?",
                      (cur.lastrowid,)).fetchone()
    return {"ok": True, **_trip_row(row)}


@router.post("/api/trips")
def add_trip(body: TripBody, user=Depends(current_user), con=Depends(get_con)):
    if not _may_file(user):
        raise HTTPException(403, "staff log trips")
    uid = user["id"]
    if body.user_id and body.user_id != user["id"]:
        _require_office(user)
        uid = body.user_id
    return _file_trip(con, uid, user, driven_at=body.driven_at or time.time(),
                      from_place=body.from_place, to_place=body.to_place,
                      purpose=body.purpose, distance=body.distance,
                      start_odo=body.start_odo, end_odo=body.end_odo,
                      vehicle=body.vehicle, truck_id=body.truck_id,
                      route_id=0, note=body.note)


@router.post("/api/trips/from-route/{rid}")
def trip_from_route(rid: int, user=Depends(current_user),
                    con=Depends(get_con)):
    """A finished route is a trip already measured: its total km, its
    truck, its date. The driver claims it in one tap, and once."""
    r = con.execute(
        "SELECT r.*, k.name AS truck, k.driver_user_id FROM routes r"
        " JOIN trucks k ON k.id=r.truck_id WHERE r.id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such route")
    if r["driver_user_id"] != user["id"] and not _office(user):
        raise HTTPException(403, "not your route")
    if r["status"] != "done":
        raise HTTPException(409, "the route is not finished")
    if con.execute("SELECT 1 FROM trips WHERE route_id=? AND state!='withdrawn'",
                   (rid,)).fetchone():
        raise HTTPException(409, "that route is already claimed")
    s = settings(CFG)
    dist = r["total_km"] / (1.609344 if s["distance_unit"] == "mi" else 1)
    try:
        when = datetime.strptime(r["route_date"], "%Y-%m-%d").timestamp() \
            if r["route_date"] else r["created_at"]
    except ValueError:
        when = r["created_at"]
    stops = con.execute("SELECT COUNT(*) FROM route_stops WHERE route_id=?",
                        (rid,)).fetchone()[0]
    return _file_trip(con, r["driver_user_id"] or user["id"], user,
                      driven_at=when, from_place="depot",
                      to_place=f"{stops} stop{'s' if stops != 1 else ''}",
                      purpose=f"route: {r['name']}", distance=round(dist, 1),
                      start_odo=None, end_odo=None,
                      vehicle="company", truck_id=r["truck_id"],
                      route_id=rid, note="")


@router.post("/api/trips/{tid}/decide")
def decide_trip(tid: int, body: DecideBody, user=Depends(current_user),
                con=Depends(get_con)):
    return _decide(con, "trips", tid, body, user)


# ---- the year ----

@router.get("/api/expenses/summary")
def year_summary(year: int = 0, user=Depends(current_user),
                 con=Depends(get_con)):
    _require_office(user)
    y = year or current_year(CFG)
    out = summary(con, CFG, y)
    out["owed"] = owed_by_person(con)
    return out


@router.get("/api/expenses/export.csv")
def export_csv(year: int = 0, user=Depends(current_user),
               con=Depends(get_con)):
    """The year as the accountant wants it: one line per approved or
    paid thing, with the deductible share worked out."""
    _require_office(user)
    y = year or current_year(CFG)
    a, b = year_bounds(CFG, y)
    cats = _cat_map(con)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "kind", "category", "who", "vendor_or_route",
                "amount", "business_pct", "deductible", "paid_by", "state",
                "note"])
    for r in con.execute(
            "SELECT e.*, u.name AS who FROM expenses e JOIN users u"
            " ON u.id=e.user_id WHERE e.spent_at>=? AND e.spent_at<?"
            " AND e.state IN ('approved','paid') ORDER BY e.spent_at", (a, b)):
        d = _expense_row(r, cats)
        w.writerow([date.fromtimestamp(d["spent_at"]).isoformat(), "expense",
                    d["category_label"], d["who"], d["vendor"],
                    f"{d['amount_cents'] / 100:.2f}", d["business_pct"],
                    f"{d['deductible_cents'] / 100:.2f}", d["paid_by"],
                    d["state"], d["note"]])
    for r in con.execute(
            "SELECT t.*, u.name AS who FROM trips t JOIN users u"
            " ON u.id=t.user_id WHERE t.driven_at>=? AND t.driven_at<?"
            " AND t.state IN ('approved','paid') ORDER BY t.driven_at", (a, b)):
        w.writerow([date.fromtimestamp(r["driven_at"]).isoformat(), "trip",
                    f"mileage ({r['unit']})", r["who"],
                    r["purpose"] or f"{r['from_place']} to {r['to_place']}",
                    f"{r['amount_cents'] / 100:.2f}", 100,
                    f"{r['amount_cents'] / 100:.2f}",
                    "me" if r["vehicle"] == "own" else "company",
                    r["state"], f"{r['distance']:g} {r['unit']}"
                    + (f" · {r['note']}" if r["note"] else "")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="expenses-{y}.csv"'})
