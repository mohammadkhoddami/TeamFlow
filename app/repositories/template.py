"""Project/task template repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import ProjectTemplate, TaskTemplate


class ProjectTemplateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(
        self, template_id: uuid.UUID, organization_id: uuid.UUID
    ) -> ProjectTemplate | None:
        statement = select(ProjectTemplate).where(
            ProjectTemplate.id == template_id,
            ProjectTemplate.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_name(self, organization_id: uuid.UUID, name: str) -> ProjectTemplate | None:
        statement = select(ProjectTemplate).where(
            ProjectTemplate.organization_id == organization_id,
            ProjectTemplate.name == name,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[ProjectTemplate]:
        statement = (
            select(ProjectTemplate)
            .where(ProjectTemplate.organization_id == organization_id)
            .order_by(ProjectTemplate.name.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, template: ProjectTemplate) -> ProjectTemplate:
        self.db.add(template)
        await self.db.flush()
        return template

    async def delete(self, template: ProjectTemplate) -> None:
        await self.db.delete(template)
        await self.db.flush()


class TaskTemplateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(
        self, template_id: uuid.UUID, organization_id: uuid.UUID
    ) -> TaskTemplate | None:
        statement = select(TaskTemplate).where(
            TaskTemplate.id == template_id,
            TaskTemplate.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_name(self, organization_id: uuid.UUID, name: str) -> TaskTemplate | None:
        statement = select(TaskTemplate).where(
            TaskTemplate.organization_id == organization_id,
            TaskTemplate.name == name,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self, organization_id: uuid.UUID, project_id: uuid.UUID | None = None
    ) -> list[TaskTemplate]:
        statement = select(TaskTemplate).where(
            TaskTemplate.organization_id == organization_id
        )
        if project_id is not None:
            from sqlmodel import or_

            statement = statement.where(
                or_(
                    TaskTemplate.project_id == project_id,
                    TaskTemplate.project_id.is_(None),
                )
            )
        statement = statement.order_by(TaskTemplate.name.asc())
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, template: TaskTemplate) -> TaskTemplate:
        self.db.add(template)
        await self.db.flush()
        return template

    async def delete(self, template: TaskTemplate) -> None:
        await self.db.delete(template)
        await self.db.flush()
