"""Supabase-path auth handlers.

The offline suite can't reach a real gotrue, so we inject a fake Supabase client
(``supabase_auth.client``) and assert the handlers (a) call the right gotrue
method, (b) turn its session body into our AuthOut + refresh cookie, and (c) map
gotrue error codes to the HTTP statuses the SPA expects. The legacy path is
exercised by test_auth_api.py / test_auth_recovery_api.py; here ``client`` is
always set, so the Supabase branch runs.
"""

import uuid

import pytest

from app.services import auth as auth_service
from app.services import supabase_auth
from app.services.supabase_auth import SupabaseAuthError

# Must contain hex letters: an all-digits UUID gets coerced to a float by
# SQLite's NUMERIC column affinity on round-trip (the in-memory test DB).
USER_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _session(email="a@example.com", display_name="Ada", *, provider="email"):
    return {
        "access_token": "supa-access-token",
        "refresh_token": "supa-refresh-token",
        "user": {
            "id": USER_ID,
            "email": email,
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "user_metadata": {"display_name": display_name},
            "app_metadata": {"provider": provider},
        },
    }


class FakeSupabase:
    """Records calls and returns canned gotrue responses; raise_with lets a test
    force a specific gotrue error from the next call to a named method."""

    def __init__(self):
        self.calls = []
        self.raise_with: dict[str, SupabaseAuthError] = {}

    def _maybe_raise(self, name):
        if name in self.raise_with:
            raise self.raise_with[name]

    async def sign_up(self, *, email, password, display_name):
        self.calls.append(("sign_up", email))
        self._maybe_raise("sign_up")
        return _session(email=email, display_name=display_name)

    async def sign_in_password(self, *, email, password):
        self.calls.append(("sign_in_password", email))
        self._maybe_raise("sign_in_password")
        return _session(email=email)

    async def refresh(self, refresh_token):
        self.calls.append(("refresh", refresh_token))
        self._maybe_raise("refresh")
        return _session()

    async def sign_out(self, access_token):
        self.calls.append(("sign_out", access_token))

    async def recover(self, email, *, redirect_to=None):
        self.calls.append(("recover", email))
        self._maybe_raise("recover")

    async def resend(self, email, *, type="signup"):
        self.calls.append(("resend", email))

    async def verify_otp(self, *, type, token_hash):
        self.calls.append(("verify_otp", type, token_hash))
        self._maybe_raise("verify_otp")
        return _session()

    async def update_user(self, *, access_token, attributes):
        self.calls.append(("update_user", attributes))

    def authorize_url(self, *, provider, redirect_to, code_challenge):
        self.calls.append(("authorize_url", provider, code_challenge))
        return f"https://proj.supabase.co/auth/v1/authorize?provider={provider}"

    async def exchange_code_for_session(self, *, auth_code, code_verifier):
        self.calls.append(("exchange_code_for_session", auth_code, code_verifier))
        self._maybe_raise("exchange_code_for_session")
        return _session(provider="google")


@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(supabase_auth, "client", fake)
    return fake


# --- signup / login ----------------------------------------------------------
async def test_supabase_signup_returns_token_and_sets_cookie(client, fake_supabase):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": "a@example.com", "password": "password123", "display_name": "Ada"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"] == "supa-access-token"
    assert body["user"]["email"] == "a@example.com"
    assert body["user"]["display_name"] == "Ada"
    assert body["user"]["email_verified"] is True
    assert "spacepad_refresh" in resp.cookies
    assert ("sign_up", "a@example.com") in fake_supabase.calls


async def test_supabase_signup_duplicate_conflicts(client, fake_supabase):
    fake_supabase.raise_with["sign_up"] = SupabaseAuthError(
        400, "already registered", code="user_already_exists"
    )
    resp = await client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "password123"}
    )
    assert resp.status_code == 409


async def test_supabase_login_success(client, fake_supabase):
    resp = await client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "password123"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "supa-access-token"
    assert "spacepad_refresh" in resp.cookies


async def test_supabase_login_invalid_credentials_401(client, fake_supabase):
    fake_supabase.raise_with["sign_in_password"] = SupabaseAuthError(
        400, "bad", code="invalid_credentials"
    )
    resp = await client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "wrongpass1"}
    )
    assert resp.status_code == 401


async def test_supabase_login_email_not_confirmed_403(client, fake_supabase):
    fake_supabase.raise_with["sign_in_password"] = SupabaseAuthError(
        400, "confirm first", code="email_not_confirmed"
    )
    resp = await client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "password123"}
    )
    assert resp.status_code == 403


# --- refresh / logout --------------------------------------------------------
async def test_supabase_refresh_rotates_cookie(client, fake_supabase):
    resp = await client.post(
        "/api/auth/refresh", cookies={"spacepad_refresh": "old-refresh"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "supa-access-token"
    assert "spacepad_refresh" in resp.cookies
    assert ("refresh", "old-refresh") in fake_supabase.calls


async def test_supabase_refresh_without_cookie_401(client, fake_supabase):
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_supabase_refresh_invalid_token_401(client, fake_supabase):
    fake_supabase.raise_with["refresh"] = SupabaseAuthError(401, "bad", code="invalid_grant")
    resp = await client.post(
        "/api/auth/refresh", cookies={"spacepad_refresh": "nope"}
    )
    assert resp.status_code == 401


async def test_supabase_logout_revokes_and_clears(client, fake_supabase):
    resp = await client.post(
        "/api/auth/logout", cookies={"spacepad_refresh": "tok"}
    )
    assert resp.status_code == 204
    assert ("sign_out", "tok") in fake_supabase.calls


# --- password reset ----------------------------------------------------------
async def test_supabase_password_reset_request_always_202(client, fake_supabase):
    resp = await client.post(
        "/api/auth/password-reset/request", json={"email": "a@example.com"}
    )
    assert resp.status_code == 202
    assert ("recover", "a@example.com") in fake_supabase.calls


async def test_supabase_password_reset_request_202_even_on_error(client, fake_supabase):
    # gotrue avoids an existence oracle; we stay quiet even if it errors.
    fake_supabase.raise_with["recover"] = SupabaseAuthError(500, "boom")
    resp = await client.post(
        "/api/auth/password-reset/request", json={"email": "x@example.com"}
    )
    assert resp.status_code == 202


async def test_supabase_password_reset_confirm_success(client, fake_supabase):
    resp = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "recovery-hash", "new_password": "brandnewpass1"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "supa-access-token"
    assert ("verify_otp", "recovery", "recovery-hash") in fake_supabase.calls
    assert any(c[0] == "update_user" for c in fake_supabase.calls)


async def test_supabase_password_reset_confirm_bad_token_400(client, fake_supabase):
    fake_supabase.raise_with["verify_otp"] = SupabaseAuthError(401, "expired")
    resp = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "bad", "new_password": "brandnewpass1"},
    )
    assert resp.status_code == 400


# --- email verification ------------------------------------------------------
async def test_supabase_verify_email_confirm(client, fake_supabase):
    resp = await client.post(
        "/api/auth/verify-email/confirm", json={"token": "email-hash"}
    )
    assert resp.status_code == 200
    assert resp.json()["email_verified"] is True
    assert ("verify_otp", "email", "email-hash") in fake_supabase.calls


async def test_supabase_verify_email_request_resends(client, fake_supabase, session_factory):
    # An unverified profile + a forged (legacy HS256) access token resolves via
    # deps.get_or_sync_from_claims; the handler then asks gotrue to resend.
    from app.models.user import User

    async with session_factory() as db:
        user = User(id=uuid.UUID(USER_ID), email="a@example.com", email_verified=False)
        db.add(user)
        await db.commit()
    token = auth_service.create_access_token(uuid.UUID(USER_ID))
    resp = await client.post(
        "/api/auth/verify-email/request", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 202
    assert ("resend", "a@example.com") in fake_supabase.calls


# --- Google OAuth via Supabase ----------------------------------------------
async def test_supabase_google_login_sets_pkce_and_redirects(client, fake_supabase):
    resp = await client.get("/api/auth/google/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "supabase.co/auth/v1/authorize" in resp.headers["location"]
    assert "spacepad_pkce" in resp.cookies


async def test_supabase_google_callback_exchanges_code(client, fake_supabase):
    resp = await client.get(
        "/api/auth/google/callback",
        params={"code": "abc"},
        cookies={"spacepad_pkce": "verifier-123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    assert "spacepad_refresh" in resp.cookies
    assert ("exchange_code_for_session", "abc", "verifier-123") in fake_supabase.calls


async def test_supabase_google_callback_missing_pkce_400(client, fake_supabase):
    resp = await client.get(
        "/api/auth/google/callback", params={"code": "abc"}, follow_redirects=False
    )
    assert resp.status_code == 400
