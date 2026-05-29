from pydantic import BaseModel

class AgentInput(BaseModel):
    tenant_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    message_text: str
    channel: str | None = None
    metadata: dict | None = None

class AgentOutput(BaseModel):
    intent: str
    response_text: str
    requested_capabilities: list[str]
    metadata: dict | None = None

class IntentClassifierOutput(BaseModel):
    intent: str
    response_text: str
    requested_capabilities: list[str]