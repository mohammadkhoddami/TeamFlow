"""Importers (Jira/Trello/Asana/generic CSV) and workspace export.

Importers normalize every source into the same row shape, then create tasks
through the regular task service so workflow validation, issue keys, labels
and events behave exactly like API-created work. `dry_run` parses and maps
without writing.
"""

import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ValidationFailedError
from app.models import (
    Attachment,
    Board,
    ChecklistItem,
    Comment,
    CustomField,
    Label,
    Membership,
    Organization,
    Project,
    ProjectTemplate,
    Sprint,
    SprintCapacity,
    Task,
    TaskAssignee,
    TaskLink,
    TaskTemplate,
    User,
    WorkflowStatus,
    Worklog,
)
from app.repositories import (
    CustomFieldValueRepository,
    LabelRepository,
    MembershipRepository,
    ProjectRepository,
    TaskRepository,
)
from app.schemas import ImportIssue, ImportSummary, LabelCreate, TaskCreate
from app.services import labels as label_service
from app.services import tasks as task_service
from app.services import workflows

logger = logging.getLogger(__name__)

MAX_IMPORT_ROWS = 5000


# ---------------------------------------------------------------- parsing


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _split_labels(value: str | None) -> list[str]:
    if not value:
        return []
    return [entry.strip() for entry in value.replace(";", ",").split(",") if entry.strip()]


def _row(
    title: str,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    type_: str | None = None,
    assignee_email: str | None = None,
    labels: list[str] | None = None,
    due_date: datetime | None = None,
    estimate: float | None = None,
    parent_key: str | None = None,
) -> dict:
    return {
        "title": (title or "").strip()[:255],
        "description": description or None,
        "status": status,
        "priority": priority,
        "type": type_,
        "assignee_email": (assignee_email or "").strip().lower() or None,
        "labels": labels or [],
        "due_date": due_date,
        "estimate": estimate,
        "parent_key": (parent_key or "").strip().upper() or None,
    }


def _get(row: dict, *names: str) -> str | None:
    for name in names:
        for key, value in row.items():
            if key is None:
                continue
            if key.strip().lower() == name.lower() and value not in (None, ""):
                return str(value)
    return None


def parse_generic_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    rows: list[dict] = []
    for raw in reader:
        estimate = _get(raw, "estimate", "story points", "points")
        rows.append(
            _row(
                _get(raw, "title", "name", "summary") or "",
                _get(raw, "description", "notes"),
                _get(raw, "status", "state"),
                _get(raw, "priority"),
                _get(raw, "type", "issue type"),
                _get(raw, "assignee_email", "assignee", "assignee email"),
                _split_labels(_get(raw, "labels", "tags")),
                _parse_dt(_get(raw, "due_date", "due")),
                float(estimate) if estimate and _is_number(estimate) else None,
                _get(raw, "parent_key", "parent", "epic link", "epic_key"),
            )
        )
    return rows


def parse_jira_csv(content: str) -> list[dict]:
    return parse_generic_csv(content)


def parse_asana_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    rows: list[dict] = []
    for raw in reader:
        completed = _get(raw, "completed at")
        rows.append(
            _row(
                _get(raw, "name", "task name") or "",
                _get(raw, "notes", "description"),
                "done" if completed else None,
                _get(raw, "priority"),
                _get(raw, "type"),
                _get(raw, "assignee", "assignee email"),
                _split_labels(_get(raw, "tags", "labels")),
                _parse_dt(_get(raw, "due date", "due on")),
                None,
                None,
            )
        )
    return rows


def parse_trello_json(content: str) -> list[dict]:
    payload = json.loads(content)
    lists = {entry.get("id"): entry.get("name", "") for entry in payload.get("lists") or []}
    rows: list[dict] = []
    for card in payload.get("cards") or []:
        list_name = (lists.get(card.get("idList"), "") or "").strip().lower()
        if list_name in ("done", "complete", "completed"):
            status = "done"
        elif list_name in ("in progress", "doing"):
            status = "in_progress"
        elif list_name in ("review", "in review"):
            status = "in_review"
        else:
            status = "todo"
        labels = [
            entry.get("name") or ""
            for entry in card.get("labels") or []
            if entry.get("name")
        ]
        rows.append(
            _row(
                card.get("name") or "",
                card.get("desc"),
                "done" if card.get("dueComplete") else status,
                None,
                None,
                None,
                labels,
                _parse_dt(card.get("due")),
                None,
                None,
            )
        )
    return rows


def parse_upload(fmt: str, content: str) -> list[dict]:
    if fmt in ("csv", "jira_csv"):
        return parse_jira_csv(content) if fmt == "jira_csv" else parse_generic_csv(content)
    if fmt == "asana_csv":
        return parse_asana_csv(content)
    if fmt == "trello_json":
        return parse_trello_json(content)
    raise ValidationFailedError(f"Unsupported import format '{fmt}'")


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- import


def _map_status(workflow: list[WorkflowStatus], value: str | None) -> str:
    if not value:
        return workflows.initial_status_key(workflow)
    needle = value.strip().lower()
    by_key = {status.key.lower(): status.key for status in workflow}
    by_name = {status.name.lower(): status.key for status in workflow}
    by_category = {}
    for status in sorted(workflow, key=lambda entry: entry.position):
        by_category.setdefault(status.category, status.key)
    if needle in by_key:
        return by_key[needle]
    if needle in by_name:
        return by_name[needle]
    normalized = needle.replace(" ", "_")
    if normalized in by_key:
        return by_key[normalized]
    if needle in by_category:
        return by_category[needle]
    return workflows.initial_status_key(workflow)


async def import_tasks(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    rows: list[dict],
    fmt: str,
    *,
    dry_run: bool = False,
) -> ImportSummary:
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationFailedError(
            f"Import is limited to {MAX_IMPORT_ROWS} rows per file"
        )
    workflow = await workflows.get_workflow(db, project)
    issues: list[ImportIssue] = []
    created_tasks = 0
    created_labels = 0

    members = await MembershipRepository(db).list_for_org(org.id, limit=1000)
    by_email = {
        membership.user.email.lower(): membership.user_id
        for membership in members
        if membership.user is not None
    }
    label_repo = LabelRepository(db)
    label_ids: dict[str, uuid.UUID] = {
        label.name.lower(): label.id for label in await label_repo.list_for_org(org.id, limit=500)
    }
    existing_tasks = {
        task.key: task for task in await TaskRepository(db).list_for_project(org.id, project.id)
    }
    created_by_key: dict[str, Task] = {}

    for index, row in enumerate(rows, start=1):
        title = row.get("title")
        if not title:
            issues.append(ImportIssue(row=index, message="Missing title — skipped"))
            continue
        status_key = _map_status(workflow, row.get("status"))
        priority = row.get("priority") or "medium"
        if priority not in ("low", "medium", "high", "urgent"):
            priority = "medium"
        type_ = row.get("type") or "task"
        type_map = {
            "story": "story",
            "epic": "epic",
            "task": "task",
            "bug": "task",
            "sub-task": "task",
            "subtask": "task",
            "improvement": "task",
        }
        type_ = type_map.get(str(type_).strip().lower(), "task")

        assignee_id = None
        email = row.get("assignee_email")
        if email:
            assignee_id = by_email.get(email)
            if assignee_id is None:
                issues.append(
                    ImportIssue(row=index, message=f"Assignee '{email}' is not a member — left unassigned")
                )

        resolved_labels: list[uuid.UUID] = []
        for name in row.get("labels") or []:
            key = name.lower()
            if key in label_ids:
                resolved_labels.append(label_ids[key])
                continue
            if dry_run:
                continue
            label = await label_service.create_label(
                db, actor, org, await _membership_for(db, actor, org), LabelCreate(name=name[:64])
            )
            label_ids[key] = label.id
            resolved_labels.append(label.id)
            created_labels += 1

        parent_id = None
        parent_key = row.get("parent_key")
        if parent_key:
            parent = created_by_key.get(parent_key) or existing_tasks.get(parent_key)
            if parent is not None:
                parent_id = parent.id
            else:
                issues.append(
                    ImportIssue(row=index, message=f"Parent '{parent_key}' not found — imported as top level")
                )

        if dry_run:
            created_tasks += 1
            continue

        try:
            task = await task_service.create_task(
                db,
                actor,
                org,
                project,
                TaskCreate(
                    title=title,
                    description=row.get("description"),
                    priority=priority,
                    type=type_,
                    parent_id=parent_id,
                    due_date=row.get("due_date"),
                    estimate=row.get("estimate"),
                    label_ids=resolved_labels,
                    assignee_id=assignee_id,
                ),
            )
        except ValidationFailedError as exc:
            issues.append(ImportIssue(row=index, message=str(exc)))
            continue
        if status_key != task.status:
            try:
                task = await _move_to_status(db, actor, org, task, status_key, workflow)
            except ValidationFailedError as exc:
                issues.append(
                    ImportIssue(
                        row=index,
                        message=f"Imported as '{task.status}' (could not move to '{status_key}': {exc})",
                    )
                )
        created_tasks += 1
        if task.key:
            created_by_key[task.key.upper()] = task

    return ImportSummary(
        format=fmt,
        dry_run=dry_run,
        rows=len(rows),
        created_tasks=created_tasks,
        created_labels=created_labels,
        skipped=len(rows) - created_tasks,
        issues=issues[:200],
    )


async def _membership_for(db: AsyncSession, actor: User, org: Organization) -> Membership:
    membership = await MembershipRepository(db).get_for_user(actor.id, org.id)
    assert membership is not None
    return membership


async def _move_to_status(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    target_key: str,
    workflow: list[WorkflowStatus],
) -> Task:
    """Walks the workflow graph to a status so imports respect transitions."""
    graph = {status.key: list(status.transitions or []) for status in workflow}
    if target_key not in graph:
        raise ValidationFailedError(f"Unknown status '{target_key}'")
    if task.status not in graph:
        raise ValidationFailedError(f"Current status '{task.status}' is not in the workflow")
    frontier: list[list[str]] = [[task.status]]
    seen = {task.status}
    path: list[str] | None = None
    while frontier:
        current_path = frontier.pop(0)
        node = current_path[-1]
        if node == target_key:
            path = current_path
            break
        for neighbor in graph.get(node, []):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append([*current_path, neighbor])
    if path is None:
        raise ValidationFailedError(
            f"No transition path from '{task.status}' to '{target_key}'"
        )
    for step in path[1:]:
        task = await task_service.update_task(
            db, actor, org, task, task_service.TaskUpdate(status=step)
        )
    return task


# ---------------------------------------------------------------- export


async def export_workspace(
    db: AsyncSession,
    org: Organization,
    *,
    include_attachment_urls: bool = False,
) -> dict:
    members = await MembershipRepository(db).list_for_org(org.id, limit=1000)
    projects = await ProjectRepository(db).list_for_org(org.id, limit=500)
    project_ids = [project.id for project in projects[0]]

    tasks: list[Task] = []
    for project_id in project_ids:
        tasks.extend(await TaskRepository(db).list_for_project(org.id, project_id))

    workflow_rows = (
        await db.execute(
            select(WorkflowStatus).where(WorkflowStatus.organization_id == org.id)
        )
    ).scalars()
    boards = (
        await db.execute(select(Board).where(Board.organization_id == org.id))
    ).scalars()
    labels = (
        await db.execute(select(Label).where(Label.organization_id == org.id))
    ).scalars()
    custom_fields = (
        await db.execute(select(CustomField).where(CustomField.organization_id == org.id))
    ).scalars()
    field_values = await CustomFieldValueRepository(db).list_for_tasks([task.id for task in tasks])
    sprints = (
        await db.execute(select(Sprint).where(Sprint.organization_id == org.id))
    ).scalars()
    capacities = (
        await db.execute(
            select(SprintCapacity).where(SprintCapacity.organization_id == org.id)
        )
    ).scalars()
    comments = (
        await db.execute(select(Comment).where(Comment.organization_id == org.id))
    ).scalars()
    links = (
        await db.execute(select(TaskLink).where(TaskLink.organization_id == org.id))
    ).scalars()
    checklists = (
        await db.execute(
            select(ChecklistItem).where(ChecklistItem.organization_id == org.id)
        )
    ).scalars()
    assignees = (
        await db.execute(
            select(TaskAssignee).where(TaskAssignee.organization_id == org.id)
        )
    ).scalars()
    worklogs = (
        await db.execute(select(Worklog).where(Worklog.organization_id == org.id))
    ).scalars()
    attachments = (
        await db.execute(select(Attachment).where(Attachment.organization_id == org.id))
    ).scalars()
    project_templates = (
        await db.execute(
            select(ProjectTemplate).where(ProjectTemplate.organization_id == org.id)
        )
    ).scalars()
    task_templates = (
        await db.execute(
            select(TaskTemplate).where(TaskTemplate.organization_id == org.id)
        )
    ).scalars()

    attachment_rows = []
    storage = None
    if include_attachment_urls:
        try:
            from app.services.integrations.storage import StorageClient

            storage = StorageClient.from_settings()
        except Exception:  # storage not configured: export metadata only
            storage = None
    for attachment in attachments:
        entry = {
            "id": str(attachment.id),
            "task_id": str(attachment.task_id),
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size": attachment.size,
            "status": attachment.status,
        }
        if storage is not None:
            try:
                entry["download_url"] = storage.presigned_download_url(
                    attachment.storage_key, attachment.filename
                )
            except Exception:
                entry["download_url"] = None
        attachment_rows.append(entry)

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": 2,
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "created_at": org.created_at.isoformat(),
        },
        "members": [
            {
                "user_id": str(membership.user_id),
                "email": membership.user.email if membership.user else None,
                "full_name": membership.user.full_name if membership.user else None,
                "role": membership.role,
                "is_active": membership.is_active,
            }
            for membership in members
        ],
        "projects": [
            {
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
                "status": project.status,
                "key": project.key,
                "estimation_unit": project.estimation_unit,
                "created_at": project.created_at.isoformat(),
            }
            for project in projects[0]
        ],
        "workflow_statuses": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "key": row.key,
                "name": row.name,
                "category": row.category,
                "position": row.position,
                "wip_limit": row.wip_limit,
                "transitions": row.transitions,
            }
            for row in workflow_rows
        ],
        "boards": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "name": row.name,
                "swimlane_by": row.swimlane_by,
                "filter_query": row.filter_query,
                "columns": row.columns,
            }
            for row in boards
        ],
        "labels": [
            {"id": str(row.id), "name": row.name, "color": row.color} for row in labels
        ],
        "custom_fields": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "name": row.name,
                "key": row.key,
                "field_type": row.field_type,
                "options": row.options,
            }
            for row in custom_fields
        ],
        "sprints": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "name": row.name,
                "goal": row.goal,
                "state": row.state,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "end_date": row.end_date.isoformat() if row.end_date else None,
            }
            for row in sprints
        ],
        "sprint_capacities": [
            {
                "sprint_id": str(row.sprint_id),
                "user_id": str(row.user_id),
                "capacity": row.capacity,
            }
            for row in capacities
        ],
        "tasks": [
            {
                "id": str(task.id),
                "key": task.key,
                "project_id": str(task.project_id),
                "title": task.title,
                "description": task.description,
                "type": task.type,
                "status": task.status,
                "status_category": task.status_category,
                "priority": task.priority,
                "parent_id": str(task.parent_id) if task.parent_id else None,
                "sprint_id": str(task.sprint_id) if task.sprint_id else None,
                "assignee_id": str(task.assignee_id) if task.assignee_id else None,
                "labels": [str(label.id) for label in task.labels],
                "estimate": task.estimate,
                "remaining_estimate": task.remaining_estimate,
                "actual_estimate": task.actual_estimate,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "created_at": task.created_at.isoformat(),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "archived_at": task.archived_at.isoformat() if task.archived_at else None,
                "recurrence_rule": task.recurrence_rule,
            }
            for task in tasks
        ],
        "custom_field_values": [
            {
                "task_id": str(row.task_id),
                "field_id": str(row.field_id),
                "value": row.value,
            }
            for row in field_values
        ],
        "task_assignees": [
            {"task_id": str(row.task_id), "user_id": str(row.user_id), "role": row.role}
            for row in assignees
        ],
        "checklist_items": [
            {
                "task_id": str(row.task_id),
                "text": row.text,
                "is_done": row.is_done,
                "position": row.position,
            }
            for row in checklists
        ],
        "task_links": [
            {
                "from_task_id": str(row.from_task_id),
                "to_task_id": str(row.to_task_id),
                "link_type": row.link_type,
            }
            for row in links
        ],
        "worklogs": [
            {
                "task_id": str(row.task_id),
                "user_id": str(row.user_id) if row.user_id else None,
                "minutes": row.minutes,
                "started_at": row.started_at.isoformat(),
                "description": row.description,
            }
            for row in worklogs
        ],
        "comments": [
            {
                "id": str(row.id),
                "task_id": str(row.task_id),
                "author_id": str(row.author_id) if row.author_id else None,
                "body": row.body,
                "created_at": row.created_at.isoformat(),
            }
            for row in comments
        ],
        "attachments": attachment_rows,
        "project_templates": [
            {"name": row.name, "description": row.description, "config": row.config}
            for row in project_templates
        ],
        "task_templates": [
            {
                "name": row.name,
                "title": row.title,
                "description": row.description,
                "priority": row.priority,
                "type": row.type,
                "estimate": row.estimate,
                "checklist": row.checklist,
            }
            for row in task_templates
        ],
    }


async def export_project_csv(
    db: AsyncSession, org_id: uuid.UUID, project: Project
) -> str:
    tasks = await TaskRepository(db).list_for_project(org_id, project.id)
    labels = {
        label.id: label.name
        for label in await LabelRepository(db).list_for_org(org_id, limit=500)
    }
    users: dict[uuid.UUID, str] = {}
    for membership in await MembershipRepository(db).list_for_org(org_id, limit=1000):
        if membership.user is not None:
            users[membership.user_id] = membership.user.email
    by_id = {task.id: task for task in tasks}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "key", "title", "type", "status", "status_category", "priority",
            "assignee_email", "labels", "due_date", "estimate", "remaining_estimate",
            "actual_estimate", "parent_key", "created_at", "completed_at", "description",
        ]
    )
    for task in tasks:
        writer.writerow(
            [
                task.key or "",
                task.title,
                task.type,
                task.status,
                task.status_category,
                task.priority,
                users.get(task.assignee_id, "") if task.assignee_id else "",
                ",".join(labels.get(label.id, "") for label in task.labels),
                task.due_date.isoformat() if task.due_date else "",
                task.estimate if task.estimate is not None else "",
                task.remaining_estimate if task.remaining_estimate is not None else "",
                task.actual_estimate if task.actual_estimate is not None else "",
                by_id[task.parent_id].key if task.parent_id in by_id else "",
                task.created_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else "",
                task.description or "",
            ]
        )
    return buffer.getvalue()
