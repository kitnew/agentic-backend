from pydantic import BaseModel
from datetime import datetime

class CreateMessageRequest(BaseModel):
    tenant_id: str
    channel: str
    external_user_id: str | None = None
    conversation_id: str | None = None
    content: str
    metadata: dict | None = None

class MessageResponse(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str | None = None
    channel: str
    external_user_id: str | None = None
    role: str
    content: str
    intent: str | None = None
    status: str
    metadata: dict | None = None
    created_at: datetime
    processed_at: datetime | None = None