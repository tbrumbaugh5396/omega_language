"""Campaigns and the creatives that run under them.

A campaign is the thing you brief once and then run everywhere: the same
video cut for TikTok, Meta and YouTube, each with its own aspect ratio, its
own copy and its own live link. Ad platforms each hold a slice of that and
none of them holds the whole picture, so this is the one place where a
merchant can see every asset for a push side by side and answer "what is
running where, and did it sell anything".

Attribution without a tracking cookie: each campaign owns a short code and a
discount code. `/c/<code>` records the click and forwards to the landing page
with the discount pre-applied, so orders carrying that discount are the
campaign's — a merchant-checkable number rather than a platform's claim.
"""
import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .api import admin_user, get_con, rate_limit

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS store_campaigns (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,               -- short code behind /c/<code>
  name TEXT NOT NULL,
  objective TEXT DEFAULT 'sales',          -- sales|awareness|launch|retention
  status TEXT DEFAULT 'draft',             -- draft|live|paused|done
  starts REAL DEFAULT 0,
  ends REAL DEFAULT 0,
  budget_cents INTEGER DEFAULT 0,
  spend_cents INTEGER DEFAULT 0,           -- entered by whoever reads the ad accounts
  discount_code TEXT DEFAULT '',           -- how orders get attributed
  landing TEXT DEFAULT '/',
  notes TEXT DEFAULT '',
  clicks INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);

-- One row per platform cut of the campaign. `kind` separates a 9:16 video
-- from a still, because that is the difference that decides where it runs.
CREATE TABLE IF NOT EXISTS store_creatives (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL,
  platform TEXT NOT NULL,                  -- tiktok|meta|youtube|...
  kind TEXT DEFAULT 'video',               -- video|image|carousel|text
  title TEXT DEFAULT '',
  url TEXT DEFAULT '',                     -- where the asset lives
  thumb_media_id INTEGER DEFAULT 0,        -- optional uploaded still
  caption TEXT DEFAULT '',
  status TEXT DEFAULT 'draft',             -- draft|review|live|paused|done
  impressions INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  spend_cents INTEGER DEFAULT 0,
  position INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS store_creatives_campaign
  ON store_creatives(campaign_id, position);
"""

# platform -> (label, the shape it wants, where it runs)
PLATFORMS = {
    "tiktok": ("TikTok", "9:16 video", "In-feed"),
    "meta": ("Meta — Instagram/Facebook", "9:16 or 1:1", "Reels, feed, stories"),
    "youtube": ("YouTube", "16:9 or 9:16 Shorts", "Pre-roll, Shorts"),
    "pinterest": ("Pinterest", "2:3 pin", "Feed"),
    "snap": ("Snapchat", "9:16 video", "Between stories"),
    "email": ("Email", "16:9 still or GIF", "Newsletter"),
    "ooh": ("Out of home", "print / screen", "Fridge clings, posters"),
    "site": ("Our own site", "any", "Hero, banners, journal"),
}
STATUSES = ("draft", "live", "paused", "done")
CREATIVE_STATUSES = ("draft", "review", "live", "paused", "done")
OBJECTIVES = ("sales", "awareness", "launch", "retention")


def init_tables(con):
    con.executescript(TABLES)


def new_code(con) -> str:
    for _ in range(20):
        code = secrets.token_urlsafe(4).replace("_", "").replace("-", "")[:6].lower()
        if code and not con.execute(
                "SELECT 1 FROM store_campaigns WHERE code=?", (code,)).fetchone():
            return code
    return str(int(time.time()))[-6:]


def orders_for(con, discount_code: str, since: float) -> dict:
    """Orders and revenue carrying this campaign's discount code. Reads the
    ledger rather than an ad platform, so the number is ours."""
    if not discount_code:
        return {"orders": 0, "revenue_cents": 0}
    row = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) v FROM orders"
        " WHERE UPPER(COALESCE(discount_code,''))=? AND created_at >= ?",
        (discount_code.upper(), since or 0)).fetchone()
    return {"orders": row["n"], "revenue_cents": row["v"]}


def campaign_json(con, r) -> dict:
    d = dict(r)
    d["link"] = f"/c/{r['code']}"
    creatives = con.execute(
        "SELECT * FROM store_creatives WHERE campaign_id=?"
        " ORDER BY position, id", (r["id"],)).fetchall()
    d["creatives"] = [dict(c) for c in creatives]
    d["platforms"] = sorted({c["platform"] for c in creatives})
    d["live_creatives"] = sum(1 for c in creatives if c["status"] == "live")
    d.update(orders_for(con, r["discount_code"], r["starts"]))
    # Cost per order, the number that decides whether to keep spending.
    spend = r["spend_cents"] or sum(c["spend_cents"] for c in creatives)
    d["spend_cents"] = spend
    d["cpo_cents"] = int(spend / d["orders"]) if d["orders"] else 0
    d["roas"] = round(d["revenue_cents"] / spend, 2) if spend else 0
    return d


# ---------- public: the tracked link ----------

@router.get("/c/{code}")
def campaign_link(code: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    row = con.execute("SELECT * FROM store_campaigns WHERE code=?",
                      (code.lower(),)).fetchone()
    if row is None:
        return RedirectResponse("/", status_code=307)
    con.execute("UPDATE store_campaigns SET clicks=clicks+1 WHERE id=?",
                (row["id"],))
    con.commit()
    dest = row["landing"] or "/"
    join = "&" if "?" in dest else "?"
    parts = [f"utm_source=campaign", f"utm_campaign={row['code']}"]
    if row["discount_code"]:
        parts.append(f"discount={row['discount_code']}")
    return RedirectResponse(f"{dest}{join}{'&'.join(parts)}", status_code=307)


# ---------- admin ----------

@router.get("/api/store/admin/campaigns")
def list_campaigns(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM store_campaigns ORDER BY"
        " CASE status WHEN 'live' THEN 0 WHEN 'draft' THEN 1"
        " WHEN 'paused' THEN 2 ELSE 3 END, created_at DESC").fetchall()
    return {"campaigns": [campaign_json(con, r) for r in rows],
            "platforms": {k: {"label": v[0], "shape": v[1], "where": v[2]}
                          for k, v in PLATFORMS.items()},
            "statuses": list(STATUSES),
            "creative_statuses": list(CREATIVE_STATUSES),
            "objectives": list(OBJECTIVES)}


class CampaignBody(BaseModel):
    name: str = ""
    objective: str = "sales"
    status: str = "draft"
    starts: float = 0
    ends: float = 0
    budget_cents: int = 0
    spend_cents: int = 0
    discount_code: str = ""
    landing: str = "/"
    notes: str = ""


def _clean_landing(v: str) -> str:
    """Only same-site paths. A campaign link that can be pointed at an
    arbitrary host is an open redirect wearing a marketing hat."""
    v = (v or "/").strip()
    if not v.startswith("/") or v.startswith("//"):
        return "/"
    return v[:200]


@router.post("/api/store/admin/campaigns")
def add_campaign(body: CampaignBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    if not body.name.strip():
        raise HTTPException(400, "a campaign needs a name")
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    if body.objective not in OBJECTIVES:
        raise HTTPException(400, f"objective must be one of {OBJECTIVES}")
    cur = con.execute(
        "INSERT INTO store_campaigns(code,name,objective,status,starts,ends,"
        " budget_cents,spend_cents,discount_code,landing,notes,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_code(con), body.name.strip()[:120], body.objective, body.status,
         body.starts, body.ends, max(0, body.budget_cents),
         max(0, body.spend_cents),
         re.sub(r"[^A-Za-z0-9_-]", "", body.discount_code)[:40].upper(),
         _clean_landing(body.landing), body.notes.strip()[:500], time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.patch("/api/store/admin/campaigns/{cid}")
def edit_campaign(cid: int, body: CampaignBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    con.execute(
        "UPDATE store_campaigns SET name=?,objective=?,status=?,starts=?,"
        " ends=?,budget_cents=?,spend_cents=?,discount_code=?,landing=?,"
        " notes=? WHERE id=?",
        (body.name.strip()[:120], body.objective, body.status, body.starts,
         body.ends, max(0, body.budget_cents), max(0, body.spend_cents),
         re.sub(r"[^A-Za-z0-9_-]", "", body.discount_code)[:40].upper(),
         _clean_landing(body.landing), body.notes.strip()[:500], cid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/campaigns/{cid}")
def del_campaign(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_creatives WHERE campaign_id=?", (cid,))
    con.execute("DELETE FROM store_campaigns WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}


class CreativeBody(BaseModel):
    campaign_id: int = 0
    platform: str = "tiktok"
    kind: str = "video"
    title: str = ""
    url: str = ""
    caption: str = ""
    status: str = "draft"
    impressions: int = 0
    clicks: int = 0
    spend_cents: int = 0


def _clean_url(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if not re.match(r"^(https?://|/)", v):
        raise HTTPException(400, "asset link must start with http(s):// or /")
    return v[:400]


@router.post("/api/store/admin/creatives")
def add_creative(body: CreativeBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    if body.platform not in PLATFORMS:
        raise HTTPException(400, "unknown platform")
    if body.status not in CREATIVE_STATUSES:
        raise HTTPException(400, "unknown creative status")
    if not con.execute("SELECT 1 FROM store_campaigns WHERE id=?",
                       (body.campaign_id,)).fetchone():
        raise HTTPException(404, "no such campaign")
    pos = con.execute(
        "SELECT COALESCE(MAX(position),0)+1 p FROM store_creatives"
        " WHERE campaign_id=?", (body.campaign_id,)).fetchone()["p"]
    cur = con.execute(
        "INSERT INTO store_creatives(campaign_id,platform,kind,title,url,"
        " caption,status,impressions,clicks,spend_cents,position,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.campaign_id, body.platform, body.kind, body.title.strip()[:140],
         _clean_url(body.url), body.caption.strip()[:600], body.status,
         max(0, body.impressions), max(0, body.clicks),
         max(0, body.spend_cents), pos, time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.patch("/api/store/admin/creatives/{crid}")
def edit_creative(crid: int, body: CreativeBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if body.status not in CREATIVE_STATUSES:
        raise HTTPException(400, "unknown creative status")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, "unknown platform")
    con.execute(
        "UPDATE store_creatives SET platform=?,kind=?,title=?,url=?,"
        " caption=?,status=?,impressions=?,clicks=?,spend_cents=?"
        " WHERE id=?",
        (body.platform, body.kind, body.title.strip()[:140],
         _clean_url(body.url), body.caption.strip()[:600], body.status,
         max(0, body.impressions), max(0, body.clicks),
         max(0, body.spend_cents), crid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/creatives/{crid}")
def del_creative(crid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_creatives WHERE id=?", (crid,))
    con.commit()
    return {"ok": True}
