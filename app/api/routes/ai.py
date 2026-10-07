"""AI work-breakdown routes (M4, heuristic — no external API).

`POST /breakdown` parses a markdown description into an epic > story > task
proposal; `POST /breakdown/apply` materializes the proposal through the normal
task service (so hierarchy, issue keys, audit and automation rules all apply).
"""

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, OrgMembership, get_project_access
from app.core.exceptions import ValidationFailedError
from app.core.rate_limit import ip_rate_limiter
from app.models import Organization, Project, User
from app.schemas.ai import (
    AiApplyFailure,
    AiApplyRequest,
    AiApplyResult,
    AiBreakdownItem,
    AiBreakdownProposal,
    AiBreakdownRequest,
)
from app.schemas.task import TaskCreate
from app.services import tasks as task_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations/{slug}/ai", tags=["ai"])

MAX_NODES = 100


def _count_nodes(items: list[AiBreakdownItem]) -> int:
    return sum(1 + _count_nodes(item.children) for item in items)


async def _create_nodes(
    db: AsyncSession,
    actor_id: uuid.UUID,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    items: list[AiBreakdownItem],
    parent_id: uuid.UUID | None,
    created_ids: list[uuid.UUID],
    failures: list[AiApplyFailure],
) -> None:
    from app.services import ai as ai_service

    for item in items:
        priority = item.priority or ai_service.suggest_priority(item.title)
        try:
            # Re-resolve after any rollback so expired instances are refreshed.
            actor = await db.get(User, actor_id)
            org = await db.get(Organization, org_id)
            project = await db.get(Project, project_id)
            if actor is None or org is None or project is None:
                raise ValidationFailedError("Project or actor no longer exists")
            task = await task_service.create_task(
                db,
                actor,
                org,
                project,
                TaskCreate(
                    title=item.title,
                    type=item.type,
                    priority=priority,
                    parent_id=parent_id,
                ),
                run_automations=True,
            )
        except Exception as exc:  # noqa: BLE001 - one bad node must not sink the batch
            await db.rollback()
            logger.warning("AI apply failed for %r: %s", item.title, exc)
            failures.append(
                AiApplyFailure(title=item.title, error=str(exc) or exc.__class__.__name__)
            )
            continue
        created_ids.append(task.id)
        if item.children:
            await _create_nodes(
                db,
                actor_id,
                org_id,
                project_id,
                item.children,
                task.id,
                created_ids,
                failures,
            )


@router.post(
    "/breakdown",
    response_model=AiBreakdownProposal,
    summary="Heuristically break a description into work items",
)
async def breakdown(
    data: AiBreakdownRequest,
    membership: OrgMembership,
    _rl: None = Depends(ip_rate_limiter("ai_breakdown", 20, 60)),
) -> AiBreakdownProposal:
    from app.services import ai as ai_service

    proposal = ai_service.breakdown(data.description)
    return AiBreakdownProposal.model_validate(proposal)


@router.post(
    "/breakdown/apply",
    response_model=AiApplyResult,
    summary="Create tasks from an AI breakdown proposal",
)
async def apply_breakdown(
    data: AiApplyRequest,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> AiApplyResult:
    _org, _m = membership
    # Resolved manually because project_id travels in the body (the route
    # lives under the org, not under /projects/{project_id}).
    project, org, _membership = await get_project_access(data.project_id, current_user, db)

    if _count_nodes(data.items) > MAX_NODES:
        raise ValidationFailedError(f"A proposal may contain at most {MAX_NODES} items")

    created_ids: list[uuid.UUID] = []
    failures: list[AiApplyFailure] = []
    await _create_nodes(
        db,
        current_user.id,
        org.id,
        project.id,
        data.items,
        data.parent_id,
        created_ids,
        failures,
    )
    return AiApplyResult(
        created=len(created_ids), task_ids=created_ids, failures=failures
    )
