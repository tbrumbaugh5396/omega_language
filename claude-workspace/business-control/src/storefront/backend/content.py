"""Blog, navigation menus, URL redirects, translations and currencies.

The growth surface: content that earns organic traffic, navigation the
merchant controls, redirects so migrating a store doesn't break inbound
links, and a translation/currency layer so the same storefront can serve
more than one market.
"""
import html as _html
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from erp.backend import db
from .api import (admin_user, get_con, get_theme, page_rows, rate_limit,
                  render_shell, slugify)
from . import sections as sect

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS blog_posts (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  excerpt TEXT DEFAULT '',
  body TEXT DEFAULT '',                    -- simple HTML
  media_id INTEGER,
  author TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  published INTEGER DEFAULT 1,
  published_at REAL NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS store_menus (
  id INTEGER PRIMARY KEY,
  location TEXT NOT NULL DEFAULT 'header', -- header|footer
  label TEXT NOT NULL,
  url TEXT NOT NULL,
  position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS store_redirects (
  id INTEGER PRIMARY KEY,
  from_path TEXT UNIQUE NOT NULL,
  to_path TEXT NOT NULL,
  code INTEGER DEFAULT 301,
  hits INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS translations (
  locale TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (locale, key)
);
"""

# UI strings the storefront can translate. Product copy uses generated keys
# ("product:12:name"), so merchants translate catalog text the same way.
UI_KEYS = {
    "shop": "Shop", "reviews": "Reviews", "faq": "FAQ",
    "cart": "Your cart", "checkout": "Checkout →", "add_to_cart": "Add to cart",
    "search": "Search…", "account": "My account", "track": "Track my order",
    "support": "Support", "empty_cart": "Your cart is empty",
    "discount_code": "Discount code", "apply": "Apply", "total": "Total",
    "free_shipping_at": "free shipping at $40", "sold_out": "Sold out",
    # The shop's own invitation. It was "Shop your Zen", in the shared
    # storefront script, on every tenant's side menu and empty cart.
    "shop_cta": "Shop the range",
    # The first-visit offer's headline. It was "Take 10% off your first
    # calm." — in the shell, for every tenant.
    "offer_title": "Take 10% off your first order.",
    # A plan's button. "Add" is wrong for something that bills every month.
    "start_plan": "Start", "plans_heading": "Your plans",
    "no_plans": "Nothing running yet.",
    # The line over the cart. It was "breathe in, check out." — one brand's
    # breathing exercise in everyone's drawer.
    "cart_tag": "",
    # Under the checkout button. Shipped with an invented shipping policy
    # and box language; a policy line belongs to the tenant that has the
    # policy.
    "cart_note": "",
}

CURRENCY_DEFAULT = [
    {"code": "USD", "symbol": "$", "rate": 1.0},
    {"code": "EUR", "symbol": "€", "rate": 0.92},
    {"code": "GBP", "symbol": "£", "rate": 0.79},
    {"code": "CAD", "symbol": "C$", "rate": 1.36},
]


def init_tables(con):
    con.executescript(TABLES)
    # Root-relative, not bare fragments. The same nav renders on /blog and
    # /affiliates, where "#shop" is a fragment of a page that has no such
    # section — it silently does nothing. "/#shop" navigates home and then
    # scrolls, and still works as a same-page jump on the home page itself.
    if not con.execute("SELECT 1 FROM store_menus").fetchone():
        con.execute(
            "INSERT INTO store_menus(location,label,url,position) VALUES"
            " ('header','Shop','/#shop',0),('header','Reviews','/#reviews',1),"
            " ('header','FAQ','/#faq',2),('header','Blog','/blog',3),"
            " ('footer','Shop','/#shop',0),('footer','Blog','/blog',1),"
            " ('footer','FAQ','/#faq',2)")
    # Stores seeded before that fix keep their broken links otherwise.
    con.execute("UPDATE store_menus SET url='/'||url WHERE url LIKE '#%'")
    # The affiliate programme needs a way in; add it once, idempotently.
    if not con.execute("SELECT 1 FROM store_menus WHERE url='/affiliates'"
                       ).fetchone():
        con.execute(
            "INSERT INTO store_menus(location,label,url,position)"
            " VALUES('footer','Affiliates','/affiliates',5)")


def menus(con) -> dict:
    out = {"header": [], "footer": []}
    for r in con.execute(
            "SELECT * FROM store_menus ORDER BY location, position, id"
            ).fetchall():
        out.setdefault(r["location"], []).append(dict(r))
    return out


def currencies(con) -> list:
    row = con.execute("SELECT v FROM store_meta WHERE k='currencies'"
                      ).fetchone()
    if row:
        try:
            return json.loads(row["v"])
        except ValueError:
            pass
    return CURRENCY_DEFAULT


def locales(con) -> list:
    rows = con.execute("SELECT DISTINCT locale FROM translations"
                       " ORDER BY locale").fetchall()
    return ["en"] + [r["locale"] for r in rows if r["locale"] != "en"]


def translations_for(con, locale: str) -> dict:
    return {r["key"]: r["value"] for r in con.execute(
        "SELECT key, value FROM translations WHERE locale=?",
        (locale,)).fetchall()}


def ui_strings(con) -> dict:
    """The interface's own words, with this tenant's overrides on top.

    UI_KEYS is the shipped English. A merchant who calls it something else —
    or ships free over a different number — writes those keys to store_meta
    under 'ui_strings' rather than asking for a code change.
    """
    row = con.execute("SELECT v FROM store_meta WHERE k='ui_strings'"
                      ).fetchone()
    if not row:
        return UI_KEYS
    try:
        own = json.loads(row["v"])
    except ValueError:
        return UI_KEYS
    return {**UI_KEYS, **{k: v for k, v in own.items() if isinstance(v, str)}}


def i18n_payload(con) -> str:
    """Injected into every storefront page so the client can localise
    prices and UI strings without a second round trip."""
    from erp.backend.main import CFG
    from . import affiliates as aff
    from .api import get_theme
    data = {"currencies": currencies(con), "locales": locales(con),
            "ui": ui_strings(con),
            # Which stand-in art this shop draws — the client twin of
            # product_art(), reading the one switch rather than guessing.
            "art": get_theme(con).get("art") or "card",
            "regions": CFG.get("regions") or [],
            "affiliate_window_days": aff.window_days(CFG),
            "strings": {loc: translations_for(con, loc)
                        for loc in locales(con) if loc != "en"}}
    return (f"<script>window.STORE_I18N={json.dumps(data)};</script>")


# ---------- blog ----------

def post_json(r) -> dict:
    d = dict(r)
    d["url"] = f"/blog/{r['slug']}"
    return d


@router.get("/api/store/blog")
def list_posts(limit: int = 20, con=Depends(get_con)):
    return [post_json(r) for r in con.execute(
        "SELECT * FROM blog_posts WHERE published=1"
        " ORDER BY published_at DESC LIMIT ?", (min(limit, 50),)).fetchall()]


@router.get("/blog")
def blog_index(request: Request, con=Depends(get_con)):
    from .partners import _require_cap
    _require_cap("marketing")
    posts = con.execute(
        "SELECT * FROM blog_posts WHERE published=1"
        " ORDER BY published_at DESC LIMIT 50").fetchall()
    if posts:
        cards = "".join(
            f'<a class="post-card" href="/blog/{sect.esc(p["slug"])}">'
            + (f'<div class="post-art"><img src="/media/m/{p["media_id"]}/thumb"'
               f' alt="" loading="lazy"></div>' if p["media_id"] else "")
            + f'<div class="post-body"><b>{sect.esc(p["title"])}</b>'
            f'<p class="dim">{sect.esc(p["excerpt"])}</p>'
            f'<span class="dim">{sect.esc(p["author"])}</span></div></a>'
            for p in posts)
    else:
        cards = ('<p class="dim">No posts yet — write the first one in '
                 'Store admin → Blog.</p>')
    body = (f'<section class="section"><h2>Journal</h2>'
            f'<div class="post-grid">{cards}</div></section>')
    return HTMLResponse(render_shell(
        con, body, title=f"Journal — {get_theme(con)['brand']}",
        description="Stories, recipes and news."))


@router.get("/blog/{slug}")
def blog_post(slug: str, request: Request, con=Depends(get_con)):
    from .partners import _require_cap
    _require_cap("marketing")
    p = con.execute("SELECT * FROM blog_posts WHERE slug=? AND published=1",
                    (slug,)).fetchone()
    if p is None:
        raise HTTPException(404, "post not found")
    base = str(request.base_url).rstrip("/")
    img = f"{base}/media/m/{p['media_id']}" if p["media_id"] else ""
    ld = {"@context": "https://schema.org", "@type": "BlogPosting",
          "headline": p["title"], "description": p["excerpt"],
          "author": {"@type": "Person", "name": p["author"] or "Team"},
          "mainEntityOfPage": f"{base}/blog/{slug}"}
    if img:
        ld["image"] = img
    hero = (f'<div class="post-hero"><img src="/media/m/{p["media_id"]}"'
            f' alt="{sect.esc(p["title"])}"></div>' if p["media_id"] else "")
    body = (f'<article class="section post">'
            f'<a class="dim" href="/blog">← Journal</a>'
            f'<h2>{sect.esc(p["title"])}</h2>'
            f'<p class="dim">{sect.esc(p["author"])}</p>{hero}'
            f'<div class="post-content">{p["body"]}</div></article>'
            f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    if p["comments_on"]:
        rows = con.execute(
            "SELECT name, body, created_at FROM blog_comments"
            " WHERE post_id=? AND approved=1 ORDER BY id",
            (p["id"],)).fetchall()
        posted = "".join(
            f'<div class="cmt"><b>{sect.esc(r["name"])}</b>'
            f'<p>{sect.esc(r["body"])}</p></div>' for r in rows)
        body += (
            f'<section class="section comments"><h2>Comments</h2>'
            f'{posted or "<p class=dim>Be the first to comment.</p>"}'
            f'<form class="cmt-form" data-slug="{sect.esc(p["slug"])}">'
            f'<div class="cmt-row">'
            f'<label>Name<input name="name" required></label>'
            f'<label>Email <span class="dim">(not published)</span>'
            f'<input name="email" type="email"></label></div>'
            f'<label>Comment<textarea name="body" rows="3" required></textarea>'
            f'</label>'
            f'<button class="btn-pill primary" type="submit">Post comment</button>'
            f'<p class="cmt-msg"></p></form></section>')

    return HTMLResponse(render_shell(
        con, body, title=f"{p['title']} — {get_theme(con)['brand']}",
        description=p["excerpt"] or p["title"]))


class PostBody(BaseModel):
    slug: str = ""
    title: str
    excerpt: str = ""
    body: str = ""
    media_id: int | None = None
    author: str = ""
    tags: str = ""
    published: bool = True


@router.get("/api/store/admin/posts")
def admin_posts(u=Depends(admin_user), con=Depends(get_con)):
    return [post_json(r) for r in con.execute(
        "SELECT * FROM blog_posts ORDER BY id DESC").fetchall()]


@router.post("/api/store/admin/posts")
def save_post(body: PostBody, u=Depends(admin_user), con=Depends(get_con)):
    slug = slugify(body.slug or body.title)
    con.execute(
        "INSERT INTO blog_posts(slug,title,excerpt,body,media_id,author,tags,"
        " published,published_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(slug) DO UPDATE SET title=excluded.title,"
        " excerpt=excluded.excerpt, body=excluded.body,"
        " media_id=excluded.media_id, author=excluded.author,"
        " tags=excluded.tags, published=excluded.published",
        (slug, body.title.strip(), body.excerpt.strip(), body.body,
         body.media_id, body.author.strip(), body.tags.strip(),
         int(body.published), db.now(), db.now()))
    con.commit()
    return {"ok": True, "slug": slug, "url": f"/blog/{slug}"}


@router.delete("/api/store/admin/posts/{slug}")
def delete_post(slug: str, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM blog_posts WHERE slug=?", (slug,))
    con.commit()
    return {"ok": True}


# ---------- menus ----------

class MenuBody(BaseModel):
    location: str = "header"
    label: str
    url: str
    position: int = 0


@router.get("/api/store/admin/menus")
def admin_menus(u=Depends(admin_user), con=Depends(get_con)):
    return menus(con)


@router.post("/api/store/admin/menus")
def add_menu(body: MenuBody, u=Depends(admin_user), con=Depends(get_con)):
    if body.location not in ("header", "footer"):
        raise HTTPException(400, "location must be header or footer")
    con.execute(
        "INSERT INTO store_menus(location,label,url,position)"
        " VALUES(?,?,?,?)", (body.location, body.label.strip()[:40],
                             body.url.strip()[:200], body.position))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/menus/{mid}")
def delete_menu(mid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_menus WHERE id=?", (mid,))
    con.commit()
    return {"ok": True}


# ---------- redirects ----------

class RedirectBody(BaseModel):
    from_path: str
    to_path: str
    code: int = 301


@router.get("/api/store/admin/redirects")
def admin_redirects(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM store_redirects ORDER BY hits DESC, id DESC").fetchall()]


@router.post("/api/store/admin/redirects")
def add_redirect(body: RedirectBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    frm = "/" + body.from_path.strip().lstrip("/")
    if body.code not in (301, 302):
        raise HTTPException(400, "code must be 301 or 302")
    if frm in ("/", "/admin", "/ops"):
        raise HTTPException(400, "refusing to redirect a core route")
    con.execute(
        "INSERT INTO store_redirects(from_path,to_path,code,created_at)"
        " VALUES(?,?,?,?) ON CONFLICT(from_path) DO UPDATE SET"
        " to_path=excluded.to_path, code=excluded.code",
        (frm, body.to_path.strip(), body.code, db.now()))
    con.commit()
    return {"ok": True, "from_path": frm}


@router.delete("/api/store/admin/redirects/{rid}")
def delete_redirect(rid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_redirects WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


def find_redirect(con, path: str):
    r = con.execute("SELECT * FROM store_redirects WHERE from_path=?",
                    (path,)).fetchone()
    if r is None:
        return None
    con.execute("UPDATE store_redirects SET hits=hits+1 WHERE id=?", (r["id"],))
    con.commit()
    return RedirectResponse(r["to_path"], status_code=r["code"])


# ---------- i18n & currency ----------

@router.get("/api/store/i18n")
def get_i18n(con=Depends(get_con)):
    return {"currencies": currencies(con), "locales": locales(con),
            "ui": UI_KEYS,
            "strings": {loc: translations_for(con, loc)
                        for loc in locales(con) if loc != "en"}}


class TranslationBody(BaseModel):
    locale: str
    entries: dict


@router.post("/api/store/admin/translations")
def save_translations(body: TranslationBody, u=Depends(admin_user),
                      con=Depends(get_con)):
    loc = body.locale.strip().lower()[:8]
    if not loc or loc == "en":
        raise HTTPException(400, "pick a locale other than the base 'en'")
    for k, v in body.entries.items():
        if not str(v).strip():
            con.execute("DELETE FROM translations WHERE locale=? AND key=?",
                        (loc, k))
        else:
            con.execute(
                "INSERT INTO translations(locale,key,value) VALUES(?,?,?)"
                " ON CONFLICT(locale,key) DO UPDATE SET value=excluded.value",
                (loc, k, str(v)))
    con.commit()
    return {"ok": True, "locale": loc,
            "count": len(translations_for(con, loc))}


@router.get("/api/store/admin/translations/{locale}")
def read_translations(locale: str, u=Depends(admin_user),
                      con=Depends(get_con)):
    prods = con.execute(
        "SELECT id, name, description FROM products WHERE active=1").fetchall()
    keys = dict(UI_KEYS)
    for p in prods:
        keys[f"product:{p['id']}:name"] = p["name"]
        if p["description"]:
            keys[f"product:{p['id']}:description"] = p["description"]
    return {"locale": locale, "base": keys,
            "values": translations_for(con, locale)}


class CurrencyBody(BaseModel):
    currencies: list


@router.post("/api/store/admin/currencies")
def save_currencies(body: CurrencyBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    clean = [{"code": str(c.get("code", ""))[:4].upper(),
              "symbol": str(c.get("symbol", ""))[:3],
              "rate": float(c.get("rate", 1) or 1)}
             for c in body.currencies if c.get("code")]
    if not clean or clean[0]["rate"] != 1.0:
        raise HTTPException(400, "the first currency is the base and must "
                                 "have rate 1.0")
    con.execute("INSERT INTO store_meta(k,v) VALUES('currencies',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (json.dumps(clean),))
    con.commit()
    return {"ok": True, "currencies": clean}
