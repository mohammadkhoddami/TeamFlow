"""Task service: CRUD, status transitions, assignment, labels, watchers,
estimation, sprints, issue keys, clone/move/archive.

Business rules:
  - status transitions follow a whitelist (with reopening); same->same is a
    no-op, unknown paths are 422
  - moving to DONE stamps completed_at; leaving DONE clears it
  - hierarchy: epic > story > task; a parent must be in the same project and
    at a strictly higher level, so cycles are structurally impossible
  - assignee must be an active member of the task's org
  - creator + assignee auto-watch; watchers get notified on comments/status
  - members may edit tasks; only managers+ (or the creator) may delete
  - issue keys use the project's atomic counter (UPDATE ... + 1 RETURNING), so
    concurrent creates can never collide
  - archive is a soft delete: archived tasks disappear from boards/backlog but
    remain queryable

Async-SQLAlchemy note: M2M collections are written through the link tables
(`TaskLabelLink`, `TaskWatcherLink`) and read back with an explicit
`select(Task)` re-fetch — implicit lazy loads (`task.labels.append(...)`)
raise MissingGreenlet inside an async session, so we never trigger them.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    AssigneeRole,
    AuditAction,
    ChecklistItem,
    CustomFieldValue,
    Membership,
    MembershipRole,
    Organization,
    Project,
    Sprint,
    SprintState,
    Task,
    TaskAssignee,
    TaskLabelLink,
    TaskStatus,
    TaskStatusHistory,
    TaskType,
    TaskWatcherLink,
    User,
    WorkflowStatus,
)
from app.repositories import (
    ChecklistRepository,
    LabelRepository,
    MembershipRepository,
    ProjectRepository,
    ReleaseRepository,
    SprintRepository,
    TaskAssigneeRepository,
    TaskRepository,
    TaskStatusHistoryRepository,
)
from app.models import Release
from app.schemas import TaskCreate, TaskUpdate
from app.services import (
    activities,
    audit,
    automations,
    cache,
    events,
    preferences,
    recurrence,
    workflows,
)
from app.services import custom_fields as custom_field_service


async def get_project_workflow(
    db: AsyncSession, project: Project
) -> list[WorkflowStatus]:
    return await workflows.get_workflow(db, project)


def initial_status_key(workflow: list[WorkflowStatus]) -> str:
    return workflows.initial_status_key(workflow)


def category_for(workflow: list[WorkflowStatus], status_key: str) -> str:
    return workflows.category_for(workflow, status_key)

logger = logging.getLogger(__name__)

# Allowed transitions; reopening a done task returns to in_progress.
STATUS_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.TODO, TaskStatus.IN_REVIEW},
    TaskStatus.IN_REVIEW: {TaskStatus.IN_PROGRESS, TaskStatus.DONE},
    TaskStatus.DONE: {TaskStatus.IN_PROGRESS},
}


def _can_delete(membership: Membership, task: Task, actor: User) -> bool:
    if membership.role != MembershipRole.MEMBER:
        return True
    return task.created_by_id == actor.id


def _type_level(task_type: str) -> int:
    return TaskType.LEVELS.get(task_type, TaskType.LEVELS[TaskType.TASK])


async def _assert_parent_valid(
    db: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    parent_id: uuid.UUID,
    child_type: str,
    child_id: uuid.UUID | None = None,
) -> None:
    """Validates the epic > story > task rule for a proposed parent link.

    A parent must live in the same project and at a strictly higher level
    than its child; the link must also not close a cycle.
    """
    repo = TaskRepository(db)
    parent = await repo.get_in_org(parent_id, org_id)
    if not parent:
        raise ValidationFailedError("Parent task not found in this organization")
    if parent.project_id != project_id:
        raise ValidationFailedError("Parent task must belong to the same project")
    if child_id is not None and parent.id == child_id:
        raise ValidationFailedError("A task cannot be its own parent")
    if _type_level(parent.type) >= _type_level(child_type):
        raise ValidationFailedError(
            f"'{parent.type}' is not a valid parent for '{child_type}': "
            "parents must be a higher level (epic > story > task)"
        )
    if child_id is None:
        return
    # Walk up from the proposed parent; meeting the child means a cycle.
    seen = {parent.id}
    current_id = parent.parent_id
    while current_id is not None and len(seen) <= len(TaskType.ALL) + 1:
        if current_id == child_id:
            raise ValidationFailedError("Cannot nest a task under its own descendant")
        if current_id in seen:
            raise ValidationFailedError("The parent chain contains a cycle")
        seen.add(current_id)
        current_id = await repo.get_parent_id(current_id)


async def _assert_type_change_valid(
    db: AsyncSession, org_id: uuid.UUID, task: Task, new_type: str
) -> None:
    """A type change must preserve the level invariant on both ends."""
    child_types = await TaskRepository(db).children_types(task.id)
    if any(_type_level(child_type) <= _type_level(new_type) for child_type in child_types):
        raise ValidationFailedError(
            f"Cannot change type to '{new_type}': this task already has "
            "children at the same or a higher level"
        )
    if task.parent_id is not None:
        await _assert_parent_valid(
            db, org_id, task.project_id, task.parent_id, new_type, task.id
        )


async def _assert_assignee_in_org(
    db: AsyncSession, org_id: uuid.UUID, assignee_id: uuid.UUID
) -> None:
    membership = await MembershipRepository(db).get_for_user(assignee_id, org_id)
    if not membership or not membership.is_active:
        raise ValidationFailedError(
            "Assignee must be an active member of this organization"
        )


async def _assert_sprint_in_project(
    db: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
) -> Sprint:
    sprint = await SprintRepository(db).get_in_org(sprint_id, org_id)
    if not sprint or sprint.project_id != project_id:
        raise ValidationFailedError("Sprint not found in this project")
    if sprint.state == SprintState.COMPLETED:
        raise ValidationFailedError("Cannot add tasks to a completed sprint")
    return sprint


async def _next_issue_key(db: AsyncSession, project: Project) -> tuple[int, str]:
    """Atomically reserve the next issue number for a project.

    `UPDATE ... SET issue_counter = issue_counter + 1 RETURNING` is a single
    statement, so parallel task creations serialize on the row and can never
    produce duplicate keys.
    """
    result = await db.execute(
        update(Project)
        .where(Project.id == project.id)
        .values(issue_counter=Project.issue_counter + 1)
        .returning(Project.issue_counter)
    )
    number = int(result.scalar_one())
    prefix = project.key or "PRJ"
    return number, f"{prefix}-{number}"


def _next_backlog_rank() -> float:
    return datetime.now(UTC).timestamp()


async def _resolve_label_ids(
    db: AsyncSession, org_id: uuid.UUID, label_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Validates every label belongs to this org (tenant safety + 404 policy)."""
    valid: list[uuid.UUID] = []
    for label_id in label_ids:
        label = await LabelRepository(db).get_in_org(label_id, org_id)
        if not label:
            raise ValidationFailedError(f"Label {label_id} not found in this organization")
        valid.append(label.id)
    return valid


async def _set_task_labels(
    db: AsyncSession, task_id: uuid.UUID, label_ids: list[uuid.UUID]
) -> None:
    await db.execute(delete(TaskLabelLink).where(TaskLabelLink.task_id == task_id))
    if label_ids:
        await db.execute(
            insert(TaskLabelLink),
            [{"task_id": task_id, "label_id": lid} for lid in label_ids],
        )


async def _add_watchers(
    db: AsyncSession, task_id: uuid.UUID, user_ids: set[uuid.UUID]
) -> None:
    if not user_ids:
        return
    existing = set(
        (
            await db.execute(
                select(TaskWatcherLink.user_id).where(
                    TaskWatcherLink.task_id == task_id,
                    TaskWatcherLink.user_id.in_(user_ids),
                )
            )
        ).scalars()
    )
    missing = user_ids - existing
    if missing:
        await db.execute(
            insert(TaskWatcherLink),
            [{"task_id": task_id, "user_id": uid} for uid in missing],
        )


async def _remove_watcher(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        delete(TaskWatcherLink).where(
            TaskWatcherLink.task_id == task_id,
            TaskWatcherLink.user_id == user_id,
        )
    )


async def get_task_for_org(
    db: AsyncSession, task_id: uuid.UUID, organization_id: uuid.UUID
) -> Task:
    task = await TaskRepository(db).get_in_org(task_id, organization_id)
    if not task:
        # 404 hides cross-org task IDs (IDOR containment).
        raise NotFoundError("Task not found")
    return task


def task_event_payload(task: Task) -> dict:
    return {
        "id": str(task.id),
        "key": task.key,
        "project_id": str(task.project_id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "type": task.type,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "sprint_id": str(task.sprint_id) if task.sprint_id else None,
        "release_id": str(task.release_id) if task.release_id else None,
        "estimate": task.estimate,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


async def _assert_release_in_project(
    db: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    release_id: uuid.UUID,
) -> Release:
    release = await ReleaseRepository(db).get_in_org(release_id, org_id)
    if release is None or release.project_id != project_id:
        raise ValidationFailedError("Release not found in this project")
    return release


async def refetch_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    """Re-select after commit so labels/watchers/assignee load eagerly and
    safely inside the async session (no implicit lazy loads).

    `populate_existing=True` matters when the Task is already in the identity
    map (e.g. loaded by the access dependency): without it, eager loaders
    leave already-populated collections untouched and responses would be
    stale (empty labels right after assignment)."""
    statement = (
        select(Task)
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(statement)).scalar_one()


async def _apply_create_fields(
    db: AsyncSession,
    org: Organization,
    project: Project,
    data: TaskCreate,
    actor: User,
) -> Task:
    """Builds a fully validated Task (without persisting it)."""
    if data.parent_id is not None:
        await _assert_parent_valid(db, org.id, project.id, data.parent_id, data.type)
    if data.recurrence_rule:
        recurrence.validate_rule(data.recurrence_rule)

    workflow = await workflows.get_workflow(db, project)
    status_key = workflows.initial_status_key(workflow)
    number, key = await _next_issue_key(db, project)
    task = Task(
        organization_id=org.id,
        project_id=project.id,
        title=data.title,
        description=data.description,
        status=status_key,
        status_category=workflows.category_for(workflow, status_key),
        priority=data.priority,
        type=data.type,
        parent_id=data.parent_id,
        due_date=data.due_date,
        created_by_id=actor.id,
        number=number,
        key=key,
        backlog_rank=_next_backlog_rank(),
        estimate=data.estimate,
        remaining_estimate=data.remaining_estimate
        if data.remaining_estimate is not None
        else data.estimate,
        actual_estimate=data.actual_estimate,
        recurrence_rule=data.recurrence_rule,
    )
    if data.sprint_id is not None:
        await _assert_sprint_in_project(db, org.id, project.id, data.sprint_id)
        task.sprint_id = data.sprint_id
    if data.release_id is not None:
        await _assert_release_in_project(db, org.id, project.id, data.release_id)
        task.release_id = data.release_id
    if data.assignee_id is not None:
        await _assert_assignee_in_org(db, org.id, data.assignee_id)
        task.assignee_id = data.assignee_id
    return task


async def create_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    data: TaskCreate,
    ip: str | None = None,
    *,
    run_automations: bool = True,
) -> Task:
    task = await _apply_create_fields(db, org, project, data, actor)

    # Additional assignees (role-bearing); the primary assignee stays in sync
    # with `assignee_id` for backwards compatibility.
    assignee_entries: list[tuple[uuid.UUID, str]] = [
        (entry.user_id, entry.role) for entry in data.assignees
    ]
    if data.assignee_id is not None and all(
        user_id != data.assignee_id for user_id, _role in assignee_entries
    ):
        assignee_entries.insert(0, (data.assignee_id, AssigneeRole.ASSIGNEE))
    for user_id, _role in assignee_entries:
        await _assert_assignee_in_org(db, org.id, user_id)
    if task.assignee_id is None and assignee_entries:
        task.assignee_id = assignee_entries[0][0]

    task = await TaskRepository(db).add(task)
    if data.label_ids:
        valid_ids = await _resolve_label_ids(db, org.id, data.label_ids)
        await _set_task_labels(db, task.id, valid_ids)

    resolved_values = await custom_field_service.resolve_values(
        db, project, data.custom_fields
    )
    await custom_field_service.set_task_values(db, org.id, task.id, resolved_values)
    await custom_field_service.assert_required_satisfied(db, project, task.id)

    for position, (user_id, role) in enumerate(assignee_entries):
        db.add(
            TaskAssignee(
                organization_id=org.id,
                task_id=task.id,
                user_id=user_id,
                role=role,
            )
        )
    if assignee_entries:
        await db.flush()

    for position, text in enumerate(data.checklist):
        db.add(
            ChecklistItem(
                organization_id=org.id,
                task_id=task.id,
                text=text[:500],
                position=position,
                created_by_id=actor.id,
            )
        )

    # Creator + assignees auto-watch.
    watcher_ids = {actor.id} | {user_id for user_id, _role in assignee_entries}
    await _add_watchers(db, task.id, watcher_ids)

    await audit.log(
        db, AuditAction.TASK_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"title": task.title, "project_id": str(project.id), "key": task.key},
    )
    for user_id, _role in assignee_entries:
        if user_id == actor.id:
            continue
        await audit.log(
            db, AuditAction.TASK_ASSIGNED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"assignee_id": str(user_id)},
        )
        await events.notify(
            db,
            user_id=user_id,
            type="task_assigned",
            title=f"You were assigned: {task.title}",
            organization_id=org.id,
            project_id=project.id,
            task_id=task.id,
            data={"task_id": str(task.id), "project_id": str(project.id)},
        )
    await activities.record(
        db,
        organization_id=org.id,
        project_id=project.id,
        task_id=task.id,
        actor_id=actor.id,
        verb="task_created",
        summary=f"created {task.key or task.title}",
        data={"title": task.title, "type": task.type, "priority": task.priority},
    )
    await db.commit()

    task = await refetch_task(db, task.id)
    payload = task_event_payload(task)
    await events.publish_project_event(project.id, "task.created", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="task.created", data=payload
    )
    await events.dispatch_integrations(
        db, organization_id=org.id, event="task.created", data=payload
    )
    for user_id, _role in assignee_entries:
        if user_id == actor.id:
            continue
        await preferences.task_email(
            db,
            user_id=user_id,
            notification_type="task_assigned",
            kind="task_assigned",
            task=task,
            project=project,
            org_slug=org.slug,
        )
    await cache.invalidate_dashboard(org.id)
    if run_automations:
        # Snapshot the PK first: automation actions commit/rollback, which can
        # expire the instance; reload before returning so serializers never
        # touch expired attributes.
        task_id = task.id
        try:
            await automations.execute_rules_for_event(
                db, event="task_created", task=task, org=org, actor=actor
            )
        except Exception:
            logger.exception("Automation execution failed for task %s", task_id)
        task = await refetch_task(db, task_id)
    return task


async def update_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: TaskUpdate,
    ip: str | None = None,
    *,
    run_automations: bool = True,
) -> Task:
    """Permission note: every org member may update tasks (collaboration-first);
    deletion and project management are the gated actions."""
    changed = data.model_fields_set
    old_status = task.status
    old_category = task.status_category

    if "type" in changed and data.type is not None and data.type != task.type:
        await _assert_type_change_valid(db, org.id, task, data.type)
        task.type = data.type

    if "parent_id" in changed and data.parent_id != task.parent_id:
        if data.parent_id is None:
            task.parent_id = None
        else:
            await _assert_parent_valid(
                db, org.id, task.project_id, data.parent_id, task.type, task.id
            )
            task.parent_id = data.parent_id

    if "assignee_id" in changed and data.assignee_id != task.assignee_id:
        if data.assignee_id is not None:
            await _assert_assignee_in_org(db, org.id, data.assignee_id)
        task.assignee_id = data.assignee_id

    if "sprint_id" in changed and data.sprint_id != task.sprint_id:
        if data.sprint_id is not None:
            await _assert_sprint_in_project(db, org.id, task.project_id, data.sprint_id)
        task.sprint_id = data.sprint_id

    if "release_id" in changed and data.release_id != task.release_id:
        if data.release_id is not None:
            await _assert_release_in_project(db, org.id, task.project_id, data.release_id)
        task.release_id = data.release_id

    if "estimate" in changed:
        task.estimate = data.estimate
    if "remaining_estimate" in changed:
        task.remaining_estimate = data.remaining_estimate
    if "actual_estimate" in changed:
        task.actual_estimate = data.actual_estimate

    if "status" in changed and data.status and data.status != task.status:
        project = await ProjectRepository(db).get(task.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        new_category = await workflows.assert_transition(
            db, project, task.status, data.status
        )
        await TaskStatusHistoryRepository(db).add(
            TaskStatusHistory(
                organization_id=org.id,
                task_id=task.id,
                from_status=task.status,
                to_status=data.status,
                from_category=old_category,
                to_category=new_category,
                changed_by_id=actor.id,
            )
        )
        task.status = data.status
        task.status_category = new_category
        task.completed_at = (
            datetime.now(UTC) if new_category == TaskStatus.DONE else None
        )

    if "custom_fields" in changed and data.custom_fields is not None:
        project = await ProjectRepository(db).get(task.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        resolved = await custom_field_service.resolve_values(
            db, project, data.custom_fields
        )
        await custom_field_service.assert_required_not_cleared(db, project, resolved)
        await custom_field_service.set_task_values(db, org.id, task.id, resolved)

    if "recurrence_rule" in changed:
        if data.recurrence_rule:
            recurrence.validate_rule(data.recurrence_rule)
        task.recurrence_rule = data.recurrence_rule

    if "title" in changed and data.title is not None:
        task.title = data.title
    if "description" in changed:
        task.description = data.description
    if "priority" in changed and data.priority is not None:
        task.priority = data.priority
    if "due_date" in changed:
        task.due_date = data.due_date

    if "label_ids" in changed and data.label_ids is not None:
        valid_ids = await _resolve_label_ids(db, org.id, data.label_ids)
        await _set_task_labels(db, task.id, valid_ids)

    if task.assignee_id:
        await _add_watchers(db, task.id, {task.assignee_id})

    task = await TaskRepository(db).update(task)
    await audit.log(
        db, AuditAction.TASK_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"fields": sorted(changed)},
    )
    if "assignee_id" in changed and task.assignee_id:
        await audit.log(
            db, AuditAction.TASK_ASSIGNED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"assignee_id": str(task.assignee_id)},
        )
        if task.assignee_id != actor.id:
            await events.notify(
                db,
                user_id=task.assignee_id,
                type="task_assigned",
                title=f"You were assigned: {task.title}",
                organization_id=org.id,
                project_id=task.project_id,
                task_id=task.id,
                data={"task_id": str(task.id), "project_id": str(task.project_id)},
            )
    completed_now = (
        task.status_category == TaskStatus.DONE
        and old_status != TaskStatus.DONE
        and old_category != TaskStatus.DONE
    )
    if completed_now:
        await _notify_task_completed(db, org, task, actor)
    if "status" in changed and task.status != old_status:
        await activities.record(
            db,
            organization_id=org.id,
            project_id=task.project_id,
            task_id=task.id,
            actor_id=actor.id,
            verb="status_changed",
            summary=f"moved {task.key or task.title} to {task.status}",
            data={"from": old_status, "to": task.status},
        )
    else:
        await activities.record(
            db,
            organization_id=org.id,
            project_id=task.project_id,
            task_id=task.id,
            actor_id=actor.id,
            verb="task_updated",
            summary=f"updated {task.key or task.title}",
            data={"fields": sorted(changed)},
        )
    await db.commit()

    task = await refetch_task(db, task.id)
    payload = task_event_payload(task)
    event_type = "task.completed" if completed_now else "task.updated"
    await events.publish_project_event(task.project_id, "task.updated", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event=event_type, data=payload
    )
    await events.dispatch_integrations(
        db, organization_id=org.id, event=event_type, data=payload
    )
    if "assignee_id" in changed and task.assignee_id and task.assignee_id != actor.id:
        project = await ProjectRepository(db).get(task.project_id)
        if project:
            await preferences.task_email(
                db,
                user_id=task.assignee_id,
                notification_type="task_assigned",
                kind="task_assigned",
                task=task,
                project=project,
                org_slug=org.slug,
            )
    if completed_now and task.recurrence_rule:
        try:
            await recurrence.spawn_next_occurrence(db, actor, org, task)
        except Exception:
            logger.exception("Failed to spawn next occurrence for task %s", task.id)
    await cache.invalidate_dashboard(org.id)
    if run_automations:
        context = {
            "changes": sorted(changed),
            "from_status": old_status,
            "from_category": old_category,
            "to_status": task.status,
            "to_category": task.status_category,
        }
        # Snapshot the PK before automation commits/rollbacks can expire it.
        task_id = task.id
        try:
            await automations.execute_rules_for_event(
                db, event="task_updated", task=task, org=org, actor=actor, context=context
            )
            task = await refetch_task(db, task_id)
            if task.status != old_status:
                await automations.execute_rules_for_event(
                    db,
                    event="status_changed",
                    task=task,
                    org=org,
                    actor=actor,
                    context=context,
                )
                task = await refetch_task(db, task_id)
        except Exception:
            logger.exception("Automation execution failed for task %s", task_id)
            task = await refetch_task(db, task_id)
    return task


async def _notify_task_completed(
    db: AsyncSession, org: Organization, task: Task, actor: User
) -> None:
    """Watchers, assignee and creator hear about a completed task
    (NotificationType.TASK_COMPLETED was declared but never emitted)."""
    recipients = {w.id for w in task.watchers}
    if task.assignee_id:
        recipients.add(task.assignee_id)
    if task.created_by_id:
        recipients.add(task.created_by_id)
    recipients.discard(actor.id)
    for user_id in recipients:
        await events.notify(
            db,
            user_id=user_id,
            type="task_completed",
            title=f"Completed: {task.title}",
            organization_id=org.id,
            project_id=task.project_id,
            task_id=task.id,
            data={"task_id": str(task.id), "project_id": str(task.project_id)},
        )


async def move_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    new_status: str,
    ip: str | None = None,
    *,
    run_automations: bool = True,
) -> Task:
    if new_status == task.status:
        return task
    # update_task validates the move against the project workflow (which may be
    # custom), records status history and enforces WIP limits.
    return await update_task(
        db, actor, org, task, TaskUpdate(status=new_status), ip,
        run_automations=run_automations,
    )


async def archive_task(
    db: AsyncSession, actor: User, org: Organization, task: Task, ip: str | None = None
) -> Task:
    if task.archived_at is None:
        task.archived_at = datetime.now(UTC)
        task = await TaskRepository(db).update(task)
        await audit.log(
            db, AuditAction.TASK_UPDATED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"archived": True},
        )
        await db.commit()
    return task


async def restore_task(
    db: AsyncSession, actor: User, org: Organization, task: Task, ip: str | None = None
) -> Task:
    if task.archived_at is not None:
        task.archived_at = None
        task = await TaskRepository(db).update(task)
        await audit.log(
            db, AuditAction.TASK_UPDATED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"archived": False},
        )
        await db.commit()
    return task


async def clone_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    *,
    target_project: Project | None = None,
    ip: str | None = None,
) -> Task:
    """Duplicate a task (optionally into another project).

    Labels/watchers are copied; the parent is kept only when it exists in the
    target project. The clone starts fresh in TODO with a new issue key.
    """
    project = target_project or await ProjectRepository(db).get(task.project_id)
    if project is None:
        raise ValidationFailedError("Target project not found")
    parent_id = task.parent_id
    if parent_id is not None:
        parent = await TaskRepository(db).get_in_org(parent_id, org.id)
        if parent is None or parent.project_id != project.id:
            parent_id = None
    workflow = await workflows.get_workflow(db, project)
    workflow_keys = {status.key for status in workflow}
    clone_status = task.status if task.status in workflow_keys else workflows.initial_status_key(workflow)
    number, key = await _next_issue_key(db, project)
    clone = Task(
        organization_id=org.id,
        project_id=project.id,
        title=f"{task.title} (copy)"[:255],
        description=task.description,
        status=clone_status,
        status_category=workflows.category_for(workflow, clone_status),
        priority=task.priority,
        type=task.type,
        parent_id=parent_id,
        due_date=task.due_date,
        created_by_id=actor.id,
        assignee_id=task.assignee_id,
        number=number,
        key=key,
        estimate=task.estimate,
        remaining_estimate=task.remaining_estimate,
        actual_estimate=task.actual_estimate,
        backlog_rank=_next_backlog_rank(),
        sprint_id=task.sprint_id if project.id == task.project_id else None,
    )
    clone = await TaskRepository(db).add(clone)
    label_ids = [label.id for label in task.labels]
    if label_ids:
        await _set_task_labels(db, clone.id, label_ids)
    watcher_ids = {w.id for w in task.watchers} | {actor.id}
    await _add_watchers(db, clone.id, watcher_ids)

    # Copy M2 attachments: custom values, assignees and checklist items.
    values = await custom_field_service.values_for_tasks(db, [task.id], task.project_id)
    for entry in values.get(task.id, []):
        db.add(
            CustomFieldValue(
                organization_id=org.id,
                task_id=clone.id,
                field_id=entry["field_id"],
                value=entry["value"],
            )
        )
    for entry in await TaskAssigneeRepository(db).list_for_task(task.id):
        db.add(
            TaskAssignee(
                organization_id=org.id,
                task_id=clone.id,
                user_id=entry.user_id,
                role=entry.role,
            )
        )
    for item in await ChecklistRepository(db).list_for_task(task.id):
        db.add(
            ChecklistItem(
                organization_id=org.id,
                task_id=clone.id,
                text=item.text,
                position=item.position,
                created_by_id=actor.id,
            )
        )
    await db.flush()
    await audit.log(
        db, AuditAction.TASK_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=clone.id, ip=ip,
        meta={"title": clone.title, "cloned_from": str(task.id), "key": clone.key},
    )
    await db.commit()
    clone = await refetch_task(db, clone.id)
    payload = task_event_payload(clone)
    await events.publish_project_event(clone.project_id, "task.created", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="task.created", data=payload
    )
    await cache.invalidate_dashboard(org.id)
    return clone


async def move_task_to_project(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    task: Task,
    target_project_id: uuid.UUID,
    ip: str | None = None,
) -> Task:
    """Move a task (and its descendants) to another project in the same org."""
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can move tasks between projects")
    if task.project_id == target_project_id:
        return task
    target = await ProjectRepository(db).get_in_org(target_project_id, org.id)
    if not target:
        raise ValidationFailedError("Target project not found")

    target_workflow = await workflows.get_workflow(db, target)
    target_keys = {status.key for status in target_workflow}
    target_by_category: dict[str, str] = {}
    for status in sorted(target_workflow, key=lambda entry: entry.position):
        target_by_category.setdefault(status.category, status.key)

    descendants = await _collect_descendants(db, org.id, task.id)
    for node in [task, *descendants]:
        number, key = await _next_issue_key(db, target)
        node.project_id = target.id
        node.number = number
        node.key = key
        if node.status not in target_keys:
            node.status = target_by_category.get(
                node.status_category, workflows.initial_status_key(target_workflow)
            )
        node.status_category = workflows.category_for(target_workflow, node.status)
        # Sprint/parent links only survive when they already live in the target.
        if node.sprint_id is not None:
            sprint = await SprintRepository(db).get_in_org(node.sprint_id, org.id)
            if sprint is None or sprint.project_id != target.id:
                node.sprint_id = None
        if node.parent_id is not None:
            moves_with_tree = node.parent_id == task.id or any(
                d.id == node.parent_id for d in descendants
            )
            if not moves_with_tree:
                parent = await TaskRepository(db).get_in_org(node.parent_id, org.id)
                if parent is None or parent.project_id != target.id:
                    node.parent_id = None
        db.add(node)
    await db.flush()
    await audit.log(
        db, AuditAction.TASK_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"moved_to_project": str(target.id)},
    )
    await db.commit()
    moved = await refetch_task(db, task.id)
    payload = task_event_payload(moved)
    await events.publish_project_event(moved.project_id, "task.updated", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="task.updated", data=payload
    )
    await cache.invalidate_dashboard(org.id)
    return moved


MAX_DESCENDANTS = 1000


async def _collect_descendants(
    db: AsyncSession, org_id: uuid.UUID, root_id: uuid.UUID
) -> list[Task]:
    """Bounded breadth-first walk of the task hierarchy below `root_id`."""
    collected: list[Task] = []
    seen: set[uuid.UUID] = {root_id}
    frontier = [root_id]
    repo = TaskRepository(db)
    while frontier and len(collected) < MAX_DESCENDANTS:
        current = frontier.pop()
        children = await repo.list_children(org_id, current, limit=500)
        for child in children:
            if child.id in seen:
                continue
            seen.add(child.id)
            collected.append(child)
            frontier.append(child.id)
            if len(collected) >= MAX_DESCENDANTS:
                break
    return collected


async def delete_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    task: Task,
    ip: str | None = None,
) -> None:
    if not _can_delete(membership, task, actor):
        raise PermissionDeniedError(
            "Only managers and above (or the creator) can delete tasks"
        )
    await audit.log(
        db, AuditAction.TASK_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"title": task.title},
    )
    project_id = task.project_id
    task_id_str = str(task.id)
    await TaskRepository(db).delete(task)
    await db.commit()
    await events.publish_project_event(project_id, "task.deleted", {"id": task_id_str})
    await cache.invalidate_dashboard(org.id)


async def add_watcher(db: AsyncSession, actor: User, org: Organization, task: Task) -> Task:
    await _add_watchers(db, task.id, {actor.id})
    await db.commit()
    return await refetch_task(db, task.id)


async def remove_watcher(db: AsyncSession, actor: User, org: Organization, task: Task) -> Task:
    await _remove_watcher(db, task.id, actor.id)
    await db.commit()
    return await refetch_task(db, task.id)


async def list_watchers(task: Task) -> list[uuid.UUID]:
    return [w.id for w in task.watchers]
