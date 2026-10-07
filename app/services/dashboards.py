"""Saved dashboard service (M4): CRUD plus widget data assembly.

Widget data is assembled with one SELECT per widget (aggregates run in the
database); the overdue widget joins its assignee in the same query, so no
widget causes per-row N+1 loads. `stats` reuses the M1 aggregation service.
"""

import uuid

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models import Dashboard, Organization, Task, TaskStatus, User
from app.repositories import ProjectRepository
from app.schemas import ActivityRead
from app.schemas.dashboard import DashboardCreate, DashboardUpdate
from app.services import activities as activity_service
from app.services import dashboard as stats_service

WIDGET_TYPES = ("stats", "status", "members", "overdue", "activity")


def normalize_widgets(widgets: list) -> list[dict]:
    """Coerces schema/dict widgets into the stored shape and assigns IDs."""
    normalized: list[dict] = []
    for widget in widgets:
        if hasattr(widget, "model_dump"):
            widget = widget.model_dump()
        widget_type = widget.get("type")
        if widget_type not in WIDGET_TYPES:
            raise ValidationFailedError(f"Unknown widget type: {widget_type}")
        normalized.append(
            {
                "id": str(widget.get("id") or uuid.uuid4().hex),
                "type": widget_type,
                "title": widget.get("title") or widget_type.replace("_", " ").title(),
                "config": widget.get("config") or {},
            }
        )
    return normalized


async def _name_taken(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    statement = select(Dashboard.id).where(
        Dashboard.organization_id == org_id, Dashboard.name == name
    )
    if exclude_id is not None:
        statement = statement.where(Dashboard.id != exclude_id)
    return (await db.execute(statement)).first() is not None


async def _assert_project(
    db: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID | None
) -> None:
    if project_id is None:
        return
    project = await ProjectRepository(db).get_in_org(project_id, org_id)
    if project is None:
        raise NotFoundError("Project not found")


async def _clear_defaults(db: AsyncSession, org_id: uuid.UUID) -> None:
    await db.execute(
        update(Dashboard)
        .where(Dashboard.organization_id == org_id, Dashboard.is_default.is_(True))
        .values(is_default=False)
    )


async def create_dashboard(
    db: AsyncSession, actor: User, org: Organization, data: DashboardCreate
) -> Dashboard:
    await _assert_project(db, org.id, data.project_id)
    if await _name_taken(db, org.id, data.name):
        raise ConflictError("A dashboard with this name already exists")
    if data.is_default:
        await _clear_defaults(db, org.id)
    dashboard = Dashboard(
        organization_id=org.id,
        project_id=data.project_id,
        name=data.name,
        widgets=normalize_widgets(data.widgets),
        is_default=data.is_default,
        created_by_id=actor.id,
    )
    db.add(dashboard)
    await db.flush()
    await db.commit()
    return dashboard


async def list_dashboards(db: AsyncSession, org_id: uuid.UUID) -> list[Dashboard]:
    statement = (
        select(Dashboard)
        .where(Dashboard.organization_id == org_id)
        .order_by(Dashboard.is_default.desc(), Dashboard.created_at.desc())
    )
    return list((await db.execute(statement)).scalars().all())


async def get_dashboard_for_org(
    db: AsyncSession, dashboard_id: uuid.UUID, organization_id: uuid.UUID
) -> Dashboard:
    statement = select(Dashboard).where(
        Dashboard.id == dashboard_id,
        Dashboard.organization_id == organization_id,
    )
    dashboard = (await db.execute(statement)).scalar_one_or_none()
    if dashboard is None:
        # 404 hides cross-org dashboard IDs (IDOR containment).
        raise NotFoundError("Dashboard not found")
    return dashboard


async def update_dashboard(
    db: AsyncSession,
    actor: User,
    org: Organization,
    dashboard: Dashboard,
    data: DashboardUpdate,
) -> Dashboard:
    changed = data.model_fields_set
    if "project_id" in changed:
        await _assert_project(db, org.id, data.project_id)
        dashboard.project_id = data.project_id
    if "name" in changed and data.name is not None and data.name != dashboard.name:
        if await _name_taken(db, org.id, data.name, exclude_id=dashboard.id):
            raise ConflictError("A dashboard with this name already exists")
        dashboard.name = data.name
    if "widgets" in changed and data.widgets is not None:
        dashboard.widgets = normalize_widgets(data.widgets)
    if "is_default" in changed and data.is_default is not None:
        if data.is_default:
            await _clear_defaults(db, org.id)
        dashboard.is_default = data.is_default
    db.add(dashboard)
    await db.flush()
    await db.commit()
    return dashboard


async def delete_dashboard(
    db: AsyncSession, actor: User, org: Organization, dashboard: Dashboard
) -> None:
    await db.delete(dashboard)
    await db.commit()


def _task_conditions(dashboard: Dashboard) -> list:
    conditions = [Task.organization_id == dashboard.organization_id]
    if dashboard.project_id is not None:
        conditions.append(Task.project_id == dashboard.project_id)
    return conditions


async def _widget_stats(db: AsyncSession, dashboard: Dashboard) -> dict:
    return await stats_service.compute_stats(db, dashboard.organization_id)


async def _widget_status(db: AsyncSession, dashboard: Dashboard) -> dict:
    rows = (
        await db.execute(
            select(Task.status_category, func.count(Task.id))
            .where(*_task_conditions(dashboard))
            .group_by(Task.status_category)
        )
    ).all()
    counts = {row[0]: int(row[1]) for row in rows}
    return {status: counts.get(status, 0) for status in TaskStatus.ALL}


async def _widget_members(db: AsyncSession, dashboard: Dashboard) -> list[dict]:
    statement = (
        select(User.id, User.full_name, func.count(Task.id))
        .join(Task, Task.assignee_id == User.id)
        .where(
            *_task_conditions(dashboard),
            Task.status_category != TaskStatus.DONE,
        )
        .group_by(User.id, User.full_name)
        .order_by(func.count(Task.id).desc())
        .limit(10)
    )
    rows = (await db.execute(statement)).all()
    return [
        {"user_id": row[0], "full_name": row[1], "open_tasks": int(row[2])}
        for row in rows
    ]


async def _widget_overdue(db: AsyncSession, dashboard: Dashboard) -> list[dict]:
    statement = (
        select(Task, User)
        .join(User, User.id == Task.assignee_id, isouter=True)
        .where(
            *_task_conditions(dashboard),
            Task.due_date.is_not(None),
            Task.due_date < func.now(),
            Task.status_category != TaskStatus.DONE,
        )
        .order_by(Task.due_date.asc())
        .limit(20)
    )
    rows = (await db.execute(statement)).all()
    return [
        {
            "id": task.id,
            "key": task.key,
            "title": task.title,
            "due_date": task.due_date,
            "status": task.status,
            "assignee": (assignee.full_name or assignee.email) if assignee else None,
        }
        for task, assignee in rows
    ]


async def _widget_activity(db: AsyncSession, dashboard: Dashboard) -> list[dict]:
    if dashboard.project_id is not None:
        items, _total = await activity_service.list_for_project(
            db, dashboard.project_id, limit=10
        )
    else:
        items, _total = await activity_service.list_for_org(
            db, dashboard.organization_id, limit=10
        )
    return [
        ActivityRead.model_validate(item).model_dump(mode="json") for item in items
    ]


async def _widget_data(db: AsyncSession, dashboard: Dashboard, widget: dict):
    widget_type = widget.get("type")
    if widget_type == "stats":
        return await _widget_stats(db, dashboard)
    if widget_type == "status":
        return await _widget_status(db, dashboard)
    if widget_type == "members":
        return await _widget_members(db, dashboard)
    if widget_type == "overdue":
        return await _widget_overdue(db, dashboard)
    if widget_type == "activity":
        return await _widget_activity(db, dashboard)
    raise ValidationFailedError(f"Unknown widget type: {widget_type}")


async def dashboard_data(db: AsyncSession, dashboard: Dashboard) -> dict:
    widgets = []
    for widget in dashboard.widgets:
        widgets.append(
            {
                "id": widget.get("id", ""),
                "type": widget.get("type", ""),
                "title": widget.get("title", ""),
                "data": await _widget_data(db, dashboard, widget),
            }
        )
    return {"widgets": widgets}
