"""Workflow + board service.

Projects without saved `WorkflowStatus` rows use the classic four-column
default. Saving a workflow validates the status graph, re-homes tasks whose
status disappeared, and updates `Project.wip_enforced`. Transition validation
and WIP enforcement are used by the task service for every move.
"""

import uuid

from sqlalchemy import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    Board,
    Membership,
    MembershipRole,
    Organization,
    Project,
    SwimlaneBy,
    Task,
    TaskStatus,
    User,
    WorkflowStatus,
)
from app.repositories import BoardRepository, WorkflowStatusRepository
from app.schemas import BoardCreate, BoardUpdate, WorkflowUpdate

DEFAULT_WORKFLOW: list[dict] = [
    {
        "key": "todo",
        "name": "To do",
        "category": TaskStatus.TODO,
        "position": 0,
        "wip_limit": None,
        "transitions": ["in_progress"],
    },
    {
        "key": "in_progress",
        "name": "In progress",
        "category": TaskStatus.IN_PROGRESS,
        "position": 1,
        "wip_limit": None,
        "transitions": ["todo", "in_review"],
    },
    {
        "key": "in_review",
        "name": "In review",
        "category": TaskStatus.IN_REVIEW,
        "position": 2,
        "wip_limit": None,
        "transitions": ["in_progress", "done"],
    },
    {
        "key": "done",
        "name": "Done",
        "category": TaskStatus.DONE,
        "position": 3,
        "wip_limit": None,
        "transitions": ["in_progress"],
    },
]


def _require_manage(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage workflows")


def default_workflow() -> list[WorkflowStatus]:
    """Synthetic (unsaved) default statuses; ids are None."""
    return [WorkflowStatus(organization_id=None, project_id=None, **entry) for entry in DEFAULT_WORKFLOW]  # type: ignore[arg-type]


async def get_workflow(db: AsyncSession, project: Project) -> list[WorkflowStatus]:
    rows = await WorkflowStatusRepository(db).list_for_project(project.id)
    return rows if rows else default_workflow()


def status_map(workflow: list[WorkflowStatus]) -> dict[str, WorkflowStatus]:
    return {status.key: status for status in workflow}


def initial_status_key(workflow: list[WorkflowStatus]) -> str:
    ordered = sorted(workflow, key=lambda entry: entry.position)
    return ordered[0].key if ordered else "todo"


def category_for(workflow: list[WorkflowStatus], status_key: str) -> str:
    status = status_map(workflow).get(status_key)
    if status is None:
        raise ValidationFailedError(f"Unknown status '{status_key}' for this project")
    return status.category


async def assert_transition(
    db: AsyncSession, project: Project, current_key: str, new_key: str
) -> str:
    """Validates a transition against the project workflow; returns the target category."""
    workflow = await get_workflow(db, project)
    statuses = status_map(workflow)
    current = statuses.get(current_key)
    if current is None:
        # Legacy task in a status that was later removed; allow moving anywhere.
        return category_for(workflow, new_key)
    target = statuses.get(new_key)
    if target is None:
        raise ValidationFailedError(
            f"Unknown status '{new_key}'. Valid: {', '.join(statuses)}"
        )
    if new_key not in (current.transitions or []):
        raise ValidationFailedError(
            f"Cannot move task from '{current_key}' to '{new_key}'"
        )
    if project.wip_enforced and target.wip_limit:
        count = (
            await db.execute(
                select(Task.id)
                .where(
                    Task.project_id == project.id,
                    Task.status == new_key,
                    Task.archived_at.is_(None),
                )
                .with_only_columns(Task.id)
            )
        ).scalars()
        if len(list(count)) >= target.wip_limit:
            raise ValidationFailedError(
                f"WIP limit reached for '{target.name}' ({target.wip_limit})"
            )
    return target.category


async def save_workflow(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    data: WorkflowUpdate,
) -> list[WorkflowStatus]:
    _require_manage(membership)
    keys = [entry.key for entry in data.statuses]
    for entry in data.statuses:
        unknown = [key for key in entry.transitions if key not in keys]
        if unknown:
            raise ValidationFailedError(
                f"Status '{entry.key}' transitions to unknown keys: {', '.join(unknown)}"
            )
        if entry.key in entry.transitions:
            raise ValidationFailedError(
                f"Status '{entry.key}' cannot transition to itself"
            )
    if not any(entry.category == TaskStatus.TODO for entry in data.statuses):
        raise ValidationFailedError("A workflow needs at least one 'todo' status")

    repo = WorkflowStatusRepository(db)
    existing = {row.key: row for row in await repo.list_for_project(project.id)}
    incoming = {entry.key: entry for entry in data.statuses}

    # Re-home tasks whose status is being removed.
    removed = [key for key in existing if key not in incoming]
    if removed:
        fallback = None
        for key in removed:
            same_category = next(
                (entry for entry in data.statuses if entry.category == existing[key].category),
                None,
            )
            fallback = same_category or data.statuses[0]
            await db.execute(
                update(Task)
                .where(Task.project_id == project.id, Task.status == key)
                .values(status=fallback.key, status_category=fallback.category)
            )

    for position, entry in enumerate(data.statuses):
        row = existing.get(entry.key)
        if row is None:
            row = WorkflowStatus(
                organization_id=org.id,
                project_id=project.id,
                key=entry.key,
                name=entry.name,
                category=entry.category,
                position=position,
                wip_limit=entry.wip_limit,
                transitions=list(entry.transitions),
            )
            await repo.add(row)
        else:
            row.name = entry.name
            row.category = entry.category
            row.position = position
            row.wip_limit = entry.wip_limit
            row.transitions = list(entry.transitions)
            await repo.update(row)
    for key in removed:
        await db.delete(existing[key])
    await db.flush()

    if data.wip_enforced is not None:
        project.wip_enforced = data.wip_enforced
        db.add(project)
        await db.flush()
    await db.commit()
    return await repo.list_for_project(project.id)


async def get_status_counts(
    db: AsyncSession, project_id: uuid.UUID
) -> dict[str, int]:
    from sqlalchemy import func

    grouped = (
        await db.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.project_id == project_id, Task.archived_at.is_(None))
            .group_by(Task.status)
        )
    ).all()
    return {row[0]: int(row[1]) for row in grouped}


# ---------------------------------------------------------------- boards


async def list_boards(
    db: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID
) -> list[Board]:
    return await BoardRepository(db).list_for_project(org_id, project_id)


async def create_board(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    data: BoardCreate,
) -> Board:
    _require_manage(membership)
    if data.swimlane_by not in SwimlaneBy.ALL:
        raise ValidationFailedError(f"Unknown swimlane grouping '{data.swimlane_by}'")
    workflow = {status.key for status in await get_workflow(db, project)}
    if data.columns:
        unknown = [key for key in data.columns if key not in workflow]
        if unknown:
            raise ValidationFailedError(f"Unknown workflow columns: {', '.join(unknown)}")
    repo = BoardRepository(db)
    if any(board.name == data.name for board in await repo.list_for_project(org.id, project.id)):
        raise ConflictError("A board with this name already exists in the project")
    if data.is_default:
        for board in await repo.list_for_project(org.id, project.id):
            board.is_default = False
            await repo.update(board)
    board = await repo.add(
        Board(
            organization_id=org.id,
            project_id=project.id,
            name=data.name,
            is_default=data.is_default,
            swimlane_by=data.swimlane_by,
            filter_query=data.filter_query,
            columns=list(data.columns) if data.columns else None,
            created_by_id=actor.id,
        )
    )
    await db.commit()
    return board


async def update_board(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    board: Board,
    data: BoardUpdate,
) -> Board:
    _require_manage(membership)
    repo = BoardRepository(db)
    if data.name is not None and data.name != board.name:
        if any(
            entry.name == data.name
            for entry in await repo.list_for_project(org.id, project.id)
            if entry.id != board.id
        ):
            raise ConflictError("A board with this name already exists in the project")
        board.name = data.name
    if data.swimlane_by is not None:
        if data.swimlane_by not in SwimlaneBy.ALL:
            raise ValidationFailedError(f"Unknown swimlane grouping '{data.swimlane_by}'")
        board.swimlane_by = data.swimlane_by
    if data.filter_query is not None:
        board.filter_query = data.filter_query or None
    if data.columns is not None:
        workflow = {status.key for status in await get_workflow(db, project)}
        unknown = [key for key in data.columns if key not in workflow]
        if unknown:
            raise ValidationFailedError(f"Unknown workflow columns: {', '.join(unknown)}")
        board.columns = list(data.columns) or None
    if data.is_default is not None and data.is_default and not board.is_default:
        for entry in await repo.list_for_project(org.id, project.id):
            entry.is_default = False
            await repo.update(entry)
        board.is_default = True
    board = await repo.update(board)
    await db.commit()
    return board


async def delete_board(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    board: Board,
) -> None:
    _require_manage(membership)
    await BoardRepository(db).delete(board)
    await db.commit()


async def get_board_for_org(
    db: AsyncSession, board_id: uuid.UUID, organization_id: uuid.UUID
) -> Board:
    board = await BoardRepository(db).get_in_org(board_id, organization_id)
    if not board:
        raise NotFoundError("Board not found")
    return board
