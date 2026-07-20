from typing import NotRequired, Sequence, TypedDict

from langchain_core.messages import BaseMessage


class AgentInput(TypedDict):
    message_text: str
    chat_history: NotRequired[Sequence[BaseMessage]]
