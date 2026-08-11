from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class RuntimeRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def _status_column() -> Mapped[RuntimeRevisionStatus]:
    return mapped_column(
        Enum(
            RuntimeRevisionStatus,
            name="runtime_revision_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=RuntimeRevisionStatus.DRAFT,
        server_default=RuntimeRevisionStatus.DRAFT.value,
    )


class PlatformRuntime(Base):
    __tablename__ = "platform_runtimes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True)


class PlatformRuntimeRevision(Base):
    __tablename__ = "platform_runtime_revisions"
    __table_args__ = (
        UniqueConstraint("platform_runtime_id", "revision_number"),
        CheckConstraint("revision_number > 0"),
        CheckConstraint("version > 0"),
        Index(
            "uq_platform_runtime_revisions_one_draft",
            "platform_runtime_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_runtime_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform_runtimes.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[RuntimeRevisionStatus] = _status_column()
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class TenantRuntime(Base):
    __tablename__ = "tenant_runtimes"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        UniqueConstraint("tenant_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class TenantRuntimeRevision(Base):
    __tablename__ = "tenant_runtime_revisions"
    __table_args__ = (
        UniqueConstraint("tenant_runtime_id", "revision_number"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("revision_number > 0"),
        CheckConstraint("version > 0"),
        Index(
            "uq_tenant_runtime_revisions_one_draft",
            "tenant_runtime_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        ForeignKeyConstraint(
            ("tenant_id", "tenant_runtime_id"),
            ("tenant_runtimes.tenant_id", "tenant_runtimes.id"),
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_runtime_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[RuntimeRevisionStatus] = _status_column()
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class VoiceRuntime(Base):
    __tablename__ = "voice_runtimes"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        UniqueConstraint("tenant_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE")
    )


class VoiceRuntimeRevision(Base):
    __tablename__ = "voice_runtime_revisions"
    __table_args__ = (
        UniqueConstraint("voice_runtime_id", "revision_number"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("revision_number > 0"),
        ForeignKeyConstraint(
            ("tenant_id", "voice_runtime_id"),
            ("voice_runtimes.tenant_id", "voice_runtimes.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "tenant_runtime_revision_id"),
            ("tenant_runtime_revisions.tenant_id", "tenant_runtime_revisions.id"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    voice_runtime_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[RuntimeRevisionStatus] = mapped_column(
        Enum(
            RuntimeRevisionStatus,
            name="runtime_revision_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=RuntimeRevisionStatus.PUBLISHED,
        server_default=RuntimeRevisionStatus.PUBLISHED.value,
    )
    platform_runtime_revision_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform_runtime_revisions.id")
    )
    tenant_runtime_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    effective_settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
