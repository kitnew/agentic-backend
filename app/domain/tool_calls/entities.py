from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.tool_calls.enums import ToolCallStatus


class ToolCall(BaseModel):
    id: str
    tenant_id: str
    message_id: str
    conversation_id: str | None = None
    call_session_id: str | None = None
    external_tool_call_id: str | None = None
    request_fingerprint: str | None = None
    capability_name: str
    provider: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: ToolCallStatus
    error: str | None = None
    response: dict[str, Any] | None = None
    latency_ms: int
    created_at: datetime
    updated_at: datetime | None = None
