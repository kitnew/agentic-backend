import asyncio
from typing import Any
from uuid import uuid4

import pytest
from backend_core.platform.messaging import (
    FINALIZATION_EVENT_GROUP,
    FINALIZATION_RESULT_GROUP,
    TransactionalOutboxBus,
)
from backend_core.platform.stream_consumer import RedisStreamConsumer
from contracts import MessageEnvelope


class Session:
    def __init__(self) -> None:
        self.rows: list[Any] = []
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


@pytest.mark.asyncio
async def test_stream_consumer_recovers_after_infrastructure_error(monkeypatch) -> None:
    class Redis:
        def __init__(self) -> None:
            self.reads = 0

        async def xgroup_create(self, *args, **kwargs) -> None:
            pass

        async def xautoclaim(self, *args, **kwargs):
            return "0-0", [], []

        async def xreadgroup(self, *args, **kwargs):
            self.reads += 1
            if self.reads == 1:
                raise ConnectionError("Redis temporarily unavailable")
            if self.reads == 2:
                return [("events", [("1-0", {"message": "ok"})])]
            raise asyncio.CancelledError

        async def xack(self, *args, **kwargs) -> None:
            pass

        async def delete(self, *args, **kwargs) -> None:
            pass

    async def no_sleep(_: float) -> None:
        pass

    received: list[dict[str, str]] = []

    async def handler(fields: dict[str, str]) -> None:
        received.append(fields)

    monkeypatch.setattr("backend_core.platform.stream_consumer.asyncio.sleep", no_sleep)
    consumer = RedisStreamConsumer(
        Redis(),  # type: ignore[arg-type]
        "events",
        "group",
        "consumer",
        handler,
    )

    with pytest.raises(asyncio.CancelledError):
        await consumer.run()

    assert received == [{"message": "ok"}]
