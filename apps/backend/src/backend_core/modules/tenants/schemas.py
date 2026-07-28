from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend_core.modules.tenants.models import ConfigRevisionStatus, TenantStatus

Slug = Annotated[
    str,
    Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
BusinessType = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class _StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LocalizationConfig(_StrictConfigModel):
    default_locale: Annotated[
        str,
        Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$"),
    ]
    timezone: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA timezone") from error
        return value


class AgentConfig(_StrictConfigModel):
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    greeting: Annotated[str, Field(min_length=1, max_length=1000)]


class ConversationScope(StrEnum):
    PROPERTY_ONLY = "property_only"


class ConversationConfig(_StrictConfigModel):
    scope: ConversationScope


class TenantConfigV1(_StrictConfigModel):
    schema_version: Literal[1]
    localization: LocalizationConfig
    agent: AgentConfig
    conversation: ConversationConfig
    capabilities: dict[str, StrictBool] = Field(default_factory=dict)


class TenantCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: Slug
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    business_type: BusinessType
    status: TenantStatus = TenantStatus.ACTIVE


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    business_type: str
    status: TenantStatus
    active_config_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ConfigRevisionCreate(BaseModel):
    schema_version: Annotated[int, Field(gt=0)] = 1
    config: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    comment: Annotated[str | None, Field(max_length=1000)] = None


class ConfigRevisionClone(BaseModel):
    created_by: UUID
    comment: Annotated[str | None, Field(max_length=1000)] = None


class ConfigRevisionUpdate(BaseModel):
    schema_version: Annotated[int | None, Field(gt=0)] = None
    config: dict[str, Any] | None = None
    comment: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("schema_version", "config", mode="before")
    @classmethod
    def non_nullable_fields_cannot_be_cleared(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class ConfigRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    revision_number: int
    schema_version: int
    status: ConfigRevisionStatus
    config: dict[str, Any]
    created_at: datetime
    published_at: datetime | None
    created_by: UUID
    comment: str | None


class ConfigValidationResult(BaseModel):
    valid: bool = True


class ActiveConfigRead(BaseModel):
    tenant_id: UUID
    revision_id: UUID
    revision_number: int
    published_at: datetime
    config: TenantConfigV1
