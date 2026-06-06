from typing import TypedDict

class AgentState(TypedDict):
    tenant_id: str
    conversation_id: str
    message_id: str
    message_text: str
    intent: str | None
    response_text: str | None
    requested_capabilities: list[str]
    metadata: dict | None
    tenant_context: dict
