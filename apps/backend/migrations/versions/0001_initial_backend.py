"""Initial mutable Backend Alembic baseline.

This revision intentionally represents the full pre-release Backend schema.
Edit/squash it until the first production deployment adopts Alembic.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_backend"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('platform_profile_prompt_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('profile', sa.String(length=100), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revision_number > 0', name='ck_platform_profile_prompt_revision_number'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile', 'revision_number', name='uq_platform_profile_prompt_revision')
    )

    op.create_table('platform_profile_prompt_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('profile', sa.String(length=100), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile', name='uq_platform_profile_prompt_draft')
    )

    op.create_table('platform_runtime_component_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_platform_runtime_draft_one'),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('platform_runtime_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revision_number > 0', name='ck_platform_runtime_revision_number'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('revision_number', name='uq_platform_runtime_revision_number')
    )

    op.create_table('platform_system_prompt_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revision_number > 0', name='ck_platform_system_prompt_revision_number'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('revision_number', name='uq_platform_system_prompt_revision_number')
    )

    op.create_table('platform_system_prompt_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_platform_system_prompt_draft_one'),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('platform_telephony',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('inbound_trunk_id', sa.String(length=255), nullable=True),
    sa.Column('outbound_trunk_id', sa.String(length=255), nullable=True),
    sa.Column('dispatch_rule_id', sa.String(length=255), nullable=True),
    sa.Column('provisioning_status', sa.Enum('pending', 'ready', 'degraded', 'error', name='telephony_provisioning_status'), server_default='pending', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_reconciled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_platform_telephony_singleton'),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('tenants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=63), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('business_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('active', 'suspended', 'archived', name='tenant_status'), server_default='active', nullable=False),
    sa.Column('active_release_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['id', 'active_release_id'], ['tenant_releases.tenant_id', 'tenant_releases.id'], name='fk_tenants_active_release_same_tenant', use_alter=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )

    op.create_table('integration_connections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.Enum('google_sheets', 'http', name='integration_kind'), nullable=False),
    sa.Column('configuration', sa.JSON(), nullable=False),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_integration_connections_tenant_id_tenants'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_integration_connections_tenant_id_id'),
    sa.UniqueConstraint('tenant_id', 'key', name='uq_integration_connections_tenant_key')
    )

    op.create_table('knowledge_bases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_knowledge_bases_tenant_id_id'),
    sa.UniqueConstraint('tenant_id', name='uq_knowledge_bases_tenant')
    )

    op.create_table('platform_releases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('release_number', sa.Integer(), nullable=False),
    sa.Column('runtime_revision_id', sa.Uuid(), nullable=False),
    sa.Column('system_prompt_revision_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['runtime_revision_id'], ['platform_runtime_component_revisions.id'], ),
    sa.ForeignKeyConstraint(['system_prompt_revision_id'], ['platform_system_prompt_component_revisions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_number', name='uq_platform_release_number')
    )

    op.create_table('runtime_bundles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('compiler_build_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name='ck_runtime_bundles_content_hash'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'content_hash', name='uq_runtime_bundles_tenant_hash'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_runtime_bundles_tenant_id')
    )

    op.create_table('tenant_agent_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_agent_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_agent_drafts_tenant')
    )

    op.create_table('tenant_agent_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_agent_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_agent_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_agent_revisions_number')
    )

    op.create_table('tenant_capabilities_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_capabilities_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_capabilities_drafts_tenant')
    )

    op.create_table('tenant_capabilities_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_capabilities_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_capabilities_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_capabilities_revisions_number')
    )

    op.create_table('tenant_knowledge_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_knowledge_component_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_knowledge_component_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_knowledge_component_revisions_number')
    )

    op.create_table('tenant_knowledge_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_knowledge_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_knowledge_drafts_tenant')
    )

    op.create_table('tenant_post_call_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_post_call_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_post_call_drafts_tenant')
    )

    op.create_table('tenant_post_call_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_post_call_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_post_call_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_post_call_revisions_number')
    )

    op.create_table('tenant_prompt_component_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_prompt_component_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_prompt_component_drafts_tenant')
    )

    op.create_table('tenant_prompt_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_prompt_component_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_prompt_component_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_prompt_component_revisions_number')
    )

    op.create_table('tenant_runtime_component_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_runtime_component_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_runtime_component_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_runtime_component_revisions_number')
    )

    op.create_table('tenant_runtime_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_runtime_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_runtime_drafts_tenant')
    )

    op.create_table('tenant_telephony_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('version > 0', name='ck_tenant_telephony_drafts_version_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_tenant_telephony_drafts_tenant')
    )

    op.create_table('tenant_telephony_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sealed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('revision_number > 0', name='ck_tenant_telephony_revisions_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_telephony_revisions_id'),
    sa.UniqueConstraint('tenant_id', 'revision_number', name='uq_tenant_telephony_revisions_number')
    )

    op.create_table('active_phone_claims',
    sa.Column('normalized_phone_number', sa.String(length=16), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('active_telephony_revision_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("normalized_phone_number ~ '^\\+[1-9][0-9]{1,14}$'", name='ck_active_phone_claims_e164'),
    sa.ForeignKeyConstraint(['tenant_id', 'active_telephony_revision_id'], ['tenant_telephony_revisions.tenant_id', 'tenant_telephony_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('normalized_phone_number'),
    sa.UniqueConstraint('tenant_id', name='uq_active_phone_claims_tenant')
    )

    op.create_table('integration_credentials',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('integration_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('active', 'retired', 'revoked', name='integration_credential_status'), server_default='active', nullable=False),
    sa.Column('nonce', sa.LargeBinary(), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id', 'integration_id'], ['integration_connections.tenant_id', 'integration_connections.id'], name='fk_integration_credentials_tenant_connection', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('integration_id', 'version', name='uq_integration_credentials_version')
    )

    op.create_table('knowledge_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('knowledge_base_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'knowledge_base_id'], ['knowledge_bases.tenant_id', 'knowledge_bases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('knowledge_base_id', 'key'),
    sa.UniqueConstraint('tenant_id', 'knowledge_base_id', 'id', name='uq_knowledge_documents_tenant_base_id')
    )

    op.create_table('platform_control',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('active_release_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint('id = 1', name='ck_platform_control_one'),
    sa.ForeignKeyConstraint(['active_release_id'], ['platform_releases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('platform_release_profile_prompts',
    sa.Column('release_id', sa.Uuid(), nullable=False),
    sa.Column('profile', sa.String(length=100), nullable=False),
    sa.Column('profile_prompt_revision_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['profile_prompt_revision_id'], ['platform_profile_prompt_component_revisions.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['platform_releases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('release_id', 'profile'),
    sa.UniqueConstraint('release_id', 'profile', name='uq_platform_release_profile')
    )

    op.create_table('tenant_releases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('release_number', sa.Integer(), nullable=False),
    sa.Column('runtime_revision_id', sa.Uuid(), nullable=False),
    sa.Column('agent_revision_id', sa.Uuid(), nullable=False),
    sa.Column('prompt_revision_id', sa.Uuid(), nullable=False),
    sa.Column('knowledge_revision_id', sa.Uuid(), nullable=False),
    sa.Column('capabilities_revision_id', sa.Uuid(), nullable=False),
    sa.Column('post_call_revision_id', sa.Uuid(), nullable=False),
    sa.Column('telephony_revision_id', sa.Uuid(), nullable=False),
    sa.Column('runtime_bundle_id', sa.Uuid(), nullable=False),
    sa.Column('source_release_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint('release_number > 0', name='ck_tenant_releases_number_positive'),
    sa.ForeignKeyConstraint(['source_release_id'], ['tenant_releases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'agent_revision_id'], ['tenant_agent_revisions.tenant_id', 'tenant_agent_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'capabilities_revision_id'], ['tenant_capabilities_revisions.tenant_id', 'tenant_capabilities_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'knowledge_revision_id'], ['tenant_knowledge_component_revisions.tenant_id', 'tenant_knowledge_component_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'post_call_revision_id'], ['tenant_post_call_revisions.tenant_id', 'tenant_post_call_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'prompt_revision_id'], ['tenant_prompt_component_revisions.tenant_id', 'tenant_prompt_component_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'runtime_bundle_id'], ['runtime_bundles.tenant_id', 'runtime_bundles.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'runtime_revision_id'], ['tenant_runtime_component_revisions.tenant_id', 'tenant_runtime_component_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'telephony_revision_id'], ['tenant_telephony_revisions.tenant_id', 'tenant_telephony_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', 'runtime_bundle_id', name='uq_tenant_releases_bundle'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tenant_releases_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'release_number', name='uq_tenant_releases_number')
    )

    op.create_table('tenant_telephony_provisioning',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('desired_revision_id', sa.Uuid(), nullable=False),
    sa.Column('applied_revision_id', sa.Uuid(), nullable=True),
    sa.Column('applied_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_reconciled_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id', 'applied_revision_id'], ['tenant_telephony_revisions.tenant_id', 'tenant_telephony_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id', 'desired_revision_id'], ['tenant_telephony_revisions.tenant_id', 'tenant_telephony_revisions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tenant_id')
    )

    op.create_table('call_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_release_id', sa.Uuid(), nullable=False),
    sa.Column('runtime_bundle_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Enum('sip', 'web', name='call_channel'), nullable=False),
    sa.Column('direction', sa.Enum('inbound', name='call_direction'), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('provider_call_id', sa.String(length=255), nullable=False),
    sa.Column('caller_phone_e164', sa.String(length=32), nullable=True),
    sa.Column('called_phone_e164', sa.String(length=32), nullable=True),
    sa.Column('caller_phone_raw', sa.String(length=64), nullable=True),
    sa.Column('called_phone_raw', sa.String(length=64), nullable=True),
    sa.Column('sip_call_id', sa.String(length=255), nullable=True),
    sa.Column('sip_call_id_full', sa.String(length=255), nullable=True),
    sa.Column('sip_trunk_id', sa.String(length=255), nullable=True),
    sa.Column('sip_dispatch_rule_id', sa.String(length=255), nullable=True),
    sa.Column('livekit_participant_identity', sa.String(length=255), nullable=True),
    sa.Column('provider_dispatch_id', sa.String(length=255), nullable=True),
    sa.Column('admin_idempotency_key', sa.String(length=255), nullable=True),
    sa.Column('admin_request_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('handoff_tool_call_id', sa.String(length=255), nullable=True),
    sa.Column('handoff_destination', sa.String(length=64), nullable=True),
    sa.Column('handoff_participant_identity', sa.String(length=255), nullable=True),
    sa.Column('handoff_sip_call_id', sa.String(length=255), nullable=True),
    sa.Column('room_name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('created', 'started', 'connected', 'ended', 'failed', name='call_session_status'), server_default='created', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.CheckConstraint("\n            (status = 'created' AND started_at IS NULL AND ended_at IS NULL\n                AND failure_reason IS NULL)\n            OR (status = 'started' AND started_at IS NOT NULL\n                AND connected_at IS NULL AND ended_at IS NULL\n                AND failure_reason IS NULL)\n            OR (status = 'connected' AND started_at IS NOT NULL\n                AND connected_at IS NOT NULL AND ended_at IS NULL\n                AND failure_reason IS NULL)\n            OR (status = 'ended' AND started_at IS NOT NULL\n                AND connected_at IS NOT NULL\n                AND ended_at IS NOT NULL AND failure_reason IS NULL)\n            OR (status = 'failed' AND ended_at IS NOT NULL\n                AND failure_reason IS NOT NULL)\n            ", name='ck_call_sessions_lifecycle_fields'),
    sa.ForeignKeyConstraint(['tenant_id', 'tenant_release_id', 'runtime_bundle_id'], ['tenant_releases.tenant_id', 'tenant_releases.id', 'tenant_releases.runtime_bundle_id'], name='fk_call_sessions_release_bundle_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_call_sessions_tenant_id_tenants'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('admin_idempotency_key', name='uq_call_sessions_admin_idempotency_key'),
    sa.UniqueConstraint('provider', 'provider_call_id', name='uq_call_sessions_provider_call_id'),
    sa.UniqueConstraint('provider', 'provider_dispatch_id', name='uq_call_sessions_provider_dispatch_id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_call_sessions_tenant_id_id')
    )

    op.create_table('knowledge_document_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('knowledge_document_id', sa.Uuid(), nullable=False),
    sa.Column('knowledge_base_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('media_type', sa.String(length=100), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'knowledge_base_id', 'knowledge_document_id'], ['knowledge_documents.tenant_id', 'knowledge_documents.knowledge_base_id', 'knowledge_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('knowledge_document_id', 'revision_number')
    )

    op.create_table('artifact_representations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('artifact_type', sa.String(length=64), nullable=False),
    sa.Column('representation', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='post_call_work_status'), server_default='processing', nullable=False),
    sa.Column('command_id', sa.Uuid(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=True),
    sa.Column('content_type', sa.String(length=255), nullable=True),
    sa.Column('byte_size', sa.Integer(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('last_error', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(artifact_type = 'transcript' AND representation = 'plain_text') OR (artifact_type = 'call_recording' AND representation = 'base64_text')", name='ck_artifact_representations_materializable_kind'),
    sa.CheckConstraint("(status = 'completed' AND byte_size IS NOT NULL AND completed_at IS NOT NULL AND ((artifact_type = 'call_recording' AND content IS NULL) OR (content IS NOT NULL AND sha256 IS NOT NULL))) OR (status <> 'completed')", name='ck_artifact_representations_completed_content'),
    sa.ForeignKeyConstraint(['tenant_id', 'call_id'], ['call_sessions.tenant_id', 'call_sessions.id'], name='fk_artifact_representations_call_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id', 'artifact_type', 'representation', name='uq_artifact_representations_call_kind'),
    sa.UniqueConstraint('command_id', name='uq_artifact_representations_command_id')
    )

    op.create_table('call_finalizations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='call_finalization_status'), server_default='pending', nullable=False),
    sa.Column('summary_command_id', sa.Uuid(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('last_error', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['call_id'], ['call_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id')
    )

    op.create_table('call_recordings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=64), server_default='livekit_egress', nullable=False),
    sa.Column('egress_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.Enum('pending', 'recording', 'ready', 'failed', name='call_recording_status'), server_default='pending', nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('content_type', sa.String(length=255), server_default='audio/mpeg', nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('start_requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('error_detail', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'ready' AND egress_id IS NOT NULL AND byte_size > 0 AND duration_ms >= 0 AND completed_at IS NOT NULL AND error_code IS NULL) OR (status = 'failed' AND error_code IS NOT NULL AND completed_at IS NOT NULL) OR (status = 'recording' AND egress_id IS NOT NULL AND started_at IS NOT NULL AND completed_at IS NULL) OR (status = 'pending' AND completed_at IS NULL)", name='ck_call_recordings_lifecycle'),
    sa.ForeignKeyConstraint(['tenant_id', 'call_id'], ['call_sessions.tenant_id', 'call_sessions.id'], name='fk_call_recordings_call_same_tenant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id', name='uq_call_recordings_call_id'),
    sa.UniqueConstraint('egress_id', name='uq_call_recordings_egress_id'),
    sa.UniqueConstraint('storage_key', name='uq_call_recordings_storage_key')
    )

    op.create_table('capability_confirmations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('tool_call_id', sa.String(length=255), nullable=False),
    sa.Column('semantic_key', sa.String(length=128), nullable=False),
    sa.Column('semantic_version', sa.Integer(), nullable=False),
    sa.Column('tenant_release_id', sa.Uuid(), nullable=False),
    sa.Column('runtime_bundle_id', sa.Uuid(), nullable=False),
    sa.Column('canonical_input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('agent_input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('invocation_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id', 'call_id'], ['call_sessions.tenant_id', 'call_sessions.id'], name='fk_capability_confirmations_call_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'tenant_release_id', 'runtime_bundle_id'], ['tenant_releases.tenant_id', 'tenant_releases.id', 'tenant_releases.runtime_bundle_id'], name='fk_capability_confirmations_release_bundle_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'call_id', 'tool_call_id', name='uq_capability_confirmations_call_tool')
    )

    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('call_session_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('open', 'complete', 'incomplete', name='conversation_persistence_status'), server_default='open', nullable=False),
    sa.Column('next_sequence_number', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'open' AND closed_at IS NULL) OR (status IN ('complete', 'incomplete') AND closed_at IS NOT NULL)", name='ck_conversations_terminal_closed'),
    sa.CheckConstraint('next_sequence_number > 0', name='ck_conversations_next_sequence_number_positive'),
    sa.ForeignKeyConstraint(['tenant_id', 'call_session_id'], ['call_sessions.tenant_id', 'call_sessions.id'], name='fk_conversations_call_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_conversations_tenant_id_tenants'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_session_id', name='uq_conversations_call_session_id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_conversations_tenant_id_id')
    )

    op.create_table('capability_invocations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('tool_call_id', sa.String(length=255), nullable=False),
    sa.Column('semantic_key', sa.String(length=128), nullable=False),
    sa.Column('semantic_version', sa.Integer(), nullable=False),
    sa.Column('tenant_release_id', sa.Uuid(), nullable=False),
    sa.Column('runtime_bundle_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'queued', 'running', 'succeeded', 'failed', 'expired', name='capability_invocation_status'), server_default='pending', nullable=False),
    sa.Column('canonical_input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('execution_plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('operation_id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('technical_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('semantic_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pii_purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'call_id'], ['call_sessions.tenant_id', 'call_sessions.id'], name='fk_capability_invocations_call_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'conversation_id'], ['conversations.tenant_id', 'conversations.id'], name='fk_capability_invocations_conversation_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'tenant_release_id', 'runtime_bundle_id'], ['tenant_releases.tenant_id', 'tenant_releases.id', 'tenant_releases.runtime_bundle_id'], name='fk_capability_invocations_release_bundle_same_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', name='uq_capability_invocations_job_id'),
    sa.UniqueConstraint('operation_id'),
    sa.UniqueConstraint('tenant_id', 'call_id', 'tool_call_id', name='uq_capability_invocations_tenant_call_tool_call')
    )

    op.create_table('conversation_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('sequence_number', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', name='conversation_message_role'), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('interrupted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('persisted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(content) <> ''", name='ck_conversation_messages_content_not_blank'),
    sa.CheckConstraint('sequence_number > 0', name='ck_conversation_messages_sequence_positive'),
    sa.ForeignKeyConstraint(['tenant_id', 'conversation_id'], ['conversations.tenant_id', 'conversations.id'], name='fk_conversation_messages_conversation_same_tenant'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'sequence_number', name='uq_conversation_messages_conversation_sequence'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_conversation_messages_tenant_id_id')
    )

    op.create_table('post_call_action_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('finalization_id', sa.Uuid(), nullable=False),
    sa.Column('action_id', sa.String(length=128), nullable=False),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='post_call_work_status'), server_default='pending', nullable=False),
    sa.Column('command_id', sa.Uuid(), nullable=True),
    sa.Column('last_error', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['finalization_id'], ['call_finalizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('command_id', name='uq_post_call_action_execution_command_id'),
    sa.UniqueConstraint('finalization_id', 'action_id', name='uq_post_call_action_execution_logical_action')
    )

    op.create_table('outbox_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('capability_invocation_id', sa.Uuid(), nullable=True),
    sa.Column('stream', sa.String(length=255), nullable=True),
    sa.Column('payload_field', sa.String(length=32), server_default='job', nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('transport_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('attempts >= 0', name='ck_outbox_messages_attempts_nonnegative'),
    sa.ForeignKeyConstraint(['capability_invocation_id'], ['capability_invocations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )

    op.create_foreign_key(
        "fk_tenants_active_release_same_tenant",
        "tenants",
        "tenant_releases",
        ["id", "active_release_id"],
        ["tenant_id", "id"],
    )

    op.create_index('ix_call_sessions_tenant_created_at', 'call_sessions', ['tenant_id', 'created_at'], unique=False)
    op.create_index('uq_call_sessions_provider_sip_call_id', 'call_sessions', ['provider', 'sip_call_id'], unique=True, postgresql_where=sa.text('sip_call_id IS NOT NULL'))
    op.create_index('uq_call_sessions_provider_sip_call_id_full', 'call_sessions', ['provider', 'sip_call_id_full'], unique=True, postgresql_where=sa.text('sip_call_id_full IS NOT NULL'))
    op.create_index(op.f('ix_artifact_representations_command_id'), 'artifact_representations', ['command_id'], unique=False)
    op.create_index(op.f('ix_call_finalizations_summary_command_id'), 'call_finalizations', ['summary_command_id'], unique=False)
    op.create_index('ix_capability_confirmations_expires_at', 'capability_confirmations', ['expires_at'], unique=False)
    op.create_index('ix_capability_invocations_tenant_created_at', 'capability_invocations', ['tenant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_post_call_action_executions_command_id'), 'post_call_action_executions', ['command_id'], unique=False)
    op.create_index(op.f('ix_post_call_action_executions_finalization_id'), 'post_call_action_executions', ['finalization_id'], unique=False)
    op.create_index('ix_outbox_messages_undispatched', 'outbox_messages', ['created_at'], unique=False, postgresql_where='dispatched_at IS NULL')

    for table in ('call_sessions', 'capability_invocations', 'capability_confirmations'):
        op.add_column(table, sa.Column('execution_snapshot_id', sa.Uuid(), nullable=True))
        op.drop_constraint(f'fk_{table}_release_bundle_same_tenant', table, type_='foreignkey')
        op.alter_column(table, 'tenant_release_id', nullable=True)
        op.alter_column(table, 'runtime_bundle_id', nullable=True)
        op.create_check_constraint(
            f'ck_{table}_snapshot_or_legacy_pin', table,
            "(execution_snapshot_id IS NOT NULL AND tenant_release_id IS NULL AND runtime_bundle_id IS NULL) OR "
            "(execution_snapshot_id IS NULL AND tenant_release_id IS NOT NULL AND runtime_bundle_id IS NOT NULL)",
        )
    op.add_column('call_sessions', sa.Column('phone_assignment_id', sa.Uuid(), nullable=True))
    op.add_column('call_sessions', sa.Column('phone_assignment_generation', sa.Integer(), nullable=True))
    op.add_column('tenant_telephony_provisioning', sa.Column('phone_assignment_id', sa.Uuid(), nullable=True))
    op.add_column('tenant_telephony_provisioning', sa.Column('desired_generation', sa.Integer(), nullable=True))
    op.add_column('tenant_telephony_provisioning', sa.Column('applied_generation', sa.Integer(), nullable=True))
    op.create_unique_constraint(
        'uq_tenant_telephony_provisioning_assignment', 'tenant_telephony_provisioning',
        ['tenant_id', 'phone_assignment_id'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_tenant_telephony_provisioning_assignment', 'tenant_telephony_provisioning', type_='unique')
    op.drop_column('tenant_telephony_provisioning', 'applied_generation')
    op.drop_column('tenant_telephony_provisioning', 'desired_generation')
    op.drop_column('tenant_telephony_provisioning', 'phone_assignment_id')
    op.drop_column('call_sessions', 'phone_assignment_generation')
    op.drop_column('call_sessions', 'phone_assignment_id')
    for table in ('capability_confirmations', 'capability_invocations', 'call_sessions'):
        op.drop_constraint(f'ck_{table}_snapshot_or_legacy_pin', table, type_='check')
        op.alter_column(table, 'tenant_release_id', nullable=False)
        op.alter_column(table, 'runtime_bundle_id', nullable=False)
        op.create_foreign_key(
            f'fk_{table}_release_bundle_same_tenant', table, 'tenant_releases',
            ['tenant_id', 'tenant_release_id', 'runtime_bundle_id'],
            ['tenant_id', 'id', 'runtime_bundle_id'],
        )
        op.drop_column(table, 'execution_snapshot_id')
    op.drop_constraint(
        "fk_tenants_active_release_same_tenant",
        "tenants",
        type_="foreignkey",
    )
    op.drop_table('outbox_messages')
    op.drop_table('post_call_action_executions')
    op.drop_table('conversation_messages')
    op.drop_table('capability_invocations')
    op.drop_table('conversations')
    op.drop_table('capability_confirmations')
    op.drop_table('call_recordings')
    op.drop_table('call_finalizations')
    op.drop_table('artifact_representations')
    op.drop_table('knowledge_document_revisions')
    op.drop_table('call_sessions')
    op.drop_table('tenant_telephony_provisioning')
    op.drop_table('tenant_releases')
    op.drop_table('platform_release_profile_prompts')
    op.drop_table('platform_control')
    op.drop_table('knowledge_documents')
    op.drop_table('integration_credentials')
    op.drop_table('active_phone_claims')
    op.drop_table('tenant_telephony_revisions')
    op.drop_table('tenant_telephony_drafts')
    op.drop_table('tenant_runtime_drafts')
    op.drop_table('tenant_runtime_component_revisions')
    op.drop_table('tenant_prompt_component_revisions')
    op.drop_table('tenant_prompt_component_drafts')
    op.drop_table('tenant_post_call_revisions')
    op.drop_table('tenant_post_call_drafts')
    op.drop_table('tenant_knowledge_drafts')
    op.drop_table('tenant_knowledge_component_revisions')
    op.drop_table('tenant_capabilities_revisions')
    op.drop_table('tenant_capabilities_drafts')
    op.drop_table('tenant_agent_revisions')
    op.drop_table('tenant_agent_drafts')
    op.drop_table('runtime_bundles')
    op.drop_table('platform_releases')
    op.drop_table('knowledge_bases')
    op.drop_table('integration_connections')
    op.drop_table('tenants')
    op.drop_table('platform_telephony')
    op.drop_table('platform_system_prompt_drafts')
    op.drop_table('platform_system_prompt_component_revisions')
    op.drop_table('platform_runtime_component_revisions')
    op.drop_table('platform_runtime_component_drafts')
    op.drop_table('platform_profile_prompt_drafts')
    op.drop_table('platform_profile_prompt_component_revisions')
    op.execute("DROP TYPE telephony_provisioning_status")
    op.execute("DROP TYPE tenant_status")
    op.execute("DROP TYPE post_call_work_status")
    op.execute("DROP TYPE integration_kind")
    op.execute("DROP TYPE integration_credential_status")
    op.execute("DROP TYPE conversation_persistence_status")
    op.execute("DROP TYPE conversation_message_role")
    op.execute("DROP TYPE capability_invocation_status")
    op.execute("DROP TYPE call_session_status")
    op.execute("DROP TYPE call_recording_status")
    op.execute("DROP TYPE call_finalization_status")
    op.execute("DROP TYPE call_direction")
    op.execute("DROP TYPE call_channel")
