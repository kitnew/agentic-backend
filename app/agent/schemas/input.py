from typing import Annotated, NotRequired, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentInput(TypedDict):
    message_text: str
    chat_history: NotRequired[Sequence[BaseMessage]]


class AgentGraphInput(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
