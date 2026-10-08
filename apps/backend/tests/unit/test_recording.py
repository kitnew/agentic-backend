import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.platform.livekit import EgressResult
from backend_core.runtime.finalization.models import CallRecording, RecordingStatus
from backend_core.runtime.finalization.recording import (
    RecordingCoordinator,
    RecordingService,
)
from contracts import HandoffState


def call() -> CallSession:
    return CallSession(
        id=uuid4(),
        tenant_id=uuid4(),
        execution_id=uuid4(),
        channel=CallChannel.WEB,
        direction=CallDirection.INBOUND,
        provider="livekit",
        provider_call_id=str(uuid4()),
        room_name="call-room",
        status=CallSessionStatus.STARTED,
        started_at=datetime.now(UTC),
    )


class Events:
    def __init__(self) -> None:
        self.items = []

    async def publish(self, event) -> None:
        self.items.append(event)


class Session:
    def __init__(self, current_call: CallSession) -> None:
        self.call = current_call
        self.recording: CallRecording | None = None

    async def scalar(self, query):
        if self.recording is None:
            return None
        values = set(query.compile().params.values())
        return (
            self.recording
            if values
            & {
                self.recording.id,
                self.recording.call_id,
                self.recording.egress_id,
                RecordingStatus.READY,
            }
            else None
        )

    async def get(self, model, key):
        if model is CallSession and key == self.call.id:
            return self.call
        return None

    def add(self, value) -> None:
        if isinstance(value, CallRecording):
            self.recording = value

    async def flush(self) -> None:
        return None

    @asynccontextmanager
    async def begin_nested(self):
        yield


@pytest.mark.asyncio
async def test_recording_claim_and_complete_are_idempotent() -> None:
    current_call = call()
    session = Session(current_call)
    events = Events()
    service = RecordingService(session, events)  # type: ignore[arg-type]

    recording, claimed = await service.claim(current_call.id)
    same, claimed_again = await service.claim(current_call.id)
    assert claimed is True
    assert claimed_again is False
    assert same is recording
    assert recording.storage_key == (
        f"recordings/{current_call.tenant_id}/{current_call.id}/{recording.id}.mp3"
    )

    await service.started(
        recording.id,
        EgressResult("EG_1", current_call.room_name, "starting"),
    )
    assert recording.status is RecordingStatus.RECORDING

    complete = EgressResult(
        "EG_1",
        current_call.room_name,
        "complete",
        filename=recording.storage_key,
        size=123,
        duration_ns=2_500_000_000,
    )
    await service.apply(complete)
    await service.apply(complete)

    assert recording.status is RecordingStatus.READY
    assert recording.byte_size == 123
    assert recording.duration_ms == 2500
    assert [event.message_type for event in events.items] == ["recording.ready"]


@pytest.mark.asyncio
async def test_start_failure_is_recording_only_and_emits_once() -> None:
    current_call = call()
    session = Session(current_call)
    events = Events()
    service = RecordingService(session, events)  # type: ignore[arg-type]
    recording, _ = await service.claim(current_call.id)

    await service.fail_start(recording.id, "provider secret must not escape")
    await service.fail_start(recording.id, "duplicate")

    assert recording.status is RecordingStatus.FAILED
    assert recording.error_code == "egress_start_failed"
    assert current_call.status is CallSessionStatus.STARTED
    assert [event.message_type for event in events.items] == ["recording.failed"]


@pytest.mark.asyncio
async def test_coordinator_provider_failure_does_not_raise_or_fail_call() -> None:
    current_call = call()
    session = Session(current_call)

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield session

    class LiveKit:
        async def start_call_recording(self, **kwargs):
            raise RuntimeError("egress unavailable")

    coordinator = RecordingCoordinator(
        Database(),  # type: ignore[arg-type]
        LiveKit(),  # type: ignore[arg-type]
        event_stream="events",
        command_stream="commands",
    )
    await coordinator.ensure(current_call.id)

    assert session.recording is not None
    assert session.recording.status is RecordingStatus.FAILED
    assert current_call.status is CallSessionStatus.STARTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handoff_state",
    [None, HandoffState.FAILED, HandoffState.TIMED_OUT, HandoffState.CANCELED],
)
async def test_coordinator_ensure_starts_egress_once(handoff_state) -> None:
    current_call = call()
    current_call.handoff_state = handoff_state
    session = Session(current_call)
    starts: list[tuple[str, str]] = []

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield session

    class LiveKit:
        async def start_call_recording(self, *, room_name: str, storage_key: str):
            starts.append((room_name, storage_key))
            return EgressResult("EG_once", room_name, "starting")

    coordinator = RecordingCoordinator(
        Database(),  # type: ignore[arg-type]
        LiveKit(),  # type: ignore[arg-type]
        event_stream="events",
        command_stream="commands",
    )
    await coordinator.ensure(current_call.id)
    await coordinator.ensure(current_call.id)

    assert len(starts) == 1
    assert starts[0][0] == current_call.room_name


@pytest.mark.asyncio
async def test_coordinator_stops_egress_and_applies_final_result_once() -> None:
    current_call = call()
    session = Session(current_call)
    stop_requests: list[str] = []

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield session

    class LiveKit:
        async def start_call_recording(self, *, room_name: str, storage_key: str):
            return EgressResult("EG_stop", room_name, "starting")

        async def stop_call_recording(self, egress_id: str):
            stop_requests.append(egress_id)
            assert session.recording is not None
            return EgressResult(
                egress_id,
                current_call.room_name,
                "complete",
                filename=session.recording.storage_key,
                size=123,
                duration_ns=2_500_000_000,
            )

    coordinator = RecordingCoordinator(
        Database(),  # type: ignore[arg-type]
        LiveKit(),  # type: ignore[arg-type]
        event_stream="events",
        command_stream="commands",
    )
    await coordinator.ensure(current_call.id)
    await coordinator.stop(current_call.id)
    await coordinator.stop(current_call.id)

    assert stop_requests == ["EG_stop"]
    assert session.recording is not None
    assert session.recording.status is RecordingStatus.READY


@pytest.mark.asyncio
async def test_handoff_completion_during_egress_start_stops_after_id_is_saved() -> None:
    current_call = call()
    session = Session(current_call)
    starting = asyncio.Event()
    release_start = asyncio.Event()
    stopped: list[str] = []

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield session

    class LiveKit:
        async def start_call_recording(self, *, room_name: str, storage_key: str):
            starting.set()
            await release_start.wait()
            return EgressResult("EG_race", room_name, "starting")

        async def stop_call_recording(self, egress_id: str):
            stopped.append(egress_id)
            assert session.recording is not None
            return EgressResult(
                egress_id,
                current_call.room_name,
                "complete",
                filename=session.recording.storage_key,
                size=123,
                duration_ns=1_000_000_000,
            )

    coordinator = RecordingCoordinator(
        Database(),  # type: ignore[arg-type]
        LiveKit(),  # type: ignore[arg-type]
        event_stream="events",
        command_stream="commands",
    )
    start = asyncio.create_task(coordinator.ensure(current_call.id))
    await starting.wait()
    current_call.handoff_state = HandoffState.COMPLETED
    await coordinator.stop(current_call.id)
    assert stopped == []
    release_start.set()
    await start
    await coordinator.stop(current_call.id)
    assert stopped == ["EG_race"]
    assert session.recording is not None
    assert session.recording.status is RecordingStatus.READY


@pytest.mark.asyncio
async def test_reconciliation_stops_active_egress_for_completed_handoff() -> None:
    current_call = call()
    current_call.handoff_state = HandoffState.COMPLETED
    recording = CallRecording(
        id=uuid4(),
        tenant_id=current_call.tenant_id,
        call_id=current_call.id,
        provider="livekit_egress",
        status=RecordingStatus.RECORDING,
        egress_id="EG_stale",
        storage_key="recordings/stale.mp3",
        start_requested_at=datetime.now(UTC),
    )
    stopped: list[object] = []

    class Session:
        async def execute(self, query):
            return [
                (
                    recording.id,
                    recording.call_id,
                    recording.egress_id,
                    recording.storage_key,
                    current_call.room_name,
                )
            ]

        async def get(self, model, key):
            return recording if model is CallRecording and key == recording.id else None

    class Database:
        @asynccontextmanager
        async def transaction(self):
            yield Session()

    class LiveKit:
        async def get_egress(self, egress_id):
            return EgressResult(egress_id, current_call.room_name, "active")

    coordinator = RecordingCoordinator(
        Database(),  # type: ignore[arg-type]
        LiveKit(),  # type: ignore[arg-type]
        event_stream="events",
        command_stream="commands",
    )

    class Service:
        async def apply(self, result):
            return None

    async def stop(call_id):
        stopped.append(call_id)

    coordinator._service = lambda session: Service()  # type: ignore[method-assign]
    coordinator.stop = stop  # type: ignore[method-assign]
    await coordinator.reconcile_stale(datetime.now(UTC), 10)
    assert stopped == [current_call.id]
