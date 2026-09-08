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
            "(scope_type = 'platform' AND scope_key IS NULL) OR (scope_type IN ('tenant', 'profile', 'interaction_mode') AND scope_key IS NOT NULL AND scope_key <> '')",
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
        "live_components",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(255)),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "(scope_type = 'system' AND scope_key IS NULL) OR "
            "(scope_type = 'tenant' AND scope_key IS NOT NULL AND scope_key <> '')",
            name="ck_live_component_scope",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_live_component_schema_version"),
        sa.CheckConstraint("generation >= 1", name="ck_live_component_generation"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_live_component_address",
        "live_components",
        ["kind", "scope_type", "scope_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_nulls_not_distinct=True,
    )
    for table_name, prefix in (
        ("profile_catalog", "profile_catalog"),
        ("interaction_mode_catalog", "interaction_mode_catalog"),
    ):
        op.create_table(
            table_name,
            sa.Column("key", sa.String(255), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.String(2000), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
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
            sa.Column("updated_by", sa.String(255), nullable=False),
            sa.CheckConstraint(
                "status IN ('enabled', 'disabled')", name=f"ck_{prefix}_status"
            ),
            sa.CheckConstraint("generation >= 1", name=f"ck_{prefix}_generation"),
            schema=SCHEMA,
        )
    op.execute(
        """
        CREATE FUNCTION control_plane.reject_catalog_key_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.key IS DISTINCT FROM NEW.key THEN
            RAISE EXCEPTION 'catalog key is immutable';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    for table_name in ("profile_catalog", "interaction_mode_catalog"):
        op.execute(
            f"CREATE TRIGGER {table_name}_key_immutable BEFORE UPDATE OF key "
            f"ON control_plane.{table_name} FOR EACH ROW "
            "EXECUTE FUNCTION control_plane.reject_catalog_key_change()"
        )
    op.create_table(
        "idempotency_replays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("principal", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("logical_result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "principal",
            "operation",
            "idempotency_key",
            name="uq_idempotency_replay_identity",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(255)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active_version_id", sa.Uuid()),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(255)),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_credential_status"),
        sa.CheckConstraint("(scope_type = 'platform' AND tenant_id IS NULL) OR (scope_type = 'tenant' AND tenant_id IS NOT NULL AND tenant_id <> '')", name="ck_credential_scope"),
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
    op.execute(
        """
        CREATE FUNCTION control_plane.reject_credential_scope_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.scope_type IS DISTINCT FROM NEW.scope_type
             OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'credential scope is immutable';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER credential_scope_immutable BEFORE UPDATE OF scope_type, tenant_id "
        "ON control_plane.credentials FOR EACH ROW "
        "EXECUTE FUNCTION control_plane.reject_credential_scope_change()"
    )
    op.execute(
        """
        CREATE FUNCTION control_plane.reject_credential_version_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'credential secret versions are immutable';
          END IF;
          IF OLD.id IS DISTINCT FROM NEW.id
             OR OLD.credential_id IS DISTINCT FROM NEW.credential_id
             OR OLD.version_number IS DISTINCT FROM NEW.version_number
             OR OLD.key_id IS DISTINCT FROM NEW.key_id
             OR OLD.algorithm IS DISTINCT FROM NEW.algorithm
             OR OLD.nonce IS DISTINCT FROM NEW.nonce
             OR OLD.ciphertext IS DISTINCT FROM NEW.ciphertext
             OR OLD.created_at IS DISTINCT FROM NEW.created_at
             OR OLD.created_by IS DISTINCT FROM NEW.created_by
             OR (OLD.retired_at IS NOT NULL AND OLD.retired_at IS DISTINCT FROM NEW.retired_at) THEN
            RAISE EXCEPTION 'credential secret versions are immutable';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER credential_version_immutable BEFORE UPDATE OR DELETE "
        "ON control_plane.credential_versions FOR EACH ROW "
        "EXECUTE FUNCTION control_plane.reject_credential_version_mutation()"
    )
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
    op.execute(
        """
        CREATE FUNCTION control_plane.reject_provider_connection_identity_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.id IS DISTINCT FROM NEW.id
             OR OLD.key IS DISTINCT FROM NEW.key
             OR OLD.provider_kind IS DISTINCT FROM NEW.provider_kind THEN
            RAISE EXCEPTION 'provider connection identity is immutable';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER provider_connection_identity_immutable "
        "BEFORE UPDATE OF id, key, provider_kind ON control_plane.provider_connections "
        "FOR EACH ROW EXECUTE FUNCTION control_plane.reject_provider_connection_identity_change()"
    )
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.provider_connections.id"), nullable=False),
        sa.Column("deployment_kind", sa.String(32), nullable=False),
        sa.Column("deployment_config", postgresql.JSONB(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "deployment_kind IN ('llm', 'realtime', 'stt', 'tts')",
            name="ck_model_deployment_kind",
        ),
        sa.CheckConstraint(
            "capabilities ->> 'kind' = deployment_kind",
            name="ck_model_deployment_capability_kind",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_model_deployment_generation"),
        schema=SCHEMA,
    )
    op.execute(
        """
        CREATE FUNCTION control_plane.reject_model_deployment_identity_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.id IS DISTINCT FROM NEW.id
             OR OLD.key IS DISTINCT FROM NEW.key
             OR OLD.deployment_kind IS DISTINCT FROM NEW.deployment_kind THEN
            RAISE EXCEPTION 'model deployment identity is immutable';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER model_deployment_identity_immutable "
        "BEFORE UPDATE OF id, key, deployment_kind ON control_plane.model_deployments "
        "FOR EACH ROW EXECUTE FUNCTION control_plane.reject_model_deployment_identity_change()"
    )
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("integration_kind", sa.String(16), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.credentials.id")),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint("integration_kind = 'http'", name="ck_integration_connection_kind"),
        sa.CheckConstraint("generation >= 1", name="ck_integration_connection_generation"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_integration_connection_tenant_key"),
        schema=SCHEMA,
    )
    op.create_table(
        "handoff_destinations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("phone_number", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint("generation >= 1", name="ck_handoff_destination_generation"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_handoff_destination_tenant_key"),
        schema=SCHEMA,
    )
    op.create_table(
        "phone_number_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint("generation >= 1", name="ck_phone_number_assignment_generation"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_phone_number_assignment_enabled_tenant",
        "phone_number_assignments",
        ["tenant_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("enabled"),
    )
    op.create_index(
        "uq_phone_number_assignment_enabled_phone",
        "phone_number_assignments",
        ["phone_number"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("enabled"),
    )
    op.create_table(
        "execution_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("architecture", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version IN (1, 2)", name="ck_execution_snapshot_schema_version"),
        sa.CheckConstraint("architecture IN ('cascade', 'realtime')", name="ck_execution_snapshot_architecture"),
        schema=SCHEMA,
    )
    op.create_index("ix_execution_snapshot_tenant_created", "execution_snapshots", ["tenant_id", "created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_execution_snapshot_tenant_created", table_name="execution_snapshots", schema=SCHEMA)
    op.drop_table("execution_snapshots", schema=SCHEMA)
    op.drop_index("uq_phone_number_assignment_enabled_phone", table_name="phone_number_assignments", schema=SCHEMA)
    op.drop_index("uq_phone_number_assignment_enabled_tenant", table_name="phone_number_assignments", schema=SCHEMA)
    op.drop_table("phone_number_assignments", schema=SCHEMA)
    op.drop_table("handoff_destinations", schema=SCHEMA)
    op.drop_table("integration_connections", schema=SCHEMA)
    op.execute("DROP TRIGGER model_deployment_identity_immutable ON control_plane.model_deployments")
    op.execute("DROP FUNCTION control_plane.reject_model_deployment_identity_change()")
    op.drop_table("model_deployments", schema=SCHEMA)
    op.execute("DROP TRIGGER provider_connection_identity_immutable ON control_plane.provider_connections")
    op.execute("DROP FUNCTION control_plane.reject_provider_connection_identity_change()")
    op.drop_table("provider_connections", schema=SCHEMA)
    op.execute("DROP TRIGGER credential_version_immutable ON control_plane.credential_versions")
    op.execute("DROP FUNCTION control_plane.reject_credential_version_mutation()")
    op.execute("DROP TRIGGER credential_scope_immutable ON control_plane.credentials")
    op.execute("DROP FUNCTION control_plane.reject_credential_scope_change()")
    op.drop_constraint("fk_credential_active_version", "credentials", schema=SCHEMA, type_="foreignkey")
    op.drop_index("uq_credential_active_version", table_name="credential_versions", schema=SCHEMA)
    op.drop_table("credential_versions", schema=SCHEMA)
    op.drop_table("credentials", schema=SCHEMA)
    op.drop_table("idempotency_replays", schema=SCHEMA)
    for table_name in ("interaction_mode_catalog", "profile_catalog"):
        op.execute(f"DROP TRIGGER {table_name}_key_immutable ON control_plane.{table_name}")
        op.drop_table(table_name, schema=SCHEMA)
    op.execute("DROP FUNCTION control_plane.reject_catalog_key_change()")
    op.drop_index("uq_live_component_address", table_name="live_components", schema=SCHEMA)
    op.drop_table("live_components", schema=SCHEMA)
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
