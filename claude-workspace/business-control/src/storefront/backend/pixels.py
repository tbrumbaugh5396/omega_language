"""Marketing pixels: configuration, consent gating and a first-party log.

Three things a merchant actually needs and most platforms only give you two of:

  1. Somewhere to paste the pixel IDs without editing theme code.
  2. A consent gate, so nothing third-party loads until the visitor agrees.
     This is the part that makes the feature legal to ship in the EU/UK, and
     it has to be the default rather than a checkbox someone forgets.
  3. A record of what we told the pixels, held first-party. Ad platforms
     famously disagree with each other; when Meta claims 40 purchases and the
     ledger says 31, this is the tiebreaker.

Snippets are built from an allow-list of known providers plus one escape
hatch for custom HTML. The ID goes through a strict character filter before
it reaches the page — a pixel ID field that accepts `"></script>` is a stored
XSS hole with a marketing label on it.
"""
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import sections as sect
from .api import admin_user, get_con, rate_limit

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS store_pixel_events (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,                  -- meta|tiktok|ga4|... or 'all'
  event TEXT NOT NULL,                     -- PageView|AddToCart|Purchase|…
  value_cents INTEGER DEFAULT 0,
  consent INTEGER DEFAULT 0,               -- did the visitor allow it
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS store_pixel_events_time
  ON store_pixel_events(created_at DESC);
"""

# provider key -> (label, id placeholder, id pattern, docs hint)
PROVIDERS = {
    "meta": ("Meta (Facebook/Instagram)", "123456789012345", r"^\d{6,20}$",
             "Events Manager → Data sources → your pixel"),
    "tiktok": ("TikTok", "CXXXXXXXXXXXXXXXXXXX", r"^[A-Za-z0-9]{10,30}$",
               "TikTok Ads → Assets → Events"),
    "ga4": ("Google Analytics 4", "G-XXXXXXXXXX", r"^G-[A-Z0-9]{6,14}$",
            "GA4 admin → Data streams → Measurement ID"),
    "gads": ("Google Ads", "AW-XXXXXXXXX", r"^AW-[0-9]{6,14}$",
             "Google Ads → Tools → Conversions"),
    "pinterest": ("Pinterest", "2612345678901", r"^\d{10,20}$",
                  "Pinterest Ads → Conversions → Tag"),
    "snap": ("Snapchat", "xxxxxxxx-xxxx-xxxx", r"^[A-Za-z0-9-]{8,50}$",
             "Snap Ads → Events Manager"),
}

# The storefront's own events, mapped to each provider's vocabulary.
EVENT_MAP = {
    "page_view": {"meta": "PageView", "tiktok": "Pageview",
                  "pinterest": "pagevisit", "snap": "PAGE_VIEW"},
    "view_product": {"meta": "ViewContent", "tiktok": "ViewContent",
                     "pinterest": "pagevisit", "snap": "VIEW_CONTENT"},
    "add_to_cart": {"meta": "AddToCart", "tiktok": "AddToCart",
                    "pinterest": "addtocart", "snap": "ADD_CART"},
    "checkout": {"meta": "InitiateCheckout", "tiktok": "InitiateCheckout",
                 "pinterest": "checkout", "snap": "START_CHECKOUT"},
    "purchase": {"meta": "Purchase", "tiktok": "CompletePayment",
                 "pinterest": "checkout", "snap": "PURCHASE"},
    "subscribe": {"meta": "Lead", "tiktok": "Subscribe",
                  "pinterest": "lead", "snap": "SIGN_UP"},
    "enquiry": {"meta": "Lead", "tiktok": "SubmitForm",
                "pinterest": "lead", "snap": "SIGN_UP"},
}

DEFAULT = {
    "enabled": False,
    "consent_required": True,     # nothing third-party loads until they agree
    "consent_text": "We use cookies to measure our ads. You can say no — the "
                    "shop works exactly the same either way.",
    "ids": {},                    # provider -> id
    "events": {k: True for k in EVENT_MAP},
    "custom_head": "",            # escape hatch, admin-only, rendered verbatim
}


def init_tables(con):
    con.executescript(TABLES)


def get_config(con) -> dict:
    row = con.execute("SELECT v FROM store_meta WHERE k='pixels'").fetchone()
    saved = {}
    if row:
        try:
            saved = json.loads(row["v"])
        except ValueError:
            saved = {}
    cfg = {**DEFAULT, **saved}
    cfg["ids"] = {k: v for k, v in (cfg.get("ids") or {}).items()
                  if k in PROVIDERS and v}
    cfg["events"] = {**DEFAULT["events"], **(cfg.get("events") or {})}
    return cfg


def clean_id(provider: str, value: str) -> str:
    """Reject anything that isn't the shape of that provider's id.

    This is the security boundary for the whole feature: these values are
    interpolated into a <script> block, so an unvalidated one is stored XSS.
    """
    value = (value or "").strip()
    if not value:
        return ""
    pattern = PROVIDERS[provider][2]
    if not re.match(pattern, value):
        raise HTTPException(
            400, f"That doesn't look like a {PROVIDERS[provider][0]} ID")
    return value


def snippet(cfg: dict) -> str:
    """The tag block for the storefront <head>.

    Loaders are gated behind window.__pixelConsent so that with consent
    required nothing third-party is even requested until the visitor agrees.
    """
    if not cfg.get("enabled"):
        return ""
    ids = cfg.get("ids") or {}
    if not ids and not cfg.get("custom_head"):
        return ""
    parts = []
    if ids.get("meta"):
        parts.append(
            "!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){"
            "n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};"
            "if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];"
            "t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];"
            "s.parentNode.insertBefore(t,s)}(window,document,'script',"
            "'https://connect.facebook.net/en_US/fbevents.js');"
            f"fbq('init','{ids['meta']}');")
    if ids.get("tiktok"):
        parts.append(
            "!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];"
            "ttq.methods=['page','track','identify','instances','debug','on','off',"
            "'once','ready','alias','group','enableCookie','disableCookie'];"
            "ttq.setAndDefer=function(t,e){t[e]=function(){"
            "t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};"
            "for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);"
            "ttq.load=function(e,n){var r='https://analytics.tiktok.com/i18n/pixel/events.js';"
            "ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=r;ttq._t=ttq._t||{};"
            "ttq._t[e]=+new Date;ttq._o=ttq._o||{};ttq._o[e]=n||{};"
            "var o=d.createElement('script');o.type='text/javascript';o.async=!0;"
            "o.src=r+'?sdkid='+e+'&lib='+t;var a=d.getElementsByTagName('script')[0];"
            "a.parentNode.insertBefore(o,a)};"
            f"ttq.load('{ids['tiktok']}');")
    for key in ("ga4", "gads"):
        if ids.get(key):
            parts.append(
                "window.dataLayer=window.dataLayer||[];"
                "function gtag(){dataLayer.push(arguments)}"
                "gtag('js',new Date());"
                f"gtag('config','{ids[key]}');"
                "var g=document.createElement('script');g.async=1;"
                f"g.src='https://www.googletagmanager.com/gtag/js?id={ids[key]}';"
                "document.head.appendChild(g);")
    if ids.get("pinterest"):
        parts.append(
            "!function(e){if(!window.pintrk){window.pintrk=function(){"
            "window.pintrk.queue.push(Array.prototype.slice.call(arguments))};"
            "var n=window.pintrk;n.queue=[],n.version='3.0';"
            "var t=document.createElement('script');t.async=!0;t.src=e;"
            "var r=document.getElementsByTagName('script')[0];"
            "r.parentNode.insertBefore(t,r)}}"
            "('https://s.pinimg.com/ct/core.js');"
            f"pintrk('load','{ids['pinterest']}');")
    if ids.get("snap"):
        parts.append(
            "(function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function(){"
            "a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};"
            "a.queue=[];var s='script';var r=t.createElement(s);r.async=!0;"
            "r.src=n;var u=t.getElementsByTagName(s)[0];"
            "u.parentNode.insertBefore(r,u)})"
            "(window,document,'https://sc-static.net/scevent.min.js');"
            f"snaptr('init','{ids['snap']}');")
    if not parts and not cfg.get("custom_head"):
        return ""
    loaders = "".join(f"try{{{p}}}catch(e){{}}" for p in parts)
    custom = cfg.get("custom_head") or ""
    gate = "true" if not cfg.get("consent_required") else "false"
    return (
        "<script>window.__pixelConfig=" + json.dumps({
            "ids": ids, "events": cfg["events"], "map": EVENT_MAP,
            "consentRequired": bool(cfg.get("consent_required")),
        }) + ";window.__pixelConsent=" + gate + ";"
        "window.__pixelLoad=function(){if(window.__pixelLoaded)return;"
        "window.__pixelLoaded=1;" + loaders + "};"
        "if(window.__pixelConsent)window.__pixelLoad();</script>" + custom)


# ---------- admin ----------

class PixelBody(BaseModel):
    enabled: bool = False
    consent_required: bool = True
    consent_text: str = ""
    ids: dict = {}
    events: dict = {}
    custom_head: str = ""


@router.get("/api/store/admin/pixels")
def read_pixels(u=Depends(admin_user), con=Depends(get_con)):
    cfg = get_config(con)
    return {**cfg, "providers": {
        k: {"label": v[0], "placeholder": v[1], "hint": v[3]}
        for k, v in PROVIDERS.items()}, "event_keys": list(EVENT_MAP)}


@router.post("/api/store/admin/pixels")
def save_pixels(body: PixelBody, u=Depends(admin_user), con=Depends(get_con)):
    ids = {}
    for k, v in (body.ids or {}).items():
        if k not in PROVIDERS:
            continue
        cleaned = clean_id(k, str(v))
        if cleaned:
            ids[k] = cleaned
    cfg = {
        "enabled": bool(body.enabled),
        "consent_required": bool(body.consent_required),
        "consent_text": sect.esc(body.consent_text or "")[:400]
        or DEFAULT["consent_text"],
        "ids": ids,
        "events": {k: bool(body.events.get(k, True)) for k in EVENT_MAP},
        # Rendered verbatim into <head>, so it is owner-only by policy: the
        # admin permission gate is the control, and it is recorded in the
        # audit log like every other admin write.
        "custom_head": (body.custom_head or "")[:4000],
    }
    con.execute(
        "INSERT INTO store_meta(k,v) VALUES('pixels',?)"
        " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(cfg),))
    con.commit()
    return {"ok": True, "active": list(ids)}


@router.get("/api/store/admin/pixels/log")
def pixel_log(u=Depends(admin_user), con=Depends(get_con)):
    """What we actually told the pixels, first-party. The reconciliation view
    for when an ad platform's numbers don't match the order ledger."""
    rows = con.execute(
        "SELECT event, COUNT(*) n, SUM(consent) consented,"
        " SUM(value_cents) value FROM store_pixel_events"
        " WHERE created_at > ? GROUP BY event ORDER BY n DESC",
        (time.time() - 30 * 86400,)).fetchall()
    orders = con.execute(
        "SELECT COUNT(*) n FROM orders WHERE created_at > ?",
        (time.time() - 30 * 86400,)).fetchone()
    return {"days": 30, "events": [dict(r) for r in rows],
            "orders": orders["n"] if orders else 0}


# ---------- public ----------

class PixelHit(BaseModel):
    event: str
    value_cents: int = 0
    consent: bool = False


@router.post("/api/store/pixel-event")
def record_pixel_event(body: PixelHit, con=Depends(get_con),
                       _rl=Depends(rate_limit)):
    if body.event not in EVENT_MAP:
        raise HTTPException(400, "unknown pixel event")
    con.execute(
        "INSERT INTO store_pixel_events(provider,event,value_cents,consent,"
        " created_at) VALUES('all',?,?,?,?)",
        (body.event, max(0, int(body.value_cents)),
         1 if body.consent else 0, time.time()))
    con.commit()
    return {"ok": True}
