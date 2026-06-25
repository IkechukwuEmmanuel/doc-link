"""Supabase Auth (gotrue) client. Supabase phase.

FastAPI is still the only backend the frontend talks to (see DECISIONS.md), but
identity now lives in Supabase Auth instead of FastAPI's own argon2/PyJWT code.
This module is the thin httpx wrapper FastAPI's auth handlers call:

  - email/password signup, login, refresh, logout
  - password-recovery email
  - admin operations (service-role) used to provision/confirm users

Supabase issues its own JWTs (ES256, verified against the project JWKS in
app/api/deps.py); this module never mints or verifies tokens itself — it just
relays gotrue's responses. All calls require the public ``apikey`` header; admin
calls additionally authenticate with the service-role key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse

import httpx

from app.core.config import get_settings

settings = get_settings()


def pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` for an OAuth PKCE flow (S256). The
    verifier is stashed in a short-lived httpOnly cookie at ``/authorize`` time
    and replayed at the ``/token`` exchange; the challenge travels in the URL."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class SupabaseAuthError(Exception):
    """A gotrue call failed. ``code`` is gotrue's machine-readable error code
    (e.g. ``invalid_credentials``, ``email_not_confirmed``, ``user_already_exists``)
    when present, so callers can map it to the right HTTP status."""

    def __init__(self, status_code: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


def _error_from(resp: httpx.Response) -> SupabaseAuthError:
    try:
        body = resp.json()
    except Exception:
        return SupabaseAuthError(resp.status_code, resp.text or "Auth request failed.")
    # gotrue uses a few error shapes across endpoints; normalise them.
    code = body.get("error_code") or body.get("code") or body.get("error")
    message = (
        body.get("msg")
        or body.get("error_description")
        or body.get("message")
        or body.get("error")
        or "Auth request failed."
    )
    if not isinstance(code, str):
        code = None
    return SupabaseAuthError(resp.status_code, str(message), code)


class SupabaseAuthClient:
    def __init__(self, url: str, anon_key: str, service_role_key: str) -> None:
        self._base = url.rstrip("/") + "/auth/v1"
        self._anon = anon_key
        self._svc = service_role_key

    def _headers(self, *, admin: bool = False, access_token: str | None = None) -> dict:
        key = self._svc if admin else self._anon
        headers = {"apikey": key, "Content-Type": "application/json"}
        bearer = access_token or (self._svc if admin else None)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    async def _post(self, path: str, *, json: dict, headers: dict) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{self._base}{path}", json=json, headers=headers)
        if resp.status_code >= 400:
            raise _error_from(resp)
        return resp.json() if resp.content else {}

    # --- public (anon-key) flows ------------------------------------------- #
    async def sign_up(
        self, *, email: str, password: str, username: str, display_name: str | None
    ) -> dict:
        """Create a user. Returns the gotrue body; if email confirmation is
        disabled it includes a ``session`` (access/refresh tokens), otherwise the
        user must confirm before logging in."""
        return await self._post(
            "/signup",
            json={
                "email": email,
                "password": password,
                "data": {
                    "username": username,
                    "display_name": display_name
                } if (username or display_name) else {},
            },
            headers=self._headers(),
        )

    async def sign_in_password(self, *, email: str, password: str) -> dict:
        """Password grant → ``{access_token, refresh_token, user, ...}``."""
        return await self._post(
            "/token?grant_type=password",
            json={"email": email, "password": password},
            headers=self._headers(),
        )

    async def refresh(self, refresh_token: str) -> dict:
        return await self._post(
            "/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
            headers=self._headers(),
        )

    async def sign_out(self, access_token: str) -> None:
        try:
            await self._post(
                "/logout", json={}, headers=self._headers(access_token=access_token)
            )
        except SupabaseAuthError:
            # Logout is best-effort — an already-invalid token still "logs out".
            pass

    async def recover(self, email: str, *, redirect_to: str | None = None) -> None:
        """Send a password-recovery email. gotrue intentionally returns 200 even
        for unknown addresses (no account-existence oracle)."""
        path = "/recover"
        if redirect_to:
            path = f"/recover?redirect_to={redirect_to}"
        await self._post(path, json={"email": email}, headers=self._headers())

    async def resend(self, email: str, *, type: str = "signup") -> None:
        """Resend a confirmation/verification email."""
        await self._post(
            "/resend", json={"email": email, "type": type}, headers=self._headers()
        )

    async def verify_otp(self, *, type: str, token_hash: str) -> dict:
        """Exchange an email-link token_hash for a session (recovery / email
        confirmation). Returns ``{access_token, refresh_token, user, ...}``."""
        return await self._post(
            "/verify",
            json={"type": type, "token_hash": token_hash},
            headers=self._headers(),
        )

    async def update_user(self, *, access_token: str, attributes: dict) -> dict:
        """Update the authenticated user (e.g. set a new password) using a
        session access token (such as one from a recovery verify_otp)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.put(
                f"{self._base}/user",
                json=attributes,
                headers=self._headers(access_token=access_token),
            )
        if resp.status_code >= 400:
            raise _error_from(resp)
        return resp.json() if resp.content else {}

    # --- OAuth (Google et al.) via Supabase's provider integration --------- #
    def authorize_url(self, *, provider: str, redirect_to: str, code_challenge: str) -> str:
        """Build the gotrue ``/authorize`` URL the browser is redirected to.
        Supabase then bounces through the provider (Google) and back to
        ``redirect_to`` with a ``?code=`` we exchange server-side (PKCE)."""
        query = urllib.parse.urlencode(
            {
                "provider": provider,
                "redirect_to": redirect_to,
                "code_challenge": code_challenge,
                "code_challenge_method": "s256",
            }
        )
        return f"{self._base}/authorize?{query}"

    async def exchange_code_for_session(
        self, *, auth_code: str, code_verifier: str
    ) -> dict:
        """Exchange an OAuth/PKCE ``code`` for a session
        (``{access_token, refresh_token, user, ...}``)."""
        return await self._post(
            "/token?grant_type=pkce",
            json={"auth_code": auth_code, "code_verifier": code_verifier},
            headers=self._headers(),
        )

    # --- admin (service-role) flows ---------------------------------------- #
    async def admin_create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None,
        email_confirm: bool,
    ) -> dict:
        return await self._post(
            "/admin/users",
            json={
                "email": email,
                "password": password,
                "email_confirm": email_confirm,
                "user_metadata": {"display_name": display_name} if display_name else {},
            },
            headers=self._headers(admin=True),
        )


def _build_client() -> SupabaseAuthClient | None:
    if not settings.supabase_enabled:
        return None
    return SupabaseAuthClient(
        settings.supabase_url,
        settings.supabase_anon_key,
        settings.supabase_service_role_key,
    )


# Module singleton. None when Supabase isn't configured (e.g. the unit-test
# harness, which injects a fake or exercises the dev/legacy path instead).
client: SupabaseAuthClient | None = _build_client()
