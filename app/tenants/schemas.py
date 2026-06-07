from typing import Any

from pydantic import BaseModel, Field


class TenantCapabilityConfig(BaseModel):
    enabled: bool
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)


class TenantContext(BaseModel):
    tenant_id: str
    name: str
    business_type: str
    default_language: str
    timezone: str
    agent_profile: str
    business_info: dict[str, str] = Field(default_factory=dict)
    enabled_capabilities: dict[str, str]
    capabilities: dict[str, TenantCapabilityConfig] = Field(default_factory=dict)
    policies: dict[str, bool]
