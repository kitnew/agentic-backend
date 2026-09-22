from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    HumanHandoffError,
)
from backend_core.modules.calls.models import CallChannel, CallSessionStatus
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.tenants.models import TenantStatus
from contracts import HandoffEvent, HandoffState, HumanHandoffRequest


class ControlPlane:
    async def create_execution(self, *_args, **_kwargs):
        request = httpx.Request("POST", "http://control-plane/internal/v1/executions")
        response = httpx.Response(422, request=request)
        raise httpx.HTTPStatusError(
            "configuration rejected", request=request, response=response
        )


@pytest.mark.asyncio
async def test_execution_resolution_422_becomes_configuration_unavailable() -> None:
    service = CallSessionService(
        None,
        None,
        None,
        None,
        None,
        ControlPlane(),  # type: ignore[arg-type]
    )

    with pytest.raises(CallSessionConfigUnavailableError):
        await service._execution(uuid4(), "test-execution")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_state",
    [HandoffState.FAILED, HandoffState.TIMED_OUT, HandoffState.CANCELED],
)
async def test_terminal_handoff_can_be_retried(terminal_state: HandoffState) -> None:
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        channel=CallChannel.SIP,
        provider="livekit",
        livekit_participant_identity="caller",
        handoff_tool_call_id="old-tool-call",
        handoff_attempt_id=uuid4(),
        handoff_state=HandoffState.DIALING,
        handoff_destination="reception",
        handoff_participant_identity="handoff-call-1",
        handoff_sip_call_id="old-sip-call",
    )

    class Calls:
        async def get_for_update(self, call_id):
            assert call_id == call.id
            return call

        async def flush(self):
            pass

    class Routes:
        async def platform(self):
            return SimpleNamespace(
                outbound_trunk_id="ST_outbound",
                provisioning_status=SimpleNamespace(value="ready"),
            )

    class Tenants:
        async def get(self, tenant_id):
            assert tenant_id == call.tenant_id
            return SimpleNamespace(status=TenantStatus.ACTIVE)

    class LiveKit:
        async def remove_participant(self, _room_name, _identity):
            pass

        async def create_sip_participant(self, **kwargs):
            return kwargs["participant_identity"], "new-sip-call"

    service = CallSessionService(
        Calls(),  # type: ignore[arg-type]
        Routes(),  # type: ignore[arg-type]
        Tenants(),  # type: ignore[arg-type]
        None,
        None,
        None,  # type: ignore[arg-type]
    )

    async def pinned_handoff(_call, _destination):
        return "+421551234567", SimpleNamespace(phone_number="+421900000001")

    service._pinned_handoff = pinned_handoff  # type: ignore[method-assign]
    request = HumanHandoffRequest(tool_call_id="new-tool-call", destination="reception")
    with pytest.raises(HumanHandoffError, match="call_not_transferable"):
        await service.transfer_to_human(
            call.id,
            request,
            LiveKit(),  # type: ignore[arg-type]
        )

    call.handoff_state = HandoffState.ANSWERED
    with pytest.raises(HumanHandoffError, match="call_not_transferable"):
        await service.transfer_to_human(
            call.id,
            request,
            LiveKit(),  # type: ignore[arg-type]
        )

    call.handoff_state = HandoffState.COMPLETED
    with pytest.raises(HumanHandoffError, match="call_not_transferable"):
        await service.transfer_to_human(
            call.id,
            request,
            LiveKit(),  # type: ignore[arg-type]
        )

    call.handoff_state = terminal_state
    old_attempt_id = call.handoff_attempt_id
    result = await service.transfer_to_human(
        call.id,
        request,
        LiveKit(),  # type: ignore[arg-type]
    )

    assert result.status == "dialing"
    assert result.attempt_id != old_attempt_id
    assert call.handoff_tool_call_id == "new-tool-call"
    assert call.handoff_sip_call_id == "new-sip-call"


@pytest.mark.asyncio
async def test_new_handoff_is_rejected_when_old_participant_cleanup_fails() -> None:
    old_attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        channel=CallChannel.SIP,
        provider="livekit",
        livekit_participant_identity="caller",
        handoff_tool_call_id="old-tool-call",
        handoff_attempt_id=old_attempt_id,
        handoff_state=HandoffState.CANCELED,
        handoff_destination="reception",
        handoff_participant_identity="old-handoff",
        handoff_sip_call_id="old-sip-call",
    )

    class Calls:
        async def get_for_update(self, _call_id):
            return call

    class LiveKit:
        created = False

        async def remove_participant(self, _room_name, _identity):
            raise RuntimeError("cleanup exhausted")

        async def create_sip_participant(self, **_kwargs):
            self.created = True

    livekit = LiveKit()
    service = CallSessionService(
        Calls(),  # type: ignore[arg-type]
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )

    with pytest.raises(HumanHandoffError, match="transfer_failed"):
        await service.transfer_to_human(
            call.id,
            HumanHandoffRequest(tool_call_id="new-tool", destination="reception"),
            livekit,  # type: ignore[arg-type]
        )

    assert call.handoff_attempt_id == old_attempt_id
    assert call.handoff_state is HandoffState.CANCELED
    assert not livekit.created


@pytest.mark.asyncio
async def test_handoff_transitions_are_correlated_terminal_and_idempotent() -> None:
    attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        handoff_attempt_id=attempt_id,
        handoff_state=HandoffState.DIALING,
        handoff_participant_identity="handoff-call-1",
    )

    class Calls:
        async def get_for_update(self, call_id):
            assert call_id == call.id
            return call

        async def flush(self):
            pass

    removed: list[tuple[str, str]] = []

    class LiveKit:
        async def remove_participant(self, room_name, identity):
            removed.append((room_name, identity))

    service = CallSessionService(
        Calls(),
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )
    livekit = LiveKit()

    canceled = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.CANCEL,
        livekit,  # type: ignore[arg-type]
    )
    late_answer = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.ANSWER,
        livekit,  # type: ignore[arg-type]
    )
    duplicate = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.CANCEL,
        livekit,  # type: ignore[arg-type]
    )

    assert canceled.state is HandoffState.CANCELED
    assert late_answer.state is HandoffState.CANCELED
    assert duplicate.state is HandoffState.CANCELED
    assert removed == [
        ("sip-call-1", "handoff-call-1"),
        ("sip-call-1", "handoff-call-1"),
    ]
    with pytest.raises(HumanHandoffError, match="handoff_attempt_mismatch"):
        await service.transition_handoff(
            call.id,
            uuid4(),
            HandoffEvent.CANCEL,
            livekit,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_resurrect_canceled_handoff() -> None:
    attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        handoff_attempt_id=attempt_id,
        handoff_state=HandoffState.DIALING,
        handoff_participant_identity="handoff-call-1",
    )

    class Calls:
        async def get_for_update(self, _call_id):
            return call

        async def flush(self):
            pass

    class LiveKit:
        async def remove_participant(self, _room_name, _identity):
            raise RuntimeError("provider unavailable")

    service = CallSessionService(
        Calls(),
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )
    result = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.CANCEL,
        LiveKit(),  # type: ignore[arg-type]
    )

    assert result.state is HandoffState.CANCELED
    assert call.handoff_state is HandoffState.CANCELED


@pytest.mark.asyncio
async def test_handoff_completion_requires_answered_attempt_and_live_call() -> None:
    attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        handoff_attempt_id=attempt_id,
        handoff_state=HandoffState.DIALING,
        handoff_participant_identity="handoff-call-1",
    )

    class Calls:
        async def get_for_update(self, _call_id):
            return call

        async def flush(self):
            pass

    service = CallSessionService(
        Calls(),
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )
    livekit = SimpleNamespace()
    with pytest.raises(HumanHandoffError, match="handoff_transition_conflict"):
        await service.transition_handoff(
            call.id,
            attempt_id,
            HandoffEvent.COMPLETE,
            livekit,  # type: ignore[arg-type]
        )

    answered = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.ANSWER,
        livekit,  # type: ignore[arg-type]
    )
    assert answered.state is HandoffState.ANSWERED
    call.status = CallSessionStatus.ENDED
    with pytest.raises(HumanHandoffError, match="handoff_transition_conflict"):
        await service.transition_handoff(
            call.id,
            attempt_id,
            HandoffEvent.COMPLETE,
            livekit,  # type: ignore[arg-type]
        )

    call.status = CallSessionStatus.CONNECTED
    completed = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.COMPLETE,
        livekit,  # type: ignore[arg-type]
    )
    late_cancel = await service.transition_handoff(
        call.id,
        attempt_id,
        HandoffEvent.CANCEL,
        livekit,  # type: ignore[arg-type]
    )
    assert completed.state is HandoffState.COMPLETED
    assert late_cancel.state is HandoffState.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        HandoffEvent.CANCEL,
        HandoffEvent.TIME_OUT,
        HandoffEvent.FAIL,
        HandoffEvent.ANSWER,
        HandoffEvent.COMPLETE,
    ],
)
async def test_completed_handoff_ignores_every_late_event(
    event: HandoffEvent,
) -> None:
    attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        handoff_attempt_id=attempt_id,
        handoff_state=HandoffState.COMPLETED,
        handoff_participant_identity="handoff-call-1",
    )

    class Calls:
        async def get_for_update(self, _call_id):
            return call

    class LiveKit:
        async def remove_participant(self, _room_name, _identity):
            raise AssertionError("completed participant must not be removed")

    service = CallSessionService(
        Calls(),  # type: ignore[arg-type]
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )

    result = await service.transition_handoff(
        call.id,
        attempt_id,
        event,
        LiveKit(),  # type: ignore[arg-type]
    )

    assert result.state is HandoffState.COMPLETED
    assert call.handoff_state is HandoffState.COMPLETED
