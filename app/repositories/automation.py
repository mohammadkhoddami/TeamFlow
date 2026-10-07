"""Automation rule + execution repositories."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AutomationExecution, AutomationRule


class AutomationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(
        self, rule_id: uuid.UUID, organization_id: uuid.UUID
    ) -> AutomationRule | None:
        statement = select(AutomationRule).where(
            AutomationRule.id == rule_id,
            AutomationRule.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        trigger_type: str | None = None,
        active_only: bool = False,
    ) -> list[AutomationRule]:
        conds = [AutomationRule.organization_id == organization_id]
        if project_id is not None:
            conds.append(
                (AutomationRule.project_id == project_id)
                | (AutomationRule.project_id.is_(None))
            )
        if trigger_type is not None:
            conds.append(AutomationRule.trigger_type == trigger_type)
        if active_only:
            conds.append(AutomationRule.is_active == True)  # noqa: E712
        statement = select(AutomationRule).where(*conds).order_by(
            AutomationRule.created_at.desc()
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_active_for_trigger(
        self,
        organization_id: uuid.UUID,
        trigger_type: str,
        project_id: uuid.UUID | None,
    ) -> list[AutomationRule]:
        conds = [
            AutomationRule.organization_id == organization_id,
            AutomationRule.trigger_type == trigger_type,
            AutomationRule.is_active == True,  # noqa: E712
        ]
        if project_id is not None:
            conds.append(
                (AutomationRule.project_id == project_id)
                | (AutomationRule.project_id.is_(None))
            )
        statement = select(AutomationRule).where(*conds)
        return list((await self.db.execute(statement)).scalars().all())

    async def list_scheduled(self) -> list[AutomationRule]:
        statement = select(AutomationRule).where(
            AutomationRule.trigger_type == "schedule",
            AutomationRule.is_active == True,  # noqa: E712
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, rule: AutomationRule) -> AutomationRule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def update(self, rule: AutomationRule) -> AutomationRule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def delete(self, rule: AutomationRule) -> None:
        await self.db.delete(rule)
        await self.db.flush()

    # --- executions -----------------------------------------------------
    async def add_execution(self, execution: AutomationExecution) -> AutomationExecution:
        self.db.add(execution)
        await self.db.flush()
        return execution

    async def list_executions(
        self,
        organization_id: uuid.UUID,
        *,
        rule_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AutomationExecution], int]:
        conds = [AutomationExecution.organization_id == organization_id]
        if rule_id is not None:
            conds.append(AutomationExecution.rule_id == rule_id)
        if status is not None:
            conds.append(AutomationExecution.status == status)
        statement = (
            select(AutomationExecution)
            .where(*conds)
            .order_by(AutomationExecution.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            await self.db.execute(
                select(func.count(AutomationExecution.id)).where(*conds)
            )
        ).scalar_one()
        return items, int(total)

    async def execution_counts(self, organization_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = (
            await self.db.execute(
                select(AutomationExecution.rule_id, func.count(AutomationExecution.id))
                .where(AutomationExecution.organization_id == organization_id)
                .group_by(AutomationExecution.rule_id)
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows}
