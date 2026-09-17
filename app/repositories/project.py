"""Project repository."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Project


class ProjectRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self.db.get(Project, project_id)

    async def get_in_org(self, project_id: uuid.UUID, organization_id: uuid.UUID) -> Project | None:
        """Tenant-safe single fetch: id must also match the caller's org."""
        statement = select(Project).where(
            Project.id == project_id,
            Project.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Project], int]:
        conds = [Project.organization_id == organization_id]
        if status:
            conds.append(Project.status == status)
        statement = (
            select(Project)
            .where(*conds)
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        count_stmt = select(func.count(Project.id)).where(*conds)
        total = (await self.db.execute(count_stmt)).scalar_one()
        return items, total

    async def count_for_org(
        self, organization_id: uuid.UUID, status: str | None = None
    ) -> int:
        conds = [Project.organization_id == organization_id]
        if status:
            conds.append(Project.status == status)
        statement = select(func.count(Project.id)).where(*conds)
        return (await self.db.execute(statement)).scalar_one()

    async def add(self, project: Project) -> Project:
        self.db.add(project)
        await self.db.flush()
        return project

    async def update(self, project: Project) -> Project:
        self.db.add(project)
        await self.db.flush()
        return project

    async def delete(self, project: Project) -> None:
        await self.db.delete(project)
        await self.db.flush()
