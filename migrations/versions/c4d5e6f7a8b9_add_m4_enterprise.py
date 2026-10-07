"""add M4 enterprise: MFA, SSO/SCIM, goals, dashboards, forms, plugins,
push subscriptions, custom roles, project members + org/user/project settings

Revision ID: c4d5e6f7a8b9
Revises: b8f4d2e6a9c1
Create Date: 2026-10-07 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: str | Sequence[str] | None = 'b8f4d2e6a9c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _encrypt_existing(bind, table: str, column: str) -> None:
    """Encrypts legacy plaintext secrets in place (no-op on fresh schemas)."""
    from app.core.crypto import encrypt_secret

    rows = bind.execute(
        sa.text(
            f"SELECT id, {column} FROM {table} "
            f"WHERE {column} IS NOT NULL AND {column} NOT LIKE 'gAAAA%'"
        )
    ).fetchall()
    for row_id, value in rows:
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": encrypt_secret(value), "id": row_id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    # --- custom roles (referenced by memberships below) ---------------------
    op.create_table(
        'custom_roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_custom_role_name'),
    )
    op.create_index('ix_custom_roles_organization_id', 'custom_roles', ['organization_id'])

    # --- org / user / project settings columns ------------------------------
    op.add_column('organizations', sa.Column('accent_color', sa.String(length=16), nullable=True))
    op.add_column('organizations', sa.Column('audit_retention_days', sa.Integer(), nullable=True))
    # Invitations become stale after a while. Backfill pending rows with a
    # 14-day window from creation so old invites cannot be redeemed forever.
    op.add_column(
        'invitations',
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE invitations SET expires_at = created_at + interval '14 days' "
        "WHERE status = 'pending' AND expires_at IS NULL"
    )
    op.add_column(
        'users',
        sa.Column('locale', sa.String(length=8), server_default='en', nullable=False),
    )
    op.add_column(
        'projects',
        sa.Column('visibility', sa.String(length=16), server_default='workspace', nullable=False),
    )
    op.add_column('memberships', sa.Column('custom_role_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_memberships_custom_role',
        'memberships',
        'custom_roles',
        ['custom_role_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # --- MFA credentials ----------------------------------------------------
    op.create_table(
        'mfa_credentials',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        # Encrypted at rest (Fernet); TEXT because ciphertext is longer.
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('recovery_codes', sa.JSON(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_mfa_credentials_user_id', 'mfa_credentials', ['user_id'])

    # --- SSO configs + SCIM tokens ------------------------------------------
    op.create_table(
        'sso_configs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=16), server_default='oidc', nullable=False),
        sa.Column('issuer', sa.String(length=512), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('client_secret', sa.Text(), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('auto_provision', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('default_role', sa.String(length=16), server_default='member', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
    )
    op.create_index('ix_sso_configs_organization_id', 'sso_configs', ['organization_id'])

    op.create_table(
        'scim_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_scim_tokens_organization_id', 'scim_tokens', ['organization_id'])
    op.create_index('ix_scim_tokens_token_hash', 'scim_tokens', ['token_hash'])

    # Per-org binding of IdP subjects to users; SSO logins may only resolve
    # through a row here, never through a global email lookup.
    op.create_table(
        'sso_identities',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('issuer', sa.String(length=512), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id', 'issuer', 'subject',
            name='uq_sso_identity_org_issuer_subject',
        ),
    )
    op.create_index('ix_sso_identities_organization_id', 'sso_identities', ['organization_id'])
    op.create_index('ix_sso_identities_user_id', 'sso_identities', ['user_id'])
    op.create_index('ix_sso_identities_org_user', 'sso_identities', ['organization_id', 'user_id'])

    # Automated provisioning must never grant ownership.
    op.execute("UPDATE sso_configs SET default_role = 'member' WHERE default_role = 'owner'")
    op.create_index('ix_scim_tokens_org', 'scim_tokens', ['organization_id'])

    # --- goals + task links -------------------------------------------------
    op.create_table(
        'goals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='active', nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_goals_organization_id', 'goals', ['organization_id'])
    op.create_index('ix_goals_org_status', 'goals', ['organization_id', 'status'])

    op.create_table(
        'goal_links',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('goal_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('goal_id', 'task_id', name='uq_goal_link'),
    )
    op.create_index('ix_goal_links_task', 'goal_links', ['task_id'])

    # --- dashboards ---------------------------------------------------------
    op.create_table(
        'dashboards',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('widgets', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_dashboard_name'),
    )
    op.create_index('ix_dashboards_organization_id', 'dashboards', ['organization_id'])

    # --- forms + submissions ------------------------------------------------
    op.create_table(
        'forms',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=False),
        sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('submit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_forms_organization_id', 'forms', ['organization_id'])
    op.create_index('ix_forms_project_id', 'forms', ['project_id'])
    op.create_index('ix_forms_slug', 'forms', ['slug'])

    op.create_table(
        'form_submissions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('form_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_submissions_organization_id', 'form_submissions', ['organization_id'])
    op.create_index('ix_form_submissions_form_id', 'form_submissions', ['form_id'])
    op.create_index(
        'ix_form_submissions_form_created', 'form_submissions', ['form_id', 'created_at']
    )

    # --- plugins ------------------------------------------------------------
    op.create_table(
        'plugins',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('manifest', sa.JSON(), nullable=False),
        sa.Column('webhook_url', sa.String(length=512), nullable=True),
        sa.Column('events', sa.JSON(), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('secret', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('installed_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['installed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_plugin_name'),
    )
    op.create_index('ix_plugins_organization_id', 'plugins', ['organization_id'])

    # --- web push subscriptions ---------------------------------------------
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('endpoint', sa.String(length=512), nullable=False),
        sa.Column('keys', sa.JSON(), nullable=False),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index('ix_push_subscriptions_user_id', 'push_subscriptions', ['user_id'])
    op.create_index('ix_push_subscriptions_endpoint', 'push_subscriptions', ['endpoint'])

    # --- per-project membership ---------------------------------------------
    op.create_table(
        'project_members',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(length=16), server_default='member', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),
    )
    op.create_index('ix_project_members_organization_id', 'project_members', ['organization_id'])
    op.create_index('ix_project_members_project_id', 'project_members', ['project_id'])
    op.create_index('ix_project_members_user_id', 'project_members', ['user_id'])

    # Encrypt any legacy plaintext secrets now that the columns are TEXT.
    bind = op.get_bind()
    _encrypt_existing(bind, 'mfa_credentials', 'secret')
    _encrypt_existing(bind, 'sso_configs', 'client_secret')
    _encrypt_existing(bind, 'plugins', 'secret')
    # Integrations predate this migration; encrypt rows from databases that
    # were already at b8f4d2e6a9c1 before the encryption change.
    _encrypt_existing(bind, 'integrations', 'secret')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('project_members')
    op.drop_table('push_subscriptions')
    op.drop_table('plugins')
    op.drop_table('form_submissions')
    op.drop_table('forms')
    op.drop_table('dashboards')
    op.drop_table('goal_links')
    op.drop_table('goals')
    op.drop_table('sso_identities')
    op.drop_table('scim_tokens')
    op.drop_table('sso_configs')
    op.drop_table('mfa_credentials')

    op.drop_constraint('fk_memberships_custom_role', 'memberships', type_='foreignkey')
    op.drop_column('memberships', 'custom_role_id')
    op.drop_column('projects', 'visibility')
    op.drop_column('users', 'locale')
    op.drop_column('organizations', 'audit_retention_days')
    op.drop_column('organizations', 'accent_color')
    op.drop_column('invitations', 'expires_at')

    op.drop_table('custom_roles')
