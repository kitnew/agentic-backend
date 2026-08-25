import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.capability import RuntimeCapabilityDefinition
from contracts.http_operation import (
    ExpressionNode,
    HttpRequestSpec,
    HttpResponseSpec,
    MappingTemplate,
)
from contracts.voice import HandoffDestinationDefinition, VoiceAgentPrompt
from contracts.voice_runtime import EffectiveVoiceRuntime


class _RuntimeBundleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuntimeBundleProvenance(_RuntimeBundleModel):
    runtime_revision_id: UUID
    agent_revision_id: UUID
    prompt_revision_id: UUID
    knowledge_revision_id: UUID
    capabilities_revision_id: UUID
    post_call_revision_id: UUID
    telephony_revision_id: UUID
    platform_runtime_revision_id: UUID
    system_prompt_revision_id: UUID
    profile_prompt_revision_id: UUID
    integration_connection_ids: list[UUID] = Field(default_factory=list)
    knowledge_artifact_id: UUID | None = None


class RuntimeCapabilityPolicy(_RuntimeBundleModel):
    requires_final_confirmation: bool = False
    requires_availability_proof: bool = False
    requires_caller_phone: bool = False
    availability_proof_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class RuntimeCapabilityDateRangeConstraint(_RuntimeBundleModel):
    kind: Literal["date_range"] = "date_range"
    start: str = Field(pattern=r"^(?:[a-z][a-z0-9_]*\.)*[a-z][a-z0-9_]*$")
    end: str = Field(pattern=r"^(?:[a-z][a-z0-9_]*\.)*[a-z][a-z0-9_]*$")
    start_not_in_past: bool = False


RuntimeCapabilityInputConstraint = RuntimeCapabilityDateRangeConstraint


class RuntimeGoogleSheetsExecution(_RuntimeBundleModel):
    plan_type: Literal["google_sheets.append_values.v1"] = "google_sheets.append_values.v1"
    mapping_language: Literal["jsonata"] = "jsonata"
    mapping_contract_version: Literal[1] = 1
    mapping_engine: Literal["jsonata-python"] = "jsonata-python"
    mapping_engine_version: Literal["0.7.0"] = "0.7.0"
    connection_id: UUID
    spreadsheet_id: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=255)
    append_range: str = Field(min_length=1, max_length=255)
    value_input_option: Literal["RAW", "USER_ENTERED"] = "RAW"
    lookup_range: str = Field(min_length=1, max_length=255)
    operation_id_column_index: int = Field(ge=0, le=1023)
    request_mapping: str = Field(min_length=1, max_length=20_000)


class RuntimeHttpExecution(_RuntimeBundleModel):
    plan_type: Literal["http.request.v1"] = "http.request.v1"
    connection_id: UUID
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str | ExpressionNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: HttpRequestSpec = Field(default_factory=lambda: HttpRequestSpec(codec="none"))
    response: HttpResponseSpec = Field(default_factory=lambda: HttpResponseSpec(codec="none"))
    timeout_seconds: int = Field(gt=0, le=60)
    success_statuses: list[int] | None = Field(default=None, max_length=20)
    result_schema: dict[str, object] | None = None


class RuntimeCapabilityBinding(_RuntimeBundleModel):
    semantic_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    semantic_version: int = Field(gt=0)
    tool_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    enabled: bool
    input_schema: dict[str, object]
    bindings: dict[str, str] = Field(default_factory=dict)
    input_constraints: list[RuntimeCapabilityInputConstraint] = Field(default_factory=list)
    policy: RuntimeCapabilityPolicy = Field(default_factory=RuntimeCapabilityPolicy)
    execution: RuntimeGoogleSheetsExecution | RuntimeHttpExecution


class RuntimePostCallInput(_RuntimeBundleModel):
    artifact: str = Field(min_length=1, max_length=64)
    representation: str = Field(min_length=1, max_length=64)


class RuntimePostCallAction(_RuntimeBundleModel):
    action_id: str = Field(min_length=1, max_length=128)
    inputs: dict[str, RuntimePostCallInput] = Field(default_factory=dict)
    execution: RuntimeHttpExecution


class RuntimeHandoffDestination(_RuntimeBundleModel):
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")


class RuntimeTelephony(_RuntimeBundleModel):
    caller_number: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    handoff_destinations: dict[str, RuntimeHandoffDestination] = Field(
        default_factory=dict
    )


class RuntimeBundlePayload(_RuntimeBundleModel):
    voice_runtime: EffectiveVoiceRuntime
    locale: str = Field(min_length=1, max_length=35)
    timezone: str = Field(min_length=1, max_length=64)
    agent_display_name: str = Field(min_length=1, max_length=100)
    agent_profile: str = Field(default="default", min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)
    conversation_scope: str = Field(min_length=1, max_length=64)
    prompt: VoiceAgentPrompt
    capabilities: list[RuntimeCapabilityDefinition] = Field(default_factory=list)
    capability_bindings: list[RuntimeCapabilityBinding] = Field(default_factory=list)
    post_call_actions: list[RuntimePostCallAction] = Field(default_factory=list)
    telephony: RuntimeTelephony = Field(default_factory=RuntimeTelephony)
    handoff_destinations: dict[str, HandoffDestinationDefinition] = Field(
        default_factory=dict
    )


class RuntimeBundle(_RuntimeBundleModel):
    id: UUID
    tenant_id: UUID
    payload: RuntimeBundlePayload
    provenance: RuntimeBundleProvenance
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_build_id: str = Field(min_length=1, max_length=255)


def canonical_json_bytes(value: Any) -> bytes:
    """The only serialization accepted when hashing runtime contracts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def runtime_bundle_content_hash(
    payload: RuntimeBundlePayload,
    provenance: RuntimeBundleProvenance,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "payload": payload.model_dump(mode="json"),
                "provenance": provenance.model_dump(mode="json"),
            }
        )
    ).hexdigest()
