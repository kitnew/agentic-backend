from uuid import uuid4

import pytest
from contracts import (
    CallLifecycleResponse,
    LiveKitJobMetadata,
    VoiceAgentRuntimeContext,
)
from pydantic import ValidationError


def runtime_context() -> dict[str, object]:
    return {
        "call_session_id": str(uuid4()),
        "voice_runtime_revision_id": str(uuid4()),
        "tenant_release_id": str(uuid4()),
        "runtime_bundle_id": str(uuid4()),
        "voice_runtime": {
            "locale": "sk-SK",
            "llm": {"provider": "azure_openai", "model": "model-a", "temperature": 0},
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
        },
        "room_name": "call_test",
        "locale": "sk-SK",
        "timezone": "Europe/Bratislava",
        "agent_display_name": "Amelia",
        "greeting": "Dobry den",
        "conversation_scope": "property_only",
        "prompt": {
            "system_prompt": "Help the guest.",
            "profile_prompt": "Hotel behavior.",
            "tenant_prompt": "Be concise.",
            "knowledge_context": "Breakfast is at seven.",
            "knowledge_base_revision_id": str(uuid4()),
        },
    }


def test_voice_contracts_round_trip_and_forbid_authoring_fields() -> None:
    payload = runtime_context()
    context = VoiceAgentRuntimeContext.model_validate(payload)
    assert (
        VoiceAgentRuntimeContext.model_validate_json(context.model_dump_json())
        == context
    )
    assert (
        not {
            "schema_version",
            "spreadsheet_id",
            "request_mapping",
            "integration_id",
        }
        & context.model_dump().keys()
    )

    with pytest.raises(ValidationError):
        VoiceAgentRuntimeContext.model_validate({**payload, "capabilities": {}})


def test_runtime_handoff_destinations_never_expose_phone_numbers() -> None:
    context = VoiceAgentRuntimeContext.model_validate(
        {
            **runtime_context(),
            "handoff_destinations": {
                "reception": {"description": "Reservations and reception requests"}
            },
        }
    )
    assert context.handoff_destinations["reception"].description.startswith(
        "Reservations"
    )
    with pytest.raises(ValidationError):
        VoiceAgentRuntimeContext.model_validate(
            {
                **runtime_context(),
                "handoff_destinations": {
                    "reception": {
                        "description": "Reception",
                        "phone_number": "+421900000001",
                    }
                },
            }
        )


def test_metadata_contains_only_call_session_id() -> None:
    metadata = LiveKitJobMetadata(call_session_id=uuid4())
    assert set(metadata.model_dump(mode="json")) == {"call_session_id"}
    with pytest.raises(ValidationError):
        LiveKitJobMetadata.model_validate(
            {"call_session_id": str(uuid4()), "tenant_id": str(uuid4())}
        )


def test_lifecycle_response_forbids_extra_fields() -> None:
    response = CallLifecycleResponse(
        call_session_id=uuid4(),
        status="created",
        started_at=None,
        ended_at=None,
        failure_reason=None,
    )
    assert (
        CallLifecycleResponse.model_validate_json(response.model_dump_json())
        == response
    )
    with pytest.raises(ValidationError):
        CallLifecycleResponse.model_validate(
            {**response.model_dump(), "room_name": "secret"}
        )
