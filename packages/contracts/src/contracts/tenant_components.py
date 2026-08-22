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


class _ComponentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LocalizationConfig(_ComponentModel):
    default_locale: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise PydanticCustomError(
                "invalid_timezone", "Unknown IANA timezone"
            ) from error
        return value


class BusinessConfig(_ComponentModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)


class ContactConfig(_ComponentModel):
    address: str | None = Field(default=None, min_length=1, max_length=1000)
    phones: list[str] = Field(default_factory=list, max_length=20)
    emails: list[str] = Field(default_factory=list, max_length=20)
    website: str | None = Field(default=None, min_length=1, max_length=2048)


class ConversationScope(StrEnum):
    PROPERTY_ONLY = "property_only"


class ConversationConfig(_ComponentModel):
    scope: ConversationScope


class AgentIdentityConfig(_ComponentModel):
    display_name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)
    profile: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")


class TenantAgentConfig(_ComponentModel):
    business: BusinessConfig
    contact: ContactConfig = Field(default_factory=ContactConfig)
    localization: LocalizationConfig
    agent: AgentIdentityConfig
    conversation: ConversationConfig


class TenantPromptConfig(_ComponentModel):
    text: str = Field(default="", max_length=1_000_000)


class TenantKnowledgeConfig(_ComponentModel):
    knowledge_base_revision_id: UUID | None = None
    artifact_id: UUID | None = None
    # The current small-KB implementation may embed this snapshot.  A future
    # immutable retrieval artifact replaces it without changing releases.
    inline_context: str = Field(default="", max_length=1_000_000)


class CapabilityBusinessPolicy(_ComponentModel):
    requires_final_confirmation: bool = False
    requires_availability_proof: bool = False
    requires_caller_phone: bool = False
    availability_proof_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class GoogleSheetsExecutionIdempotency(_ComponentModel):
    lookup_range: str = Field(min_length=1, max_length=255)
    operation_id_column_index: int = Field(ge=0, le=1023)


class GoogleSheetsAppendExecution(_ComponentModel):
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


class ManagedWebhookExecution(_ComponentModel):
    plan_type: Literal["managed_webhook.post_json.v1"]
    connection_id: UUID
    mapping_language: Literal["jsonata"]
    mapping_contract_version: Literal[1]
    mapping_engine: Literal["jsonata-python"]
    mapping_engine_version: Literal["0.7.0"]
    request_mapping: str = Field(min_length=1, max_length=20_000)
    response: ManagedWebhookResponseConfig | None = None
    timeout_seconds: int = Field(gt=0, le=60)


class PostCallActionInput(_ComponentModel):
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


class PostCallAction(_ComponentModel):
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


class TenantCapabilityProfile(_ComponentModel):
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


class TenantCapabilitiesConfig(_ComponentModel):
    capabilities: dict[str, StrictBool | TenantCapabilityProfile] = Field(
        default_factory=dict
    )
    post_call_actions: list[PostCallAction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def post_call_action_ids_are_unique(self) -> TenantCapabilitiesConfig:
        action_ids = [action.action_id for action in self.post_call_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("post-call action IDs must be unique")
        return self


HandoffDestinationKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class HandoffDestination(_ComponentModel):
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")


class HandoffConfig(_ComponentModel):
    destinations: dict[HandoffDestinationKey, HandoffDestination] = Field(
        default_factory=dict, max_length=20
    )


class TenantTelephonyConfig(_ComponentModel):
    phone_number: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
