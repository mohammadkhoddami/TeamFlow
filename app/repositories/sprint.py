"""Sprint repository: tenant-safe fetch, project listing, task aggregates."""

import uuid

from sqlalchemy import case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Project, Sprint, SprintState, Task, TaskStatus


class SprintRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, sprint_id: uuid.UUID) -> Sprint | None:
        return await self.db.get(Sprint, sprint_id)

    async def get_in_org(self, sprint_id: uuid.UUID, organization_id: uuid.UUID) -> Sprint | None:
        statement = select(Sprint).where(
            Sprint.id == sprint_id,
            Sprint.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_project(
        self, organization_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[Sprint]:
        statement = (
            select(Sprint)
            .where(
                Sprint.organization_id == organization_id,
                Sprint.project_id == project_id,
            )
            .order_by(Sprint.created_at.desc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_for_org(
        self, organization_id: uuid.UUID
    ) -> list[tuple[Sprint, str]]:
        """Every sprint in the org with its project name (TeamQL lookups)."""
        statement = (
            select(Sprint, Project.name)
            .join(Project, Project.id == Sprint.project_id)
            .where(Sprint.organization_id == organization_id)
        )
        return [(row[0], row[1]) for row in (await self.db.execute(statement)).all()]

    async def get_active(self, project_id: uuid.UUID) -> Sprint | None:
        statement = select(Sprint).where(
            Sprint.project_id == project_id,
            Sprint.state == SprintState.ACTIVE,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def task_aggregates(
        self, organization_id: uuid.UUID, project_id: uuid.UUID
    ) -> dict[uuid.UUID, dict[str, float]]:
        """`sprint_id -> {task_count, done_task_count, total_estimate, done_estimate}`."""
        done = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
        done_estimate = func.sum(
            case((Task.status == TaskStatus.DONE, Task.estimate), else_=0)
        )
        statement = (
            select(
                Task.sprint_id,
                func.count(Task.id),
                done,
                func.coalesce(func.sum(Task.estimate), 0),
                func.coalesce(done_estimate, 0),
            )
            .where(
                Task.organization_id == organization_id,
                Task.project_id == project_id,
                Task.sprint_id.is_not(None),
                Task.archived_at.is_(None),
            )
            .group_by(Task.sprint_id)
        )
        rows = (await self.db.execute(statement)).all()
        return {
            row[0]: {
                "task_count": int(row[1]),
                "done_task_count": int(row[2] or 0),
                "total_estimate": float(row[3] or 0),
                "done_estimate": float(row[4] or 0),
            }
            for row in rows
        }

    async def add(self, sprint: Sprint) -> Sprint:
        self.db.add(sprint)
        await self.db.flush()
        return sprint

    async def update(self, sprint: Sprint) -> Sprint:
        self.db.add(sprint)
        await self.db.flush()
        return sprint

    async def delete(self, sprint: Sprint) -> None:
        await self.db.delete(sprint)
        await self.db.flush()
