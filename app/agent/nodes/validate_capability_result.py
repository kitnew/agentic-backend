from app.agent.contracts.state import AgentWorkingState
from app.capabilities.schemas import CapabilityStatus


class ValidateCapabilityResultNode:
    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        failed = [
            result.name
            for result in state.capability_results
            if result.status == CapabilityStatus.FAILED
        ]
        disabled = [
            result.name
            for result in state.capability_results
            if result.status == CapabilityStatus.DISABLED
        ]
        state.trace["validate_capability_result"] = {
            "ok": not failed and not disabled,
            "failed": failed,
            "disabled": disabled,
            "results": [result.model_dump(mode="json") for result in state.capability_results],
        }
        return state
