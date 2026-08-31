from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    livekit_url: Annotated[str, Field(min_length=1)]
    livekit_api_key: Annotated[SecretStr, Field(min_length=1)]
    livekit_api_secret: Annotated[SecretStr, Field(min_length=1)]
    livekit_agent_name: Annotated[str, Field(min_length=1, max_length=128)]

    backend_core_url: Annotated[str, Field(min_length=1)]
    internal_api_audience: Annotated[str, Field(min_length=1)] = "backend-core"
    voice_agent_service_secret: Annotated[SecretStr, Field(min_length=32)]
    backend_http_timeout_seconds: Annotated[float, Field(gt=0)] = 10.0

    elevenlabs_api_key: Annotated[SecretStr, Field(min_length=1)]
    azure_openai_api_key: Annotated[SecretStr, Field(min_length=1)]
    azure_openai_endpoint: Annotated[str, Field(min_length=1)]
    azure_openai_deployment: Annotated[str, Field(min_length=1)]
    azure_openai_api_version: Annotated[str, Field(min_length=1)]

    voice_architecture: Literal["cascade", "realtime"] = "cascade"
    azure_realtime_endpoint: Annotated[str | None, Field(min_length=1)] = None
    azure_realtime_api_key: Annotated[SecretStr | None, Field(min_length=1)] = None
    azure_realtime_deployment: Annotated[str | None, Field(min_length=1)] = None
    azure_realtime_voice: Annotated[str | None, Field(min_length=1)] = None

    provider_timeout_seconds: Annotated[float, Field(gt=0)] = 10.0
    provider_retry_limit: Annotated[int, Field(ge=0)] = 3
    participant_wait_timeout_seconds: Annotated[float, Field(gt=0)] = 300.0
    capability_poll_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 15.0
    capability_poll_interval_seconds: Annotated[float, Field(gt=0, le=5)] = 0.15

    @model_validator(mode="after")
    def realtime_configuration_is_complete(self) -> Self:
        if self.voice_architecture != "realtime":
            return self
        missing = []
        if self.azure_realtime_endpoint is None:
            missing.append("AZURE_REALTIME_ENDPOINT")
        if self.azure_realtime_api_key is None:
            missing.append("AZURE_REALTIME_API_KEY")
        if self.azure_realtime_deployment is None:
            missing.append("AZURE_REALTIME_DEPLOYMENT")
        if missing:
            raise ValueError(
                "VOICE_ARCHITECTURE=realtime requires " + ", ".join(missing)
            )
        return self
