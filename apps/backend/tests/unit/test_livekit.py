from types import SimpleNamespace

import pytest
from backend_core.platform.livekit import LiveKitAdapter
from livekit import api


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


@pytest.mark.asyncio
async def test_recording_uses_audio_only_room_composite_mp3_without_s3_credentials() -> None:
    requests: list[object] = []

    class Egress:
        async def start_room_composite_egress(self, request):
            requests.append(request)
            return api.EgressInfo(
                egress_id="EG_recording",
                room_name=request.room_name,
                status=api.EgressStatus.EGRESS_STARTING,
            )

    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(egress=Egress())  # type: ignore[assignment]

    result = await adapter.start_call_recording(
        room_name="call-1", storage_key="recordings/t/c/r.mp3"
    )

    request = requests[0]
    output = request.file_outputs[0]  # type: ignore[union-attr]
    assert result.egress_id == "EG_recording"
    assert result.status == "starting"
    assert request.audio_only is True  # type: ignore[union-attr]
    assert request.layout == ""  # type: ignore[union-attr]
    assert request.custom_base_url == ""  # type: ignore[union-attr]
    assert output.file_type == api.EncodedFileType.MP3
    assert output.filepath == "recordings/t/c/r.mp3"
    assert output.disable_manifest is True
    assert not output.HasField("s3")
