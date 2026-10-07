"""Organization / membership repositories."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Membership, Organization, User


class OrganizationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        return await self.db.get(Organization, org_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        statement = select(Organization).where(Organization.slug == slug)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Organization], list[str]]:
        """Returns (organizations, roles) aligned by index via one JOIN."""
        statement = (
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.db.execute(statement)).all()
        return [row[0] for row in rows], [row[1] for row in rows]

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        statement = select(func.count(Membership.id)).where(Membership.user_id == user_id)
        return (await self.db.execute(statement)).scalar_one()

    async def add(self, org: Organization) -> Organization:
        self.db.add(org)
        await self.db.flush()
        return org

    async def update(self, org: Organization) -> Organization:
        self.db.add(org)
        await self.db.flush()
        return org

    async def delete(self, org: Organization) -> None:
        await self.db.delete(org)
        await self.db.flush()


class MembershipRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Membership | None:
        statement = select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Membership]:
        # Membership.user is joined-eager; no N+1 on the user column.
        # Service-account shadow users are hidden from rosters/pickers (M3 #24).
        statement = (
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == organization_id,
                User.is_service_account == False,  # noqa: E712
            )
            .order_by(Membership.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def count_for_org(self, organization_id: uuid.UUID) -> int:
        statement = select(func.count(Membership.id)).where(
            Membership.organization_id == organization_id
        )
        return (await self.db.execute(statement)).scalar_one()

    async def active_member_ids(self, organization_id: uuid.UUID) -> list[uuid.UUID]:
        statement = (
            select(Membership.user_id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == organization_id,
                Membership.is_active == True,  # noqa: E712
                User.is_service_account == False,  # noqa: E712
            )
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, membership: Membership) -> Membership:
        self.db.add(membership)
        await self.db.flush()
        return membership

    async def update(self, membership: Membership) -> Membership:
        self.db.add(membership)
        await self.db.flush()
        return membership

    async def delete(self, membership: Membership) -> None:
        await self.db.delete(membership)
        await self.db.flush()
