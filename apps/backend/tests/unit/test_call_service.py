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
from contracts import HumanHandoffRequest


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
async def test_failed_handoff_can_be_retried() -> None:
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        room_name="sip-call-1",
        status=CallSessionStatus.CONNECTED,
        channel=CallChannel.SIP,
        provider="livekit",
        livekit_participant_identity="caller",
        handoff_tool_call_id="old-tool-call",
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

    participant_exists = True

    class LiveKit:
        async def participant_exists(self, room_name, identity):
            assert (room_name, identity) == ("sip-call-1", "handoff-call-1")
            return participant_exists

        async def create_sip_participant(self, **_kwargs):
            return "handoff-call-1", "new-sip-call"

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
    request = HumanHandoffRequest(
        tool_call_id="new-tool-call", destination="reception"
    )
    with pytest.raises(HumanHandoffError, match="call_not_transferable"):
        await service.transfer_to_human(
            call.id,
            request,
            LiveKit(),  # type: ignore[arg-type]
        )

    participant_exists = False
    result = await service.transfer_to_human(
        call.id,
        request,
        LiveKit(),  # type: ignore[arg-type]
    )

    assert result.status == "dialing"
    assert call.handoff_tool_call_id == "new-tool-call"
    assert call.handoff_sip_call_id == "new-sip-call"
