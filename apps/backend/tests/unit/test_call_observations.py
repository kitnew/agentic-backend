from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.router import (
    observe_call,
    start_call_recording,
    stop_call_recording,
)
from backend_core.modules.calls.service import CallSessionService
from contracts import ConversationPersistenceStatus, HandoffState, VoiceCallObservation
from fastapi import FastAPI, HTTPException, Request


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
async def test_agent_relinquish_stops_recording_without_ending_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service()
    service.call.status = CallSessionStatus.CONNECTED
    attempt_id = uuid4()
    stopped: list[object] = []

    class Coordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def stop(self, call_id) -> None:
            stopped.append(call_id)

    monkeypatch.setattr(
        "backend_core.modules.calls.router.RecordingCoordinator", Coordinator
    )

    response = await observe_call(
        service.call.id,
        VoiceCallObservation(
            observation_type="agent_relinquished",
            handoff_attempt_id=attempt_id,
        ),
        service,  # type: ignore[arg-type]
        SimpleNamespace(
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
        ),  # type: ignore[arg-type]
    )

    assert service.observed == [f"relinquished:{attempt_id}:complete"]
    assert response.status.value == "connected"
    assert stopped == [service.call.id]


@pytest.mark.asyncio
async def test_repeated_relinquish_after_sip_disconnect_is_idempotent() -> None:
    attempt_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        status=CallSessionStatus.CONNECTED,
        handoff_attempt_id=attempt_id,
        handoff_state=HandoffState.COMPLETED,
    )
    closed: list[object] = []
    events: list[object] = []

    class Conversations:
        async def close_for_call(self, call_id, status):
            closed.append((call_id, status))

    class Events:
        async def publish(self, event):
            events.append(event)

    service = object.__new__(CallSessionService)

    async def get_for_update(call_id):
        return call

    service._get_for_update = get_for_update  # type: ignore[method-assign]
    service._conversations = Conversations()  # type: ignore[assignment]
    service._events = Events()  # type: ignore[assignment]
    await service.relinquish_agent(
        call.id, attempt_id, ConversationPersistenceStatus.COMPLETE
    )
    assert call.status is CallSessionStatus.CONNECTED
    call.status = CallSessionStatus.ENDED
    await service.relinquish_agent(
        call.id, attempt_id, ConversationPersistenceStatus.COMPLETE
    )
    assert len(closed) == 2
    assert [event.message_type for event in events] == [
        "call.agent_relinquished",
        "call.agent_relinquished",
    ]


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
async def test_early_recording_stop_requires_confirmed_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_id = uuid4()
    stopped: list[object] = []
    call = SimpleNamespace(handoff_state=HandoffState.ANSWERED)

    class Database:
        async def get(self, model, key):
            return call

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def transaction(self):
            return self

    class Coordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def stop(self, requested_call_id) -> None:
            stopped.append(requested_call_id)

    monkeypatch.setattr(
        "backend_core.modules.calls.router.RecordingCoordinator", Coordinator
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                database=Database(),
                livekit=object(),
                settings=SimpleNamespace(
                    call_recording_enabled=True,
                    domain_event_stream="events",
                    command_stream="commands",
                ),
            )
        )
    )
    with pytest.raises(HTTPException) as error:
        await stop_call_recording(call_id, request)  # type: ignore[arg-type]
    assert error.value.status_code == 409
    assert stopped == []

    call.handoff_state = HandoffState.COMPLETED
    await stop_call_recording(call_id, request)  # type: ignore[arg-type]
    await stop_call_recording(call_id, request)  # type: ignore[arg-type]
    assert stopped == [call_id, call_id]


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
