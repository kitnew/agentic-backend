import asyncio

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import publish_config, publish_prompt_set
from test_voice_test_sessions import cleanup_tenants


async def create_tenant(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/admin/v1/tenants",
        json={
            "slug": slug,
            "display_name": slug.replace("-", " ").title(),
            "business_type": "hotel",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_prompt_set_lifecycle_and_config_v3_reference(
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
            tenant_id = await create_tenant(client, "prompt-set-hotel")
            drafts_url = f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts"

            draft_response = await client.post(
                drafts_url,
                json={"text": "Answer only about this property."},
            )
            assert draft_response.status_code == 201
            assert draft_response.headers["etag"] == '"1"'
            revision_id = draft_response.json()["id"]
            assert draft_response.json()["revision_number"] == 1
            assert draft_response.json()["status"] == "draft"

            assert (
                await client.post(
                    drafts_url,
                    json={"text": "Another draft"},
                )
            ).status_code == 409
            assert (
                await client.patch(
                    f"{drafts_url}/{revision_id}",
                    json={"text": "Missing If-Match"},
                )
            ).status_code == 428

            updated = await client.patch(
                f"{drafts_url}/{revision_id}",
                json={"text": "Updated tenant instructions."},
                headers={"If-Match": '"1"'},
            )
            assert updated.status_code == 200
            assert updated.headers["etag"] == '"2"'
            assert updated.json()["version"] == 2
            assert (
                await client.patch(
                    f"{drafts_url}/{revision_id}",
                    json={"text": "Stale"},
                    headers={"If-Match": '"1"'},
                )
            ).status_code == 412

            publish_responses = await asyncio.gather(
                *(client.post(f"{drafts_url}/{revision_id}/publish") for _ in range(2))
            )
            assert sorted(response.status_code for response in publish_responses) == [
                200,
                409,
            ]
            published = next(
                response.json()
                for response in publish_responses
                if response.status_code == 200
            )
            assert published["status"] == "published"
            assert published["published_at"] is not None
            assert (
                await client.patch(
                    f"{drafts_url}/{revision_id}",
                    json={"text": "Immutable"},
                    headers={"If-Match": '"2"'},
                )
            ).status_code == 409

            revisions = (
                await client.get(
                    f"/admin/v1/tenants/{tenant_id}/tenant-prompt/revisions"
                )
            ).json()
            assert revisions == [published]

            prompt_set = await publish_prompt_set(client, tenant_id)
            config_id = await publish_config(client, tenant_id, greeting="Dobrý deň")
            active_config = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/config/active")
            ).json()
            assert active_config["revision_id"] == config_id
            assert active_config["config"]["schema_version"] == 3
            assert active_config["config"]["agent"]["profile"] == "hotel_assistant"

            active_prompt_set = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            assert active_prompt_set["id"] == prompt_set["prompt_set_revision_id"]
            assert active_prompt_set["status"] == "published"
    finally:
        await cleanup_tenants(database, "prompt-set-hotel")
        await database.close()
