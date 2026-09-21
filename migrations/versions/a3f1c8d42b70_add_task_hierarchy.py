"""add task hierarchy (type + parent_id)

Revision ID: a3f1c8d42b70
Revises: f699cd23df0b
Create Date: 2026-09-21 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f1c8d42b70'
down_revision: str | Sequence[str] | None = 'f699cd23df0b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows are backfilled with the default 'task' level.
    op.add_column(
        'tasks',
        sa.Column('type', sa.String(length=16), server_default='task', nullable=False),
    )
    op.add_column('tasks', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_parent_id_tasks',
        'tasks',
        'tasks',
        ['parent_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_tasks_org_parent', 'tasks', ['organization_id', 'parent_id'], unique=False
    )
    op.create_index('ix_tasks_org_type', 'tasks', ['organization_id', 'type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tasks_org_type', table_name='tasks')
    op.drop_index('ix_tasks_org_parent', table_name='tasks')
    op.drop_constraint('fk_tasks_parent_id_tasks', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'parent_id')
    op.drop_column('tasks', 'type')
