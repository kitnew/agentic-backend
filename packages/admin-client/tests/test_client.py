from http import HTTPStatus

import admin_client
import httpx
from admin_client.generated.api.admintenants import (
    list_tenants_admin_v1_tenants_get,
)


def test_generated_client_calls_tenant_list_with_bearer_auth() -> None:
    def backend(request: httpx.Request) -> httpx.Response:
        assert (
            request.url == "https://backend.example/admin/v1/tenants?offset=0&limit=100"
        )
        assert request.headers["Authorization"] == "Bearer admin-secret"
        return httpx.Response(
            HTTPStatus.OK,
            json=[
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "slug": "penzion-grand",
                    "display_name": "Penzion Grand",
                    "business_type": "hospitality",
                    "status": "active",
                    "active_release_id": None,
                    "created_at": "2026-08-09T00:00:00Z",
                    "updated_at": "2026-08-09T00:00:00Z",
                }
            ],
        )

    client = admin_client.AuthenticatedClient(
        base_url="https://backend.example",
        token="admin-secret",
        httpx_args={"transport": httpx.MockTransport(backend)},
    )
    with client:
        response = list_tenants_admin_v1_tenants_get.sync_detailed(client=client)

    assert response.status_code is HTTPStatus.OK
    assert response.parsed is not None
    assert response.parsed[0].slug == "penzion-grand"
    assert admin_client.Client(base_url="https://backend.example")
