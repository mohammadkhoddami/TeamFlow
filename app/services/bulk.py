"""Bulk task operations: update, move, clone, delete, archive, move project.

Multi-select editing has to be fast (50 tasks in seconds) and honest: each
task's own validation still applies, and per-task failures are reported
instead of aborting the whole batch. Simple field updates run in one
transaction; clone/move-project reuse the single-task service so hierarchy and
issue-key rules stay in exactly one place.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
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
    Task,
    TaskStatus,
    TaskStatusHistory,
    User,
)
from app.repositories import (
    ProjectRepository,
    TaskRepository,
    TaskStatusHistoryRepository,
)
from app.schemas import BulkTaskFailure, BulkTaskRequest, BulkTaskResult
from app.services import audit, cache, events, workflows
from app.services import tasks as task_service


async def bulk_operate(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: BulkTaskRequest,
    ip: str | None = None,
) -> BulkTaskResult:
    if data.action == "move_project":
        if membership.role == MembershipRole.MEMBER:
            raise PermissionDeniedError(
                "Only managers and above can move tasks between projects"
            )
        if data.project_id is None:
            raise ValidationFailedError("'move_project' requires project_id")

    result = await db.execute(
        select(Task).where(
            Task.organization_id == org.id,
            Task.id.in_(data.task_ids),
        )
    )
    tasks = list(result.scalars().all())
    by_id = {task.id: task for task in tasks}
    failures = [
        BulkTaskFailure(task_id=task_id, reason="Task not found")
        for task_id in data.task_ids
        if task_id not in by_id
    ]
    ordered = [by_id[task_id] for task_id in data.task_ids if task_id in by_id]

    if data.action == "clone":
        created: list[uuid.UUID] = []
        for task in ordered:
            target = None
            if data.project_id is not None and data.project_id != task.project_id:
                target = await ProjectRepository(db).get_in_org(data.project_id, org.id)
                if target is None:
                    failures.append(
                        BulkTaskFailure(task_id=task.id, reason="Target project not found")
                    )
                    continue
            clone = await task_service.clone_task(
                db, actor, org, task, target_project=target, ip=ip
            )
            created.append(clone.id)
        await cache.invalidate_dashboard(org.id)
        return BulkTaskResult(
            requested=len(data.task_ids),
            updated=0,
            skipped=len(failures),
            created_ids=created,
            failures=failures,
        )

    if data.action == "delete":
        deleted = 0
        for task in ordered:
            if not task_service._can_delete(membership, task, actor):
                failures.append(
                    BulkTaskFailure(task_id=task.id, reason="Not allowed to delete")
                )
                continue
            await TaskRepository(db).delete(task)
            deleted += 1
        if deleted:
            project_ids = {task.project_id for task in ordered}
            await audit.log(
                db, AuditAction.TASK_DELETED, actor_id=actor.id,
                organization_id=org.id, target_type="task", ip=ip,
                meta={"bulk": True, "deleted": deleted, "task_ids": [
                    str(task.id) for task in ordered
                ]},
            )
            await db.commit()
            for project_id in project_ids:
                await events.publish_project_event(
                    project_id, "task.deleted", {"bulk": True}
                )
            await cache.invalidate_dashboard(org.id)
        return BulkTaskResult(
            requested=len(data.task_ids),
            updated=deleted,
            skipped=len(failures),
            failures=failures,
        )

    if data.action in ("archive", "restore"):
        archiving = data.action == "archive"
        changed = 0
        for task in ordered:
            if archiving and task.archived_at is None:
                task.archived_at = datetime.now(UTC)
                db.add(task)
                changed += 1
            elif not archiving and task.archived_at is not None:
                task.archived_at = None
                db.add(task)
                changed += 1
        await audit.log(
            db, AuditAction.TASK_UPDATED, actor_id=actor.id,
            organization_id=org.id, target_type="task", ip=ip,
            meta={"bulk": True, data.action: changed},
        )
        await db.commit()
        await cache.invalidate_dashboard(org.id)
        return BulkTaskResult(
            requested=len(data.task_ids),
            updated=changed,
            skipped=len(failures),
            failures=failures,
        )

    if data.action == "move_project":
        moved: list[str] = []
        for task in ordered:
            try:
                await task_service.move_task_to_project(
                    db, actor, org, membership, task, data.project_id, ip=ip
                )
                moved.append(str(task.id))
            except ValidationFailedError as exc:
                failures.append(BulkTaskFailure(task_id=task.id, reason=str(exc)))
        return BulkTaskResult(
            requested=len(data.task_ids),
            updated=len(moved),
            skipped=len(failures),
            failures=failures,
        )

    # --- update / move: one transaction, shared validations ---------------
    if data.action == "move" and data.status is None:
        raise ValidationFailedError("'move' requires a status")

    if data.assignee_id is not None:
        await task_service._assert_assignee_in_org(db, org.id, data.assignee_id)
    valid_label_ids: list[uuid.UUID] | None = None
    if data.label_ids is not None:
        valid_label_ids = await task_service._resolve_label_ids(db, org.id, data.label_ids)

    sprint_by_project: dict[uuid.UUID, uuid.UUID | None] = {}
    projects_cache: dict[uuid.UUID, Project] = {}
    completed_ids: list[uuid.UUID] = []
    updated = 0
    for task in ordered:
        task_changed = False
        if data.status is not None and data.status != task.status:
            project = projects_cache.get(task.project_id)
            if project is None:
                project = await ProjectRepository(db).get(task.project_id)
                if project is None:
                    failures.append(
                        BulkTaskFailure(task_id=task.id, reason="Project not found")
                    )
                    continue
                projects_cache[task.project_id] = project
            try:
                new_category = await workflows.assert_transition(
                    db, project, task.status, data.status
                )
            except ValidationFailedError as exc:
                failures.append(BulkTaskFailure(task_id=task.id, reason=str(exc)))
                continue
            await TaskStatusHistoryRepository(db).add(
                TaskStatusHistory(
                    organization_id=org.id,
                    task_id=task.id,
                    from_status=task.status,
                    to_status=data.status,
                    from_category=task.status_category,
                    to_category=new_category,
                    changed_by_id=actor.id,
                )
            )
            task.status = data.status
            task.status_category = new_category
            task.completed_at = (
                datetime.now(UTC) if new_category == TaskStatus.DONE else None
            )
            if new_category == TaskStatus.DONE:
                completed_ids.append(task.id)
            task_changed = True
        if data.priority is not None and data.priority != task.priority:
            task.priority = data.priority
            task_changed = True
        if data.assignee_id is not None and data.assignee_id != task.assignee_id:
            task.assignee_id = data.assignee_id
            task_changed = True
        if data.sprint_id is not None:
            if task.project_id not in sprint_by_project:
                await task_service._assert_sprint_in_project(
                    db, org.id, task.project_id, data.sprint_id
                )
                sprint_by_project[task.project_id] = data.sprint_id
            if task.sprint_id != sprint_by_project[task.project_id]:
                task.sprint_id = sprint_by_project[task.project_id]
                task_changed = True
        if data.estimate is not None and data.estimate != task.estimate:
            task.estimate = data.estimate
            task_changed = True
        if task_changed:
            db.add(task)
            updated += 1

    if valid_label_ids is not None:
        for task in ordered:
            await task_service._set_task_labels(db, task.id, valid_label_ids)

    if updated or valid_label_ids is not None:
        await audit.log(
            db, AuditAction.TASK_UPDATED, actor_id=actor.id,
            organization_id=org.id, target_type="task", ip=ip,
            meta={
                "bulk": True,
                "action": data.action,
                "updated": updated,
                "task_ids": [str(task.id) for task in ordered],
            },
        )
    await db.commit()

    for task in ordered:
        try:
            refreshed = await task_service.refetch_task(db, task.id)
            payload = task_service.task_event_payload(refreshed)
            event_type = (
                "task.completed"
                if refreshed.id in completed_ids
                else "task.updated"
            )
            await events.publish_project_event(refreshed.project_id, "task.updated", payload)
            await events.dispatch_webhooks(
                db, organization_id=org.id, event=event_type, data=payload
            )
            if refreshed.id in completed_ids:
                await task_service._notify_task_completed(
                    db, org, refreshed, actor
                )
                await db.commit()
        except NotFoundError:
            continue
    await cache.invalidate_dashboard(org.id)
    return BulkTaskResult(
        requested=len(data.task_ids),
        updated=updated,
        skipped=len(failures),
        failures=failures,
    )
