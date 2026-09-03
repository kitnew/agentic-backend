from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID


class ResourceKind(StrEnum):
    AGENT = "agent"
    RUNTIME = "runtime"
    PROMPT = "prompt"
    KNOWLEDGE = "knowledge"
    CAPABILITIES = "capabilities"
    POST_CALL = "post_call"


class WorkspaceResourceKind(StrEnum):
    AGENT = "workspace_agent"
    RUNTIME_ARCHITECTURE = "workspace_runtime_architecture"
    RUNTIME_SPEECH = "workspace_runtime_speech"
    PROMPT_PROFILE_SELECTION = "workspace_prompt_profile_selection"
    PROMPT_TENANT = "workspace_prompt_tenant"
    KNOWLEDGE = "workspace_knowledge"
    CAPABILITIES = "workspace_capabilities"
    POST_CALL = "workspace_post_call"
    PLATFORM_RUNTIME_LLM = "platform_runtime_llm"
    PLATFORM_RUNTIME_STT = "platform_runtime_stt"
    PLATFORM_RUNTIME_TTS = "platform_runtime_tts"
    PLATFORM_RUNTIME_CASCADE = "platform_runtime_cascade"
    PLATFORM_RUNTIME_REALTIME = "platform_runtime_realtime"


class PlatformResourceKind(StrEnum):
    SYSTEM_PROMPT = "system_prompt"
    PROFILE_PROMPT = "profile_prompt"


class LiveResourceKind(StrEnum):
    INTEGRATION = "integration"


class DraftResourceKind(StrEnum):
    TELEPHONY = "telephony"


@dataclass(frozen=True, slots=True)
class ResourceId:
    scope: str
    owner: str
    kind: ResourceKind | WorkspaceResourceKind | PlatformResourceKind | LiveResourceKind | DraftResourceKind
    qualifier: str | None = None

    def __str__(self) -> str:
        if self.scope == "platform":
            parts: tuple[str, ...] = (self.scope, self.kind.value)
            return ":".join((*parts, self.qualifier) if self.qualifier else parts)
        parts = (self.scope, self.owner, self.kind.value)
        return ":".join((*parts, self.qualifier) if self.qualifier else parts)


@dataclass(frozen=True, slots=True)
class LocalResource:
    value: Any | None
    present: bool
    valid: bool = True


@dataclass(frozen=True, slots=True)
class RemoteAuthoringState:
    working_value: Any | None
    published_value: Any | None = None
    write_etag: str | None = None
    active_revision_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ResourceStatus:
    resource_id: ResourceId
    local: str
    synchronization: str
    publication: str
    local_fingerprint: str | None
    remote_fingerprint: str | None


def fingerprint(value: Any | None) -> str | None:
    if value is None:
        return None
    import json

    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(data).hexdigest()


def synchronization_state(
    baseline: str | None, local: str | None, remote: str | None
) -> str:
    if baseline is None:
        if local is None and remote is None:
            return "clean"
        if local is None and remote is not None:
            return "initial_remote"
        if local is not None and remote is None:
            return "initial_local"
        return "clean" if local == remote else "unbased_divergence"
    if local == remote:
        return "clean"
    if local != baseline and remote == baseline:
        return "local_changed"
    if local == baseline and remote != baseline:
        return "remote_changed"
    return "conflict"


def publication_state(working: str | None, published: str | None) -> str:
    if working is None and published is None:
        return "empty"
    return "published" if working == published else "unpublished"


def resource_path(root: Path, resource_id: ResourceId) -> Path:
    if resource_id.kind in {LiveResourceKind.INTEGRATION, DraftResourceKind.TELEPHONY}:
        raise ValueError("resource has no local projection")
    if resource_id.scope == "platform":
        if resource_id.kind is ResourceKind.RUNTIME:
            return root / "platform" / "runtime.yaml"
        if resource_id.kind in {
            WorkspaceResourceKind.RUNTIME_ARCHITECTURE,
            WorkspaceResourceKind.RUNTIME_SPEECH,
        }:
            return root / "platform" / "runtime" / f"{resource_id.kind.value.removeprefix('workspace_runtime_')}.yaml"
        if resource_id.kind in {
            WorkspaceResourceKind.PLATFORM_RUNTIME_LLM,
            WorkspaceResourceKind.PLATFORM_RUNTIME_STT,
            WorkspaceResourceKind.PLATFORM_RUNTIME_TTS,
            WorkspaceResourceKind.PLATFORM_RUNTIME_CASCADE,
            WorkspaceResourceKind.PLATFORM_RUNTIME_REALTIME,
        }:
            return root / "platform" / "runtime" / f"{resource_id.kind.value.removeprefix('platform_runtime_')}.yaml"
        if resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
            return root / "platform" / "system_prompt.md"
        if resource_id.kind is PlatformResourceKind.PROFILE_PROMPT:
            qualifier = resource_id.qualifier
            if (
                not qualifier
                or Path(qualifier).name != qualifier
                or "/" in qualifier
                or "\\" in qualifier
                or qualifier in {".", ".."}
            ):
                raise ValueError("unsafe platform profile qualifier")
            return root / "platform" / "profiles" / f"{qualifier}.md"
        raise ValueError(f"unsupported platform resource: {resource_id.kind}")
    base = root / "tenants" / resource_id.owner
    return {
        ResourceKind.AGENT: base / "tenant.yaml",
        ResourceKind.RUNTIME: base / "runtime.yaml",
        ResourceKind.PROMPT: base / "tenant_prompt.md",
        ResourceKind.KNOWLEDGE: base / "knowledge",
        ResourceKind.CAPABILITIES: base / "capabilities.yaml",
        ResourceKind.POST_CALL: base / "post_call.yaml",
        WorkspaceResourceKind.AGENT: base / "agent.yaml",
        WorkspaceResourceKind.RUNTIME_ARCHITECTURE: base / "runtime" / "architecture.yaml",
        WorkspaceResourceKind.RUNTIME_SPEECH: base / "runtime" / "speech.yaml",
        WorkspaceResourceKind.PROMPT_PROFILE_SELECTION: base / "prompt" / "profile_selection.yaml",
        WorkspaceResourceKind.PROMPT_TENANT: base / "prompt" / "tenant.md",
        WorkspaceResourceKind.KNOWLEDGE: base / "knowledge.md",
        WorkspaceResourceKind.CAPABILITIES: base / "capabilities.yaml",
        WorkspaceResourceKind.POST_CALL: base / "post_call.yaml",
    }[resource_id.kind]
