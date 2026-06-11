from pydantic import BaseModel, Field

from app.agent.contracts.state import ChatMessage
from app.tenants.schemas import TenantContext


class AgentInput(BaseModel):
    tenant_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    message_text: str
    channel: str | None = None
    tenant_context: TenantContext
    chat_history: list[ChatMessage] = Field(default_factory=list)
