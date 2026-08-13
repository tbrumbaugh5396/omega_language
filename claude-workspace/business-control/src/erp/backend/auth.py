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


def user_for_token(con, token: str):
    if not token:
        return None
    row = con.execute(
        "SELECT * FROM users WHERE token=? AND active=1", (token,)).fetchone()
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
        role = "customer"
    is_admin = 1 if valid_key else 0
    row = con.execute(
        "SELECT * FROM users WHERE lower(name)=lower(?)", (name,)).fetchone()
    if row is None:
        if cfg.get("require_passwords") and not password:
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
            "is_admin": bool(u["is_admin"]), "token": u["token"]}
