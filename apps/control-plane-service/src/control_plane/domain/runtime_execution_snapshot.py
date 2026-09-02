import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, TypeAdapter

from control_plane.domain.managed_resources import (
    CredentialRef,
    DeploymentKind,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.domain.runtime_components import (
    CascadeExecutionDefaults,
    LLMDefaults,
    RealtimeInterruptionPolicy,
    RealtimeTurnCompletion,
    STTDefaults,
    TTSDefaults,
)
from control_plane.domain.runtime_resolution import (
    CandidateAttempt,
    CandidateFailure,
    ComponentProvenance,
    CredentialProvenance,
    ResolutionFailureReason,
    ResolvedCascadeExecution,
    ResolvedCascadeLLM,
    ResolvedCascadeRuntime,
    ResolvedCascadeSTT,
    ResolvedCascadeTTS,
    ResolvedKeyterms,
    ResolvedProviderResource,
    ResolvedRealtimeModel,
    ResolvedRealtimeRuntime,
    ResolvedRealtimeTranscription,
    ResolvedRuntime,
    ResolvedSpeechHints,
    RuntimeResolution,
    SpeechHintStatus,
)

SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    snapshot_id: UUID
    schema_version: int
    tenant_id: str
    architecture: str
    created_at: datetime
    execution: Mapping[str, object]
    runtime: ResolvedRuntime
    resolution: RuntimeResolution
    content_hash: str


def snapshot_payload(
    tenant_id: str,
    resolution: RuntimeResolution,
    execution: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "architecture": resolution.selected.architecture,
        "runtime": _json_value(resolution.selected),
        "execution": _json_value(execution or {"runtime": resolution.selected}),
        "resolution": {
            "architecture_policy": _json_value(resolution.architecture_policy),
            "speech_overrides": _json_value(resolution.speech_overrides),
            "attempts": _json_value(resolution.attempts),
        },
    }


def content_hash(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def snapshot_from_payload(
    snapshot_id: UUID,
    created_at: datetime,
    payload: Mapping[str, object],
    digest: str,
) -> ExecutionSnapshot:
    runtime_raw = _mapping(payload["runtime"])
    resolution_raw = _mapping(payload["resolution"])
    runtime = _runtime(runtime_raw)
    resolution = RuntimeResolution(
        runtime,
        _provenance(_mapping(resolution_raw["architecture_policy"])),
        _provenance(_mapping(resolution_raw["speech_overrides"])),
        tuple(_attempt(_mapping(value)) for value in resolution_raw["attempts"]),
    )
    return ExecutionSnapshot(
        snapshot_id,
        int(cast(Any, payload["schema_version"])),
        str(payload["tenant_id"]),
        str(payload["architecture"]),
        created_at,
        _mapping(payload.get("execution", {"runtime": runtime})),
        runtime,
        resolution,
        digest,
    )




def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value


def _provenance(value: Mapping[str, Any]) -> ComponentProvenance:
    return ComponentProvenance(
        value["component_kind"],
        value["scope_type"],
        value["scope_key"],
        UUID(value["revision_id"]),
        value["revision_number"],
        value["schema_version"],
    )


def _resource(value: Mapping[str, Any]) -> ResolvedProviderResource:
    deployment = _mapping(value["deployment"])
    connection = _mapping(value["connection"])
    credential = _mapping(value["credential"])
    return ResolvedProviderResource(
        ModelDeployment(
            ModelDeploymentRef(_uuid(deployment["ref"])),
            deployment["key"],
            ProviderConnectionRef(_uuid(deployment["connection_ref"])),
            DeploymentKind(deployment["deployment_kind"]),
            deployment["deployment_config"],
            LLMCapabilities(**deployment["llm_capabilities"])
            if deployment["llm_capabilities"]
            else None,
            RealtimeCapabilities(**deployment["realtime_capabilities"])
            if deployment["realtime_capabilities"]
            else None,
            STTCapabilities(**deployment["stt_capabilities"])
            if deployment["stt_capabilities"]
            else None,
            deployment["enabled"],
            deployment["generation"],
            datetime.fromisoformat(deployment["created_at"]),
            deployment["created_by"],
            datetime.fromisoformat(deployment["updated_at"]),
            deployment["updated_by"],
        ),
        ProviderConnection(
            ProviderConnectionRef(_uuid(connection["ref"])),
            connection["key"],
            connection["provider_kind"],
            CredentialRef(_uuid(connection["credential_ref"])),
            connection["connection_config"],
            connection["enabled"],
            connection["generation"],
            datetime.fromisoformat(connection["created_at"]),
            connection["created_by"],
            datetime.fromisoformat(connection["updated_at"]),
            connection["updated_by"],
        ),
        CredentialProvenance(
            _uuid(credential["credential_ref"]),
            credential["generation"],
            credential["status"],
            _uuid(credential["active_version_id"])
            if credential["active_version_id"]
            else None,
            credential["active_secret_version_number"],
        ),
    )


def _hints(value: Mapping[str, Any]) -> ResolvedSpeechHints:
    keyterms = _mapping(value["keyterms"])
    return ResolvedSpeechHints(
        ResolvedKeyterms(
            SpeechHintStatus(keyterms["status"]), tuple(keyterms["values"])
        )
    )


def _runtime(value: Mapping[str, Any]) -> ResolvedRuntime:
    if value["architecture"] == "cascade":
        llm, stt, tts, execution = (
            _mapping(value[key]) for key in ("llm", "stt", "tts", "execution")
        )
        return ResolvedCascadeRuntime(
            "cascade",
            ResolvedCascadeLLM(
                _provenance(_mapping(llm["component"])),
                LLMDefaults.model_validate(llm["parameters"]),
                _resource(_mapping(llm["resource"])),
            ),
            ResolvedCascadeSTT(
                _provenance(_mapping(stt["component"])),
                STTDefaults.model_validate(stt["defaults"]),
                _resource(_mapping(stt["resource"])),
                stt["language"],
                _hints(_mapping(stt["speech_hints"])),
            ),
            ResolvedCascadeTTS(
                _provenance(_mapping(tts["component"])),
                TTSDefaults.model_validate(tts["defaults"]),
                _resource(_mapping(tts["resource"])),
                tts["voice"],
            ),
            ResolvedCascadeExecution(
                _provenance(_mapping(execution["component"])),
                CascadeExecutionDefaults.model_validate(execution["policy"]),
            ),
        )
    model, transcription = (
        _mapping(value["model"]),
        _mapping(value["input_transcription"]),
    )
    return ResolvedRealtimeRuntime(
        "realtime",
        ResolvedRealtimeModel(
            _provenance(_mapping(model["component"])),
            _resource(_mapping(model["resource"])),
        ),
        ResolvedRealtimeTranscription(
            _resource(_mapping(transcription["resource"])),
            transcription["language"],
            _hints(_mapping(transcription["speech_hints"])),
        ),
        value["voice"],
        TypeAdapter(RealtimeTurnCompletion).validate_python(value["turn_completion"]),
        RealtimeInterruptionPolicy.model_validate(value["interruption"]),
    )


def _attempt(value: Mapping[str, Any]) -> CandidateAttempt:
    failure = value["failure"]
    return CandidateAttempt(
        value["architecture"],
        value["status"],
        CandidateFailure(
            _mapping(failure)["architecture"],
            ResolutionFailureReason(_mapping(failure)["reason"]),
            _mapping(failure)["details"],
        )
        if failure
        else None,
    )


def _uuid(value: object) -> UUID:
    return (
        UUID(str(_mapping(value)["value"]))
        if isinstance(value, Mapping)
        else UUID(str(value))
    )
