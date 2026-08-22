from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class _TenantDraft(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class _TenantRevision(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenantRuntimeDraft(_TenantDraft):
    __tablename__ = "tenant_runtime_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint(
            "version > 0", name="ck_tenant_runtime_drafts_version_positive"
        ),
        UniqueConstraint("tenant_id", name="uq_tenant_runtime_drafts_tenant"),
    )


class TenantRuntimeComponentRevision(_TenantRevision):
    __tablename__ = "tenant_runtime_component_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_runtime_component_revisions_number",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_tenant_runtime_component_revisions_id"
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_runtime_component_revisions_number_positive",
        ),
    )


class TenantAgentDraft(_TenantDraft):
    __tablename__ = "tenant_agent_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint("version > 0", name="ck_tenant_agent_drafts_version_positive"),
        UniqueConstraint("tenant_id", name="uq_tenant_agent_drafts_tenant"),
    )


class TenantAgentRevision(_TenantRevision):
    __tablename__ = "tenant_agent_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id", "revision_number", name="uq_tenant_agent_revisions_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_agent_revisions_id"),
        CheckConstraint(
            "revision_number > 0", name="ck_tenant_agent_revisions_number_positive"
        ),
    )


class TenantPromptDraft(_TenantDraft):
    __tablename__ = "tenant_prompt_component_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint(
            "version > 0", name="ck_tenant_prompt_component_drafts_version_positive"
        ),
        UniqueConstraint("tenant_id", name="uq_tenant_prompt_component_drafts_tenant"),
    )


class TenantPromptComponentRevision(_TenantRevision):
    __tablename__ = "tenant_prompt_component_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_prompt_component_revisions_number",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_tenant_prompt_component_revisions_id"
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_prompt_component_revisions_number_positive",
        ),
    )


class TenantKnowledgeDraft(_TenantDraft):
    __tablename__ = "tenant_knowledge_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint(
            "version > 0", name="ck_tenant_knowledge_drafts_version_positive"
        ),
        UniqueConstraint("tenant_id", name="uq_tenant_knowledge_drafts_tenant"),
    )


class TenantKnowledgeComponentRevision(_TenantRevision):
    __tablename__ = "tenant_knowledge_component_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_knowledge_component_revisions_number",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_tenant_knowledge_component_revisions_id"
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_knowledge_component_revisions_number_positive",
        ),
    )


class TenantCapabilitiesDraft(_TenantDraft):
    __tablename__ = "tenant_capabilities_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint(
            "version > 0", name="ck_tenant_capabilities_drafts_version_positive"
        ),
        UniqueConstraint("tenant_id", name="uq_tenant_capabilities_drafts_tenant"),
    )


class TenantCapabilitiesRevision(_TenantRevision):
    __tablename__ = "tenant_capabilities_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_capabilities_revisions_number",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_capabilities_revisions_id"),
        CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_capabilities_revisions_number_positive",
        ),
    )


class TenantTelephonyDraft(_TenantDraft):
    __tablename__ = "tenant_telephony_drafts"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        CheckConstraint(
            "version > 0", name="ck_tenant_telephony_drafts_version_positive"
        ),
        UniqueConstraint("tenant_id", name="uq_tenant_telephony_drafts_tenant"),
    )


class TenantTelephonyRevision(_TenantRevision):
    __tablename__ = "tenant_telephony_revisions"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint(
            "tenant_id", "revision_number", name="uq_tenant_telephony_revisions_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_telephony_revisions_id"),
        CheckConstraint(
            "revision_number > 0", name="ck_tenant_telephony_revisions_number_positive"
        ),
    )


class RuntimeBundleRecord(Base):
    __tablename__ = "runtime_bundles"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_runtime_bundles_tenant_id"),
        UniqueConstraint(
            "tenant_id", "content_hash", name="uq_runtime_bundles_tenant_hash"
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_runtime_bundles_content_hash"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    compiler_build_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenantRelease(Base):
    __tablename__ = "tenant_releases"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        ForeignKeyConstraint(
            ("tenant_id", "runtime_revision_id"),
            (
                "tenant_runtime_component_revisions.tenant_id",
                "tenant_runtime_component_revisions.id",
            ),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "agent_revision_id"),
            ("tenant_agent_revisions.tenant_id", "tenant_agent_revisions.id"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "prompt_revision_id"),
            (
                "tenant_prompt_component_revisions.tenant_id",
                "tenant_prompt_component_revisions.id",
            ),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_revision_id"),
            (
                "tenant_knowledge_component_revisions.tenant_id",
                "tenant_knowledge_component_revisions.id",
            ),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "capabilities_revision_id"),
            (
                "tenant_capabilities_revisions.tenant_id",
                "tenant_capabilities_revisions.id",
            ),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "telephony_revision_id"),
            ("tenant_telephony_revisions.tenant_id", "tenant_telephony_revisions.id"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "runtime_bundle_id"),
            ("runtime_bundles.tenant_id", "runtime_bundles.id"),
        ),
        ForeignKeyConstraint(("source_release_id",), ("tenant_releases.id",)),
        UniqueConstraint(
            "tenant_id", "release_number", name="uq_tenant_releases_number"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_releases_tenant_id"),
        UniqueConstraint(
            "tenant_id", "id", "runtime_bundle_id", name="uq_tenant_releases_bundle"
        ),
        CheckConstraint(
            "release_number > 0", name="ck_tenant_releases_number_positive"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    release_number: Mapped[int] = mapped_column(Integer)
    runtime_revision_id: Mapped[UUID] = mapped_column(Uuid)
    agent_revision_id: Mapped[UUID] = mapped_column(Uuid)
    prompt_revision_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_revision_id: Mapped[UUID] = mapped_column(Uuid)
    capabilities_revision_id: Mapped[UUID] = mapped_column(Uuid)
    telephony_revision_id: Mapped[UUID] = mapped_column(Uuid)
    runtime_bundle_id: Mapped[UUID] = mapped_column(Uuid)
    source_release_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenantTelephonyProvisioning(Base):
    __tablename__ = "tenant_telephony_provisioning"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        ForeignKeyConstraint(
            ("tenant_id", "desired_revision_id"),
            ("tenant_telephony_revisions.tenant_id", "tenant_telephony_revisions.id"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "applied_revision_id"),
            ("tenant_telephony_revisions.tenant_id", "tenant_telephony_revisions.id"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    desired_revision_id: Mapped[UUID] = mapped_column(Uuid)
    applied_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    applied_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ActivePhoneClaim(Base):
    __tablename__ = "active_phone_claims"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        ForeignKeyConstraint(
            ("tenant_id", "active_telephony_revision_id"),
            ("tenant_telephony_revisions.tenant_id", "tenant_telephony_revisions.id"),
        ),
        UniqueConstraint("tenant_id", name="uq_active_phone_claims_tenant"),
        CheckConstraint(
            "normalized_phone_number ~ '^\\+[1-9][0-9]{1,14}$'",
            name="ck_active_phone_claims_e164",
        ),
    )

    normalized_phone_number: Mapped[str] = mapped_column(String(16), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    active_telephony_revision_id: Mapped[UUID] = mapped_column(Uuid)
