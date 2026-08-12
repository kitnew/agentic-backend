from uuid import UUID

from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    create_inbound_route_admin_v1_tenants_tenant_id_inbound_routes_post,
    delete_inbound_route_admin_v1_tenants_tenant_id_inbound_routes_route_id_delete,
    list_inbound_routes_admin_v1_tenants_tenant_id_inbound_routes_get,
)
from admin_client.generated.models.create_inbound_route_request import (
    CreateInboundRouteRequest,
)
from admin_client.generated.models.inbound_route_response import InboundRouteResponse

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
)
from control_plane.settings import Settings


def _routes(client: AuthenticatedClient, tenant_id: UUID) -> list[InboundRouteResponse]:
    response = (
        list_inbound_routes_admin_v1_tenants_tenant_id_inbound_routes_get.sync_detailed(
            tenant_id, client=client
        )
    )
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, InboundRouteResponse) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def run_inbound_route(
    settings: Settings,
    action: str,
    tenant_slug: str,
    number: str | None = None,
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        if action == "list":
            routes = _routes(client, tenant.id)
            if not routes:
                print("No inbound routes.")
                return
            print("DID\tSTATUS\tID")
            for route in routes:
                print(
                    f"{route.normalized_did}\t"
                    f"{'enabled' if route.enabled else 'disabled'}\t{route.id}"
                )
            return
        assert number is not None
        if action == "add":
            response = create_inbound_route_admin_v1_tenants_tenant_id_inbound_routes_post.sync_detailed(
                tenant.id,
                client=client,
                body=CreateInboundRouteRequest(normalized_did=number),
            )
            _response_error(response)
            if not isinstance(response.parsed, InboundRouteResponse):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            print(f"Added inbound route {response.parsed.normalized_did}.")
            return
        if action == "remove":
            matches = [
                route
                for route in _routes(client, tenant.id)
                if route.normalized_did == number
            ]
            if len(matches) != 1:
                raise PromptCommandError(f"unknown inbound route: {number}", 2)
            response = delete_inbound_route_admin_v1_tenants_tenant_id_inbound_routes_route_id_delete.sync_detailed(
                tenant.id, matches[0].id, client=client
            )
            _response_error(response)
            print(f"Removed inbound route {number}.")
            return
        raise PromptCommandError(f"unsupported inbound route action: {action}", 2)
