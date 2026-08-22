from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenant_components import (
    component_state_admin_v1_tenants_tenant_id_components_component_get,
    publish_all_admin_v1_tenants_tenant_id_components_publish_all_post,
    save_draft_admin_v1_tenants_tenant_id_components_component_draft_put,
)
from admin_client.generated.api.admintenants import list_tenants_admin_v1_tenants_get
from admin_client.generated.models.component_draft_expectation import (
    ComponentDraftExpectation,
)
from admin_client.generated.models.component_draft_write import ComponentDraftWrite
from admin_client.generated.models.component_draft_write_payload import (
    ComponentDraftWritePayload,
)
from admin_client.generated.models.component_state_response import (
    ComponentStateResponse,
)
from admin_client.generated.models.publish_all_request import PublishAllRequest
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.types import UNSET, Response

from control_plane.commands.errors import CommandError
from control_plane.settings import Settings

COMPONENTS = ("runtime", "agent", "prompt", "knowledge", "capabilities", "telephony")


def tenant_config_path(state_dir: Path, slug: str) -> Path:
    return state_dir / "tenants" / slug / "tenant.yaml"


def parse_tenant_yaml(text: str) -> dict[str, dict[str, Any]]:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CommandError(f"invalid tenant.yaml: {error}", 2) from error
    if not isinstance(document, dict) or not all(
        isinstance(key, str) for key in document
    ):
        raise CommandError("tenant.yaml root must be a mapping", 2)
    unknown = set(document) - set(COMPONENTS)
    if unknown:
        raise CommandError(
            f"unknown tenant components: {', '.join(sorted(unknown))}", 2
        )
    sections: dict[str, dict[str, Any]] = {}
    for name, value in document.items():
        if not isinstance(value, dict):
            raise CommandError(f"{name} must be a mapping", 2)
        sections[name] = value
    return sections


def run_tenant_components(settings: Settings, action: str, slug: str) -> None:
    path = tenant_config_path(settings.state_dir, slug)
    if action == "show":
        print(path.read_text(encoding="utf-8"))
        return
    sections = parse_tenant_yaml(path.read_text(encoding="utf-8"))
    with AuthenticatedClient(base_url=settings.api_url, token=settings.token) as client:
        tenant = _tenant(client, slug)
        if action == "push":
            _push(client, tenant, sections)
            return
        if action == "publish":
            _publish(client, tenant)
            return
    raise CommandError(f"unsupported tenant config action: {action}", 2)


def _tenant(client: AuthenticatedClient, slug: str) -> TenantResponse:
    response = list_tenants_admin_v1_tenants_get.sync_detailed(client=client)
    tenants = _expect(response)
    tenant = next((item for item in tenants if item.slug == slug), None)
    if tenant is None:
        raise CommandError(f"tenant {slug!r} not found", 2)
    return tenant


def _state(
    client: AuthenticatedClient, tenant_id, component: str
) -> ComponentStateResponse:
    return _expect(
        component_state_admin_v1_tenants_tenant_id_components_component_get.sync_detailed(
            tenant_id, component, client=client
        )
    )


def _push(
    client: AuthenticatedClient,
    tenant: TenantResponse,
    sections: dict[str, dict[str, Any]],
) -> None:
    for component, payload in sections.items():
        state = _state(client, tenant.id, component)
        current = (
            state.draft.payload.to_dict()
            if state.draft is not None
            else (
                None
                if state.active_revision is None
                else state.active_revision.payload.to_dict()
            )
        )
        if current == payload:
            print(f"{component}: unchanged")
            continue
        response = (
            save_draft_admin_v1_tenants_tenant_id_components_component_draft_put.sync_detailed(
                tenant.id,
                component,
                client=client,
                body=ComponentDraftWrite(
                    payload=ComponentDraftWritePayload.from_dict(payload)
                ),
                if_match=(
                    UNSET if state.draft is None else f'"{state.draft.version}"'
                ),
            )
        )
        draft = _expect(response)
        print(f"{component}: saved draft version {draft.version}")


def _publish(client: AuthenticatedClient, tenant: TenantResponse) -> None:
    expectations = []
    for component in COMPONENTS:
        state = _state(client, tenant.id, component)
        if state.draft is not None:
            expectations.append(
                ComponentDraftExpectation(
                    component=component,
                    draft_id=state.draft.id,
                    version=state.draft.version,
                )
            )
    if not expectations:
        print("No saved component drafts to publish.")
        return
    release = _expect(
        publish_all_admin_v1_tenants_tenant_id_components_publish_all_post.sync_detailed(
            tenant.id, client=client, body=PublishAllRequest(drafts=expectations)
        )
    )
    print(f"Published tenant release {release.release_number}.")


def _expect(response: Response[Any]) -> Any:
    if 200 <= response.status_code < 300 and response.parsed is not None:
        return response.parsed
    detail = response.content.decode(errors="replace")[:500]
    raise CommandError(f"Admin API request failed: {detail}", 3)
