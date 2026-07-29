import asyncio
from uuid import UUID

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.models import TenantConfigRevision
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError


def config_v1() -> dict[str, object]:
    return {
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
    }


@pytest.mark.asyncio
async def test_concurrent_draft_creation_and_publication_are_serialized(
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
            tenant = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "concurrent-config-hotel",
                    "display_name": "Concurrent Config Hotel",
                    "business_type": "hotel",
                },
            )
            tenant_id = UUID(tenant.json()["id"])
            config_url = f"/admin/v1/tenants/{tenant_id}/config"

            create_responses = await asyncio.gather(
                *(
                    client.post(
                        f"{config_url}/drafts",
                        json={
                            "config": config_v1(),
                            "comment": comment,
                        },
                    )
                    for comment in ("concurrent A", "concurrent B")
                )
            )
            assert sorted(response.status_code for response in create_responses) == [
                201,
                409,
            ]
            created = next(
                response.json()
                for response in create_responses
                if response.status_code == 201
            )
            assert created["revision_number"] == 1

            revisions = (await client.get(f"{config_url}/revisions")).json()
            assert [
                (revision["revision_number"], revision["status"])
                for revision in revisions
            ] == [(1, "draft")]

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        TenantConfigRevision(
                            tenant_id=tenant_id,
                            revision_number=2,
                            schema_version=1,
                            config=config_v1(),
                            created_by=None,
                        )
                    )
                    await session.flush()

            revision_id = created["id"]
            publish_responses = await asyncio.gather(
                *(
                    client.post(
                        f"{config_url}/drafts/{revision_id}/publish",
                    )
                    for _ in range(2)
                )
            )
            assert sorted(response.status_code for response in publish_responses) == [
                200,
                409,
            ]

            revisions = (await client.get(f"{config_url}/revisions")).json()
            assert [
                (revision["revision_number"], revision["status"])
                for revision in revisions
            ] == [(1, "published")]
            tenant = (await client.get(f"/admin/v1/tenants/{tenant_id}")).json()
            assert tenant["active_config_revision_id"] == revision_id

            next_draft = await client.post(
                f"{config_url}/drafts",
                json={},
            )
            assert next_draft.status_code == 201
            assert next_draft.json()["revision_number"] == 2

            next_revision_id = next_draft.json()["id"]
            update_responses = await asyncio.gather(
                *(
                    client.patch(
                        f"{config_url}/drafts/{next_revision_id}",
                        json={"comment": comment},
                        headers={"If-Match": '"1"'},
                    )
                    for comment in ("editor A", "editor B")
                )
            )
            assert sorted(response.status_code for response in update_responses) == [
                200,
                412,
            ]
            saved_draft = await client.get(f"{config_url}/drafts/{next_revision_id}")
            assert saved_draft.json()["version"] == 2
            assert saved_draft.json()["comment"] in {"editor A", "editor B"}
    finally:
        await database.close()
