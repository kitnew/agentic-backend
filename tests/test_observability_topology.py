import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
DEV = (COMPOSE / "docker-compose.dev.yml").read_text()
BASE = (COMPOSE / "docker-compose.yml").read_text()
DEPLOY = (COMPOSE / "docker-compose.deploy.yml").read_text()
COLLECTOR = (COMPOSE / "otel-collector.yml").read_text()
PROMETHEUS = (COMPOSE / "prometheus.yml").read_text()
TEMPO = (COMPOSE / "tempo.yml").read_text()
GRAFANA = (COMPOSE.parent / "grafana" / "provisioning" / "datasources" / "datasources.yml").read_text()
DASHBOARD_PROVIDER = (
    COMPOSE.parent / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
).read_text()
DASHBOARDS = [
    json.loads(path.read_text()) for path in sorted((COMPOSE.parent / "grafana" / "dashboards").glob("*.json"))
]


def test_collector_is_pinned_and_internal() -> None:
    assert "otel/opentelemetry-collector-contrib:0.158.0" in DEV
    assert "otel-collector:" in DEPLOY
    assert '"127.0.0.1:${OTEL_COLLECTOR_OTLP_HTTP_PORT:-4318}:4318"' in DEV
    assert '"127.0.0.1:${OTEL_COLLECTOR_HEALTH_PORT:-13133}:13133"' in DEV
    assert "./otel-collector.yml:/etc/otelcol/config.yaml:ro" in DEV
    assert "networks: [application]" in DEV


def test_development_storage_is_pinned_private_and_persistent() -> None:
    assert "prom/prometheus:v3.5.0" in DEV
    assert "grafana/tempo:3.0.0" in DEV
    assert '"127.0.0.1:${PROMETHEUS_PORT:-9090}:9090"' in DEV
    assert '"127.0.0.1:${TEMPO_HTTP_PORT:-3200}:3200"' in DEV
    assert "prometheus-data:/prometheus" in DEV
    assert "tempo-data:/var/tempo" in DEV
    assert "prometheus-data:" in DEV
    assert "tempo-data:" in DEV
    assert "4317:4317" not in DEV
    assert "8889:8889" not in DEV


def test_grafana_is_pinned_and_provisioned_from_git() -> None:
    assert "grafana/grafana:12.4.3" in DEV
    assert "grafana:" in DEPLOY
    assert '"127.0.0.1:${GRAFANA_PORT:-3001}:3000"' in DEV
    assert "grafana-data:/var/lib/grafana" in DEV
    assert "grafana-data:" in DEV
    assert "../grafana/provisioning/datasources/datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml:ro" in DEV
    assert "../grafana/provisioning/dashboards/dashboards.yml:/etc/grafana/provisioning/dashboards/dashboards.yml:ro" in DEV
    assert "../grafana/dashboards:/var/lib/grafana/dashboards:ro" in DEV
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD}" in DEV
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD}" in DEPLOY
    assert "healthcheck:" in DEV
    assert "depends_on:" not in DEV.split("  grafana:", 1)[1].split("  redis:", 1)[0]


def test_collector_exports_metrics_to_prometheus_and_traces_to_tempo() -> None:
    assert "traces:" in COLLECTOR
    assert "metrics:" in COLLECTOR
    assert "logs:" not in COLLECTOR
    assert "batch:" in COLLECTOR
    assert "health_check:" in COLLECTOR
    assert "otlp_grpc/tempo:" in COLLECTOR
    assert "endpoint: tempo:4317" in COLLECTOR
    assert "prometheus:" in COLLECTOR
    assert "endpoint: 0.0.0.0:8889" in COLLECTOR
    assert 'set(datapoint.attributes["service_name"], resource.attributes["service.name"])' in COLLECTOR
    assert (
        'set(datapoint.attributes["deployment_environment_name"], '
        'resource.attributes["deployment.environment.name"])' in COLLECTOR
    )
    assert "keep_keys(resource.attributes, [\"service.name\", \"deployment.environment.name\"])" in COLLECTOR
    assert "vcs.ref.head.revision" not in COLLECTOR


def test_storage_configs_keep_the_single_node_boundary() -> None:
    assert "scrape_interval: 15s" in PROMETHEUS
    assert "targets: [otel-collector:8889]" in PROMETHEUS
    assert "rule_files:" not in PROMETHEUS
    assert "backend: local" in TEMPO
    assert "path: /var/tempo/wal" in TEMPO
    assert "path: /var/tempo/blocks" in TEMPO
    assert "endpoint: 0.0.0.0:4317" in TEMPO
    assert all(term not in TEMPO for term in ("s3:", "minio", "multitenancy"))


def test_grafana_datasources_have_stable_internal_identities() -> None:
    assert "prune: true" in GRAFANA
    assert "uid: prometheus" in GRAFANA
    assert "url: http://prometheus:9090" in GRAFANA
    assert "isDefault: true" in GRAFANA
    assert "uid: tempo" in GRAFANA
    assert "url: http://tempo:3200" in GRAFANA
    assert "access: proxy" in GRAFANA
    assert "editable: false" in GRAFANA
    assert "tracesToMetrics:" in GRAFANA
    assert "datasourceUid: prometheus" in GRAFANA
    assert "name: Backend call throughput" in GRAFANA
    assert 'call_started_total{service_name="backend-core"}' in GRAFANA
    assert "key: service.name" not in GRAFANA


def test_dashboards_are_provisioned_with_stable_uids_and_datasources() -> None:
    assert "type: file" in DASHBOARD_PROVIDER
    assert "path: /var/lib/grafana/dashboards" in DASHBOARD_PROVIDER
    assert [dashboard["uid"] for dashboard in DASHBOARDS] == [
        "capabilities-worker",
        "agentic-backend-overview",
        "post-call-integrations",
        "voice-agent",
    ]
    assert {dashboard["title"] for dashboard in DASHBOARDS} == {
        "Agentic Backend — Overview",
        "Capabilities & Worker",
        "Post-call & Integrations",
        "Voice Agent",
    }
    assert len({dashboard["uid"] for dashboard in DASHBOARDS}) == len(DASHBOARDS)
    for dashboard in DASHBOARDS:
        assert dashboard["schemaVersion"] == 41
        assert dashboard["version"] == 1
        assert dashboard["panels"]
        for panel in dashboard["panels"]:
            datasource = panel.get("datasource")
            if datasource:
                assert datasource["uid"] in {"prometheus", "tempo"}


def test_success_and_failure_rates_leave_empty_denominators_as_no_data() -> None:
    dashboards = {dashboard["uid"]: dashboard for dashboard in DASHBOARDS}
    panels = {
        panel["title"]: panel
        for dashboard in dashboards.values()
        for panel in dashboard["panels"]
        if "targets" in panel
    }
    for title in (
        "Call success rate",
        "Capability success rate",
        "Post-call failure rate",
        "Integration failure rate",
    ):
        matched = False
        for panel_title, panel in panels.items():
            if panel_title == title:
                matched = True
                assert "clamp_min" not in " ".join(
                    target["expr"] for target in panel["targets"]
                )
        assert matched
