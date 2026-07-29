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
