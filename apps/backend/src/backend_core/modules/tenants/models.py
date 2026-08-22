from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class TelephonyProvisioningStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        ForeignKeyConstraint(
            ("id", "active_release_id"),
            ("tenant_releases.tenant_id", "tenant_releases.id"),
            name="fk_tenants_active_release_same_tenant",
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
            values_callable=lambda values: [value.value for value in values],
        ),
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )
    active_release_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def is_available_in_runtime(self) -> bool:
        return self.status is TenantStatus.ACTIVE and self.active_release_id is not None


class PlatformTelephony(Base):
    __tablename__ = "platform_telephony"
    __table_args__ = (CheckConstraint("id = 1", name="ck_platform_telephony_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    inbound_trunk_id: Mapped[str | None] = mapped_column(String(255))
    outbound_trunk_id: Mapped[str | None] = mapped_column(String(255))
    dispatch_rule_id: Mapped[str | None] = mapped_column(String(255))
    provisioning_status: Mapped[TelephonyProvisioningStatus] = mapped_column(
        Enum(
            TelephonyProvisioningStatus,
            name="telephony_provisioning_status",
            values_callable=lambda values: [value.value for value in values],
            create_type=False,
        ),
        default=TelephonyProvisioningStatus.PENDING,
        server_default=TelephonyProvisioningStatus.PENDING.value,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "key"),
        UniqueConstraint(
            "tenant_id", "knowledge_base_id", "id", name="uq_knowledge_documents_tenant_base_id"
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
        ForeignKeyConstraint(
            ("tenant_id", "knowledge_base_id", "knowledge_document_id"),
            (
                "knowledge_documents.tenant_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ),
            ondelete="CASCADE",
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
