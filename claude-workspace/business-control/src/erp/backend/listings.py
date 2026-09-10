"""Listings and reviews: what the map says about you, and what people
say under it.

A business's Google listing is read more often than its website, and its
Yelp page more often than either by somebody choosing where to eat. Both
are edited in a portal nobody opens until the hours are wrong. So the
profile lives here — name, phone, website, address, hours, description —
and Google's copy is pulled from it and pushed back to it. Yelp's is
pulled and compared: Yelp offers no API for editing a listing, and the
screen says so rather than pretending a button does something.

Reviews come into one inbox from both. Google's can be answered from
here, through the same API that reads them. Yelp's public API returns
three excerpts and takes no reply, so each of those links to its page,
which is the honest version of "manage Yelp reviews". Asking for a
review — the thing that actually moves a rating — is a link emailed to
a customer from the address book, logged like every other email.

Every outside call goes through integrations._req, where tests stub it.
"""
import json
import time
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, mailer
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS business_listing (
  id INTEGER PRIMARY KEY,                  -- always 1
  name TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  website TEXT DEFAULT '',
  address TEXT DEFAULT '',
  city TEXT DEFAULT '',
  region TEXT DEFAULT '',
  postal TEXT DEFAULT '',
  country TEXT DEFAULT '',
  description TEXT DEFAULT '',
  category TEXT DEFAULT '',
  hours TEXT DEFAULT '{}',                 -- JSON {mon: [["09:00","17:00"]], ...}
  maps_url TEXT DEFAULT '',
  yelp_url TEXT DEFAULT '',
  updated_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews_inbox (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,                  -- google_business | yelp
  external_id TEXT NOT NULL,
  author TEXT DEFAULT '',
  rating INTEGER DEFAULT 0,                -- 1..5
  body TEXT DEFAULT '',
  url TEXT DEFAULT '',
  at REAL DEFAULT 0,
  reply TEXT DEFAULT '',
  replied_at REAL DEFAULT 0,
  pulled_at REAL DEFAULT 0,
  UNIQUE(provider, external_id)
);

CREATE TABLE IF NOT EXISTS review_requests (
  id INTEGER PRIMARY KEY,
  to_name TEXT DEFAULT '',
  to_email TEXT NOT NULL,
  link TEXT DEFAULT '',
  status TEXT DEFAULT '',
  sent_at REAL NOT NULL,
  by_name TEXT DEFAULT ''
);
"""

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_GDAY = {"mon": "MONDAY", "tue": "TUESDAY", "wed": "WEDNESDAY", "thu": "THURSDAY",
         "fri": "FRIDAY", "sat": "SATURDAY", "sun": "SUNDAY"}
_GDAY_BACK = {v: k for k, v in _GDAY.items()}
_GSTAR = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
GBI = "https://mybusinessbusinessinformation.googleapis.com/v1"
GBA = "https://mybusinessaccountmanagement.googleapis.com/v1"
GB4 = "https://mybusiness.googleapis.com/v4"


def init_tables(con):
    con.executescript(TABLES)
    if not con.execute("SELECT 1 FROM business_listing WHERE id=1").fetchone():
        from .main import CFG
        con.execute("INSERT INTO business_listing(id,name,updated_at) VALUES(1,?,?)",
                    (CFG.get("brand_name") or "", time.time()))
    con.commit()


def _office(user) -> bool:
    """A listing is the shop's public copy and a review is a reply in
    its name, so this is the marketing and content grant."""
    return auth.office(user, "settings", "marketing", "content")

def _may_see(user) -> bool:
    return _office(user) or user["role"] == "employee"


def profile(con) -> dict:
    r = dict(con.execute("SELECT * FROM business_listing WHERE id=1").fetchone())
    try:
        r["hours"] = json.loads(r["hours"] or "{}")
    except ValueError:
        r["hours"] = {}
    return r


def _clean_hours(h) -> dict:
    out = {}
    for d in DAYS:
        spans = []
        for span in (h or {}).get(d) or []:
            if isinstance(span, (list, tuple)) and len(span) == 2 \
                    and all(isinstance(x, str) and len(x) == 5 and x[2] == ":"
                            for x in span):
                spans.append([span[0], span[1]])
        if spans:
            out[d] = spans
    return out


def save_profile(con, fields: dict) -> dict:
    cur = profile(con)
    cols = ("name", "phone", "website", "address", "city", "region", "postal",
            "country", "description", "category", "maps_url", "yelp_url")
    vals = {k: str(fields.get(k, cur[k]) or "").strip()[:400] for k in cols}
    hours = _clean_hours(fields["hours"]) if "hours" in fields else cur["hours"]
    con.execute(
        "UPDATE business_listing SET name=?, phone=?, website=?, address=?, city=?,"
        " region=?, postal=?, country=?, description=?, category=?, maps_url=?,"
        " yelp_url=?, hours=?, updated_at=? WHERE id=1",
        (*[vals[k] for k in cols], json.dumps(hours), time.time()))
    con.commit()
    return profile(con)


# ---------- Google Business Profile ----------

def _gtok(con) -> str:
    from .main import CFG
    tok = IG.access_token(con, "google_business", CFG)
    if not tok:
        raise HTTPException(400, "reconnect Google Business Profile")
    return tok


def _gh(con) -> dict:
    return {"Authorization": f"Bearer {_gtok(con)}"}


def _verify_google(con, tok, c) -> tuple:
    ok, d = IG._req(f"{GBA}/accounts", headers={"Authorization": f"Bearer {tok}"})
    if not ok:
        return False, str(d)
    accts = (d.get("accounts") or []) if isinstance(d, dict) else []
    return True, (accts[0].get("accountName") if accts else "connected")


IG.VERIFIERS["google_business"] = _verify_google


def google_locations(con) -> list:
    """Every location on every account the token can see, so the office
    picks the one this business is."""
    h = _gh(con)
    ok, d = IG._req(f"{GBA}/accounts", headers=h)
    if not ok:
        raise HTTPException(400, f"Google said: {d}")
    out = []
    for a in (d.get("accounts") or []) if isinstance(d, dict) else []:
        ok2, ld = IG._req(f"{GBI}/{a['name']}/locations?readMask=name,title,"
                          "storefrontAddress&pageSize=50", headers=h)
        if not ok2:
            continue
        for loc in (ld.get("locations") or []) if isinstance(ld, dict) else []:
            addr = loc.get("storefrontAddress") or {}
            out.append({"name": loc.get("name"), "account": a["name"],
                        "title": loc.get("title", ""),
                        "where": ", ".join(x for x in (
                            *(addr.get("addressLines") or []), addr.get("locality", ""))
                            if x)})
    return out


def _location(con) -> tuple:
    s = IG.settings(con, "google_business")
    loc = s.get("location", "")
    if not loc:
        raise HTTPException(400, "pick the Google location first")
    return loc, s.get("_account", "")


def pull_google(con) -> dict:
    loc, _ = _location(con)
    ok, d = IG._req(f"{GBI}/{loc}?readMask=name,title,phoneNumbers,websiteUri,"
                    "regularHours,storefrontAddress,profile,categories",
                    headers=_gh(con))
    if not ok:
        raise HTTPException(400, f"Google said: {d}")
    addr = d.get("storefrontAddress") or {}
    hours = {}
    for p in ((d.get("regularHours") or {}).get("periods") or []):
        day = _GDAY_BACK.get(p.get("openDay"), "")
        o, c = p.get("openTime") or {}, p.get("closeTime") or {}
        if day:
            hours.setdefault(day, []).append(
                [f"{int(o.get('hours', 0)):02d}:{int(o.get('minutes', 0)):02d}",
                 f"{int(c.get('hours', 0)):02d}:{int(c.get('minutes', 0)):02d}"])
    fields = {
        "name": d.get("title", ""),
        "phone": (d.get("phoneNumbers") or {}).get("primaryPhone", ""),
        "website": d.get("websiteUri", ""),
        "address": " ".join(addr.get("addressLines") or []),
        "city": addr.get("locality", ""), "region": addr.get("administrativeArea", ""),
        "postal": addr.get("postalCode", ""), "country": addr.get("regionCode", ""),
        "description": (d.get("profile") or {}).get("description", ""),
        "category": ((d.get("categories") or {}).get("primaryCategory") or {}).get("displayName", ""),
        "hours": hours,
    }
    IG.log(con, "google_business", "pull_listing", True, fields["name"])
    return save_profile(con, {k: v for k, v in fields.items() if v or k == "hours"})


def push_google(con) -> dict:
    """Phone, website, hours, description: the fields Google lets an API
    change without re-verification. The name and address are not among
    them — a changed address on a verified listing goes through Google's
    own review, so those are shown as Google's and edited there."""
    loc, _ = _location(con)
    p = profile(con)
    periods = []
    for day, spans in p["hours"].items():
        for o, c in spans:
            periods.append({"openDay": _GDAY[day], "closeDay": _GDAY[day],
                            "openTime": {"hours": int(o[:2]), "minutes": int(o[3:])},
                            "closeTime": {"hours": int(c[:2]), "minutes": int(c[3:])}})
    body = {"phoneNumbers": {"primaryPhone": p["phone"]},
            "websiteUri": p["website"],
            "regularHours": {"periods": periods},
            "profile": {"description": p["description"][:750]}}
    ok, d = IG._json_req(f"{GBI}/{loc}?updateMask=phoneNumbers,websiteUri,"
                         "regularHours,profile", "PATCH", _gh(con), body)
    IG.log(con, "google_business", "push_listing", ok, "" if ok else str(d)[:200])
    if not ok:
        raise HTTPException(400, f"Google said: {d}")
    return {"ok": True}


def _upsert_review(con, provider: str, ext: str, author: str, rating: int,
                   body: str, url: str, at: float, reply: str = "",
                   replied_at: float = 0) -> None:
    con.execute(
        "INSERT INTO reviews_inbox(provider,external_id,author,rating,body,url,at,"
        " reply,replied_at,pulled_at) VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(provider, external_id) DO UPDATE SET author=excluded.author,"
        " rating=excluded.rating, body=excluded.body, url=excluded.url,"
        " reply=CASE WHEN excluded.reply<>'' THEN excluded.reply ELSE reviews_inbox.reply END,"
        " replied_at=CASE WHEN excluded.replied_at>0 THEN excluded.replied_at"
        " ELSE reviews_inbox.replied_at END, pulled_at=excluded.pulled_at",
        (provider, ext, author[:120], int(rating or 0), body[:4000], url[:400], at,
         reply[:4000], replied_at, time.time()))


def _iso(s: str) -> float:
    try:
        return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return time.time()


def pull_google_reviews(con) -> dict:
    loc, acct = _location(con)
    # v4 wants accounts/{a}/locations/{l}; v1 named the location alone.
    path = f"{acct}/{loc}" if acct and not loc.startswith("accounts/") else loc
    ok, d = IG._req(f"{GB4}/{path}/reviews?pageSize=50", headers=_gh(con))
    if not ok:
        raise HTTPException(400, f"Google said: {d}")
    n = 0
    for r in (d.get("reviews") or []) if isinstance(d, dict) else []:
        rep = r.get("reviewReply") or {}
        _upsert_review(con, "google_business", str(r.get("reviewId") or r.get("name")),
                       (r.get("reviewer") or {}).get("displayName", "A customer"),
                       _GSTAR.get(r.get("starRating"), 0), r.get("comment", ""),
                       "", _iso(r.get("createTime", "")),
                       rep.get("comment", ""), _iso(rep["updateTime"]) if rep else 0)
        n += 1
    con.commit()
    IG.log(con, "google_business", "pull_reviews", True, f"{n} review(s)")
    return {"ok": True, "pulled": n}


def reply_google(con, review_id: int, text: str) -> dict:
    r = con.execute("SELECT * FROM reviews_inbox WHERE id=?", (review_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such review")
    if r["provider"] != "google_business":
        raise HTTPException(400, "Yelp takes no reply by API — open the review "
                                 "on Yelp and answer it there")
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "say something")
    loc, acct = _location(con)
    path = f"{acct}/{loc}" if acct and not loc.startswith("accounts/") else loc
    ok, d = IG._json_req(f"{GB4}/{path}/reviews/{r['external_id']}/reply", "PUT",
                         _gh(con), {"comment": text[:4000]})
    IG.log(con, "google_business", "reply_review", ok, "" if ok else str(d)[:200])
    if not ok:
        raise HTTPException(400, f"Google said: {d}")
    con.execute("UPDATE reviews_inbox SET reply=?, replied_at=? WHERE id=?",
                (text[:4000], time.time(), review_id))
    con.commit()
    return {"ok": True}


# ---------- Yelp ----------

def _check_yelp(c: dict) -> tuple:
    bid = urllib.parse.quote(c.get("business_id", ""))
    ok, d = IG._req(f"https://api.yelp.com/v3/businesses/{bid}",
                    headers={"Authorization": f"Bearer {c.get('api_key','')}"})
    if not ok:
        return False, str(d)
    return True, (d.get("name") if isinstance(d, dict) else None) or c.get("business_id", "")


IG.CHECKS["yelp"] = _check_yelp


def _yelp(con) -> tuple:
    c = IG.creds(con, "yelp")
    if not c:
        raise HTTPException(400, "connect Yelp first")
    s = IG.settings(con, "yelp")
    return ({"Authorization": f"Bearer {c.get('api_key','')}"},
            urllib.parse.quote(s.get("business_id", "")))


def pull_yelp(con) -> dict:
    """Yelp's listing, beside ours — not into ours, because Yelp's copy
    cannot be written back and a merge nobody can push is confusing."""
    h, bid = _yelp(con)
    ok, d = IG._req(f"https://api.yelp.com/v3/businesses/{bid}", headers=h)
    if not ok:
        raise HTTPException(400, f"Yelp said: {d}")
    loc = d.get("location") or {}
    hours = {}
    for blk in ((d.get("hours") or [{}])[0]).get("open") or []:
        day = DAYS[int(blk.get("day", 0))]
        s, e = blk.get("start", "0000"), blk.get("end", "0000")
        hours.setdefault(day, []).append([f"{s[:2]}:{s[2:]}", f"{e[:2]}:{e[2:]}"])
    out = {"name": d.get("name", ""), "phone": d.get("display_phone", ""),
           "address": " ".join(loc.get("display_address") or []),
           "rating": d.get("rating"), "review_count": d.get("review_count"),
           "url": d.get("url", ""), "hours": hours,
           "categories": ", ".join(c.get("title", "") for c in d.get("categories") or [])}
    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES('yelp_listing',?)",
                (json.dumps(out),))
    if out["url"]:
        con.execute("UPDATE business_listing SET yelp_url=? WHERE id=1", (out["url"],))
    con.commit()
    IG.log(con, "yelp", "pull_listing", True, out["name"])
    return out


def pull_yelp_reviews(con) -> dict:
    h, bid = _yelp(con)
    ok, d = IG._req(f"https://api.yelp.com/v3/businesses/{bid}/reviews?sort_by=newest",
                    headers=h)
    if not ok:
        raise HTTPException(400, f"Yelp said: {d}")
    n = 0
    for r in (d.get("reviews") or []) if isinstance(d, dict) else []:
        _upsert_review(con, "yelp", str(r.get("id")),
                       (r.get("user") or {}).get("name", "A Yelper"),
                       int(r.get("rating") or 0), r.get("text", ""), r.get("url", ""),
                       _iso(r.get("time_created", "").replace(" ", "T")))
        n += 1
    con.commit()
    IG.log(con, "yelp", "pull_reviews", True, f"{n} review(s)")
    return {"ok": True, "pulled": n}


# ---------- asking ----------

def review_link(con) -> str:
    s = IG.settings(con, "google_business")
    if s.get("place_id"):
        return f"https://search.google.com/local/writereview?placeid={s['place_id']}"
    p = profile(con)
    return p["maps_url"] or p["yelp_url"] or ""


def ask_for_review(con, cfg, by, to_email: str, to_name: str = "") -> dict:
    link = review_link(con)
    if not link:
        raise HTTPException(400, "set a place id on Google Business Profile, or a "
                                 "Maps link on the profile, so there is somewhere "
                                 "to send them")
    to_email = (to_email or "").strip()
    if "@" not in to_email:
        raise HTTPException(400, "an email address")
    p = profile(con)
    shop = p["name"] or cfg.get("brand_name") or "us"
    first = (to_name or "").strip().split(" ")[0]
    text = (f"Hi{(' ' + first) if first else ''},\n\nThank you for coming to {shop}. "
            "If you have a minute, a review helps the next person find us:\n\n"
            f"{link}\n\nWith thanks,\n{shop}")
    status = mailer.send_logged(con, cfg, to_email, f"How was {shop}?", text,
                                "review_request")
    con.execute("INSERT INTO review_requests(to_name,to_email,link,status,sent_at,"
                " by_name) VALUES(?,?,?,?,?,?)",
                ((to_name or "")[:120], to_email[:200], link, status or "",
                 time.time(), by["name"]))
    con.commit()
    return {"ok": True, "status": status, "link": link}


# ---------- routes ----------

router = APIRouter()

from .main import CFG, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/listings")
def listings_page(user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "listings"}
    y = con.execute("SELECT v FROM store_meta WHERE k='yelp_listing'").fetchone()
    reviews = [dict(r) for r in con.execute(
        "SELECT * FROM reviews_inbox ORDER BY at DESC LIMIT 200").fetchall()]
    counts = {}
    for r in reviews:
        c = counts.setdefault(r["provider"], {"n": 0, "sum": 0, "unanswered": 0})
        c["n"] += 1
        c["sum"] += r["rating"]
        if not r["reply"] and r["provider"] == "google_business":
            c["unanswered"] += 1
    return {"profile": profile(con), "connections": list(status.values()),
            "yelp": json.loads(y["v"]) if y else None,
            "reviews": reviews,
            "summary": {k: {**v, "avg": round(v["sum"] / v["n"], 1) if v["n"] else 0}
                        for k, v in counts.items()},
            "requests": [dict(r) for r in con.execute(
                "SELECT * FROM review_requests ORDER BY id DESC LIMIT 30").fetchall()],
            "review_link": review_link(con), "days": list(DAYS)}


class ProfileBody(BaseModel):
    name: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    postal: str | None = None
    country: str | None = None
    description: str | None = None
    category: str | None = None
    maps_url: str | None = None
    yelp_url: str | None = None
    hours: dict | None = None


@router.post("/api/listings/profile")
def listings_profile(body: ProfileBody, user=Depends(current_user),
                     con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    return save_profile(con, fields)


@router.get("/api/listings/google_business/locations")
def listings_glocs(user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return {"locations": google_locations(con)}


class LocationBody(BaseModel):
    location: str
    account: str = ""


@router.post("/api/listings/google_business/location")
def listings_gloc(body: LocationBody, user=Depends(current_user),
                  con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    IG.save_settings(con, "google_business", {"location": body.location})
    row = con.execute("SELECT settings FROM integrations WHERE provider='google_business'"
                      ).fetchone()
    s = json.loads(row["settings"] or "{}")
    s["_account"] = body.account
    con.execute("UPDATE integrations SET settings=? WHERE provider='google_business'",
                (json.dumps(s),))
    con.commit()
    return {"ok": True}


@router.post("/api/listings/{name}/pull")
def listings_pull(name: str, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if name == "google_business":
        return pull_google(con)
    if name == "yelp":
        return pull_yelp(con)
    raise HTTPException(404, "no such listing")


@router.post("/api/listings/google_business/push")
def listings_push(user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return push_google(con)


@router.post("/api/listings/{name}/reviews/pull")
def listings_reviews_pull(name: str, user=Depends(current_user),
                          con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if name == "google_business":
        return pull_google_reviews(con)
    if name == "yelp":
        return pull_yelp_reviews(con)
    raise HTTPException(404, "no such listing")


class ReplyBody(BaseModel):
    text: str


@router.post("/api/listings/reviews/{rid}/reply")
def listings_reply(rid: int, body: ReplyBody, user=Depends(current_user),
                   con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return reply_google(con, rid, body.text)


class AskBody(BaseModel):
    email: str
    name: str = ""


@router.post("/api/listings/ask")
def listings_ask(body: AskBody, user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "staff only")
    return ask_for_review(con, CFG, user, body.email, body.name)
