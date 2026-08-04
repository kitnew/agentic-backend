from datetime import datetime
from uuid import UUID, uuid4

from contracts import ConversationMessageRole, ConversationPersistenceStatus
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_session_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_conversations_call_same_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
        UniqueConstraint("call_session_id", name="uq_conversations_call_session_id"),
        CheckConstraint(
            "next_sequence_number > 0",
            name="ck_conversations_next_sequence_number_positive",
        ),
        CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status IN ('complete', 'incomplete') AND closed_at IS NOT NULL)",
            name="ck_conversations_terminal_closed",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", name="fk_conversations_tenant_id_tenants"),
    )
    call_session_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[ConversationPersistenceStatus] = mapped_column(
        Enum(
            ConversationPersistenceStatus,
            name="conversation_persistence_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=ConversationPersistenceStatus.OPEN,
        server_default=ConversationPersistenceStatus.OPEN.value,
    )
    next_sequence_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "conversation_id"),
            ("conversations.tenant_id", "conversations.id"),
            name="fk_conversation_messages_conversation_same_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_conversation_messages_tenant_id_id",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_messages_conversation_sequence",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_conversation_messages_sequence_positive",
        ),
        CheckConstraint(
            "btrim(content) <> ''",
            name="ck_conversation_messages_content_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[ConversationMessageRole] = mapped_column(
        Enum(
            ConversationMessageRole,
            name="conversation_message_role",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    interrupted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    persisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
