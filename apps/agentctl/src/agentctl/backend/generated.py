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

_SYSTEM_FIELDS = {
    WorkspaceResourceKind.PLATFORM_RUNTIME_LLM: "llm_defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_STT: "stt_defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_TTS: "tts_defaults",
    WorkspaceResourceKind.PLATFORM_RUNTIME_CASCADE: "policies",
    WorkspaceResourceKind.PLATFORM_RUNTIME_REALTIME: "realtime_defaults",
    ResourceKind.RUNTIME: "llm_defaults",
}

_TENANT_FIELDS = {
    WorkspaceResourceKind.AGENT: ("versioned", "agent_personality"),
    WorkspaceResourceKind.RUNTIME_ARCHITECTURE: ("live", "architecture"),
    WorkspaceResourceKind.RUNTIME_SPEECH: ("live", "runtime_overrides"),
    WorkspaceResourceKind.PROMPT_PROFILE_SELECTION: ("live", "profile_reference"),
    WorkspaceResourceKind.PROMPT_TENANT: ("versioned", "tenant_prompt"),
    WorkspaceResourceKind.KNOWLEDGE: ("versioned", "knowledge"),
    WorkspaceResourceKind.CAPABILITIES: ("versioned", "actions_definition"),
    WorkspaceResourceKind.POST_CALL: ("versioned", "business_info"),
    ResourceKind.AGENT: ("versioned", "agent_personality"),
    ResourceKind.RUNTIME: ("live", "architecture"),
    ResourceKind.PROMPT: ("versioned", "tenant_prompt"),
    ResourceKind.KNOWLEDGE: ("versioned", "knowledge"),
    ResourceKind.CAPABILITIES: ("versioned", "actions_definition"),
    ResourceKind.POST_CALL: ("versioned", "business_info"),
}


def _selected(state: dict[str, Any]) -> Any:
    return state.get("draft") or state.get("active")


def _platform_desired(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_prompt": _selected(value["system_prompt"]),
        "profiles": [
            {**profile, "prompt": _selected(profile["prompt"])}
            for profile in value["profiles"]
        ],
        "interaction_modes": [
            {**mode, "prompt": _selected(mode["prompt"])}
            for mode in value["interaction_modes"]
        ],
    }


def _tenant_desired(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value["live"],
        **{key: _selected(state) for key, state in value["versioned"].items()},
    }


class GeneratedPlatformRemoteAdapter:
    """High-level Management API adapter for platform workspace workflows."""

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

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        field = _SYSTEM_FIELDS.get(resource_id.kind)
        if field:
            state = self.client.get_configuration("system")
            value = state.value[field]
            return RemoteAuthoringState(value, value, state.write_etag)
        state = self.client.get_configuration("platform")
        if resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
            prompt = state.value["system_prompt"]
        else:
            prompt = next(
                profile["prompt"]
                for profile in state.value["profiles"]
                if profile["key"] == resource_id.qualifier
            )
        return RemoteAuthoringState(
            _selected(prompt), prompt.get("active"), state.write_etag
        )

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        return PlanResult(
            self.get_state(resource_id).working_value != value, [], [], []
        )

    def save(
        self, resource_id: ResourceId, value: Any, etag: str | None
    ) -> RemoteAuthoringState:
        field = _SYSTEM_FIELDS.get(resource_id.kind)
        if field:
            state = self.client.get_configuration("system")
            self.client.apply_configuration(
                "system", {**state.value, field: value}, etag or state.write_etag
            )
        else:
            state = self.client.get_configuration("platform")
            desired = _platform_desired(state.value)
            if resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
                desired["system_prompt"] = value
            else:
                profile = next(
                    item
                    for item in desired["profiles"]
                    if item["key"] == resource_id.qualifier
                )
                profile["prompt"] = value
            self.client.apply_configuration(
                "platform", desired, etag or state.write_etag
            )
        return self.get_state(resource_id)

    def publish_component(self, resource_id: ResourceId) -> Any:
        if resource_id.kind in _SYSTEM_FIELDS:
            return None
        state = self.client.get_configuration("platform")
        if not state.value["status"]["has_drafts"]:
            return None
        return self.client.publish_configuration("platform", state.write_etag)


class GeneratedRemoteAuthoringAdapter:
    """High-level Management API adapter for tenant workspace workflows."""

    def __init__(self, client: ControlPlaneClient, tenant_id: str) -> None:
        self.client = client
        self.tenant_id = tenant_id

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        return ()

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        lifecycle, field = _TENANT_FIELDS[resource_id.kind]
        state = self.client.get_configuration("tenant", self.tenant_id)
        if lifecycle == "live":
            value = state.value["live"][field]
            return RemoteAuthoringState(value, value, state.write_etag)
        value = state.value["versioned"][field]
        return RemoteAuthoringState(
            _selected(value), value.get("active"), state.write_etag
        )

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        return PlanResult(
            self.get_state(resource_id).working_value != value, [], [], []
        )

    def save(
        self, resource_id: ResourceId, value: Any, etag: str | None
    ) -> RemoteAuthoringState:
        _, field = _TENANT_FIELDS[resource_id.kind]
        state = self.client.get_configuration("tenant", self.tenant_id)
        desired = _tenant_desired(state.value)
        desired[field] = value
        self.client.apply_configuration(
            "tenant", desired, etag or state.write_etag, self.tenant_id
        )
        return self.get_state(resource_id)

    def publish_component(self, resource_id: ResourceId) -> Any:
        state = self.client.get_configuration("tenant", self.tenant_id)
        if not state.value["status"]["has_drafts"]:
            return None
        return self.client.publish_configuration(
            "tenant", state.write_etag, self.tenant_id
        )
