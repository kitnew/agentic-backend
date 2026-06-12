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


class TenantPromptConfig(BaseModel):
    tenant_instructions: str = ""


class TenantBusinessInfoConfig(BaseModel):
    opening_hours_text: str | None = None
    parking: str | None = None
    address: str | None = None
    phone: str | None = None
    menu_summary: str | None = None


class TenantReservationFieldConfig(BaseModel):
    required: bool = True
    label: str


class TenantScheduleInterval(BaseModel):
    start: str
    end: str


class TenantWeeklyScheduleDay(BaseModel):
    open: bool
    intervals: list[TenantScheduleInterval] = Field(default_factory=list)


class TenantReservationScheduleConfig(BaseModel):
    weekly: dict[str, TenantWeeklyScheduleDay] = Field(default_factory=dict)


class TenantReservationConfig(BaseModel):
    enabled: bool = True
    mode: str = "request_only"
    requires_human_confirmation: bool = True
    can_confirm_reservation: bool = False
    required_fields: dict[str, TenantReservationFieldConfig] = Field(default_factory=dict)
    schedule: TenantReservationScheduleConfig = Field(default_factory=TenantReservationScheduleConfig)


class TenantContext(BaseModel):
    tenant_id: str
    name: str
    business_type: str
    default_language: str
    locale: str | None = None
    timezone: str
    agent: TenantAgentConfig
    prompt: TenantPromptConfig = Field(default_factory=TenantPromptConfig)
    business_info: TenantBusinessInfoConfig = Field(default_factory=TenantBusinessInfoConfig)
    reservation: TenantReservationConfig = Field(default_factory=TenantReservationConfig)
    capabilities: dict[str, TenantCapabilityConfig] = Field(default_factory=dict)
