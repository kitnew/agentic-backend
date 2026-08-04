from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
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


class ConversationScope(StrEnum):
    PROPERTY_ONLY = "property_only"


class ConversationConfig(_TenantConfigModel):
    scope: ConversationScope


class CapabilityBusinessPolicy(_TenantConfigModel):
    requires_final_confirmation: bool = False
    requires_availability_proof: bool = False
    requires_caller_phone: bool = False
    availability_proof_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class GoogleSheetsExecutionIdempotency(_TenantConfigModel):
    lookup_range: str = Field(min_length=1, max_length=255)
    operation_id_column_index: int = Field(ge=0, le=1023)


class GoogleSheetsAppendExecution(_TenantConfigModel):
    plan_type: Literal["google_sheets.append_values.v1"]
    mapping_language: Literal["jsonata"]
    mapping_contract_version: Literal[1]
    mapping_engine: Literal["jsonata-python"]
    mapping_engine_version: Literal["0.7.0"]
    connection_id: UUID
    spreadsheet_id: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=255)
    append_range: str = Field(min_length=1, max_length=255)
    value_input_option: Literal["RAW", "USER_ENTERED"] = "RAW"
    idempotency: GoogleSheetsExecutionIdempotency
    request_mapping: str = Field(min_length=1, max_length=20_000)


class TenantCapabilityProfile(_TenantConfigModel):
    enabled: StrictBool
    semantic_version: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=1000)
    announcement: str = Field(min_length=1, max_length=1000)
    agent_input_schema: dict[str, Any]
    business_policy: CapabilityBusinessPolicy = Field(
        default_factory=CapabilityBusinessPolicy
    )
    execution: GoogleSheetsAppendExecution
    validation_fixtures: list[dict[str, Any]] = Field(min_length=2, max_length=3)


class _TenantConfigBase(_TenantConfigModel):
    localization: LocalizationConfig
    agent: AgentConfig
    conversation: ConversationConfig
    capabilities: dict[str, StrictBool | TenantCapabilityProfile] = Field(
        default_factory=dict
    )


class TenantConfigV1(_TenantConfigBase):
    schema_version: Literal[1]


class TenantConfigV2(_TenantConfigBase):
    schema_version: Literal[2]
    prompt_bundle_revision_id: UUID


TenantConfig = TenantConfigV1 | TenantConfigV2


class ActiveTenantConfig(_TenantConfigModel):
    tenant_id: UUID
    revision_id: UUID
    revision_number: int
    published_at: datetime
    config: TenantConfig
