from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from control_plane.domain.managed_resources import ModelDeployment, ProviderConnection
from control_plane.domain.runtime_components import (
    ArchitectureKind,
    CascadeExecutionDefaults,
    LLMDefaults,
    RealtimeInterruptionPolicy,
    RealtimeTurnCompletion,
    STTDefaults,
    TTSDefaults,
)


class ResolutionFailureReason(StrEnum):
    MISSING_TENANT_COMPONENT = "MISSING_TENANT_COMPONENT"
    MISSING_PLATFORM_COMPONENT = "MISSING_PLATFORM_COMPONENT"
    MISSING_RESOURCE = "MISSING_RESOURCE"
    RESOURCE_DISABLED = "RESOURCE_DISABLED"
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED"
    WRONG_RESOURCE_KIND = "WRONG_RESOURCE_KIND"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    INCOMPATIBLE_CONNECTION = "INCOMPATIBLE_CONNECTION"
    INCOMPATIBLE_PROVIDER = "INCOMPATIBLE_PROVIDER"
    INVALID_VOICE = "INVALID_VOICE"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    CURRENT_STATE_INVALID = "CURRENT_STATE_INVALID"


@dataclass(frozen=True, slots=True)
class ComponentProvenance:
    component_kind: str
    scope_type: str
    scope_key: str | None
    revision_id: UUID
    revision_number: int
    schema_version: int


@dataclass(frozen=True, slots=True)
class CredentialProvenance:
    credential_ref: UUID
    generation: int
    status: str
    active_version_id: UUID | None
    active_secret_version_number: int | None


@dataclass(frozen=True, slots=True)
class ResolvedProviderResource:
    deployment: ModelDeployment
    connection: ProviderConnection
    credential: CredentialProvenance


class SpeechHintStatus(StrEnum):
    APPLIED = "applied"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ResolvedKeyterms:
    status: SpeechHintStatus
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSpeechHints:
    keyterms: ResolvedKeyterms


@dataclass(frozen=True, slots=True)
class ResolvedCascadeLLM:
    component: ComponentProvenance
    parameters: LLMDefaults
    resource: ResolvedProviderResource


@dataclass(frozen=True, slots=True)
class ResolvedCascadeSTT:
    component: ComponentProvenance
    defaults: STTDefaults
    resource: ResolvedProviderResource
    language: str
    speech_hints: ResolvedSpeechHints


@dataclass(frozen=True, slots=True)
class ResolvedCascadeTTS:
    component: ComponentProvenance
    defaults: TTSDefaults
    resource: ResolvedProviderResource
    voice: str


@dataclass(frozen=True, slots=True)
class ResolvedCascadeExecution:
    component: ComponentProvenance
    policy: CascadeExecutionDefaults


@dataclass(frozen=True, slots=True)
class ResolvedCascadeRuntime:
    architecture: Literal["cascade"]
    llm: ResolvedCascadeLLM
    stt: ResolvedCascadeSTT
    tts: ResolvedCascadeTTS
    execution: ResolvedCascadeExecution


@dataclass(frozen=True, slots=True)
class ResolvedRealtimeModel:
    component: ComponentProvenance
    resource: ResolvedProviderResource


@dataclass(frozen=True, slots=True)
class ResolvedRealtimeTranscription:
    resource: ResolvedProviderResource
    language: str
    speech_hints: ResolvedSpeechHints


@dataclass(frozen=True, slots=True)
class ResolvedRealtimeRuntime:
    architecture: Literal["realtime"]
    model: ResolvedRealtimeModel
    input_transcription: ResolvedRealtimeTranscription
    voice: str
    turn_completion: RealtimeTurnCompletion
    interruption: RealtimeInterruptionPolicy


ResolvedRuntime = ResolvedCascadeRuntime | ResolvedRealtimeRuntime


@dataclass(frozen=True, slots=True)
class CandidateFailure:
    architecture: ArchitectureKind
    reason: ResolutionFailureReason
    details: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CandidateAttempt:
    architecture: ArchitectureKind
    status: Literal["selected", "rejected"]
    failure: CandidateFailure | None = None


@dataclass(frozen=True, slots=True)
class RuntimeResolution:
    selected: ResolvedRuntime
    architecture_policy: ComponentProvenance
    speech_overrides: ComponentProvenance
    attempts: tuple[CandidateAttempt, ...]


class RuntimeResolutionError(Exception):
    def __init__(
        self,
        reason: ResolutionFailureReason,
        details: Mapping[str, object],
        attempts: tuple[CandidateAttempt, ...] = (),
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.details = details
        self.attempts = attempts
