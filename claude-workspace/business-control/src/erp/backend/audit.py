"""Who changed what, recorded at one place instead of a hundred.

Every state-changing request already passes through the same door: an HTTP
method that isn't GET, carrying a token that identifies someone. So the log
is written by middleware rather than by each endpoint. The alternative —
an `audit(...)` call inside every handler — is wrong the moment somebody adds
the hundred-and-first endpoint and forgets, and a log with silent holes is
worse than no log, because it reads as complete.

What gets recorded is the request line, the actor, and the outcome. Bodies
are summarised, never stored whole: a request body can contain a password, a
PIN or an API key, and an audit trail is the last place those should end up
sitting in plaintext. The summary keeps the field *names* and the identifiers,
which is what you actually need when reconstructing what happened.
"""
import json
import re
import time

from . import db

def note(request, detail: str) -> None:
    """Describe the current request in the log, in the handler's own words.

    The middleware prefers this over its own summary of the request body, so
    a permission change reads "set permissions: Dana → orders,products"
    rather than "permissions[2]" — and there is still one row per request.

    It hangs off the request rather than a context variable: sync endpoints
    run in a worker thread, and a contextvar set there never reaches the
    middleware, which runs back on the event loop. The request object is the
    thing both of them genuinely share.
    """
    try:
        request.state.audit_note = detail[:400]
    except Exception:
        pass

TABLES = """
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  actor TEXT DEFAULT '',
  action TEXT NOT NULL,                    -- POST /api/admin/products
  entity TEXT DEFAULT '',                  -- products/12
  detail TEXT DEFAULT '',                  -- summarised body
  status INTEGER DEFAULT 0,                -- HTTP status of the response
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_time ON audit_log(created_at DESC);
"""

# Field names whose values never reach the log. Matched loosely because the
# same secret travels under several names across the codebase.
SECRET = re.compile(
    r"pin|pass|token|secret|webhook|key|hash|signature|cvv|card", re.I)

# How long entries are kept. Two windows, because these are not the same
# kind of record: most rows answer "what changed last week" and stop being
# useful quickly, while the handful that touch access — who was granted what,
# whose PIN was reset, who opened the raw tables — are the ones you go
# looking for long after the fact, often precisely because something went
# wrong. Deleting those on the same schedule as a product rename would throw
# away the only rows anyone ever needs a year later.
KEEP_DAYS = 180
KEEP_DAYS_SENSITIVE = 1095            # three years
SENSITIVE = re.compile(
    r"/permissions|/pin|/staff|/keys|/admin/db|/discord|/webhooks|"
    r"/users/\d+/update|/login", re.I)

# A backstop against the window being useless — a burst of writes inside the
# retention period shouldn't be able to fill the disk before it expires.
MAX_ROWS = 200_000

# Pruning is bookkeeping, not something to do on every request.
PRUNE_EVERY = 3600
_last_prune: dict = {}    # per tenant — one busy tenant must not starve another's prune

# Requests that change nothing worth recording. Clocking in is already its own
# durable record in `shifts`, and the read-tracking endpoints would bury the
# real edits under thousands of rows.
SKIP = (
    "/api/notifications/read",
    "/api/events",              # storefront analytics beacon
    "/api/push/",
    "/api/store/track",
)


def init_tables(con=None) -> None:
    own = con is None
    con = con or db.connect()
    try:
        con.executescript(TABLES)
        # Older installs have the table without `status`.
        try:
            con.execute("ALTER TABLE audit_log ADD COLUMN status INTEGER"
                        " DEFAULT 0")
        except Exception:
            pass
        con.commit()
    finally:
        if own:
            con.close()


def summarise(body: bytes) -> str:
    """A one-line description of a request body, with values dropped for
    anything that looks like a credential."""
    if not body:
        return ""
    try:
        data = json.loads(body)
    except Exception:
        return f"{len(body)} bytes"
    if not isinstance(data, dict):
        return str(data)[:200]
    parts = []
    for k, v in data.items():
        if SECRET.search(k):
            parts.append(f"{k}=***")
        elif isinstance(v, (dict, list)):
            parts.append(f"{k}[{len(v)}]")
        else:
            parts.append(f"{k}={str(v)[:60]}")
    return ", ".join(parts)[:400]


def record(con, user, method: str, path: str, detail: str,
           status: int) -> None:
    try:
        # The trailing identifier is the entity: /api/admin/products/12 acted
        # on products/12. Worth splitting out so the viewer can filter.
        bits = [b for b in path.split("/") if b]
        entity = "/".join(bits[-2:]) if len(bits) >= 2 else path
        con.execute(
            "INSERT INTO audit_log(user_id,actor,action,entity,detail,status,"
            " created_at) VALUES(?,?,?,?,?,?,?)",
            (user["id"] if user else None,
             user["name"] if user else "anonymous",
             f"{method} {path}"[:160], entity[:80], detail[:400], status,
             time.time()))
        con.commit()
    except Exception:
        pass        # auditing must never break the action it records


def prune(con, now: float | None = None) -> int:
    """Drop entries past their window. Called at most hourly.

    The sensitive/ordinary split is decided in Python rather than SQL:
    SQLite has no REGEXP built in, and one pattern applied in one place
    beats a WHERE clause listing paths that will drift from the pattern.
    """
    from . import tenancy
    tid = tenancy.CURRENT.get()
    now = now or time.time()
    if now - _last_prune.get(tid, 0) < PRUNE_EVERY:
        return 0
    _last_prune[tid] = now
    removed = 0

    # Ordinary entries past the short window.
    old = con.execute(
        "SELECT id, action FROM audit_log WHERE created_at < ?",
        (now - KEEP_DAYS * 86400,)).fetchall()
    doomed = [r["id"] for r in old if not SENSITIVE.search(r["action"] or "")]
    for i in range(0, len(doomed), 500):
        chunk = doomed[i:i + 500]
        con.execute(
            f"DELETE FROM audit_log WHERE id IN"
            f" ({','.join('?' * len(chunk))})", chunk)
        removed += len(chunk)

    # The long window applies to everything, sensitive rows included.
    removed += con.execute(
        "DELETE FROM audit_log WHERE created_at < ?",
        (now - KEEP_DAYS_SENSITIVE * 86400,)).rowcount

    # Backstop: keep the newest MAX_ROWS whatever the dates say, so a burst
    # inside the window can't fill the disk before the window expires.
    n = con.execute("SELECT COUNT(*) n FROM audit_log").fetchone()["n"]
    if n > MAX_ROWS:
        cut = con.execute(
            "SELECT id FROM audit_log ORDER BY id DESC LIMIT 1 OFFSET ?",
            (MAX_ROWS,)).fetchone()
        if cut:
            removed += con.execute("DELETE FROM audit_log WHERE id<=?",
                                   (cut["id"],)).rowcount
    con.commit()
    return removed


def should_log(method: str, path: str) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return False
    return not path.startswith(SKIP)


# ---------- reading it back ----------

def read(con, limit: int = 200, actor: str = "", entity: str = "") -> dict:
    """The log, newest first, optionally narrowed. Exposed as an endpoint by
    main.py, which owns the admin dependency."""
    where, args = ["1=1"], []
    if actor:
        where.append("actor LIKE ?"); args.append(f"%{actor}%")
    if entity:
        where.append("(entity LIKE ? OR action LIKE ?)")
        args += [f"%{entity}%", f"%{entity}%"]
    args.append(min(max(limit, 1), 500))
    rows = con.execute(
        f"SELECT * FROM audit_log WHERE {' AND '.join(where)}"
        " ORDER BY id DESC LIMIT ?", tuple(args)).fetchall()
    actors = con.execute(
        "SELECT actor, COUNT(*) n FROM audit_log WHERE actor!=''"
        " GROUP BY actor ORDER BY n DESC LIMIT 20").fetchall()
    oldest = con.execute(
        "SELECT MIN(created_at) t FROM audit_log").fetchone()["t"]
    return {"entries": [dict(r) for r in rows],
            "actors": [dict(a) for a in actors],
            "total": con.execute(
                "SELECT COUNT(*) n FROM audit_log").fetchone()["n"],
            "oldest": oldest,
            "retention": {"days": KEEP_DAYS,
                          "sensitive_days": KEEP_DAYS_SENSITIVE,
                          "max_rows": MAX_ROWS}}
