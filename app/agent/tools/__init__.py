from app.agent.tools.base import BaseAgentTool
from app.agent.tools.create_reservation import CreateReservationTool
from app.agent.tools.get_business_info import GetBusinessInfoTool

TOOL_CLASSES = (
    CreateReservationTool,
    GetBusinessInfoTool,
)


def create_agent_tools() -> list[BaseAgentTool]:
    return [tool_class() for tool_class in TOOL_CLASSES]


def create_langchain_tools():
    return [tool.as_langchain_tool() for tool in create_agent_tools()]


__all__ = [
    "BaseAgentTool",
    "CreateReservationTool",
    "GetBusinessInfoTool",
    "TOOL_CLASSES",
    "create_agent_tools",
    "create_langchain_tools",
]
