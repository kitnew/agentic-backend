from __future__ import annotations

from uuid import UUID

from admin_client import AuthenticatedClient
from admin_client.generated.api.adminintegrations import (
    create_connection_admin_v1_tenants_tenant_id_integration_connections_post,
    delete_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_delete,
    list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
)
from admin_client.generated.models.create_integration_connection_request import (
    CreateIntegrationConnectionRequest,
)
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.integration_provider import IntegrationProvider

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
)
from control_plane.settings import Settings


def _connections(
    client: AuthenticatedClient, tenant_id: UUID
) -> list[IntegrationConnectionResponse]:
    response = list_connections_admin_v1_tenants_tenant_id_integration_connections_get.sync_detailed(
        tenant_id, client=client
    )
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, IntegrationConnectionResponse) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _connection(
    client: AuthenticatedClient, tenant_id: UUID, key: str
) -> IntegrationConnectionResponse:
    matches = [item for item in _connections(client, tenant_id) if item.key == key]
    if not matches:
        raise PromptCommandError(f"unknown integration connection: {key}", 2)
    if len(matches) != 1:
        raise PromptCommandError(f"ambiguous integration connection: {key}", 1)
    return matches[0]


def run_integration(
    settings: Settings,
    action: str,
    tenant_slug: str,
    key: str | None = None,
    *,
    provider: str | None = None,
    credential_ref: str | None = None,
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        if action == "list":
            items = _connections(client, tenant.id)
            if not items:
                print("No integration connections.")
                return
            print("KEY\tPROVIDER\tSTATUS\tCREDENTIAL_REF")
            for item in items:
                print(
                    f"{item.key}\t{item.provider.value}\t{item.status.value}\t"
                    f"{item.credential_ref}"
                )
            return
        assert key is not None
        if action == "show":
            item = _connection(client, tenant.id, key)
            print(f"Integration: {item.key}")
            print(f"Provider: {item.provider.value}")
            print(f"Status: {item.status.value}")
            print(f"Credential reference: {item.credential_ref}")
            print(f"ID: {item.id}")
            return
        if action == "create":
            assert provider is not None and credential_ref is not None
            response = create_connection_admin_v1_tenants_tenant_id_integration_connections_post.sync_detailed(
                tenant.id,
                client=client,
                body=CreateIntegrationConnectionRequest(
                    key=key,
                    provider=IntegrationProvider(provider),
                    credential_ref=credential_ref,
                ),
            )
            _response_error(response)
            if not isinstance(response.parsed, IntegrationConnectionResponse):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            print(
                f"Created integration {response.parsed.key} "
                f"({response.parsed.provider.value}, {response.parsed.credential_ref})."
            )
            return
        if action == "delete":
            item = _connection(client, tenant.id, key)
            response = delete_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_delete.sync_detailed(
                tenant.id, item.id, client=client
            )
            _response_error(response)
            print(f"Deleted integration {item.key}.")
            return
        raise PromptCommandError(f"unsupported integration action: {action}", 2)
