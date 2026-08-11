from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from contracts import ConversationPersistenceStatus
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
    caller_phone_e164: E164Did | None = None
    room_name: Annotated[str, Field(min_length=1, max_length=255)]


class FailCallSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    failure_reason: Annotated[str, Field(min_length=1, max_length=4000)]
    conversation_status: ConversationPersistenceStatus = (
        ConversationPersistenceStatus.INCOMPLETE
    )


class CompleteCallSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_status: ConversationPersistenceStatus = (
        ConversationPersistenceStatus.COMPLETE
    )


class CreateTestVoiceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID


class CreateTestVoiceSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_session_id: UUID
    room_name: str
    livekit_url: str
    participant_identity: str
    participant_token: str


class CallSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    tenant_config_revision_id: UUID
    prompt_set_revision_id: UUID
    voice_runtime_revision_id: UUID | None
    channel: CallChannel
    direction: CallDirection
    provider: str
    provider_call_id: str
    caller_phone_e164: str | None
    provider_dispatch_id: str | None
    room_name: str
    status: CallSessionStatus
    created_at: datetime
    started_at: datetime | None
    connected_at: datetime | None
    ended_at: datetime | None
    failure_reason: str | None
