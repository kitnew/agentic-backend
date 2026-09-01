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
            "(scope_type = 'platform' AND scope_key IS NULL) OR (scope_type IN ('tenant', 'profile') AND scope_key IS NOT NULL AND scope_key <> '')",
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


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        Index(
            "ix_outbox_pending",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index(
            "ix_outbox_component_revision",
            "component_id",
            "revision_number",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    component_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(2000))
