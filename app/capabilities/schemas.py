from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CapabilityStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DISABLED = "disabled"


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
