from __future__ import annotations

from typing import Any
from uuid import UUID

from admin_client import AuthenticatedClient
from admin_client.generated.api.adminplatform_components import (
    plan_profile_prompt_admin_v1_platform_components_profiles_profile_plan_post,
    plan_runtime_admin_v1_platform_components_runtime_plan_post,
    plan_system_prompt_admin_v1_platform_components_system_prompt_plan_post,
    publish_admin_v1_platform_components_publish_post,
    save_profile_prompt_admin_v1_platform_components_profiles_profile_draft_put,
    save_runtime_admin_v1_platform_components_runtime_draft_put,
    save_system_prompt_admin_v1_platform_components_system_prompt_draft_put,
    state_admin_v1_platform_components_state_get,
)
from admin_client.generated.models.platform_publish_request import (
    PlatformPublishRequest,
)
from admin_client.generated.models.platform_publish_request_profile_prompt_versions import (
    PlatformPublishRequestProfilePromptVersions,
)
from admin_client.generated.models.platform_runtime_policy import PlatformRuntimePolicy
from admin_client.generated.models.prompt_draft_write import PromptDraftWrite
from admin_client.generated.models.runtime_draft_write import RuntimeDraftWrite
from admin_client.generated.types import UNSET
from control_plane.backend.facade import PlanResult
from control_plane.commands.errors import CommandError
from control_plane.workspace.model import (
    PlatformResourceKind,
    RemoteAuthoringState,
    ResourceId,
    ResourceKind,
)
from control_plane.workspace.registry import publishable_component_names

_COMPONENTS = {
    ResourceKind.AGENT: "agent",
    ResourceKind.RUNTIME: "runtime",
    ResourceKind.PROMPT: "prompt",
    ResourceKind.KNOWLEDGE: "knowledge",
    ResourceKind.CAPABILITIES: "capabilities",
    ResourceKind.POST_CALL: "post_call",
}
_AUTHORING = {
    **_COMPONENTS,
    ResourceKind.AGENT: "config",
    ResourceKind.POST_CALL: "post-call",
}


class GeneratedRemoteAuthoringAdapter:
    """Small HTTP adapter; all validation and release semantics stay in Backend."""

    def __init__(self, client: AuthenticatedClient, tenant_id: UUID) -> None:
        self.client = client
        self.tenant_id = tenant_id

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        return ()

    def _request(self, method: str, path: str, value: Any = None, etag: str | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if etag is not None:
            headers["If-Match"] = etag
        response = self.client.get_httpx_client().request(method, path, json=value, headers=headers)
        if response.status_code >= 400:
            raise CommandError(f"Admin API request failed ({response.status_code}): {response.text[:500]}", 3)
        if not response.content:
            return {"_headers": dict(response.headers)}
        result = response.json()
        if not isinstance(result, dict):
            raise CommandError("unexpected client failure: invalid Backend response", 1)
        result["_headers"] = dict(response.headers)
        return result

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        component = _AUTHORING[resource_id.kind]
        result = self._request(
            "GET", f"/admin/v1/tenants/{self.tenant_id}/authoring/{component}"
        )
        return RemoteAuthoringState(
            result.get("value"),
            result.get("published_value"),
            result.get("etag") or result.get("_headers", {}).get("etag"),
        )

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        component = _AUTHORING[resource_id.kind]
        result = self._request(
            "POST",
            f"/admin/v1/tenants/{self.tenant_id}/authoring/{component}/plan",
            value,
        )
        return PlanResult(
            bool(result.get("valid", not result.get("errors"))),
            result.get("changes", []),
            result.get("warnings", []),
            result.get("errors", []),
        )

    def save(self, resource_id: ResourceId, value: Any, etag: str | None) -> RemoteAuthoringState:
        component = _AUTHORING[resource_id.kind]
        self._request(
            "PUT",
            f"/admin/v1/tenants/{self.tenant_id}/authoring/{component}",
            value,
            etag,
        )
        return self.get_state(resource_id)

    def publish_all(self, tenant: str) -> Any:
        expectations = []
        for component in publishable_component_names():
            result = self._request("GET", f"/admin/v1/tenants/{self.tenant_id}/components/{component}")
            draft = result.get("draft")
            if isinstance(draft, dict) and draft.get("id") is not None:
                expectations.append({"component": component, "draft_id": draft["id"], "version": draft["version"]})
        if not expectations:
            return None
        return self._request(
            "POST",
            f"/admin/v1/tenants/{self.tenant_id}/components/publish-all",
            {"drafts": expectations},
        )


class GeneratedPlatformRemoteAdapter:
    """Thin adapter for the existing Platform state/save/publish API."""

    def __init__(self, client: AuthenticatedClient) -> None:
        self.client = client

    def _state(self):
        response = state_admin_v1_platform_components_state_get.sync_detailed(client=self.client)
        if response.status_code >= 400 or response.parsed is None:
            raise CommandError(f"Admin API request failed ({response.status_code})", 3)
        return response.parsed

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        state = self._state()
        names = set(state.active_profile_prompts.additional_properties) | set(state.profile_prompt_drafts.additional_properties)
        return tuple(ResourceId("platform", "platform", PlatformResourceKind.PROFILE_PROMPT, name) for name in sorted(names))

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        state = self._state()
        if resource_id.kind is ResourceKind.RUNTIME:
            draft = None if state.runtime_draft is None else state.runtime_draft.value.to_dict()
            working = draft if draft is not None else (None if state.active_runtime is None else state.active_runtime.to_dict())
            published = None if state.active_runtime is None else state.active_runtime.to_dict()
            etag = None if state.runtime_draft is None else f'"{state.runtime_draft.version}"'
        elif resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
            draft = None if state.system_prompt_draft is None else state.system_prompt_draft.value
            working = draft if draft is not None else state.active_system_prompt
            published = state.active_system_prompt
            etag = None if state.system_prompt_draft is None else f'"{state.system_prompt_draft.version}"'
        else:
            name = resource_id.qualifier
            draft = state.profile_prompt_drafts.additional_properties.get(name) if name else None
            working = draft.value if draft is not None else (state.active_profile_prompts.additional_properties.get(name) if name else None)
            published = state.active_profile_prompts.additional_properties.get(name) if name else None
            etag = None if draft is None else f'"{draft.version}"'
        return RemoteAuthoringState(working, published, etag)

    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult:
        if resource_id.kind is ResourceKind.RUNTIME:
            response = plan_runtime_admin_v1_platform_components_runtime_plan_post.sync_detailed(
                client=self.client,
                body=RuntimeDraftWrite(policy=PlatformRuntimePolicy.from_dict(value)),
            )
        elif resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
            response = plan_system_prompt_admin_v1_platform_components_system_prompt_plan_post.sync_detailed(
                client=self.client, body=PromptDraftWrite(text=value)
            )
        else:
            response = plan_profile_prompt_admin_v1_platform_components_profiles_profile_plan_post.sync_detailed(
                resource_id.qualifier or "",
                client=self.client,
                body=PromptDraftWrite(text=value),
            )
        if response.status_code >= 400 or response.parsed is None or not hasattr(response.parsed, "to_dict"):
            raise CommandError(f"Admin API request failed ({response.status_code})", 3)
        result = response.parsed.to_dict()
        return PlanResult(
            bool(result.get("valid")),
            result.get("changes", []),
            result.get("warnings", []),
            result.get("errors", []),
        )

    def save(self, resource_id: ResourceId, value: Any, etag: str | None) -> RemoteAuthoringState:
        if resource_id.kind is ResourceKind.RUNTIME:
            response = save_runtime_admin_v1_platform_components_runtime_draft_put.sync_detailed(
                client=self.client,
                body=RuntimeDraftWrite(policy=PlatformRuntimePolicy.from_dict(value)),
                if_match=UNSET if etag is None else etag,
            )
        elif resource_id.kind is PlatformResourceKind.SYSTEM_PROMPT:
            response = save_system_prompt_admin_v1_platform_components_system_prompt_draft_put.sync_detailed(
                client=self.client,
                body=PromptDraftWrite(text=value),
                if_match=UNSET if etag is None else etag,
            )
        else:
            response = save_profile_prompt_admin_v1_platform_components_profiles_profile_draft_put.sync_detailed(
                resource_id.qualifier or "",
                client=self.client,
                body=PromptDraftWrite(text=value),
                if_match=UNSET if etag is None else etag,
            )
        if response.status_code >= 400:
            raise CommandError(f"Admin API request failed ({response.status_code})", 3)
        return self.get_state(resource_id)

    def publish_all(self, scope: str) -> Any:
        state = self._state()
        if (
            state.active_release is not None
            and state.runtime_draft is None
            and state.system_prompt_draft is None
            and not state.profile_prompt_drafts.additional_properties
        ):
            return None
        profiles = PlatformPublishRequestProfilePromptVersions()
        for name, draft in state.profile_prompt_drafts.additional_properties.items():
            profiles[name] = draft.version
        response = publish_admin_v1_platform_components_publish_post.sync_detailed(
            client=self.client,
            body=PlatformPublishRequest(
                runtime_version=None if state.runtime_draft is None else state.runtime_draft.version,
                system_prompt_version=None if state.system_prompt_draft is None else state.system_prompt_draft.version,
                profile_prompt_versions=profiles,
            ),
        )
        if response.status_code >= 400 or response.parsed is None:
            raise CommandError(f"Admin API request failed ({response.status_code})", 3)
        return response.parsed
