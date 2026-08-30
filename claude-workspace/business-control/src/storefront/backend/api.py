"""Storefront API — the face of the business, served from the same process.

The storefront never touches ERP tables directly except through this adapter:
swap these functions later to point at a different brain (or Shopify) without
touching the storefront UI. Public endpoints are unauthenticated; admin
endpoints reuse the ERP's bearer-token + is_admin gate.
"""
import hashlib
import hmac
import html as _html
import json
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               Response)
from pydantic import BaseModel

from erp.backend import auth, config, cycles, db
from . import sections as sect

try:  # real Liquid rendering when python-liquid is installed
    import liquid as _liquid
except ImportError:  # graceful: snippets render verbatim
    _liquid = None

router = APIRouter()


def render_liquid(src: str, con) -> str:
    """Render a Liquid snippet against the shop context (products,
    collections, shop, page come from the same adapter the UI uses)."""
    if not src.strip():
        return ""
    if _liquid is None:
        return src  # engine not installed — verbatim fallback
    prods = [dict(r) for r in con.execute(
        "SELECT id, sku, name, description, category, price_cents, image"
        " FROM products WHERE active=1 ORDER BY category, name").fetchall()]
    for p in prods:
        p["price"] = "$%.2f" % (p["price_cents"] / 100)
        p["url"] = "/#shop"
        p["image_url"] = f"/media/product/{p['id']}" if p["image"] else ""
    cols = [dict(r) for r in con.execute(
        "SELECT * FROM collections ORDER BY position, name").fetchall()]
    ctx = {"products": prods, "collections": cols,
           "shop": {"name": get_theme(con)["brand"].title(), "url": "/",
                    "currency": "USD"}}
    try:
        return _liquid.Template(src).render(**ctx)
    except Exception as e:  # template error → show it to the page author
        return (f'<pre style="color:#c01060;background:#fdf0f4;padding:12px;'
                f'border-radius:10px">Liquid error: {e}</pre>')

TABLES = """
CREATE TABLE IF NOT EXISTS store_subscribers (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  source TEXT DEFAULT 'storefront',        -- storefront|rewards|checkout
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS product_reviews (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  name TEXT DEFAULT 'Anonymous',
  rating INTEGER NOT NULL,                 -- 1..5
  body TEXT DEFAULT '',
  approved INTEGER DEFAULT 1,              -- simple moderation flag
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS store_pages (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  content_html TEXT DEFAULT '',
  content_css TEXT DEFAULT '',
  content_js TEXT DEFAULT '',
  liquid TEXT DEFAULT '',                  -- raw liquid/hydrogen snippet (rendered verbatim for now)
  published INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collections (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS collection_products (
  collection_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  PRIMARY KEY (collection_id, product_id)
);
CREATE TABLE IF NOT EXISTS store_discounts (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  pct INTEGER NOT NULL,
  active INTEGER DEFAULT 1,
  expires_at REAL DEFAULT 0                -- 0 = never
);
CREATE TABLE IF NOT EXISTS store_webhooks (
  id INTEGER PRIMARY KEY,
  event TEXT NOT NULL,                     -- order.created|subscriber.created|review.created
  url TEXT NOT NULL,
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS store_pageviews (
  id INTEGER PRIMARY KEY,
  visitor_id TEXT NOT NULL,
  page TEXT NOT NULL,                      -- home|/p/<slug>|product:<id>|cart|...
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS product_variants (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  name TEXT NOT NULL,                      -- "12-pack · Mango"
  option1 TEXT DEFAULT '',                 -- e.g. size
  option2 TEXT DEFAULT '',                 -- e.g. flavor
  sku TEXT DEFAULT '',
  price_cents INTEGER NOT NULL,
  stock INTEGER DEFAULT 0,
  position INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS store_shipping_methods (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  price_cents INTEGER NOT NULL,
  eta TEXT DEFAULT '',                     -- "3–5 business days"
  position INTEGER DEFAULT 0,             -- position 0 = standard (free-threshold applies)
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS store_meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
-- Merchandising facts the ERP has no opinion about: which flavour a SKU is,
-- its ring colour, tasting note, nutrition panel and ingredients. Kept beside
-- the catalog adapter rather than on `products` so swapping the catalog slot
-- for Shopify or another ERP doesn't take the storefront's copy with it.
CREATE TABLE IF NOT EXISTS store_product_meta (
  product_id INTEGER NOT NULL,
  k TEXT NOT NULL,                         -- flavour|colour|note|nutrition|ingredients|badge
  v TEXT DEFAULT '',
  PRIMARY KEY (product_id, k)
);
CREATE TABLE IF NOT EXISTS page_sections (
  id INTEGER PRIMARY KEY,
  page_slug TEXT NOT NULL,                 -- 'home' or a store_pages.slug
  type TEXT NOT NULL,                      -- sections.SECTION_TYPES key
  settings TEXT DEFAULT '{}',              -- JSON blob per the type's fields
  position INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS page_sections_slug
  ON page_sections(page_slug, position);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  key_hash TEXT UNIQUE NOT NULL,           -- sha256; the secret is shown once
  prefix TEXT NOT NULL,                    -- 'sk_live_ab12…' for the UI
  scopes TEXT DEFAULT '',                  -- comma list, '*' = everything
  active INTEGER DEFAULT 1,
  last_used_at REAL DEFAULT 0,
  calls INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS product_media (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'image',      -- image|video
  ext TEXT DEFAULT 'jpg',                  -- stored original extension
  video_url TEXT DEFAULT '',               -- external embed (YouTube/Vimeo/mp4)
  alt TEXT DEFAULT '',
  position INTEGER DEFAULT 0,              -- 0 = primary
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS product_media_pid
  ON product_media(product_id, position);
CREATE TABLE IF NOT EXISTS store_subscriptions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  variant_id INTEGER,
  qty INTEGER DEFAULT 1,
  status TEXT DEFAULT 'active',            -- active|skipped_next|paused|cancelled
  created_at REAL NOT NULL
);
"""

STORE_MIGRATIONS = (
    "ALTER TABLE product_reviews ADD COLUMN email TEXT DEFAULT ''",
    "ALTER TABLE product_reviews ADD COLUMN verified INTEGER DEFAULT 0",
)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "item"


def MEDIA_DIR():
    from erp.backend import tenancy
    return tenancy.data_dir() / "uploads" / "media"
IMAGE_MAGIC = {b"\xff\xd8": ("jpg", "image/jpeg"),
               b"\x89P": ("png", "image/png"),
               b"RI": ("webp", "image/webp"),
               b"GI": ("gif", "image/gif")}
VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}
# Derivatives: (suffix, max edge, quality) — generated when Pillow is present.
DERIVS = (("lg", 1400, 86), ("th", 420, 80))


def sniff_media(raw: bytes) -> tuple[str, str] | None:
    """Return (kind, ext) for recognised image/video bytes, else None."""
    if raw[:2] in IMAGE_MAGIC:
        return "image", IMAGE_MAGIC[raw[:2]][0]
    if raw[4:8] == b"ftyp":                      # mp4 / mov family
        return "video", "mov" if raw[8:12] == b"qt  " else "mp4"
    if raw[:4] == b"\x1a\x45\xdf\xa3":           # matroska / webm
        return "video", "webm"
    return None


def has_alpha(im) -> bool:
    """True if any pixel is actually see-through, not merely capable of it."""
    if im.mode == "P":
        im = im.convert("RGBA")
    if "A" not in im.getbands():
        return False
    lo, _ = im.getchannel("A").getextrema()
    return lo < 250


def make_derivatives(mid: int, ext: str) -> None:
    """Write _lg and _th beside the original. No-op without Pillow — the
    original is then served for every size (correct, just heavier).

    Cut-out product renders stay PNG. Flattening them onto white produced a
    JPEG with a white rectangle baked in, which is invisible on a white page
    and glaring the moment the art sits on a coloured background — as it now
    does on every carousel slide. Photographs still become JPEG, where the
    size saving is real and there is no transparency to lose.
    """
    try:
        from PIL import Image
    except ImportError:
        return
    src = MEDIA_DIR() / f"{mid}.{ext}"
    for suffix, edge, quality in DERIVS:
        try:
            with Image.open(src) as im:
                im.seek(0)                        # animated gif → first frame
                keep = has_alpha(im)
                im = im.convert("RGBA" if keep else "RGB")
                if keep:
                    # Trim to the opaque bounds. Product renders arrive with
                    # generous transparent margins — the can is often under
                    # 70% of its own file — and every layout that sizes the
                    # image ends up sizing the empty air around it instead.
                    # A tight derivative means "70% tall" means the can.
                    bbox = im.getchannel("A").getbbox()
                    if bbox:
                        im = im.crop(bbox)
                im.thumbnail((edge, edge), Image.LANCZOS)
                if keep:
                    im.save(MEDIA_DIR() / f"{mid}_{suffix}.png", "PNG",
                            optimize=True)
                else:
                    im.save(MEDIA_DIR() / f"{mid}_{suffix}.jpg", "JPEG",
                            quality=quality, optimize=True)
        except Exception:
            pass


# Derivatives are looked up in this order everywhere, so one helper decides
# it rather than three routes each guessing.
def derivative(mid: int, suffix: str, ext: str = ""):
    for cand in (MEDIA_DIR() / f"{mid}_{suffix}.png",
                 MEDIA_DIR() / f"{mid}_{suffix}.jpg"):
        if cand.exists():
            return cand
    orig = MEDIA_DIR() / f"{mid}.{ext}" if ext else None
    return orig if orig and orig.exists() else None


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
        ".gif": "image/gif"}


def media_json(rows) -> list[dict]:
    out = []
    for m in rows:
        d = dict(m)
        if d["kind"] == "video":
            d["url"] = d["video_url"] or f"/media/m/{d['id']}"
            d["thumb"] = f"/media/m/{d['id']}/thumb"
        else:
            d["url"] = f"/media/m/{d['id']}"
            d["thumb"] = f"/media/m/{d['id']}/thumb"
        out.append(d)
    return out


# Neutral on purpose: the default is what a FRESH tenant sees before any
# branding, and the brand belongs to the tenant's store_meta.theme, not to
# the codebase. (ZenJoy's values live in its own tenant's saved theme.)
THEME_DEFAULT = {
    "brand": "your brand", "dot": ".",
    "title": "Your Brand — online store",
    "description": "Shop the collection.",
    "purple": "#6c00bf", "lavender": "#8a77e1", "orange": "#ff6900",
    "ink": "#1b181f", "bg": "#fbf9f6",
    # Two faces, two jobs: `font` is the interface (buttons, prices, nav),
    # `display_font` is the brand voice (headlines only). Setting one face for
    # both is what made the old storefront read as cute.
    # A third face, and the one most often wrong: the wordmark. Quicksand
    # is round and soft — right for a drinks brand, wrong for most things.
    "font": "Inter", "display_font": "Fraunces", "wordmark_font": "Quicksand",
    "announce": ["Free shipping over $40"],
    "footer": "powered by business-control",
    # What stands in for a product with no photograph yet. "can" draws the
    # drinks can this storefront was born selling; "card" draws a neutral
    # panel. The default is neutral, because a business selling software or
    # services should not have to explain a soda can on its own shop.
    "art": "card",
}


def get_theme(con) -> dict:
    row = con.execute("SELECT v FROM store_meta WHERE k='theme'").fetchone()
    saved = {}
    if row:
        try:
            saved = json.loads(row["v"])
        except ValueError:
            saved = {}
    return {**THEME_DEFAULT, **saved}


def theme_css(t: dict) -> str:
    """Emit tokens only. store.css owns the rules — the theme just rebinds the
    variables, so a colour change can't fight the stylesheet's cascade."""
    disp = t.get("display_font") or THEME_DEFAULT["display_font"]
    mark = t.get("wordmark_font") or THEME_DEFAULT["wordmark_font"]
    return (f":root{{--purple:{t['purple']};--lavender:{t['lavender']};"
            f"--orange:{t['orange']};--ink:{t['ink']};--bg:{t['bg']};"
            f"--ui:'{t['font']}',system-ui,sans-serif;"
            f"--display:'{disp}',Georgia,serif;"
            f"--wordmark:'{mark}',var(--ui);}}")


def font_link(t: dict) -> str:
    """Load the two faces the theme actually asks for.

    The shell used to hard-code three families, so a tenant could set a
    typeface and get a fallback — the theme changed and the page did not.
    """
    fams, seen = [], set()
    for face in (t.get("font"), t.get("display_font"),
                 t.get("wordmark_font")):
        name = re.sub(r"[^A-Za-z0-9 ]", "", (face or "")).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            fams.append(f"family={name.replace(' ', '+')}:wght@400;500;600;700")
    if not fams:
        return FONT_LINK
    return ('<link rel="preconnect" href="https://fonts.gstatic.com" '
            'crossorigin><link rel="stylesheet" '
            'href="https://fonts.googleapis.com/css2?'
            + "&".join(fams) + '&display=swap">')


FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;'
    '500;600;700&family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@'
    '9..144,400;9..144,600;9..144,700&display=swap" rel="stylesheet">')


def icon_sprite() -> str:
    """The shared SVG symbol sheet. One file, injected into every document, so
    the storefront and the server-rendered product page can't drift apart."""
    try:
        return (config.STOREFRONT_DIR / "icons.svg").read_text(encoding="utf-8")
    except OSError:
        return ""


def card_svg(pid: int, name: str, colour: str, key: str = "",
             mini: bool = False, brand: str = "") -> str:
    """The neutral stand-in: a panel carrying the brand's ring mark and the
    product's name. What a plan, a licence or a service looks like before
    anybody has photographed it — which is to say, before it looks like
    anything at all."""
    c = colour or "#6c00bf"
    gid = f"pk{pid}{key}"
    # A wordmark is as long as the business's name. Fitting it to the panel
    # beats picking one size and letting "BUSINESS CONTROL" run off both
    # edges of it.
    mark = (brand or "").upper()
    size = min(14, max(8, int(150 / max(len(mark), 1) * 1.35)))
    cap = "" if mini else (
        f'<text x="100" y="78" text-anchor="middle" fill="#fff"'
        f' font-size="{size}" font-weight="700" letter-spacing=".8"'
        f' opacity=".85" aria-hidden="true">{_html.escape(mark)}</text>')
    return (
        f'<svg class="can card-art" viewBox="0 0 200 320" role="img"'
        f' aria-label="{_html.escape(name or "")}">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c}" stop-opacity=".95"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity=".70"/>'
        f'</linearGradient></defs>'
        f'<ellipse cx="100" cy="296" rx="62" ry="6" fill="rgba(27,24,31,.10)"/>'
        f'<rect x="22" y="40" width="156" height="240" rx="18"'
        f' fill="url(#{gid})"/>'
        f'<g fill="none" stroke="#fff" opacity=".85">'
        f'<circle cx="100" cy="152" r="12" stroke-width="7"/>'
        f'<circle cx="100" cy="152" r="30" stroke-width="5" opacity=".72"/>'
        f'<circle cx="100" cy="152" r="50" stroke-width="3.4" opacity=".46"/>'
        f'</g>'
        f'<rect x="22" y="40" width="156" height="240" rx="18" fill="none"'
        f' stroke="rgba(27,24,31,.10)"/>{cap}</svg>')


def product_art(theme: dict, pid: int, name: str, colour: str, key: str = "",
                mini: bool = False, brand: str = "") -> str:
    """Which stand-in this tenant draws — one switch, read from the theme,
    so the storefront grid and the server-rendered product page agree."""
    fn = can_svg if (theme or {}).get("art") == "can" else card_svg
    return fn(pid, name, colour, key, mini, brand)


def can_svg(pid: int, name: str, colour: str, key: str = "",
            mini: bool = False, brand: str = "") -> str:
    """Server-side twin of canSVG() in store.js — the drawn can that stands in
    until real photography exists. Both draw the brand's ring grammar, so the
    product page and the grid show the same thing."""
    c = colour or "#6c00bf"
    gid = f"pc{pid}{key}"
    label = _html.escape((name or "").split(" —")[0])
    return f"""<svg class="can" viewBox="0 0 200 320" role="img"
 aria-label="{_html.escape(name or '')} can">
 <defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">
 <stop offset="0" stop-color="{c}" stop-opacity=".95"/>
 <stop offset="1" stop-color="{c}" stop-opacity=".72"/></linearGradient>
 <clipPath id="{gid}c"><rect x="40" y="26" width="120" height="268" rx="26"/></clipPath></defs>
 <ellipse cx="100" cy="300" rx="52" ry="7" fill="rgba(27,24,31,.13)"/>
 <rect x="40" y="26" width="120" height="268" rx="26" fill="url(#{gid})"/>
 <g clip-path="url(#{gid}c)" fill="none" stroke="#fff">
 <circle cx="100" cy="182" r="10" stroke-width="6" opacity=".95"/>
 <circle cx="100" cy="182" r="26" stroke-width="4.6" opacity=".8"/>
 <circle cx="100" cy="182" r="44" stroke-width="3.4" opacity=".6"/>
 <circle cx="100" cy="182" r="63" stroke-width="2.4" opacity=".42"/>
 <circle cx="100" cy="182" r="83" stroke-width="1.8" opacity=".26"/></g>
 <rect x="40" y="26" width="120" height="268" rx="26" fill="none"
 stroke="rgba(27,24,31,.10)"/>
 <path d="M52 32h96" stroke="rgba(255,255,255,.55)" stroke-width="7"
 stroke-linecap="round"/>
 <ellipse cx="100" cy="26" rx="60" ry="9" fill="#d9d4dd"/>
 <ellipse cx="100" cy="24" rx="52" ry="7" fill="#eceaef"/>
 {"" if mini else f'''<text x="100" y="92" text-anchor="middle" fill="#fff"
 font-size="21" font-family="Quicksand, sans-serif" font-weight="700"
 letter-spacing="-.5" aria-hidden="true">{_html.escape(brand or "")}<tspan fill="#ffd9b8">.</tspan></text>
 <text x="100" y="266" text-anchor="middle" fill="#fff" font-size="13"
 font-family="Inter, sans-serif" font-weight="600" opacity=".95"
 aria-hidden="true">{label}</text>'''}
</svg>"""


def product_meta(con, pid: int) -> dict:
    return {r["k"]: r["v"] for r in con.execute(
        "SELECT k, v FROM store_product_meta WHERE product_id=?",
        (pid,)).fetchall()}


def asset_version() -> str:
    """Newest mtime across every storefront script and stylesheet.

    Without this a deploy leaves people on the previous CSS/JS until they
    hard-reload. The service worker is network-first, so the stale copy
    doesn't come from the SW — it comes from ordinary HTTP caching, where a
    file served with no explicit Cache-Control gets a heuristic freshness
    lifetime and isn't revalidated at all.

    It used to list three filenames, which meant a change to admin.js or a
    shared script didn't move the version and the back office kept running
    yesterday's code. Globbing is the fix: a new asset is covered the day
    it's added rather than the day someone remembers this function.
    """
    newest = 0.0
    for pattern in ("*.js", "*.css", "*.html"):
        for f in config.STOREFRONT_DIR.glob(pattern):
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return str(int(newest))


def pixels_snippet(con) -> str:
    from . import pixels as _px
    try:
        return _px.snippet(_px.get_config(con))
    except Exception:          # a bad pixel config must never break the shop
        return ""


def render_shell(con, body_html: str, *, title=None, description=None,
                 head_extra: str = "") -> str:
    """Wrap rendered sections in the storefront shell (nav, cart, modals).

    `head_extra` is for what only one page can know — a canonical URL, its
    own structured data, the flavour colour it recolours itself with. It is
    composed by the caller and inserted verbatim, so nothing page-specific
    has to leak into the shell.
    """
    from . import content as content_mod
    t = get_theme(con)
    shell = (config.STOREFRONT_DIR / "index.html").read_text(encoding="utf-8")
    v = asset_version()
    for asset in ("/store.css", "/store.js", "/qr-scan.js", "/qr-scan.css"):
        shell = shell.replace(f'"{asset}"', f'"{asset}?v={v}"')
    announce = "".join(f"<span>{sect.esc(a)}</span>"
                       for a in (t.get("announce") or []) * 2)
    nav = content_mod.menus(con)
    repl = {
        "<!--NAV-->": "".join(
            f'<a href="{sect.esc(m["url"])}">{sect.esc(m["label"])}</a>'
            for m in nav.get("header", [])),
        "<!--FOOTNAV-->": "".join(
            f'<a href="{sect.esc(m["url"])}">{sect.esc(m["label"])}</a>'
            for m in nav.get("footer", [])),
        "<!--I18N-->": content_mod.i18n_payload(con),
        "<!--ICONS-->": icon_sprite(),
        "<!--SECTIONS-->": body_html,
        "<!--ANNOUNCE-->": announce,
        "<!--THEME-CSS-->": f"<style>{theme_css(t)}</style>",
        "<!--PIXELS-->": pixels_snippet(con),
        "<!--BRAND-->": (f'{sect.esc(t["brand"])}'
                         f'<span class="brand-dot">{sect.esc(t["dot"])}</span>'),
        "<!--TITLE-->": sect.esc(title or t["title"]),
        "<!--DESCRIPTION-->": sect.esc(description or t["description"]),
        "<!--FOOTER-->": sect.esc(t["footer"]),
        "<!--FONTS-->": font_link(t),
        "<!--OFFER-TITLE-->": sect.esc(
            content_mod.ui_strings(con).get("offer_title", "")),
        "<!--HEAD-EXTRA-->": head_extra,
    }
    for k, v in repl.items():
        shell = shell.replace(k, v)
    return shell


def page_rows(con, slug: str):
    return con.execute(
        "SELECT * FROM page_sections WHERE page_slug=? ORDER BY position, id",
        (slug,)).fetchall()


def primary_media_file(con, product_id: int):
    """Best on-disk image for a product (used by the legacy ERP art route)."""
    row = con.execute(
        "SELECT id, ext FROM product_media WHERE product_id=? AND kind='image'"
        " ORDER BY position, id LIMIT 1", (product_id,)).fetchone()
    if row is None:
        return None
    return derivative(row["id"], "lg", row["ext"])


def ensure_search_index(con, force_rebuild: bool = False) -> bool:
    """Standalone FTS5 index over products, kept in sync by triggers.

    Deliberately *not* an external-content table: those require every trigger
    'delete' to replay the exact indexed values, and any drift makes SQLite
    report the whole database as malformed on the next write to products.
    A standalone index costs a little disk and cannot desync that way.
    Returns True when a usable index exists."""
    try:
        if force_rebuild:
            for t in ("products_fts_ai", "products_fts_ad", "products_fts_au"):
                con.execute(f"DROP TRIGGER IF EXISTS {t}")
            con.execute("DROP TABLE IF EXISTS products_fts")
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS products_fts"
                    " USING fts5(name, description, category)")
        con.executescript("""
CREATE TRIGGER IF NOT EXISTS products_fts_ai AFTER INSERT ON products BEGIN
  INSERT INTO products_fts(rowid,name,description,category)
  VALUES (new.id,new.name,new.description,new.category); END;
CREATE TRIGGER IF NOT EXISTS products_fts_ad AFTER DELETE ON products BEGIN
  DELETE FROM products_fts WHERE rowid=old.id; END;
CREATE TRIGGER IF NOT EXISTS products_fts_au AFTER UPDATE ON products BEGIN
  DELETE FROM products_fts WHERE rowid=new.id;
  INSERT INTO products_fts(rowid,name,description,category)
  VALUES (new.id,new.name,new.description,new.category); END;""")
        if force_rebuild or not con.execute(
                "SELECT 1 FROM products_fts LIMIT 1").fetchone():
            con.execute("DELETE FROM products_fts")
            con.execute(
                "INSERT INTO products_fts(rowid,name,description,category)"
                " SELECT id,name,description,category FROM products")
        con.commit()
        return True
    except sqlite3.Error:
        return False       # FTS5 unavailable — search falls back to LIKE


def init_tables():
    con = db.connect()
    try:
        con.executescript(TABLES)
        for stmt in STORE_MIGRATIONS:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
        if not con.execute("SELECT v FROM store_meta WHERE k='webhook_secret'"
                           ).fetchone():
            con.execute("INSERT INTO store_meta VALUES('webhook_secret',?)",
                        (secrets.token_urlsafe(32),))
        # Seed the home page from the shipped design so the theme editor
        # opens on the real layout instead of an empty canvas.
        if not con.execute("SELECT 1 FROM page_sections WHERE page_slug='home'"
                           ).fetchone():
            for pos, stype in enumerate(sect.HOME_DEFAULT):
                con.execute(
                    "INSERT INTO page_sections(page_slug,type,settings,"
                    " position) VALUES('home',?,?,?)",
                    (stype, json.dumps(sect.defaults_for(stype)), pos))
        # A store seeded before the showcase existed keeps its own layout —
        # HOME_DEFAULT only ever runs on an empty page. Sections added to
        # the design later have to be placed on the page that already
        # exists, and each lands EXACTLY ONCE: the applied list is written
        # to store_meta, because "is the type absent?" is not the same
        # question as "has this ever run?" — a merchant who deleted the
        # carousel on purpose used to find it back on the next restart,
        # forever.
        else:
            row = con.execute("SELECT v FROM store_meta WHERE"
                              " k='home_backfill'").fetchone()
            try:
                done = set(json.loads(row["v"])) if row else set()
            except ValueError:
                done = set()
            for stype, under in (("showcase", None), ("social_proof",
                                                      "showcase")):
                if stype in done:
                    continue
                done.add(stype)
                if con.execute("SELECT 1 FROM page_sections WHERE"
                               " page_slug='home' AND type=?",
                               (stype,)).fetchone():
                    continue
                if under is None:
                    pos = 0
                else:
                    r2 = con.execute(
                        "SELECT position FROM page_sections WHERE"
                        " page_slug='home' AND type=?", (under,)).fetchone()
                    pos = (r2["position"] + 1) if r2 else 0
                con.execute("UPDATE page_sections SET position=position+1"
                            " WHERE page_slug='home' AND position>=?", (pos,))
                con.execute(
                    "INSERT INTO page_sections(page_slug,type,settings,"
                    " position) VALUES('home',?,?,?)",
                    (stype, json.dumps(sect.defaults_for(stype)), pos))
            con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                        " VALUES('home_backfill',?)",
                        (json.dumps(sorted(done)),))
        if not con.execute("SELECT 1 FROM store_shipping_methods").fetchone():
            con.execute(
                "INSERT INTO store_shipping_methods(name,price_cents,eta,"
                " position) VALUES ('Standard',599,'3–5 business days',0),"
                " ('Express',1499,'1–2 business days',1)")
        from . import (affiliates, campaigns, content, crud, discord,
                       documents, emailer, engagements, governance,
                       partners, pixels, promos, support)
        promos.init_tables(con)
        content.init_tables(con)
        governance.init_tables(con)
        affiliates.init_tables(con)
        partners.init_tables(con)
        pixels.init_tables(con)
        support.init_tables(con)
        campaigns.init_tables(con)
        documents.init_tables(con)
        engagements.init_tables(con)
        crud.init_tables(con)
        discord.init_tables(con)
        emailer.init_tables(con)
        ensure_search_index(con)
        # Self-heal: a stale index from an older build makes any write to
        # products fail. Probe with a rolled-back no-op and rebuild if needed.
        try:
            con.execute("BEGIN")
            con.execute("UPDATE products SET image=image WHERE id="
                        "(SELECT id FROM products LIMIT 1)")
            con.execute("ROLLBACK")
        except sqlite3.Error:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            ensure_search_index(con, force_rebuild=True)
        con.commit()
    finally:
        con.close()


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def admin_user(request: Request, authorization: str = Header(default=""),
               con=Depends(get_con)):
    """The single gate for every store-admin request: authenticates, applies
    staff permissions, and records mutations in the audit log."""
    from . import governance
    token = authorization.removeprefix("Bearer ").strip()
    user = auth.user_for_token(con, token)
    if user is None:
        raise HTTPException(403, "admin only")
    perms = governance.granted(user)
    if not user["is_admin"] and not perms:
        raise HTTPException(403, "admin only")
    governance.check(user, request.url.path)
    # No audit call here any more: the middleware records every mutating
    # request, so this one only produced a second row saying the same thing.
    return user


# Simple in-memory rate limit for public write endpoints: N hits per IP+path
# per minute. Single-process, resets on restart — an abuse brake, not a WAF.
_HITS: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request):
    from erp.backend import tenancy
    key = (f"{tenancy.CURRENT.get()}:"
           f"{request.client.host if request.client else '?'}:"
           f"{request.url.path}")
    now = time.monotonic()
    dq = _HITS[key]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= 20:
        raise HTTPException(429, "slow down — try again in a minute")
    dq.append(now)


def fire_webhooks(event: str, payload: dict):
    """Announce a business event to everything listening.

    HTTP webhooks, Discord and the integrations all watch the same events,
    and they are fanned out from here rather than from each emitter — so a
    new place that raises an event reaches all of them, and a new listener
    reaches every existing event, without either having to know about the
    other. (The docstring used to sit below the Discord call, where Python
    treated it as a stray expression rather than documentation.)

    Webhook bodies are HMAC-SHA256 signed (X-Store-Signature) with the
    store's webhook secret so receivers can verify authenticity.
    """
    for fan in (_fan_discord, _fan_integrations):
        try:
            fan(event, payload)
        except Exception:
            pass          # a listener must never break the thing it heard


def _fan_discord(event: str, payload: dict) -> None:
    from . import discord as _dc
    _dc.emit(event, payload)


def _fan_integrations(event: str, payload: dict) -> None:
    from erp.backend import integrations as _ig
    _ig.emit(event, payload)
    con = db.connect()
    try:
        hooks = con.execute(
            "SELECT url FROM store_webhooks WHERE event=? AND active=1",
            (event,)).fetchall()
        secret = con.execute(
            "SELECT v FROM store_meta WHERE k='webhook_secret'").fetchone()
    finally:
        con.close()
    body = json.dumps({"event": event, "data": payload}).encode()
    sig = hmac.new((secret["v"] if secret else "").encode(), body,
                   hashlib.sha256).hexdigest()

    def send(url):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json",
                         "X-Store-Signature": f"sha256={sig}"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
    for h in hooks:
        from erp.backend import tenancy
        threading.Thread(target=tenancy.with_tenant(
            tenancy.CURRENT.get(), send), args=(h["url"],),
            daemon=True).start()


# ---------- public: catalog, promos, discounts ----------

@router.get("/api/store/catalog")
def catalog(con=Depends(get_con)):
    prods = [dict(r) for r in con.execute(
        "SELECT id, sku, name, description, category, price_cents, image"
        " FROM products WHERE active=1 ORDER BY category, name").fetchall()]
    cols = [dict(r) for r in con.execute(
        "SELECT * FROM collections ORDER BY position, name").fetchall()]
    members = con.execute("SELECT * FROM collection_products").fetchall()
    by_col = {}
    for m in members:
        by_col.setdefault(m["collection_id"], []).append(m["product_id"])
    for c in cols:
        c["product_ids"] = by_col.get(c["id"], [])
    reviews = {r["product_id"]: dict(r) for r in con.execute(
        "SELECT product_id, COUNT(*) n, AVG(rating) avg FROM product_reviews"
        " WHERE approved=1 GROUP BY product_id").fetchall()}
    variants = {}
    for v in con.execute(
            "SELECT * FROM product_variants WHERE active=1"
            " ORDER BY position, id").fetchall():
        variants.setdefault(v["product_id"], []).append(dict(v))
    media = {}
    for m in media_json(con.execute(
            "SELECT * FROM product_media ORDER BY position, id").fetchall()):
        media.setdefault(m["product_id"], []).append(m)
    meta: dict[int, dict] = {}
    for m in con.execute("SELECT * FROM store_product_meta").fetchall():
        meta.setdefault(m["product_id"], {})[m["k"]] = m["v"]
    for p in prods:
        rv = reviews.get(p["id"])
        p["review_count"] = rv["n"] if rv else 0
        p["review_avg"] = round(rv["avg"], 1) if rv else None
        p["variants"] = variants.get(p["id"], [])
        p["media"] = media.get(p["id"], [])
        p["slug"] = slugify(p["name"])
        md = meta.get(p["id"], {})
        p["flavour"] = md.get("flavour", "")
        p["colour"] = md.get("colour", "")
        # The one the hero puts on stage. Without it the hero shows
        # whatever happens to sort first, which for a shop selling plans
        # was the cheapest support plan in grey.
        p["featured"] = md.get("featured", "") == "1"
        p["note"] = md.get("note", "")
        p["ingredients"] = md.get("ingredients", "")
        p["badge"] = md.get("badge", "")
        try:
            p["nutrition"] = json.loads(md.get("nutrition") or "{}")
        except ValueError:
            p["nutrition"] = {}
    return {"products": prods, "collections": cols}


@router.get("/media/m/{mid}")
def media_file(mid: int, con=Depends(get_con)):
    m = con.execute("SELECT * FROM product_media WHERE id=?", (mid,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such media")
    if m["kind"] == "video":
        f = MEDIA_DIR() / f"{mid}.{m['ext']}"
        if not f.exists():
            raise HTTPException(404, "video is an external embed")
        return FileResponse(f, media_type=VIDEO_MIME.get(m["ext"], "video/mp4"))
    f = derivative(mid, "lg", m["ext"])
    if f is None:
        raise HTTPException(404, "file missing")
    return FileResponse(f, media_type=MIME.get(f.suffix, "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=31536000"})


@router.get("/media/m/{mid}/thumb")
def media_thumb(mid: int, con=Depends(get_con)):
    m = con.execute("SELECT * FROM product_media WHERE id=?", (mid,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such media")
    th = derivative(mid, "th")
    if th is not None:
        return FileResponse(th, media_type=MIME.get(th.suffix, "image/jpeg"),
                            headers={"Cache-Control": "public, max-age=31536000"})
    orig = MEDIA_DIR() / f"{mid}.{m['ext']}"
    if m["kind"] == "image" and orig.exists():
        return FileResponse(orig,
                            headers={"Cache-Control": "public, max-age=31536000"})
    # Video (embed or un-posterable upload): borrow the product's primary
    # image, else a self-contained film-strip placeholder. Never a 404, so
    # galleries and cards can point here unconditionally.
    sib = primary_media_file(con, m["product_id"])
    if sib is not None:
        return FileResponse(sib, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
    return Response(
        content='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                '<rect width="64" height="64" rx="10" fill="#ebe1f5"/>'
                '<polygon points="26,20 46,32 26,44" fill="#6c00bf"/></svg>',
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/store/search")
def search(q: str = "", con=Depends(get_con)):
    q = q.strip()
    if not q:
        return []
    safe = re.sub(r"[^\w\s]", " ", q).strip()
    rows = []
    if safe:
        try:
            rows = con.execute(
                "SELECT p.id, p.name, p.description, p.category,"
                " p.price_cents, p.image FROM products_fts f"
                " JOIN products p ON p.id=f.rowid"
                " WHERE products_fts MATCH ? AND p.active=1 LIMIT 30",
                (" ".join(t + "*" for t in safe.split()),)).fetchall()
        except sqlite3.Error:
            rows = []
    if not rows:  # FTS missing or no match — LIKE fallback
        like = f"%{q}%"
        rows = con.execute(
            "SELECT id, name, description, category, price_cents, image"
            " FROM products WHERE active=1 AND (name LIKE ? OR"
            " description LIKE ? OR category LIKE ?) LIMIT 30",
            (like, like, like)).fetchall()
    out = [dict(r) for r in rows]
    for p in out:
        p["slug"] = slugify(p["name"])
    return out


@router.get("/api/store/shipping")
def shipping_methods(con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM store_shipping_methods WHERE active=1"
        " ORDER BY position, id").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/store/promos")
def active_promos(con=Depends(get_con)):
    rows = con.execute(
        "SELECT id, kind, name, body, product_id, discount_pct, starts"
        " FROM promos WHERE active=1 AND kind='promo'"
        " ORDER BY id DESC LIMIT 6").fetchall()
    return [dict(r) for r in rows]


class DiscountBody(BaseModel):
    code: str


@router.post("/api/store/discount/validate")
def validate_discount(body: DiscountBody, con=Depends(get_con),
                      _rl=Depends(rate_limit)):
    row = con.execute(
        "SELECT * FROM store_discounts WHERE lower(code)=lower(?) AND active=1",
        (body.code.strip(),)).fetchone()
    if row is None or (row["expires_at"] and row["expires_at"] < db.now()):
        raise HTTPException(404, "invalid or expired code")
    return {"code": row["code"], "pct": row["pct"]}


# ---------- public: email intake / rewards ----------

class SubscribeBody(BaseModel):
    email: str
    source: str = "storefront"


@router.post("/api/store/subscribe")
def subscribe(body: SubscribeBody, con=Depends(get_con),
              _rl=Depends(rate_limit)):
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "enter a valid email")
    con.execute(
        "INSERT OR IGNORE INTO store_subscribers(email, source, created_at)"
        " VALUES(?,?,?)", (email, body.source[:32], db.now()))
    con.commit()
    fire_webhooks("subscriber.created", {"email": email, "source": body.source})
    return {"ok": True}


# ---------- public: reviews ----------

class ReviewBody(BaseModel):
    product_id: int
    name: str = "Anonymous"
    email: str = ""
    rating: int
    body: str = ""


@router.get("/api/store/reviews/{product_id}")
def reviews(product_id: int, con=Depends(get_con)):
    rows = con.execute(
        "SELECT name, rating, body, verified, created_at FROM product_reviews"
        " WHERE product_id=? AND approved=1 ORDER BY id DESC LIMIT 50",
        (product_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/store/reviews")
def add_review(body: ReviewBody, con=Depends(get_con),
               _rl=Depends(rate_limit)):
    if not 1 <= body.rating <= 5:
        raise HTTPException(400, "rating must be 1–5")
    email = body.email.strip().lower()
    # Verified buyer: this email's account has an order containing the product.
    verified = 0
    if email:
        verified = 1 if con.execute(
            "SELECT 1 FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " JOIN users u ON u.id=o.user_id"
            " WHERE oi.product_id=? AND lower(u.email)=? LIMIT 1",
            (body.product_id, email)).fetchone() else 0
    con.execute(
        "INSERT INTO product_reviews(product_id, name, email, rating, body,"
        " approved, verified, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (body.product_id, body.name.strip()[:60] or "Anonymous", email,
         body.rating, body.body.strip()[:2000], 0, verified, db.now()))
    con.commit()
    fire_webhooks("review.created",
                  {"product_id": body.product_id, "rating": body.rating,
                   "verified": bool(verified)})
    return {"ok": True, "pending": True,
            "note": "thanks! your review appears once approved"}


# ---------- public: order tracking ----------

@router.get("/api/store/order-status/{order_id}")
def order_status(order_id: int, con=Depends(get_con)):
    o = con.execute(
        "SELECT o.id, o.status, o.payment_status, o.total_cents,"
        " o.discount_cents, o.discount_code, o.city, o.created_at"
        " FROM orders o WHERE o.id=?", (order_id,)).fetchone()
    if o is None:
        raise HTTPException(404, "order not found")
    steps = ["pending", "confirmed", "shipped", "delivered"]
    d = dict(o)
    d["steps"] = steps
    d["step_index"] = steps.index(o["status"]) if o["status"] in steps else -1
    return d


# ---------- public: custom pages ----------

PAGE_SHELL = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/store.css">
<style>{css}</style></head>
<body class="custom-page"><nav class="topbar"><a class="brand" href="/">← back to store</a></nav>
<main class="page-body">{html}{liquid}</main>
<script>
let v=localStorage.getItem('sf_vid')||crypto.randomUUID();localStorage.setItem('sf_vid',v);
fetch('/api/store/track',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{visitor_id:v,page:'/p/{slug}'}})}}).catch(()=>{{}});
</script>
<script>{js}</script></body></html>"""


def render_home(con) -> str:
    body = sect.render_page(con, page_rows(con, "home"), render_liquid)
    return render_shell(con, body)


@router.get("/p/{slug}")
def page(slug: str, con=Depends(get_con)):
    row = con.execute(
        "SELECT * FROM store_pages WHERE slug=? AND published=1",
        (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, "page not found")
    rows = page_rows(con, slug)
    if rows:            # built visually — same engine as the theme editor
        body = sect.render_page(con, rows, render_liquid)
        html = render_shell(con, body, title=f"{row['title']} — "
                            f"{get_theme(con)['brand']}",
                            description=row["title"])
        return HTMLResponse(html.replace(
            "</body>",
            f"<script>(function(){{let v=localStorage.getItem('sf_vid')||"
            f"crypto.randomUUID();localStorage.setItem('sf_vid',v);"
            f"fetch('/api/store/track',{{method:'POST',headers:"
            f"{{'Content-Type':'application/json'}},body:JSON.stringify("
            f"{{visitor_id:v,page:'/p/{slug}'}})}}).catch(()=>{{}});}})()"
            f"</script></body>"))
    # Legacy raw-code page (pre-builder) — still fully supported.
    return HTMLResponse(PAGE_SHELL.format(
        title=row["title"], css=row["content_css"], html=row["content_html"],
        liquid=render_liquid(row["liquid"], con),
        js=row["content_js"], slug=slug))


# ---------- customer account: orders + subscription self-service ----------

def current_customer(authorization: str = Header(default=""),
                     con=Depends(get_con)):
    user = auth.user_for_token(
        con, authorization.removeprefix("Bearer ").strip())
    if user is None:
        raise HTTPException(401, "sign in first")
    return user


@router.get("/api/store/account/orders")
def account_orders(user=Depends(current_customer), con=Depends(get_con)):
    orders = [dict(o) for o in con.execute(
        "SELECT id, status, payment_status, total_cents, discount_cents,"
        " discount_code, created_at FROM orders WHERE user_id=?"
        " ORDER BY id DESC LIMIT 25", (user["id"],)).fetchall()]
    for o in orders:
        o["items"] = [dict(i) for i in con.execute(
            "SELECT oi.qty, oi.unit_price_cents, oi.variant_name, p.name"
            " FROM order_items oi JOIN products p ON p.id=oi.product_id"
            " WHERE order_id=?", (o["id"],)).fetchall()]
    return orders


class SubItemsBody(BaseModel):
    items: list[dict]                      # [{product_id, variant_id, qty}]


@router.get("/api/store/account/subscriptions")
def account_subs(user=Depends(current_customer), con=Depends(get_con)):
    subs = [dict(s) for s in con.execute(
        "SELECT s.*, p.name, p.price_cents FROM store_subscriptions s"
        " JOIN products p ON p.id=s.product_id WHERE s.user_id=?"
        " AND s.status != 'cancelled' ORDER BY s.id DESC",
        (user["id"],)).fetchall()]
    for s in subs:
        if s["variant_id"]:
            v = con.execute("SELECT name, price_cents FROM product_variants"
                            " WHERE id=?", (s["variant_id"],)).fetchone()
            if v:
                s["name"] += " · " + v["name"]
                s["price_cents"] = v["price_cents"]
    cyc = cycles.current(con)
    return {"subscriptions": subs, "cycle": cyc,
            "changes_open": (cyc is None) or cyc.get("changes_open", True)}


@router.post("/api/store/account/subscriptions")
def create_subs(body: SubItemsBody, user=Depends(current_customer),
                con=Depends(get_con)):
    made = 0
    for it in body.items[:20]:
        pid = int(it.get("product_id") or 0)
        if not con.execute("SELECT 1 FROM products WHERE id=? AND active=1",
                           (pid,)).fetchone():
            continue
        con.execute(
            "INSERT INTO store_subscriptions(user_id, product_id, variant_id,"
            " qty, created_at) VALUES(?,?,?,?,?)",
            (user["id"], pid, it.get("variant_id") or None,
             max(1, int(it.get("qty") or 1)), db.now()))
        made += 1
    con.commit()
    return {"ok": True, "created": made}


class SubActionBody(BaseModel):
    action: str                            # skip|unskip|pause|resume|cancel


@router.post("/api/store/account/subscriptions/{sid}/action")
def sub_action(sid: int, body: SubActionBody, user=Depends(current_customer),
               con=Depends(get_con)):
    s = con.execute("SELECT * FROM store_subscriptions WHERE id=? AND"
                    " user_id=?", (sid, user["id"])).fetchone()
    if s is None:
        raise HTTPException(404, "no such subscription")
    cyc = cycles.current(con)
    changes_open = (cyc is None) or cyc.get("changes_open", True)
    transitions = {"skip": "skipped_next", "unskip": "active",
                   "pause": "paused", "resume": "active",
                   "cancel": "cancelled"}
    if body.action not in transitions:
        raise HTTPException(400, "unknown action")
    # Skip/unskip race the curation cutoff; pause/resume/cancel are always OK.
    if body.action in ("skip", "unskip") and not changes_open:
        raise HTTPException(409, "changes are closed for this box cycle —"
                            " the next window opens after shipping")
    con.execute("UPDATE store_subscriptions SET status=? WHERE id=?",
                (transitions[body.action], sid))
    con.commit()
    return {"ok": True, "status": transitions[body.action]}


# ---------- public: server-rendered product pages + SEO ----------

@router.get("/product/{pid_slug}")
def product_page(pid_slug: str, request: Request, con=Depends(get_con)):
    try:
        pid = int(pid_slug.split("-")[0])
    except ValueError:
        raise HTTPException(404, "product not found")
    p = con.execute("SELECT * FROM products WHERE id=? AND active=1",
                    (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "product not found")
    base = str(request.base_url).rstrip("/")
    _t = get_theme(con)
    name = _html.escape(p["name"])
    desc = _html.escape(p["description"]
                        or f"{p['name']} from {_t['brand'].title()}.")
    canonical = f"{base}/product/{pid}-{slugify(p['name'])}"
    meta = product_meta(con, pid)
    colour = meta.get("colour") or "#6c00bf"
    note = _html.escape(meta.get("note") or "")
    ingredients = _html.escape(meta.get("ingredients") or "")
    try:
        nutri = json.loads(meta.get("nutrition") or "{}")
    except ValueError:
        nutri = {}
    media = media_json(con.execute(
        "SELECT * FROM product_media WHERE product_id=? ORDER BY position, id",
        (pid,)).fetchall())
    hero = next((m for m in media if m["kind"] == "image"), None)
    img = (f"{base}{hero['url']}" if hero
           else (f"{base}/media/product/{pid}" if p["image"] else ""))
    variants = [dict(v) for v in con.execute(
        "SELECT * FROM product_variants WHERE product_id=? AND active=1"
        " ORDER BY position, id", (pid,)).fetchall()]
    revs = [dict(r) for r in con.execute(
        "SELECT name, rating, body FROM product_reviews WHERE product_id=?"
        " AND approved=1 ORDER BY id DESC LIMIT 20", (pid,)).fetchall()]
    agg = con.execute(
        "SELECT COUNT(*) n, AVG(rating) avg FROM product_reviews"
        " WHERE product_id=? AND approved=1", (pid,)).fetchone()
    prices = [v["price_cents"] for v in variants] or [p["price_cents"]]
    in_stock = (not variants) or any(v["stock"] > 0 for v in variants)
    ld = {"@context": "https://schema.org", "@type": "Product",
          "name": p["name"], "description": p["description"] or "",
          "sku": p["sku"], "url": canonical,
          "offers": {"@type": "AggregateOffer",
                     "priceCurrency": "USD",
                     "lowPrice": f"{min(prices) / 100:.2f}",
                     "highPrice": f"{max(prices) / 100:.2f}",
                     "availability": "https://schema.org/" +
                     ("InStock" if in_stock else "OutOfStock")}}
    gallery = [f"{base}{m['url']}" for m in media if m["kind"] == "image"]
    if gallery:
        ld["image"] = gallery
    elif img:
        ld["image"] = img
    vid = next((m for m in media if m["kind"] == "video"), None)
    if vid:
        ld["video"] = {"@type": "VideoObject", "name": p["name"],
                       "description": p["description"] or p["name"],
                       "thumbnailUrl": img or "",
                       "uploadDate": "2026-01-01",
                       "contentUrl": vid["video_url"] or f"{base}{vid['url']}"}
    if agg["n"]:
        ld["aggregateRating"] = {"@type": "AggregateRating",
                                 "ratingValue": f"{agg['avg']:.1f}",
                                 "reviewCount": agg["n"]}
    if media:
        first = media[0]
        if first["kind"] == "video" and first["video_url"]:
            stage = (f'<iframe id="pp-stage-frame" src="{_html.escape(first["video_url"])}"'
                     ' allow="autoplay; encrypted-media" allowfullscreen></iframe>')
        elif first["kind"] == "video":
            stage = (f'<video id="pp-stage-video" src="{first["url"]}" controls'
                     ' playsinline></video>')
        else:
            stage = (f'<img id="pp-stage" src="{first["url"]}"'
                     f' alt="{_html.escape(first["alt"] or p["name"])}">')
        strip = "".join(
            f'<button class="pp-thumb" data-kind="{m["kind"]}"'
            f' data-url="{_html.escape(m["url"])}"'
            f' data-alt="{_html.escape(m["alt"] or p["name"])}">'
            f'<img src="{m["thumb"]}" alt="{_html.escape(m["alt"] or p["name"])}"'
            f' loading="lazy">'
            f'{sect.icon("play", "ico play") if m["kind"] == "video" else ""}'
            f'</button>' for m in media) if len(media) > 1 else ""
        art = f'<div class="pp-stage">{stage}</div>' + (
            f'<div class="pp-strip">{strip}</div>' if strip else "")
    elif p["image"]:
        art = (f'<div class="pp-stage"><img src="/media/product/{pid}"'
               f' alt="{name}"></div>')
    else:
        art = (f'<div class="pp-stage">'
               f'{product_art(_t, pid, p["name"], colour, brand=_t["brand"])}'
               f'</div>')
    var_html = ""
    if variants:
        opts = "".join(
            f'<option value="{v["id"]}" data-price="{v["price_cents"]}"'
            f'{" disabled" if v["stock"] <= 0 else ""}>'
            f'{_html.escape(v["name"])} — ${v["price_cents"] / 100:.2f}'
            f'{" (sold out)" if v["stock"] <= 0 else ""}</option>'
            for v in variants)
        var_html = f'<select id="pp-var" class="var-sel">{opts}</select>'
    revs_html = "".join(
        f'<div class="review-card" style="margin-bottom:12px">'
        f'<span class="stars">{sect.icon("star") * r["rating"]}</span>'
        f'<p>&ldquo;{_html.escape(r["body"] or "")}&rdquo;</p>'
        f'<span class="who">{_html.escape(r["name"])}</span></div>'
        for r in revs) or '<p class="dim">No reviews yet.</p>'

    # Flavour switcher — the range, not a dropdown. Each sibling keeps its own
    # ring colour so the page recolours as you move through the family.
    sibs = con.execute(
        "SELECT p.id, p.name, m.v colour FROM products p"
        " JOIN store_product_meta m ON m.product_id=p.id AND m.k='colour'"
        " WHERE p.active=1 AND p.id IN (SELECT product_id FROM"
        " store_product_meta WHERE k='flavour' AND v NOT IN ('','pack'))"
        " ORDER BY p.name").fetchall()
    flav_html = ""
    if len(sibs) > 1:
        opts = "".join(
            f'<a class="flav-opt{" on" if s["id"] == pid else ""}"'
            f' href="/product/{s["id"]}-{slugify(s["name"])}">'
            f'<svg class="ring" viewBox="0 0 120 120" aria-hidden="true">'
            f'<g fill="none" stroke="{s["colour"]}">'
            f'<circle cx="60" cy="60" r="9" stroke-width="11"/>'
            f'<circle cx="60" cy="60" r="26" stroke-width="8"/>'
            f'<circle cx="60" cy="60" r="44" stroke-width="5.5" opacity=".7"/>'
            f'</g></svg>{_html.escape(s["name"].split(" ")[0])}</a>'
            for s in sibs)
        flav_html = (f'<div class="pp-block"><span class="eyebrow">'
                     f'Flavor</span>'
                     f'<div class="flavour-picker">{opts}</div></div>')

    nutri_html = ""
    if nutri:
        rows = "".join(
            f'<div class="nutri-row"><span>{_html.escape(str(k))}</span>'
            f'<b>{_html.escape(str(v))}</b></div>' for k, v in nutri.items())
        nutri_html = (
            f'<div class="pp-block"><span class="eyebrow">Per can</span>'
            f'<div class="nutri">{rows}</div>'
            + (f'<p class="ingredients" style="margin-top:12px">'
               f'<b>Ingredients.</b> {ingredients}</p>' if ingredients else "")
            + '</div>')

    unit = min(prices)
    sub_price = int(round(unit * 0.85))
    buy_html = (
        f'<div class="pp-block"><span class="eyebrow">How often</span>'
        f'<div class="buy-mode">'
        f'<label class="buy-opt on" data-mode="once">'
        f'<input type="radio" name="buymode" value="once" checked>'
        f'<span class="lbl"><b>One time</b>'
        f'<span>${unit / 100:.2f} — no commitment</span></span></label>'
        f'<label class="buy-opt" data-mode="sub">'
        f'<input type="radio" name="buymode" value="sub">'
        f'<span class="lbl"><b>Subscribe &amp; save</b>'
        f'<span>${sub_price / 100:.2f} — every month, skip or cancel any time'
        f'</span></span><span class="save">Save 15%</span></label>'
        f'</div></div>')
    # "You may also like" — co-purchase first, then same category.
    from . import promos as promos_mod
    recs = promos_mod.recommendations(pid, 4, con)
    recs_html = ""
    if recs:
        # A card, not a link wrapping everything: an Add button cannot live
        # inside an <a> without breaking both the link and the button.
        cards = "".join(
            f'<div class="product"'
            f' style="--flavour:{product_meta(con, r["id"]).get("colour") or "#6c00bf"}">'
            + f'<a href="/product/{r["id"]}-{r["slug"]}" aria-label="{_html.escape(r["name"])}">'
            + (f'<div class="art"><img src="{r["media"][0]["thumb"]}"'
               f' alt="" loading="lazy"></div>' if r.get("media")
               else f'<div class="art">'
                    f'{product_art(_t, r["id"], r["name"], product_meta(con, r["id"]).get("colour") or "", "rec")}'
                    f'</div>')
            + '</a>'
            + f'<div class="body">'
            f'<a href="/product/{r["id"]}-{r["slug"]}"><b>{_html.escape(r["name"])}</b></a>'
            f'<div class="price-row"><span class="price">'
            f'${r["price_cents"] / 100:,.2f}</span>'
            f'<button class="add-btn" data-rec-add="{r["id"]}">Add</button>'
            f'</div></div></div>'
            for r in recs)
        recs_html = (f'<h2 style="margin-top:56px">You may also like</h2>'
                     f'<div class="grid">{cards}</div>')
    # Rendered through the storefront shell, exactly like the blog, the
    # partner pages and the locator. It used to be a standalone document
    # with a hand-rolled topbar and its own drawer, which is precisely why
    # its navigation drifted from every other page and why it needed a
    # "back to shop" button to make up for the missing menu. One shell, one
    # nav, one cart drawer — the product page is part of the storefront, not
    # a preview of it.
    body = f"""
<main class="section pp-main" id="pp-main">
 <div class="pp-grid">
  <div class="pp-art">{art}</div>
  <div class="pp-info">
   <h1>{name}</h1>
   {f'<p class="pp-tagline">{note}</p>' if note else ''}
   <span class="stars">{(sect.icon("star") * round(agg["avg"]) + f' {agg["avg"]:.1f} ({agg["n"]} reviews)') if agg["n"] else ''}</span>
   <div class="pp-price"><span class="amt" id="pp-price">${min(prices) / 100:.2f}</span>
    <span class="dim">12 fl oz can</span></div>
   <p style="color:var(--ink-2)">{desc}</p>
   {flav_html}
   {f'<div class="pp-block"><span class="eyebrow">Options</span>{var_html}</div>' if var_html else ''}
   {buy_html}
   <div class="pp-block">
    <div class="buy-row">
     <span class="qty-step">
      <button id="pp-minus" aria-label="Decrease quantity">{sect.icon("minus", "ico ico-sm")}</button>
      <span id="pp-qty">1</span>
      <button id="pp-plus" aria-label="Increase quantity">{sect.icon("plus", "ico ico-sm")}</button>
     </span>
     <button class="btn-pill primary" id="pp-add"{"" if in_stock else " disabled"}>
      {"Add to cart" if in_stock else "Sold out"}</button>
    </div>
    <p class="dim" style="margin-top:12px">
     {sect.icon("truck", "ico ico-sm")} Free shipping over $40 ·
     {sect.icon("shield", "ico ico-sm")} Love it or we make it right</p>
   </div>
   {nutri_html}
  </div>
 </div>
 {recs_html}
 <div class="pp-rev-head">
  <h2>Reviews</h2>
  <button class="btn-pill ghost sm" data-review-for="{pid}">
   {sect.icon("star", "ico ico-sm")} Write a review</button>
 </div>
 {revs_html}
</main>
<div class="sticky-buy" id="sticky-buy" style="--flavour:{colour}">
 <div class="sticky-inner">
  {(f'<span class="sticky-shot"><img src="/media/product/{pid}" alt=""></span>')
   if p["image"] else product_art(_t, pid, p["name"], colour, "sticky", mini=True)}
  <span class="who"><b>{name}</b><span class="dim" id="sticky-price">${min(prices) / 100:.2f}</span></span>
  <button class="btn-pill primary" id="sticky-add"{"" if in_stock else " disabled"}>
   {"Add to cart" if in_stock else "Sold out"}</button>
 </div>
</div>
<script>
let v=localStorage.getItem('sf_vid')||crypto.randomUUID();localStorage.setItem('sf_vid',v);
fetch('/api/store/track',{{method:'POST',headers:{{'Content-Type':'application/json'}},
 body:JSON.stringify({{visitor_id:v,page:'product:{pid}'}})}}).catch(()=>{{}});
fetch('/api/events',{{method:'POST',headers:{{'Content-Type':'application/json'}},
 body:JSON.stringify({{visitor_id:v,step:'view_product',product_id:{pid}}})}}).catch(()=>{{}});
const sel=document.getElementById('pp-var');
const SUB_RATE=0.85;
let qty=1, mode='once';
function unitPrice(){{
 const base=sel?+sel.selectedOptions[0].dataset.price:{unit};
 return mode==='sub'?Math.round(base*SUB_RATE):base;
}}
function paint(){{
 const each=unitPrice();
 document.getElementById('pp-price').textContent='$'+(each/100).toFixed(2);
 const s=document.getElementById('sticky-price');
 if(s)s.textContent='$'+(each*qty/100).toFixed(2)+(qty>1?' · '+qty+' cans':'');
 document.getElementById('pp-qty').textContent=qty;
}}
if(sel)sel.onchange=paint;
document.getElementById('pp-plus').onclick=()=>{{qty++;paint();}};
document.getElementById('pp-minus').onclick=()=>{{if(qty>1)qty--;paint();}};
document.querySelectorAll('.buy-opt').forEach(function(o){{
 o.onclick=function(){{
  mode=o.dataset.mode;
  document.querySelectorAll('.buy-opt').forEach(function(x){{
   x.classList.toggle('on',x===o);}});
  o.querySelector('input').checked=true;
  paint();
 }};}});
paint();
// Sticky buy bar appears once the real one scrolls off — the single most
// reliable conversion lift on a long product page.
const realBuy=document.getElementById('pp-add');
const sticky=document.getElementById('sticky-buy');
if(window.IntersectionObserver&&realBuy&&sticky){{
 new IntersectionObserver(function(es){{
  const shown=!es[0].isIntersecting&&es[0].boundingClientRect.top<0;
  sticky.classList.toggle('show',shown);
  // both floating badges clear the bar together, so they stay on one line
  const fab=document.getElementById('buy-fab');
  if(fab)fab.classList.toggle('lifted',shown);
  const a11y=document.querySelector('.a11y-fab');
  if(a11y)a11y.classList.toggle('lifted',shown);
 }},{{threshold:0}}).observe(realBuy);
}}
document.querySelectorAll('.pp-thumb').forEach(function(b){{
 b.onclick=function(){{
  var stage=document.querySelector('.pp-stage');
  var u=b.dataset.url,k=b.dataset.kind;
  if(k==='video'){{
   stage.innerHTML=u.indexOf('/media/m/')===0
    ?'<video src="'+u+'" controls autoplay playsinline></video>'
    :'<iframe src="'+u+'" allow="autoplay; encrypted-media" allowfullscreen></iframe>';
  }}else{{
   stage.innerHTML='<img id="pp-stage-img" src="'+u+'" alt="'+b.dataset.alt+'">';
  }}
  document.querySelectorAll('.pp-thumb').forEach(function(x){{
   x.classList.toggle('on',x===b);}});
 }};}});
if(document.querySelector('.pp-thumb'))
 document.querySelector('.pp-thumb').classList.add('on');
function addToCart(){{
 const cart=JSON.parse(localStorage.getItem('sf_cart')||'{{}}');
 const key='{pid}:'+(sel?sel.value:0);
 cart[key]=(cart[key]||0)+qty;
 localStorage.setItem('sf_cart',JSON.stringify(cart));
 if(mode==='sub')localStorage.setItem('sf_sub_intent','{pid}');
 fetch('/api/events',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{visitor_id:v,step:'add_to_cart',product_id:{pid}}})}})
  .catch(()=>{{}});
 location.href='/?cart=1';
}}
document.getElementById('pp-add').onclick=addToCart;
// "You may also like" adds straight to the cart, same as everywhere else.
document.querySelectorAll('[data-rec-add]').forEach(function(b){{
 b.onclick=function(){{
  var cart=JSON.parse(localStorage.getItem('sf_cart')||'{{}}');
  var k=b.dataset.recAdd+':0';
  cart[k]=(cart[k]||0)+1;
  localStorage.setItem('sf_cart',JSON.stringify(cart));
  location.href='/?cart=1';
 }};}});
const sa=document.getElementById('sticky-add');
if(sa)sa.onclick=addToCart;
const bf=document.getElementById('buy-fab');
if(bf)bf.onclick=addToCart;
</script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"{name} — {get_theme(con)['brand'].title()}",
        description=desc[:155],
        head_extra=(f'<link rel="canonical" href="{canonical}">'
                    f'<meta property="og:type" content="product">'
                    + (f'<meta property="og:image" content="{img}">' if img else "")
                    + f'<meta property="og:url" content="{canonical}">'
                    # Only the colour. The soft tint derives from it per
                    # component, so a card on this page keeps its own.
                    + f'<style>:root{{--flavour:{colour}}}</style>'
                    + f'<script type="application/ld+json">'
                      f'{json.dumps(ld)}</script>')))


@router.get("/sitemap.xml")
def sitemap(request: Request, con=Depends(get_con)):
    base = str(request.base_url).rstrip("/")
    urls = [f"{base}/"]
    for p in con.execute(
            "SELECT id, name FROM products WHERE active=1").fetchall():
        urls.append(f"{base}/product/{p['id']}-{slugify(p['name'])}")
    for pg in con.execute(
            "SELECT slug FROM store_pages WHERE published=1").fetchall():
        urls.append(f"{base}/p/{pg['slug']}")
    urls.append(f"{base}/blog")
    for post in con.execute(
            "SELECT slug FROM blog_posts WHERE published=1").fetchall():
        urls.append(f"{base}/blog/{post['slug']}")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(f"<url><loc>{_html.escape(u)}</loc></url>" for u in urls)
           + "</urlset>")
    return Response(content=xml, media_type="application/xml")


@router.get("/robots.txt")
def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        f"User-agent: *\nAllow: /\nDisallow: /ops/\nDisallow: /admin\n"
        f"Sitemap: {base}/sitemap.xml\n")


# ---------- admin: pages / collections / discounts / webhooks ----------

class PageBody(BaseModel):
    slug: str
    title: str
    content_html: str = ""
    content_css: str = ""
    content_js: str = ""
    liquid: str = ""
    published: bool = True


@router.get("/api/store/admin/pages")
def list_pages(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in
            con.execute("SELECT * FROM store_pages ORDER BY slug").fetchall()]


@router.post("/api/store/admin/pages")
def save_page(body: PageBody, u=Depends(admin_user), con=Depends(get_con)):
    slug = body.slug.strip().lower().replace(" ", "-")[:60]
    if not slug:
        raise HTTPException(400, "slug required")
    con.execute(
        "INSERT INTO store_pages(slug, title, content_html, content_css,"
        " content_js, liquid, published, created_at) VALUES(?,?,?,?,?,?,?,?)"
        " ON CONFLICT(slug) DO UPDATE SET title=excluded.title,"
        " content_html=excluded.content_html, content_css=excluded.content_css,"
        " content_js=excluded.content_js, liquid=excluded.liquid,"
        " published=excluded.published",
        (slug, body.title.strip(), body.content_html, body.content_css,
         body.content_js, body.liquid, int(body.published), db.now()))
    con.commit()
    return {"ok": True, "slug": slug, "url": f"/p/{slug}"}


@router.delete("/api/store/admin/pages/{slug}")
def delete_page(slug: str, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_pages WHERE slug=?", (slug,))
    con.commit()
    return {"ok": True}


class CollectionBody(BaseModel):
    slug: str
    name: str
    product_ids: list[int] = []


@router.post("/api/store/admin/collections")
def save_collection(body: CollectionBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    slug = body.slug.strip().lower().replace(" ", "-")[:60]
    con.execute(
        "INSERT INTO collections(slug, name) VALUES(?,?)"
        " ON CONFLICT(slug) DO UPDATE SET name=excluded.name",
        (slug, body.name.strip()))
    cid = con.execute("SELECT id FROM collections WHERE slug=?",
                      (slug,)).fetchone()["id"]
    con.execute("DELETE FROM collection_products WHERE collection_id=?", (cid,))
    for pid in body.product_ids:
        con.execute("INSERT OR IGNORE INTO collection_products VALUES(?,?)",
                    (cid, pid))
    con.commit()
    return {"ok": True, "id": cid}


@router.delete("/api/store/admin/collections/{slug}")
def delete_collection(slug: str, u=Depends(admin_user), con=Depends(get_con)):
    row = con.execute("SELECT id FROM collections WHERE slug=?",
                      (slug,)).fetchone()
    if row:
        con.execute("DELETE FROM collection_products WHERE collection_id=?",
                    (row["id"],))
        con.execute("DELETE FROM collections WHERE id=?", (row["id"],))
        con.commit()
    return {"ok": True}


class DiscountAdminBody(BaseModel):
    code: str
    pct: int
    active: bool = True


@router.get("/api/store/admin/discounts")
def list_discounts(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in
            con.execute("SELECT * FROM store_discounts ORDER BY code").fetchall()]


@router.post("/api/store/admin/discounts")
def save_discount(body: DiscountAdminBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if not 1 <= body.pct <= 100:
        raise HTTPException(400, "pct must be 1–100")
    con.execute(
        "INSERT INTO store_discounts(code, pct, active) VALUES(?,?,?)"
        " ON CONFLICT(code) DO UPDATE SET pct=excluded.pct,"
        " active=excluded.active",
        (body.code.strip().upper(), body.pct, int(body.active)))
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/reviews")
def pending_reviews(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT r.*, p.name product_name FROM product_reviews r"
        " JOIN products p ON p.id=r.product_id WHERE r.approved=0"
        " ORDER BY r.id DESC LIMIT 100").fetchall()]


@router.post("/api/store/admin/reviews/{rid}/approve")
def approve_review(rid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE product_reviews SET approved=1 WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/reviews/{rid}")
def delete_review(rid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM product_reviews WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


# ---------- admin: theme editor & visual page builder ----------

@router.get("/api/store/admin/section-schema")
def section_schema(u=Depends(admin_user)):
    return sect.schema_json()


@router.get("/api/store/admin/sections/{slug}")
def get_sections(slug: str, u=Depends(admin_user), con=Depends(get_con)):
    out = []
    for r in page_rows(con, slug):
        d = dict(r)
        try:
            d["settings"] = {**sect.defaults_for(r["type"]),
                             **json.loads(r["settings"] or "{}")}
        except ValueError:
            d["settings"] = sect.defaults_for(r["type"])
        d["label"] = sect.SECTION_TYPES.get(r["type"], {}).get(
            "label", r["type"])
        d["icon"] = sect.SECTION_TYPES.get(r["type"], {}).get("icon", "▫")
        out.append(d)
    return out


class SectionAddBody(BaseModel):
    page_slug: str
    type: str


@router.post("/api/store/admin/sections")
def add_section(body: SectionAddBody, u=Depends(admin_user),
                con=Depends(get_con)):
    if body.type not in sect.SECTION_TYPES:
        raise HTTPException(400, "unknown section type")
    nxt = con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 n FROM page_sections"
        " WHERE page_slug=?", (body.page_slug,)).fetchone()["n"]
    cur = con.execute(
        "INSERT INTO page_sections(page_slug,type,settings,position)"
        " VALUES(?,?,?,?)",
        (body.page_slug, body.type,
         json.dumps(sect.defaults_for(body.type)), nxt))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class SectionPatchBody(BaseModel):
    settings: dict | None = None
    move: str | None = None          # up|down
    enabled: bool | None = None


@router.post("/api/store/admin/sections/{sid}")
def patch_section(sid: int, body: SectionPatchBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    s = con.execute("SELECT * FROM page_sections WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "no such section")
    if body.settings is not None:
        allowed = {f["k"] for f in
                   sect.SECTION_TYPES[s["type"]]["fields"]}
        clean = {k: v for k, v in body.settings.items() if k in allowed}
        con.execute("UPDATE page_sections SET settings=? WHERE id=?",
                    (json.dumps(clean), sid))
    if body.enabled is not None:
        con.execute("UPDATE page_sections SET enabled=? WHERE id=?",
                    (int(body.enabled), sid))
    if body.move in ("up", "down"):
        ids = [r["id"] for r in page_rows(con, s["page_slug"])]
        i = ids.index(sid)
        j = i - 1 if body.move == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, rid in enumerate(ids):
                con.execute("UPDATE page_sections SET position=? WHERE id=?",
                            (pos, rid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/sections/{sid}")
def delete_section(sid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM page_sections WHERE id=?", (sid,))
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/theme")
def read_theme(u=Depends(admin_user), con=Depends(get_con)):
    return get_theme(con)


@router.post("/api/store/admin/theme")
def write_theme(body: dict, u=Depends(admin_user), con=Depends(get_con)):
    clean = {k: v for k, v in body.items() if k in THEME_DEFAULT}
    con.execute(
        "INSERT INTO store_meta(k,v) VALUES('theme',?)"
        " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (json.dumps({**get_theme(con), **clean}),))
    con.commit()
    return {"ok": True, "theme": get_theme(con)}


@router.get("/admin/theme")
def theme_editor_page():
    return HTMLResponse(_admin_html("theme.html"))


# ---------- admin: API keys (the app platform) ----------

class KeyBody(BaseModel):
    name: str
    scopes: list[str] = []


@router.get("/api/store/admin/keys")
def list_keys(u=Depends(admin_user), con=Depends(get_con)):
    from .public_api import SCOPES
    return {"keys": [dict(r) for r in con.execute(
        "SELECT id,name,prefix,scopes,active,last_used_at,calls,created_at"
        " FROM api_keys ORDER BY id DESC").fetchall()],
        "scopes": SCOPES}


@router.post("/api/store/admin/keys")
def create_key(body: KeyBody, u=Depends(admin_user), con=Depends(get_con)):
    from .public_api import SCOPES, mint_key
    scopes = [s for s in body.scopes if s in SCOPES or s == "*"]
    if not scopes:
        raise HTTPException(400, "pick at least one scope")
    raw, hashed, prefix = mint_key()
    con.execute(
        "INSERT INTO api_keys(name,key_hash,prefix,scopes,created_at)"
        " VALUES(?,?,?,?,?)",
        (body.name.strip()[:60] or "app key", hashed, prefix,
         ",".join(scopes), db.now()))
    con.commit()
    # Shown once — we only keep the hash.
    return {"ok": True, "key": raw, "prefix": prefix,
            "note": "copy this now; it cannot be shown again"}


@router.delete("/api/store/admin/keys/{kid}")
def revoke_key(kid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE api_keys SET active=0 WHERE id=?", (kid,))
    con.commit()
    return {"ok": True}


class MediaBody(BaseModel):
    product_id: int
    data_url: str = ""       # base64 upload (image or video file)
    video_url: str = ""      # or an external embed / hosted video URL
    alt: str = ""


@router.get("/api/store/admin/media/{product_id}")
def list_media(product_id: int, u=Depends(admin_user), con=Depends(get_con)):
    return media_json(con.execute(
        "SELECT * FROM product_media WHERE product_id=? ORDER BY position, id",
        (product_id,)).fetchall())


@router.post("/api/store/admin/media")
def add_media(body: MediaBody, u=Depends(admin_user), con=Depends(get_con)):
    import base64
    if not con.execute("SELECT 1 FROM products WHERE id=?",
                       (body.product_id,)).fetchone():
        raise HTTPException(404, "no such product")
    nxt = (con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 n FROM product_media"
        " WHERE product_id=?", (body.product_id,)).fetchone()["n"])
    kind, ext, raw = "image", "jpg", None
    if body.video_url.strip():
        kind, ext = "video", ""
    elif body.data_url:
        try:
            _, b64 = body.data_url.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(400, "bad upload data")
        sniffed = sniff_media(raw)
        if sniffed is None:
            raise HTTPException(400, "not a recognised image or video")
        kind, ext = sniffed
        cap = 25_000_000 if kind == "video" else 8_000_000
        if len(raw) > cap:
            raise HTTPException(
                400, f"{kind} too large ({cap // 1_000_000} MB max)"
                + (" — host big video externally and paste the URL"
                   if kind == "video" else ""))
    else:
        raise HTTPException(400, "provide an upload or a video URL")
    cur = con.execute(
        "INSERT INTO product_media(product_id,kind,ext,video_url,alt,"
        " position,created_at) VALUES(?,?,?,?,?,?,?)",
        (body.product_id, kind, ext, body.video_url.strip(),
         body.alt.strip()[:200], nxt, db.now()))
    mid = cur.lastrowid
    if raw is not None:
        MEDIA_DIR().mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR() / f"{mid}.{ext}").write_bytes(raw)
        if kind == "image":
            make_derivatives(mid, ext)
    # Keep the ERP's legacy art flag in step with the primary image.
    if kind == "image" and nxt == 0:
        con.execute("UPDATE products SET image=1 WHERE id=?",
                    (body.product_id,))
    con.commit()
    return {"ok": True, "id": mid, "kind": kind}


class MediaPatchBody(BaseModel):
    alt: str | None = None
    move: str | None = None      # up|down|primary


@router.post("/api/store/admin/media/{mid}")
def patch_media(mid: int, body: MediaPatchBody, u=Depends(admin_user),
                con=Depends(get_con)):
    m = con.execute("SELECT * FROM product_media WHERE id=?", (mid,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such media")
    if body.alt is not None:
        con.execute("UPDATE product_media SET alt=? WHERE id=?",
                    (body.alt.strip()[:200], mid))
    if body.move:
        sibs = con.execute(
            "SELECT id FROM product_media WHERE product_id=?"
            " ORDER BY position, id", (m["product_id"],)).fetchall()
        ids = [r["id"] for r in sibs]
        i = ids.index(mid)
        if body.move == "primary":
            ids.insert(0, ids.pop(i))
        elif body.move == "up" and i > 0:
            ids[i - 1], ids[i] = ids[i], ids[i - 1]
        elif body.move == "down" and i < len(ids) - 1:
            ids[i + 1], ids[i] = ids[i], ids[i + 1]
        for pos, rid in enumerate(ids):
            con.execute("UPDATE product_media SET position=? WHERE id=?",
                        (pos, rid))
        first = con.execute(
            "SELECT kind FROM product_media WHERE product_id=?"
            " ORDER BY position, id LIMIT 1", (m["product_id"],)).fetchone()
        con.execute("UPDATE products SET image=? WHERE id=?",
                    (1 if first and first["kind"] == "image" else 0,
                     m["product_id"]))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/media/{mid}")
def delete_media(mid: int, u=Depends(admin_user), con=Depends(get_con)):
    m = con.execute("SELECT * FROM product_media WHERE id=?", (mid,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such media")
    for f in (MEDIA_DIR() / f"{mid}.{m['ext']}", MEDIA_DIR() / f"{mid}_lg.jpg",
              MEDIA_DIR() / f"{mid}_th.jpg"):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    con.execute("DELETE FROM product_media WHERE id=?", (mid,))
    left = con.execute(
        "SELECT kind FROM product_media WHERE product_id=?"
        " ORDER BY position, id LIMIT 1", (m["product_id"],)).fetchone()
    con.execute("UPDATE products SET image=? WHERE id=?",
                (1 if left and left["kind"] == "image" else 0,
                 m["product_id"]))
    con.commit()
    return {"ok": True}


class VariantBody(BaseModel):
    product_id: int
    name: str
    option1: str = ""
    option2: str = ""
    sku: str = ""
    price_cents: int
    stock: int = 0


@router.get("/api/store/admin/variants/{product_id}")
def list_variants(product_id: int, u=Depends(admin_user),
                  con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM product_variants WHERE product_id=?"
        " ORDER BY position, id", (product_id,)).fetchall()]


@router.post("/api/store/admin/variants")
def add_variant(body: VariantBody, u=Depends(admin_user),
                con=Depends(get_con)):
    if body.price_cents <= 0:
        raise HTTPException(400, "price required")
    con.execute(
        "INSERT INTO product_variants(product_id,name,option1,option2,sku,"
        " price_cents,stock) VALUES(?,?,?,?,?,?,?)",
        (body.product_id, body.name.strip(), body.option1.strip(),
         body.option2.strip(), body.sku.strip(), body.price_cents,
         body.stock))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/variants/{vid}")
def delete_variant(vid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE product_variants SET active=0 WHERE id=?", (vid,))
    con.commit()
    return {"ok": True}


class ShippingBody(BaseModel):
    name: str
    price_cents: int
    eta: str = ""
    position: int = 1


@router.post("/api/store/admin/shipping")
def add_shipping(body: ShippingBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    con.execute(
        "INSERT INTO store_shipping_methods(name,price_cents,eta,position)"
        " VALUES(?,?,?,?)",
        (body.name.strip(), body.price_cents, body.eta.strip(),
         body.position))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/shipping/{sid}")
def delete_shipping(sid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("UPDATE store_shipping_methods SET active=0 WHERE id=?",
                (sid,))
    con.commit()
    return {"ok": True}


class WebhookBody(BaseModel):
    event: str
    url: str
    active: bool = True


@router.get("/api/store/admin/webhooks")
def list_webhooks(u=Depends(admin_user), con=Depends(get_con)):
    secret = con.execute(
        "SELECT v FROM store_meta WHERE k='webhook_secret'").fetchone()
    return {"hooks": [dict(r) for r in con.execute(
                "SELECT * FROM store_webhooks ORDER BY id").fetchall()],
            "secret": secret["v"] if secret else ""}


@router.post("/api/store/admin/webhooks")
def add_webhook(body: WebhookBody, u=Depends(admin_user), con=Depends(get_con)):
    from .public_api import EVENTS
    if body.event not in EVENTS:
        raise HTTPException(400, f"event must be one of {EVENTS}")
    con.execute("INSERT INTO store_webhooks(event, url, active) VALUES(?,?,?)",
                (body.event, body.url.strip(), int(body.active)))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/webhooks/{wid}")
def delete_webhook(wid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_webhooks WHERE id=?", (wid,))
    con.commit()
    return {"ok": True}


@router.post("/api/store/admin/webhooks/{wid}/test")
def test_webhook(wid: int, u=Depends(admin_user), con=Depends(get_con)):
    row = con.execute("SELECT * FROM store_webhooks WHERE id=?",
                      (wid,)).fetchone()
    if row is None:
        raise HTTPException(404, "webhook not found")
    fire_webhooks(row["event"], {"test": True})
    return {"ok": True, "fired": row["url"]}


# ---------- admin: page navigation + funnel analytics ----------

class TrackBody(BaseModel):
    visitor_id: str
    page: str


@router.post("/api/store/track")
def track_page(body: TrackBody, con=Depends(get_con),
               _rl=Depends(rate_limit)):
    con.execute(
        "INSERT INTO store_pageviews(visitor_id, page, created_at)"
        " VALUES(?,?,?)", (body.visitor_id[:64], body.page[:120], db.now()))
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/page-analytics")
def page_analytics(u=Depends(admin_user), con=Depends(get_con)):
    """Per-page navigation counts (storefront pageviews) plus the shared
    funnel (ERP events table) and subscriber total."""
    pages = [dict(r) for r in con.execute(
        "SELECT page, COUNT(*) hits, COUNT(DISTINCT visitor_id) visitors"
        " FROM store_pageviews GROUP BY page ORDER BY hits DESC LIMIT 100"
        ).fetchall()]
    funnel = [dict(r) for r in con.execute(
        "SELECT step, COUNT(*) hits, COUNT(DISTINCT visitor_id) visitors"
        " FROM events GROUP BY step").fetchall()]
    subs = con.execute("SELECT COUNT(*) n FROM store_subscribers").fetchone()
    return {"pages": pages, "funnel": funnel, "subscribers": subs["n"]}


# ---------- static frontend ----------

def _admin_html(name: str) -> str:
    """The back-office pages get the same icon sprite as the storefront.

    They used to be served straight off disk, which is why they still had
    emoji in them: there was no way to draw an icon. One sprite for every
    surface means the page builder and the store look like the same product.
    """
    html = (config.STOREFRONT_DIR / name).read_text(encoding="utf-8")
    # Same cache-busting the shop and the ops app get. Without it the back
    # office silently runs the previous deploy's JavaScript, which is how a
    # button ends up on the page with nothing wired to it.
    v = asset_version()
    for asset in ("/admin.js", "/theme.js", "/qr-scan.js", "/qr-scan.css"):
        html = html.replace(f'"{asset}"', f'"{asset}?v={v}"')
    return html.replace("<!--ICONS-->", icon_sprite())


@router.get("/admin")
def store_admin_page():
    return HTMLResponse(_admin_html("admin.html"))
