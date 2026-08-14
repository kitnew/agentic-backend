from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
DEV = (COMPOSE / "docker-compose.dev.yml").read_text()
BASE = (COMPOSE / "docker-compose.yml").read_text()
DEPLOY = (COMPOSE / "docker-compose.deploy.yml").read_text()
COLLECTOR = (COMPOSE / "otel-collector.yml").read_text()


def test_collector_is_pinned_and_development_only() -> None:
    assert "otel/opentelemetry-collector:0.158.0" in DEV
    assert "otel-collector:" not in BASE + DEPLOY
    assert '"127.0.0.1:${OTEL_COLLECTOR_OTLP_HTTP_PORT:-4318}:4318"' in DEV
    assert '"127.0.0.1:${OTEL_COLLECTOR_HEALTH_PORT:-13133}:13133"' in DEV
    assert "./otel-collector.yml:/etc/otelcol/config.yaml:ro" in DEV
    assert "networks: [application]" in DEV


def test_collector_has_only_debug_trace_and_metric_pipelines() -> None:
    assert "traces:" in COLLECTOR
    assert "metrics:" in COLLECTOR
    assert "logs:" not in COLLECTOR
    assert "debug:" in COLLECTOR
    assert "verbosity: detailed" in COLLECTOR
    assert "batch:" in COLLECTOR
    assert "health_check:" in COLLECTOR
    assert all(term not in COLLECTOR for term in ("storage:", "volume", "loki", "jaeger", "tempo", "prometheus"))
