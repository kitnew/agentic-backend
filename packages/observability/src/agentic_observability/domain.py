"""Privacy-safe domain tracing and core metrics for application runtimes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from .attributes import metric_attributes


@contextmanager
def domain_span(
    tracer: Tracer | None,
    name: str,
    attributes: Mapping[str, str] | None = None,
) -> Iterator[Span | None]:
    """Create a domain span without capturing exception text or events."""
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        name,
        attributes=dict(attributes or {}),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as error:
            span.set_attribute("status", "error")
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
        else:
            span.set_attribute("status", "ok")


@dataclass
class CoreMetrics:
    """One owner per metric semantic; callers choose the authoritative transition."""

    meter: Meter

    def __post_init__(self) -> None:
        self._calls_started = self.meter.create_counter("call.started")
        self._ai_usage_tokens = self.meter.create_counter("voice.ai_usage.tokens")
        self._ai_usage_seconds = self.meter.create_counter("voice.ai_usage.seconds")
        self._ai_usage_characters = self.meter.create_counter(
            "voice.ai_usage.characters"
        )
        self._ai_estimated_cost = self.meter.create_counter(
            "voice.ai_usage.estimated_cost_usd"
        )
        self._calls_completed = self.meter.create_counter("call.completed")
        self._calls_failed = self.meter.create_counter("call.failed")
        self._calls_active = self.meter.create_up_down_counter("call.active")
        self._call_duration = self.meter.create_histogram("call.duration", unit="s")
        self._capability_executions = self.meter.create_counter("capability.executions")
        self._capability_failures = self.meter.create_counter("capability.failures")
        self._capability_duration = self.meter.create_histogram(
            "capability.execution.duration", unit="s"
        )
        self._capability_attempts = self.meter.create_counter(
            "worker.capability.execution_attempts"
        )
        self._capability_attempt_duration = self.meter.create_histogram(
            "worker.capability.execution_attempt.duration", unit="s"
        )
        self._worker_commands = self.meter.create_counter("worker.command.attempts")
        self._worker_command_failures = self.meter.create_counter(
            "worker.command.failures"
        )
        self._worker_command_duration = self.meter.create_histogram(
            "worker.command.duration", unit="s"
        )
        self._worker_retries = self.meter.create_counter("worker.command.retries")
        self._worker_dlq = self.meter.create_counter("worker.command.dlq")
        self._post_call_executions = self.meter.create_counter("post_call.executions")
        self._post_call_failures = self.meter.create_counter("post_call.failures")
        self._post_call_duration = self.meter.create_histogram(
            "post_call.duration", unit="s"
        )
        self._integration_executions = self.meter.create_counter(
            "integration.executions"
        )
        self._integration_failures = self.meter.create_counter("integration.failures")
        self._integration_duration = self.meter.create_histogram(
            "integration.duration", unit="s"
        )
        self._telephony_reconciliations = self.meter.create_counter(
            "telephony.reconciliations"
        )
        self._telephony_reconciliation_duration = self.meter.create_histogram(
            "telephony.reconciliation.duration", unit="s"
        )
        self._telephony_routing_failures = self.meter.create_counter(
            "telephony.inbound_routing.failures"
        )
        self._telephony_handoff_failures = self.meter.create_counter(
            "telephony.handoff_setup.failures"
        )

    def call_started(self) -> None:
        self._calls_started.add(1)
        self._calls_active.add(1)

    def ai_usage_delta(
        self,
        provider: str,
        service: str,
        model: str,
        counters: dict[str, float],
        estimated_cost_usd: float,
    ) -> None:
        dimensions = {
            "voice.provider": provider,
            "voice.service": service,
            "voice.model": model,
        }
        for name, value in counters.items():
            if value <= 0:
                continue
            attrs = metric_attributes({**dimensions, "voice.usage_kind": name})
            if name.endswith("tokens"):
                self._ai_usage_tokens.add(int(value), attrs)
            elif name in {"audio_duration", "session_duration"}:
                self._ai_usage_seconds.add(value, attrs)
            elif name == "characters_count":
                self._ai_usage_characters.add(int(value), attrs)
        if estimated_cost_usd > 0:
            self._ai_estimated_cost.add(
                estimated_cost_usd, metric_attributes(dimensions)
            )

    def set_active_calls(self, count: int) -> None:
        if count > 0:
            self._calls_active.add(count)

    def call_terminal(
        self, status: str, duration_seconds: float | None, *, was_active: bool
    ) -> None:
        if status == "completed":
            self._calls_completed.add(1)
        else:
            self._calls_failed.add(1, metric_attributes({"status": "failed"}))
        if was_active:
            self._calls_active.add(-1)
        if duration_seconds is not None and duration_seconds >= 0:
            self._call_duration.record(
                duration_seconds, metric_attributes({"status": status})
            )

    def capability_completed(
        self,
        *,
        name: str,
        version: str,
        status: str,
        duration_seconds: float,
        error_type: str | None = None,
    ) -> None:
        attributes = _capability_attributes(name, version, status, error_type)
        self._capability_executions.add(1, attributes)
        self._capability_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._capability_failures.add(1, attributes)

    def capability_attempt(
        self, *, name: str, version: str, status: str, duration_seconds: float
    ) -> None:
        attributes = _capability_attributes(name, version, status)
        self._capability_attempts.add(1, attributes)
        self._capability_attempt_duration.record(duration_seconds, attributes)

    def command_attempt(
        self, *, operation: str, status: str, duration_seconds: float
    ) -> None:
        attributes = metric_attributes({"operation.type": operation, "status": status})
        self._worker_commands.add(1, attributes)
        self._worker_command_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._worker_command_failures.add(1, attributes)

    def command_retry(self, operation: str) -> None:
        self._worker_retries.add(
            1, metric_attributes({"operation.type": operation, "status": "retry"})
        )

    def command_dlq(self, operation: str, error_type: str) -> None:
        self._worker_dlq.add(
            1,
            metric_attributes(
                {
                    "operation.type": operation,
                    "status": "failed",
                    "error.type": error_type,
                }
            ),
        )

    def post_call(
        self, *, operation: str, status: str, duration_seconds: float
    ) -> None:
        attributes = metric_attributes({"operation.type": operation, "status": status})
        self._post_call_executions.add(1, attributes)
        self._post_call_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._post_call_failures.add(1, attributes)

    def integration(self, *, status: str, duration_seconds: float) -> None:
        attributes = metric_attributes(
            {"operation.type": "post_call_action", "status": status}
        )
        self._integration_executions.add(1, attributes)
        self._integration_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._integration_failures.add(1, attributes)

    def telephony_reconciliation(self, status: str, duration_seconds: float) -> None:
        attributes = metric_attributes({"status": status})
        self._telephony_reconciliations.add(1, attributes)
        self._telephony_reconciliation_duration.record(duration_seconds, attributes)

    def telephony_routing_failure(self, reason: str) -> None:
        self._telephony_routing_failures.add(
            1, metric_attributes({"error.type": reason})
        )

    def telephony_handoff_failure(self, reason: str) -> None:
        self._telephony_handoff_failures.add(
            1, metric_attributes({"error.type": reason})
        )


def _capability_attributes(
    name: str, version: str, status: str, error_type: str | None = None
) -> dict[str, str]:
    attributes = {
        "capability.name": name,
        "capability.version": version,
        "status": status,
    }
    if error_type is not None:
        attributes["error.type"] = error_type
    metric_attributes(attributes)
    return attributes
