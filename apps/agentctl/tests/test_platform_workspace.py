from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from agentctl.application.workspace import plan, publish, pull, push, status
from agentctl.backend import generated
from agentctl.backend.facade import PlanResult
from agentctl.workspace.model import (
    PlatformResourceKind,
    RemoteAuthoringState,
    ResourceId,
    ResourceKind,
)
from agentctl.workspace.registry import (
    platform_profile_descriptor,
    platform_resources,
)
from agentctl.workspace.state_store import StateStore


class PlatformRemote:
    def __init__(self, values: dict[ResourceId, object | None]) -> None:
        self.values = values
        self.publish_calls = 0
        self.saved: list[ResourceId] = []

    def list_resources(self, scope: str) -> tuple[ResourceId, ...]:
        return tuple(self.values)

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        value = self.values.get(resource_id)
        return RemoteAuthoringState(value, value, '"1"')

    def plan(self, resource_id: ResourceId, value: object) -> PlanResult:
        return PlanResult(True, [], [], [])

    def save(self, resource_id: ResourceId, value: object, etag: str | None) -> RemoteAuthoringState:
        self.saved.append(resource_id)
        self.values[resource_id] = value
        return self.get_state(resource_id)

    def publish_all(self, scope: str) -> str:
        self.publish_calls += 1
        return scope


def profile(name: str) -> ResourceId:
    return ResourceId("platform", "platform", PlatformResourceKind.PROFILE_PROMPT, name)


def test_platform_registry_discovers_local_and_remote_profiles(tmp_path: Path) -> None:
    profiles = tmp_path / "platform" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "hotel_assistant.md").write_text("hotel", encoding="utf-8")
    remote = (profile("hotel_assistant"), profile("concierge"))
    resources = platform_resources(tmp_path, remote)
    assert profile("hotel_assistant") in resources
    assert profile("concierge") in resources
    assert profile("restaurant") not in resources
    assert platform_profile_descriptor("concierge").resource_id("platform") == profile("concierge")
    assert str(profile("concierge")) == "platform:profile_prompt:concierge"


@pytest.mark.parametrize("name", ("../escape", "/tmp/escape", "a/b", "a\\b", ".."))
def test_platform_profile_qualifier_rejects_traversal(name: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        platform_profile_descriptor(name)


def test_platform_remote_only_profile_pulls_and_does_not_mean_delete(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = PlatformRemote({profile("concierge"): "hello"})
    pull(tmp_path, store, remote, "platform")
    assert (tmp_path / "platform" / "profiles" / "concierge.md").read_text(encoding="utf-8") == "hello"


def test_platform_pull_creates_profiles_directory_and_local_profile_can_push(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = PlatformRemote(
        {
            ResourceId("platform", "platform", ResourceKind.RUNTIME): {"version": 1},
            ResourceId("platform", "platform", PlatformResourceKind.SYSTEM_PROMPT): "system",
        }
    )

    pull(tmp_path, store, remote, "platform")
    profiles = tmp_path / "platform" / "profiles"
    assert profiles.is_dir()
    profile_path = profiles / "hotel_assistant.md"
    profile_path.write_text("Hotel assistant", encoding="utf-8")

    resource = profile("hotel_assistant")
    profile_status = next(
        item for item in status(tmp_path, store, remote, "platform")
        if item.resource_id == resource
    )
    assert profile_status.synchronization == "initial_local"
    assert profile_status.publication == "empty"
    assert plan(tmp_path, store, remote, "platform")
    push(tmp_path, store, remote, "platform")
    assert remote.saved == [resource]
    assert next(
        item for item in status(tmp_path, store, remote, "platform")
        if item.resource_id == resource
    ).synchronization == "clean"


def test_platform_status_uses_shared_state_engine_and_publish_ignores_remote_only_profile(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    runtime = ResourceId("platform", "platform", ResourceKind.RUNTIME)
    runtime_path = tmp_path / "platform" / "runtime.yaml"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text("version: 1\n", encoding="utf-8")
    system_prompt = ResourceId("platform", "platform", PlatformResourceKind.SYSTEM_PROMPT)
    (tmp_path / "platform" / "system_prompt.md").write_text("system", encoding="utf-8")
    remote = PlatformRemote({runtime: {"version": 1}, system_prompt: "system", profile("concierge"): "remote"})
    states = status(tmp_path, store, remote, "platform")
    assert next(item for item in states if item.resource_id == runtime).synchronization == "clean"
    assert next(item for item in states if item.resource_id == profile("concierge")).synchronization == "initial_remote"
    publish(tmp_path, store, remote, "platform")
    assert remote.publish_calls == 1


def test_platform_adapter_plan_delegates_to_generated_backend_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from admin_client.generated.models.authoring_plan import AuthoringPlan

    calls: list[str] = []
    response = SimpleNamespace(
        status_code=200,
        parsed=AuthoringPlan.from_dict(
            {"valid": True, "changes": [], "warnings": [], "errors": [], "impact": {}}
        ),
    )
    names = (
        "plan_runtime_admin_v1_platform_components_runtime_plan_post",
        "plan_system_prompt_admin_v1_platform_components_system_prompt_plan_post",
        "plan_profile_prompt_admin_v1_platform_components_profiles_profile_plan_post",
    )
    for name in names:
        monkeypatch.setattr(
            getattr(generated, name),
            "sync_detailed",
            lambda *args, _name=name, **kwargs: calls.append(_name) or response,
        )
    monkeypatch.setattr(generated.PlatformRuntimePolicy, "from_dict", lambda value: object())

    adapter = generated.GeneratedPlatformRemoteAdapter(object())
    adapter.plan(ResourceId("platform", "platform", ResourceKind.RUNTIME), {})
    adapter.plan(
        ResourceId("platform", "platform", PlatformResourceKind.SYSTEM_PROMPT),
        "system",
    )
    adapter.plan(profile("hotel_assistant"), "profile")
    assert calls == list(names)


def test_platform_publish_skips_when_active_release_has_no_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = generated.GeneratedPlatformRemoteAdapter(object())
    adapter._state = lambda: SimpleNamespace(
        active_release=object(),
        runtime_draft=None,
        system_prompt_draft=None,
        profile_prompt_drafts=SimpleNamespace(additional_properties={}),
    )
    monkeypatch.setattr(
        generated.publish_admin_v1_platform_components_publish_post,
        "sync_detailed",
        lambda **_kwargs: pytest.fail("publish endpoint must not be called"),
    )

    assert adapter.publish_all("platform") is None
