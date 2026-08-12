from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"


def test_development_has_no_sip_service_or_configuration() -> None:
    assert "livekit-sip" not in (COMPOSE / "docker-compose.yml").read_text()
    assert "livekit-sip" not in (COMPOSE / "docker-compose.dev.yml").read_text()
    assert "LIVEKIT_SIP_" not in (COMPOSE / ".env.dev.example").read_text()


def test_staging_and_production_add_only_internal_sip_topology() -> None:
    for environment in ("staging", "prod"):
        compose = (COMPOSE / f"docker-compose.{environment}.yml").read_text()
        env = (COMPOSE / f".env.{environment}.example").read_text()
        assert "livekit-sip:" in compose
        assert "livekit/sip:v1.2.0" in compose
        assert "address: \"${LIVEKIT_SIP_REDIS_ADDRESS:-redis:6379}\"" in compose
        assert "health_port:" in compose
        assert "ports:" not in compose
        assert "caddy" not in compose.lower()
        assert "LIVEKIT_SIP_WS_URL=" in env
        assert "LIVEKIT_SIP_OUTBOUND_TRUNK_ID=" in env
        assert "LIVEKIT_SIP_OUTBOUND_TRUNK_ID:" in compose
