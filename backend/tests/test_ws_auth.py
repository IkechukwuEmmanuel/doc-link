"""Phase 5 WebSocket authorization. Tests the gate the WS endpoint applies
before accepting a room join (app.api.ws.authorize_ws), against a real DB."""

import uuid

import pytest_asyncio

from app.api import ws as ws_module
from app.models.pad import CollaboratorRole, Pad, PadCollaborator, Visibility
from app.models.user import User
from app.services import auth as auth_service


@pytest_asyncio.fixture
async def wsdb(session_factory, monkeypatch):
    # authorize_ws opens its own session via SessionLocal; point it at the test DB.
    monkeypatch.setattr(ws_module, "SessionLocal", session_factory)
    return session_factory


async def _make_user(factory, email) -> uuid.UUID:
    async with factory() as db:
        username = email.split("@")[0]
        # Ensure minimum length of 3 for username
        if len(username) < 3:
            username = username + "user"
        user = User(email=email, password_hash="x", username=username)
        db.add(user)
        await db.commit()
        return user.id


async def _make_pad(factory, slug, *, owner_id=None, visibility=Visibility.public_edit):
    async with factory() as db:
        pad = Pad(slug=slug, owner_id=owner_id, visibility=visibility, is_anonymous=owner_id is None)
        db.add(pad)
        await db.commit()
        return pad.id


async def _add_collab(factory, pad_id, user_id, role):
    async with factory() as db:
        db.add(PadCollaborator(pad_id=pad_id, user_id=user_id, role=role))
        await db.commit()


def _token(user_id):
    return auth_service.create_access_token(user_id)


async def test_ws_private_rejects_anonymous(wsdb):
    owner_id = await _make_user(wsdb, "o@example.com")
    await _make_pad(wsdb, "priv-pad-11", owner_id=owner_id, visibility=Visibility.private)
    auth = await ws_module.authorize_ws("priv-pad-11", token=None)
    assert auth.allowed is False
    assert auth.close_code == ws_module.CLOSE_NO_ACCESS


async def test_ws_private_rejects_stranger_token(wsdb):
    owner_id = await _make_user(wsdb, "o@example.com")
    stranger_id = await _make_user(wsdb, "s@example.com")
    await _make_pad(wsdb, "priv-pad-12", owner_id=owner_id, visibility=Visibility.private)
    auth = await ws_module.authorize_ws("priv-pad-12", token=_token(stranger_id))
    assert auth.allowed is False


async def test_ws_private_allows_owner(wsdb):
    owner_id = await _make_user(wsdb, "o@example.com")
    await _make_pad(wsdb, "priv-pad-13", owner_id=owner_id, visibility=Visibility.private)
    auth = await ws_module.authorize_ws("priv-pad-13", token=_token(owner_id))
    assert auth.allowed is True


async def test_ws_private_allows_editor_not_viewer(wsdb):
    owner_id = await _make_user(wsdb, "o@example.com")
    editor_id = await _make_user(wsdb, "e@example.com")
    viewer_id = await _make_user(wsdb, "v@example.com")
    pad_id = await _make_pad(wsdb, "priv-pad-14", owner_id=owner_id, visibility=Visibility.private)
    await _add_collab(wsdb, pad_id, editor_id, CollaboratorRole.editor)
    await _add_collab(wsdb, pad_id, viewer_id, CollaboratorRole.viewer)

    assert (await ws_module.authorize_ws("priv-pad-14", _token(editor_id))).allowed is True
    # viewer has read access but the live socket is a write channel → rejected
    assert (await ws_module.authorize_ws("priv-pad-14", _token(viewer_id))).allowed is False


async def test_ws_public_edit_allows_anonymous(wsdb):
    await _make_pad(wsdb, "open-pad-15", visibility=Visibility.public_edit)
    assert (await ws_module.authorize_ws("open-pad-15", token=None)).allowed is True


async def test_ws_public_view_blocks_anonymous_writer(wsdb):
    owner_id = await _make_user(wsdb, "o@example.com")
    await _make_pad(wsdb, "view-pad-16", owner_id=owner_id, visibility=Visibility.public_view)
    assert (await ws_module.authorize_ws("view-pad-16", token=None)).allowed is False


async def test_ws_nonexistent_pad_is_allowed(wsdb):
    # No pad to protect yet (matches REST "creatable" behaviour).
    assert (await ws_module.authorize_ws("ghost-pad-17", token=None)).allowed is True
