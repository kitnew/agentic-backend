from typing import Annotated, Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: Literal["control-plane-service"] = "control-plane-service"
    http_host: Annotated[str, Field(min_length=1)] = "0.0.0.0"
    http_port: Annotated[int, Field(gt=0, le=65535)] = 8000
    database_url: PostgresDsn
    nats_url: Annotated[str, Field(min_length=1)] = "nats://nats:4222"
    otel_enabled: bool = False
