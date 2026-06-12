from app.agent.tools.base import BaseAgentTool
from app.agent.tools.create_reservation import CreateReservationTool

TOOL_CLASSES = (
    CreateReservationTool,
)


def create_agent_tools(**kwargs) -> list[BaseAgentTool]:
    return [tool_class(**kwargs) for tool_class in TOOL_CLASSES]


def create_langchain_tools(agent_tools: list[BaseAgentTool] | None = None, **kwargs):
    tools = agent_tools or create_agent_tools(**kwargs)
    return [tool.as_langchain_tool() for tool in tools]


__all__ = [
    "BaseAgentTool",
    "CreateReservationTool",
    "TOOL_CLASSES",
    "create_agent_tools",
    "create_langchain_tools",
]
