"""Worker tests: cleanup task purges expired data."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.db_sync import session_scope
from app.models import Attachment, IdempotencyKey
from app.workers.tasks import cleanup_expired_data


def test_cleanup_purges_expired_idempotency_keys():
    with session_scope() as db:
        old = IdempotencyKey(key="old-key-00000001", method="POST", path="/x", request_hash="h")
        db.add(old)
        db.flush()
        db.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.key == "old-key-00000001")
            .values(created_at=datetime.now(UTC) - timedelta(hours=48))
        )
        db.add(
            IdempotencyKey(key="fresh-key-0000001", method="POST", path="/x", request_hash="h")
        )

    removed = cleanup_expired_data.run()
    assert removed["idempotency_keys"] == 1

    with session_scope() as db:
        remaining = list(db.execute(select(IdempotencyKey.key)).scalars())
        assert remaining == ["fresh-key-0000001"]


def test_cleanup_removes_stale_pending_attachments():
    import uuid

    from app.models import Organization, Project, Task

    with session_scope() as db:
        org = Organization(name="Stale Org", slug=f"stale-org-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        project = Project(organization_id=org.id, name="P")
        db.add(project)
        db.flush()
        task = Task(organization_id=org.id, project_id=project.id, title="T")
        db.add(task)
        db.flush()
        stale = Attachment(
            organization_id=org.id,
            task_id=task.id,
            filename="old.txt",
            content_type="text/plain",
            size=10,
            storage_key="orgs/old/tasks/old/old.txt",
            status="pending",
        )
        db.add(stale)
        db.flush()
        db.execute(
            update(Attachment)
            .where(Attachment.id == stale.id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=30))
        )
        fresh = Attachment(
            organization_id=org.id,
            task_id=task.id,
            filename="new.txt",
            content_type="text/plain",
            size=10,
            storage_key="orgs/new/tasks/new/new.txt",
            status="pending",
        )
        db.add(fresh)
        db.flush()

    removed = cleanup_expired_data.run()
    assert removed["pending_attachments"] == 1

    with session_scope() as db:
        remaining = list(db.execute(select(Attachment.storage_key)).scalars())
        assert remaining == ["orgs/new/tasks/new/new.txt"]
