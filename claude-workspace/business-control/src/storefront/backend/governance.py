"""Staff permissions and the audit log.

Both hang off one choke point: `api.admin_user`. Every store-admin request
already passes through it, so permission checks and audit records are applied
uniformly instead of being sprinkled across a hundred endpoints (and forgotten
on the hundred-and-first).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from erp.backend import audit as erp_audit
from .api import admin_user, get_con

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  actor TEXT DEFAULT '',
  action TEXT NOT NULL,                    -- POST /api/store/admin/products
  entity TEXT DEFAULT '',
  detail TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_time ON audit_log(created_at DESC);
"""

MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''",
)

PERMISSIONS = {
    "products": "Products, variants, media, collections",
    "orders": "Orders: fulfilment and refunds",
    "content": "Pages, sections, theme, blog, menus, reviews",
    "discounts": "Discount codes and gift cards",
    "customers": "Customer and subscriber lists",
    "analytics": "Store analytics",
    "settings": "Shipping, webhooks, API keys, staff, translations",
    "marketing": "Campaigns and ad creatives",
    "documents": "Contracts, policies and signatures",
    "supply": "Suppliers, materials, purchase orders and production",
}

# What each role gets when no explicit grant is recorded.
ROLE_DEFAULTS = {
    "owner": ["*"],
    "employee": ["products", "orders", "analytics"],
    "influencer": [],
    "distributor": [],
    "customer": [],
}

# Path prefix → required permission. First match wins.
PATH_RULES = [
    ("/api/store/admin/products", "products"),
    ("/api/store/admin/variants", "products"),
    ("/api/store/admin/media", "products"),
    ("/api/store/admin/collections", "products"),
    ("/api/store/admin/discounts", "discounts"),
    ("/api/store/admin/gift-cards", "discounts"),
    ("/api/store/admin/pages", "content"),
    ("/api/store/admin/sections", "content"),
    ("/api/store/admin/section-schema", "content"),
    ("/api/store/admin/theme", "content"),
    ("/api/store/admin/posts", "content"),
    ("/api/store/admin/menus", "content"),
    ("/api/store/admin/redirects", "content"),
    ("/api/store/admin/reviews", "content"),
    ("/api/store/admin/page-analytics", "analytics"),
    ("/api/store/admin/keys", "settings"),
    ("/api/store/admin/webhooks", "settings"),
    ("/api/store/admin/shipping", "settings"),
    ("/api/store/admin/translations", "settings"),
    ("/api/store/admin/currencies", "settings"),
    ("/api/store/admin/staff", "settings"),
    ("/api/store/admin/audit", "settings"),
    ("/api/store/admin/enquiries", "customers"),
    ("/api/store/admin/events", "content"),
    ("/api/store/admin/heatmap", "analytics"),
    ("/api/store/admin/tickets", "customers"),
    ("/api/store/admin/support-contact", "settings"),
    ("/api/store/admin/campaigns", "marketing"),
    ("/api/store/admin/creatives", "marketing"),
    ("/api/store/admin/documents", "documents"),
    ("/api/store/admin/signatures", "documents"),
    ("/api/store/admin/comments", "content"),
    ("/api/store/admin/page-funnel", "analytics"),
    ("/api/store/admin/discord", "settings"),
    ("/api/store/admin/email", "marketing"),
    # The ERP's own paths. Sourcing was admin-only, which meant a warehouse
    # lead couldn't book in a delivery without being made an owner — the
    # blunt kind of permission that gets granted once and never revoked.
    ("/api/supply", "supply"),
]


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass


def granted(user) -> list:
    """Explicit grants win; otherwise fall back to the role default.
    The is_admin flag remains a superuser bit."""
    try:
        explicit = (user["permissions"] or "").strip()
    except (KeyError, IndexError):
        explicit = ""
    if explicit:
        return [p.strip() for p in explicit.split(",") if p.strip()]
    if user["is_admin"]:
        return ["*"]
    return ROLE_DEFAULTS.get(user["role"], [])


def permission_for(path: str) -> str | None:
    for prefix, perm in PATH_RULES:
        if path.startswith(prefix):
            return perm
    return None


def check(user, path: str) -> None:
    perm = permission_for(path)
    if perm is None:
        return
    have = granted(user)
    if "*" in have or perm in have:
        return
    raise HTTPException(
        403, f"your account lacks the '{perm}' permission "
             f"({PERMISSIONS.get(perm, perm)})")


def audit(request, action: str, entity: str = "", detail: str = "") -> None:
    """Describe what just happened, in business terms.

    This used to insert its own row. Since every request already produces one
    from the middleware, that meant two entries for the same action — so it
    now annotates that row instead. The handler knows what it did; the
    middleware knows the outcome; the log gets one line with both.
    """
    erp_audit.note(request, f"{action}: {detail}" if detail else action)


# ---------- endpoints ----------

@router.get("/api/store/admin/whoami")
def whoami(u=Depends(admin_user)):
    """Deliberately has no PATH_RULES entry, so any signed-in staff member
    can ask what they're allowed to do. The back office uses it to route
    people to the right surface and hide tabs they can't use."""
    perms = granted(u)
    return {"id": u["id"], "name": u["name"], "role": u["role"],
            "is_admin": bool(u["is_admin"]), "job": u["job"],
            "permissions": perms,
            "back_office": bool(perms)}


@router.get("/api/store/admin/staff")
def list_staff(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT id, name, role, is_admin, active, permissions FROM users"
        " WHERE is_admin=1 OR role IN ('owner','employee')"
        " ORDER BY is_admin DESC, name").fetchall()
    return {"staff": [{**dict(r), "effective": granted(r)} for r in rows],
            "permissions": PERMISSIONS}


class PermBody(BaseModel):
    permissions: list


@router.post("/api/store/admin/staff/{uid}/permissions")
def set_permissions(uid: int, body: PermBody, request: Request,
                    u=Depends(admin_user), con=Depends(get_con)):
    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        raise HTTPException(404, "no such user")
    if target["id"] == u["id"]:
        raise HTTPException(400, "you can't change your own permissions")
    clean = [p for p in body.permissions if p in PERMISSIONS or p == "*"]
    con.execute("UPDATE users SET permissions=? WHERE id=?",
                (",".join(clean), uid))
    con.commit()
    audit(request, "set permissions", f"user:{uid}",
          f"{target['name']} → {','.join(clean) or 'role default'}")
    return {"ok": True, "permissions": clean}


@router.get("/api/store/admin/audit")
def read_audit(limit: int = 200, u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
        (min(limit, 500),)).fetchall()]
