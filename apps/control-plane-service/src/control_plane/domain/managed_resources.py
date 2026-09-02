import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CredentialRef:
    value: UUID


@dataclass(frozen=True, slots=True)
class ProviderConnectionRef:
    value: UUID


@dataclass(frozen=True, slots=True)
class IntegrationConnectionRef:
    value: UUID


@dataclass(frozen=True, slots=True)
class ModelDeploymentRef:
    value: UUID


@dataclass(frozen=True, slots=True)
class HandoffDestinationRef:
    value: UUID


@dataclass(frozen=True, slots=True)
class PhoneNumberAssignmentRef:
    value: UUID


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class DeploymentKind(StrEnum):
    LLM = "llm"
    REALTIME = "realtime"
    STT = "stt"
    TTS = "tts"


@dataclass(frozen=True, slots=True)
class LLMCapabilities:
    supports_temperature: bool
    supports_reasoning_effort: bool


@dataclass(frozen=True, slots=True)
class RealtimeCapabilities:
    supports_server_vad: bool
    supports_semantic_vad: bool


@dataclass(frozen=True, slots=True)
class STTCapabilities:
    supports_cascade: bool
    supports_realtime_input_transcription: bool


@dataclass(frozen=True, slots=True)
class Credential:
    ref: CredentialRef
    name: str
    active_version_id: UUID | None
    active_secret_version_number: int | None
    status: CredentialStatus
    generation: int
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    revoked_by: str | None


@dataclass(frozen=True, slots=True)
class CredentialVersion:
    id: UUID
    credential_ref: CredentialRef
    version_number: int
    created_at: datetime
    created_by: str
    retired_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    ref: ProviderConnectionRef
    key: str
    provider_kind: str
    credential_ref: CredentialRef
    connection_config: dict[str, Any]
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


@dataclass(frozen=True, slots=True)
class IntegrationConnection:
    ref: IntegrationConnectionRef
    tenant_id: str
    key: str
    integration_kind: str
    config: dict[str, Any]
    credential_ref: CredentialRef | None
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


@dataclass(frozen=True, slots=True)
class ModelDeployment:
    ref: ModelDeploymentRef
    key: str
    connection_ref: ProviderConnectionRef
    deployment_kind: DeploymentKind
    deployment_config: dict[str, Any]
    llm_capabilities: LLMCapabilities | None
    realtime_capabilities: RealtimeCapabilities | None
    stt_capabilities: STTCapabilities | None
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


@dataclass(frozen=True, slots=True)
class HandoffDestination:
    """Current routing data.

    Snapshots may select only enabled destinations; an actual later handoff must
    resolve this ref live and reject a disabled or missing destination. Enabling
    one later never changes an already materialized snapshot.
    """

    ref: HandoffDestinationRef
    tenant_id: str
    key: str
    description: str
    phone_number: str
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


@dataclass(frozen=True, slots=True)
class PhoneNumberAssignment:
    """Stable tenant/DID identity; disabled rows preserve prior ownership history."""

    ref: PhoneNumberAssignmentRef
    tenant_id: str
    phone_number: str
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


HANDOFF_DESTINATION_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")


def normalize_e164(value: str) -> str:
    normalized = value.strip().replace(" ", "").replace("-", "")
    if not E164.fullmatch(normalized):
        raise ValueError("phone_number must be canonical E.164")
    return normalized
