"""Traffic: every request, written down; and the door, with a list.

A website is asked for things all day by people it will never meet, and
most of what an operator learns about an attack, a scraper or a bot
that is hammering the checkout comes too late, from a bill or a
complaint. This is the other order: every request is logged as it
happens — who, what, how it went, how long — and the same screen that
shows the log lets the operator act on it in one click: ban that
address, block that user agent, refuse that path, for an hour or for
good. Rules are checked before anything else the server does, so a
banned address costs one lookup and nothing more.

What is kept, and what is not: the address, the method, the path, the
status, the time it took, the user agent, the referer, and the account
if one was signed in. Not the body, not a cookie, not a token. A log
that held those would be the leak it was meant to catch.

Bans are honest about what they are. An address is a household, a
coffee shop or a whole mobile network as often as it is a person, so a
ban has an expiry by default and a reason always, and the screen shows
what the address did before offering to ban it. The allow list — only
these addresses may open the operations screens — is the sharp tool
and is off until somebody turns it on, because an allow list with the
operator's own address missing locks the operator out.

Automatic bans are for what needs no judgement: an address asking for
/wp-login.php, /.env or /phpmyadmin is not a customer, and an address
making more requests in a minute than a person could is not a person.
Both are temporary, both are logged with the reason, both can be lifted.
"""
import ipaddress
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS request_log (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  ip TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  query TEXT DEFAULT '',
  status INTEGER NOT NULL,
  ms INTEGER DEFAULT 0,
  ua TEXT DEFAULT '',
  referer TEXT DEFAULT '',
  user_id INTEGER DEFAULT 0,
  kind TEXT DEFAULT 'page',                -- page|api|asset
  blocked INTEGER DEFAULT 0,               -- refused by a rule
  rule_id INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS request_log_at ON request_log(at);
CREATE INDEX IF NOT EXISTS request_log_ip ON request_log(ip, at);

/* The door's list. kind: deny (refuse) or allow (only these may pass the
   scope). target: ip (an address or a CIDR), ua (a substring of the user
   agent), path (a prefix). scope: which paths the rule guards — '' is
   everything; '/ops' the operations screens; '/admin' the store admin. */
CREATE TABLE IF NOT EXISTS access_rules (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                      -- deny|allow
  target TEXT NOT NULL,                    -- ip|ua|path
  value TEXT NOT NULL,
  scope TEXT DEFAULT '',
  reason TEXT DEFAULT '',
  expires_at REAL DEFAULT 0,               -- 0 = never
  hits INTEGER DEFAULT 0,
  last_hit REAL DEFAULT 0,
  auto INTEGER DEFAULT 0,                  -- made by the guard itself
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS access_rules_live ON access_rules(expires_at);
"""

# Paths nobody who belongs here asks for. One request for any of them is
# a scanner, and a scanner is banned for a while without a person having
# to look — the list is the operator's to edit.
PROBE_DEFAULT = ["/wp-login.php", "/wp-admin", "/xmlrpc.php", "/.env", "/.git",
                 "/phpmyadmin", "/vendor/phpunit", "/cgi-bin/", "/.aws", "/config.json",
                 "/etc/passwd", "/shell", "/boaform"]
SETTINGS_DEFAULT = {
    "enabled": True,
    "keep_days": 14,                 # how long the log is kept
    "log_assets": False,             # /vendor, images, fonts — noise unless wanted
    "auto_ban": True,
    "probe_paths": PROBE_DEFAULT,
    "probe_ban_hours": 24,
    "rate_per_minute": 300,          # more than this from one address in a minute
    "rate_ban_minutes": 30,
    "errors_per_minute": 60,         # 4xx/5xx from one address in a minute
}
ASSET_PREFIXES = ("/vendor/", "/media/", "/static/", "/icons", "/hero/")
ASSET_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".woff", ".woff2", ".map")

_lock = threading.Lock()
# One buffer per tenant of rows waiting to be written, flushed in a
# batch: a request must not wait on a disk write for its own log line.
_buffers: dict = {}
_rules_cache: dict = {}          # tenant -> (loaded_at, rules)
_settings_cache: dict = {}       # tenant -> (loaded_at, settings)
_rate: dict = {}                 # tenant -> {ip: [timestamps]}
CACHE_SEC = 5


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _tenant() -> str:
    from . import tenancy
    return tenancy.CURRENT.get() or ""


def settings(con) -> dict:
    import json
    row = con.execute("SELECT v FROM store_meta WHERE k='traffic'").fetchone() if _has_meta(con) else None
    try:
        own = json.loads(row["v"]) if row else {}
    except ValueError:
        own = {}
    return {**SETTINGS_DEFAULT, **{k: v for k, v in own.items() if k in SETTINGS_DEFAULT}}


def _has_meta(con) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name='store_meta'").fetchone() is not None


def save_settings(con, patch: dict) -> dict:
    import json
    cur = settings(con)
    for k, v in patch.items():
        if k in SETTINGS_DEFAULT:
            cur[k] = v
    con.execute("INSERT INTO store_meta(k,v) VALUES('traffic',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(cur),))
    con.commit()
    _settings_cache.pop(_tenant(), None)
    return cur


def _cached_settings(con) -> dict:
    t = _tenant()
    hit = _settings_cache.get(t)
    if hit and time.time() - hit[0] < CACHE_SEC:
        return hit[1]
    s = settings(con)
    _settings_cache[t] = (time.time(), s)
    return s


def live_rules(con) -> list:
    t = _tenant()
    hit = _rules_cache.get(t)
    if hit and time.time() - hit[0] < CACHE_SEC:
        return hit[1]
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM access_rules WHERE expires_at=0 OR expires_at>?",
        (time.time(),)).fetchall()]
    for r in rows:
        if r["target"] == "ip":
            try:
                r["_net"] = ipaddress.ip_network(r["value"], strict=False)
            except ValueError:
                r["_net"] = None
    _rules_cache[t] = (time.time(), rows)
    return rows


def _forget_rules() -> None:
    _rules_cache.pop(_tenant(), None)


def _matches(rule: dict, ip: str, ua: str, path: str) -> bool:
    if rule["scope"] and not path.startswith(rule["scope"]):
        return False
    if rule["target"] == "ip":
        net = rule.get("_net")
        if net is None:
            return False
        try:
            return ipaddress.ip_address(ip) in net
        except ValueError:
            return False
    if rule["target"] == "ua":
        return rule["value"].lower() in (ua or "").lower()
    if rule["target"] == "path":
        return path.startswith(rule["value"])
    return False


def decide(con, ip: str, ua: str, path: str) -> tuple:
    """(allowed, rule) — the door's answer for one request. Deny rules
    win. Then, for any scope that has allow rules, only a matching
    address passes; a scope with no allow rules is open."""
    rules = live_rules(con)
    for r in rules:
        if r["kind"] == "deny" and _matches(r, ip, ua, path):
            return False, r
    scopes = {r["scope"] for r in rules if r["kind"] == "allow"}
    for scope in scopes:
        if scope and not path.startswith(scope):
            continue
        if not any(r["kind"] == "allow" and r["scope"] == scope and _matches(r, ip, ua, path)
                   for r in rules):
            gate = next(r for r in rules if r["kind"] == "allow" and r["scope"] == scope)
            return False, {**gate, "reason": f"not on the allow list for {scope or 'the site'}"}
    return True, None


def add_rule(con, *, kind: str, target: str, value: str, scope: str = "",
             reason: str = "", hours: float = 0, by: str = "", auto: bool = False) -> dict:
    if kind not in ("deny", "allow"):
        raise HTTPException(400, "kind is deny or allow")
    if target not in ("ip", "ua", "path"):
        raise HTTPException(400, "target is ip, ua or path")
    value = value.strip()
    if not value:
        raise HTTPException(400, "a rule needs a value")
    if target == "ip":
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as e:
            raise HTTPException(400, f"not an address or a network: {value}") from e
    if target == "path" and not value.startswith("/"):
        raise HTTPException(400, "a path rule starts with /")
    if scope and not scope.startswith("/"):
        raise HTTPException(400, "a scope is a path prefix, like /ops")
    if not reason.strip() and not auto:
        raise HTTPException(400, "say why — a ban with no reason is a ban nobody can lift with confidence")
    expires = time.time() + hours * 3600 if hours and hours > 0 else 0
    dup = con.execute("SELECT id FROM access_rules WHERE kind=? AND target=? AND value=? AND scope=?"
                      " AND (expires_at=0 OR expires_at>?)",
                      (kind, target, value, scope, time.time())).fetchone()
    if dup:
        con.execute("UPDATE access_rules SET expires_at=?, reason=? WHERE id=?",
                    (expires, reason.strip()[:200] or "", dup["id"]))
        con.commit(); _forget_rules()
        return {"ok": True, "id": dup["id"], "already": True}
    cur = con.execute(
        "INSERT INTO access_rules(kind,target,value,scope,reason,expires_at,auto,by_name,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (kind, target, value[:300], scope[:100], reason.strip()[:200], expires, int(auto),
         by[:80], db.now()))
    con.commit(); _forget_rules()
    return {"ok": True, "id": cur.lastrowid}


def _kind_of(path: str) -> str:
    if path.startswith("/api/"):
        return "api"
    if path.startswith(ASSET_PREFIXES) or path.endswith(ASSET_SUFFIXES):
        return "asset"
    return "page"


def record(con_factory, *, ip: str, method: str, path: str, query: str, status: int,
           ms: int, ua: str, referer: str, user_id: int, blocked: bool, rule_id: int) -> None:
    """Queue one line; written in a batch by flush()."""
    t = _tenant()
    with _lock:
        _buffers.setdefault(t, []).append(
            (time.time(), ip, method[:8], path[:300], query[:300], int(status), int(ms),
             (ua or "")[:300], (referer or "")[:300], int(user_id or 0), _kind_of(path),
             int(blocked), int(rule_id or 0)))
        n = len(_buffers[t])
    if n >= 50:
        flush(con_factory, t)


def flush(con_factory, tenant: str | None = None) -> int:
    """Write what is queued. Called when a buffer fills and when the
    screen reads, so what the operator sees is up to the second."""
    tenants = [tenant] if tenant is not None else list(_buffers)
    written = 0
    for t in tenants:
        with _lock:
            rows, _buffers[t] = _buffers.get(t, []), []
        if not rows:
            continue
        try:
            con = con_factory(t)
            con.executemany(
                "INSERT INTO request_log(at,ip,method,path,query,status,ms,ua,referer,user_id,"
                " kind,blocked,rule_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
            written += len(rows)
            con.close()
        except Exception:                                    # noqa: BLE001
            pass                    # a log that cannot be written must not break the request
    return written


def prune(con, keep_days: int) -> int:
    cur = con.execute("DELETE FROM request_log WHERE at<?", (time.time() - keep_days * 86400,))
    con.execute("DELETE FROM access_rules WHERE expires_at>0 AND expires_at<?",
                (time.time() - 7 * 86400,))
    con.commit()
    return cur.rowcount


def note_rate(ip: str, path: str, status: int, s: dict) -> tuple:
    """Count this address's requests in the last minute; say whether it
    has crossed a line that earns an automatic ban."""
    if not s.get("auto_ban"):
        return None, ""
    for probe in s.get("probe_paths") or []:
        if probe and path.startswith(probe):
            return "probe", f"asked for {probe}"
    t = _tenant()
    now = time.time()
    with _lock:
        per = _rate.setdefault(t, {})
        hist = per.setdefault(ip, [])
        hist.append((now, status))
        cutoff = now - 60
        while hist and hist[0][0] < cutoff:
            hist.pop(0)
        n = len(hist)
        errs = sum(1 for _, st in hist if st >= 400)
        if len(per) > 5000:                # do not let a flood grow the table
            for k in list(per)[:1000]:
                per.pop(k, None)
    if n > int(s.get("rate_per_minute") or 300):
        return "rate", f"{n} requests in a minute"
    if errs > int(s.get("errors_per_minute") or 60):
        return "errors", f"{errs} errors in a minute"
    return None, ""


# ---------- reading it back ----------

def recent(con, *, minutes: int = 60, ip: str = "", path: str = "", status: str = "",
           ua: str = "", kind: str = "", limit: int = 300) -> list:
    where, args = ["at>?"], [time.time() - minutes * 60]
    if ip:
        where.append("ip=?"); args.append(ip)
    if path:
        where.append("path LIKE ?"); args.append(f"%{path}%")
    if ua:
        where.append("lower(ua) LIKE ?"); args.append(f"%{ua.lower()}%")
    if kind:
        where.append("kind=?"); args.append(kind)
    if status == "4xx":
        where.append("status BETWEEN 400 AND 499")
    elif status == "5xx":
        where.append("status>=500")
    elif status == "blocked":
        where.append("blocked=1")
    elif status.isdigit():
        where.append("status=?"); args.append(int(status))
    return [dict(r) for r in con.execute(
        "SELECT * FROM request_log WHERE " + " AND ".join(where)
        + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 2000))).fetchall()]


def talkers(con, *, minutes: int = 60, limit: int = 40) -> list:
    """Who is asking the most, with what it looks like: requests, errors,
    distinct paths, one user agent, whether any of it was refused. The
    list a person bans from."""
    rows = [dict(r) for r in con.execute(
        "SELECT ip, COUNT(*) AS n, SUM(status>=400) AS errors, SUM(blocked) AS blocked,"
        " COUNT(DISTINCT path) AS paths, MIN(at) AS first_at, MAX(at) AS last_at,"
        " MAX(ua) AS ua, MAX(user_id) AS user_id"
        " FROM request_log WHERE at>? GROUP BY ip ORDER BY n DESC LIMIT ?",
        (time.time() - minutes * 60, limit)).fetchall()]
    for r in rows:
        r["sample_paths"] = [x["path"] for x in con.execute(
            "SELECT path, COUNT(*) AS c FROM request_log WHERE ip=? AND at>? GROUP BY path"
            " ORDER BY c DESC LIMIT 5", (r["ip"], time.time() - minutes * 60)).fetchall()]
        r["looks_like"] = classify(r)
    return rows


def classify(r: dict) -> str:
    ua = (r.get("ua") or "").lower()
    if any(b in ua for b in ("bot", "crawler", "spider", "curl", "python-requests", "scrapy", "wget", "go-http-client")):
        return "bot, says so"
    if not ua:
        return "no user agent"
    if r.get("paths", 0) > 50 and r.get("n", 0) > 100:
        return "crawling"
    if r.get("errors", 0) and r["errors"] / max(1, r["n"]) > 0.5:
        return "mostly errors"
    if r.get("user_id"):
        return "signed in"
    return "visitor"


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _require(user) -> None:
    if not auth.office(user, "settings"):
        raise HTTPException(403, "the door is the owner's and the admin's")


def _con_for(tenant: str):
    from . import tenancy
    tok = tenancy.CURRENT.set(tenant or None)
    try:
        return db.connect()
    finally:
        tenancy.CURRENT.reset(tok)


@router.get("/api/traffic")
def traffic_page(minutes: int = 60, ip: str = "", path: str = "", status: str = "",
                 ua: str = "", kind: str = "", user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    flush(_con_for, _tenant())
    s = settings(con)
    now = time.time()
    return {
        "settings": s,
        "recent": recent(con, minutes=minutes, ip=ip, path=path, status=status, ua=ua, kind=kind),
        "talkers": talkers(con, minutes=minutes),
        "rules": [dict(r) for r in con.execute(
            "SELECT * FROM access_rules WHERE expires_at=0 OR expires_at>? ORDER BY id DESC",
            (now,)).fetchall()],
        "counts": {
            "hour": con.execute("SELECT COUNT(*) FROM request_log WHERE at>?", (now - 3600,)).fetchone()[0],
            "day": con.execute("SELECT COUNT(*) FROM request_log WHERE at>?", (now - 86400,)).fetchone()[0],
            "blocked_day": con.execute("SELECT COUNT(*) FROM request_log WHERE at>? AND blocked=1",
                                       (now - 86400,)).fetchone()[0],
            "addresses_day": con.execute("SELECT COUNT(DISTINCT ip) FROM request_log WHERE at>?",
                                         (now - 86400,)).fetchone()[0],
        },
        "you": {"ip": ""},
    }


class RuleBody(BaseModel):
    kind: str = "deny"
    target: str = "ip"
    value: str
    scope: str = ""
    reason: str = ""
    hours: float = 0


@router.post("/api/traffic/rules")
def rule_add(body: RuleBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return add_rule(con, kind=body.kind, target=body.target, value=body.value,
                    scope=body.scope, reason=body.reason, hours=body.hours, by=user["name"])


@router.delete("/api/traffic/rules/{rid}")
def rule_lift(rid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM access_rules WHERE id=?", (rid,))
    con.commit(); _forget_rules()
    return {"ok": True}


class SettingsBody(BaseModel):
    patch: dict


@router.post("/api/traffic/settings")
def settings_save(body: SettingsBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    p = dict(body.patch)
    if "probe_paths" in p:
        p["probe_paths"] = [str(x).strip() for x in p["probe_paths"] if str(x).strip().startswith("/")][:200]
    for k in ("keep_days", "probe_ban_hours", "rate_per_minute", "rate_ban_minutes", "errors_per_minute"):
        if k in p:
            try:
                p[k] = max(1, int(p[k]))
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"{k} is a number") from e
    return save_settings(con, p)


@router.get("/api/traffic/export.csv")
def traffic_csv(minutes: int = 1440, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    import csv
    import io
    flush(_con_for, _tenant())
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["at", "ip", "method", "path", "query", "status", "ms", "ua", "referer",
                "user_id", "kind", "blocked"])
    for r in con.execute("SELECT * FROM request_log WHERE at>? ORDER BY id",
                         (time.time() - minutes * 60,)).fetchall():
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["at"])), r["ip"], r["method"],
                    r["path"], r["query"], r["status"], r["ms"], r["ua"], r["referer"],
                    r["user_id"], r["kind"], r["blocked"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="traffic.csv"'})
