from typing import NotRequired, TypedDict


class AgentContext(TypedDict):
    tenant_id: str
    conversation_id: NotRequired[str]
    agent_profile: str
    tenant_prompt: str
    now: str
    datetime: str
    locale: str
    date: str
    time: str
    timezone: str
    business_profile: NotRequired[str]
    available_capabilities: NotRequired[list[str]]
