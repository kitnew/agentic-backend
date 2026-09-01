from typing import Annotated
from uuid import UUID

from contracts.voice_runtime import (
    Identifier,
    ReasoningEffort,
    ServerVADRuntimeSettings,
)
from pydantic import BaseModel, ConfigDict, Field

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
    server_vad: ServerVADRuntimeSettings


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
    _deployment(value, DeploymentKind.STT)


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
