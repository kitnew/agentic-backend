from typing import Annotated, Any, NotRequired, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    response_text: NotRequired[str]
    response: NotRequired[dict[str, Any]]
    agent_trace: NotRequired[dict[str, Any]]
