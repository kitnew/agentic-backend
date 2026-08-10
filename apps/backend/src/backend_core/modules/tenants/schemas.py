from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    PromptBundleRevisionStatus,
    TenantStatus,
)

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
E164Did = Annotated[
    str,
    Field(
        min_length=3,
        max_length=16,
        pattern=r"^\+[1-9][0-9]{1,14}$",
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
    active_prompt_set_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CreateInboundRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_did: E164Did
    enabled: bool = True


class UpdateInboundRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_did: E164Did | None = None
    enabled: bool | None = None

    @field_validator("normalized_did", "enabled", mode="before")
    @classmethod
    def fields_cannot_be_cleared(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> UpdateInboundRouteRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class InboundRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    normalized_did: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ResolveTenantRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["sip"]
    called_number: E164Did


class TenantRouteResolutionResponse(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    active_config_revision_id: UUID
    active_config_revision_number: int


class CreatePromptBundleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_instructions: Annotated[str, Field(min_length=1, max_length=100_000)]
    tenant_instructions: Annotated[str, Field(max_length=100_000)] = ""
    knowledge_text: Annotated[str, Field(max_length=1_000_000)] = ""


class UpdatePromptBundleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_instructions: (
        Annotated[str, Field(min_length=1, max_length=100_000)] | None
    ) = None
    tenant_instructions: Annotated[str, Field(max_length=100_000)] | None = None
    knowledge_text: Annotated[str, Field(max_length=1_000_000)] | None = None

    @field_validator(
        "system_instructions",
        "tenant_instructions",
        "knowledge_text",
        mode="before",
    )
    @classmethod
    def fields_cannot_be_cleared(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> UpdatePromptBundleDraftRequest:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class PromptBundleRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    revision_number: int
    status: PromptBundleRevisionStatus
    system_instructions: str
    tenant_instructions: str
    knowledge_text: str
    created_at: datetime
    published_at: datetime | None
    version: int


PromptText = Annotated[str, Field(max_length=1_000_000)]


class CreatePlatformPromptDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[
        str, Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    ]
    text: PromptText


class CreateTextDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: PromptText = ""


class UpdateTextDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: PromptText


class PromptTextRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision_number: int
    status: str
    text: str
    created_at: datetime
    published_at: datetime | None
    version: int


class PlatformPromptRevisionResponse(PromptTextRevisionResponse):
    prompt_id: UUID
    key: str


class TenantPromptRevisionResponse(PromptTextRevisionResponse):
    tenant_id: UUID
    prompt_id: UUID


class KnowledgeBaseRevisionResponse(PromptTextRevisionResponse):
    tenant_id: UUID
    knowledge_base_id: UUID


class CreatePromptSetDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt_revision_id: UUID
    profile_prompt_revision_id: UUID
    tenant_prompt_revision_id: UUID
    knowledge_base_revision_id: UUID


class UpdatePromptSetDraftRequest(CreatePromptSetDraftRequest):
    pass


class PromptSetRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    revision_number: int
    status: str
    system_prompt_revision_id: UUID
    profile_prompt_revision_id: UUID
    tenant_prompt_revision_id: UUID
    knowledge_base_revision_id: UUID
    created_at: datetime
    published_at: datetime | None
    version: int


class PromptSetComponentResponse(BaseModel):
    revision_id: UUID
    revision_number: int
    key: str | None = None


class PromptSetCompositionResponse(BaseModel):
    system: PromptSetComponentResponse
    profile: PromptSetComponentResponse
    tenant_prompt: PromptSetComponentResponse
    knowledge_base: PromptSetComponentResponse


class PromptSetDetailResponse(BaseModel):
    revision: PromptSetRevisionResponse
    components: PromptSetCompositionResponse


class PromptSetComponentPlanResponse(BaseModel):
    active: PromptSetComponentResponse | None
    desired: PromptSetComponentResponse
    changed: bool
    reason: str | None = None


class PromptSetPlanComponentsResponse(BaseModel):
    system: PromptSetComponentPlanResponse
    profile: PromptSetComponentPlanResponse
    tenant_prompt: PromptSetComponentPlanResponse
    knowledge_base: PromptSetComponentPlanResponse


class PromptSetPlanResponse(BaseModel):
    tenant_id: UUID
    status: Literal["unchanged", "modified", "missing-active"]
    active_revision_number: int | None
    components: PromptSetPlanComponentsResponse


class PromptSetApplyResponse(BaseModel):
    changed: bool
    prompt_set: PromptSetDetailResponse


class PromptSetRolloutSummaryResponse(BaseModel):
    updated_tenants: int
    unchanged_tenants: int


class PlatformPromptPublishResponse(PromptTextRevisionResponse):
    rollout: PromptSetRolloutSummaryResponse


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


class ValidateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[int, Field(gt=0)]
    config: dict[str, Any]


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


class ValidateConfigResponse(ValidateDraftResponse):
    normalized_config: dict[str, Any] | None = None


class PromptSetResolutionErrorDetail(BaseModel):
    message: str
    errors: list[ValidationIssue]


class PromptSetResolutionErrorResponse(BaseModel):
    detail: PromptSetResolutionErrorDetail


class LegacyTenantIdentity(BaseModel):
    legacy_id: str
    display_name: str
    business_type: str


class LegacyConfigImportResponse(BaseModel):
    revision: ConfigRevisionResponse
    validation: ValidateDraftResponse
    source_tenant: LegacyTenantIdentity
    unsupported_fields: list[str] = Field(default_factory=list)
