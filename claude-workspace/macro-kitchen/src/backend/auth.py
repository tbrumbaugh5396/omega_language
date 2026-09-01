"""Password hashing (stdlib pbkdf2 — no external deps) and session tokens."""
import hashlib
import secrets

_ITER = 200_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex). Generates a salt when none is given."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hex: str) -> bool:
    _, actual = hash_password(password, salt)
    return secrets.compare_digest(actual, expected_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)
