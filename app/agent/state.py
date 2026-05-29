from typing import TypedDict


class AgentState(TypedDict):
    message: str
    intent: str
