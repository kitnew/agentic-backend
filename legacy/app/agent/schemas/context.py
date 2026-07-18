from typing import NotRequired, TypedDict


class AgentContext(TypedDict):
    tenant_id: str
    conversation_id: NotRequired[str]
    agent_profile: str
    now: str
    datetime: str
    locale: str
    date: str
    time: str
    timezone: str
    agent_style_rules: list[str]
    tenant_instructions: str
    business_info: dict[str, str]
    reservation_policy: str
    required_reservation_fields: list[str]
    schedule_summary: str
    enabled_capabilities: list[str]
    call_session_id: NotRequired[str]
    channel: NotRequired[str]
    language: NotRequired[str]
    thread_id: NotRequired[str]
    idempotency_key: NotRequired[str]
