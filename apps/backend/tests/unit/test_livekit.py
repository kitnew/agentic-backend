from types import SimpleNamespace

import pytest
from backend_core.platform.livekit import LiveKitAdapter
from livekit import api
from livekit.api.twirp_client import TwirpError


@pytest.mark.asyncio
async def test_outbound_sip_participant_joins_existing_room_without_waiting_for_answer() -> (
    None
):
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
    )
    adapter._client = SimpleNamespace(sip=Sip())  # type: ignore[assignment]

    result = await adapter.create_sip_participant(
        room_name="sip-call-1",
        participant_identity="handoff-call-1",
        phone_number="+421900000001",
        caller_number="+421551234567",
        outbound_trunk_id="ST_outbound",
    )

    request = requests[0]
    assert result == ("handoff-call-1", "SCL_handoff")
    assert request.room_name == "sip-call-1"  # type: ignore[union-attr]
    assert request.sip_call_to == "+421900000001"  # type: ignore[union-attr]
    assert request.sip_number == "+421551234567"  # type: ignore[union-attr]
    assert request.sip_trunk_id == "ST_outbound"  # type: ignore[union-attr]
    assert request.wait_until_answered is False  # type: ignore[union-attr]
    assert request.ringing_timeout.seconds == 30  # type: ignore[union-attr]
    assert request.hide_phone_number is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_participant_exists_checks_the_current_room() -> None:
    class Room:
        async def list_participants(self, request):
            assert request.room == "sip-call-1"
            return SimpleNamespace(
                participants=[SimpleNamespace(identity="handoff-call-1")]
            )

    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(room=Room())  # type: ignore[assignment]

    assert await adapter.participant_exists("sip-call-1", "handoff-call-1")
    assert not await adapter.participant_exists("sip-call-1", "missing")


@pytest.mark.asyncio
async def test_remove_participant_is_idempotent_when_already_absent() -> None:
    requests: list[object] = []

    class Room:
        async def remove_participant(self, request):
            requests.append(request)
            raise TwirpError("not_found", "missing", status=404)

    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(room=Room())  # type: ignore[assignment]

    await adapter.remove_participant("sip-call-1", "handoff-call-1")

    assert requests[0].room == "sip-call-1"  # type: ignore[union-attr]
    assert requests[0].identity == "handoff-call-1"  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failures",
    [
        [TwirpError("unavailable", "retry", status=503)],
        [
            TwirpError("unavailable", "retry", status=503),
            TwirpError("internal", "retry", status=500),
        ],
    ],
)
async def test_remove_participant_retries_transient_failures_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    failures: list[TwirpError],
) -> None:
    outcomes: list[Exception | None] = [*failures, None]
    sleeps: list[float] = []

    class Room:
        async def remove_participant(self, _request):
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("backend_core.platform.livekit.asyncio.sleep", sleep)
    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(room=Room())  # type: ignore[assignment]

    await adapter.remove_participant("sip-call-1", "handoff-call-1")

    assert not outcomes
    assert sleeps == [0.2, 0.5][: len(failures)]


@pytest.mark.asyncio
async def test_remove_participant_stops_after_bounded_transient_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    class Room:
        async def remove_participant(self, _request):
            nonlocal attempts
            attempts += 1
            raise TwirpError("unavailable", "retry", status=503)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("backend_core.platform.livekit.asyncio.sleep", sleep)
    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(room=Room())  # type: ignore[assignment]

    with pytest.raises(TwirpError, match="unavailable"):
        await adapter.remove_participant("sip-call-1", "handoff-call-1")

    assert attempts == 3
    assert sleeps == [0.2, 0.5]


@pytest.mark.asyncio
async def test_remove_participant_does_not_retry_non_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class Room:
        async def remove_participant(self, _request):
            nonlocal attempts
            attempts += 1
            raise TwirpError("invalid_argument", "invalid", status=400)

    async def unexpected_sleep(_delay: float) -> None:
        raise AssertionError("non-transient errors must not be retried")

    monkeypatch.setattr("backend_core.platform.livekit.asyncio.sleep", unexpected_sleep)
    adapter = LiveKitAdapter(
        url="ws://livekit:7880",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    adapter._client = SimpleNamespace(room=Room())  # type: ignore[assignment]

    with pytest.raises(TwirpError, match="invalid_argument"):
        await adapter.remove_participant("sip-call-1", "handoff-call-1")

    assert attempts == 1


@pytest.mark.asyncio
async def test_recording_uses_audio_only_room_composite_mp3_without_s3_credentials() -> (
    None
):
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
