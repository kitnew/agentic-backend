from json import dumps

from admin_client.generated.api.admintenants import (
    save_tenant_telephony_admin_v1_tenants_tenant_id_telephony_put,
    show_tenant_telephony_admin_v1_tenants_tenant_id_telephony_get,
    tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get,
)
from admin_client.generated.models.tenant_telephony_response import (
    TenantTelephonyResponse,
)
from admin_client.generated.models.tenant_telephony_update import TenantTelephonyUpdate

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
)
from control_plane.settings import Settings


def run_tenant_telephony(
    settings: Settings,
    action: str,
    tenant_slug: str,
    *,
    number: str | None = None,
    destination: str | None = None,
    label: str | None = None,
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        call = (
            tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get
            if action == "status"
            else show_tenant_telephony_admin_v1_tenants_tenant_id_telephony_get
        )
        response = call.sync_detailed(tenant.id, client=client)
        _response_error(response)
        if not isinstance(response.parsed, TenantTelephonyResponse):
            raise PromptCommandError("invalid Backend telephony response", 1)
        state = response.parsed
        if action in {"show", "status"}:
            print(dumps(state.to_dict(), indent=2, ensure_ascii=False))
            return

        desired = state.desired.to_dict()
        handoff = desired.setdefault("handoff", {"destinations": {}})
        destinations = handoff.setdefault("destinations", {})
        if action == "set-number":
            desired["phone_number"] = number
        elif action == "handoff-set":
            assert destination is not None and number is not None
            destinations[destination] = {
                "description": label or destination.replace("_", " ").title(),
                "phone_number": number,
            }
        elif action == "handoff-remove":
            assert destination is not None
            if destinations.pop(destination, None) is None:
                raise PromptCommandError(f"unknown handoff destination: {destination}", 2)
        else:
            raise PromptCommandError(f"unsupported telephony action: {action}", 2)
        body = TenantTelephonyUpdate.from_dict(desired)
        if state.draft_version is not None:
            saved = save_tenant_telephony_admin_v1_tenants_tenant_id_telephony_put.sync_detailed(
                tenant.id,
                client=client,
                body=body,
                if_match=f'"{state.draft_version}"',
            )
        else:
            saved = save_tenant_telephony_admin_v1_tenants_tenant_id_telephony_put.sync_detailed(
                tenant.id, client=client, body=body
            )
        _response_error(saved)
        if not isinstance(saved.parsed, TenantTelephonyResponse):
            raise PromptCommandError("invalid Backend telephony response", 1)
        print("Tenant Telephony saved as an unpublished draft.")
