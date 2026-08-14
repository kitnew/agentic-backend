import os
import subprocess
import time
from pathlib import Path

import pytest
from agentic_observability.bootstrap import bootstrap
from agentic_observability.config import TelemetryConfig

pytestmark = pytest.mark.skipif(
    os.getenv("OTEL_COLLECTOR_SMOKE") != "1",
    reason="set OTEL_COLLECTOR_SMOKE=1 after starting the development collector",
)


def test_collector_receives_synthetic_trace_and_metric() -> None:
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
    with providers.tracer_provider.get_tracer(__name__).start_as_current_span("telemetry.smoke.span"):  # type: ignore[attr-defined]
        pass
    providers.meter_provider.get_meter(__name__).create_counter("telemetry.smoke.counter").add(1)  # type: ignore[attr-defined]
    assert providers.force_flush()
    providers.shutdown()

    compose = Path(__file__).resolve().parents[1] / "infrastructure" / "compose"
    for _ in range(10):
        logs = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                ".env.dev.example",
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.dev.yml",
                "logs",
                "otel-collector",
            ],
            cwd=compose,
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "MINIO_WORKER_SECRET_KEY": os.environ.get(
                    "MINIO_WORKER_SECRET_KEY", "collector-smoke-temporary"
                ),
            },
        ).stdout
        if "telemetry.smoke.span" in logs and "telemetry.smoke.counter" in logs:
            break
        time.sleep(1)
    assert "telemetry.smoke.span" in logs
    assert "telemetry.smoke.counter" in logs
    assert "service.namespace: Str(agentic-backend)" in logs
