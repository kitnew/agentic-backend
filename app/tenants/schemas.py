from typing import Any

from pydantic import BaseModel, Field


class TenantCapabilityConfig(BaseModel):
    enabled: bool
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)


class TenantAgentConfig(BaseModel):
    profile: str
    display_name: str | None = None
    use_display_name: bool = False
    greeting_phrase: str | None = None
    tone: str | None = None
    language: str | None = None
    style_rules: list[str] = Field(default_factory=list)


class TenantTimeRange(BaseModel):
    start: str
    end: str


class TenantReservationConfig(BaseModel):
    required_fields: list[str] = Field(
        default_factory=lambda: ["guest_name", "date", "time", "party_size", "phone"]
    )
    opening_hours: list[TenantTimeRange] = Field(default_factory=list)


class TenantContext(BaseModel):
    tenant_id: str
    name: str
    business_type: str
    default_language: str
    locale: str | None = None
    timezone: str
    agent_profile: str
    agent: TenantAgentConfig | None = None
    business_info: dict[str, str] = Field(default_factory=dict)
    reservation: TenantReservationConfig = Field(default_factory=TenantReservationConfig)
    enabled_capabilities: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, TenantCapabilityConfig] = Field(default_factory=dict)
    policies: dict[str, bool] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.agent is None:
            self.agent = TenantAgentConfig(
                profile=self.agent_profile,
                language=self.default_language,
            )
