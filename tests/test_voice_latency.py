import pytest
from pydantic import ValidationError

from app.voice.latency import VoiceTurnConfig, VoiceTurnOverrides, resolve_voice_turn_config


def test_recommended_defaults_and_sdk_units_are_unambiguous():
    config = VoiceTurnConfig()
    assert config.vad.min_silence_ms == 550
    assert config.endpointing.min_delay_ms == 700
    assert config.stt_segmentation.silence_ms == 400
    assert config.stt_segmentation.threshold == 0.4


def test_tenant_then_debug_precedence_and_immutability():
    tenant = VoiceTurnConfig(endpointing={"min_delay_ms": 600, "max_delay_ms": 2500})
    resolved = resolve_voice_turn_config(
        tenant,
        VoiceTurnOverrides(endpointing={"min_delay_ms": 250}),
    )
    assert resolved.endpointing.min_delay_ms == 250
    assert resolved.endpointing.max_delay_ms == 2500
    with pytest.raises(ValidationError):
        resolved.endpointing.min_delay_ms = 1000


def test_sessions_do_not_share_mutable_configuration():
    first = resolve_voice_turn_config(
        session_overrides=VoiceTurnOverrides(vad={"min_silence_ms": 200})
    )
    second = resolve_voice_turn_config()
    assert first.vad.min_silence_ms == 200
    assert second.vad.min_silence_ms == 550


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": {}},
        {"endpointing": {"min_delay_ms": 8000}},
        {"interruption": {"min_words": -1}},
        {"stt_segmentation": {"threshold": 1.5}},
    ],
)
def test_invalid_and_unknown_overrides_are_rejected(payload):
    with pytest.raises(ValidationError):
        VoiceTurnOverrides.model_validate(payload)


def test_stt_silence_and_probability_threshold_cannot_be_swapped():
    with pytest.raises(ValidationError):
        VoiceTurnConfig(stt_segmentation={"silence_ms": 400, "threshold": 1.5})
