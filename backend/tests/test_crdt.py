import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.pad import Pad
from app.services import crdt

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # The CRDT service opens its own sessions via SessionLocal.
    monkeypatch.setattr(crdt, "SessionLocal", factory)
    yield factory
    await engine.dispose()


async def _make_pad(factory, **kwargs) -> str:
    async with factory() as db:
        pad = Pad(slug=kwargs.pop("slug", "test-pad-01"), **kwargs)
        db.add(pad)
        await db.commit()
        return pad.slug


async def test_seed_from_plain_content(session_factory):
    slug = await _make_pad(session_factory, content="hello from phase 1")
    server = crdt.PadWebsocketServer()
    doc = await server._seed_doc(slug)
    assert crdt._doc_text(doc) == "hello from phase 1"


async def test_seed_prefers_snapshot_over_content(session_factory):
    from pycrdt import Doc, Text

    snap_doc = Doc()
    snap_doc.get("content", type=Text).insert(0, "snapshot text")
    snapshot = snap_doc.get_update()

    slug = await _make_pad(
        session_factory, content="stale plain text", crdt_snapshot=snapshot
    )
    server = crdt.PadWebsocketServer()
    doc = await server._seed_doc(slug)
    assert crdt._doc_text(doc) == "snapshot text"


async def test_seed_missing_pad_is_empty(session_factory):
    server = crdt.PadWebsocketServer()
    doc = await server._seed_doc("does-not-exist-99")
    assert crdt._doc_text(doc) == ""


async def test_flush_writes_snapshot_and_content(session_factory):
    from pycrdt import Doc, Text
    from pycrdt.websocket import YRoom

    slug = await _make_pad(session_factory, content="")
    server = crdt.PadWebsocketServer()
    doc = Doc()
    doc.get("content", type=Text).insert(0, "edited live")
    server.rooms[slug] = YRoom(ydoc=doc)

    await server._flush(slug)

    async with session_factory() as db:
        from sqlalchemy import select

        pad = (await db.execute(select(Pad).where(Pad.slug == slug))).scalar_one()
        assert pad.content == "edited live"
        assert pad.crdt_snapshot is not None
        assert pad.crdt_snapshot_updated_at is not None
        # Snapshot round-trips back to the same text.
        restored = Doc()
        restored.apply_update(pad.crdt_snapshot)
        assert str(restored.get("content", type=Text)) == "edited live"
