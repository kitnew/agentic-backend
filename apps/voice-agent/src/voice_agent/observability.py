"""Process-owned, privacy-safe OpenTelemetry for LiveKit job processes."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentic_observability.attributes import metric_attributes
from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.logging import install_trace_context_filter
from livekit import agents
from livekit.agents.telemetry import set_tracer_provider
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import Status

_runtime: VoiceTelemetryRuntime | None = None


class LiveKitPrivacySpanProcessor(SpanProcessor):
    """Remove conversational content from native LiveKit spans before export."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        scope = span.instrumentation_scope
        if scope is None or scope.name != "livekit-agents":
            return
        attributes: Any = span._attributes  # type: ignore[attr-defined]
        if attributes is not None:
            for key in list(attributes):
                if _is_private_livekit_attribute(str(key)):
                    del attributes[key]
        span._events = BoundedList(maxlen=0)  # type: ignore[attr-defined]
        span._status = Status(span.status.status_code)  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _is_private_livekit_attribute(key: str) -> bool:
    # Native LiveKit attributes include chat contexts, transcripts, tool payloads,
    # provider request ids, and session metadata. Metrics are sourced separately.
    return key.startswith(("lk.", "gen_ai.")) or key in {
        "exception.message",
        "exception.stacktrace",
    }


@dataclass
class VoiceMetrics:
    _meter: Any

    def __post_init__(self) -> None:
        self._turn_transcription_delay = self._meter.create_histogram(
            "voice.turn.transcription_delay", unit="s"
        )
        self._turn_end_of_turn_delay = self._meter.create_histogram(
            "voice.turn.end_of_turn_delay", unit="s"
        )
        self._turn_user_completed_delay = self._meter.create_histogram(
            "voice.turn.on_user_turn_completed_delay", unit="s"
        )
        self._turn_llm_ttft = self._meter.create_histogram(
            "voice.turn.llm_ttft", unit="s"
        )
        self._turn_tts_ttfb = self._meter.create_histogram(
            "voice.turn.tts_ttfb", unit="s"
        )
        self._turn_e2e_latency = self._meter.create_histogram(
            "voice.turn.e2e_latency", unit="s"
        )
        self._llm_requests = self._meter.create_counter("voice.llm.requests")
        self._llm_duration = self._meter.create_histogram(
            "voice.llm.duration", unit="s"
        )
        self._llm_ttft = self._meter.create_histogram("voice.llm.ttft", unit="s")
        self._llm_input_tokens = self._meter.create_counter("voice.llm.input_tokens")
        self._llm_cached_tokens = self._meter.create_counter(
            "voice.llm.input_cached_tokens"
        )
        self._llm_output_tokens = self._meter.create_counter("voice.llm.output_tokens")
        self._stt_requests = self._meter.create_counter("voice.stt.requests")
        self._stt_duration = self._meter.create_histogram(
            "voice.stt.duration", unit="s"
        )
        self._stt_audio_duration = self._meter.create_counter(
            "voice.stt.audio_duration", unit="s"
        )
        self._tts_requests = self._meter.create_counter("voice.tts.requests")
        self._tts_duration = self._meter.create_histogram(
            "voice.tts.duration", unit="s"
        )
        self._tts_ttfb = self._meter.create_histogram("voice.tts.ttfb", unit="s")
        self._tts_audio_duration = self._meter.create_counter(
            "voice.tts.audio_duration", unit="s"
        )
        self._tts_characters = self._meter.create_counter("voice.tts.characters")
        self._errors = self._meter.create_counter("voice.component.errors")
        self._capability_executions = self._meter.create_counter(
            "capability.executions"
        )
        self._capability_failures = self._meter.create_counter("capability.failures")
        self._capability_duration = self._meter.create_histogram(
            "capability.execution.duration", unit="s"
        )

    def record_turn(self, item: object) -> None:
        values = getattr(item, "metrics", None)
        if not isinstance(values, Mapping):
            return
        self._record(
            self._turn_transcription_delay,
            values.get("transcription_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_end_of_turn_delay,
            values.get("end_of_turn_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_user_completed_delay,
            values.get("on_user_turn_completed_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_llm_ttft,
            values.get("llm_node_ttft"),
            _turn_attrs(values, "llm_metadata"),
        )
        self._record(
            self._turn_tts_ttfb,
            values.get("tts_node_ttfb"),
            _turn_attrs(values, "tts_metadata"),
        )
        self._record(
            self._turn_e2e_latency,
            values.get("e2e_latency"),
            _turn_attrs(values, "llm_metadata"),
        )

    def record_component_metric(self, metric: object) -> None:
        kind = getattr(metric, "type", None)
        if kind == "llm_metrics":
            attributes = _component_attrs("llm", metric)
            attributes["status"] = (
                "cancelled" if getattr(metric, "cancelled", False) else "ok"
            )
            self._add(self._llm_requests, 1, attributes)
            self._record(
                self._llm_duration, getattr(metric, "duration", None), attributes
            )
            self._record(self._llm_ttft, getattr(metric, "ttft", None), attributes)
            self._add(
                self._llm_input_tokens, getattr(metric, "prompt_tokens", 0), attributes
            )
            self._add(
                self._llm_cached_tokens,
                getattr(metric, "prompt_cached_tokens", 0),
                attributes,
            )
            self._add(
                self._llm_output_tokens,
                getattr(metric, "completion_tokens", 0),
                attributes,
            )
        elif kind == "stt_metrics":
            attributes = _component_attrs("stt", metric)
            self._add(self._stt_requests, 1, attributes)
            if not getattr(metric, "streamed", False):
                self._record(
                    self._stt_duration, getattr(metric, "duration", None), attributes
                )
            self._add(
                self._stt_audio_duration,
                getattr(metric, "audio_duration", 0),
                attributes,
            )
        elif kind == "tts_metrics":
            attributes = _component_attrs("tts", metric)
            attributes["status"] = (
                "cancelled" if getattr(metric, "cancelled", False) else "ok"
            )
            self._add(self._tts_requests, 1, attributes)
            self._record(
                self._tts_duration, getattr(metric, "duration", None), attributes
            )
            self._record(self._tts_ttfb, getattr(metric, "ttfb", None), attributes)
            self._add(
                self._tts_audio_duration,
                getattr(metric, "audio_duration", 0),
                attributes,
            )
            self._add(
                self._tts_characters,
                getattr(metric, "characters_count", 0),
                attributes,
            )

    def record_component_error(self, component: str, error: object) -> None:
        self._add(
            self._errors,
            1,
            {
                "voice.component": component,
                "error.type": type(error).__name__,
                "status": "error",
            },
        )

    def record_capability_execution(
        self,
        *,
        name: str,
        version: str,
        status: str,
        duration_seconds: float,
        error_type: str | None = None,
    ) -> None:
        attributes = {
            "capability.name": name,
            "capability.version": version,
            "status": status,
        }
        if error_type is not None:
            attributes["error.type"] = error_type
        metric_attributes(attributes)
        self._capability_executions.add(1, attributes)
        self._capability_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._capability_failures.add(1, attributes)

    def _record(
        self, instrument: Any, value: object, attributes: dict[str, str]
    ) -> None:
        if (measurement := _measurement(value)) is not None:
            instrument.record(measurement, attributes=metric_attributes(attributes))

    def _add(self, instrument: Any, value: object, attributes: dict[str, str]) -> None:
        if (measurement := _measurement(value)) and measurement > 0:
            instrument.add(measurement, attributes=metric_attributes(attributes))


def _measurement(value: object) -> float | None:
    if isinstance(value, int | float) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def record_capability_execution(
    *,
    name: str,
    version: str,
    status: str,
    duration_seconds: float,
    error_type: str | None = None,
) -> None:
    runtime = current_voice_telemetry()
    if runtime is not None:
        runtime.metrics.record_capability_execution(
            name=name,
            version=version,
            status=status,
            duration_seconds=duration_seconds,
            error_type=error_type,
        )


def _component_attrs(component: str, metric: object) -> dict[str, str]:
    attributes = {"voice.component": component}
    metadata = getattr(metric, "metadata", None)
    provider = getattr(metadata, "model_provider", None)
    model = getattr(metadata, "model_name", None)
    if isinstance(provider, str) and provider:
        attributes["voice.provider"] = provider
    if isinstance(model, str) and model:
        attributes["voice.model"] = model
    return attributes


def _turn_attrs(values: Mapping[str, object], metadata_name: str) -> dict[str, str]:
    metadata = values.get(metadata_name)
    if not isinstance(metadata, Mapping):
        return {}
    attributes: dict[str, str] = {}
    for source, target in (
        ("model_provider", "voice.provider"),
        ("model_name", "voice.model"),
    ):
        value = metadata.get(source)
        if isinstance(value, str) and value:
            attributes[target] = value
    return attributes


@dataclass(slots=True)
class VoiceTelemetryRuntime:
    providers: TelemetryProviders
    metrics: VoiceMetrics

    def set_session_correlation(self, call_id: UUID) -> None:
        span = trace.get_current_span()
        if span.get_span_context().is_valid:
            span.set_attribute("call.id", str(call_id))


def setup_voice_telemetry(_: agents.JobProcess) -> None:
    if _runtime is not None or os.getenv("OTEL_ENABLED", "").lower() != "true":
        return
    environ = {**os.environ, "OTEL_SERVICE_NAME": "voice-agent"}
    providers = bootstrap(
        TelemetryConfig.from_env(default_service_name="voice-agent", environ=environ),
        span_processors=(LiveKitPrivacySpanProcessor(),),
    )
    configure_voice_telemetry(providers)


def configure_voice_telemetry(
    providers: TelemetryProviders,
) -> VoiceTelemetryRuntime | None:
    global _runtime
    if _runtime is not None:
        return _runtime
    if providers.tracer_provider is None or providers.meter_provider is None:
        return None
    set_tracer_provider(providers.tracer_provider)  # type: ignore[arg-type]
    meter = providers.meter("voice-agent")
    if meter is None:
        return None
    install_trace_context_filter(logging.getLogger().handlers)
    _runtime = VoiceTelemetryRuntime(providers, VoiceMetrics(meter))
    return _runtime


def current_voice_telemetry() -> VoiceTelemetryRuntime | None:
    return _runtime


def shutdown_voice_telemetry() -> None:
    global _runtime
    if _runtime is None:
        return
    runtime = _runtime
    _runtime = None
    runtime.providers.shutdown()
