from uuid import UUID, uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.schemas import TenantConfigV1
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError


def config_v1(*, greeting: str = "Dobrý deň...") -> dict[str, object]:
    return {
        "schema_version": 1,
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {
            "display_name": "Amélia",
            "greeting": greeting,
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


@pytest.mark.asyncio
async def test_config_revision_lifecycle(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    app = create_app(database=database)
    actor_id = uuid4()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tenant_response = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "config-hotel",
                    "display_name": "Config Hotel",
                    "business_type": "hotel",
                },
            )
            tenant_id = UUID(tenant_response.json()["id"])
            config_url = f"/admin/v1/tenants/{tenant_id}/config"
            assert (await client.get(f"{config_url}/active")).status_code == 404

            draft_response = await client.post(
                f"{config_url}/drafts",
                json={
                    "schema_version": 1,
                    "config": config_v1(),
                    "created_by": str(actor_id),
                    "comment": "Initial config",
                },
            )
            assert draft_response.status_code == 201
            draft_1 = draft_response.json()
            revision_1_id = UUID(draft_1["id"])
            assert draft_1["revision_number"] == 1
            assert draft_1["status"] == "draft"

            second_draft_response = await client.post(
                f"{config_url}/drafts",
                json={"created_by": str(actor_id)},
            )
            assert second_draft_response.status_code == 409

            validation_response = await client.post(
                f"{config_url}/drafts/{revision_1_id}/validate"
            )
            assert validation_response.status_code == 200
            assert validation_response.json() == {"valid": True, "errors": []}

            publish_response = await client.post(
                f"{config_url}/drafts/{revision_1_id}/publish"
            )
            assert publish_response.status_code == 200
            assert publish_response.json()["status"] == "published"
            assert publish_response.json()["published_at"] is not None

            tenant_after_publish = (
                await client.get(f"/admin/v1/tenants/{tenant_id}")
            ).json()
            assert tenant_after_publish["active_config_revision_id"] == str(
                revision_1_id
            )

            immutable_response = await client.patch(
                f"{config_url}/drafts/{revision_1_id}",
                json={"comment": "Must not change"},
            )
            assert immutable_response.status_code == 409

            clone_response = await client.post(
                f"{config_url}/drafts",
                json={
                    "created_by": str(actor_id),
                    "comment": "Second revision",
                },
            )
            assert clone_response.status_code == 201
            draft_2 = clone_response.json()
            revision_2_id = UUID(draft_2["id"])
            assert draft_2["revision_number"] == 2
            assert draft_2["config"] == draft_1["config"]

            duplicate_clone_response = await client.post(
                f"{config_url}/drafts",
                json={"created_by": str(actor_id)},
            )
            assert duplicate_clone_response.status_code == 409

            invalid_update_response = await client.patch(
                f"{config_url}/drafts/{revision_2_id}",
                json={
                    "schema_version": 2,
                    "config": {**config_v1(greeting="Ahoj"), "schema_version": 2},
                },
            )
            assert invalid_update_response.status_code == 200
            invalid_validation = await client.post(
                f"{config_url}/drafts/{revision_2_id}/validate"
            )
            assert invalid_validation.status_code == 200
            assert invalid_validation.json() == {
                "valid": False,
                "errors": [
                    {
                        "path": "schema_version",
                        "code": "unsupported_schema_version",
                        "message": "Only schema_version 1 is supported",
                    }
                ],
            }
            assert (
                await client.post(f"{config_url}/drafts/{revision_2_id}/publish")
            ).status_code == 422

            valid_update_response = await client.patch(
                f"{config_url}/drafts/{revision_2_id}",
                json={
                    "schema_version": 1,
                    "config": config_v1(greeting="Ahoj"),
                },
            )
            assert valid_update_response.status_code == 200

            publish_2_response = await client.post(
                f"{config_url}/drafts/{revision_2_id}/publish"
            )
            assert publish_2_response.status_code == 200
            assert publish_2_response.json()["status"] == "published"

            revisions = (await client.get(f"{config_url}/revisions")).json()
            assert [revision["revision_number"] for revision in revisions] == [1, 2]
            assert [revision["status"] for revision in revisions] == [
                "archived",
                "published",
            ]

            tenant_after_publish_2 = (
                await client.get(f"/admin/v1/tenants/{tenant_id}")
            ).json()
            assert tenant_after_publish_2["active_config_revision_id"] == str(
                revision_2_id
            )

            active_config_response = await client.get(f"{config_url}/active")
            assert active_config_response.status_code == 200
            active_config = active_config_response.json()
            assert active_config["revision_id"] == str(revision_2_id)
            assert active_config["revision_number"] == 2
            assert active_config["config"] == config_v1(greeting="Ahoj")

            invalid_config = {
                **config_v1(),
                "localization": {
                    "default_locale": "sk-SK",
                    "timezone": "Mars/Olympus",
                },
            }
            invalid_draft_response = await client.post(
                f"{config_url}/drafts",
                json={
                    "schema_version": 1,
                    "config": invalid_config,
                    "created_by": str(actor_id),
                },
            )
            assert invalid_draft_response.status_code == 201
            invalid_revision_id = invalid_draft_response.json()["id"]
            invalid_validation = await client.post(
                f"{config_url}/drafts/{invalid_revision_id}/validate"
            )
            assert invalid_validation.status_code == 200
            assert invalid_validation.json() == {
                "valid": False,
                "errors": [
                    {
                        "path": "localization.timezone",
                        "code": "invalid_timezone",
                        "message": "Unknown IANA timezone",
                    }
                ],
            }
            assert (
                await client.post(f"{config_url}/drafts/{invalid_revision_id}/publish")
            ).status_code == 422

            other_tenant_response = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "other-config-hotel",
                    "display_name": "Other Config Hotel",
                    "business_type": "hotel",
                },
            )
            other_tenant_id = UUID(other_tenant_response.json()["id"])

        with pytest.raises(IntegrityError):
            async with database.transaction() as session:
                await session.execute(
                    update(Tenant)
                    .where(Tenant.id == other_tenant_id)
                    .values(active_config_revision_id=revision_2_id)
                )
    finally:
        await database.close()


@pytest.mark.parametrize(
    "invalid_config",
    [
        {**config_v1(), "prices": {}},
        {
            **config_v1(),
            "localization": {
                "default_locale": "sk-SK",
                "timezone": "Mars/Olympus",
            },
        },
        {
            **config_v1(),
            "conversation": {"scope": "global"},
        },
        {
            **config_v1(),
            "capabilities": {"booking": "yes"},
        },
    ],
)
def test_tenant_config_v1_rejects_out_of_scope_values(
    invalid_config: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TenantConfigV1.model_validate(invalid_config)
