from app.agent.tools.base import BaseAgentTool
from app.agent.tools.check_room_availability import CheckRoomAvailabilityTool
from app.agent.tools.create_reservation import CreateReservationTool

TOOL_CLASSES = (
    CreateReservationTool,
    CheckRoomAvailabilityTool,
)


def create_agent_tools(*, tenant_context=None, **kwargs) -> list[BaseAgentTool]:
    tool_classes = TOOL_CLASSES
    if tenant_context is not None:
        tool_classes = tuple(
            tool_class
            for tool_class in TOOL_CLASSES
            if (
                capability := tenant_context.capabilities.get(tool_class.capability_name)
            )
            and capability.enabled
        )
    return [tool_class(**kwargs) for tool_class in tool_classes]


def create_langchain_tools(agent_tools: list[BaseAgentTool] | None = None, **kwargs):
    tools = create_agent_tools(**kwargs) if agent_tools is None else agent_tools
    return [tool.as_langchain_tool() for tool in tools]


__all__ = [
    "BaseAgentTool",
    "CheckRoomAvailabilityTool",
    "CreateReservationTool",
    "TOOL_CLASSES",
    "create_agent_tools",
    "create_langchain_tools",
]
