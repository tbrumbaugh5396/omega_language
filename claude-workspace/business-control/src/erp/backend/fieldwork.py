"""Somebody went somewhere, did a list, took pictures, got a signature.

Delivering cases to a shop, resetting a shelf, checking a display, taking
a pallet in off a truck, walking a production line — four departments
call these four things, and they are one shape. A visit has a place, a
person, a checklist, evidence, and a moment it was finished. Building
four systems for that produces four half-finished ones and four sets of
photos nobody can find.

What makes a visit evidence rather than a claim:

  * **The pictures carry their own coordinates and clock.** A photo of a
    shelf proves nothing about which shelf or when; the same photo with a
    fix and a timestamp taken at the moment of capture proves both. They
    are recorded as the phone reported them, including the accuracy,
    because a rounded-off truth is a number somebody will later insist
    was exact.
  * **A checklist that can be refused.** Every step can be done, skipped
    with a reason, or failed with a reason. A list that only offers
    "done" gets ticked from the van, and everybody involved knows it.
  * **Mileage from the odometer.** Not from the GPS trail: a phone in a
    pocket loses signal in a loading bay and invents a straight line
    through a building, and a mileage claim is a payment.
  * **The name of whoever was there.** A delivery accepted by "manager"
    is a delivery nobody accepted.
"""
import secrets
import time

from . import db

KINDS = ("delivery", "merchandising", "receiving", "production", "visit")
STEP_STATES = ("open", "done", "skipped", "failed")
VISIT_STATES = ("planned", "started", "done", "abandoned")

TABLES = """
/* The kind of visit, and what it asks. A template rather than a hard
   coded list per department: the questions on a merchandising call change
   every season, and a change that needs a developer is a change that
   happens in a spreadsheet instead. */
CREATE TABLE IF NOT EXISTS visit_templates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'visit',
  steps TEXT NOT NULL DEFAULT '[]',        -- JSON: [{label, photo, note}]
  needs_signature INTEGER DEFAULT 0,
  needs_mileage INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY,
  template_id INTEGER DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'visit',
  title TEXT DEFAULT '',
  user_id INTEGER NOT NULL,
  store_id INTEGER DEFAULT 0,              -- ours, or a customer's
  supplier_id INTEGER DEFAULT 0,           -- for goods coming in
  order_id INTEGER DEFAULT 0,              -- the delivery this proves
  po_id INTEGER DEFAULT 0,                 -- the purchase order received
  route_id INTEGER DEFAULT 0,
  route_seq INTEGER DEFAULT -1,            -- which stop on it
  state TEXT NOT NULL DEFAULT 'planned',
  planned_for REAL DEFAULT 0,
  started_at REAL DEFAULT 0,
  finished_at REAL DEFAULT 0,
  start_lat REAL, start_lng REAL, start_accuracy_m REAL,
  end_lat REAL, end_lng REAL, end_accuracy_m REAL,
  start_odo_km REAL, end_odo_km REAL,
  contact_name TEXT DEFAULT '',
  contact_role TEXT DEFAULT '',
  signature TEXT DEFAULT '',               -- typed name; the paper is the photo
  signed_at REAL DEFAULT 0,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS visits_who ON visits(user_id, planned_for);
CREATE INDEX IF NOT EXISTS visits_state ON visits(state, planned_for);

CREATE TABLE IF NOT EXISTS visit_steps (
  id INTEGER PRIMARY KEY,
  visit_id INTEGER NOT NULL,
  seq INTEGER DEFAULT 0,
  label TEXT NOT NULL,
  wants_photo INTEGER DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'open',
  note TEXT DEFAULT '',
  qty REAL,                                -- counted, where a step counts
  line_id INTEGER DEFAULT 0,               -- the purchase order line, if any
  material_id INTEGER DEFAULT 0,           -- what it is, when no order says
  product_id INTEGER DEFAULT 0,            -- the line being delivered out
  expected_qty REAL,                       -- what is actually coming
  ordered_qty REAL,                        -- what we asked for, if different
  done_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS visit_steps_v ON visit_steps(visit_id, seq);

/* Evidence. The file is on disk; this row is what makes it evidence —
   where and when the phone said it was taken, and how sure it was. */
CREATE TABLE IF NOT EXISTS visit_media (
  id INTEGER PRIMARY KEY,
  visit_id INTEGER NOT NULL,
  step_id INTEGER DEFAULT 0,
  token TEXT UNIQUE NOT NULL,
  kind TEXT DEFAULT 'photo',               -- photo | receipt | signature
  caption TEXT DEFAULT '',
  lat REAL, lng REAL, accuracy_m REAL,
  taken_at REAL DEFAULT 0,
  bytes INTEGER DEFAULT 0,
  mime TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS visit_media_v ON visit_media(visit_id);
"""


def init_tables(con):
    con.executescript(TABLES)
    vcols = {r["name"] for r in con.execute("PRAGMA table_info(visits)")}
    if "route_seq" not in vcols:
        con.execute("ALTER TABLE visits ADD COLUMN route_seq INTEGER"
                    " DEFAULT -1")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(visit_steps)")}
    for name, decl in (("line_id", "INTEGER DEFAULT 0"),
                       ("expected_qty", "REAL"),
                       ("ordered_qty", "REAL"),
                       ("material_id", "INTEGER DEFAULT 0"),
                       ("product_id", "INTEGER DEFAULT 0")):
        if name not in cols:
            con.execute(f"ALTER TABLE visit_steps ADD COLUMN {name} {decl}")
    con.commit()


def steps_for(con, visit_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM visit_steps WHERE visit_id=? ORDER BY seq, id",
        (visit_id,))]


def media_for(con, visit_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM visit_media WHERE visit_id=? ORDER BY id",
        (visit_id,))]


def shape(con, r) -> dict:
    d = dict(r)
    d["steps"] = steps_for(con, r["id"])
    d["media"] = media_for(con, r["id"])
    d["done_steps"] = sum(1 for s in d["steps"] if s["state"] == "done")
    d["open_steps"] = sum(1 for s in d["steps"] if s["state"] == "open")
    d["failed_steps"] = [s["label"] for s in d["steps"]
                         if s["state"] == "failed"]
    d["km"] = (round(r["end_odo_km"] - r["start_odo_km"], 1)
               if r["end_odo_km"] and r["start_odo_km"]
               and r["end_odo_km"] >= r["start_odo_km"] else None)
    who = con.execute("SELECT name FROM users WHERE id=?",
                      (r["user_id"],)).fetchone()
    d["who"] = who["name"] if who else ""
    st = con.execute("SELECT name, city, lat, lng FROM stores WHERE id=?",
                     (r["store_id"] or 0,)).fetchone()
    d["store"] = dict(st) if st else None
    # How far the visit was recorded from the place it was recorded AT.
    # Not a verdict — a delivery bay is often a hundred metres from the
    # pin somebody dropped on a map years ago — but the number that makes
    # a fabricated visit obvious.
    d["metres_from_store"] = None
    if st and st["lat"] and r["start_lat"]:
        from .main import _metres
        d["metres_from_store"] = round(
            _metres(r["start_lat"], r["start_lng"], st["lat"], st["lng"]))
    return d


def open_visit(con, template_id: int, user_id: int, **kw) -> int:
    import json
    tpl = con.execute("SELECT * FROM visit_templates WHERE id=?",
                      (template_id,)).fetchone() if template_id else None
    kind = kw.get("kind") or (tpl["kind"] if tpl else "visit")
    cur = con.execute(
        "INSERT INTO visits(template_id,kind,title,user_id,store_id,"
        " supplier_id,order_id,po_id,route_id,route_seq,state,planned_for,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'planned',?,?)",
        (template_id, kind, (kw.get("title") or (tpl["name"] if tpl else ""))
         [:120], user_id, kw.get("store_id", 0), kw.get("supplier_id", 0),
         kw.get("order_id", 0), kw.get("po_id", 0), kw.get("route_id", 0),
         kw.get("route_seq", -1), kw.get("planned_for", 0), db.now()))
    vid = cur.lastrowid
    steps = kw.get("steps")
    if steps is None and tpl:
        try:
            steps = json.loads(tpl["steps"])
        except Exception:                                    # noqa: BLE001
            steps = []
    # Goods coming in: the list IS the paperwork. A receiving checklist
    # somebody types out by hand says what they remember was ordered,
    # which is the number least worth checking against.
    #
    # Three numbers meet on a loading bay and they are all different:
    # what we ORDERED, what the supplier PROMISED when they confirmed,
    # and what actually ARRIVED. Counting against the order alone flags
    # a delivery short when the supplier already told us it would be —
    # which trains everybody to ignore the flag. So the step is measured
    # against the promise where there is one, and carries the order
    # beside it so the two arguments stay separate: one is with the
    # driver at the door, the other is with the buyer next week.
    # Going out. The mirror image of receiving in shape and not at all in
    # meaning: the stock left when the order shipped, so what this visit
    # settles is whether it ARRIVED — and a delivery argument is never
    # about our count, it is about whether the customer got it. Which is
    # why the proof here is the signature at the door and the photograph
    # in the bay, and why anything refused has to come back to stock
    # rather than being quietly written off the order.
    order_id = kw.get("order_id", 0)
    if order_id and not kw.get("po_id"):
        for it in con.execute(
                "SELECT oi.product_id, oi.qty, COALESCE(p.name,'item') AS name"
                " FROM order_items oi LEFT JOIN products p"
                "  ON p.id=oi.product_id WHERE oi.order_id=?", (order_id,)):
            con.execute(
                "INSERT INTO visit_steps(visit_id,seq,label,wants_photo,"
                " product_id,expected_qty,ordered_qty) VALUES(?,?,?,1,?,?,?)",
                (vid, 2000 + it["product_id"],
                 f"{it['name']} — {it['qty']:g} to hand over",
                 it["product_id"], float(it["qty"]), float(it["qty"])))

    po_id = kw.get("po_id", 0)
    if po_id:
        promised = _promised(con, po_id)
        for ln in con.execute(
                "SELECT l.id, l.qty, l.received, COALESCE(m.name,'material')"
                "  AS name, COALESCE(m.unit,'') AS unit"
                " FROM purchase_order_lines l"
                " LEFT JOIN materials m ON m.id=l.material_id"
                " WHERE l.po_id=? ORDER BY l.id", (po_id,)):
            ordered_left = round(ln["qty"] - (ln["received"] or 0), 3)
            said = promised.get(str(ln["id"]))
            coming = ordered_left if said is None else round(
                min(said, ordered_left) if said <= ln["qty"] else said, 3)
            if coming <= 0 and ordered_left <= 0:
                continue
            unit = (" " + ln["unit"]).rstrip()
            label = f"{ln['name']} — {coming:g}{unit} expected"
            if said is not None and abs(coming - ordered_left) > 1e-9:
                label += f" (we ordered {ordered_left:g}{unit})"
            con.execute(
                "INSERT INTO visit_steps(visit_id,seq,label,wants_photo,"
                " line_id,expected_qty,ordered_qty) VALUES(?,?,?,1,?,?,?)",
                (vid, 1000 + ln["id"], label, ln["id"], coming,
                 ordered_left))
    for i, st in enumerate(steps or []):
        if isinstance(st, str):
            st = {"label": st}
        con.execute(
            "INSERT INTO visit_steps(visit_id,seq,label,wants_photo)"
            " VALUES(?,?,?,?)",
            (vid, i, str(st.get("label", ""))[:200],
             1 if st.get("photo") else 0))
    con.commit()
    return vid


def hand_over(con, visit_id: int, actor: str) -> dict:
    """Settle a delivery against the order it was carrying.

    Stock does not leave here — it left when the order shipped. What
    happens here is the opposite: anything the customer would not take
    comes BACK, to the store that sent it, because two cases refused at a
    door are two cases on a van and not two cases that evaporated. An
    order settled by writing the shortfall off the paperwork is how a
    van's stock and the system's diverge by exactly the amount nobody
    wanted.
    """
    v = con.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
    if v is None or not v["order_id"]:
        return {"handed": 0}
    o = con.execute("SELECT * FROM orders WHERE id=?",
                    (v["order_id"],)).fetchone()
    if o is None:
        return {"handed": 0}
    back_to = o["fulfilled_store_id"] or o["store_id"] or 0
    handed, refused, returned = 0, [], 0
    for st in con.execute(
            "SELECT * FROM visit_steps WHERE visit_id=? AND product_id>0",
            (visit_id,)):
        if st["state"] == "open":
            continue
        want = float(st["ordered_qty"] or 0)
        got = float(st["qty"]) if st["qty"] is not None else (
            0.0 if st["state"] in ("failed", "skipped") else want)
        handed += 1
        short = round(want - got, 3)
        if short <= 0:
            continue
        refused.append({"label": st["label"], "ordered": want,
                        "accepted": got, "back": short,
                        "why": st["note"] or ""})
        if back_to and st["product_id"]:
            # Cases in units, the way the order shipped them.
            per = con.execute("SELECT case_size FROM products WHERE id=?",
                              (st["product_id"],)).fetchone()
            units = short * ((per["case_size"] or 1)
                             if o["kind"] == "distributor" else 1)
            con.execute(
                "INSERT INTO inventory(store_id,product_id,qty,updated_at)"
                " VALUES(?,?,?,?) ON CONFLICT(store_id,product_id)"
                " DO UPDATE SET qty=qty+?, updated_at=?",
                (back_to, st["product_id"], units, db.now(), units, db.now()))
            returned += units
    if handed:
        # Delivered means all of it was taken. A partly-refused delivery
        # is not delivered, and calling it so is how a credit note goes
        # unwritten.
        con.execute("UPDATE orders SET status=? WHERE id=?",
                    ("delivered" if not refused else "part_delivered",
                     v["order_id"]))
        con.commit()
    return {"handed": handed, "refused": refused,
            "returned_units": returned, "back_to_store": back_to,
            # Refused stock with no store on the order has nowhere to go
            # back to. Saying so is the whole of the fix available here:
            # silently dropping it is how a van and the system diverge by
            # exactly the amount nobody wanted.
            "nowhere_to_return": bool(refused and not back_to),
            "accepted_all": not refused}


def book_loose(con, visit_id: int, actor: str) -> dict:
    """Post a delivery that answers to no order.

    Replacement pallets, samples, a case coming back, a supplier turning
    up on the strength of a phone call — these arrive, and refusing to
    book them until somebody raises a retrospective purchase order means
    they get booked as an adjustment, or not at all, and the stock is
    wrong either way.

    What a purchase order provides is authority: somebody agreed to this
    before it happened. Without one the authority has to come from
    somewhere, so it comes from a named person and a written reason, and
    the movement carries both into the ledger. "Where did forty litres
    come from" then has an answer that is not "an adjustment".
    """
    from . import supply
    v = con.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
    if v is None or v["po_id"]:
        return {"booked": 0}
    booked, took = 0, []
    for st in con.execute(
            "SELECT * FROM visit_steps WHERE visit_id=? AND material_id>0",
            (visit_id,)):
        if st["qty"] is None or st["state"] == "open" or float(st["qty"]) <= 0:
            continue
        why = (st["note"] or v["note"] or "").strip()
        supply.move(con, st["material_id"], float(st["qty"]),
                    f"visit:{visit_id}", actor,
                    why[:200] or "received with no order")
        booked += 1
        took.append({"label": st["label"], "got": float(st["qty"]),
                     "why": why})
    if booked:
        con.commit()
    return {"booked": booked, "loose": True, "lines": took}


def book_in(con, visit_id: int, actor: str) -> dict:
    """Post what was counted on a receiving visit against its order.

    Counted, not expected. The whole reason the step carries both is that
    they differ, and a receiving screen that books the ordered quantity
    because that is what the paperwork said is a screen that invents
    stock. A line counted short leaves the order part-received, which is
    what it is.
    """
    from . import supply
    v = con.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
    if v is None:
        return {"booked": 0}
    if not v["po_id"]:
        return book_loose(con, visit_id, actor)
    lines, short, over, agreed = {}, [], [], []
    for st in con.execute(
            "SELECT * FROM visit_steps WHERE visit_id=? AND line_id>0",
            (visit_id,)):
        if st["qty"] is None or st["state"] == "open":
            continue
        got = float(st["qty"])
        if got > 0:
            lines[str(st["line_id"])] = got
        want = float(st["expected_qty"] or 0)
        ordered = float(st["ordered_qty"] or 0)
        row = {"label": st["label"], "expected": want, "ordered": ordered,
               "got": got}
        if want and got < want:
            # Short against what they promised: an argument with the
            # driver, now, while the pallet is still on the tail lift.
            short.append(row)
        elif want and got > want:
            over.append(row)
        elif ordered and want and want < ordered - 1e-9:
            # Exactly what they promised, and less than we ordered. Not a
            # delivery problem at all — a buying one, and filing it with
            # the short deliveries is how everybody learns to ignore the
            # short deliveries.
            agreed.append(row)
    if not lines:
        return {"booked": 0, "short": short, "over": over,
                "short_of_order": agreed}
    out = supply.receive_po(con, v["po_id"], lines, actor)
    return {"booked": out["lines"], "complete": out["complete"],
            "short": short, "over": over, "short_of_order": agreed}


def _promised(con, po_id: int) -> dict:
    """What the supplier said they would actually ship, line by line.

    The latest confirmation wins: a supplier who writes twice has changed
    their mind, and the second message is the one the driver is bringing.
    """
    import json as _json
    r = con.execute(
        "SELECT lines FROM po_confirmations WHERE po_id=?"
        " ORDER BY id DESC LIMIT 1", (po_id,)).fetchone()
    if r is None:
        return {}
    try:
        said = _json.loads(r["lines"] or "{}")
    except Exception:                                        # noqa: BLE001
        return {}
    return {str(k): float(v) for k, v in said.items()
            if str(v).strip() != ""}


def stop_lines(con, store_id: int) -> list:
    """Everything owed to one shop, as lines to hand over.

    A stop is a store, and what is being delivered there is whichever
    orders are outstanding for it — often more than one, arriving on the
    same pallet. Building the list from the stop rather than from a
    single order is the difference between a driver with one docket and a
    driver with the day's work for that door.
    """
    out = []
    for it in con.execute(
            "SELECT oi.product_id, SUM(oi.qty) AS qty,"
            " COALESCE(p.name,'item') AS name,"
            " GROUP_CONCAT(DISTINCT o.id) AS orders"
            " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " LEFT JOIN products p ON p.id=oi.product_id"
            " WHERE o.store_id=? AND o.status IN"
            "  ('paid','confirmed','shipped','part_delivered')"
            " GROUP BY oi.product_id", (store_id,)):
        out.append({"product_id": it["product_id"], "qty": float(it["qty"]),
                    "name": it["name"], "orders": it["orders"]})
    return out


def close_stop(con, visit_id: int) -> dict:
    """A finished visit closes the stop it was for.

    Until now a stop was marked delivered by a checkbox, which is a claim.
    A stop closed by a visit carries the name of whoever took it, the
    photographs, and the coordinates the phone gave — the same delivery,
    with the difference between saying so and showing it.
    """
    v = con.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
    if v is None or not v["route_id"] or v["route_seq"] is None \
            or v["route_seq"] < 0:
        return {"stop": None}
    con.execute(
        "UPDATE route_stops SET delivered=1 WHERE route_id=? AND seq=?",
        (v["route_id"], v["route_seq"]))
    # A route whose every stop is closed is a route that is over.
    left = con.execute(
        "SELECT COUNT(*) AS n FROM route_stops WHERE route_id=?"
        " AND delivered=0", (v["route_id"],)).fetchone()["n"]
    if not left:
        con.execute("UPDATE routes SET status='done' WHERE id=?",
                    (v["route_id"],))
    con.commit()
    return {"stop": v["route_seq"], "route": v["route_id"],
            "stops_left": left, "route_done": not left}


def outbound(con, days: int = 14, when: float = 0) -> dict:
    """What is going out, and who is taking it.

    An order that has been paid for and not yet handed over is a promise
    with a van in front of it. The column that matters is the same one as
    on the way in: whether anybody is booked to do it — a drop nobody is
    named on is a drop that happens when somebody has a spare hour.
    """
    when = when or time.time()
    out = []
    for o in con.execute(
            "SELECT o.*, COALESCE(u.name,'') AS who,"
            " COALESCE(s.name,'') AS store FROM orders o"
            " LEFT JOIN users u ON u.id=o.user_id"
            " LEFT JOIN stores s ON s.id=o.store_id"
            " WHERE o.status IN ('paid','confirmed','shipped',"
            "  'part_delivered') AND o.kind!='pos'"
            " ORDER BY o.created_at DESC LIMIT 60"):
        items = [dict(r) for r in con.execute(
            "SELECT oi.qty, COALESCE(p.name,'item') AS name"
            " FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id"
            " WHERE oi.order_id=?", (o["id"],))]
        if not items:
            continue
        v = con.execute(
            "SELECT id, state, finished_at FROM visits WHERE order_id=?"
            " ORDER BY id DESC LIMIT 1", (o["id"],)).fetchone()
        out.append({
            "order_id": o["id"], "kind": o["kind"], "status": o["status"],
            "who": o["who"] or o["ship_name"] or "",
            "where": o["store"] or o["city"] or "",
            "cents": o["total_cents"], "items": items,
            "placed": o["created_at"],
            "visit": dict(v) if v else None,
        })
    return {"drops": out, "count": len(out),
            "unbooked": sum(1 for x in out if not x["visit"]),
            "note": "An order paid for and not yet handed over is a promise "
                    "with a van in front of it. A drop nobody is named on "
                    "is a drop that happens when somebody has a spare hour."}


def inbound(con, days: int = 30, when: float = 0) -> dict:
    """What is on its way in, and whether anybody is expecting it.

    An order that has been confirmed is a delivery with a date on it. The
    gap this closes is the ordinary one: a truck arrives, nobody knew it
    was coming, and it is counted by whoever happened to be near the
    door — which is the receiving that goes wrong.
    """
    when = when or time.time()
    out = []
    for po in con.execute(
            "SELECT p.*, COALESCE(s.name,'supplier') AS supplier"
            " FROM purchase_orders p"
            " LEFT JOIN suppliers s ON s.id=p.supplier_id"
            " WHERE p.status IN ('sent','part','confirmed')"
            " ORDER BY p.id DESC LIMIT 60"):
        conf = con.execute(
            "SELECT confirmed_by, confirmed_eta, created_at FROM"
            " po_confirmations WHERE po_id=? ORDER BY id DESC LIMIT 1",
            (po["id"],)).fetchone()
        promised = _promised(con, po["id"])
        lines, outstanding = [], 0.0
        for ln in con.execute(
                "SELECT l.id, l.qty, l.received, COALESCE(m.name,'material')"
                "  AS name, COALESCE(m.unit,'') AS unit"
                " FROM purchase_order_lines l"
                " LEFT JOIN materials m ON m.id=l.material_id"
                " WHERE l.po_id=?", (po["id"],)):
            left = round(ln["qty"] - (ln["received"] or 0), 3)
            if left <= 0:
                continue
            outstanding += left
            # A promise is only worth showing while it is smaller than
            # what is still owed. Once part of the line has arrived, "they
            # promised 60" against 15 outstanding reads as sixty more
            # coming — which is a promise that was already kept.
            said = promised.get(str(ln["id"]))
            lines.append({"id": ln["id"], "name": ln["name"],
                          "unit": ln["unit"], "outstanding": left,
                          "promised": said if (said is not None
                                               and said < left) else None})
        if not lines:
            continue
        v = con.execute(
            "SELECT id, state, finished_at FROM visits WHERE po_id=?"
            " ORDER BY id DESC LIMIT 1", (po["id"],)).fetchone()
        eta = conf["confirmed_eta"] if conf else 0
        out.append({
            "po_id": po["id"], "reference": po["reference"],
            "supplier": po["supplier"], "status": po["status"],
            "confirmed": bool(conf),
            "confirmed_by": conf["confirmed_by"] if conf else "",
            "eta": eta or 0,
            "overdue": bool(eta and eta < when),
            "lines": lines, "outstanding": round(outstanding, 3),
            "visit": dict(v) if v else None,
        })
    out.sort(key=lambda x: (x["eta"] or 9e12))
    return {"deliveries": out,
            "unexpected": sum(1 for x in out if not x["confirmed"]),
            "overdue": sum(1 for x in out if x["overdue"]),
            "unbooked": sum(1 for x in out if not x["visit"]),
            "note": "An order the supplier has confirmed is a delivery with "
                    "a date on it. The ones with nobody booked to meet them "
                    "are the ones counted by whoever happens to be near the "
                    "door, which is the receiving that goes wrong."}


def new_token() -> str:
    return secrets.token_urlsafe(16)


def summary(con, days: int = 30, user_id: int = 0, when: float = 0) -> dict:
    """What the field did, and what it did not.

    Completion counts a visit finished only when nothing on its list is
    still open — a visit marked done over a half-ticked checklist is the
    thing this exists to make visible, not something to round up.
    """
    when = when or time.time()
    since = when - days * 86400
    q = "SELECT * FROM visits WHERE created_at>=?"
    args = [since]
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    rows = [shape(con, r) for r in con.execute(q + " ORDER BY id DESC", args)]
    done = [v for v in rows if v["state"] == "done"]
    clean = [v for v in done if not v["open_steps"] and not v["failed_steps"]]
    km = sum(v["km"] or 0 for v in rows)
    by_kind = {}
    for v in rows:
        k = by_kind.setdefault(v["kind"], {"kind": v["kind"], "n": 0,
                                           "done": 0, "photos": 0, "km": 0.0})
        k["n"] += 1
        k["done"] += 1 if v["state"] == "done" else 0
        k["photos"] += len(v["media"])
        k["km"] += v["km"] or 0
    return {
        "days": days, "visits": rows[:60], "count": len(rows),
        "done": len(done), "clean": len(clean),
        "clean_pct": round(len(clean) / len(done) * 100, 1) if done else None,
        "km": round(km, 1),
        "photos": sum(len(v["media"]) for v in rows),
        "failed": [{"id": v["id"], "title": v["title"], "who": v["who"],
                    "failed": v["failed_steps"]} for v in rows
                   if v["failed_steps"]],
        "by_kind": sorted(by_kind.values(), key=lambda k: -k["n"]),
    }
