"""add M1 agile MVP: issue keys, estimates, sprints, saved filters, notification prefs, search

Revision ID: c9f31a7d5e21
Revises: b7d2e9f14c05
Create Date: 2026-10-06 05:30:00.000000

"""
import re
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9f31a7d5e21'
down_revision: str | Sequence[str] | None = 'b7d2e9f14c05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _derive_key(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    base = letters[:4] or "PRJ"
    if base[0].isdigit():
        base = f"P{base}"[:4]
    return base


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # --- projects: issue key + counter + estimation unit -------------------
    op.add_column('projects', sa.Column('key', sa.String(length=16), nullable=True))
    op.add_column(
        'projects',
        sa.Column('issue_counter', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'projects',
        sa.Column(
            'estimation_unit', sa.String(length=16), server_default='points', nullable=False
        ),
    )
    op.create_unique_constraint('uq_projects_org_key', 'projects', ['organization_id', 'key'])

    # --- sprints ------------------------------------------------------------
    op.create_table(
        'sprints',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_sprints_org_project_state',
        'sprints',
        ['organization_id', 'project_id', 'state'],
    )
    op.create_index('ix_sprints_organization_id', 'sprints', ['organization_id'])
    op.create_index('ix_sprints_project_id', 'sprints', ['project_id'])
    op.create_index(
        'uq_sprints_one_active',
        'sprints',
        ['project_id'],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # --- tasks: issue numbers, estimates, sprint, backlog rank, archive ----
    op.add_column('tasks', sa.Column('key', sa.String(length=32), nullable=True))
    op.add_column('tasks', sa.Column('number', sa.Integer(), nullable=True))
    op.add_column('tasks', sa.Column('estimate', sa.Float(), nullable=True))
    op.add_column('tasks', sa.Column('remaining_estimate', sa.Float(), nullable=True))
    op.add_column('tasks', sa.Column('actual_estimate', sa.Float(), nullable=True))
    op.add_column('tasks', sa.Column('backlog_rank', sa.Float(), nullable=True))
    op.add_column('tasks', sa.Column('sprint_id', sa.Uuid(), nullable=True))
    op.add_column(
        'tasks', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_tasks_sprint_id_sprints',
        'tasks',
        'sprints',
        ['sprint_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_tasks_project_number', 'tasks', ['project_id', 'number'])
    op.create_index('ix_tasks_org_sprint', 'tasks', ['organization_id', 'sprint_id'])
    op.create_index('ix_tasks_org_archived', 'tasks', ['organization_id', 'archived_at'])

    # --- saved filters ------------------------------------------------------
    op.create_table(
        'saved_filters',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('is_shared', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'owner_id', 'organization_id', 'project_id', 'name',
            name='uq_saved_filter_owner_name',
        ),
    )
    op.create_index('ix_saved_filters_organization_id', 'saved_filters', ['organization_id'])
    op.create_index('ix_saved_filters_owner_id', 'saved_filters', ['owner_id'])
    op.create_index(
        'ix_saved_filters_org_project', 'saved_filters', ['organization_id', 'project_id']
    )

    # --- notification preferences ------------------------------------------
    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('email_enabled', sa.Boolean(), nullable=False),
        sa.Column('assigned', sa.Boolean(), nullable=False),
        sa.Column('mentioned', sa.Boolean(), nullable=False),
        sa.Column('comments', sa.Boolean(), nullable=False),
        sa.Column('due', sa.Boolean(), nullable=False),
        sa.Column('digest', sa.String(length=16), nullable=False),
        sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('unsubscribe_token'),
    )
    op.create_index(
        'ix_notification_preferences_user_id', 'notification_preferences', ['user_id']
    )
    op.create_index(
        'ix_notification_preferences_unsubscribe_token',
        'notification_preferences',
        ['unsubscribe_token'],
    )

    # --- backfill issue keys/numbers + backlog rank -------------------------
    projects = bind.execute(
        sa.text("SELECT id, organization_id, name FROM projects ORDER BY created_at")
    ).fetchall()
    used_keys: dict[uuid.UUID, set[str]] = {}
    for project_id, organization_id, name in projects:
        used = used_keys.setdefault(organization_id, set())
        base = _derive_key(name or "")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base[:2]}{suffix}"
            suffix += 1
        used.add(candidate)

        rows = bind.execute(
            sa.text(
                "SELECT id FROM tasks WHERE project_id = :pid "
                "ORDER BY created_at, id"
            ),
            {"pid": project_id},
        ).fetchall()
        for offset, (task_id,) in enumerate(rows, start=1):
            bind.execute(
                sa.text(
                    "UPDATE tasks SET number = :n, key = :key, "
                    "backlog_rank = COALESCE(backlog_rank, :rank) WHERE id = :tid"
                ),
                {
                    "n": offset,
                    "key": f"{candidate}-{offset}",
                    "rank": float(offset),
                    "tid": task_id,
                },
            )
        bind.execute(
            sa.text("UPDATE projects SET key = :key, issue_counter = :n WHERE id = :pid"),
            {"key": candidate, "n": len(rows), "pid": project_id},
        )
    # Defensive pass: any project still without a key goes through the same
    # per-org dedup as above, otherwise the uq_projects_org_key constraint
    # could abort the migration with duplicate/empty keys.
    remaining = bind.execute(
        sa.text(
            "SELECT id, organization_id, name FROM projects "
            "WHERE key IS NULL ORDER BY created_at"
        )
    ).fetchall()
    for project_id, organization_id, name in remaining:
        used = used_keys.setdefault(organization_id, set())
        base = _derive_key(name or "")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base[:2]}{suffix}"
            suffix += 1
        used.add(candidate)
        bind.execute(
            sa.text("UPDATE projects SET key = :key WHERE id = :pid"),
            {"key": candidate, "pid": project_id},
        )

    # --- full-text search indexes (expression GIN) --------------------------
    op.create_index(
        'ix_tasks_search_vector',
        'tasks',
        [sa.text("to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))")],
        postgresql_using='gin',
    )
    op.create_index(
        'ix_comments_search_vector',
        'comments',
        [sa.text("to_tsvector('english', coalesce(body,''))")],
        postgresql_using='gin',
    )
    op.create_index(
        'ix_projects_search_vector',
        'projects',
        [sa.text("to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,''))")],
        postgresql_using='gin',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_projects_search_vector', table_name='projects')
    op.drop_index('ix_comments_search_vector', table_name='comments')
    op.drop_index('ix_tasks_search_vector', table_name='tasks')

    op.drop_table('notification_preferences')
    op.drop_table('saved_filters')

    op.drop_index('ix_tasks_org_archived', table_name='tasks')
    op.drop_index('ix_tasks_org_sprint', table_name='tasks')
    op.drop_constraint('uq_tasks_project_number', 'tasks', type_='unique')
    op.drop_constraint('fk_tasks_sprint_id_sprints', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'archived_at')
    op.drop_column('tasks', 'sprint_id')
    op.drop_column('tasks', 'backlog_rank')
    op.drop_column('tasks', 'actual_estimate')
    op.drop_column('tasks', 'remaining_estimate')
    op.drop_column('tasks', 'estimate')
    op.drop_column('tasks', 'number')
    op.drop_column('tasks', 'key')

    op.drop_index('uq_sprints_one_active', table_name='sprints')
    op.drop_index('ix_sprints_project_id', table_name='sprints')
    op.drop_index('ix_sprints_organization_id', table_name='sprints')
    op.drop_index('ix_sprints_org_project_state', table_name='sprints')
    op.drop_table('sprints')

    op.drop_constraint('uq_projects_org_key', 'projects', type_='unique')
    op.drop_column('projects', 'estimation_unit')
    op.drop_column('projects', 'issue_counter')
    op.drop_column('projects', 'key')
