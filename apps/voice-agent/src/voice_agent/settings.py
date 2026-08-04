from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    livekit_url: Annotated[str, Field(min_length=1)]
    livekit_api_key: Annotated[SecretStr, Field(min_length=1)]
    livekit_api_secret: Annotated[SecretStr, Field(min_length=1)]
    livekit_agent_name: Annotated[str, Field(min_length=1, max_length=128)]

    backend_core_url: Annotated[str, Field(min_length=1)]
    internal_api_audience: Annotated[str, Field(min_length=1)] = "backend-core"
    voice_agent_service_secret: Annotated[SecretStr, Field(min_length=32)]
    backend_http_timeout_seconds: Annotated[float, Field(gt=0)] = 10.0

    elevenlabs_api_key: Annotated[SecretStr, Field(min_length=1)]
    elevenlabs_voice_id: Annotated[str, Field(min_length=1)]
    azure_openai_api_key: Annotated[SecretStr, Field(min_length=1)]
    azure_openai_endpoint: Annotated[str, Field(min_length=1)]
    azure_openai_deployment: Annotated[str, Field(min_length=1)]
    azure_openai_api_version: Annotated[str, Field(min_length=1)]

    provider_timeout_seconds: Annotated[float, Field(gt=0)] = 10.0
    provider_retry_limit: Annotated[int, Field(ge=0)] = 3
    participant_wait_timeout_seconds: Annotated[float, Field(gt=0)] = 300.0
    capability_poll_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 15.0
    capability_poll_interval_seconds: Annotated[float, Field(gt=0, le=5)] = 0.5
