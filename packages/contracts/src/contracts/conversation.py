from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationPersistenceStatus(StrEnum):
    OPEN = "open"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class _ConversationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppendConversationMessage(_ConversationModel):
    message_id: UUID
    role: ConversationMessageRole
    content: Annotated[str, Field(min_length=1, max_length=65536)]
    interrupted: bool
    source_created_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value

    @field_validator("source_created_at")
    @classmethod
    def source_created_at_must_be_timezone_aware(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("source_created_at must be timezone-aware")
        return value


class ConversationMessageResponse(_ConversationModel):
    message_id: UUID
    conversation_id: UUID
    sequence_number: int
    role: ConversationMessageRole
    content: str
    interrupted: bool
    source_created_at: datetime | None
    persisted_at: datetime


class ConversationResponse(_ConversationModel):
    conversation_id: UUID
    call_session_id: UUID
    status: ConversationPersistenceStatus
    created_at: datetime
    closed_at: datetime | None
    messages: list[ConversationMessageResponse]
