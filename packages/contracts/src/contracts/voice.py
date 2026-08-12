from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.capability import RuntimeCapabilityDefinition
from contracts.voice_runtime import EffectiveVoiceRuntime


class _VoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CallLifecycleStatus(StrEnum):
    CREATED = "created"
    STARTED = "started"
    CONNECTED = "connected"
    ENDED = "ended"
    FAILED = "failed"


class VoiceCallObservation(_VoiceModel):
    schema_version: Literal[1] = 1
    observation_type: Literal[
        "session_started",
        "participant_connected",
        "agent_relinquished",
        "session_finished",
        "session_failed",
    ]
    failure_reason: str | None = Field(default=None, min_length=1, max_length=4000)
    conversation_status: Literal["complete", "incomplete"] = "complete"

    @model_validator(mode="after")
    def failure_reason_matches_observation(self) -> VoiceCallObservation:
        failed = self.observation_type == "session_failed"
        if failed != (self.failure_reason is not None):
            raise ValueError("failure_reason is required only for session_failed")
        return self


class LiveKitJobMetadata(_VoiceModel):
    call_session_id: UUID


class InboundSipClaimRequest(_VoiceModel):
    sip_call_id: str = Field(min_length=1, max_length=255)
    sip_call_id_full: str | None = Field(default=None, min_length=1, max_length=255)
    trunk_id: str = Field(min_length=1, max_length=255)
    dispatch_rule_id: str = Field(min_length=1, max_length=255)
    caller_number: str = Field(min_length=1, max_length=64)
    called_number: str = Field(min_length=1, max_length=64)
    room_name: str = Field(min_length=1, max_length=255)
    participant_identity: str = Field(min_length=1, max_length=255)


class InboundSipClaimResponse(_VoiceModel):
    call_session_id: UUID
    created: bool


class HandoffDestinationDefinition(_VoiceModel):
    description: str = Field(min_length=1, max_length=1000)


class HumanHandoffRequest(_VoiceModel):
    tool_call_id: str = Field(min_length=1, max_length=255)
    destination: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class HumanHandoffResponse(_VoiceModel):
    status: Literal["transferred"] = "transferred"
    destination: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class VoiceAgentPrompt(_VoiceModel):
    system_prompt: str = Field(min_length=1)
    profile_prompt: str = ""
    tenant_prompt: str = ""
    knowledge_context: str = ""
    knowledge_base_revision_id: UUID


class VoiceAgentRuntimeContext(_VoiceModel):
    call_session_id: UUID
    voice_runtime_revision_id: UUID
    voice_runtime: EffectiveVoiceRuntime
    room_name: str = Field(min_length=1, max_length=255)
    locale: str = Field(min_length=1, max_length=35)
    timezone: str = Field(min_length=1, max_length=64)
    agent_display_name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(min_length=1, max_length=1000)
    conversation_scope: str = Field(min_length=1, max_length=64)
    prompt: VoiceAgentPrompt
    capabilities: list[RuntimeCapabilityDefinition] = Field(default_factory=list)
    handoff_destinations: dict[str, HandoffDestinationDefinition] = Field(
        default_factory=dict
    )


class CallLifecycleResponse(_VoiceModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )

    call_session_id: UUID
    status: CallLifecycleStatus
    started_at: datetime | None
    connected_at: datetime | None = None
    ended_at: datetime | None
    failure_reason: str | None
