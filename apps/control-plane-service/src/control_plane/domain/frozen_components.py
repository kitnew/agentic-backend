from typing import Annotated, Any, Literal, NotRequired
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypedDict

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentDefinitionRegistry,
    ComponentKind,
    ScopeType,
)


class FrozenValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SystemPrompt(FrozenValue):
    content: str = Field(min_length=1)


class ProfilePrompt(SystemPrompt):
    pass


class InteractionPrompt(SystemPrompt):
    pass


class TenantPrompt(SystemPrompt):
    pass


class Knowledge(FrozenValue):
    content: str


class STTDefaults(FrozenValue):
    deployment_ref: UUID


class LLMDefaults(FrozenValue):
    deployment_ref: UUID
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: (
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    max_completion_tokens: int = Field(gt=0)


class TTSDefaults(FrozenValue):
    deployment_ref: UUID
    default_voice_id: str = Field(min_length=1, max_length=255)


class RealtimeInputTranscription(FrozenValue):
    deployment_ref: UUID


class RealtimeServerVAD(FrozenValue):
    strategy: Literal["server_vad"]
    activation_threshold: float = Field(default=0.5, ge=0, le=1)
    silence_duration_ms: int = Field(default=200, gt=0)


class RealtimeSemanticVAD(FrozenValue):
    strategy: Literal["semantic_vad"]
    eagerness: Literal["auto", "low", "medium", "high"] = "auto"


RealtimeTurnCompletion = Annotated[
    RealtimeServerVAD | RealtimeSemanticVAD, Field(discriminator="strategy")
]


class RealtimeInterruption(FrozenValue):
    enabled: bool = Field(json_schema_extra={"default": True})


class RealtimeDefaults(FrozenValue):
    deployment_ref: UUID
    input_transcription: RealtimeInputTranscription
    default_voice: str = Field(
        min_length=1, max_length=255, json_schema_extra={"default": "marin"}
    )
    turn_completion: RealtimeTurnCompletion
    interruption: RealtimeInterruption


PositiveSeconds = Annotated[float, Field(gt=0, le=60)]
Threshold = Annotated[float, Field(ge=0, le=1)]


class CascadeSpeechActivity(FrozenValue):
    min_speech_seconds: PositiveSeconds
    min_silence_seconds: PositiveSeconds
    activation_threshold: Threshold


class LocalVADCommit(FrozenValue):
    strategy: Literal["local_vad"]


class ProviderVAD(FrozenValue):
    threshold: Threshold
    silence_threshold_seconds: PositiveSeconds
    min_speech_ms: int = Field(ge=1, le=60_000)
    min_silence_ms: int = Field(ge=1, le=60_000)


class ProviderVADCommit(FrozenValue):
    strategy: Literal["provider_vad"]
    provider_vad: ProviderVAD


CascadeSTTCommit = Annotated[
    LocalVADCommit | ProviderVADCommit, Field(discriminator="strategy")
]


class CascadeEndpointing(FrozenValue):
    min_delay_seconds: PositiveSeconds
    max_delay_seconds: PositiveSeconds

    @model_validator(mode="after")
    def delays_are_ordered(self) -> CascadeEndpointing:
        if self.min_delay_seconds > self.max_delay_seconds:
            raise ValueError("min_delay_seconds must not exceed max_delay_seconds")
        return self


class CascadeInterruption(FrozenValue):
    enabled: bool
    min_duration_seconds: float = Field(ge=0, le=60)
    min_words: int = Field(ge=0)
    false_interruption_timeout_seconds: float = Field(ge=0, le=60)
    resume_after_false_interruption: bool


class CascadeResponseScheduling(FrozenValue):
    preemptive_generation: bool
    preemptive_tts: bool


class CascadeTokenizer(FrozenValue):
    min_sentence_chars: int = Field(ge=3, le=200)


class CascadePolicies(FrozenValue):
    speech_activity: CascadeSpeechActivity
    stt_commit: CascadeSTTCommit
    endpointing: CascadeEndpointing
    interruption: CascadeInterruption
    response_scheduling: CascadeResponseScheduling
    tokenizer: CascadeTokenizer


class Policies(FrozenValue):
    cascade: CascadePolicies


class AgentPersonality(FrozenValue):
    identity: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)
    conversation_scope: Literal["property_only"]


class Business(FrozenValue):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)


Email = Annotated[str, Field(json_schema_extra={"format": "email"})]


class Contact(FrozenValue):
    address: str | None = Field(default=None, max_length=1000)
    phones: list[str] = Field(max_length=20)
    emails: list[Email] = Field(max_length=20)
    website: str | None = Field(default=None, max_length=2048)


class Localization(FrozenValue):
    default_locale: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str


class BusinessInfo(FrozenValue):
    business: Business
    contact: Contact
    localization: Localization


class DateRangeConstraint(FrozenValue):
    kind: Literal["date_range"]
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    start_not_in_past: bool = False


class RuntimeBusinessPolicy(FrozenValue):
    requires_final_confirmation: bool = False
    requires_caller_phone: bool = False


class ExprNode(FrozenValue):
    expression: str = Field(alias="$expr", min_length=1, max_length=20_000)


type MappingTemplate = (
    str
    | int
    | float
    | bool
    | None
    | ExprNode
    | dict[str, MappingTemplate]
    | list[MappingTemplate]
)


class HttpRequestSpec(FrozenValue):
    codec: Literal["none", "json", "text"]
    mapping: MappingTemplate = None
    content_type: str | None = None


class HttpResponseSpec(FrozenValue):
    codec: Literal["none", "json", "text"]
    mapping: MappingTemplate = None


class HttpSemanticExecution(FrozenValue):
    integration_key: str = Field(min_length=1, max_length=255)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str | ExprNode | None = None
    query: dict[str, MappingTemplate] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request: HttpRequestSpec
    response: HttpResponseSpec
    timeout_seconds: float = Field(gt=0, le=60)
    success_statuses: list[Annotated[int, Field(ge=100, le=599)]] | None = Field(
        default=None, max_length=20
    )


class RuntimeActionDefinition(FrozenValue):
    phase: Literal["runtime"]
    description: str = Field(min_length=1, max_length=1000)
    announcement: Annotated[str, Field(min_length=1, max_length=1000)] | dict[str, str]
    agent_input_schema: dict[str, Any]
    bindings: dict[str, str] = Field(default_factory=dict)
    input_constraints: list[DateRangeConstraint] = Field(default_factory=list)
    business_policy: RuntimeBusinessPolicy = Field(
        default_factory=RuntimeBusinessPolicy
    )
    execution: HttpSemanticExecution
    result_schema: dict[str, Any] | None = None


class TranscriptArtifactInput(FrozenValue):
    artifact: Literal["transcript"]
    representation: Literal["raw_json", "plain_text"]


class RecordingArtifactInput(FrozenValue):
    artifact: Literal["call_recording"]
    representation: Literal["original", "base64_text"]


class SummaryArtifactInput(FrozenValue):
    artifact: Literal["call_summary"]
    representation: Literal["plain_text"]


PostCallArtifactInput = Annotated[
    TranscriptArtifactInput | RecordingArtifactInput | SummaryArtifactInput,
    Field(discriminator="artifact"),
]


class PostCallActionDefinition(FrozenValue):
    phase: Literal["post_call"]
    artifact_inputs: dict[str, PostCallArtifactInput]
    execution: HttpSemanticExecution
    result_schema: dict[str, Any] | None = None


ActionDefinition = Annotated[
    RuntimeActionDefinition | PostCallActionDefinition, Field(discriminator="phase")
]
SemanticKey = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
]


class ActionsDefinition(FrozenValue):
    actions: dict[SemanticKey, ActionDefinition]


class Architecture(FrozenValue):
    architecture_key: str = Field(min_length=1, max_length=64)


class ProfileReference(FrozenValue):
    profile_key: str = Field(min_length=1, max_length=255)


class STTOverrides(TypedDict):
    keyterms: NotRequired[
        Annotated[
            list[Annotated[str, Field(min_length=1, max_length=64)]],
            Field(max_length=50),
        ]
    ]


class TTSOverrides(TypedDict):
    voice_id: NotRequired[Annotated[str, Field(min_length=1, max_length=255)]]


class RealtimeOverrides(TypedDict):
    voice: NotRequired[Annotated[str, Field(min_length=1, max_length=255)]]


class RuntimeOverrides(TypedDict):
    stt: NotRequired[STTOverrides]
    tts: NotRequired[TTSOverrides]
    realtime: NotRequired[RealtimeOverrides]


for _typed_dict in (STTOverrides, TTSOverrides, RealtimeOverrides, RuntimeOverrides):
    setattr(  # noqa: B010
        _typed_dict, "__pydantic_config__", ConfigDict(extra="forbid")
    )


class ActionsAvailability(FrozenValue):
    actions: dict[str, bool]


_DEFINITIONS = (
    (SystemPrompt, ScopeType.PLATFORM, "versioned"),
    (ProfilePrompt, ScopeType.PROFILE, "versioned"),
    (InteractionPrompt, ScopeType.INTERACTION_MODE, "versioned"),
    (STTDefaults, ScopeType.SYSTEM, "live"),
    (LLMDefaults, ScopeType.SYSTEM, "live"),
    (TTSDefaults, ScopeType.SYSTEM, "live"),
    (RealtimeDefaults, ScopeType.SYSTEM, "live"),
    (Policies, ScopeType.SYSTEM, "live"),
    (TenantPrompt, ScopeType.TENANT, "versioned"),
    (Knowledge, ScopeType.TENANT, "versioned"),
    (AgentPersonality, ScopeType.TENANT, "versioned"),
    (BusinessInfo, ScopeType.TENANT, "versioned"),
    (ActionsDefinition, ScopeType.TENANT, "versioned"),
    (Architecture, ScopeType.TENANT, "live"),
    (ProfileReference, ScopeType.TENANT, "live"),
    (RuntimeOverrides, ScopeType.TENANT, "live"),
    (ActionsAvailability, ScopeType.TENANT, "live"),
)


def default_component_definition_registry() -> ComponentDefinitionRegistry:
    registry = ComponentDefinitionRegistry()
    for value_type, scope, lifecycle in _DEFINITIONS:
        registry.register(
            ComponentDefinition(
                ComponentKind(value_type.__name__),
                value_type,
                frozenset({scope}),
                1,
                metadata={
                    "lifecycle": lifecycle,
                    "validation": "json_schema_draft_2020_12",
                },
            )
        )
    registry.freeze()
    return registry
