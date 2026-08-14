import pytest
from agentic_observability.domain import CoreMetrics, domain_span
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _points(reader: InMemoryMetricReader) -> dict[str, list[object]]:
    points: dict[str, list[object]] = {}
    for resource_metric in reader.get_metrics_data().resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points[metric.name] = list(metric.data.data_points)
    return points


def test_core_metrics_have_authoritative_units_and_no_identifier_dimensions() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = CoreMetrics(provider.get_meter(__name__))

    metrics.call_started()
    metrics.call_terminal("completed", 12.5, was_active=True)
    metrics.call_terminal("failed", None, was_active=False)
    metrics.capability_completed(
        name="reservation.submit_request",
        version="1",
        status="failed",
        duration_seconds=2.0,
        error_type="provider_timeout",
    )
    metrics.command_attempt(
        operation="summary_generation", status="ok", duration_seconds=1.0
    )
    metrics.command_retry("summary_generation")
    metrics.command_dlq("summary_generation", "provider_timeout")
    provider.force_flush()

    points = _points(reader)
    assert points["call.active"][0].value == 0
    assert points["call.duration"][0].sum == 12.5
    assert points["capability.executions"][0].value == 1
    assert points["worker.command.retries"][0].value == 1
    assert all(
        not {"call.id", "conversation.id", "operation.id", "message.id"}
        & set(point.attributes)
        for metric_points in points.values()
        for point in metric_points
    )
    provider.shutdown()


def test_domain_span_keeps_correlation_but_never_records_exception_text() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with (
        pytest.raises(RuntimeError, match="private payload"),
        domain_span(
            provider.get_tracer(__name__),
            "capability.execute",
            {"call.id": "call-1", "capability.name": "reservation.submit_request"},
        ),
    ):
        raise RuntimeError("private payload")

    span = exporter.get_finished_spans()[0]
    assert span.attributes["call.id"] == "call-1"
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.events == ()
    assert span.status.description is None
    assert "private payload" not in str(span.attributes)
    provider.shutdown()
