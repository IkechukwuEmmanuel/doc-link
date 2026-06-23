"""Auth dependencies.

Access tokens are now Supabase-issued JWTs (ES256, verified against the project
JWKS). The token's ``sub`` is the ``auth.users`` UUID; we map it to a
``public.users`` profile row (same UUID), creating/refreshing the profile on
first use. A legacy HS256 path (self-minted with ``jwt_secret``) is retained for
the offline test harness and is rejected in production.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User
from app.services import user as user_service

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)

_jwk_client: jwt.PyJWKClient | None = None


def _jwks() -> jwt.PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(settings.supabase_jwks_url)
    return _jwk_client


class AuthError(Exception):
    pass


def verify_access_token(token: str) -> tuple[dict, bool]:
    """Verify an access token. Returns (claims, is_supabase).

    Routing is by the token's ``alg`` header: asymmetric (ES256/RS256) tokens are
    Supabase user tokens verified against the project JWKS; HS256 tokens are the
    legacy self-minted kind, accepted only outside production (the test harness).
    """
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc))

    if alg in ("ES256", "RS256"):
        if not settings.supabase_url:
            raise AuthError("Supabase not configured for token verification.")
        try:
            signing_key = _jwks().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=settings.supabase_jwt_aud,
            )
        except Exception as exc:  # network, signature, expiry, audience…
            raise AuthError(str(exc))
        return claims, True

    if alg == "HS256":
        # Legacy/offline path. Never trust a symmetric, self-minted token in
        # production once Supabase is the issuer.
        if settings.environment == "production":
            raise AuthError("Legacy HS256 tokens are not accepted in production.")
        try:
            claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc))
        if claims.get("type") != "access":
            raise AuthError("Unexpected token type.")
        return claims, False

    raise AuthError(f"Unsupported token algorithm: {alg}.")


async def _resolve_user(token: str, db: AsyncSession) -> User | None:
    claims, is_supabase = verify_access_token(token)
    return await user_service.get_or_sync_from_claims(
        db, claims, mark_verified=is_supabase
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )
    try:
        user = await _resolve_user(creds.credentials, db)
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists."
        )
    return user


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if creds is None:
        return None
    try:
        return await _resolve_user(creds.credentials, db)
    except AuthError:
        return None
