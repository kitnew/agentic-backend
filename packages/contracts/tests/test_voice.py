from uuid import uuid4

import pytest
from contracts import (
    CallLifecycleResponse,
    HandoffAttemptResponse,
    HandoffState,
    HumanHandoffResponse,
    LiveKitJobMetadata,
    VoiceCallObservation,
    VoiceExecutionContext,
)
from pydantic import ValidationError


def test_voice_execution_context_is_strict_and_semantic() -> None:
    context = VoiceExecutionContext(
        execution_id=uuid4(),
        agent={
            "display_name": "Amelia",
            "role": "Concierge",
            "greeting": "Hello",
            "conversation_scope": "property_only",
        },
        business={
            "name": "Hotel",
            "type": "hotel",
            "phones": [],
            "emails": [],
            "links": [],
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        architecture="cascade",
        prompts={
            "system": "Help",
            "profile": "",
            "interaction": "",
            "tenant": "",
            "knowledge": "",
        },
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


def test_handoff_contracts_require_attempt_correlation() -> None:
    attempt_id = uuid4()
    started = HumanHandoffResponse(
        status=HandoffState.DIALING,
        destination="reception",
        attempt_id=attempt_id,
        participant_identity="handoff-participant",
    )
    transitioned = HandoffAttemptResponse(
        attempt_id=attempt_id,
        state=HandoffState.ANSWERED,
        participant_identity="handoff-participant",
    )
    relinquished = VoiceCallObservation(
        observation_type="agent_relinquished",
        handoff_attempt_id=attempt_id,
    )

    assert started.attempt_id == transitioned.attempt_id
    assert relinquished.handoff_attempt_id == attempt_id
    with pytest.raises(ValidationError, match="handoff_attempt_id"):
        VoiceCallObservation(observation_type="agent_relinquished")
