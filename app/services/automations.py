"""Automation rule engine (M3 #14).

Rules = trigger + conditions + actions. The API calls
`execute_rules_for_event` after task/comment mutations; `run_due_scheduled_rules`
is invoked by a Celery beat job for `schedule` triggers.

Safety properties:
  - actions call the normal task/comment services with `run_automations=False`,
    so an automation can never recursively trigger itself (or another rule)
  - every evaluation is logged to `automation_executions`, including failures,
    so non-engineers can debug without reading code
  - a failing rule never blocks the triggering request (errors are captured)
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    AppError,
    NotFoundError,
    ValidationFailedError,
)
from app.models import (
    AuditAction,
    AutomationExecution,
    AutomationExecutionStatus,
    AutomationRule,
    AutomationTrigger,
    Membership,
    MembershipRole,
    Organization,
    Project,
    Task,
    TaskPriority,
    User,
)
from app.repositories import (
    AutomationRepository,
    LabelRepository,
    MembershipRepository,
    ProjectRepository,
    TaskRepository,
    UserRepository,
)
from app.schemas import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    AutomationRunSummary,
)
from app.services import activities, audit, events

logger = logging.getLogger(__name__)

ROLE_VALUES = ("owner", "admin", "manager", "member")
MAX_ACTIONS_PER_RULE = 20


# --- templates -------------------------------------------------------------


def list_templates() -> list[dict]:
    """Starter rules non-engineers can apply in one click (values editable)."""
    return [
        {
            "id": "urgent-notify-leads",
            "name": "Notify leads about urgent work",
            "description": "When an urgent task is created, managers get an in-app notification.",
            "trigger_type": "task_created",
            "trigger_config": None,
            "conditions": [{"field": "priority", "op": "equals", "value": "urgent"}],
            "actions": [{"type": "notify", "role": "manager"}],
        },
        {
            "id": "high-priority-watch",
            "name": "Comment on high-priority tasks",
            "description": "Adds a reminder comment whenever a high/urgent task is created.",
            "trigger_type": "task_created",
            "trigger_config": None,
            "conditions": [{"field": "priority", "op": "in", "value": ["high", "urgent"]}],
            "actions": [
                {"type": "comment", "body": "Flagged as high priority — please size this today."}
            ],
        },
        {
            "id": "celebrate-completion",
            "name": "Celebrate completed tasks",
            "description": "Posts a comment when a task moves to done.",
            "trigger_type": "status_changed",
            "trigger_config": {"to_category": "done"},
            "conditions": None,
            "actions": [{"type": "comment", "body": "Done! 🎉"}],
        },
        {
            "id": "review-sweep",
            "name": "Notify reviewer when review starts",
            "description": "When work enters in_review, notify the managers group.",
            "trigger_type": "status_changed",
            "trigger_config": {"to_status": "in_review"},
            "conditions": None,
            "actions": [{"type": "notify", "role": "manager"}],
        },
        {
            "id": "daily-standup",
            "name": "Daily standup reminder",
            "description": "Every day at 09:00 UTC, notify all members.",
            "trigger_type": "schedule",
            "trigger_config": {"interval": "daily", "at": "09:00"},
            "conditions": None,
            "actions": [{"type": "notify", "role": "member"}],
        },
        {
            "id": "urgent-triage",
            "name": "Urgent triage checklist",
            "description": "When an urgent task is created, leads are notified and a triage note is posted.",
            "trigger_type": "task_created",
            "trigger_config": None,
            "conditions": [
                {"field": "priority", "op": "equals", "value": "urgent"},
            ],
            "actions": [
                {"type": "notify", "role": "manager"},
                {"type": "comment", "body": "Urgent — triage and assign an owner today. ⏱️"},
            ],
        },
        {
            "id": "completion-webhook",
            "name": "POST completed tasks to a webhook",
            "description": "Sends a JSON payload to your endpoint when a task is completed.",
            "trigger_type": "task_updated",
            "trigger_config": None,
            "conditions": [{"field": "status_category", "op": "equals", "value": "done"}],
            "actions": [{"type": "webhook", "url": "https://example.com/teamflow-hook"}],
        },
    ]


# --- validation ------------------------------------------------------------


async def _require_project(
    db: AsyncSession, org: Organization, project_id: uuid.UUID | None
) -> Project | None:
    if project_id is None:
        return None
    project = await ProjectRepository(db).get_in_org(project_id, org.id)
    if project is None:
        raise ValidationFailedError("Project not found in this organization")
    return project


def _validate_trigger(trigger_type: str, config: dict | None) -> None:
    if trigger_type not in AutomationTrigger.ALL:
        raise ValidationFailedError("Unknown trigger type")
    config = config or {}
    if trigger_type == AutomationTrigger.SCHEDULE:
        interval = config.get("interval", "daily")
        if interval not in ("hourly", "daily", "weekly"):
            raise ValidationFailedError("Schedule interval must be hourly, daily or weekly")
        at = config.get("at")
        if at is not None:
            try:
                hour, minute = at.split(":")
                if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                raise ValidationFailedError("Schedule 'at' must be HH:MM (UTC)") from None
    if trigger_type == AutomationTrigger.STATUS_CHANGED:
        for key in ("to_status", "from_status", "to_category", "from_category"):
            value = config.get(key)
            if value is not None and not isinstance(value, str):
                raise ValidationFailedError(f"trigger_config.{key} must be a string")


async def _validate_actions(
    db: AsyncSession, org: Organization, actions: list[Any] | None
) -> list[dict]:
    if not actions:
        raise ValidationFailedError("A rule needs at least one action")
    if len(actions) > MAX_ACTIONS_PER_RULE:
        raise ValidationFailedError(f"At most {MAX_ACTIONS_PER_RULE} actions per rule")
    payloads: list[dict] = []
    for action in actions:
        # mode="json" renders UUID fields as strings so the action list is
        # JSON-serializable for the JSONB column.
        data = (
            action.model_dump(mode="json", exclude_none=True)
            if hasattr(action, "model_dump")
            else dict(action)
        )
        kind = data.get("type")
        if kind == "assign":
            assignee_id = data.get("assignee_id")
            if assignee_id is None:
                raise ValidationFailedError("assign action requires assignee_id")
            membership = await MembershipRepository(db).get_for_user(
                uuid.UUID(str(assignee_id)), org.id
            )
            if membership is None or not membership.is_active:
                raise ValidationFailedError("assignee must be an active org member")
        elif kind == "transition":
            if not data.get("status"):
                raise ValidationFailedError("transition action requires status")
        elif kind == "comment":
            if not data.get("body"):
                raise ValidationFailedError("comment action requires body")
        elif kind == "notify":
            if not data.get("user_id") and not data.get("role"):
                raise ValidationFailedError("notify action requires user_id or role")
            role = data.get("role")
            if role is not None and role not in ROLE_VALUES:
                raise ValidationFailedError("notify role must be owner/admin/manager/member")
            if data.get("user_id"):
                user = await UserRepository(db).get(uuid.UUID(str(data["user_id"])))
                if user is None:
                    raise ValidationFailedError("notify user not found")
        elif kind == "webhook":
            url = data.get("url") or ""
            if not url.startswith(("http://", "https://")):
                raise ValidationFailedError("webhook action requires an http(s) url")
        elif kind == "add_label":
            if not data.get("label_id"):
                raise ValidationFailedError("add_label action requires label_id")
            label = await LabelRepository(db).get_in_org(
                uuid.UUID(str(data["label_id"])), org.id
            )
            if label is None:
                raise ValidationFailedError("label not found in this organization")
        elif kind == "set_priority":
            if data.get("priority") not in TaskPriority.ALL:
                raise ValidationFailedError("set_priority requires a valid priority")
        else:
            raise ValidationFailedError(f"Unknown action type '{kind}'")
        payloads.append(data)
    return payloads


# --- CRUD ------------------------------------------------------------------


async def create_rule(
    db: AsyncSession,
    actor: User,
    org: Organization,
    data: AutomationRuleCreate,
    *,
    ip: str | None = None,
) -> AutomationRule:
    await _require_project(db, org, data.project_id)
    _validate_trigger(data.trigger_type, data.trigger_config)
    actions = await _validate_actions(db, org, data.actions)
    conditions = (
        [condition.model_dump(mode="json", exclude_none=True) for condition in data.conditions]
        if data.conditions
        else None
    )
    rule = await AutomationRepository(db).add(
        AutomationRule(
            organization_id=org.id,
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            is_active=data.is_active,
            trigger_type=data.trigger_type,
            trigger_config=data.trigger_config,
            conditions=conditions,
            actions=actions,
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.AUTOMATION_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="automation_rule", target_id=rule.id, ip=ip,
        meta={"name": rule.name, "trigger": rule.trigger_type},
    )
    await db.commit()
    return rule


async def list_rules(
    db: AsyncSession,
    org: Organization,
    *,
    project_id: uuid.UUID | None = None,
    trigger_type: str | None = None,
    active_only: bool = False,
) -> list[AutomationRule]:
    return await AutomationRepository(db).list_for_org(
        org.id, project_id=project_id, trigger_type=trigger_type, active_only=active_only
    )


async def get_rule_for_org(
    db: AsyncSession, rule_id: uuid.UUID, organization_id: uuid.UUID
) -> AutomationRule:
    rule = await AutomationRepository(db).get_in_org(rule_id, organization_id)
    if rule is None:
        raise NotFoundError("Automation rule not found")
    return rule


async def update_rule(
    db: AsyncSession,
    actor: User,
    org: Organization,
    rule: AutomationRule,
    data: AutomationRuleUpdate,
    *,
    ip: str | None = None,
) -> AutomationRule:
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        rule.name = data.name
    if "description" in changed:
        rule.description = data.description
    if "is_active" in changed and data.is_active is not None:
        rule.is_active = data.is_active
    if "trigger_config" in changed:
        _validate_trigger(rule.trigger_type, data.trigger_config)
        rule.trigger_config = data.trigger_config
    if "conditions" in changed:
        rule.conditions = (
            [condition.model_dump(mode="json", exclude_none=True) for condition in data.conditions]
            if data.conditions
            else None
        )
    if "actions" in changed and data.actions is not None:
        rule.actions = await _validate_actions(db, org, data.actions)
    rule = await AutomationRepository(db).update(rule)
    await audit.log(
        db, AuditAction.AUTOMATION_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="automation_rule", target_id=rule.id, ip=ip,
        meta={"fields": sorted(changed)},
    )
    await db.commit()
    return rule


async def delete_rule(
    db: AsyncSession,
    actor: User,
    org: Organization,
    rule: AutomationRule,
    *,
    ip: str | None = None,
) -> None:
    await audit.log(
        db, AuditAction.AUTOMATION_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="automation_rule", target_id=rule.id, ip=ip,
        meta={"name": rule.name},
    )
    await AutomationRepository(db).delete(rule)
    await db.commit()


async def list_executions(
    db: AsyncSession,
    org: Organization,
    *,
    rule_id: uuid.UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AutomationExecution], int]:
    return await AutomationRepository(db).list_executions(
        org.id, rule_id=rule_id, status=status, offset=offset, limit=limit
    )


# --- condition evaluation --------------------------------------------------


def _task_field(task: Task, field: str, context: dict[str, Any] | None) -> Any:
    if context and field in context:
        return context[field]
    if field == "labels":
        return [str(label.id) for label in task.labels]
    if field == "assignee":
        return str(task.assignee_id) if task.assignee_id else None
    if field in ("due_date", "created_at", "updated_at"):
        value = getattr(task, field, None)
        return value.isoformat() if value is not None else None
    return getattr(task, field, None)


def _evaluate_condition(condition: dict, task: Task, context: dict[str, Any] | None) -> bool:
    field = condition.get("field", "")
    op = condition.get("op", "equals")
    expected = condition.get("value")
    actual = _task_field(task, field, context)
    try:
        if op == "is_set":
            return actual not in (None, "", [])
        if op == "is_empty":
            return actual in (None, "", [])
        if op == "equals":
            if isinstance(actual, list):
                return str(expected) in [str(item) for item in actual]
            return actual == expected or str(actual) == str(expected)
        if op == "not_equals":
            return not _evaluate_condition({**condition, "op": "equals"}, task, context)
        if op == "contains":
            return expected is not None and str(expected).lower() in str(actual or "").lower()
        if op == "not_contains":
            return not _evaluate_condition({**condition, "op": "contains"}, task, context)
        if op in ("in", "not_in"):
            values = expected if isinstance(expected, list) else [expected]
            hit = any(
                actual == value or str(actual) == str(value)
                or (isinstance(actual, list) and str(value) in [str(i) for i in actual])
                for value in values
            )
            return hit if op == "in" else not hit
        if op == "gt":
            return actual is not None and float(actual) > float(expected)
        if op == "lt":
            return actual is not None and float(actual) < float(expected)
    except (TypeError, ValueError):
        return False
    return False


def _conditions_match(
    rule: AutomationRule, task: Task | None, context: dict[str, Any] | None
) -> bool:
    if not rule.conditions:
        return True
    if task is None:
        return False
    return all(_evaluate_condition(condition, task, context) for condition in rule.conditions)


def _trigger_matches(
    rule: AutomationRule, task: Task | None, context: dict[str, Any] | None
) -> bool:
    if rule.trigger_type != AutomationTrigger.STATUS_CHANGED:
        return True
    config = rule.trigger_config or {}
    if task is None:
        return True
    for key in ("to_status", "from_status", "to_category", "from_category"):
        expected = config.get(key)
        if expected is None:
            continue
        actual_key = "status" if key.endswith("status") else "status_category"
        if context and key in context:
            actual = context[key]
        else:
            actual = getattr(task, actual_key, None)
        if actual != expected:
            return False
    return True


# --- action execution ------------------------------------------------------


async def _recipients_for_role(
    db: AsyncSession, org_id: uuid.UUID, role: str
) -> list[uuid.UUID]:
    statement = (
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == org_id,
            Membership.role == role,
            Membership.is_active == True,  # noqa: E712
            User.is_active == True,  # noqa: E712
            User.is_service_account == False,  # noqa: E712
        )
    )
    return list((await db.execute(statement)).scalars().all())


async def _execute_action(
    db: AsyncSession,
    action: dict,
    *,
    rule_id: uuid.UUID,
    rule_name: str,
    rule_project_id: uuid.UUID | None,
    org: Organization,
    task: Task | None,
    actor: User,
) -> dict:
    """Runs one action; returns its log entry (never raises AppError upward).

    Rule fields are passed as snapshots (`rule_id`/`rule_name`) because action
    services commit, which expires ORM instances — touching a live `rule`
    object afterwards would trigger an async lazy-load error.
    """
    from app.schemas import CommentCreate, TaskUpdate
    from app.services import comments as comment_service
    from app.services import tasks as task_service

    kind = action.get("type")
    try:
        if kind == "assign":
            if task is None:
                return {"action": kind, "status": "skipped", "detail": "no task in context"}
            await task_service.update_task(
                db, actor, org, task,
                TaskUpdate(assignee_id=uuid.UUID(str(action["assignee_id"]))),
                run_automations=False,
            )
            return {"action": kind, "status": "success", "detail": "assignee updated"}
        if kind == "transition":
            if task is None:
                return {"action": kind, "status": "skipped", "detail": "no task in context"}
            await task_service.move_task(
                db, actor, org, task, str(action["status"]), run_automations=False
            )
            return {"action": kind, "status": "success", "detail": f"moved to {action['status']}"}
        if kind == "comment":
            if task is None:
                return {"action": kind, "status": "skipped", "detail": "no task in context"}
            await comment_service.create_comment(
                db, actor, org, task,
                CommentCreate(body=action["body"]),
                run_automations=False,
            )
            return {"action": kind, "status": "success", "detail": "comment posted"}
        if kind == "notify":
            if action.get("user_id"):
                recipients = [uuid.UUID(str(action["user_id"]))]
            else:
                recipients = await _recipients_for_role(db, org.id, action["role"])
            title = f"Automation: {rule_name}"
            if task is not None:
                title = f"Automation on {task.key or task.title}: {rule_name}"
            detail = action.get("body")
            for user_id in recipients:
                await events.notify(
                    db,
                    user_id=user_id,
                    type="automation",
                    title=title[:255],
                    body=detail,
                    organization_id=org.id,
                    project_id=task.project_id if task else rule_project_id,
                    task_id=task.id if task else None,
                    data={"rule_id": str(rule_id)},
                )
            await db.commit()
            return {
                "action": kind,
                "status": "success",
                "detail": f"notified {len(recipients)} user(s)",
            }
        if kind == "webhook":
            from starlette.concurrency import run_in_threadpool

            from app.workers.celery_app import celery_app

            payload = {
                "rule_id": str(rule_id),
                "rule_name": rule_name,
                "organization_id": str(org.id),
                "task": (
                    {
                        "id": str(task.id),
                        "key": task.key,
                        "title": task.title,
                        "status": task.status,
                        "priority": task.priority,
                    }
                    if task
                    else None
                ),
                "fired_at": datetime.now(UTC).isoformat(),
            }
            await run_in_threadpool(
                celery_app.send_task,
                "teamflow.post_webhook_url",
                [action["url"], payload],
            )
            return {"action": kind, "status": "success", "detail": "webhook queued"}
        if kind == "add_label":
            if task is None:
                return {"action": kind, "status": "skipped", "detail": "no task in context"}
            label_id = uuid.UUID(str(action["label_id"]))
            current = [label.id for label in task.labels]
            if label_id not in current:
                current.append(label_id)
            await task_service.update_task(
                db, actor, org, task, TaskUpdate(label_ids=current), run_automations=False
            )
            return {"action": kind, "status": "success", "detail": "label added"}
        if kind == "set_priority":
            if task is None:
                return {"action": kind, "status": "skipped", "detail": "no task in context"}
            await task_service.update_task(
                db, actor, org, task,
                TaskUpdate(priority=action["priority"]),
                run_automations=False,
            )
            return {"action": kind, "status": "success", "detail": f"priority {action['priority']}"}
        return {"action": str(kind), "status": "skipped", "detail": "unknown action"}
    except AppError as exc:
        await db.rollback()
        return {"action": str(kind), "status": "failed", "detail": exc.detail}
    except Exception as exc:  # noqa: BLE001 - logged, never breaks the caller
        await db.rollback()
        logger.exception("Automation action %s failed", kind)
        return {"action": str(kind), "status": "failed", "detail": str(exc)[:500]}


# --- engine ----------------------------------------------------------------


async def _run_rule(
    db: AsyncSession,
    rule: AutomationRule,
    *,
    org: Organization,
    task: Task | None,
    actor: User,
    trigger_event: str,
    context: dict[str, Any] | None,
) -> AutomationExecution:
    rule_id = rule.id
    rule_name = rule.name
    rule_project_id = rule.project_id
    actions = list(rule.actions or [])
    org_id = org.id
    task_id = task.id if task is not None else None
    actor_id = actor.id

    log: list[dict] = []
    status = AutomationExecutionStatus.SUCCESS
    error: str | None = None
    task_project_id = rule_project_id
    for action in actions:
        # Action services commit, which expires ORM instances; refresh the
        # context objects so the next action sees current, loadable state.
        await db.refresh(org)
        await db.refresh(actor)
        if task_id is not None:
            task = await TaskRepository(db).get_in_org(task_id, org_id)
        if task is not None:
            task_project_id = task.project_id
        entry = await _execute_action(
            db,
            action,
            rule_id=rule_id,
            rule_name=rule_name,
            rule_project_id=rule_project_id,
            org=org,
            task=task,
            actor=actor,
        )
        log.append(entry)
        if entry["status"] == "failed":
            status = AutomationExecutionStatus.FAILED
            error = entry.get("detail")
        elif entry["status"] == "skipped" and status == AutomationExecutionStatus.SUCCESS:
            status = AutomationExecutionStatus.SKIPPED
    execution = await AutomationRepository(db).add_execution(
        AutomationExecution(
            organization_id=org_id,
            rule_id=rule_id,
            project_id=task_project_id,
            task_id=task_id,
            trigger_event=trigger_event,
            status=status,
            actions_log=log,
            error=error,
            actor_id=actor_id,
        )
    )
    await db.execute(
        sa_update(AutomationRule)
        .where(AutomationRule.id == rule_id)
        .values(run_count=AutomationRule.run_count + 1, last_run_at=datetime.now(UTC))
    )
    if task_id is not None and status == AutomationExecutionStatus.SUCCESS:
        await activities.record(
            db,
            organization_id=org_id,
            project_id=task_project_id,
            task_id=task_id,
            actor_id=None,
            verb="automation_ran",
            summary=f"Automation '{rule_name}' ran",
            data={"rule_id": str(rule_id), "execution_id": str(execution.id)},
        )
    return execution


async def _actor_for_rule(db: AsyncSession, rule: AutomationRule, actor: User | None) -> User:
    if actor is not None:
        return actor
    if rule.created_by_id is not None:
        creator = await db.get(User, rule.created_by_id)
        if creator is not None:
            return creator
    # Last resort: any active member of the org.
    members = await _recipients_for_role(db, rule.organization_id, MembershipRole.MANAGER)
    if members:
        user = await db.get(User, members[0])
        if user is not None:
            return user
    raise NotFoundError("No actor available to run automation")


async def execute_rules_for_event(
    db: AsyncSession,
    *,
    event: str,
    task: Task,
    org: Organization,
    actor: User | None,
    context: dict[str, Any] | None = None,
) -> int:
    """Run every matching active rule for an event. Returns rules executed."""
    if event not in AutomationTrigger.ALL:
        return 0
    rules = await AutomationRepository(db).list_active_for_trigger(
        org.id, event, task.project_id
    )
    if not rules:
        return 0
    run_actor = await _actor_for_rule(db, rules[0], actor)
    org_id = org.id
    task_id = task.id
    executed = 0
    for rule in rules:
        # Commits inside earlier rules expire every instance in the session;
        # reload rule/org/task before inspecting or acting on them.
        await db.refresh(rule)
        await db.refresh(org)
        task = await TaskRepository(db).get_in_org(task_id, org_id)
        if task is None:
            break
        rule_id = rule.id
        if not _trigger_matches(rule, task, context):
            continue
        if not _conditions_match(rule, task, context):
            continue
        try:
            await _run_rule(
                db, rule,
                org=org, task=task, actor=run_actor,
                trigger_event=event, context=context,
            )
            await db.commit()
            executed += 1
        except Exception:
            await db.rollback()
            logger.exception("Automation rule %s failed", rule_id)
    return executed


# --- schedule trigger ------------------------------------------------------


def _schedule_due(rule: AutomationRule, now: datetime) -> bool:
    config = rule.trigger_config or {}
    interval = config.get("interval", "daily")
    last = rule.last_run_at
    if interval == "hourly":
        return last is None or now - last >= timedelta(hours=1)
    if interval == "weekly":
        return last is None or now - last >= timedelta(days=7)
    # daily
    at = config.get("at", "09:00")
    hour, minute = (int(part) for part in at.split(":"))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled:
        return False
    return last is None or last.date() < now.date()


async def run_due_scheduled_rules(db: AsyncSession) -> AutomationRunSummary:
    """Executed by the beat job: runs schedule-trigger rules whose time is due."""
    now = datetime.now(UTC)
    rules = await AutomationRepository(db).list_scheduled()
    evaluated = executed = skipped = 0
    for rule in rules:
        await db.refresh(rule)  # a previous rule's actions commit
        if not _schedule_due(rule, now):
            continue
        evaluated += 1
        org = await db.get(Organization, rule.organization_id)
        if org is None:
            skipped += 1
            continue
        # Schedule rules have no task context; conditions referencing task
        # fields can never match, so rules with conditions are skipped.
        if rule.conditions:
            skipped += 1
            continue
        try:
            actor = await _actor_for_rule(db, rule, None)
            await _run_rule(
                db, rule,
                org=org, task=None, actor=actor,
                trigger_event=AutomationTrigger.SCHEDULE, context=None,
            )
            await db.commit()
            executed += 1
        except Exception:
            await db.rollback()
            logger.exception("Scheduled automation rule %s failed", rule.id)
            skipped += 1
    return AutomationRunSummary(evaluated=evaluated, executed=executed, skipped=skipped)
