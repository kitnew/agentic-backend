import os
from math import isfinite
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = "sqlite:///./test.db"
    echo: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        settings = cls(
            url=_text("DATABASE_URL", cls.url),
            echo=_text("DB_ECHO", "false").lower() == "true",
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.url.startswith(("sqlite:", "postgresql+psycopg://")):
            raise ValueError("DATABASE_URL must use sqlite or postgresql+psycopg")


@dataclass(frozen=True)
class CapabilitySettings:
    execution_mode: str = "in_process"
    redis_url: str = "redis://localhost:6379/0"
    command_stream: str = "capability:commands"
    consumer_group: str = "capability-workers"
    dead_letter_stream: str = "capability:commands:dead-letter"
    result_timeout_seconds: float = 30
    result_ttl_seconds: int = 300
    idempotency_ttl_seconds: int = 86_400
    max_retries: int = 3
    pending_idle_seconds: float = 60
    worker_concurrency: int = 4

    @classmethod
    def from_env(cls) -> "CapabilitySettings":
        command_stream = _text("CAPABILITY_COMMAND_STREAM", cls.command_stream)
        settings = cls(
            execution_mode=_text("CAPABILITY_EXECUTION_MODE", cls.execution_mode),
            redis_url=_text("REDIS_URL", cls.redis_url),
            command_stream=command_stream,
            consumer_group=_text("CAPABILITY_CONSUMER_GROUP", cls.consumer_group),
            dead_letter_stream=_text(
                "CAPABILITY_DEAD_LETTER_STREAM",
                os.getenv("CAPABILITY_DLQ_STREAM", f"{command_stream}:dead-letter"),
            ),
            result_timeout_seconds=_number(
                "CAPABILITY_RESULT_TIMEOUT_SECONDS", cls.result_timeout_seconds, float
            ),
            result_ttl_seconds=_number(
                "CAPABILITY_RESULT_TTL_SECONDS", cls.result_ttl_seconds, int
            ),
            idempotency_ttl_seconds=_number(
                "CAPABILITY_IDEMPOTENCY_TTL_SECONDS", cls.idempotency_ttl_seconds, int
            ),
            max_retries=_number("CAPABILITY_MAX_RETRIES", cls.max_retries, int),
            pending_idle_seconds=_number(
                "CAPABILITY_PENDING_IDLE_SECONDS", cls.pending_idle_seconds, float
            ),
            worker_concurrency=_number(
                "CAPABILITY_WORKER_CONCURRENCY", cls.worker_concurrency, int
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.execution_mode not in {"in_process", "redis"}:
            raise ValueError("CAPABILITY_EXECUTION_MODE must be 'in_process' or 'redis'")
        for name in (
            "redis_url",
            "command_stream",
            "consumer_group",
            "dead_letter_stream",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        for name in (
            "result_timeout_seconds",
            "result_ttl_seconds",
            "idempotency_ttl_seconds",
            "pending_idle_seconds",
            "worker_concurrency",
        ):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")

    def result_key(self, command_id: str) -> str:
        return f"{self.command_stream}:result:{command_id}"

    def completion_key(self, command_id: str) -> str:
        return f"{self.command_stream}:completed:{command_id}"

    def completion_lock_key(self, command_id: str) -> str:
        return f"{self.completion_key(command_id)}:lock"

    def idempotency_key(self, digest: str) -> str:
        return f"{self.command_stream}:idempotency:{digest}"

    def idempotency_lock_key(self, digest: str) -> str:
        return f"{self.idempotency_key(digest)}:lock"

    def attempt_key(self, stream_id: str) -> str:
        return f"{self.command_stream}:attempt:{stream_id}"


@dataclass(frozen=True)
class AgentRuntimeSettings:
    public_ws_url: str
    session_token_secret: str
    session_token_ttl_seconds: int = 120
    call_session_ttl_seconds: int = 3600
    call_mode_enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8001
    stt_mode: str = "batch"
    realtime_stt_model: str = "scribe_v2_realtime"
    stt_connect_timeout_seconds: float = 10
    stt_finalize_timeout_seconds: float = 10
    stt_max_turn_seconds: float = 30
    stt_max_chunk_bytes: int = 32_000
    call_vad_silence_threshold_seconds: float = 1.5
    call_vad_threshold: float = 0.4
    call_min_speech_duration_ms: int = 100
    call_min_silence_duration_ms: int = 100
    call_max_utterance_seconds: float = 30

    @classmethod
    def from_env(cls) -> "AgentRuntimeSettings":
        settings = cls(
            public_ws_url=_text("AGENT_RUNTIME_PUBLIC_WS_URL", ""),
            session_token_secret=os.getenv("VOICE_SESSION_TOKEN_SECRET", ""),
            session_token_ttl_seconds=_number("VOICE_SESSION_TOKEN_TTL_SECONDS", 120, int),
            call_session_ttl_seconds=_number("VOICE_CALL_SESSION_TTL_SECONDS", 3600, int),
            call_mode_enabled=_text("VOICE_CALL_MODE_ENABLED", "false").lower() in {"1", "true", "yes"},
            host=_text("AGENT_RUNTIME_HOST", "0.0.0.0"),
            port=_number("AGENT_RUNTIME_PORT", 8001, int),
            stt_mode=_text("VOICE_STT_MODE", "batch"),
            realtime_stt_model=_text("ELEVENLABS_REALTIME_STT_MODEL", "scribe_v2_realtime"),
            stt_connect_timeout_seconds=_number("VOICE_STT_CONNECT_TIMEOUT_SECONDS", 10, float),
            stt_finalize_timeout_seconds=_number("VOICE_STT_FINALIZE_TIMEOUT_SECONDS", 10, float),
            stt_max_turn_seconds=_number("VOICE_STT_MAX_TURN_SECONDS", 30, float),
            stt_max_chunk_bytes=_number("VOICE_STT_MAX_CHUNK_BYTES", 32_000, int),
            call_vad_silence_threshold_seconds=_number("VOICE_CALL_VAD_SILENCE_THRESHOLD_SECONDS", 1.5, float),
            call_vad_threshold=_number("VOICE_CALL_VAD_THRESHOLD", .4, float),
            call_min_speech_duration_ms=_number("VOICE_CALL_MIN_SPEECH_DURATION_MS", 100, int),
            call_min_silence_duration_ms=_number("VOICE_CALL_MIN_SILENCE_DURATION_MS", 100, int),
            call_max_utterance_seconds=_number("VOICE_CALL_MAX_UTTERANCE_SECONDS", 30, float),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed = urlparse(self.public_ws_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("AGENT_RUNTIME_PUBLIC_WS_URL must be an absolute ws:// or wss:// URL")
        if len(self.session_token_secret.encode()) < 32 or not self.session_token_secret.strip():
            raise ValueError("VOICE_SESSION_TOKEN_SECRET must contain at least 32 bytes")
        if self.session_token_ttl_seconds <= 0:
            raise ValueError("VOICE_SESSION_TOKEN_TTL_SECONDS must be positive")
        if not self.host:
            raise ValueError("AGENT_RUNTIME_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("AGENT_RUNTIME_PORT must be between 1 and 65535")
        if self.stt_mode not in {"batch", "streaming"}:
            raise ValueError("VOICE_STT_MODE must be 'batch' or 'streaming'")
        if not self.realtime_stt_model:
            raise ValueError("ELEVENLABS_REALTIME_STT_MODEL must not be empty")
        for name in ("stt_connect_timeout_seconds", "stt_finalize_timeout_seconds", "stt_max_turn_seconds", "stt_max_chunk_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.call_session_ttl_seconds <= 0 or self.call_max_utterance_seconds <= 0:
            raise ValueError("call session and utterance limits must be positive")
        if not 0 <= self.call_vad_threshold <= 1:
            raise ValueError("VOICE_CALL_VAD_THRESHOLD must be between 0 and 1")
        if min(self.call_vad_silence_threshold_seconds, self.call_min_speech_duration_ms, self.call_min_silence_duration_ms) <= 0:
            raise ValueError("call VAD durations must be positive")


def _text(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _number(name: str, default, cast):
    raw = os.getenv(name)
    try:
        return default if raw is None else cast(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid {cast.__name__}") from exc
