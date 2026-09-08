import base64
from uuid import uuid4

import pytest
from control_plane.bootstrap import create_app
from control_plane.infrastructure.persistence.database import Database
from control_plane.settings import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        control_plane_encryption_key=base64.b64encode(b"0" * 32).decode(),
        control_plane_management_token="management-token",
        control_plane_management_actor="management:alice",
        control_plane_management_scopes="resources:read,resources:write,credentials:write,configuration:read,configuration:write,configuration:publish",
        voice_agent_service_secret="voice-secret",
        backend_core_service_secret="backend-secret",
    )


async def credential(client: AsyncClient, scope: dict[str, str], name: str):
    response = await client.post(
        "/management/v1/credentials",
        headers={"Idempotency-Key": f"credential-{name}"},
        json={"scope": scope, "name": name, "secret": "never-return-this"},
    )
    assert response.status_code == 201
    return response


async def create_integration(
    client: AsyncClient, tenant_id: str, key: str, credential_ref: str | None = None
):
    return await client.post(
        f"/management/v1/tenants/{tenant_id}/integrations",
        headers={"Idempotency-Key": f"create-{tenant_id}-{key}"},
        json={
            "key": key,
            "integration_kind": "pms",
            "config": {},
            "credential_ref": credential_ref,
        },
    )


def action(integration_key: str) -> dict[str, object]:
    return {
        "actions": {
            "availability.lookup": {
                "phase": "runtime",
                "description": "Look up availability",
                "announcement": "One moment",
                "agent_input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                "execution": {
                    "integration_key": integration_key,
                    "method": "GET",
                    "request": {"codec": "none"},
                    "response": {"codec": "none"},
                    "timeout_seconds": 5,
                },
            }
        }
    }


@pytest.mark.asyncio
async def test_credentialless_integration_can_be_enabled(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings(migrated_database_url), database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-token"},
        ) as client:
            created = await create_integration(client, "tenant-a", "public-api")
            assert created.status_code == 201
            assert created.json()["credential_ref"] is None
            enabled = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{created.json()['id']}/enable",
                headers={
                    "If-Match": created.headers["etag"],
                    "Idempotency-Key": "enable-public-api",
                },
            )
            assert enabled.status_code == 200
            assert enabled.json()["enabled"] is True
            assert enabled.json()["credential_ref"] is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_revoked_referenced_credential_rejects_enable(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings(migrated_database_url), database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-token"},
        ) as client:
            secret = await credential(
                client,
                {"type": "tenant", "tenant_id": "tenant-a"},
                "revoked-before-enable",
            )
            created = await create_integration(
                client, "tenant-a", "secured-api", secret.json()["id"]
            )
            assert created.status_code == 201
            revoked = await client.post(
                f"/management/v1/credentials/{secret.json()['id']}/revoke",
                headers={
                    "If-Match": secret.headers["etag"],
                    "Idempotency-Key": "revoke-before-enable",
                },
            )
            assert revoked.status_code == 200
            enabled = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{created.json()['id']}/enable",
                headers={
                    "If-Match": created.headers["etag"],
                    "Idempotency-Key": "enable-with-revoked-credential",
                },
            )
            assert enabled.status_code == 422
            assert enabled.json()["code"] == "invalid_managed_resource"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_tenant_credentials_lifecycle_etag_replay_and_no_secret_leak(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings(migrated_database_url), database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-token"},
        ) as client:
            same = await credential(
                client, {"type": "tenant", "tenant_id": "tenant-a"}, "same"
            )
            other = await credential(
                client, {"type": "tenant", "tenant_id": "tenant-b"}, "other"
            )
            platform = await credential(client, {"type": "platform"}, "platform")

            accepted = await create_integration(
                client, "tenant-a", "booking", same.json()["id"]
            )
            assert accepted.status_code == 201
            assert set(accepted.json()) == {
                "id",
                "tenant_id",
                "key",
                "integration_kind",
                "config",
                "credential_ref",
                "enabled",
                "created_at",
                "updated_at",
            }
            assert "never-return-this" not in accepted.text
            with pytest.raises(DBAPIError, match="identity is immutable"):
                async with database.sessions.begin() as session:
                    await session.execute(
                        text(
                            "UPDATE control_plane.integration_connections "
                            "SET key = 'changed' WHERE id = :id"
                        ),
                        {"id": accepted.json()["id"]},
                    )
            assert (
                await create_integration(
                    client, "tenant-a", "foreign", other.json()["id"]
                )
            ).status_code == 422
            assert (
                await create_integration(
                    client, "tenant-a", "platform", platform.json()["id"]
                )
            ).status_code == 422
            assert (
                await create_integration(client, "tenant-a", "missing", str(uuid4()))
            ).status_code == 422
            recovered = await create_integration(client, "tenant-a", "missing")
            assert recovered.status_code == 201

            enabled = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{accepted.json()['id']}/enable",
                headers={
                    "If-Match": accepted.headers["etag"],
                    "Idempotency-Key": "enable-booking",
                },
            )
            assert enabled.status_code == 200
            validated = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{accepted.json()['id']}/validate"
            )
            assert validated.status_code == 200
            assert validated.json() == {
                "valid": True,
                "usable": True,
                "code": None,
                "message": None,
            }
            replay = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{accepted.json()['id']}/enable",
                headers={
                    "If-Match": accepted.headers["etag"],
                    "Idempotency-Key": "enable-booking",
                },
            )
            assert replay.status_code == 200
            assert replay.json() == enabled.json()
            assert (
                await client.put(
                    f"/management/v1/tenants/tenant-a/integrations/{accepted.json()['id']}",
                    headers={
                        "If-Match": accepted.headers["etag"],
                        "Idempotency-Key": "stale-update",
                    },
                    json={"config": {}, "credential_ref": same.json()["id"]},
                )
            ).status_code == 412

            blocked = await client.post(
                f"/management/v1/credentials/{same.json()['id']}/revoke",
                headers={
                    "If-Match": same.headers["etag"],
                    "Idempotency-Key": "revoke-enabled",
                },
            )
            assert blocked.status_code == 409
            disabled = await client.post(
                f"/management/v1/tenants/tenant-a/integrations/{accepted.json()['id']}/disable",
                headers={
                    "If-Match": enabled.headers["etag"],
                    "Idempotency-Key": "disable-booking",
                },
            )
            assert disabled.status_code == 200
            revoked = await client.post(
                f"/management/v1/credentials/{same.json()['id']}/revoke",
                headers={
                    "If-Match": same.headers["etag"],
                    "Idempotency-Key": "revoke-disabled",
                },
            )
            assert revoked.status_code == 200
            assert disabled.json()["credential_ref"] == same.json()["id"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_actions_definition_validates_same_tenant_semantic_key_on_draft(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings(migrated_database_url), database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-token"},
        ) as client:
            assert (
                await create_integration(client, "tenant-a", "booking")
            ).status_code == 201
            assert (
                await create_integration(client, "tenant-b", "foreign")
            ).status_code == 201
            accepted = await client.put(
                "/management/v1/tenants/tenant-a/components/ActionsDefinition/draft",
                headers={"If-Match": "*"},
                json={"value": action("booking")},
            )
            assert accepted.status_code == 200
            assert accepted.json()["active"] is None
            assert accepted.json()["draft"] is not None
            rejected = await client.put(
                "/management/v1/tenants/tenant-a/components/ActionsDefinition/draft",
                headers={"If-Match": accepted.headers["etag"]},
                json={"value": action("foreign")},
            )
            assert rejected.status_code == 422
            published = await client.post(
                "/management/v1/tenants/tenant-a/components/ActionsDefinition/publish",
                headers={
                    "If-Match": accepted.headers["etag"],
                    "Idempotency-Key": "publish-actions",
                },
            )
            assert published.status_code == 200
            assert published.json()["draft"] is None
            published_action = published.json()["active"]["value"]["actions"][
                "availability.lookup"
            ]
            assert published_action["phase"] == "runtime"
            assert published_action["execution"]["integration_key"] == "booking"
            legacy = await client.put(
                "/v1/scopes/tenant/tenant-a/components/ActionsDefinition/draft",
                json={"value": action("booking")},
            )
            assert legacy.status_code == 404
    finally:
        await database.close()
