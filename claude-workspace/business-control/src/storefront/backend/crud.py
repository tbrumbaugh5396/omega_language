"""Editing and deleting what could previously only be created.

The admin grew add-only: products, collections and discounts could be made
but never changed or removed, which is fine for a demo and useless for a real
store. This module fills those gaps, plus three things that were missing
entirely:

  Unique discount codes — one-per-customer codes generated in bulk, so a
  campaign can hand out codes that can't be posted to a deals forum.

  Blog comments — off by default, moderated when on.

  The page-to-page funnel — where visitors go next, computed from the
  pageview log, which is the question "which pages leak" actually needs.
"""
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import admin_user, get_con, rate_limit, slugify

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS blog_comments (
  id INTEGER PRIMARY KEY,
  post_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  body TEXT NOT NULL,
  approved INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS blog_comments_post ON blog_comments(post_id);
"""

MIGRATIONS = (
    # Comments are per-post so a merchant can open them on one article
    # without opening them everywhere.
    "ALTER TABLE blog_posts ADD COLUMN comments_on INTEGER DEFAULT 0",
    # A code minted for one person, dead once used.
    "ALTER TABLE store_discounts ADD COLUMN unique_for TEXT DEFAULT ''",
    "ALTER TABLE store_discounts ADD COLUMN batch TEXT DEFAULT ''",
)


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass


# ---------- products ----------

class ProductEdit(BaseModel):
    name: str = ""
    sku: str = ""
    description: str = ""
    category: str = ""
    price_cents: int = 0
    case_size: int = 12
    case_price_cents: int = 0
    active: bool = True


@router.patch("/api/store/admin/products/{pid}")
def edit_product(pid: int, body: ProductEdit, u=Depends(admin_user),
                 con=Depends(get_con)):
    p = con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such product")
    sku = body.sku.strip().upper() or p["sku"]
    clash = con.execute("SELECT id FROM products WHERE sku=? AND id!=?",
                        (sku, pid)).fetchone()
    if clash:
        raise HTTPException(400, f"SKU {sku} is already used by another product")
    if body.price_cents < 0 or body.case_price_cents < 0:
        raise HTTPException(400, "prices can't be negative")
    con.execute(
        "UPDATE products SET name=?, sku=?, description=?, category=?,"
        " price_cents=?, case_size=?, case_price_cents=?, active=? WHERE id=?",
        (body.name.strip()[:160] or p["name"], sku, body.description.strip(),
         body.category.strip()[:60], body.price_cents,
         max(1, body.case_size), body.case_price_cents,
         1 if body.active else 0, pid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/products/{pid}")
def delete_product(pid: int, u=Depends(admin_user), con=Depends(get_con)):
    """Deactivates rather than deletes when the product has history.

    Hard-deleting a product that appears on past orders would leave those
    orders referencing nothing — the order total would stop reconciling and
    the customer's receipt would break. Retiring keeps the record honest.
    """
    p = con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such product")
    used = con.execute("SELECT COUNT(*) n FROM order_items WHERE product_id=?",
                       (pid,)).fetchone()["n"]
    if used:
        con.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        return {"ok": True, "action": "retired",
                "detail": f"appears on {used} order line(s), so it was "
                          f"retired rather than deleted"}
    con.execute("DELETE FROM collection_products WHERE product_id=?", (pid,))
    con.execute("DELETE FROM store_product_meta WHERE product_id=?", (pid,))
    con.execute("DELETE FROM products WHERE id=?", (pid,))
    con.commit()
    return {"ok": True, "action": "deleted"}


# ---------- collections ----------

class CollectionEdit(BaseModel):
    name: str = ""
    position: int = 0
    product_ids: list = []


@router.patch("/api/store/admin/collections/{cid}")
def edit_collection(cid: int, body: CollectionEdit, u=Depends(admin_user),
                    con=Depends(get_con)):
    c = con.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "no such collection")
    name = body.name.strip()[:80] or c["name"]
    con.execute("UPDATE collections SET name=?, slug=?, position=? WHERE id=?",
                (name, slugify(name), body.position, cid))
    con.execute("DELETE FROM collection_products WHERE collection_id=?", (cid,))
    for pid in body.product_ids[:500]:
        try:
            con.execute(
                "INSERT INTO collection_products(collection_id, product_id)"
                " VALUES(?,?)", (cid, int(pid)))
        except Exception:
            pass
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/collections/id/{cid}")
def delete_collection(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM collection_products WHERE collection_id=?", (cid,))
    con.execute("DELETE FROM collections WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}


# ---------- discounts ----------

class DiscountEdit(BaseModel):
    pct: int = 0
    active: bool = True
    usage_limit: int = 0
    per_customer_limit: int = 0
    min_subtotal_cents: int = 0
    expires_at: float = 0


@router.patch("/api/store/admin/discounts/{code}")
def edit_discount(code: str, body: DiscountEdit, u=Depends(admin_user),
                  con=Depends(get_con)):
    d = con.execute("SELECT * FROM store_discounts WHERE code=?",
                    (code.upper(),)).fetchone()
    if d is None:
        raise HTTPException(404, "no such code")
    if not 1 <= body.pct <= 100:
        raise HTTPException(400, "pct must be 1–100")
    con.execute(
        "UPDATE store_discounts SET pct=?, active=?, usage_limit=?,"
        " per_customer_limit=?, min_subtotal_cents=?, expires_at=?"
        " WHERE code=?",
        (body.pct, 1 if body.active else 0, max(0, body.usage_limit),
         max(0, body.per_customer_limit), max(0, body.min_subtotal_cents),
         body.expires_at, code.upper()))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/discounts/{code}")
def delete_discount(code: str, u=Depends(admin_user), con=Depends(get_con)):
    d = con.execute("SELECT * FROM store_discounts WHERE code=?",
                    (code.upper(),)).fetchone()
    if d is None:
        raise HTTPException(404, "no such code")
    if d["used_count"]:
        # Past orders record the code they used; deleting it would orphan
        # that reference and break the campaign attribution built on it.
        con.execute("UPDATE store_discounts SET active=0 WHERE code=?",
                    (code.upper(),))
        con.commit()
        return {"ok": True, "action": "deactivated",
                "detail": f"used on {d['used_count']} order(s), so it was "
                          f"switched off rather than deleted"}
    con.execute("DELETE FROM store_discounts WHERE code=?", (code.upper(),))
    con.commit()
    return {"ok": True, "action": "deleted"}


class UniqueBatch(BaseModel):
    prefix: str = "ZJ"
    count: int = 25
    pct: int = 10
    expires_at: float = 0
    min_subtotal_cents: int = 0


@router.post("/api/store/admin/discounts/unique")
def mint_unique(body: UniqueBatch, u=Depends(admin_user),
                con=Depends(get_con)):
    """Mint single-use codes.

    A shared code posted to a deals site gets used ten thousand times by
    people who were never the audience. One code per recipient, each dead
    after a single order, is the fix — and it makes redemption per campaign
    measurable rather than estimated.
    """
    if not 1 <= body.pct <= 100:
        raise HTTPException(400, "pct must be 1–100")
    n = max(1, min(500, body.count))
    prefix = re.sub(r"[^A-Za-z0-9]", "", body.prefix)[:8].upper() or "ZJ"
    batch = f"{prefix}-{int(time.time())}"
    made = []
    for _ in range(n):
        for _attempt in range(8):
            code = f"{prefix}-{secrets.token_hex(3).upper()}"
            try:
                con.execute(
                    "INSERT INTO store_discounts(code,pct,active,usage_limit,"
                    " per_customer_limit,min_subtotal_cents,expires_at,batch)"
                    " VALUES(?,?,1,1,1,?,?,?)",
                    (code, body.pct, max(0, body.min_subtotal_cents),
                     body.expires_at, batch))
                made.append(code)
                break
            except Exception:
                continue          # collision, try another
    con.commit()
    return {"ok": True, "batch": batch, "count": len(made), "codes": made}


@router.get("/api/store/admin/discounts/batches")
def list_batches(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT batch, COUNT(*) n, SUM(used_count) used, MAX(pct) pct,"
        " MAX(expires_at) expires FROM store_discounts"
        " WHERE batch != '' GROUP BY batch ORDER BY batch DESC").fetchall()
    return [dict(r) for r in rows]


# ---------- blog comments ----------

class CommentToggle(BaseModel):
    comments_on: bool = False


@router.post("/api/store/admin/posts/{pid}/comments-toggle")
def toggle_comments(pid: int, body: CommentToggle, u=Depends(admin_user),
                    con=Depends(get_con)):
    con.execute("UPDATE blog_posts SET comments_on=? WHERE id=?",
                (1 if body.comments_on else 0, pid))
    con.commit()
    return {"ok": True, "comments_on": bool(body.comments_on)}


class CommentBody(BaseModel):
    name: str
    email: str = ""
    body: str


@router.post("/api/store/blog/{slug}/comments")
def post_comment(slug: str, body: CommentBody, con=Depends(get_con),
                 _rl=Depends(rate_limit)):
    post = con.execute(
        "SELECT id, comments_on FROM blog_posts WHERE slug=? AND published=1",
        (slug,)).fetchone()
    if post is None:
        raise HTTPException(404, "no such post")
    if not post["comments_on"]:
        raise HTTPException(403, "comments are closed on this post")
    name, text = body.name.strip(), body.body.strip()
    if not name or not text:
        raise HTTPException(400, "a name and a comment are required")
    if len(text) > 4000:
        raise HTTPException(400, "that comment is too long")
    con.execute(
        "INSERT INTO blog_comments(post_id,name,email,body,approved,created_at)"
        " VALUES(?,?,?,?,0,?)",
        (post["id"], name[:80], body.email.strip()[:120], text, time.time()))
    con.commit()
    # Held for moderation on purpose. Auto-publishing comments on a small
    # site means the merchant finds out about spam from a customer.
    return {"ok": True, "held": True}


@router.get("/api/store/blog/{slug}/comments")
def read_comments(slug: str, con=Depends(get_con)):
    post = con.execute("SELECT id, comments_on FROM blog_posts WHERE slug=?",
                       (slug,)).fetchone()
    if post is None:
        raise HTTPException(404, "no such post")
    rows = con.execute(
        "SELECT name, body, created_at FROM blog_comments"
        " WHERE post_id=? AND approved=1 ORDER BY id", (post["id"],)).fetchall()
    return {"comments_on": bool(post["comments_on"]),
            "comments": [dict(r) for r in rows]}


@router.get("/api/store/admin/comments")
def moderation_queue(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT c.*, p.title post_title, p.slug post_slug FROM blog_comments c"
        " JOIN blog_posts p ON p.id=c.post_id ORDER BY c.approved, c.id DESC"
        " LIMIT 200").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/store/admin/comments/{cid}")
def moderate(cid: int, body: dict, u=Depends(admin_user),
             con=Depends(get_con)):
    action = body.get("action")
    if action == "approve":
        con.execute("UPDATE blog_comments SET approved=1 WHERE id=?", (cid,))
    elif action == "delete":
        con.execute("DELETE FROM blog_comments WHERE id=?", (cid,))
    else:
        raise HTTPException(400, "action must be approve or delete")
    con.commit()
    return {"ok": True}


# ---------- page-to-page funnel ----------

@router.get("/api/store/admin/page-funnel")
def page_funnel(days: int = 30, u=Depends(admin_user), con=Depends(get_con)):
    """Where visitors go next, and where they stop.

    The step funnel answers "how many reached checkout". This answers "which
    page leaks", which is the one you can act on — it reconstructs each
    visitor's path from the pageview log and counts the transitions.
    """
    since = time.time() - max(1, min(365, days)) * 86400
    rows = con.execute(
        "SELECT visitor_id, page, created_at FROM store_pageviews"
        " WHERE created_at > ? ORDER BY visitor_id, created_at",
        (since,)).fetchall()

    paths: dict[str, list] = {}
    for r in rows:
        paths.setdefault(r["visitor_id"], []).append(r["page"])

    entries: dict[str, int] = {}
    exits: dict[str, int] = {}
    views: dict[str, int] = {}
    edges: dict[tuple, int] = {}
    for pages in paths.values():
        # Collapse immediate repeats — a refresh isn't a journey.
        seq = [p for i, p in enumerate(pages) if i == 0 or p != pages[i - 1]]
        if not seq:
            continue
        entries[seq[0]] = entries.get(seq[0], 0) + 1
        exits[seq[-1]] = exits.get(seq[-1], 0) + 1
        for i, p in enumerate(seq):
            views[p] = views.get(p, 0) + 1
            if i + 1 < len(seq):
                key = (p, seq[i + 1])
                edges[key] = edges.get(key, 0) + 1

    top = sorted(views.items(), key=lambda kv: -kv[1])[:12]
    page_rows = []
    for page, n in top:
        ex = exits.get(page, 0)
        page_rows.append({
            "page": page, "views": n,
            "entries": entries.get(page, 0),
            "exits": ex,
            "exit_rate": round(100 * ex / n) if n else 0,
        })
    flow = [{"from": a, "to": b, "n": n}
            for (a, b), n in sorted(edges.items(), key=lambda kv: -kv[1])[:25]]
    return {"days": days, "sessions": len(paths), "pages": page_rows,
            "flow": flow}
