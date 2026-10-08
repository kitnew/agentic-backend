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


async def started_controller(
    timeout=1.0, *, backend=None, remove_participant=None, backend_timeout=10.0
):
    backend = backend or Backend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(
        backend,
        uuid4(),
        timeout,
        backend_timeout=backend_timeout,
        remove_participant=remove_participant,
    )
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
async def test_unanswered_attempt_has_hard_25_second_deadline_and_cleans_outbound() -> (
    None
):
    removed: list[str] = []

    async def remove(identity: str) -> None:
        removed.append(identity)

    controller, backend, session, result = await started_controller(
        timeout=25.0, remove_participant=remove
    )
    assert controller._deadline is not None
    assert 24.9 < controller._deadline.when() - asyncio.get_running_loop().time() <= 25

    controller._expire(result.attempt_id)
    assert controller.state is HandoffState.TIMED_OUT
    assert not controller.active
    assert controller.waiter is not None
    await controller.waiter
    await controller.close()

    assert removed == [result.participant_identity]
    assert backend.events == [(result.attempt_id, HandoffEvent.TIME_OUT)]
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_deadline_wins_even_before_participant_watcher_starts() -> None:
    backend = Backend()
    session = Session()
    attempt = response()
    backend.states[attempt.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), 25.0)
    await controller.start(attempt, session)  # type: ignore[arg-type]

    controller._expire(attempt.attempt_id)
    assert controller.state is HandoffState.TIMED_OUT
    assert controller.waiter is not None
    await controller.waiter
    await controller.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_failure", ["http_500", "http_timeout"])
async def test_backend_failure_cannot_keep_expired_attempt_dialing(
    backend_failure: str,
) -> None:
    blocked = asyncio.Event()

    class FailingBackend(Backend):
        async def transition_handoff(self, call_id, attempt_id, event):
            if event is HandoffEvent.TIME_OUT:
                if backend_failure == "http_500":
                    raise RuntimeError("HTTP 500")
                await blocked.wait()
            return await super().transition_handoff(call_id, attempt_id, event)

    removed: list[str] = []

    async def remove(identity: str) -> None:
        removed.append(identity)

    controller, _, _, result = await started_controller(
        timeout=25.0,
        backend=FailingBackend(),
        remove_participant=remove,
        backend_timeout=0.001,
    )
    states: list[HandoffState] = []
    controller.set_state_listener(lambda state, _reason: states.append(state))
    controller._expire(result.attempt_id)

    assert controller.state is HandoffState.TIMED_OUT
    assert not controller.active
    assert states == [HandoffState.TIMED_OUT]
    assert controller.waiter is not None
    await controller.waiter
    await controller.close()
    assert removed == [result.participant_identity]
    assert controller.state is HandoffState.TIMED_OUT


@pytest.mark.asyncio
async def test_answer_before_deadline_wins_and_answer_after_deadline_is_ignored() -> (
    None
):
    before, backend, session, attempt = await started_controller(timeout=25.0)
    before_states: list[HandoffState] = []
    before.set_state_listener(lambda state, _reason: before_states.append(state))
    participant = SimpleNamespace(
        identity=attempt.participant_identity,
        attributes={"sip.callStatus": "active"},
    )
    session.room_io.room.emit("participant_connected", participant)
    assert before.state is HandoffState.ANSWERED
    before._expire(attempt.attempt_id)
    assert before.waiter is not None
    await before.waiter
    assert before.state is HandoffState.COMPLETED
    before._expire(attempt.attempt_id)
    assert before.state is HandoffState.COMPLETED
    assert before_states == [HandoffState.ANSWERED, HandoffState.COMPLETED]
    assert HandoffEvent.TIME_OUT not in [event for _, event in backend.events]

    after, backend, session, attempt = await started_controller(timeout=25.0)
    after_states: list[HandoffState] = []
    after.set_state_listener(lambda state, _reason: after_states.append(state))
    after._expire(attempt.attempt_id)
    session.room_io.room.emit(
        "participant_connected",
        SimpleNamespace(
            identity=attempt.participant_identity,
            attributes={"sip.callStatus": "active"},
        ),
    )
    assert after.waiter is not None
    await after.waiter
    await after.close()
    assert after.state is HandoffState.TIMED_OUT
    assert after_states == [HandoffState.TIMED_OUT]
    assert HandoffEvent.ANSWER not in [event for _, event in backend.events]


@pytest.mark.asyncio
async def test_stale_deadline_cannot_expire_new_attempt() -> None:
    controller, backend, session, first = await started_controller(timeout=25.0)
    controller._expire(first.attempt_id)
    assert controller.waiter is not None
    await controller.waiter
    second = response()
    backend.states[second.attempt_id] = HandoffState.DIALING
    await controller.start(second, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    controller._expire(first.attempt_id)
    assert controller.attempt_id == second.attempt_id
    assert controller.state is HandoffState.DIALING
    await controller.cancel("test_cleanup")


@pytest.mark.asyncio
async def test_late_backend_timeout_response_cannot_change_new_attempt() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedBackend(Backend):
        async def transition_handoff(self, call_id, attempt_id, event):
            if event is HandoffEvent.TIME_OUT:
                entered.set()
                await release.wait()
            return await super().transition_handoff(call_id, attempt_id, event)

    backend = DelayedBackend()
    controller, _, session, first = await started_controller(
        timeout=25.0, backend=backend
    )
    controller._expire(first.attempt_id)
    await entered.wait()
    assert controller.waiter is not None
    await controller.waiter
    second = response()
    backend.states[second.attempt_id] = HandoffState.DIALING
    await controller.start(second, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    release.set()
    await asyncio.gather(*controller._pending)
    assert controller.attempt_id == second.attempt_id
    assert controller.state is HandoffState.DIALING
    await controller.cancel("test_cleanup")


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_restore_dialing() -> None:
    async def remove(_identity: str) -> None:
        raise RuntimeError("LiveKit unavailable")

    controller, _, _, attempt = await started_controller(
        timeout=25.0, remove_participant=remove
    )
    controller._expire(attempt.attempt_id)
    assert controller.waiter is not None
    await controller.waiter
    await controller.close()
    assert controller.state is HandoffState.TIMED_OUT
    assert not controller.active


@pytest.mark.asyncio
async def test_failed_start_also_cleans_outbound_participant() -> None:
    removed: list[str] = []

    async def remove(identity: str) -> None:
        removed.append(identity)

    backend = Backend()
    session = Session()
    attempt = response().model_copy(update={"status": HandoffState.FAILED})
    backend.states[attempt.attempt_id] = HandoffState.FAILED
    controller = HandoffController(backend, uuid4(), 25.0, remove_participant=remove)
    await controller.start(attempt, session)  # type: ignore[arg-type]
    await controller.close()

    assert controller.state is HandoffState.FAILED
    assert removed == [attempt.participant_identity]


@pytest.mark.asyncio
async def test_state_listener_tracks_handoff_start_and_timeout() -> None:
    backend = Backend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(backend, uuid4(), 0.001)
    states: list[tuple[HandoffState, str]] = []
    controller.set_state_listener(lambda state, reason: states.append((state, reason)))

    await controller.start(result, session)  # type: ignore[arg-type]
    assert controller.waiter is not None
    await controller.waiter

    assert states == [
        (HandoffState.DIALING, "started"),
        (HandoffState.TIMED_OUT, HandoffEvent.TIME_OUT.value),
    ]
    controller._expire(result.attempt_id)
    assert await controller._transition(result.attempt_id, HandoffEvent.ANSWER) is None
    assert states == [
        (HandoffState.DIALING, "started"),
        (HandoffState.TIMED_OUT, HandoffEvent.TIME_OUT.value),
    ]
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_destination_disconnect_after_answer_closes_transferred_call() -> None:
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
    disconnected: list[tuple[object, str, str, HandoffState]] = []
    completed: list[object] = []
    completed_event = asyncio.Event()

    def on_completed(attempt_id):
        completed.append(attempt_id)
        completed_event.set()

    controller = HandoffController(
        backend,
        uuid4(),
        1.0,
        bridge_disconnected=lambda attempt_id, identity, role, state: (
            disconnected.append((attempt_id, identity, role, state))
        ),
        on_completed=on_completed,
    )
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
    assert disconnected == [
        (
            result.attempt_id,
            result.participant_identity,
            "destination",
            HandoffState.ANSWERED,
        )
    ]
    assert completed == []
    release_answer.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert controller.state is HandoffState.COMPLETED
    await asyncio.wait_for(completed_event.wait(), 1)
    assert completed == [result.attempt_id]
    assert [event for _, event in backend.events] == [
        HandoffEvent.ANSWER,
        HandoffEvent.COMPLETE,
    ]
    assert session.shutdowns == []
    await controller.close()


@pytest.mark.asyncio
async def test_destination_disconnect_before_answer_wins_over_late_active_event() -> (
    None
):
    disconnected: list[object] = []
    completed: list[object] = []
    controller, backend, session, result = await started_controller()
    controller._on_completed = completed.append
    controller._bridge_disconnected = lambda attempt_id, _identity, _role, _state: (
        disconnected.append(attempt_id)
    )
    participant = SimpleNamespace(
        identity=result.participant_identity,
        attributes={"sip.callStatus": "active"},
    )
    room = session.room_io.room
    room.emit("participant_disconnected", participant)
    room.emit("participant_connected", participant)
    assert controller.waiter is not None
    await controller.waiter
    await controller.close()

    assert controller.state is HandoffState.FAILED
    assert backend.events == [(result.attempt_id, HandoffEvent.FAIL)]
    assert disconnected == []
    assert completed == []
    assert session.shutdowns == []


@pytest.mark.asyncio
async def test_completed_destination_disconnect_is_current_attempt_only() -> None:
    disconnected: list[tuple[object, str, str, HandoffState]] = []
    completed: list[object] = []
    completed_event = asyncio.Event()

    def on_completed(attempt_id):
        completed.append(attempt_id)
        completed_event.set()

    backend = Backend()
    session = Session()
    result = response()
    backend.states[result.attempt_id] = HandoffState.DIALING
    controller = HandoffController(
        backend,
        uuid4(),
        25.0,
        bridge_disconnected=lambda attempt_id, identity, role, state: (
            disconnected.append((attempt_id, identity, role, state))
        ),
        on_completed=on_completed,
    )
    await controller.start(result, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)
    participant = SimpleNamespace(
        identity=result.participant_identity,
        attributes={"sip.callStatus": "active"},
    )
    room = session.room_io.room
    room.emit("participant_connected", participant)
    for _ in range(10):
        if controller.state is HandoffState.COMPLETED:
            break
        await asyncio.sleep(0)
    assert controller.state is HandoffState.COMPLETED
    await asyncio.wait_for(completed_event.wait(), 1)
    assert completed == [result.attempt_id]
    assert session.shutdowns == []

    for identity in ("egress", "agent", "unrelated", f"handoff-{uuid4()}"):
        room.emit(
            "participant_disconnected",
            SimpleNamespace(identity=identity, attributes={}),
        )
    assert disconnected == []
    room.emit("participant_disconnected", participant)
    assert disconnected == [
        (
            result.attempt_id,
            result.participant_identity,
            "destination",
            HandoffState.COMPLETED,
        )
    ]
    await controller.close()
    assert completed == [result.attempt_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [HandoffState.ANSWERED, HandoffState.COMPLETED])
@pytest.mark.parametrize(
    ("identity", "role"),
    [("caller", "caller"), ("destination", "destination")],
)
async def test_successful_bridge_identifies_either_human_peer(
    state: HandoffState, identity: str, role: str
) -> None:
    events: list[tuple[object, str, str, HandoffState]] = []
    controller, _, session, result = await started_controller()
    controller._bridge_disconnected = (
        lambda attempt_id, participant, peer_role, current_state: events.append(
            (attempt_id, participant, peer_role, current_state)
        )
    )
    assert controller._attempt is not None
    controller._attempt.state = state
    participant_identity = (
        "caller" if identity == "caller" else result.participant_identity
    )

    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity=participant_identity, attributes={}),
    )

    assert events == [(result.attempt_id, participant_identity, role, state)]
    assert session.shutdowns == []
    await controller.close(cancel=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("old_state", [HandoffState.CANCELED, HandoffState.COMPLETED])
async def test_stale_destination_disconnect_cannot_close_new_attempt(
    old_state: HandoffState,
) -> None:
    disconnected: list[tuple[object, str, str, HandoffState]] = []
    controller, backend, session, first = await started_controller()
    controller._bridge_disconnected = lambda attempt_id, identity, role, state: (
        disconnected.append((attempt_id, identity, role, state))
    )
    old_callback = session.room_io.room.callbacks["participant_disconnected"]
    if old_state is HandoffState.CANCELED:
        await controller.cancel("retry")
    else:
        assert controller._attempt is not None
        controller._attempt.state = HandoffState.COMPLETED
    second = response()
    backend.states[second.attempt_id] = HandoffState.DIALING
    await controller.start(second, session)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    old_callback(SimpleNamespace(identity=first.participant_identity, attributes={}))
    session.room_io.room.emit(
        "participant_disconnected",
        SimpleNamespace(identity=first.participant_identity, attributes={}),
    )
    assert disconnected == []
    assert controller.attempt_id == second.attempt_id
    assert controller.state is HandoffState.DIALING
    await controller.cancel("test_cleanup")


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
async def test_backend_cancellation_failure_does_not_keep_local_attempt_active() -> (
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

    assert await controller.cancel("caller_disconnected")
    assert controller.state is HandoffState.CANCELED
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
