from uuid import UUID, uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.modules.tenants.models import Tenant, TenantStatus
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_tenant_admin_api(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    app = create_app(database=database)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "slug": "grand-hotel",
                "display_name": "Grand Hotel",
                "business_type": "hotel",
            }
            create_response = await client.post("/admin/v1/tenants", json=payload)
            assert create_response.status_code == 201
            created = create_response.json()
            tenant_id = UUID(created["id"])
            assert created["status"] == "active"
            assert created["slug"] == payload["slug"]

            get_response = await client.get(f"/admin/v1/tenants/{tenant_id}")
            assert get_response.status_code == 200
            assert get_response.json() == created

            list_response = await client.get("/admin/v1/tenants")
            assert list_response.status_code == 200
            assert list_response.json() == [created]

            duplicate_response = await client.post(
                "/admin/v1/tenants",
                json=payload,
            )
            assert duplicate_response.status_code == 409

            missing_response = await client.get(f"/admin/v1/tenants/{uuid4()}")
            assert missing_response.status_code == 404

            invalid_slug_response = await client.post(
                "/admin/v1/tenants",
                json={**payload, "slug": "Grand Hotel"},
            )
            assert invalid_slug_response.status_code == 422
    finally:
        await database.close()


def test_archived_tenant_is_not_available_in_runtime() -> None:
    tenant = Tenant(
        slug="archived-hotel",
        display_name="Archived Hotel",
        business_type="hotel",
        status=TenantStatus.ARCHIVED,
    )

    assert not tenant.is_available_in_runtime
