import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from contracts import (
    HandoffAttemptResponse,
    HandoffEvent,
    HandoffState,
    HumanHandoffResponse,
)
from voice_agent.handoff import HandoffController


class Room:
    def __init__(self) -> None:
        self.remote_participants: dict[str, object] = {}
        self.callbacks: dict[str, object] = {}

    def on(self, event, callback) -> None:
        self.callbacks[event] = callback

    def off(self, event, callback) -> None:
        if self.callbacks.get(event) is callback:
            self.callbacks.pop(event)

    def emit(self, event, *args) -> None:
        if event == "participant_connected":
            self.remote_participants[args[0].identity] = args[0]
        elif event == "participant_disconnected":
            self.remote_participants.pop(args[0].identity, None)
        callback = self.callbacks.get(event)
        if callback is not None:
            callback(*args)


class Session:
    def __init__(self) -> None:
        self.room_io = SimpleNamespace(room=Room())
        self.room_io.room.remote_participants["caller"] = SimpleNamespace(
            identity="caller", attributes={}
        )
        self.shutdowns: list[bool] = []

    def shutdown(self, *, drain=True) -> None:
        self.shutdowns.append(drain)


class Backend:
    def __init__(self) -> None:
        self.states: dict[object, HandoffState] = {}
        self.events: list[tuple[object, HandoffEvent]] = []

    async def transition_handoff(self, call_id, attempt_id, event):
        self.events.append((attempt_id, event))
        state = self.states[attempt_id]
        transitions = {
            (HandoffState.DIALING, HandoffEvent.ANSWER): HandoffState.ANSWERED,
            (HandoffState.DIALING, HandoffEvent.FAIL): HandoffState.FAILED,
            (HandoffState.DIALING, HandoffEvent.TIME_OUT): HandoffState.TIMED_OUT,
            (HandoffState.DIALING, HandoffEvent.CANCEL): HandoffState.CANCELED,
            (HandoffState.ANSWERED, HandoffEvent.COMPLETE): HandoffState.COMPLETED,
            (HandoffState.ANSWERED, HandoffEvent.FAIL): HandoffState.FAILED,
            (HandoffState.ANSWERED, HandoffEvent.CANCEL): HandoffState.CANCELED,
        }
        state = transitions.get((state, event), state)
        self.states[attempt_id] = state
        return HandoffAttemptResponse(
            attempt_id=attempt_id,
            state=state,
            participant_identity=f"handoff-{attempt_id}",
        )


def response(attempt_id=None) -> HumanHandoffResponse:
    attempt_id = attempt_id or uuid4()
    return HumanHandoffResponse(
        status=HandoffState.DIALING,
        destination="reception",
        attempt_id=attempt_id,
        participant_identity=f"handoff-{attempt_id}",
    )


async def started_controller(timeout=1.0):
    backend = Backend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), timeout)
    controller.set_caller_identity("caller")
    await controller.start(result, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)
    return controller, backend, session, result


@pytest.mark.asyncio
async def test_answered_attempt_completes_and_relinquishes() -> None:
    controller, backend, session, result = await started_controller()
    participant = SimpleNamespace(
        identity=result.participant_identity,
        attributes={"sip.callStatus": "dialing"},
    )

    session.room_io.room.emit("participant_connected", participant)
    await asyncio.sleep(0)
    assert controller.state is HandoffState.DIALING
    session.room_io.room.emit(
        "participant_attributes_changed", {"sip.callStatus": "active"}, participant
    )
    assert controller.waiter is not None
    await controller.waiter

    assert controller.state is HandoffState.COMPLETED
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.COMPLETE,
    ]
    assert session.shutdowns == [True]


@pytest.mark.asyncio
async def test_caller_disconnect_cancels_and_late_answer_is_ignored() -> None:
    controller, backend, session, result = await started_controller()
    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity="caller", attributes={}),
    )
    assert controller.waiter is not None
    await controller.waiter

    assert controller.state is HandoffState.CANCELED
    assert session.shutdowns == [False]
    assert await controller._transition(result.attempt_id, HandoffEvent.ANSWER) is None
    assert backend.states[result.attempt_id] is HandoffState.CANCELED


@pytest.mark.asyncio
async def test_outbound_disconnect_keeps_agent_owner() -> None:
    controller, _backend, session, result = await started_controller()
    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity=result.participant_identity, attributes={}),
    )
    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity=result.participant_identity, attributes={}),
    )
    assert controller.waiter is not None
    await controller.waiter
    assert controller.state is HandoffState.FAILED
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_voice_agent_shutdown_cancels_attempt_and_consumes_waiter() -> None:
    controller, backend, session, result = await started_controller()

    await controller.close()

    assert controller.state is HandoffState.CANCELED
    assert controller.waiter is not None and controller.waiter.done()
    assert backend.events == [(result.attempt_id, HandoffEvent.CANCEL)]
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_timeout_keeps_agent_owner() -> None:
    controller, _backend, session, _result = await started_controller(timeout=0.001)
    assert controller.waiter is not None
    await controller.waiter
    assert controller.state is HandoffState.TIMED_OUT
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_destination_disconnect_after_answer_prevents_completion() -> None:
    answer_entered = asyncio.Event()
    release_answer = asyncio.Event()

    class GatedBackend(Backend):
        async def transition_handoff(self, call_id, attempt_id, event):
            if event is HandoffEvent.ANSWER:
                answer_entered.set()
                await release_answer.wait()
            return await super().transition_handoff(call_id, attempt_id, event)

    backend = GatedBackend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), 1.0)
    controller.set_caller_identity("caller")
    await controller.start(result, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)
    participant = SimpleNamespace(
        identity=result.participant_identity,
        attributes={"sip.callStatus": "active"},
    )
    session.room_io.room.emit("participant_connected", participant)
    await answer_entered.wait()
    session.room_io.room.emit("participant_disconnected", participant)
    release_answer.set()
    assert controller.waiter is not None
    await controller.waiter

    assert controller.state is HandoffState.FAILED
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.FAIL,
    ]
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_stale_attempt_and_wrong_participant_do_not_affect_current_attempt() -> (
    None
):
    controller, backend, session, first = await started_controller()
    await controller.cancel("retry")
    second = response()
    backend.states[second.attempt_id] = HandoffState.DIALING
    await controller.start(second, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    session.room_io.room.emit(
        "participant_attributes_changed",
        {"sip.callStatus": "active"},
        SimpleNamespace(identity="wrong", attributes={}),
    )
    assert await controller._transition(first.attempt_id, HandoffEvent.ANSWER) is None
    assert controller.attempt_id == second.attempt_id
    assert controller.state is HandoffState.DIALING
    assert session.shutdowns == []
    await controller.cancel("test_cleanup")


@pytest.mark.asyncio
async def test_caller_cancellation_queued_during_answer_wins_before_completion() -> (
    None
):
    answer_entered = asyncio.Event()
    release_answer = asyncio.Event()

    class GatedBackend(Backend):
        async def transition_handoff(self, call_id, attempt_id, event):
            if event is HandoffEvent.ANSWER:
                answer_entered.set()
                await release_answer.wait()
            return await super().transition_handoff(call_id, attempt_id, event)

    backend = GatedBackend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), 1.0)
    controller.set_caller_identity("caller")
    await controller.start(result, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)
    participant = SimpleNamespace(
        identity=result.participant_identity,
        attributes={"sip.callStatus": "active"},
    )
    session.room_io.room.emit("participant_connected", participant)
    await answer_entered.wait()
    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity="caller", attributes={}),
    )
    release_answer.set()
    assert controller.waiter is not None
    await controller.waiter

    assert controller.state is HandoffState.CANCELED
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.CANCEL,
    ]
    assert session.shutdowns == [False]


@pytest.mark.asyncio
async def test_completion_wins_before_late_cancellation() -> None:
    controller, backend, session, result = await started_controller()
    session.room_io.room.emit(
        "participant_connected",
        SimpleNamespace(
            identity=result.participant_identity,
            attributes={"sip.callStatus": "active"},
        ),
    )
    assert controller.waiter is not None
    await controller.waiter

    assert not await controller.cancel("caller_disconnected")
    assert controller.state is HandoffState.COMPLETED
    assert session.shutdowns == [True]
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.COMPLETE,
    ]


@pytest.mark.asyncio
async def test_backend_cancellation_failure_does_not_fabricate_local_terminal_state() -> (
    None
):
    class FailsOnceBackend(Backend):
        failed = False

        async def transition_handoff(self, call_id, attempt_id, event):
            if event is HandoffEvent.CANCEL and not self.failed:
                self.failed = True
                raise RuntimeError("backend unavailable")
            return await super().transition_handoff(call_id, attempt_id, event)

    backend = FailsOnceBackend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), 1.0)
    await controller.start(result, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    assert not await controller.cancel("caller_disconnected")
    assert controller.state is HandoffState.DIALING
    await controller.close()
    assert controller.state is HandoffState.CANCELED


@pytest.mark.asyncio
async def test_caller_absence_prevents_completion_before_disconnect_event_delivery() -> (
    None
):
    controller, backend, session, result = await started_controller()
    session.room_io.room.remote_participants.pop("caller")
    session.room_io.room.emit(
        "participant_connected",
        SimpleNamespace(
            identity=result.participant_identity,
            attributes={"sip.callStatus": "active"},
        ),
    )
    assert controller.waiter is not None
    await controller.waiter

    assert controller.state is HandoffState.CANCELED
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.CANCEL,
    ]
    assert session.shutdowns == [False]
