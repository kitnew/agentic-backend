import math

import pytest
from contracts import PlatformRuntimePolicy, TenantRuntimeOverride
from pydantic import ValidationError


def policy() -> dict[str, object]:
    return {
        "llm": {
            "provider": "azure_openai",
            "model": "model-a",
            "temperature": 0,
        },
        "stt": {
            "provider": "elevenlabs",
            "model": "scribe_v2_realtime",
            "server_vad": {
                "silence_threshold_seconds": 0.35,
                "activity_threshold": 0.35,
                "min_speech_ms": 100,
                "min_silence_ms": 350,
            },
        },
        "tts": {
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice_id": "voice-a",
        },
        "local_vad": {
            "min_speech_seconds": 0.05,
            "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "turn": {
            "detection": "stt",
            "min_endpointing_delay_seconds": 0.1,
            "max_endpointing_delay_seconds": 0.7,
        },
    }


def test_valid_complete_platform_runtime_policy() -> None:
    runtime = PlatformRuntimePolicy.model_validate(policy())
    assert (
        PlatformRuntimePolicy.model_validate_json(runtime.model_dump_json()) == runtime
    )


def test_reasoning_and_temperature_are_model_compatible() -> None:
    payload = policy()
    payload["llm"] = {
        "provider": "azure_openai",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "none",
    }
    PlatformRuntimePolicy.model_validate(payload)

    payload["llm"] = {
        "provider": "azure_openai",
        "model": "gpt-4o-mini",
        "temperature": 0,
        "reasoning_effort": "none",
    }
    PlatformRuntimePolicy.model_validate(payload)

    payload["llm"]["reasoning_effort"] = "low"  # type: ignore[index]
    with pytest.raises(ValidationError):
        PlatformRuntimePolicy.model_validate(payload)

    payload["llm"] = {
        "provider": "azure_openai",
        "model": "gpt-5.6-terra",
        "temperature": 0,
        "reasoning_effort": "none",
    }
    with pytest.raises(ValidationError):
        PlatformRuntimePolicy.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unknown",), True),
        (("llm", "provider"), "openai"),
        (("llm", "model"), ""),
        (("tts", "voice_id"), ""),
        (("local_vad", "activation_threshold"), 1.1),
        (("turn", "min_endpointing_delay_seconds"), 0.8),
        (("llm", "temperature"), math.nan),
        (("stt", "server_vad", "silence_threshold_seconds"), math.inf),
    ],
)
def test_invalid_platform_runtime_policy(path: tuple[str, ...], value: object) -> None:
    payload = policy()
    target = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        PlatformRuntimePolicy.model_validate(payload)


def test_tenant_runtime_override_is_strict_and_may_be_empty() -> None:
    assert TenantRuntimeOverride.model_validate({}).model_dump(exclude_none=True) == {}
    assert (
        TenantRuntimeOverride.model_validate(
            {"tts": {"voice_id": "tenant-voice"}}
        ).tts.voice_id
        == "tenant-voice"
    )  # type: ignore[union-attr]
    assert (
        TenantRuntimeOverride.model_validate({"llm": {"model": "model-b"}}).llm.model
        == "model-b"
    )  # type: ignore[union-attr]
    tenant_llm = TenantRuntimeOverride.model_validate(
        {
            "llm": {
                "model": "gpt-4o-mini",
                "temperature": 0,
                "reasoning_effort": "none",
            }
        }
    ).llm
    assert tenant_llm is not None
    assert tenant_llm.temperature == 0
    with pytest.raises(ValidationError):
        TenantRuntimeOverride.model_validate(
            {"llm": {"model": "gpt-5.6-terra", "temperature": 0}}
        )
    with pytest.raises(ValidationError):
        TenantRuntimeOverride.model_validate({"llm": {"model": ""}})
