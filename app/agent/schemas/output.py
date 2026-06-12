from typing import Any, TypedDict


class AgentOutput(TypedDict):
    response_text: str
    response: dict[str, Any]
    agent_trace: dict[str, Any]
