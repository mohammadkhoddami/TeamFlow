"""Sprint service: plan, start, complete (with carry-over), delete.

State machine: planned -> active -> completed. One active sprint per project
is enforced at start time; completing a sprint moves unfinished work to a
chosen planned sprint or back to the backlog.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    Project,
    Sprint,
    SprintState,
    Task,
    TaskStatus,
    User,
)
from app.repositories import SprintRepository
from app.schemas import SprintComplete, SprintCreate, SprintUpdate
from app.services import audit, events


def _require_manage(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage sprints")


async def get_sprint_for_project(
    db: AsyncSession, sprint_id: uuid.UUID, organization_id: uuid.UUID
) -> Sprint:
    sprint = await SprintRepository(db).get_in_org(sprint_id, organization_id)
    if not sprint:
        raise NotFoundError("Sprint not found")
    return sprint


async def create_sprint(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    data: SprintCreate,
    ip: str | None = None,
) -> Sprint:
    _require_manage(membership)
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise ValidationFailedError("Sprint end date must be after the start date")
    sprint = await SprintRepository(db).add(
        Sprint(
            organization_id=org.id,
            project_id=project.id,
            name=data.name,
            goal=data.goal,
            start_date=data.start_date,
            end_date=data.end_date,
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="sprint", target_id=sprint.id, ip=ip,
        meta={"name": sprint.name, "project_id": str(project.id)},
    )
    await db.commit()
    await db.refresh(sprint)
    await events.publish_project_event(
        project.id, "sprint.created", {"id": str(sprint.id), "name": sprint.name}
    )
    return sprint


async def list_sprints(
    db: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[list[Sprint], dict[uuid.UUID, dict[str, float]]]:
    sprints = await SprintRepository(db).list_for_project(org_id, project_id)
    aggregates = await SprintRepository(db).task_aggregates(org_id, project_id)
    return sprints, aggregates


async def update_sprint(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    sprint: Sprint,
    data: SprintUpdate,
    ip: str | None = None,
) -> Sprint:
    _require_manage(membership)
    if sprint.state == SprintState.COMPLETED:
        raise ValidationFailedError("Completed sprints cannot be edited")
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        sprint.name = data.name
    if "goal" in changed:
        sprint.goal = data.goal
    if "start_date" in changed:
        sprint.start_date = data.start_date
    if "end_date" in changed:
        sprint.end_date = data.end_date
    if sprint.start_date and sprint.end_date and sprint.end_date < sprint.start_date:
        raise ValidationFailedError("Sprint end date must be after the start date")
    sprint = await SprintRepository(db).update(sprint)
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="sprint", target_id=sprint.id, ip=ip,
        meta={"fields": sorted(changed)},
    )
    await db.commit()
    await events.publish_project_event(
        sprint.project_id, "sprint.updated", {"id": str(sprint.id)}
    )
    return sprint


async def start_sprint(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    sprint: Sprint,
    ip: str | None = None,
) -> Sprint:
    _require_manage(membership)
    if sprint.state != SprintState.PLANNED:
        raise ValidationFailedError(f"Cannot start a {sprint.state} sprint")
    active = await SprintRepository(db).get_active(sprint.project_id)
    if active is not None:
        raise ValidationFailedError(
            f"Sprint '{active.name}' is already active in this project"
        )
    sprint.state = SprintState.ACTIVE
    if sprint.start_date is None:
        sprint.start_date = datetime.now(UTC)
    sprint = await SprintRepository(db).update(sprint)
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="sprint", target_id=sprint.id, ip=ip,
        meta={"started": True},
    )
    await db.commit()
    await events.publish_project_event(
        sprint.project_id, "sprint.started", {"id": str(sprint.id), "name": sprint.name}
    )
    return sprint


async def complete_sprint(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    sprint: Sprint,
    data: SprintComplete,
    ip: str | None = None,
) -> tuple[Sprint, int]:
    """Completes an active sprint; unfinished tasks carry over.

    Returns `(sprint, moved_count)`. Target must be a planned sprint in the
    same project, or None to return unfinished tasks to the backlog.
    """
    _require_manage(membership)
    if sprint.state != SprintState.ACTIVE:
        raise ValidationFailedError(f"Cannot complete a {sprint.state} sprint")
    target_id: uuid.UUID | None = None
    if data.carry_over_sprint_id is not None:
        target = await SprintRepository(db).get_in_org(
            data.carry_over_sprint_id, org.id
        )
        if (
            target is None
            or target.project_id != sprint.project_id
            or target.state != SprintState.PLANNED
        ):
            raise ValidationFailedError(
                "Carry-over target must be a planned sprint in the same project"
            )
        target_id = target.id

    unfinished = (Task.status != TaskStatus.DONE) & (Task.sprint_id == sprint.id)
    result = await db.execute(
        update(Task)
        .where(
            Task.organization_id == org.id,
            Task.project_id == sprint.project_id,
            unfinished,
        )
        .values(sprint_id=target_id)
    )
    moved = int(result.rowcount or 0)

    sprint.state = SprintState.COMPLETED
    sprint.completed_at = datetime.now(UTC)
    if sprint.end_date is None:
        sprint.end_date = sprint.completed_at
    sprint = await SprintRepository(db).update(sprint)
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="sprint", target_id=sprint.id, ip=ip,
        meta={"completed": True, "carried_over": moved,
              "carry_over_sprint_id": str(target_id) if target_id else None},
    )
    await db.commit()
    await events.publish_project_event(
        sprint.project_id, "sprint.completed", {"id": str(sprint.id)}
    )
    return sprint, moved


async def delete_sprint(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    sprint: Sprint,
    ip: str | None = None,
) -> None:
    _require_manage(membership)
    if sprint.state == SprintState.ACTIVE:
        raise ValidationFailedError("Complete the active sprint before deleting it")
    await db.execute(
        update(Task)
        .where(Task.organization_id == org.id, Task.sprint_id == sprint.id)
        .values(sprint_id=None)
    )
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="sprint", target_id=sprint.id, ip=ip,
        meta={"deleted": True},
    )
    project_id = sprint.project_id
    await SprintRepository(db).delete(sprint)
    await db.commit()
    await events.publish_project_event(
        project_id, "sprint.deleted", {"id": str(sprint.id)}
    )
