from uuid import uuid4

from contracts.runtime_bundle import (
    RuntimeBundlePayload,
    RuntimeBundleProvenance,
    canonical_json_bytes,
    runtime_bundle_content_hash,
)
from contracts.voice import VoiceAgentPrompt
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    LLMRuntimeSettings,
    LocalVADRuntimeSettings,
    STTRuntimeSettings,
    TTSRuntimeSettings,
    TurnRuntimeSettings,
)


def test_canonical_json_bytes_are_stable_for_key_order() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes(
        {"a": 1, "b": 2}
    )


def test_canonical_json_bytes_reject_nan() -> None:
    try:
        canonical_json_bytes({"value": float("nan")})
    except ValueError:
        return
    raise AssertionError("NaN must not be part of a runtime bundle hash")


def test_canonical_json_bytes_requires_json_ready_values() -> None:
    try:
        canonical_json_bytes({"id": uuid4()})
    except TypeError:
        return
    raise AssertionError("callers must use Pydantic JSON mode before hashing")


def test_runtime_bundle_hash_includes_provenance() -> None:
    payload = RuntimeBundlePayload(
        voice_runtime=EffectiveVoiceRuntime(
            llm=LLMRuntimeSettings(provider="azure_openai", model="gpt-4.1"),
            stt=STTRuntimeSettings(
                provider="elevenlabs",
                model="scribe",
                server_vad={
                    "silence_threshold_seconds": 1,
                    "activity_threshold": 0.5,
                    "min_speech_ms": 100,
                    "min_silence_ms": 100,
                },
            ),
            tts=TTSRuntimeSettings(
                provider="elevenlabs", model="flash", voice_id="voice"
            ),
            turn=TurnRuntimeSettings(
                detection="stt",
                min_endpointing_delay_seconds=0.1,
                max_endpointing_delay_seconds=1,
            ),
            local_vad=LocalVADRuntimeSettings(
                min_speech_seconds=0.1,
                min_silence_seconds=0.1,
                activation_threshold=0.5,
            ),
            locale="en",
        ),
        locale="en",
        timezone="Europe/Bucharest",
        agent_display_name="Agent",
        greeting="Hello",
        conversation_scope="property_only",
        prompt=VoiceAgentPrompt(system_prompt="System"),
    )
    first = RuntimeBundleProvenance(
        runtime_revision_id=uuid4(),
        agent_revision_id=uuid4(),
        prompt_revision_id=uuid4(),
        knowledge_revision_id=uuid4(),
        capabilities_revision_id=uuid4(),
        telephony_revision_id=uuid4(),
        platform_runtime_revision_id=uuid4(),
        system_prompt_revision_id=uuid4(),
        profile_prompt_revision_id=uuid4(),
        post_call_revision_id=uuid4(),
    )
    second = first.model_copy(update={"system_prompt_revision_id": uuid4()})

    assert runtime_bundle_content_hash(payload, first) != runtime_bundle_content_hash(
        payload, second
    )
