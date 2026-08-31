"""Affiliate landing pages, public sign-up, and referral attribution.

The ERP already owned the affiliate *ledger* (codes, clicks, referrals,
commissions). This adds the acquisition surface: a public join page, a
per-affiliate landing page built on the same section engine as the rest of
the storefront, and an attribution window so a referral doesn't live forever.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from erp.backend import auth, db, notify
from .api import (admin_user, current_customer, get_con, get_theme,
                  page_rows, rate_limit, render_shell)
from . import sections as sect

router = APIRouter()


# The storefront sprite is already on the page; this just references it.
def _ic(name: str) -> str:
    return f'<svg class="ico-s" aria-hidden="true"><use href="#i-{name}"/></svg>'

MIGRATIONS = (
    "ALTER TABLE affiliates ADD COLUMN headline TEXT DEFAULT ''",
    "ALTER TABLE affiliates ADD COLUMN bio TEXT DEFAULT ''",
    "ALTER TABLE affiliates ADD COLUMN media_id INTEGER",
    "ALTER TABLE affiliates ADD COLUMN landing_enabled INTEGER DEFAULT 1",
    "ALTER TABLE affiliates ADD COLUMN landing_views INTEGER DEFAULT 0",
    "ALTER TABLE referrals ADD COLUMN code TEXT DEFAULT ''",
)

# How long a click keeps earning the affiliate credit.
DEFAULT_WINDOW_DAYS = 30


def init_tables(con):
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass


def window_days(cfg) -> int:
    try:
        return int(cfg.get("affiliate_window_days") or DEFAULT_WINDOW_DAYS)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS


def affiliate_by_code(con, code: str):
    return con.execute(
        "SELECT a.*, u.name FROM affiliates a JOIN users u ON u.id=a.user_id"
        " WHERE lower(a.code)=lower(?)", (code.strip(),)).fetchone()


# ---------- the tracked link ----------

@router.get("/r/{code}")
def referral_link(code: str, con=Depends(get_con)):
    """Counts the click, then sends the visitor to the affiliate's landing
    page when they have one, or straight to the shop when they don't."""
    a = affiliate_by_code(con, code)
    if a is None:
        return RedirectResponse("/")
    con.execute("UPDATE affiliates SET clicks=clicks+1 WHERE id=?",
                (a["id"],))
    con.commit()
    if a["landing_enabled"]:
        return RedirectResponse(f"/a/{a['code']}")
    return RedirectResponse(f"/?ref={a['code']}")


# ---------- the landing page ----------

def default_landing(con, a) -> str:
    """What an affiliate gets without customising anything: their name and
    pitch over the catalog, so a fresh code is useful immediately."""
    theme = get_theme(con)
    headline = a["headline"] or f"{a['name']}'s picks"
    bio = a["bio"] or (f"{a['name']} partners with {theme['brand']} — shop "
                       f"their favourites below.")
    photo = (f'<div class="aff-photo"><img src="/media/m/{a["media_id"]}"'
             f' alt="{sect.esc(a["name"])}"></div>' if a["media_id"] else "")
    return (
        f'<section class="hero" style="background:linear-gradient(135deg,'
        f'var(--purple),var(--lavender))">'
        f'<div class="hero-inner"><h1>{sect.esc(headline)}</h1>'
        f'<p>{sect.esc(bio)}</p>'
        f'<div class="hero-cta">'
        f'<a class="btn-pill primary" href="/#shop">Shop the collection</a>'
        f'</div></div></section>'
        f'{photo}'
        f'<section class="section" id="shop">'
        f'<div class="shop-head"><h2>Shop {sect.esc(a["name"])}\'s picks</h2>'
        f'<input id="search-input" type="search" placeholder="Search…">'
        f'</div>'
        f'<div class="collection-tabs" id="collection-tabs"></div>'
        f'<div class="grid" id="product-grid" data-collection=""'
        f' data-limit="0"></div></section>')


@router.get("/a/{code}")
def landing_page(code: str, con=Depends(get_con)):
    a = affiliate_by_code(con, code)
    if a is None or not a["landing_enabled"]:
        return RedirectResponse("/")
    con.execute("UPDATE affiliates SET landing_views=landing_views+1"
                " WHERE id=?", (a["id"],))
    con.commit()
    # A customised page (built in the theme editor) wins; else the default.
    rows = page_rows(con, f"affiliate:{a['code']}")
    body = (sect.render_page(con, rows) if rows else default_landing(con, a))
    theme = get_theme(con)
    html = render_shell(
        con, body,
        title=f"{a['headline'] or a['name']} — {theme['brand']}",
        description=a["bio"] or f"Shop {a['name']}'s picks at {theme['brand']}.")
    # Stamp attribution the moment the page loads, with an expiry.
    stamp = (
        f"<script>(function(){{var d={{code:'{a['code']}',"
        f"ts:Date.now()}};localStorage.setItem('sf_ref_v2',"
        f"JSON.stringify(d));localStorage.setItem('sf_ref','{a['code']}');"
        f"}})()</script>")
    return HTMLResponse(html.replace("</body>", stamp + "</body>"))


# ---------- public sign-up ----------

@router.get("/affiliates")
def affiliate_pitch(con=Depends(get_con)):
    from .partners import _require_cap
    _require_cap("affiliates")
    theme = get_theme(con)
    rate = 10
    row = con.execute("SELECT rate_bps FROM affiliates ORDER BY id LIMIT 1"
                      ).fetchone()
    if row:
        rate = row["rate_bps"] // 100
    # The whole pitch, in the order someone actually asks it: what is it,
    # what do I earn, how does it work, what do I get, then the form. The
    # rate is read from the programme rather than written in prose twice.
    body = (
        f'<section class="hero centred aff-hero">'
        f'<div class="hero-grid"><div class="hero-inner">'
        f'<span class="aff-eyebrow">Affiliate program</span>'
        f'<h1>Share the calm.<br>Earn on every can.</h1>'
        f'<p>Post it, link it, tell a friend. When someone orders through '
        f'your link you earn {rate}% — on that order and every reorder they '
        f'make in the next 30 days.</p>'
        f'<div class="hero-cta">'
        f'<a class="btn-pill primary" href="#join">Get my link'
        f'{sect.icon("arrow", "ico ico-sm")}</a>'
        f'<a class="btn-pill ghost" href="/#shop">See the range</a></div>'
        f'<div class="hero-note">'
        f'<span class="stat"><b>{rate}%</b>on every order</span>'
        f'<span class="stat"><b>30 days</b>cookie window</span>'
        f'<span class="stat"><b>$0</b>to join</span>'
        f'</div></div></div></section>'

        f'<section class="section"><h2>How it works</h2>'
        f'<div class="story-grid aff-steps">'
        f'<div class="story-card"><span class="aff-step">1</span>'
        f'<span class="ic">{_ic("link")}</span><b>Get your link</b>'
        f'<p>Enter your name below and it exists immediately — plus a landing '
        f'page with your name on it, if you want one.</p></div>'
        f'<div class="story-card"><span class="aff-step">2</span>'
        f'<span class="ic">{_ic("chat")}</span><b>Share it anywhere</b>'
        f'<p>Stories, bio, newsletter, group chat. Every click is counted, '
        f'wherever it came from.</p></div>'
        f'<div class="story-card"><span class="aff-step">3</span>'
        f'<span class="ic">{_ic("gift")}</span><b>Get paid</b>'
        f'<p>{rate}% of every order, tracked to the cent. Paid monthly once '
        f'you clear $25.</p></div>'
        f'</div></section>'

        f'<section class="section"><h2>What you get</h2>'
        f'<div class="story-grid">'
        f'<div class="story-card"><span class="ic">{_ic("chart")}</span>'
        f'<b>Live numbers</b><p>Clicks, orders and earnings as they happen — '
        f'not a monthly PDF.</p></div>'
        f'<div class="story-card"><span class="ic">{_ic("image")}</span>'
        f'<b>Assets that fit</b><p>Product shots, the film, and copy you can '
        f'paste. No design work required.</p></div>'
        f'<div class="story-card"><span class="ic">{_ic("shield")}</span>'
        f'<b>No lock-in</b><p>No exclusivity, no quotas, no minimum posts. '
        f'Leave whenever; your earned commission is still yours.</p></div>'
        f'</div></section>'

        f'<section class="section" id="join">'
        f'<div class="aff-join"><div class="aff-join-copy">'
        f'<h2>Join the program</h2>'
        f'<p>Tell us who you are and your link is ready immediately. '
        f'No application, no waiting.</p>'
        f'<ul class="aff-ticks">'
        f'<li>{sect.icon("check", "ico ico-sm")} Free, and free to leave</li>'
        f'<li>{sect.icon("check", "ico ico-sm")} Paid monthly over $25</li>'
        f'<li>{sect.icon("check", "ico ico-sm")} Your own landing page</li>'
        f'</ul></div>'
        f'<form id="aff-form" class="aff-form">'
        f'<label>Your name<input id="aff-name" placeholder="Alex Rivera" '
        f'required autocomplete="name"></label>'
        f'<label>Email<input id="aff-email" type="email" '
        f'placeholder="you@example.com" autocomplete="email"></label>'
        f'<button class="btn-pill primary" type="submit">Get my link'
        f'{sect.icon("arrow", "ico ico-sm")}</button>'
        f'<p class="aff-fine">We only email you about your link and your '
        f'earnings.</p>'
        f'</form></div>'
        f'<div id="aff-result"></div></section>')

    html = render_shell(
        con, body, title=f"Affiliate program — {theme['brand']}",
        description=f"Earn {rate}% sharing {theme['brand']}.")
    script = """<script>
document.getElementById('aff-form').onsubmit = async (e) => {
  e.preventDefault();
  const out = await (await fetch('/api/store/affiliate/join', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: document.getElementById('aff-name').value,
      email: document.getElementById('aff-email').value})})).json();
  const box = document.getElementById('aff-result');
  if (!out.ok) { box.innerHTML =
    '<p class="dim">' + (out.detail || 'could not join') + '</p>'; return; }
  localStorage.setItem('sf_support', JSON.stringify(
    {token: out.token, me: out.user_id}));
  box.innerHTML = '<p><b>You\\'re in!</b> Your link:</p>' +
    '<p style="user-select:all"><b>' + location.origin + out.link + '</b></p>' +
    '<p class="dim">Landing page: <a href="' + out.landing +
    '" style="color:inherit"><b>' + out.landing + '</b></a> · ' +
    'track earnings any time from My account.</p>';
};
</script>"""
    return HTMLResponse(html.replace("</body>", script + "</body>"))


class JoinBody(BaseModel):
    name: str
    email: str = ""


@router.post("/api/store/affiliate/join")
def public_join(body: JoinBody, con=Depends(get_con), _rl=Depends(rate_limit)):
    """Sign up from the storefront: finds or creates the account, enrols it
    in the program, and hands back the link. No admin involvement."""
    from erp.backend.main import CFG
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(400, "tell us your name")
    try:
        u = auth.login(con, name, "influencer", "", "", CFG, "")
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))
    if body.email.strip():
        con.execute("UPDATE users SET email=? WHERE id=?",
                    (body.email.strip(), u["id"]))
    a = con.execute("SELECT * FROM affiliates WHERE user_id=?",
                    (u["id"],)).fetchone()
    if a is None:
        code = f"{name.split()[0].lower()}{secrets.token_hex(2)}"
        code = "".join(ch for ch in code if ch.isalnum()) or secrets.token_hex(4)
        con.execute(
            "INSERT INTO affiliates(user_id,code,rate_bps,created_at)"
            " VALUES(?,?,?,?)",
            (u["id"], code, CFG.get("default_commission_bps", 1000), db.now()))
        con.commit()
        notify.push(con, f"New affiliate: {name} ({code})", kind="affiliate")
        a = con.execute("SELECT * FROM affiliates WHERE user_id=?",
                        (u["id"],)).fetchone()
    con.commit()
    return {"ok": True, "code": a["code"], "link": f"/r/{a['code']}",
            "landing": f"/a/{a['code']}", "token": u["token"],
            "user_id": u["id"],
            "rate_pct": a["rate_bps"] / 100}


@router.get("/api/store/affiliate/stats")
def my_affiliate(user=Depends(current_customer), con=Depends(get_con)):
    """Affiliate stats for the storefront's account panel."""
    a = con.execute("SELECT * FROM affiliates WHERE user_id=?",
                    (user["id"],)).fetchone()
    if a is None:
        return {"joined": False}
    agg = con.execute(
        "SELECT COUNT(*) orders, COALESCE(SUM(commission_cents),0) earned"
        " FROM referrals WHERE affiliate_id=?", (a["id"],)).fetchone()
    return {"joined": True, "code": a["code"], "rate_pct": a["rate_bps"] / 100,
            "clicks": a["clicks"], "landing_views": a["landing_views"],
            "orders": agg["orders"], "earned_cents": agg["earned"],
            "link": f"/r/{a['code']}", "landing": f"/a/{a['code']}"}


# ---------- admin ----------

class AffiliatePatch(BaseModel):
    headline: str | None = None
    bio: str | None = None
    media_id: int | None = None
    landing_enabled: bool | None = None
    rate_bps: int | None = None


@router.get("/api/store/admin/affiliates")
def list_affiliates(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT a.*, u.name, u.email,"
        " (SELECT COUNT(*) FROM referrals r WHERE r.affiliate_id=a.id) orders,"
        " (SELECT COALESCE(SUM(commission_cents),0) FROM referrals r"
        "  WHERE r.affiliate_id=a.id) earned"
        " FROM affiliates a JOIN users u ON u.id=a.user_id"
        " ORDER BY earned DESC, a.id DESC").fetchall()
    return [{**dict(r), "link": f"/r/{r['code']}",
             "landing": f"/a/{r['code']}"} for r in rows]


@router.post("/api/store/admin/affiliates/{aid}")
def patch_affiliate(aid: int, body: AffiliatePatch, u=Depends(admin_user),
                    con=Depends(get_con)):
    a = con.execute("SELECT * FROM affiliates WHERE id=?", (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such affiliate")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    sets = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE affiliates SET {sets} WHERE id=?",
                (*[int(v) if isinstance(v, bool) else v
                   for v in fields.values()], aid))
    con.commit()
    return {"ok": True, "updated": list(fields)}
