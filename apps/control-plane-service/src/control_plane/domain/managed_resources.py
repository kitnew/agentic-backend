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
class ModelDeploymentRef:
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
class ModelDeployment:
    ref: ModelDeploymentRef
    key: str
    connection_ref: ProviderConnectionRef
    deployment_kind: DeploymentKind
    deployment_config: dict[str, Any]
    llm_capabilities: LLMCapabilities | None
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
