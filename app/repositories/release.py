"""Release repository."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Release, Task, TaskStatus


class ReleaseRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, release_id: uuid.UUID, organization_id: uuid.UUID) -> Release | None:
        statement = select(Release).where(
            Release.id == release_id,
            Release.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> list[Release]:
        statement = (
            select(Release)
            .where(Release.project_id == project_id)
            .order_by(Release.release_date.asc().nulls_last(), Release.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def task_counts(
        self, project_id: uuid.UUID, release_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """(total, done) per release for the roadmap progress bars."""
        if not release_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    Task.release_id,
                    func.count(Task.id),
                    func.count(Task.id).filter(Task.status_category == TaskStatus.DONE),
                )
                .where(Task.project_id == project_id, Task.release_id.in_(release_ids))
                .group_by(Task.release_id)
            )
        ).all()
        return {row[0]: (int(row[1]), int(row[2])) for row in rows}

    async def add(self, release: Release) -> Release:
        self.db.add(release)
        await self.db.flush()
        return release

    async def update(self, release: Release) -> Release:
        self.db.add(release)
        await self.db.flush()
        return release

    async def delete(self, release: Release) -> None:
        await self.db.delete(release)
        await self.db.flush()
