from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from control_plane.application.workspace import (
    WorkspaceTarget,
    plan,
    publish,
    publish_many,
    pull,
    pull_many,
    push,
    push_many,
    status,
)
from control_plane.backend.facade import PlanResult
from control_plane.backend.generated import GeneratedRemoteAuthoringAdapter
from control_plane.commands.errors import CommandError
from control_plane.workspace.codecs import load
from control_plane.workspace.model import (
    DraftResourceKind,
    RemoteAuthoringState,
    ResourceId,
    ResourceKind,
    ResourceStatus,
    fingerprint,
    publication_state,
    synchronization_state,
)
from control_plane.workspace.registry import descriptors
from control_plane.workspace.state_store import StateStore


class FakeRemote:
    def __init__(self, values: dict[ResourceId, object | None]) -> None:
        self.values = values
        self.published: dict[ResourceId, object | None] = {}
        self.planned: list[ResourceId] = []
        self.saved: list[ResourceId] = []
        self.publish_calls = 0
        self.plan_errors: set[ResourceId] = set()
        self.save_errors: set[ResourceId] = set()

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState:
        value = self.values.get(resource_id)
        return RemoteAuthoringState(value, self.published.get(resource_id, value), '"1"')

    def plan(self, resource_id: ResourceId, value: object) -> PlanResult:
        self.planned.append(resource_id)
        if resource_id in self.plan_errors:
            return PlanResult(False, [], [], [{"code": "invalid"}])
        return PlanResult(True, [], [], [])

    def save(self, resource_id: ResourceId, value: object, etag: str | None) -> RemoteAuthoringState:
        if resource_id in self.save_errors:
            raise CommandError(f"etag_conflict: {resource_id}", 3)
        self.saved.append(resource_id)
        self.values[resource_id] = value
        return self.get_state(resource_id)

    def publish_all(self, tenant: str) -> str:
        self.publish_calls += 1
        return tenant


def rid(kind: ResourceKind) -> ResourceId:
    return ResourceId("tenant", "demo", kind)


def tenant_rid(tenant: str, kind: ResourceKind) -> ResourceId:
    return ResourceId("tenant", tenant, kind)


def test_sync_and_publication_matrix() -> None:
    base = fingerprint({"v": 1})
    assert synchronization_state(base, base, base) == "clean"
    assert synchronization_state(base, fingerprint({"v": 2}), base) == "local_changed"
    assert synchronization_state(base, base, fingerprint({"v": 3})) == "remote_changed"
    assert synchronization_state(base, fingerprint({"v": 2}), fingerprint({"v": 3})) == "conflict"
    assert synchronization_state(None, fingerprint({"v": 2}), fingerprint({"v": 3})) == "unbased_divergence"
    assert synchronization_state(None, fingerprint({"v": 2}), None) == "initial_local"
    assert synchronization_state(None, None, fingerprint({"v": 2})) == "initial_remote"
    assert publication_state(base, base) == "published"
    assert publication_state(base, fingerprint({"v": 2})) == "unpublished"
    assert {descriptor.kind for descriptor in descriptors()} == set(ResourceKind)


def test_yaml_fingerprint_ignores_key_order_and_markdown_newlines(tmp_path: Path) -> None:
    first = ResourceId("tenant", "demo", ResourceKind.RUNTIME)
    path = tmp_path / "tenants" / "demo" / "runtime.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("b: 2\na: 1\n", encoding="utf-8")
    one = load(tmp_path, first).value
    path.write_text("a: 1\nb: 2\n", encoding="utf-8")
    two = load(tmp_path, first).value
    assert fingerprint(one) == fingerprint(two)


def test_pull_preflights_before_writing_and_push_plans_before_saving(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    resource = rid(ResourceKind.AGENT)
    path = tmp_path / "tenants" / "demo" / "tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: local\n", encoding="utf-8")
    remote = FakeRemote({resource: {"name": "remote"}})
    with pytest.raises(CommandError, match="unbased_divergence"):
        pull(tmp_path, store, remote, "demo")
    path.write_text("name: remote\n", encoding="utf-8")
    # Establish the no-baseline convergence for all six resources.
    for item in (ResourceKind.AGENT, ResourceKind.RUNTIME, ResourceKind.PROMPT, ResourceKind.KNOWLEDGE, ResourceKind.CAPABILITIES, ResourceKind.POST_CALL):
            remote.values[rid(item)] = (
                {"text": "remote"}
                if item is ResourceKind.PROMPT
                else {"content": "remote"}
                if item is ResourceKind.KNOWLEDGE
                else {"name": "remote"}
            )
    pull(tmp_path, store, remote, "demo")
    path.write_text("name: changed\n", encoding="utf-8")
    plan(tmp_path, store, remote, "demo")
    push(tmp_path, store, remote, "demo")
    assert resource in remote.planned
    assert resource in remote.saved


def test_state_is_metadata_only_and_publish_never_saves(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    path = tmp_path / "tenants" / "demo" / "tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: same\n", encoding="utf-8")
    remote = FakeRemote({rid(item): {"text": "same"} if item is ResourceKind.PROMPT else {"content": "same"} if item is ResourceKind.KNOWLEDGE else {"name": "same"} for item in ResourceKind})
    pull(tmp_path, store, remote, "demo")
    state = store.path.read_text(encoding="utf-8")
    assert "secret" not in state
    assert "base_fingerprint" in state
    before = path.read_text(encoding="utf-8")
    publish(tmp_path, store, remote, "demo")
    assert remote.publish_calls == 1
    assert remote.saved == []
    assert path.read_text(encoding="utf-8") == before


def test_publish_refuses_local_divergence_without_save_or_publish(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    path = tmp_path / "tenants" / "demo" / "tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: same\n", encoding="utf-8")
    remote = FakeRemote({rid(item): {"text": "same"} if item is ResourceKind.PROMPT else {"content": "same"} if item is ResourceKind.KNOWLEDGE else {"name": "same"} for item in ResourceKind})
    pull(tmp_path, store, remote, "demo")
    path.write_text("name: changed\n", encoding="utf-8")
    with pytest.raises(CommandError, match="publish_has_unpushed_changes"):
        publish(tmp_path, store, remote, "demo")
    assert remote.saved == []
    assert remote.publish_calls == 0


def test_publish_ignores_remote_only_publish_participant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = FakeRemote({})
    telephony = ResourceId("tenant", "demo", DraftResourceKind.TELEPHONY)
    monkeypatch.setattr(
        "control_plane.application.workspace.statuses",
        lambda *_args: [
            ResourceStatus(telephony, "remote_only", "not_applicable", "unpublished", None, "remote")
        ],
    )

    publish(tmp_path, store, remote, "demo")

    assert remote.publish_calls == 1


def test_backend_publish_all_includes_remote_only_telephony_draft() -> None:
    adapter = GeneratedRemoteAuthoringAdapter(None, uuid4())  # type: ignore[arg-type]
    requests: list[tuple[str, str, object]] = []

    def request(method: str, path: str, value=None, etag=None):
        requests.append((method, path, value))
        if method == "GET":
            return {"draft": {"id": path, "version": 1}}
        return {}

    adapter._request = request  # type: ignore[method-assign]
    adapter.publish_all("demo")

    payload = requests[-1][2]
    assert isinstance(payload, dict)
    assert any(item["component"] == "telephony" for item in payload["drafts"])


def test_backend_publish_all_skips_empty_draft_snapshot() -> None:
    adapter = GeneratedRemoteAuthoringAdapter(None, uuid4())  # type: ignore[arg-type]
    requests: list[tuple[str, str]] = []

    def request(method: str, path: str, value=None, etag=None):
        requests.append((method, path))
        return {"draft": None} if method == "GET" else {}

    adapter._request = request  # type: ignore[method-assign]

    assert adapter.publish_all("demo") is None
    assert all(method == "GET" for method, _ in requests)


def test_status_is_read_only_and_target_mismatch_blocks_mutations(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = FakeRemote({})
    assert not store.path.exists()
    assert all(item.local == "missing" for item in status(tmp_path, store, remote, "demo"))
    assert not store.path.exists()
    store.write({"format_version": 1, "target": {"api_url": "https://other.example"}, "resources": {}})
    for operation in (pull, plan, push, publish):
        with pytest.raises(CommandError, match="workspace_target_mismatch"):
            operation(tmp_path, store, remote, "demo")


def test_equal_local_remote_without_baseline_is_not_rewritten(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    path = tmp_path / "tenants" / "demo" / "tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: same\n", encoding="utf-8")
    before = path.stat().st_mtime_ns
    remote = FakeRemote({rid(ResourceKind.AGENT): {"name": "same"}})
    pull(tmp_path, store, remote, "demo")
    assert path.read_text(encoding="utf-8") == "name: same\n"
    assert path.stat().st_mtime_ns == before
    assert store.read()["resources"][str(rid(ResourceKind.AGENT))]["base_fingerprint"] == fingerprint({"name": "same"})


def test_required_missing_is_not_clean_and_blocks_before_plan_or_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    resource = rid(ResourceKind.AGENT)
    remote = FakeRemote({resource: None})
    monkeypatch.setattr(
        "control_plane.application.workspace.selected",
        lambda *_args: (resource,),
    )

    item = status(tmp_path, store, remote, "demo")[0]
    assert item.synchronization == "missing"
    assert item.publication == "empty"
    with pytest.raises(CommandError, match="required_resource_missing"):
        push(tmp_path, store, remote, "demo")
    assert remote.planned == []
    assert remote.saved == []


def test_converged_resource_without_baseline_is_not_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    resource = rid(ResourceKind.AGENT)
    path = tmp_path / "tenants/demo/tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: same\n", encoding="utf-8")
    remote = FakeRemote({resource: {"name": "same"}})
    monkeypatch.setattr(
        "control_plane.application.workspace.selected",
        lambda *_args: (resource,),
    )

    push(tmp_path, store, remote, "demo")

    assert remote.planned == []
    assert remote.saved == []


def test_push_projects_backend_canonical_value_after_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    resource = rid(ResourceKind.AGENT)
    path = tmp_path / "tenants/demo/tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: local\n", encoding="utf-8")

    class CanonicalRemote(FakeRemote):
        def save(self, resource_id: ResourceId, value: object, etag: str | None) -> RemoteAuthoringState:
            super().save(resource_id, value, etag)
            self.values[resource_id] = {"name": "local", "normalized": True}
            return self.get_state(resource_id)

    remote = CanonicalRemote({resource: {"name": "remote"}})
    monkeypatch.setattr(
        "control_plane.application.workspace.selected",
        lambda *_args: (resource,),
    )
    store.write({
        "format_version": 1,
        "target": {"api_url": store.api_url},
        "resources": {str(resource): {"base_fingerprint": fingerprint({"name": "remote"})}},
    })

    push(tmp_path, store, remote, "demo")

    assert load(tmp_path, resource).value == {"name": "local", "normalized": True}
    assert status(tmp_path, store, remote, "demo")[0].synchronization == "clean"


def test_deleted_local_required_file_is_not_implicit_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    resource = rid(ResourceKind.AGENT)
    path = tmp_path / "tenants/demo/tenant.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: same\n", encoding="utf-8")
    remote = FakeRemote({resource: {"name": "same"}})
    monkeypatch.setattr(
        "control_plane.application.workspace.selected",
        lambda *_args: (resource,),
    )
    pull(tmp_path, store, remote, "demo")
    path.unlink()

    assert status(tmp_path, store, remote, "demo")[0].synchronization == "local_changed"
    with pytest.raises(CommandError, match="required_resource_missing"):
        push(tmp_path, store, remote, "demo")
    assert remote.saved == []


def test_pull_global_preflight_does_not_rewrite_an_earlier_resource(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    agent = rid(ResourceKind.AGENT)
    runtime = rid(ResourceKind.RUNTIME)
    agent_path = tmp_path / "tenants" / "demo" / "tenant.yaml"
    runtime_path = tmp_path / "tenants" / "demo" / "runtime.yaml"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text("name: base\n", encoding="utf-8")
    runtime_path.write_text("version: base\n", encoding="utf-8")
    remote = FakeRemote({agent: {"name": "remote"}, runtime: {"version": "remote"}})
    store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": {
        str(agent): {"base_fingerprint": fingerprint({"name": "base"})},
        str(runtime): {"base_fingerprint": fingerprint({"version": "base"})},
    }})
    pull(tmp_path, store, remote, "demo")
    assert agent_path.read_text(encoding="utf-8") == "name: remote\n"
    assert runtime_path.read_text(encoding="utf-8") == "version: remote\n"
    resources = store.read()["resources"]
    assert resources[str(agent)]["base_fingerprint"] == fingerprint({"name": "remote"})
    assert resources[str(runtime)]["base_fingerprint"] == fingerprint({"version": "remote"})


def test_push_plans_all_before_any_save_and_never_publishes(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = FakeRemote({rid(item): {"v": "remote"} for item in ResourceKind})
    for item in ResourceKind:
        path = tmp_path / "tenants" / "demo" / {
            ResourceKind.AGENT: "tenant.yaml",
            ResourceKind.RUNTIME: "runtime.yaml",
            ResourceKind.PROMPT: "tenant_prompt.md",
            ResourceKind.KNOWLEDGE: "knowledge",
            ResourceKind.CAPABILITIES: "capabilities.yaml",
            ResourceKind.POST_CALL: "post_call.yaml",
        }[item]
        if item is ResourceKind.KNOWLEDGE:
            path.mkdir(parents=True)
            (path / "knowledge.md").write_text("remote", encoding="utf-8")
        elif item is ResourceKind.PROMPT:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("remote", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("v: local\n", encoding="utf-8")
    store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": {
        str(rid(item)): {"base_fingerprint": fingerprint(remote.values[rid(item)])} for item in ResourceKind
    }})
    remote.plan_errors.add(rid(ResourceKind.RUNTIME))
    with pytest.raises(CommandError, match="backend_plan_invalid"):
        push(tmp_path, store, remote, "demo")
    assert remote.saved == []
    assert remote.publish_calls == 0


def test_push_reports_partial_cas_failure_and_persists_only_successful_baselines(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    remote = FakeRemote({rid(item): {"v": "remote"} for item in ResourceKind})
    for item in ResourceKind:
        path = tmp_path / "tenants" / "demo" / {
            ResourceKind.AGENT: "tenant.yaml",
            ResourceKind.RUNTIME: "runtime.yaml",
            ResourceKind.PROMPT: "tenant_prompt.md",
            ResourceKind.KNOWLEDGE: "knowledge",
            ResourceKind.CAPABILITIES: "capabilities.yaml",
            ResourceKind.POST_CALL: "post_call.yaml",
        }[item]
        path.parent.mkdir(parents=True, exist_ok=True)
        if item is ResourceKind.KNOWLEDGE:
            path.mkdir(parents=True, exist_ok=True)
            (path / "knowledge.md").write_text("local", encoding="utf-8")
        else:
            path.write_text("v: local\n" if item is not ResourceKind.PROMPT else "local", encoding="utf-8")
    store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": {
        str(rid(item)): {"base_fingerprint": fingerprint(remote.values[rid(item)])} for item in ResourceKind
    }})
    failing = rid(ResourceKind.PROMPT)
    remote.save_errors.add(failing)
    report = push(tmp_path, store, remote, "demo")
    assert report.saved == (rid(ResourceKind.AGENT), rid(ResourceKind.RUNTIME))
    assert report.failed == failing
    assert rid(ResourceKind.CAPABILITIES) in report.not_attempted
    assert remote.saved == [rid(ResourceKind.AGENT), rid(ResourceKind.RUNTIME)]
    state = store.read()["resources"]
    assert str(rid(ResourceKind.AGENT)) in state
    assert str(rid(ResourceKind.RUNTIME)) in state
    assert state[str(failing)]["base_fingerprint"] == fingerprint(remote.values[failing])
    assert state[str(rid(ResourceKind.CAPABILITIES))]["base_fingerprint"] == fingerprint(remote.values[rid(ResourceKind.CAPABILITIES)])


def test_global_pull_preflights_all_tenants_before_writing(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    first = FakeRemote({tenant_rid("first", ResourceKind.AGENT): {"v": "remote"}})
    second = FakeRemote({tenant_rid("second", ResourceKind.AGENT): {"v": "remote"}})
    first.values[rid(ResourceKind.AGENT)] = {"v": "remote"}
    local = tmp_path / "tenants" / "first" / "tenant.yaml"
    local.parent.mkdir(parents=True)
    local.write_text("v: local\n", encoding="utf-8")
    with pytest.raises(CommandError, match="unbased_divergence"):
        pull_many(
            tmp_path,
            store,
            (WorkspaceTarget("first", first), WorkspaceTarget("second", second)),
        )
    assert not (tmp_path / "tenants" / "second").exists()


def test_global_push_plans_all_targets_before_any_save(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    first_id = tenant_rid("first", ResourceKind.AGENT)
    second_id = tenant_rid("second", ResourceKind.AGENT)
    first = FakeRemote({first_id: {"v": "remote"}})
    second = FakeRemote({second_id: {"v": "remote"}})
    first.plan_errors.add(first_id)
    for tenant in ("first", "second"):
        path = tmp_path / "tenants" / tenant / "tenant.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("v: local\n", encoding="utf-8")
    store.write(
        {
            "format_version": 1,
            "target": {"api_url": store.api_url},
            "resources": {
                str(first_id): {"base_fingerprint": fingerprint({"v": "remote"})},
                str(second_id): {"base_fingerprint": fingerprint({"v": "remote"})},
            },
        }
    )
    with pytest.raises(CommandError, match="backend_plan_invalid"):
        push_many(
            tmp_path,
            store,
            (WorkspaceTarget("first", first), WorkspaceTarget("second", second)),
        )
    assert first.saved == []
    assert second.saved == []


def test_global_push_required_missing_blocks_all_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    platform_resource = ResourceId("platform", "platform", ResourceKind.RUNTIME)
    hotel_resource = tenant_rid("hotel", ResourceKind.AGENT)
    penzion_resource = tenant_rid("penzion-grand", ResourceKind.AGENT)
    platform_path = tmp_path / "platform/runtime.yaml"
    platform_path.parent.mkdir(parents=True)
    platform_path.write_text("version: local\n", encoding="utf-8")
    platform = FakeRemote({platform_resource: {"version": "remote"}})
    hotel = FakeRemote({hotel_resource: None})
    penzion = FakeRemote({penzion_resource: None})
    store.write(
        {
            "format_version": 1,
            "target": {"api_url": store.api_url},
            "resources": {
                str(platform_resource): {
                    "base_fingerprint": fingerprint({"version": "remote"})
                }
            },
        }
    )

    def selected(scope: str, *_args):
        return (
            (platform_resource,)
            if scope == "platform"
            else (hotel_resource,)
            if scope == "hotel"
            else (penzion_resource,)
        )

    monkeypatch.setattr("control_plane.application.workspace.selected", selected)
    with pytest.raises(CommandError, match="required_resource_missing: tenant:hotel:agent"):
        push_many(
            tmp_path,
            store,
            (
                WorkspaceTarget("platform", platform),
                WorkspaceTarget("hotel", hotel),
                WorkspaceTarget("penzion-grand", penzion),
            ),
        )
    assert platform.saved == []
    assert hotel.saved == []
    assert penzion.saved == []


def test_global_publish_preflights_all_targets_then_publishes_each_scope(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    first_values = {
        tenant_rid("first", kind): {"text": "same"} if kind is ResourceKind.PROMPT else {"content": "same"} if kind is ResourceKind.KNOWLEDGE else {"v": "same"}
        for kind in ResourceKind
    }
    second_values = {
        tenant_rid("second", kind): {"text": "same"} if kind is ResourceKind.PROMPT else {"content": "same"} if kind is ResourceKind.KNOWLEDGE else {"v": "same"}
        for kind in ResourceKind
    }
    first = FakeRemote(first_values)
    second = FakeRemote(second_values)
    targets = (WorkspaceTarget("first", first), WorkspaceTarget("second", second))
    pull_many(tmp_path, store, targets)
    (tmp_path / "tenants/first/tenant.yaml").write_text("v: changed\n", encoding="utf-8")
    with pytest.raises(CommandError, match="publish_has_unpushed_changes"):
        publish_many(tmp_path, store, targets)
    assert first.publish_calls == 0
    assert second.publish_calls == 0
    (tmp_path / "tenants/first/tenant.yaml").write_text("v: same\n", encoding="utf-8")
    report = publish_many(tmp_path, store, targets)
    assert report.published == ("first", "second")
    assert first.publish_calls == 1
    assert second.publish_calls == 1


def test_global_publish_ignores_remote_only_publish_participants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path, "https://backend.example")
    first = FakeRemote({})
    second = FakeRemote({})
    telephony = ResourceId("tenant", "first", DraftResourceKind.TELEPHONY)
    monkeypatch.setattr(
        "control_plane.application.workspace.statuses",
        lambda *_args: [
            ResourceStatus(telephony, "remote_only", "not_applicable", "unpublished", None, "remote")
        ],
    )

    report = publish_many(
        tmp_path,
        store,
        (WorkspaceTarget("first", first), WorkspaceTarget("second", second)),
    )

    assert report.published == ("first", "second")
    assert first.publish_calls == 1
    assert second.publish_calls == 1
