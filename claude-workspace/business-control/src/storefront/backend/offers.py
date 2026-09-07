"""The offer at checkout: one, or none.

A shop's last screen is where an extra item costs nothing to suggest and
everything to get wrong. Four offers on a checkout is a checkout people
leave; one, chosen because it fits what is already in the basket, is the
difference between "would you like anything else" and a rack of sweets.

So this returns at most one offer, ever. Rules are ordered and the first
that matches wins, which makes the behaviour something an owner can
predict from the screen rather than something they discover from sales.

Three rules, because they are the three real situations:

  cart_has        they have X, so offer Y — the sauce with the chips
  under_free_ship they are close to free shipping and do not know it
  always          the one thing this shop suggests to everybody

And it is measured, which is the part that decides whether any of it is
worth keeping. Shown, taken, and the money on the offers that were taken.

That last number is deliberately NOT called revenue added. Some of those
people would have bought the thing anyway, and there is no honest way
from here to know how many — so it is reported as what it is, the value
of what was taken from this slot, and the screen says so. A number that
quietly claims credit for sales that would have happened is how a
feature nobody can evaluate survives for years.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import admin_user, get_con

router = APIRouter()

TRIGGERS = ("always", "cart_has", "under_free_ship")

TABLES = """
CREATE TABLE IF NOT EXISTS checkout_offers (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,                 -- what the shopper is told
  blurb TEXT DEFAULT '',
  product_id INTEGER NOT NULL,         -- what gets added
  trigger TEXT NOT NULL DEFAULT 'always',
  needs_product_id INTEGER DEFAULT 0,  -- cart_has: which product
  under_cents INTEGER DEFAULT 0,       -- under_free_ship: the threshold
  discount_pct INTEGER DEFAULT 0,      -- 0 = at the usual price
  position INTEGER DEFAULT 0,          -- first match wins, low first
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS checkout_offer_events (
  id INTEGER PRIMARY KEY,
  offer_id INTEGER NOT NULL,
  visitor_id TEXT DEFAULT '',
  what TEXT NOT NULL,                  -- shown | taken
  value_cents INTEGER DEFAULT 0,       -- what the taken offer was worth
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS coe_offer ON checkout_offer_events(offer_id, at);
"""


def init_tables(con) -> None:
    con.executescript(TABLES)


def _price(con, pid: int, pct: int) -> tuple:
    r = con.execute("SELECT id, name, price_cents, image, sku FROM products"
                    " WHERE id=? AND active=1", (pid,)).fetchone()
    if r is None:
        return None, 0
    was = r["price_cents"]
    now = int(round(was * (100 - max(0, min(90, pct))) / 100)) if pct else was
    return r, now


def pick(con, subtotal_cents: int, product_ids: list) -> dict | None:
    """The one offer this basket should see, or nothing.

    Nothing is a real answer and the common one. A slot that always
    finds something to say ends up saying something irrelevant, and an
    irrelevant offer at checkout is worse than an empty space — it is a
    reason to stop and think, at the exact moment a shop wants neither.
    """
    have = set(product_ids or [])
    for o in con.execute(
            "SELECT * FROM checkout_offers WHERE active=1"
            " ORDER BY position, id"):
        if o["product_id"] in have:
            continue                    # never offer what is already in
        if o["trigger"] == "cart_has" and o["needs_product_id"] not in have:
            continue
        if o["trigger"] == "under_free_ship":
            line = o["under_cents"] or 0
            if not line or subtotal_cents >= line:
                continue
        p, now = _price(con, o["product_id"], o["discount_pct"])
        if p is None:
            continue                    # the product was retired under it
        d = {"offer_id": o["id"], "label": o["label"], "blurb": o["blurb"],
             "product_id": p["id"], "name": p["name"], "sku": p["sku"],
             "image": bool(p["image"]),
             "price_cents": now, "was_cents": p["price_cents"],
             "saving_cents": max(0, p["price_cents"] - now),
             "trigger": o["trigger"]}
        if o["trigger"] == "under_free_ship":
            d["short_by_cents"] = max(0, (o["under_cents"] or 0)
                                      - subtotal_cents)
        return d
    return None


def note(con, offer_id: int, what: str, visitor: str = "",
         value_cents: int = 0) -> None:
    """Never fatal. A shop must not fail to take an order because a
    counter would not increment."""
    try:
        con.execute(
            "INSERT INTO checkout_offer_events(offer_id,visitor_id,what,"
            "value_cents,at) VALUES(?,?,?,?,?)",
            (offer_id, (visitor or "")[:64], what, max(0, value_cents),
             time.time()))
        con.commit()
    except Exception:                                        # noqa: BLE001
        pass


# ---------- what the shop asks ----------

class AskBody(BaseModel):
    subtotal_cents: int = 0
    product_ids: list[int] = []
    visitor_id: str = ""


@router.post("/api/store/checkout-offer")
def checkout_offer(body: AskBody, con=Depends(get_con)):
    """POST rather than GET because the basket goes in the body: a cart
    in a query string is a cart in somebody's server logs."""
    o = pick(con, max(0, body.subtotal_cents), body.product_ids or [])
    if o:
        note(con, o["offer_id"], "shown", body.visitor_id)
    return {"offer": o}


class TookBody(BaseModel):
    offer_id: int = 0
    visitor_id: str = ""
    value_cents: int = 0


@router.post("/api/store/checkout-offer/taken")
def checkout_offer_taken(body: TookBody, con=Depends(get_con)):
    note(con, body.offer_id, "taken", body.visitor_id, body.value_cents)
    return {"ok": True}


# ---------- what the shop's owner reads ----------

class OfferBody(BaseModel):
    label: str = ""
    blurb: str = ""
    product_id: int = 0
    trigger: str = "always"
    needs_product_id: int = 0
    under_cents: int = 0
    discount_pct: int = 0
    position: int = 0
    active: bool = True


@router.get("/api/store/admin/checkout-offers")
def list_offers(days: int = 30, user=Depends(admin_user),
                con=Depends(get_con)):
    since = time.time() - max(1, days) * 86400
    rows = [dict(r) for r in con.execute(
        "SELECT o.*, COALESCE(p.name,'(retired)') AS product,"
        " COALESCE(n.name,'') AS needs FROM checkout_offers o"
        " LEFT JOIN products p ON p.id=o.product_id"
        " LEFT JOIN products n ON n.id=o.needs_product_id"
        " ORDER BY o.position, o.id")]
    for r in rows:
        stat = con.execute(
            "SELECT SUM(what='shown') AS shown, SUM(what='taken') AS taken,"
            " SUM(CASE WHEN what='taken' THEN value_cents ELSE 0 END) AS cents"
            " FROM checkout_offer_events WHERE offer_id=? AND at>?",
            (r["id"], since)).fetchone()
        shown = stat["shown"] or 0
        taken = stat["taken"] or 0
        r["shown"] = shown
        r["taken"] = taken
        r["take_pct"] = round(taken / shown * 100, 1) if shown else None
        r["taken_cents"] = stat["cents"] or 0
    return {
        "offers": rows, "days": days, "triggers": list(TRIGGERS),
        # Said on the object rather than left for the reader to assume.
        "note": "The money is the value of what was taken from this slot, "
                "not revenue this slot created. Some of those people "
                "would have bought it anyway and there is no honest way "
                "from here to know how many — a number that quietly "
                "claims credit for sales that would have happened is how "
                "a feature nobody can evaluate survives for years.",
    }


@router.post("/api/store/admin/checkout-offers")
def add_offer(body: OfferBody, user=Depends(admin_user),
              con=Depends(get_con)):
    if not body.label.strip():
        raise HTTPException(400, "an offer needs something to say")
    if body.trigger not in TRIGGERS:
        raise HTTPException(400, f"trigger is one of {TRIGGERS}")
    if con.execute("SELECT 1 FROM products WHERE id=? AND active=1",
                   (body.product_id,)).fetchone() is None:
        raise HTTPException(400, "that product is not on sale")
    if body.trigger == "cart_has" and not body.needs_product_id:
        raise HTTPException(400, "a 'they already have' offer needs to be "
                                 "told what they already have")
    if body.trigger == "under_free_ship" and body.under_cents <= 0:
        raise HTTPException(400, "a free-shipping nudge needs the line it "
                                 "is nudging them over")
    cur = con.execute(
        "INSERT INTO checkout_offers(label,blurb,product_id,trigger,"
        "needs_product_id,under_cents,discount_pct,position,active,"
        "created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (body.label.strip()[:120], body.blurb.strip()[:300], body.product_id,
         body.trigger, max(0, body.needs_product_id),
         max(0, body.under_cents), max(0, min(90, body.discount_pct)),
         body.position, 1 if body.active else 0, time.time()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/store/admin/checkout-offers/{oid}")
def edit_offer(oid: int, body: OfferBody, user=Depends(admin_user),
               con=Depends(get_con)):
    if con.execute("SELECT 1 FROM checkout_offers WHERE id=?",
                   (oid,)).fetchone() is None:
        raise HTTPException(404, "no such offer")
    if body.trigger not in TRIGGERS:
        raise HTTPException(400, f"trigger is one of {TRIGGERS}")
    con.execute(
        "UPDATE checkout_offers SET label=?, blurb=?, product_id=?,"
        " trigger=?, needs_product_id=?, under_cents=?, discount_pct=?,"
        " position=?, active=? WHERE id=?",
        (body.label.strip()[:120] or "offer", body.blurb.strip()[:300],
         body.product_id, body.trigger, max(0, body.needs_product_id),
         max(0, body.under_cents), max(0, min(90, body.discount_pct)),
         body.position, 1 if body.active else 0, oid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/checkout-offers/{oid}")
def drop_offer(oid: int, user=Depends(admin_user), con=Depends(get_con)):
    """The offer goes, its record stays. What was tried and did not work
    is the only reason the next one is a better guess."""
    con.execute("DELETE FROM checkout_offers WHERE id=?", (oid,))
    con.commit()
    return {"ok": True, "kept": "its shown/taken history"}
