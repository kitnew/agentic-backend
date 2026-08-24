from __future__ import annotations

from getpass import getpass
from uuid import UUID

from admin_client import AuthenticatedClient
from admin_client.generated.api.adminintegrations import (
    configure_connection_admin_v1_tenants_tenant_id_integrations_key_put,
    create_connection_admin_v1_tenants_tenant_id_integrations_post,
    delete_connection_admin_v1_tenants_tenant_id_integrations_key_delete,
    disable_connection_admin_v1_tenants_tenant_id_integrations_key_disable_post,
    enable_connection_admin_v1_tenants_tenant_id_integrations_key_enable_post,
    list_connections_admin_v1_tenants_tenant_id_integrations_get,
    plan_connection_admin_v1_tenants_tenant_id_integrations_key_plan_post,
    revoke_credential_admin_v1_tenants_tenant_id_integrations_key_credentials_revoke_post,
    rotate_credential_admin_v1_tenants_tenant_id_integrations_key_credentials_rotate_post,
    validate_connection_admin_v1_tenants_tenant_id_integrations_key_validate_post,
)
from admin_client.generated.models.configure_integration_connection_request import (
    ConfigureIntegrationConnectionRequest,
)
from admin_client.generated.models.create_integration_connection_request import (
    CreateIntegrationConnectionRequest,
)
from admin_client.generated.models.create_integration_connection_request_kind import (
    CreateIntegrationConnectionRequestKind,
)
from admin_client.generated.models.http_api_key_header_authentication import (
    HttpApiKeyHeaderAuthentication,
)
from admin_client.generated.models.http_authentication_none import (
    HttpAuthenticationNone,
)
from admin_client.generated.models.http_connection_configuration import (
    HttpConnectionConfiguration,
)
from admin_client.generated.models.http_connection_configuration_headers import (
    HttpConnectionConfigurationHeaders,
)
from admin_client.generated.models.http_connection_security import (
    HttpConnectionSecurity,
)
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.integration_credential_write import (
    IntegrationCredentialWrite,
)
from admin_client.generated.models.integration_plan import IntegrationPlan
from admin_client.generated.models.integration_validate_response import (
    IntegrationValidateResponse,
)

from control_plane.commands.common import _client, _response_error, _tenant
from control_plane.commands.errors import CommandError
from control_plane.settings import Settings


def _connections(
    client: AuthenticatedClient, tenant_id: UUID
) -> list[IntegrationConnectionResponse]:
    response = (
        list_connections_admin_v1_tenants_tenant_id_integrations_get.sync_detailed(
            tenant_id, client=client
        )
    )
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, IntegrationConnectionResponse) for item in response.parsed
    ):
        raise CommandError("unexpected client failure: invalid Backend response", 1)
    return response.parsed


def _connection(
    client: AuthenticatedClient, tenant_id: UUID, key: str
) -> IntegrationConnectionResponse:
    matches = [item for item in _connections(client, tenant_id) if item.key == key]
    if not matches:
        raise CommandError(f"unknown integration connection: {key}", 2)
    return matches[0]


def _api_key() -> str:
    value = getpass("API key: ")
    if not value:
        raise CommandError("API key is required", 2)
    return value


def _headers(values: list[str] | None) -> HttpConnectionConfigurationHeaders:
    result = HttpConnectionConfigurationHeaders()
    for value in values or []:
        name, separator, header_value = value.partition("=")
        if not separator or not name.strip():
            raise CommandError("header must use NAME=VALUE syntax", 2)
        result[name.strip()] = header_value
    return result


def _candidate(
    *,
    endpoint: str,
    auth: str,
    auth_header: str,
    headers: list[str] | None,
    additional_allowed_hosts: list[str] | None,
    api_key: str | None,
) -> ConfigureIntegrationConnectionRequest:
    authentication = (
        HttpAuthenticationNone()
        if auth == "none"
        else HttpApiKeyHeaderAuthentication(header_name=auth_header)
    )
    configuration = HttpConnectionConfiguration(
        endpoint=endpoint,
        authentication=authentication,
        headers=_headers(headers),
        security=HttpConnectionSecurity(
            additional_allowed_hosts=additional_allowed_hosts or []
        ),
    )
    if api_key:
        return ConfigureIntegrationConnectionRequest(
            configuration=configuration,
            credential=IntegrationCredentialWrite(api_key=api_key),
        )
    return ConfigureIntegrationConnectionRequest(configuration=configuration)


def _print(item: IntegrationConnectionResponse) -> None:
    print(f"Integration: {item.key}")
    print(f"Kind: {item.kind.value}")
    print(f"Configuration: {item.configuration.to_dict()}")
    print(f"Enabled: {item.enabled}")
    print(f"Revision: {item.revision}")
    print(f"Credential status: {item.credential_status}")
    print(f"Credential version: {item.credential_version}")
    print(f"Readiness: {item.readiness.to_dict()}")


def _print_plan(plan: IntegrationPlan) -> None:
    for change in plan.changes if hasattr(plan.changes, "__iter__") else []:
        print(f"{change.path}: {change.before} -> {change.after}")
    print(f"credential: {plan.credential.value}")
    print(f"live_apply: {plan.live_apply}")
    print(f"would_be_ready: {plan.would_be_ready}")
    for issue in plan.issues if hasattr(plan.issues, "__iter__") else []:
        print(f"{issue.code}: {issue.message}")


def _print_validation(result: IntegrationValidateResponse, enabled: bool) -> None:
    print(f"configuration: {result.configuration.value}")
    print(f"credentials: {result.credentials.value}")
    print(f"ready: {result.ready}")
    print(f"enabled: {enabled}")
    print(f"usable: {result.usable}")
    for issue in result.issues if hasattr(result.issues, "__iter__") else []:
        print(f"{issue.code}: {issue.message}")


def run_integration(
    settings: Settings,
    action: str,
    tenant_slug: str,
    key: str | None = None,
    *,
    kind: str = "http",
    endpoint: str | None = None,
    auth: str = "none",
    auth_header: str = "X-API-Key",
    headers: list[str] | None = None,
    additional_allowed_hosts: list[str] | None = None,
    api_key: str | None = None,
) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, tenant_slug)
        if action == "list":
            items = _connections(client, tenant.id)
            print("KEY\tKIND\tENABLED\tREADY\tUSABLE")
            for item in items:
                print(
                    f"{item.key}\t{item.kind.value}\t{item.enabled}\t{item.readiness.ready}\t{item.readiness.usable}"
                )
            return
        if key is None:
            raise CommandError("integration key is required", 2)
        if action == "create":
            response = create_connection_admin_v1_tenants_tenant_id_integrations_post.sync_detailed(
                tenant.id,
                client=client,
                body=CreateIntegrationConnectionRequest(
                    key=key, kind=CreateIntegrationConnectionRequestKind(kind)
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
        if action == "show":
            _print(item)
            return
        if action in {"configure", "plan"}:
            if endpoint is None:
                raise CommandError("--endpoint is required", 2)
            if auth not in {"none", "api_key_header"}:
                raise CommandError("--auth must be none or api_key_header", 2)
            secret = api_key or (_api_key() if auth == "api_key_header" else None)
            body = _candidate(
                endpoint=endpoint,
                auth=auth,
                auth_header=auth_header,
                headers=headers,
                additional_allowed_hosts=additional_allowed_hosts,
                api_key=secret,
            )
            if action == "plan":
                response = plan_connection_admin_v1_tenants_tenant_id_integrations_key_plan_post.sync_detailed(
                    tenant.id, key, client=client, body=body
                )
                _response_error(response)
                if not isinstance(response.parsed, IntegrationPlan):
                    raise CommandError(
                        "unexpected client failure: invalid Backend response", 1
                    )
                _print_plan(response.parsed)
                return
            response = configure_connection_admin_v1_tenants_tenant_id_integrations_key_put.sync_detailed(
                tenant.id, key, client=client, body=body, if_match=f'"{item.revision}"'
            )
        elif action == "validate":
            response = validate_connection_admin_v1_tenants_tenant_id_integrations_key_validate_post.sync_detailed(
                tenant.id, key, client=client
            )
            _response_error(response)
            if not isinstance(response.parsed, IntegrationValidateResponse):
                raise CommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _print_validation(response.parsed, item.enabled)
            return
        elif action == "enable":
            response = enable_connection_admin_v1_tenants_tenant_id_integrations_key_enable_post.sync_detailed(
                tenant.id, key, client=client
            )
        elif action == "disable":
            response = disable_connection_admin_v1_tenants_tenant_id_integrations_key_disable_post.sync_detailed(
                tenant.id, key, client=client
            )
        elif action == "rotate-credential":
            response = rotate_credential_admin_v1_tenants_tenant_id_integrations_key_credentials_rotate_post.sync_detailed(
                tenant.id,
                key,
                client=client,
                body=IntegrationCredentialWrite(api_key=api_key or _api_key()),
            )
        elif action == "revoke-credential":
            response = revoke_credential_admin_v1_tenants_tenant_id_integrations_key_credentials_revoke_post.sync_detailed(
                tenant.id, key, client=client
            )
        elif action == "delete":
            response = delete_connection_admin_v1_tenants_tenant_id_integrations_key_delete.sync_detailed(
                tenant.id, key, client=client
            )
            _response_error(response)
            print(f"Deleted integration {key}.")
            return
        else:
            raise CommandError(f"unsupported integration action: {action}", 2)
        _response_error(response)
        if isinstance(response.parsed, IntegrationConnectionResponse):
            _print(response.parsed)
