from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend_core.modules.tenants.models import ConfigRevisionStatus, TenantStatus

Slug = Annotated[
    str,
    Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
BusinessType = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class CreateTenantRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: Slug
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    business_type: BusinessType
    status: TenantStatus = TenantStatus.ACTIVE


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    business_type: str
    status: TenantStatus
    active_config_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[int | None, Field(gt=0)] = None
    config: dict[str, Any] | None = None
    comment: Annotated[str | None, Field(max_length=1000)] = None


class UpdateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[int | None, Field(gt=0)] = None
    config: dict[str, Any] | None = None
    comment: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("schema_version", "config", mode="before")
    @classmethod
    def non_nullable_fields_cannot_be_cleared(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> UpdateDraftRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class ConfigRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    revision_number: int
    schema_version: int
    status: ConfigRevisionStatus
    config: dict[str, Any]
    created_at: datetime
    published_at: datetime | None
    created_by: UUID | None
    comment: str | None
    version: int


class ValidationIssue(BaseModel):
    path: str
    code: str
    message: str


class ValidateDraftResponse(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class LegacyTenantIdentity(BaseModel):
    legacy_id: str
    display_name: str
    business_type: str


class LegacyConfigImportResponse(BaseModel):
    revision: ConfigRevisionResponse
    validation: ValidateDraftResponse
    source_tenant: LegacyTenantIdentity
    unsupported_fields: list[str] = Field(default_factory=list)
