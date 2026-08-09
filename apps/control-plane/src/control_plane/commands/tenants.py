import httpx
from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    list_tenants_admin_v1_tenants_get,
)
from admin_client.generated.models.http_validation_error import HTTPValidationError
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.types import Response

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
