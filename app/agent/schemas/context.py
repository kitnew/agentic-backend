from typing import Any, NotRequired, TypedDict


class AgentContext(TypedDict):
    tenant_id: str
    conversation_id: NotRequired[str]
    agent_profile: str
    now: str
    datetime: str
    current_local_datetime: NotRequired[str]
    current_local_date: NotRequired[str]
    current_local_time: NotRequired[str]
    locale: str
    date: str
    time: str
    timezone: str
    agent_style_rules: list[str]
    tenant_instructions: str
    business_info: dict[str, Any]
    reservation_policy: str
    required_reservation_fields: list[str]
    schedule_summary: str
    tenant_identity: NotRequired[dict[str, Any]]
    supported_operations: NotRequired[str]
    conversation_scope: NotRequired[str]
    knowledge_base: NotRequired[str]
    supplementary_guidance: NotRequired[list[str]]
    call_session_id: NotRequired[str]
    channel: NotRequired[str]
    language: NotRequired[str]
    thread_id: NotRequired[str]
    idempotency_key: NotRequired[str]
