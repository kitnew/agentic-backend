from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class ConfigRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PromptBundleRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PromptRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        ForeignKeyConstraint(
            ("id", "active_config_revision_id"),
            (
                "tenant_config_revisions.tenant_id",
                "tenant_config_revisions.id",
            ),
            name="fk_tenants_active_config_revision_same_tenant",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("id", "active_prompt_set_revision_id"),
            ("prompt_set_revisions.tenant_id", "prompt_set_revisions.id"),
            name="fk_tenants_active_prompt_set_revision_same_tenant",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    business_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[TenantStatus] = mapped_column(
        Enum(
            TenantStatus,
            name="tenant_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )
    active_config_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    active_prompt_set_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def is_available_in_runtime(self) -> bool:
        return self.status is TenantStatus.ACTIVE


class TenantConfigRevision(Base):
    __tablename__ = "tenant_config_revisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_config_revisions_tenant_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tenant_config_revisions_tenant_id_id",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_config_revisions_revision_number_positive",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_tenant_config_revisions_schema_version_positive",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_tenant_config_revisions_version_positive",
        ),
        Index(
            "uq_tenant_config_revisions_one_draft",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_tenant_config_revisions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ConfigRevisionStatus] = mapped_column(
        Enum(
            ConfigRevisionStatus,
            name="config_revision_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=ConfigRevisionStatus.DRAFT,
        server_default=ConfigRevisionStatus.DRAFT.value,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class InboundRoute(Base):
    __tablename__ = "inbound_routes"
    __table_args__ = (
        UniqueConstraint(
            "normalized_did",
            name="uq_inbound_routes_normalized_did",
        ),
        CheckConstraint(
            "normalized_did ~ '^\\+[1-9][0-9]{1,14}$'",
            name="ck_inbound_routes_normalized_did_e164",
        ),
        Index("ix_inbound_routes_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_inbound_routes_tenant_id_tenants",
            ondelete="CASCADE",
        ),
    )
    normalized_did: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PromptBundleRevision(Base):
    __tablename__ = "prompt_bundle_revisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_prompt_bundle_revisions_tenant_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_prompt_bundle_revisions_tenant_id_id",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_prompt_bundle_revisions_revision_number_positive",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_prompt_bundle_revisions_version_positive",
        ),
        Index(
            "uq_prompt_bundle_revisions_one_draft",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_prompt_bundle_revisions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PromptBundleRevisionStatus] = mapped_column(
        Enum(
            PromptBundleRevisionStatus,
            name="prompt_bundle_revision_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=PromptBundleRevisionStatus.DRAFT,
        server_default=PromptBundleRevisionStatus.DRAFT.value,
    )
    system_instructions: Mapped[str] = mapped_column(Text)
    tenant_instructions: Mapped[str] = mapped_column(Text)
    knowledge_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True)


class ProfilePrompt(Base):
    __tablename__ = "profile_prompts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True)


class TenantPrompt(Base):
    __tablename__ = "tenant_prompts"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_prompts_tenant"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_knowledge_bases_tenant"),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_bases_tenant_id_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class _PromptTextRevision:
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PromptRevisionStatus] = mapped_column(
        Enum(
            PromptRevisionStatus,
            name="prompt_revision_status",
            values_callable=lambda statuses: [status.value for status in statuses],
            create_type=False,
        ),
        default=PromptRevisionStatus.DRAFT,
        server_default=PromptRevisionStatus.DRAFT.value,
    )
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class SystemPromptRevision(_PromptTextRevision, Base):
    __tablename__ = "system_prompt_revisions"
    __table_args__ = (
        UniqueConstraint("system_prompt_id", "revision_number"),
        Index(
            "uq_system_prompt_revisions_one_draft",
            "system_prompt_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    system_prompt_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("system_prompts.id", ondelete="CASCADE")
    )


class ProfilePromptRevision(_PromptTextRevision, Base):
    __tablename__ = "profile_prompt_revisions"
    __table_args__ = (
        UniqueConstraint("profile_prompt_id", "revision_number"),
        Index(
            "uq_profile_prompt_revisions_one_draft",
            "profile_prompt_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_prompt_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profile_prompts.id", ondelete="CASCADE")
    )


class TenantPromptRevision(_PromptTextRevision, Base):
    __tablename__ = "tenant_prompt_revisions"
    __table_args__ = (
        UniqueConstraint("tenant_prompt_id", "revision_number"),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "uq_tenant_prompt_revisions_one_draft",
            "tenant_prompt_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_prompt_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenant_prompts.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "key"),
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_documents_tenant_base_id",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_base_id"),
            ("knowledge_bases.tenant_id", "knowledge_bases.id"),
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeDocumentRevision(Base):
    __tablename__ = "knowledge_document_revisions"
    __table_args__ = (
        UniqueConstraint("knowledge_document_id", "revision_number"),
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "knowledge_document_id",
            "id",
            name="uq_knowledge_document_revisions_owner_id",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_base_id", "knowledge_document_id"),
            (
                "knowledge_documents.tenant_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ),
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "media_type = 'text/markdown'",
            name="ck_knowledge_document_revisions_markdown",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_knowledge_document_revisions_revision_number_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_document_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_base_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision_number: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeBaseRevision(Base):
    __tablename__ = "knowledge_base_revisions"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "revision_number"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_base_revisions_tenant_base_id",
        ),
        Index(
            "uq_knowledge_base_revisions_one_draft",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PromptRevisionStatus] = mapped_column(
        Enum(
            PromptRevisionStatus,
            name="prompt_revision_status",
            values_callable=lambda values: [value.value for value in values],
            create_type=False,
        ),
        default=PromptRevisionStatus.DRAFT,
        server_default=PromptRevisionStatus.DRAFT.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class KnowledgeBaseRevisionDocument(Base):
    __tablename__ = "knowledge_base_revision_documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_revision_id", "position"),
        UniqueConstraint("knowledge_base_revision_id", "knowledge_document_id"),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_base_id", "knowledge_base_revision_id"),
            (
                "knowledge_base_revisions.tenant_id",
                "knowledge_base_revisions.knowledge_base_id",
                "knowledge_base_revisions.id",
            ),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            (
                "tenant_id",
                "knowledge_base_id",
                "knowledge_document_id",
                "knowledge_document_revision_id",
            ),
            (
                "knowledge_document_revisions.tenant_id",
                "knowledge_document_revisions.knowledge_base_id",
                "knowledge_document_revisions.knowledge_document_id",
                "knowledge_document_revisions.id",
            ),
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_knowledge_base_revision_documents_position_nonnegative",
        ),
    )

    knowledge_base_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    knowledge_document_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_base_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_document_id: Mapped[UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)


class PromptSet(Base):
    __tablename__ = "prompt_sets"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_prompt_sets_tenant"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class PromptSetRevision(Base):
    __tablename__ = "prompt_set_revisions"
    __table_args__ = (
        UniqueConstraint("prompt_set_id", "revision_number"),
        UniqueConstraint("tenant_id", "id"),
        Index(
            "uq_prompt_set_revisions_one_draft",
            "prompt_set_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "tenant_prompt_revision_id"),
            ("tenant_prompt_revisions.tenant_id", "tenant_prompt_revisions.id"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_base_revision_id"),
            ("knowledge_base_revisions.tenant_id", "knowledge_base_revisions.id"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prompt_set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prompt_sets.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PromptRevisionStatus] = mapped_column(
        Enum(
            PromptRevisionStatus,
            name="prompt_revision_status",
            values_callable=lambda values: [value.value for value in values],
            create_type=False,
        ),
        default=PromptRevisionStatus.DRAFT,
        server_default=PromptRevisionStatus.DRAFT.value,
    )
    system_prompt_revision_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("system_prompt_revisions.id")
    )
    profile_prompt_revision_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profile_prompt_revisions.id")
    )
    tenant_prompt_revision_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_base_revision_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
