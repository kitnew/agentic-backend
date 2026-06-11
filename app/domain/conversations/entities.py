from datetime import datetime

from pydantic import BaseModel

from app.domain.conversations.enums import ConversationStatus


class Conversation(BaseModel):
    id: str
    tenant_id: str
    channel: str
    external_user_id: str | None = None
    status: ConversationStatus
    metadata: dict | None = None
    created_at: datetime
    updated_at: datetime
