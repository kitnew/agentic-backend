from datetime import UTC, datetime
from uuid import uuid4

import pytest
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.managed_resources import (
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    ProviderConnectionRef,
)
from control_plane.domain.runtime_components import register_runtime_components


def deployment(kind: DeploymentKind, capabilities: LLMCapabilities | None = None) -> ModelDeployment:
    now = datetime.now(UTC)
    return ModelDeployment(
        ModelDeploymentRef(uuid4()), "test", ProviderConnectionRef(uuid4()), kind,
        {}, capabilities, True, 1, now, "test", now, "test"
    )


def definition(kind: str):
    registry = ComponentRegistry()
    register_runtime_components(registry)
    return registry.resolve(ComponentAddress(ComponentKind(kind), PlatformScope()))


def test_runtime_registry_registers_only_platform_defaults() -> None:
    registry = ComponentRegistry()
    register_runtime_components(registry)
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.llm.defaults"), PlatformScope()))
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.stt.defaults"), PlatformScope()))
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.tts.defaults"), PlatformScope()))


def test_llm_capabilities_and_runtime_ranges() -> None:
    terra = definition("runtime.llm.defaults")
    reasoning = terra.deserialize({"deployment_ref": str(uuid4()), "reasoning_effort": "high", "max_completion_tokens": 1})
    terra.validate_deployment(reasoning, deployment(DeploymentKind.LLM, LLMCapabilities(False, True)))
    temperature = terra.deserialize({"deployment_ref": str(uuid4()), "temperature": 0.2, "max_completion_tokens": 1})
    terra.validate_deployment(temperature, deployment(DeploymentKind.LLM, LLMCapabilities(True, False)))
    with pytest.raises(InvalidComponentValue, match="temperature"):
        terra.validate_deployment(temperature, deployment(DeploymentKind.LLM, LLMCapabilities(False, True)))
    with pytest.raises(InvalidComponentValue, match="reasoning_effort"):
        terra.validate_deployment(reasoning, deployment(DeploymentKind.LLM, LLMCapabilities(True, False)))
    with pytest.raises(InvalidComponentValue):
        terra.deserialize({"deployment_ref": str(uuid4()), "max_completion_tokens": 0})


def test_stt_and_tts_shapes_reject_deferred_fields() -> None:
    stt = definition("runtime.stt.defaults")
    value = stt.deserialize({"deployment_ref": str(uuid4()), "server_vad": {"silence_threshold_seconds": 0.25, "activity_threshold": 0.5, "min_speech_ms": 100, "min_silence_ms": 100}})
    stt.validate_deployment(value, deployment(DeploymentKind.STT))
    with pytest.raises(InvalidComponentValue, match="deployment_kind"):
        stt.validate_deployment(value, deployment(DeploymentKind.TTS))
    with pytest.raises(InvalidComponentValue):
        stt.deserialize({"deployment_ref": str(uuid4()), "server_vad": {"silence_threshold_seconds": 0.25, "activity_threshold": 0.5, "min_speech_ms": 100, "min_silence_ms": 100}, "language": "sk"})
    tts = definition("runtime.tts.defaults")
    value = tts.deserialize({"deployment_ref": str(uuid4()), "default_voice_id": "voice", "min_sentence_chars": 20})
    tts.validate_deployment(value, deployment(DeploymentKind.TTS))
    with pytest.raises(InvalidComponentValue, match="deployment_kind"):
        tts.validate_deployment(value, deployment(DeploymentKind.STT))
