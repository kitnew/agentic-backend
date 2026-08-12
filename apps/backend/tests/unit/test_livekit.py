from types import SimpleNamespace

import pytest
from backend_core.platform.livekit import LiveKitAdapter


@pytest.mark.asyncio
async def test_outbound_sip_participant_joins_existing_room_and_waits_for_answer() -> None:
    requests: list[object] = []

    class Sip:
        async def create_sip_participant(self, request):
            requests.append(request)
            return SimpleNamespace(
                participant_identity=request.participant_identity,
                sip_call_id="SCL_handoff",
            )

    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
        sip_outbound_trunk_id="ST_outbound",
    )
    adapter._client = SimpleNamespace(sip=Sip())  # type: ignore[assignment]

    result = await adapter.create_sip_participant(
        room_name="sip-call-1",
        participant_identity="handoff-call-1",
        phone_number="+421900000001",
    )

    request = requests[0]
    assert result == ("handoff-call-1", "SCL_handoff")
    assert request.room_name == "sip-call-1"  # type: ignore[union-attr]
    assert request.sip_call_to == "+421900000001"  # type: ignore[union-attr]
    assert request.sip_trunk_id == "ST_outbound"  # type: ignore[union-attr]
    assert request.wait_until_answered is True  # type: ignore[union-attr]
    assert request.hide_phone_number is True  # type: ignore[union-attr]
