from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from admin_client.generated.api.admintenants import list_tenants_admin_v1_tenants_get
from admin_client.generated.models.tenant_response import TenantResponse

from agentctl.application.workspace import (
    WorkspaceTarget,
    plans_many,
    publish_many,
    pull_many,
    push_many,
    statuses_many,
)
from agentctl.backend.facade import RemoteAuthoringAdapter
from agentctl.backend.generated import (
    GeneratedPlatformRemoteAdapter,
    GeneratedRemoteAuthoringAdapter,
)
from agentctl.commands.common import _client, _response_error, _tenant
from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings
from agentctl.workspace.model import ResourceStatus
from agentctl.workspace.state_store import StateStore


@dataclass(frozen=True, slots=True)
class WorkspaceSelection:
    scope: Literal["all", "platform", "tenant"]
    tenant_slug: str | None = None


def _targets(backend, control_plane: ControlPlaneClient, selection: WorkspaceSelection) -> tuple[WorkspaceTarget, ...]:
    platform = WorkspaceTarget("platform", GeneratedPlatformRemoteAdapter(control_plane))
    if selection.scope == "platform":
        return (platform,)
    if selection.scope == "tenant":
        if not selection.tenant_slug:
            raise CommandError("tenant slug is required", 2)
        tenant = _tenant(backend, selection.tenant_slug)
        return (WorkspaceTarget(tenant.slug, GeneratedRemoteAuthoringAdapter(control_plane, str(tenant.id))),)

    response = list_tenants_admin_v1_tenants_get.sync_detailed(client=backend)
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, TenantResponse) for item in response.parsed
    ):
        raise CommandError("unexpected client failure: invalid Backend tenant list", 1)
    tenants = tuple(
        WorkspaceTarget(item.slug, GeneratedRemoteAuthoringAdapter(control_plane, str(item.id)))
        for item in sorted(response.parsed, key=lambda value: value.slug)
    )
    return (platform, *tenants)


def _print_status(targets, items) -> None:
    grouped: dict[str, list[ResourceStatus]] = {target.name: [] for target in targets}
    for item in items:
        grouped[item.resource_id.owner if item.resource_id.scope == "tenant" else "platform"].append(item)
    for target in targets:
        print(f"[{target.name}]")
        for item in grouped[target.name]:
            print(f"{item.resource_id.kind.value}: {item.synchronization} ({item.publication})")


def run_workspace(
    settings: Settings,
    action: str,
    selection: WorkspaceSelection,
    remote: RemoteAuthoringAdapter | None = None,
) -> None:
    backend_context = None
    control_plane = None
    if remote is None:
        backend_context = _client(settings)
        backend_context.__enter__()
        control_plane = ControlPlaneClient(settings)
        targets = _targets(backend_context, control_plane, selection)
    else:
        name = "platform" if selection.scope == "platform" else selection.tenant_slug or "tenant"
        targets = (WorkspaceTarget(name, remote),)
    store = StateStore(settings.state_dir, settings.control_plane_url or settings.api_url)
    try:
        if action == "status":
            _print_status(targets, statuses_many(settings.state_dir, store, targets))
            return
        if action == "pull":
            pull_many(settings.state_dir, store, targets)
            return
        if action == "plan":
            for resource_id, result in plans_many(settings.state_dir, store, targets):
                print(f"{resource_id}: {'valid' if result.valid else 'invalid'}")
            return
        if action == "push":
            push_report = push_many(settings.state_dir, store, targets)
            if push_report.saved:
                print("SAVED: " + ", ".join(str(item) for item in push_report.saved))
            if push_report.failed is not None:
                print(f"FAILED: {push_report.failed}")
            if push_report.not_attempted:
                    print("NOT ATTEMPTED: " + ", ".join(map(str, push_report.not_attempted)))
            return
        if action == "publish":
            publish_report = publish_many(settings.state_dir, store, targets)
            if publish_report.published:
                print("PUBLISHED: " + ", ".join(publish_report.published))
            if publish_report.not_dirty:
                print("NOT DIRTY: " + ", ".join(publish_report.not_dirty))
            if publish_report.failed is not None:
                print(f"FAILED: {publish_report.failed}")
                if publish_report.not_attempted:
                    print("NOT ATTEMPTED: " + ", ".join(publish_report.not_attempted))
                raise CommandError(f"publish_failed: {publish_report.failed}", 3)
            return
        raise CommandError(f"unsupported workspace action: {action}", 2)
    finally:
        if control_plane is not None:
            control_plane.close()
        if backend_context is not None:
            backend_context.__exit__(None, None, None)
