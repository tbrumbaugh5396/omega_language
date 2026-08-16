"""The upstream half: where the product comes from before it's a product.

Everything else in this ERP starts at a finished case sitting in a warehouse.
That is the back half of the business. The front half — who supplies the
yuzu concentrate, what a co-packer charges per run, how many cans of stock
one purchase order actually yields, and whether the aluminium arrives before
the production slot — has had no home, which is why it lives in spreadsheets
in every company this size.

Five things, and the links between them are the point:

  Suppliers — who you buy from, with a lead time and the terms you agreed.
  Lead time is a field rather than folklore because every shortage is
  ultimately someone assuming a shorter one.

  Materials — ingredients, cans, cartons, labels. Each has a unit, a stock
  level and a reorder point, so "are we about to run out" is a query rather
  than a phone call.

  Purchase orders — a supplier, some lines, a promised date. Receiving one
  moves stock in and records what actually turned up, which is rarely
  identical to what was ordered.

  Production runs — materials in, finished cases out, at a co-packer or your
  own line. This is the join between the two halves of the system: a run
  consumes materials and produces the products the rest of the ERP sells.

  Shipments — inbound freight with a carrier and an ETA, because a PO that
  has left the supplier and a PO that has arrived are different facts.

The recurring decision here is that quantities are only ever changed by an
event that explains them — receiving a PO, completing a run — never by
typing a new number into a stock field. A stock level you can overwrite is a
stock level nobody trusts by the second month.
"""
import json
import secrets
import time

from fastapi import HTTPException
from pydantic import BaseModel

TABLES = """
CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'ingredient',     -- see KINDS
  contact TEXT DEFAULT '',
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  country TEXT DEFAULT '',
  lead_days INTEGER DEFAULT 14,
  terms TEXT DEFAULT '',              -- "net 30"
  notes TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT DEFAULT '',
  kind TEXT DEFAULT 'ingredient',
  unit TEXT DEFAULT 'kg',
  supplier_id INTEGER,
  unit_cost_cents INTEGER DEFAULT 0,
  on_hand REAL DEFAULT 0,             -- moved by receipts and runs only
  reorder_point REAL DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL,
  reference TEXT DEFAULT '',
  status TEXT DEFAULT 'draft',        -- draft|sent|part|received|cancelled
  expected REAL DEFAULT 0,
  notes TEXT DEFAULT '',
  created_at REAL NOT NULL,
  received_at REAL DEFAULT 0,
  portal_token TEXT DEFAULT '',       -- the supplier's login-free link
  confirmed_at REAL DEFAULT 0
);

/* What the supplier said back, against what we asked for. Kept separate
   from the order itself: "we ordered 100 for the 14th" and "they confirmed
   80 for the 21st" are two different facts, and collapsing them into one
   row loses the discrepancy that is the whole reason to ask. */
CREATE TABLE IF NOT EXISTS po_confirmations (
  id INTEGER PRIMARY KEY,
  po_id INTEGER NOT NULL,
  confirmed_by TEXT DEFAULT '',
  confirmed_eta REAL DEFAULT 0,
  message TEXT DEFAULT '',
  lines TEXT DEFAULT '',              -- JSON: line id -> qty they'll ship
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
  id INTEGER PRIMARY KEY,
  po_id INTEGER NOT NULL,
  material_id INTEGER NOT NULL,
  qty REAL NOT NULL,
  received REAL DEFAULT 0,
  unit_cost_cents INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS production_runs (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  facility TEXT DEFAULT '',
  status TEXT DEFAULT 'planned',      -- planned|running|done|scrapped
  planned_cases INTEGER DEFAULT 0,
  actual_cases INTEGER DEFAULT 0,
  scheduled REAL DEFAULT 0,
  finished_at REAL DEFAULT 0,
  notes TEXT DEFAULT '',
  created_at REAL NOT NULL
);

/* What one case of a product consumes. The recipe, in other words — kept
   per product so a run can work out what it needs and what it used. */
CREATE TABLE IF NOT EXISTS bill_of_materials (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  material_id INTEGER NOT NULL,
  qty_per_case REAL NOT NULL,
  UNIQUE(product_id, material_id)
);

CREATE TABLE IF NOT EXISTS inbound_shipments (
  id INTEGER PRIMARY KEY,
  po_id INTEGER,
  carrier TEXT DEFAULT '',
  tracking TEXT DEFAULT '',
  status TEXT DEFAULT 'booked',       -- booked|in_transit|customs|arrived
  origin TEXT DEFAULT '',
  eta REAL DEFAULT 0,
  arrived_at REAL DEFAULT 0,
  notes TEXT DEFAULT '',
  created_at REAL NOT NULL
);

/* Every movement, with its reason. The stock number is derived from this,
   not the other way round. */
CREATE TABLE IF NOT EXISTS material_moves (
  id INTEGER PRIMARY KEY,
  material_id INTEGER NOT NULL,
  qty REAL NOT NULL,                  -- signed: + received, - consumed
  reason TEXT NOT NULL,               -- po:12, run:4, adjust
  actor TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS material_moves_mat
  ON material_moves(material_id, created_at DESC);
"""

KINDS = ("ingredient", "packaging", "co-packer", "logistics", "service")
UNITS = ("kg", "L", "each", "case", "roll", "pallet")
PO_STATUS = ("draft", "sent", "part", "received", "cancelled")
RUN_STATUS = ("planned", "running", "done", "scrapped")
SHIP_STATUS = ("booked", "in_transit", "customs", "arrived")


# Columns added after the tables first shipped. CREATE TABLE IF NOT EXISTS
# leaves an existing table exactly as it was, so a database created before
# these existed needs them added explicitly — and only a real install has
# that shape, which is why a fresh test database can't catch it.
MIGRATIONS = (
    "ALTER TABLE purchase_orders ADD COLUMN portal_token TEXT DEFAULT ''",
    "ALTER TABLE purchase_orders ADD COLUMN confirmed_at REAL DEFAULT 0",
)


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass            # already there
    con.commit()


def move(con, material_id: int, qty: float, reason: str, actor: str,
         note: str = "") -> None:
    """The only way stock changes. Writes the movement and applies it in one
    place, so the ledger and the running total can't disagree."""
    con.execute(
        "INSERT INTO material_moves(material_id,qty,reason,actor,note,"
        " created_at) VALUES(?,?,?,?,?,?)",
        (material_id, qty, reason, actor, note, time.time()))
    con.execute("UPDATE materials SET on_hand=on_hand+? WHERE id=?",
                (qty, material_id))


# ---------- bodies ----------

class SupplierBody(BaseModel):
    name: str
    kind: str = "ingredient"
    contact: str = ""
    email: str = ""
    phone: str = ""
    country: str = ""
    lead_days: int = 14
    terms: str = ""
    notes: str = ""
    active: int = 1


class MaterialBody(BaseModel):
    name: str
    code: str = ""
    kind: str = "ingredient"
    unit: str = "kg"
    supplier_id: int | None = None
    unit_cost_cents: int = 0
    reorder_point: float = 0
    active: int = 1


class POLineBody(BaseModel):
    material_id: int
    qty: float
    unit_cost_cents: int = 0


class POBody(BaseModel):
    supplier_id: int
    reference: str = ""
    expected: float = 0
    notes: str = ""
    lines: list[POLineBody] = []


class RunBody(BaseModel):
    product_id: int
    facility: str = ""
    planned_cases: int = 0
    scheduled: float = 0
    notes: str = ""


class ShipmentBody(BaseModel):
    po_id: int | None = None
    carrier: str = ""
    tracking: str = ""
    origin: str = ""
    eta: float = 0
    notes: str = ""


# ---------- reads ----------

def overview(con) -> dict:
    """One payload for the whole screen — the tab shows these together, and
    six round trips to render one page is six chances to render half of it."""
    suppliers = [dict(r) for r in con.execute(
        "SELECT * FROM suppliers ORDER BY active DESC, name").fetchall()]

    materials = []
    for r in con.execute(
            "SELECT m.*, s.name supplier_name FROM materials m"
            " LEFT JOIN suppliers s ON s.id=m.supplier_id"
            " ORDER BY m.active DESC, m.name").fetchall():
        d = dict(r)
        d["low"] = d["on_hand"] <= d["reorder_point"] and d["active"]
        # On order but not yet received — the difference between "we're
        # short" and "we're short and nobody has done anything about it".
        d["incoming"] = con.execute(
            "SELECT COALESCE(SUM(l.qty - l.received),0) n"
            " FROM purchase_order_lines l JOIN purchase_orders p"
            " ON p.id=l.po_id WHERE l.material_id=?"
            " AND p.status IN ('sent','part')", (r["id"],)).fetchone()["n"]
        materials.append(d)

    pos = []
    for r in con.execute(
            "SELECT p.*, s.name supplier_name FROM purchase_orders p"
            " JOIN suppliers s ON s.id=p.supplier_id"
            " ORDER BY p.created_at DESC LIMIT 60").fetchall():
        d = dict(r)
        d["lines"] = [dict(x) for x in con.execute(
            "SELECT l.*, m.name material_name, m.unit"
            " FROM purchase_order_lines l JOIN materials m"
            " ON m.id=l.material_id WHERE l.po_id=?", (r["id"],)).fetchall()]
        d["value_cents"] = sum(int(x["qty"] * x["unit_cost_cents"])
                               for x in d["lines"])
        # What the supplier said back, attached to the lines it refers to.
        # Receiving is where the three numbers finally meet — ordered,
        # promised, arrived — and the discrepancy is only visible if all
        # three are on the same screen.
        conf = con.execute(
            "SELECT * FROM po_confirmations WHERE po_id=?"
            " ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        if conf:
            try:
                said = json.loads(conf["lines"] or "{}")
            except Exception:
                said = {}
            d["confirmation"] = {
                "by": conf["confirmed_by"], "at": conf["created_at"],
                "eta": conf["confirmed_eta"], "message": conf["message"]}
            for ln in d["lines"]:
                v = said.get(str(ln["id"]))
                ln["confirmed"] = float(v) if v is not None else None
        else:
            d["confirmation"] = None
            for ln in d["lines"]:
                ln["confirmed"] = None
        pos.append(d)

    runs = []
    for r in con.execute(
            "SELECT r.*, pr.name product_name FROM production_runs r"
            " LEFT JOIN products pr ON pr.id=r.product_id"
            " ORDER BY r.created_at DESC LIMIT 40").fetchall():
        d = dict(r)
        d["needs"] = shortfall(con, r["product_id"],
                               r["planned_cases"]) if r["status"] in (
            "planned", "running") else []
        runs.append(d)

    shipments = [dict(r) for r in con.execute(
        "SELECT sh.*, p.reference po_reference FROM inbound_shipments sh"
        " LEFT JOIN purchase_orders p ON p.id=sh.po_id"
        " ORDER BY sh.eta DESC LIMIT 40").fetchall()]

    return {
        "suppliers": suppliers,
        "materials": materials,
        "purchase_orders": pos,
        "runs": runs,
        "shipments": shipments,
        "kinds": list(KINDS), "units": list(UNITS),
        "po_status": list(PO_STATUS), "run_status": list(RUN_STATUS),
        "ship_status": list(SHIP_STATUS),
        "stats": {
            "suppliers": sum(1 for s in suppliers if s["active"]),
            "low": sum(1 for m in materials if m["low"]),
            "open_pos": sum(1 for p in pos if p["status"] in ("sent", "part")),
            "on_order_cents": sum(p["value_cents"] for p in pos
                                  if p["status"] in ("sent", "part")),
            "runs_planned": sum(1 for r in runs if r["status"] == "planned"),
        },
    }


def shortfall(con, product_id: int, cases: int) -> list:
    """What a run of this size would be short of, given what's on hand.
    Empty means it can go ahead."""
    out = []
    for b in con.execute(
            "SELECT b.qty_per_case, m.id, m.name, m.unit, m.on_hand"
            " FROM bill_of_materials b JOIN materials m ON m.id=b.material_id"
            " WHERE b.product_id=?", (product_id,)).fetchall():
        need = b["qty_per_case"] * max(cases, 0)
        if need > b["on_hand"]:
            out.append({"material_id": b["id"], "name": b["name"],
                        "unit": b["unit"], "need": round(need, 2),
                        "have": round(b["on_hand"], 2),
                        "short": round(need - b["on_hand"], 2)})
    return out


def unit_costs(con) -> dict:
    """Material cost per *unit* of each product, from its recipe.

    The recipe is per case, orders are in units, so the case size does the
    conversion. Products with no recipe are absent rather than zero — the
    difference between "costs nothing" and "we haven't said" matters when
    this feeds a margin, and a zero would quietly flatter it.
    """
    rows = con.execute(
        "SELECT b.product_id, SUM(b.qty_per_case * m.unit_cost_cents) cents,"
        " p.case_size FROM bill_of_materials b"
        " JOIN materials m ON m.id=b.material_id"
        " JOIN products p ON p.id=b.product_id"
        " GROUP BY b.product_id").fetchall()
    out = {}
    for r in rows:
        case = max(1, r["case_size"] or 1)
        out[r["product_id"]] = {"per_case_cents": int(r["cents"]),
                                "per_unit_cents": int(r["cents"] / case)}
    return out


def consumption(con, material_id: int, days: int = 30) -> float:
    """How much of a material has been used per day lately, from the
    movements. Only outward moves count: receiving stock is not demand."""
    row = con.execute(
        "SELECT COALESCE(SUM(-qty),0) used FROM material_moves"
        " WHERE material_id=? AND qty<0 AND created_at >= ?",
        (material_id, time.time() - days * 86400)).fetchone()
    return (row["used"] or 0) / max(1, days)


def bom(con, product_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT b.*, m.name material_name, m.unit, m.on_hand"
        " FROM bill_of_materials b JOIN materials m ON m.id=b.material_id"
        " WHERE b.product_id=? ORDER BY m.name", (product_id,)).fetchall()]


# ---------- writes ----------

def add_supplier(con, body: SupplierBody) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a supplier needs a name")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    cur = con.execute(
        "INSERT INTO suppliers(name,kind,contact,email,phone,country,"
        " lead_days,terms,notes,active,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (body.name.strip()[:120], body.kind, body.contact.strip()[:120],
         body.email.strip()[:120], body.phone.strip()[:40],
         body.country.strip()[:60], max(0, body.lead_days),
         body.terms.strip()[:60], body.notes.strip()[:500],
         1 if body.active else 0, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


def add_material(con, body: MaterialBody) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a material needs a name")
    if body.unit not in UNITS:
        raise HTTPException(400, f"unit must be one of {UNITS}")
    cur = con.execute(
        "INSERT INTO materials(name,code,kind,unit,supplier_id,"
        " unit_cost_cents,on_hand,reorder_point,active,created_at)"
        " VALUES(?,?,?,?,?,?,0,?,?,?)",
        (body.name.strip()[:120], body.code.strip()[:40], body.kind,
         body.unit, body.supplier_id, max(0, body.unit_cost_cents),
         max(0.0, body.reorder_point), 1 if body.active else 0, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


def add_po(con, body: POBody) -> dict:
    if not con.execute("SELECT 1 FROM suppliers WHERE id=?",
                       (body.supplier_id,)).fetchone():
        raise HTTPException(404, "no such supplier")
    if not body.lines:
        raise HTTPException(400, "a purchase order needs at least one line")
    cur = con.execute(
        "INSERT INTO purchase_orders(supplier_id,reference,status,expected,"
        " notes,created_at) VALUES(?,?,'draft',?,?,?)",
        (body.supplier_id, body.reference.strip()[:60], body.expected,
         body.notes.strip()[:500], time.time()))
    pid = cur.lastrowid
    for ln in body.lines:
        if ln.qty <= 0:
            raise HTTPException(400, "a line needs a quantity above zero")
        con.execute(
            "INSERT INTO purchase_order_lines(po_id,material_id,qty,"
            " unit_cost_cents) VALUES(?,?,?,?)",
            (pid, ln.material_id, ln.qty, ln.unit_cost_cents))
    con.commit()
    return {"id": pid}


def receive_po(con, po_id: int, lines: dict, actor: str) -> dict:
    """Book in what actually arrived.

    `lines` maps line id to the quantity received now. Partial deliveries are
    the normal case, not the exception, so a PO stays open until every line
    is satisfied — marking it received on the first pallet is how phantom
    stock gets created.
    """
    po = con.execute("SELECT * FROM purchase_orders WHERE id=?",
                     (po_id,)).fetchone()
    if po is None:
        raise HTTPException(404, "no such purchase order")
    if po["status"] in ("received", "cancelled"):
        raise HTTPException(400, f"that order is already {po['status']}")

    rows = con.execute("SELECT * FROM purchase_order_lines WHERE po_id=?",
                       (po_id,)).fetchall()
    booked = 0
    for r in rows:
        got = float(lines.get(str(r["id"]), lines.get(r["id"], 0)) or 0)
        if got <= 0:
            continue
        outstanding = r["qty"] - r["received"]
        if got > outstanding + 1e-9:
            raise HTTPException(
                400, f"line {r['id']}: {got} is more than the {outstanding} "
                     "still outstanding")
        con.execute("UPDATE purchase_order_lines SET received=received+?"
                    " WHERE id=?", (got, r["id"]))
        move(con, r["material_id"], got, f"po:{po_id}", actor)
        booked += 1
    if not booked:
        raise HTTPException(400, "nothing was received")

    rows = con.execute("SELECT qty, received FROM purchase_order_lines"
                       " WHERE po_id=?", (po_id,)).fetchall()
    complete = all(r["received"] >= r["qty"] - 1e-9 for r in rows)
    con.execute("UPDATE purchase_orders SET status=?, received_at=?"
                " WHERE id=?",
                ("received" if complete else "part",
                 time.time() if complete else 0, po_id))
    con.commit()
    return {"ok": True, "complete": complete, "lines": booked}


def finish_run(con, run_id: int, actual_cases: int, actor: str) -> dict:
    """Close a production run: consume the materials it used, add the cases
    it made. Consumption is computed from what was actually produced, not
    what was planned, because those differ and the materials followed the
    real number."""
    r = con.execute("SELECT * FROM production_runs WHERE id=?",
                    (run_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    if r["status"] in ("done", "scrapped"):
        raise HTTPException(400, f"that run is already {r['status']}")
    if actual_cases < 0:
        raise HTTPException(400, "cases can't be negative")

    used = []
    for b in con.execute(
            "SELECT b.material_id, b.qty_per_case, m.name, m.on_hand"
            " FROM bill_of_materials b JOIN materials m ON m.id=b.material_id"
            " WHERE b.product_id=?", (r["product_id"],)).fetchall():
        qty = b["qty_per_case"] * actual_cases
        if qty <= 0:
            continue
        move(con, b["material_id"], -qty, f"run:{run_id}", actor)
        used.append({"name": b["name"], "qty": round(qty, 2),
                     "negative": b["on_hand"] - qty < 0})
    con.execute(
        "UPDATE production_runs SET status='done', actual_cases=?,"
        " finished_at=? WHERE id=?", (actual_cases, time.time(), run_id))
    con.commit()
    # A negative stock level is left visible rather than clamped: it means
    # the recipe or the counts are wrong, and hiding it hides the problem.
    return {"ok": True, "cases": actual_cases, "materials": used,
            "went_negative": [u["name"] for u in used if u["negative"]]}


# ---------- the supplier's side ----------
#
# Receiving currently means someone here types in what turned up. That is
# the last fact in the chain and the least useful one: by the time a pallet
# is on the dock, a short shipment is a problem you're absorbing rather than
# planning around. Asking the supplier to confirm the order moves that
# discovery weeks earlier.
#
# The link carries its own token and needs no account, for the same reason
# the signature links do: a supplier will not create a login to answer one
# question, and an integration nobody uses tells you nothing.

def portal_link(con, po_id: int, base: str) -> str:
    """A stable per-order link. Stable rather than single-use, because a
    supplier may come back to it when the ETA changes."""
    po = con.execute("SELECT * FROM purchase_orders WHERE id=?",
                     (po_id,)).fetchone()
    if po is None:
        raise HTTPException(404, "no such purchase order")
    token = po["portal_token"]
    if not token:
        token = secrets.token_urlsafe(24)
        con.execute("UPDATE purchase_orders SET portal_token=? WHERE id=?",
                    (token, po_id))
        con.commit()
    return f"{base}/supplier/{token}"


def portal_view(con, token: str) -> dict:
    """What the supplier sees. Deliberately narrow: their order, and nothing
    else about the business — not our stock, not our other suppliers, not
    what we paid anyone else."""
    po = con.execute(
        "SELECT p.*, s.name supplier_name FROM purchase_orders p"
        " JOIN suppliers s ON s.id=p.supplier_id"
        " WHERE p.portal_token=? AND p.portal_token!=''", (token,)).fetchone()
    if po is None:
        raise HTTPException(404, "that link isn't valid")
    lines = con.execute(
        "SELECT l.id, l.qty, l.received, m.name material_name, m.unit"
        " FROM purchase_order_lines l JOIN materials m ON m.id=l.material_id"
        " WHERE l.po_id=?", (po["id"],)).fetchall()
    conf = con.execute(
        "SELECT * FROM po_confirmations WHERE po_id=?"
        " ORDER BY id DESC LIMIT 1", (po["id"],)).fetchone()
    return {
        "reference": po["reference"] or f"PO #{po['id']}",
        "supplier_name": po["supplier_name"],
        "status": po["status"],
        "expected": po["expected"],
        "notes": po["notes"],
        "lines": [dict(r) for r in lines],
        "confirmed": dict(conf) if conf else None,
        "closed": po["status"] in ("received", "cancelled"),
    }


def portal_confirm(con, token: str, body: dict) -> dict:
    po = con.execute(
        "SELECT * FROM purchase_orders WHERE portal_token=?"
        " AND portal_token!=''", (token,)).fetchone()
    if po is None:
        raise HTTPException(404, "that link isn't valid")
    if po["status"] in ("received", "cancelled"):
        raise HTTPException(400, "this order is already closed")
    who = str(body.get("confirmed_by", "")).strip()
    if not who:
        raise HTTPException(400, "please give your name")

    valid = {str(r["id"]) for r in con.execute(
        "SELECT id FROM purchase_order_lines WHERE po_id=?",
        (po["id"],)).fetchall()}
    lines = {k: float(v) for k, v in (body.get("lines") or {}).items()
             if str(k) in valid and str(v).strip() != ""}
    eta = float(body.get("confirmed_eta") or 0)
    con.execute(
        "INSERT INTO po_confirmations(po_id,confirmed_by,confirmed_eta,"
        " message,lines,created_at) VALUES(?,?,?,?,?,?)",
        (po["id"], who[:120], eta, str(body.get("message", ""))[:800],
         json.dumps(lines), time.time()))
    con.execute("UPDATE purchase_orders SET confirmed_at=? WHERE id=?",
                (time.time(), po["id"]))
    con.commit()
    # Shortfalls and slips are the point of asking, so name them back rather
    # than just saying "thanks".
    short = []
    for r in con.execute(
            "SELECT l.id, l.qty, m.name FROM purchase_order_lines l"
            " JOIN materials m ON m.id=l.material_id WHERE l.po_id=?",
            (po["id"],)).fetchall():
        said = lines.get(str(r["id"]))
        if said is not None and said < r["qty"]:
            short.append({"name": r["name"], "asked": r["qty"], "said": said})
    return {"ok": True, "short": short,
            "later": bool(eta and po["expected"] and eta > po["expected"])}


# ---------- days of cover ----------

def forecast(con, days: int = 30) -> dict:
    """How long the stock lasts at the rate it's actually going.

    Two different questions with the same shape. For materials the rate
    comes from consumption; for finished product it comes from sales. Both
    are measured over a recent window rather than assumed, and a thing with
    no movement gets no forecast at all — "infinite cover" and "we haven't
    touched it in a month" look identical in a number and are not the same
    situation.
    """
    since = time.time() - days * 86400
    mats = []
    for m in con.execute(
            "SELECT m.*, s.lead_days FROM materials m"
            " LEFT JOIN suppliers s ON s.id=m.supplier_id"
            " WHERE m.active=1").fetchall():
        rate = consumption(con, m["id"], days)
        if rate <= 0:
            continue
        # Round once. Deriving the order-by date from the same whole number
        # the screen shows keeps the two consistent — int() truncates toward
        # zero, so computing them separately makes them disagree by a day
        # exactly when the answer is negative and someone is reading closely.
        cover = int(m["on_hand"] / rate)
        lead = m["lead_days"] if m["lead_days"] is not None else 14

        # Stock already bought but not yet here. Counting it is the
        # difference between "we're short" and "we're short and nobody has
        # done anything about it" — the first needs a purchase order, the
        # second needs a phone call, and they look identical without this.
        inc = con.execute(
            "SELECT COALESCE(SUM(l.qty - l.received),0) qty,"
            " MIN(NULLIF(p.expected,0)) soonest"
            " FROM purchase_order_lines l JOIN purchase_orders p"
            " ON p.id=l.po_id WHERE l.material_id=?"
            " AND p.status IN ('sent','part')", (m["id"],)).fetchone()
        incoming = inc["qty"] or 0
        cover_inc = int((m["on_hand"] + incoming) / rate)

        # Incoming only helps if it lands before the shelf empties. A pallet
        # that arrives the week after you run out is not cover.
        eta_days = None
        if incoming and inc["soonest"]:
            eta_days = int((inc["soonest"] - time.time()) / 86400)
        arrives_in_time = bool(incoming) and (
            eta_days is None or eta_days <= cover)

        mats.append({
            "id": m["id"], "name": m["name"], "unit": m["unit"],
            "on_hand": round(m["on_hand"], 2),
            "incoming": round(incoming, 2),
            "eta_days": eta_days,
            "per_day": round(rate, 2),
            "days_cover": cover,
            "days_cover_with_incoming": cover_inc,
            "lead_days": lead,
            # The number that matters isn't "when do we run out" but "have we
            # already missed the moment to order".
            "order_by_days": cover - lead,
            "covered_by_order": arrives_in_time,
            "urgent": cover <= lead and not arrives_in_time,
        })
    mats.sort(key=lambda m: m["days_cover"])

    prods = []
    rows = con.execute(
        "SELECT oi.product_id, p.name, p.case_size, SUM(oi.qty) sold"
        " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
        " JOIN products p ON p.id=oi.product_id"
        " WHERE o.created_at>=? AND o.status!='cancelled'"
        " GROUP BY oi.product_id", (since,)).fetchall()
    for r in rows:
        rate = r["sold"] / days
        if rate <= 0:
            continue
        stock = con.execute(
            "SELECT COALESCE(SUM(qty),0) q FROM inventory WHERE product_id=?",
            (r["product_id"],)).fetchone()["q"]
        cover = int(stock / rate)
        prods.append({
            "id": r["product_id"], "name": r["name"],
            "on_hand": stock, "per_day": round(rate, 2),
            "days_cover": cover, "urgent": cover <= 14,
        })
    prods.sort(key=lambda p: p["days_cover"])
    return {"window_days": days, "materials": mats, "products": prods}
