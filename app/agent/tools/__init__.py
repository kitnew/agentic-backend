from app.agent.tools.base import BaseAgentTool
from app.agent.tools.check_room_availability import CheckRoomAvailabilityTool
from app.agent.tools.create_reservation import CreateReservationTool
from app.agent.tools.reservation_requests import (
    NewReservationRequestTool,
    ReservationCancellationRequestTool,
    ReservationChangeRequestTool,
)

TOOL_CLASSES = (
    CreateReservationTool,
    CheckRoomAvailabilityTool,
)


def create_agent_tools(*, tenant_context=None, **kwargs) -> list[BaseAgentTool]:
    tool_classes = TOOL_CLASSES
    if tenant_context is not None:
        create_config = tenant_context.capabilities.get("reservation.create_request")
        if create_config and create_config.config.get("row_format") == "penzion_grand":
            tool_classes = (
                NewReservationRequestTool,
                ReservationChangeRequestTool,
                ReservationCancellationRequestTool,
                CheckRoomAvailabilityTool,
            )
        tool_classes = tuple(
            tool_class
            for tool_class in tool_classes
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
    "NewReservationRequestTool",
    "ReservationCancellationRequestTool",
    "ReservationChangeRequestTool",
    "TOOL_CLASSES",
    "create_agent_tools",
    "create_langchain_tools",
]
