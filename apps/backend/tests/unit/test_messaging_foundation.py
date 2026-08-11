from uuid import uuid4

import pytest
from backend_core.platform.messaging import (
    FINALIZATION_EVENT_GROUP,
    FINALIZATION_RESULT_GROUP,
    TransactionalOutboxBus,
)
from contracts import MessageEnvelope


class Session:
    def __init__(self) -> None:
        self.rows = []
        self.flushed = False

    def add(self, row) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_transactional_bus_adds_message_to_the_call_transaction() -> None:
    session = Session()
    bus = TransactionalOutboxBus(session)  # type: ignore[arg-type]
    event = MessageEnvelope(
        message_kind="event",
        message_type="call.ended",
        correlation_id=uuid4(),
        payload={"call_id": str(uuid4()), "status": "ended"},
    )

    await bus.publish(event)

    assert session.flushed
    assert session.rows[0].job_id == event.message_id
    assert session.rows[0].stream == "domain:events"


def test_event_subscriptions_use_independent_consumer_groups() -> None:
    assert FINALIZATION_EVENT_GROUP != FINALIZATION_RESULT_GROUP
