from datetime import datetime
from typing import Literal
from uuid import UUID

from contracts.integration import HttpConnectionConfiguration
from pydantic import BaseModel, ConfigDict, Field

from backend_core.modules.integrations.models import IntegrationKind


class CreateIntegrationConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: Literal["http", "google_sheets"]


class UpdateIntegrationConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: object | None = None
    config: dict[str, object] | None = None


class IntegrationCredentialWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=4096)


class ConfigureIntegrationConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: HttpConnectionConfiguration
    credential: IntegrationCredentialWrite | None = None


class IntegrationIssue(BaseModel):
    code: str
    message: str


class IntegrationReadiness(BaseModel):
    configuration: Literal["valid", "incomplete", "invalid"]
    credentials: Literal["not_required", "missing", "configured", "revoked"]
    ready: bool
    usable: bool
    issues: list[IntegrationIssue] = Field(default_factory=list)


class IntegrationConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    key: str
    kind: IntegrationKind
    configuration: dict[str, object]
    enabled: bool
    revision: int
    credential_version: int | None = None
    credential_fingerprint: str | None = None
    credential_status: str | None = None
    readiness: IntegrationReadiness
    created_at: datetime
    updated_at: datetime


class IntegrationPlanChange(BaseModel):
    path: str
    operation: Literal["add", "remove", "replace"]
    before: object | None = None
    after: object | None = None


class IntegrationPlan(BaseModel):
    valid: bool
    changes: list[IntegrationPlanChange] = Field(default_factory=list)
    issues: list[IntegrationIssue] = Field(default_factory=list)
    credential: Literal["rotate", "unchanged"]
    live_apply: Literal[True] = True
    would_be_ready: bool


class IntegrationValidateResponse(IntegrationReadiness):
    pass
