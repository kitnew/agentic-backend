from typing import Annotated, Self

from pydantic import Field, PostgresDsn, SecretStr, model_validator
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
