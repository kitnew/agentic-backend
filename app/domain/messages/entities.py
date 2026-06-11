from datetime import datetime

from pydantic import BaseModel

from app.domain.messages.enums import MessageRole, MessageStatus


class Message(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str | None = None
    channel: str
    external_user_id: str | None = None
    role: MessageRole
    content: str
    status: MessageStatus
    metadata: dict | None = None
    created_at: datetime
    processed_at: datetime | None = None
