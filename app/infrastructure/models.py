from sqlalchemy import Column, DateTime, Integer, JSON, String

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

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    livekit_room_name = Column(String, nullable=False, unique=True)
    livekit_job_id = Column(String, nullable=True, unique=True)
    caller_phone = Column(String, nullable=True)
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

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    message_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    capability_name = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)
    input = Column(JSON, nullable=False)
    output = Column(JSON, nullable=True)
    status = Column(String, nullable=False, index=True)
    error = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, index=True)
