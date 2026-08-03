import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes"}


def _number(name: str, default, cast):
    value = os.getenv(name)
    return default if value is None else cast(value)


@dataclass(frozen=True)
class LiveKitSettings:
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    internal_url: str = "ws://livekit:7880"
    public_url: str = "ws://localhost:7880"
    backend_url: str = "http://api:8000"
    agent_name: str = "hospitality-voice"
    participant_token_ttl_seconds: int = 120
    backend_token_ttl_seconds: int = 7200
    host: str = "0.0.0.0"
    port: int = 8081
    elevenlabs_api_key: str = ""
    realtime_stt_model: str = "scribe_v2_realtime"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o-mini"
    azure_openai_api_version: str = "2025-01-01-preview"
    session_token_secret: str = ""
    turn_debug_overrides_enabled: bool = False

    @classmethod
    def from_env(cls) -> "LiveKitSettings":
        return cls(
            enabled=_bool("VOICE_LIVEKIT_ENABLED"),
            api_key=os.getenv("LIVEKIT_API_KEY", "").strip(),
            api_secret=os.getenv("LIVEKIT_API_SECRET", "").strip(),
            internal_url=os.getenv("LIVEKIT_INTERNAL_URL", cls.internal_url).strip(),
            public_url=os.getenv("LIVEKIT_PUBLIC_URL", cls.public_url).strip(),
            backend_url=os.getenv("BACKEND_INTERNAL_URL", cls.backend_url).strip(),
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", cls.agent_name).strip(),
            participant_token_ttl_seconds=_number(
                "LIVEKIT_PARTICIPANT_TOKEN_TTL_SECONDS", cls.participant_token_ttl_seconds, int
            ),
            backend_token_ttl_seconds=_number(
                "LIVEKIT_BACKEND_TOKEN_TTL_SECONDS", cls.backend_token_ttl_seconds, int
            ),
            host=os.getenv("LIVEKIT_AGENT_HOST", cls.host).strip(),
            port=_number("LIVEKIT_AGENT_PORT", cls.port, int),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
            realtime_stt_model=os.getenv(
                "ELEVENLABS_REALTIME_STT_MODEL", cls.realtime_stt_model
            ).strip(),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "").strip(),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", "").strip(),
            azure_openai_deployment=os.getenv(
                "AZURE_OPENAI_DEPLOYMENT", cls.azure_openai_deployment
            ).strip(),
            azure_openai_api_version=os.getenv(
                "AZURE_OPENAI_API_VERSION", cls.azure_openai_api_version
            ).strip(),
            session_token_secret=os.getenv("VOICE_SESSION_TOKEN_SECRET", ""),
            turn_debug_overrides_enabled=_bool("VOICE_TURN_DEBUG_OVERRIDES_ENABLED"),
        )

    @property
    def api_url(self) -> str:
        parsed = urlparse(self.internal_url)
        return parsed._replace(scheme="https" if parsed.scheme == "wss" else "http").geturl()

    def validate_api(self) -> None:
        if not self.api_key or len(self.api_secret.encode()) < 32:
            raise ValueError("LIVEKIT_API_KEY and a 32-byte LIVEKIT_API_SECRET are required")
        for name in ("internal_url", "public_url"):
            parsed = urlparse(getattr(self, name))
            if parsed.scheme not in {"ws", "wss"} or not parsed.netloc or parsed.username:
                raise ValueError(f"{name} must be an absolute ws:// or wss:// URL")
        if not self.agent_name or self.participant_token_ttl_seconds <= 0:
            raise ValueError("LIVEKIT_AGENT_NAME and a positive token TTL are required")

    def validate_worker(self) -> None:
        self.validate_api()
        backend = urlparse(self.backend_url)
        if backend.scheme not in {"http", "https"} or not backend.netloc:
            raise ValueError("BACKEND_INTERNAL_URL must be an absolute HTTP URL")
        required = (
            self.elevenlabs_api_key,
            self.realtime_stt_model,
            self.azure_openai_endpoint,
            self.azure_openai_api_key,
            self.azure_openai_deployment,
            self.azure_openai_api_version,
        )
        if not all(required):
            raise ValueError("ElevenLabs and Azure OpenAI voice-agent settings are required")
        if len(self.session_token_secret.encode()) < 32 or self.backend_token_ttl_seconds <= 0:
            raise ValueError("voice backend authentication settings are invalid")
        if not 1 <= self.port <= 65535:
            raise ValueError("LiveKit agent port is invalid")
