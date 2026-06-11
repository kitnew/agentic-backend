from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.contracts.enums import ResponseMode
from app.capabilities.schemas import CapabilityRequest, CapabilityResult


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    response_text: str | None = None
    requested_capabilities: list[CapabilityRequest] = Field(default_factory=list)
    capability_results: list[CapabilityResult] = Field(default_factory=list)
    tool_calls: list[Any] = Field(default_factory=list)
    response_mode: ResponseMode = ResponseMode.DIRECT
    trace: dict[str, Any] = Field(default_factory=dict)
