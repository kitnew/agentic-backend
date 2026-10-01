import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from contracts import HandoffEvent, HandoffState, HumanHandoffResponse
from livekit import agents, rtc

from voice_agent.backend import BackendClient

logger = logging.getLogger(__name__)

ACTIVE_STATES = {HandoffState.DIALING, HandoffState.ANSWERED}


@dataclass
class HandoffAttempt:
    id: UUID
    participant_identity: str
    state: HandoffState
    destination: str = ""
    events: asyncio.Queue[HandoffEvent] | None = None


class HandoffController:
    def __init__(
        self,
        backend: BackendClient,
        call_id: UUID,
        timeout: float,
        *,
        backend_timeout: float = 10.0,
        remove_participant: Callable[[str], Awaitable[None]] | None = None,
        bridge_disconnected: Callable[[UUID, str, str, HandoffState], None]
        | None = None,
    ) -> None:
        self._backend = backend
        self._call_id = call_id
        self._timeout = timeout
        self._backend_timeout = backend_timeout
        self._remove_participant = remove_participant
        self._bridge_disconnected = bridge_disconnected
        self._lock = asyncio.Lock()
        self._attempt: HandoffAttempt | None = None
        self._waiter: asyncio.Task[None] | None = None
        self._deadline: asyncio.TimerHandle | None = None
        self._pending: set[asyncio.Task[None]] = set()
        self._caller_identity: str | None = None
        self._state_listener: Callable[[HandoffState, str], None] | None = None

    def set_state_listener(self, listener: Callable[[HandoffState, str], None]) -> None:
        self._state_listener = listener

    def _notify_state(self, state: HandoffState, reason: str) -> None:
        if self._state_listener is not None:
            self._state_listener(state, reason)

    @property
    def attempt_id(self) -> UUID | None:
        return self._attempt.id if self._attempt is not None else None

    @property
    def destination(self) -> str | None:
        return self._attempt.destination if self._attempt is not None else None

    @property
    def participant_identity(self) -> str | None:
        return self._attempt.participant_identity if self._attempt is not None else None

    @property
    def caller_identity(self) -> str | None:
        return self._caller_identity

    @property
    def state(self) -> HandoffState | None:
        return self._attempt.state if self._attempt is not None else None

    @property
    def completed(self) -> bool:
        return self.state is HandoffState.COMPLETED

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def waiter(self) -> asyncio.Task[None] | None:
        return self._waiter

    def set_caller_identity(self, identity: str) -> None:
        self._caller_identity = identity

    def bridge_peer_disconnected(self, identity: str) -> bool:
        attempt = self._attempt
        if attempt is None or attempt.state not in {
            HandoffState.ANSWERED,
            HandoffState.COMPLETED,
        }:
            return False
        if identity == self._caller_identity:
            role = "caller"
        elif identity == attempt.participant_identity:
            role = "destination"
        else:
            return False
        if self._bridge_disconnected is not None:
            self._bridge_disconnected(attempt.id, identity, role, attempt.state)
        return True

    def _cancel_deadline(self) -> None:
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None

    def _terminal(
        self, attempt: HandoffAttempt, state: HandoffState, reason: str
    ) -> bool:
        if self._attempt is not attempt or attempt.state not in ACTIVE_STATES:
            return False
        attempt.state = state
        self._cancel_deadline()
        self._notify_state(state, reason)
        return True

    def _finish_later(
        self, attempt: HandoffAttempt, event: HandoffEvent
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(self._finish_terminal(attempt, event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def _finish_terminal(
        self, attempt: HandoffAttempt, event: HandoffEvent
    ) -> None:
        async def cleanup() -> None:
            if self._remove_participant is None:
                return
            try:
                await asyncio.wait_for(
                    self._remove_participant(attempt.participant_identity),
                    self._backend_timeout,
                )
            except Exception:
                logger.exception("Handoff outbound participant cleanup failed")

        async def persist() -> None:
            try:
                await asyncio.wait_for(
                    self._backend.transition_handoff(self._call_id, attempt.id, event),
                    self._backend_timeout,
                )
            except Exception:
                logger.exception("Handoff terminal state persistence failed")

        await asyncio.gather(cleanup(), persist())

    def _expire(self, attempt_id: UUID) -> None:
        attempt = self._attempt
        if (
            attempt is None
            or attempt.id != attempt_id
            or attempt.state is not HandoffState.DIALING
        ):
            return
        if not self._terminal(
            attempt, HandoffState.TIMED_OUT, HandoffEvent.TIME_OUT.value
        ):
            return
        self._finish_later(attempt, HandoffEvent.TIME_OUT)
        if attempt.events is not None:
            attempt.events.put_nowait(HandoffEvent.TIME_OUT)

    def _answer(self, attempt: HandoffAttempt) -> bool:
        if self._attempt is not attempt or attempt.state is not HandoffState.DIALING:
            return False
        attempt.state = HandoffState.ANSWERED
        self._cancel_deadline()
        self._notify_state(HandoffState.ANSWERED, HandoffEvent.ANSWER.value)
        return True

    async def start(
        self, response: HumanHandoffResponse, session: agents.AgentSession
    ) -> None:
        async with self._lock:
            if self.state in ACTIVE_STATES:
                if self.attempt_id == response.attempt_id:
                    return
                raise RuntimeError("handoff already in progress")
        await self._stop_waiter()
        async with self._lock:
            self._cancel_deadline()
            self._attempt = HandoffAttempt(
                response.attempt_id,
                response.participant_identity,
                response.status,
                response.destination,
            )
            if response.status is HandoffState.DIALING:
                self._deadline = asyncio.get_running_loop().call_later(
                    self._timeout, self._expire, response.attempt_id
                )
                self._waiter = asyncio.create_task(
                    self._watch(session, response.attempt_id)
                )
            self._notify_state(response.status, "started")
            if response.status is HandoffState.FAILED:
                self._finish_later(self._attempt, HandoffEvent.FAIL)

    async def cancel(self, reason: str) -> bool:
        attempt = self._attempt
        if attempt is None or not self._terminal(
            attempt, HandoffState.CANCELED, reason
        ):
            return False
        finish = self._finish_later(attempt, HandoffEvent.CANCEL)
        await self._stop_waiter()
        await finish
        return True

    async def close(self, *, cancel: bool = True) -> None:
        if cancel:
            await self.cancel("voice_agent_shutdown")
        await self._stop_waiter()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    async def _stop_waiter(self) -> None:
        waiter = self._waiter
        if waiter is None or waiter.done() or waiter is asyncio.current_task():
            return
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)

    async def _transition(
        self, attempt_id: UUID, event: HandoffEvent
    ) -> HandoffState | None:
        async with self._lock:
            attempt = self._attempt
            if (
                attempt is None
                or attempt.id != attempt_id
                or attempt.state not in ACTIVE_STATES
            ):
                logger.info(
                    "Stale handoff event ignored",
                    extra={
                        "call_session_id": str(self._call_id),
                        "handoff_attempt_id": str(attempt_id),
                        "reason": event.value,
                    },
                )
                return None
            response = await asyncio.wait_for(
                self._backend.transition_handoff(self._call_id, attempt_id, event),
                self._backend_timeout,
            )
            if (
                self._attempt is not attempt
                or attempt.state not in ACTIVE_STATES
                or response.attempt_id != attempt_id
                or response.participant_identity != attempt.participant_identity
            ):
                return None
            if response.state is HandoffState.ANSWERED and event is HandoffEvent.ANSWER:
                return response.state
            if response.state is HandoffState.COMPLETED:
                self._terminal(attempt, response.state, event.value)
            elif response.state not in ACTIVE_STATES and self._terminal(
                attempt, response.state, event.value
            ):
                self._finish_later(attempt, HandoffEvent.FAIL)
            return response.state

    async def _watch(self, session: agents.AgentSession, attempt_id: UUID) -> None:
        room = session.room_io.room
        events: asyncio.Queue[HandoffEvent] = asyncio.Queue()
        bridge_closed = asyncio.Event()
        attempt = self._attempt
        if (
            attempt is None
            or attempt.id != attempt_id
            or attempt.state is HandoffState.TIMED_OUT
        ):
            return
        attempt.events = events

        def participant_connected(participant: rtc.RemoteParticipant) -> None:
            if (
                participant.identity == attempt.participant_identity
                and participant.attributes.get("sip.callStatus") == "active"
                and self._answer(attempt)
            ):
                events.put_nowait(HandoffEvent.ANSWER)

        def participant_attributes_changed(
            changed_attributes: dict[str, str], participant: rtc.Participant
        ) -> None:
            if (
                participant.identity == attempt.participant_identity
                and changed_attributes.get("sip.callStatus") == "active"
                and self._answer(attempt)
            ):
                events.put_nowait(HandoffEvent.ANSWER)

        def participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            if self._attempt is not attempt:
                return
            if self.bridge_peer_disconnected(participant.identity):
                bridge_closed.set()
            elif participant.identity == attempt.participant_identity:
                if self._terminal(
                    attempt, HandoffState.FAILED, HandoffEvent.FAIL.value
                ):
                    self._finish_later(attempt, HandoffEvent.FAIL)
                    events.put_nowait(HandoffEvent.FAIL)
            elif participant.identity == self._caller_identity:
                events.put_nowait(HandoffEvent.CANCEL)

        room.on("participant_connected", participant_connected)
        room.on("participant_attributes_changed", participant_attributes_changed)
        room.on("participant_disconnected", participant_disconnected)
        try:
            participant = room.remote_participants.get(attempt.participant_identity)
            if participant is not None:
                participant_connected(participant)
            event = await events.get()
            if event is HandoffEvent.TIME_OUT:
                return
            if event is HandoffEvent.CANCEL:
                await self.cancel("caller_disconnected")
                session.shutdown(drain=False)
                return
            if event is HandoffEvent.FAIL:
                if self._terminal(attempt, HandoffState.FAILED, event.value):
                    await self._finish_later(attempt, event)
                return
            state = await self._transition(attempt_id, event)
            if state is HandoffState.COMPLETED:
                if self._bridge_disconnected is None:
                    session.shutdown(drain=True)
                else:
                    await bridge_closed.wait()
                return
            if state is not HandoffState.ANSWERED:
                if self._terminal(attempt, HandoffState.FAILED, "answer_rejected"):
                    self._finish_later(attempt, HandoffEvent.FAIL)
                return
            # Room presence closes the event-delivery gap; Backend serialization
            # remains authoritative when cancellation and completion race.
            if (
                self._caller_identity is not None
                and self._caller_identity not in room.remote_participants
            ):
                await self.cancel("caller_absent_after_answer")
                session.shutdown(drain=False)
                return
            while not events.empty():
                event = events.get_nowait()
                if event is HandoffEvent.ANSWER:
                    continue
                if event is HandoffEvent.CANCEL:
                    await self.cancel("caller_disconnected")
                    session.shutdown(drain=False)
                elif event is HandoffEvent.FAIL:
                    if self._terminal(attempt, HandoffState.FAILED, event.value):
                        await self._finish_later(attempt, event)
                return
            interrupt = asyncio.create_task(events.get())
            completion = asyncio.create_task(
                self._transition(attempt_id, HandoffEvent.COMPLETE)
            )
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {completion, interrupt}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if completion in done:
                        if completion.result() is HandoffState.COMPLETED:
                            if self._bridge_disconnected is None:
                                session.shutdown(drain=True)
                            else:
                                await bridge_closed.wait()
                        elif self._terminal(
                            attempt, HandoffState.FAILED, "completion_rejected"
                        ):
                            self._finish_later(attempt, HandoffEvent.FAIL)
                        return
                    event = interrupt.result()
                    if event is HandoffEvent.ANSWER:
                        interrupt = asyncio.create_task(events.get())
                        continue
                    if event is HandoffEvent.CANCEL:
                        await self.cancel("caller_disconnected")
                        session.shutdown(drain=False)
                    elif event is HandoffEvent.FAIL:
                        if self._terminal(attempt, HandoffState.FAILED, event.value):
                            await self._finish_later(attempt, event)
                    return
            finally:
                for task in (completion, interrupt):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(completion, interrupt, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Handoff participant watcher failed",
                extra={
                    "call_session_id": str(self._call_id),
                    "handoff_attempt_id": str(attempt_id),
                    "participant_identity": attempt.participant_identity,
                },
            )
            if self._terminal(attempt, HandoffState.FAILED, "watcher_error"):
                self._finish_later(attempt, HandoffEvent.FAIL)
        finally:
            room.off("participant_connected", participant_connected)
            room.off("participant_attributes_changed", participant_attributes_changed)
            room.off("participant_disconnected", participant_disconnected)
