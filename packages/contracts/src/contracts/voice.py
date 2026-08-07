from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.capability import RuntimeCapabilityDefinition


class _VoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CallLifecycleStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class LiveKitJobMetadata(_VoiceModel):
    call_session_id: UUID


class VoiceAgentPrompt(_VoiceModel):
    system_prompt: str = Field(min_length=1)
    profile_prompt: str = ""
    tenant_prompt: str = ""
    knowledge_context: str = ""
    knowledge_base_revision_id: UUID


class VoiceAgentRuntimeContext(_VoiceModel):
    call_session_id: UUID
    room_name: str = Field(min_length=1, max_length=255)
    locale: str = Field(min_length=1, max_length=35)
    timezone: str = Field(min_length=1, max_length=64)
    agent_display_name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)
    conversation_scope: str = Field(min_length=1, max_length=64)
    prompt: VoiceAgentPrompt
    capabilities: list[RuntimeCapabilityDefinition] = Field(default_factory=list)


class CallLifecycleResponse(_VoiceModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )

    call_session_id: UUID
    status: CallLifecycleStatus
    started_at: datetime | None
    ended_at: datetime | None
    failure_reason: str | None
