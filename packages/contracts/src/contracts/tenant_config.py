from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from pydantic_core import PydanticCustomError


class _TenantConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LocalizationConfig(_TenantConfigModel):
    default_locale: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise PydanticCustomError(
                "invalid_timezone",
                "Unknown IANA timezone",
            ) from error
        return value


class AgentConfig(_TenantConfigModel):
    display_name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)


class ConversationConfig(_TenantConfigModel):
    scope: Literal["property_only"]


class TenantConfigV1(_TenantConfigModel):
    schema_version: Literal[1]
    localization: LocalizationConfig
    agent: AgentConfig
    conversation: ConversationConfig
    capabilities: dict[str, StrictBool] = Field(default_factory=dict)


class ActiveTenantConfig(_TenantConfigModel):
    tenant_id: UUID
    revision_id: UUID
    revision_number: int
    published_at: datetime
    config: TenantConfigV1
