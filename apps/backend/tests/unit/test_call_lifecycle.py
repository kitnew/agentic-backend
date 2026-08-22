from hashlib import sha256
from uuid import uuid4

import pytest
from backend_core.modules.calls.errors import CallSessionConflictError
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.calls.service import CallSessionService
from contracts import ConversationPersistenceStatus, MessageEnvelope


class Calls:
    def __init__(self, call: CallSession) -> None:
        self.call = call
        self.flushed = 0

    async def get_for_update(self, call_id):
        return self.call if self.call.id == call_id else None

    async def flush(self) -> None:
        self.flushed += 1


class Conversations:
    status = ConversationPersistenceStatus.COMPLETE

    async def close_for_call(self, call_id, status) -> None:
        return None

    async def status_for_call(self, call_id):
        return self.status


class Events:
    def __init__(self) -> None:
        self.messages: list[MessageEnvelope] = []

    async def publish(self, event: MessageEnvelope) -> None:
        self.messages.append(event)


class Metrics:
    def __init__(self) -> None:
        self.started = 0
        self.terminal: list[tuple[str, bool]] = []

    def call_started(self) -> None:
        self.started += 1

    def call_terminal(self, status, duration, *, was_active) -> None:
        self.terminal.append((status, was_active))


def call() -> CallSession:
    return CallSession(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_config_revision_id=uuid4(),
        prompt_set_revision_id=uuid4(),
        voice_runtime_revision_id=uuid4(),
        channel=CallChannel.WEB,
        direction=CallDirection.INBOUND,
        provider="livekit",
        provider_call_id=str(uuid4()),
        room_name="room",
        status=CallSessionStatus.CREATED,
    )


def service(
    current: CallSession, metrics: Metrics | None = None
) -> tuple[CallSessionService, Events]:
    events = Events()
    return (
        CallSessionService(
            Calls(current),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            Conversations(),  # type: ignore[arg-type]
            events,
            metrics=metrics,  # type: ignore[arg-type]
        ),
        events,
    )


def test_phone_log_fingerprint_is_keyed_and_not_plain_sha256() -> None:
    current = call()
    keyed = CallSessionService(
        Calls(current),
        None,
        None,
        None,
        None,
        None,
        Conversations(),
        Events(),
        privacy_key=b"test-key",
    )
    fingerprint = keyed._phone_hash("+421551234567")
    assert fingerprint != ""
    assert fingerprint != sha256(b"+421551234567").hexdigest()[:16]


@pytest.mark.asyncio
async def test_allowed_lifecycle_transitions_emit_authoritative_events() -> None:
    current = call()
    metrics = Metrics()
    lifecycle, events = service(current, metrics)

    await lifecycle.mark_started(current.id)
    await lifecycle.mark_connected(current.id)
    await lifecycle.end(current.id, ConversationPersistenceStatus.COMPLETE)

    assert current.status is CallSessionStatus.ENDED
    assert [message.message_type for message in events.messages] == [
        "call.started",
        "call.connected",
        "call.ended",
    ]
    assert metrics.started == 1
    assert metrics.terminal == [("completed", True)]

    await lifecycle.end(current.id, ConversationPersistenceStatus.COMPLETE)
    assert [message.message_type for message in events.messages] == [
        "call.started",
        "call.connected",
        "call.ended",
    ]


@pytest.mark.asyncio
async def test_rejected_transition_and_failure_from_each_nonterminal_state() -> None:
    current = call()
    lifecycle, _ = service(current)
    with pytest.raises(CallSessionConflictError):
        await lifecycle.mark_connected(current.id)

    for status in (
        CallSessionStatus.CREATED,
        CallSessionStatus.STARTED,
        CallSessionStatus.CONNECTED,
    ):
        current = call()
        current.status = status
        if status is not CallSessionStatus.CREATED:
            from datetime import UTC, datetime

            current.started_at = datetime.now(UTC)
        lifecycle, events = service(current)
        await lifecycle.fail(
            current.id, "runtime_failed", ConversationPersistenceStatus.INCOMPLETE
        )
        assert current.status is CallSessionStatus.FAILED
        assert events.messages[-1].message_type == "call.failed"


@pytest.mark.asyncio
async def test_reconcile_missing_runtime_uses_existing_terminal_transitions() -> None:
    connected = call()
    lifecycle, events = service(connected)
    await lifecycle.mark_started(connected.id)
    await lifecycle.mark_connected(connected.id)

    assert await lifecycle.reconcile_missing_runtime(connected.id) is connected
    assert connected.status is CallSessionStatus.ENDED
    assert events.messages[-1].message_type == "call.ended"
    assert await lifecycle.reconcile_missing_runtime(connected.id) is None
    assert [event.message_type for event in events.messages].count("call.ended") == 1

    started = call()
    lifecycle, events = service(started)
    await lifecycle.mark_started(started.id)
    assert await lifecycle.reconcile_missing_runtime(started.id) is started
    assert started.status is CallSessionStatus.FAILED
    assert started.failure_reason == "runtime_unavailable"
    assert events.messages[-1].message_type == "call.failed"
