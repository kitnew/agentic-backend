from typing import Literal

from app.agent.nodes.base import ConditionalNode
from app.agent.schemas.state import AgentState


class ShouldContinueNode(ConditionalNode):
    name = "should_continue"

    def __call__(self, state: AgentState) -> Literal["continue", "end"]:
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "continue"
        return "end"
