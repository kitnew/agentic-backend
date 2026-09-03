from __future__ import annotations

from typing import Any

from agentctl.backend.facade import PlanResult
from agentctl.control_plane import ControlPlaneClient
from agentctl.workspace.model import (
    PlatformResourceKind,
    RemoteAuthoringState,
    ResourceId,
    ResourceKind,
    WorkspaceResourceKind,
)

_PLATFORM_COMPONENTS = {
    WorkspaceResourceKind.PLATFORM_RUNTIME_LLM: "runtime.llm.defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_STT: "runtime.stt.defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_TTS: "runtime.tts.defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_CASCADE: "runtime.cascade.execution.defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_REALTIME: "runtime.realtime.execution.defaults",
    ResourceKind.RUNTIME: "runtime.llm.defaults",
    PlatformResourceKind.SYSTEM_PROMPT: "prompt.system",
}


class GeneratedPlatformRemoteAdapter:
    """CP-backed adapter used by the existing local workspace engine."""

    def __init__(self, client: ControlPlaneClient) -> None:
        self.client = client

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        return tuple(
            ResourceId("platform", "platform", kind)
            for kind in (
                WorkspaceResourceKind.PLATFORM_RUNTIME_LLM,
                WorkspaceResourceKind.PLATFORM_RUNTIME_STT,
                WorkspaceResourceKind.PLATFORM_RUNTIME_TTS,
                WorkspaceResourceKind.PLATFORM_RUNTIME_CASCADE,
                WorkspaceResourceKind.PLATFORM_RUNTIME_REALTIME,
                PlatformResourceKind.SYSTEM_PROMPT,
            )
        )

    def _kind(self, resource_id: ResourceId) -> str:
        if resource_id.kind is PlatformResourceKind.PROFILE_PROMPT:
            return "prompt.profile"
        return _PLATFORM_COMPONENTS[resource_id.kind]

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        state = self.client.get_component(
            self._kind(resource_id),
            profile_key=(
                resource_id.qualifier
                if resource_id.kind is PlatformResourceKind.PROFILE_PROMPT
                else None
            ),
        )
        return RemoteAuthoringState(
            state.working,
            state.active,
            None if state.draft_version is None else f'"{state.draft_version}"',
        )

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        current = self.get_state(resource_id).working_value
        return PlanResult(current != value, [], [], [])

    def save(
        self, resource_id: ResourceId, value: Any, etag: str | None
    ) -> RemoteAuthoringState:
        version = None if etag is None else int(etag.strip('"'))
        payload = value if isinstance(value, dict) else {"content": value}
        self.client.save_component(
            self._kind(resource_id),
            payload,
            draft_version=version,
            profile_key=(
                resource_id.qualifier
                if resource_id.kind is PlatformResourceKind.PROFILE_PROMPT
                else None
            ),
        )
        return self.get_state(resource_id)

    def publish_component(self, resource_id: ResourceId) -> Any:
        etag = self.get_state(resource_id).write_etag
        if etag is None:
            return None
        return self.client.publish_component(self._kind(resource_id), int(etag.strip('"')), profile_key=resource_id.qualifier)


class GeneratedRemoteAuthoringAdapter:
    """CP-backed tenant adapter retained behind the workspace protocol."""

    def __init__(self, client: ControlPlaneClient, tenant_id: str) -> None:
        self.client = client
        self.tenant_id = tenant_id

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        return ()

    def _kind(self, resource_id: ResourceId) -> str:
        return {
            WorkspaceResourceKind.AGENT: "agent.tenant",
            WorkspaceResourceKind.RUNTIME_ARCHITECTURE: "runtime.architecture.policy",
            WorkspaceResourceKind.RUNTIME_SPEECH: "runtime.speech.overrides",
            WorkspaceResourceKind.PROMPT_PROFILE_SELECTION: "prompt.profile.selection",
            WorkspaceResourceKind.PROMPT_TENANT: "prompt.tenant",
            WorkspaceResourceKind.KNOWLEDGE: "knowledge.tenant",
            WorkspaceResourceKind.CAPABILITIES: "capabilities.tenant",
            WorkspaceResourceKind.POST_CALL: "post_call.tenant",
            ResourceKind.AGENT: "agent.tenant",
            ResourceKind.RUNTIME: "runtime.architecture.policy",
            ResourceKind.PROMPT: "prompt.tenant",
            ResourceKind.KNOWLEDGE: "knowledge.tenant",
            ResourceKind.CAPABILITIES: "capabilities.tenant",
            ResourceKind.POST_CALL: "post_call.tenant",
        }[resource_id.kind]

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        state = self.client.get_component(self._kind(resource_id), tenant_id=self.tenant_id)
        return RemoteAuthoringState(
            state.working,
            state.active,
            None if state.draft_version is None else f'"{state.draft_version}"',
        )

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        return PlanResult(self.get_state(resource_id).working_value != value, [], [], [])

    def save(self, resource_id: ResourceId, value: Any, etag: str | None) -> RemoteAuthoringState:
        self.client.save_component(
            self._kind(resource_id),
            value,
            tenant_id=self.tenant_id,
            draft_version=None if etag is None else int(etag.strip('"')),
        )
        return self.get_state(resource_id)

    def publish_component(self, resource_id: ResourceId) -> Any:
        etag = self.get_state(resource_id).write_etag
        if etag is None:
            return None
        return self.client.publish_component(
            self._kind(resource_id),
            int(etag.strip('"')),
            tenant_id=self.tenant_id,
        )
