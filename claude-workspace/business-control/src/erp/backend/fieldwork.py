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
        " supplier_id,order_id,po_id,route_id,state,planned_for,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,'planned',?,?)",
        (template_id, kind, (kw.get("title") or (tpl["name"] if tpl else ""))
         [:120], user_id, kw.get("store_id", 0), kw.get("supplier_id", 0),
         kw.get("order_id", 0), kw.get("po_id", 0), kw.get("route_id", 0),
         kw.get("planned_for", 0), db.now()))
    vid = cur.lastrowid
    steps = kw.get("steps")
    if steps is None and tpl:
        try:
            steps = json.loads(tpl["steps"])
        except Exception:                                    # noqa: BLE001
            steps = []
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
