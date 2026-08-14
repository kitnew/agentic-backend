import asyncio
from typing import Any
from uuid import uuid4

import pytest
from agentic_observability.propagation import inject_trace_context
from backend_core.platform.messaging import (
    FINALIZATION_EVENT_GROUP,
    FINALIZATION_RESULT_GROUP,
    TransactionalOutboxBus,
)
from backend_core.platform.stream_consumer import RedisStreamConsumer
from contracts import MessageEnvelope
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import set_span_in_context


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
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    bus = TransactionalOutboxBus(  # type: ignore[arg-type]
        session, tracer=provider.get_tracer(__name__)
    )
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
    assert session.rows[0].transport_metadata["traceparent"]
    assert [span.name for span in exporter.get_finished_spans()] == [
        "messaging.outbox.create"
    ]
    provider.shutdown()


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


@pytest.mark.asyncio
async def test_stream_processing_starts_a_new_trace_linked_to_creation_context() -> None:
    class Redis:
        async def xack(self, *args) -> None:
            pass

        async def delete(self, *args) -> None:
            pass

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    source = provider.get_tracer(__name__).start_span("messaging.outbox.create")
    fields = {"message": "ok"}
    inject_trace_context(fields, set_span_in_context(source))
    source_context = source.get_span_context()
    source.end()
    received: list[dict[str, str]] = []

    async def handler(message: dict[str, str]) -> None:
        received.append(message)

    consumer = RedisStreamConsumer(
        Redis(),  # type: ignore[arg-type]
        "events",
        "group",
        "consumer",
        handler,
        tracer=provider.get_tracer(__name__),
    )
    await consumer.handle("1-0", fields)

    process = exporter.get_finished_spans()[-1]
    assert process.name == "messaging.process"
    assert process.context.trace_id != source_context.trace_id
    assert process.links[0].context.trace_id == source_context.trace_id
    assert process.links[0].context.span_id == source_context.span_id
    assert received == [fields]
    provider.shutdown()


@pytest.mark.asyncio
async def test_missing_or_invalid_redis_context_starts_an_unlinked_process_span() -> None:
    class Redis:
        async def xack(self, *args) -> None:
            pass

        async def delete(self, *args) -> None:
            pass

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    async def handler(_: dict[str, str]) -> None:
        pass

    consumer = RedisStreamConsumer(
        Redis(),  # type: ignore[arg-type]
        "events",
        "group",
        "consumer",
        handler,
        tracer=provider.get_tracer(__name__),
    )
    await consumer.handle("1-0", {"message": "ok"})
    await consumer.handle("2-0", {"message": "ok", "traceparent": "invalid"})

    assert [span.links for span in exporter.get_finished_spans()] == [(), ()]
    provider.shutdown()


@pytest.mark.asyncio
async def test_xautoclaim_and_dead_letter_preserve_original_context_carrier() -> None:
    class Redis:
        def __init__(self) -> None:
            self.dead_letters: list[dict[str, str]] = []

        async def xautoclaim(self, *args, **kwargs):
            return "0-0", [("1-0", fields)], []

        async def incr(self, *args) -> int:
            return 1

        async def xadd(self, _stream, message) -> None:
            self.dead_letters.append(message)

        async def xack(self, *args) -> None:
            pass

        async def delete(self, *args) -> None:
            pass

    fields = {"message": "bad", "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}
    redis = Redis()

    async def fail(_: dict[str, str]) -> None:
        raise RuntimeError("boom")

    consumer = RedisStreamConsumer(
        redis,  # type: ignore[arg-type]
        "events",
        "group",
        "consumer",
        fail,
        max_retries=0,
    )
    await consumer.recover_stale()

    assert redis.dead_letters[0]["traceparent"] == fields["traceparent"]
