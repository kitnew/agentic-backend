from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    id: str
    tenant_id: str
    message_id: str
    conversation_id: str | None = None
    capability_name: str
    provider: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: str
    error: str | None = None
    latency_ms: int
    created_at: datetime
