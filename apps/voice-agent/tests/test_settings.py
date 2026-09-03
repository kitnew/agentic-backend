import pytest
from voice_agent.settings import VoiceAgentSettings


def test_settings_require_service_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LIVEKIT_URL": "ws://livekit:7880",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret",
        "LIVEKIT_AGENT_NAME": "voice-agent",
        "BACKEND_CORE_URL": "http://backend:8000",
        "VOICE_AGENT_SERVICE_SECRET": "v" * 32,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = VoiceAgentSettings()  # type: ignore[call-arg]
    assert settings.control_plane_url == "http://control-plane-service:8000"


def test_provider_environment_is_not_a_setting() -> None:
    assert "voice_architecture" not in VoiceAgentSettings.model_fields
