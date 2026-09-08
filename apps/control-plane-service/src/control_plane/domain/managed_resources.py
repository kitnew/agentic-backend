import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
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


@dataclass(frozen=True, slots=True)
class PlatformCredentialScope:
    type: Literal["platform"] = field(default="platform", init=False)


@dataclass(frozen=True, slots=True)
class TenantCredentialScope:
    tenant_id: str
    type: Literal["tenant"] = field(default="tenant", init=False)


CredentialScope = PlatformCredentialScope | TenantCredentialScope


class DeploymentKind(StrEnum):
    LLM = "llm"
    REALTIME = "realtime"
    STT = "stt"
    TTS = "tts"


@dataclass(frozen=True, slots=True)
class LLMCapabilities:
    supports_temperature: bool
    supports_reasoning_effort: bool
    kind: Literal["llm"] = field(default="llm", init=False)


@dataclass(frozen=True, slots=True)
class RealtimeCapabilities:
    supports_server_vad: bool
    supports_semantic_vad: bool
    kind: Literal["realtime"] = field(default="realtime", init=False)


@dataclass(frozen=True, slots=True)
class STTCapabilities:
    supports_cascade: bool
    supports_realtime_input_transcription: bool
    kind: Literal["stt"] = field(default="stt", init=False)


@dataclass(frozen=True, slots=True)
class TTSCapabilities:
    kind: Literal["tts"] = field(default="tts", init=False)


DeploymentCapabilities = (
    LLMCapabilities | RealtimeCapabilities | STTCapabilities | TTSCapabilities
)


@dataclass(frozen=True, slots=True)
class Credential:
    ref: CredentialRef
    scope: CredentialScope
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
    capabilities: DeploymentCapabilities
    enabled: bool
    generation: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


def capabilities_from_payload(value: dict[str, Any]) -> DeploymentCapabilities:
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise TypeError("invalid deployment capabilities")
    fields = {key: item for key, item in value.items() if key != "kind"}
    try:
        return {
            "llm": LLMCapabilities,
            "realtime": RealtimeCapabilities,
            "stt": STTCapabilities,
            "tts": TTSCapabilities,
        }[kind](**fields)
    except (KeyError, TypeError) as error:
        raise ValueError("invalid deployment capabilities") from error


def capabilities_payload(value: DeploymentCapabilities) -> dict[str, object]:
    payload: dict[str, object] = {"kind": value.kind}
    for name in value.__dataclass_fields__:
        if name != "kind":
            payload[name] = getattr(value, name)
    return payload


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


@dataclass(frozen=True, slots=True)
class InboundRoute:
    tenant_id: str
    phone_number: str
    route_version: str


HANDOFF_DESTINATION_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")


def normalize_e164(value: str) -> str:
    normalized = value.strip().replace(" ", "").replace("-", "")
    if not E164.fullmatch(normalized):
        raise ValueError("phone_number must be canonical E.164")
    return normalized
