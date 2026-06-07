from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.capabilities.schemas import CapabilityRequest, CapabilityResult
from app.schemas.tool_calls import ToolCallResponse

class CreateMessageRequest(BaseModel):
    tenant_id: str
    channel: str
    external_user_id: str | None = None
    conversation_id: str | None = None
    content: str
    metadata: dict | None = None

class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

class ProcessMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    user_message: MessageResponse
    assistant_message: MessageResponse | None = None
    intent: str | None = None
    response_text: str | None = None
    requested_capabilities: list[CapabilityRequest] | None = None
    capability_results: list[CapabilityResult] | None = None
    tool_calls: list[ToolCallResponse] | None = None
    status: str
