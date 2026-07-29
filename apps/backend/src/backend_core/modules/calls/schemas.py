from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSessionStatus,
)
from backend_core.modules.tenants.schemas import E164Did

ProviderName = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$"),
]


class CreateCallSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    channel: Literal["sip"]
    called_number: E164Did
    provider: ProviderName
    provider_call_id: Annotated[str, Field(min_length=1, max_length=255)]
    room_name: Annotated[str, Field(min_length=1, max_length=255)]


class FailCallSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    failure_reason: Annotated[str, Field(min_length=1, max_length=4000)]


class CallSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    tenant_config_revision_id: UUID
    prompt_bundle_revision_id: UUID
    channel: CallChannel
    direction: CallDirection
    provider: str
    provider_call_id: str
    room_name: str
    status: CallSessionStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    failure_reason: str | None
