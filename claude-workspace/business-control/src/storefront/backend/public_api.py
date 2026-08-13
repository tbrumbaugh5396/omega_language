"""Public API (v1) — the app platform.

Third-party apps authenticate with a scoped API key (`Authorization: Bearer
sk_live_…` or `X-API-Key`). Keys are stored as SHA-256 hashes: the secret is
shown once at creation and is unrecoverable afterwards, so a leaked database
backup does not leak working credentials.

Scopes gate every route. `*` grants everything.
"""
import hashlib
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from erp.backend import db
from . import api as store

router = APIRouter(prefix="/api/v1")

SCOPES = {
    "products:read": "List and read products, variants, media, collections",
    "products:write": "Create and update products, variants, collections",
    "orders:read": "List and read orders",
    "orders:write": "Advance order status and refund",
    "customers:read": "List customers and subscribers",
    "content:write": "Create and edit pages and sections",
    "webhooks:manage": "Register and remove webhook endpoints",
}

RATE_PER_MIN = 120
_CALLS: dict[int, deque] = defaultdict(deque)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_key() -> tuple[str, str, str]:
    raw = "sk_live_" + secrets.token_urlsafe(24)
    return raw, hash_key(raw), raw[:16] + "…"


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def api_key(request: Request, authorization: str = Header(default=""),
            x_api_key: str = Header(default=""), con=Depends(get_con)):
    raw = (authorization.removeprefix("Bearer ").strip() or x_api_key.strip())
    if not raw:
        raise HTTPException(401, "provide an API key: Authorization: Bearer "
                                 "sk_live_… or X-API-Key")
    row = con.execute("SELECT * FROM api_keys WHERE key_hash=? AND active=1",
                      (hash_key(raw),)).fetchone()
    if row is None:
        raise HTTPException(401, "invalid or revoked API key")
    dq = _CALLS[row["id"]]
    now = time.monotonic()
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_PER_MIN:
        raise HTTPException(429, f"rate limit: {RATE_PER_MIN} requests/minute")
    dq.append(now)
    con.execute("UPDATE api_keys SET last_used_at=?, calls=calls+1 WHERE id=?",
                (db.now(), row["id"]))
    con.commit()
    return row


def need(scope: str):
    """Dependency factory: require a scope on the calling key."""
    def dep(key=Depends(api_key)):
        granted = [s.strip() for s in (key["scopes"] or "").split(",")]
        if "*" not in granted and scope not in granted:
            raise HTTPException(403, f"this key lacks the '{scope}' scope")
        return key
    return dep


# ---------- products ----------

@router.get("/products")
def list_products(limit: int = 50, offset: int = 0,
                  key=Depends(need("products:read")), con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY id LIMIT ? OFFSET ?",
        (min(limit, 250), offset)).fetchall()
    out = []
    for p in rows:
        d = dict(p)
        d["variants"] = [dict(v) for v in con.execute(
            "SELECT * FROM product_variants WHERE product_id=? AND active=1"
            " ORDER BY position, id", (p["id"],)).fetchall()]
        d["media"] = store.media_json(con.execute(
            "SELECT * FROM product_media WHERE product_id=?"
            " ORDER BY position, id", (p["id"],)).fetchall())
        out.append(d)
    total = con.execute(
        "SELECT COUNT(*) n FROM products WHERE active=1").fetchone()["n"]
    return {"data": out, "total": total, "limit": limit, "offset": offset}


@router.get("/products/{pid}")
def get_product(pid: int, key=Depends(need("products:read")),
                con=Depends(get_con)):
    p = con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such product")
    d = dict(p)
    d["variants"] = [dict(v) for v in con.execute(
        "SELECT * FROM product_variants WHERE product_id=? AND active=1",
        (pid,)).fetchall()]
    d["media"] = store.media_json(con.execute(
        "SELECT * FROM product_media WHERE product_id=? ORDER BY position, id",
        (pid,)).fetchall())
    return d


class ProductIn(BaseModel):
    sku: str
    name: str
    description: str = ""
    category: str = ""
    price_cents: int
    case_price_cents: int | None = None


@router.post("/products")
def create_product(body: ProductIn, key=Depends(need("products:write")),
                   con=Depends(get_con)):
    cur = con.execute(
        "INSERT INTO products(sku,name,description,category,price_cents,"
        " case_size,case_price_cents) VALUES(?,?,?,?,?,?,?)",
        (body.sku, body.name, body.description, body.category,
         body.price_cents, 12, body.case_price_cents or body.price_cents * 10))
    con.commit()
    pid = cur.lastrowid
    store.fire_webhooks("product.created", {"id": pid, "sku": body.sku,
                                            "name": body.name})
    return {"id": pid, "ok": True}


class ProductPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    price_cents: int | None = None
    active: bool | None = None


@router.patch("/products/{pid}")
def update_product(pid: int, body: ProductPatch,
                   key=Depends(need("products:write")), con=Depends(get_con)):
    if con.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
        raise HTTPException(404, "no such product")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE products SET {sets} WHERE id=?",
                    (*[int(v) if isinstance(v, bool) else v
                       for v in fields.values()], pid))
        con.commit()
    store.fire_webhooks("product.updated", {"id": pid, **fields})
    return {"ok": True, "updated": list(fields)}


@router.get("/collections")
def list_collections(key=Depends(need("products:read")), con=Depends(get_con)):
    cols = [dict(c) for c in con.execute(
        "SELECT * FROM collections ORDER BY position, name").fetchall()]
    for c in cols:
        c["product_ids"] = [r["product_id"] for r in con.execute(
            "SELECT product_id FROM collection_products WHERE collection_id=?",
            (c["id"],)).fetchall()]
    return {"data": cols}


# ---------- orders ----------

@router.get("/orders")
def list_orders(status: str = "", limit: int = 50, offset: int = 0,
                key=Depends(need("orders:read")), con=Depends(get_con)):
    sql = "SELECT * FROM orders"
    args: list = []
    if status:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [min(limit, 250), offset]
    rows = con.execute(sql, args).fetchall()
    out = []
    for o in rows:
        d = dict(o)
        d["items"] = [dict(i) for i in con.execute(
            "SELECT oi.*, p.name, p.sku FROM order_items oi"
            " JOIN products p ON p.id=oi.product_id WHERE order_id=?",
            (o["id"],)).fetchall()]
        out.append(d)
    return {"data": out, "limit": limit, "offset": offset}


@router.get("/orders/{oid}")
def get_order(oid: int, key=Depends(need("orders:read")),
              con=Depends(get_con)):
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    d = dict(o)
    d["items"] = [dict(i) for i in con.execute(
        "SELECT oi.*, p.name, p.sku FROM order_items oi"
        " JOIN products p ON p.id=oi.product_id WHERE order_id=?",
        (oid,)).fetchall()]
    return d


class OrderStatusIn(BaseModel):
    status: str


@router.post("/orders/{oid}/status")
def set_order_status(oid: int, body: OrderStatusIn,
                     key=Depends(need("orders:write")), con=Depends(get_con)):
    if body.status not in ("pending", "confirmed", "shipped", "delivered",
                           "cancelled"):
        raise HTTPException(400, "bad status")
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    con.execute("UPDATE orders SET status=? WHERE id=?", (body.status, oid))
    con.commit()
    store.fire_webhooks("order.updated", {"id": oid, "status": body.status})
    return {"ok": True, "id": oid, "status": body.status}


# ---------- customers ----------

@router.get("/customers")
def list_customers(limit: int = 50, offset: int = 0,
                   key=Depends(need("customers:read")), con=Depends(get_con)):
    rows = con.execute(
        "SELECT id, name, role, region, email, job, employment, created_at"
        " FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
        (min(limit, 250), offset)).fetchall()
    return {"data": [dict(r) for r in rows]}


@router.get("/subscribers")
def list_subscribers(key=Depends(need("customers:read")),
                     con=Depends(get_con)):
    return {"data": [dict(r) for r in con.execute(
        "SELECT * FROM store_subscribers ORDER BY id DESC LIMIT 500"
        ).fetchall()]}


# ---------- content ----------

class PageIn(BaseModel):
    slug: str
    title: str
    sections: list[dict] = []      # [{type, settings}]


@router.post("/pages")
def create_page(body: PageIn, key=Depends(need("content:write")),
                con=Depends(get_con)):
    from . import sections as sect
    slug = store.slugify(body.slug)
    con.execute(
        "INSERT INTO store_pages(slug,title,published,created_at)"
        " VALUES(?,?,1,?) ON CONFLICT(slug) DO UPDATE SET title=excluded.title",
        (slug, body.title, db.now()))
    for pos, s in enumerate(body.sections):
        if s.get("type") not in sect.SECTION_TYPES:
            continue
        con.execute(
            "INSERT INTO page_sections(page_slug,type,settings,position)"
            " VALUES(?,?,?,?)",
            (slug, s["type"],
             json.dumps({**sect.defaults_for(s["type"]),
                         **(s.get("settings") or {})}), pos))
    con.commit()
    return {"ok": True, "slug": slug, "url": f"/p/{slug}"}


# ---------- webhooks ----------

EVENTS = ["order.created", "order.updated", "product.created",
          "product.updated", "customer.created", "review.created",
          "subscriber.created"]


class HookIn(BaseModel):
    event: str
    url: str


@router.get("/webhooks")
def list_hooks(key=Depends(need("webhooks:manage")), con=Depends(get_con)):
    return {"data": [dict(r) for r in con.execute(
        "SELECT id, event, url, active FROM store_webhooks").fetchall()],
        "events": EVENTS}


@router.post("/webhooks")
def add_hook(body: HookIn, key=Depends(need("webhooks:manage")),
             con=Depends(get_con)):
    if body.event not in EVENTS:
        raise HTTPException(400, f"event must be one of {EVENTS}")
    cur = con.execute(
        "INSERT INTO store_webhooks(event,url,active) VALUES(?,?,1)",
        (body.event, body.url.strip()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/webhooks/{wid}")
def del_hook(wid: int, key=Depends(need("webhooks:manage")),
             con=Depends(get_con)):
    con.execute("DELETE FROM store_webhooks WHERE id=?", (wid,))
    con.commit()
    return {"ok": True}


# ---------- discovery ----------

@router.get("/me")
def whoami(key=Depends(api_key)):
    return {"name": key["name"], "prefix": key["prefix"],
            "scopes": [s.strip() for s in (key["scopes"] or "").split(",")],
            "calls": key["calls"], "rate_limit_per_min": RATE_PER_MIN}


ENDPOINTS = [
    ("GET", "/api/v1/me", "—", "Who this key is and what it can do"),
    ("GET", "/api/v1/products", "products:read", "List products (variants + media)"),
    ("GET", "/api/v1/products/{id}", "products:read", "One product"),
    ("POST", "/api/v1/products", "products:write", "Create a product"),
    ("PATCH", "/api/v1/products/{id}", "products:write", "Update a product"),
    ("GET", "/api/v1/collections", "products:read", "List collections"),
    ("GET", "/api/v1/orders", "orders:read", "List orders (?status=&limit=&offset=)"),
    ("GET", "/api/v1/orders/{id}", "orders:read", "One order with line items"),
    ("POST", "/api/v1/orders/{id}/status", "orders:write", "Advance fulfilment status"),
    ("GET", "/api/v1/customers", "customers:read", "List customers"),
    ("GET", "/api/v1/subscribers", "customers:read", "List email subscribers"),
    ("POST", "/api/v1/pages", "content:write", "Create a page with sections"),
    ("GET", "/api/v1/webhooks", "webhooks:manage", "List webhooks + event catalogue"),
    ("POST", "/api/v1/webhooks", "webhooks:manage", "Register a webhook"),
    ("DELETE", "/api/v1/webhooks/{id}", "webhooks:manage", "Remove a webhook"),
]


@router.get("/openapi.json")
def openapi_lite(request: Request):
    base = str(request.base_url).rstrip("/")
    paths: dict = {}
    for method, path, scope, desc in ENDPOINTS:
        p = path.replace("/api/v1", "")
        paths.setdefault(p, {})[method.lower()] = {
            "summary": desc,
            "security": [{"apiKey": []}],
            "x-scope": scope,
            "responses": {"200": {"description": "OK"}}}
    return {"openapi": "3.0.0",
            "info": {"title": "Business Control Storefront API", "version": "1.0.0"},
            "servers": [{"url": f"{base}/api/v1"}],
            "components": {"securitySchemes": {
                "apiKey": {"type": "http", "scheme": "bearer"}}},
            "paths": paths}


@router.get("/docs", response_class=HTMLResponse)
def docs(request: Request):
    base = str(request.base_url).rstrip("/")
    rows = "".join(
        f"<tr><td><code class=m data-m='{m}'>{m}</code></td>"
        f"<td><code>{p}</code></td><td><code class=sc>{s}</code></td>"
        f"<td>{d}</td></tr>" for m, p, s, d in ENDPOINTS)
    scopes = "".join(f"<tr><td><code>{k}</code></td><td>{v}</td></tr>"
                     for k, v in SCOPES.items())
    events = "".join(f"<li><code>{e}</code></li>" for e in EVENTS)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Storefront API — docs</title>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body{{font-family:Quicksand,system-ui,sans-serif;color:#3a3a3a;background:#fdfdfd;
 margin:0;padding:0 20px 60px}}
.wrap{{max-width:920px;margin:0 auto}}
h1{{color:#6c00bf;margin:34px 0 6px}} h2{{color:#6c00bf;margin:34px 0 10px}}
code{{background:#f2eefa;border-radius:6px;padding:2px 6px;font-size:13px}}
pre{{background:#1e1430;color:#eee;padding:16px;border-radius:12px;
 overflow-x:auto;font-size:13px}}
pre code{{background:none;color:inherit;padding:0}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0}}
th{{text-align:left;color:#8a77e1;border-bottom:2px solid #ebe1f5;padding:7px 6px}}
td{{border-bottom:1px solid #f2eefa;padding:7px 6px;vertical-align:top}}
.m{{font-weight:700}} .m[data-m=GET]{{color:#2a9d5c}}
.m[data-m=POST]{{color:#6c00bf}} .m[data-m=PATCH]{{color:#c47a00}}
.m[data-m=DELETE]{{color:#c01060}}
.sc{{color:#c01060}}
.note{{background:#f7f4fb;border-left:4px solid #8a77e1;padding:12px 16px;
 border-radius:0 10px 10px 0;margin:14px 0;font-size:14px}}
a{{color:#6c00bf}}
</style></head><body><div class="wrap">
<h1>Storefront API <small style="color:#8a77e1">v1</small></h1>
<p>Build apps against this store: catalog, orders, customers, content and
webhooks. Create keys in <a href="/admin">Store admin → API keys</a>.</p>

<h2>Authentication</h2>
<p>Send your key as a bearer token (or <code>X-API-Key</code>):</p>
<pre><code>curl {base}/api/v1/products \\
  -H "Authorization: Bearer sk_live_your_key_here"</code></pre>
<div class="note">Keys are stored as SHA-256 hashes — the secret is shown
<b>once</b> when you create it. Lost keys are revoked and replaced, never
recovered. Rate limit: <b>{RATE_PER_MIN} requests/minute</b> per key.</div>

<h2>Scopes</h2>
<table><tr><th>Scope</th><th>Grants</th></tr>{scopes}
<tr><td><code>*</code></td><td>Everything (use sparingly)</td></tr></table>

<h2>Endpoints</h2>
<table><tr><th>Method</th><th>Path</th><th>Scope</th><th>Description</th></tr>
{rows}</table>
<p>Machine-readable: <a href="/api/v1/openapi.json"><code>/api/v1/openapi.json</code></a></p>

<h2>Webhooks</h2>
<p>Register endpoints via the API or the admin. Every delivery is signed:</p>
<pre><code>X-Store-Signature: sha256=&lt;hmac of the raw body&gt;</code></pre>
<p>Verify with your store's webhook secret (Store admin → Webhooks):</p>
<pre><code>import hmac, hashlib
expected = "sha256=" + hmac.new(SECRET.encode(), raw_body,
                                hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-Store-Signature"])</code></pre>
<p>Events:</p><ul>{events}</ul>

<h2>Example: create a product and register a webhook</h2>
<pre><code>curl -X POST {base}/api/v1/products \\
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \\
  -d '{{"sku":"ZJ-001","name":"Sparkling Yuzu","price_cents":499}}'

curl -X POST {base}/api/v1/webhooks \\
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \\
  -d '{{"event":"order.created","url":"https://your-app.example/hooks"}}'</code></pre>
</div></body></html>"""
