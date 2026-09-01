"""Initial mutable Control Plane baseline.

Revision ID: 0001_versioned_components
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_control_plane"
down_revision = None
branch_labels = None
depends_on = None
SCHEMA = "control_plane"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "configuration_components",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(255)),
        sa.Column("active_revision_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope_type = 'platform' AND scope_key IS NULL) OR (scope_type IN ('tenant', 'profile') AND scope_key IS NOT NULL AND scope_key <> '')",
            name="ck_configuration_component_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_configuration_component_address",
        "configuration_components",
        ["kind", "scope_type", "scope_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "configuration_component_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "component_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "based_on_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "restored_from_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_configuration_component_revision_number"
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_revision_schema_version",
        ),
        sa.UniqueConstraint(
            "component_id",
            "revision_number",
            name="uq_configuration_component_revision_number",
        ),
        sa.UniqueConstraint(
            "id", "component_id", name="uq_configuration_component_revision_identity"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "configuration_component_drafts",
        sa.Column(
            "component_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "based_on_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_draft_schema_version",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_configuration_component_draft_version"
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_configuration_component_active_revision",
        "configuration_components",
        "configuration_component_revisions",
        ["active_revision_id", "id"],
        ["id", "component_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("component_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE")),
        sa.Column("revision_number", sa.Integer()),
        sa.Column("ordering_key", sa.String(255), nullable=False),
        sa.Column("ordering_sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(2000)),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        sa.UniqueConstraint("ordering_key", "ordering_sequence", name="uq_outbox_ordering"),
        schema=SCHEMA,
    )
    op.create_index("ix_outbox_pending", "outbox_messages", ["created_at"], schema=SCHEMA, postgresql_where=sa.text("published_at IS NULL"))
    op.create_index("ix_outbox_component_revision", "outbox_messages", ["component_id", "revision_number"], schema=SCHEMA)
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("active_version_id", sa.Uuid()),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(255)),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_credential_status"),
        sa.CheckConstraint("(status = 'active' AND revoked_at IS NULL AND revoked_by IS NULL) OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)", name="ck_credential_revocation"),
        sa.CheckConstraint("generation >= 1", name="ck_credential_generation"),
        schema=SCHEMA,
    )
    op.create_table(
        "credential_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("credential_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.credentials.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(255), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("version_number >= 1", name="ck_credential_version_number"),
        sa.UniqueConstraint("credential_id", "version_number", name="uq_credential_version_number"),
        sa.UniqueConstraint("id", "credential_id", name="uq_credential_version_identity"),
        schema=SCHEMA,
    )
    op.create_index("uq_credential_active_version", "credential_versions", ["credential_id"], unique=True, schema=SCHEMA, postgresql_where=sa.text("retired_at IS NULL"))
    op.create_foreign_key("fk_credential_active_version", "credentials", "credential_versions", ["active_version_id", "id"], ["id", "credential_id"], source_schema=SCHEMA, referent_schema=SCHEMA)
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_kind", sa.String(64), nullable=False),
        sa.Column("credential_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.credentials.id"), nullable=False),
        sa.Column("connection_config", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint("generation >= 1", name="ck_provider_connection_generation"),
        schema=SCHEMA,
    )
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.provider_connections.id"), nullable=False),
        sa.Column("deployment_kind", sa.String(32), nullable=False),
        sa.Column("deployment_config", postgresql.JSONB(), nullable=False),
        sa.Column("llm_capabilities", postgresql.JSONB()),
        sa.Column("realtime_capabilities", postgresql.JSONB()),
        sa.Column("stt_capabilities", postgresql.JSONB()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint("generation >= 1", name="ck_model_deployment_generation"),
        schema=SCHEMA,
    )
    op.create_table(
        "runtime_execution_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("architecture", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_runtime_execution_snapshot_schema_version"),
        sa.CheckConstraint("architecture IN ('cascade', 'realtime')", name="ck_runtime_execution_snapshot_architecture"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_execution_snapshot_tenant_created", "runtime_execution_snapshots", ["tenant_id", "created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_runtime_execution_snapshot_tenant_created", table_name="runtime_execution_snapshots", schema=SCHEMA)
    op.drop_table("runtime_execution_snapshots", schema=SCHEMA)
    op.drop_table("model_deployments", schema=SCHEMA)
    op.drop_table("provider_connections", schema=SCHEMA)
    op.drop_constraint("fk_credential_active_version", "credentials", schema=SCHEMA, type_="foreignkey")
    op.drop_index("uq_credential_active_version", table_name="credential_versions", schema=SCHEMA)
    op.drop_table("credential_versions", schema=SCHEMA)
    op.drop_table("credentials", schema=SCHEMA)
    op.drop_index("ix_outbox_component_revision", table_name="outbox_messages", schema=SCHEMA)
    op.drop_index("ix_outbox_pending", table_name="outbox_messages", schema=SCHEMA)
    op.drop_table("outbox_messages", schema=SCHEMA)
    op.drop_constraint(
        "fk_configuration_component_active_revision",
        "configuration_components",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("configuration_component_drafts", schema=SCHEMA)
    op.drop_table("configuration_component_revisions", schema=SCHEMA)
    op.drop_index(
        "uq_configuration_component_address",
        table_name="configuration_components",
        schema=SCHEMA,
    )
    op.drop_table("configuration_components", schema=SCHEMA)
    op.execute(f"DROP SCHEMA {SCHEMA}")
