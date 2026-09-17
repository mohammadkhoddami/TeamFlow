"""Sync DB access for Celery workers.

Workers are synchronous by design: running an async loop inside Celery adds
complexity with zero benefit for these short I/O tasks, and psycopg (sync) is
already a dependency for Alembic. One short-lived session per task execution
via `session_scope()`.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

sync_engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    """Transaction-per-task: commit on success, rollback on failure."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
