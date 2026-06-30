import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.file import ScanStatus
from app.services import file as file_service
from app.services import scan as scan_service
from app.services import storage

# In-memory SQLite for fast, isolated tests. Phase 1 uses no Postgres-specific
# types in a way SQLite can't emulate (UUID/bytea map fine for unit tests).
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    """Shared session factory — used by the get_db override and by tests that
    need to set up DB state directly (e.g. private pads, collaborators)."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fake_storage_and_scan(monkeypatch):
    """In-memory object store + controllable scan verdict, so file tests need no
    MinIO or ClamAV. Shared by test_files_api and test_files_authz."""
    store: dict[str, bytes] = {}

    async def put_object(key, data, content_type):
        store[key] = data

    async def get_object(key):
        return store[key]

    async def delete_object(key):
        store.pop(key, None)

    monkeypatch.setattr(storage, "put_object", put_object)
    monkeypatch.setattr(storage, "get_object", get_object)
    monkeypatch.setattr(storage, "delete_object", delete_object)

    verdict = {"status": ScanStatus.clean}

    async def fake_scan(data):
        return verdict["status"]

    monkeypatch.setattr(scan_service, "scan", fake_scan)
    monkeypatch.setattr(file_service, "scan_service", scan_service)
    return {"store": store, "verdict": verdict}
