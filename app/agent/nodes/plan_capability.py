from app.agent.contracts.state import AgentWorkingState
from app.agent.policies.capability import (
    enabled_capabilities,
    plan_capability_requests,
    reservation_submission_gate,
)


class PlanCapabilityNode:
    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        state.requested_capabilities = plan_capability_requests(state)
        state.trace["plan_capability"] = {
            "gate": reservation_submission_gate(state),
            "enabled_capabilities": sorted(enabled_capabilities(state)),
            "requested": [request.model_dump(mode="json") for request in state.requested_capabilities],
        }
        return state
