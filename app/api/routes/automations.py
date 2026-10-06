"""Automation rule routes (M3 #14)."""

import uuid

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.schemas import (
    AutomationExecutionRead,
    AutomationRuleCreate,
    AutomationRuleRead,
    AutomationRuleUpdate,
    AutomationTemplateRead,
)
from app.services import automations as automation_service

router = APIRouter(prefix="/organizations/{slug}/automations", tags=["automations"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[AutomationRuleRead])
async def list_rules(
    org_membership: OrgMembership,
    db: DB,
    project_id: uuid.UUID | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    active_only: bool = Query(default=False),
) -> list[AutomationRuleRead]:
    org, _m = org_membership
    rules = await automation_service.list_rules(
        db, org, project_id=project_id, trigger_type=trigger_type, active_only=active_only
    )
    return [AutomationRuleRead.model_validate(rule) for rule in rules]


@router.get("/templates", response_model=list[AutomationTemplateRead])
async def list_templates(org_membership: OrgMembership) -> list[AutomationTemplateRead]:
    return [
        AutomationTemplateRead(**template)
        for template in automation_service.list_templates()
    ]


@router.get("/executions", response_model=list[AutomationExecutionRead])
async def list_executions(
    org_membership: OrgMembership,
    db: DB,
    rule_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AutomationExecutionRead]:
    org, _m = org_membership
    executions, _total = await automation_service.list_executions(
        db, org, rule_id=rule_id, status=status_filter, offset=offset, limit=limit
    )
    rule_names: dict[uuid.UUID, str] = {}
    for execution in executions:
        if execution.rule is not None:
            rule_names[execution.rule_id] = execution.rule.name
    return [
        AutomationExecutionRead(
            id=execution.id,
            rule_id=execution.rule_id,
            rule_name=rule_names.get(execution.rule_id),
            project_id=execution.project_id,
            task_id=execution.task_id,
            trigger_event=execution.trigger_event,
            status=execution.status,
            actions_log=execution.actions_log or [],
            error=execution.error,
            created_at=execution.created_at,
        )
        for execution in executions
    ]


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=AutomationRuleRead
)
async def create_rule(
    data: AutomationRuleCreate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> AutomationRuleRead:
    org, _m = org_membership
    rule = await automation_service.create_rule(
        db, current_user, org, data, ip=_ip(request)
    )
    return AutomationRuleRead.model_validate(rule)


@router.get("/{rule_id}", response_model=AutomationRuleRead)
async def get_rule(rule_id: uuid.UUID, org_membership: OrgMembership, db: DB) -> AutomationRuleRead:
    org, _m = org_membership
    rule = await automation_service.get_rule_for_org(db, rule_id, org.id)
    return AutomationRuleRead.model_validate(rule)


@router.patch("/{rule_id}", response_model=AutomationRuleRead)
async def update_rule(
    rule_id: uuid.UUID,
    data: AutomationRuleUpdate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> AutomationRuleRead:
    org, _m = org_membership
    rule = await automation_service.get_rule_for_org(db, rule_id, org.id)
    updated = await automation_service.update_rule(
        db, current_user, org, rule, data, ip=_ip(request)
    )
    return AutomationRuleRead.model_validate(updated)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, _m = org_membership
    rule = await automation_service.get_rule_for_org(db, rule_id, org.id)
    await automation_service.delete_rule(db, current_user, org, rule, ip=_ip(request))


@router.get("/{rule_id}/executions", response_model=list[AutomationExecutionRead])
async def rule_executions(
    rule_id: uuid.UUID,
    org_membership: OrgMembership,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AutomationExecutionRead]:
    org, _m = org_membership
    executions, _total = await automation_service.list_executions(
        db, org, rule_id=rule_id, offset=offset, limit=limit
    )
    return [
        AutomationExecutionRead(
            id=execution.id,
            rule_id=execution.rule_id,
            rule_name=execution.rule.name if execution.rule else None,
            project_id=execution.project_id,
            task_id=execution.task_id,
            trigger_event=execution.trigger_event,
            status=execution.status,
            actions_log=execution.actions_log or [],
            error=execution.error,
            created_at=execution.created_at,
        )
        for execution in executions
    ]
