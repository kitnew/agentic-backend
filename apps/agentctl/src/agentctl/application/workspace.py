from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentctl.backend.facade import PlanResult, RemoteAuthoringAdapter
from agentctl.commands.errors import CommandError
from agentctl.workspace.codecs import dump, load, write_atomic
from agentctl.workspace.model import (
    PlatformResourceKind,
    ResourceId,
    ResourceStatus,
    fingerprint,
    publication_state,
    synchronization_state,
)
from agentctl.workspace.registry import (
    ResourceCapability,
    ResourcePresence,
    descriptors,
    platform_resources,
    resource_capabilities,
    resource_presence,
)
from agentctl.workspace.state_store import StateStore


@dataclass(frozen=True, slots=True)
class PushReport:
    saved: tuple[ResourceId, ...]
    failed: ResourceId | None = None
    not_attempted: tuple[ResourceId, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceTarget:
    name: str
    remote: RemoteAuthoringAdapter


@dataclass(frozen=True, slots=True)
class PublishReport:
    published: tuple[str, ...]
    failed: str | None = None
    not_attempted: tuple[str, ...] = ()
    not_dirty: tuple[str, ...] = ()


def _requires_local_preflight(resource_id: ResourceId) -> bool:
    return ResourceCapability.LOCAL_PROJECTABLE in resource_capabilities(resource_id)


def selected(scope: str, root: Path, remote: RemoteAuthoringAdapter) -> tuple[ResourceId, ...]:
    if scope == "platform":
        remote_resources = getattr(remote, "list_resources", lambda _: ())
        return platform_resources(root, remote_resources(scope))
    return tuple(descriptor.resource_id(scope) for descriptor in descriptors())


def _records(store: StateStore) -> dict[str, dict[str, Any]]:
    return store.read().setdefault("resources", {})


def statuses(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> list[ResourceStatus]:
    records = _records(store)
    result = []
    for resource_id in selected(tenant, root, remote):
        local = load(root, resource_id)
        state = remote.get_state(resource_id)
        local_fp = fingerprint(local.value) if local.present and local.valid else None
        remote_fp = fingerprint(state.working_value)
        baseline = records.get(str(resource_id), {}).get("base_fingerprint")
        synchronization = synchronization_state(baseline, local_fp, remote_fp)
        if (
            resource_presence(resource_id) is ResourcePresence.REQUIRED
            and local_fp is None
            and remote_fp is None
        ):
            synchronization = "missing"
        result.append(
            ResourceStatus(
                resource_id,
                "missing" if not local.present else "invalid" if not local.valid else "present",
                synchronization,
                publication_state(remote_fp, fingerprint(state.published_value)),
                local_fp,
                remote_fp,
            )
        )
    return result


def _preflight(
    root: Path,
    store: StateStore,
    remote: RemoteAuthoringAdapter,
    tenant: str,
    *,
    with_plan: bool,
    allow_initial_local: bool = False,
) -> list[tuple[ResourceId, Any, Any, str | None]]:
    records = _records(store)
    work = []
    for resource_id in selected(tenant, root, remote):
        local = load(root, resource_id)
        state = remote.get_state(resource_id)
        local_fp = fingerprint(local.value) if local.present and local.valid else None
        remote_fp = fingerprint(state.working_value)
        baseline = records.get(str(resource_id), {}).get("base_fingerprint")
        sync = synchronization_state(baseline, local_fp, remote_fp)
        required_missing = (
            resource_presence(resource_id) is ResourcePresence.REQUIRED
            and local_fp is None
        )
        if required_missing:
            raise CommandError(f"required_resource_missing: {resource_id}", 2)
        if not local.valid:
            raise CommandError(f"local_invalid: {resource_id}", 2)
        blocked = {"remote_changed", "conflict", "unbased_divergence", "initial_remote"}
        if not allow_initial_local:
            blocked.add("initial_local")
        if sync in blocked:
            raise CommandError(f"{sync}: {resource_id}", 2)
        if local_fp != remote_fp:
            if with_plan:
                plan = remote.plan(resource_id, local.value)
                if not plan.valid or plan.errors:
                    raise CommandError(f"backend_plan_invalid: {resource_id}", 2)
            work.append((resource_id, local.value, state, state.write_etag))
    return work


def status(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> list[ResourceStatus]:
    return statuses(root, store, remote, tenant)


def pull(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> None:
    records = _records(store)
    prepared = _prepare_pull(root, store, remote, tenant)
    with store.lock():
        if tenant == "platform":
            (root / "platform" / "profiles").mkdir(parents=True, exist_ok=True)
        for resource_id, files, _ in prepared:
            if files:
                write_atomic(files)
            records[str(resource_id)] = {"base_fingerprint": _}
        store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})


def _prepare_pull(
    root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str
) -> list[tuple[ResourceId, dict[Path, str], str | None]]:
    prepared: list[tuple[ResourceId, dict[Path, str], str | None]] = []
    for item in statuses(root, store, remote, tenant):
        resource_id = item.resource_id
        state = remote.get_state(resource_id)
        local = load(root, resource_id)
        if item.synchronization in {"local_changed", "conflict", "unbased_divergence", "initial_local"}:
            raise CommandError(f"{item.synchronization}: {resource_id}", 2)
        if state.working_value is None:
            continue
        files = (
            {}
            if item.synchronization == "clean" and local.present
            else dump(root, resource_id, state.working_value)
        )
        prepared.append((resource_id, files, fingerprint(state.working_value)))
    return prepared


def pull_many(root: Path, store: StateStore, targets: tuple[WorkspaceTarget, ...]) -> None:
    records = _records(store)
    prepared: list[tuple[ResourceId, dict[Path, str], str | None]] = []
    for target in targets:
        prepared.extend(_prepare_pull(root, store, target.remote, target.name))
    with store.lock():
        if any(target.name == "platform" for target in targets):
            (root / "platform" / "profiles").mkdir(parents=True, exist_ok=True)
        for resource_id, files, _ in prepared:
            if files:
                write_atomic(files)
            records[str(resource_id)] = {"base_fingerprint": _}
        store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})


def plan(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> list[tuple[ResourceId, PlanResult]]:
    return [(resource_id, remote.plan(resource_id, value)) for resource_id, value, _, _ in _preflight(root, store, remote, tenant, with_plan=True, allow_initial_local=True)]


def push(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> PushReport:
    work = _preflight(root, store, remote, tenant, with_plan=True, allow_initial_local=True)
    records = _records(store)
    saved: list[ResourceId] = []
    with store.lock():
        for index, (resource_id, value, _, etag) in enumerate(work):
            try:
                state = remote.save(resource_id, value, etag)
            except CommandError:
                store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})
                return PushReport(tuple(saved), resource_id, tuple(item[0] for item in work[index + 1 :]))
            write_atomic(dump(root, resource_id, state.working_value))
            records[str(resource_id)] = {"base_fingerprint": fingerprint(state.working_value)}
            saved.append(resource_id)
            store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})
    return PushReport(tuple(saved))


def push_many(root: Path, store: StateStore, targets: tuple[WorkspaceTarget, ...]) -> PushReport:
    work: list[tuple[ResourceId, Any, Any, str | None]] = []
    owners: dict[ResourceId, RemoteAuthoringAdapter] = {}
    for target in targets:
        owners.update({resource_id: target.remote for resource_id in selected(target.name, root, target.remote)})
        work.extend(_preflight(root, store, target.remote, target.name, with_plan=True, allow_initial_local=True))
    records = _records(store)
    saved: list[ResourceId] = []
    with store.lock():
        for index, (resource_id, value, _, etag) in enumerate(work):
            try:
                state = owners[resource_id].save(resource_id, value, etag)
            except CommandError:
                store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})
                return PushReport(tuple(saved), resource_id, tuple(item[0] for item in work[index + 1 :]))
            write_atomic(dump(root, resource_id, state.working_value))
            records[str(resource_id)] = {"base_fingerprint": fingerprint(state.working_value)}
            saved.append(resource_id)
            store.write({"format_version": 1, "target": {"api_url": store.api_url}, "resources": records})
    return PushReport(tuple(saved))


def publish(root: Path, store: StateStore, remote: RemoteAuthoringAdapter, tenant: str) -> PublishReport:
    for item in statuses(root, store, remote, tenant):
        if not _requires_local_preflight(item.resource_id):
            continue
        if (
            tenant == "platform"
            and item.resource_id.kind is PlatformResourceKind.PROFILE_PROMPT
            and item.local == "missing"
            and item.synchronization == "initial_remote"
        ):
            continue
        if item.local in {"missing", "invalid"} or item.synchronization != "clean":
            raise CommandError(f"publish_has_unpushed_changes: {item.resource_id}", 2)
    items = statuses(root, store, remote, tenant)
    dirty = [item for item in items if item.publication == "unpublished"]
    not_dirty = tuple(f"{tenant}:{item.resource_id.kind.value}" for item in items if item.publication != "unpublished")
    published: list[str] = []
    for index, item in enumerate(dirty):
        name = f"{tenant}:{item.resource_id.kind.value}"
        try:
            remote.publish_component(item.resource_id)
        except CommandError:
            return PublishReport(tuple(published), name, tuple(f"{tenant}:{pending.resource_id.kind.value}" for pending in dirty[index + 1:]), not_dirty)
        published.append(name)
    return PublishReport(tuple(published), not_dirty=not_dirty)


def publish_many(root: Path, store: StateStore, targets: tuple[WorkspaceTarget, ...]) -> PublishReport:
    for target in targets:
        for item in statuses(root, store, target.remote, target.name):
            if not _requires_local_preflight(item.resource_id):
                continue
            if (
                target.name == "platform"
                and item.resource_id.kind is PlatformResourceKind.PROFILE_PROMPT
                and item.local == "missing"
                and item.synchronization == "initial_remote"
            ):
                continue
            if item.local in {"missing", "invalid"} or item.synchronization != "clean":
                raise CommandError(f"publish_has_unpushed_changes: {item.resource_id}", 2)
    published: list[str] = []
    not_dirty: list[str] = []
    for target_index, target in enumerate(targets):
        all_items = statuses(root, store, target.remote, target.name)
        items = [item for item in all_items if item.publication == "unpublished"]
        not_dirty.extend(f"{target.name}:{item.resource_id.kind.value}" for item in all_items if item.publication != "unpublished")
        for index, item in enumerate(items):
            try:
                target.remote.publish_component(item.resource_id)
            except CommandError:
                remaining = tuple(f"{target.name}:{pending.resource_id.kind.value}" for pending in items[index + 1:])
                later = tuple(
                    f"{later_target.name}:{later_item.resource_id.kind.value}"
                    for later_target in targets[target_index + 1:]
                    for later_item in statuses(root, store, later_target.remote, later_target.name)
                    if later_item.publication == "unpublished"
                )
                return PublishReport(tuple(published), f"{target.name}:{item.resource_id.kind.value}", remaining + later, tuple(not_dirty))
            published.append(f"{target.name}:{item.resource_id.kind.value}")
    return PublishReport(tuple(published), not_dirty=tuple(not_dirty))


def statuses_many(root: Path, store: StateStore, targets: tuple[WorkspaceTarget, ...]) -> list[ResourceStatus]:
    return [item for target in targets for item in statuses(root, store, target.remote, target.name)]


def plans_many(root: Path, store: StateStore, targets: tuple[WorkspaceTarget, ...]) -> list[tuple[ResourceId, PlanResult]]:
    return [
        result
        for target in targets
        for result in plan(root, store, target.remote, target.name)
    ]
