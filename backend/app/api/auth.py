"""Auth endpoints: signup, login, refresh, logout, me, Google OAuth.

Identity lives in Supabase Auth (gotrue) in production: these handlers call
Supabase's REST API and hand the SPA Supabase-issued access tokens (verified in
``app/api/deps.py`` against the project JWKS), storing the Supabase refresh token
in the same httpOnly cookie the SPA never reads.

A **legacy local path** (argon2 + self-minted HS256, ``app/services/auth.py``)
is retained for the offline test harness and dev runs where Supabase isn't
configured — selected per request by ``supabase_auth.client is None``. The two
paths are mutually exclusive; production runs Supabase only (see DECISIONS.md).
"""

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
from app.services import supabase_auth
from app.services import token as token_service
from app.services import user as user_service
from app.services.supabase_auth import SupabaseAuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

_REFRESH_COOKIE = "spacepad_refresh"
_COOKIE_PATH = "/api/auth"
# Short-lived cookie carrying the PKCE verifier across the OAuth round-trip.
_PKCE_COOKIE = "spacepad_pkce"
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


# --------------------------------------------------------------------------- #
# Legacy local path (no Supabase): self-minted HS256 tokens, argon2 passwords.
# --------------------------------------------------------------------------- #
def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookies_secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def _legacy_payload(response: Response, user: User) -> AuthOut:
    _set_refresh_cookie(response, auth_service.create_refresh_token(user.id))
    return AuthOut(
        access_token=auth_service.create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


# --------------------------------------------------------------------------- #
# Supabase path helpers.
# --------------------------------------------------------------------------- #
def _supabase_http_error(err: SupabaseAuthError) -> HTTPException:
    """Map a gotrue error to the HTTP status the SPA expects."""
    code = (err.code or "").lower()
    if code in ("user_already_exists", "email_exists"):
        return HTTPException(status.HTTP_409_CONFLICT, "That email is already registered.")
    if code in ("invalid_credentials", "invalid_grant"):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    if code == "email_not_confirmed":
        return HTTPException(
            status.HTTP_403_FORBIDDEN, "Please confirm your email before signing in."
        )
    # Otherwise surface gotrue's own status (clamped to a sane client error).
    sc = err.status_code if 400 <= err.status_code < 600 else status.HTTP_400_BAD_REQUEST
    return HTTPException(sc, err.message)


async def _profile_from_gotrue(db: AsyncSession, gotrue_user: dict) -> User:
    """Mirror a gotrue user into the ``public.users`` profile (same UUID)."""
    meta = gotrue_user.get("user_metadata") or {}
    display_name = meta.get("display_name") or meta.get("full_name") or meta.get("name")
    provider = (gotrue_user.get("app_metadata") or {}).get("provider")
    return await user_service.upsert_profile(
        db,
        user_id=gotrue_user["id"],
        email=gotrue_user.get("email") or "",
        display_name=display_name,
        email_verified=bool(gotrue_user.get("email_confirmed_at")),
        provider=provider,
    )


async def _supabase_session_payload(
    db: AsyncSession, response: Response, body: dict
) -> AuthOut:
    """Turn a gotrue session body into our AuthOut + refresh cookie."""
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    gotrue_user = body.get("user") or {}
    if not access_token or not gotrue_user:
        # Signup with email-confirmation required yields no session. We preserve
        # the Phase-4 UX (logged in at signup, verify later) by expecting the
        # project to issue a session at signup; otherwise tell the user clearly.
        raise HTTPException(
            status.HTTP_202_ACCEPTED,
            "Check your email to confirm your account before signing in.",
        )
    user = await _profile_from_gotrue(db, gotrue_user)
    if refresh_token:
        _set_refresh_cookie(response, refresh_token)
    return AuthOut(access_token=access_token, user=UserOut.model_validate(user))


# --------------------------------------------------------------------------- #
# Endpoints.
# --------------------------------------------------------------------------- #
@router.post("/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, response: Response, db: AsyncSession = Depends(get_db)):
    if supabase_auth.client is not None:
        try:
            gotrue = await supabase_auth.client.sign_up(
                email=body.email, password=body.password, username=body.username, display_name=body.display_name
            )
        except SupabaseAuthError as err:
            raise _supabase_http_error(err)
        return await _supabase_session_payload(db, response, gotrue)

    try:
        user = await user_service.create_user(
            db, email=body.email, username=body.username, password=body.password, display_name=body.display_name
        )
    except user_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        )
    except user_service.UsernameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That username is already taken."
        )
    return _legacy_payload(response, user)


@router.post("/login", response_model=AuthOut)
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    if supabase_auth.client is not None:
        try:
            gotrue = await supabase_auth.client.sign_in_password(
                email=body.email, password=body.password
            )
        except SupabaseAuthError as err:
            raise _supabase_http_error(err)
        return await _supabase_session_payload(db, response, gotrue)

    user = await user_service.get_by_email(db, body.email)
    if (
        user is None
        or user.password_hash is None
        or not auth_service.verify_password(user.password_hash, body.password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )
    return _legacy_payload(response, user)


@router.post("/refresh", response_model=AuthOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token."
        )

    if supabase_auth.client is not None:
        try:
            gotrue = await supabase_auth.client.refresh(token)
        except SupabaseAuthError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token."
            )
        return await _supabase_session_payload(db, response, gotrue)

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
    return _legacy_payload(response, user)  # rotate


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response):
    # Best-effort server-side revoke for Supabase; the cookie removal below is
    # what actually ends the session for both paths.
    token = request.cookies.get(_REFRESH_COOKIE)
    if supabase_auth.client is not None and token:
        await supabase_auth.client.sign_out(token)
    response.delete_cookie(_REFRESH_COOKIE, path=_COOKIE_PATH)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def password_reset_request(
    body: PasswordResetRequestIn, db: AsyncSession = Depends(get_db)
):
    """Send a reset link. Always 202 — never reveal whether an account exists."""
    if supabase_auth.client is not None:
        redirect_to = f"{settings.frontend_base_url}/reset-password"
        try:
            await supabase_auth.client.recover(body.email, redirect_to=redirect_to)
        except SupabaseAuthError:
            pass  # gotrue already avoids an existence oracle; stay quiet regardless
        return {"status": "accepted"}

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
    if supabase_auth.client is not None:
        # The emailed recovery link carries a token_hash; exchange it for a
        # session, then set the new password via that session.
        try:
            session = await supabase_auth.client.verify_otp(
                type="recovery", token_hash=body.token
            )
            await supabase_auth.client.update_user(
                access_token=session["access_token"],
                attributes={"password": body.new_password},
            )
        except (SupabaseAuthError, KeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This reset link is invalid or has expired.",
            )
        return await _supabase_session_payload(db, response, session)

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
    return _legacy_payload(response, user)


@router.post("/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
async def verify_email_request(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if user.email_verified:
        return {"status": "already_verified"}

    if supabase_auth.client is not None:
        try:
            await supabase_auth.client.resend(user.email, type="signup")
        except SupabaseAuthError:
            pass
        return {"status": "accepted"}

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
    if supabase_auth.client is not None:
        try:
            session = await supabase_auth.client.verify_otp(
                type="email", token_hash=body.token
            )
        except SupabaseAuthError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This verification link is invalid or has expired.",
            )
        gotrue_user = session.get("user") or {}
        if not gotrue_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This verification link is invalid or has expired.",
            )
        # gotrue confirmed the address; mirror that into the profile.
        gotrue_user.setdefault("email_confirmed_at", "confirmed")
        return await _profile_from_gotrue(db, gotrue_user)

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


# --------------------------------------------------------------------------- #
# Google OAuth.
#
# With Supabase configured, Google is a Supabase Auth provider: we redirect the
# browser through gotrue's ``/authorize`` (PKCE) and exchange the returned code
# server-side. Without Supabase, the legacy direct-to-Google auth-code flow runs.
# --------------------------------------------------------------------------- #
@router.get("/google/login")
async def google_login(response: Response):
    callback = f"{settings.frontend_base_url}/api/auth/google/callback"

    if supabase_auth.client is not None:
        verifier, challenge = supabase_auth.pkce_pair()
        url = supabase_auth.client.authorize_url(
            provider="google", redirect_to=callback, code_challenge=challenge
        )
        redirect = RedirectResponse(url)
        redirect.set_cookie(
            key=_PKCE_COOKIE,
            value=verifier,
            max_age=600,
            httponly=True,
            secure=settings.cookies_secure,
            samesite="lax",
            path=_COOKIE_PATH,
        )
        return redirect

    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured.",
        )
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": callback,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH}?{urllib.parse.urlencode(params)}")


@router.get("/google/callback")
async def google_callback(
    code: str, request: Request, db: AsyncSession = Depends(get_db)
):
    if supabase_auth.client is not None:
        verifier = request.cookies.get(_PKCE_COOKIE)
        if not verifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth session expired — please try signing in again.",
            )
        try:
            session = await supabase_auth.client.exchange_code_for_session(
                auth_code=code, code_verifier=verifier
            )
        except SupabaseAuthError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google sign-in failed.",
            )
        redirect = RedirectResponse(settings.frontend_base_url)
        await _supabase_session_payload(db, redirect, session)
        redirect.delete_cookie(_PKCE_COOKIE, path=_COOKIE_PATH)
        return redirect

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
    _set_refresh_cookie(redirect, auth_service.create_refresh_token(user.id))
    return redirect
