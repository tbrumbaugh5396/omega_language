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
    return {"entries": [dict(r) for r in rows],
            "actors": [dict(a) for a in actors],
            "total": con.execute(
                "SELECT COUNT(*) n FROM audit_log").fetchone()["n"]}
