async def _signup(client, email="a@example.com", password="password123", **extra):
    return await client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, **extra},
    )


async def test_signup_returns_access_token_and_sets_cookie(client):
    resp = await _signup(client, display_name="Ada")
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == "a@example.com"
    assert body["user"]["display_name"] == "Ada"
    assert "spacepad_refresh" in resp.cookies


async def test_signup_duplicate_email_conflicts(client):
    await _signup(client)
    dup = await _signup(client)
    assert dup.status_code == 409


async def test_signup_normalizes_email_case(client):
    await _signup(client, email="Mixed@Example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "mixed@example.com", "password": "password123"},
    )
    assert login.status_code == 200


async def test_login_wrong_password_unauthorized(client):
    await _signup(client)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "wrongpass1"},
    )
    assert resp.status_code == 401


async def test_me_requires_valid_token(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401

    token = (await _signup(client)).json()["access_token"]
    ok = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["email"] == "a@example.com"


async def test_refresh_rotates_and_issues_new_access(client):
    signup = await _signup(client)
    cookie = signup.cookies["spacepad_refresh"]
    resp = await client.post(
        "/api/auth/refresh", cookies={"spacepad_refresh": cookie}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert "spacepad_refresh" in resp.cookies


async def test_refresh_without_cookie_unauthorized(client):
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_access_token_rejected_as_refresh(client):
    # An access token must not be usable on the refresh endpoint.
    access = (await _signup(client)).json()["access_token"]
    resp = await client.post(
        "/api/auth/refresh", cookies={"spacepad_refresh": access}
    )
    assert resp.status_code == 401


async def test_claim_pad_flow(client):
    token = (await _signup(client)).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    await client.post("/api/pads", json={"slug": "claim-me"})

    claim = await client.post("/api/pads/claim-me/claim", headers=auth)
    assert claim.status_code == 200
    body = claim.json()
    assert body["owner_id"] is not None
    assert body["is_anonymous"] is False


async def test_claim_requires_auth(client):
    await client.post("/api/pads", json={"slug": "claim-anon"})
    assert (await client.post("/api/pads/claim-anon/claim")).status_code == 401


async def test_claim_already_owned_conflicts(client):
    t1 = (await _signup(client, email="one@example.com")).json()["access_token"]
    t2 = (await _signup(client, email="two@example.com")).json()["access_token"]
    await client.post("/api/pads", json={"slug": "contested"})

    first = await client.post(
        "/api/pads/contested/claim", headers={"Authorization": f"Bearer {t1}"}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/pads/contested/claim", headers={"Authorization": f"Bearer {t2}"}
    )
    assert second.status_code == 409


async def test_google_upsert_creates_user(client, monkeypatch):
    # Mock Google's token + userinfo exchange.
    import app.api.auth as auth_api

    class FakeResp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            return FakeResp(200, {"access_token": "g-access"})

        async def get(self, url, headers=None):
            return FakeResp(
                200,
                {"email": "g@example.com", "sub": "google-123", "name": "Goo Gle"},
            )

    monkeypatch.setattr(auth_api.settings, "google_oauth_client_id", "cid", raising=False)
    monkeypatch.setattr(auth_api.httpx, "AsyncClient", FakeClient)

    resp = await client.get(
        "/api/auth/google/callback", params={"code": "abc"}, follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert "spacepad_refresh" in resp.cookies
