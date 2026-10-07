"""Agile report routes (project + sprint)."""

import uuid

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import DB, ProjectAccess, SprintAccess
from app.schemas import (
    BurndownReport,
    CfdReport,
    CycleTimeReport,
    SprintReport,
    VelocityReport,
)
from app.services import reports as report_service

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])
sprint_report_router = APIRouter(prefix="/sprints/{sprint_id}", tags=["reports"])


@router.get("/burndown", response_model=BurndownReport)
async def burndown(
    project_access: ProjectAccess,
    db: DB,
    sprint_id: uuid.UUID = Query(description="Sprint to burn down"),
) -> BurndownReport:
    _project, org, _m = project_access
    sprint = await report_service.get_sprint_for_org(db, sprint_id, org.id)
    return BurndownReport.model_validate(await report_service.burndown(db, sprint))


@router.get("/velocity", response_model=VelocityReport)
async def velocity(
    project_access: ProjectAccess,
    db: DB,
    limit: int = Query(default=6, ge=1, le=20),
) -> VelocityReport:
    project, org, _m = project_access
    return VelocityReport.model_validate(
        await report_service.velocity(db, org.id, project.id, limit)
    )


@router.get("/cumulative-flow", response_model=CfdReport)
async def cumulative_flow(
    project_access: ProjectAccess,
    db: DB,
    days: int = Query(default=30, ge=1, le=90),
) -> CfdReport:
    project, _org, _m = project_access
    return CfdReport.model_validate(
        await report_service.cumulative_flow(db, project.id, days)
    )


@router.get("/cycle-time", response_model=CycleTimeReport)
async def cycle_time(
    project_access: ProjectAccess,
    db: DB,
    days: int = Query(default=30, ge=1, le=90),
    format: str | None = Query(default=None, pattern="^(csv)?$"),
):
    project, _org, _m = project_access
    report = await report_service.cycle_time(db, project.id, days)
    if format == "csv":
        csv_text = report_service.rows_to_csv(
            report["items"],
            ["key", "title", "lead_time_days", "cycle_time_days", "completed_at"],
        )
        return PlainTextResponse(
            csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cycle-time.csv"},
        )
    return CycleTimeReport.model_validate(report)


@router.get("/sprint/{sprint_id}", response_model=SprintReport)
async def project_sprint_report(
    sprint_id: uuid.UUID, project_access: ProjectAccess, db: DB
) -> SprintReport:
    _project, org, _m = project_access
    sprint = await report_service.get_sprint_for_org(db, sprint_id, org.id)
    return SprintReport.model_validate(
        await report_service.sprint_report(db, org.id, sprint)
    )


@sprint_report_router.get("/report", response_model=SprintReport)
async def sprint_report(sprint_access: SprintAccess, db: DB) -> SprintReport:
    sprint, org, _m = sprint_access
    return SprintReport.model_validate(
        await report_service.sprint_report(db, org.id, sprint)
    )
