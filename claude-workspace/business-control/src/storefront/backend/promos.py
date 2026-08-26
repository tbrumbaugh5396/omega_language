"""Discounts, gift cards and recommendations.

Discounts grew from "percent off" into four kinds (percent, fixed amount,
free shipping, BOGO) with eligibility rules — minimum spend, usage caps,
per-customer caps, date windows — plus automatic discounts that need no code.
`compute_discount` is the single place order totals consult, so the storefront
preview and the real order always agree.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from erp.backend import auth, db
from .api import admin_user, get_con, rate_limit

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS discount_redemptions (
  id INTEGER PRIMARY KEY,
  discount_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  user_id INTEGER,
  amount_cents INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_cards (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  initial_cents INTEGER NOT NULL,
  balance_cents INTEGER NOT NULL,
  recipient_email TEXT DEFAULT '',
  note TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_card_redemptions (
  id INTEGER PRIMARY KEY,
  gift_card_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL,
  created_at REAL NOT NULL
);
"""

# store_discounts gained these after v1 shipped with percent-only codes.
MIGRATIONS = (
    "ALTER TABLE store_discounts ADD COLUMN kind TEXT DEFAULT 'percent'",
    "ALTER TABLE store_discounts ADD COLUMN value_cents INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN min_subtotal_cents INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN usage_limit INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN used_count INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN per_customer_limit INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN starts_at REAL DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN auto INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN bogo_buy INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN bogo_get INTEGER DEFAULT 0",
    "ALTER TABLE store_discounts ADD COLUMN bogo_product_id INTEGER",
)

KINDS = ("percent", "fixed", "free_shipping", "bogo")


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass


def _eligible(con, d, subtotal: int, user_id: int | None) -> str | None:
    """Returns a human reason when the discount cannot apply, else None."""
    now = db.now()
    if not d["active"]:
        return "this code is no longer active"
    if d["starts_at"] and d["starts_at"] > now:
        return "this code isn't active yet"
    if d["expires_at"] and d["expires_at"] < now:
        return "this code has expired"
    if d["min_subtotal_cents"] and subtotal < d["min_subtotal_cents"]:
        return (f"spend ${d['min_subtotal_cents'] / 100:,.2f} to use this code"
                f" (you're at ${subtotal / 100:,.2f})")
    if d["usage_limit"] and d["used_count"] >= d["usage_limit"]:
        return "this code has been fully claimed"
    if d["per_customer_limit"] and user_id:
        mine = con.execute(
            "SELECT COUNT(*) n FROM discount_redemptions WHERE discount_id=?"
            " AND user_id=?", (d["id"], user_id)).fetchone()["n"]
        if mine >= d["per_customer_limit"]:
            return "you've already used this code"
    return None


def _bogo_value(con, d, lines) -> int:
    """Cheapest-unit-free BOGO: for every `buy` qty of the target product,
    `get` units come free (priced at that line's unit price)."""
    buy, get = max(1, d["bogo_buy"] or 1), max(1, d["bogo_get"] or 1)
    total = 0
    for ln in lines:
        pid, qty, unit = ln[0], ln[1], ln[2]
        if d["bogo_product_id"] and pid != d["bogo_product_id"]:
            continue
        free_units = (qty // (buy + get)) * get
        total += free_units * unit
    return total


def compute_discount(con, code: str, subtotal: int, lines, user_id=None,
                     shipping_cents: int = 0):
    """The single source of truth for order discounts.

    `lines` is [(product_id, qty, unit_cents, ...)] as built by place_order.
    Returns {amount_cents, code, kind, free_shipping, discount_id, reason}.
    Automatic discounts apply with no code when nothing was typed.
    """
    d = None
    if code and code.strip():
        d = con.execute(
            "SELECT * FROM store_discounts WHERE lower(code)=lower(?)",
            (code.strip(),)).fetchone()
        if d is None:
            return {"amount_cents": 0, "code": "", "kind": "",
                    "free_shipping": False, "discount_id": None,
                    "reason": "that code doesn't exist"}
        why = _eligible(con, d, subtotal, user_id)
        if why:
            return {"amount_cents": 0, "code": "", "kind": "",
                    "free_shipping": False, "discount_id": None,
                    "reason": why}
    else:
        # Best automatic discount the cart qualifies for.
        best, best_amt = None, 0
        for cand in con.execute(
                "SELECT * FROM store_discounts WHERE auto=1 AND active=1"
                ).fetchall():
            if _eligible(con, cand, subtotal, user_id):
                continue
            amt = _amount(con, cand, subtotal, lines, shipping_cents)
            if amt > best_amt:
                best, best_amt = cand, amt
        d = best
        if d is None:
            return {"amount_cents": 0, "code": "", "kind": "",
                    "free_shipping": False, "discount_id": None, "reason": ""}
    amount = _amount(con, d, subtotal, lines, shipping_cents)
    return {"amount_cents": min(amount, subtotal), "code": d["code"],
            "kind": d["kind"] or "percent",
            "free_shipping": (d["kind"] == "free_shipping"),
            "discount_id": d["id"], "reason": "",
            "auto": bool(d["auto"])}


def _amount(con, d, subtotal: int, lines, shipping_cents: int) -> int:
    kind = d["kind"] or "percent"
    if kind == "percent":
        return subtotal * (d["pct"] or 0) // 100
    if kind == "fixed":
        return min(d["value_cents"] or 0, subtotal)
    if kind == "free_shipping":
        return 0                       # handled by the free_shipping flag
    if kind == "bogo":
        return _bogo_value(con, d, lines)
    return 0


def record_redemption(con, discount_id, order_id, user_id, amount):
    if not discount_id:
        return
    con.execute(
        "INSERT INTO discount_redemptions(discount_id,order_id,user_id,"
        " amount_cents,created_at) VALUES(?,?,?,?,?)",
        (discount_id, order_id, user_id, amount, db.now()))
    con.execute("UPDATE store_discounts SET used_count=used_count+1"
                " WHERE id=?", (discount_id,))


# ---------- gift cards ----------

def gift_balance(con, code: str):
    return con.execute(
        "SELECT * FROM gift_cards WHERE upper(code)=upper(?) AND active=1",
        (code.strip(),)).fetchone()


def apply_gift_card(con, code: str, due_cents: int, order_id: int):
    """Spend up to `due_cents` from the card. Returns cents applied."""
    g = gift_balance(con, code)
    if g is None or g["balance_cents"] <= 0:
        return 0
    use = min(g["balance_cents"], due_cents)
    con.execute("UPDATE gift_cards SET balance_cents=balance_cents-?"
                " WHERE id=?", (use, g["id"]))
    con.execute(
        "INSERT INTO gift_card_redemptions(gift_card_id,order_id,amount_cents,"
        " created_at) VALUES(?,?,?,?)", (g["id"], order_id, use, db.now()))
    return use


# ---------- public endpoints ----------

class CodeBody(BaseModel):
    code: str
    subtotal_cents: int = 0


@router.post("/api/store/discount/preview")
def preview_discount(body: CodeBody, con=Depends(get_con),
                     _rl=Depends(rate_limit)):
    """Cart-side check so shoppers see the real rule, not a generic error."""
    out = compute_discount(con, body.code, body.subtotal_cents, [])
    if out["reason"]:
        raise HTTPException(400, out["reason"])
    if not out["code"]:
        raise HTTPException(404, "invalid or expired code")
    d = con.execute("SELECT * FROM store_discounts WHERE id=?",
                    (out["discount_id"],)).fetchone()
    label = {"percent": f"{d['pct']}% off",
             "fixed": f"${(d['value_cents'] or 0) / 100:,.2f} off",
             "free_shipping": "free shipping",
             "bogo": f"buy {d['bogo_buy']} get {d['bogo_get']} free"}.get(
        out["kind"], "discount")
    return {**out, "label": label}


@router.get("/api/store/gift-card/{code}")
def check_gift_card(code: str, con=Depends(get_con),
                    _rl=Depends(rate_limit)):
    g = gift_balance(con, code)
    if g is None:
        raise HTTPException(404, "no such gift card")
    return {"code": g["code"], "balance_cents": g["balance_cents"],
            "initial_cents": g["initial_cents"]}


@router.get("/api/store/recommendations/{pid}")
def recommendations(pid: int, limit: int = 4, con=Depends(get_con)):
    """Co-purchase first (people who bought this also bought…), topped up
    from the same category, then anything else. Never returns the product."""
    rows = con.execute(
        "SELECT oi2.product_id pid, COUNT(*) n FROM order_items oi1"
        " JOIN order_items oi2 ON oi2.order_id=oi1.order_id"
        " AND oi2.product_id!=oi1.product_id"
        " JOIN products p ON p.id=oi2.product_id AND p.active=1"
        " WHERE oi1.product_id=? GROUP BY oi2.product_id"
        " ORDER BY n DESC LIMIT ?", (pid, limit)).fetchall()
    ids = [r["pid"] for r in rows]
    if len(ids) < limit:
        cat = con.execute("SELECT category FROM products WHERE id=?",
                          (pid,)).fetchone()
        if cat:
            for r in con.execute(
                    "SELECT id FROM products WHERE active=1 AND category=?"
                    " AND id!=? ORDER BY id LIMIT ?",
                    (cat["category"], pid, limit)).fetchall():
                if r["id"] not in ids:
                    ids.append(r["id"])
    if len(ids) < limit:
        for r in con.execute(
                "SELECT id FROM products WHERE active=1 AND id!=?"
                " ORDER BY id LIMIT ?", (pid, limit)).fetchall():
            if r["id"] not in ids:
                ids.append(r["id"])
    ids = ids[:limit]
    if not ids:
        return []
    from .api import media_json, slugify
    out = []
    for r in con.execute(
            "SELECT id, name, description, category, price_cents, image"
            f" FROM products WHERE id IN ({','.join('?' * len(ids))})",
            ids).fetchall():
        d = dict(r)
        d["slug"] = slugify(d["name"])
        # Colour travels with the product. Without it the client had nothing
        # to tint with and silently fell back to brand purple, which is why
        # every cross-sell row looked the same regardless of what was in it.
        for m in con.execute(
                "SELECT k, v FROM store_product_meta WHERE product_id=?"
                " AND k IN ('colour','flavour','note')", (d["id"],)).fetchall():
            d[m["k"]] = m["v"]
        d["media"] = media_json(con.execute(
            "SELECT * FROM product_media WHERE product_id=?"
            " ORDER BY position, id LIMIT 1", (d["id"],)).fetchall())
        out.append(d)
    return out


# ---------- admin ----------

class DiscountBody(BaseModel):
    code: str
    kind: str = "percent"
    pct: int = 0
    value_cents: int = 0
    min_subtotal_cents: int = 0
    usage_limit: int = 0
    per_customer_limit: int = 0
    expires_at: float = 0
    auto: bool = False
    bogo_buy: int = 0
    bogo_get: int = 0
    bogo_product_id: int | None = None
    active: bool = True


@router.get("/api/store/admin/discounts2")
def list_discounts(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM store_discounts ORDER BY id DESC").fetchall()]


@router.post("/api/store/admin/discounts2")
def save_discount(body: DiscountBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    if body.kind == "percent" and not 1 <= body.pct <= 100:
        raise HTTPException(400, "percent must be 1–100")
    if body.kind == "fixed" and body.value_cents <= 0:
        raise HTTPException(400, "amount required")
    if body.kind == "bogo" and (body.bogo_buy < 1 or body.bogo_get < 1):
        raise HTTPException(400, "buy and get quantities required")
    code = body.code.strip().upper() or ("AUTO-" + secrets.token_hex(3).upper())
    con.execute(
        "INSERT INTO store_discounts(code,pct,active,kind,value_cents,"
        " min_subtotal_cents,usage_limit,per_customer_limit,expires_at,auto,"
        " bogo_buy,bogo_get,bogo_product_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(code) DO UPDATE SET pct=excluded.pct,"
        " active=excluded.active, kind=excluded.kind,"
        " value_cents=excluded.value_cents,"
        " min_subtotal_cents=excluded.min_subtotal_cents,"
        " usage_limit=excluded.usage_limit,"
        " per_customer_limit=excluded.per_customer_limit,"
        " expires_at=excluded.expires_at, auto=excluded.auto,"
        " bogo_buy=excluded.bogo_buy, bogo_get=excluded.bogo_get,"
        " bogo_product_id=excluded.bogo_product_id",
        (code, body.pct, int(body.active), body.kind, body.value_cents,
         body.min_subtotal_cents, body.usage_limit, body.per_customer_limit,
         body.expires_at, int(body.auto), body.bogo_buy, body.bogo_get,
         body.bogo_product_id))
    con.commit()
    return {"ok": True, "code": code}


class GiftBody(BaseModel):
    amount_cents: int
    recipient_email: str = ""
    note: str = ""


@router.get("/api/store/admin/gift-cards")
def list_gift_cards(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM gift_cards ORDER BY id DESC LIMIT 200").fetchall()]


@router.post("/api/store/admin/gift-cards")
def issue_gift_card(body: GiftBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    if body.amount_cents <= 0:
        raise HTTPException(400, "amount required")
    code = "GC-" + secrets.token_hex(4).upper()
    con.execute(
        "INSERT INTO gift_cards(code,initial_cents,balance_cents,"
        " recipient_email,note,created_at) VALUES(?,?,?,?,?,?)",
        (code, body.amount_cents, body.amount_cents,
         body.recipient_email.strip(), body.note.strip()[:200], db.now()))
    con.commit()
    return {"ok": True, "code": code, "balance_cents": body.amount_cents}


@router.delete("/api/store/admin/gift-cards/{gid}")
def void_gift_card(gid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE gift_cards SET active=0 WHERE id=?", (gid,))
    con.commit()
    return {"ok": True}
