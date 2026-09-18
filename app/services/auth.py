from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


PBKDF2_ITERATIONS = 310_000
MINIMUM_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class SessionToken:
    raw: str
    token_hash: str
    expires_at: str


def hash_password(password: str) -> str:
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters.")
    if password.lower() in {"password1234", "administrator", "changeme12345"}:
        raise ValueError("Choose a password that is not commonly used.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.urlsafe_b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(digest, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def create_session(hours: int = 12) -> SessionToken:
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    return SessionToken(raw, hash_token(raw), expires.isoformat())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_expired(value: str) -> bool:
    return datetime.fromisoformat(value) <= datetime.now(timezone.utc)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode()
