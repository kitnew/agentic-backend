from typing import TypedDict, Dict, Any
from langchain_core.messages import AIMessage

class AgentOutput(TypedDict):
    response: AIMessage
    agent_trace: Dict[str, Any]