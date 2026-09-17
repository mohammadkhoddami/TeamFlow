"""Attachment schemas: requests carry only metadata; bytes go to S3 directly."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel


class AttachmentCreate(SQLModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(ge=1, le=10485760)  # enforced again against settings


class AttachmentRead(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    filename: str
    content_type: str
    size: int
    status: str
    created_at: datetime


class UploadGrant(SQLModel):
    """Response for the upload-intent call: metadata row + presigned PUT URL."""

    attachment: AttachmentRead
    upload_url: str
    expires_in: int


class DownloadGrant(SQLModel):
    download_url: str
    expires_in: int
