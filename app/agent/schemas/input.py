from typing import TypedDict, NotRequired
from langchain_core.messages import HumanMessage

class AgentInput(TypedDict):
    message: HumanMessage