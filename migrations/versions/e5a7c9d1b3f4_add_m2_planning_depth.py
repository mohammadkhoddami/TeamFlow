"""add M2 planning depth: workflows/boards, custom fields, links, reports
history, worklogs, capacity, templates, checklists, multi-assignees, recurrence

Revision ID: e5a7c9d1b3f4
Revises: c9f31a7d5e21
Create Date: 2026-10-06 08:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a7c9d1b3f4'
down_revision: str | Sequence[str] | None = 'c9f31a7d5e21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- projects: WIP enforcement flag ------------------------------------
    op.add_column(
        'projects',
        sa.Column('wip_enforced', sa.Boolean(), server_default='false', nullable=False),
    )

    # --- tasks: status category, recurrence --------------------------------
    op.alter_column('tasks', 'status', existing_type=sa.String(length=16), type_=sa.String(length=32))
    op.add_column(
        'tasks',
        sa.Column('status_category', sa.String(length=16), server_default='todo', nullable=False),
    )
    op.add_column('tasks', sa.Column('recurrence_rule', sa.String(length=255), nullable=True))
    op.add_column('tasks', sa.Column('recurrence_source_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_recurrence_source',
        'tasks',
        'tasks',
        ['recurrence_source_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_tasks_org_category', 'tasks', ['organization_id', 'status_category'])
    op.create_index('ix_tasks_org_recurrence', 'tasks', ['organization_id', 'recurrence_rule'])
    # Legacy statuses are exactly the four canonical categories.
    op.execute("UPDATE tasks SET status_category = status")

    # --- workflow statuses + boards ----------------------------------------
    op.create_table(
        'workflow_statuses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=16), nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('wip_limit', sa.Integer(), nullable=True),
        sa.Column('transitions', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'key', name='uq_workflow_status_project_key'),
    )
    op.create_index('ix_workflow_statuses_organization_id', 'workflow_statuses', ['organization_id'])
    op.create_index('ix_workflow_statuses_project_id', 'workflow_statuses', ['project_id'])
    op.create_index(
        'ix_workflow_statuses_project_position', 'workflow_statuses', ['project_id', 'position']
    )

    op.create_table(
        'boards',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('swimlane_by', sa.String(length=16), server_default='none', nullable=False),
        sa.Column('filter_query', sa.Text(), nullable=True),
        sa.Column('columns', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'name', name='uq_boards_project_name'),
    )
    op.create_index('ix_boards_organization_id', 'boards', ['organization_id'])
    op.create_index('ix_boards_project', 'boards', ['project_id'])

    # --- custom fields ------------------------------------------------------
    op.create_table(
        'custom_fields',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=32), nullable=False),
        sa.Column('field_type', sa.String(length=16), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'key', name='uq_custom_field_project_key'),
    )
    op.create_index('ix_custom_fields_organization_id', 'custom_fields', ['organization_id'])
    op.create_index('ix_custom_fields_project_id', 'custom_fields', ['project_id'])
    op.create_index('ix_custom_fields_project_position', 'custom_fields', ['project_id', 'position'])

    op.create_table(
        'custom_field_values',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('field_id', sa.Uuid(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['field_id'], ['custom_fields.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'field_id', name='uq_custom_value_task_field'),
    )
    op.create_index('ix_custom_field_values_task_id', 'custom_field_values', ['task_id'])
    op.create_index('ix_custom_values_org_field', 'custom_field_values', ['organization_id', 'field_id'])

    # --- task links + status history ---------------------------------------
    op.create_table(
        'task_links',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('from_task_id', sa.Uuid(), nullable=False),
        sa.Column('to_task_id', sa.Uuid(), nullable=False),
        sa.Column('link_type', sa.String(length=16), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_task_id', 'to_task_id', 'link_type', name='uq_task_link'),
    )
    op.create_index('ix_task_links_organization_id', 'task_links', ['organization_id'])
    op.create_index('ix_task_links_from', 'task_links', ['from_task_id'])
    op.create_index('ix_task_links_to', 'task_links', ['to_task_id'])

    op.create_table(
        'task_status_history',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('from_status', sa.String(length=32), nullable=False),
        sa.Column('to_status', sa.String(length=32), nullable=False),
        sa.Column('from_category', sa.String(length=16), nullable=False),
        sa.Column('to_category', sa.String(length=16), nullable=False),
        sa.Column('changed_by_id', sa.Uuid(), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_status_history_task_changed', 'task_status_history', ['task_id', 'changed_at'])
    op.create_index('ix_task_status_history_org_changed', 'task_status_history', ['organization_id', 'changed_at'])

    # --- worklogs -----------------------------------------------------------
    op.create_table(
        'worklogs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('minutes', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_worklogs_task_started', 'worklogs', ['task_id', 'started_at'])
    op.create_index('ix_worklogs_org_started', 'worklogs', ['organization_id', 'started_at'])
    op.create_index('ix_worklogs_user_started', 'worklogs', ['user_id', 'started_at'])

    # --- sprint capacities --------------------------------------------------
    op.create_table(
        'sprint_capacities',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('sprint_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('capacity', sa.Float(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sprint_id', 'user_id', name='uq_sprint_capacity_member'),
    )
    op.create_index('ix_sprint_capacities_organization_id', 'sprint_capacities', ['organization_id'])
    op.create_index('ix_sprint_capacities_sprint', 'sprint_capacities', ['sprint_id'])

    # --- templates ----------------------------------------------------------
    op.create_table(
        'project_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_project_template_name'),
    )
    op.create_index('ix_project_templates_organization_id', 'project_templates', ['organization_id'])

    op.create_table(
        'task_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('estimate', sa.Float(), nullable=True),
        sa.Column('label_ids', sa.JSON(), nullable=False),
        sa.Column('checklist', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_task_template_name'),
    )
    op.create_index('ix_task_templates_organization_id', 'task_templates', ['organization_id'])

    # --- multiple assignees + checklists ------------------------------------
    op.create_table(
        'task_assignees',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'user_id', name='uq_task_assignee'),
    )
    op.create_index('ix_task_assignees_task_id', 'task_assignees', ['task_id'])
    op.create_index('ix_task_assignees_user', 'task_assignees', ['user_id'])

    op.create_table(
        'checklist_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('is_done', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_checklist_items_task_position', 'checklist_items', ['task_id', 'position'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('checklist_items')
    op.drop_table('task_assignees')
    op.drop_table('task_templates')
    op.drop_table('project_templates')
    op.drop_table('sprint_capacities')
    op.drop_table('worklogs')
    op.drop_table('task_status_history')
    op.drop_table('task_links')
    op.drop_table('custom_field_values')
    op.drop_table('custom_fields')
    op.drop_table('boards')
    op.drop_table('workflow_statuses')

    op.drop_index('ix_tasks_org_recurrence', table_name='tasks')
    op.drop_index('ix_tasks_org_category', table_name='tasks')
    op.drop_constraint('fk_tasks_recurrence_source', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'recurrence_source_id')
    op.drop_column('tasks', 'recurrence_rule')
    op.drop_column('tasks', 'status_category')
    op.alter_column('tasks', 'status', existing_type=sa.String(length=32), type_=sa.String(length=16))

    op.drop_column('projects', 'wip_enforced')
