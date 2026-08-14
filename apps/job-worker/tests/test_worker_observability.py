import asyncio
from uuid import uuid4

import httpx
import pytest
from agentic_observability.propagation import inject_trace_context
from contracts import GenerateCallSummary, command_envelope
from job_worker import command_worker
from job_worker import worker as worker_module
from job_worker.worker import CapabilityWorker, Settings, run_worker
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import set_span_in_context


class Telemetry:
    tracer_provider = object()
    meter_provider = object()

    def __init__(self) -> None:
        self.shutdowns = 0

    def tracer(self, _name: str):
        return None

    def meter(self, _name: str):
        return None

    def shutdown(self) -> None:
        self.shutdowns += 1


class Redis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def settings() -> Settings:
    return Settings(
        redis_url="redis://redis",
        stream="capability:jobs",
        group="capability-workers",
        consumer="worker-1",
        dead_letter_stream="capability:jobs:dead-letter",
        backend_url="http://backend",
        backend_audience="backend",
        service_secret="secret",
        credential_file_map_json="{}",
    )


@pytest.mark.asyncio
async def test_worker_disabled_does_not_bootstrap_telemetry(monkeypatch) -> None:
    redis = Redis()
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.setattr(worker_module.Redis, "from_url", lambda *_args, **_: redis)
    monkeypatch.setattr(
        worker_module,
        "bootstrap",
        lambda *_: pytest.fail("disabled worker must not bootstrap telemetry"),
    )
    monkeypatch.setattr(
        worker_module,
        "MountedSecretFileCredentialResolver",
        lambda *_: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        await run_worker(settings())

    assert redis.closed


@pytest.mark.asyncio
async def test_worker_enabled_instruments_created_clients_and_cleans_up_failure(
    monkeypatch,
) -> None:
    redis = Redis()
    telemetry = Telemetry()
    redis_calls: list[object] = []
    http_calls: list[object] = []
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.version=test,deployment.environment.name=test,vcs.ref.head.revision=test",
    )
    monkeypatch.setattr(worker_module.Redis, "from_url", lambda *_args, **_: redis)
    monkeypatch.setattr(worker_module, "bootstrap", lambda *_: telemetry)
    monkeypatch.setattr(
        worker_module.RedisInstrumentor,
        "instrument_client",
        lambda client, **_: redis_calls.append(client),
    )
    monkeypatch.setattr(
        worker_module.HTTPXClientInstrumentor,
        "instrument_client",
        lambda client, **_: http_calls.append(client),
    )
    monkeypatch.setattr(
        worker_module,
        "MountedSecretFileCredentialResolver",
        lambda *_: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        await run_worker(settings())

    assert redis_calls == [redis]
    assert len(http_calls) == 2
    assert redis.closed
    assert telemetry.shutdowns == 1


@pytest.mark.asyncio
async def test_worker_cancellation_flushes_telemetry_and_closes_redis(
    monkeypatch,
) -> None:
    redis = Redis()
    telemetry = Telemetry()
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.version=test,deployment.environment.name=test,vcs.ref.head.revision=test",
    )
    monkeypatch.setattr(worker_module.Redis, "from_url", lambda *_args, **_: redis)
    monkeypatch.setattr(worker_module, "bootstrap", lambda *_: telemetry)
    monkeypatch.setattr(
        worker_module.RedisInstrumentor, "instrument_client", lambda *_1, **_2: None
    )
    monkeypatch.setattr(
        worker_module.HTTPXClientInstrumentor,
        "instrument_client",
        lambda *_1, **_2: None,
    )

    async def cancelled(_self) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_module.CapabilityWorker, "run", cancelled)
    monkeypatch.setattr(command_worker.CommandWorker, "run", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await run_worker(settings())

    assert redis.closed
    assert telemetry.shutdowns == 1


@pytest.mark.asyncio
async def test_worker_process_links_creation_context_and_parents_httpx_callback() -> (
    None
):
    class StreamRedis:
        async def get(self, _key):
            return None

        async def xadd(self, *_args) -> None:
            pass

        async def set(self, *_args, **_kwargs) -> None:
            pass

        async def xack(self, *_args) -> None:
            pass

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    source = provider.get_tracer(__name__).start_span("messaging.outbox.create")
    envelope = command_envelope(
        GenerateCallSummary(call_id=uuid4(), finalization_id=uuid4()),
        tenant_id=uuid4(),
        correlation_id=uuid4(),
    )
    fields = {"message": envelope.model_dump_json()}
    inject_trace_context(fields, set_span_in_context(source))
    source_context = source.get_span_context()
    source.end()

    async def call_http(_command, _envelope):
        await client.get("http://backend.test/callback")
        return {"summary": "done"}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        HTTPXClientInstrumentor.instrument_client(
            client,
            tracer_provider=provider,
            meter_provider=MeterProvider(),
        )
        command = command_worker.CommandWorker(
            settings(),
            StreamRedis(),  # type: ignore[arg-type]
            {"call.generate_summary.v1": call_http},
            provider.get_tracer(__name__),
        )
        await command.handle("1-0", fields)

    process = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "messaging.process"
    )
    domain = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "post_call.summary.generate"
    )
    http_span = next(
        span for span in exporter.get_finished_spans() if span.name == "GET"
    )
    assert process.context.trace_id != source_context.trace_id
    assert process.links[0].context.trace_id == source_context.trace_id
    assert domain.parent.span_id == process.context.span_id
    assert http_span.parent.span_id == domain.context.span_id
    provider.shutdown()


@pytest.mark.asyncio
async def test_capability_dead_letter_keeps_sibling_w3c_metadata() -> None:
    class StreamRedis:
        def __init__(self) -> None:
            self.dead_letters: list[dict[str, str]] = []

        async def xadd(self, _stream, fields) -> None:
            self.dead_letters.append(fields)

        async def xack(self, *_args) -> None:
            pass

    redis = StreamRedis()
    worker = CapabilityWorker(
        settings(),
        redis,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    fields = {
        "job": "not-json",
        "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    }

    await worker.handle("1-0", fields)

    assert redis.dead_letters[0]["traceparent"] == fields["traceparent"]
