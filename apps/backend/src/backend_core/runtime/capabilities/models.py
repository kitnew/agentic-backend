from datetime import datetime
from uuid import UUID, uuid4

from contracts import CapabilityInvocationStatus
from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class CapabilityInvocation(Base):
    __tablename__ = "capability_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_capability_invocations_call_same_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "conversation_id"),
            ("conversations.tenant_id", "conversations.id"),
            name="fk_capability_invocations_conversation_same_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "tenant_config_revision_id"),
            ("tenant_config_revisions.tenant_id", "tenant_config_revisions.id"),
            name="fk_capability_invocations_config_same_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "call_id",
            "tool_call_id",
            name="uq_capability_invocations_tenant_call_tool_call",
        ),
        UniqueConstraint("job_id", name="uq_capability_invocations_job_id"),
        Index("ix_capability_invocations_tenant_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    call_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    tool_call_id: Mapped[str] = mapped_column(String(255))
    semantic_key: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[int] = mapped_column(Integer)
    tenant_config_revision_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[CapabilityInvocationStatus] = mapped_column(
        Enum(
            CapabilityInvocationStatus,
            name="capability_invocation_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=CapabilityInvocationStatus.PENDING,
        server_default=CapabilityInvocationStatus.PENDING.value,
    )
    canonical_input: Mapped[dict[str, object]] = mapped_column(JSONB)
    execution_plan: Mapped[dict[str, object]] = mapped_column(JSONB)
    operation_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    job_id: Mapped[UUID] = mapped_column(Uuid)
    technical_result: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    semantic_result: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pii_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CapabilityConfirmation(Base):
    __tablename__ = "capability_confirmations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_capability_confirmations_call_same_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "tenant_config_revision_id"),
            ("tenant_config_revisions.tenant_id", "tenant_config_revisions.id"),
            name="fk_capability_confirmations_config_same_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "call_id",
            "tool_call_id",
            name="uq_capability_confirmations_call_tool",
        ),
        Index("ix_capability_confirmations_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    call_id: Mapped[UUID] = mapped_column(Uuid)
    tool_call_id: Mapped[str] = mapped_column(String(255))
    semantic_key: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[int] = mapped_column(Integer)
    tenant_config_revision_id: Mapped[UUID] = mapped_column(Uuid)
    canonical_input: Mapped[dict[str, object]] = mapped_column(JSONB)
    agent_input: Mapped[dict[str, object]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    invocation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(
            "attempts >= 0", name="ck_outbox_messages_attempts_nonnegative"
        ),
        Index(
            "ix_outbox_messages_undispatched",
            "created_at",
            postgresql_where="dispatched_at IS NULL",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    capability_invocation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("capability_invocations.id", ondelete="CASCADE"),
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
