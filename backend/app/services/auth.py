"""Password hashing and JWT issuance/verification. Phase 4."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()
_ph = PasswordHasher()
_ALGORITHM = "HS256"

ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or the wrong type."""


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _encode(sub: uuid.UUID, token_type: str, ttl_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub),
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, ACCESS, settings.jwt_access_ttl_seconds)


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, REFRESH, settings.jwt_refresh_ttl_seconds)


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc))
    if payload.get("type") != expected_type:
        raise TokenError("Unexpected token type.")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise TokenError("Invalid subject.")
