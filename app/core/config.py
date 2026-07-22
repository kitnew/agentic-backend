import os
from math import isfinite
from dataclasses import dataclass


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
class SummarySettings:
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_deployment: str = "gpt-4o-mini"
    azure_api_version: str = "2025-01-01-preview"

    @classmethod
    def from_env(cls) -> "SummarySettings":
        return cls(
            azure_endpoint=_text("AZURE_OPENAI_ENDPOINT", ""),
            azure_api_key=_text("AZURE_OPENAI_API_KEY", ""),
            azure_deployment=_text("AZURE_OPENAI_DEPLOYMENT", cls.azure_deployment),
            azure_api_version=_text("AZURE_OPENAI_API_VERSION", cls.azure_api_version),
        )

    def validate(self) -> None:
        if not all(
            (
                self.azure_endpoint,
                self.azure_api_key,
                self.azure_deployment,
                self.azure_api_version,
            )
        ):
            raise ValueError("Azure OpenAI summary settings are required")


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


def _text(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _number(name: str, default, cast):
    raw = os.getenv(name)
    try:
        return default if raw is None else cast(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid {cast.__name__}") from exc
