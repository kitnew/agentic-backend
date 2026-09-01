from typing import Annotated, Literal
from uuid import UUID

from contracts.voice_runtime import (
    Identifier,
    ReasoningEffort,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentKind,
    ScopeType,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resources import DeploymentKind, ModelDeployment


class _RuntimeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class LLMDefaults(_RuntimeComponent):
    deployment_ref: UUID
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    reasoning_effort: ReasoningEffort | None = None
    max_completion_tokens: int = Field(gt=0)


class STTDefaults(_RuntimeComponent):
    deployment_ref: UUID


Seconds = Annotated[float, Field(gt=0, le=60)]
Threshold = Annotated[float, Field(ge=0, le=1)]


class SpeechActivityPolicy(_RuntimeComponent):
    min_speech_seconds: Seconds
    min_silence_seconds: Seconds
    activation_threshold: Threshold


class LocalVADCommitPolicy(_RuntimeComponent):
    strategy: Literal["local_vad"]


class ProviderVADTuning(_RuntimeComponent):
    threshold: Threshold
    silence_threshold_seconds: Seconds
    min_speech_ms: int = Field(gt=0, le=60_000)
    min_silence_ms: int = Field(gt=0, le=60_000)


class ProviderVADCommitPolicy(_RuntimeComponent):
    strategy: Literal["provider_vad"]
    provider_vad: ProviderVADTuning


STTCommitPolicy = Annotated[
    LocalVADCommitPolicy | ProviderVADCommitPolicy,
    Field(discriminator="strategy"),
]


class EndpointingPolicy(_RuntimeComponent):
    min_delay_seconds: Seconds
    max_delay_seconds: Seconds

    @model_validator(mode="after")
    def delays_are_ordered(self) -> EndpointingPolicy:
        if self.min_delay_seconds > self.max_delay_seconds:
            raise ValueError("min_delay_seconds must not exceed max_delay_seconds")
        return self


class InterruptionPolicy(_RuntimeComponent):
    enabled: bool
    min_duration_seconds: Annotated[float, Field(ge=0, le=60)]
    min_words: int = Field(ge=0)
    false_interruption_timeout_seconds: Annotated[float, Field(ge=0, le=60)]
    resume_after_false_interruption: bool


class ResponseSchedulingPolicy(_RuntimeComponent):
    preemptive_generation: bool
    preemptive_tts: bool


class CascadeExecutionDefaults(_RuntimeComponent):
    speech_activity: SpeechActivityPolicy
    stt_commit: STTCommitPolicy
    endpointing: EndpointingPolicy
    interruption: InterruptionPolicy
    response_scheduling: ResponseSchedulingPolicy


class RealtimeInputTranscription(_RuntimeComponent):
    deployment_ref: UUID


class ServerVADTurnCompletion(_RuntimeComponent):
    strategy: Literal["server_vad"]
    activation_threshold: Threshold = 0.5
    silence_duration_ms: int = Field(default=200, gt=0)


class SemanticVADTurnCompletion(_RuntimeComponent):
    strategy: Literal["semantic_vad"]
    eagerness: Literal["auto", "low", "medium", "high"] = "auto"


RealtimeTurnCompletion = Annotated[
    ServerVADTurnCompletion | SemanticVADTurnCompletion,
    Field(discriminator="strategy"),
]


class RealtimeInterruptionPolicy(_RuntimeComponent):
    enabled: bool = True


class RealtimeExecutionDefaults(_RuntimeComponent):
    deployment_ref: UUID
    input_transcription: RealtimeInputTranscription
    default_voice: str = Field(default="marin", min_length=1)
    turn_completion: RealtimeTurnCompletion
    interruption: RealtimeInterruptionPolicy


class TTSDefaults(_RuntimeComponent):
    deployment_ref: UUID
    default_voice_id: Identifier
    min_sentence_chars: int = Field(ge=3, le=200)


def _deployment(value: object, expected: DeploymentKind) -> ModelDeployment:
    assert isinstance(value, ModelDeployment)
    if value.deployment_kind is not expected:
        raise InvalidComponentValue(
            f"referenced deployment must have deployment_kind={expected.value}"
        )
    return value


def _validate_llm(config: LLMDefaults, value: object) -> None:
    deployment = _deployment(value, DeploymentKind.LLM)
    capabilities = deployment.llm_capabilities
    if capabilities is None:
        raise InvalidComponentValue("llm deployment has no capabilities")
    if config.temperature is not None and not capabilities.supports_temperature:
        raise InvalidComponentValue("deployment does not support temperature")
    if config.reasoning_effort is not None and not capabilities.supports_reasoning_effort:
        raise InvalidComponentValue("deployment does not support reasoning_effort")


def _validate_stt(config: STTDefaults, value: object) -> None:
    deployment = _deployment(value, DeploymentKind.STT)
    if (
        deployment.stt_capabilities is None
        or not deployment.stt_capabilities.supports_cascade
    ):
        raise InvalidComponentValue("deployment does not support cascade STT usage")


def _validate_tts(config: TTSDefaults, value: object) -> None:
    _deployment(value, DeploymentKind.TTS)


def register_runtime_components(registry: object) -> None:
    from control_plane.domain.components import ComponentRegistry

    assert isinstance(registry, ComponentRegistry)
    platform = frozenset({ScopeType.PLATFORM})
    registry.register(ComponentDefinition(
        ComponentKind("runtime.llm.defaults"), LLMDefaults, platform, 1,
        lambda value: value.deployment_ref, _validate_llm,
    ))
    registry.register(ComponentDefinition(
        ComponentKind("runtime.stt.defaults"), STTDefaults, platform, 1,
        lambda value: value.deployment_ref, _validate_stt,
    ))
    registry.register(ComponentDefinition(
        ComponentKind("runtime.tts.defaults"), TTSDefaults, platform, 1,
        lambda value: value.deployment_ref, _validate_tts,
    ))
    registry.register(ComponentDefinition(
        ComponentKind("runtime.cascade.execution.defaults"),
        CascadeExecutionDefaults,
        platform,
        1,
    ))
    registry.register(ComponentDefinition(
        ComponentKind("runtime.realtime.execution.defaults"),
        RealtimeExecutionDefaults,
        platform,
        1,
    ))
