"""Auth dependencies. Phase 4."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.services import auth as auth_service
from app.services import user as user_service

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )
    try:
        user_id = auth_service.decode_token(creds.credentials, auth_service.ACCESS)
    except auth_service.TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    user = await user_service.get_by_id(db, user_id)
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
        user_id = auth_service.decode_token(creds.credentials, auth_service.ACCESS)
    except auth_service.TokenError:
        return None
    return await user_service.get_by_id(db, user_id)
