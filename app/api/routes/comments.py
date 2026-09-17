"""Comment routes."""

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CommentAccess, CurrentUser, TaskAccess
from app.schemas import CommentCreate, CommentRead, CommentUpdate
from app.services import comments as comment_service

router = APIRouter(prefix="/tasks/{task_id}/comments", tags=["comments"])
comment_router = APIRouter(prefix="/comments", tags=["comments"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CommentRead)
async def create_comment(
    data: CommentCreate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CommentRead:
    task, org, _m = task_access
    comment = await comment_service.create_comment(
        db, current_user, org, task, data, ip=_ip(request)
    )
    return CommentRead.model_validate(comment)


@router.get("", response_model=list[CommentRead])
async def list_comments(
    task_access: TaskAccess,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CommentRead]:
    task, _org, _m = task_access
    comments, _total = await comment_service.list_comments(
        db, task.id, offset=offset, limit=limit
    )
    return [CommentRead.model_validate(c) for c in comments]


@comment_router.get("/{comment_id}", response_model=CommentRead)
async def get_comment(comment_access: CommentAccess) -> CommentRead:
    comment, _org, _m = comment_access
    return CommentRead.model_validate(comment)


@comment_router.patch("/{comment_id}", response_model=CommentRead)
async def update_comment(
    data: CommentUpdate,
    comment_access: CommentAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CommentRead:
    comment, org, m = comment_access
    updated = await comment_service.update_comment(
        db, current_user, org, m, comment, data, ip=_ip(request)
    )
    return CommentRead.model_validate(updated)


@comment_router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_access: CommentAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    comment, org, m = comment_access
    await comment_service.delete_comment(db, current_user, org, m, comment, ip=_ip(request))

