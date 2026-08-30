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
            "interim_preflight": {
                "enabled": False,
                "min_transcript_chars": 20,
                "min_growth_chars": 12,
                "max_generations_per_turn": 2,
            },
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
            "min_sentence_chars": 20,
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


def test_latency_settings_serialize_validate_and_preserve_defaults() -> None:
    payload = policy()
    del payload["tts"]["min_sentence_chars"]  # type: ignore[index]
    runtime = PlatformRuntimePolicy.model_validate(payload)
    assert runtime.tts.min_sentence_chars == 20
    assert (
        PlatformRuntimePolicy.model_validate_json(
            runtime.model_dump_json()
        ).tts.min_sentence_chars
        == 20
    )

    payload = policy()
    payload["tts"]["min_sentence_chars"] = 12  # type: ignore[index]
    payload["stt"]["server_vad"] = {  # type: ignore[index]
        "silence_threshold_seconds": 0.25,
        "activity_threshold": 0.35,
        "min_speech_ms": 100,
        "min_silence_ms": 250,
    }
    candidate = PlatformRuntimePolicy.model_validate(payload)
    assert candidate.tts.min_sentence_chars == 12
    assert candidate.stt.server_vad.silence_threshold_seconds == 0.25
    assert candidate.stt.server_vad.min_silence_ms == 250


def test_interim_preflight_defaults_and_validation() -> None:
    payload = policy()
    del payload["stt"]["interim_preflight"]  # type: ignore[index]
    runtime = PlatformRuntimePolicy.model_validate(payload)
    assert runtime.stt.interim_preflight.model_dump() == {
        "enabled": False,
        "min_transcript_chars": 20,
        "min_growth_chars": 12,
        "max_generations_per_turn": 2,
    }
    assert (
        PlatformRuntimePolicy.model_validate_json(
            runtime.model_dump_json()
        ).stt.interim_preflight
        == runtime.stt.interim_preflight
    )


def test_local_vad_commit_defaults_off_and_serializes_explicit_enablement() -> None:
    baseline = PlatformRuntimePolicy.model_validate(policy())
    assert baseline.stt.local_vad_commit.enabled is False

    payload = policy()
    payload["stt"]["local_vad_commit"] = {"enabled": True}  # type: ignore[index]
    enabled = PlatformRuntimePolicy.model_validate(payload)
    assert enabled.stt.local_vad_commit.enabled is True
    assert (
        PlatformRuntimePolicy.model_validate_json(enabled.model_dump_json()) == enabled
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
        (("tts", "min_sentence_chars"), 2),
        (("tts", "min_sentence_chars"), 201),
        (("local_vad", "activation_threshold"), 1.1),
        (("turn", "min_endpointing_delay_seconds"), 0.8),
        (("llm", "temperature"), math.nan),
        (("stt", "server_vad", "silence_threshold_seconds"), math.inf),
        (("stt", "interim_preflight", "min_transcript_chars"), 2),
        (("stt", "interim_preflight", "min_growth_chars"), 0),
        (("stt", "interim_preflight", "max_generations_per_turn"), 6),
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
