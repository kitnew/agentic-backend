from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.messages import MessageResponse


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    channel: str
    external_user_id: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationMessagesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation: ConversationResponse
    messages: list[MessageResponse]
