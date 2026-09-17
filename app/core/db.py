"""Async SQLAlchemy/SQLModel engine and session management.

One engine per process. Each request gets a session via the `get_db`
dependency; the session (and its connection) is closed when the request ends.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

# Tests run against multiple event loops (TestClient portals, pytest-asyncio
# session loop); a pooled asyncpg connection is loop-bound, so tests use
# NullPool to avoid "attached to a different loop" errors.
_engine_kwargs: dict = {"echo": settings.debug, "pool_pre_ping": True}
if settings.environment == "testing":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow

engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs)

# async_sessionmaker produces AsyncSession objects bound to the engine.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, always closed."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Import models so SQLModel registers every table, then create all.

    Used by tests and the dev bootstrap only; production uses Alembic
    migrations so schema changes are versioned and reviewable.
    """
    from app import models  # noqa: F401  (import registers tables)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
