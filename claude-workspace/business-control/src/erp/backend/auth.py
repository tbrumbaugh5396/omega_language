"""Token auth. Login is name-based; accounts may carry a password (set on
first sign-in via the same field, then required). The admin key grants admin."""
import hashlib
import hmac
import secrets

from . import db


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt),
                            200_000).hex()
    return f"{salt}${h}"


def verify_password(stored: str, pw: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt),
                               200_000).hex()
    return hmac.compare_digest(calc, h)


# ---------- time-clock PINs ----------
#
# A PIN is looked up *by the PIN itself*: someone walks up to a tablet in a
# warehouse and types four digits, with no username. That rules out the
# per-user salt used for passwords — verifying would mean running a slow KDF
# against every employee on every punch.
#
# So the PIN is hashed with a secret the database doesn't contain. A dump of
# users.db no longer reveals anybody's PIN, and the four-digit space can't be
# enumerated without also stealing the config file. That is the threat this
# is actually defending against; it is deliberately weaker than the password
# path, and the short input is why.


def hash_pin(pin: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), pin.strip().encode(),
                    hashlib.sha256).hexdigest()


def check_pin(con, pin: str, pepper: str):
    """The employee with this PIN, or None. Compared as a hash, so the
    lookup is still a single indexed equality."""
    pin = (pin or "").strip()
    if not pin:
        return None
    return con.execute(
        "SELECT * FROM users WHERE pin_hash=? AND pin_hash!='' AND active=1",
        (hash_pin(pin, pepper),)).fetchone()


def migrate_pins(con, pepper: str) -> int:
    """Hash any PINs still sitting in the old plaintext column, then clear it.

    Runs at boot and is a no-op once done. Left in place rather than made a
    one-off script: an install that was never upgraded is exactly the one
    still holding plaintext PINs.
    """
    for stmt in ("ALTER TABLE users ADD COLUMN pin_hash TEXT DEFAULT ''",
                 "ALTER TABLE users ADD COLUMN clock_token TEXT DEFAULT ''"):
        try:
            con.execute(stmt)
        except Exception:
            pass
    try:
        rows = con.execute(
            "SELECT id, pin FROM users WHERE pin IS NOT NULL AND pin!=''"
        ).fetchall()
    except Exception:
        return 0                      # column already gone
    for r in rows:
        con.execute("UPDATE users SET pin_hash=?, pin='' WHERE id=?",
                    (hash_pin(r["pin"], pepper), r["id"]))
    con.commit()
    return len(rows)


# ---------- clock badges ----------
#
# A badge identifies someone at the time clock. It deliberately is not a
# login: the worst a stolen badge can do is clock its owner in or out, which
# a supervisor can see and correct, whereas a stolen sign-in QR would be an
# account. Keeping them separate is the whole point — a badge gets left on a
# lanyard, photographed, and pinned to a noticeboard, and none of that should
# be a way into the business.
#
# It is stable rather than single-use, because a badge you have to reissue
# after every shift is a badge nobody uses.

def clock_badge(con, user_id: int, reset: bool = False) -> str:
    row = con.execute("SELECT clock_token FROM users WHERE id=?",
                      (user_id,)).fetchone()
    if row is None:
        raise ValueError("no such user")
    token = row["clock_token"]
    if reset or not token:
        token = "bc:clock:" + secrets.token_urlsafe(18)
        con.execute("UPDATE users SET clock_token=? WHERE id=?",
                    (token, user_id))
        con.commit()
    return token


def user_for_badge(con, token: str):
    token = (token or "").strip()
    if not token.startswith("bc:clock:"):
        return None
    return con.execute(
        "SELECT * FROM users WHERE clock_token=? AND clock_token!=''"
        " AND active=1", (token,)).fetchone()


def passwords_required(cfg) -> bool:
    """An explicit require_passwords answers either way. Unset, the
    question becomes "is this install public?" — name-only sign-in is
    fine on a trusted LAN and reckless on the internet, and the operator
    who set public_base_url should not also have to remember this row of
    the checklist."""
    v = cfg.get("require_passwords")
    if v is not None:
        return bool(v)
    return bool(cfg.get("public_base_url"))


def user_for_token(con, token: str):
    if not token:
        return None
    row = con.execute(
        "SELECT * FROM users WHERE token=? AND active=1", (token,)).fetchone()
    if row is None:
        return None
    # The sliding window: a token unused for session_days expires — and
    # expires DEAD, rotated so the stale bearer cannot be replayed. Use
    # refreshes the stamp (at most hourly, so this read path stays a
    # read). 0 on the row means pre-window history: stamped on first
    # touch, so shipping this change signs nobody out.
    from .main import CFG                       # tenant-aware, late
    days = CFG.get("session_days", 30) or 0
    if days:
        import time as _t
        now = _t.time()
        seen = row["token_seen_at"] or 0
        if seen and now - seen > days * 86400:
            con.execute(
                "UPDATE users SET token=?, token_seen_at=0 WHERE id=?",
                (secrets.token_urlsafe(24), row["id"]))
            con.commit()
            return None
        if now - seen > 3600:
            con.execute("UPDATE users SET token_seen_at=? WHERE id=?",
                        (now, row["id"]))
            con.commit()
    return row


def login(con, name: str, role: str, region: str, admin_key: str, cfg: dict,
          password: str = ""):
    """Find-or-create a user by name. Returns the full row.

    Passwords: an account with one requires it (PermissionError otherwise);
    an account without one adopts the password on the first sign-in that
    supplies it. With require_passwords on, new accounts must supply one.

    The 'owner' (founder) role can only be claimed with the admin key —
    without it the request quietly falls back to customer. Owners always
    carry the admin flag."""
    name = name.strip()
    if not name:
        raise ValueError("name required")
    valid_key = bool(admin_key) and admin_key == cfg.get("admin_key")
    if role == "owner":
        if not valid_key:
            role = "customer"
    elif role not in ("customer", "distributor", "influencer", "employee"):
        # The school roles (roles.py) are conferred, not claimed: only the
        # key-holder mints them directly — everyone else's request rides
        # the role-claims queue and lands here as a plain customer.
        if not (valid_key and role in ("teacher", "volunteer", "director",
                                       "board", "donor")):
            role = "customer"
    if (cfg.get("public_base_url") and not valid_key
            and role != "customer"):
        # Public installs confer EVERY non-customer role — partner and
        # staff included. On a LAN the historic self-serve picker is a
        # dev convenience; on the internet it is an escalation form.
        role = "customer"
    is_admin = 1 if valid_key else 0
    row = con.execute(
        "SELECT * FROM users WHERE lower(name)=lower(?)", (name,)).fetchone()
    if row is None:
        if passwords_required(cfg) and not password:
            raise ValueError("a password is required to create an account")
        token = secrets.token_urlsafe(24)
        con.execute(
            "INSERT INTO users(name, role, token, region, is_admin,"
            " password_hash, created_at) VALUES(?,?,?,?,?,?,?)",
            (name, role, token, region, is_admin,
             hash_password(password) if password else "", db.now()))
        con.commit()
        return con.execute("SELECT * FROM users WHERE token=?",
                           (token,)).fetchone()
    if row["password_hash"]:
        if not verify_password(row["password_hash"], password):
            raise PermissionError("wrong password for this account")
    elif password:
        con.execute("UPDATE users SET password_hash=? WHERE id=?",
                    (hash_password(password), row["id"]))
        con.commit()
    if valid_key and (not row["is_admin"] or
                      (role == "owner" and row["role"] != "owner")):
        new_role = "owner" if role == "owner" else row["role"]
        con.execute("UPDATE users SET is_admin=1, role=? WHERE id=?",
                    (new_role, row["id"]))
        con.commit()
    return con.execute("SELECT * FROM users WHERE id=?",
                       (row["id"],)).fetchone()


def user_json(u) -> dict:
    return {"id": u["id"], "name": u["name"], "role": u["role"],
            "job": u["job"], "employment": u["employment"],
            "region": u["region"], "email": u["email"],
            "has_password": bool(u["password_hash"]),
            "requested_role": u["requested_role"] or "",
            "is_admin": bool(u["is_admin"]), "token": u["token"]}
