from uuid import UUID, uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.models import Tenant, TenantStatus
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete


@pytest.mark.asyncio
async def test_tenant_admin_api(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
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

            slug_response = await client.get(
                f"/admin/v1/tenants/by-slug/{payload['slug']}"
            )
            assert slug_response.status_code == 200
            assert slug_response.json() == created

            list_response = await client.get("/admin/v1/tenants")
            assert list_response.status_code == 200
            assert created in list_response.json()

            duplicate_response = await client.post(
                "/admin/v1/tenants",
                json=payload,
            )
            assert duplicate_response.status_code == 409

            missing_response = await client.get(f"/admin/v1/tenants/{uuid4()}")
            assert missing_response.status_code == 404

            missing_slug_response = await client.get(
                "/admin/v1/tenants/by-slug/missing-tenant"
            )
            assert missing_slug_response.status_code == 404

            invalid_slug_response = await client.post(
                "/admin/v1/tenants",
                json={**payload, "slug": "Grand Hotel"},
            )
            assert invalid_slug_response.status_code == 422
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_tenant_prompt_draft_publish_is_immutable_and_does_not_activate(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)
    tenant_id: UUID | None = None

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant = (
                await client.post(
                    "/admin/v1/tenants",
                    json={
                        "slug": "tenant-prompt-hotel",
                        "display_name": "Tenant Prompt Hotel",
                        "business_type": "hotel",
                    },
                )
            ).json()
            tenant_id = UUID(tenant["id"])
            drafts_url = f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts"

            created = await client.post(drafts_url, json={"text": "first"})
            assert created.status_code == 201
            draft = created.json()
            assert draft["status"] == "draft"
            assert created.headers["etag"] == '"1"'

            updated = await client.patch(
                f"{drafts_url}/{draft['id']}",
                json={"text": "second"},
                headers={"If-Match": '"1"'},
            )
            assert updated.status_code == 200
            assert updated.json()["version"] == 2
            assert (
                await client.patch(
                    f"{drafts_url}/{draft['id']}",
                    json={"text": "stale"},
                    headers={"If-Match": '"1"'},
                )
            ).status_code == 412

            published = await client.post(f"{drafts_url}/{draft['id']}/publish")
            assert published.status_code == 200
            assert published.json()["status"] == "published"
            assert (
                await client.patch(
                    f"{drafts_url}/{draft['id']}",
                    json={"text": "immutable"},
                    headers={"If-Match": '"2"'},
                )
            ).status_code == 409
            tenant_after = await client.get(f"/admin/v1/tenants/{tenant_id}")
            assert tenant_after.json()["active_prompt_set_revision_id"] is None
    finally:
        if tenant_id is not None:
            async with database.transaction() as session:
                await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await database.close()


def test_archived_tenant_is_not_available_in_runtime() -> None:
    tenant = Tenant(
        slug="archived-hotel",
        display_name="Archived Hotel",
        business_type="hotel",
        status=TenantStatus.ARCHIVED,
    )

    assert not tenant.is_available_in_runtime
