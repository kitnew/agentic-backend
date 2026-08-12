from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
DEPLOY = (COMPOSE / "docker-compose.deploy.yml").read_text()


def test_development_has_no_sip_service_or_configuration() -> None:
    assert "livekit-sip" not in (COMPOSE / "docker-compose.yml").read_text()
    assert "livekit-sip" not in (COMPOSE / "docker-compose.dev.yml").read_text()
    assert "LIVEKIT_SIP_" not in (COMPOSE / ".env.dev.example").read_text()


def test_staging_and_production_add_only_internal_sip_topology() -> None:
    for environment in ("staging", "production"):
        env = (COMPOSE / f".env.{environment}.example").read_text()
        assert "livekit-sip:" in DEPLOY
        assert "livekit/sip:v1.2.0" in DEPLOY
        assert 'address: "127.0.0.1:6379"' in DEPLOY
        assert 'ws_url: "ws://127.0.0.1:7880"' in DEPLOY
        assert "health_port:" in DEPLOY
        assert "network_mode: host" in DEPLOY
        assert "${LIVEKIT_SIP_PORT:-5060}:5060/tcp" not in DEPLOY
        assert "${LIVEKIT_SIP_PORT:-5060}:5060/udp" not in DEPLOY
        assert "${LIVEKIT_SIP_RTP_PORT:-10000-20000}:${LIVEKIT_SIP_RTP_PORT:-10000-20000}/udp" not in DEPLOY
        assert "LIVEKIT_SIP_WS_URL=" not in env
        assert "LIVEKIT_SIP_OUTBOUND_TRUNK_ID=" in env
        assert "LIVEKIT_SIP_OUTBOUND_TRUNK_ID:" in DEPLOY
