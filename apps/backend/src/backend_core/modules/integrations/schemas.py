from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_core.modules.integrations.models import (
    IntegrationConnectionStatus,
    IntegrationProvider,
)

ConnectionKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class CreateIntegrationConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: ConnectionKey
    provider: IntegrationProvider
    config: dict[str, object] = Field(default_factory=dict)


class UpdateIntegrationConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    config: dict[str, object] | None = None
    status: IntegrationConnectionStatus | None = None

    @model_validator(mode="after")
    def has_change(self) -> UpdateIntegrationConnectionRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("fields cannot be null")
        return self


class IntegrationConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    key: str
    provider: IntegrationProvider
    config: dict[str, object]
    status: IntegrationConnectionStatus
    revision: int
    credential_version: int | None = None
    credential_fingerprint: str | None = None
    created_at: datetime
    updated_at: datetime


class SetIntegrationSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: dict[str, object]


class IntegrationTestResponse(BaseModel):
    integration_id: UUID
    status: str
    credential_version: int
