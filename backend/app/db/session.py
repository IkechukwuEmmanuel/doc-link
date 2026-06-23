import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _connect_args(url: str) -> dict:
    """asyncpg connect args.

    Supabase's transaction-mode pooler (pgbouncer) multiplexes many clients onto
    a few server connections, so server-side prepared statements created by one
    client can collide with another's. Disable both asyncpg's and SQLAlchemy's
    prepared-statement caches and give each statement a unique name. Harmless on
    a direct/session connection too; only applies to the asyncpg driver.
    """
    if not url.startswith("postgresql+asyncpg"):
        return {}
    return {
        "statement_cache_size": 0,  # asyncpg: no client-side PS cache
        "prepared_statement_cache_size": 0,  # SQLAlchemy asyncpg dialect cache off
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    }


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_connect_args(settings.database_url),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
