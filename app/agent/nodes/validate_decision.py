from app.agent.contracts.state import AgentWorkingState
from app.agent.policies.decision import validate_decision


class ValidateDecisionNode:
    def __init__(self, max_iterations: int):
        self.max_iterations = max_iterations

    def __call__(self, state: AgentWorkingState, *, iteration: int) -> AgentWorkingState:
        decision, validation = validate_decision(
            state,
            state.decision,
            iteration=iteration,
            max_iterations=self.max_iterations,
        )
        state.decision = decision
        state.decision_validation = validation
        state.decision_feedback = validation.get("issues", [])
        state.trace.setdefault("validate_decision", []).append(
            {
                "iteration": iteration,
                "validation": validation,
                "decision": decision.model_dump(mode="json"),
            }
        )
        return state
