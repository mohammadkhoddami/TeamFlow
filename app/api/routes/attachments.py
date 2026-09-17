"""Attachment routes: upload intent/confirm, list, download, delete."""

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import DB, AttachmentAccess, CurrentUser, Storage, TaskAccess
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Attachment, MembershipRole
from app.schemas import AttachmentCreate, AttachmentRead, DownloadGrant, UploadGrant
from app.services import attachments as attachment_service

router = APIRouter(prefix="/tasks/{task_id}/attachments", tags=["attachments"])
attachment_router = APIRouter(prefix="/attachments", tags=["attachments"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UploadGrant)
async def create_upload_intent(
    data: AttachmentCreate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
    storage: Storage,
) -> UploadGrant:
    task, org, _m = task_access
    attachment, upload_url, expires_in = await attachment_service.create_upload_intent(
        db, current_user, org, task, storage,
        data.filename, data.content_type, data.size, ip=_ip(request),
    )
    return UploadGrant(
        attachment=AttachmentRead.model_validate(attachment),
        upload_url=upload_url,
        expires_in=expires_in,
    )


@router.post("/{attachment_id}/confirm", response_model=AttachmentRead)
async def confirm_upload(
    attachment_id: uuid.UUID,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
    storage: Storage,
) -> AttachmentRead:
    task, org, _m = task_access
    attachment = await _get_in_task(db, attachment_id, task.id)
    attachment = await attachment_service.confirm_upload(
        db, current_user, org, attachment, storage, ip=_ip(request)
    )
    return AttachmentRead.model_validate(attachment)


@router.get("", response_model=list[AttachmentRead])
async def list_attachments(task_access: TaskAccess, db: DB) -> list[AttachmentRead]:
    task, _org, _m = task_access
    attachments = await attachment_service.list_attachments(db, task.id)
    return [AttachmentRead.model_validate(a) for a in attachments]


@attachment_router.post("/{attachment_id}/download-url", response_model=DownloadGrant)
async def download_url(
    attachment_access: AttachmentAccess,
    storage: Storage,
) -> DownloadGrant:
    attachment, _org, _m = attachment_access
    url, expires_in = await attachment_service.download_grant(attachment, storage)
    return DownloadGrant(download_url=url, expires_in=expires_in)


@attachment_router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_access: AttachmentAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
    storage: Storage,
) -> None:
    attachment, org, m = attachment_access
    if attachment.uploader_id != current_user.id and m.role == MembershipRole.MEMBER:
        raise PermissionDeniedError(
            "Only the uploader (or managers+) can delete an attachment"
        )
    await attachment_service.delete_attachment(
        db, current_user, org, attachment, storage, ip=_ip(request)
    )


async def _get_in_task(db: DB, attachment_id: uuid.UUID, task_id: uuid.UUID) -> Attachment:
    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id, Attachment.task_id == task_id
            )
        )
    ).scalar_one_or_none()
    if not attachment:
        raise NotFoundError("Attachment not found")
    return attachment

