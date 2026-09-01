from datetime import UTC, datetime
from uuid import uuid4

import pytest
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
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


def cascade_policy(strategy: str = "local_vad") -> dict[str, object]:
    stt_commit: dict[str, object] = {"strategy": strategy}
    if strategy == "provider_vad":
        stt_commit["provider_vad"] = {
            "threshold": 0.5, "silence_threshold_seconds": 0.35,
            "min_speech_ms": 100, "min_silence_ms": 350,
        }
    return {
        "speech_activity": {
            "min_speech_seconds": 0.05, "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "stt_commit": stt_commit,
        "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.7},
        "interruption": {
            "enabled": True, "min_duration_seconds": 0.5, "min_words": 0,
            "false_interruption_timeout_seconds": 2.0,
            "resume_after_false_interruption": True,
        },
        "response_scheduling": {
            "preemptive_generation": True, "preemptive_tts": True,
        },
    }


def test_runtime_registry_registers_only_platform_defaults() -> None:
    registry = ComponentRegistry()
    register_runtime_components(registry)
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.llm.defaults"), PlatformScope()))
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.stt.defaults"), PlatformScope()))
    assert registry.resolve(ComponentAddress(ComponentKind("runtime.tts.defaults"), PlatformScope()))
    cascade = ComponentKind("runtime.cascade.execution.defaults")
    assert registry.resolve(ComponentAddress(cascade, PlatformScope()))
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(ComponentAddress(cascade, TenantScope("tenant")))


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


def test_stt_defaults_contains_only_deployment_ref() -> None:
    stt = definition("runtime.stt.defaults")
    deployment_ref = uuid4()
    value = stt.deserialize({"deployment_ref": str(deployment_ref)})
    assert stt.serialize(value) == {"deployment_ref": str(deployment_ref)}
    stt.validate_deployment(value, deployment(DeploymentKind.STT))
    with pytest.raises(InvalidComponentValue, match="deployment_kind"):
        stt.validate_deployment(value, deployment(DeploymentKind.TTS))
    with pytest.raises(InvalidComponentValue):
        stt.deserialize({"deployment_ref": str(uuid4()), "server_vad": {}})


def test_cascade_commit_strategy_is_structurally_discriminated() -> None:
    cascade = definition("runtime.cascade.execution.defaults")
    assert cascade.deserialize(cascade_policy()).stt_commit.strategy == "local_vad"
    provider = cascade.deserialize(cascade_policy("provider_vad"))
    assert provider.stt_commit.provider_vad.min_silence_ms == 350

    mixed = cascade_policy()
    mixed_commit = mixed["stt_commit"]
    assert isinstance(mixed_commit, dict)
    mixed_commit["provider_vad"] = {
        "threshold": 0.5, "silence_threshold_seconds": 0.35,
        "min_speech_ms": 100, "min_silence_ms": 350,
    }
    with pytest.raises(InvalidComponentValue):
        cascade.deserialize(mixed)
    missing = cascade_policy("provider_vad")
    missing_commit = missing["stt_commit"]
    assert isinstance(missing_commit, dict)
    del missing_commit["provider_vad"]
    with pytest.raises(InvalidComponentValue):
        cascade.deserialize(missing)


@pytest.mark.parametrize(
    ("field", "value"),
    [("threshold", 1.1), ("silence_threshold_seconds", 0),
     ("min_speech_ms", 0), ("min_silence_ms", 60_001)],
)
def test_provider_vad_tuning_is_validated(field: str, value: object) -> None:
    payload = cascade_policy("provider_vad")
    stt_commit = payload["stt_commit"]
    assert isinstance(stt_commit, dict)
    provider_vad = stt_commit["provider_vad"]
    assert isinstance(provider_vad, dict)
    provider_vad[field] = value
    with pytest.raises(InvalidComponentValue):
        definition("runtime.cascade.execution.defaults").deserialize(payload)


def test_cascade_schema_rejects_interim_preflight() -> None:
    payload = cascade_policy()
    payload["interim_preflight"] = {"enabled": False}
    with pytest.raises(InvalidComponentValue):
        definition("runtime.cascade.execution.defaults").deserialize(payload)


def test_tts_shape_rejects_deferred_fields() -> None:
    tts = definition("runtime.tts.defaults")
    value = tts.deserialize({"deployment_ref": str(uuid4()), "default_voice_id": "voice", "min_sentence_chars": 20})
    tts.validate_deployment(value, deployment(DeploymentKind.TTS))
    with pytest.raises(InvalidComponentValue, match="deployment_kind"):
        tts.validate_deployment(value, deployment(DeploymentKind.STT))
