from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class FinalizationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CallFinalization(Base):
    __tablename__ = "call_finalizations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("call_sessions.id", ondelete="CASCADE"), unique=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    status: Mapped[FinalizationStatus] = mapped_column(
        Enum(
            FinalizationStatus,
            name="call_finalization_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=FinalizationStatus.PENDING,
        server_default=FinalizationStatus.PENDING.value,
    )
    summary_command_id: Mapped[UUID | None] = mapped_column(
        Uuid, nullable=True, index=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PostCallActionExecution(Base):
    __tablename__ = "post_call_action_executions"
    __table_args__ = (
        UniqueConstraint(
            "finalization_id",
            "action_id",
            name="uq_post_call_action_execution_logical_action",
        ),
        UniqueConstraint("command_id", name="uq_post_call_action_execution_command_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    finalization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("call_finalizations.id", ondelete="CASCADE"), index=True
    )
    action_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[WorkStatus] = mapped_column(
        Enum(
            WorkStatus,
            name="post_call_work_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=WorkStatus.PENDING,
        server_default=WorkStatus.PENDING.value,
    )
    command_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CallRecording(Base):
    __tablename__ = "call_recordings"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_call_recordings_call_same_tenant",
        ),
        UniqueConstraint("call_id", name="uq_call_recordings_call_id"),
        CheckConstraint("byte_size > 0", name="ck_call_recordings_byte_size_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    call_id: Mapped[UUID] = mapped_column(Uuid)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ArtifactRepresentation(Base):
    __tablename__ = "artifact_representations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_artifact_representations_call_same_tenant",
        ),
        UniqueConstraint(
            "call_id",
            "artifact_type",
            "representation",
            name="uq_artifact_representations_call_kind",
        ),
        UniqueConstraint("command_id", name="uq_artifact_representations_command_id"),
        CheckConstraint(
            "(artifact_type = 'transcript' AND representation = 'plain_text') "
            "OR (artifact_type = 'call_recording' AND representation = 'base64_text')",
            name="ck_artifact_representations_materializable_kind",
        ),
        CheckConstraint(
            "(status = 'completed' AND content IS NOT NULL AND byte_size IS NOT NULL "
            "AND sha256 IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status <> 'completed')",
            name="ck_artifact_representations_completed_content",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    call_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_type: Mapped[str] = mapped_column(String(64))
    representation: Mapped[str] = mapped_column(String(64))
    status: Mapped[WorkStatus] = mapped_column(
        Enum(
            WorkStatus,
            name="post_call_work_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=WorkStatus.PROCESSING,
        server_default=WorkStatus.PROCESSING.value,
    )
    command_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
