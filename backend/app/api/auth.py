"""Auth endpoints: signup, login, refresh, logout, me, Google OAuth. Phase 4."""

from __future__ import annotations

import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.token import TokenPurpose
from app.models.user import User
from app.schemas.auth import (
    AuthOut,
    EmailVerifyConfirmIn,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    SignupIn,
    UserOut,
)
from app.services import auth as auth_service
from app.services import email as email_service
from app.services import token as token_service
from app.services import user as user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

_REFRESH_COOKIE = "spacepad_refresh"
_COOKIE_PATH = "/api/auth"
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _set_refresh_cookie(response: Response, user: User) -> None:
    token = auth_service.create_refresh_token(user.id)
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookies_secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def _auth_payload(user: User) -> AuthOut:
    return AuthOut(
        access_token=auth_service.create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        user = await user_service.create_user(
            db, email=body.email, password=body.password, display_name=body.display_name
        )
    except user_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        )
    _set_refresh_cookie(response, user)
    return _auth_payload(user)


@router.post("/login", response_model=AuthOut)
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    user = await user_service.get_by_email(db, body.email)
    if (
        user is None
        or user.password_hash is None
        or not auth_service.verify_password(user.password_hash, body.password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )
    _set_refresh_cookie(response, user)
    return _auth_payload(user)


@router.post("/refresh", response_model=AuthOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token."
        )
    try:
        user_id = auth_service.decode_token(token, auth_service.REFRESH)
    except auth_service.TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token."
        )
    user = await user_service.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists."
        )
    _set_refresh_cookie(response, user)  # rotate
    return _auth_payload(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(_REFRESH_COOKIE, path=_COOKIE_PATH)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def password_reset_request(
    body: PasswordResetRequestIn, db: AsyncSession = Depends(get_db)
):
    """Email a single-use reset link. Always 202 — never reveal whether an
    account exists for the address (PRD §6.4)."""
    user = await user_service.get_by_email(db, body.email)
    if user is not None and user.password_hash is not None:
        raw = await token_service.issue(
            db,
            user_id=user.id,
            purpose=TokenPurpose.password_reset,
            ttl_seconds=settings.password_reset_ttl_seconds,
        )
        link = f"{settings.frontend_base_url}/reset-password?token={raw}"
        subject, message = email_service.password_reset_email(link)
        await email_service.send_email(to=user.email, subject=subject, body=message)
    return {"status": "accepted"}


@router.post("/password-reset/confirm", response_model=AuthOut)
async def password_reset_confirm(
    body: PasswordResetConfirmIn, response: Response, db: AsyncSession = Depends(get_db)
):
    user_id = await token_service.consume(
        db, raw=body.token, purpose=TokenPurpose.password_reset
    )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )
    user = await user_service.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Account no longer exists."
        )
    await user_service.set_password(db, user, body.new_password)
    _set_refresh_cookie(response, user)
    return _auth_payload(user)


@router.post("/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
async def verify_email_request(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if user.email_verified:
        return {"status": "already_verified"}
    raw = await token_service.issue(
        db,
        user_id=user.id,
        purpose=TokenPurpose.email_verify,
        ttl_seconds=settings.password_reset_ttl_seconds,
    )
    link = f"{settings.frontend_base_url}/verify-email?token={raw}"
    subject, message = email_service.verify_email_email(link)
    await email_service.send_email(to=user.email, subject=subject, body=message)
    return {"status": "accepted"}


@router.post("/verify-email/confirm", response_model=UserOut)
async def verify_email_confirm(
    body: EmailVerifyConfirmIn, db: AsyncSession = Depends(get_db)
):
    user_id = await token_service.consume(
        db, raw=body.token, purpose=TokenPurpose.email_verify
    )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link is invalid or has expired.",
        )
    user = await user_service.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Account no longer exists."
        )
    await user_service.mark_email_verified(db, user)
    return user


@router.get("/google/login")
async def google_login():
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured.",
        )
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": f"{settings.frontend_base_url}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH}?{urllib.parse.urlencode(params)}")


@router.get("/google/callback")
async def google_callback(
    code: str, response: Response, db: AsyncSession = Depends(get_db)
):
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured.",
        )
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": f"{settings.frontend_base_url}/api/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google token exchange failed.",
            )
        access = token_resp.json()["access_token"]
        info_resp = await client.get(
            _GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"}
        )
        if info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not fetch Google profile.",
            )
        info = info_resp.json()

    user = await user_service.upsert_google_user(
        db,
        email=info["email"],
        subject=info["sub"],
        display_name=info.get("name"),
    )
    redirect = RedirectResponse(settings.frontend_base_url)
    _set_refresh_cookie(redirect, user)
    return redirect
