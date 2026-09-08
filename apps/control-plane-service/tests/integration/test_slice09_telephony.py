import base64
from dataclasses import asdict

import pytest
from control_plane.bootstrap import create_app
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
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
        control_plane_management_actor="ignored-legacy-actor",
        control_plane_management_scopes="resources:read,resources:write",
        voice_agent_service_secret="voice-secret",
        job_worker_service_secret="worker-secret",
        backend_core_service_secret="backend-secret",
    )


async def create_assignment(
    client: AsyncClient, tenant_id: str, phone: str, key: str
):
    return await client.post(
        f"/management/v1/tenants/{tenant_id}/telephony/phone-number-assignments",
        headers={"Idempotency-Key": key},
        json={"phone_number": phone},
    )


async def enable(client: AsyncClient, tenant_id: str, value, key: str):
    return await client.post(
        f"/management/v1/tenants/{tenant_id}/telephony/phone-number-assignments/{value.json()['id']}/enable",
        headers={"Idempotency-Key": key, "If-Match": value.headers["etag"]},
    )


@pytest.mark.asyncio
async def test_assignment_normalization_uniqueness_routing_and_replay(
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
            first = await create_assignment(
                client, "tenant-a", "+421 900-111-111", "create-first"
            )
            first_replay = await create_assignment(
                client, "tenant-a", "+421 900-111-111", "create-first"
            )
            second = await create_assignment(
                client, "tenant-a", "+421900222222", "create-second"
            )
            assert first.status_code == second.status_code == 201
            assert first.json()["phone_number"] == "+421900111111"
            assert first_replay.json() == first.json()
            assert first.json()["enabled"] is False
            assert "generation" not in first.json()

            first_enabled = await enable(client, "tenant-a", first, "enable-first")
            second_enabled = await enable(client, "tenant-a", second, "enable-second")
            assert first_enabled.status_code == second_enabled.status_code == 200
            assert first_enabled.json()["enabled"] is second_enabled.json()["enabled"] is True

            route = await app.state.telephony.resolve_inbound("+421 900 111 111")
            replay_route = await app.state.telephony.resolve_inbound("+421900111111")
            assert asdict(route) == {
                "tenant_id": "tenant-a",
                "phone_number": "+421900111111",
                "route_version": route.route_version,
            }
            assert replay_route == route
            assert route.route_version != "2"
            assert first.json()["id"] not in route.route_version
            with pytest.raises(ManagedResourceNotFound):
                await app.state.telephony.resolve_inbound("+421900000000")
            assert (
                await create_assignment(client, "tenant-a", "not-a-phone", "invalid")
            ).status_code == 422
            with pytest.raises(DBAPIError, match="identity is immutable"):
                async with database.sessions.begin() as session:
                    await session.execute(
                        text(
                            "UPDATE control_plane.phone_number_assignments "
                            "SET tenant_id = 'tenant-z' WHERE id = :id"
                        ),
                        {"id": first.json()["id"]},
                    )

            duplicate = await create_assignment(
                client, "tenant-b", "+421-900-111-111", "create-duplicate"
            )
            conflict = await enable(
                client, "tenant-b", duplicate, "failed-enable-duplicate"
            )
            assert conflict.status_code == 409
            async with database.sessions() as session:
                assert await session.scalar(
                    text(
                        "SELECT count(*) FROM control_plane.idempotency_replays "
                        "WHERE idempotency_key = 'failed-enable-duplicate'"
                    )
                ) == 0

            disabled = await client.post(
                f"/management/v1/tenants/tenant-a/telephony/phone-number-assignments/{first.json()['id']}/disable",
                headers={
                    "Idempotency-Key": "disable-first",
                    "If-Match": first_enabled.headers["etag"],
                },
            )
            assert disabled.status_code == 200
            with pytest.raises(ManagedResourceNotFound):
                await app.state.telephony.resolve_inbound("+421900111111")

            replacement = await enable(
                client, "tenant-b", duplicate, "failed-enable-duplicate"
            )
            assert replacement.status_code == 200
            replaced_route = await app.state.telephony.resolve_inbound(
                "+421900111111"
            )
            assert replaced_route.tenant_id == "tenant-b"
            assert replaced_route.route_version != route.route_version

            replay = await enable(client, "tenant-b", duplicate, "failed-enable-duplicate")
            assert replay.status_code == 200
            assert replay.json() == replacement.json()
            another = await create_assignment(
                client, "tenant-a", "+421900444444", "create-another"
            )
            changed_request = await enable(
                client, "tenant-a", another, "failed-enable-duplicate"
            )
            assert changed_request.status_code == 409
            assert changed_request.json()["code"] == "idempotency_key_reused"

            stale = await client.post(
                f"/management/v1/tenants/tenant-b/telephony/phone-number-assignments/{duplicate.json()['id']}/disable",
                headers={
                    "Idempotency-Key": "stale-disable",
                    "If-Match": duplicate.headers["etag"],
                },
            )
            assert stale.status_code == 412

            ownership = await create_assignment(
                client, "tenant-a", "+421900333333", "ownership"
            )
            assert ownership.status_code == 201
            assert (
                await client.get(
                    f"/management/v1/tenants/tenant-b/telephony/phone-number-assignments/{ownership.json()['id']}"
                )
            ).status_code == 404
            overridden = await client.post(
                "/management/v1/tenants/tenant-a/telephony/phone-number-assignments",
                headers={"Idempotency-Key": "ownership-body"},
                json={"tenant_id": "tenant-b", "phone_number": "+421900444444"},
            )
            assert overridden.status_code == 422
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_handoff_destination_identity_updates_and_live_state(
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
            path = "/management/v1/tenants/tenant-a/telephony/handoff-destinations"
            created = await client.post(
                path,
                headers={"Idempotency-Key": "create-front-desk"},
                json={
                    "key": "front_desk",
                    "description": "Front desk",
                    "phone_number": "+421 900-555-555",
                },
            )
            assert created.status_code == 201
            assert created.json()["phone_number"] == "+421900555555"
            assert created.json()["enabled"] is False
            duplicate = await client.post(
                path,
                headers={"Idempotency-Key": "duplicate-front-desk"},
                json={
                    "key": "front_desk",
                    "description": "Duplicate",
                    "phone_number": "+421900666666",
                },
            )
            assert duplicate.status_code == 409
            other_tenant = await client.post(
                path.replace("tenant-a", "tenant-b"),
                headers={"Idempotency-Key": "other-front-desk"},
                json={
                    "key": "front_desk",
                    "description": "Other",
                    "phone_number": "+421900777777",
                },
            )
            assert other_tenant.status_code == 201

            resource = f"{path}/{created.json()['id']}"
            updated = await client.put(
                resource,
                headers={
                    "Idempotency-Key": "update-front-desk",
                    "If-Match": created.headers["etag"],
                },
                json={
                    "description": "Reception",
                    "phone_number": "+421 900-888-888",
                },
            )
            assert updated.status_code == 200
            assert (updated.json()["key"], updated.json()["description"]) == (
                "front_desk",
                "Reception",
            )
            update_replay = await client.put(
                resource,
                headers={
                    "Idempotency-Key": "update-front-desk",
                    "If-Match": created.headers["etag"],
                },
                json={
                    "description": "Reception",
                    "phone_number": "+421 900-888-888",
                },
            )
            assert update_replay.json() == updated.json()
            enabled = await client.post(
                f"{resource}/enable",
                headers={
                    "Idempotency-Key": "enable-front-desk",
                    "If-Match": updated.headers["etag"],
                },
            )
            disabled = await client.post(
                f"{resource}/disable",
                headers={
                    "Idempotency-Key": "disable-front-desk",
                    "If-Match": enabled.headers["etag"],
                },
            )
            assert enabled.json()["enabled"] is True
            assert disabled.json()["enabled"] is False
            assert (
                await client.post(
                    f"{resource}/enable",
                    headers={
                        "Idempotency-Key": "enable-front-desk",
                        "If-Match": updated.headers["etag"],
                    },
                )
            ).json() == enabled.json()
            assert (
                await client.post(
                    f"{resource}/disable",
                    headers={
                        "Idempotency-Key": "disable-front-desk",
                        "If-Match": enabled.headers["etag"],
                    },
                )
            ).json() == disabled.json()
            assert disabled.json()["id"] == created.json()["id"]
            assert (await client.get(resource)).json()["description"] == "Reception"

            for column, value in (("tenant_id", "tenant-c"), ("key", "changed")):
                with pytest.raises(DBAPIError, match="identity is immutable"):
                    async with database.sessions.begin() as session:
                        await session.execute(
                            text(
                                f"UPDATE control_plane.handoff_destinations SET {column} = :value WHERE id = :id"
                            ),
                            {"value": value, "id": created.json()["id"]},
                        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_replay_write_failure_rolls_back_assignment_creation(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings(migrated_database_url), database=database)
    try:
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_slice09_replay() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''replay insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_slice09_replay BEFORE INSERT ON "
                    "control_plane.idempotency_replays FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_slice09_replay()"
                )
            )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer management-token"},
        ) as client:
            with pytest.raises(DBAPIError, match="replay insert failed"):
                await create_assignment(
                    client, "tenant-a", "+421900999999", "rollback-create"
                )
        async with database.sessions() as session:
            assert await session.scalar(
                text("SELECT count(*) FROM control_plane.phone_number_assignments")
            ) == 0
            assert await session.scalar(
                text("SELECT count(*) FROM control_plane.idempotency_replays")
            ) == 0
    finally:
        await database.close()
