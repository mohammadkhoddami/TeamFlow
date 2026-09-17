"""Label service: org-scoped tags for tasks."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    Label,
    Membership,
    MembershipRole,
    Organization,
    User,
)
from app.repositories import LabelRepository
from app.schemas import LabelCreate, LabelUpdate
from app.services import audit


def _require_write(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage labels")


async def create_label(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: LabelCreate,
    ip: str | None = None,
) -> Label:
    _require_write(membership)
    repo = LabelRepository(db)
    if await repo.get_by_name(org.id, data.name):
        raise ConflictError("A label with this name already exists in this organization")
    label = await repo.add(Label(organization_id=org.id, name=data.name, color=data.color))
    await audit.log(
        db, "label.created", actor_id=actor.id,
        organization_id=org.id, target_type="label", target_id=label.id, ip=ip,
        meta={"name": label.name},
    )
    await db.commit()
    await db.refresh(label)
    return label


async def list_labels(
    db: AsyncSession, organization_id: uuid.UUID, *, offset: int = 0, limit: int = 100
) -> list[Label]:
    return await LabelRepository(db).list_for_org(
        organization_id, offset=offset, limit=limit
    )


async def get_label_for_org(
    db: AsyncSession, label_id: uuid.UUID, organization_id: uuid.UUID
) -> Label:
    label = await LabelRepository(db).get_in_org(label_id, organization_id)
    if not label:
        raise NotFoundError("Label not found")
    return label


async def update_label(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    label: Label,
    data: LabelUpdate,
    ip: str | None = None,
) -> Label:
    _require_write(membership)
    if data.name is not None and data.name != label.name:
        if await LabelRepository(db).get_by_name(org.id, data.name):
            raise ConflictError("A label with this name already exists in this organization")
        label.name = data.name
    if data.color is not None:
        label.color = data.color
    label = await LabelRepository(db).update(label)
    await audit.log(
        db, "label.updated", actor_id=actor.id,
        organization_id=org.id, target_type="label", target_id=label.id, ip=ip,
    )
    await db.commit()
    return label


async def delete_label(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    label: Label,
    ip: str | None = None,
) -> None:
    _require_write(membership)
    await audit.log(
        db, "label.deleted", actor_id=actor.id,
        organization_id=org.id, target_type="label", target_id=label.id, ip=ip,
    )
    await LabelRepository(db).delete(label)
    await db.commit()
