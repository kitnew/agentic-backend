from __future__ import annotations

import sys
from getpass import getpass
from json import JSONDecodeError, loads
from uuid import UUID

from admin_client import AuthenticatedClient
from admin_client.generated.api.adminintegrations import (
    create_connection_admin_v1_tenants_tenant_id_integration_connections_post,
    delete_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_delete,
    disable_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_disable_post,
    enable_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_enable_post,
    list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
    rotate_secret_admin_v1_tenants_tenant_id_integration_connections_connection_id_secrets_rotate_post,
    set_secret_admin_v1_tenants_tenant_id_integration_connections_connection_id_secrets_post,
    test_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_test_post,
    update_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_patch,
)
from admin_client.generated.models.create_integration_connection_request import (
    CreateIntegrationConnectionRequest,
)
from admin_client.generated.models.create_integration_connection_request_config import (
    CreateIntegrationConnectionRequestConfig,
)
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.integration_provider import IntegrationProvider
from admin_client.generated.models.integration_test_response import (
    IntegrationTestResponse,
)
from admin_client.generated.models.set_integration_secret_request import (
    SetIntegrationSecretRequest,
)
from admin_client.generated.models.set_integration_secret_request_secret import (
    SetIntegrationSecretRequestSecret,
)
from admin_client.generated.models.update_integration_connection_request import (
    UpdateIntegrationConnectionRequest,
)
from admin_client.generated.models.update_integration_connection_request_config_type_0 import (
    UpdateIntegrationConnectionRequestConfigType0,
)

from control_plane.commands.common import (
    _client,
    _response_error,
    _tenant,
)
from control_plane.commands.errors import CommandError
from control_plane.settings import Settings


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        parsed = loads(value)
    except JSONDecodeError as error:
        raise CommandError(f"{label} must be a JSON object", 2) from error
    if not isinstance(parsed, dict):
        raise CommandError(f"{label} must be a JSON object", 2)
    return parsed


def _secret() -> dict[str, object]:
    value = (
        getpass("Integration secret JSON: ") if sys.stdin.isatty() else sys.stdin.read()
    )
    if not value.strip():
        raise CommandError("integration secret JSON is required on stdin", 2)
    return _json_object(value, "integration secret")


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
        raise CommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _connection(
    client: AuthenticatedClient, tenant_id: UUID, key: str
) -> IntegrationConnectionResponse:
    matches = [item for item in _connections(client, tenant_id) if item.key == key]
    if not matches:
        raise CommandError(f"unknown integration connection: {key}", 2)
    if len(matches) != 1:
        raise CommandError(f"ambiguous integration connection: {key}", 1)
    return matches[0]


def _print(item: IntegrationConnectionResponse) -> None:
    print(f"Integration: {item.key}")
    print(f"Provider: {item.provider.value}")
    print(f"Status: {item.status.value}")
    print(f"Revision: {item.revision}")
    print(f"Credential version: {item.credential_version}")
    print(f"Credential fingerprint: {item.credential_fingerprint}")
    print(f"ID: {item.id}")


def run_integration(
    settings: Settings,
    action: str,
    tenant_slug: str,
    key: str | None = None,
    *,
    provider: str | None = None,
    config_json: str | None = None,
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        if action == "list":
            items = _connections(client, tenant.id)
            if not items:
                print("No integrations.")
                return
            print("KEY\tPROVIDER\tSTATUS\tCREDENTIAL_VERSION")
            for item in items:
                print(
                    f"{item.key}\t{item.provider.value}\t{item.status.value}\t"
                    f"{item.credential_version}"
                )
            return
        assert key is not None
        if action == "show":
            _print(_connection(client, tenant.id, key))
            return
        if action == "create":
            assert provider is not None and config_json is not None
            response = create_connection_admin_v1_tenants_tenant_id_integration_connections_post.sync_detailed(
                tenant.id,
                client=client,
                body=CreateIntegrationConnectionRequest(
                    key=key,
                    provider=IntegrationProvider(provider),
                    config=CreateIntegrationConnectionRequestConfig.from_dict(
                        _json_object(config_json, "integration config")
                    ),
                ),
            )
            _response_error(response)
            if not isinstance(response.parsed, IntegrationConnectionResponse):
                raise CommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _print(response.parsed)
            return
        item = _connection(client, tenant.id, key)
        if action == "test":
            test_response = test_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_test_post.sync_detailed(
                tenant.id, item.id, client=client
            )
            _response_error(test_response)
            if not isinstance(test_response.parsed, IntegrationTestResponse):
                raise CommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            print(f"Integration {item.key} is {test_response.parsed.status}.")
            return
        if action == "configure":
            assert config_json is not None
            response = update_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_patch.sync_detailed(
                tenant.id,
                item.id,
                client=client,
                body=UpdateIntegrationConnectionRequest(
                    config=UpdateIntegrationConnectionRequestConfigType0.from_dict(
                        _json_object(config_json, "integration config")
                    )
                ),
            )
        elif action in {"set-secret", "rotate-secret"}:
            endpoint = (
                rotate_secret_admin_v1_tenants_tenant_id_integration_connections_connection_id_secrets_rotate_post
                if action == "rotate-secret"
                else set_secret_admin_v1_tenants_tenant_id_integration_connections_connection_id_secrets_post
            )
            response = endpoint.sync_detailed(
                tenant.id,
                item.id,
                client=client,
                body=SetIntegrationSecretRequest(
                    secret=SetIntegrationSecretRequestSecret.from_dict(_secret())
                ),
            )
        elif action == "enable":
            response = enable_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_enable_post.sync_detailed(
                tenant.id, item.id, client=client
            )
        elif action == "disable":
            response = disable_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_disable_post.sync_detailed(
                tenant.id, item.id, client=client
            )
        elif action == "delete":
            response = delete_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_delete.sync_detailed(
                tenant.id, item.id, client=client
            )
            _response_error(response)
            print(f"Deleted integration {item.key}.")
            return
        else:
            raise CommandError(f"unsupported integration action: {action}", 2)
        _response_error(response)
        if not isinstance(response.parsed, IntegrationConnectionResponse):
            raise CommandError(
                "unexpected client failure: invalid Backend response", 1
            )
        _print(response.parsed)
