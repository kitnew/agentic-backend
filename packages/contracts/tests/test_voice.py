from uuid import uuid4

import pytest
from contracts import CallLifecycleResponse, LiveKitJobMetadata, VoiceExecutionContext
from pydantic import ValidationError


def test_voice_execution_context_is_strict_and_semantic() -> None:
    context = VoiceExecutionContext(
        execution_id=uuid4(),
        tenant={"locale": "sk-SK", "timezone": "Europe/Bratislava"},
        agent={"name": "Amelia", "personality": "helpful", "greeting": "Hello"},
        architecture="cascade",
        prompts={"system": "Help", "profile": "", "tenant": "", "knowledge": ""},
        runtime={"stt": {}, "llm": {}, "tts": {}, "realtime": {}},
        actions=[],
        handoff=[{"destination_key": "reception", "description": "Reception"}],
    )
    serialized = context.model_dump(mode="json")
    assert (
        VoiceExecutionContext.model_validate_json(context.model_dump_json()) == context
    )
    assert (
        not {"snapshot_id", "revision_id", "generation", "phone_number"}
        & serialized.keys()
    )
    with pytest.raises(ValidationError):
        VoiceExecutionContext.model_validate(
            {**serialized, "snapshot_id": str(uuid4())}
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
