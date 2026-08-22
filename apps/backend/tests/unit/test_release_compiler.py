from uuid import uuid4

from backend_core.modules.tenants.release_compiler import compile_runtime_bundle
from contracts.runtime_bundle import RuntimeBundlePayload, RuntimeBundleProvenance
from contracts.voice import VoiceAgentPrompt
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    LLMRuntimeSettings,
    LocalVADRuntimeSettings,
    STTRuntimeSettings,
    TTSRuntimeSettings,
    TurnRuntimeSettings,
)


def _payload() -> RuntimeBundlePayload:
    return RuntimeBundlePayload(
        voice_runtime=EffectiveVoiceRuntime(
            llm=LLMRuntimeSettings(
                provider="azure_openai", model="gpt-4.1", temperature=0.1
            ),
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
        prompt=VoiceAgentPrompt(
            system_prompt="System", knowledge_base_revision_id=uuid4()
        ),
    )


def _provenance() -> RuntimeBundleProvenance:
    return RuntimeBundleProvenance(
        runtime_revision_id=uuid4(),
        agent_revision_id=uuid4(),
        prompt_revision_id=uuid4(),
        knowledge_revision_id=uuid4(),
        capabilities_revision_id=uuid4(),
        telephony_revision_id=uuid4(),
        platform_runtime_revision_id=uuid4(),
        system_prompt_revision_id=uuid4(),
        profile_prompt_revision_id=uuid4(),
    )


def test_compiler_is_deterministic_without_release_identity() -> None:
    first = compile_runtime_bundle(
        tenant_id=uuid4(),
        payload=_payload(),
        provenance=_provenance(),
        compiler_build_id="test",
    )
    second = compile_runtime_bundle(
        tenant_id=first.bundle.tenant_id,
        payload=first.bundle.payload,
        provenance=first.bundle.provenance,
        compiler_build_id="test",
    )

    assert first.bundle.content_hash == second.bundle.content_hash
    assert first.bundle.id != second.bundle.id
