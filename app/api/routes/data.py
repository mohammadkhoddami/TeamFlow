"""Import + export routes.

Imports accept multipart CSV/JSON uploads (10 MB cap) and run through the
regular task service. Exports stream JSON for the whole workspace and CSV for
a single project's tasks.
"""

import uuid

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess
from app.core.exceptions import ValidationFailedError
from app.repositories import ProjectRepository
from app.schemas import ImportFormatLiteral, ImportSummary
from app.services import importers

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/organizations/{slug}", tags=["import-export"])
project_export_router = APIRouter(prefix="/projects/{project_id}/export", tags=["import-export"])


@router.post("/imports", response_model=ImportSummary)
async def import_tasks(
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    project_id: str = Form(...),
    format: ImportFormatLiteral = Form(default="csv"),
    dry_run: bool = Form(default=False),
) -> ImportSummary:
    org, _m = membership
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise ValidationFailedError("project_id must be a UUID") from None
    project = await ProjectRepository(db).get_in_org(project_uuid, org.id)
    if project is None:
        raise ValidationFailedError("Project not found in this organization")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError("Import file is limited to 10 MB")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationFailedError("Import files must be UTF-8 encoded") from None
    rows = importers.parse_upload(format, content)
    return await importers.import_tasks(
        db, current_user, org, project, rows, format, dry_run=dry_run
    )


@router.get("/export", response_class=JSONResponse)
async def export_workspace(
    membership: OrgMembership,
    db: DB,
    attachments: bool = Query(default=False, description="Include attachment download URLs"),
) -> JSONResponse:
    org, _m = membership
    payload = await importers.export_workspace(
        db, org, include_attachment_urls=attachments
    )
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f"attachment; filename=teamflow-{org.slug}-export.json"
        },
    )


@project_export_router.get("", response_class=PlainTextResponse)
async def export_project_csv(project_access: ProjectAccess, db: DB) -> PlainTextResponse:
    project, org, _m = project_access
    csv_text = await importers.export_project_csv(db, org.id, project)
    safe_name = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in project.name
    )
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_name}.csv"},
    )
