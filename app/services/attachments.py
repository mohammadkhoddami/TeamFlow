"""Attachment service: metadata in Postgres, bytes in S3 (MinIO locally).

Flow: client declares a file -> we validate metadata, create a `pending`
attachment row, and return a short-lived presigned PUT URL. The client uploads
directly to MinIO/S3 (the API never proxies file bytes) and then confirms;
confirmation does a HEAD against the stored object before flipping status.
Downloads return short-lived presigned GET URLs for the private bucket.

Security: storage keys are server-generated UUIDs under org/task prefixes
(no client path control), content types are allowlisted, sizes are capped,
and filenames are sanitized to their basename.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import ValidationFailedError
from app.models import (
    Attachment,
    AttachmentStatus,
    AuditAction,
    Organization,
    Task,
    User,
)
from app.repositories import AttachmentRepository
from app.services import audit
from app.services.integrations.storage import StorageClient

UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str) -> str:
    basename = name.replace("\\", "/").split("/")[-1]
    basename = basename.rsplit(".", 1)[0][:80] + (
        ("." + basename.rsplit(".", 1)[1][:16]) if "." in basename else ""
    )
    cleaned = UNSAFE_CHARS.sub("_", basename).strip("._")
    return cleaned or "file"


def build_storage_key(org_id: uuid.UUID, task_id: uuid.UUID, filename: str) -> str:
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[1][:12].lower()
    return f"orgs/{org_id}/tasks/{task_id}/{uuid.uuid4().hex}{ext}"


def validate_upload(filename: str, content_type: str, size: int) -> None:
    if size <= 0 or size > settings.upload_max_bytes:
        raise ValidationFailedError(
            f"File size must be between 1 byte and {settings.upload_max_bytes} bytes"
        )
    if content_type not in settings.upload_allowed_content_types:
        raise ValidationFailedError(f"Content type '{content_type}' is not allowed")
    if not sanitize_filename(filename):
        raise ValidationFailedError("Invalid filename")


async def create_upload_intent(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    storage: StorageClient,
    filename: str,
    content_type: str,
    size: int,
    ip: str | None = None,
) -> tuple[Attachment, str, int]:
    validate_upload(filename, content_type, size)
    safe_name = sanitize_filename(filename)
    key = build_storage_key(org.id, task.id, safe_name)
    attachment = await AttachmentRepository(db).add(
        Attachment(
            organization_id=org.id,
            task_id=task.id,
            uploader_id=actor.id,
            filename=safe_name,
            content_type=content_type,
            size=size,
            storage_key=key,
            status=AttachmentStatus.PENDING,
        )
    )
    await audit.log(
        db, AuditAction.ATTACHMENT_REQUESTED, actor_id=actor.id,
        organization_id=org.id, target_type="attachment", target_id=attachment.id,
        ip=ip, meta={"filename": safe_name, "size": size, "task_id": str(task.id)},
    )
    await db.commit()
    upload_url = storage.presign_put(key, content_type=content_type)
    return attachment, upload_url, settings.s3_presign_expiry_seconds


async def confirm_upload(
    db: AsyncSession,
    actor: User,
    org: Organization,
    attachment: Attachment,
    storage: StorageClient,
    ip: str | None = None,
) -> Attachment:
    if attachment.status == AttachmentStatus.AVAILABLE:
        return attachment
    # PENDING or FAILED (retry after the client actually uploaded) both allowed.
    try:
        stored = await storage.stat(attachment.storage_key)
    except Exception as exc:
        attachment.status = AttachmentStatus.FAILED
        await AttachmentRepository(db).update(attachment)
        await db.commit()
        raise ValidationFailedError("Object not found in storage; upload the file first") from exc
    if stored is None:
        attachment.status = AttachmentStatus.FAILED
        await AttachmentRepository(db).update(attachment)
        await db.commit()
        raise ValidationFailedError("Object not found in storage; upload the file first")

    attachment.status = AttachmentStatus.AVAILABLE
    attachment = await AttachmentRepository(db).update(attachment)
    await audit.log(
        db, AuditAction.ATTACHMENT_UPLOADED, actor_id=actor.id,
        organization_id=org.id, target_type="attachment", target_id=attachment.id,
        ip=ip, meta={"filename": attachment.filename, "size": attachment.size},
    )
    await db.commit()
    return attachment


async def download_grant(attachment: Attachment, storage: StorageClient) -> tuple[str, int]:
    if attachment.status != AttachmentStatus.AVAILABLE:
        raise ValidationFailedError("Attachment is not available for download")
    url = storage.presign_get(attachment.storage_key)
    return url, settings.s3_presign_expiry_seconds


async def delete_attachment(
    db: AsyncSession,
    actor: User,
    org: Organization,
    attachment: Attachment,
    storage: StorageClient,
    ip: str | None = None,
) -> None:
    storage.remove(attachment.storage_key)
    await audit.log(
        db, AuditAction.ATTACHMENT_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="attachment", target_id=attachment.id,
        ip=ip, meta={"filename": attachment.filename},
    )
    await AttachmentRepository(db).delete(attachment)
    await db.commit()


async def list_attachments(db: AsyncSession, task_id: uuid.UUID) -> list:
    return await AttachmentRepository(db).list_for_task(task_id)


def stale_pending_cutoff() -> "datetime":
    from datetime import timedelta

    return datetime.now(UTC) - timedelta(hours=24)
