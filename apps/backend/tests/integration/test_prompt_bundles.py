import asyncio
from uuid import uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient


def config_v2(prompt_bundle_revision_id: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "prompt_bundle_revision_id": prompt_bundle_revision_id,
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
    }


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
async def test_prompt_bundle_lifecycle_and_config_v2_reference(
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
            tenant_id = await create_tenant(client, "prompt-bundle-hotel")
            drafts_url = (
                f"/admin/v1/tenants/{tenant_id}/prompt-bundle/drafts"
            )

            assert (
                await client.post(
                    f"/admin/v1/tenants/{uuid4()}/prompt-bundle/drafts",
                    json={"system_instructions": "You are a hotel assistant."},
                )
            ).status_code == 404
            assert (
                await client.post(
                    drafts_url,
                    json={"system_instructions": ""},
                )
            ).status_code == 422

            draft_response = await client.post(
                drafts_url,
                json={
                    "system_instructions": "You are a hotel assistant.",
                    "tenant_instructions": "Answer only about this property.",
                    "knowledge_text": "# Hotel\nBreakfast starts at 07:00.",
                },
            )
            assert draft_response.status_code == 201
            assert draft_response.headers["etag"] == '"1"'
            draft = draft_response.json()
            revision_id = draft["id"]
            assert draft["revision_number"] == 1
            assert draft["status"] == "draft"

            assert (
                await client.post(
                    drafts_url,
                    json={"system_instructions": "Another draft"},
                )
            ).status_code == 409
            assert (
                await client.patch(
                    f"{drafts_url}/{revision_id}",
                    json={"knowledge_text": "Missing If-Match"},
                )
            ).status_code == 428

            updated = await client.patch(
                f"{drafts_url}/{revision_id}",
                json={"knowledge_text": "# Hotel\nBreakfast starts at 06:30."},
                headers={"If-Match": '"1"'},
            )
            assert updated.status_code == 200
            assert updated.headers["etag"] == '"2"'
            assert updated.json()["version"] == 2
            assert (
                await client.patch(
                    f"{drafts_url}/{revision_id}",
                    json={"knowledge_text": "Stale"},
                    headers={"If-Match": '"1"'},
                )
            ).status_code == 412

            publish_responses = await asyncio.gather(
                *(
                    client.post(f"{drafts_url}/{revision_id}/publish")
                    for _ in range(2)
                )
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
                    json={"knowledge_text": "Immutable"},
                    headers={"If-Match": '"2"'},
                )
            ).status_code == 409

            revisions = (
                await client.get(
                    f"/admin/v1/tenants/{tenant_id}/prompt-bundle/revisions"
                )
            ).json()
            assert revisions == [published]

            config_url = f"/admin/v1/tenants/{tenant_id}/config"
            config_draft = await client.post(
                f"{config_url}/drafts",
                json={
                    "schema_version": 2,
                    "config": config_v2(revision_id),
                },
            )
            assert config_draft.status_code == 201
            config_revision_id = config_draft.json()["id"]
            validation = await client.post(
                f"{config_url}/drafts/{config_revision_id}/validate"
            )
            assert validation.json() == {"valid": True, "errors": []}
            assert (
                await client.post(
                    f"{config_url}/drafts/{config_revision_id}/publish"
                )
            ).status_code == 200
            active = (await client.get(f"{config_url}/active")).json()
            assert active["config"]["schema_version"] == 2
            assert active["config"]["prompt_bundle_revision_id"] == revision_id

            other_tenant_id = await create_tenant(client, "other-prompt-hotel")
            other_prompt = await client.post(
                f"/admin/v1/tenants/{other_tenant_id}/prompt-bundle/drafts",
                json={"system_instructions": "Other tenant assistant."},
            )
            assert other_prompt.status_code == 201
            other_prompt_id = other_prompt.json()["id"]
            other_config_url = (
                f"/admin/v1/tenants/{other_tenant_id}/config/drafts"
            )
            other_config = await client.post(
                other_config_url,
                json={
                    "schema_version": 2,
                    "config": config_v2(revision_id),
                },
            )
            assert other_config.status_code == 201
            other_config_id = other_config.json()["id"]
            cross_tenant_validation = await client.post(
                f"{other_config_url}/{other_config_id}/validate"
            )
            assert cross_tenant_validation.json() == {
                "valid": False,
                "errors": [
                    {
                        "path": "prompt_bundle_revision_id",
                        "code": "prompt_bundle_revision_not_found",
                        "message": "Prompt bundle revision does not belong to tenant",
                    }
                ],
            }

            draft_prompt_config = await client.patch(
                f"{other_config_url}/{other_config_id}",
                json={"config": config_v2(other_prompt_id)},
                headers={"If-Match": '"1"'},
            )
            assert draft_prompt_config.status_code == 200
            draft_prompt_validation = await client.post(
                f"{other_config_url}/{other_config_id}/validate"
            )
            assert draft_prompt_validation.json() == {
                "valid": False,
                "errors": [
                    {
                        "path": "prompt_bundle_revision_id",
                        "code": "prompt_bundle_revision_not_published",
                        "message": "Prompt bundle revision is not published",
                    }
                ],
            }
            assert (
                await client.post(
                    f"{other_config_url}/{other_config_id}/publish"
                )
            ).status_code == 422
            assert (
                await client.post(
                    f"/admin/v1/tenants/{other_tenant_id}/prompt-bundle/"
                    f"drafts/{other_prompt_id}/publish"
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"{other_config_url}/{other_config_id}/validate"
                )
            ).json() == {"valid": True, "errors": []}
    finally:
        await database.close()
