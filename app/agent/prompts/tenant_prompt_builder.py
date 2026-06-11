import json
from typing import Any

from pydantic import BaseModel


BUSINESS_INFO_FIELDS = (
    "opening_hours",
    "parking",
    "address",
    "phone",
    "menu_summary",
)


def build_tenant_prompt(
    tenant_context: dict[str, Any] | BaseModel,
    profile: dict[str, Any] | BaseModel,
    *,
    active_task: str | None = None,
    task_status: str | None = None,
    reservation_frame: dict[str, Any] | None = None,
    missing_fields: list[str] | None = None,
) -> str:
    tenant = _to_dict(tenant_context)
    agent = tenant.get("agent") or {}
    profile_data = _to_dict(profile)
    business_info = tenant.get("business_info") or {}
    capabilities = tenant.get("capabilities") or {}
    enabled_capabilities = {
        name: {
            "provider": config.get("provider"),
            "enabled": config.get("enabled", False),
        }
        for name, config in capabilities.items()
        if config.get("enabled")
    }
    reservation = tenant.get("reservation") or {}

    prompt_data = {
        "tenant": {
            "tenant_id": tenant.get("tenant_id"),
            "name": tenant.get("name"),
            "business_type": tenant.get("business_type"),
            "timezone": tenant.get("timezone"),
        },
        "agent": {
            "profile": agent.get("profile") or tenant.get("agent_profile"),
            "profile_name": profile_data.get("name"),
            "profile_behavior_rules": profile_data.get("behavior_rules") or [],
            "display_name": agent.get("display_name"),
            "use_display_name": agent.get("use_display_name", False),
            "language": (
                agent.get("language")
                or tenant.get("default_language")
                or profile_data.get("default_language")
            ),
            "tone": agent.get("tone") or profile_data.get("tone"),
            "greeting_phrase": agent.get("greeting_phrase"),
            "style_rules": agent.get("style_rules") or [],
        },
        "business_info": {
            field: business_info.get(field)
            for field in BUSINESS_INFO_FIELDS
            if business_info.get(field) is not None
        },
        "supported_intents": profile_data.get("supported_intents") or [],
        "available_capabilities": enabled_capabilities,
        "reservation": {
            "required_fields": reservation.get("required_fields") or [],
            "opening_hours": reservation.get("opening_hours") or [],
        },
        "current_active_task_state": {
            "active_task": active_task,
            "task_status": task_status,
            "reservation_frame": reservation_frame or {},
            "missing_fields": missing_fields or [],
        },
    }

    return (
        "Tenant-specific instructions and facts. Use this data only for this tenant.\n"
        f"{json.dumps(prompt_data, ensure_ascii=False, indent=2)}"
    )


def _to_dict(value: dict[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    return value
