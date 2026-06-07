from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.infrastructure.database import Base


class ConversationModel(Base):
    """
    SQLAlchemy model representing a conversation thread.
    """
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    channel = Column(String, nullable=False)
    external_user_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class MessageModel(Base):
    """
    SQLAlchemy model representing the 'messages' table.
    """
    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    channel = Column(String, nullable=False)
    external_user_id = Column(String, nullable=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    intent = Column(String, nullable=True)
    status = Column(String, nullable=False)
    
    # We map the database column "metadata" to "extra_metadata" to avoid conflict
    # with the SQLAlchemy Base's reserved property 'metadata'
    extra_metadata = Column("metadata", JSON, nullable=True)
    
    created_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class ToolCallModel(Base):
    """
    SQLAlchemy model representing one backend capability execution.
    """
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
