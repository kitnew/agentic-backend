from backend_core.bootstrap.settings import Settings
from voice_agent.settings import VoiceAgentSettings


def test_python_settings_load_deployment_secret_files(tmp_path, monkeypatch) -> None:
    values = {
        "admin_api_token": "a" * 32,
        "voice_agent_service_secret": "v" * 32,
        "job_worker_service_secret": "j" * 32,
        "livekit_api_secret": "l" * 32,
        "postgres_password": "p" * 12,
        "elevenlabs_api_key": "elevenlabs-file-key",
        "azure_openai_api_key": "azure-file-key",
    }
    for name, value in values.items():
        (tmp_path / name).write_text(value)
        monkeypatch.delenv(name.upper(), raising=False)

    backend = Settings(
        _secrets_dir=tmp_path,
        database_url="postgresql+asyncpg://postgres@postgres:5432/backend",
        livekit_url="ws://livekit:7880",
        livekit_public_url="wss://livekit.example",
        livekit_api_key="key",
        livekit_agent_name="agent",
    )
    assert "pppppppppppp" in backend.database_connection_url()
    assert backend.admin_api_token.get_secret_value() == values["admin_api_token"]

    voice = VoiceAgentSettings(
        _secrets_dir=tmp_path,
        livekit_url="ws://livekit:7880",
        livekit_api_key="key",
        livekit_agent_name="agent",
        backend_core_url="http://backend:8000",
        azure_openai_endpoint="https://azure.example",
        azure_openai_model="model",
        azure_openai_deployment="deployment",
        azure_openai_api_version="2025-01-01",
    )
    assert voice.elevenlabs_api_key.get_secret_value() == values["elevenlabs_api_key"]
    assert voice.azure_openai_api_key.get_secret_value() == values["azure_openai_api_key"]
