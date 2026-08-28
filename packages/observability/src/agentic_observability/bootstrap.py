"""Explicit provider construction. Importing this module has no global SDK side effects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import (
    ExplicitBucketHistogramAggregation,
    View,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanProcessor,
)
from opentelemetry.trace import Tracer

from .config import TelemetryConfig

MAX_FLUSH_TIMEOUT_MILLIS = 10_000

VOICE_FAST_BUCKETS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5)
VOICE_DURATION_BUCKETS = (
    0.1,
    0.25,
    0.5,
    0.75,
    1,
    1.5,
    2,
    3,
    4,
    5,
    7.5,
    10,
    15,
    30,
)


def _histogram_views() -> tuple[View, ...]:
    fast = {
        "voice.turn.transcription_delay",
        "voice.turn.end_of_turn_delay",
        "voice.turn.on_user_turn_completed_delay",
        "voice.turn.llm_ttft",
        "voice.turn.llm_usable_ttft",
        "voice.turn.llm_to_tts_dispatch_latency",
        "voice.turn.tts_ttfb",
        "voice.turn.tts_effective_first_audio_latency",
        "voice.turn.playback_latency",
        "voice.stt.duration",
        "voice.llm.ttft",
        "voice.tts.ttfb",
        "voice.tts.connection.acquire_time",
        "voice.speculative_generation.lead_time",
    }
    duration = {
        "call.duration",
        "capability.execution.duration",
        "worker.capability.execution_attempt.duration",
        "worker.command.duration",
        "post_call.duration",
        "integration.duration",
        "voice.turn.e2e_latency",
        "voice.llm.duration",
        "voice.tts.duration",
    }
    return tuple(
        View(
            instrument_name=name,
            aggregation=ExplicitBucketHistogramAggregation(boundaries=boundaries),
        )
        for names, boundaries in (
            (fast, VOICE_FAST_BUCKETS),
            (duration, VOICE_DURATION_BUCKETS),
        )
        for name in sorted(names)
    )


DEFAULT_HISTOGRAM_VIEWS = _histogram_views()


class Provider(Protocol):
    def force_flush(self, timeout_millis: int = ...) -> bool: ...

    def shutdown(self) -> object: ...


@dataclass(slots=True)
class TelemetryProviders:
    resource: Resource
    tracer_provider: Provider | None
    meter_provider: Provider | None
    _shutdown: bool = False

    def force_flush(self, timeout_millis: int = MAX_FLUSH_TIMEOUT_MILLIS) -> bool:
        timeout = min(max(timeout_millis, 1), MAX_FLUSH_TIMEOUT_MILLIS)
        return all(_force_flush(provider, timeout) for provider in self._providers())

    def shutdown(self, timeout_millis: int = MAX_FLUSH_TIMEOUT_MILLIS) -> bool:
        if self._shutdown:
            return True
        flushed = self.force_flush(timeout_millis)
        for provider in self._providers():
            try:
                provider.shutdown()
            except Exception:  # noqa: BLE001
                flushed = False
        self._shutdown = True
        return flushed

    def _providers(self) -> tuple[Provider, ...]:
        return tuple(
            provider
            for provider in (self.tracer_provider, self.meter_provider)
            if provider
        )

    def tracer(self, name: str) -> Tracer | None:
        if self.tracer_provider is None:
            return None
        return cast(TracerProvider, self.tracer_provider).get_tracer(name)

    def meter(self, name: str) -> Meter | None:
        if self.meter_provider is None:
            return None
        return cast(MeterProvider, self.meter_provider).get_meter(name)


def bootstrap(
    config: TelemetryConfig,
    *,
    trace_exporter: SpanExporter | None = None,
    metric_exporter: MetricExporter | None = None,
    span_processors: Sequence[SpanProcessor] = (),
    views: Sequence[View] = DEFAULT_HISTOGRAM_VIEWS,
) -> TelemetryProviders:
    resource = Resource.create(dict(config.resource_attributes))
    if not config.enabled or config.sdk_disabled:
        return TelemetryProviders(resource, None, None)

    tracer_provider = TracerProvider(resource=resource)
    for processor in span_processors:
        tracer_provider.add_span_processor(processor)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            trace_exporter
            or OTLPSpanExporter(endpoint=_signal_endpoint(config.endpoint, "traces"))
        )
    )
    meter_provider = MeterProvider(
        resource=resource,
        views=list(views),
        metric_readers=[
            PeriodicExportingMetricReader(
                metric_exporter
                or OTLPMetricExporter(
                    endpoint=_signal_endpoint(config.endpoint, "metrics")
                )
            )
        ],
    )
    return TelemetryProviders(resource, tracer_provider, meter_provider)


def _force_flush(provider: Provider, timeout_millis: int) -> bool:
    try:
        return provider.force_flush(timeout_millis)
    except Exception:  # noqa: BLE001
        return False


def _signal_endpoint(endpoint: str, signal: str) -> str:
    return f"{endpoint.rstrip('/')}/v1/{signal}"
