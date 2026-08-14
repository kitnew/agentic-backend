import httpx
from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    create_tenant_admin_v1_tenants_post,
    list_tenants_admin_v1_tenants_get,
)
from admin_client.generated.models.create_tenant_request import CreateTenantRequest
from admin_client.generated.models.http_validation_error import HTTPValidationError
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.tenant_status import TenantStatus
from admin_client.generated.types import Response

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
)
from control_plane.settings import Settings


def fetch_tenants(
    settings: Settings,
) -> Response[HTTPValidationError | list[TenantResponse]]:
    with AuthenticatedClient(
        base_url=settings.api_url,
        token=settings.token,
        timeout=httpx.Timeout(10.0),
    ) as client:
        return list_tenants_admin_v1_tenants_get.sync_detailed(client=client)


def run_tenant_create(
    settings: Settings,
    slug: str,
    display_name: str,
    business_type: str,
    status: str,
) -> None:
    with _client(settings) as client:
        response = create_tenant_admin_v1_tenants_post.sync_detailed(
            client=client,
            body=CreateTenantRequest(
                slug=slug,
                display_name=display_name,
                business_type=business_type,
                status=TenantStatus(status),
            ),
        )
        if response.status_code == 409:
            raise PromptCommandError("tenant slug already exists", 2)
        _response_error(response)
        if not isinstance(response.parsed, TenantResponse):
            raise PromptCommandError(
                "unexpected client failure: invalid Backend response", 1
            )
        tenant = response.parsed
        print("Created tenant:")
        print(f"  ID: {tenant.id}")
        print(f"  Slug: {tenant.slug}")
        print(f"  Display name: {tenant.display_name}")
        print(f"  Business type: {tenant.business_type}")
        print(f"  Status: {tenant.status.value}")
