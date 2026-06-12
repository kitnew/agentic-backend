from typing import TypedDict, List, NotRequired

class AgentContext(TypedDict):
    tenant_id: str
    conversation_id: NotRequired[str]
    tenant_prompt: str
    business_profile: NotRequired[str]
    available_capabilities: NotRequired[List[str]]