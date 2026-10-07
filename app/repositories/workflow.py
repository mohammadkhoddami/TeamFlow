"""Workflow status + board repositories."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Board, WorkflowStatus


class WorkflowStatusRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_project(
        self, project_id: uuid.UUID
    ) -> list[WorkflowStatus]:
        statement = (
            select(WorkflowStatus)
            .where(WorkflowStatus.project_id == project_id)
            .order_by(WorkflowStatus.position.asc(), WorkflowStatus.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def get_by_key(
        self, project_id: uuid.UUID, key: str
    ) -> WorkflowStatus | None:
        statement = select(WorkflowStatus).where(
            WorkflowStatus.project_id == project_id, WorkflowStatus.key == key
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, status: WorkflowStatus) -> WorkflowStatus:
        self.db.add(status)
        await self.db.flush()
        return status

    async def update(self, status: WorkflowStatus) -> WorkflowStatus:
        self.db.add(status)
        await self.db.flush()
        return status

    async def delete_for_project(self, project_id: uuid.UUID) -> None:
        for status in await self.list_for_project(project_id):
            await self.db.delete(status)
        await self.db.flush()


class BoardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, board_id: uuid.UUID, organization_id: uuid.UUID) -> Board | None:
        statement = select(Board).where(
            Board.id == board_id, Board.organization_id == organization_id
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_project(
        self, organization_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[Board]:
        statement = (
            select(Board)
            .where(
                Board.organization_id == organization_id,
                Board.project_id == project_id,
            )
            .order_by(Board.is_default.desc(), Board.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, board: Board) -> Board:
        self.db.add(board)
        await self.db.flush()
        return board

    async def update(self, board: Board) -> Board:
        self.db.add(board)
        await self.db.flush()
        return board

    async def delete(self, board: Board) -> None:
        await self.db.delete(board)
        await self.db.flush()
