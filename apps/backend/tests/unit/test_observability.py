import logging

import pytest
from agentic_observability.attributes import metric_attributes, safe_log_fields
from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.logging import TraceContextFilter
from agentic_observability.propagation import (
    extract_trace_context,
    inject_trace_context,
)
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import set_span_in_context


def _config(environ: dict[str, str] | None = None) -> TelemetryConfig:
    values = {
        "OTEL_RESOURCE_ATTRIBUTES": (
            "service.version=1.2.3,deployment.environment.name=test,"
            "vcs.ref.head.revision=deadbeef"
        )
    }
    values.update(environ or {})
    return TelemetryConfig.from_env(default_service_name="backend-core", environ=values)


def test_resource_identity_is_required_and_generic_build_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing resource attributes"):
        _config({"OTEL_RESOURCE_ATTRIBUTES": "service.version=1"})
    with pytest.raises(ValueError, match="only agentic_backend.build.id"):
        _config(
            {
                "OTEL_RESOURCE_ATTRIBUTES": (
                    "service.version=1,deployment.environment.name=test,"
                    "vcs.ref.head.revision=abc,build.id=build-1"
                )
            }
        )
    config = _config(
        {
            "OTEL_RESOURCE_ATTRIBUTES": (
                "service.version=1,deployment.environment.name=test,"
                "vcs.ref.head.revision=abc,agentic_backend.build.id=build-1"
            )
        }
    )
    assert config.resource_attributes["service.namespace"] == "agentic-backend"
    assert config.resource_attributes["service.name"] == "backend-core"


def test_otel_is_disabled_by_default_and_sdk_disabled_uses_standard_true_semantics() -> (
    None
):
    assert not _config().enabled
    assert _config({"OTEL_ENABLED": "true"}).enabled
    assert not _config().sdk_disabled
    assert _config({"OTEL_SDK_DISABLED": "true"}).sdk_disabled
    assert not _config({"OTEL_SDK_DISABLED": "1"}).sdk_disabled


def test_bootstrap_does_not_create_providers_when_otel_is_disabled() -> None:
    providers = bootstrap(_config())
    assert providers.tracer_provider is None
    assert providers.meter_provider is None


def test_metric_and_log_attribute_policy_rejects_private_or_high_cardinality_fields() -> (
    None
):
    assert metric_attributes({"capability.name": "reservation", "status": "ok"})
    with pytest.raises(ValueError, match="tenant.id"):
        metric_attributes({"tenant.id": "tenant-123"})
    assert safe_log_fields({"tenant_id": "tenant-123", "event": "completed"})
    with pytest.raises(ValueError, match="transcript"):
        safe_log_fields({"transcript": "private"})


def test_log_filter_correlates_active_and_absent_spans() -> None:
    filter_ = TraceContextFilter()
    record = logging.makeLogRecord({})
    assert filter_.filter(record)
    assert record.__dict__["trace_id"] is None
    assert record.__dict__["span_id"] is None

    provider = TracerProvider()
    with provider.get_tracer(__name__).start_as_current_span("test") as span:
        record = logging.makeLogRecord({"telemetry_fields": {"call_id": "call-123"}})
        assert filter_.filter(record)
        assert record.__dict__["trace_id"] == f"{span.get_span_context().trace_id:032x}"
        assert record.__dict__["span_id"] == f"{span.get_span_context().span_id:016x}"
    provider.shutdown()


def test_trace_context_round_trip_has_no_baggage() -> None:
    provider = TracerProvider()
    span = provider.get_tracer(__name__).start_span("test")
    carrier: dict[str, str] = {"baggage": "tenant=do-not-propagate"}
    inject_trace_context(carrier, set_span_in_context(span))
    extracted = trace.get_current_span(
        extract_trace_context(carrier)
    ).get_span_context()
    assert carrier["traceparent"]
    assert "tracestate" not in carrier or carrier["tracestate"] == ""
    assert extracted.trace_id == span.get_span_context().trace_id
    span.end()
    provider.shutdown()


class _FakeProvider:
    def __init__(self) -> None:
        self.flushes: list[float] = []
        self.shutdowns = 0

    def force_flush(self, timeout_millis: int = 0) -> bool:
        self.flushes.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.shutdowns += 1


def test_shutdown_is_bounded_and_idempotent() -> None:
    trace_provider = _FakeProvider()
    meter_provider = _FakeProvider()
    providers = TelemetryProviders(Resource.create({}), trace_provider, meter_provider)
    assert providers.shutdown(999_999)
    assert trace_provider.flushes == [10_000]
    assert meter_provider.flushes == [10_000]
    assert trace_provider.shutdowns == meter_provider.shutdowns == 1
    assert providers.shutdown()
    assert trace_provider.shutdowns == meter_provider.shutdowns == 1
