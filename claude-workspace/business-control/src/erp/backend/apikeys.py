"""API keys — the machine door the price book already sold.

The "API & data platform" capability promises scoped keys; this is them.
A key is named, scoped, revocable, and **bound to an account**: it acts
AS that account through every permission check the UI already trusts, so
there is no second authorization model to drift — a key bound to an
admin does admin things, a key bound to a customer sees that customer's
world, and a `read` key can do neither any harm because mutations are
refused at the front door.

The secret (`bck_<random>`) is shown ONCE at minting and stored hashed;
the row keeps a prefix so the list can say which key is which without
being able to say the key. Machine keys do not slide-expire the way
human sessions do — revocation is their lifecycle — and using one stamps
last_used_at, so a stale key is visible before it is a mystery.

Capability walls, both doors: minting 404s on a plan without `api`, and
a key from the paid days stops WORKING the moment the capability is
revoked — entitlement is read live, never baked into the secret.
"""
import hashlib
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

PREFIX = "bck_"
SCOPES = ("read", "write")

TABLES = """
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'read',
  user_id INTEGER NOT NULL,
  created_by INTEGER NOT NULL,
  created_at REAL NOT NULL,
  last_used_at REAL DEFAULT 0,
  revoked_at REAL
);
"""


def init_tables(con):
    # An earlier experiment left an api_keys table with a different shape
    # in some databases. Empty, it is debris and goes; holding rows, it
    # is somebody's history and is parked aside — never destroyed.
    cols = {r[1] for r in con.execute("PRAGMA table_info(api_keys)")}
    if cols and "scope" not in cols:
        n = con.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        if n:
            con.execute("ALTER TABLE api_keys RENAME TO api_keys_legacy")
        else:
            con.execute("DROP TABLE api_keys")
    con.executescript(TABLES)
    con.commit()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def cap_on() -> bool:
    from . import tenancy
    caps = tenancy.caps_of(tenancy.CURRENT.get())
    return caps is None or "api" in caps


def mint(con, *, name: str, scope: str, user_id: int,
         created_by: int) -> dict:
    name = str(name or "").strip()[:120]
    if not name:
        raise HTTPException(400, "a key needs a name — 'warehouse sync', "
                                 "not a mystery")
    if scope not in SCOPES:
        raise HTTPException(400, f"scope is one of {', '.join(SCOPES)}")
    secret = PREFIX + secrets.token_urlsafe(24)
    cur = con.execute(
        "INSERT INTO api_keys(name,key_hash,prefix,scope,user_id,"
        " created_by,created_at) VALUES(?,?,?,?,?,?,?)",
        (name, _hash(secret), secret[:12], scope, int(user_id),
         int(created_by), time.time()))
    con.commit()
    return {"id": cur.lastrowid, "secret": secret,
            "prefix": secret[:12], "name": name, "scope": scope}


def resolve(con, token: str):
    """The key row for a presented secret, or None. Live checks in one
    place: revoked keys are dead, and a plan without the api capability
    makes EVERY key stop working — the entitlement outranks the secret."""
    if not token.startswith(PREFIX):
        return None
    row = con.execute("SELECT * FROM api_keys WHERE key_hash=?",
                      (_hash(token),)).fetchone()
    if row is None or row["revoked_at"]:
        return None
    if not cap_on():
        return None
    now = time.time()
    if now - (row["last_used_at"] or 0) > 300:
        con.execute("UPDATE api_keys SET last_used_at=? WHERE id=?",
                    (now, row["id"]))
        con.commit()
    return row


# ── routes ───────────────────────────────────────────────────────────────────

router = APIRouter()

from .main import admin_user, get_con  # noqa: E402  (safe: included late)


def _gate():
    if not cap_on():
        raise HTTPException(404, "the API & data platform capability is "
                                 "not on this plan")


@router.get("/api/admin/api-keys")
def list_keys(user=Depends(admin_user), con=Depends(get_con)):
    _gate()
    rows = con.execute(
        "SELECT k.id, k.name, k.prefix, k.scope, k.created_at,"
        " k.last_used_at, k.revoked_at,"
        " u.name AS acts_as, c.name AS minted_by"
        " FROM api_keys k"
        " JOIN users u ON u.id=k.user_id"
        " JOIN users c ON c.id=k.created_by"
        " ORDER BY k.revoked_at IS NOT NULL, k.id DESC").fetchall()
    return [dict(r) for r in rows]


class KeyBody(BaseModel):
    name: str
    scope: str = "read"
    user_id: int | None = None    # None = acts as the minting admin


@router.post("/api/admin/api-keys")
def create_key(body: KeyBody, user=Depends(admin_user),
               con=Depends(get_con)):
    _gate()
    uid = body.user_id or user["id"]
    bound = con.execute("SELECT id FROM users WHERE id=? AND active=1",
                        (uid,)).fetchone()
    if bound is None:
        raise HTTPException(404, "no active account to bind the key to")
    out = mint(con, name=body.name, scope=body.scope, user_id=uid,
               created_by=user["id"])
    from . import notify
    notify.push(con, f"API key minted: {out['name']}",
                f"{out['prefix']}… · {out['scope']} · by {user['name']}",
                kind="api")
    return out


@router.post("/api/admin/api-keys/{kid}/revoke")
def revoke_key(kid: int, user=Depends(admin_user), con=Depends(get_con)):
    _gate()
    cur = con.execute(
        "UPDATE api_keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
        (time.time(), kid))
    if cur.rowcount == 0:
        raise HTTPException(404, "no live key with that id")
    con.commit()
    return {"ok": True}
