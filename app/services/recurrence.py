"""RRULE-based recurring tasks.

A task carrying `recurrence_rule` spawns its next occurrence when completed
(and a daily beat sweep catches overdue series whose previous occurrence was
never completed). Occurrences keep a `recurrence_source_id` pointer at the
series root so generation is idempotent.
"""

import logging
import uuid
from datetime import UTC, datetime

from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ValidationFailedError
from app.models import Organization, Task, TaskAssignee, User
from app.repositories import TaskRepository

logger = logging.getLogger(__name__)


def validate_rule(rule: str) -> None:
    try:
        rrulestr(rule, dtstart=datetime.now(UTC))
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(f"Invalid recurrence rule: {exc}") from None


def next_occurrence(rule: str, anchor: datetime) -> datetime | None:
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    try:
        parsed = rrulestr(rule, dtstart=anchor)
    except (ValueError, TypeError):
        return None
    return parsed.after(anchor, inc=False)


async def _already_generated(
    db: AsyncSession, org_id: uuid.UUID, root_id: uuid.UUID, due: datetime
) -> bool:
    statement = select(Task.id).where(
        Task.organization_id == org_id,
        Task.recurrence_source_id == root_id,
        Task.due_date == due,
        Task.archived_at.is_(None),
    )
    return (await db.execute(statement)).scalars().first() is not None


async def spawn_next_occurrence(
    db: AsyncSession,
    actor: User | None,
    org: Organization,
    task: Task,
) -> Task | None:
    """Creates the next occurrence of a recurring task (idempotent)."""
    if not task.recurrence_rule:
        return None
    anchor = task.due_date or task.completed_at or datetime.now(UTC)
    now = datetime.now(UTC)
    effective_anchor = max(anchor, now) if anchor.tzinfo else now
    due = next_occurrence(task.recurrence_rule, effective_anchor)
    if due is None:
        return None
    root_id = task.recurrence_source_id or task.id
    if await _already_generated(db, org.id, root_id, due):
        return None

    from app.services import tasks as task_service

    project = None
    from app.repositories import ProjectRepository

    project = await ProjectRepository(db).get(task.project_id)
    if project is None:
        return None
    number, key = await task_service._next_issue_key(db, project)
    occurrence = Task(
        organization_id=org.id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        status=task.status if task.status_category != "done" else None,
        priority=task.priority,
        type=task.type,
        parent_id=task.parent_id,
        created_by_id=task.created_by_id or (actor.id if actor else None),
        assignee_id=task.assignee_id,
        number=number,
        key=key,
        estimate=task.estimate,
        remaining_estimate=task.remaining_estimate,
        actual_estimate=None,
        backlog_rank=task_service._next_backlog_rank(),
        sprint_id=None,
        due_date=due,
        recurrence_rule=task.recurrence_rule,
        recurrence_source_id=root_id,
    )
    if occurrence.status is None:
        # The template was done: the new occurrence starts at the workflow's
        # first status (category 'todo').
        workflow = await task_service.get_project_workflow(db, project)
        occurrence.status = task_service.initial_status_key(workflow)
        occurrence.status_category = task_service.category_for(
            workflow, occurrence.status
        )
    else:
        occurrence.status_category = task.status_category
    try:
        # `uq_tasks_recurrence_occurrence` is the idempotency backstop: if a
        # concurrent completion (or overlapping beat sweep) already created
        # this occurrence, the flush fails and this call is a no-op.
        occurrence = await TaskRepository(db).add(occurrence)
    except IntegrityError:
        await db.rollback()
        return None

    label_ids = [label.id for label in task.labels]
    if label_ids:
        await task_service._set_task_labels(db, occurrence.id, label_ids)
    assignees = (
        await db.execute(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
    ).scalars()
    for entry in assignees:
        db.add(
            TaskAssignee(
                organization_id=org.id,
                task_id=occurrence.id,
                user_id=entry.user_id,
                role=entry.role,
            )
        )
    watcher_ids = {w.id for w in task.watchers}
    if actor:
        watcher_ids.add(actor.id)
    await task_service._add_watchers(db, occurrence.id, watcher_ids)
    await db.commit()

    refreshed = await task_service.refetch_task(db, occurrence.id)
    payload = task_service.task_event_payload(refreshed)
    from app.services import events

    await events.publish_project_event(refreshed.project_id, "task.created", payload)
    return refreshed
