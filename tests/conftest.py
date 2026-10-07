"""Shared test fixtures.

Environment: Postgres database `teamflow_test` + Redis DB 15 (flushed between
tests). Schema is created once per session via SQLModel.metadata.create_all
(testing only — production uses Alembic); every test runs against empty tables.

The ASGI client is httpx + ASGITransport (lifespan does NOT run for HTTP
tests; WebSocket tests use TestClient, which does).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["ENVIRONMENT"] = "testing"
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://teamflow:teamflow@localhost:5432/teamflow_test",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg://teamflow:teamflow@localhost:5432/teamflow_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # per-test opt-in
# Worker tests deliver to real 127.0.0.1 receivers; the SSRF guard has its own
# unit tests (tests/unit/test_outbound_urls.py) with the flag disabled.
os.environ.setdefault("OUTBOUND_ALLOW_PRIVATE_HOSTS", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal, engine
from app.main import app


def _test_database_name() -> str:
    """Guards every destructive schema operation: tests reset the schema, so
    they must never point at anything but a throwaway `*_test` database."""
    name = make_url(os.environ["DATABASE_URL"]).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(f"Refusing to run tests against non-test database {name!r}")
    return name


def _create_test_database() -> None:
    import psycopg

    url = make_url(os.environ["DATABASE_URL"])
    name = _test_database_name()
    admin_url = url.set(drivername="postgresql", database="postgres")
    try:
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{name}"')
    except Exception:
        pass  # concurrent creation during xdist or already exists


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    _create_test_database()
    _test_database_name()
    app  # noqa: B018  (imports routers eagerly)

    # Own throwaway engine with NullPool: the app engine must never see
    # connections from a temporary loop. The schema is rebuilt from the models
    # each session so stale test databases cannot drift from Alembic/models.
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def _create() -> None:
        import app.models  # noqa: F401  (register all tables)

        eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            async with eng.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
                await conn.run_sync(SQLModel.metadata.create_all)
        finally:
            await eng.dispose()

    asyncio.run(_create())
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_state():
    """Truncate all tables + flush Redis DB 15 after each test."""
    yield
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t}"' for t in SQLModel.metadata.tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    from app.core.redis import get_redis_client

    try:
        await get_redis_client().flushdb()
    except Exception:
        pass


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


from tests.utils import (  # noqa: E402
    auth_headers,
    make_org,
    make_project,
    make_task,
    make_user,
    plant_otp,
)

__all__ = [
    "auth_headers",
    "make_org",
    "make_project",
    "make_task",
    "make_user",
    "plant_otp",
]
