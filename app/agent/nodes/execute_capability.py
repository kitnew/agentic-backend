from app.agent.contracts.state import AgentWorkingState
from app.agent.runtime.capability_executor import CapabilityExecutor, MissingCapabilityExecutor


class ExecuteCapabilityNode:
    def __init__(self, capability_executor: CapabilityExecutor | None):
        self.capability_executor = capability_executor or MissingCapabilityExecutor()

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        executions = []
        state.capability_results = []
        state.tool_calls = []
        for request in state.requested_capabilities:
            execution = self.capability_executor.execute(request)
            state.capability_results.append(execution.result)
            if execution.tool_call is not None:
                state.tool_calls.append(execution.tool_call)
            executions.append(
                {
                    "request": execution.request.model_dump(mode="json"),
                    "result": execution.result.model_dump(mode="json"),
                    "tool_call": _dump_tool_call(execution.tool_call),
                }
            )
        state.trace["execute_capability"] = {"executions": executions}
        return state


def _dump_tool_call(tool_call):
    if tool_call is None:
        return None
    if hasattr(tool_call, "model_dump"):
        return tool_call.model_dump(mode="json")
    return tool_call
