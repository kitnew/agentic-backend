from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _ExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuntimeSecretSlot(StrEnum):
    LLM = "llm"
    STT = "stt"
    TTS = "tts"
    MODEL = "model"
    INPUT_TRANSCRIPTION = "input_transcription"


class CreateExecutionRequest(_ExecutionContract):
    tenant_id: str = Field(min_length=1, max_length=255)
    context: dict[str, object] | None = None


class BackendExecutionContext(_ExecutionContract):
    execution_id: UUID
    tenant_id: str = Field(min_length=1, max_length=255)
    architecture: str = Field(min_length=1)
    backend_actions: dict[str, object]
    handoff: list[dict[str, object]]
    metadata: dict[str, object]


class VoiceExecutionContext(_ExecutionContract):
    execution_id: UUID
    tenant: dict[str, object]
    agent: dict[str, object]
    architecture: str = Field(min_length=1)
    prompts: dict[str, object]
    runtime: dict[str, object]
    actions: list[dict[str, object]]
    handoff: list[dict[str, object]]


class WorkerExecutionContext(_ExecutionContract):
    execution_id: UUID
    tenant_id: str = Field(min_length=1, max_length=255)
    action: dict[str, object]
    integration: dict[str, object] | None = None


class RuntimeSecretMaterial(_ExecutionContract):
    slot: RuntimeSecretSlot
    secret: str = Field(min_length=1)

    def __repr__(self) -> str:
        return f"RuntimeSecretMaterial(slot={self.slot!r}, secret='***')"


class IntegrationExecutionMaterial(_ExecutionContract):
    integration_kind: str = Field(min_length=1)
    config: dict[str, object]
    secret: str | None = None

    def __repr__(self) -> str:
        return (
            "IntegrationExecutionMaterial("
            f"integration_kind={self.integration_kind!r}, "
            f"secret={'***' if self.secret else None!r})"
        )


class HandoffExecutionMaterial(_ExecutionContract):
    destination_key: str = Field(min_length=1)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")


class InboundRoute(_ExecutionContract):
    tenant_id: str = Field(min_length=1, max_length=255)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    route_version: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str


class ErrorResponse(_ExecutionContract):
    code: str
    message: str
    issues: list[ValidationIssue] | None = None
    details: dict[str, Any] | None = None
    request_id: str
