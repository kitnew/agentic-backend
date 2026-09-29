from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.router import observe_call, start_call_recording
from contracts import VoiceCallObservation
from fastapi import FastAPI, Request


class Service:
    def __init__(self) -> None:
        self.observed: list[str] = []
        self.call = type(
            "Call",
            (),
            {
                "id": uuid4(),
                "status": CallSessionStatus.CREATED,
                "started_at": None,
                "connected_at": None,
                "ended_at": None,
                "failure_reason": None,
            },
        )()

    async def mark_started(self, call_id):
        self.observed.append("started")
        self.call.status = CallSessionStatus.STARTED
        return self.call

    async def mark_connected(self, call_id):
        self.observed.append("connected")
        self.call.status = CallSessionStatus.CONNECTED
        return self.call

    async def relinquish_agent(self, call_id, attempt_id, conversation_status):
        self.observed.append(f"relinquished:{attempt_id}:{conversation_status.value}")
        return self.call


@pytest.mark.asyncio
async def test_runtime_observation_routes_to_authoritative_call_service() -> None:
    service = Service()

    response = await observe_call(
        service.call.id,
        VoiceCallObservation(observation_type="session_started"),
        service,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert service.observed == ["started"]
    assert response.status.value == "started"


@pytest.mark.asyncio
async def test_agent_relinquish_does_not_end_the_call() -> None:
    service = Service()
    service.call.status = CallSessionStatus.CONNECTED
    attempt_id = uuid4()

    response = await observe_call(
        service.call.id,
        VoiceCallObservation(
            observation_type="agent_relinquished",
            handoff_attempt_id=attempt_id,
        ),
        service,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert service.observed == [f"relinquished:{attempt_id}:complete"]
    assert response.status.value == "connected"


@pytest.mark.asyncio
async def test_recording_start_operation_uses_existing_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_id = uuid4()
    started: list[object] = []

    class Coordinator:
        def __init__(self, database, livekit, **kwargs) -> None:
            started.append((database, livekit, kwargs))

        async def ensure(self, requested_call_id) -> None:
            started.append(requested_call_id)

    monkeypatch.setattr(
        "backend_core.modules.calls.router.RecordingCoordinator", Coordinator
    )
    app = FastAPI()
    app.state.database = object()
    app.state.livekit = object()
    app.state.settings = SimpleNamespace(
        call_recording_enabled=True,
        domain_event_stream="events",
        command_stream="commands",
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )

    response = await start_call_recording(call_id, request)

    assert response.status_code == 204
    assert started[0][2] == {
        "event_stream": "events",
        "command_stream": "commands",
        "tracer": None,
    }
    assert started[1] == call_id


@pytest.mark.asyncio
async def test_session_finished_stops_recording_in_terminalization_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class Service:
        call = SimpleNamespace(
            id=uuid4(),
            status=CallSessionStatus.ENDED,
            started_at=None,
            connected_at=None,
            ended_at=None,
            failure_reason=None,
        )

        async def end(self, call_id, conversation_status):
            order.append("call-ended")
            return self.call

    class Coordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def stop(self, call_id) -> None:
            order.append("egress-stop")

    monkeypatch.setattr(
        "backend_core.modules.calls.router.RecordingCoordinator", Coordinator
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    call_recording_enabled=True,
                    domain_event_stream="events",
                    command_stream="commands",
                ),
                database=object(),
                livekit=object(),
            )
        )
    )

    response = await observe_call(
        Service.call.id,
        VoiceCallObservation(observation_type="session_finished"),
        Service(),  # type: ignore[arg-type]
        request,  # type: ignore[arg-type]
    )

    assert response.status.value == "ended"
    assert order == ["call-ended", "egress-stop"]
