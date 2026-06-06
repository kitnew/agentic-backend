from pydantic import BaseModel, Field


class TenantContext(BaseModel):
    tenant_id: str
    name: str
    business_type: str
    default_language: str
    timezone: str
    agent_profile: str
    business_info: dict[str, str] = Field(default_factory=dict)
    enabled_capabilities: dict[str, str]
    policies: dict[str, bool]
