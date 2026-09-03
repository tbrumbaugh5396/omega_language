"""Business Control — FastAPI backend. Serves the API and the PWA frontend."""
import csv
import time
import io
import json
import os
import secrets
import socket

from fastapi import (Depends, FastAPI, File, Header, HTTPException, Request,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (abtest, achieve, analytics, audit, auth, chat, config, cycles,
               db, dbview, integrations, logistics, mailer, notify,
               payments, push, shopify_sub, social, supply, tenancy)

app = FastAPI(title="Business Control")
# The tenant-aware view of config: every read and every settings-page write
# lands on whichever tenant the current request resolved to. In legacy mode
# there is one tenant (None) and this is the same dict it always was.
CFG = config.proxy()


def _init_core(tid=None):
    """Schema and one-time conversions for one tenant's database."""
    tok = tenancy.CURRENT.set(tid)
    try:
        db.init()
        audit.init_tables()
        con = db.connect()
        # Any PIN still in plaintext from before hashing gets converted here.
        auth.migrate_pins(con, CFG["pin_pepper"])
        supply.init_tables(con)
        integrations.init_tables(con)
        # imported here, not at the top: learning imports main's auth deps
        # back, which only exist once this module has finished defining them
        # — and _init_core first runs at the bottom of this file, where it has
        from . import classroom, community, learning, library, materials
        from . import nutrition
        learning.init_tables(con)
        classroom.init_tables(con)
        community.init_tables(con)
        library.init_tables(con)
        materials.init_tables(con)
        nutrition.init_tables(con)
        from . import apikeys as _ak
        _ak.init_tables(con)
        con.commit()
        con.close()
    finally:
        tenancy.CURRENT.reset(tok)


@app.middleware("http")
async def audit_edits(request: Request, call_next):
    """Record every change, at the one place every change goes through.

    Doing this per-endpoint would mean remembering on each new one; doing it
    here means the log is complete by construction. The body has to be read
    before the route sees it, so it is put back on the receive channel
    afterwards — otherwise the handler would find an empty request.
    """
    method = request.method
    path = request.url.path
    if not audit.should_log(method, path):
        return await call_next(request)

    body = b""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= 100_000:
            body = await request.body()

            async def receive():
                return {"type": "http.request", "body": body,
                        "more_body": False}
            request._receive = receive

    response = await call_next(request)

    # A handler that described what it did in business terms wins over the
    # middleware's read of the raw body.
    detail = getattr(request.state, "audit_note", None) or audit.summarise(body)
    token = request.headers.get("authorization", "")
    token = token.removeprefix("Bearer ").strip()
    con = db.connect()
    try:
        user = auth.user_for_token(con, token) if token else None
        audit.record(con, user, method, path, detail, response.status_code)
        # Bookkeeping, rate-limited inside prune() to once an hour. Done on
        # the write path so the log can't grow unbounded on an install where
        # nobody ever opens the audit tab.
        audit.prune(con)
    finally:
        con.close()
    return response

@app.middleware("http")
async def resolve_tenant(request: Request, call_next):
    """Host header -> tenant, before anything touches a database.

    Added AFTER the audit middleware on purpose: Starlette runs the
    last-added middleware outermost, and audit opens its own connection
    after call_next — that write must still land in the tenant's database,
    so the tenant context has to outlive the whole audit wrapper.
    """
    # The node dock and the TLS gate are addressed to the PROCESS, not to
    # a tenant — a shipment arrives at 127.0.0.1, which no tenant claims,
    # and must not be bounced by the resolver that exists for storefronts.
    # (This is exactly what broke the first registry push to a worker: the
    # ship itself landed while the worker was still registry-less, and
    # every call after tenancy activated died here.)
    if (request.url.path.startswith("/api/node/")
            or request.url.path == "/caddy/ask"):
        return await call_next(request)
    try:
        tid = tenancy.resolve(request.headers.get("host", ""))
    except tenancy.UnknownHost as e:
        return JSONResponse({"detail": f"no tenant answers to '{e}' — "
                             "check data/tenants.json"}, status_code=404)
    except tenancy.Suspended as e:
        # 503, not 404: the site exists and is paused. Saying "no such
        # site" to a customer whose account is merely suspended is a lie,
        # and it is the lie their customers would see too.
        return JSONResponse(
            {"detail": f"'{e}' is suspended — the data is intact; ask the "
                       f"platform operator to resume it"}, status_code=503)
    # A tenant whose booked node is a real machine elsewhere is SERVED
    # from there. When public DNS points at that node directly this branch
    # never fires; when traffic arrives here (one public IP, wildcard DNS
    # at the front box), the request is proxied through. Data never lives
    # in two places — this process simply does not have it.
    if tid is not None:
        _nid = tenancy.node_of(tid)
        if _nid != tenancy.NODE_ID:
            from . import fleet
            _addr = fleet.node_addr(_nid)
            if _addr and not request.url.path.startswith("/api/node/"):
                if request.headers.get("upgrade", "").lower() == "websocket":
                    return JSONResponse(
                        {"detail": f"'{tid}' lives on node {_nid} — "
                         "websockets connect to it directly; point the "
                         "tenant's DNS at its node"}, status_code=421)
                return await _proxy_to_node(request, _addr)
    tok = tenancy.CURRENT.set(tid)
    try:
        # A read-scoped API key is refused mutations HERE, before any
        # route runs — one wall for two hundred doors, instead of two
        # hundred doors remembering to check.
        bearer = request.headers.get("authorization", "")
        bearer = bearer.removeprefix("Bearer ").strip()
        if (bearer.startswith("bck_")
                and request.method not in ("GET", "HEAD", "OPTIONS")):
            from . import apikeys
            _kcon = db.connect()
            try:
                _krow = apikeys.resolve(_kcon, bearer)
            finally:
                _kcon.close()
            if _krow is not None and _krow["scope"] == "read":
                return JSONResponse(
                    {"detail": "this API key is read-only — mint a write "
                               "key for mutations"}, status_code=403)
        return await call_next(request)
    finally:
        tenancy.CURRENT.reset(tok)


async def _proxy_to_node(request: Request, addr: str):
    """Forward one HTTP request to the node that holds the tenant.

    Hop-by-hop headers are dropped; the Host header travels intact, since
    it is the whole tenancy mechanism. A node that does not answer is a
    502 with the truth, not a hang.
    """
    import httpx
    from starlette.responses import Response as RawResponse
    body = await request.body()
    drop = {"connection", "keep-alive", "transfer-encoding", "upgrade",
            "proxy-authorization", "te", "trailers"}
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in drop}
    try:
        async with httpx.AsyncClient(timeout=60.0) as cl:
            r = await cl.request(
                request.method, addr + request.url.path,
                params=dict(request.query_params), headers=headers,
                content=body)
    except Exception as e:                              # noqa: BLE001
        return JSONResponse(
            {"detail": f"this tenant's node is not answering "
                       f"({str(e)[:100]})"}, status_code=502)
    out_drop = drop | {"content-length", "content-encoding"}
    return RawResponse(
        content=r.content, status_code=r.status_code,
        headers={k: v for k, v in r.headers.items()
                 if k.lower() not in out_drop},
        media_type=r.headers.get("content-type"))


JOBS = ["general", "driver", "dsd", "warehouse", "sales_rep", "ambassador",
        "event_staff"]
# One list, so the status-change endpoint and the order editor can't drift.
ORDER_STATUSES = ("pending", "confirmed", "shipped", "delivered", "cancelled")


# ---------- helpers ----------

def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def current_user(authorization: str = Header(default=""), con=Depends(get_con)):
    token = authorization.removeprefix("Bearer ").strip()
    user = auth.user_for_token(con, token)
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


def admin_user(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "admin only")
    return user


def permitted(perm: str):
    """Admin, or anyone explicitly granted this permission.

    The admin bit is all-or-nothing, so gating a screen on it means the only
    way to let a warehouse lead book in a delivery is to make them an owner
    — a grant that gets handed out once and never taken back. Permissions
    are the finer instrument, and they already exist for the store side.
    """
    def dep(user=Depends(current_user)):
        if user["is_admin"]:
            return user
        from storefront.backend import governance      # avoids a cycle
        if perm in governance.granted(user):
            return user
        raise HTTPException(
            403, f"your account lacks the '{perm}' permission — an owner can "
                 "grant it under Team & access")
    return dep


def order_json(con, o) -> dict:
    items = con.execute(
        "SELECT oi.*, p.name, p.sku FROM order_items oi"
        " JOIN products p ON p.id=oi.product_id WHERE order_id=?",
        (o["id"],)).fetchall()
    d = dict(o)
    d["items"] = [dict(i) for i in items]
    return d


# ---------- auth ----------

class LoginBody(BaseModel):
    name: str
    role: str = "customer"
    region: str = ""
    admin_key: str = ""
    email: str = ""
    password: str = ""
    # "" keeps the historic find-or-create; "signin" refuses to mint an
    # account by typo; "create" refuses to silently join someone else's.
    mode: str = ""


@app.post("/api/login")
def login(body: LoginBody, con=Depends(get_con)):
    existed = con.execute("SELECT 1 FROM users WHERE lower(name)=lower(?)",
                          (body.name.strip(),)).fetchone() is not None
    if body.mode == "signin" and not existed:
        raise HTTPException(404, "no account by that name — create one"
                                 " first")
    if body.mode == "create" and existed:
        raise HTTPException(409, "that name is already taken — sign in"
                                 " instead")
    # The historic mode-less find-or-create stays for scripts, seeds and
    # LAN dev — but a PUBLIC install creates accounts only through its
    # doors (the storefront's create/claim, invites, the key). A bare API
    # call with an unknown name gets the same answer sign-in gives.
    if (body.mode == "" and not existed
            and CFG.get("public_base_url")
            and not (body.admin_key
                     and body.admin_key == CFG.get("admin_key"))):
        raise HTTPException(404, "no account by that name — this install "
                                 "creates accounts through its sign-up "
                                 "doors")
    # The storefront door's role picker is a CLAIM, not a grant. Anything
    # beyond student files a request the office decides (roles.py rules);
    # the account is created as a plain customer meanwhile — so the door's
    # promise, "confirmed before it opens anything", is finally true. The
    # admin key is the exception on purpose: holding it IS the authority
    # the queue exists to consult, so a key-holder's create is direct.
    from . import roles as R
    claim = ""
    role = body.role
    if (body.mode == "create" and body.role != "owner"
            and not (body.admin_key
                     and body.admin_key == CFG.get("admin_key"))):
        wanted = R.normalise(body.role)
        if R.claimable(wanted):
            claim, role = wanted, "customer"
    try:
        u = auth.login(con, body.name, role, body.region, body.admin_key,
                       CFG, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if body.email.strip() and body.email.strip() != u["email"]:
        con.execute("UPDATE users SET email=? WHERE id=?",
                    (body.email.strip(), u["id"]))
        con.commit()
        u = con.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    # A key-holder minting someone ELSE's account (mode create) confers the
    # role, not the flag: presenting the key means "I have authority", not
    # "make this new teacher an admin". The flag rides only the roles that
    # are the admin surface. Mode-less key sign-ins keep their historic
    # meaning — claiming admin for yourself.
    if (body.mode == "create" and not existed and u["is_admin"]
            and u["role"] not in ("owner", "director")):
        con.execute("UPDATE users SET is_admin=0 WHERE id=?", (u["id"],))
        con.commit()
        u = con.execute("SELECT * FROM users WHERE id=?",
                        (u["id"],)).fetchone()
    if claim and not existed:
        con.execute("UPDATE users SET requested_role=? WHERE id=?",
                    (claim, u["id"]))
        con.commit()
        notify.push(con, f"Role request: {u['name']} asked to be"
                         f" {R.LABELS.get(claim, claim)}",
                    "Decide it under Team & access.", kind="role")
        u = con.execute("SELECT * FROM users WHERE id=?",
                        (u["id"],)).fetchone()
    if not existed:
        store_api.fire_webhooks("customer.created", {
            "id": u["id"], "name": u["name"], "role": u["role"],
            "email": u["email"] or ""})
    return auth.user_json(u)


@app.get("/api/whoami")
def whoami(user=Depends(current_user)):
    """The signed-in account, in the shape every surface's session store
    keeps — so walking from the storefront to /ops or /admin carries the
    session instead of showing a stranger a sign-in form."""
    return auth.user_json(user)


@app.get("/api/meta")
def meta(con=Depends(get_con)):
    return {"brand": CFG["brand_name"],
            # Whether this install runs the platform, so the ops app knows
            # to offer the fleet at all. False for every client tenant and
            # for a plain single-shop install.
            "is_provider": tenancy.provider() is not None
                           and tenancy.provider() == tenancy.CURRENT.get(),
            # What this install is entitled to. null = everything — a
            # tenant with no recorded grant keeps the whole product.
            "caps": tenancy.caps_of(tenancy.CURRENT.get()),
            "tagline": CFG.get("brand_tagline", ""),
            "accent": CFG.get("brand_accent", ""),
            "regions": CFG["regions"], "jobs": JOBS,
            "funnel_steps": config.FUNNEL_STEPS,
            "tracking": CFG.get("tracking", {}),
            "stripe_enabled": payments.enabled(CFG),
            "tax_bps": CFG.get("tax_bps", 0),
            "shipping_flat_cents": CFG.get("shipping_flat_cents", 0),
            "free_shipping_over_cents": CFG.get("free_shipping_over_cents", 0)}


class BrandingBody(BaseModel):
    brand_name: str = ""
    tagline: str = ""
    accent: str = ""


@app.post("/api/admin/branding")
def set_branding(body: BrandingBody, user=Depends(admin_user)):
    if body.brand_name.strip():
        CFG["brand_name"] = body.brand_name.strip()[:60]
    CFG["brand_tagline"] = body.tagline.strip()[:120]
    accent = body.accent.strip()
    if accent and not (accent.startswith("#") and len(accent) in (4, 7)):
        raise HTTPException(400, "accent must be a hex color like #35b26b")
    CFG["brand_accent"] = accent
    config.save(CFG)
    return {"ok": True}


def UPLOADS():
    # A function, not a constant: the path is the tenant's.
    return tenancy.data_dir() / "uploads"
IMAGE_MAGIC = {b"\xff\xd8": "image/jpeg", b"\x89P": "image/png",
               b"RI": "image/webp", b"GI": "image/gif"}


class ImageBody(BaseModel):
    data_url: str          # data:image/...;base64,....


@app.post("/api/admin/products/{pid}/image")
def set_product_image(pid: int, body: ImageBody, user=Depends(admin_user),
                      con=Depends(get_con)):
    import base64
    p = con.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such product")
    try:
        _, b64 = body.data_url.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(400, "bad image data")
    if len(raw) > 2_000_000:
        raise HTTPException(400, "image too large (2 MB max)")
    if raw[:2] not in IMAGE_MAGIC:
        raise HTTPException(400, "not a recognized image")
    UPLOADS().mkdir(parents=True, exist_ok=True)
    (UPLOADS() / f"product_{pid}").write_bytes(raw)
    con.execute("UPDATE products SET image=1 WHERE id=?", (pid,))
    con.commit()
    return {"ok": True}


@app.get("/media/product/{pid}")
def product_image(pid: int, con=Depends(get_con)):
    f = UPLOADS() / f"product_{pid}"
    if not f.exists():
        # Newer uploads live in the storefront media pipeline.
        from storefront.backend import api as store_api
        alt = store_api.primary_media_file(con, pid)
        if alt is None:
            raise HTTPException(404, "no image")
        # Not always a JPEG any more: cut-out product art keeps its alpha,
        # and mislabelling a PNG here is what puts a white box behind a can.
        # must-revalidate, not immutable: this path always means "the
        # current primary image", so it has to notice when that changes.
        return FileResponse(
            alt, media_type=store_api.MIME.get(alt.suffix, "image/jpeg"),
            headers={"Cache-Control": "no-cache"})
    raw2 = f.read_bytes()[:2]
    return FileResponse(f, media_type=IMAGE_MAGIC.get(raw2, "image/jpeg"))


class TrackingBody(BaseModel):
    ga_measurement_id: str = ""
    meta_pixel_id: str = ""
    tiktok_pixel_id: str = ""


@app.post("/api/admin/tracking")
def set_tracking(body: TrackingBody, user=Depends(admin_user)):
    CFG["tracking"] = {"ga_measurement_id": body.ga_measurement_id.strip(),
                       "meta_pixel_id": body.meta_pixel_id.strip(),
                       "tiktok_pixel_id": body.tiktok_pixel_id.strip()}
    config.save(CFG)
    return {"ok": True, "tracking": CFG["tracking"]}


class PaymentsBody(BaseModel):
    secret_key: str = ""


@app.get("/api/admin/payments")
def payments_config(user=Depends(admin_user)):
    """Whether card payments are on, and never the key itself."""
    key = CFG.get("stripe_secret_key", "")
    return {"enabled": payments.enabled(CFG),
            "key_set": bool(key),
            # Enough to tell a live key from a test one at a glance, without
            # putting a working credential on a screen.
            "mode": ("live" if key.startswith("sk_live") else
                     "test" if key.startswith("sk_test") else ""),
            "tail": key[-4:] if key else ""}


@app.post("/api/admin/payments")
def set_payments(body: PaymentsBody, user=Depends(admin_user)):
    """Turn card payments on by pasting a Stripe secret key.

    The key is checked against Stripe before it's saved — a mistyped key that
    only fails at checkout means a customer meets the error, not the person
    who typed it. Sending an empty string turns card payments off, which
    falls the shop back to pay-on-delivery rather than breaking it.
    """
    key = body.secret_key.strip()
    if not key:
        CFG["stripe_secret_key"] = ""
        config.save(CFG)
        return {"ok": True, "enabled": False}
    if not key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
        raise HTTPException(
            400, "that doesn't look like a Stripe secret key — it starts "
                 "sk_test_ or sk_live_. The publishable key (pk_) is the "
                 "wrong one; this side needs the secret.")
    ok, detail = payments.verify_key(key)
    if not ok:
        raise HTTPException(400, f"Stripe rejected that key: {detail}")
    CFG["stripe_secret_key"] = key
    config.save(CFG)
    return {"ok": True, "enabled": True,
            "mode": "live" if key.startswith(("sk_live", "rk_live")) else "test"}


# ---------- QR codes & QR sign-in ----------

def lan_url() -> str:
    """Best-guess LAN address so QR codes work from phones on the same wifi."""
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return f"http://{ip}:{CFG.get('port', 8860)}"


def base_url() -> str:
    """Public URL when deployed (config public_base_url), else the LAN IP.
    Everything outward-facing — QRs, sign-in links, emails, Stripe returns —
    goes through here."""
    return (CFG.get("public_base_url") or "").rstrip("/") or lan_url()


@app.get("/api/net")
def net_info():
    return {"lan_url": base_url()}


@app.get("/api/qr.svg")
def qr_svg(data: str):
    if not data or len(data) > 512:
        raise HTTPException(400, "data must be 1-512 chars")
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


class MeBody(BaseModel):
    name: str | None = None
    email: str | None = None
    region: str | None = None
    pin: str | None = None


@app.get("/api/me")
def read_me(user=Depends(current_user), con=Depends(get_con)):
    """Your own profile. Separate from the admin user endpoints, which
    deliberately refuse to edit the caller's own account — that guard exists
    to stop someone granting themselves a role, and it shouldn't also stop
    them fixing a typo in their name."""
    return {"id": user["id"], "name": user["name"], "email": user["email"],
            "role": user["role"], "job": user["job"],
            "region": user["region"], "is_admin": bool(user["is_admin"]),
            "employment": user["employment"],
            "has_password": bool(user["password_hash"]),
            "member_since": user["created_at"],
            # The checkout needs to know whether to ask for an email, and
            # asking the account is the only way to tell.
            "email_confirmed": bool(user["email_verified_at"]),
            # The token is deliberately absent. The caller sent it to get
            # here, so echoing it back adds nothing and puts a credential in
            # one more response body.
            "has_pin": bool((user["pin_hash"] or "").strip())}


@app.post("/api/me")
def update_me(body: MeBody, user=Depends(current_user), con=Depends(get_con)):
    """Name, email, region and time-clock PIN only. Role, job and admin are
    deliberately absent — those are grants, not preferences, and a user who
    can change their own role can promote themselves."""
    fields, args = [], []
    if body.name is not None:
        n = body.name.strip()
        if len(n) < 2:
            raise HTTPException(400, "name is too short")
        fields.append("name=?"); args.append(n[:80])
    if body.email is not None:
        e = body.email.strip()
        if e and "@" not in e:
            raise HTTPException(400, "that email doesn't look right")
        fields.append("email=?"); args.append(e[:120])
    if body.region is not None:
        fields.append("region=?"); args.append(body.region.strip()[:40])
    if body.pin is not None:
        pin = body.pin.strip()
        if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
            raise HTTPException(400, "PIN must be 4–8 digits")
        # Uniqueness is checked on the hash, since the clock identifies
        # someone by their PIN alone and two people sharing one would mean
        # the wrong person's timesheet.
        h = auth.hash_pin(pin, CFG["pin_pepper"]) if pin else ""
        if h and con.execute(
                "SELECT 1 FROM users WHERE pin_hash=? AND id!=?",
                (h, user["id"])).fetchone():
            raise HTTPException(400, "that PIN is already taken")
        fields.append("pin_hash=?"); args.append(h)
    if not fields:
        return {"ok": True}
    args.append(user["id"])
    con.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", tuple(args))
    con.commit()
    return {"ok": True}


@app.post("/api/me/qr")
def my_qr_login(user=Depends(current_user), con=Depends(get_con)):
    """A sign-in QR for your own phone. Same single-use, short-lived token as
    the admin-issued one — scanning it on a handset saves typing a password
    into a cracked screen in a cold warehouse."""
    token = secrets.token_urlsafe(24)
    ttl = CFG.get("qr_login_ttl_sec", 600)
    con.execute("INSERT INTO login_tokens(token,user_id,expires_at)"
                " VALUES(?,?,?)", (token, user["id"], db.now() + ttl))
    con.commit()
    return {"url": f"{base_url()}/qr-login/{token}", "expires_sec": ttl}


@app.post("/api/admin/users/{uid}/qr")
def qr_login_link(uid: int, user=Depends(admin_user), con=Depends(get_con)):
    """One-time sign-in link for a user — render it as a QR, they scan it on
    their phone and land signed in. Single use, short expiry."""
    target = con.execute("SELECT * FROM users WHERE id=? AND active=1",
                         (uid,)).fetchone()
    if target is None:
        raise HTTPException(404, "no such active user")
    token = secrets.token_urlsafe(24)
    ttl = CFG.get("qr_login_ttl_sec", 600)
    con.execute("INSERT INTO login_tokens(token,user_id,expires_at)"
                " VALUES(?,?,?)", (token, uid, db.now() + ttl))
    con.commit()
    return {"url": f"{base_url()}/qr-login/{token}", "name": target["name"],
            "expires_sec": ttl}


@app.get("/qr-login/{token}")
def qr_login(token: str, con=Depends(get_con)):
    row = con.execute(
        "SELECT * FROM login_tokens WHERE token=? AND used=0 AND expires_at>?",
        (token, db.now())).fetchone()
    if row is None:
        return HTMLResponse("<h3>Sign-in link expired or already used.</h3>"
                            "<p>Ask an admin for a fresh QR.</p>", 410)
    con.execute("UPDATE login_tokens SET used=1 WHERE token=?", (token,))
    con.commit()
    u = con.execute("SELECT * FROM users WHERE id=? AND active=1",
                    (row["user_id"],)).fetchone()
    if u is None:
        return HTMLResponse("<h3>Account is deactivated.</h3>", 410)
    payload = json.dumps(auth.user_json(u))
    return HTMLResponse(
        f"<script>localStorage.setItem('bc_user', JSON.stringify({payload}));"
        "location.replace('/ops/');</script>")


# ---------- products & orders ----------

@app.get("/api/products")
def products(con=Depends(get_con)):
    """Every live product, wearing what it IS. The back office groups and
    tints by the same kinds the shop does — one table, so the two faces
    of the catalogue cannot sort it differently."""
    from storefront.backend.api import KIND_BY_ID, kind_of
    rows = con.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY category, name"
    ).fetchall()
    meta: dict = {}
    for m in con.execute("SELECT product_id, k, v FROM store_product_meta"
                         " WHERE k IN ('kind','colour','quote','caps','unlisted')"
    ).fetchall():
        meta.setdefault(m["product_id"], {})[m["k"]] = m["v"]
    out = []
    for r in rows:
        p = dict(r)
        md = meta.get(p["id"], {})
        p["kind"] = kind_of(md)
        p["kind_label"] = KIND_BY_ID[p["kind"]]["label"]
        p["colour"] = md.get("colour") or KIND_BY_ID[p["kind"]]["colour"]
        p["quote"] = md.get("quote", "") == "1"
        p["caps"] = [x for x in (md.get("caps", "") or "").split(",") if x]
        # off the public shelf, but the back office must still see it —
        # somebody is paying for it and somebody will have to service it
        p["unlisted"] = md.get("unlisted", "") == "1"
        out.append(p)
    # In the shelf's order, not the alphabet's: what you run on, what keeps
    # it running, then the work that builds it. The shop reads the same
    # table, so the two faces cannot disagree about where a thing belongs.
    order = {k["id"]: i for i, k in enumerate(KIND_BY_ID.values())}
    out.sort(key=lambda p: (order.get(p["kind"], 99), p["price_cents"],
                            p["name"]))
    return out


class ProductBody(BaseModel):
    sku: str
    name: str
    description: str = ""
    category: str = ""
    price_cents: int
    case_size: int = 12
    case_price_cents: int


@app.post("/api/admin/products")
def add_product(body: ProductBody, user=Depends(admin_user), con=Depends(get_con)):
    con.execute(
        "INSERT INTO products(sku,name,description,category,price_cents,"
        " case_size,case_price_cents) VALUES(?,?,?,?,?,?,?)",
        (body.sku, body.name, body.description, body.category,
         body.price_cents, body.case_size, body.case_price_cents))
    con.commit()
    return {"ok": True}


class OrderItemBody(BaseModel):
    product_id: int
    qty: int
    variant_id: int | None = None    # storefront product_variants row


class OrderBody(BaseModel):
    items: list[OrderItemBody]
    email: str = ""             # required when ordering without an account
    store_id: int | None = None
    affiliate_code: str = ""
    visitor_id: str = ""
    region: str = ""
    ship_name: str = ""
    address: str = ""
    city: str = ""
    postal: str = ""
    phone: str = ""
    pay_method: str = ""        # "card" to request Stripe Checkout
    discount_code: str = ""     # storefront discount code (store_discounts)
    gift_card_code: str = ""    # storefront gift card (gift_cards)
    shipping_method_id: int | None = None  # store_shipping_methods row


def customer_for_order(con, authorization: str, body):
    """Who this order belongs to — signed in, or a guest identified by email.

    Guest checkout goes through the same endpoint rather than a parallel one,
    because the interesting parts of placing an order (pricing, stock,
    discounts, payment, the notifications that follow) are exactly the parts
    you must not end up with two copies of.

    Two rules make the guest path safe. It never returns a token, so ordering
    to an address is not a way into the account that owns it. And a guest is
    always priced as a customer even when the email belongs to a distributor
    — otherwise typing a wholesaler's address into the guest form would be a
    way to buy at wholesale.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        u = auth.user_for_token(con, token)
        if u is not None:
            return u, False
    email = (body.email or "").strip().lower()
    name = body.ship_name.strip()
    if not email or "@" not in email:
        raise HTTPException(
            400, "an email address is needed to order without signing in — "
                 "it's where the receipt and tracking go")
    if not name:
        raise HTTPException(400, "a name is needed for the delivery")
    existing = con.execute(
        "SELECT * FROM users WHERE lower(email)=? AND active=1",
        (email,)).fetchone()
    if existing is not None:
        return existing, True
    cur = con.execute(
        "INSERT INTO users(name,email,role,token,region,created_at)"
        " VALUES(?,?,'customer',?,?,?)",
        (name[:80], email[:120], secrets.token_urlsafe(24),
         body.region or "", db.now()))
    con.commit()
    return con.execute("SELECT * FROM users WHERE id=?",
                       (cur.lastrowid,)).fetchone(), True


@app.post("/api/orders")
def place_order(body: OrderBody, authorization: str = Header(default=""),
                con=Depends(get_con)):
    """Place it, or hold it until the email is confirmed.

    Pay-on-delivery is the one route where nothing is verified at the moment
    of ordering: no card is charged and, for a guest, nobody has proved they
    own the address. So a first pay-on-delivery order from an unconfirmed
    email is held rather than placed, and a link makes it real. Once an
    address has confirmed once it isn't asked again — the check is there to
    stop orders being sent to people who never asked for them, not to make
    regulars click a link every time.
    """
    if not body.items:
        raise HTTPException(400, "empty order")
    user, as_guest = customer_for_order(con, authorization, body)
    # Check the order is well-formed before holding it. Emailing someone a
    # confirmation link for an order that can never be placed wastes their
    # time and hides the real problem behind a click.
    _check_order_shape(order_kind(user, as_guest), body)
    _refuse_plans(con, body)
    cod = (body.pay_method or "").lower() != "card"
    if cod and user["role"] != "distributor" and not user["email_verified_at"]:
        # Nothing is charged and nothing is proven at this point, so there
        # has to be a reachable address to confirm against. An account with
        # no email on it can't be sent goods on trust.
        email = (user["email"] or "").strip() or (body.email or "").strip()
        if not email:
            raise HTTPException(
                400, "paying on delivery needs an email address to confirm "
                     "the order — add one, or pay by card")
        if not (user["email"] or "").strip():
            con.execute("UPDATE users SET email=? WHERE id=?",
                        (email[:120], user["id"]))
            con.commit()
            user = con.execute("SELECT * FROM users WHERE id=?",
                               (user["id"],)).fetchone()
        return hold_for_confirmation(con, user, body)
    return _place(con, user, body, as_guest)


def _refuse_plans(con, body) -> None:
    """A plan is a commitment on a clock; this route charges once.

    The check sits ahead of the confirm/place fork so both paths cross it —
    letting one through would take a month's money and then never again, or
    a year's as a single payment. Both are the kind of wrong that reaches a
    bank statement.
    """
    for it in body.items:
        row = con.execute(
            "SELECT p.name FROM products p JOIN store_product_meta m"
            " ON m.product_id=p.id AND m.k='billing' AND m.v!=''"
            " WHERE p.id=?", (it.product_id,)).fetchone()
        if row:
            raise HTTPException(
                400, f"{row['name']} bills every month — it is started from "
                     f"its own page, not bought in the cart")


CONFIRM_TTL = 3 * 86400


def hold_for_confirmation(con, user, body):
    """Park the order and email a link that makes it real.

    The order isn't priced or reserved here — it is re-placed from scratch on
    confirmation, through the same function a direct order goes through. That
    keeps one code path for what an order *is*, and it means stock and prices
    are read when the order actually becomes one rather than days earlier.
    """
    token = secrets.token_urlsafe(24)
    con.execute(
        "INSERT INTO pending_orders(token,user_id,email,payload,as_guest,"
        " created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
        (token, user["id"], user["email"], body.model_dump_json(),
         1 if not user["password_hash"] else 0,
         db.now(), db.now() + CONFIRM_TTL))
    con.commit()
    link = f"{base_url()}/confirm-order/{token}"
    try:
        mailer.log_and_send(
            con, CFG, user["id"], user["email"], "order-confirm",
            "Confirm your order",
            f"Hi {user['name']},\n\nYou asked to pay on delivery, so we need "
            "to know this address is yours before we send anything.\n\n"
            f"Confirm the order: {link}\n\n"
            "The link works for three days. If you didn't order anything, "
            "ignore this — nothing has been placed and nobody will call.",
            f"confirm-{token[:12]}")
        con.commit()
    except Exception:
        pass          # a mail failure must not lose the order
    return {"awaiting_confirmation": True, "email": user["email"],
            "expires_in_days": CONFIRM_TTL // 86400}


@app.get("/confirm-order/{token}")
def confirm_order_page(token: str, con=Depends(get_con)):
    row = con.execute("SELECT * FROM pending_orders WHERE token=?",
                      (token,)).fetchone()

    def page(title: str, body: str) -> HTMLResponse:
        return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>body{{margin:0;background:#f7f6f3;color:#1c1a17;padding:40px 18px;
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif}}
 .c{{max-width:520px;margin:0 auto;background:#fff;border:1px solid #e3e0d9;
 border-radius:14px;padding:26px}} h1{{font-size:22px;margin:0 0 10px}}
 a{{color:#6d55d6}}</style>
<div class="c"><h1>{title}</h1>{body}</div>""")

    if row is None:
        return page("Link not valid",
                    "<p>This confirmation link has already been used or was "
                    "mistyped. Nothing has been placed.</p>")
    if row["placed_order_id"]:
        return page("Already confirmed",
                    f"<p>Order #{row['placed_order_id']} is confirmed and on "
                    "its way through.</p>")
    if row["expires_at"] < db.now():
        return page("Link expired",
                    "<p>This link was only good for a few days. Nothing was "
                    'placed — please <a href="/">order again</a>.</p>')

    user = con.execute("SELECT * FROM users WHERE id=?",
                       (row["user_id"],)).fetchone()
    try:
        body = OrderBody(**json.loads(row["payload"]))
        o = _place(con, user, body, bool(row["as_guest"]))
    except HTTPException as e:
        return page("Couldn't place that order",
                    f"<p>{esc_html(str(e.detail))}</p>"
                    '<p><a href="/">Start again</a></p>')
    con.execute("UPDATE pending_orders SET placed_order_id=? WHERE id=?",
                (o["id"], row["id"]))
    # Confirming proves the address. Ask once, not on every future order.
    con.execute("UPDATE users SET email_verified_at=? WHERE id=?",
                (db.now(), user["id"]))
    con.commit()
    return page("Order confirmed",
                f"<p>Thank you — order #{o['id']} is placed, paying on "
                "delivery. A receipt is on its way.</p>"
                '<p><a href="/">Back to the shop</a></p>')


def esc_html(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def order_kind(user, as_guest: bool) -> str:
    """A guest is a customer, whatever the matched account happens to be."""
    if as_guest:
        return "customer"
    return "distributor" if user["role"] == "distributor" else "customer"


def _check_order_shape(kind: str, body) -> None:
    """What every order needs, wherever it is being checked from. One
    function so the version that runs before a hold and the version that
    runs when it is finally placed can't disagree."""
    if kind == "customer" and not (body.ship_name.strip()
                                   and body.address.strip()
                                   and body.city.strip()):
        raise HTTPException(400, "shipping name, address, and city required")


def _card_failed(con, oid: int, err: Exception) -> HTTPException:
    """A card payment that couldn't be started leaves no order behind.

    This used to keep the order and quietly mark it pay-on-delivery. Two
    things wrong with that: the customer believes they have paid when they
    haven't, and — since pay-on-delivery now waits on a confirmed email — it
    was also the one route that skipped that check. An order nobody agreed to
    the terms of is worse than no order, so it is rolled back and the person
    is told, which leaves them able to retry or choose pay-on-delivery
    themselves.
    """
    con.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
    con.execute("DELETE FROM orders WHERE id=?", (oid,))
    con.commit()
    return HTTPException(
        502, "we couldn't start the card payment just now, so nothing has "
             "been ordered and nothing has been charged. Try again, or "
             "choose pay on delivery.")


def _place(con, user, body, as_guest):
    kind = order_kind(user, as_guest)
    _check_order_shape(kind, body)
    subtotal = 0
    lines = []
    stripe_items = []
    for it in body.items:
        p = con.execute("SELECT * FROM products WHERE id=? AND active=1",
                        (it.product_id,)).fetchone()
        if p is None or it.qty <= 0:
            raise HTTPException(400, f"bad item {it.product_id}")
        # Distributors buy by the case at wholesale.
        unit = p["case_price_cents"] if kind == "distributor" else p["price_cents"]
        vid, vname = None, ""
        if it.variant_id and kind == "customer":
            v = con.execute(
                "SELECT * FROM product_variants WHERE id=? AND product_id=?"
                " AND active=1", (it.variant_id, p["id"])).fetchone()
            if v is None:
                raise HTTPException(400, f"bad variant {it.variant_id}")
            unit, vid, vname = v["price_cents"], v["id"], v["name"]
            con.execute(
                "UPDATE product_variants SET stock=MAX(0,stock-?) WHERE id=?",
                (it.qty, v["id"]))
        subtotal += unit * it.qty
        lines.append((p["id"], it.qty, unit, vid, vname))
        stripe_items.append(
            {"name": p["name"] + (f" — {vname}" if vname else ""),
             "unit_cents": unit, "qty": it.qty})
    # Discounts (percent · fixed · free shipping · BOGO, plus automatic
    # offers) all resolve through the storefront's one rules engine.
    discount, disc_code, disc_id, free_ship = 0, "", None, False
    if kind == "customer":
        dres = store_promos.compute_discount(
            con, body.discount_code, subtotal, lines, user["id"])
        discount = dres["amount_cents"]
        disc_code = dres["code"]
        disc_id = dres["discount_id"]
        free_ship = dres["free_shipping"]
    discounted = subtotal - discount
    tax = discounted * CFG.get("tax_bps", 0) // 10000 if kind == "customer" else 0
    shipping = 0
    if kind == "customer":
        method = None
        if body.shipping_method_id:
            method = con.execute(
                "SELECT * FROM store_shipping_methods WHERE id=? AND active=1",
                (body.shipping_method_id,)).fetchone()
        if method:
            shipping = method["price_cents"]
            # Standard shipping (position 0) honours the free-over threshold.
            if (method["position"] == 0 and
                    discounted >= CFG.get("free_shipping_over_cents", 0)):
                shipping = 0
        elif discounted < CFG.get("free_shipping_over_cents", 0):
            shipping = CFG.get("shipping_flat_cents", 0)
        if free_ship:
            shipping = 0
    # Gift cards settle last, against the full amount due.
    gift = 0
    if body.gift_card_code.strip() and kind == "customer":
        g = store_promos.gift_balance(con, body.gift_card_code)
        if g:
            gift = min(g["balance_cents"], discounted + tax + shipping)
    total = discounted + tax + shipping - gift
    pay_status = "on_terms" if kind == "distributor" else "cod"
    want_card = body.pay_method == "card" and payments.enabled(CFG)
    if want_card:
        pay_status = "unpaid"
    region = body.region or user["region"] or ""
    cur = con.execute(
        "INSERT INTO orders(user_id,kind,region,store_id,subtotal_cents,"
        " discount_cents,discount_code,gift_cents,gift_card_code,tax_cents,"
        " shipping_cents,total_cents,payment_status,ship_name,address,city,"
        " postal,phone,affiliate_code,visitor_id,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], kind, region, body.store_id, subtotal, discount,
         disc_code, gift, body.gift_card_code.strip().upper() if gift else "",
         tax, shipping, total, pay_status, body.ship_name.strip(),
         body.address.strip(), body.city.strip(), body.postal.strip(),
         body.phone.strip(), body.affiliate_code.strip(), body.visitor_id,
         db.now()))
    oid = cur.lastrowid
    if disc_id:
        store_promos.record_redemption(con, disc_id, oid, user["id"], discount)
    if gift:
        store_promos.apply_gift_card(con, body.gift_card_code, gift, oid)
    checkout_url = None
    if want_card:
        try:
            sess = payments.create_checkout(CFG, oid, stripe_items,
                                            max(0, tax + shipping - discount),
                                            base_url())
            if sess:
                con.execute("UPDATE orders SET payment_ref=? WHERE id=?",
                            (sess["id"], oid))
                checkout_url = sess["url"]
        except Exception as e:                          # noqa: BLE001
            raise _card_failed(con, oid, e)
    for pid, qty, unit, vid, vname in lines:
        con.execute("INSERT INTO order_items(order_id,product_id,qty,"
                    " unit_price_cents,variant_id,variant_name)"
                    " VALUES(?,?,?,?,?,?)", (oid, pid, qty, unit, vid, vname))
    # A product can be a course's door: buying it enrols the buyer. Placement
    # is the moment (COD is this store's normal); a cancelled order is the
    # operator's cue to end the seat, same as any other refund consequence.
    if kind == "customer":
        from . import learning, nutrition
        enrolled_courses = learning.enroll_by_order(con, oid, user["id"])
        if enrolled_courses:
            notify.push(con, f"Enrolled by order #{oid}",
                        f"{user['name']} joined: "
                        + ", ".join(enrolled_courses), kind="learning")
        # same rail, different desk: a product can open a coaching seat
        opened = nutrition.open_by_order(con, oid, user["id"])
        if opened:
            notify.push(con, f"Coaching seat by order #{oid}",
                        f"{user['name']} joined: " + ", ".join(opened),
                        kind="nutrition")
    # Affiliate attribution
    if body.affiliate_code:
        aff = con.execute("SELECT * FROM affiliates WHERE code=?",
                          (body.affiliate_code.strip(),)).fetchone()
        if aff:
            com = subtotal * aff["rate_bps"] // 10000
            con.execute("INSERT INTO referrals(affiliate_id,order_id,"
                        " commission_cents,created_at) VALUES(?,?,?,?)",
                        (aff["id"], oid, com, db.now()))
    con.commit()
    notify.push(con,
                f"New {kind} order #{oid} — ${total / 100:,.2f}"
                f"{' (' + region + ')' if region else ''}",
                f"placed by {user['name']}", kind="order")
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    d = order_json(con, o)
    d["checkout_url"] = checkout_url
    store_api.fire_webhooks("order.created", {
        "id": oid, "kind": kind, "total_cents": total,
        "status": o["status"], "customer": user["name"]})
    # Order receipt to the customer (dry-mode safe; never blocks the order).
    if user["email"]:
        try:
            item_lines = "\n".join(
                f"  {i['qty']}× {i['name']}"
                f"{' · ' + i['variant_name'] if i.get('variant_name') else ''}"
                f" — ${i['unit_price_cents'] * i['qty'] / 100:,.2f}"
                for i in d["items"])
            mailer.log_and_send(
                con, CFG, user["id"], user["email"], "receipt",
                f"Your order #{oid} is in! 💜",
                f"Thanks {user['name']}!\n\n{item_lines}\n\n"
                + (f"Discount {o['discount_code']}:"
                   f" −${o['discount_cents'] / 100:,.2f}\n"
                   if o["discount_cents"] else "")
                + f"Tax: ${tax / 100:,.2f}\nShipping: ${shipping / 100:,.2f}\n"
                f"Total: ${total / 100:,.2f}\n\n"
                f"Track any time: {base_url()}/  →  📦 order #{oid}",
                f"receipt-{oid}")
            con.commit()
        except Exception:
            pass
    return d


class RefundBody(BaseModel):
    amount_cents: int | None = None   # None = full refund
    restock: bool = False


@app.post("/api/admin/orders/{oid}/refund")
def refund_order(oid: int, body: RefundBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    if o["payment_status"] == "refunded":
        raise HTTPException(400, "already refunded")
    amount = body.amount_cents or o["total_cents"]
    if not 0 < amount <= o["total_cents"]:
        raise HTTPException(400, "bad refund amount")
    stripe_ok = None
    if o["payment_status"] == "paid" and o["payment_ref"]:
        stripe_ok = payments.refund(CFG, o["payment_ref"], amount)
        if not stripe_ok:
            raise HTTPException(502, "Stripe refund failed — money not moved")
    full = amount >= o["total_cents"]
    con.execute(
        "UPDATE orders SET payment_status='refunded'" +
        (", status='cancelled'" if full else "") + " WHERE id=?", (oid,))
    if body.restock:
        for it in con.execute(
                "SELECT * FROM order_items WHERE order_id=?",
                (oid,)).fetchall():
            if it["variant_id"]:
                con.execute(
                    "UPDATE product_variants SET stock=stock+? WHERE id=?",
                    (it["qty"], it["variant_id"]))
    con.commit()
    notify.push(con, f"Order #{oid} refunded ${amount / 100:,.2f}"
                     f"{' + restocked' if body.restock else ''}",
                f"by {user['name']}", kind="order")
    cust = con.execute("SELECT * FROM users WHERE id=?",
                       (o["user_id"],)).fetchone()
    if cust and cust["email"]:
        try:
            mailer.log_and_send(
                con, CFG, cust["id"], cust["email"], "refund",
                f"Refund for order #{oid}",
                f"Hi {cust['name']},\n\nWe've refunded"
                f" ${amount / 100:,.2f} on order #{oid}."
                + ("" if stripe_ok is None else
                   " It should reach your card in 5–10 business days.")
                + "\n\nQuestions? Just reply — we're here. 💜",
                f"refund-{oid}")
            con.commit()
        except Exception:
            pass
    return {"ok": True, "refunded_cents": amount,
            "stripe": stripe_ok, "restocked": body.restock}


class ConfirmPayBody(BaseModel):
    session_id: str


@app.post("/api/orders/{oid}/confirm-payment")
def confirm_payment(oid: int, body: ConfirmPayBody,
                    user=Depends(current_user), con=Depends(get_con)):
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None or (o["user_id"] != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "no such order")
    if o["payment_status"] == "paid":
        return {"ok": True, "status": "paid"}
    if body.session_id != o["payment_ref"] or not payments.session_paid(
            CFG, body.session_id):
        raise HTTPException(402, "payment not confirmed yet")
    con.execute("UPDATE orders SET payment_status='paid' WHERE id=?", (oid,))
    con.commit()
    notify.push(con, f"Order #{oid} paid — "
                     f"${o['total_cents'] / 100:,.2f}", kind="order")
    _order_paid(con, oid)
    return {"ok": True, "status": "paid"}


def _order_paid(con, oid: int) -> None:
    """Announce a paid order.

    Both routes to "paid" — Stripe confirming and someone marking it by hand
    — go through here, because an integration that only hears about half the
    payments is worse than one that hears about none: the books look right
    until they don't.
    """
    o = con.execute(
        "SELECT o.*, u.name customer, u.email FROM orders o"
        " LEFT JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,)).fetchone()
    if o is None:
        return
    items = [dict(r) for r in con.execute(
        "SELECT oi.qty, oi.unit_price_cents, p.name, p.sku FROM order_items oi"
        " JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?",
        (oid,)).fetchall()]
    store_api.fire_webhooks("order.paid", {
        "id": oid, "customer": o["customer"] or "a customer",
        "email": o["email"] or "",
        "total": f"${(o['total_cents'] or 0) / 100:,.2f}",
        "total_cents": o["total_cents"], "tax_cents": o["tax_cents"],
        "items": items})


@app.post("/api/admin/orders/{oid}/paid")
def mark_paid(oid: int, user=Depends(admin_user), con=Depends(get_con)):
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    con.execute("UPDATE orders SET payment_status='paid' WHERE id=?", (oid,))
    con.commit()
    notify.push(con, f"Order #{oid} marked paid", kind="order",
                user_id=o["user_id"])
    _order_paid(con, oid)
    return {"ok": True}


@app.get("/api/orders")
def list_orders(all: int = 0, user=Depends(current_user), con=Depends(get_con)):
    if all and user["is_admin"]:
        rows = con.execute(
            "SELECT o.*, u.name user_name FROM orders o JOIN users u"
            " ON u.id=o.user_id ORDER BY o.id DESC LIMIT 200").fetchall()
    else:
        rows = con.execute(
            "SELECT o.*, '' user_name FROM orders o WHERE user_id=?"
            " ORDER BY id DESC LIMIT 100", (user["id"],)).fetchall()
    return [order_json(con, r) for r in rows]


class StatusBody(BaseModel):
    status: str


@app.post("/api/admin/orders/{oid}/status")
def order_status(oid: int, body: StatusBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(400, "bad status")
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    con.execute("UPDATE orders SET status=? WHERE id=?", (body.status, oid))
    con.commit()
    # Shipping an order consumes stock from the fulfilling store — once.
    if body.status == "shipped" and o["fulfilled_store_id"] is None:
        _consume_stock(con, o)
    notify.push(con, f"Order #{oid} {body.status}",
                kind="order", user_id=o["user_id"])
    # Customer email on the milestones they care about.
    if body.status in ("shipped", "delivered"):
        cust = con.execute("SELECT * FROM users WHERE id=?",
                           (o["user_id"],)).fetchone()
        if cust and cust["email"]:
            try:
                verb = ("is on its way 🚚" if body.status == "shipped"
                        else "has arrived 🎉")
                mailer.log_and_send(
                    con, CFG, cust["id"], cust["email"], "order-status",
                    f"Order #{oid} {verb}",
                    f"Hi {cust['name']},\n\nYour order #{oid} {verb}\n"
                    f"Track it: {base_url()}/  →  📦 order #{oid}",
                    f"status-{oid}-{body.status}")
                con.commit()
            except Exception:
                pass
    return {"ok": True}


def _consume_stock(con, o) -> None:
    """Decrement inventory at the best source store (the order's store, else
    the region's best-stocked store, else the overall best-stocked one)."""
    sid = o["store_id"]
    if sid is None:
        row = con.execute(
            "SELECT s.id FROM stores s JOIN inventory i ON i.store_id=s.id"
            " WHERE s.active=1 AND (s.region=? OR ?='')"
            " GROUP BY s.id ORDER BY SUM(i.qty) DESC LIMIT 1",
            (o["region"], o["region"])).fetchone()
        if row is None:
            row = con.execute(
                "SELECT s.id FROM stores s JOIN inventory i ON i.store_id=s.id"
                " GROUP BY s.id ORDER BY SUM(i.qty) DESC LIMIT 1").fetchone()
        if row is None:
            return
        sid = row["id"]
    items = con.execute(
        "SELECT oi.product_id, oi.qty, p.case_size, p.name FROM order_items oi"
        " JOIN products p ON p.id=oi.product_id WHERE order_id=?",
        (o["id"],)).fetchall()
    shorts = []
    for it in items:
        units = it["qty"] * (it["case_size"] if o["kind"] == "distributor"
                             else 1)
        inv = con.execute(
            "SELECT qty FROM inventory WHERE store_id=? AND product_id=?",
            (sid, it["product_id"])).fetchone()
        have = inv["qty"] if inv else 0
        if have < units:
            shorts.append(f"{it['name']} (need {units}, have {have})")
        con.execute(
            "INSERT INTO inventory(store_id,product_id,qty,updated_at)"
            " VALUES(?,?,0,?) ON CONFLICT(store_id,product_id)"
            " DO UPDATE SET qty=MAX(0, qty-?), updated_at=?",
            (sid, it["product_id"], db.now(), units, db.now()))
    con.execute("UPDATE orders SET fulfilled_store_id=? WHERE id=?",
                (sid, o["id"]))
    con.commit()
    if shorts:
        notify.push(con, f"Order #{o['id']} shipped short-stocked",
                    "; ".join(shorts), kind="inventory")


# ---------- time clock ----------

class ClockBody(BaseModel):
    pin: str
    event_id: int | None = None      # promo event being worked, if any


@app.post("/api/clock")
def clock(body: ClockBody, con=Depends(get_con)):
    """PIN-based toggle so the store tablet needs no login."""
    emp = auth.check_pin(con, body.pin, CFG["pin_pepper"])
    if emp is None:
        raise HTTPException(404, "no employee with that PIN")
    return _punch(con, emp, body.event_id)


def _punch(con, emp, event_id):
    """Toggle a shift for this employee. Shared by the PIN keypad and the
    badge scanner, so the two can't drift into behaving differently."""
    open_shift = con.execute(
        "SELECT * FROM shifts WHERE user_id=? AND clock_out IS NULL",
        (emp["id"],)).fetchone()
    if open_shift:
        con.execute("UPDATE shifts SET clock_out=? WHERE id=?",
                    (db.now(), open_shift["id"]))
        con.commit()
        return {"name": emp["name"], "action": "clock_out",
                "shift_id": open_shift["id"],
                "hours": round((db.now() - open_shift["clock_in"]) / 3600, 2)}
    event_name = ""
    if event_id:
        ev = con.execute("SELECT * FROM promos WHERE id=? AND kind='event'"
                         " AND active=1", (event_id,)).fetchone()
        if ev is None:
            raise HTTPException(400, "no such active event")
        event_name = ev["name"]
    cur = con.execute("INSERT INTO shifts(user_id, clock_in, event_id)"
                      " VALUES(?,?,?)", (emp["id"], db.now(), event_id))
    con.commit()
    return {"name": emp["name"], "action": "clock_in",
            "shift_id": cur.lastrowid, "event": event_name}


class BadgeBody(BaseModel):
    token: str
    event_id: int | None = None


@app.post("/api/clock/badge")
def clock_badge_punch(body: BadgeBody, con=Depends(get_con)):
    """Punch by scanning a badge. Unauthenticated for the same reason the
    PIN keypad is: it runs on a shared tablet by the door, and requiring a
    login to record that you arrived defeats the point."""
    emp = auth.user_for_badge(con, body.token)
    if emp is None:
        raise HTTPException(404, "that badge isn't recognised")
    return _punch(con, emp, body.event_id)


@app.post("/api/me/badge")
def my_badge(reset: int = 0, user=Depends(current_user), con=Depends(get_con)):
    """Your own badge. Reset it if the old one is on a lanyard you lost."""
    return {"token": auth.clock_badge(con, user["id"], bool(reset))}


@app.post("/api/admin/users/{uid}/badge")
def issue_badge(uid: int, reset: int = 0, user=Depends(admin_user),
                con=Depends(get_con)):
    if not con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        raise HTTPException(404, "no such user")
    return {"token": auth.clock_badge(con, uid, bool(reset))}


@app.get("/api/admin/orders/awaiting")
def orders_awaiting(user=Depends(admin_user), con=Depends(get_con)):
    """Pay-on-delivery orders still waiting on their email confirmation.

    They aren't in `orders` yet — that's what stops them counting as revenue
    — but the business still needs to see them, or demand that has been asked
    for simply isn't visible anywhere.
    """
    rows = con.execute(
        "SELECT p.*, u.name FROM pending_orders p"
        " JOIN users u ON u.id=p.user_id"
        " WHERE p.placed_order_id=0 AND p.expires_at > ?"
        " ORDER BY p.created_at DESC LIMIT 50", (db.now(),)).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except Exception:
            payload = {}
        out.append({"id": r["id"], "name": r["name"], "email": r["email"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "items": len(payload.get("items") or []),
                    "city": payload.get("city", "")})
    return out


@app.post("/api/admin/orders/awaiting/{pid}/resend")
def resend_confirmation(pid: int, user=Depends(admin_user),
                        con=Depends(get_con)):
    r = con.execute("SELECT * FROM pending_orders WHERE id=? AND"
                    " placed_order_id=0", (pid,)).fetchone()
    if r is None:
        raise HTTPException(404, "nothing waiting under that id")
    link = f"{base_url()}/confirm-order/{r['token']}"
    mailer.log_and_send(
        con, CFG, r["user_id"], r["email"], "order-confirm",
        "Confirm your order",
        f"Just a reminder — your order isn't placed until you confirm this "
        f"address.\n\n{link}\n\nIf you didn't order anything, ignore this.",
        f"confirm-resend-{r['id']}-{int(db.now())}")
    con.commit()
    return {"ok": True, "email": r["email"]}


@app.get("/api/shifts")
def shifts(all: int = 0, user=Depends(current_user), con=Depends(get_con)):
    if all and user["is_admin"]:
        rows = con.execute(
            "SELECT s.*, u.name, u.job, u.employment, p.name event_name"
            " FROM shifts s JOIN users u ON u.id=s.user_id"
            " LEFT JOIN promos p ON p.id=s.event_id"
            " ORDER BY s.clock_in DESC LIMIT 200").fetchall()
    else:
        rows = con.execute(
            "SELECT s.*, ? name, p.name event_name FROM shifts s"
            " LEFT JOIN promos p ON p.id=s.event_id WHERE s.user_id=?"
            " ORDER BY s.clock_in DESC LIMIT 100",
            (user["name"], user["id"])).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["hours"] = round(((r["clock_out"] or db.now()) - r["clock_in"]) / 3600, 2)
        out.append(d)
    return out


class EmployeeBody(BaseModel):
    name: str
    pin: str
    region: str = ""
    job: str = "general"
    employment: str = "employee"


def _ensure_affiliate(con, u) -> None:
    if con.execute("SELECT 1 FROM affiliates WHERE user_id=?",
                   (u["id"],)).fetchone():
        return
    code = f"{u['name'].split()[0].lower()}{secrets.token_hex(2)}"
    con.execute("INSERT INTO affiliates(user_id,code,rate_bps,created_at)"
                " VALUES(?,?,?,?)",
                (u["id"], code, CFG["default_commission_bps"], db.now()))
    con.commit()


@app.post("/api/admin/employees")
def add_employee(body: EmployeeBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    pin = (body.pin or "").strip()
    if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
        raise HTTPException(400, "PIN must be 4–8 digits")
    pin_hash = auth.hash_pin(pin, CFG["pin_pepper"]) if pin else ""
    if pin_hash and con.execute(
            "SELECT 1 FROM users WHERE pin_hash=?", (pin_hash,)).fetchone():
        raise HTTPException(400, "PIN already in use")
    if body.job not in JOBS or body.employment not in ("employee",
                                                       "contractor"):
        raise HTTPException(400, "bad job or employment type")
    cur = con.execute(
        "INSERT INTO users(name,role,token,pin_hash,region,job,employment,"
        " created_at) VALUES(?,?,?,?,?,?,?,?)",
        (body.name, "employee", secrets.token_urlsafe(24), pin_hash,
         body.region, body.job, body.employment, db.now()))
    con.commit()
    if body.job == "ambassador":     # ambassadors get an affiliate code
        u = con.execute("SELECT * FROM users WHERE id=?",
                        (cur.lastrowid,)).fetchone()
        _ensure_affiliate(con, u)
    return {"ok": True}


@app.get("/api/admin/users")
def all_users(user=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT id,name,role,job,employment,region,is_admin,active,created_at,"
        " requested_role,"
        " (password_hash!='') AS password_set FROM users"
        " ORDER BY is_admin DESC, role, name").fetchall()
    return [dict(r) for r in rows]



class UserUpdateBody(BaseModel):
    role: str | None = None
    job: str | None = None
    employment: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    active: bool | None = None
    clear_password: bool = False


@app.post("/api/admin/users/{uid}/update")
def update_user(uid: int, body: UserUpdateBody, user=Depends(admin_user),
                con=Depends(get_con)):
    if uid == user["id"]:
        raise HTTPException(400, "you can't edit your own account here")
    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        raise HTTPException(404, "no such user")
    role = target["role"]
    if body.role is not None:
        if body.role not in ("customer", "distributor", "influencer",
                             "employee", "owner", "teacher", "volunteer",
                             "director", "board", "donor"):
            raise HTTPException(400, "bad role")
        role = body.role
    is_admin = target["is_admin"] if body.is_admin is None else int(body.is_admin)
    if role == "owner":
        is_admin = 1                       # founders always have admin
    job = target["job"]
    if body.job is not None:
        if body.job not in JOBS:
            raise HTTPException(400, "bad job")
        job = body.job
    employment = target["employment"]
    if body.employment is not None:
        if body.employment not in ("employee", "contractor"):
            raise HTTPException(400, "bad employment type")
        employment = body.employment
    active = target["active"] if body.active is None else int(body.active)
    email = target["email"] if body.email is None else body.email.strip()[:200]
    con.execute("UPDATE users SET role=?, is_admin=?, active=?, job=?,"
                " employment=?, email=? WHERE id=?",
                (role, is_admin, active, job, employment, email, uid))
    if job == "ambassador":
        _ensure_affiliate(con, target)
    if body.clear_password:
        # Password reset: next sign-in with a password re-adopts it.
        con.execute("UPDATE users SET password_hash='' WHERE id=?", (uid,))
    con.commit()
    return {"ok": True}


class PinResetBody(BaseModel):
    pin: str = ""            # blank clears it


@app.post("/api/admin/users/{uid}/pin")
def reset_pin(uid: int, body: PinResetBody, user=Depends(admin_user),
              con=Depends(get_con)):
    """Set or clear someone's time-clock PIN.

    An admin can't look one up — they're hashed, and the employee list only
    reports whether a PIN exists. So "I've forgotten my PIN" is answered by
    issuing a new one, which is the right answer anyway: a PIN a manager can
    read is a PIN a manager can use to clock someone else in.
    """
    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        raise HTTPException(404, "no such user")
    pin = (body.pin or "").strip()
    if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
        raise HTTPException(400, "PIN must be 4–8 digits")
    h = auth.hash_pin(pin, CFG["pin_pepper"]) if pin else ""
    if h and con.execute("SELECT 1 FROM users WHERE pin_hash=? AND id!=?",
                         (h, uid)).fetchone():
        raise HTTPException(400, "that PIN is already taken")
    con.execute("UPDATE users SET pin_hash=? WHERE id=?", (h, uid))
    con.commit()
    if pin:
        notify.push(con, "Your time-clock PIN was changed",
                    f"{user['name']} set a new PIN for you.",
                    kind="achievement", user_id=uid,
                    dedup=f"pin:{uid}:{db.now()}")
    return {"ok": True, "cleared": not pin}


@app.get("/api/admin/employees")
def list_employees(user=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT id,name,region,active,pin_hash FROM users"
        " WHERE role='employee' ORDER BY name").fetchall()
    # Whether a PIN exists, never what it is — an admin who needs to change
    # one sets a new one rather than reading the old.
    return [{"id": r["id"], "name": r["name"], "region": r["region"],
             "active": r["active"], "has_pin": bool(r["pin_hash"])}
            for r in rows]


# ---------- A/B testing & funnel events ----------

@app.get("/api/ab/active")
def ab_active(visitor: str, con=Depends(get_con)):
    """Assign the visitor to every running experiment; return the content the
    storefront should render."""
    if not visitor:
        raise HTTPException(400, "visitor required")
    exps = con.execute(
        "SELECT * FROM experiments WHERE status='running'").fetchall()
    out = []
    for e in exps:
        vid = abtest.assign(con, e["id"], visitor)
        if vid is None:
            continue
        v = con.execute("SELECT * FROM variants WHERE id=?", (vid,)).fetchone()
        out.append({"experiment_id": e["id"], "experiment": e["name"],
                    "goal": e["goal"], "variant_id": v["id"],
                    "name": v["name"], "headline": v["headline"],
                    "cta": v["cta"], "theme": v["theme"]})
    return out


class EventBody(BaseModel):
    visitor_id: str
    step: str
    region: str = ""
    product_id: int | None = None
    experiment_id: int | None = None
    variant_id: int | None = None
    value_cents: int = 0


@app.post("/api/events")
def track(body: EventBody, authorization: str = Header(default=""),
          con=Depends(get_con)):
    if body.step not in config.FUNNEL_STEPS:
        raise HTTPException(400, f"step must be one of {config.FUNNEL_STEPS}")
    # Attribute to the signed-in user when possible (email playbooks need it).
    u = auth.user_for_token(con, authorization.removeprefix("Bearer ").strip())
    con.execute(
        "INSERT INTO events(visitor_id,user_id,step,region,product_id,"
        " experiment_id,variant_id,value_cents,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (body.visitor_id, u["id"] if u else None, body.step, body.region,
         body.product_id, body.experiment_id, body.variant_id,
         body.value_cents, db.now()))
    con.commit()
    return {"ok": True}


@app.get("/api/experiments")
def experiments(user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
    return [abtest.results(con, r, CFG) for r in rows]


class AutoExpBody(BaseModel):
    goal: str = "purchase"
    product_id: int | None = None
    n_variants: int = 3


@app.post("/api/admin/experiments/auto")
def auto_experiment(body: AutoExpBody, user=Depends(admin_user),
                    con=Depends(get_con)):
    """Auto-pick the focus product (top seller if unspecified) and generate
    grouped content variants for it."""
    if body.product_id:
        p = con.execute("SELECT * FROM products WHERE id=?",
                        (body.product_id,)).fetchone()
    else:
        p = con.execute(
            "SELECT p.*, COALESCE(SUM(oi.qty),0) sold FROM products p"
            " LEFT JOIN order_items oi ON oi.product_id=p.id"
            " WHERE p.active=1 GROUP BY p.id ORDER BY sold DESC LIMIT 1"
        ).fetchone()
    if p is None:
        raise HTTPException(400, "no products to test against")
    variants = abtest.generate_variants(body.goal, p["name"],
                                        max(2, min(body.n_variants, 4)))
    cur = con.execute(
        "INSERT INTO experiments(name,goal,status,auto_generated,created_at)"
        " VALUES(?,?,?,?,?)",
        (f"{p['name']} — {body.goal}", body.goal, "running", 1, db.now()))
    eid = cur.lastrowid
    for v in variants:
        con.execute(
            "INSERT INTO variants(experiment_id,name,headline,cta,theme)"
            " VALUES(?,?,?,?,?)",
            (eid, v["name"], v["headline"], v["cta"], v["theme"]))
    con.commit()
    e = con.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    return abtest.results(con, e, CFG)


@app.post("/api/admin/experiments/{eid}/stop")
def stop_experiment(eid: int, user=Depends(admin_user), con=Depends(get_con)):
    e = con.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    if e is None:
        raise HTTPException(404, "no such experiment")
    r = abtest.results(con, e, CFG)
    winner_id = r["winner"]["variant_id"] if r["winner"] else None
    con.execute("UPDATE experiments SET status='done', winner_variant_id=?"
                " WHERE id=?", (winner_id, eid))
    con.commit()
    if r["winner"]:
        notify.push(con, f"Experiment finished: {e['name']}",
                    f"winner {r['winner']['name']} at "
                    f"{round(r['winner']['rate'] * 100, 1)}%",
                    kind="experiment")
    return {"ok": True, "winner": r["winner"]}


# ---------- affiliates ----------

@app.post("/api/affiliates/join")
def join_affiliates(user=Depends(current_user), con=Depends(get_con)):
    row = con.execute("SELECT * FROM affiliates WHERE user_id=?",
                      (user["id"],)).fetchone()
    if row is None:
        code = f"{user['name'].split()[0].lower()}{secrets.token_hex(2)}"
        con.execute(
            "INSERT INTO affiliates(user_id,code,rate_bps,created_at)"
            " VALUES(?,?,?,?)",
            (user["id"], code, CFG["default_commission_bps"], db.now()))
        con.commit()
        notify.push(con, f"New affiliate: {user['name']} ({code})",
                    kind="affiliate")
    return affiliate_stats(user=user, con=con)


@app.get("/api/affiliates/mine")
def affiliate_stats(user=Depends(current_user), con=Depends(get_con)):
    a = con.execute("SELECT * FROM affiliates WHERE user_id=?",
                    (user["id"],)).fetchone()
    if a is None:
        return {"joined": False}
    agg = con.execute(
        "SELECT COUNT(*) orders, COALESCE(SUM(commission_cents),0) earned"
        " FROM referrals WHERE affiliate_id=?", (a["id"],)).fetchone()
    return {"joined": True, "code": a["code"], "rate_bps": a["rate_bps"],
            "clicks": a["clicks"], "orders": agg["orders"],
            "earned_cents": agg["earned"],
            "link": f"/r/{a['code']}"}


@app.get("/api/admin/affiliates")
def all_affiliates(user=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT a.*, u.name, COALESCE(SUM(r.commission_cents),0) earned,"
        " COUNT(r.id) ref_orders FROM affiliates a JOIN users u ON u.id=a.user_id"
        " LEFT JOIN referrals r ON r.affiliate_id=a.id"
        " GROUP BY a.id ORDER BY earned DESC").fetchall()
    return [dict(r) for r in rows]


# NOTE: /r/{code} now lives in storefront.backend.affiliates — it counts the
# click and routes to the affiliate's landing page when they have one.


# ---------- affiliate feed ----------

class PostBody(BaseModel):
    body: str = ""
    url: str = ""


@app.post("/api/feed")
def add_post(body: PostBody, user=Depends(current_user), con=Depends(get_con)):
    """Affiliates (and admins) post updates; a URL gets a best-effort preview
    fetched from the platform's oEmbed endpoint or the page's OpenGraph tags."""
    is_affiliate = con.execute("SELECT 1 FROM affiliates WHERE user_id=?",
                               (user["id"],)).fetchone()
    if not (is_affiliate or user["is_admin"]):
        raise HTTPException(403, "join the affiliate program first")
    text, url = body.body.strip(), body.url.strip()
    if not text and not url:
        raise HTTPException(400, "post needs text or a link")
    preview = social.fetch_preview(url) if url else {
        "provider": "", "title": "", "image": "", "description": ""}
    cur = con.execute(
        "INSERT INTO posts(user_id,body,url,provider,title,image,description,"
        " created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], text, url, preview["provider"], preview["title"],
         preview["image"], preview["description"], db.now()))
    con.commit()
    return feed_post_json(con, cur.lastrowid)


def feed_post_json(con, pid: int) -> dict:
    p = con.execute(
        "SELECT p.*, u.name, u.region, a.code FROM posts p"
        " JOIN users u ON u.id=p.user_id"
        " LEFT JOIN affiliates a ON a.user_id=p.user_id WHERE p.id=?",
        (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such post")
    d = dict(p)
    if p["code"]:
        week = con.execute(
            "SELECT COUNT(*) orders, COALESCE(SUM(commission_cents),0) earned"
            " FROM referrals r JOIN affiliates a ON a.id=r.affiliate_id"
            " WHERE a.code=? AND r.created_at>=?",
            (p["code"], db.now() - 7 * 86400)).fetchone()
        d["week_orders"] = week["orders"]
        d["week_commission_cents"] = week["earned"]
    return d


@app.get("/api/feed")
def feed(user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT id FROM posts ORDER BY id DESC LIMIT 100").fetchall()
    return [feed_post_json(con, r["id"]) for r in rows]


# ---------- stores & inventory ----------

@app.get("/api/stores")
def stores(region: str = "", con=Depends(get_con)):
    q = "SELECT * FROM stores WHERE active=1"
    args = []
    if region:
        q += " AND region=?"
        args.append(region)
    rows = con.execute(q + " ORDER BY region, name", args).fetchall()
    return [dict(r) for r in rows]


class StoreBody(BaseModel):
    name: str
    kind: str = "retail"
    region: str
    city: str = ""
    lat: float
    lng: float
    contact: str = ""


@app.post("/api/admin/stores")
def add_store(body: StoreBody, user=Depends(admin_user), con=Depends(get_con)):
    con.execute(
        "INSERT INTO stores(name,kind,region,city,lat,lng,contact)"
        " VALUES(?,?,?,?,?,?,?)",
        (body.name, body.kind, body.region, body.city, body.lat, body.lng,
         body.contact))
    con.commit()
    # Coverage grows with the store map: regenerate this region's route.
    regenerated = None
    if CFG.get("auto_routes_on_store_add", True):
        try:
            regenerated = _coverage_route(con, body.region)
        except HTTPException:
            pass                      # fewer than 2 stores in region yet
    return {"ok": True, "coverage_route": regenerated}


@app.get("/api/warehouse/picklist")
def picklist(user=Depends(current_user), con=Depends(get_con)):
    """Orders waiting to be picked/packed (warehouse view). Staff only."""
    if not chat.is_staff(user):
        raise HTTPException(403, "staff only")
    rows = con.execute(
        "SELECT o.id, o.kind, o.status, o.city, o.region, o.ship_name,"
        " o.created_at FROM orders o WHERE o.status IN ('pending','confirmed')"
        " ORDER BY o.id LIMIT 100").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        items = con.execute(
            "SELECT oi.qty, p.name, p.sku, p.case_size FROM order_items oi"
            " JOIN products p ON p.id=oi.product_id WHERE order_id=?",
            (r["id"],)).fetchall()
        d["items"] = [dict(i) for i in items]
        out.append(d)
    return out


@app.get("/api/inventory")
def inventory(store_id: int = 0, user=Depends(current_user),
              con=Depends(get_con)):
    q = ("SELECT i.*, s.name store_name, s.region, p.name product_name, p.sku"
         " FROM inventory i JOIN stores s ON s.id=i.store_id"
         " JOIN products p ON p.id=i.product_id")
    args = []
    if store_id:
        q += " WHERE i.store_id=?"
        args.append(store_id)
    rows = con.execute(q + " ORDER BY s.region, s.name, p.name", args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["low"] = d["qty"] < max(1, d["par"] // 4)
        out.append(d)
    return out


class InventoryBody(BaseModel):
    store_id: int
    product_id: int
    qty: int
    par: int = 24


@app.post("/api/admin/inventory")
def set_inventory(body: InventoryBody, user=Depends(admin_user),
                  con=Depends(get_con)):
    con.execute(
        "INSERT INTO inventory(store_id,product_id,qty,par,updated_at)"
        " VALUES(?,?,?,?,?) ON CONFLICT(store_id,product_id)"
        " DO UPDATE SET qty=excluded.qty, par=excluded.par,"
        " updated_at=excluded.updated_at",
        (body.store_id, body.product_id, body.qty, body.par, db.now()))
    con.commit()
    return {"ok": True}


# ---------- editing and removing what's already here ----------
#
# These sit together on purpose. Each screen grew a "create" endpoint first
# and stopped there, which left the ERP able to make a mess but not tidy one
# up. The pattern is the same throughout: PATCH takes a partial body and only
# touches the fields present, DELETE deactivates when the row is referenced by
# history and removes it when it isn't. Nothing here hard-deletes a row that
# an order, shift or ledger entry still points at — that would turn a report
# into a lie.


def _patch(con, table: str, row_id: int, fields: dict, allowed: tuple) -> dict:
    """Apply the fields that were sent, ignore the ones that weren't.

    Column names are checked against `allowed` rather than taken from the
    request, so a caller can't name a column the endpoint never meant to
    expose.
    """
    sets, args = [], []
    for k, v in fields.items():
        if v is None or k not in allowed:
            continue
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        raise HTTPException(400, "nothing to change")
    args.append(row_id)
    cur = con.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?",
                      tuple(args))
    con.commit()
    if not cur.rowcount:
        raise HTTPException(404, "no such row")
    return {"ok": True}


class ProductEdit(BaseModel):
    sku: str | None = None
    name: str | None = None
    description: str | None = None
    category: str | None = None
    price_cents: int | None = None
    case_size: int | None = None
    case_price_cents: int | None = None
    active: int | None = None


@app.patch("/api/admin/products/{pid}")
def edit_product(pid: int, body: ProductEdit, user=Depends(admin_user),
                 con=Depends(get_con)):
    return _patch(con, "products", pid, body.model_dump(),
                  ("sku", "name", "description", "category", "price_cents",
                   "case_size", "case_price_cents", "active"))


@app.delete("/api/admin/products/{pid}")
def delete_product(pid: int, user=Depends(admin_user), con=Depends(get_con)):
    """Retire, don't erase, once a product has been sold.

    An order line points at a product row; deleting it would leave past
    orders describing something that no longer exists, and every revenue
    figure derived from them would quietly change.
    """
    sold = con.execute("SELECT COUNT(*) n FROM order_items WHERE product_id=?",
                       (pid,)).fetchone()["n"]
    if sold:
        con.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        con.commit()
        return {"ok": True, "retired": True, "orders": sold,
                "note": f"kept and hidden — {sold} order lines reference it"}
    con.execute("DELETE FROM inventory WHERE product_id=?", (pid,))
    con.execute("DELETE FROM products WHERE id=?", (pid,))
    con.commit()
    return {"ok": True, "retired": False}


class OrderEdit(BaseModel):
    status: str | None = None
    ship_name: str | None = None
    address: str | None = None
    city: str | None = None
    postal: str | None = None
    phone: str | None = None
    region: str | None = None
    note: str | None = None


@app.patch("/api/admin/orders/{oid}")
def edit_order(oid: int, body: OrderEdit, user=Depends(admin_user),
               con=Depends(get_con)):
    """Shipping details and status. Money is deliberately not editable here.

    Totals come from the line items and the discounts that were applied at
    the time; letting someone type a new total would break the arithmetic
    between an order, its refunds and the P&L. Refunds have their own
    endpoint, which writes a ledger entry.
    """
    if body.status is not None and body.status not in ORDER_STATUSES:
        raise HTTPException(400, f"status must be one of {ORDER_STATUSES}")
    return _patch(con, "orders", oid, body.model_dump(),
                  ("status", "ship_name", "address", "city", "postal",
                   "phone", "region", "note"))


@app.delete("/api/admin/orders/{oid}")
def delete_order(oid: int, user=Depends(admin_user), con=Depends(get_con)):
    """Cancel rather than delete. An order is a financial record; the honest
    way to undo one is to mark it cancelled, which the P&L already excludes."""
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such order")
    if o["status"] == "cancelled":
        raise HTTPException(400, "that order is already cancelled")
    con.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oid,))
    con.commit()
    return {"ok": True, "cancelled": True}


class PromoEdit(BaseModel):
    name: str | None = None
    body: str | None = None
    product_id: int | None = None
    discount_pct: int | None = None
    region: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    starts: str | None = None
    video_url: str | None = None
    active: int | None = None


@app.patch("/api/admin/promos/{pid}")
def edit_promo(pid: int, body: PromoEdit, user=Depends(admin_user),
               con=Depends(get_con)):
    return _patch(con, "promos", pid, body.model_dump(),
                  ("name", "body", "product_id", "discount_pct", "region",
                   "city", "lat", "lng", "starts", "video_url", "active"))


@app.delete("/api/admin/promos/{pid}")
def delete_promo(pid: int, user=Depends(admin_user), con=Depends(get_con)):
    """Promos and events share a table. Scans and shifts point at them, so a
    promo people actually used is deactivated rather than removed."""
    used = con.execute("SELECT COUNT(*) n FROM promo_scans WHERE promo_id=?",
                       (pid,)).fetchone()["n"]
    worked = con.execute("SELECT COUNT(*) n FROM shifts WHERE event_id=?",
                         (pid,)).fetchone()["n"]
    if used or worked:
        con.execute("UPDATE promos SET active=0 WHERE id=?", (pid,))
        con.commit()
        return {"ok": True, "retired": True, "scans": used, "shifts": worked}
    con.execute("DELETE FROM promos WHERE id=?", (pid,))
    con.commit()
    return {"ok": True, "retired": False}


class StoreEdit(BaseModel):
    name: str | None = None
    kind: str | None = None
    region: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    contact: str | None = None
    active: int | None = None


@app.patch("/api/admin/stores/{sid}")
def edit_store(sid: int, body: StoreEdit, user=Depends(admin_user),
               con=Depends(get_con)):
    return _patch(con, "stores", sid, body.model_dump(),
                  ("name", "kind", "region", "city", "lat", "lng", "contact",
                   "active"))


@app.delete("/api/admin/stores/{sid}")
def delete_store(sid: int, user=Depends(admin_user), con=Depends(get_con)):
    """A store that has ordered stays on the books, closed. Its inventory
    rows go either way — they describe stock on a shelf that no longer
    exists."""
    ordered = con.execute("SELECT COUNT(*) n FROM orders WHERE store_id=?",
                          (sid,)).fetchone()["n"]
    con.execute("DELETE FROM inventory WHERE store_id=?", (sid,))
    if ordered:
        con.execute("UPDATE stores SET active=0 WHERE id=?", (sid,))
        con.commit()
        return {"ok": True, "closed": True, "orders": ordered}
    con.execute("DELETE FROM stores WHERE id=?", (sid,))
    con.commit()
    return {"ok": True, "closed": False}


@app.delete("/api/admin/inventory/{store_id}/{product_id}")
def clear_inventory(store_id: int, product_id: int, user=Depends(admin_user),
                    con=Depends(get_con)):
    """Remove the line entirely — "this store doesn't carry this" is a
    different statement from "this store has none left", and a zero row keeps
    showing up in low-stock reports as if it were the latter."""
    cur = con.execute(
        "DELETE FROM inventory WHERE store_id=? AND product_id=?",
        (store_id, product_id))
    con.commit()
    if not cur.rowcount:
        raise HTTPException(404, "that store doesn't stock that product")
    return {"ok": True}


class PostEdit(BaseModel):
    body: str | None = None


@app.patch("/api/admin/feed/{pid}")
def edit_post(pid: int, body: PostEdit, user=Depends(admin_user),
              con=Depends(get_con)):
    return _patch(con, "posts", pid, body.model_dump(), ("body",))


@app.delete("/api/admin/feed/{pid}")
def remove_post(pid: int, user=Depends(admin_user), con=Depends(get_con)):
    """The POST /delete form of this already existed; this is the same thing
    under the verb that describes it, so the feed matches every other screen."""
    con.execute("DELETE FROM posts WHERE id=?", (pid,))
    con.commit()
    return {"ok": True}


# ---------- sourcing, supply and manufacturing ----------

@app.get("/api/supply")
def supply_overview(user=Depends(permitted("supply")), con=Depends(get_con)):
    return supply.overview(con)


@app.post("/api/supply/suppliers")
def supply_add_supplier(body: supply.SupplierBody, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    return supply.add_supplier(con, body)


@app.patch("/api/supply/suppliers/{sid}")
def supply_edit_supplier(sid: int, body: supply.SupplierBody,
                         user=Depends(permitted("supply")), con=Depends(get_con)):
    return _patch(con, "suppliers", sid, body.model_dump(),
                  ("name", "kind", "contact", "email", "phone", "country",
                   "lead_days", "terms", "notes", "active"))


@app.delete("/api/supply/suppliers/{sid}")
def supply_del_supplier(sid: int, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    """A supplier with history is deactivated: purchase orders name them, and
    an order from nobody isn't a record of anything."""
    used = con.execute("SELECT COUNT(*) n FROM purchase_orders"
                       " WHERE supplier_id=?", (sid,)).fetchone()["n"]
    if used:
        con.execute("UPDATE suppliers SET active=0 WHERE id=?", (sid,))
        con.commit()
        return {"ok": True, "retired": True, "purchase_orders": used}
    con.execute("UPDATE materials SET supplier_id=NULL WHERE supplier_id=?",
                (sid,))
    con.execute("DELETE FROM suppliers WHERE id=?", (sid,))
    con.commit()
    return {"ok": True, "retired": False}


@app.post("/api/supply/materials")
def supply_add_material(body: supply.MaterialBody, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    return supply.add_material(con, body)


@app.patch("/api/supply/materials/{mid}")
def supply_edit_material(mid: int, body: supply.MaterialBody,
                         user=Depends(permitted("supply")), con=Depends(get_con)):
    """Note what is absent: on_hand. Stock moves only through a receipt, a
    production run or an explicit adjustment that records a reason."""
    return _patch(con, "materials", mid, body.model_dump(),
                  ("name", "code", "kind", "unit", "supplier_id",
                   "unit_cost_cents", "reorder_point", "active"))


@app.delete("/api/supply/materials/{mid}")
def supply_del_material(mid: int, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    moves = con.execute("SELECT COUNT(*) n FROM material_moves"
                        " WHERE material_id=?", (mid,)).fetchone()["n"]
    if moves:
        con.execute("UPDATE materials SET active=0 WHERE id=?", (mid,))
        con.commit()
        return {"ok": True, "retired": True, "moves": moves}
    con.execute("DELETE FROM bill_of_materials WHERE material_id=?", (mid,))
    con.execute("DELETE FROM materials WHERE id=?", (mid,))
    con.commit()
    return {"ok": True, "retired": False}


class AdjustBody(BaseModel):
    qty: float
    note: str = ""


@app.post("/api/supply/materials/{mid}/adjust")
def supply_adjust(mid: int, body: AdjustBody, user=Depends(permitted("supply")),
                  con=Depends(get_con)):
    """A stock correction, with a reason attached. This is the one way to
    change a level by hand, and it still leaves a row behind saying who did
    it and why — a count that changes with no explanation is the thing this
    module exists to avoid."""
    if not body.note.strip():
        raise HTTPException(400, "an adjustment needs a reason")
    if not con.execute("SELECT 1 FROM materials WHERE id=?", (mid,)).fetchone():
        raise HTTPException(404, "no such material")
    supply.move(con, mid, body.qty, "adjust", user["name"],
                body.note.strip()[:200])
    con.commit()
    return {"ok": True}


@app.get("/api/supply/materials/{mid}/moves")
def supply_moves(mid: int, user=Depends(permitted("supply")), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM material_moves WHERE material_id=?"
        " ORDER BY id DESC LIMIT 100", (mid,)).fetchall()]


@app.post("/api/supply/purchase-orders")
def supply_add_po(body: supply.POBody, user=Depends(permitted("supply")),
                  con=Depends(get_con)):
    return supply.add_po(con, body)


class POStatusBody(BaseModel):
    status: str


@app.post("/api/supply/purchase-orders/{pid}/status")
def supply_po_status(pid: int, body: POStatusBody, user=Depends(permitted("supply")),
                     con=Depends(get_con)):
    if body.status not in supply.PO_STATUS:
        raise HTTPException(400, f"status must be one of {supply.PO_STATUS}")
    con.execute("UPDATE purchase_orders SET status=? WHERE id=?",
                (body.status, pid))
    con.commit()
    return {"ok": True}


class ReceiveBody(BaseModel):
    lines: dict = {}


@app.post("/api/supply/purchase-orders/{pid}/receive")
def supply_receive(pid: int, body: ReceiveBody, user=Depends(permitted("supply")),
                   con=Depends(get_con)):
    return supply.receive_po(con, pid, body.lines, user["name"])


@app.delete("/api/supply/purchase-orders/{pid}")
def supply_del_po(pid: int, user=Depends(permitted("supply")), con=Depends(get_con)):
    po = con.execute("SELECT * FROM purchase_orders WHERE id=?",
                     (pid,)).fetchone()
    if po is None:
        raise HTTPException(404, "no such purchase order")
    got = con.execute("SELECT COALESCE(SUM(received),0) n FROM"
                      " purchase_order_lines WHERE po_id=?",
                      (pid,)).fetchone()["n"]
    if got:
        # Stock already moved against it; cancelling keeps the paperwork
        # matching the warehouse.
        con.execute("UPDATE purchase_orders SET status='cancelled'"
                    " WHERE id=?", (pid,))
        con.commit()
        return {"ok": True, "cancelled": True, "received": got}
    con.execute("DELETE FROM purchase_order_lines WHERE po_id=?", (pid,))
    con.execute("DELETE FROM purchase_orders WHERE id=?", (pid,))
    con.commit()
    return {"ok": True, "cancelled": False}


@app.get("/api/supply/bom/{product_id}")
def supply_bom(product_id: int, user=Depends(permitted("supply")),
               con=Depends(get_con)):
    return {"lines": supply.bom(con, product_id)}


class BomBody(BaseModel):
    material_id: int
    qty_per_case: float


@app.post("/api/supply/bom/{product_id}")
def supply_set_bom(product_id: int, body: BomBody, user=Depends(permitted("supply")),
                   con=Depends(get_con)):
    if body.qty_per_case <= 0:
        con.execute("DELETE FROM bill_of_materials WHERE product_id=?"
                    " AND material_id=?", (product_id, body.material_id))
    else:
        con.execute(
            "INSERT INTO bill_of_materials(product_id,material_id,"
            " qty_per_case) VALUES(?,?,?) ON CONFLICT(product_id,material_id)"
            " DO UPDATE SET qty_per_case=excluded.qty_per_case",
            (product_id, body.material_id, body.qty_per_case))
    con.commit()
    return {"ok": True}


@app.post("/api/supply/runs")
def supply_add_run(body: supply.RunBody, user=Depends(permitted("supply")),
                   con=Depends(get_con)):
    if not con.execute("SELECT 1 FROM products WHERE id=?",
                       (body.product_id,)).fetchone():
        raise HTTPException(404, "no such product")
    cur = con.execute(
        "INSERT INTO production_runs(product_id,facility,status,"
        " planned_cases,scheduled,notes,created_at)"
        " VALUES(?,?,'planned',?,?,?,?)",
        (body.product_id, body.facility.strip()[:120],
         max(0, body.planned_cases), body.scheduled,
         body.notes.strip()[:500], db.now()))
    con.commit()
    return {"id": cur.lastrowid,
            "shortfall": supply.shortfall(con, body.product_id,
                                          body.planned_cases)}


class RunFinishBody(BaseModel):
    actual_cases: int


@app.post("/api/supply/runs/{rid}/finish")
def supply_finish_run(rid: int, body: RunFinishBody, user=Depends(permitted("supply")),
                      con=Depends(get_con)):
    return supply.finish_run(con, rid, body.actual_cases, user["name"])


@app.patch("/api/supply/runs/{rid}")
def supply_edit_run(rid: int, body: supply.RunBody, user=Depends(permitted("supply")),
                    con=Depends(get_con)):
    return _patch(con, "production_runs", rid, body.model_dump(),
                  ("product_id", "facility", "planned_cases", "scheduled",
                   "notes"))


@app.delete("/api/supply/runs/{rid}")
def supply_del_run(rid: int, user=Depends(permitted("supply")), con=Depends(get_con)):
    r = con.execute("SELECT * FROM production_runs WHERE id=?",
                    (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such run")
    if r["status"] == "done":
        raise HTTPException(
            400, "a finished run has already moved stock — scrap it instead "
                 "of deleting it, so the movements still have something to "
                 "point at")
    con.execute("DELETE FROM production_runs WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


@app.post("/api/supply/shipments")
def supply_add_shipment(body: supply.ShipmentBody, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    cur = con.execute(
        "INSERT INTO inbound_shipments(po_id,carrier,tracking,status,origin,"
        " eta,notes,created_at) VALUES(?,?,?,'booked',?,?,?,?)",
        (body.po_id, body.carrier.strip()[:80], body.tracking.strip()[:120],
         body.origin.strip()[:120], body.eta, body.notes.strip()[:400],
         db.now()))
    con.commit()
    return {"id": cur.lastrowid}


class ShipStatusBody(BaseModel):
    status: str


@app.post("/api/supply/shipments/{sid}/status")
def supply_ship_status(sid: int, body: ShipStatusBody,
                       user=Depends(permitted("supply")), con=Depends(get_con)):
    if body.status not in supply.SHIP_STATUS:
        raise HTTPException(400, f"status must be one of {supply.SHIP_STATUS}")
    con.execute(
        "UPDATE inbound_shipments SET status=?, arrived_at=? WHERE id=?",
        (body.status, db.now() if body.status == "arrived" else 0, sid))
    con.commit()
    return {"ok": True}


@app.delete("/api/supply/shipments/{sid}")
def supply_del_shipment(sid: int, user=Depends(permitted("supply")),
                        con=Depends(get_con)):
    con.execute("DELETE FROM inbound_shipments WHERE id=?", (sid,))
    con.commit()
    return {"ok": True}


@app.get("/api/supply/forecast")
def supply_forecast(days: int = 30, user=Depends(permitted("supply")),
                    con=Depends(get_con)):
    return supply.forecast(con, max(7, min(days, 180)))


class PortalLinkBody(BaseModel):
    rotate: bool = False


@app.post("/api/supply/purchase-orders/{pid}/portal-link")
def supply_portal_link(pid: int, body: PortalLinkBody = PortalLinkBody(),
                       user=Depends(permitted("supply")),
                       con=Depends(get_con)):
    return {"url": supply.portal_link(con, pid, base_url(), body.rotate)}


@app.delete("/api/supply/purchase-orders/{pid}/portal-link")
def supply_revoke_link(pid: int, user=Depends(permitted("supply")),
                       con=Depends(get_con)):
    return supply.revoke_portal(con, pid)


# --- the supplier's side: no account, just the link they were sent ---

@app.get("/api/supplier/{token}")
def supplier_view(token: str, con=Depends(get_con)):
    return supply.portal_view(con, token)


@app.post("/api/supplier/{token}/confirm")
def supplier_confirm(token: str, body: dict, con=Depends(get_con)):
    r = supply.portal_confirm(con, token, body)
    if r["short"] or r["later"]:
        bits = [f"{s['name']} {s['said']} of {s['asked']}" for s in r["short"]]
        notify.push(
            con, "A supplier confirmed less than we ordered"
            if r["short"] else "A supplier pushed back a delivery date",
            "; ".join(bits) or "new ETA is later than expected",
            kind="inventory", dedup=f"poconf:{token[:8]}:{db.now()}")
    return r


@app.get("/supplier/{token}")
def supplier_page(token: str):
    """A page rather than a redirect into the app: the recipient is somebody
    else's staff, on somebody else's device, and the ops PWA would ask them
    to sign in to a business that isn't theirs."""
    return HTMLResponse(SUPPLIER_PAGE)


SUPPLIER_PAGE = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Confirm your order</title>
<style>
 :root { --bg:#f7f6f3; --card:#fff; --line:#e3e0d9; --text:#1c1a17;
   --dim:#6f6a62; --accent:#6d55d6; --bad:#c0483f; }
 * { box-sizing:border-box }
 body { margin:0; background:var(--bg); color:var(--text); padding:24px 16px;
   font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif }
 .wrap { max-width:660px; margin:0 auto }
 .card { background:var(--card); border:1px solid var(--line);
   border-radius:14px; padding:22px; margin-bottom:16px }
 h1 { font-size:22px; margin:0 0 4px }
 .dim { color:var(--dim) }
 table { width:100%; border-collapse:collapse; margin:12px 0 }
 th { text-align:left; font-size:11px; text-transform:uppercase;
   letter-spacing:.06em; color:var(--dim); padding:6px 8px }
 td { padding:8px; border-top:1px solid var(--line) }
 input { width:100%; padding:9px 11px; border:1px solid var(--line);
   border-radius:8px; font-size:15px; background:#fff; color:var(--text) }
 label { display:block; font-size:13px; color:var(--dim); margin:12px 0 4px }
 button { background:var(--accent); color:#fff; border:none; border-radius:8px;
   padding:12px 20px; font-size:16px; font-weight:600; cursor:pointer;
   width:100%; margin-top:18px }
 .num { width:110px }
 .ok { color:#2b7a55 } .bad { color:var(--bad) }
</style></head><body><div class="wrap" id="app">
<div class="card dim">Loading…</div></div>
<script>
const token = location.pathname.split("/").pop();
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const day = (t) => t ? new Date(t*1000).toLocaleDateString([], {
  year:"numeric", month:"short", day:"numeric" }) : "—";

async function load() {
  const r = await fetch(`/api/supplier/${token}`);
  const app = document.getElementById("app");
  if (!r.ok) {
    app.innerHTML = `<div class="card"><h1>Link not valid</h1>
      <p class="dim">This link has expired or was mistyped. Ask your contact
      to send a new one.</p></div>`;
    return;
  }
  const d = await r.json();
  app.innerHTML = `
    <div class="card">
      <h1>${esc(d.reference)}</h1>
      <p class="dim">For ${esc(d.supplier_name)}${d.expected
        ? ` &middot; we asked for ${day(d.expected)}` : ""}</p>
      ${d.notes ? `<p>${esc(d.notes)}</p>` : ""}
      ${d.confirmed ? `<p class="ok">Confirmed by
        ${esc(d.confirmed.confirmed_by)} on
        ${day(d.confirmed.created_at)}. You can send an update below if
        anything has changed.</p>` : ""}
      ${d.closed ? '<p class="bad">This order is closed.</p>' : ""}
    </div>
    ${d.closed ? "" : `<div class="card">
      <p>Please confirm what you can ship and when. If a quantity or the
      date has changed, say so here — knowing now is far more useful to us
      than finding out on the loading dock.</p>
      <table><thead><tr><th>Item</th><th>We asked for</th>
        <th>You'll ship</th></tr></thead><tbody>
        ${d.lines.map((l) => `<tr>
          <td>${esc(l.material_name)}</td>
          <td class="dim">${l.qty} ${esc(l.unit)}</td>
          <td><input class="num" type="number" step="any" data-line="${l.id}"
            value="${l.qty}"></td></tr>`).join("")}
      </tbody></table>
      <label>Your name</label><input id="who">
      <label>Ship date you can meet</label><input id="eta" type="date">
      <label>Anything else we should know</label><input id="msg">
      <button id="go">Confirm this order</button>
      <p class="dim" id="msg-out" style="margin-top:12px"></p>
    </div>`}`;
  if (d.closed) return;
  document.getElementById("go").onclick = async () => {
    const lines = {};
    document.querySelectorAll("[data-line]").forEach((el) => {
      if (el.value !== "") lines[el.dataset.line] = Number(el.value);
    });
    const eta = document.getElementById("eta").value;
    const res = await fetch(`/api/supplier/${token}/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmed_by: document.getElementById("who").value,
        confirmed_eta: eta ? Date.parse(eta) / 1000 : 0,
        message: document.getElementById("msg").value, lines }) });
    const out = document.getElementById("msg-out");
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      out.className = "bad";
      out.textContent = e.detail || "Something went wrong — please try again.";
      return;
    }
    document.getElementById("app").innerHTML = `<div class="card">
      <h1>Thank you</h1><p>We've recorded your confirmation. If anything
      changes, come back to this link and send an update.</p></div>`;
  };
}
load();
</script></body></html>"""


# ---------- integrations ----------

@app.get("/api/admin/integrations")
def integrations_status(user=Depends(admin_user), con=Depends(get_con)):
    d = integrations.status(con)
    # Which OAuth apps have had their client id and secret saved. The secret
    # itself never appears here.
    apps = CFG.get("integration_apps") or {}
    for p in d["providers"]:
        p["app_ready"] = bool((apps.get(p["name"]) or {}).get("client_id"))
    return d


class ConnectBody(BaseModel):
    fields: dict = {}


@app.post("/api/admin/integrations/{name}/connect")
def integrations_connect(name: str, body: ConnectBody,
                         user=Depends(admin_user), con=Depends(get_con)):
    return integrations.connect(con, name, body.fields)


@app.delete("/api/admin/integrations/{name}")
def integrations_disconnect(name: str, user=Depends(admin_user),
                            con=Depends(get_con)):
    return integrations.disconnect(con, name)


class OAuthAppBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""


@app.post("/api/admin/integrations/{name}/app")
def integrations_app(name: str, body: OAuthAppBody, user=Depends(admin_user)):
    """Store the client id and secret of an app you registered.

    These belong to your company rather than to this software, which is why
    they are pasted rather than shipped: an OAuth client secret baked into a
    distributed application is a secret in name only.
    """
    p = integrations.provider(name)
    if p["auth"] != "oauth2":
        raise HTTPException(400, f"{p['label']} doesn't use OAuth")
    apps = dict(CFG.get("integration_apps") or {})
    apps[name] = {"client_id": body.client_id.strip(),
                  "client_secret": body.client_secret.strip()}
    CFG["integration_apps"] = apps
    config.save(CFG)
    return {"ok": True, "redirect_uri": f"{base_url()}/oauth/{name}"}


@app.get("/api/admin/integrations/{name}/authorize")
def integrations_authorize(name: str, user=Depends(admin_user),
                           con=Depends(get_con)):
    """The URL to send someone to so they can approve access."""
    state = secrets.token_urlsafe(18)
    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES(?,?)",
                (f"oauth_state:{name}", state))
    con.commit()
    return {"url": integrations.oauth_url(
        con, name, CFG, f"{base_url()}/oauth/{name}", state)}


@app.get("/oauth/{name}")
def oauth_return(name: str, request: Request, code: str = "", state: str = "",
                 error: str = "", con=Depends(get_con)):
    """Where the provider sends the person back.

    The state is checked because without it this endpoint would accept an
    authorisation code from anywhere — which is how an attacker attaches
    their own account to somebody else's integration.
    """
    def page(title, body):
        return HTMLResponse(
            f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>body{{font:16px/1.6 system-ui;margin:0;background:#f7f6f3;padding:44px 18px}}
.c{{max-width:520px;margin:0 auto;background:#fff;border:1px solid #e3e0d9;
border-radius:14px;padding:26px}} a{{color:#6d55d6}}</style>
<div class="c"><h1>{title}</h1>{body}</div>""")

    if error:
        return page("Not connected", f"<p>{esc_html(error)}</p>")
    want = con.execute("SELECT v FROM store_meta WHERE k=?",
                       (f"oauth_state:{name}",)).fetchone()
    if not want or not state or state != want["v"]:
        return page("Not connected",
                    "<p>That approval didn't come from a request this app "
                    "made. Nothing has been connected.</p>")
    con.execute("DELETE FROM store_meta WHERE k=?", (f"oauth_state:{name}",))
    con.commit()
    try:
        r = integrations.oauth_exchange(
            con, name, CFG, code, f"{base_url()}/oauth/{name}",
            dict(request.query_params))
    except HTTPException as e:
        return page("Not connected", f"<p>{esc_html(str(e.detail))}</p>")
    return page(
        f"{integrations.provider(name)['label']} connected",
        f"<p>Connected as {esc_html(r['account'])}.</p>"
        '<p><a href="/ops/">Back to Business Control</a></p>')


@app.post("/api/admin/integrations/{name}/test")
def integrations_test(name: str, user=Depends(admin_user),
                      con=Depends(get_con)):
    ok, detail = integrations.verify(con, name, CFG)
    integrations.log(con, name, "test", ok, detail)
    if not ok:
        raise HTTPException(400, str(detail))
    return {"ok": True, "detail": detail}


# --- Slack, read and reply ---

@app.get("/api/admin/integrations/slack/channels")
def slack_channels(user=Depends(admin_user), con=Depends(get_con)):
    return integrations.slack_channels(con)


@app.get("/api/admin/integrations/slack/{channel}/messages")
def slack_messages(channel: str, user=Depends(admin_user),
                   con=Depends(get_con)):
    return integrations.slack_messages(con, channel)


class SlackSayBody(BaseModel):
    text: str


@app.post("/api/admin/integrations/slack/{channel}/messages")
def slack_send(channel: str, body: SlackSayBody, user=Depends(admin_user),
               con=Depends(get_con)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "nothing to send")
    return integrations.slack_send(con, channel, text, user["name"])


@app.get("/api/admin/integrations/dropbox/files")
def dropbox_files(user=Depends(admin_user), con=Depends(get_con)):
    return integrations.dropbox_list(con, CFG)


@app.post("/api/admin/integrations/dropbox/backup")
def dropbox_backup(user=Depends(admin_user), con=Depends(get_con)):
    """Send the whole database to Dropbox.

    The unredacted file, same as the download — a backup with the
    credentials stripped out is a file that looks like one right up until
    you need it. Owners only, for that reason, and it lands in a folder the
    screen can then show you, because a backup nobody has ever seen is a
    belief rather than a backup.
    """
    if not user["is_admin"]:
        raise HTTPException(403, "owners only")
    blob = dbview.backup_bytes(con)
    stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime())
    r = integrations.dropbox_upload(
        con, CFG, f"/business-control/backups/business-control-{stamp}.db",
        blob)
    audit.record(con, user, "POST", "/api/admin/integrations/dropbox/backup",
                 f"database backup to Dropbox ({len(blob) // 1024} KB)", 200)
    return r


@app.get("/api/admin/integrations/trello/cards")
def trello_cards(user=Depends(admin_user), con=Depends(get_con)):
    return integrations.trello_cards(con)


@app.post("/api/admin/integrations/{name}/webhook")
def integrations_webhook_on(name: str, user=Depends(admin_user),
                            con=Depends(get_con)):
    return integrations.webhook_register(con, name, base_url())


@app.delete("/api/admin/integrations/{name}/webhook")
def integrations_webhook_off(name: str, user=Depends(admin_user),
                             con=Depends(get_con)):
    return integrations.webhook_remove(con, name)


@app.post("/api/admin/integrations/{name}/sync")
def integrations_sync(name: str, user=Depends(admin_user),
                      con=Depends(get_con)):
    """Pull back what happened to the cards and deals we made."""
    return integrations.sync(con, name)


@app.get("/api/admin/integrations/links/{kind}/{local_id}")
def integrations_links(kind: str, local_id: int, user=Depends(admin_user),
                       con=Depends(get_con)):
    return {"links": integrations.links_for(con, kind, local_id)}


@app.post("/api/admin/integrations/{name}/inbound-key")
def integrations_inbound_key(name: str, rotate: int = 0,
                             user=Depends(admin_user), con=Depends(get_con)):
    key = integrations.inbound_key(con, name, bool(rotate))
    return {"key": key, "url": f"{base_url()}/api/inbound/{name}"}


@app.head("/api/inbound/{name}")
def inbound_probe(name: str):
    """Trello calls the address before it will register a webhook against it.

    Answering here rather than letting it 405 is the difference between a
    subscription that registers and one that is refused with a message about
    the callback — which reads like a bug in us rather than a check passing.
    """
    integrations.provider(name)
    return Response(status_code=200)


@app.post("/api/inbound/{name}")
async def inbound(name: str, request: Request, con=Depends(get_con)):
    """Anything an outside service pushes at us.

    Two different jobs behind one door, because the door is the same: a key
    we issued, on an address we published. LaceUp sends orders, because it
    publishes no API to call into. Trello and Pipedrive send changes, so a
    card finished on the board lands here as it happens rather than when
    somebody remembers to press sync.
    """
    integrations.provider(name)
    key = (request.headers.get("x-api-key")
           or request.query_params.get("key", ""))
    integrations.check_inbound(con, name, key)
    body = await request.json()

    if name in ("trello", "pipedrive"):
        return integrations.handle_push(con, name, body if isinstance(
            body, dict) else {})

    rows = body if isinstance(body, list) else body.get("orders") or [body]
    made, skipped = [], []
    for row in rows:
        try:
            made.append(_inbound_order(con, name, row))
        except HTTPException as e:
            skipped.append({"row": row.get("reference") or row.get("id"),
                            "why": str(e.detail)})
    integrations.log(con, name, "inbound", True,
                     f"{len(made)} order(s), {len(skipped)} skipped")
    return {"placed": made, "skipped": skipped}


def _inbound_order(con, source: str, row: dict) -> int:
    """One order from an outside system.

    Products are matched by SKU rather than by id: an outside system knows
    the code printed on the case, not our primary keys, and asking it to
    learn them is how imports break the first time a database is restored.
    """
    items = []
    for line in (row.get("items") or row.get("lines") or []):
        sku = str(line.get("sku") or line.get("code") or "").strip()
        p = con.execute("SELECT id FROM products WHERE sku=? AND active=1",
                        (sku,)).fetchone()
        if p is None:
            raise HTTPException(400, f"no product with SKU {sku!r}")
        items.append(OrderItemBody(product_id=p["id"],
                                   qty=int(line.get("qty") or 1)))
    if not items:
        raise HTTPException(400, "no recognisable lines")

    name = str(row.get("customer") or row.get("store") or source).strip()
    email = str(row.get("email") or "").strip()
    user = None
    if email:
        user = con.execute("SELECT * FROM users WHERE lower(email)=?",
                           (email.lower(),)).fetchone()
    if user is None:
        cur = con.execute(
            "INSERT INTO users(name,email,role,token,created_at)"
            " VALUES(?,?,'customer',?,?)",
            (name[:80], email[:120], secrets.token_urlsafe(24), db.now()))
        con.commit()
        user = con.execute("SELECT * FROM users WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    body = OrderBody(
        items=items, ship_name=name or "Delivery",
        address=str(row.get("address") or "—"),
        city=str(row.get("city") or "—"),
        postal=str(row.get("postal") or ""),
        region=str(row.get("region") or ""),
        # Already sold on the van: this is a record of an order, not a
        # request for one, so it doesn't go through the confirmation gate.
        pay_method="card")
    o = _place(con, user, body, False)
    return o["id"]


@app.post("/api/admin/integrations/{name}/import")
async def integrations_import(name: str, file: UploadFile = File(...),
                              user=Depends(admin_user), con=Depends(get_con)):
    """A CSV of orders, for when the push route isn't set up.

    Columns: reference, customer, email, city, sku, qty. One row per line
    item; rows sharing a reference become one order.
    """
    integrations.provider(name)
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    grouped: dict = {}
    for r in reader:
        ref = (r.get("reference") or r.get("order") or "1").strip()
        g = grouped.setdefault(ref, {"items": []})
        for k in ("customer", "email", "city", "address", "postal", "region"):
            if r.get(k):
                g[k] = r[k].strip()
        g["items"].append({"sku": r.get("sku", ""), "qty": r.get("qty", 1)})
    made, skipped = [], []
    for ref, row in grouped.items():
        try:
            made.append(_inbound_order(con, name, row))
        except HTTPException as e:
            skipped.append({"row": ref, "why": str(e.detail)})
    integrations.log(con, name, "import", True,
                     f"{len(made)} order(s) from {file.filename}")
    return {"placed": made, "skipped": skipped}


@app.get("/api/admin/integrations/canva/designs")
def canva_designs(user=Depends(admin_user), con=Depends(get_con)):
    """Your Canva designs, so finished artwork can come straight in."""
    tok = integrations.access_token(con, "canva", CFG)
    ok, d = integrations._req(
        "https://api.canva.com/rest/v1/designs",
        headers={"Authorization": f"Bearer {tok}"})
    if not ok:
        raise HTTPException(400, f"Canva said: {d}")
    return d


# ---------- the audit log ----------

@app.get("/api/admin/audit")
def read_audit(limit: int = 200, actor: str = "", entity: str = "",
               user=Depends(admin_user), con=Depends(get_con)):
    return audit.read(con, limit, actor, entity)


# ---------- the database, directly ----------

@app.get("/api/admin/db")
def db_overview(user=Depends(admin_user), con=Depends(get_con)):
    return dbview.overview(con)


# These two sit above /api/admin/db/{table} on purpose: routes match in
# registration order, so a path parameter declared first would swallow
# "export.json" and "backup.db" as though they were table names.
@app.get("/api/admin/db/export.json")
def db_export_json(tables: str = "", request: Request = None,
                   user=Depends(admin_user), con=Depends(get_con)):
    names = [t for t in tables.split(",") if t.strip()] or None
    body = dbview.export_json(con, names)
    audit.record(con, user, "GET", "/api/admin/db/export.json",
                 f"exported {len(names) if names else 'all'} table(s) as JSON",
                 200)
    return Response(
        body, media_type="application/json",
        headers={"Content-Disposition":
                 'attachment; filename="business-control-export.json"'})


@app.get("/api/admin/db/backup.db")
def db_backup(user=Depends(admin_user), con=Depends(get_con)):
    """The unredacted file. Owners only — the database permission is for
    fixing a row, not for walking out with every credential in the
    business."""
    if not user["is_admin"]:
        raise HTTPException(403, "owners only")
    blob = dbview.backup_bytes(con)
    audit.record(con, user, "GET", "/api/admin/db/backup.db",
                 f"downloaded a full backup ({len(blob) // 1024} KB)", 200)
    return Response(
        blob, media_type="application/vnd.sqlite3",
        headers={"Content-Disposition":
                 'attachment; filename="business-control-backup.db"'})


@app.get("/api/admin/db/{table}")
def db_rows(table: str, q: str = "", limit: int = 50, offset: int = 0,
            user=Depends(admin_user), con=Depends(get_con)):
    return dbview.rows(con, table, q, limit, offset)


class RowEdit(BaseModel):
    values: dict


@app.patch("/api/admin/db/{table}/{row_id}")
def db_update(table: str, row_id: str, body: RowEdit,
              user=Depends(admin_user), con=Depends(get_con)):
    return dbview.update(con, table, row_id, body.values)


@app.delete("/api/admin/db/{table}/{row_id}")
def db_delete(table: str, row_id: str, user=Depends(admin_user),
              con=Depends(get_con)):
    return dbview.delete(con, table, row_id)


# --- getting the data out ---
# These are GETs so a browser can download them directly, which means they
# don't pass through the audit middleware. Each records itself: an export is
# a copy of the business leaving the building, and it is exactly the sort of
# thing you want to be able to look up afterwards.

@app.get("/api/admin/db/{table}/export.csv")
def db_export_csv(table: str, request: Request, user=Depends(admin_user),
                  con=Depends(get_con)):
    body = dbview.export_csv(con, table)
    audit.record(con, user, "GET", f"/api/admin/db/{table}/export.csv",
                 f"exported {table} as CSV", 200)
    return Response(
        body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{table}.csv"'})




# ---------- trucks & routes ----------

@app.get("/api/trucks")
def trucks(user=Depends(current_user), con=Depends(get_con)):
    return [dict(r) for r in
            con.execute("SELECT * FROM trucks WHERE active=1").fetchall()]


class TruckBody(BaseModel):
    name: str
    capacity_cases: int = 400
    home_region: str = ""


@app.post("/api/admin/trucks")
def add_truck(body: TruckBody, user=Depends(admin_user), con=Depends(get_con)):
    con.execute("INSERT INTO trucks(name,capacity_cases,home_region)"
                " VALUES(?,?,?)",
                (body.name, body.capacity_cases, body.home_region))
    con.commit()
    return {"ok": True}


@app.get("/api/trucks/{tid}/route")
def truck_route(tid: int, user=Depends(current_user), con=Depends(get_con)):
    """Latest not-done route for a truck — what the driver sees after check-in."""
    r = con.execute(
        "SELECT id FROM routes WHERE truck_id=? AND status!='done'"
        " ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
    return route_json(con, r["id"]) if r else None


@app.post("/api/trucks/{tid}/checkin")
def truck_checkin(tid: int, user=Depends(current_user), con=Depends(get_con)):
    """Driver scanned the truck's QR: record them as its driver and hand back
    the truck plus its current route."""
    t = con.execute("SELECT * FROM trucks WHERE id=? AND active=1",
                    (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such truck")
    con.execute("UPDATE trucks SET driver_user_id=? WHERE id=?",
                (user["id"], tid))
    con.commit()
    notify.push(con, f"{user['name']} checked into {t['name']}",
                kind="logistics")
    return {"truck": dict(con.execute("SELECT * FROM trucks WHERE id=?",
                                      (tid,)).fetchone()),
            "driver": user["name"],
            "route": truck_route(tid, user, con)}


class RoutePlanBody(BaseModel):
    truck_id: int
    route_date: str = ""
    store_ids: list[int] = []
    region: str = ""            # used when store_ids is empty
    name: str = ""


@app.post("/api/routes/plan")
def plan_route(body: RoutePlanBody, user=Depends(current_user),
               con=Depends(get_con)):
    if body.store_ids:
        marks = ",".join("?" * len(body.store_ids))
        rows = con.execute(
            f"SELECT * FROM stores WHERE id IN ({marks})",
            body.store_ids).fetchall()
    elif body.region:
        rows = con.execute(
            "SELECT * FROM stores WHERE region=? AND active=1",
            (body.region,)).fetchall()
    else:
        raise HTTPException(400, "give store_ids or a region")
    if len(rows) < 2:
        raise HTTPException(400, "need at least 2 stops")
    pts = [dict(r) for r in rows if r["lat"] is not None]
    name = body.name or (f"{body.region or 'custom'} run"
                         f"{' ' + body.route_date if body.route_date else ''}")
    return _create_route(con, pts, body.truck_id, body.route_date, name)


def _create_route(con, pts, truck_id, route_date, name) -> dict:
    # Depot first: prefer a distributor DC if one is in the set.
    pts.sort(key=lambda p: 0 if p["kind"] == "distributor_dc" else 1)
    ordered, total = logistics.plan(pts)
    total_min = logistics.add_times(ordered, CFG.get("route_avg_kmh", 55),
                                    CFG.get("stop_service_min", 20))
    cur = con.execute(
        "INSERT INTO routes(name,truck_id,route_date,total_km,total_min,"
        " created_at) VALUES(?,?,?,?,?,?)",
        (name, truck_id, route_date, total, total_min, db.now()))
    rid = cur.lastrowid
    for i, p in enumerate(ordered):
        con.execute("INSERT INTO route_stops(route_id,seq,store_id,leg_km)"
                    " VALUES(?,?,?,?)", (rid, i, p["id"], p["leg_km"]))
    con.commit()
    return route_json(con, rid)


def _coverage_route(con, region: str) -> dict:
    """(Re)generate the auto-maintained coverage route for a region: every
    active store, optimized order, assigned to the region's truck."""
    rows = con.execute("SELECT * FROM stores WHERE region=? AND active=1",
                       (region,)).fetchall()
    pts = [dict(r) for r in rows if r["lat"] is not None]
    if len(pts) < 2:
        raise HTTPException(400, f"need at least 2 stores in {region}")
    name = f"Coverage — {region}"
    # Replace the previous auto-plan (only if still in 'planned' state).
    for old in con.execute("SELECT id FROM routes WHERE name=? AND"
                           " status='planned'", (name,)).fetchall():
        con.execute("DELETE FROM route_stops WHERE route_id=?", (old["id"],))
        con.execute("DELETE FROM routes WHERE id=?", (old["id"],))
    truck = con.execute(
        "SELECT id FROM trucks WHERE active=1 ORDER BY"
        " (home_region=?) DESC, id LIMIT 1", (region,)).fetchone()
    return _create_route(con, pts, truck["id"] if truck else None, "", name)


class AutoRouteBody(BaseModel):
    region: str = ""            # empty = every region with 2+ stores


@app.post("/api/admin/routes/auto")
def auto_routes(body: AutoRouteBody, user=Depends(admin_user),
                con=Depends(get_con)):
    regions = [body.region] if body.region else CFG["regions"]
    made = []
    for region in regions:
        try:
            made.append(_coverage_route(con, region))
        except HTTPException:
            continue
    if not made:
        raise HTTPException(400, "no region has 2+ mapped stores")
    return made


def route_json(con, rid: int) -> dict:
    r = con.execute("SELECT * FROM routes WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such route")
    stops = con.execute(
        "SELECT rs.*, s.name, s.city, s.region, s.lat, s.lng FROM route_stops rs"
        " JOIN stores s ON s.id=rs.store_id WHERE route_id=? ORDER BY seq",
        (rid,)).fetchall()
    d = dict(r)
    d["stops"] = [dict(s) for s in stops]
    d["total_min"] = logistics.add_times(
        d["stops"], CFG.get("route_avg_kmh", 55),
        CFG.get("stop_service_min", 20))
    return d


@app.get("/api/routes")
def routes(user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute("SELECT id FROM routes ORDER BY id DESC LIMIT 50").fetchall()
    return [route_json(con, r["id"]) for r in rows]


@app.post("/api/routes/{rid}/status")
def route_status(rid: int, body: StatusBody, user=Depends(current_user),
                 con=Depends(get_con)):
    if body.status not in ("planned", "active", "done"):
        raise HTTPException(400, "bad status")
    con.execute("UPDATE routes SET status=? WHERE id=?", (body.status, rid))
    con.commit()
    return {"ok": True}


class StopBody(BaseModel):
    seq: int
    delivered: bool


@app.post("/api/routes/{rid}/stop")
def mark_stop(rid: int, body: StopBody, user=Depends(current_user),
              con=Depends(get_con)):
    stop = con.execute(
        "SELECT * FROM route_stops WHERE route_id=? AND seq=?",
        (rid, body.seq)).fetchone()
    if stop is None:
        raise HTTPException(404, "no such stop")
    con.execute("UPDATE route_stops SET delivered=? WHERE route_id=? AND seq=?",
                (1 if body.delivered else 0, rid, body.seq))
    # Coverage trucks restock to par: delivering a stop tops the store up.
    if body.delivered and not stop["delivered"]:
        con.execute(
            "UPDATE inventory SET qty=MAX(qty, par), updated_at=?"
            " WHERE store_id=?", (db.now(), stop["store_id"]))
    con.commit()
    return {"ok": True}


# ---------- promotions & in-person events ----------

@app.get("/api/promos")
def promos(kind: str = "", con=Depends(get_con)):
    """Public list of active promos/events — powers QR landing pages and the
    Time Clock's event picker."""
    q = "SELECT * FROM promos WHERE active=1"
    args = []
    if kind:
        q += " AND kind=?"
        args.append(kind)
    rows = con.execute(q + " ORDER BY id DESC", args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/promos")
def all_promos(user=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT p.*, COUNT(ps.promo_id) scans,"
        " COUNT(DISTINCT ps.visitor_id) unique_scans"
        " FROM promos p LEFT JOIN promo_scans ps ON ps.promo_id=p.id"
        " GROUP BY p.id ORDER BY p.id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["staff_hours"] = con.execute(
            "SELECT COALESCE(SUM(COALESCE(clock_out,?) - clock_in),0)/3600.0 h"
            " FROM shifts WHERE event_id=?", (db.now(), r["id"])).fetchone()["h"]
        d["staff_hours"] = round(d["staff_hours"], 1)
        out.append(d)
    return out


class PromoBody(BaseModel):
    kind: str = "promo"
    name: str
    body: str = ""
    product_id: int | None = None
    discount_pct: int = 0
    region: str = ""
    city: str = ""
    lat: float | None = None
    lng: float | None = None
    starts: str = ""
    video_url: str = ""


@app.post("/api/admin/promos")
def add_promo(body: PromoBody, user=Depends(admin_user), con=Depends(get_con)):
    if body.kind not in ("promo", "event"):
        raise HTTPException(400, "kind must be promo or event")
    cur = con.execute(
        "INSERT INTO promos(kind,name,body,product_id,discount_pct,region,"
        " city,lat,lng,starts,video_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.kind, body.name, body.body, body.product_id, body.discount_pct,
         body.region, body.city, body.lat, body.lng, body.starts,
         body.video_url.strip(), db.now()))
    con.commit()
    pid = cur.lastrowid
    return {"ok": True, "id": pid, "link": f"/?promo={pid}",
            "qr_url": f"{base_url()}/?promo={pid}"}


@app.post("/api/admin/promos/{pid}/toggle")
def toggle_promo(pid: int, user=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE promos SET active=1-active WHERE id=?", (pid,))
    con.commit()
    return {"ok": True}


class ScanBody(BaseModel):
    visitor_id: str


@app.post("/api/promos/{pid}/scan")
def promo_scan(pid: int, body: ScanBody, con=Depends(get_con)):
    p = con.execute("SELECT * FROM promos WHERE id=? AND active=1",
                    (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "promotion ended")
    con.execute("INSERT INTO promo_scans(promo_id,visitor_id,created_at)"
                " VALUES(?,?,?)", (pid, body.visitor_id, db.now()))
    con.commit()
    d = dict(p)
    if p["product_id"]:
        prod = con.execute("SELECT * FROM products WHERE id=?",
                           (p["product_id"],)).fetchone()
        d["product"] = dict(prod) if prod else None
    return d


# ---------- box cycles (cutoff orchestration) ----------

@app.get("/api/cycles")
def list_cycles(user=Depends(current_user), con=Depends(get_con)):
    if not chat.is_staff(user):
        raise HTTPException(403, "staff only")
    rows = con.execute("SELECT * FROM box_cycles ORDER BY month DESC"
                       " LIMIT 24").fetchall()
    return [cycles.as_json(r) for r in rows]


@app.get("/api/cycles/current")
def current_cycle(user=Depends(current_user), con=Depends(get_con)):
    """The gate the subscriber portal obeys: changes_open says whether
    skip/swap is still allowed this cycle."""
    return cycles.current(con)


class CycleBody(BaseModel):
    month: str                    # 'YYYY-MM'
    bill_date: str = ""
    dunning_close: str = ""
    curation_lock: str = ""
    ship_date: str = ""


@app.post("/api/admin/cycles")
def add_cycle(body: CycleBody, user=Depends(admin_user), con=Depends(get_con)):
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", body.month):
        raise HTTPException(400, "month must be YYYY-MM")
    if con.execute("SELECT 1 FROM box_cycles WHERE month=?",
                   (body.month,)).fetchone():
        raise HTTPException(400, "cycle already exists")
    try:
        return cycles.create(con, CFG, body.month, {
            "bill_date": body.bill_date, "dunning_close": body.dunning_close,
            "curation_lock": body.curation_lock, "ship_date": body.ship_date})
    except ValueError as e:
        raise HTTPException(400, str(e))


class CycleUpdateBody(BaseModel):
    billed_count: int | None = None
    skipped_count: int | None = None
    allocated_count: int | None = None
    closed: bool | None = None


@app.post("/api/admin/cycles/{cid}/update")
def update_cycle(cid: int, body: CycleUpdateBody, user=Depends(admin_user),
                 con=Depends(get_con)):
    c = con.execute("SELECT * FROM box_cycles WHERE id=?", (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "no such cycle")
    vals = {k: getattr(body, k) for k in ("billed_count", "skipped_count",
            "allocated_count", "closed") if getattr(body, k) is not None}
    for k, v in vals.items():
        con.execute(f"UPDATE box_cycles SET {k}=? WHERE id=?",
                    (int(v), cid))
    con.commit()
    return cycles.as_json(con.execute("SELECT * FROM box_cycles WHERE id=?",
                                      (cid,)).fetchone())


# ---------- private Shopify subscription app ----------

@app.get("/api/admin/shopify/status")
def shopify_status(user=Depends(admin_user), con=Depends(get_con)):
    try:
        info = shopify_sub.ping(CFG)
    except Exception as e:
        info = {"connected": False, "mode": "error", "error": str(e)[:200]}
    info["billing_log"] = [dict(r) for r in con.execute(
        "SELECT * FROM sub_billing ORDER BY id DESC LIMIT 30").fetchall()]
    return info


class PlanBody(BaseModel):
    name: str = "Monthly Box"
    interval: str = "MONTH"
    percent_off: float = 10.0


@app.post("/api/admin/shopify/selling-plan")
def shopify_plan(body: PlanBody, user=Depends(admin_user)):
    if body.interval not in ("WEEK", "MONTH", "YEAR"):
        raise HTTPException(400, "interval must be WEEK/MONTH/YEAR")
    try:
        return shopify_sub.create_selling_plan(CFG, body.name, body.interval,
                                               body.percent_off)
    except Exception as e:
        raise HTTPException(502, f"Shopify error: {e}")


class BillRunBody(BaseModel):
    cycle_month: str


@app.post("/api/admin/shopify/bill-run")
def shopify_bill_run(body: BillRunBody, user=Depends(admin_user),
                     con=Depends(get_con)):
    c = con.execute("SELECT * FROM box_cycles WHERE month=?",
                    (body.cycle_month,)).fetchone()
    if c is None:
        raise HTTPException(404, "create the box cycle first")
    result = shopify_sub.bill_run(con, CFG, body.cycle_month)
    notify.push(con, f"Bill run {body.cycle_month}: "
                     f"{result['attempted']} attempted, "
                     f"{result['billed_success']} succeeded"
                     f" ({result['mode']})", kind="cycle")
    return result


@app.post("/webhooks/shopify")
async def shopify_webhook(request: Request, con=Depends(get_con)):
    raw = await request.body()
    if not shopify_sub.verify_webhook(
            CFG, raw, request.headers.get("X-Shopify-Hmac-Sha256", "")):
        raise HTTPException(401, "bad hmac")
    topic = request.headers.get("X-Shopify-Topic", "")
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    return {"result": shopify_sub.handle_webhook(con, CFG, topic, payload)}


# ---------- analytics ----------

@app.get("/api/analytics/pnl")
def pnl_analytics(days: int = 30, user=Depends(admin_user),
                  con=Depends(get_con)):
    return analytics.pnl(con, CFG, days)


# ---------- notifications & achievements ----------

@app.get("/api/notifications")
def notifications(user=Depends(current_user), con=Depends(get_con)):
    if user["is_admin"]:
        notify.sweep(con, CFG)
    items, unread = notify.for_user(con, user)
    return {"items": items, "unread": unread}


@app.post("/api/notifications/read")
def read_notifications(user=Depends(current_user), con=Depends(get_con)):
    notify.mark_all_read(con, user)
    return {"ok": True}


@app.get("/api/achievements")
def achievements(user=Depends(admin_user), con=Depends(get_con)):
    return achieve.check(con, CFG)


# ---------- web push ----------

@app.get("/api/push/pubkey")
def push_pubkey(user=Depends(current_user)):
    return {"key": push.public_key()}


class SubscribeBody(BaseModel):
    subscription: dict


@app.post("/api/push/subscribe")
def push_subscribe(body: SubscribeBody, user=Depends(current_user),
                   con=Depends(get_con)):
    if not body.subscription.get("endpoint"):
        raise HTTPException(400, "bad subscription")
    push.save_subscription(con, user["id"], body.subscription)
    return {"ok": True}


class UnsubscribeBody(BaseModel):
    endpoint: str


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: UnsubscribeBody, user=Depends(current_user),
                     con=Depends(get_con)):
    push.drop_subscription(con, body.endpoint)
    return {"ok": True}


# ---------- chat, calls, support ----------

@app.get("/api/chat/convs")
def chat_convs(user=Depends(current_user), con=Depends(get_con)):
    return {"convs": chat.convs_for(con, user), "online": chat.online_ids(),
            "me": user["id"]}


def _conv_or_403(con, user, cid: int):
    conv = con.execute("SELECT * FROM conversations WHERE id=?",
                       (cid,)).fetchone()
    if conv is None:
        raise HTTPException(404, "no such conversation")
    if not chat.can_access(con, user, conv):
        raise HTTPException(403, "not your conversation")
    return conv


@app.get("/api/chat/convs/{cid}/messages")
def chat_history(cid: int, after: int = 0, user=Depends(current_user),
                 con=Depends(get_con)):
    _conv_or_403(con, user, cid)
    rows = con.execute(
        "SELECT m.*, u.name FROM messages m JOIN users u ON u.id=m.user_id"
        " WHERE conv_id=? AND m.id>? ORDER BY m.id LIMIT 200",
        (cid, after)).fetchall()
    return [dict(r) for r in rows]


class MessageBody(BaseModel):
    body: str


@app.post("/api/chat/convs/{cid}/messages")
async def chat_send(cid: int, body: MessageBody, user=Depends(current_user),
                    con=Depends(get_con)):
    conv = _conv_or_403(con, user, cid)
    text = body.body.strip()[:2000]
    if not text:
        raise HTTPException(400, "empty message")
    m = chat.add_message(con, cid, user, text)
    aud = chat.audience(con, conv)
    await chat.send_to(aud, {"type": "msg", "conv_id": cid, "message": m})
    offline = [u for u in aud if u not in chat.online_ids()
               and u != user["id"]]
    if offline:
        push.send(CFG, f"{user['name']}: {text[:90]}", user_ids=offline)
    return m


class DMBody(BaseModel):
    user_id: int


@app.post("/api/chat/dm")
def chat_dm(body: DMBody, user=Depends(current_user), con=Depends(get_con)):
    if not chat.is_staff(user):
        raise HTTPException(403, "staff only")
    other = con.execute("SELECT * FROM users WHERE id=? AND active=1",
                        (body.user_id,)).fetchone()
    if other is None or not chat.is_staff(other):
        raise HTTPException(400, "pick another staff member")
    return {"conv_id": chat.ensure_dm(con, user["id"], other["id"])}


@app.get("/api/chat/staff")
def chat_staff(user=Depends(current_user), con=Depends(get_con)):
    if not chat.is_staff(user):
        raise HTTPException(403, "staff only")
    rows = con.execute(
        "SELECT id, name, role FROM users WHERE active=1 AND id!=? AND"
        " (is_admin=1 OR role IN ('employee','owner')) ORDER BY name",
        (user["id"],)).fetchall()
    return {"staff": [dict(r) for r in rows], "online": chat.online_ids()}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = ""):
    # HTTP middleware does not wrap websockets, so the tenant is resolved
    # here from the handshake's own Host header — before any connect().
    try:
        _wtid = tenancy.resolve(websocket.headers.get("host", ""))
    except (tenancy.UnknownHost, tenancy.Suspended):
        await websocket.close(code=4404)
        return
    _wtok = tenancy.CURRENT.set(_wtid)
    con = db.connect()
    user = auth.user_for_token(con, token)
    if user is None:
        con.close()
        await websocket.close(code=4401)
        return
    await websocket.accept()
    chat.register(user["id"], websocket)
    try:
        while True:
            try:
                msg = json.loads(await websocket.receive_text())
            except ValueError:
                continue
            if msg.get("type") == "msg":
                conv = con.execute("SELECT * FROM conversations WHERE id=?",
                                   (msg.get("conv_id"),)).fetchone()
                if conv is None or not chat.can_access(con, user, conv):
                    continue
                text = str(msg.get("body", "")).strip()[:2000]
                if not text:
                    continue
                m = chat.add_message(con, conv["id"], user, text)
                aud = chat.audience(con, conv)
                await chat.send_to(aud, {"type": "msg",
                                         "conv_id": conv["id"], "message": m})
                offline = [u for u in aud if u not in chat.online_ids()
                           and u != user["id"]]
                if offline:
                    push.send(CFG, f"{user['name']}: {text[:90]}",
                              user_ids=offline)
            elif msg.get("type") == "signal":
                # WebRTC call signaling: relay verbatim to the target user.
                to = int(msg.get("to") or 0)
                await chat.send_to([to], {
                    "type": "signal", "from": user["id"],
                    "from_name": user["name"],
                    "payload": msg.get("payload") or {}})
    except WebSocketDisconnect:
        pass
    finally:
        chat.unregister(user["id"], websocket)
        con.close()
        tenancy.CURRENT.reset(_wtok)


# ---------- email marketing ----------

class EmailConfigBody(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    starttls: bool = True
    email_from: str = ""
    abandoned_cart: bool = True
    winback: bool = True


@app.get("/api/admin/email/config")
def email_config(user=Depends(admin_user)):
    s = CFG.get("smtp", {})
    return {"host": s.get("host", ""), "port": s.get("port", 587),
            "username": s.get("username", ""),
            "password_set": bool(s.get("password")),
            "starttls": s.get("starttls", True),
            "email_from": CFG.get("email_from", ""),
            "playbooks": CFG.get("email_playbooks", {})}


@app.post("/api/admin/email/config")
def set_email_config(body: EmailConfigBody, user=Depends(admin_user)):
    smtp = dict(CFG.get("smtp", {}))
    smtp.update({"host": body.host.strip(), "port": body.port,
                 "username": body.username.strip(),
                 "starttls": body.starttls})
    if body.password:                     # empty = keep existing
        smtp["password"] = body.password
    CFG["smtp"] = smtp
    if body.email_from.strip():
        CFG["email_from"] = body.email_from.strip()
    CFG["email_playbooks"] = {"abandoned_cart": body.abandoned_cart,
                              "winback": body.winback}
    config.save(CFG)
    return {"ok": True}


@app.get("/api/admin/email/log")
def email_log(user=Depends(admin_user), con=Depends(get_con)):
    # A client's point of contact is not a user of this system, so the
    # address recorded on the send wins over the one a join could find.
    rows = con.execute(
        "SELECT l.*, u.name, COALESCE(NULLIF(l.to_addr,''), u.email, '')"
        "   AS email"
        " FROM email_log l LEFT JOIN users u ON u.id=l.user_id"
        " ORDER BY l.id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


class TestEmailBody(BaseModel):
    to: str


@app.post("/api/admin/email/test")
def email_test(body: TestEmailBody, user=Depends(admin_user)):
    if not body.to.strip():
        raise HTTPException(400, "recipient required")
    status = mailer.send(
        CFG, body.to.strip(), f"{CFG['brand_name']} — test email",
        "If you're reading this, SMTP is configured correctly.\n\n"
        f"— {CFG['brand_name']}")
    return {"status": status}


class BlastBody(BaseModel):
    promo_id: int


@app.post("/api/admin/email/blast")
def email_blast(body: BlastBody, user=Depends(admin_user),
                con=Depends(get_con)):
    promo = con.execute("SELECT * FROM promos WHERE id=? AND active=1",
                        (body.promo_id,)).fetchone()
    if promo is None:
        raise HTTPException(404, "no such active promo")
    return mailer.blast(con, CFG, promo, f"{base_url()}/?promo={promo['id']}")


@app.get("/api/game")
def game_view(user=Depends(admin_user), con=Depends(get_con)):
    return analytics.game(con, CFG)

@app.get("/api/analytics/regions")
def region_analytics(days: int = 30, user=Depends(current_user),
                     con=Depends(get_con)):
    return analytics.regions(con, days)


@app.get("/api/analytics/funnel")
def funnel_analytics(days: int = 30, region: str = "",
                     user=Depends(current_user), con=Depends(get_con)):
    return analytics.funnel(con, days, region)


@app.get("/api/analytics/engagement")
def engagement_analytics(user=Depends(current_user), con=Depends(get_con)):
    return analytics.engagement(con, CFG)


# ---------- outreach ----------

@app.get("/api/outreach")
def outreach(region: str = "", user=Depends(current_user), con=Depends(get_con)):
    q = ("SELECT o.*, u.name owner FROM outreach o"
         " LEFT JOIN users u ON u.id=o.owner_user_id")
    args = []
    if region:
        q += " WHERE o.region=?"
        args.append(region)
    rows = con.execute(q + " ORDER BY o.updated_at DESC", args).fetchall()
    return [dict(r) for r in rows]


class OutreachBody(BaseModel):
    name: str
    region: str
    city: str = ""
    lat: float | None = None
    lng: float | None = None
    next_action: str = ""
    next_action_date: str = ""


@app.post("/api/outreach")
def add_outreach(body: OutreachBody, user=Depends(current_user),
                 con=Depends(get_con)):
    cur = con.execute(
        "INSERT INTO outreach(name,region,city,lat,lng,owner_user_id,"
        " next_action,next_action_date,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (body.name, body.region, body.city, body.lat, body.lng, user["id"],
         body.next_action, body.next_action_date, db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class StageBody(BaseModel):
    stage: str
    note: str = ""
    next_action: str = ""
    next_action_date: str = ""


@app.post("/api/outreach/{oid}/update")
def update_outreach(oid: int, body: StageBody, user=Depends(current_user),
                    con=Depends(get_con)):
    if body.stage not in ("lead", "contacted", "sampled", "stocked", "lost"):
        raise HTTPException(400, "bad stage")
    prev = con.execute("SELECT * FROM outreach WHERE id=?", (oid,)).fetchone()
    con.execute(
        "UPDATE outreach SET stage=?, next_action=?, next_action_date=?,"
        " updated_at=? WHERE id=?",
        (body.stage, body.next_action, body.next_action_date, db.now(), oid))
    if prev and body.stage == "stocked" and prev["stage"] != "stocked":
        notify.push(con, f"New account stocked: {prev['name']}"
                         f" ({prev['region']})", kind="outreach")
    if body.note:
        con.execute("INSERT INTO outreach_log(outreach_id,user_id,note,"
                    " created_at) VALUES(?,?,?,?)",
                    (oid, user["id"], body.note, db.now()))
    con.commit()
    return {"ok": True}


@app.get("/api/outreach/{oid}/log")
def outreach_history(oid: int, user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT l.*, u.name FROM outreach_log l LEFT JOIN users u"
        " ON u.id=l.user_id WHERE outreach_id=? ORDER BY l.id DESC",
        (oid,)).fetchall()
    return [dict(r) for r in rows]


# ---------- frontends ----------
# Two products, one process: the customer storefront (the face) owns "/",
# the ERP/CRM ops app (the brain) lives at /ops, the store admin at /admin.

from storefront.backend import affiliates as store_aff  # noqa: E402
from storefront.backend import api as store_api  # noqa: E402
from storefront.backend import content as store_content  # noqa: E402
from storefront.backend import governance as store_gov  # noqa: E402
from storefront.backend import partners as store_partners  # noqa: E402
from storefront.backend import campaigns as store_campaigns  # noqa: E402
from storefront.backend import crud as store_crud  # noqa: E402
from storefront.backend import discord as store_discord  # noqa: E402
from storefront.backend import emailer as store_email  # noqa: E402
from storefront.backend import documents as store_docs  # noqa: E402
from storefront.backend import engagements as store_eng  # noqa: E402
from storefront.backend import fleetadmin as store_fleet  # noqa: E402
from storefront.backend import sow as store_sow  # noqa: E402
from storefront.backend import pixels as store_pixels  # noqa: E402
from storefront.backend import support as store_support  # noqa: E402
from storefront.backend import promos as store_promos  # noqa: E402
from storefront.backend import public_api as store_v1  # noqa: E402

def init_tenant(tid=None):
    """Everything a tenant's database needs, in one call — the ERP core and
    the storefront's fourteen-module fan-out. Runs per tenant at boot, and
    for a tenant minted at runtime via tenancy.create()."""
    _init_core(tid)
    tok = tenancy.CURRENT.set(tid)
    try:
        store_api.init_tables()
    finally:
        tenancy.CURRENT.reset(tok)


tenancy.INIT = init_tenant
for _tid in (tenancy.all_tenants() or [None]):
    init_tenant(_tid)

app.include_router(store_api.router)
app.include_router(store_promos.router)
app.include_router(store_content.router)
app.include_router(store_aff.router)
app.include_router(store_gov.router)
app.include_router(store_partners.router)
app.include_router(store_pixels.router)
app.include_router(store_support.router)
app.include_router(store_campaigns.router)
app.include_router(store_docs.router)
app.include_router(store_eng.router)
app.include_router(store_fleet.router)
app.include_router(store_sow.router)
app.include_router(store_crud.router)
app.include_router(store_discord.router)
app.include_router(store_email.router)
app.include_router(store_v1.router)

from . import classroom, community, learning  # noqa: E402  (safe — see _init_core)
from . import datarights, identity, library, materials, nutrition  # noqa: E402
from storefront.backend import learn as store_learn  # noqa: E402
from storefront.backend import nutrition as store_nutrition  # noqa: E402
app.include_router(learning.router)
app.include_router(classroom.router)
app.include_router(community.router)
app.include_router(library.router)
app.include_router(materials.router)
app.include_router(identity.router)
app.include_router(datarights.router)
app.include_router(nutrition.router)
app.include_router(store_learn.router)
app.include_router(store_nutrition.router)
from . import people  # noqa: E402  (safe: included late)
app.include_router(people.router)
from . import apikeys  # noqa: E402  (safe: included late)
app.include_router(apikeys.router)


@app.exception_handler(404)
async def maybe_redirect(request: Request, exc):
    """Merchant-managed redirects, so migrating a store keeps inbound links
    alive. Only plain page GETs are considered — never the API."""
    path = request.url.path
    if request.method == "GET" and not path.startswith(("/api/", "/media/")):
        con = db.connect()
        try:
            r = store_content.find_redirect(con, path)
            if r is not None:
                return r
        finally:
            con.close()
    return JSONResponse({"detail": getattr(exc, "detail", "not found")},
                        status_code=404)


@app.get("/ops")
def ops_redirect():
    return RedirectResponse("/ops/")


@app.get("/ops/")
def ops_index():
    """Serve the shell with mtime-stamped asset URLs.

    StaticFiles alone left ops staff on the previous app.js after a deploy —
    the service worker is network-first, so the stale copy came from ordinary
    HTTP caching. Same fix as the storefront's asset_version()."""
    shell = (config.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    newest = 0.0
    for f in (list(config.FRONTEND_DIR.glob("*.js"))
              + list(config.FRONTEND_DIR.glob("*.css"))
              + list(config.FRONTEND_DIR.glob("*.html"))
              # the QR scanner is shared and lives with the storefront, so a
              # change to it has to move this version too
              + [config.STOREFRONT_DIR / "qr-scan.js",
                 config.STOREFRONT_DIR / "qr-scan.css"]):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            pass
    v = str(int(newest))
    for asset in ("/ops/styles.css", "/ops/app.js", "/qr-scan.js",
                  "/qr-scan.css"):
        shell = shell.replace(f'"{asset}"', f'"{asset}?v={v}"')
    shell = shell.replace("</head>", _ops_brand_style() + "</head>", 1)
    return HTMLResponse(shell)


def _ops_brand_style() -> str:
    """The back office in this business's own colours.

    The two faces of one install were two different brands: the shop wore
    the colours somebody chose and the ops app wore a violet baked into a
    stylesheet. So the shell carries the tenant's brand hues in, and the
    dark palette derives its accent from them — lightened, because a
    colour picked to sit on paper is rarely readable on a dark panel.
    A tenant with no theme keeps exactly what it had.
    """
    from storefront.backend import api as store_api
    try:
        con = db.connect()
        try:
            t = store_api.get_theme(con) or {}
        finally:
            con.close()
    except Exception:                                        # noqa: BLE001
        return ""
    hue = str(t.get("purple") or "").strip()
    second = str(t.get("lavender") or "").strip()
    warm = str(t.get("orange") or "").strip()
    if not (hue.startswith("#") and len(hue) in (4, 7)):
        return ""
    parts = [f"--brand:{hue}"]
    if second.startswith("#"):
        parts.append(f"--brand-2:{second}")
    if warm.startswith("#"):
        parts.append(f"--brand-warm:{warm}")
    return "<style>:root{" + ";".join(parts) + "}</style>"


def _worker_response(p):
    """A worker script the browser has to revalidate.

    Served by StaticFiles it carries no cache headers at all, so a browser
    is free to keep it on heuristic freshness — and a service worker that
    updates a day late is a fix that lands a day late for everyone already
    running the old one. It is one small file; asking every time is free.
    """
    return Response(p.read_bytes(), media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


_APP_JS_CACHE = {"stamp": None, "body": ""}


@app.get("/ops/app.js")
def ops_app_js():
    """The ops app, composed. The source lives as ordered part files in
    frontend/app/ — small enough to reason about, guarded against
    cross-file collisions by the suite — and the browser still loads ONE
    script at ONE url, so the service worker, the cache-buster and ten
    years of script tags need never learn the layout changed."""
    parts = sorted((config.FRONTEND_DIR / "app").glob("*.js"))
    stamp = tuple((p.name, p.stat().st_mtime_ns) for p in parts)
    if _APP_JS_CACHE["stamp"] != stamp:
        _APP_JS_CACHE["body"] = "\n".join(
            p.read_text(encoding="utf-8") for p in parts)
        _APP_JS_CACHE["stamp"] = stamp
    return PlainTextResponse(_APP_JS_CACHE["body"],
                             media_type="text/javascript")


def _pwa_on() -> bool:
    """The Progressive App is a CAPABILITY ($20, price book §3): the
    installable, offline-capable shell is what the row sells, so a tenant
    without it gets a perfectly good website that simply does not install.
    Null caps = everything, as everywhere."""
    caps = tenancy.caps_of(tenancy.CURRENT.get())
    return caps is None or "pwa" in caps


@app.get("/ops/sw.js")
def ops_worker():
    if not _pwa_on():
        raise HTTPException(404, "the Progressive App capability is not "
                                 "on this plan")
    return _worker_response(config.FRONTEND_DIR / "sw.js")


@app.get("/ops/manifest.webmanifest")
def ops_manifest_gate():
    if not _pwa_on():
        raise HTTPException(404, "the Progressive App capability is not "
                                 "on this plan")
    return FileResponse(config.FRONTEND_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sf-sw.js")
def store_worker():
    if not _pwa_on():
        raise HTTPException(404, "the Progressive App capability is not "
                                 "on this plan")
    return _worker_response(config.STOREFRONT_DIR / "sf-sw.js")




# ---------- the node dock: what a worker accepts from its provider ----------
# A worker process (BUSINESS_CONTROL_NODE=<id>) serves its tenants like any
# install, plus these — the receiving side of the fleet's shipments. Every
# call must present the node's key; a process with no key configured
# accepts nothing, so a plain install cannot be talked into hosting.

def _fleet_auth(request: Request) -> None:
    if not tenancy.NODE_KEY:
        raise HTTPException(404, "this process is not a fleet worker")
    if request.headers.get("X-Fleet-Key", "") != tenancy.NODE_KEY:
        raise HTTPException(403, "wrong fleet key")


@app.get("/api/node/ping")
def node_ping(request: Request):
    from . import fleet, services
    _fleet_auth(request)
    return {"ok": True, "node": tenancy.NODE_ID,
            "version": fleet.app_version(),
            "services": services.summary(),
            "tenants": tenancy.all_tenants()}


@app.post("/api/node/update")
async def node_update(request: Request):
    """Receive a code bundle, wear it, and restart. The response leaves
    first; then the process exits and systemd brings it back on the new
    code — the provider polls the ping until the version it pushed is the
    version that answers."""
    _fleet_auth(request)
    from . import fleet
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty bundle")
    try:
        version = fleet.apply_bundle(blob, config.APP_ROOT)
    except ValueError as e:
        raise HTTPException(400, str(e))
    import threading
    threading.Timer(1.0, lambda: os._exit(3)).start()
    return {"ok": True, "version": version, "restarting": True}


@app.get("/api/fleet/bundle")
def fleet_bundle(request: Request, con=Depends(get_con)):
    """The app as cargo — what a fresh node installs and an update ships.
    Authenticated by any booked node's key (the key IS the invitation to
    run this code), or by a signed-in admin."""
    from . import fleet
    key = request.headers.get("X-Fleet-Key", "")
    allowed = bool(key) and any(
        (n.get("key") or "") == key for n in fleet.nodes().values())
    if not allowed:
        tok = request.headers.get("Authorization", "")
        u = auth.user_for_token(con, tok.removeprefix("Bearer ").strip())
        allowed = bool(u and u["is_admin"])
    if not allowed:
        raise HTTPException(403, "a node key or an admin signs for the "
                                 "bundle")
    blob, version = fleet.build_bundle()
    from fastapi.responses import Response as _Resp
    return _Resp(blob, media_type="application/zip",
                 headers={"X-Bundle-Version": version})


@app.get("/fleet/install.sh")
def fleet_install_sh():
    """The node installer, as curl finds it. Public and generic on
    purpose: it carries no secrets — the node id and key travel only in
    the command the operator copies from the Platform tab."""
    from . import fleet
    from fastapi.responses import PlainTextResponse as _PT
    try:
        return _PT(fleet.install_script())
    except OSError:
        raise HTTPException(404, "this install ships without the script")


@app.post("/api/node/registry")
async def node_registry(request: Request):
    """The provider keeping this node's registry slice current — the
    tenant's hosts, status and caps, replaced whole because the provider
    is the source of truth and a worker has no competing opinion."""
    _fleet_auth(request)
    data = json.loads(await request.body() or b"{}")
    tenancy.merge_tenants(data.get("tenants") or {})
    return {"ok": True}


@app.post("/api/node/tenants/{tid}/import")
async def node_import(tid: str, request: Request):
    """Receive a tenant: unpack the shipment, give it schema, serve it."""
    _fleet_auth(request)
    from . import fleet
    if not tid.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad tenant id")
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty shipment")
    try:
        fleet.unpack_tenant(tid, blob)
    except (ValueError, Exception) as e:
        raise HTTPException(400, f"shipment refused: {str(e)[:200]}")
    if not (tenancy.tenant_dir(tid) / "business_control.db").exists():
        raise HTTPException(400, "shipment carried no database")
    if init_tenant:
        init_tenant(tid)          # idempotent — migrations run on arrival
    return {"ok": True, "tenant": tid, "node": tenancy.NODE_ID}


@app.get("/api/node/tenants/{tid}/usage")
def node_usage(tid: str, request: Request):
    """The client dossier's remote half: a worker answers for a tenant it
    hosts, through the same authenticated dock the backups pull from."""
    _fleet_auth(request)
    if tid not in tenancy.all_tenants():
        raise HTTPException(404, "this node does not hold that tenant")
    from storefront.backend import fleetadmin
    tok = tenancy.CURRENT.set(tid)
    try:
        con = db.connect()
        try:
            return fleetadmin._usage_from(con)
        finally:
            con.close()
    finally:
        tenancy.CURRENT.reset(tok)


@app.get("/api/node/tenants/{tid}/export")
def node_export(tid: str, request: Request):
    """Hand a tenant back — the recall's first half."""
    _fleet_auth(request)
    from . import fleet
    if tid not in tenancy.all_tenants() and not             tenancy.tenant_dir(tid).exists():
        raise HTTPException(404, f"'{tid}' is not on this node")
    from fastapi.responses import Response as RawResp
    return RawResp(content=fleet.pack_tenant(tid),
                   media_type="application/gzip")


@app.delete("/api/node/tenants/{tid}")
def node_delete(tid: str, request: Request):
    """Forget a tenant that was recalled or destroyed. Only ever called
    AFTER the provider holds (or has knowingly discarded) the data."""
    _fleet_auth(request)
    import shutil
    shutil.rmtree(tenancy.tenant_dir(tid), ignore_errors=True)
    tenancy.drop_tenant_entry(tid)
    return {"ok": True}


@app.get("/caddy/ask")
def caddy_ask(domain: str = ""):
    """Caddy's on-demand-TLS gate: may a certificate be issued for this name?

    200 = the registry answers to it (suspended included — the 503 page
    deserves TLS too); 404 = nobody here by that name, so no certificate.
    Without this gate, on-demand TLS would mint a cert for any hostname a
    stranger points at the box — a free resource-exhaustion lever and a
    reputation risk. Unauthenticated by design (Caddy calls it locally);
    it leaks exactly one bit.

    Caddyfile:  on_demand_tls { ask http://127.0.0.1:8860/caddy/ask }
    """
    name = (domain or "").split(":", 1)[0].lower().strip()
    if not name:
        raise HTTPException(404, "no domain asked about")
    try:
        tid = tenancy.resolve(name)
    except tenancy.Suspended:
        return {"ok": True, "suspended": True}
    except tenancy.UnknownHost:
        raise HTTPException(404, f"no tenant answers to '{name}'")
    if tid is None:
        # legacy single-shop install: no registry to consult — list your
        # domains in the Caddyfile directly rather than using on-demand.
        raise HTTPException(404, "tenancy is off — use explicit site blocks")
    return {"ok": True, "tenant": tid}


@app.get("/store.webmanifest")
def store_manifest(con=Depends(get_con)):
    """The installed app is named for the tenant's brand, not the demo's.

    A static manifest would put one brand's name on every tenant's home
    screen; this one reads the theme. The static file remains on disk as
    the shape reference only — this route shadows it (routes are matched
    before the catch-all static mount).
    """
    if not _pwa_on():
        raise HTTPException(404, "the Progressive App capability is not "
                                 "on this plan")
    t = store_api.get_theme(con)
    return JSONResponse({
        "name": t["brand"].title(), "short_name": t["brand"].title(),
        "description": t.get("description", ""),
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": t.get("bg", "#fdfdfd"),
        "theme_color": t.get("purple", "#6c00bf"),
        "icons": [{"src": "/ops/icons/icon-192.png", "sizes": "192x192",
                   "type": "image/png"},
                  {"src": "/ops/icons/icon-512.png", "sizes": "512x512",
                   "type": "image/png"}],
    }, media_type="application/manifest+json")


app.mount("/ops", StaticFiles(directory=config.FRONTEND_DIR, html=True),
          name="ops")


@app.get("/")
def index(con=Depends(get_con)):
    # The storefront home is composed from merchant-editable sections.
    return HTMLResponse(store_api.render_home(con))


app.mount("/", StaticFiles(directory=config.STOREFRONT_DIR), name="store")
