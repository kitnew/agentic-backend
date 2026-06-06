from pydantic import BaseModel

from app.capabilities.schemas import CapabilityRequest
from app.tenants.schemas import TenantContext

class AgentInput(BaseModel):
    tenant_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    message_text: str
    channel: str | None = None
    metadata: dict | None = None
    tenant_context: TenantContext

class AgentOutput(BaseModel):
    intent: str
    response_text: str
    requested_capabilities: list[CapabilityRequest]
    metadata: dict | None = None

class IntentClassifierOutput(BaseModel):
    intent: str
    response_text: str
    requested_capabilities: list[CapabilityRequest]
