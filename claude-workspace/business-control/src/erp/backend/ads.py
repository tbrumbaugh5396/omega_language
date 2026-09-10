"""Advertising: what each platform was paid and what it returned.

One ledger, many platforms. Facebook, Instagram, YouTube, TikTok, X,
Reddit, Snapchat, LinkedIn and Twitch each have an ads manager with its
own report, and the question a small business actually asks — "what did
we spend this month and where did it go" — has no screen anywhere,
because each platform only knows about itself. This is that screen.

The ledger is READ from the platforms, never written to them. Nothing
here creates a campaign or spends a cent; the platforms' own managers are
better at that, and a wrong click there costs money in a way a wrong
click here never can. What comes in is each campaign's status, budget,
spend, impressions and clicks over a window, upserted by the platform's
own campaign id so a pull is safe to repeat.

Two things follow from spend being here rather than in nine tabs:

  * It can be filed. A platform's spend for a window becomes an expense
    in the advertising category, through the same table the phone bill
    goes through, so the tax summary already knows about it.
  * It can be typed. Twitch ads are bought through Amazon Ads, which has
    no self-serve API; a flyer run or a local paper has none at all. A
    manual row sits in the same ledger as a pulled one, marked as typed,
    so the total is the whole total.

Every platform call goes through integrations._req, which is where the
tests swap the network for a stub.
"""
import json
import time
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS ad_campaigns (
  id INTEGER PRIMARY KEY,
  platform TEXT NOT NULL,                  -- PLATFORMS key
  external_id TEXT NOT NULL,               -- the platform's id, or manual:<n>
  name TEXT NOT NULL,
  status TEXT DEFAULT '',                  -- as the platform says it
  objective TEXT DEFAULT '',
  daily_budget_cents INTEGER DEFAULT 0,
  spend_cents INTEGER DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  results INTEGER DEFAULT 0,               -- conversions / leads, where reported
  currency TEXT DEFAULT 'USD',
  window_from TEXT DEFAULT '',             -- YYYY-MM-DD
  window_to TEXT DEFAULT '',
  source TEXT DEFAULT 'pulled',            -- pulled | manual
  note TEXT DEFAULT '',
  synced_at REAL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(platform, external_id)
);
CREATE INDEX IF NOT EXISTS ad_campaigns_platform ON ad_campaigns(platform);
"""

# The order is the order of the screen. A platform with no provider is
# typed, not pulled, and the screen says why.
PLATFORMS = [
    {"key": "meta_ads", "label": "Facebook & Instagram", "provider": "meta_ads"},
    {"key": "google_ads", "label": "YouTube & Google", "provider": "google_ads"},
    {"key": "tiktok_ads", "label": "TikTok", "provider": "tiktok_ads"},
    {"key": "linkedin_ads", "label": "LinkedIn", "provider": "linkedin_ads"},
    {"key": "x_ads", "label": "X", "provider": "x_ads"},
    {"key": "reddit_ads", "label": "Reddit", "provider": "reddit_ads"},
    {"key": "snapchat_ads", "label": "Snapchat", "provider": "snapchat_ads"},
    {"key": "twitch", "label": "Twitch", "provider": None,
     "note": "Twitch ads are bought through Amazon Ads, which has no "
             "self-serve API. Type what you spent."},
    {"key": "other", "label": "Everything else", "provider": None,
     "note": "Print, radio, a sponsored newsletter, a sign. Typed."},
]
PLATFORM_KEYS = {p["key"] for p in PLATFORMS}
WINDOW_DAYS = 30


def init_tables(con):
    con.executescript(TABLES)
    # The category the ledger files into. Added here as well as in the
    # expense defaults so a tenant stood up before this existed has it.
    have = con.execute("SELECT 1 FROM expense_categories WHERE code='advertising'"
                       ).fetchone()
    if not have:
        n = con.execute("SELECT COUNT(*) AS n FROM expense_categories"
                        ).fetchone()["n"]
        con.execute(
            "INSERT INTO expense_categories(code,label,deductible,default_pct,"
            " hint,position) VALUES('advertising','Advertising',1,100,"
            " 'ad platforms, print, sponsorships — the ad ledger files here',?)",
            (n,))
    con.commit()


def _window() -> tuple:
    now = time.time()
    return (time.strftime("%Y-%m-%d", time.localtime(now - WINDOW_DAYS * 86400)),
            time.strftime("%Y-%m-%d", time.localtime(now)))


def _office(user) -> bool:
    """The ledger is marketing's money: whoever runs the campaigns, and
    whoever answers for what they cost."""
    return auth.office(user, "settings", "marketing", "finance")

def _may_see(user) -> bool:
    return _office(user) or user["role"] in ("employee",)


# ---------- the platforms, one reader each ----------
# Each returns a list of campaign dicts with the keys the ledger stores,
# or raises with the platform's own words. Spend is normalised to cents.

def _cents(x) -> int:
    try:
        return int(round(float(x or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _int(x) -> int:
    try:
        return int(float(x or 0))
    except (TypeError, ValueError):
        return 0


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _meta(con, c: dict, s: dict) -> list:
    acct = str(s.get("ad_account_id", "")).strip()
    if not acct:
        raise HTTPException(400, "set the Meta ad account id first")
    if not acct.startswith("act_"):
        acct = "act_" + acct
    tok = c.get("access_token", "")
    q = urllib.parse.urlencode({
        "fields": "id,name,status,objective,daily_budget,"
                  "insights.date_preset(last_30d){spend,impressions,clicks,actions}",
        "limit": 200, "access_token": tok})
    ok, d = IG._req(f"https://graph.facebook.com/v19.0/{acct}/campaigns?{q}")
    if not ok:
        raise HTTPException(400, f"Meta said: {d}")
    out = []
    for cp in (d.get("data") or []) if isinstance(d, dict) else []:
        ins = ((cp.get("insights") or {}).get("data") or [{}])[0]
        results = sum(_int(a.get("value")) for a in (ins.get("actions") or [])
                      if a.get("action_type") in ("lead", "purchase",
                                                  "onsite_conversion.messaging_first_reply"))
        out.append({"external_id": str(cp.get("id")), "name": cp.get("name", ""),
                    "status": (cp.get("status") or "").lower(),
                    "objective": (cp.get("objective") or "").lower(),
                    "daily_budget_cents": _int(cp.get("daily_budget")),
                    "spend_cents": _cents(ins.get("spend")),
                    "impressions": _int(ins.get("impressions")),
                    "clicks": _int(ins.get("clicks")), "results": results})
    return out


def _google(con, c: dict, s: dict) -> list:
    cid = str(s.get("customer_id", "")).replace("-", "").strip()
    dev = c.get("developer_token", "")
    if not cid or not dev:
        raise HTTPException(400, "set the Google Ads customer id and "
                                 "developer token first")
    from .main import CFG
    tok = IG.access_token(con, "google_ads", CFG)
    gaql = ("SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, campaign_budget.amount_micros, "
            "metrics.cost_micros, metrics.impressions, metrics.clicks, "
            "metrics.conversions FROM campaign WHERE segments.date DURING "
            "LAST_30_DAYS")
    ok, d = IG._json_req(
        f"https://googleads.googleapis.com/v17/customers/{cid}/googleAds:search",
        "POST", {**_bearer(tok), "developer-token": dev,
                 "login-customer-id": cid}, {"query": gaql})
    if not ok:
        raise HTTPException(400, f"Google Ads said: {d}")
    out = []
    for r in (d.get("results") or []) if isinstance(d, dict) else []:
        cp, m = r.get("campaign") or {}, r.get("metrics") or {}
        out.append({"external_id": str(cp.get("id")), "name": cp.get("name", ""),
                    "status": (cp.get("status") or "").lower(),
                    "objective": (cp.get("advertisingChannelType") or "").lower(),
                    "daily_budget_cents": _int(
                        (r.get("campaignBudget") or {}).get("amountMicros")) // 10000,
                    "spend_cents": _int(m.get("costMicros")) // 10000,
                    "impressions": _int(m.get("impressions")),
                    "clicks": _int(m.get("clicks")),
                    "results": _int(m.get("conversions"))})
    return out


def _tiktok(con, c: dict, s: dict) -> list:
    adv = s.get("advertiser_id", "")
    h = {"Access-Token": c.get("token", "")}
    frm, to = _window()
    q = urllib.parse.urlencode({
        "advertiser_id": adv, "report_type": "BASIC", "data_level": "AUCTION_CAMPAIGN",
        "dimensions": json.dumps(["campaign_id"]),
        "metrics": json.dumps(["campaign_name", "spend", "impressions", "clicks",
                               "conversion"]),
        "start_date": frm, "end_date": to, "page_size": 200})
    ok, d = IG._req("https://business-api.tiktok.com/open_api/v1.3/report/"
                    f"integrated/get/?{q}", headers=h)
    if not ok or not isinstance(d, dict) or d.get("code") not in (0, None):
        raise HTTPException(400, f"TikTok said: {d}")
    out = []
    for r in ((d.get("data") or {}).get("list") or []):
        dims, m = r.get("dimensions") or {}, r.get("metrics") or {}
        out.append({"external_id": str(dims.get("campaign_id")),
                    "name": m.get("campaign_name", ""), "status": "",
                    "objective": "", "daily_budget_cents": 0,
                    "spend_cents": _cents(m.get("spend")),
                    "impressions": _int(m.get("impressions")),
                    "clicks": _int(m.get("clicks")),
                    "results": _int(m.get("conversion"))})
    return out


def _linkedin(con, c: dict, s: dict) -> list:
    acct = str(s.get("account_id", "")).strip()
    if not acct:
        raise HTTPException(400, "set the LinkedIn ad account id first")
    from .main import CFG
    tok = IG.access_token(con, "linkedin_ads", CFG)
    h = {**_bearer(tok), "Linkedin-Version": "202401",
         "X-Restli-Protocol-Version": "2.0.0"}
    ok, d = IG._req(f"https://api.linkedin.com/rest/adAccounts/{acct}/adCampaigns"
                    "?q=search&count=200", headers=h)
    if not ok:
        raise HTTPException(400, f"LinkedIn said: {d}")
    frm, to = _window()
    fy, fm, fd = (int(x) for x in frm.split("-"))
    ty, tm, td = (int(x) for x in to.split("-"))
    rng = (f"(start:(year:{fy},month:{fm},day:{fd}),"
           f"end:(year:{ty},month:{tm},day:{td}))")
    ok2, a = IG._req("https://api.linkedin.com/rest/adAnalytics?q=analytics"
                     f"&pivot=CAMPAIGN&timeGranularity=ALL&dateRange={rng}"
                     f"&accounts=List(urn%3Ali%3AsponsoredAccount%3A{acct})"
                     "&fields=costInLocalCurrency,impressions,clicks,"
                     "externalWebsiteConversions,pivotValues", headers=h)
    stats = {}
    if ok2 and isinstance(a, dict):
        for e in a.get("elements") or []:
            for pv in e.get("pivotValues") or []:
                stats[pv.rsplit(":", 1)[-1]] = e
    out = []
    for cp in (d.get("elements") or []) if isinstance(d, dict) else []:
        cid = str(cp.get("id"))
        st = stats.get(cid, {})
        out.append({"external_id": cid, "name": cp.get("name", ""),
                    "status": (cp.get("status") or "").lower(),
                    "objective": (cp.get("objectiveType") or "").lower(),
                    "daily_budget_cents": _cents(
                        (cp.get("dailyBudget") or {}).get("amount")),
                    "spend_cents": _cents(st.get("costInLocalCurrency")),
                    "impressions": _int(st.get("impressions")),
                    "clicks": _int(st.get("clicks")),
                    "results": _int(st.get("externalWebsiteConversions"))})
    return out


def _x(con, c: dict, s: dict) -> list:
    acct = str(s.get("ads_account_id", "")).strip()
    if not acct:
        raise HTTPException(400, "set the X ads account id first")
    from .main import CFG
    tok = IG.access_token(con, "x_ads", CFG)
    ok, d = IG._req(f"https://ads-api.x.com/12/accounts/{acct}/campaigns?count=200",
                    headers=_bearer(tok))
    if not ok:
        raise HTTPException(400, f"X said: {d} — reading campaigns needs Ads "
                                 "API access approved for your app")
    camps = (d.get("data") or []) if isinstance(d, dict) else []
    ids = [cp.get("id") for cp in camps][:20]
    stats = {}
    if ids:
        frm, to = _window()
        q = urllib.parse.urlencode({
            "entity": "CAMPAIGN", "entity_ids": ",".join(ids),
            "start_time": f"{frm}T00:00:00Z", "end_time": f"{to}T00:00:00Z",
            "granularity": "TOTAL", "placement": "ALL_ON_TWITTER",
            "metric_groups": "BILLING,ENGAGEMENT"})
        ok2, st = IG._req(f"https://ads-api.x.com/12/stats/accounts/{acct}?{q}",
                          headers=_bearer(tok))
        if ok2 and isinstance(st, dict):
            for e in st.get("data") or []:
                m = ((e.get("id_data") or [{}])[0]).get("metrics") or {}
                stats[e.get("id")] = m
    out = []
    for cp in camps:
        m = stats.get(cp.get("id"), {})
        out.append({"external_id": str(cp.get("id")), "name": cp.get("name", ""),
                    "status": (cp.get("entity_status") or "").lower(),
                    "objective": "",
                    "daily_budget_cents": _int(cp.get("daily_budget_amount_local_micro")) // 10000,
                    "spend_cents": sum(_int(v) for v in (m.get("billed_charge_local_micro") or [])) // 10000,
                    "impressions": sum(_int(v) for v in (m.get("impressions") or [])),
                    "clicks": sum(_int(v) for v in (m.get("clicks") or [])),
                    "results": 0})
    return out


def _reddit(con, c: dict, s: dict) -> list:
    acct = str(s.get("ad_account_id", "")).strip()
    if not acct:
        raise HTTPException(400, "set the Reddit ad account id first")
    from .main import CFG
    tok = IG.access_token(con, "reddit_ads", CFG)
    h = {**_bearer(tok), "User-Agent": "business-control/1.0"}
    ok, d = IG._req(f"https://ads-api.reddit.com/api/v3/ad_accounts/{acct}/campaigns"
                    "?page.size=200", headers=h)
    if not ok:
        raise HTTPException(400, f"Reddit said: {d}")
    frm, to = _window()
    ok2, r = IG._json_req(
        f"https://ads-api.reddit.com/api/v3/ad_accounts/{acct}/reports", "POST",
        h, {"data": {"breakdowns": ["CAMPAIGN_ID"],
                     "fields": ["SPEND", "IMPRESSIONS", "CLICKS", "CONVERSIONS"],
                     "starts_at": f"{frm}T00:00:00Z", "ends_at": f"{to}T00:00:00Z",
                     "time_zone_id": "UTC"}})
    stats = {}
    if ok2 and isinstance(r, dict):
        for row in ((r.get("data") or {}).get("metrics") or []):
            stats[str(row.get("campaign_id"))] = row
    out = []
    for cp in (d.get("data") or []) if isinstance(d, dict) else []:
        cid = str(cp.get("id"))
        m = stats.get(cid, {})
        out.append({"external_id": cid, "name": cp.get("name", ""),
                    "status": (cp.get("effective_status") or cp.get("configured_status") or "").lower(),
                    "objective": (cp.get("objective") or "").lower(),
                    "daily_budget_cents": 0,
                    "spend_cents": _int(m.get("spend")) // 10000,   # micros
                    "impressions": _int(m.get("impressions")),
                    "clicks": _int(m.get("clicks")),
                    "results": _int(m.get("conversions"))})
    return out


def _snapchat(con, c: dict, s: dict) -> list:
    acct = str(s.get("ad_account_id", "")).strip()
    if not acct:
        raise HTTPException(400, "set the Snapchat ad account id first")
    from .main import CFG
    tok = IG.access_token(con, "snapchat_ads", CFG)
    ok, d = IG._req(f"https://adsapi.snapchat.com/v1/adaccounts/{acct}/campaigns",
                    headers=_bearer(tok))
    if not ok:
        raise HTTPException(400, f"Snapchat said: {d}")
    camps = [x.get("campaign") or {} for x in (d.get("campaigns") or [])] \
        if isinstance(d, dict) else []
    out = []
    frm, to = _window()
    for cp in camps:
        cid = str(cp.get("id"))
        ok2, st = IG._req(f"https://adsapi.snapchat.com/v1/campaigns/{cid}/stats"
                          f"?granularity=TOTAL&fields=spend,impressions,swipes,"
                          f"conversion_purchases&start_time={frm}T00:00:00.000Z"
                          f"&end_time={to}T00:00:00.000Z", headers=_bearer(tok))
        m = {}
        if ok2 and isinstance(st, dict):
            tl = ((st.get("total_stats") or [{}])[0]).get("total_stat") or {}
            m = tl.get("stats") or {}
        out.append({"external_id": cid, "name": cp.get("name", ""),
                    "status": (cp.get("status") or "").lower(),
                    "objective": (cp.get("objective") or "").lower(),
                    "daily_budget_cents": _int(cp.get("daily_budget_micro")) // 10000,
                    "spend_cents": _int(m.get("spend")) // 10000,
                    "impressions": _int(m.get("impressions")),
                    "clicks": _int(m.get("swipes")),
                    "results": _int(m.get("conversion_purchases"))})
    return out


READERS = {"meta_ads": _meta, "google_ads": _google, "tiktok_ads": _tiktok,
           "linkedin_ads": _linkedin, "x_ads": _x, "reddit_ads": _reddit,
           "snapchat_ads": _snapchat}


# ---------- checks: is the credential real ----------

def _check_tiktok(c: dict) -> tuple:
    ok, d = IG._req("https://business-api.tiktok.com/open_api/v1.3/user/info/",
                    headers={"Access-Token": c.get("token", "")})
    if not ok or not isinstance(d, dict) or d.get("code") not in (0, None):
        return False, str(d)
    who = (d.get("data") or {}).get("display_name") or "TikTok for Business"
    return True, f"{who} · advertiser {c.get('advertiser_id', '')}"


def _verify_meta(con, tok, c) -> tuple:
    ok, d = IG._req("https://graph.facebook.com/v19.0/me?fields=id,name"
                    f"&access_token={urllib.parse.quote(tok)}")
    return (True, d.get("name", "ok")) if ok and isinstance(d, dict) \
        else (False, str(d))


def _verify_google(con, tok, c) -> tuple:
    ok, d = IG._json_req("https://www.googleapis.com/oauth2/v3/userinfo", "GET",
                         _bearer(tok))
    return (True, d.get("email") or "connected") if ok and isinstance(d, dict) \
        else (False, str(d))


def _verify_linkedin(con, tok, c) -> tuple:
    ok, d = IG._req("https://api.linkedin.com/rest/adAccounts?q=search&count=1",
                    headers={**_bearer(tok), "Linkedin-Version": "202401"})
    return (True, "ad accounts readable") if ok else (False, str(d))


def _verify_x(con, tok, c) -> tuple:
    ok, d = IG._req("https://api.x.com/2/users/me", headers=_bearer(tok))
    return (True, "@" + ((d.get("data") or {}).get("username") or "")) \
        if ok and isinstance(d, dict) else (False, str(d))


def _verify_reddit(con, tok, c) -> tuple:
    ok, d = IG._req("https://ads-api.reddit.com/api/v3/me",
                    headers={**_bearer(tok), "User-Agent": "business-control/1.0"})
    return (True, ((d.get("data") or {}).get("username") or "ok")) \
        if ok and isinstance(d, dict) else (False, str(d))


def _verify_snapchat(con, tok, c) -> tuple:
    ok, d = IG._req("https://adsapi.snapchat.com/v1/me", headers=_bearer(tok))
    return (True, ((d.get("me") or {}).get("display_name") or "ok")) \
        if ok and isinstance(d, dict) else (False, str(d))


IG.CHECKS["tiktok_ads"] = _check_tiktok
IG.VERIFIERS.update({"meta_ads": _verify_meta, "google_ads": _verify_google,
                     "linkedin_ads": _verify_linkedin, "x_ads": _verify_x,
                     "reddit_ads": _verify_reddit, "snapchat_ads": _verify_snapchat})


# ---------- the ledger ----------

def pull(con, platform: str) -> dict:
    """Read one platform's campaigns for the window into the ledger."""
    reader = READERS.get(platform)
    if reader is None:
        raise HTTPException(400, "that platform is typed, not pulled")
    c = IG.creds(con, platform)
    if not c:
        raise HTTPException(400, f"connect {IG.PROVIDERS[platform]['label']} first")
    s = IG.settings(con, platform)
    try:
        rows = reader(con, c, s)
    except HTTPException as e:
        IG.log(con, platform, "pull_ads", False, str(e.detail)[:200])
        raise
    frm, to = _window()
    now = time.time()
    for r in rows:
        con.execute(
            "INSERT INTO ad_campaigns(platform,external_id,name,status,objective,"
            " daily_budget_cents,spend_cents,impressions,clicks,results,"
            " window_from,window_to,source,synced_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'pulled',?,?)"
            " ON CONFLICT(platform, external_id) DO UPDATE SET"
            " name=excluded.name, status=excluded.status,"
            " objective=excluded.objective,"
            " daily_budget_cents=excluded.daily_budget_cents,"
            " spend_cents=excluded.spend_cents, impressions=excluded.impressions,"
            " clicks=excluded.clicks, results=excluded.results,"
            " window_from=excluded.window_from, window_to=excluded.window_to,"
            " synced_at=excluded.synced_at",
            (platform, r["external_id"], (r.get("name") or "")[:200],
             r.get("status", ""), r.get("objective", ""),
             int(r.get("daily_budget_cents") or 0), int(r.get("spend_cents") or 0),
             int(r.get("impressions") or 0), int(r.get("clicks") or 0),
             int(r.get("results") or 0), frm, to, now, now))
    con.commit()
    IG.log(con, platform, "pull_ads", True, f"{len(rows)} campaign(s)")
    return {"ok": True, "pulled": len(rows)}


def _row(r) -> dict:
    d = dict(r)
    d["cpc_cents"] = (d["spend_cents"] // d["clicks"]) if d["clicks"] else 0
    d["ctr_bps"] = (d["clicks"] * 10000 // d["impressions"]) if d["impressions"] else 0
    return d


def ledger(con) -> dict:
    rows = [_row(r) for r in con.execute(
        "SELECT * FROM ad_campaigns ORDER BY spend_cents DESC, name").fetchall()]
    by = {}
    for r in rows:
        t = by.setdefault(r["platform"], {"spend_cents": 0, "impressions": 0,
                                          "clicks": 0, "results": 0, "campaigns": 0,
                                          "synced_at": 0})
        for k in ("spend_cents", "impressions", "clicks", "results"):
            t[k] += r[k]
        t["campaigns"] += 1
        t["synced_at"] = max(t["synced_at"], r["synced_at"] or 0)
    status = {p["name"]: p for p in IG.status(con)["providers"]}
    plats = []
    for p in PLATFORMS:
        st = status.get(p["provider"]) if p["provider"] else None
        plats.append({**p, "connected": bool(st and st["connected"]),
                      "account": st["account"] if st else "",
                      "settings": st["settings"] if st else {},
                      "settings_fields": st["settings_fields"] if st else [],
                      "totals": by.get(p["key"], {"spend_cents": 0, "impressions": 0,
                                                  "clicks": 0, "results": 0,
                                                  "campaigns": 0, "synced_at": 0})})
    frm, to = _window()
    return {"platforms": plats, "campaigns": rows, "window": {"from": frm, "to": to},
            "total_cents": sum(r["spend_cents"] for r in rows)}


def file_expense(con, cfg, user, platform: str) -> dict:
    """The platform's spend in the ledger, as one expense in the
    advertising category. Office-filed and company-paid, so it is a fact
    rather than a claim and needs no second signature."""
    from . import expenses as EX
    t = con.execute("SELECT COALESCE(SUM(spend_cents),0) AS s, MIN(window_from) AS a,"
                    " MAX(window_to) AS b FROM ad_campaigns WHERE platform=?",
                    (platform,)).fetchone()
    cents = int(t["s"] or 0)
    if cents <= 0:
        raise HTTPException(400, "nothing to file — no spend in the ledger")
    label = next((p["label"] for p in PLATFORMS if p["key"] == platform), platform)
    s = EX.settings(cfg)
    tax = EX._tax_inside(cents, s)
    con.execute(
        "INSERT INTO expenses(user_id,category,vendor,amount_cents,spent_at,note,"
        " business_pct,paid_by,recurring,next_at,tax_cents,capitalised,state,"
        " decided_by,decided_at,created_at)"
        " VALUES(?,'advertising',?,?,?,?,100,'company','',0,?,0,'approved',?,?,?)",
        (user["id"], label[:120], cents, time.time(),
         f"ad ledger, {t['a'] or ''} to {t['b'] or ''}"[:400], tax,
         user["name"], db.now(), db.now()))
    con.commit()
    return {"ok": True, "amount_cents": cents}


# ---------- routes ----------

router = APIRouter()

from .main import CFG, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/ads")
def ads_page(user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "the ad ledger is an office screen")
    return ledger(con)


class ManualBody(BaseModel):
    id: int = 0
    platform: str
    name: str
    spend_cents: int = 0
    impressions: int = 0
    clicks: int = 0
    results: int = 0
    window_from: str = ""
    window_to: str = ""
    note: str = ""
    status: str = "active"


@router.post("/api/ads/manual")
def ads_manual(body: ManualBody, user=Depends(current_user),
               con=Depends(get_con)):
    """A row typed in: a Twitch run, a flyer, a newspaper. Same ledger,
    marked as typed."""
    if not _office(user):
        raise HTTPException(403, "office only")
    if body.platform not in PLATFORM_KEYS:
        raise HTTPException(400, "pick a platform")
    if not body.name.strip():
        raise HTTPException(400, "name the campaign")
    if body.spend_cents < 0:
        raise HTTPException(400, "spend can't be negative")
    now = time.time()
    if body.id:
        r = con.execute("SELECT * FROM ad_campaigns WHERE id=?", (body.id,)).fetchone()
        if r is None or r["source"] != "manual":
            raise HTTPException(400, "only a typed row can be edited here")
        con.execute(
            "UPDATE ad_campaigns SET platform=?, name=?, spend_cents=?, impressions=?,"
            " clicks=?, results=?, window_from=?, window_to=?, note=?, status=?,"
            " synced_at=? WHERE id=?",
            (body.platform, body.name.strip()[:200], body.spend_cents,
             body.impressions, body.clicks, body.results, body.window_from,
             body.window_to, body.note.strip()[:400], body.status, now, body.id))
        con.commit()
        return {"ok": True, "id": body.id}
    ext = f"manual:{int(now * 1000)}"
    cur = con.execute(
        "INSERT INTO ad_campaigns(platform,external_id,name,status,spend_cents,"
        " impressions,clicks,results,window_from,window_to,source,note,synced_at,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'manual',?,?,?)",
        (body.platform, ext, body.name.strip()[:200], body.status, body.spend_cents,
         body.impressions, body.clicks, body.results, body.window_from,
         body.window_to, body.note.strip()[:400], now, now))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/ads/{cid}")
def ads_delete(cid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    con.execute("DELETE FROM ad_campaigns WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}


@router.post("/api/ads/{platform}/pull")
def ads_pull(platform: str, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if platform not in PLATFORM_KEYS:
        raise HTTPException(404, "no such platform")
    return pull(con, platform)


@router.post("/api/ads/{platform}/expense")
def ads_expense(platform: str, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if platform not in PLATFORM_KEYS:
        raise HTTPException(404, "no such platform")
    return file_expense(con, CFG, user, platform)
