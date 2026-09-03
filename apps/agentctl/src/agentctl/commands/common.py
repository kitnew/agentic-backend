from typing import Any

import httpx
from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.types import Response

from agentctl.commands.errors import CommandError
from agentctl.settings import Settings


def _client(settings: Settings) -> AuthenticatedClient:
    return AuthenticatedClient(
        base_url=settings.api_url, token=settings.token, timeout=httpx.Timeout(10.0)
    )


def _response_error(response: Response[Any]) -> None:
    if 200 <= response.status_code < 300:
        return
    raise CommandError(
        f"Admin API request failed ({response.status_code}): {response.content.decode(errors='replace')[:500]}",
        3,
    )


def _tenant(client: AuthenticatedClient, slug: str) -> TenantResponse:
    response = get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get.sync_detailed(
        slug, client=client
    )
    _response_error(response)
    if not isinstance(response.parsed, TenantResponse):
        raise CommandError("unexpected client failure: invalid Backend response", 1)
    return response.parsed
