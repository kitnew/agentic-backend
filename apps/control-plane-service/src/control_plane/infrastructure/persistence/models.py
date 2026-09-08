from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "control_plane"


class Base(DeclarativeBase):
    pass


class ConfigurationComponent(Base):
    __tablename__ = "configuration_components"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'platform' AND scope_key IS NULL) OR (scope_type IN ('tenant', 'profile', 'interaction_mode') AND scope_key IS NOT NULL AND scope_key <> '')",
            name="ck_configuration_component_scope",
        ),
        Index(
            "uq_configuration_component_address",
            "kind",
            "scope_type",
            "scope_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            [
                f"{SCHEMA}.configuration_component_revisions.id",
                f"{SCHEMA}.configuration_component_revisions.component_id",
            ],
            name="fk_configuration_component_active_revision",
            use_alter=True,
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(255))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str | None] = mapped_column(String(255))
    active_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConfigurationComponentDraft(Base):
    __tablename__ = "configuration_component_drafts"
    __table_args__ = (
        CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_draft_schema_version",
        ),
        CheckConstraint(
            "version >= 1", name="ck_configuration_component_draft_version"
        ),
        {"schema": SCHEMA},
    )

    component_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    based_on_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.configuration_component_revisions.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class ConfigurationComponentRevision(Base):
    __tablename__ = "configuration_component_revisions"
    __table_args__ = (
        CheckConstraint(
            "revision_number >= 1", name="ck_configuration_component_revision_number"
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_revision_schema_version",
        ),
        UniqueConstraint(
            "component_id",
            "revision_number",
            name="uq_configuration_component_revision_number",
        ),
        UniqueConstraint(
            "id", "component_id", name="uq_configuration_component_revision_identity"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    component_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    based_on_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.configuration_component_revisions.id")
    )
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.configuration_component_revisions.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))


class LiveComponent(Base):
    __tablename__ = "live_components"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'system' AND scope_key IS NULL) OR "
            "(scope_type = 'tenant' AND scope_key IS NOT NULL AND scope_key <> '')",
            name="ck_live_component_scope",
        ),
        CheckConstraint("schema_version >= 1", name="ck_live_component_schema_version"),
        CheckConstraint("generation >= 1", name="ck_live_component_generation"),
        Index(
            "uq_live_component_address",
            "kind",
            "scope_type",
            "scope_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(255))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str | None] = mapped_column(String(255))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class ProfileCatalogEntry(Base):
    __tablename__ = "profile_catalog"
    __table_args__ = (
        CheckConstraint(
            "status IN ('enabled', 'disabled')", name="ck_profile_catalog_status"
        ),
        CheckConstraint("generation >= 1", name="ck_profile_catalog_generation"),
        {"schema": SCHEMA},
    )

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class InteractionModeCatalogEntry(Base):
    __tablename__ = "interaction_mode_catalog"
    __table_args__ = (
        CheckConstraint(
            "status IN ('enabled', 'disabled')",
            name="ck_interaction_mode_catalog_status",
        ),
        CheckConstraint(
            "generation >= 1", name="ck_interaction_mode_catalog_generation"
        ),
        {"schema": SCHEMA},
    )

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_credential_status"),
        CheckConstraint(
            "(scope_type = 'platform' AND tenant_id IS NULL) OR "
            "(scope_type = 'tenant' AND tenant_id IS NOT NULL AND tenant_id <> '')",
            name="ck_credential_scope",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)",
            name="ck_credential_revocation",
        ),
        CheckConstraint("generation >= 1", name="ck_credential_generation"),
        ForeignKeyConstraint(
            ["active_version_id", "id"],
            [
                f"{SCHEMA}.credential_versions.id",
                f"{SCHEMA}.credential_versions.credential_id",
            ],
            name="fk_credential_active_version",
            use_alter=True,
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(16))
    tenant_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    active_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="active")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(255))


class CredentialVersion(Base):
    __tablename__ = "credential_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="ck_credential_version_number"),
        UniqueConstraint(
            "credential_id", "version_number", name="uq_credential_version_number"
        ),
        UniqueConstraint("id", "credential_id", name="uq_credential_version_identity"),
        Index(
            "uq_credential_active_version",
            "credential_id",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    credential_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.credentials.id")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    key_id: Mapped[str] = mapped_column(String(255))
    algorithm: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="ck_provider_connection_generation"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    provider_kind: Mapped[str] = mapped_column(String(64))
    credential_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.credentials.id")
    )
    connection_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    enabled: Mapped[bool]
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(
            "integration_kind = 'http'", name="ck_integration_connection_kind"
        ),
        CheckConstraint("generation >= 1", name="ck_integration_connection_generation"),
        UniqueConstraint(
            "tenant_id", "key", name="uq_integration_connection_tenant_key"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(255))
    integration_kind: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    credential_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.credentials.id")
    )
    enabled: Mapped[bool]
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class HandoffDestination(Base):
    __tablename__ = "handoff_destinations"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="ck_handoff_destination_generation"),
        UniqueConstraint("tenant_id", "key", name="uq_handoff_destination_tenant_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(1000))
    phone_number: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool]
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class PhoneNumberAssignment(Base):
    __tablename__ = "phone_number_assignments"
    __table_args__ = (
        CheckConstraint(
            "generation >= 1", name="ck_phone_number_assignment_generation"
        ),
        Index(
            "uq_phone_number_assignment_enabled_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("enabled"),
        ),
        Index(
            "uq_phone_number_assignment_enabled_phone",
            "phone_number",
            unique=True,
            postgresql_where=text("enabled"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool]
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class ModelDeployment(Base):
    __tablename__ = "model_deployments"
    __table_args__ = (
        CheckConstraint(
            "deployment_kind IN ('llm', 'realtime', 'stt', 'tts')",
            name="ck_model_deployment_kind",
        ),
        CheckConstraint(
            "capabilities ->> 'kind' = deployment_kind",
            name="ck_model_deployment_capability_kind",
        ),
        CheckConstraint("generation >= 1", name="ck_model_deployment_generation"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.provider_connections.id")
    )
    deployment_kind: Mapped[str] = mapped_column(String(32))
    deployment_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB)
    enabled: Mapped[bool]
    generation: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(255))


class ExecutionSnapshot(Base):
    __tablename__ = "execution_snapshots"
    __table_args__ = (
        CheckConstraint(
            "schema_version IN (1, 2)", name="ck_execution_snapshot_schema_version"
        ),
        CheckConstraint(
            "architecture IN ('cascade', 'realtime')",
            name="ck_execution_snapshot_architecture",
        ),
        Index("ix_execution_snapshot_tenant_created", "tenant_id", "created_at"),
        {"schema": SCHEMA},
    )

    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255))
    schema_version: Mapped[int] = mapped_column(Integer)
    architecture: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyReplay(Base):
    __tablename__ = "idempotency_replays"
    __table_args__ = (
        UniqueConstraint(
            "principal",
            "operation",
            "idempotency_key",
            name="uq_idempotency_replay_identity",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    principal: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    logical_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
