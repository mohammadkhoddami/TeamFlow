"""Releases and the roadmap/timeline projection (M3 #16)."""

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import (
    AuditAction,
    Organization,
    Project,
    Release,
    ReleaseStatus,
    Task,
    TaskStatus,
    User,
)
from app.repositories import ReleaseRepository, TaskRepository
from app.schemas import ReleaseCreate, ReleaseUpdate
from app.services import audit, activities, events

ROADMAP_CHILD_LIMIT = 200
UNASSIGNED_LIMIT = 200


async def create_release(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    data: ReleaseCreate,
    *,
    ip: str | None = None,
) -> Release:
    released_at = datetime.now(UTC) if data.status == ReleaseStatus.RELEASED else None
    release = await ReleaseRepository(db).add(
        Release(
            organization_id=org.id,
            project_id=project.id,
            name=data.name,
            description=data.description,
            version=data.version,
            status=data.status,
            start_date=data.start_date,
            release_date=data.release_date,
            released_at=released_at,
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.RELEASE_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="release", target_id=release.id, ip=ip,
        meta={"name": release.name, "project_id": str(project.id)},
    )
    await activities.record(
        db,
        organization_id=org.id,
        project_id=project.id,
        actor_id=actor.id,
        verb="release_created",
        summary=f"Release {release.name} created",
        data={"release_id": str(release.id)},
    )
    await db.commit()
    await events.publish_project_event(
        project.id, "release.created", {"id": str(release.id), "name": release.name}
    )
    return release


async def list_releases(
    db: AsyncSession, project: Project
) -> list[tuple[Release, int, int]]:
    repo = ReleaseRepository(db)
    releases = await repo.list_for_project(project.id)
    counts = await repo.task_counts(project.id, [release.id for release in releases])
    return [
        (release, *counts.get(release.id, (0, 0)))
        for release in releases
    ]


async def get_release_for_org(
    db: AsyncSession, release_id: uuid.UUID, organization_id: uuid.UUID
) -> Release:
    release = await ReleaseRepository(db).get_in_org(release_id, organization_id)
    if release is None:
        # 404 hides cross-org release IDs (IDOR containment).
        raise NotFoundError("Release not found")
    return release


async def update_release(
    db: AsyncSession,
    actor: User,
    org: Organization,
    release: Release,
    data: ReleaseUpdate,
    *,
    ip: str | None = None,
) -> Release:
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        release.name = data.name
    if "description" in changed:
        release.description = data.description
    if "version" in changed:
        release.version = data.version
    if "start_date" in changed:
        release.start_date = data.start_date
    if "release_date" in changed:
        release.release_date = data.release_date
    if "status" in changed and data.status is not None:
        if data.status == ReleaseStatus.RELEASED and release.released_at is None:
            release.released_at = datetime.now(UTC)
        elif data.status != ReleaseStatus.RELEASED:
            release.released_at = None
        release.status = data.status
    release = await ReleaseRepository(db).update(release)
    await audit.log(
        db, AuditAction.RELEASE_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="release", target_id=release.id, ip=ip,
        meta={"fields": sorted(changed)},
    )
    if "status" in changed and data.status == ReleaseStatus.RELEASED:
        await activities.record(
            db,
            organization_id=org.id,
            project_id=release.project_id,
            actor_id=actor.id,
            verb="release_published",
            summary=f"Release {release.name} published",
            data={"release_id": str(release.id)},
        )
    await db.commit()
    await events.publish_project_event(
        release.project_id, "release.updated", {"id": str(release.id), "status": release.status}
    )
    return release


async def delete_release(
    db: AsyncSession,
    actor: User,
    org: Organization,
    release: Release,
    *,
    ip: str | None = None,
) -> None:
    project_id = release.project_id
    await audit.log(
        db, AuditAction.RELEASE_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="release", target_id=release.id, ip=ip,
        meta={"name": release.name},
    )
    await ReleaseRepository(db).delete(release)
    await db.commit()
    await events.publish_project_event(project_id, "release.deleted", {"id": str(release.id)})


def _task_ref(task: Task) -> dict:
    return {
        "id": task.id,
        "key": task.key,
        "title": task.title,
        "type": task.type,
        "status": task.status,
        "status_category": task.status_category,
        "priority": task.priority,
        "due_date": task.due_date,
        "estimate": task.estimate,
        "assignee": task.assignee,
    }


async def roadmap(db: AsyncSession, org: Organization, project: Project) -> dict:
    """Timeline projection: releases + epics (with their work) + loose roots.

    Epic start/end are derived from their children's due dates (earliest /
    latest), falling back to the epic's own due date. Only one bounded
    project fetch is issued; everything else is grouped in memory.
    """
    tasks = await TaskRepository(db).list_for_project(org.id, project.id)
    by_parent: dict[uuid.UUID, list[Task]] = {}
    epics: list[Task] = []
    loose_roots: list[Task] = []
    for task in tasks:
        if task.parent_id is not None:
            by_parent.setdefault(task.parent_id, []).append(task)
        elif task.type == "epic":
            epics.append(task)
        else:
            loose_roots.append(task)

    epic_payloads = []
    for epic in epics:
        children = by_parent.get(epic.id, [])[:ROADMAP_CHILD_LIMIT]
        all_dates = [t.due_date for t in [epic, *children] if t.due_date is not None]
        done = sum(1 for t in children if t.status_category == TaskStatus.DONE)
        epic_payloads.append(
            {
                "id": epic.id,
                "key": epic.key,
                "title": epic.title,
                "status": epic.status,
                "status_category": epic.status_category,
                "priority": epic.priority,
                "start_date": min(all_dates) if all_dates else None,
                "due_date": max(all_dates) if all_dates else None,
                "task_count": len(children),
                "done_task_count": done,
                "children": [_task_ref(child) for child in children],
            }
        )
    epic_payloads.sort(key=lambda entry: (entry["start_date"] is None, entry["start_date"] or datetime.max.replace(tzinfo=UTC)))

    releases = await list_releases(db, project)
    release_payloads = [
        {
            "id": release.id,
            "organization_id": release.organization_id,
            "project_id": release.project_id,
            "name": release.name,
            "description": release.description,
            "version": release.version,
            "status": release.status,
            "start_date": release.start_date,
            "release_date": release.release_date,
            "released_at": release.released_at,
            "created_at": release.created_at,
            "task_count": total,
            "done_task_count": done,
        }
        for release, total, done in releases
    ]

    loose_roots.sort(key=lambda task: (task.due_date is None, task.due_date or datetime.max.replace(tzinfo=UTC)))
    return {
        "project_id": project.id,
        "releases": release_payloads,
        "epics": epic_payloads,
        "unassigned": [_task_ref(task) for task in loose_roots[:UNASSIGNED_LIMIT]],
    }
