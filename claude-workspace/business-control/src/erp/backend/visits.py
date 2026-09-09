"""Who has been here: devices, addresses, and where they seem to be.

Every page load leaves an address and a user-agent; every browser that
runs the site's own script leaves a little more — its timezone, its
language, its screen. Put together, that is a device: not a person, a
browser on a machine, recognisable across visits without a cookie. The
same browser coming back is one device with a growing count, not a new
row every time.

What this is honest about. "Where" is the browser's own timezone and
language, which is where somebody's clock and keyboard think they are —
usually right, never certain, and nothing more is claimed. A real
address-to-city lookup needs a GeoIP database this install does not
ship; if one is ever added it slots in beside these columns rather than
replacing them. The fingerprint is a hash of things the browser volunteers
(user-agent, language, timezone, screen, platform) plus the visitor id
the storefront already keeps; it is for recognising a device on this site,
and is useless to anyone else, which is the point.

Kept small. Per device: first seen, last seen, hit count, the last
address. Per device per day: hits. Per path per day: hits. Nothing per
request beyond that, so a busy month is thousands of rows, not millions,
and pruning is a date cut.
"""
import hashlib
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

TABLES = """
CREATE TABLE IF NOT EXISTS devices (
  fp TEXT PRIMARY KEY,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0,
  ip TEXT DEFAULT '',                 -- the last one seen
  ua TEXT DEFAULT '',
  lang TEXT DEFAULT '',
  tz TEXT DEFAULT '',
  screen TEXT DEFAULT '',
  platform TEXT DEFAULT '',
  touch INTEGER DEFAULT 0,
  visitor_id TEXT DEFAULT '',
  user_id INTEGER DEFAULT 0,          -- the last account seen on it
  surface TEXT DEFAULT ''             -- storefront | ops | learn
);
CREATE INDEX IF NOT EXISTS devices_seen ON devices(last_seen);
CREATE TABLE IF NOT EXISTS device_days (
  fp TEXT NOT NULL, day TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (fp, day)
);
CREATE TABLE IF NOT EXISTS visit_paths (
  day TEXT NOT NULL, path TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, path)
);
CREATE TABLE IF NOT EXISTS device_ips (
  fp TEXT NOT NULL, ip TEXT NOT NULL, last_seen REAL NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (fp, ip)
);
"""

KEEP_DAYS = 400


def init_tables(con) -> None:
    con.executescript(TABLES)
    con.commit()


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def fingerprint(ua: str, lang: str = "", tz: str = "", screen: str = "",
                platform: str = "", visitor_id: str = "") -> str:
    """Stable for one browser on one machine, and nothing else. The
    visitor id is in it because two identical phones on the same
    network are two devices, and only the id the storefront minted
    tells them apart."""
    raw = "|".join((ua or "", lang or "", tz or "", screen or "",
                    platform or "", visitor_id or ""))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def touch(con, fp: str, *, ip: str, ua: str, path: str = "",
          user_id: int = 0, surface: str = "", **facts) -> None:
    """One sighting. Cheap enough to run on every page load."""
    now = time.time()
    day = _day(now)
    cols = {k: v for k, v in facts.items()
            if k in ("lang", "tz", "screen", "platform", "touch",
                     "visitor_id") and v not in (None, "")}
    row = con.execute("SELECT fp FROM devices WHERE fp=?", (fp,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO devices(fp,first_seen,last_seen,hits,ip,ua,lang,tz,"
            "screen,platform,touch,visitor_id,user_id,surface)"
            " VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
            (fp, now, now, ip[:64], ua[:300], cols.get("lang", "")[:16],
             cols.get("tz", "")[:64], cols.get("screen", "")[:24],
             cols.get("platform", "")[:40], 1 if cols.get("touch") else 0,
             cols.get("visitor_id", "")[:64], user_id or 0, surface[:16]))
    else:
        sets = ["last_seen=?", "hits=hits+1", "ip=?"]
        args = [now, ip[:64]]
        for k, v in cols.items():
            sets.append(f"{k}=?")
            args.append(1 if (k == "touch" and v) else str(v)[:64])
        if user_id:
            sets.append("user_id=?"); args.append(user_id)
        if surface:
            sets.append("surface=?"); args.append(surface[:16])
        if ua:
            sets.append("ua=?"); args.append(ua[:300])
        args.append(fp)
        con.execute(f"UPDATE devices SET {', '.join(sets)} WHERE fp=?", args)
    con.execute("INSERT INTO device_days(fp,day,hits) VALUES(?,?,1)"
                " ON CONFLICT(fp,day) DO UPDATE SET hits=device_days.hits+1", (fp, day))
    if ip:
        con.execute("INSERT INTO device_ips(fp,ip,last_seen,hits) VALUES(?,?,?,1)"
                    " ON CONFLICT(fp,ip) DO UPDATE SET last_seen=excluded.last_seen,"
                    " hits=device_ips.hits+1", (fp, ip[:64], now))
    if path:
        con.execute("INSERT INTO visit_paths(day,path,hits) VALUES(?,?,1)"
                    " ON CONFLICT(day,path) DO UPDATE SET hits=visit_paths.hits+1",
                    (day, path[:120]))


def prune(con) -> None:
    cut = _day(time.time() - KEEP_DAYS * 86400)
    con.execute("DELETE FROM device_days WHERE day<?", (cut,))
    con.execute("DELETE FROM visit_paths WHERE day<?", (cut,))


# ── what a page load says, with no script at all ──────────────────────────

PAGE_PREFIXES = ("/", "/ops", "/ops/", "/admin", "/learn", "/product/",
                 "/p/", "/blog", "/dr/", "/rc/", "/training/")


def is_page(method: str, path: str, accept: str) -> bool:
    """A human loading a page, not the page's own script fetching JSON:
    only GETs that ask for HTML, on the paths people arrive at."""
    if method != "GET" or "text/html" not in (accept or ""):
        return False
    return path in ("/", "/ops", "/ops/", "/admin", "/learn") or \
        path.startswith(("/product/", "/p/", "/blog", "/dr/", "/rc/",
                         "/training/", "/learn"))


# ── the browser's own report ────────────────────────────────────────────────

class BeaconBody(BaseModel):
    visitor_id: str = ""
    tz: str = ""
    lang: str = ""
    screen: str = ""
    platform: str = ""
    touch: bool = False
    surface: str = ""
    path: str = ""


def _ua_family(ua: str) -> tuple:
    """Browser and OS, coarsely — enough to read a table by, and nothing
    a parsing library would argue with."""
    u = ua or ""
    os_ = ("iOS" if "iPhone" in u or "iPad" in u else
           "Android" if "Android" in u else
           "macOS" if "Mac OS X" in u or "Macintosh" in u else
           "Windows" if "Windows" in u else
           "Linux" if "Linux" in u else "other")
    br = ("Edge" if "Edg/" in u else
          "Opera" if "OPR/" in u else
          "Samsung" if "SamsungBrowser" in u else
          "Chrome" if "Chrome/" in u and "Chromium" not in u else
          "Firefox" if "Firefox/" in u else
          "Safari" if "Safari/" in u and "Chrome" not in u else "other")
    return br, os_


def register(app, get_con, admin_user, client_ip):
    """Routes need the app's own dependencies, which exist only after
    main has finished defining them — hence a function, called late."""
    router = APIRouter()

    @router.post("/api/device")
    def beacon(body: BeaconBody, request: Request, con=Depends(get_con)):
        ua = request.headers.get("user-agent", "")
        fp = fingerprint(ua, body.lang, body.tz, body.screen, body.platform,
                         body.visitor_id)
        uid = 0
        tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if tok:
            from . import auth
            u = auth.user_for_token(con, tok)
            uid = u["id"] if u else 0
        touch(con, fp, ip=client_ip(request), ua=ua, path="",
              user_id=uid, surface=body.surface, lang=body.lang, tz=body.tz,
              screen=body.screen, platform=body.platform, touch=body.touch,
              visitor_id=body.visitor_id)
        con.commit()
        return {"ok": True}

    @router.get("/api/admin/devices")
    def list_devices(days: int = 30, q: str = "", user=Depends(admin_user),
                     con=Depends(get_con)):
        since = time.time() - max(1, days) * 86400
        rows = [dict(r) for r in con.execute(
            "SELECT d.*, COALESCE(u.name,'') AS who FROM devices d"
            " LEFT JOIN users u ON u.id=d.user_id"
            " WHERE d.last_seen>=? ORDER BY d.last_seen DESC LIMIT 500",
            (since,))]
        needle = q.strip().lower()
        out = []
        for r in rows:
            br, os_ = _ua_family(r["ua"])
            r["browser"], r["os"] = br, os_
            r["ips"] = [dict(x) for x in con.execute(
                "SELECT ip, hits, last_seen FROM device_ips WHERE fp=?"
                " ORDER BY last_seen DESC LIMIT 6", (r["fp"],))]
            r["days"] = con.execute("SELECT COUNT(*) FROM device_days WHERE fp=?",
                                    (r["fp"],)).fetchone()[0]
            if needle and needle not in " ".join(
                    str(v).lower() for v in (r["ip"], r["ua"], r["tz"], r["lang"],
                                             r["who"], r["platform"], os_, br,
                                             " ".join(x["ip"] for x in r["ips"]))):
                continue
            out.append(r)
        return {"devices": out, "days": days,
                "note": "A device is one browser on one machine, recognised by "
                        "what it volunteers — not a person, and not a cookie. "
                        "Where it is comes from its own clock and keyboard; a "
                        "real address lookup needs a GeoIP database this "
                        "install does not ship."}

    @router.get("/api/admin/devices/analysis")
    def analysis(days: int = 30, user=Depends(admin_user), con=Depends(get_con)):
        since = time.time() - max(1, days) * 86400
        cut = _day(since)
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM devices WHERE last_seen>=?", (since,))]
        def tally(key):
            t = {}
            for r in rows:
                k = key(r) or "(unknown)"
                t[k] = t.get(k, 0) + 1
            return sorted(({"k": k, "n": n} for k, n in t.items()),
                          key=lambda x: -x["n"])[:12]
        by_day = [dict(r) for r in con.execute(
            "SELECT day, COUNT(DISTINCT fp) AS devices, SUM(hits) AS hits"
            " FROM device_days WHERE day>=? GROUP BY day ORDER BY day", (cut,))]
        paths = [dict(r) for r in con.execute(
            "SELECT path, SUM(hits) AS hits FROM visit_paths WHERE day>=?"
            " GROUP BY path ORDER BY hits DESC LIMIT 15", (cut,))]
        ips = [dict(r) for r in con.execute(
            "SELECT ip, COUNT(DISTINCT fp) AS devices, SUM(hits) AS hits"
            " FROM device_ips WHERE last_seen>=? GROUP BY ip"
            " ORDER BY hits DESC LIMIT 15", (since,))]
        return {
            "days": days, "devices": len(rows),
            "returning": sum(1 for r in rows if r["hits"] > 1),
            "signed_in": sum(1 for r in rows if r["user_id"]),
            "by_tz": tally(lambda r: r["tz"]),
            "by_lang": tally(lambda r: (r["lang"] or "").split(",")[0][:5]),
            "by_browser": tally(lambda r: _ua_family(r["ua"])[0]),
            "by_os": tally(lambda r: _ua_family(r["ua"])[1]),
            "by_surface": tally(lambda r: r["surface"]),
            "by_screen": tally(lambda r: r["screen"]),
            "by_day": by_day, "paths": paths, "ips": ips,
            "note": "Timezone and language are where a browser's clock and "
                    "keyboard think they are — a good guess, never a claim.",
        }

    app.include_router(router)
