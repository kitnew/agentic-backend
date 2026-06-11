from app.agent.contracts.state import AgentWorkingState
from app.agent.policies.capability import reservation_submission_gate, validate_capability_request


class ValidateCapabilityRequestNode:
    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        valid_requests = []
        validations = []
        for request in state.requested_capabilities:
            valid_request, validation = validate_capability_request(state, request)
            validations.append(validation)
            if valid_request is not None:
                valid_requests.append(valid_request)

        state.requested_capabilities = valid_requests
        state.capability_validation = {
            "ok": all(validation.get("ok") for validation in validations) if validations else True,
            "skipped": not validations,
            "reason": "no_requested_capabilities" if not validations else None,
            "gate": reservation_submission_gate(state),
            "validations": validations,
        }
        state.trace["validate_capability_request"] = state.capability_validation
        return state
