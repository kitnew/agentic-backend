from dataclasses import dataclass
from typing import Any, Protocol

from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus


@dataclass
class CapabilityExecution:
    request: CapabilityRequest
    result: CapabilityResult
    tool_call: Any | None = None


class CapabilityExecutor(Protocol):
    def execute(self, capability_request: CapabilityRequest) -> CapabilityExecution:
        pass


class MissingCapabilityExecutor:
    def execute(self, capability_request: CapabilityRequest) -> CapabilityExecution:
        return CapabilityExecution(
            request=capability_request,
            result=CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.DISABLED,
                provider="missing_executor",
                user_message="Žiadosť momentálne nevieme spracovať automaticky. Personál sa vám ozve.",
                error="Capability executor was not provided to AgentRuntime.",
            ),
        )
