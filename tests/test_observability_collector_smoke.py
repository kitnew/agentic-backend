import base64
import json
import os
import time
from secrets import token_hex
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from agentic_observability.bootstrap import bootstrap  # type: ignore[import-untyped]
from agentic_observability.config import TelemetryConfig  # type: ignore[import-untyped]
from opentelemetry.trace import Link, SpanContext, TraceFlags

pytestmark = pytest.mark.skipif(
    os.getenv("OTEL_STORAGE_SMOKE") != "1"
    and os.getenv("OTEL_GRAFANA_SMOKE") != "1",
    reason="set OTEL_STORAGE_SMOKE=1 or OTEL_GRAFANA_SMOKE=1 after starting the development stack",
)


def test_collector_persists_metric_and_trace() -> None:
    prometheus_port = os.getenv("PROMETHEUS_PORT", "9090")
    tempo_port = os.getenv("TEMPO_HTTP_PORT", "3200")
    metric_url = (
        f"http://localhost:{prometheus_port}/api/v1/query?"
        + urlencode(
            {
                "query": (
                    'call_started_total{service_name="backend-core",'
                    'deployment_environment_name="development"}'
                )
            }
        )
    )
    previous = _read_json(metric_url)["data"]["result"]
    previous_value = float(previous[0]["value"][1]) if previous else 0
    call_id = f"smoke-{token_hex(8)}"
    config = TelemetryConfig.from_env(
        default_service_name="backend-core",
        environ={
            "OTEL_ENABLED": "true",
            "OTEL_RESOURCE_ATTRIBUTES": (
                "service.version=smoke,deployment.environment.name=development,"
                "vcs.ref.head.revision=smoke"
            ),
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        },
    )
    providers = bootstrap(config)
    assert providers.tracer_provider is not None
    assert providers.meter_provider is not None
    tracer = providers.tracer_provider.get_tracer(__name__)  # type: ignore[attr-defined]
    link = Link(
        SpanContext(
            trace_id=1,
            span_id=1,
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
    )
    with tracer.start_as_current_span("telemetry.smoke.root", links=[link]) as root:
        root.set_attribute("call.id", call_id)
        with tracer.start_as_current_span("telemetry.smoke.child"):
            pass
    meter = providers.meter_provider.get_meter(__name__)  # type: ignore[attr-defined]
    meter.create_counter("call.started").add(previous_value + 1)
    _emit_dashboard_fixture_metrics(meter)
    assert providers.force_flush()
    providers.shutdown()
    for service_name in ("voice-agent", "job-worker"):
        _emit_correlated_trace(service_name, call_id)

    trace_url = (
        f"http://localhost:{tempo_port}/api/search?"
        + urlencode(
            {
                "q": f'{{ span.call.id = "{call_id}" }}'
            }
        )
    )
    for _ in range(60):
        metrics = _read_json(metric_url)
        traces = _read_json(trace_url)
        metric_result = metrics["data"]["result"]
        if (
            metric_result
            and float(metric_result[0]["value"][1]) >= previous_value + 1
            and {trace["rootServiceName"] for trace in traces["traces"]}
            >= {"backend-core", "voice-agent", "job-worker"}
        ):
            break
        time.sleep(1)
    result = metrics["data"]["result"]
    assert result
    labels = result[0]["metric"]
    assert labels["__name__"] == "call_started_total"
    assert labels["service_name"] == "backend-core"
    assert labels["deployment_environment_name"] == "development"
    assert "call_id" not in labels
    assert float(result[0]["value"][1]) >= previous_value + 1

    trace_id = next(
        trace["traceID"]
        for trace in traces["traces"]
        if trace["rootServiceName"] == "backend-core"
    )
    stored_trace = _read_json(f"http://localhost:{tempo_port}/api/traces/{trace_id}")
    trace_json = json.dumps(stored_trace)
    assert "telemetry.smoke.root" in trace_json
    assert "telemetry.smoke.child" in trace_json
    assert "call.id" in trace_json
    assert call_id in trace_json
    assert "links" in trace_json
    if os.getenv("OTEL_GRAFANA_SMOKE") == "1":
        _assert_grafana_query_path(
            metric_url=metric_url,
            trace_id=trace_id,
            call_id=call_id,
        )


def _emit_correlated_trace(service_name: str, call_id: str) -> None:
    config = TelemetryConfig.from_env(
        default_service_name=service_name,
        environ={
            "OTEL_ENABLED": "true",
            "OTEL_RESOURCE_ATTRIBUTES": (
                "service.version=smoke,deployment.environment.name=development,"
                "vcs.ref.head.revision=smoke"
            ),
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        },
    )
    providers = bootstrap(config)
    assert providers.tracer_provider is not None
    tracer = providers.tracer_provider.get_tracer(__name__)  # type: ignore[attr-defined]
    with tracer.start_as_current_span(f"telemetry.smoke.{service_name}.root") as root:
        root.set_attribute("call.id", call_id)
    assert providers.force_flush()
    providers.shutdown()


def _emit_dashboard_fixture_metrics(meter: Any) -> None:
    capability = {
        "capability.name": "reservation.submit_request",
        "capability.version": "1",
        "status": "failed",
        "error.type": "provider_timeout",
    }
    worker = {"operation.type": "summary_generation", "status": "failed"}
    post_call = {"operation.type": "summary_generation", "status": "failed"}
    integration = {"operation.type": "post_call_action", "status": "failed"}
    voice = {
        "voice.component": "llm",
        "voice.provider": "azure",
        "voice.model": "smoke-model",
        "status": "ok",
    }
    meter.create_up_down_counter("call.active").add(1)
    meter.create_counter("call.completed").add(1)
    meter.create_counter("call.failed").add(1, {"status": "failed"})
    meter.create_histogram("call.duration", unit="s").record(1, {"status": "completed"})
    meter.create_counter("capability.executions").add(1, capability)
    meter.create_counter("capability.failures").add(1, capability)
    meter.create_histogram("capability.execution.duration", unit="s").record(1, capability)
    meter.create_counter("worker.capability.execution_attempts").add(1, capability)
    meter.create_histogram("worker.capability.execution_attempt.duration", unit="s").record(1, capability)
    meter.create_counter("worker.command.attempts").add(1, worker)
    meter.create_counter("worker.command.failures").add(1, worker)
    meter.create_histogram("worker.command.duration", unit="s").record(1, worker)
    meter.create_counter("worker.command.retries").add(1, {"operation.type": "summary_generation", "status": "retry"})
    meter.create_counter("worker.command.dlq").add(1, worker)
    meter.create_counter("post_call.executions").add(1, post_call)
    meter.create_counter("post_call.failures").add(1, post_call)
    meter.create_histogram("post_call.duration", unit="s").record(1, post_call)
    meter.create_counter("integration.executions").add(1, integration)
    meter.create_counter("integration.failures").add(1, integration)
    meter.create_histogram("integration.duration", unit="s").record(1, integration)
    for name in (
        "voice.turn.transcription_delay",
        "voice.turn.end_of_turn_delay",
        "voice.turn.on_user_turn_completed_delay",
        "voice.turn.llm_ttft",
        "voice.turn.tts_ttfb",
        "voice.turn.e2e_latency",
        "voice.llm.duration",
        "voice.llm.ttft",
        "voice.stt.duration",
        "voice.tts.duration",
        "voice.tts.ttfb",
    ):
        meter.create_histogram(name, unit="s").record(1, voice)
    for name in (
        "voice.llm.requests",
        "voice.llm.input_tokens",
        "voice.llm.input_cached_tokens",
        "voice.llm.output_tokens",
        "voice.stt.requests",
        "voice.stt.audio_duration",
        "voice.tts.requests",
        "voice.tts.audio_duration",
        "voice.tts.characters",
    ):
        meter.create_counter(name).add(1, voice)
    meter.create_counter("voice.component.errors").add(1, {**voice, "status": "error"})


def _read_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=2) as response:
        return json.load(response)


def _assert_grafana_query_path(*, metric_url: str, trace_id: str, call_id: str) -> None:
    health = _grafana_json("/api/health")
    assert health["database"] == "ok"
    page = _grafana_text("/")
    assert "Grafana" in page

    datasources = _grafana_json("/api/datasources")
    by_uid = {datasource["uid"]: datasource for datasource in datasources}
    assert {"prometheus", "tempo"} <= set(by_uid)
    assert by_uid["prometheus"]["url"] == "http://prometheus:9090"
    assert by_uid["prometheus"]["isDefault"] is True
    assert by_uid["tempo"]["url"] == "http://tempo:3200"
    assert _grafana_json("/api/datasources/uid/prometheus/health")["status"] == "OK"
    assert _grafana_json("/api/datasources/uid/tempo/health")["status"] == "OK"
    dashboards = _grafana_json("/api/search?type=dash-db")
    dashboard_uids = [dashboard["uid"] for dashboard in dashboards]
    for uid in (
        "agentic-backend-overview",
        "voice-agent",
        "capabilities-worker",
        "post-call-integrations",
    ):
        assert dashboard_uids.count(uid) == 1

    metric = _grafana_json(
        "/api/datasources/proxy/uid/prometheus/api/v1/query?"
        + metric_url.split("?", 1)[1]
    )
    result = metric["data"]["result"]
    assert result
    labels = result[0]["metric"]
    assert labels["service_name"] == "backend-core"
    assert labels["deployment_environment_name"] == "development"
    assert "call_id" not in labels
    _assert_canonical_queries()

    trace = _grafana_json(f"/api/datasources/proxy/uid/tempo/api/traces/{trace_id}")
    trace_json = json.dumps(trace)
    assert "telemetry.smoke.root" in trace_json
    assert "telemetry.smoke.child" in trace_json
    assert "call.id" in trace_json
    assert call_id in trace_json
    assert "links" in trace_json
    trace_search = _grafana_json(
        "/api/datasources/proxy/uid/tempo/api/search?"
        + urlencode(
            {
                "q": f'{{ span.call.id = "{call_id}" }}'
            }
        )
    )
    assert any(result["traceID"] == trace_id for result in trace_search["traces"])
    assert {result["rootServiceName"] for result in trace_search["traces"]} >= {
        "backend-core",
        "voice-agent",
        "job-worker",
    }


def _assert_canonical_queries() -> None:
    labels = 'service_name="backend-core", deployment_environment_name="development"'
    queries = {
        "call throughput": f"sum(rate(call_started_total{{{labels}}}[1m]))",
        "call success rate": (
            f"sum(rate(call_completed_total{{{labels}}}[1m])) / "
            f"(sum(rate(call_completed_total{{{labels}}}[1m])) + "
            f"sum(rate(call_failed_total{{{labels}}}[1m])))"
        ),
        "call duration p95": (
            "histogram_quantile(0.95, sum by (le) "
            f"(rate(call_duration_seconds_bucket{{{labels}}}[1m])))"
        ),
        "logical capability executions": (
            f"sum(rate(capability_executions_total{{{labels}}}[1m]))"
        ),
        "worker retries": f"sum(rate(worker_command_retries_total{{{labels}}}[1m]))",
        "voice E2E p95": (
            "histogram_quantile(0.95, sum by (le) "
            f"(rate(voice_turn_e2e_latency_seconds_bucket{{{labels}}}[1m])))"
        ),
        "post-call executions": f"sum(rate(post_call_executions_total{{{labels}}}[1m]))",
        "integration executions": f"sum(rate(integration_executions_total{{{labels}}}[1m]))",
    }
    for title, query in queries.items():
        result = _grafana_json(
            "/api/datasources/proxy/uid/prometheus/api/v1/query?"
            + urlencode({"query": query})
        )["data"]["result"]
        assert result, title
        assert float(result[0]["value"][1]) >= 0, title


def _grafana_json(path: str) -> Any:
    with _grafana_request(path) as response:
        return json.load(response)


def _grafana_text(path: str) -> str:
    with _grafana_request(path) as response:
        return response.read().decode()


def _grafana_request(path: str) -> Any:
    user = os.getenv("GRAFANA_ADMIN_USER", "admin")
    password = os.getenv("GRAFANA_ADMIN_PASSWORD", "development-grafana-admin-password-change-me")
    authorization = base64.b64encode(f"{user}:{password}".encode()).decode()
    port = os.getenv("GRAFANA_PORT", "3001")
    return urlopen(
        Request(
            f"http://localhost:{port}{path}",
            headers={"Authorization": f"Basic {authorization}"},
        ),
        timeout=2,
    )
