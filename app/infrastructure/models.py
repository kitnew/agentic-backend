from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class ConversationModel(Base):
    """SQLAlchemy model representing a conversation thread."""

    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    channel = Column(String, nullable=False)
    external_user_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, index=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class CallSessionModel(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'failed')"),
        CheckConstraint(
            "finalization_status IN ('pending', 'processing', 'completed', 'failed')"
        ),
        Index(
            "uq_call_sessions_sip_call_key",
            "sip_call_key",
            unique=True,
            sqlite_where=text("sip_call_key IS NOT NULL"),
            postgresql_where=text("sip_call_key IS NOT NULL"),
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    livekit_room_name = Column(String, nullable=False, unique=True)
    livekit_job_id = Column(String, nullable=True, unique=True)
    recording_egress_id = Column(String, nullable=True, unique=True)
    caller_phone = Column(String, nullable=True)
    called_phone = Column(String, nullable=True)
    sip_call_key = Column(String, nullable=True)
    sip_call_id = Column(String, nullable=True, index=True)
    sip_call_id_full = Column(String, nullable=True, index=True)
    sip_participant_identity = Column(String, nullable=True)
    sip_trunk_id = Column(String, nullable=True)
    sip_rule_id = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)
    finalization_status = Column(String, nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    terminal_reason = Column(String, nullable=True)
    terminal_error = Column(String, nullable=True)
    finalization_error = Column(String, nullable=True)
    finalization_command_id = Column(String, nullable=True, unique=True)
    finalization_enqueued_at = Column(DateTime, nullable=True)
    transcript = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    transcript_sheet_range = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False)


class MessageModel(Base):
    """SQLAlchemy model representing a persisted chat message."""

    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    channel = Column(String, nullable=False)
    external_user_id = Column(String, nullable=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    status = Column(String, nullable=False)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class ToolCallModel(Base):
    """SQLAlchemy model representing one backend capability execution."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "call_session_id",
            "external_tool_call_id",
            name="uq_tool_calls_livekit_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    call_session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    external_tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    capability_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
