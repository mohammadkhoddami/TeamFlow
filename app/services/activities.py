"""Activity feed recording + queries (M3 #21).

Recording is deliberately cheap (single INSERT, no fan-out); reads are
offset-paginated per task/project/org. Automation actions pass actor_id=None
so system events are visually distinct from human ones.
"""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Activity
from app.repositories import ActivityRepository


async def record(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    verb: str,
    summary: str,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    data: dict | None = None,
) -> Activity:
    return await ActivityRepository(db).add(
        Activity(
            organization_id=organization_id,
            project_id=project_id,
            task_id=task_id,
            actor_id=actor_id,
            verb=verb,
            summary=summary[:255],
            data=data,
        )
    )


async def list_for_task(
    db: AsyncSession, task_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> tuple[list[Activity], int]:
    return await ActivityRepository(db).list_for_task(task_id, offset=offset, limit=limit)


async def list_for_project(
    db: AsyncSession, project_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> tuple[list[Activity], int]:
    return await ActivityRepository(db).list_for_project(
        project_id, offset=offset, limit=limit
    )


async def list_for_org(
    db: AsyncSession, organization_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> tuple[list[Activity], int]:
    return await ActivityRepository(db).list_for_org(
        organization_id, offset=offset, limit=limit
    )
