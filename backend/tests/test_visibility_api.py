"""Phase 5 visibility enforcement over REST. Mirrors test_pads_api patterns."""

import uuid

from sqlalchemy import select

from app.models.pad import CollaboratorRole, Pad, PadCollaborator, Visibility


async def _signup(client, email):
    resp = await client.post(
        "/api/auth/signup", json={"email": email, "password": "password123"}
    )
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _set_pad(factory, slug, *, owner_id=None, visibility=Visibility.public_edit):
    async with factory() as db:
        pad = (await db.execute(select(Pad).where(Pad.slug == slug))).scalar_one()
        pad.owner_id = owner_id
        pad.visibility = visibility
        pad.is_anonymous = owner_id is None
        await db.commit()


async def _add_collaborator(factory, slug, user_id, role):
    async with factory() as db:
        pad = (await db.execute(select(Pad).where(Pad.slug == slug))).scalar_one()
        db.add(
            PadCollaborator(pad_id=pad.id, user_id=user_id, role=role)
        )
        await db.commit()


# --- private pad: read access -------------------------------------------------
async def test_private_pad_blocks_stranger(client, session_factory):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    await client.post("/api/pads", json={"slug": "secret-notes"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "secret-notes", owner_id=owner_id, visibility=Visibility.private)

    # anonymous stranger
    assert (await client.get("/api/pads/secret-notes")).status_code == 403
    # authenticated but unrelated stranger
    stranger_token, _ = await _signup(client, "stranger@example.com")
    resp = await client.get("/api/pads/secret-notes", headers=_auth(stranger_token))
    assert resp.status_code == 403


async def test_private_pad_allows_owner(client, session_factory):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    await client.post("/api/pads", json={"slug": "owner-secret"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "owner-secret", owner_id=owner_id, visibility=Visibility.private)

    resp = await client.get("/api/pads/owner-secret", headers=_auth(owner_token))
    assert resp.status_code == 200
    assert resp.json()["can_edit"] is True


# --- private pad: write access by role ---------------------------------------
async def test_private_editor_can_write_viewer_cannot(client, session_factory):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    editor_token, editor_id = await _signup(client, "editor@example.com")
    viewer_token, viewer_id = await _signup(client, "viewer@example.com")
    await client.post("/api/pads", json={"slug": "team-pad"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "team-pad", owner_id=owner_id, visibility=Visibility.private)
    await _add_collaborator(session_factory, "team-pad", editor_id, CollaboratorRole.editor)
    await _add_collaborator(session_factory, "team-pad", viewer_id, CollaboratorRole.viewer)

    # viewer can read but not write
    assert (await client.get("/api/pads/team-pad", headers=_auth(viewer_token))).status_code == 200
    vw = await client.put(
        "/api/pads/team-pad", json={"content": "nope"}, headers=_auth(viewer_token)
    )
    assert vw.status_code == 403

    # editor can write
    ew = await client.put(
        "/api/pads/team-pad", json={"content": "edited"}, headers=_auth(editor_token)
    )
    assert ew.status_code == 200
    assert ew.json()["content"] == "edited"

    # the GET can_edit flag reflects the role
    viewer_get = await client.get("/api/pads/team-pad", headers=_auth(viewer_token))
    assert viewer_get.json()["can_edit"] is False
    editor_get = await client.get("/api/pads/team-pad", headers=_auth(editor_token))
    assert editor_get.json()["can_edit"] is True


# --- public_view: read open, write restricted --------------------------------
async def test_public_view_blocks_stranger_write_allows_read(client, session_factory):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    await client.post("/api/pads", json={"slug": "announcement"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "announcement", owner_id=owner_id, visibility=Visibility.public_view)

    # anyone can read
    assert (await client.get("/api/pads/announcement")).status_code == 200
    # anonymous write is rejected
    anon_write = await client.put("/api/pads/announcement", json={"content": "x"})
    assert anon_write.status_code == 403
    # owner can write
    owner_write = await client.put(
        "/api/pads/announcement", json={"content": "ok"}, headers=_auth(owner_token)
    )
    assert owner_write.status_code == 200


async def test_public_edit_pad_is_open(client):
    # Default visibility: anyone reads and writes (no regression).
    await client.post("/api/pads", json={"slug": "open-pad"})
    assert (await client.get("/api/pads/open-pad")).status_code == 200
    w = await client.put("/api/pads/open-pad", json={"content": "anyone"})
    assert w.status_code == 200
