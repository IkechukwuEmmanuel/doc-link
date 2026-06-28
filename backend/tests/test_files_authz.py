"""Access control on the file endpoints (AUDIT B5 — IDOR fix).

Proves the four file routes enforce the *same* authorization as pad content:
read for list/download, write for upload/delete, plus the PIN gate — mirroring
``services/access.py`` and ``services/pin.py``. The fake storage/scan fixture is
shared with ``test_files_api`` (re-imported here)."""

import uuid

from sqlalchemy import select

from app.models.pad import CollaboratorRole, Pad, PadCollaborator, Visibility

# The `fake_storage_and_scan` fixture lives in conftest.py (shared, no MinIO/ClamAV).


async def _signup(client, email, username=None):
    if username is None:
        username = email.split("@")[0]
        if len(username) < 3:
            username = username + "user"
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "username": username},
    )
    body = resp.json()
    return body["access_token"], uuid.UUID(body["user"]["id"])


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _set_pad(factory, slug, *, owner_id, visibility):
    async with factory() as db:
        pad = (await db.execute(select(Pad).where(Pad.slug == slug))).scalar_one()
        pad.owner_id = owner_id
        pad.visibility = visibility
        pad.is_anonymous = owner_id is None
        await db.commit()


async def _add_collaborator(factory, slug, user_id, role):
    async with factory() as db:
        pad = (await db.execute(select(Pad).where(Pad.slug == slug))).scalar_one()
        db.add(PadCollaborator(pad_id=pad.id, user_id=user_id, role=role))
        await db.commit()


async def _upload(client, slug, *, headers=None, name="a.txt", data=b"abc"):
    return await client.post(
        f"/api/pads/{slug}/files",
        files={"file": (name, data, "text/plain")},
        headers=headers or {},
    )


# --------------------------------------------------------------------------- #
# private pad: a stranger can do NONE of the four operations
# --------------------------------------------------------------------------- #
async def test_private_pad_files_blocked_for_anonymous_stranger(
    client, session_factory, fake_storage_and_scan
):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    await client.post("/api/pads", json={"slug": "priv-files"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "priv-files", owner_id=owner_id, visibility=Visibility.private)

    # Owner seeds a file (legitimate write path still works).
    up = await _upload(client, "priv-files", headers=_auth(owner_token))
    assert up.status_code == 201, up.text
    fid = up.json()["id"]

    # Anonymous stranger: no auth header, no cookie.
    client.cookies.clear()
    assert (await _upload(client, "priv-files")).status_code == 403
    assert (await client.get("/api/pads/priv-files/files")).status_code == 403
    # Direct file-ID download URL must also be gated, not just the listing.
    assert (await client.get(f"/api/pads/priv-files/files/{fid}")).status_code == 403
    assert (await client.delete(f"/api/pads/priv-files/files/{fid}")).status_code == 403


async def test_private_pad_files_blocked_for_authenticated_stranger(
    client, session_factory, fake_storage_and_scan
):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    await client.post("/api/pads", json={"slug": "priv-files2"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "priv-files2", owner_id=owner_id, visibility=Visibility.private)
    fid = (await _upload(client, "priv-files2", headers=_auth(owner_token))).json()["id"]

    stranger_token, _ = await _signup(client, "stranger@example.com")
    client.cookies.clear()
    h = _auth(stranger_token)
    assert (await client.get("/api/pads/priv-files2/files", headers=h)).status_code == 403
    assert (await client.get(f"/api/pads/priv-files2/files/{fid}", headers=h)).status_code == 403


# --------------------------------------------------------------------------- #
# owner + editor collaborator keep full access; viewer is read-only (no regression)
# --------------------------------------------------------------------------- #
async def test_owner_and_editor_full_access_viewer_readonly(
    client, session_factory, fake_storage_and_scan
):
    owner_token, owner_id = await _signup(client, "owner@example.com")
    editor_token, editor_id = await _signup(client, "editor@example.com")
    viewer_token, viewer_id = await _signup(client, "viewer@example.com")
    await client.post("/api/pads", json={"slug": "team-files"}, headers=_auth(owner_token))
    await _set_pad(session_factory, "team-files", owner_id=owner_id, visibility=Visibility.private)
    await _add_collaborator(session_factory, "team-files", editor_id, CollaboratorRole.editor)
    await _add_collaborator(session_factory, "team-files", viewer_id, CollaboratorRole.viewer)

    # Editor can upload, list, download, delete.
    up = await _upload(client, "team-files", headers=_auth(editor_token), name="e.txt")
    assert up.status_code == 201, up.text
    fid = up.json()["id"]
    assert (await client.get("/api/pads/team-files/files", headers=_auth(editor_token))).status_code == 200
    dl = await client.get(f"/api/pads/team-files/files/{fid}", headers=_auth(editor_token))
    assert dl.status_code == 200 and dl.content == b"abc"

    # Viewer can read but not upload or delete.
    assert (await client.get("/api/pads/team-files/files", headers=_auth(viewer_token))).status_code == 200
    assert (await client.get(f"/api/pads/team-files/files/{fid}", headers=_auth(viewer_token))).status_code == 200
    assert (await _upload(client, "team-files", headers=_auth(viewer_token))).status_code == 403
    assert (await client.delete(f"/api/pads/team-files/files/{fid}", headers=_auth(viewer_token))).status_code == 403

    # Owner can delete.
    assert (await client.delete(f"/api/pads/team-files/files/{fid}", headers=_auth(owner_token))).status_code == 204


# --------------------------------------------------------------------------- #
# PIN-protected pad: files locked until a valid unlock token is presented
# --------------------------------------------------------------------------- #
async def _make_pin_pad(client, owner_token, slug, pin="1234"):
    await client.post(
        "/api/pads", json={"slug": slug, "content": "secret"}, headers=_auth(owner_token)
    )
    resp = await client.patch(
        f"/api/pads/{slug}",
        json={"pin_protected": True, "pin": pin, "pin_format": "numeric"},
        headers=_auth(owner_token),
    )
    assert resp.status_code == 200, resp.text


async def test_pin_pad_files_require_unlock_token(client, fake_storage_and_scan):
    owner_token, _ = await _signup(client, "owner@example.com")
    await _make_pin_pad(client, owner_token, "pin-files")
    # Owner bypasses the PIN and seeds a file.
    fid = (await _upload(client, "pin-files", headers=_auth(owner_token))).json()["id"]

    # Fresh visitor (no unlock cookie): every route is gated — including the
    # direct file-ID download URL, not just the listing.
    client.cookies.clear()
    assert (await client.get("/api/pads/pin-files/files")).status_code == 403
    assert (await client.get(f"/api/pads/pin-files/files/{fid}")).status_code == 403
    assert (await _upload(client, "pin-files")).status_code == 403
    assert (await client.delete(f"/api/pads/pin-files/files/{fid}")).status_code == 403

    # Unlock with the correct PIN → the path-scoped cookie now unlocks the files.
    unlock = await client.post("/api/pads/pin-files/unlock", json={"pin": "1234"})
    assert unlock.status_code == 200 and unlock.json()["locked"] is False
    listed = await client.get("/api/pads/pin-files/files")
    assert listed.status_code == 200 and len(listed.json()) == 1
    dl = await client.get(f"/api/pads/pin-files/files/{fid}")
    assert dl.status_code == 200 and dl.content == b"abc"
