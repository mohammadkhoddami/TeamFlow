"""User repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_google_id(self, google_id: str) -> User | None:
        statement = select(User).where(User.google_id == google_id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, user: User) -> User:
        """Persists without committing: the service owns the transaction."""
        self.db.add(user)
        await self.db.flush()
        return user

    async def update(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        return user
