from uuid import UUID, uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.modules.tenants.models import Tenant, TenantStatus
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

LEGACY_YAML = """
schema_version: 1
tenant_id: legacy_hotel
name: Legacy Hotel
business_type: hotel
locale: sk-SK
timezone: Europe/Bratislava
agent:
  display_name: Amélia
  greeting_phrase: Dobrý deň...
  tone: warm
conversation_scope:
  mode: property_only
voice:
  enabled: true
"""


@pytest.mark.asyncio
async def test_legacy_yaml_import_and_internal_active_config(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(database=database)
    transport = ASGITransport(app=app)
    actor_id = uuid4()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tenant_response = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "legacy-hotel",
                    "display_name": "Legacy Hotel",
                    "business_type": "hotel",
                },
            )
            tenant_id = UUID(tenant_response.json()["id"])
            import_url = f"/admin/v1/tenants/{tenant_id}/config/import-yaml"
            internal_config_url = f"/internal/v1/tenants/{tenant_id}/active-config"

            mismatch = await client.post(
                import_url,
                params={"created_by": str(actor_id)},
                content=LEGACY_YAML.replace("legacy_hotel", "another_hotel"),
                headers={"content-type": "application/yaml"},
            )
            assert mismatch.status_code == 422
            assert mismatch.json()["detail"]["errors"][0]["code"] == (
                "tenant_identity_mismatch"
            )

            draft_response = await client.post(
                import_url,
                params={"created_by": str(actor_id)},
                content=LEGACY_YAML,
                headers={"content-type": "application/yaml"},
            )
            assert draft_response.status_code == 201
            imported = draft_response.json()
            assert imported["revision"]["status"] == "draft"
            assert imported["validation"] == {"valid": True, "errors": []}
            assert imported["source_tenant"] == {
                "legacy_id": "legacy_hotel",
                "display_name": "Legacy Hotel",
                "business_type": "hotel",
            }
            assert imported["unsupported_fields"] == ["agent.tone", "voice"]
            assert (await client.get(internal_config_url)).status_code == 404

            revision_id = imported["revision"]["id"]
            publish_response = await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts/{revision_id}/publish"
            )
            assert publish_response.status_code == 200

            internal_response = await client.get(internal_config_url)
            assert internal_response.status_code == 200
            internal_config = internal_response.json()
            admin_config = (
                await client.get(
                    f"/admin/v1/tenants/{tenant_id}/config/active",
                )
            ).json()
            assert internal_config == admin_config
            assert internal_config == {
                "tenant_id": str(tenant_id),
                "revision_id": revision_id,
                "revision_number": 1,
                "published_at": publish_response.json()["published_at"],
                "config": {
                    "schema_version": 1,
                    "localization": {
                        "default_locale": "sk-SK",
                        "timezone": "Europe/Bratislava",
                    },
                    "agent": {
                        "display_name": "Amélia",
                        "greeting": "Dobrý deň...",
                    },
                    "conversation": {"scope": "property_only"},
                    "capabilities": {},
                },
            }

            published_import = await client.post(
                import_url,
                params={"created_by": str(actor_id), "publish": "true"},
                content=LEGACY_YAML,
                headers={"content-type": "application/yaml"},
            )
            assert published_import.status_code == 201
            assert published_import.json()["revision"]["status"] == "published"
            assert published_import.json()["revision"]["revision_number"] == 2

            async with database.transaction() as session:
                await session.execute(
                    update(Tenant)
                    .where(Tenant.id == tenant_id)
                    .values(status=TenantStatus.ARCHIVED)
                )
            assert (await client.get(internal_config_url)).status_code == 404
    finally:
        await database.close()
