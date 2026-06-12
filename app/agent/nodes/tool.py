from langgraph.prebuilt import ToolNode

from app.agent.nodes.base import AgentNode
from app.agent.schemas.state import AgentState


class ToolExecutionNode(AgentNode):
    name = "tool"

    def __init__(self, tools):
        self._node = ToolNode(tools=tools, messages_key="messages")

    def __call__(self, state: AgentState) -> AgentState:
        return self._node.invoke(state)
