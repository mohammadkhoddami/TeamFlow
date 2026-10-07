"""Task link/dependency service.

`blocks` links are directional and cycle-checked; `relates_to`, `duplicates`
and `clones` are symmetric (stored once, rendered both ways). `is_blocked` is
derived from blockers that are not done, so the board and filters reflect it.
"""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models import (
    Organization,
    Task,
    TaskLink,
    TaskLinkType,
    TaskStatus,
    User,
)
from app.repositories import TaskLinkRepository, TaskRepository
from app.schemas import TaskLinkCreate, TaskLinkSummary

SYMMETRIC_TYPES = {TaskLinkType.RELATES_TO, TaskLinkType.DUPLICATES, TaskLinkType.CLONES}


def _direction(link: TaskLink, task_id: uuid.UUID) -> str:
    return "out" if link.from_task_id == task_id else "in"


def _inverse_type(link_type: str) -> str:
    if link_type == TaskLinkType.BLOCKS:
        return "is_blocked_by"
    if link_type == TaskLinkType.RELATES_TO:
        return "relates_to"
    if link_type == TaskLinkType.DUPLICATES:
        return "duplicates"
    return "clones"


async def _assert_no_block_cycle(
    db: AsyncSession, from_task_id: uuid.UUID, to_task_id: uuid.UUID
) -> None:
    """Adding `from blocks to` must not close a cycle (to must not reach from)."""
    seen = {to_task_id}
    frontier = [to_task_id]
    repo = TaskLinkRepository(db)
    while frontier:
        current = frontier.pop()
        links = await repo.list_for_task(current)
        for link in links:
            if link.link_type != TaskLinkType.BLOCKS or link.from_task_id != current:
                continue
            nxt = link.to_task_id
            if nxt == from_task_id:
                raise ValidationFailedError(
                    "This link would create a circular dependency"
                )
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)


async def create_link(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: TaskLinkCreate,
) -> TaskLink:
    if data.link_type not in TaskLinkType.ALL:
        raise ValidationFailedError(f"Unknown link type '{data.link_type}'")
    if data.to_task_id == task.id:
        raise ValidationFailedError("A task cannot link to itself")
    target = await TaskRepository(db).get_in_org(data.to_task_id, org.id)
    if target is None:
        raise NotFoundError("Linked task not found")
    repo = TaskLinkRepository(db)
    if await repo.find(task.id, target.id, data.link_type):
        raise ConflictError("This link already exists")
    if data.link_type in SYMMETRIC_TYPES:
        if await repo.find(target.id, task.id, data.link_type):
            raise ConflictError("This link already exists")
    if data.link_type == TaskLinkType.BLOCKS:
        await _assert_no_block_cycle(db, task.id, target.id)
    link = await repo.add(
        TaskLink(
            organization_id=org.id,
            from_task_id=task.id,
            to_task_id=target.id,
            link_type=data.link_type,
            created_by_id=actor.id,
        )
    )
    await db.commit()
    return link


async def delete_link(
    db: AsyncSession, actor: User, org: Organization, link: TaskLink
) -> None:
    await TaskLinkRepository(db).delete(link)
    await db.commit()


async def get_link_for_org(
    db: AsyncSession, link_id: uuid.UUID, organization_id: uuid.UUID
) -> TaskLink:
    link = await TaskLinkRepository(db).get(link_id)
    if not link or link.organization_id != organization_id:
        raise NotFoundError("Link not found")
    return link


async def list_links(db: AsyncSession, task: Task) -> TaskLinkSummary:
    links = await TaskLinkRepository(db).list_for_task(task.id)
    other_ids = {
        link.to_task_id if link.from_task_id == task.id else link.from_task_id
        for link in links
    }
    tasks: dict[uuid.UUID, Task] = {}
    for other_id in other_ids:
        other = await TaskRepository(db).get_in_org(other_id, task.organization_id)
        if other is not None:
            tasks[other_id] = other

    def ref(other_id: uuid.UUID) -> dict:
        other = tasks.get(other_id)
        return {
            "id": other_id,
            "key": other.key if other else None,
            "title": other.title if other else "(deleted)",
            "status": other.status if other else "todo",
            "status_category": other.status_category if other else "todo",
            "project_id": other.project_id if other else task.project_id,
        }

    summary = TaskLinkSummary(
        blocks=[], blocked_by=[], relates_to=[], duplicates=[], clones=[]
    )
    for link in links:
        out = link.from_task_id == task.id
        other_id = link.to_task_id if out else link.from_task_id
        entry = {
            "id": link.id,
            "link_type": link.link_type,
            "direction": _direction(link, task.id),
            "task": ref(other_id),
            "created_at": link.created_at,
        }
        if link.link_type == TaskLinkType.BLOCKS:
            summary.blocks.append(entry) if out else summary.blocked_by.append(entry)
        elif link.link_type == TaskLinkType.RELATES_TO:
            summary.relates_to.append(entry)
        elif link.link_type == TaskLinkType.DUPLICATES:
            summary.duplicates.append(entry)
        else:
            summary.clones.append(entry)
    return summary


async def link_stats(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[bool, int, int]]:
    """`task_id -> (is_blocked, blocks_count, blocked_by_count)` (batched)."""
    if not task_ids:
        return {}
    links = await TaskLinkRepository(db).list_for_tasks(task_ids)
    blocks_out: dict[uuid.UUID, int] = {}
    blocker_ids: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in links:
        if link.link_type != TaskLinkType.BLOCKS:
            continue
        if link.from_task_id in task_ids:
            blocks_out[link.from_task_id] = blocks_out.get(link.from_task_id, 0) + 1
        if link.to_task_id in task_ids:
            blocker_ids.setdefault(link.to_task_id, []).append(link.from_task_id)
    all_blockers = {blocker for blockers in blocker_ids.values() for blocker in blockers}
    blocker_status: dict[uuid.UUID, str] = {}
    for blocker_id in all_blockers:
        blocker = await TaskRepository(db).get(blocker_id)
        if blocker is not None:
            blocker_status[blocker_id] = blocker.status_category
    result: dict[uuid.UUID, tuple[bool, int, int]] = {}
    for task_id in task_ids:
        blockers = blocker_ids.get(task_id, [])
        open_blockers = [
            blocker
            for blocker in blockers
            if blocker_status.get(blocker, TaskStatus.TODO) != TaskStatus.DONE
        ]
        result[task_id] = (
            bool(open_blockers),
            blocks_out.get(task_id, 0),
            len(blockers),
        )
    return result
