import pytest
from pydantic import ValidationError
from voice_agent.settings import VoiceAgentSettings


def configure_cascade_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LIVEKIT_URL": "ws://livekit:7880",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret",
        "LIVEKIT_AGENT_NAME": "hospitality-voice-agent",
        "BACKEND_CORE_URL": "http://backend:8000",
        "VOICE_AGENT_SERVICE_SECRET": "v" * 32,
        "ELEVENLABS_API_KEY": "eleven-key",
        "AZURE_OPENAI_API_KEY": "cascade-key",
        "AZURE_OPENAI_ENDPOINT": "https://cascade.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT": "cascade-deployment",
        "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in (
        "VOICE_ARCHITECTURE",
        "AZURE_REALTIME_ENDPOINT",
        "AZURE_REALTIME_API_KEY",
        "AZURE_REALTIME_DEPLOYMENT",
        "AZURE_REALTIME_VOICE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_voice_architecture_defaults_to_cascade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_cascade_environment(monkeypatch)

    settings = VoiceAgentSettings()  # type: ignore[call-arg]

    assert settings.voice_architecture == "cascade"


def test_explicit_cascade_does_not_require_realtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_cascade_environment(monkeypatch)
    monkeypatch.setenv("VOICE_ARCHITECTURE", "cascade")

    settings = VoiceAgentSettings()  # type: ignore[call-arg]

    assert settings.azure_realtime_endpoint is None
    assert settings.azure_realtime_api_key is None
    assert settings.azure_realtime_deployment is None


def test_realtime_configuration_is_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_cascade_environment(monkeypatch)
    monkeypatch.setenv("VOICE_ARCHITECTURE", "realtime")
    monkeypatch.setenv("AZURE_REALTIME_ENDPOINT", "https://realtime.openai.azure.com")
    monkeypatch.setenv("AZURE_REALTIME_API_KEY", "realtime-key")
    monkeypatch.setenv("AZURE_REALTIME_DEPLOYMENT", "gpt-realtime-2.1-mini")
    monkeypatch.setenv("AZURE_REALTIME_VOICE", "verse")

    settings = VoiceAgentSettings()  # type: ignore[call-arg]

    assert settings.voice_architecture == "realtime"
    assert settings.azure_realtime_endpoint == "https://realtime.openai.azure.com"
    assert settings.azure_realtime_api_key is not None
    assert settings.azure_realtime_api_key.get_secret_value() == "realtime-key"
    assert settings.azure_realtime_deployment == "gpt-realtime-2.1-mini"
    assert settings.azure_realtime_voice == "verse"
    assert settings.azure_openai_api_key.get_secret_value() == "cascade-key"
    assert settings.azure_openai_endpoint == "https://cascade.openai.azure.com"
    assert settings.azure_openai_deployment == "cascade-deployment"


def test_realtime_configuration_reports_missing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_cascade_environment(monkeypatch)
    monkeypatch.setenv("VOICE_ARCHITECTURE", "realtime")
    monkeypatch.setenv("AZURE_REALTIME_ENDPOINT", "https://realtime.openai.azure.com")
    monkeypatch.setenv("AZURE_REALTIME_API_KEY", "realtime-key")

    with pytest.raises(ValidationError) as error:
        VoiceAgentSettings()  # type: ignore[call-arg]

    assert "VOICE_ARCHITECTURE=realtime" in str(error.value)
    assert "AZURE_REALTIME_DEPLOYMENT" in str(error.value)


def test_invalid_voice_architecture_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_cascade_environment(monkeypatch)
    monkeypatch.setenv("VOICE_ARCHITECTURE", "invalid")

    with pytest.raises(ValidationError, match="voice_architecture"):
        VoiceAgentSettings()  # type: ignore[call-arg]
