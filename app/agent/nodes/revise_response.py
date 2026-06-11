from app.agent.contracts.state import AgentWorkingState
from app.agent.nodes.plan_response import PlanResponseNode


class ReviseResponseNode:
    def __init__(self, plan_response_node: PlanResponseNode):
        self.plan_response_node = plan_response_node

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        state.trace.setdefault("revise_response", []).append(
            {
                "previous_response": state.response_text,
                "validation": state.response_validation,
            }
        )
        return self.plan_response_node(state)
