from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: Literal["control-plane-service"] = "control-plane-service"
    http_host: Annotated[str, Field(min_length=1)] = "0.0.0.0"
    http_port: Annotated[int, Field(gt=0, le=65535)] = 8000
    database_url: PostgresDsn
    control_plane_encryption_key: SecretStr
    control_plane_encryption_key_id: Annotated[str, Field(min_length=1)] = "bootstrap"
    voice_agent_service_secret: SecretStr
    job_worker_service_secret: SecretStr
    backend_core_service_secret: SecretStr
    control_plane_management_token: SecretStr = SecretStr("")
    control_plane_management_actor: str = "agentctl"
    nats_url: Annotated[str, Field(min_length=1)] = "nats://nats:4222"
    outbox_poll_interval_seconds: Annotated[float, Field(gt=0)] = 1.0
    otel_enabled: bool = False
