from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CapabilityStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DISABLED = "disabled"


class CapabilityExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


class CapabilityRequest(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


class CapabilityResult(BaseModel):
    name: str
    status: CapabilityStatus
    output: dict[str, Any] | None = None
    user_message: str | None = None
    error: str | None = None
    provider: str


class CapabilityCommand(BaseModel):
    command_id: str
    tenant_id: str
    conversation_id: str | None = None
    call_session_id: str | None = None
    capability: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityExecutionResult(BaseModel):
    command_id: str
    status: CapabilityExecutionStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    execution_duration_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)
