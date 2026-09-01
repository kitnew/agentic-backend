from __future__ import annotations

from typing import Any

from admin_client import AuthenticatedClient
from admin_client.generated.api.adminauthoring import (
    plan_telephony_admin_v1_tenants_tenant_id_authoring_telephony_plan_post,
)
from admin_client.generated.api.admintenant_components import (
    component_state_admin_v1_tenants_tenant_id_components_component_get,
    save_draft_admin_v1_tenants_tenant_id_components_component_draft_put,
)
from admin_client.generated.api.admintenants import (
    tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get,
)
from admin_client.generated.models.authoring_plan import AuthoringPlan
from admin_client.generated.models.component_draft_write import ComponentDraftWrite
from admin_client.generated.models.component_draft_write_payload import (
    ComponentDraftWritePayload,
)
from admin_client.generated.models.component_state_response import (
    ComponentStateResponse,
)
from admin_client.generated.models.tenant_telephony_config import TenantTelephonyConfig
from admin_client.generated.models.tenant_telephony_status import TenantTelephonyStatus
from admin_client.generated.types import UNSET, Response, Unset

from agentctl.commands.common import _client, _response_error, _tenant
from agentctl.commands.errors import CommandError
from agentctl.settings import Settings


def _expect(response: Response[Any]) -> Any:
    _response_error(response)
    if response.parsed is None:
        raise CommandError("unexpected client failure: empty Backend response", 1)
    return response.parsed


def _state(client: AuthenticatedClient, tenant_id) -> ComponentStateResponse:
    result = _expect(
        component_state_admin_v1_tenants_tenant_id_components_component_get.sync_detailed(
            tenant_id, "telephony", client=client
        )
    )
    if not isinstance(result, ComponentStateResponse):
        raise CommandError("unexpected client failure: invalid Telephony response", 1)
    return result


def _payload(value: Any | None) -> dict[str, Any]:
    return {} if value is None else value.to_dict()


def _phone(value: Any | None) -> str | None:
    return _payload(value).get("phone_number")


def _status(client: AuthenticatedClient, tenant_id) -> TenantTelephonyStatus:
    result = _expect(
        tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get.sync_detailed(
            tenant_id, client=client
        )
    )
    if not isinstance(result, TenantTelephonyStatus):
        raise CommandError("unexpected client failure: invalid Telephony status response", 1)
    return result


def _show(status: TenantTelephonyStatus, tenant_slug: str) -> None:
    draft = None if status.draft is None else status.draft.phone_number
    published = None if status.published is None else status.published.phone_number
    print(f"Tenant: {tenant_slug}")
    print(f"Draft DID: {draft or 'none'}")
    print(f"Published DID: {published or 'none'}")
    print(f"Publication: {status.publication}")
    claim_phone = status.claim.phone_number
    print(f"Claim: {status.claim.state}{f' — {claim_phone}' if claim_phone else ''}")
    print(f"Provisioning: {status.provisioning.state}")
    if status.provisioning.last_error:
        print(status.provisioning.last_error)


def _plan(
    client: AuthenticatedClient, tenant_id, candidate: dict[str, Any]
) -> AuthoringPlan:
    result = _expect(
        plan_telephony_admin_v1_tenants_tenant_id_authoring_telephony_plan_post.sync_detailed(
            tenant_id,
            client=client,
            body=TenantTelephonyConfig.from_dict(candidate),
        )
    )
    if not isinstance(result, AuthoringPlan):
        raise CommandError(
            "unexpected client failure: invalid Telephony plan response", 1
        )
    return result


def _print_plan(plan: AuthoringPlan) -> None:
    for change in plan.changes if not isinstance(plan.changes, Unset) else []:
        print(f"{change.path}: {change.before} -> {change.after}")
    for issue in (
        *([] if isinstance(plan.errors, Unset) else plan.errors),
        *([] if isinstance(plan.warnings, Unset) else plan.warnings),
    ):
        print(f"{issue.code}: {issue.message}")


def run_did(
    settings: Settings, action: str, tenant_slug: str, phone_number: str | None = None
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        if action == "show":
            _show(_status(client, tenant.id), tenant_slug)
            return
        if action not in {"assign", "remove"}:
            raise CommandError(f"unsupported DID action: {action}", 2)
        if action == "assign" and not phone_number:
            raise CommandError("phone number is required", 2)
        state = _state(client, tenant.id)
        candidate = _payload(
            state.draft.payload
            if state.draft
            else state.active_revision.payload
            if state.active_revision
            else None
        )
        candidate["phone_number"] = phone_number if action == "assign" else None
        plan = _plan(client, tenant.id, candidate)
        _print_plan(plan)
        if not plan.valid:
            raise CommandError("Telephony plan is invalid", 2)
        saved = _expect(
            save_draft_admin_v1_tenants_tenant_id_components_component_draft_put.sync_detailed(
                tenant.id,
                "telephony",
                client=client,
                body=ComponentDraftWrite(
                    payload=ComponentDraftWritePayload.from_dict(candidate)
                ),
                if_match=UNSET if state.draft is None else f'"{state.draft.version}"',
            )
        )
        print(f"DID draft saved (version {saved.version}).")
        print("Publish the tenant to activate this DID; no publication was performed.")
