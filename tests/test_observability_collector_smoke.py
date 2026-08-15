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
    providers.meter_provider.get_meter(__name__).create_counter("call.started").add(  # type: ignore[attr-defined]
        previous_value + 1
    )
    assert providers.force_flush()
    providers.shutdown()

    trace_url = (
        f"http://localhost:{tempo_port}/api/search?"
        + urlencode(
            {
                "q": (
                    '{ resource.service.name = "backend-core" && '
                    f'span.call.id = "{call_id}" }}'
                )
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
            and traces["traces"]
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

    trace_id = traces["traces"][0]["traceID"]
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

    trace = _grafana_json(f"/api/datasources/proxy/uid/tempo/api/traces/{trace_id}")
    trace_json = json.dumps(trace)
    assert "telemetry.smoke.root" in trace_json
    assert "telemetry.smoke.child" in trace_json
    assert "call.id" in trace_json
    assert call_id in trace_json
    assert "links" in trace_json


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
