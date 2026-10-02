"""add google_id to users

Revision ID: b7d2e9f14c05
Revises: a3f1c8d42b70
Create Date: 2026-10-02 04:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7d2e9f14c05'
down_revision: str | Sequence[str] | None = 'a3f1c8d42b70'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('google_id', sa.String(length=255), nullable=True))
    op.create_index('ix_users_google_id', 'users', ['google_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_users_google_id', table_name='users')
    op.drop_column('users', 'google_id')
