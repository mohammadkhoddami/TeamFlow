"""Repositories for API tokens, service accounts and OAuth apps."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import ApiToken, OAuthApp, OAuthToken, ServiceAccount


class ApiTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, token_id: uuid.UUID, organization_id: uuid.UUID) -> ApiToken | None:
        statement = select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        statement = select(ApiToken).where(ApiToken.token_hash == token_hash)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self, organization_id: uuid.UUID, *, user_id: uuid.UUID | None = None
    ) -> list[ApiToken]:
        statement = select(ApiToken).where(ApiToken.organization_id == organization_id)
        if user_id is not None:
            statement = statement.where(ApiToken.user_id == user_id)
        statement = statement.order_by(ApiToken.created_at.desc())
        return list((await self.db.execute(statement)).scalars().all())

    async def count_for_service_account(self, service_account_id: uuid.UUID) -> int:
        statement = select(func.count(ApiToken.id)).where(
            ApiToken.service_account_id == service_account_id
        )
        return (await self.db.execute(statement)).scalar_one()

    async def add(self, token: ApiToken) -> ApiToken:
        self.db.add(token)
        await self.db.flush()
        return token

    async def update(self, token: ApiToken) -> ApiToken:
        self.db.add(token)
        await self.db.flush()
        return token

    async def delete(self, token: ApiToken) -> None:
        await self.db.delete(token)
        await self.db.flush()


class ServiceAccountRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(
        self, account_id: uuid.UUID, organization_id: uuid.UUID
    ) -> ServiceAccount | None:
        statement = select(ServiceAccount).where(
            ServiceAccount.id == account_id,
            ServiceAccount.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[ServiceAccount]:
        statement = (
            select(ServiceAccount)
            .where(ServiceAccount.organization_id == organization_id)
            .order_by(ServiceAccount.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, account: ServiceAccount) -> ServiceAccount:
        self.db.add(account)
        await self.db.flush()
        return account

    async def update(self, account: ServiceAccount) -> ServiceAccount:
        self.db.add(account)
        await self.db.flush()
        return account

    async def delete(self, account: ServiceAccount) -> None:
        await self.db.delete(account)
        await self.db.flush()


class OAuthAppRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, app_id: uuid.UUID, organization_id: uuid.UUID) -> OAuthApp | None:
        statement = select(OAuthApp).where(
            OAuthApp.id == app_id,
            OAuthApp.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_client_id(self, client_id: str) -> OAuthApp | None:
        statement = select(OAuthApp).where(OAuthApp.client_id == client_id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[OAuthApp]:
        statement = (
            select(OAuthApp)
            .where(OAuthApp.organization_id == organization_id)
            .order_by(OAuthApp.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, app: OAuthApp) -> OAuthApp:
        self.db.add(app)
        await self.db.flush()
        return app

    async def update(self, app: OAuthApp) -> OAuthApp:
        self.db.add(app)
        await self.db.flush()
        return app

    async def delete(self, app: OAuthApp) -> None:
        await self.db.delete(app)
        await self.db.flush()


class OAuthTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_hash(self, token_hash: str) -> OAuthToken | None:
        statement = select(OAuthToken).where(OAuthToken.token_hash == token_hash)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, token: OAuthToken) -> OAuthToken:
        self.db.add(token)
        await self.db.flush()
        return token
