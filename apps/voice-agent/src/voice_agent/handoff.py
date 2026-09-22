import asyncio
import logging
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


class HandoffController:
    def __init__(self, backend: BackendClient, call_id: UUID, timeout: float) -> None:
        self._backend = backend
        self._call_id = call_id
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._attempt: HandoffAttempt | None = None
        self._waiter: asyncio.Task[None] | None = None
        self._caller_identity: str | None = None

    @property
    def attempt_id(self) -> UUID | None:
        return self._attempt.id if self._attempt is not None else None

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
            self._attempt = HandoffAttempt(
                response.attempt_id,
                response.participant_identity,
                response.status,
            )
            if response.status is HandoffState.DIALING:
                self._waiter = asyncio.create_task(
                    self._watch(session, response.attempt_id)
                )

    async def cancel(self, reason: str) -> bool:
        async with self._lock:
            attempt = self._attempt
            if attempt is None or attempt.state not in ACTIVE_STATES:
                return False
            try:
                response = await self._backend.transition_handoff(
                    self._call_id, attempt.id, HandoffEvent.CANCEL
                )
                if self._attempt is not attempt:
                    return False
                attempt.state = response.state
            except Exception:
                logger.exception(
                    "Handoff cancellation request failed",
                    extra={
                        "call_session_id": str(self._call_id),
                        "handoff_attempt_id": str(attempt.id),
                        "handoff_state": attempt.state.value,
                        "participant_identity": attempt.participant_identity,
                        "reason": reason,
                    },
                )
                return False
            waiter = self._waiter
        if waiter is not None and waiter is not asyncio.current_task():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        return True

    async def close(self) -> None:
        await self.cancel("voice_agent_shutdown")
        await self._stop_waiter()

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
            response = await self._backend.transition_handoff(
                self._call_id, attempt_id, event
            )
            if (
                self._attempt is not attempt
                or response.attempt_id != attempt_id
                or response.participant_identity != attempt.participant_identity
            ):
                return None
            attempt.state = response.state
            return response.state

    async def _watch(self, session: agents.AgentSession, attempt_id: UUID) -> None:
        room = session.room_io.room
        events: asyncio.Queue[HandoffEvent] = asyncio.Queue()
        attempt = self._attempt
        if attempt is None or attempt.id != attempt_id:
            return

        def participant_connected(participant: rtc.RemoteParticipant) -> None:
            if (
                participant.identity == attempt.participant_identity
                and participant.attributes.get("sip.callStatus") == "active"
            ):
                events.put_nowait(HandoffEvent.ANSWER)

        def participant_attributes_changed(
            changed_attributes: dict[str, str], participant: rtc.Participant
        ) -> None:
            if (
                participant.identity == attempt.participant_identity
                and changed_attributes.get("sip.callStatus") == "active"
            ):
                events.put_nowait(HandoffEvent.ANSWER)

        def participant_disconnected(participant: rtc.RemoteParticipant) -> None:
            if participant.identity == attempt.participant_identity:
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
            try:
                event = await asyncio.wait_for(events.get(), self._timeout)
            except TimeoutError:
                event = HandoffEvent.TIME_OUT
            if event is HandoffEvent.CANCEL:
                await self.cancel("caller_disconnected")
                session.shutdown(drain=False)
                return
            state = await self._transition(attempt_id, event)
            if state is not HandoffState.ANSWERED:
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
                    await self._transition(attempt_id, event)
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
                            session.shutdown(drain=True)
                        return
                    event = interrupt.result()
                    if event is HandoffEvent.ANSWER:
                        interrupt = asyncio.create_task(events.get())
                        continue
                    if event is HandoffEvent.CANCEL:
                        await self.cancel("caller_disconnected")
                        session.shutdown(drain=False)
                    elif event is HandoffEvent.FAIL:
                        await self._transition(attempt_id, event)
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
        finally:
            room.off("participant_connected", participant_connected)
            room.off("participant_attributes_changed", participant_attributes_changed)
            room.off("participant_disconnected", participant_disconnected)
