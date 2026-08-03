"""Sign-In-With-Ethereum-style auth + optional dev (name-only) login.

Wallet flow: GET /api/auth/nonce -> user signs the message with their wallet
(personal_sign) -> POST /api/auth/verify with the signature. We recover the
signer address with eth_account; no passwords or keys are ever handled.
"""
import secrets
import sqlite3

from .db import now

SESSION_TTL = 60 * 60 * 24 * 30  # 30 days


def login_message(address: str, nonce: str) -> str:
    return (
        "Every Reward wants you to sign in with your Ethereum account:\n"
        f"{address}\n\nNonce: {nonce}"
    )


def issue_nonce(con: sqlite3.Connection, address: str) -> str:
    address = address.lower()
    nonce = secrets.token_hex(16)
    with con:
        con.execute(
            "INSERT INTO nonces(address,nonce,created_at) VALUES(?,?,?) "
            "ON CONFLICT(address) DO UPDATE SET nonce=excluded.nonce, "
            "created_at=excluded.created_at",
            (address, nonce, now()),
        )
    return nonce


def verify_signature(address: str, nonce: str, signature: str) -> bool:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    msg = encode_defunct(text=login_message(address, nonce))
    try:
        recovered = Account.recover_message(msg, signature=signature)
    except Exception:
        return False
    return recovered.lower() == address.lower()


def get_or_create_user(con: sqlite3.Connection, address: str, cfg: dict) -> sqlite3.Row:
    address = address.lower()
    row = con.execute("SELECT * FROM users WHERE address=?", (address,)).fetchone()
    if row is None:
        is_admin = 1 if address in [a.lower() for a in cfg.get("admin_addresses", [])] else 0
        with con:
            con.execute(
                "INSERT INTO users(address,nickname,is_admin,created_at) VALUES(?,?,?,?)",
                (address, address[:6] + "…" + address[-4:], is_admin, now()),
            )
        row = con.execute("SELECT * FROM users WHERE address=?", (address,)).fetchone()
    return row


def create_dev_user(con: sqlite3.Connection, nickname: str, admin_key: str, cfg: dict) -> sqlite3.Row:
    nickname = nickname.strip()[:40] or "guest"
    is_admin = 1 if (admin_key and admin_key == cfg.get("admin_key")) else 0
    row = con.execute(
        "SELECT * FROM users WHERE address IS NULL AND nickname=?", (nickname,)
    ).fetchone()
    if row is None:
        with con:
            con.execute(
                "INSERT INTO users(address,nickname,is_admin,created_at) VALUES(NULL,?,?,?)",
                (nickname, is_admin, now()),
            )
        row = con.execute(
            "SELECT * FROM users WHERE address IS NULL AND nickname=?", (nickname,)
        ).fetchone()
    elif is_admin and not row["is_admin"]:
        with con:
            con.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
        row = con.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    return row


def create_session(con: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with con:
        con.execute(
            "INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (token, user_id, now(), now() + SESSION_TTL),
        )
    return token


def user_for_token(con: sqlite3.Connection, token: str):
    if not token:
        return None
    return con.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=? AND s.expires_at>?",
        (token, now()),
    ).fetchone()
