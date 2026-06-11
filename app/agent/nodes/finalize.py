from app.agent.contracts.output import AgentResult
from app.agent.contracts.state import AgentWorkingState


class FinalizeNode:
    def __call__(self, state: AgentWorkingState) -> AgentResult:
        return AgentResult(
            response_text=state.response_text,
            requested_capabilities=state.requested_capabilities,
            capability_results=state.capability_results,
            tool_calls=state.tool_calls,
            response_mode=state.response_mode,
            trace=state.trace,
        )
