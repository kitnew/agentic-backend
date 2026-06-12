from typing import TypedDict, Annotated, Sequence, List, Dict, NotRequired, Union
from langchain_core.messages import BaseMessage, ToolCall, ToolMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    message_history: Annotated[Sequence[BaseMessage], add_messages]
    tool_trace: NotRequired[List[Union[ToolCall, ToolMessage]]]