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
        "room_name": "call_test",
        "locale": "sk-SK",
        "timezone": "Europe/Bratislava",
        "agent_display_name": "Amelia",
        "greeting": "Dobry den",
        "conversation_scope": "property_only",
        "prompt": {
            "system_instructions": "Help the guest.",
            "tenant_instructions": "Be concise.",
            "knowledge_text": "Breakfast is at seven.",
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
            "prompt_bundle_revision_id",
            "spreadsheet_id",
            "request_mapping",
            "credential_ref",
        }
        & context.model_dump().keys()
    )

    with pytest.raises(ValidationError):
        VoiceAgentRuntimeContext.model_validate({**payload, "capabilities": {}})


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
