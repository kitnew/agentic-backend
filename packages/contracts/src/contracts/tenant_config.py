from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from contracts.capability import ManagedWebhookResponseConfig


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


class BusinessConfig(_TenantConfigModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)


class ContactConfig(_TenantConfigModel):
    address: str | None = Field(default=None, min_length=1, max_length=1000)
    phones: list[str] = Field(default_factory=list, max_length=20)
    emails: list[str] = Field(default_factory=list, max_length=20)
    website: str | None = Field(default=None, min_length=1, max_length=2048)


class AgentConfigV3(AgentConfig):
    profile: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")


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


class ManagedWebhookExecution(_TenantConfigModel):
    plan_type: Literal["managed_webhook.post_json.v1"]
    connection_id: UUID
    mapping_language: Literal["jsonata"]
    mapping_contract_version: Literal[1]
    mapping_engine: Literal["jsonata-python"]
    mapping_engine_version: Literal["0.7.0"]
    request_mapping: str = Field(min_length=1, max_length=20_000)
    response: ManagedWebhookResponseConfig | None = None
    timeout_seconds: int = Field(gt=0, le=60)


class PostCallActionInput(_TenantConfigModel):
    artifact: Literal["transcript", "call_recording", "call_summary"]
    representation: Literal["raw_json", "plain_text", "original", "base64_text"]

    @model_validator(mode="after")
    def representation_matches_artifact(self) -> PostCallActionInput:
        supported = {
            "transcript": {"raw_json", "plain_text"},
            "call_recording": {"original", "base64_text"},
            "call_summary": {"plain_text"},
        }
        if self.representation not in supported[self.artifact]:
            raise ValueError("unsupported artifact representation")
        return self


class PostCallAction(_TenantConfigModel):
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    type: Literal["http.post_json"] = "http.post_json"
    inputs: dict[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")],
        PostCallActionInput,
    ] = Field(default_factory=dict, max_length=10)
    semantic_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    semantic_version: int = Field(gt=0)
    execution: ManagedWebhookExecution


CapabilityExecution = Annotated[
    GoogleSheetsAppendExecution | ManagedWebhookExecution,
    Field(discriminator="plan_type"),
]


class TenantCapabilityProfile(_TenantConfigModel):
    enabled: StrictBool
    semantic_version: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=1000)
    announcement: str = Field(min_length=1, max_length=1000)
    agent_input_schema: dict[str, Any]
    business_policy: CapabilityBusinessPolicy = Field(
        default_factory=CapabilityBusinessPolicy
    )
    execution: CapabilityExecution
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


class TenantConfigV3(_TenantConfigModel):
    schema_version: Literal[3]
    business: BusinessConfig
    contact: ContactConfig = Field(default_factory=ContactConfig)
    localization: LocalizationConfig
    agent: AgentConfigV3
    conversation: ConversationConfig
    capabilities: dict[str, StrictBool | TenantCapabilityProfile] = Field(
        default_factory=dict
    )
    post_call_actions: list[PostCallAction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def post_call_action_ids_are_unique(self) -> TenantConfigV3:
        action_ids = [action.action_id for action in self.post_call_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("post_call action IDs must be unique")
        return self


HandoffDestinationKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class HandoffDestination(_TenantConfigModel):
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")


class HandoffConfig(_TenantConfigModel):
    destinations: dict[HandoffDestinationKey, HandoffDestination] = Field(
        default_factory=dict, max_length=20
    )


class TenantConfigV4(TenantConfigV3):
    schema_version: Literal[4]  # type: ignore[assignment]
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)


TenantConfig = TenantConfigV1 | TenantConfigV2 | TenantConfigV3 | TenantConfigV4

# The persisted revision schema version is the dispatch key for deserialization.
TENANT_CONFIG_SCHEMAS: dict[
    int, type[TenantConfigV1 | TenantConfigV2 | TenantConfigV3 | TenantConfigV4]
] = {
    1: TenantConfigV1,
    2: TenantConfigV2,
    3: TenantConfigV3,
    4: TenantConfigV4,
}


class ActiveTenantConfig(_TenantConfigModel):
    tenant_id: UUID
    revision_id: UUID
    revision_number: int
    published_at: datetime
    config: TenantConfig
