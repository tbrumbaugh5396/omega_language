"""Delivery apps: a menu out to Uber Eats and DoorDash, their orders in.

A restaurant on two delivery apps keeps three menus — its own, and one
in each app's merchant portal — and the day a price changes is the day
one of them is wrong. So the menu here is the products table with a
flag: a product marked "on the menu" is pushed, with its price, to
every connected app, and pushed again the moment it changes. There is
one menu, and the apps have copies.

Orders come the other way. Both apps POST each order to an address we
publish (the key is in the URL, because their webhooks sign in their own
way rather than with a header we choose), the lines are matched to
products by SKU — the code we put on each item when we pushed the menu,
so the round trip needs no mapping table — and the order joins the same
queue a counter order does. Then it is accepted back, because an order
nobody acknowledges is cancelled by the app after a few minutes.

Both APIs are partner APIs: Uber and DoorDash each approve an
integration before issuing a credential, and their endpoints move by
version. Every URL is in ENDPOINTS at the top for that reason — the
day a portal says v3, that is the one line to change.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS marketplace_menu (
  provider TEXT NOT NULL,
  product_id INTEGER NOT NULL,
  listed INTEGER DEFAULT 1,
  synced_at REAL DEFAULT 0,
  PRIMARY KEY (provider, product_id)
);

CREATE TABLE IF NOT EXISTS marketplace_orders (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  external_id TEXT NOT NULL,
  order_id INTEGER DEFAULT 0,              -- ours, once placed
  state TEXT DEFAULT 'received',           -- received|accepted|failed
  detail TEXT DEFAULT '',
  raw TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(provider, external_id)
);
"""

ENDPOINTS = {
    "ubereats": {
        "token": "https://auth.uber.com/oauth/v2/token",
        "store": "https://api.uber.com/v1/eats/stores/{store_id}",
        "menu": "https://api.uber.com/v2/eats/stores/{store_id}/menus",
        "status": "https://api.uber.com/v1/eats/stores/{store_id}/status",
        "order": "https://api.uber.com/v2/eats/order/{order_id}",
        "accept": "https://api.uber.com/v1/eats/orders/{order_id}/accept_pos_order",
    },
    "doordash": {
        "base": "https://openapi.doordash.com/marketplace/api/v1",
        "store": "https://openapi.doordash.com/marketplace/api/v1/stores/{location_id}",
        "menu": "https://openapi.doordash.com/marketplace/api/v1/menus",
        "status": "https://openapi.doordash.com/marketplace/api/v1/stores/{location_id}/status",
        "confirm": "https://openapi.doordash.com/marketplace/api/v1/orders/{order_id}/confirmation",
    },
}
PROVIDERS = ("ubereats", "doordash")
_TOKENS: dict = {}       # client_id -> (token, expires_at); Uber's are hours long


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return bool(user["is_admin"] or user["role"] in ("admin", "owner"))


# ---------- credentials ----------

def _uber_token(c: dict) -> str:
    cid = c.get("client_id", "")
    tok, exp = _TOKENS.get(cid, ("", 0))
    if tok and exp > time.time():
        return tok
    body = ("grant_type=client_credentials&scope=eats.store%20eats.order"
            f"&client_id={cid}&client_secret={c.get('client_secret','')}").encode()
    ok, d = IG._req(ENDPOINTS["ubereats"]["token"], "POST",
                    {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if not ok or not isinstance(d, dict) or not d.get("access_token"):
        raise HTTPException(400, f"Uber would not issue a token: {d}")
    _TOKENS[cid] = (d["access_token"], time.time() + int(d.get("expires_in") or 3600) - 60)
    return d["access_token"]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def dd_jwt(c: dict, ttl: int = 300) -> str:
    """DoorDash's JWT: HS256 over the developer id and key id, signed with
    the base64url signing secret, five minutes at a time."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT",
                                 "dd-ver": "DD-JWT-V1"}).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({"aud": "doordash", "iss": c.get("developer_id", ""),
                                  "kid": c.get("key_id", ""), "exp": now + ttl,
                                  "iat": now}).encode())
    secret = c.get("signing_secret", "")
    key = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    sig = hmac.new(key, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _headers(name: str, c: dict) -> dict:
    if name == "ubereats":
        return {"Authorization": f"Bearer {_uber_token(c)}",
                "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {dd_jwt(c)}",
            "Content-Type": "application/json"}


def _check_uber(c: dict) -> tuple:
    if not c.get("store_id"):
        return False, "the store id is needed"
    try:
        h = _headers("ubereats", c)
    except HTTPException as e:
        return False, str(e.detail)
    ok, d = IG._req(ENDPOINTS["ubereats"]["store"].format(store_id=c["store_id"]),
                    headers=h)
    if not ok:
        return False, str(d)
    return True, (d.get("name") if isinstance(d, dict) else None) or c["store_id"]


def _check_doordash(c: dict) -> tuple:
    if not c.get("location_id"):
        return False, "the location id is needed"
    try:
        h = _headers("doordash", c)
    except Exception as e:                                   # noqa: BLE001
        return False, f"the signing secret isn't base64: {e}"
    ok, d = IG._req(ENDPOINTS["doordash"]["store"].format(location_id=c["location_id"]),
                    headers=h)
    if not ok:
        return False, str(d)
    return True, (d.get("name") if isinstance(d, dict) else None) or c["location_id"]


IG.CHECKS["ubereats"] = _check_uber
IG.CHECKS["doordash"] = _check_doordash


def _creds(con, name: str) -> dict:
    c = IG.creds(con, name)
    if not c:
        raise HTTPException(400, f"connect {IG.PROVIDERS[name]['label']} first")
    return {**IG.settings(con, name), **c}


# ---------- the menu ----------

def menu_products(con, name: str) -> list:
    return [dict(r) for r in con.execute(
        "SELECT p.id, p.sku, p.name, p.description, p.category, p.price_cents,"
        " p.image, COALESCE(m.listed, 0) AS listed, COALESCE(m.synced_at, 0) AS synced_at"
        " FROM products p LEFT JOIN marketplace_menu m"
        " ON m.product_id=p.id AND m.provider=?"
        " WHERE p.active=1 ORDER BY p.category, p.name", (name,)).fetchall()]


def set_menu(con, name: str, product_ids: list) -> int:
    ids = {int(x) for x in product_ids}
    con.execute("DELETE FROM marketplace_menu WHERE provider=?", (name,))
    for pid in ids:
        con.execute("INSERT INTO marketplace_menu(provider,product_id,listed)"
                    " VALUES(?,?,1)", (name, pid))
    con.commit()
    return len(ids)


def _listed(con, name: str) -> list:
    return [p for p in menu_products(con, name) if p["listed"]]


def uber_menu(con, name: str, products: list) -> dict:
    """Uber's whole-menu shape: one menu, a category per ours, an item
    per product with the SKU as its id AND its external_data — the
    latter is what comes back on an order line."""
    from .main import base_url
    by_cat = {}
    for p in products:
        by_cat.setdefault(p["category"] or "Menu", []).append(p)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
            "sunday"]
    return {
        "menus": [{"id": "all-day", "title": {"translations": {"en_us": "Menu"}},
                   "service_availability": [{"day_of_week": d, "time_periods": [
                       {"start_time": "00:00", "end_time": "23:59"}]} for d in days],
                   "category_ids": [f"cat-{i}" for i, _ in enumerate(by_cat)]}],
        "categories": [{"id": f"cat-{i}", "title": {"translations": {"en_us": cat}},
                        "entities": [{"id": p["sku"], "type": "ITEM"} for p in ps]}
                       for i, (cat, ps) in enumerate(by_cat.items())],
        "items": [{"id": p["sku"], "external_data": p["sku"],
                   "title": {"translations": {"en_us": p["name"]}},
                   "description": {"translations": {"en_us": p["description"] or ""}},
                   "image_url": f"{base_url()}/api/products/{p['id']}/image" if p["image"] else "",
                   "price_info": {"price": int(p["price_cents"])},
                   "quantity_info": {"quantity": {"max_permitted": 20}}}
                  for p in products],
        "modifier_groups": [],
        "display_options": {"disable_item_instructions": False},
    }


def doordash_menu(con, name: str, c: dict, products: list) -> dict:
    by_cat = {}
    for p in products:
        by_cat.setdefault(p["category"] or "Menu", []).append(p)
    return {
        "reference": "business-control",
        "store": {"merchant_supplied_id": c.get("location_id", ""),
                  "provider_type": "business_control"},
        "open_hours": [{"day_index": d, "start_time": "00:00:00", "end_time": "23:59:59"}
                       for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")],
        "menu": {"name": "Menu", "subtitle": "", "active": True,
                 "categories": [{"name": cat, "merchant_supplied_id": f"cat-{i}",
                                 "items": [{"name": p["name"],
                                            "description": p["description"] or "",
                                            "merchant_supplied_id": p["sku"],
                                            "price": int(p["price_cents"]),
                                            "active": True}
                                           for p in ps]}
                                for i, (cat, ps) in enumerate(by_cat.items())]},
    }


def push_menu(con, name: str) -> dict:
    c = _creds(con, name)
    products = _listed(con, name)
    if not products:
        raise HTTPException(400, "nothing is marked as on the menu")
    if name == "ubereats":
        ok, d = IG._json_req(ENDPOINTS["ubereats"]["menu"].format(store_id=c["store_id"]),
                             "PUT", _headers(name, c), uber_menu(con, name, products))
    else:
        ok, d = IG._json_req(ENDPOINTS["doordash"]["menu"], "POST",
                             _headers(name, c), doordash_menu(con, name, c, products))
    IG.log(con, name, "push_menu", ok, f"{len(products)} item(s)" if ok else str(d)[:200])
    if not ok:
        raise HTTPException(400, f"{IG.PROVIDERS[name]['label']} said: {d}")
    now = time.time()
    con.execute("UPDATE marketplace_menu SET synced_at=? WHERE provider=?", (now, name))
    con.commit()
    return {"ok": True, "items": len(products)}


def deliver(con, name: str, event: str, d: dict, c: dict) -> tuple:
    """A product changed. If it is on this app's menu, the whole menu
    goes again — both APIs take menus, not items."""
    pid = d.get("id") or d.get("product_id")
    if pid is None:
        return True, "no product id on the event"
    on = con.execute("SELECT 1 FROM marketplace_menu WHERE provider=? AND"
                     " product_id=? AND listed=1", (name, int(pid))).fetchone()
    if not on:
        return True, "not on this menu"
    try:
        r = push_menu(con, name)
        return True, f"menu re-pushed, {r['items']} item(s)"
    except HTTPException as e:
        return False, str(e.detail)


IG.DELIVERS["ubereats"] = lambda con, event, d, c: deliver(con, "ubereats", event, d, c)
IG.DELIVERS["doordash"] = lambda con, event, d, c: deliver(con, "doordash", event, d, c)


# ---------- open / paused ----------

def set_status(con, name: str, is_open: bool) -> dict:
    c = _creds(con, name)
    if name == "ubereats":
        ok, d = IG._json_req(ENDPOINTS["ubereats"]["status"].format(store_id=c["store_id"]),
                             "POST", _headers(name, c),
                             {"status": "ONLINE" if is_open else "PAUSED",
                              "reason": "" if is_open else "Paused from Business Control"})
    else:
        ok, d = IG._json_req(ENDPOINTS["doordash"]["status"].format(location_id=c["location_id"]),
                             "PUT", _headers(name, c),
                             {"is_active": bool(is_open),
                              "reason": "" if is_open else "Paused from Business Control"})
    IG.log(con, name, "store_status", ok, "open" if is_open else "paused")
    if not ok:
        raise HTTPException(400, f"{IG.PROVIDERS[name]['label']} said: {d}")
    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES(?,?)",
                (f"marketplace_open:{name}", "1" if is_open else "0"))
    con.commit()
    return {"ok": True, "open": bool(is_open)}


def is_open(con, name: str) -> bool:
    r = con.execute("SELECT v FROM store_meta WHERE k=?",
                    (f"marketplace_open:{name}",)).fetchone()
    return (r["v"] if r else "1") == "1"


# ---------- orders in ----------

def _lines_uber(o: dict) -> tuple:
    items = []
    for cart in o.get("carts") or ([o["cart"]] if o.get("cart") else []):
        for it in cart.get("items") or []:
            q = it.get("quantity")
            if isinstance(q, dict):
                q = ((q.get("in_sellable_unit") or {}).get("quantity")
                     or q.get("quantity") or 1)
            items.append({"sku": it.get("external_data") or it.get("id") or "",
                          "qty": int(q or 1)})
    who = o.get("eater") or o.get("customer") or {}
    name = (f"{who.get('first_name','')} {who.get('last_name','')}".strip()
            or who.get("name") or "Uber Eats customer")
    return items, name


def _lines_doordash(o: dict) -> tuple:
    items = [{"sku": it.get("merchant_supplied_id") or it.get("sku") or "",
              "qty": int(it.get("quantity") or 1)}
             for it in (o.get("items") or [])]
    who = o.get("consumer") or o.get("customer") or {}
    name = (f"{who.get('first_name','')} {who.get('last_name','')}".strip()
            or who.get("name") or "DoorDash customer")
    return items, name


def inbound_order(con, name: str, body: dict) -> dict:
    """Uber sends a notification with the order's id and expects us to
    fetch it; DoorDash sends the order itself. Either way one row lands
    in marketplace_orders, one order in the queue, and the app hears
    an acceptance."""
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    c = _creds(con, name)
    order = body
    ext = str(body.get("id") or body.get("order_id") or body.get("external_id") or "")
    if name == "ubereats":
        rid = (body.get("meta") or {}).get("resource_id")
        if rid and not body.get("cart") and not body.get("carts"):
            ok, fetched = IG._req(ENDPOINTS["ubereats"]["order"].format(order_id=rid),
                                  headers=_headers(name, c))
            if not ok:
                raise HTTPException(400, f"Uber said: {fetched}")
            order, ext = fetched, str(rid)
        elif rid:
            ext = str(rid)
    if not ext:
        raise HTTPException(400, "no order id on that")
    have = con.execute("SELECT * FROM marketplace_orders WHERE provider=? AND"
                       " external_id=?", (name, ext)).fetchone()
    if have and have["order_id"]:
        return {"ok": True, "order_id": have["order_id"], "already": True}
    items, who = (_lines_uber if name == "ubereats" else _lines_doordash)(order)
    from .main import _inbound_order
    state, detail, oid = "accepted", "", 0
    try:
        oid = _inbound_order(con, name, {"items": items, "customer": who,
                                          "address": f"{IG.PROVIDERS[name]['label']} delivery",
                                          "city": ""})
    except HTTPException as e:
        state, detail = "failed", str(e.detail)
    con.execute(
        "INSERT INTO marketplace_orders(provider,external_id,order_id,state,detail,"
        " raw,created_at) VALUES(?,?,?,?,?,?,?)"
        " ON CONFLICT(provider, external_id) DO UPDATE SET order_id=excluded.order_id,"
        " state=excluded.state, detail=excluded.detail",
        (name, ext, oid, state, detail, json.dumps(order)[:20000], time.time()))
    con.commit()
    if state == "accepted":
        try:
            if name == "ubereats":
                IG._json_req(ENDPOINTS["ubereats"]["accept"].format(order_id=ext), "POST",
                             _headers(name, c), {"reason": "accepted"})
            else:
                IG._json_req(ENDPOINTS["doordash"]["confirm"].format(order_id=ext), "PATCH",
                             _headers(name, c),
                             {"merchant_supplied_id": str(oid), "order_status": "success"})
        except Exception:                                    # noqa: BLE001
            pass
    IG.log(con, name, "order", state == "accepted",
           f"#{oid}" if oid else detail[:200])
    if state != "accepted":
        raise HTTPException(400, detail)
    return {"ok": True, "order_id": oid}


IG.INBOUND["ubereats"] = lambda con, body: inbound_order(con, "ubereats", body)
IG.INBOUND["doordash"] = lambda con, body: inbound_order(con, "doordash", body)


# ---------- routes ----------

router = APIRouter()

from .main import base_url, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/marketplaces")
def marketplaces_page(user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "delivery"}
    out = []
    for name in PROVIDERS:
        st = status[name]
        key = con.execute("SELECT key FROM integration_inbound WHERE provider=?",
                          (name,)).fetchone()
        out.append({**st, "menu": menu_products(con, name),
                    "open": is_open(con, name),
                    "inbound_url": f"{base_url()}/api/inbound/{name}"
                                   + (f"?key={key['key']}" if key else ""),
                    "orders": [dict(r) for r in con.execute(
                        "SELECT id, external_id, order_id, state, detail, created_at"
                        " FROM marketplace_orders WHERE provider=?"
                        " ORDER BY id DESC LIMIT 30", (name,)).fetchall()]})
    return {"providers": out}


class MenuBody(BaseModel):
    product_ids: list


@router.post("/api/marketplaces/{name}/menu")
def marketplaces_menu(name: str, body: MenuBody, user=Depends(current_user),
                      con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if name not in PROVIDERS:
        raise HTTPException(404, "no such app")
    return {"ok": True, "listed": set_menu(con, name, body.product_ids)}


@router.post("/api/marketplaces/{name}/push")
def marketplaces_push(name: str, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if name not in PROVIDERS:
        raise HTTPException(404, "no such app")
    return push_menu(con, name)


class StatusBody(BaseModel):
    open: bool


@router.post("/api/marketplaces/{name}/status")
def marketplaces_status(name: str, body: StatusBody, user=Depends(current_user),
                        con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if name not in PROVIDERS:
        raise HTTPException(404, "no such app")
    return set_status(con, name, body.open)
