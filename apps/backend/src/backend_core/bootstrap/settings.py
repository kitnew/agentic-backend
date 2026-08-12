from typing import Annotated, Self

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Secret = Annotated[SecretStr, Field(min_length=32)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: PostgresDsn
    admin_api_token: Secret
    internal_api_audience: Annotated[str, Field(min_length=1)] = "backend-core"
    voice_agent_service_secret: Secret
    job_worker_service_secret: Secret
    livekit_url: Annotated[str, Field(min_length=1)]
    livekit_public_url: Annotated[str, Field(min_length=1)]
    livekit_api_key: Annotated[SecretStr, Field(min_length=1)]
    livekit_api_secret: Annotated[SecretStr, Field(min_length=1)]
    livekit_agent_name: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    ]
    livekit_participant_token_ttl_seconds: Annotated[
        int,
        Field(gt=0, le=600),
    ] = 600
    livekit_sip_outbound_trunk_id: Annotated[
        str, Field(min_length=1, max_length=255)
    ] | None = None
    redis_url: RedisDsn = RedisDsn("redis://redis:6379/0")
    capability_job_stream: Annotated[str, Field(min_length=1, max_length=255)] = (
        "capability:jobs"
    )
    capability_job_consumer_group: Annotated[
        str, Field(min_length=1, max_length=255)
    ] = "capability-workers"
    capability_job_dead_letter_stream: Annotated[
        str, Field(min_length=1, max_length=255)
    ] = "capability:jobs:dead-letter"
    domain_event_stream: Annotated[str, Field(min_length=1, max_length=255)] = (
        "domain:events"
    )
    command_stream: Annotated[str, Field(min_length=1, max_length=255)] = (
        "application:commands"
    )
    command_result_stream: Annotated[str, Field(min_length=1, max_length=255)] = (
        "application:command-results"
    )
    outbox_dispatch_enabled: bool = False
    outbox_dispatch_interval_seconds: Annotated[float, Field(gt=0, le=60)] = 1.0
    capability_invocation_pii_retention_seconds: Annotated[int, Field(gt=0)] = (
        30 * 24 * 60 * 60
    )
    capability_outbox_retention_seconds: Annotated[int, Field(gt=0)] = 7 * 24 * 60 * 60
    capability_stream_maxlen: Annotated[int, Field(gt=0)] = 10_000
    capability_retention_maintenance_interval_seconds: Annotated[int, Field(gt=0)] = (
        3600
    )
    call_runtime_reconciliation_enabled: bool = True
    call_runtime_reconciliation_interval_seconds: Annotated[
        float, Field(gt=0, le=3600)
    ] = 60.0
    call_runtime_reconciliation_grace_seconds: Annotated[
        float, Field(gt=0, le=86400)
    ] = 120.0
    call_runtime_reconciliation_batch_size: Annotated[int, Field(gt=0, le=1000)] = 100
    call_recording_enabled: bool = False

    @model_validator(mode="after")
    def credentials_must_be_distinct(self) -> Self:
        credentials = {
            self.admin_api_token.get_secret_value(),
            self.voice_agent_service_secret.get_secret_value(),
            self.job_worker_service_secret.get_secret_value(),
        }
        if len(credentials) != 3:
            raise ValueError("admin and service credentials must be distinct")
        return self
