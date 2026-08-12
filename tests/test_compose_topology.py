from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
BASE = (COMPOSE / "docker-compose.yml").read_text()
DEV = (COMPOSE / "docker-compose.dev.yml").read_text()
DEPLOY = (COMPOSE / "docker-compose.deploy.yml").read_text()
CADDY = (ROOT / "infrastructure" / "caddy" / "Caddyfile").read_text()
DEBUG_CHAT_NGINX = (ROOT / "apps" / "debug-chat" / "nginx.conf").read_text()
STAGING_ENV = (COMPOSE / ".env.staging.example").read_text()
PRODUCTION_ENV = (COMPOSE / ".env.production.example").read_text()


def test_compose_service_tiers_are_separate() -> None:
    for service in ("backend", "voice-agent", "job-worker", "debug-chat", "redis", "postgres"):
        assert f"  {service}:" in BASE
    assert "  livekit:" in DEV
    for service in ("caddy", "livekit", "livekit-sip", "livekit-egress", "minio", "minio-init"):
        assert f"  {service}:" in DEPLOY
    for service in ("caddy", "livekit-sip", "livekit-egress", "minio", "minio-init"):
        assert f"  {service}:" not in DEV
    assert "CALL_RECORDING_ENABLED: \"false\"" in DEV


def test_deployment_public_ports_and_private_services() -> None:
    for port in ('"80:80"', '"443:443"', '"127.0.0.1:7880:7880"', '"${LIVEKIT_TCP_PORT:-7881}:7881"', '"${LIVEKIT_UDP_PORT:-7882}:7882/udp"', '"127.0.0.1:6379:6379"'):
        assert port in DEPLOY
    for port in ("8000:8000", "5432:5432", "9000:9000", "9001:9001", "8080:8080"):
        assert port not in DEPLOY
    assert '"6379:6379"' not in DEPLOY
    assert "network_mode: host" in DEPLOY
    assert "${LIVEKIT_SIP_PORT:-5060}:5060" not in DEPLOY
    assert "${LIVEKIT_SIP_RTP_PORT:-10000-20000}:${LIVEKIT_SIP_RTP_PORT:-10000-20000}/udp" not in DEPLOY


def test_deployment_keeps_caddy_edge_and_persistent_state() -> None:
    assert "admin off" in CADDY
    assert "basic_auth" in CADDY
    assert "reverse_proxy backend:8000" in CADDY
    assert "reverse_proxy debug-chat:80" in CADDY
    assert "@debug_chat_api path /api/*" in CADDY
    assert "handle @debug_chat_api" in CADDY
    assert "listen 80;" in DEBUG_CHAT_NGINX
    assert "reverse_proxy livekit:7880" in CADDY
    assert "stream_close_delay 5m" in CADDY
    assert "request>headers delete" in CADDY
    assert "request>uri delete" in CADDY
    for volume in ("postgres-data", "redis-data", "minio-data", "caddy-data", "caddy-config"):
        assert f"{volume}:" in BASE or f"{volume}:" in DEPLOY
    assert "restart: \"no\"" in DEPLOY
    assert "restart: unless-stopped" in DEPLOY
    assert "seccomp=../livekit/egress/chrome-sandboxing-seccomp-profile.json" in DEPLOY
    assert "enable_chrome_sandbox: true" in DEPLOY
    assert "./apps/" not in DEPLOY
    assert ":latest" not in BASE + DEV + DEPLOY


def test_deployment_environments_are_selected_only_by_env_file() -> None:
    assert not (COMPOSE / "docker-compose.staging.yml").exists()
    assert not (COMPOSE / "docker-compose.prod.yml").exists()
    assert "COMPOSE_PROJECT_NAME=agentic-backend-staging" in STAGING_ENV
    assert "COMPOSE_PROJECT_NAME=agentic-backend-production" in PRODUCTION_ENV


def test_deployment_credentials_are_env_backed() -> None:
    for name in (
        "POSTGRES_PASSWORD",
        "ADMIN_API_TOKEN",
        "VOICE_AGENT_SERVICE_SECRET",
        "JOB_WORKER_SERVICE_SECRET",
        "LIVEKIT_API_SECRET",
        "ELEVENLABS_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "MINIO_ROOT_PASSWORD",
        "MINIO_EGRESS_SECRET_KEY",
        "MINIO_WORKER_SECRET_KEY",
        "DEBUG_CHAT_BASIC_AUTH_HASH",
    ):
        assert f"{name}:" in BASE or f"{name}:" in DEPLOY
        assert f"{name}=" in STAGING_ENV + PRODUCTION_ENV
    assert "\nSECRETS_DIR=" not in "\n" + STAGING_ENV + "\n" + PRODUCTION_ENV
    assert "\nsecrets:\n" not in DEPLOY


def test_sip_uses_loopback_dependencies_without_docker_networking() -> None:
    assert 'ws_url: "ws://127.0.0.1:7880"' in DEPLOY
    assert 'address: "127.0.0.1:6379"' in DEPLOY
    assert 'rtp_port: "${LIVEKIT_SIP_RTP_PORT:-10000-20000}"' in DEPLOY
    assert (
        "networks: [application]"
        not in DEPLOY.split("  livekit-sip:", 1)[1].split("  caddy:", 1)[0]
    )
