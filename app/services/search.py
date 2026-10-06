"""Global full-text search across tasks, comments and projects.

Uses PostgreSQL `websearch_to_tsquery` against the expression GIN indexes
added in the M1 migration. Comments inherit their task's project for context.
"""

import uuid

from sqlalchemy import func as sa_func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Comment, Project, Task
from app.repositories.task import TASK_SEARCH_VECTOR, fts_condition
from app.schemas import (
    CommentSearchHit,
    ProjectSearchHit,
    SearchResponse,
    TaskSearchHit,
)

COMMENT_SEARCH_VECTOR = sa_func.to_tsvector(
    "english", sa_func.coalesce(Comment.body, "")
)
PROJECT_SEARCH_VECTOR = sa_func.to_tsvector(
    "english",
    sa_func.concat(
        sa_func.coalesce(Project.name, ""),
        " ",
        sa_func.coalesce(Project.description, ""),
    ),
)

MAX_RESULTS = 25


def _snippet(text: str | None, length: int = 160) -> str | None:
    if not text:
        return None
    clean = " ".join(text.split())
    return clean if len(clean) <= length else f"{clean[: length - 1]}…"


async def search(
    db: AsyncSession,
    organization_id: uuid.UUID,
    query: str,
    *,
    limit: int = 10,
) -> SearchResponse:
    term = query.strip()
    limit = max(1, min(limit, MAX_RESULTS))
    if not term:
        return SearchResponse(query=term, tasks=[], comments=[], projects=[])

    task_stmt = (
        select(Task, Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.organization_id == organization_id,
            Task.archived_at.is_(None),
            fts_condition(TASK_SEARCH_VECTOR, term),
        )
        .order_by(sa_func.ts_rank(TASK_SEARCH_VECTOR, sa_func.websearch_to_tsquery("english", term)).desc())
        .limit(limit)
    )
    task_hits = [
        TaskSearchHit(
            id=task.id,
            key=task.key,
            title=task.title,
            status=task.status,
            priority=task.priority,
            type=task.type,
            project_id=task.project_id,
            project_name=project_name,
            snippet=_snippet(task.description),
        )
        for task, project_name in (await db.execute(task_stmt)).all()
    ]

    comment_stmt = (
        select(Comment, Task.title, Task.key, Task.project_id)
        .join(Task, Task.id == Comment.task_id)
        .where(
            Comment.organization_id == organization_id,
            Task.archived_at.is_(None),
            fts_condition(COMMENT_SEARCH_VECTOR, term),
        )
        .order_by(Comment.created_at.desc())
        .limit(limit)
    )
    comment_hits = [
        CommentSearchHit(
            id=comment.id,
            task_id=comment.task_id,
            task_title=task_title,
            task_key=task_key,
            project_id=project_id,
            body=comment.body,
            snippet=_snippet(comment.body),
            created_at=comment.created_at,
        )
        for comment, task_title, task_key, project_id in (await db.execute(comment_stmt)).all()
    ]

    project_stmt = (
        select(Project)
        .where(
            Project.organization_id == organization_id,
            fts_condition(PROJECT_SEARCH_VECTOR, term),
        )
        .order_by(Project.updated_at.desc().nulls_last(), Project.created_at.desc())
        .limit(limit)
    )
    project_hits = [
        ProjectSearchHit(
            id=project.id,
            name=project.name,
            key=project.key,
            status=project.status,
            snippet=_snippet(project.description),
        )
        for project in (await db.execute(project_stmt)).scalars().all()
    ]

    return SearchResponse(
        query=term, tasks=task_hits, comments=comment_hits, projects=project_hits
    )
