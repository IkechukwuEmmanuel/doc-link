"""Pad naming, redirects, and the token-based claim flow (Path A)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _signup(client, email):
    username = email.split("@")[0].replace(".", "").replace("+", "")
    if len(username) < 3:
        username += "user"
    r = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "username": username},
    )
    return r.json()["access_token"], username


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _claim(client, slug, token, auth, pin=None):
    body = {"token": token}
    if pin is not None:
        body["pin"] = pin
    return await client.post(f"/api/pads/{slug}/claim", json=body, headers=auth)


async def _gen_token(client, slug):
    return (await client.post(f"/api/pads/{slug}/claim-token")).json()["token"]


# --- rename: namespaced uniqueness, reject-on-collision -----------------------

async def test_claimed_rename_creates_resolvable_redirect(client):
    token, username = await _signup(client, "alice@example.com")
    await client.post("/api/pads", json={"slug": "crisp-badger-68"})
    ct = await _gen_token(client, "crisp-badger-68")
    assert (await _claim(client, "crisp-badger-68", ct, _auth(token))).status_code == 200

    # rename to "tester"
    r = await client.patch(
        "/api/pads/crisp-badger-68", json={"name": "tester"}, headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.json()["name"] == "tester"
    assert r.json()["canonical_url"] == f"/{username}/tester"

    # rename again to "notes"
    r = await client.patch(
        "/api/pads/crisp-badger-68", json={"name": "notes"}, headers=_auth(token)
    )
    assert r.status_code == 200

    # old name still resolves (200), canonical points at the *current* name — the
    # redirect never chains.
    old = await client.get(f"/api/pads/u/{username}/tester", headers=_auth(token))
    assert old.status_code == 200
    assert old.json()["canonical_url"] == f"/{username}/notes"
    # the immutable slug always resolves too
    by_slug = await client.get("/api/pads/crisp-badger-68", headers=_auth(token))
    assert by_slug.status_code == 200
    assert by_slug.json()["canonical_url"] == f"/{username}/notes"


async def test_rename_collision_within_owner_rejected(client):
    token, _ = await _signup(client, "bob@example.com")
    await client.post("/api/pads", json={"slug": "pad-one-11"}, headers=_auth(token))
    await client.post("/api/pads", json={"slug": "pad-two-22"}, headers=_auth(token))
    assert (
        await client.patch(
            "/api/pads/pad-one-11", json={"name": "shared"}, headers=_auth(token)
        )
    ).status_code == 200
    clash = await client.patch(
        "/api/pads/pad-two-22", json={"name": "shared"}, headers=_auth(token)
    )
    assert clash.status_code == 409


async def test_rename_same_name_across_owners_allowed(client):
    t1, _ = await _signup(client, "one@example.com")
    t2, _ = await _signup(client, "two@example.com")
    await client.post("/api/pads", json={"slug": "p-one-11"}, headers=_auth(t1))
    await client.post("/api/pads", json={"slug": "p-two-22"}, headers=_auth(t2))
    assert (
        await client.patch("/api/pads/p-one-11", json={"name": "shared"}, headers=_auth(t1))
    ).status_code == 200
    # different owner namespace → same name is fine
    assert (
        await client.patch("/api/pads/p-two-22", json={"name": "shared"}, headers=_auth(t2))
    ).status_code == 200


async def test_rename_rejects_reserved_and_malformed(client):
    token, _ = await _signup(client, "carol@example.com")
    await client.post("/api/pads", json={"slug": "rename-bad"}, headers=_auth(token))
    assert (
        await client.patch("/api/pads/rename-bad", json={"name": "new"}, headers=_auth(token))
    ).status_code == 422  # reserved
    assert (
        await client.patch(
            "/api/pads/rename-bad", json={"name": "Bad Name"}, headers=_auth(token)
        )
    ).status_code == 422  # spaces/caps


# --- anonymous rename (world-editable) ----------------------------------------

async def test_anonymous_rename_and_resolution(client):
    await client.post("/api/pads", json={"slug": "anon-pad-01"})
    # no auth — anonymous pads are world-editable
    r = await client.patch("/api/pads/anon-pad-01", json={"name": "scratch"})
    assert r.status_code == 200
    assert r.json()["canonical_url"] == "/scratch"
    # new anon name resolves at the bare route
    assert (await client.get("/api/pads/scratch")).status_code == 200
    # original slug still resolves
    assert (await client.get("/api/pads/anon-pad-01")).status_code == 200


async def test_anonymous_rename_collision_with_existing_slug(client):
    await client.post("/api/pads", json={"slug": "taken-name-01"})
    await client.post("/api/pads", json={"slug": "other-pad-02"})
    # renaming to a name already used as another pad's slug (shared anon pool)
    clash = await client.patch("/api/pads/other-pad-02", json={"name": "taken-name-01"})
    assert clash.status_code == 409


# --- claim token flow ---------------------------------------------------------

async def test_claim_token_single_active_per_pad(client):
    await client.post("/api/pads", json={"slug": "tok-pad-01"})
    first = await _gen_token(client, "tok-pad-01")
    second = await _gen_token(client, "tok-pad-01")
    assert first != second
    token, _ = await _signup(client, "dan@example.com")
    # the superseded token no longer works
    assert (await _claim(client, "tok-pad-01", first, _auth(token))).status_code == 401
    # the current token works
    assert (await _claim(client, "tok-pad-01", second, _auth(token))).status_code == 200


async def test_claim_token_required(client):
    await client.post("/api/pads", json={"slug": "needs-tok"})
    token, _ = await _signup(client, "erin@example.com")
    bad = await _claim(client, "needs-tok", "not-a-real-token", _auth(token))
    assert bad.status_code == 401


async def test_claim_pin_persists_and_gates(client):
    # anonymous pad, PIN-protected (set by any viewer — world-editable)
    await client.post("/api/pads", json={"slug": "locked-claim"})
    set_pin = await client.patch(
        "/api/pads/locked-claim",
        json={"pin_protected": True, "pin": "1234", "pin_format": "numeric"},
    )
    assert set_pin.status_code == 200

    token, username = await _signup(client, "frank@example.com")
    ct = await _gen_token(client, "locked-claim")

    # token but no PIN → generic 401
    assert (await _claim(client, "locked-claim", ct, _auth(token))).status_code == 401
    # token + wrong PIN → generic 401
    assert (
        await _claim(client, "locked-claim", ct, _auth(token), pin="9999")
    ).status_code == 401
    # token + correct PIN → claimed, and the PIN persists (option b)
    ok = await _claim(client, "locked-claim", ct, _auth(token), pin="1234")
    assert ok.status_code == 200
    assert ok.json()["owner_id"] is not None
    assert ok.json()["pin_protected"] is True


async def test_claim_frees_anonymous_name_via_redirect(client):
    # an anon pad renamed, then claimed: old anon URL redirects to the claimed URL
    await client.post("/api/pads", json={"slug": "rename-claim-01"})
    await client.patch("/api/pads/rename-claim-01", json={"name": "myscratch"})
    token, username = await _signup(client, "gina@example.com")
    ct = await _gen_token(client, "rename-claim-01")
    claimed = await _claim(client, "rename-claim-01", ct, _auth(token))
    assert claimed.status_code == 200
    assert claimed.json()["canonical_url"] == f"/{username}/myscratch"
    # the old anonymous /myscratch now resolves and points at the claimed URL
    old = await client.get("/api/pads/myscratch")
    assert old.status_code == 200
    assert old.json()["canonical_url"] == f"/{username}/myscratch"


# --- kill the trail -----------------------------------------------------------

async def test_kill_redirect_frees_name(client):
    token, username = await _signup(client, "hugo@example.com")
    await client.post("/api/pads", json={"slug": "trail-pad-01"}, headers=_auth(token))
    await client.patch("/api/pads/trail-pad-01", json={"name": "first"}, headers=_auth(token))
    await client.patch("/api/pads/trail-pad-01", json={"name": "second"}, headers=_auth(token))

    listing = await client.get("/api/pads/trail-pad-01/redirects", headers=_auth(token))
    assert listing.status_code == 200
    rows = listing.json()
    assert any(r["old_slug"] == "first" for r in rows)
    rid = next(r["id"] for r in rows if r["old_slug"] == "first")

    # before kill, the old name resolves
    assert (
        await client.get(f"/api/pads/u/{username}/first", headers=_auth(token))
    ).status_code == 200

    killed = await client.delete(
        f"/api/pads/trail-pad-01/redirects/{rid}", headers=_auth(token)
    )
    assert killed.status_code == 204

    # after kill, the old name 404s and is free to reuse on another pad
    assert (
        await client.get(f"/api/pads/u/{username}/first", headers=_auth(token))
    ).status_code == 404
    await client.post("/api/pads", json={"slug": "trail-pad-02"}, headers=_auth(token))
    assert (
        await client.patch(
            "/api/pads/trail-pad-02", json={"name": "first"}, headers=_auth(token)
        )
    ).status_code == 200


async def test_redirects_listing_owner_only(client):
    owner, _ = await _signup(client, "owner2@example.com")
    stranger, _ = await _signup(client, "stranger2@example.com")
    await client.post("/api/pads", json={"slug": "priv-trail-01"}, headers=_auth(owner))
    assert (
        await client.get("/api/pads/priv-trail-01/redirects", headers=_auth(stranger))
    ).status_code == 403
