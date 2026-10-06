"""add M3 collaboration & ecosystem: automation rules, releases, comments
threading + reactions, activity feed, notification mutes, API tokens/service
accounts/OAuth apps, integrations

Revision ID: b8f4d2e6a9c1
Revises: e5a7c9d1b3f4
Create Date: 2026-10-06 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8f4d2e6a9c1'
down_revision: str | Sequence[str] | None = 'e5a7c9d1b3f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- users: service-account shadow users --------------------------------
    op.add_column(
        'users',
        sa.Column('is_service_account', sa.Boolean(), server_default='false', nullable=False),
    )

    # --- comments: threading ------------------------------------------------
    op.add_column('comments', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.add_column('comments', sa.Column('root_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_comments_parent_id', 'comments', 'comments', ['parent_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_comments_root_id', 'comments', 'comments', ['root_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_comments_task_root', 'comments', ['task_id', 'root_id', 'created_at'])

    # --- notifications: grouping pointers -----------------------------------
    op.add_column('notifications', sa.Column('project_id', sa.Uuid(), nullable=True))
    op.add_column('notifications', sa.Column('task_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_notifications_project_id',
        'notifications',
        'projects',
        ['project_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_notifications_task_id', 'notifications', 'tasks', ['task_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_notifications_project_id', 'notifications', ['project_id'])
    op.create_index('ix_notifications_task_id', 'notifications', ['task_id'])

    # --- releases -----------------------------------------------------------
    op.create_table(
        'releases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='planned', nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('release_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'name', name='uq_releases_project_name'),
    )
    op.create_index('ix_releases_organization_id', 'releases', ['organization_id'])
    op.create_index('ix_releases_project_id', 'releases', ['project_id'])
    op.create_index('ix_releases_project_date', 'releases', ['project_id', 'release_date'])

    op.add_column('tasks', sa.Column('release_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_release_id', 'tasks', 'releases', ['release_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_tasks_org_release', 'tasks', ['organization_id', 'release_id'])

    # --- comment reactions --------------------------------------------------
    op.create_table(
        'comment_reactions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('comment_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('emoji', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['comment_id'], ['comments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('comment_id', 'user_id', 'emoji', name='uq_comment_reaction'),
    )
    op.create_index('ix_comment_reactions_organization_id', 'comment_reactions', ['organization_id'])
    op.create_index('ix_comment_reactions_comment', 'comment_reactions', ['comment_id'])

    # --- activity feed ------------------------------------------------------
    op.create_table(
        'activities',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('verb', sa.String(length=32), nullable=False),
        sa.Column('summary', sa.String(length=255), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_activities_organization_id', 'activities', ['organization_id'])
    op.create_index('ix_activities_org_created', 'activities', ['organization_id', 'created_at'])
    op.create_index('ix_activities_project_created', 'activities', ['project_id', 'created_at'])
    op.create_index('ix_activities_task_created', 'activities', ['task_id', 'created_at'])

    # --- notification mutes -------------------------------------------------
    op.create_table(
        'notification_mutes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'project_id', name='uq_notification_mute'),
    )
    op.create_index('ix_notification_mutes_user', 'notification_mutes', ['user_id'])

    # --- automation rules + executions --------------------------------------
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('trigger_type', sa.String(length=32), nullable=False),
        sa.Column('trigger_config', sa.JSON(), nullable=True),
        sa.Column('conditions', sa.JSON(), nullable=True),
        sa.Column('actions', sa.JSON(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_automation_rules_organization_id', 'automation_rules', ['organization_id'])
    op.create_index('ix_automation_rules_project', 'automation_rules', ['project_id'])
    op.create_index(
        'ix_automation_rules_trigger', 'automation_rules', ['organization_id', 'trigger_type']
    )

    op.create_table(
        'automation_executions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('rule_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('trigger_event', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('actions_log', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rule_id'], ['automation_rules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_automation_executions_organization_id', 'automation_executions', ['organization_id'])
    op.create_index('ix_automation_executions_rule', 'automation_executions', ['rule_id', 'created_at'])
    op.create_index('ix_automation_executions_org', 'automation_executions', ['organization_id', 'created_at'])

    # --- integrations -------------------------------------------------------
    op.create_table(
        'integrations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('secret', sa.String(length=128), nullable=True),
        sa.Column('events', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'provider', 'name', name='uq_integration_name'),
    )
    op.create_index('ix_integrations_organization_id', 'integrations', ['organization_id'])
    op.create_index('ix_integrations_org_provider', 'integrations', ['organization_id', 'provider'])

    op.create_table(
        'integration_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('integration_id', sa.Uuid(), nullable=False),
        sa.Column('direction', sa.String(length=8), server_default='inbound', nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='received', nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_integration_events_organization_id', 'integration_events', ['organization_id'])
    op.create_index('ix_integration_events_integration', 'integration_events', ['integration_id', 'created_at'])
    op.create_index('ix_integration_events_org', 'integration_events', ['organization_id', 'created_at'])

    # --- API tokens / service accounts / OAuth apps -------------------------
    op.create_table(
        'service_accounts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_service_accounts_organization_id', 'service_accounts', ['organization_id'])
    op.create_index('ix_service_accounts_org', 'service_accounts', ['organization_id'])

    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('service_account_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('token_prefix', sa.String(length=24), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('rate_limit_per_minute', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('usage_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_account_id'], ['service_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_api_tokens_organization_id', 'api_tokens', ['organization_id'])
    op.create_index('ix_api_tokens_user_id', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_org', 'api_tokens', ['organization_id'])
    op.create_index('ix_api_tokens_user', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_token_hash', 'api_tokens', ['token_hash'])

    op.create_table(
        'oauth_apps',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('client_secret_hash', sa.String(length=64), nullable=False),
        sa.Column('redirect_uris', sa.JSON(), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id'),
    )
    op.create_index('ix_oauth_apps_organization_id', 'oauth_apps', ['organization_id'])
    op.create_index('ix_oauth_apps_org', 'oauth_apps', ['organization_id'])
    op.create_index('ix_oauth_apps_client_id', 'oauth_apps', ['client_id'])

    op.create_table(
        'oauth_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('app_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['app_id'], ['oauth_apps.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_oauth_tokens_organization_id', 'oauth_tokens', ['organization_id'])
    op.create_index('ix_oauth_tokens_app', 'oauth_tokens', ['app_id'])
    op.create_index('ix_oauth_tokens_token_hash', 'oauth_tokens', ['token_hash'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('oauth_tokens')
    op.drop_table('oauth_apps')
    op.drop_table('api_tokens')
    op.drop_table('service_accounts')
    op.drop_table('integration_events')
    op.drop_table('integrations')
    op.drop_table('automation_executions')
    op.drop_table('automation_rules')
    op.drop_table('notification_mutes')
    op.drop_table('activities')
    op.drop_table('comment_reactions')

    op.drop_index('ix_tasks_org_release', table_name='tasks')
    op.drop_constraint('fk_tasks_release_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'release_id')
    op.drop_table('releases')

    op.drop_index('ix_notifications_task_id', table_name='notifications')
    op.drop_index('ix_notifications_project_id', table_name='notifications')
    op.drop_constraint('fk_notifications_task_id', 'notifications', type_='foreignkey')
    op.drop_constraint('fk_notifications_project_id', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'task_id')
    op.drop_column('notifications', 'project_id')

    op.drop_index('ix_comments_task_root', table_name='comments')
    op.drop_constraint('fk_comments_root_id', 'comments', type_='foreignkey')
    op.drop_constraint('fk_comments_parent_id', 'comments', type_='foreignkey')
    op.drop_column('comments', 'root_id')
    op.drop_column('comments', 'parent_id')

    op.drop_column('users', 'is_service_account')
