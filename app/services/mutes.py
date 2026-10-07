"""Per-project notification mutes (M3 #25)."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import NotificationMute, Organization, Project, User
from app.repositories import MuteRepository


async def is_muted(db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    return await MuteRepository(db).get(user_id, project_id) is not None


async def list_mutes(db: AsyncSession, user: User) -> list[NotificationMute]:
    return await MuteRepository(db).list_for_user(user.id)


async def add_mute(
    db: AsyncSession, user: User, org: Organization, project: Project
) -> NotificationMute:
    repo = MuteRepository(db)
    existing = await repo.get(user.id, project.id)
    if existing is not None:
        return existing
    mute = await repo.add(
        NotificationMute(
            user_id=user.id,
            organization_id=org.id,
            project_id=project.id,
        )
    )
    await db.commit()
    return mute


async def remove_mute(db: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    repo = MuteRepository(db)
    mute = await repo.get(user.id, project_id)
    if mute is None:
        raise NotFoundError("Project is not muted")
    await repo.delete(mute)
    await db.commit()
