"""Blog, navigation menus, URL redirects, translations and currencies.

The growth surface: content that earns organic traffic, navigation the
merchant controls, redirects so migrating a store doesn't break inbound
links, and a translation/currency layer so the same storefront can serve
more than one market.
"""
import html as _html
import json
import time

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

# The shell's own chrome — header buttons, the side menu — was raw
# literals in index.html and never reached t(). These keys carry them,
# applied to data-i18n attributes at boot, so a Spanish visitor's menu is
# in Spanish and not only the product cards.
UI_KEYS.update({
    "nav_account": "My account", "nav_track": "Track my order",
    "nav_support": "Support", "nav_menu": "Menu",
    "side_learn": "Learn with us", "side_learning": "Learning",
    "side_learning_sub": "Your courses, lessons, quizzes and people",
    "side_nutrition": "Nutrition",
    "side_nutrition_sub": "Plan, prep and track — coach optional",
    "side_find": "Come find us", "side_stores": "Find a store",
    "side_stores_sub": "Shops that carry the range", "side_events": "Events",
    "side_events_sub": "Tastings, pop-ups and markets",
    "side_work": "Work with us", "side_account": "Your account",
    "side_signin": "Sign in", "side_signin_sub": "Customers and team — one door",
    "side_track": "Track an order", "side_track_sub": "Where your order is right now",
    "side_support": "Support",
    "side_support_sub": "Real humans, same system the team runs on",
    "side_a11y": "Accessibility & language",
    "side_a11y_sub": "Text size, contrast, region and currency",
    "close": "Close", "back": "Back", "continue": "Continue", "cancel": "Cancel",
    "quantity": "Quantity", "subtotal": "Subtotal", "shipping": "Shipping",
    "tax": "Tax", "order_placed": "Order placed", "sign_out": "Sign out",
})

# Languages a shop can offer. A code, a name in its own language, and
# which way it reads — the three things a picker and a page need. A
# merchant adds one on Store admin → Languages; translations for it are
# typed on the same screen. Direction is the one that is not guessable
# from a code, so it is stored, not derived.
LOCALE_DEFAULT = [{"code": "en", "label": "English", "dir": "ltr"}]
RTL = {"ar", "he", "fa", "ur", "ps", "sd", "ug", "yi", "dv"}
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


def i18n_settings(con) -> dict:
    """Which languages, which is the default, and whether a first visit
    follows the browser's language. Locales come from the setting when
    one is kept and from the translations table when it is not, so an
    install that translated before this setting existed keeps its picker."""
    row = con.execute("SELECT v FROM store_meta WHERE k='i18n'").fetchone()
    cfg = {}
    if row:
        try:
            cfg = json.loads(row["v"])
        except ValueError:
            cfg = {}
    locs = [dict(l) for l in cfg.get("locales") or [] if isinstance(l, dict) and l.get("code")]
    known = {l["code"] for l in locs}
    if "en" not in known:
        locs.insert(0, LOCALE_DEFAULT[0])
        known.add("en")
    for r in con.execute("SELECT DISTINCT locale FROM translations ORDER BY locale").fetchall():
        if r["locale"] not in known:
            locs.append({"code": r["locale"], "label": r["locale"].upper(),
                         "dir": "rtl" if r["locale"].split("-")[0] in RTL else "ltr"})
            known.add(r["locale"])
    for l in locs:
        l.setdefault("label", l["code"].upper())
        l["dir"] = "rtl" if l.get("dir") == "rtl" or (
            "dir" not in l and l["code"].split("-")[0] in RTL) else "ltr"
    default = cfg.get("default") if cfg.get("default") in known else "en"
    return {"locales": locs, "default": default,
            "auto_detect": bool(cfg.get("auto_detect", True))}


def locales(con) -> list:
    return [l["code"] for l in i18n_settings(con)["locales"]]


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
    i18n = i18n_settings(con)
    data = {"currencies": currencies(con), "locales": locales(con),
            "locale_info": i18n["locales"], "default_locale": i18n["default"],
            "auto_detect": i18n["auto_detect"],
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


def _day(ts: float) -> str:
    """The day a post went up, as a reader would say it.

    The column has been ordering the journal since it was made and was
    never once shown: a blog whose posts carry no date reads as a blog
    nobody has touched in years, which is the opposite of what an
    up-to-date one is for.
    """
    try:
        return time.strftime("%-d %B %Y", time.localtime(float(ts)))
    except Exception:                                        # noqa: BLE001
        return ""


def _iso(ts: float) -> str:
    """The same moment for machines."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(ts)))
    except Exception:                                        # noqa: BLE001
        return ""


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
            f'<span class="dim">{sect.esc(p["author"])}'
            f'{" · " + _day(p["published_at"]) if p["published_at"] else ""}'
            f'</span></div></a>'
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
    if p["published_at"]:
        # datePublished is what a search engine needs to show this as
        # anything other than undated, and the column has been sat on
        # since the table was made — sorted by, never said.
        ld["datePublished"] = _iso(p["published_at"])
    if img:
        ld["image"] = img
    hero = (f'<div class="post-hero"><img src="/media/m/{p["media_id"]}"'
            f' alt="{sect.esc(p["title"])}"></div>' if p["media_id"] else "")
    body = (f'<article class="section post">'
            f'<a class="dim" href="/blog">← Journal</a>'
            f'<h2>{sect.esc(p["title"])}</h2>'
            f'<p class="dim">{sect.esc(p["author"])}'
            f'{" · " + _day(p["published_at"]) if p["published_at"] else ""}'
            f'</p>{hero}'
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
    i18n = i18n_settings(con)
    return {"currencies": currencies(con), "locales": locales(con),
            "locale_info": i18n["locales"], "default_locale": i18n["default"],
            "auto_detect": i18n["auto_detect"],
            "ui": UI_KEYS,
            "strings": {loc: translations_for(con, loc)
                        for loc in locales(con) if loc != "en"}}


class I18nBody(BaseModel):
    locales: list = []
    default: str = "en"
    auto_detect: bool = True


@router.post("/api/store/admin/i18n")
def save_i18n(body: I18nBody, u=Depends(admin_user), con=Depends(get_con)):
    """The languages the shop offers. A code, a name in its own
    language, and which way it reads."""
    locs, seen = [], set()
    for l in body.locales:
        code = str(l.get("code", "")).strip().lower()[:8]
        if not code or code in seen:
            continue
        if not all(ch.isalnum() or ch == "-" for ch in code):
            raise HTTPException(400, f"'{code}' is not a language code (es, pt-br, zh-hant)")
        seen.add(code)
        locs.append({"code": code, "label": str(l.get("label", "")).strip()[:40] or code.upper(),
                     "dir": "rtl" if str(l.get("dir", "")) == "rtl" or (
                         "dir" not in l and code.split("-")[0] in RTL) else "ltr"})
    if "en" not in seen:
        locs.insert(0, LOCALE_DEFAULT[0]); seen.add("en")
    default = body.default.strip().lower()
    if default not in seen:
        raise HTTPException(400, "the default has to be one of the languages offered")
    con.execute("INSERT INTO store_meta(k,v) VALUES('i18n',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (json.dumps({"locales": locs, "default": default,
                             "auto_detect": body.auto_detect}),))
    con.commit()
    return {"ok": True, **i18n_settings(con)}


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
