from datetime import datetime
from enum import StrEnum
from uuid import UUID

from contracts import (
    EffectiveVoiceRuntime,
    PlatformRuntimePolicy,
    TenantRuntimeOverride,
)
from pydantic import BaseModel, ConfigDict

from backend_core.modules.voice_runtime.models import RuntimeRevisionStatus


class PlatformRuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: PlatformRuntimePolicy


class TenantRuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: TenantRuntimeOverride


class PlatformRuntimeRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    revision_number: int
    status: RuntimeRevisionStatus
    policy: PlatformRuntimePolicy
    created_at: datetime
    published_at: datetime | None
    version: int


class TenantRuntimeRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    revision_number: int
    status: RuntimeRevisionStatus
    settings: TenantRuntimeOverride
    created_at: datetime
    published_at: datetime | None
    version: int


class PlatformRuntimeStateResponse(BaseModel):
    latest_published_revision: PlatformRuntimeRevisionResponse | None
    draft_revision: PlatformRuntimeRevisionResponse | None


class TenantRuntimeStateResponse(BaseModel):
    latest_published_revision: TenantRuntimeRevisionResponse | None
    draft_revision: TenantRuntimeRevisionResponse | None


class VoiceRuntimeRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    revision_number: int
    status: RuntimeRevisionStatus
    platform_runtime_revision_id: UUID
    tenant_runtime_revision_id: UUID | None
    effective_settings: EffectiveVoiceRuntime
    created_at: datetime
    published_at: datetime


class VoiceRuntimePlanStatus(StrEnum):
    MISSING_ACTIVE = "missing-active"
    UNCHANGED = "unchanged"
    MODIFIED = "modified"


class VoiceRuntimeChange(BaseModel):
    path: str
    before: object | None
    after: object


class VoiceRuntimePlanResponse(BaseModel):
    status: VoiceRuntimePlanStatus
    active_revision: VoiceRuntimeRevisionResponse | None
    desired_settings: EffectiveVoiceRuntime
    platform_runtime_revision_id: UUID
    tenant_runtime_revision_id: UUID | None
    changes: list[VoiceRuntimeChange]


class VoiceRuntimeApplyResponse(BaseModel):
    changed: bool
    voice_runtime: VoiceRuntimeRevisionResponse


class RuntimeValidationResponse(BaseModel):
    valid: bool = True
