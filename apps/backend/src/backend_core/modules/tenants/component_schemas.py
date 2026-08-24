from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ComponentDraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    comment: str | None = Field(default=None, max_length=4_000)


class ComponentDraftResponse(BaseModel):
    id: UUID
    component: str
    payload: dict[str, Any]
    version: int
    comment: str | None
    updated_at: datetime


class ComponentRevisionResponse(BaseModel):
    id: UUID
    revision_number: int
    payload: dict[str, Any]
    comment: str | None
    sealed_at: datetime


class ComponentStateResponse(BaseModel):
    component: str
    draft: ComponentDraftResponse | None
    active_revision: ComponentRevisionResponse | None


class ComponentPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    version: int = Field(gt=0)
    comment: str | None = Field(default=None, max_length=4_000)


class ComponentDraftExpectation(ComponentPublishRequest):
    component: str


class PublishAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: list[ComponentDraftExpectation] = Field(min_length=1, max_length=7)
    comment: str | None = Field(default=None, max_length=4_000)


class TenantReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    release_number: int
    runtime_bundle_id: UUID
    source_release_id: UUID | None
    created_at: datetime
    comment: str | None


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_release_id: UUID
