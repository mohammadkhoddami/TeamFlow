"""Workflow status + board routes."""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess
from app.schemas import (
    BoardCreate,
    BoardRead,
    BoardUpdate,
    WorkflowStatusRead,
    WorkflowUpdate,
)
from app.services import workflows as workflow_service

project_workflow_router = APIRouter(
    prefix="/projects/{project_id}/workflow", tags=["workflows"]
)
project_board_router = APIRouter(prefix="/projects/{project_id}/boards", tags=["boards"])
board_router = APIRouter(prefix="/organizations/{slug}/boards", tags=["boards"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _status_read(row, position: int) -> WorkflowStatusRead:
    return WorkflowStatusRead(
        id=getattr(row, "id", None),
        key=row.key,
        name=row.name,
        category=row.category,
        wip_limit=row.wip_limit,
        transitions=list(row.transitions or []),
        position=position,
    )


@project_workflow_router.get(
    "", response_model=list[WorkflowStatusRead], summary="Project workflow (defaults when unset)"
)
async def get_workflow(project_access: ProjectAccess, db: DB) -> list[WorkflowStatusRead]:
    project, _org, _m = project_access
    rows = await workflow_service.get_workflow(db, project)
    return [
        _status_read(row, index)
        for index, row in enumerate(
            sorted(rows, key=lambda entry: entry.position)
        )
    ]


@project_workflow_router.put(
    "", response_model=list[WorkflowStatusRead], summary="Replace the project workflow"
)
async def save_workflow(
    data: WorkflowUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> list[WorkflowStatusRead]:
    project, org, m = project_access
    rows = await workflow_service.save_workflow(
        db, current_user, org, project, m, data
    )
    return [_status_read(row, index) for index, row in enumerate(rows)]


@project_board_router.get("", response_model=list[BoardRead])
async def list_boards(project_access: ProjectAccess, db: DB) -> list[BoardRead]:
    project, org, _m = project_access
    boards = await workflow_service.list_boards(db, org.id, project.id)
    return [BoardRead.model_validate(board) for board in boards]


@project_board_router.post("", status_code=status.HTTP_201_CREATED, response_model=BoardRead)
async def create_board(
    data: BoardCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> BoardRead:
    project, org, m = project_access
    board = await workflow_service.create_board(
        db, current_user, org, project, m, data
    )
    return BoardRead.model_validate(board)


@board_router.patch("/{board_id}", response_model=BoardRead)
async def update_board(
    board_id: uuid.UUID,
    data: BoardUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> BoardRead:
    org, m = membership
    board = await workflow_service.get_board_for_org(db, board_id, org.id)
    project = await _project_for_board(db, board.project_id)
    updated = await workflow_service.update_board(
        db, current_user, org, project, m, board, data
    )
    return BoardRead.model_validate(updated)


@board_router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    board = await workflow_service.get_board_for_org(db, board_id, org.id)
    await workflow_service.delete_board(db, current_user, org, m, board)


async def _project_for_board(db: DB, project_id: uuid.UUID):
    from app.repositories import ProjectRepository

    project = await ProjectRepository(db).get(project_id)
    assert project is not None
    return project
